#!/usr/bin/env bash
# The fixture has no published image. Build only the reviewed source revision.
set -Eeuo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
runtime="${CONTAINER_RUNTIME:-podman}"
image="${POSTGRES_IMAGE:-localhost/postgresql-lakekeeper-ubi:development}"
revision="$(cat "${repository_root}/artifacts/postgresql-lakekeeper.commit")"
[[ "${revision}" =~ ^[0-9a-f]{40}$ ]]
case "$(uname -m)" in
    x86_64) architecture=amd64 ;;
    aarch64 | arm64) architecture=arm64 ;;
    *) echo 'Unsupported native architecture' >&2; exit 1 ;;
esac

source_directory="$(mktemp -d)"
trap 'rm -rf -- "${source_directory}"' EXIT
started="${SECONDS}"
git -C "${source_directory}" init --quiet
git -C "${source_directory}" remote add origin https://github.com/datopsis/postgresql-lakekeeper-ubi.git
git -C "${source_directory}" fetch --depth=1 origin "${revision}"
git -C "${source_directory}" checkout --detach FETCH_HEAD
test "$(git -C "${source_directory}" rev-parse HEAD)" = "${revision}"
test -z "$(git -C "${source_directory}" status --porcelain)"

(
    cd "${source_directory}"
    CONTAINER_RUNTIME="${runtime}" IMAGE="${image}" RELEASE_REVISION="${revision}" \
        bash scripts/build-offline.sh
)

# Check the loaded image, not just the Git checkout or a build success status.
test "$("${runtime}" image inspect --format '{{.Architecture}}' "${image}")" = "${architecture}"
test "$("${runtime}" image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "${image}")" = "${revision}"
lock_sha="$(sha256sum "${source_directory}/artifacts/locks/${architecture}.json" | cut -d' ' -f1)"
test "$("${runtime}" image inspect --format '{{index .Config.Labels "io.datopsis.artifact-lock.sha256"}}' "${image}")" = "${lock_sha}"
image_id="$("${runtime}" image inspect --format '{{.Id}}' "${image}")"
printf 'PostgreSQL fixture: revision=%s architecture=%s image=%s lock=%s elapsed=%ss\n' \
    "${revision}" "${architecture}" "${image_id}" "${lock_sha}" "$((SECONDS - started))"
if test -n "${GITHUB_STEP_SUMMARY:-}"; then
    printf 'PostgreSQL fixture: %s, %s, image %s, lock %s; acquisition/build/verification: **%ss**.\n' \
        "${revision}" "${architecture}" "${image_id}" "${lock_sha}" "$((SECONDS - started))" >> "${GITHUB_STEP_SUMMARY}"
fi
