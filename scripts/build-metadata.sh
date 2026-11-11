#!/usr/bin/env bash
# Shared build arguments for local assembly and CI (also GitHub output syntax).
set -Eeuo pipefail

# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/common.sh"

require_command git "Build from a Git checkout of this repository."
require_command sha256sum "Install coreutils."

revision="$(git -C "${REPOSITORY_ROOT}" rev-parse --verify HEAD)"
[[ "${revision}" =~ ^[0-9a-f]{40}$ ]] || die "expected a full source commit SHA"
# Hash the exact lock bytes, including both architectures, as Trino does.
lock_sha="$(sha256_of "${LOCK_FILE}")"
printf 'SOURCE_REVISION=%s\nLOCK_SHA256=%s\n' "${revision}" "${lock_sha}"
