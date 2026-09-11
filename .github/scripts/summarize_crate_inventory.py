#!/usr/bin/env python3
"""Summarize the crate inventory and its findings into the job summary.

The point of the inventory is that somebody looks at it. A retained artifact
nobody opens is not visibility, so the counts are printed where a reviewer sees
them without downloading anything.
"""

from __future__ import annotations

import collections
import json
import os
import pathlib
import sys

SBOM_PATH = pathlib.Path("lakekeeper-crates.spdx.json")
FINDINGS_PATH = pathlib.Path("grype-crates.json")
SEVERITY_ORDER = ["Critical", "High", "Medium", "Low", "Negligible", "Unknown"]


def main() -> int:
    lines = ["## Lakekeeper crate inventory", ""]

    if not SBOM_PATH.exists():
        lines.append("The crate inventory was not generated.")
        emit(lines)
        return 1

    sbom = json.loads(SBOM_PATH.read_text(encoding="utf-8"))
    packages = sbom.get("packages", [])
    lines.append(f"Declared crates: **{len(packages)}**")
    lines.append("")
    lines.append(
        "This is the dependency graph declared by the upstream source at the "
        "pinned release commit. It is not derived from the shipped binary, "
        "which carries no dependency metadata, so it over-reports: crates "
        "excluded by feature flags still appear."
    )
    lines.append("")

    if FINDINGS_PATH.exists():
        findings = json.loads(FINDINGS_PATH.read_text(encoding="utf-8"))
        counts = collections.Counter(
            match["vulnerability"]["severity"] for match in findings.get("matches", [])
        )
        total = sum(counts.values())
        lines.append(f"Vulnerability matches: **{total}** (report-only)")
        lines.append("")
        if total:
            lines.append("| Severity | Count |")
            lines.append("| --- | --- |")
            for severity in SEVERITY_ORDER:
                if counts.get(severity):
                    lines.append(f"| {severity} | {counts[severity]} |")
            lines.append("")
            notable = [
                match
                for match in findings.get("matches", [])
                if match["vulnerability"]["severity"] in ("Critical", "High")
            ]
            if notable:
                lines.append("Critical and High matches:")
                lines.append("")
                for match in notable[:25]:
                    vulnerability = match["vulnerability"]
                    artifact = match["artifact"]
                    lines.append(
                        f"- `{artifact['name']} {artifact['version']}` "
                        f"{vulnerability['id']} ({vulnerability['severity']})"
                    )
                lines.append("")
        lines.append(
            "These are upstream's dependencies. This project cannot patch them; "
            "it can report them, raise them upstream, and decide whether a given "
            "finding blocks a release."
        )
    else:
        lines.append("No findings file was produced.")

    emit(lines)
    return 0


def emit(lines: list[str]) -> None:
    text = "\n".join(lines)
    print(text)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


if __name__ == "__main__":
    sys.exit(main())
