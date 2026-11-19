#!/usr/bin/env python3
"""Resolve the upstream release build without compiling; audit shipped crates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import tomllib
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    try:
        return subprocess.run(args, check=True, text=True, **kwargs)
    except subprocess.CalledProcessError as error:
        if kwargs.get("capture_output"):
            print(error.stdout or "")
            print(error.stderr or "")
        raise


def canonical_source(source):
    # Cargo.lock escapes '/' in git tag queries; metadata can leave it literal.
    # Normalize only the query encoding, preserving repository and commit SHA.
    if source and source.startswith("git+"):
        url = urllib.parse.urlsplit(source)
        query = urllib.parse.urlencode(urllib.parse.parse_qsl(url.query, strict_parsing=True))
        return urllib.parse.urlunsplit(url._replace(query=query))
    return source


def verified_download(url, digest, destination):
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS inputs are admitted")
    with urllib.request.urlopen(url, timeout=120) as response:
        destination.write_bytes(response.read())
    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise ValueError(f"Digest mismatch: {url}")


def runtime_packages(graph, metadata):
    """Follow target library edges, stopping at build scripts and proc macros.

    Cargo's unit graph has already resolved features, platform predicates and
    resolver-v2 host/target separation for the exact build command. Unlike a
    Cargo.lock walk, it does not guess optional dependencies or feature unions.
    """
    if graph["version"] != 1:
        raise ValueError("Unsupported Cargo unit graph version")
    units = graph["units"]
    roots = [i for i in graph["roots"]
             if units[i]["target"]["name"] == "lakekeeper"
             and units[i]["target"]["kind"] == ["bin"]]
    if len(roots) != 1:
        raise ValueError("Expected exactly one shipped lakekeeper executable")
    packages = {p["id"]: p for p in metadata["packages"]}
    selected, seen, pending = set(), set(), roots[:]
    while pending:
        index = pending.pop()
        if index in seen:
            continue
        seen.add(index)
        unit = units[index]
        if set(unit["target"]["kind"]) & {"custom-build", "proc-macro"}:
            continue
        if unit["mode"] != "build":
            raise ValueError(f"Unexpected runtime compilation mode: {unit['mode']}")
        package = packages[unit["pkg_id"]]  # Missing identities fail closed.
        selected.add((package["name"], package["version"], canonical_source(package["source"])))
        pending.extend(d["index"] for d in unit["dependencies"])
    if len(selected) < 2:
        raise ValueError("Empty or incomplete runtime dependency graph")
    return selected


def partition_lock(lock, selected):
    shipped, other = [], []
    remaining = set(selected)
    for package in lock["package"]:
        key = (package["name"], package["version"], canonical_source(package.get("source")))
        (shipped if key in selected else other).append(package)
        remaining.discard(key)
    if remaining:
        raise ValueError(f"Resolved packages absent from exact lock: {remaining}")
    return shipped, other


def write_lock(path, packages):
    # cargo-audit matches package identities, not dependency edges. These are
    # inventory lockfiles, not inputs for a subsequent Cargo build.
    lines = ["# Generated audit inventory; not a build lockfile", "version = 4", ""]
    for package in packages:
        lines.append("[[package]]")
        for key in ("name", "version", "source", "checksum"):
            if key in package:
                lines.append(f"{key} = {json.dumps(package[key])}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def audit(tool, inventory, database, output):
    result = subprocess.run(
        [str(tool), "audit", "--file", str(inventory), "--db", str(database),
         "--no-fetch", "--json", "--deny", "warnings"],
        text=True, capture_output=True, cwd=output.parent,
    )
    output.write_text(result.stdout, encoding="utf-8")
    output.with_suffix(".stderr.txt").write_text(result.stderr, encoding="utf-8")
    report = json.loads(result.stdout)  # An error/empty report is never clean.
    if result.returncode not in (0, 1) or "vulnerabilities" not in report:
        raise ValueError(f"cargo-audit failed: {result.stderr}")
    findings = list(report["vulnerabilities"]["list"])
    for values in report["warnings"].values():
        findings.extend(values)
    if bool(findings) != (result.returncode == 1):
        raise ValueError("cargo-audit exit status disagrees with its report")
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", choices=("amd64", "arm64"))
    parser.add_argument("--historical-baseline", action="store_true")
    args = parser.parse_args()
    lock_name = ("rustsec-historical-baseline.lock.json" if args.historical_baseline
                 else "lakekeeper.lock.json")
    lock = json.loads((ROOT / "artifacts" / lock_name).read_text())
    policy = lock["rustsec"]
    entry = lock["architectures"][args.architecture]
    target = entry["rustTarget"]
    output = ROOT / "security-results" / ("rustsec-historical" if args.historical_baseline else "rustsec")
    output.mkdir(parents=True, exist_ok=True)
    binary = ROOT / ".artifact-bundle" / args.architecture / "lakekeeper"
    if args.historical_baseline:
        # Historical evidence is never used to admit the new release.
        archive = output / "historical.tgz"
        verified_download(entry["archive"]["url"], entry["archive"]["sha256"], archive)
        with tarfile.open(archive) as tar:
            if tar.getnames() != ["lakekeeper"]:
                raise ValueError("Unexpected historical archive members")
            tar.extractall(output, filter="data")
        archive.unlink()
        binary = output / "lakekeeper"
    if hashlib.sha256(binary.read_bytes()).hexdigest() != entry["binary"]["sha256"]:
        raise ValueError("The audited artifact differs from the shipped binary")
    sections = run(["readelf", "-SW", str(binary)], capture_output=True).stdout
    (output / "elf-sections.txt").write_text(sections)
    if args.historical_baseline:
        binary.unlink()
    if ".dep-v0" in sections:
        raise ValueError("Embedded cargo-auditable data is now available; audit it directly")

    with tempfile.TemporaryDirectory(prefix="lakekeeper-rustsec-") as work:
        work = Path(work)
        archive = work / "source.tgz"
        verified_download(policy["sourceArchiveUrl"], policy["sourceArchiveSha256"], archive)
        with tarfile.open(archive) as tar:
            tar.extractall(work / "source", filter="data")
        source, = (work / "source").iterdir()
        exact_lock = (source / "Cargo.lock").read_bytes()
        if hashlib.sha256(exact_lock).hexdigest() != lock["crateInventory"]["sha256"]:
            raise ValueError("Source archive Cargo.lock differs from the admitted lock")
        toolchain = tomllib.loads((source / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
        if toolchain != policy["toolchain"]:
            raise ValueError("Upstream toolchain pin has drifted")
        run(["rustup", "toolchain", "install", toolchain, "--profile", "minimal", "--target", target])
        env = dict(os.environ, RUSTFLAGS=policy["rustflags"])
        command = ["cargo", f"+{toolchain}", *policy["buildArguments"], "--target", target,
                   "-Z", "unstable-options", "--unit-graph"]
        graph = run(command, cwd=source, env=env, capture_output=True)
        (output / "unit-graph.json").write_text(graph.stdout)
        metadata = run(["cargo", f"+{toolchain}", "metadata", "--locked", "--all-features",
                        "--filter-platform", target, "--format-version", "1"],
                       cwd=source, env=env, capture_output=True)
        (output / "metadata.json").write_text(metadata.stdout)
        if (source / "Cargo.lock").read_bytes() != exact_lock:
            raise ValueError("Cargo changed the upstream lock")
        selected = runtime_packages(json.loads(graph.stdout), json.loads(metadata.stdout))
        shipped, other = partition_lock(tomllib.loads(exact_lock.decode()), selected)
        write_lock(output / "shipped.Cargo.lock", shipped)
        write_lock(output / "build-only-or-unselected.Cargo.lock", other)
        tool_lock = json.loads((ROOT / "artifacts/cargo-audit.lock.json").read_text())
        pin = tool_lock["archives"][args.architecture]
        verified_download(pin["url"], pin["sha256"], work / "audit.tgz")
        with tarfile.open(work / "audit.tgz") as tar:
            tar.extractall(work / "audit", filter="data")
        tool, = (work / "audit").glob("*/cargo-audit")
        run([str(tool), "--version"])
        database = work / "advisory-db"
        # Fresh DB each run. Both classifications use the exact same snapshot.
        run(["git", "clone", "--depth", "1", "https://github.com/RustSec/advisory-db.git", str(database)])
        database_sha = run(["git", "-C", str(database), "rev-parse", "HEAD"], capture_output=True).stdout.strip()
        evidence = dict(architecture=args.architecture, target=target,
                        upstreamCommit=lock["upstreamReleaseCommit"],
                        binarySha256=entry["binary"]["sha256"],
                        sourceArchiveSha256=policy["sourceArchiveSha256"],
                        cargoLockSha256=lock["crateInventory"]["sha256"],
                        toolVersion=tool_lock["version"], toolArchiveSha256=pin["sha256"],
                        advisoryDatabaseCommit=database_sha, command=command,
                        rustflags=policy["rustflags"],
                        inventoryBasis="source release build unit graph; not embedded artifact provenance",
                        shippedPackages=len(shipped), buildOnlyOrUnselectedPackages=len(other))
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        # Evaluate both reports before returning failure for shipped code.
        excluded = audit(tool, output / "build-only-or-unselected.Cargo.lock", database,
                         output / "build-only-or-unselected.json")
        blocking = audit(tool, output / "shipped.Cargo.lock", database, output / "shipped.json")
        lines = ["## RustSec " + ("historical 0.13.4 evidence" if args.historical_baseline else "shipped-code gate"), "",
                 f"Shipped: {len(shipped)} packages, **{len(blocking)} blocking findings**.",
                 f"Build-only or unselected: {len(other)} packages, {len(excluded)} report-only findings.",
                 f"Database: `{database_sha}`. No ignore lists; all advisory severities and warnings block shipped code.", ""]
        for label, findings in (("BLOCK", blocking), ("REPORT", excluded)):
            for finding in findings:
                package, advisory = finding["package"], finding.get("advisory")
                lines.append(f"- {label}: {package['name']} {package['version']} "
                             f"{advisory['id'] if advisory else 'yanked'}")
        summary = "\n".join(lines) + "\n"
        print(summary)
        (output / "summary.md").write_text(summary)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
                handle.write(summary)
        return 0 if args.historical_baseline else int(bool(blocking))


if __name__ == "__main__":
    raise SystemExit(main())
