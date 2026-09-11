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

    expected = {
        "LAKEKEEPER_VERSION": lock["upstreamVersion"],
        "UBI_MINIMAL_IMAGE": lock["baseImages"]["builder"],
        "UBI_MICRO_IMAGE": lock["baseImages"]["runtime"],
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

    # Artifact acquisition happens before the build. A Containerfile that can
    # download, or resolve a package, is a Containerfile that can consume
    # something unreviewed, so the absence of both is a checked property rather
    # than a convention.
    containerfile = CONTAINERFILE_PATH.read_text(encoding="utf-8")
    forbidden_tokens = (
        "curl ",
        "wget ",
        "https://github.com/lakekeeper",
        "dnf ",
        "microdnf ",
        "--releasever",
    )
    for forbidden in forbidden_tokens:
        if forbidden in containerfile:
            failures.append(
                f"the Containerfile must not acquire or resolve inputs, found {forbidden!r}"
            )
    for required in ("COPY --from=bundle rpms/", "COPY --from=bundle"):
        if required not in containerfile:
            failures.append(
                f"the Containerfile must consume the verified bundle, missing {required!r}"
            )

    # The runtime package manifest is what makes a network-free build possible.
    requested = lock.get("runtimePackages", {}).get("requested") or []
    if not requested:
        failures.append("runtimePackages.requested must list the packages the image asks for")

    package_names = {}
    for architecture, entry in lock["architectures"].items():
        rpms = entry.get("rpms") or []
        if not rpms:
            failures.append(f"{architecture}: no runtime package manifest recorded")
            continue
        names = set()
        for rpm in rpms:
            for field in ("filename", "url", "sizeBytes", "sha256"):
                if not rpm.get(field):
                    failures.append(
                        f"{architecture}: {rpm.get('filename', '?')} is missing {field}"
                    )
            if not str(rpm.get("url", "")).startswith("https://"):
                failures.append(
                    f"{architecture}: {rpm.get('filename')} must be fetched over HTTPS"
                )
            names.add(rpm["filename"].rsplit("-", 2)[0])
        package_names[architecture] = names

    # The architectures should ship the same packages. A difference is not
    # automatically wrong, but it is never something to discover after release.
    if len(package_names) == 2:
        first, second = package_names.values()
        if first != second:
            failures.append(
                f"architectures resolve different packages: {sorted(first ^ second)}"
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
