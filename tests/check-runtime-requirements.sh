#!/usr/bin/env bash
# Prove that the shipped binary can actually run on the shipped base image.
#
# The upstream release binaries are built on a different distribution than UBI.
# A future upstream build could require a newer glibc symbol version or a new
# shared library than the UBI major version provides, which would produce an
# image that builds cleanly and fails at startup. This check compares the
# binary's requirements against the runtime's own glibc and the reviewed lock.
set -Eeuo pipefail

runtime="${CONTAINER_RUNTIME:-podman}"
image="${IMAGE:-localhost/lakekeeper-ubi9:development}"
architecture="${ARCHITECTURE:-amd64}"
lock="${LOCK:-artifacts/lakekeeper.lock.json}"

workdir="$(mktemp -d)"
container=""

cleanup() {
    if test -n "${container}"; then
        "${runtime}" rm --force "${container}" >/dev/null 2>&1 || true
    fi
    rm -rf "${workdir}"
}
trap cleanup EXIT

container="$("${runtime}" create "${image}" serve)"
"${runtime}" cp "${container}:/usr/local/bin/lakekeeper" "${workdir}/lakekeeper"

libc_found=""
for candidate in /usr/lib64/libc.so.6 /lib64/libc.so.6 /usr/lib/aarch64-linux-gnu/libc.so.6; do
    if "${runtime}" cp "${container}:${candidate}" "${workdir}/libc.so.6" 2>/dev/null; then
        libc_found="${candidate}"
        break
    fi
done
test -n "${libc_found}"

highest_glibc() {
    # Highest GLIBC_x.y token in the file, ordered as versions rather than text.
    readelf --version-info "$1" 2>/dev/null \
        | grep -oE 'GLIBC_[0-9]+(\.[0-9]+)+' \
        | sed 's/^GLIBC_//' \
        | sort -uV \
        | tail -1
}

required="$(highest_glibc "${workdir}/lakekeeper")"
provided="$(highest_glibc "${workdir}/libc.so.6")"
test -n "${required}"
test -n "${provided}"

if test "$(printf '%s\n%s\n' "${required}" "${provided}" | sort -V | tail -1)" != "${provided}"; then
    echo "The binary requires glibc ${required} but the runtime provides ${provided}" >&2
    exit 1
fi

locked_required="$(ARCHITECTURE="${architecture}" LOCK="${lock}" python3 -c '
import json
import os

lock = json.load(open(os.environ["LOCK"], encoding="utf-8"))
entry = lock["architectures"][os.environ["ARCHITECTURE"]]["runtimeRequirements"]
print(entry["maxGlibcSymbolVersion"])
')"
if test "${required}" != "${locked_required}"; then
    echo "The binary requires glibc ${required}, but the lock records ${locked_required}" >&2
    exit 1
fi

needed="$(readelf --dynamic "${workdir}/lakekeeper" \
    | grep -oE 'Shared library: \[[^]]+\]' \
    | sed -e 's/^Shared library: \[//' -e 's/\]$//' \
    | sort -u)"
locked_needed="$(ARCHITECTURE="${architecture}" LOCK="${lock}" python3 -c '
import json
import os

lock = json.load(open(os.environ["LOCK"], encoding="utf-8"))
entry = lock["architectures"][os.environ["ARCHITECTURE"]]["runtimeRequirements"]
for library in sorted(entry["neededSharedLibraries"]):
    print(library)
')"
if test "${needed}" != "${locked_needed}"; then
    echo "The binary's needed shared libraries do not match the lock." >&2
    echo "image:" >&2
    printf '%s\n' "${needed}" >&2
    echo "lock:" >&2
    printf '%s\n' "${locked_needed}" >&2
    exit 1
fi

echo "The locked binary requires glibc ${required}; ${image} provides ${provided}"
