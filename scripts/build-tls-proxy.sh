#!/usr/bin/env bash
# Use nginx-ubi's native Podman acquisition/build contract, then load into Docker.
set -Eeuo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
revision="$(cat "${root}/artifacts/nginx.commit")"
[[ "${revision}" =~ ^[0-9a-f]{40}$ ]]
case "$(uname -m)" in
    x86_64) architecture=amd64 ;;
    aarch64) architecture=arm64 ;;
    *) exit 1 ;;
esac
image=localhost/nginx-ubi:tls
source_directory="$(mktemp -d)"
trap 'rm -rf -- "${source_directory}"' EXIT
git -C "${source_directory}" init --quiet
git -C "${source_directory}" remote add origin https://github.com/datopsis/nginx-ubi.git
git -C "${source_directory}" fetch --depth=1 origin "${revision}"
git -C "${source_directory}" checkout --detach FETCH_HEAD
test "$(git -C "${source_directory}" rev-parse HEAD)" = "${revision}"
test -z "$(git -C "${source_directory}" status --porcelain)"
(
    cd "${source_directory}"
    python3 scripts/artifacts.py acquire --lock "artifacts/locks/${architecture}.json" \
        --output ".artifact-bundle/${architecture}"
    CONTAINER_RUNTIME=podman bash scripts/build-image.sh "${architecture}" "${image}"
    podman save --format docker-archive "${image}" | docker load
)
test "$(docker image inspect --format '{{.Architecture}}' "${image}")" = "${architecture}"
test "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "${image}")" = "${revision}"
lock_sha="$(sha256sum "${source_directory}/artifacts/locks/${architecture}.json" | cut -d' ' -f1)"
test "$(docker image inspect --format '{{index .Config.Labels "io.datopsis.artifact-lock.sha256"}}' "${image}")" = "${lock_sha}"
mkdir -p "${root}/.tls-fixture"
cp "${source_directory}/examples/profiles/lakekeeper/nginx.conf" "${root}/.tls-fixture/nginx.conf"
printf 'TLS proxy: revision=%s architecture=%s lock=%s image=%s\n' \
    "${revision}" "${architecture}" "${lock_sha}" "$(docker image inspect --format '{{.Id}}' "${image}")"
