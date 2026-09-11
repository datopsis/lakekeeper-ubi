#!/usr/bin/env bash
# Acquire the locked upstream release artifact for one architecture.
#
# This is the only step that touches the network on behalf of the image
# contents. It downloads exactly what artifacts/lakekeeper.lock.json names,
# proves the bytes match before extracting anything, and leaves a bundle that
# the build consumes offline. Nothing here resolves a version, queries a
# release feed, or follows "latest".
set -Eeuo pipefail

# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/common.sh"

architecture=""
bundle_directory=""
force="no"

usage() {
    cat <<'USAGE'
Usage: fetch-artifacts.sh [--arch amd64|arm64] [--bundle-dir DIR] [--force]

Downloads and verifies the locked Lakekeeper release archive, leaving a bundle
that scripts/build-image.sh can consume without network access.

  --arch        Architecture to fetch. Defaults to this host's architecture.
  --bundle-dir  Where to place the bundle. Defaults to .artifact-bundle/<arch>.
  --force       Re-download even if an existing bundle already verifies.
USAGE
}

while test "$#" -gt 0; do
    case "$1" in
        --arch)
            architecture="${2:-}"
            shift 2
            ;;
        --bundle-dir)
            bundle_directory="${2:-}"
            shift 2
            ;;
        --force)
            force="yes"
            shift
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            die "unknown argument: $1"
            ;;
    esac
done

require_command python3 "Install Python 3 to read the artifact lock."
require_command curl "Install curl."
require_command sha256sum "Install coreutils."
require_command tar "Install tar."

architecture="${architecture:-$(host_architecture)}"
bundle_directory="${bundle_directory:-$(bundle_directory_for "${architecture}")}"

case "${architecture}" in
    amd64 | arm64) ;;
    *) die "unsupported architecture: ${architecture}" ;;
esac

verify_bundle() {
    "$(dirname -- "${BASH_SOURCE[0]}")/verify-bundle.sh" \
        --arch "${architecture}" --bundle-dir "${bundle_directory}"
}

if test "${force}" = "no" && test -d "${bundle_directory}"; then
    if verify_bundle >/dev/null 2>&1; then
        log "bundle already present and verified: ${bundle_directory}"
        verify_bundle
        exit 0
    fi
    log "existing bundle did not verify; re-downloading"
fi

upstream_version="$(lock_get upstreamVersion)"
archive_url="$(lock_get "architectures.${architecture}.archive.url")"
archive_sha256="$(lock_get "architectures.${architecture}.archive.sha256")"
archive_size="$(lock_get "architectures.${architecture}.archive.sizeBytes")"
binary_name="$(lock_get "architectures.${architecture}.binary.path")"

staging="$(mktemp -d)"
cleanup() {
    rm -rf -- "${staging}"
}
trap cleanup EXIT

archive_path="${staging}/archive.tar.gz"

log "downloading ${archive_url}"
curl --fail --location --silent --show-error \
    --proto '=https' --tlsv1.2 \
    --output "${archive_path}" \
    "${archive_url}"

# Size first: it is the cheapest way to notice a truncated or redirected body.
actual_size="$(size_of "${archive_path}")"
test "${actual_size}" = "${archive_size}" \
    || die "archive size is ${actual_size}, the lock records ${archive_size}."

actual_digest="$(sha256_of "${archive_path}")"
test "${actual_digest}" = "${archive_sha256}" \
    || die "archive SHA-256 is ${actual_digest}, the lock records ${archive_sha256}."

# The archive must contain exactly the member the lock names. An extra member
# is a change in what upstream ships and needs review, not a silent extraction.
members="$(tar --list --gzip --file "${archive_path}")"
test "${members}" = "${binary_name}" \
    || die "archive contains unexpected members: $(printf '%s' "${members}" | tr '\n' ' ')"

tar --extract --gzip --file "${archive_path}" --directory "${staging}" "${binary_name}"
chmod 0555 "${staging}/${binary_name}"

UPSTREAM_VERSION="${upstream_version}" \
ARCHITECTURE="${architecture}" \
ARCHIVE_SHA256="${archive_sha256}" \
BINARY_SHA256="$(sha256_of "${staging}/${binary_name}")" \
BINARY_NAME="${binary_name}" \
ARCHIVE_URL="${archive_url}" \
python3 -c '
import json
import os

manifest = {
    "upstreamVersion": os.environ["UPSTREAM_VERSION"],
    "architecture": os.environ["ARCHITECTURE"],
    "archiveUrl": os.environ["ARCHIVE_URL"],
    "archiveSha256": os.environ["ARCHIVE_SHA256"],
    "binary": os.environ["BINARY_NAME"],
    "binarySha256": os.environ["BINARY_SHA256"],
}
print(json.dumps(manifest, indent=2, sort_keys=True))
' > "${staging}/bundle.json"

# The runtime packages are acquired here for the same reason the binary is:
# so that assembly consumes only reviewed bytes and needs no repository.
mkdir -p "${staging}/rpms"
while IFS=$'\t' read -r filename url expected_rpm_size expected_rpm_digest; do
    log "downloading ${filename}"
    curl --fail --location --silent --show-error \
        --proto '=https' --tlsv1.2 \
        --output "${staging}/rpms/${filename}" \
        "${url}"
    rpm_size="$(size_of "${staging}/rpms/${filename}")"
    test "${rpm_size}" = "${expected_rpm_size}" \
        || die "${filename} is ${rpm_size} bytes, the lock records ${expected_rpm_size}."
    rpm_digest="$(sha256_of "${staging}/rpms/${filename}")"
    test "${rpm_digest}" = "${expected_rpm_digest}" \
        || die "${filename} SHA-256 is ${rpm_digest}, the lock records ${expected_rpm_digest}."
done < <(LOCK_FILE="${LOCK_FILE}" ARCHITECTURE="${architecture}" python3 -c '
import json
import os

lock = json.load(open(os.environ["LOCK_FILE"], encoding="utf-8"))
for entry in lock["architectures"][os.environ["ARCHITECTURE"]]["rpms"]:
    print("\t".join([
        entry["filename"],
        entry["url"],
        str(entry["sizeBytes"]),
        entry["sha256"],
    ]))
')

# The archive itself is not part of the bundle. Only the verified binary and
# its manifest may reach a build context.
rm -f -- "${archive_path}"

# Replace the bundle only once its contents are complete, so an interrupted
# run cannot leave a half-written bundle that a later build would trust.
rm -rf -- "${bundle_directory}"
mkdir -p -- "$(dirname -- "${bundle_directory}")"
mv -- "${staging}" "${bundle_directory}"
trap - EXIT

verify_bundle
