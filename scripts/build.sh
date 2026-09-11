#!/usr/bin/env bash
# Convenience wrapper: acquire, then assemble.
#
# This exists so a contributor can get a working image with one command. It is
# deliberately not the only entry point. CI runs the phases separately, and a
# controlled-network transfer runs acquisition and assembly on different hosts,
# which is the whole reason they are separable.
set -Eeuo pipefail

script_directory="$(dirname -- "${BASH_SOURCE[0]}")"

architecture=""
bundle_directory=""
image_tag=""
runtime=""
force="no"

usage() {
    cat <<'USAGE'
Usage: build.sh [--arch amd64|arm64] [--bundle-dir DIR] [--tag TAG]
                [--runtime podman|docker] [--force]

Fetches and verifies the locked artifacts, pulls the pinned base images, then
builds the image without pulling. Each phase is also runnable on its own:

  scripts/fetch-artifacts.sh    acquire and verify (needs network)
  scripts/fetch-base-images.sh  pull pinned bases (needs network)
  scripts/build-image.sh        verify again, then assemble (no image pulls)
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
            printf 'error: unknown argument: %s\n' "$1" >&2
            exit 1
            ;;
    esac
done

shared_arguments=()
test -z "${architecture}" || shared_arguments+=(--arch "${architecture}")
test -z "${bundle_directory}" || shared_arguments+=(--bundle-dir "${bundle_directory}")

fetch_arguments=("${shared_arguments[@]+"${shared_arguments[@]}"}")
test "${force}" = "no" || fetch_arguments+=(--force)

base_arguments=()
test -z "${runtime}" || base_arguments+=(--runtime "${runtime}")

build_arguments=("${shared_arguments[@]+"${shared_arguments[@]}"}")
test -z "${image_tag}" || build_arguments+=(--tag "${image_tag}")
test -z "${runtime}" || build_arguments+=(--runtime "${runtime}")

"${script_directory}/fetch-artifacts.sh" "${fetch_arguments[@]+"${fetch_arguments[@]}"}"
"${script_directory}/fetch-base-images.sh" "${base_arguments[@]+"${base_arguments[@]}"}"
"${script_directory}/build-image.sh" "${build_arguments[@]+"${build_arguments[@]}"}"
