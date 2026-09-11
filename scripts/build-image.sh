#!/usr/bin/env bash
# Assemble the image from a verified local bundle.
#
# This step must not acquire anything that ends up in the image. It re-verifies
# the bundle immediately before building, because acquisition and assembly are
# separate phases and the bundle sits on disk in between.
#
# The bundle enters the build as a named build context rather than through the
# default context, so an unrelated file in the working tree cannot reach the
# image, and so a disconnected host can keep its bundle outside the repository.
set -Eeuo pipefail

# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/common.sh"

architecture=""
bundle_directory=""
image_tag="${DEFAULT_IMAGE_TAG}"
runtime="${CONTAINER_RUNTIME:-podman}"

usage() {
    cat <<'USAGE'
Usage: build-image.sh [--arch amd64|arm64] [--bundle-dir DIR] [--tag TAG]
                      [--runtime podman|docker]

Verifies the bundle, then builds the image without pulling.
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
        --tag)
            image_tag="${2:-}"
            shift 2
            ;;
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

architecture="${architecture:-$(host_architecture)}"
bundle_directory="${bundle_directory:-$(bundle_directory_for "${architecture}")}"

# The builder stage still runs package management, which cannot execute for a
# foreign architecture without emulation. Refuse clearly rather than failing
# deep inside the build.
host="$(host_architecture)"
test "${architecture}" = "${host}" \
    || die "cannot build ${architecture} on a ${host} host: the builder stage runs commands natively. Build on a native runner."

"$(dirname -- "${BASH_SOURCE[0]}")/verify-bundle.sh" \
    --arch "${architecture}" --bundle-dir "${bundle_directory}"

pull_argument=(--pull=never)
if ! grep -qi podman <<< "$("${runtime}" --version 2>&1)"; then
    # Docker spells the same intent differently.
    pull_argument=(--pull=false)
fi

log "building ${image_tag} for ${architecture}"
"${runtime}" build \
    --format docker \
    --file "${REPOSITORY_ROOT}/Containerfile" \
    --build-context "bundle=${bundle_directory}" \
    "${pull_argument[@]}" \
    --tag "${image_tag}" \
    "${REPOSITORY_ROOT}"

log "built ${image_tag}"
