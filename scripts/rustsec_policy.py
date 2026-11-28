"""RustSec decisions depend on compiled scope and patched ranges, never IDs/types."""

import hashlib
import json
import re
import tomllib

POLICY_VERSION = "2026-11-27"


def patched_ranges(versions):
    if not isinstance(versions, dict) or not isinstance(versions.get("patched"), list):
        raise ValueError("Missing or malformed RustSec versions.patched")
    values = versions["patched"]
    if any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError("Malformed RustSec patched range")
    return sorted({re.sub(r"\s+", "", value) for value in values})


def all_findings(report):
    findings = report["vulnerabilities"]["list"]
    warnings = report["warnings"]
    if not isinstance(findings, list) or not isinstance(warnings, dict):
        raise ValueError("Malformed cargo-audit findings")
    if type(report["vulnerabilities"]["count"]) is not int or report["vulnerabilities"]["count"] != len(findings):
        raise ValueError("cargo-audit count disagrees with its findings")
    result = list(findings)
    for values in warnings.values():
        if not isinstance(values, list):
            raise ValueError("Malformed cargo-audit warnings")
        result.extend(values)
    return result


def classify(finding, scope="shipped", report_only=False):
    if scope not in {"shipped", "build-only-or-unselected"}:
        raise ValueError("Unknown crate scope")
    package = finding["package"]
    advisory = finding.get("advisory")
    # Preserve the independent existing yanked-crate control. A yanked warning
    # has no RustSec advisory or patched field and is not counted as an advisory.
    patched = patched_ranges(finding.get("versions")) if advisory else []
    decision = "block" if scope == "shipped" and not report_only and (patched or not advisory) else "report"
    return dict(package=package["name"], version=package["version"], source=package.get("source"),
                advisory=advisory["id"] if advisory else None,
                type=(advisory.get("informational") or "vulnerability") if advisory else "yanked",
                patched=patched, scope=scope, decision=decision,
                reason=("build-only or unselected" if scope != "shipped" else
                        "unshipped subject" if report_only else
                        "yanked crate (existing independent control)" if not advisory else
                        "patched version available" if patched else "no patched version available"))


def advisory_catalog(database):
    """Snapshot every crate advisory to detect fixes after a finding disappears.

    RustSec has no structured replacement field. Its description, URL and
    references carry remediation/replacement guidance; changes are flagged for
    review rather than guessing that two crates are equivalent.
    """
    catalog = {}
    for path in sorted((database / "crates").rglob("RUSTSEC-*.md")):
        text = path.read_text(encoding="utf-8")
        match = re.match(r"\s*```toml\s*\n(.*?)\n```(.*)", text, re.S)
        if not match:
            raise ValueError(f"Invalid RustSec front matter: {path.name}")
        record = tomllib.loads(match[1])
        advisory = record["advisory"]
        identifier = advisory["id"]
        if not re.fullmatch(r"RUSTSEC-\d{4}-\d{4,}", identifier) or identifier in catalog:
            raise ValueError("Invalid or duplicate RustSec advisory identity")
        # Ignore formatting/reference-order changes and unrelated DB updates.
        guidance = " ".join(match[2].split())
        references = sorted(set(advisory.get("references", [])))
        url = advisory.get("url")
        digest = hashlib.sha256(json.dumps([guidance, url, references], sort_keys=True).encode()).hexdigest()
        catalog[identifier] = dict(package=advisory["package"],
                                   patched=patched_ranges(record["versions"]),
                                   informational=advisory.get("informational"),
                                   withdrawn=str(advisory["withdrawn"]) if advisory.get("withdrawn") else None,
                                   guidance=guidance, guidance_sha256=digest)
    if not catalog:
        raise ValueError("Empty RustSec advisory catalog")
    return catalog
