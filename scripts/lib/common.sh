# Shared helpers for the acquisition and assembly scripts.
#
# This file is sourced, not executed. Callers set their own shell options.

# shellcheck shell=bash

repository_root() {
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd
}

REPOSITORY_ROOT="${REPOSITORY_ROOT:-$(repository_root)}"
LOCK_FILE="${LOCK_FILE:-${REPOSITORY_ROOT}/artifacts/lakekeeper.lock.json}"
BUNDLE_ROOT="${BUNDLE_ROOT:-${REPOSITORY_ROOT}/.artifact-bundle}"
DEFAULT_IMAGE_TAG="${DEFAULT_IMAGE_TAG:-localhost/lakekeeper-ubi9:development}"

log() {
    printf '%s\n' "$*" >&2
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

require_command() {
    local name="$1"
    local hint="${2:-}"
    if ! command -v "${name}" >/dev/null 2>&1; then
        if test -n "${hint}"; then
            die "${name} is required but was not found. ${hint}"
        fi
        die "${name} is required but was not found."
    fi
}

# Read one dotted path out of the artifact lock.
lock_get() {
    LOCK_FILE="${LOCK_FILE}" LOCK_PATH="$1" python3 -c '
import json
import os

value = json.load(open(os.environ["LOCK_FILE"], encoding="utf-8"))
for key in os.environ["LOCK_PATH"].split("."):
    value = value[key]
print(value)
'
}

# Read a list out of the artifact lock, one element per line.
lock_get_list() {
    LOCK_FILE="${LOCK_FILE}" LOCK_PATH="$1" python3 -c '
import json
import os

value = json.load(open(os.environ["LOCK_FILE"], encoding="utf-8"))
for key in os.environ["LOCK_PATH"].split("."):
    value = value[key]
for element in value:
    print(element)
'
}

host_architecture() {
    local machine
    machine="$(uname -m)"
    case "${machine}" in
        x86_64 | amd64)
            printf 'amd64\n'
            ;;
        aarch64 | arm64)
            printf 'arm64\n'
            ;;
        *)
            die "unsupported host architecture: ${machine}"
            ;;
    esac
}

# The ELF machine string readelf prints for each supported architecture.
elf_machine_for() {
    case "$1" in
        amd64)
            printf 'Advanced Micro Devices X86-64\n'
            ;;
        arm64)
            printf 'AArch64\n'
            ;;
        *)
            die "unsupported architecture: $1"
            ;;
    esac
}

sha256_of() {
    sha256sum -- "$1" | cut -d' ' -f1
}

size_of() {
    # BSD and GNU stat disagree; wc is portable and the files are local.
    wc -c < "$1" | tr -d '[:space:]'
}

bundle_directory_for() {
    printf '%s/%s\n' "${BUNDLE_ROOT}" "$1"
}
