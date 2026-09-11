#!/usr/bin/env bash
# Decide whether a local artifact bundle may enter an image build.
#
# This is the admission gate described in docs/ARTIFACT-ACQUISITION.md. It runs
# after acquisition and again immediately before assembly, because the bundle
# sits on disk between those two steps and nothing else proves it is unchanged.
#
# Every check compares the bundle against artifacts/lakekeeper.lock.json, which
# is reviewed repository content. The lock is the authority; the bundle is not.
set -Eeuo pipefail

# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/common.sh"

architecture=""
bundle_directory=""

usage() {
    cat <<'USAGE'
Usage: verify-bundle.sh [--arch amd64|arm64] [--bundle-dir DIR]

Verifies a downloaded artifact bundle against artifacts/lakekeeper.lock.json.
Exits non-zero, and says which property failed, if the bundle is not admissible.
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
require_command sha256sum "Install coreutils."
require_command readelf "Install binutils. Verification reads the binary's ELF metadata and will not be skipped."

architecture="${architecture:-$(host_architecture)}"
bundle_directory="${bundle_directory:-$(bundle_directory_for "${architecture}")}"

case "${architecture}" in
    amd64 | arm64) ;;
    *) die "unsupported architecture: ${architecture}" ;;
esac

binary_name="$(lock_get "architectures.${architecture}.binary.path")"
binary_path="${bundle_directory}/${binary_name}"
manifest_path="${bundle_directory}/bundle.json"

test -d "${bundle_directory}" \
    || die "no bundle at ${bundle_directory}. Run scripts/fetch-artifacts.sh first."
test -f "${binary_path}" \
    || die "the bundle is missing ${binary_name}. Re-run scripts/fetch-artifacts.sh --force."
test -f "${manifest_path}" \
    || die "the bundle has no bundle.json. Re-run scripts/fetch-artifacts.sh --force."

# A bundle produced before a lock update must not be reused silently.
recorded_version="$(BUNDLE="${manifest_path}" python3 -c '
import json
import os

print(json.load(open(os.environ["BUNDLE"], encoding="utf-8"))["upstreamVersion"])
')"
expected_version="$(lock_get upstreamVersion)"
test "${recorded_version}" = "${expected_version}" \
    || die "the bundle holds ${recorded_version} but the lock now requires ${expected_version}. Re-run scripts/fetch-artifacts.sh --force."

expected_size="$(lock_get "architectures.${architecture}.binary.sizeBytes")"
actual_size="$(size_of "${binary_path}")"
test "${actual_size}" = "${expected_size}" \
    || die "binary size is ${actual_size}, the lock records ${expected_size}."

expected_digest="$(lock_get "architectures.${architecture}.binary.sha256")"
actual_digest="$(sha256_of "${binary_path}")"
test "${actual_digest}" = "${expected_digest}" \
    || die "binary SHA-256 is ${actual_digest}, the lock records ${expected_digest}."

expected_machine="$(elf_machine_for "${architecture}")"
actual_machine="$(readelf --file-header "${binary_path}" \
    | sed -n 's/^[[:space:]]*Machine:[[:space:]]*//p')"
test "${actual_machine}" = "${expected_machine}" \
    || die "binary targets '${actual_machine}', expected '${expected_machine}' for ${architecture}."

expected_build_id="$(lock_get "architectures.${architecture}.binary.buildId")"
actual_build_id="$(readelf --notes "${binary_path}" \
    | sed -n 's/^[[:space:]]*Build ID:[[:space:]]*//p' | head -1)"
test "${actual_build_id}" = "${expected_build_id}" \
    || die "binary build ID is ${actual_build_id}, the lock records ${expected_build_id}."

expected_glibc="$(lock_get "architectures.${architecture}.runtimeRequirements.maxGlibcSymbolVersion")"
actual_glibc="$(readelf --version-info "${binary_path}" 2>/dev/null \
    | grep -oE 'GLIBC_[0-9]+(\.[0-9]+)+' \
    | sed 's/^GLIBC_//' \
    | sort -uV \
    | tail -1)"
test "${actual_glibc}" = "${expected_glibc}" \
    || die "binary requires glibc ${actual_glibc}, the lock records ${expected_glibc}."

expected_libraries="$(lock_get_list "architectures.${architecture}.runtimeRequirements.neededSharedLibraries" | sort)"
actual_libraries="$(readelf --dynamic "${binary_path}" \
    | grep -oE 'Shared library: \[[^]]+\]' \
    | sed -e 's/^Shared library: \[//' -e 's/\]$//' \
    | sort -u)"
if test "${actual_libraries}" != "${expected_libraries}"; then
    log "binary needs:"
    printf '%s\n' "${actual_libraries}" >&2
    log "the lock records:"
    printf '%s\n' "${expected_libraries}" >&2
    die "the binary's needed shared libraries do not match the lock."
fi

# The dependency manifest is the only inventory of Lakekeeper's own
# dependencies this project can obtain, so it is admitted on the same terms as
# everything else.
crate_manifest="${bundle_directory}/Cargo.lock"
test -f "${crate_manifest}" \
    || die "the bundle has no Cargo.lock. Re-run scripts/fetch-artifacts.sh --force."
expected_crate_size="$(lock_get crateInventory.sizeBytes)"
actual_crate_size="$(size_of "${crate_manifest}")"
test "${actual_crate_size}" = "${expected_crate_size}" \
    || die "Cargo.lock is ${actual_crate_size} bytes, the lock records ${expected_crate_size}."
expected_crate_digest="$(lock_get crateInventory.sha256)"
actual_crate_digest="$(sha256_of "${crate_manifest}")"
test "${actual_crate_digest}" = "${expected_crate_digest}" \
    || die "Cargo.lock SHA-256 is ${actual_crate_digest}, the lock records ${expected_crate_digest}."

# Every locked runtime package must be present and unaltered.
rpm_directory="${bundle_directory}/rpms"
test -d "${rpm_directory}" \
    || die "the bundle has no rpms directory. Re-run scripts/fetch-artifacts.sh --force."

locked_rpm_count=0
while IFS=$'\t' read -r filename expected_rpm_size expected_rpm_digest; do
    locked_rpm_count=$((locked_rpm_count + 1))
    rpm_path="${rpm_directory}/${filename}"
    test -f "${rpm_path}" || die "the bundle is missing ${filename}."
    rpm_size="$(size_of "${rpm_path}")"
    test "${rpm_size}" = "${expected_rpm_size}" \
        || die "${filename} is ${rpm_size} bytes, the lock records ${expected_rpm_size}."
    rpm_digest="$(sha256_of "${rpm_path}")"
    test "${rpm_digest}" = "${expected_rpm_digest}" \
        || die "${filename} SHA-256 is ${rpm_digest}, the lock records ${expected_rpm_digest}."
done < <(LOCK_FILE="${LOCK_FILE}" ARCHITECTURE="${architecture}" python3 -c '
import json
import os

lock = json.load(open(os.environ["LOCK_FILE"], encoding="utf-8"))
for entry in lock["architectures"][os.environ["ARCHITECTURE"]]["rpms"]:
    print("\t".join([entry["filename"], str(entry["sizeBytes"]), entry["sha256"]]))
')

# An unlocked package in the bundle would be installed without review.
present_rpm_count="$(find "${rpm_directory}" -mindepth 1 -maxdepth 1 -type f | wc -l)"
test "${present_rpm_count}" = "${locked_rpm_count}" \
    || die "the bundle holds ${present_rpm_count} packages, the lock records ${locked_rpm_count}."

# Nothing beyond the binary, its manifest, and the locked packages may reach
# the build context.
unexpected="$(find "${bundle_directory}" -mindepth 1 -maxdepth 1 \
    ! -name "${binary_name}" ! -name bundle.json ! -name rpms ! -name Cargo.lock \
    -printf '%f\n' 2>/dev/null || true)"
test -z "${unexpected}" \
    || die "the bundle contains unexpected entries: $(printf '%s' "${unexpected}" | tr '\n' ' ')"

log "bundle verified: ${binary_name} ${expected_version} (${architecture}), glibc ${actual_glibc}, ${locked_rpm_count} runtime packages"
