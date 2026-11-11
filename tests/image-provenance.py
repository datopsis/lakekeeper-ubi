#!/usr/bin/env python3
"""Inspect the built image against the checkout, independently of build args."""

import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REVISION_LABEL = "org.opencontainers.image.revision"
LOCK_LABEL = "io.datopsis.artifact-lock.sha256"


def verify(image, revision, lock_sha, architecture):
    labels = image.get("Config", {}).get("Labels") or {}
    for name, expected in ((REVISION_LABEL, revision), (LOCK_LABEL, lock_sha)):
        actual = labels.get(name)
        if actual != expected:
            raise ValueError(f"{name}: expected {expected}, got {actual!r}")
    if image.get("Architecture") != architecture:
        raise ValueError(f"expected architecture {architecture}, got {image.get('Architecture')!r}")
    return {
        "image_id": image["Id"],
        "architecture": image["Architecture"],
        REVISION_LABEL: labels[REVISION_LABEL],
        LOCK_LABEL: labels[LOCK_LABEL],
    }


def main():
    runtime = os.environ.get("CONTAINER_RUNTIME", "podman")
    image_name = os.environ.get("IMAGE", "localhost/lakekeeper-ubi9:development")
    revision = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD"], text=True
    ).strip()
    lock_path = Path(os.environ.get("LOCK_FILE", ROOT / "artifacts/lakekeeper.lock.json"))
    lock_sha = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    architecture = os.environ["ARCHITECTURE"]
    images = json.loads(subprocess.check_output(
        [runtime, "image", "inspect", image_name], text=True
    ))
    evidence = json.dumps(verify(images[0], revision, lock_sha, architecture), indent=2)
    print(evidence)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"\nVerified Lakekeeper image provenance:\n\n```json\n{evidence}\n```\n")


if __name__ == "__main__":
    main()
