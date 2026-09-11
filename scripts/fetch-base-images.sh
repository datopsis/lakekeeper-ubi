#!/usr/bin/env bash
# Pull the digest-pinned UBI base images named by the artifact lock.
#
# Assembly runs with --pull=never so that a build cannot silently resolve a tag
# to different content. That requires the images to be present first, which is
# this script's only job.
set -Eeuo pipefail

# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/common.sh"

runtime="${CONTAINER_RUNTIME:-podman}"

usage() {
    cat <<'USAGE'
Usage: fetch-base-images.sh [--runtime podman|docker]

Pulls the digest-pinned base images recorded in artifacts/lakekeeper.lock.json.
USAGE
}

while test "$#" -gt 0; do
    case "$1" in
        --runtime)
            runtime="${2:-}"
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
require_command "${runtime}" "Install ${runtime}, or pass --runtime."

for key in builder runtime; do
    image="$(lock_get "baseImages.${key}")"
    log "pulling ${image}"
    "${runtime}" pull --quiet "${image}" >/dev/null
done

log "base images present"
