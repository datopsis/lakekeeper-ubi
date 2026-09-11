#!/usr/bin/env python3
"""Record a resolved RPM set into the artifact lock.

Called by scripts/update-rpm-lock.sh. Kept separate so that the lock is edited
by something that parses JSON rather than by shell text manipulation.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys


def digest_of(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    architecture = os.environ["ARCHITECTURE"]
    rpm_directory = pathlib.Path(os.environ["RPM_DIR"])
    url_file = pathlib.Path(os.environ["URL_FILE"])
    lock_path = pathlib.Path(os.environ["LOCK_FILE"])

    urls_by_filename = {}
    if url_file.exists():
        for line in url_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                urls_by_filename[line.rsplit("/", 1)[-1]] = line

    entries = []
    missing_urls = []
    for path in sorted(rpm_directory.glob("*.rpm")):
        url = urls_by_filename.get(path.name)
        if url is None:
            missing_urls.append(path.name)
        entries.append(
            {
                "filename": path.name,
                "url": url,
                "sizeBytes": path.stat().st_size,
                "sha256": digest_of(path),
            }
        )

    if not entries:
        print("no RPMs were resolved; refusing to write an empty manifest", file=sys.stderr)
        return 1

    if missing_urls:
        # A manifest entry without a download location cannot be acquired by an
        # ordinary build, so it is a failure rather than a partial result.
        print("no download location was resolved for:", file=sys.stderr)
        for name in missing_urls:
            print(f"  - {name}", file=sys.stderr)
        return 1

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["architectures"][architecture]["rpms"] = entries
    lock_path.write_text(
        json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    total = sum(entry["sizeBytes"] for entry in entries)
    print(f"{architecture}: recorded {len(entries)} RPMs, {total} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
