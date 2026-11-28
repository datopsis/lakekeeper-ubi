#!/usr/bin/env python3
"""One scheduled RustSec issue; comment only on tracked finding/state changes."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tomllib

from rustsec_policy import POLICY_VERSION, all_findings, classify, patched_ranges
from track_deferred_fixes import api
from ubi_vulnerability_gate import cell

MARKER = "<!-- lakekeeper-ubi-unpatched-rustsec -->"
TITLE = "RustSec: shipped advisories awaiting patches or replacement"
KEYS = ("architecture", "package", "version", "source", "advisory")


def identity(row):
    return tuple(row[k] for k in KEYS)


def native_reports(directory):
    paths = list(directory.glob("**/rustsec/policy.json"))
    reports = {}
    for path in paths:
        policy = json.loads(path.read_text())
        arch = policy["architecture"]
        if (arch not in {"amd64", "arm64"} or arch in reports
                or policy["schema_version"] != 1 or policy["policy_version"] != POLICY_VERSION
                or policy["complete"] is not True or policy["admissionBlocking"] is not True):
            raise ValueError("Missing, duplicate, incomplete or unshipped native evidence")
        catalog_bytes = (path.parent / "advisory-catalog.json").read_bytes()
        raw = (path.parent / "shipped.json").read_bytes()
        if (hashlib.sha256(catalog_bytes).hexdigest() != policy["advisoryCatalogSha256"]
                or hashlib.sha256(raw).hexdigest() != policy["shippedReportSha256"]):
            raise ValueError("Native RustSec evidence hash mismatch")
        evidence = json.loads((path.parent / "evidence.json").read_text())
        if (evidence["architecture"] != arch or evidence["admissionBlocking"] is not True
                or evidence["advisoryDatabaseCommit"] != policy["advisoryDatabaseCommit"]):
            raise ValueError("Inconsistent native provenance")
        runtime = [classify(f) for f in all_findings(json.loads(raw))]
        if runtime != policy["runtime"] or policy["blocked"] != any(r["decision"] == "block" for r in runtime):
            raise ValueError("Native classification disagrees with raw findings")
        catalog = json.loads(catalog_bytes)
        for row in runtime:
            if row["advisory"]:
                record = catalog[row["advisory"]]
                if record["package"] != row["package"] or bool(record["patched"]) != bool(row["patched"]):
                    raise ValueError("Advisory snapshot disagrees with native findings")
        lock = tomllib.loads((path.parent / "shipped.Cargo.lock").read_text())
        packages = {(p["name"], p["version"], p.get("source")) for p in lock["package"]}
        reports[arch] = dict(runtime=runtime, catalog=catalog, packages=packages)
    if set(reports) != {"amd64", "arm64"}:
        raise ValueError("Require exactly one complete admission report per architecture")
    return reports


def read_state(body):
    match = re.search(r"<!-- rustsec-state:([A-Za-z0-9_=-]+) -->", body)
    if not match:
        raise ValueError("Tracking issue lacks valid state; refusing to reset history")
    state = json.loads(base64.urlsafe_b64decode(match[1]))
    if state["schema_version"] != 1 or not isinstance(state["tracked"], list):
        raise ValueError("Invalid tracking state")
    rows = state["tracked"]
    if len({identity(r) for r in rows}) != len(rows):
        raise ValueError("Duplicate tracking identities")
    return rows


def evolve(reports, previous):
    current = {}
    tracked = {identity(row) for row in previous}
    for arch, report in reports.items():
        for row in report["runtime"]:
            key = identity(dict(architecture=arch, **row))
            current[key] = row
            if row["advisory"] and not row["patched"]:
                tracked.add(key)
    rows = []
    for key in tracked:
        row = dict(zip(KEYS, key))
        report = reports[row["architecture"]]
        # Snapshot includes prior IDs even when withdrawal, a fix or an upgrade
        # makes cargo-audit stop reporting them. Missing history fails closed.
        advisory = report["catalog"][row["advisory"]]
        if advisory["package"] != row["package"]:
            raise ValueError("Tracked package identity differs from advisory catalog")
        patched = patched_ranges(advisory)
        if advisory["withdrawn"]:
            status = "withdrawn"
        elif key in current:
            status = "fix-available" if patched else "no-patch"
        elif (row["package"], row["version"], row["source"]) not in report["packages"]:
            status = "no-longer-shipped"
        else:
            status = "no-longer-reported"
        rows.append(dict(row, status=status, patched=patched,
                         type=advisory["informational"] or "vulnerability",
                         withdrawn=advisory["withdrawn"], guidance_sha256=advisory["guidance_sha256"]))
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))


def render(rows, reports, run_url):
    state = json.dumps(dict(schema_version=1, tracked=rows), sort_keys=True)
    digest = hashlib.sha256(state.encode()).hexdigest()
    fingerprint = f"<!-- rustsec-sha256:{digest} -->"
    encoded = base64.urlsafe_b64encode(state.encode()).decode()
    lines = [MARKER, fingerprint, f"<!-- rustsec-state:{encoded} -->", "",
             "Shipped RustSec advisories without patched versions are reported, not exempted.",
             "A non-empty patched range blocks shipped code regardless of advisory type.",
             "Build-only/unselected crates are outside this tracker and remain separately reported.",
             "This issue retains previously tracked identities to flag new fixes and guidance after a finding disappears.",
             f"[Native RustSec evidence]({run_url})", "",
             "| Architecture | Crate | Advisory | Type | State | Patched versions |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        values = [row["architecture"], f"{row['package']} {row['version']}", row["advisory"],
                  row["type"], row["status"], ", ".join(row["patched"]) or "none"]
        lines.append("| " + " | ".join(cell(v) for v in values) + " |")
    if not rows:
        lines += ["", "No shipped no-patch advisories have been observed."]
    for identifier in sorted({r["advisory"] for r in rows}):
        lines += ["", f"### {cell(identifier)}: remediation / replacement guidance", "",
                  f"[RustSec advisory](https://rustsec.org/advisories/{identifier}.html)"]
        guidance = {reports[r["architecture"]]["catalog"][identifier]["guidance"]
                    for r in rows if r["advisory"] == identifier}
        for text in sorted(guidance):
            lines += ["", "<pre>" + cell(text) + "</pre>"]
    lines += ["", "Replacement guidance comes from RustSec text and references, not a hand-maintained crate map.",
              "Guidance changes are flagged for review; they do not approve a replacement or alter the patched-field gate."]
    body = "\n".join(lines) + "\n"
    if len(body.encode()) > 65000:
        raise ValueError("Tracking body exceeds issue size budget")
    return body, fingerprint


def transitions(previous, rows):
    old = {identity(r): r for r in previous}
    lines = ["RustSec tracked set/state changed."]
    for row in rows:
        before = old.get(identity(row))
        label = f"{cell(row['architecture'])}: {cell(row['package'])} {cell(row['advisory'])}"
        if before and not before["patched"] and row["patched"]:
            lines.append(f"- FIX NOW AVAILABLE: {label}; {cell(', '.join(row['patched']))}.")
        if before and before["guidance_sha256"] != row["guidance_sha256"]:
            lines.append(f"- REMEDIATION/REPLACEMENT GUIDANCE CHANGED: {label}; review the linked advisory.")
    return "\n".join(lines)


def update(repo, reports, run_url, call=api, dry_run=False):
    pages = call(repo, "issues?state=all&per_page=100")
    issues = [i for page in pages for i in page
              if not i.get("pull_request") and MARKER in (i.get("body") or "")]
    if len(issues) > 1:
        raise ValueError("Multiple RustSec tracking issues; refusing another")
    issue = issues[0] if issues else None
    previous = read_state(issue["body"]) if issue else []
    rows = evolve(reports, previous)
    body, fingerprint = render(rows, reports, run_url)
    if dry_run:
        print(transitions(previous, rows) + "\n\n" + body)
        return
    if not issue:
        return call(repo, "issues", "POST", dict(title=TITLE, body=body))
    if fingerprint not in issue["body"]:
        # Recover a successful comment followed by a failed body update without
        # posting the same notification again on the next scheduled attempt.
        comments = call(repo, f'issues/{issue["number"]}/comments?per_page=100')
        if not any(fingerprint in (c.get("body") or "") for page in comments for c in page):
            call(repo, f'issues/{issue["number"]}/comments', "POST",
                 dict(body=transitions(previous, rows) + "\n\n" + body))
        return call(repo, f'issues/{issue["number"]}', "PATCH", dict(body=body, state="open"))
    if issue["state"] != "open":
        return call(repo, f'issues/{issue["number"]}', "PATCH", dict(state="open"))
    return issue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and (os.environ.get("GITHUB_EVENT_NAME") != "schedule"
                            or os.environ.get("GITHUB_REF") != "refs/heads/main"):
        raise ValueError("Issue writes require a scheduled main-branch run")
    reports = native_reports(args.directory)  # Validate before any API mutation.
    repo = os.environ["GITHUB_REPOSITORY"]
    run_url = f'https://github.com/{repo}/actions/runs/{os.environ["GITHUB_RUN_ID"]}'
    update(repo, reports, run_url, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
