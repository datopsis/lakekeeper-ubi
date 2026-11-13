#!/usr/bin/env python3
"""Keep one scheduled tracking issue; notify only on deferred-set changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from ubi_vulnerability_gate import cell

MARKER = "<!-- lakekeeper-ubi-deferred-fixes -->"
TITLE = "UBI fixes awaiting repository publication"


def deferred_set(directory):
    reports = [json.loads(path.read_text()) for path in directory.rglob("gate.json")]
    if sorted(r["architecture"] for r in reports) != ["amd64", "arm64"]:
        raise ValueError("Require exactly one native report for each architecture")
    rows = []
    for report in reports:
        if report["schema_version"] != 1 or report["errors"]:
            raise ValueError("Incomplete gate evidence cannot resolve deferred findings")
        for finding in report["findings"]:
            if finding["decision"] not in {"block", "deferred", "unfixed"}:
                raise ValueError("Invalid admission decision")
            if finding["decision"] == "deferred":
                if finding["kind"] != "rpm" or not finding["fixes"]:
                    raise ValueError("Invalid RPM deferral")
                rows.append({"architecture": report["architecture"], **{
                    key: finding[key] for key in
                    ("scanner", "vulnerability", "package", "installed", "severity", "fixes")}})
    # Metadata timestamps, order, available versions, and unrelated findings
    # cannot cause notifications. Normalize scanner ordering of alternatives.
    for row in rows:
        row["fixes"] = sorted(set(row["fixes"]))
    return sorted({json.dumps(r, sort_keys=True) for r in rows})


def render(rows, run_url):
    digest = hashlib.sha256(json.dumps(rows).encode()).hexdigest()
    fingerprint = f"<!-- deferred-sha256:{digest} -->"
    lines = [MARKER, fingerprint, "", "Tracks vendor fixes not yet available in the build's UBI repositories.",
             "Deferred findings remain vulnerabilities. An installable fix blocks the next gate until applied.",
             "", f"[Native scanner and repository evidence]({run_url})", "",
             "| Architecture | Scanner | Finding | Package | Installed | Severity | Vendor fixed version |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for encoded in rows:
        row = json.loads(encoded)
        values = [row[k] for k in ("architecture", "scanner", "vulnerability", "package", "installed", "severity")]
        lines.append("| " + " | ".join(cell(v) for v in [*values, ", ".join(row["fixes"])]) + " |")
    if not rows:
        lines += ["", "No deferred fixes in either architecture's current reports."]
    return "\n".join(lines) + "\n", fingerprint


def api(repo, endpoint, method="GET", payload=None):
    command = ["gh", "api", f"repos/{repo}/{endpoint}"]
    command += ["--paginate", "--slurp"] if method == "GET" else ["--method", method, "--input", "-"]
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True, check=True, timeout=60)
    return json.loads(result.stdout)


def update(repo, rows, run_url, call=api):
    body, fingerprint = render(rows, run_url)
    pages = call(repo, "issues?state=all&per_page=100")
    issues = [i for page in pages for i in page if not i.get("pull_request") and MARKER in (i.get("body") or "")]
    if len(issues) > 1:
        raise ValueError("Multiple tracking issues; refusing to create another")
    if not issues:
        return call(repo, "issues", "POST", {"title": TITLE, "body": body})
    issue = issues[0]
    if fingerprint not in issue["body"]:
        # Update the fingerprint only after a successful comment so failures retry.
        call(repo, f'issues/{issue["number"]}/comments', "POST", {"body": "Deferred set changed.\n\n" + body})
        return call(repo, f'issues/{issue["number"]}', "PATCH", {"body": body, "state": "open"})
    if issue["state"] != "open":
        return call(repo, f'issues/{issue["number"]}', "PATCH", {"state": "open"})
    return issue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repo = os.environ["GITHUB_REPOSITORY"]
    run_url = f'https://github.com/{repo}/actions/runs/{os.environ["GITHUB_RUN_ID"]}'
    rows = deferred_set(args.directory)
    if args.dry_run:
        print(render(rows, run_url)[0])
    else:
        if os.environ.get("GITHUB_EVENT_NAME") != "schedule" or os.environ.get("GITHUB_REF") != "refs/heads/main":
            raise ValueError("Issue writes require a scheduled main-branch run")
        update(repo, rows, run_url)


if __name__ == "__main__":
    main()
