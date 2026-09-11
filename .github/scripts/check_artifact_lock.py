#!/usr/bin/env python3
"""Fail when the Containerfile and the artifact lock disagree.

The lock is the reviewed record of which bytes may enter an image. The
Containerfile carries the same values as build arguments. If the two drift, a
build can silently consume an input that nobody approved, so every ordinary CI
run re-checks the pair.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "artifacts" / "lakekeeper.lock.json"
CONTAINERFILE_PATH = ROOT / "Containerfile"

ARG_PATTERN = re.compile(r'^ARG\s+([A-Z0-9_]+)="([^"]*)"\s*$', re.MULTILINE)


def containerfile_args(text: str) -> dict[str, str]:
    return {name: value for name, value in ARG_PATTERN.findall(text)}


def main() -> int:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    args = containerfile_args(CONTAINERFILE_PATH.read_text(encoding="utf-8"))

    amd64 = lock["architectures"]["amd64"]
    arm64 = lock["architectures"]["arm64"]

    expected = {
        "LAKEKEEPER_VERSION": lock["upstreamVersion"],
        "UBI_MINIMAL_IMAGE": lock["baseImages"]["builder"],
        "UBI_MICRO_IMAGE": lock["baseImages"]["runtime"],
        "LAKEKEEPER_AMD64_URL": amd64["archive"]["url"],
        "LAKEKEEPER_AMD64_ARCHIVE_SHA256": amd64["archive"]["sha256"],
        "LAKEKEEPER_AMD64_BINARY_SHA256": amd64["binary"]["sha256"],
        "LAKEKEEPER_ARM64_URL": arm64["archive"]["url"],
        "LAKEKEEPER_ARM64_ARCHIVE_SHA256": arm64["archive"]["sha256"],
        "LAKEKEEPER_ARM64_BINARY_SHA256": arm64["binary"]["sha256"],
    }

    failures = []
    for name, want in expected.items():
        got = args.get(name)
        if got is None:
            failures.append(f"{name}: missing from the Containerfile")
        elif got != want:
            failures.append(f"{name}: Containerfile has {got!r}, lock has {want!r}")

    # The release tag must agree with the version the image labels itself with.
    if lock["upstreamReleaseTag"] != f"v{lock['upstreamVersion']}":
        failures.append(
            "upstreamReleaseTag does not match upstreamVersion: "
            f"{lock['upstreamReleaseTag']!r} vs {lock['upstreamVersion']!r}"
        )

    # A digest recorded without its size is not a complete record.
    for architecture, entry in lock["architectures"].items():
        for section in ("archive", "binary"):
            values = entry[section]
            if not values.get("sha256") or not values.get("sizeBytes"):
                failures.append(
                    f"{architecture}.{section}: both sha256 and sizeBytes are required"
                )

    if failures:
        print("The Containerfile and artifact lock disagree:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print("The Containerfile matches artifacts/lakekeeper.lock.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
