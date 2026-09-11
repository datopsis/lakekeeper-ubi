#!/usr/bin/env bash
# Regenerate the runtime RPM manifest in the artifact lock.
#
# This is a maintainer tool, not part of a build. Dependency resolution is an
# update activity that produces a reviewable change; ordinary builds consume
# only what a merged lock already names.
#
# Resolution happens against a root that already carries the UBI Micro RPM
# database, so the result is the genuine delta between the final stage and what
# the image needs, rather than a full base system the final stage already has.
set -Eeuo pipefail

# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/lib/common.sh"

runtime="${CONTAINER_RUNTIME:-podman}"
architectures=()

usage() {
    cat <<'USAGE'
Usage: update-rpm-lock.sh [--arch amd64|arm64] [--runtime podman|docker]

Resolves the runtime package delta over UBI Micro and writes the resulting RPM
manifest into artifacts/lakekeeper.lock.json. Repeat --arch to update several
architectures; the default updates both.

The resulting change must be reviewed like any other lock change.
USAGE
}

while test "$#" -gt 0; do
    case "$1" in
        --arch)
            architectures+=("${2:-}")
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

if test "${#architectures[@]}" -eq 0; then
    architectures=(amd64 arm64)
fi

minimal_image="$(lock_get baseImages.builder)"
micro_image="$(lock_get baseImages.runtime)"
requested="$(lock_get_list runtimePackages.requested | tr '\n' ' ')"

workdir="$(mktemp -d)"
cleanup() {
    rm -rf -- "${workdir}"
}
trap cleanup EXIT

for architecture in "${architectures[@]}"; do
    case "${architecture}" in
        amd64) rpm_architecture="x86_64" ;;
        arm64) rpm_architecture="aarch64" ;;
        *) die "unsupported architecture: ${architecture}" ;;
    esac

    log "resolving the runtime package delta for ${architecture}"

    # --forcearch lets one host resolve either architecture. Nothing is
    # executed from the foreign package set; it is only downloaded and hashed.
    cat > "${workdir}/Containerfile" <<CONTAINERFILE
# The Micro database must come from the architecture being resolved, or the
# already-installed set is wrong and the delta is meaningless. Nothing from
# this stage is executed; its files are only read.
FROM --platform=linux/${architecture} ${micro_image} AS microbase

FROM ${minimal_image} AS resolver
COPY --from=microbase / /runtime
RUN microdnf install -y dnf >/dev/null 2>&1 \
    && mkdir -p /rpms \
    && dnf install -y --installroot=/runtime --releasever=9 \
        --forcearch=${rpm_architecture} \
        --setopt=install_weak_deps=0 --downloadonly --destdir=/rpms \
        ${requested}
# Packages the Micro database already records, but whose files the image ships
# without, must be requested explicitly or they will never be reinstalled.
RUN for package in ${requested}; do \
        dnf reinstall -y --installroot=/runtime --releasever=9 \
            --forcearch=${rpm_architecture} \
            --downloadonly --destdir=/rpms "\${package}" >/dev/null 2>&1 || true; \
    done \
    && test "\$(find /rpms -name '*.rpm' | wc -l)" -ge 10
CONTAINERFILE

    "${runtime}" build --format docker --quiet \
        --file "${workdir}/Containerfile" \
        --tag "localhost/lakekeeper-rpm-resolver:${architecture}" \
        "${workdir}" >/dev/null

    container="$("${runtime}" create "localhost/lakekeeper-rpm-resolver:${architecture}" sh)"
    rm -rf -- "${workdir}/rpms"
    "${runtime}" cp "${container}:/rpms" "${workdir}/rpms"
    "${runtime}" rm --force "${container}" >/dev/null

    # The download location is recorded from repository metadata so that an
    # ordinary build never needs repository metadata of its own.
    "${runtime}" run --rm --entrypoint sh \
        "localhost/lakekeeper-rpm-resolver:${architecture}" -c "
            microdnf install -y dnf >/dev/null 2>&1
            dnf repoquery --installroot=/runtime --releasever=9 \
                --forcearch=${rpm_architecture} --location \
                \$(ls -1 /rpms | sed 's/\.rpm\$//') 2>/dev/null
        " | grep '^http' | sort -u > "${workdir}/urls.txt"

    ARCHITECTURE="${architecture}" \
    RPM_DIR="${workdir}/rpms" \
    URL_FILE="${workdir}/urls.txt" \
    LOCK_FILE="${LOCK_FILE}" \
    python3 "$(dirname -- "${BASH_SOURCE[0]}")/lib/write_rpm_lock.py"

    log "recorded the ${architecture} runtime package manifest"
done

log "artifact lock updated; review the change before committing it"
