#!/usr/bin/env bash
set -Eeuo pipefail

runtime="${CONTAINER_RUNTIME:-podman}"
image="${IMAGE:-localhost/lakekeeper-ubi9:development}"
expected_version="${LAKEKEEPER_VERSION:-0.13.4}"
postgres_image="${POSTGRES_IMAGE:-docker.io/library/postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73}"

prefix="lakekeeper-ubi9-smoke-${RANDOM}-$$"
network="${prefix}-net"
database="${prefix}-db"
primary="${prefix}-primary"
arbitrary="${prefix}-arbitrary"
default_key="${prefix}-default-key"
missing_key="${prefix}-missing-key"
invalid_toggle="${prefix}-invalid-toggle"
blank_key="${prefix}-blank-key"
default_value_key="${prefix}-default-value-key"
unmigrated="${prefix}-unmigrated"
unreachable="${prefix}-unreachable"

no_new_privileges="no-new-privileges:true"
readonly_runtime_args=(--read-only)

if grep -qi podman <<< "$("${runtime}" --version 2>&1)"; then
    # Podman otherwise creates a writable tmpfs for read-only containers, which
    # would hide a dependency on a writable path.
    readonly_runtime_args+=(--read-only-tmpfs=false)
    # Older supported-for-development Podman releases reject Docker's :true
    # spelling but enforce the same security option with the bare name.
    no_new_privileges="no-new-privileges"
fi

# Credentials are generated per run. No credential is committed to this
# repository or reused between runs.
postgres_password="$(head -c 24 /dev/urandom | base64 | tr -d '=+/[:space:]')"
encryption_key="$(head -c 24 /dev/urandom | base64 | tr -d '=+/[:space:]')"
database_url="postgres://lakekeeper:${postgres_password}@${database}:5432/lakekeeper"

cleanup() {
    "${runtime}" rm --force \
        "${primary}" "${arbitrary}" "${default_key}" "${missing_key}" \
        "${invalid_toggle}" "${blank_key}" "${default_value_key}" \
        "${unmigrated}" "${unreachable}" \
        "${database}" \
        >/dev/null 2>&1 || true
    "${runtime}" network rm --force "${network}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

run_catalog() {
    local name="$1"
    shift
    "${runtime}" run --detach --name "${name}" \
        --network "${network}" \
        "${readonly_runtime_args[@]}" \
        --cap-drop ALL \
        --security-opt "${no_new_privileges}" \
        --env "LAKEKEEPER__PG_DATABASE_URL_WRITE=${database_url}" \
        --env "LAKEKEEPER__PG_ENCRYPTION_KEY=${encryption_key}" \
        "$@" \
        "${image}" serve >/dev/null
}

assert_process_security() {
    local name="$1"
    # The variables expand in the inner container shell, not this script.
    # shellcheck disable=SC2016
    "${runtime}" exec "${name}" sh -eu -c '
        for status in /proc/[0-9]*/status; do
            uid=""
            cap_eff=""
            no_new_privs=""
            while IFS=: read -r key value; do
                case "${key}" in
                    Uid)
                        set -- ${value}
                        uid="$1"
                        ;;
                    CapEff)
                        set -- ${value}
                        cap_eff="$1"
                        ;;
                    NoNewPrivs)
                        set -- ${value}
                        no_new_privs="$1"
                        ;;
                esac
            done < "${status}"
            test -n "${uid}"
            test "${uid}" -ne 0
            test "${cap_eff}" = "0000000000000000"
            test "${no_new_privs}" = "1"
        done
    '
}

wait_for_database() {
    local _
    for _ in {1..60}; do
        if "${runtime}" exec "${database}" \
            pg_isready --username lakekeeper --dbname lakekeeper \
            >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    "${runtime}" logs "${database}" >&2
    echo "The PostgreSQL fixture never became ready" >&2
    return 1
}

wait_for_catalog() {
    local name="$1"
    local _
    for _ in {1..60}; do
        if "${runtime}" exec "${name}" lakekeeper healthcheck -s \
            >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    "${runtime}" logs "${name}" >&2
    echo "The catalog in ${name} never became healthy" >&2
    return 1
}

wait_for_exit() {
    local name="$1"
    local expected_code="${2:-}"
    local state
    local exit_code
    local _
    for _ in {1..60}; do
        state="$("${runtime}" inspect --format '{{.State.Status}}' "${name}")"
        if test "${state}" != "running"; then
            exit_code="$("${runtime}" inspect --format '{{.State.ExitCode}}' "${name}")"
            if test -n "${expected_code}"; then
                test "${exit_code}" = "${expected_code}"
            else
                test "${exit_code}" != "0"
            fi
            return
        fi
        sleep 1
    done
    "${runtime}" logs "${name}" >&2
    echo "Expected ${name} to exit with a failure" >&2
    return 1
}

wait_for_log() {
    local name="$1"
    local expected="$2"
    local logs
    local _
    for _ in {1..60}; do
        logs="$("${runtime}" logs "${name}" 2>&1)"
        if grep -Fq "${expected}" <<< "${logs}"; then
            return
        fi
        sleep 1
    done
    "${runtime}" logs "${name}" >&2
    echo "Timed out waiting for ${name} to log: ${expected}" >&2
    return 1
}

assert_clean_exit() {
    local name="$1"
    "${runtime}" stop --time 30 "${name}" >/dev/null
    test "$("${runtime}" inspect --format '{{.State.ExitCode}}' "${name}")" = "0"
}

test "$("${runtime}" image inspect --format '{{.Config.User}}' "${image}")" = "999:0"

"${runtime}" network create "${network}" >/dev/null

"${runtime}" run --detach --name "${database}" \
    --network "${network}" \
    --env POSTGRES_USER=lakekeeper \
    --env POSTGRES_DB=lakekeeper \
    --env "POSTGRES_PASSWORD=${postgres_password}" \
    "${postgres_image}" >/dev/null
wait_for_database

# `serve` must never migrate implicitly, so migration runs as its own unit
# under the same restricted runtime the server uses.
"${runtime}" run --rm \
    --network "${network}" \
    "${readonly_runtime_args[@]}" \
    --cap-drop ALL \
    --security-opt "${no_new_privileges}" \
    --env "LAKEKEEPER__PG_DATABASE_URL_WRITE=${database_url}" \
    --env "LAKEKEEPER__PG_ENCRYPTION_KEY=${encryption_key}" \
    "${image}" migrate >/dev/null

# The catalog receives no writable mount at all: the default profile must run
# entirely on a read-only root filesystem.
run_catalog "${primary}" --publish 127.0.0.1::8181
wait_for_catalog "${primary}"

test "$("${runtime}" exec "${primary}" id -u)" = "999"
test "$("${runtime}" exec "${primary}" id -g)" = "0"
assert_process_security "${primary}"
"${runtime}" exec "${primary}" sh -c \
    '! command -v dnf && ! command -v microdnf && ! command -v rpm && ! command -v yum'
"${runtime}" exec "${primary}" sh -c \
    '! (printf probe > /root-filesystem-probe) >/dev/null 2>&1'
"${runtime}" exec "${primary}" test ! -w /usr/local/bin/lakekeeper
# The entrypoint must exec, leaving the server as PID 1 so that it receives
# signals directly and no shell remains in the container.
# The variable expands in the inner container shell, not this script.
# shellcheck disable=SC2016
"${runtime}" exec "${primary}" sh -c \
    'read -r comm < /proc/1/comm; test "${comm}" = "lakekeeper"'
test "$("${runtime}" exec "${primary}" lakekeeper version)" = "${expected_version}"

binding="$("${runtime}" port "${primary}" 8181/tcp)"
host_port="${binding##*:}"
base_url="http://127.0.0.1:${host_port}"

health_body="$(curl --fail --silent --show-error "${base_url}/health")"
grep -Fq '"health":"ok"' <<< "${health_body}"

info_body="$(curl --fail --silent --show-error "${base_url}/management/v1/info")"
grep -Fq "\"lakekeeper-version\":\"${expected_version}\"" <<< "${info_body}"

# An unknown warehouse must be refused rather than silently resolved.
test "$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    "${base_url}/catalog/v1/config?warehouse=smoke-probe-missing")" = "404"

# Responses carry a correlation identifier and no server banner.
headers="$(curl --fail --silent --show-error --dump-header - --output /dev/null \
    "${base_url}/health")"
grep -Eiq '^x-request-id:' <<< "${headers}"
if grep -Eiq '^server:' <<< "${headers}"; then
    echo "The catalog unexpectedly advertised a server banner" >&2
    exit 1
fi

primary_logs="$("${runtime}" logs "${primary}" 2>&1)"
# Logs are structured and record the refused request for correlation.
grep -Fq '"target":"lakekeeper::serve"' <<< "${primary_logs}"
grep -Fq 'smoke-probe-missing' <<< "${primary_logs}"
# Supplying a key must silence the upstream unsafe-default warning.
if grep -Fq 'Using default encryption key' <<< "${primary_logs}"; then
    echo "The catalog fell back to the default encryption key" >&2
    exit 1
fi
# Neither the database password nor the encryption key may reach the logs.
if grep -Fq "${postgres_password}" <<< "${primary_logs}" \
    || grep -Fq "${encryption_key}" <<< "${primary_logs}"; then
    echo "A secret value appeared in the container logs" >&2
    exit 1
fi

# Platforms such as OpenShift assign an arbitrary non-root UID in group 0.
run_catalog "${arbitrary}" --user 10001:0
wait_for_catalog "${arbitrary}"
test "$("${runtime}" exec "${arbitrary}" id -u)" = "10001"
test "$("${runtime}" exec "${arbitrary}" id -g)" = "0"
assert_process_security "${arbitrary}"

# The image adds a fail-closed guard for the secret encryption key.
#
# Upstream starts with a publicly known default key when none is supplied and
# only warns, so a deployment can look healthy indefinitely while every stored
# storage credential is decryptable by anyone. These cases pin both the guard
# and the upstream behavior it replaces. See docs/CONFIGURATION.md.

# Default: a missing key is a startup failure, not a silent fallback.
"${runtime}" run --detach --name "${missing_key}" \
    --network "${network}" \
    "${readonly_runtime_args[@]}" \
    --cap-drop ALL \
    --security-opt "${no_new_privileges}" \
    --env "LAKEKEEPER__PG_DATABASE_URL_WRITE=${database_url}" \
    "${image}" serve >/dev/null
wait_for_exit "${missing_key}" 78
missing_key_logs="$("${runtime}" logs "${missing_key}" 2>&1)"
# The diagnostic must name the variable to set and the way to opt out.
grep -Fq 'LAKEKEEPER__PG_ENCRYPTION_KEY' <<< "${missing_key_logs}"
grep -Fq 'LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY=false' <<< "${missing_key_logs}"
# The guard must refuse before the server reaches the database.
if grep -Fq 'Using default encryption key' <<< "${missing_key_logs}"; then
    echo "The catalog started despite the fail-closed guard" >&2
    exit 1
fi

# A key of only whitespace is empty, not a value.
"${runtime}" run --detach --name "${blank_key}" \
    --network "${network}" \
    "${readonly_runtime_args[@]}" \
    --cap-drop ALL \
    --security-opt "${no_new_privileges}" \
    --env "LAKEKEEPER__PG_DATABASE_URL_WRITE=${database_url}" \
    --env "LAKEKEEPER__PG_ENCRYPTION_KEY=   " \
    "${image}" serve >/dev/null
wait_for_exit "${blank_key}" 78

# Setting the key to upstream's published default is as unsafe as leaving it
# unset, and upstream does not warn in that case: its warning fires only on an
# absent variable. A chart default or a copied example lands exactly here.
"${runtime}" run --detach --name "${default_value_key}" \
    --network "${network}" \
    "${readonly_runtime_args[@]}" \
    --cap-drop ALL \
    --security-opt "${no_new_privileges}" \
    --env "LAKEKEEPER__PG_DATABASE_URL_WRITE=${database_url}" \
    --env "LAKEKEEPER__PG_ENCRYPTION_KEY=This is unsafe, please set a proper key" \
    "${image}" serve >/dev/null
wait_for_exit "${default_value_key}" 78
grep -Fq 'publicly known upstream default' <<< \
    "$("${runtime}" logs "${default_value_key}" 2>&1)"

# An unreadable toggle fails closed rather than being ignored.
"${runtime}" run --detach --name "${invalid_toggle}" \
    --network "${network}" \
    "${readonly_runtime_args[@]}" \
    --cap-drop ALL \
    --security-opt "${no_new_privileges}" \
    --env "LAKEKEEPER__PG_DATABASE_URL_WRITE=${database_url}" \
    --env "LAKEKEEPER__PG_ENCRYPTION_KEY=${encryption_key}" \
    --env "LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY=perhaps" \
    "${image}" serve >/dev/null
wait_for_exit "${invalid_toggle}" 78
grep -Fq 'LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY' <<< \
    "$("${runtime}" logs "${invalid_toggle}" 2>&1)"

# Informational commands stay usable without a key so that an operator can
# still diagnose a container that the guard refuses to start.
test "$("${runtime}" run --rm "${image}" version)" = "${expected_version}"

# Opting out restores upstream behavior exactly: the server starts and warns.
# This also detects an upstream change to fail-closed, which would be good
# news but must be noticed deliberately rather than silently inherited.
"${runtime}" run --detach --name "${default_key}" \
    --network "${network}" \
    "${readonly_runtime_args[@]}" \
    --cap-drop ALL \
    --security-opt "${no_new_privileges}" \
    --env "LAKEKEEPER__PG_DATABASE_URL_WRITE=${database_url}" \
    --env "LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY=false" \
    "${image}" serve >/dev/null
wait_for_log "${default_key}" 'Using default encryption key'
"${runtime}" rm --force "${default_key}" >/dev/null

# `serve` against an unmigrated database must fail with a useful diagnostic
# instead of starting and creating schema on demand.
"${runtime}" exec "${database}" \
    psql --username lakekeeper --dbname lakekeeper \
    --command 'CREATE DATABASE unmigrated;' >/dev/null
"${runtime}" run --detach --name "${unmigrated}" \
    --network "${network}" \
    "${readonly_runtime_args[@]}" \
    --cap-drop ALL \
    --security-opt "${no_new_privileges}" \
    --env "LAKEKEEPER__PG_DATABASE_URL_WRITE=postgres://lakekeeper:${postgres_password}@${database}:5432/unmigrated" \
    --env "LAKEKEEPER__PG_ENCRYPTION_KEY=${encryption_key}" \
    "${image}" serve >/dev/null
wait_for_exit "${unmigrated}"
grep -Fq 'does not exist' <<< "$("${runtime}" logs "${unmigrated}" 2>&1)"

# An unreachable database must fail the migration rather than hang silently.
"${runtime}" run --detach --name "${unreachable}" \
    --network "${network}" \
    "${readonly_runtime_args[@]}" \
    --cap-drop ALL \
    --security-opt "${no_new_privileges}" \
    --env "LAKEKEEPER__PG_DATABASE_URL_WRITE=postgres://lakekeeper:${postgres_password}@no-such-database-host:5432/lakekeeper" \
    --env "LAKEKEEPER__PG_ENCRYPTION_KEY=${encryption_key}" \
    "${image}" migrate >/dev/null
wait_for_exit "${unreachable}"
grep -Eiq 'error communicating with database|database' <<< \
    "$("${runtime}" logs "${unreachable}" 2>&1)"

assert_clean_exit "${arbitrary}"
assert_clean_exit "${primary}"

echo "Rootless restricted-runtime scenario tests passed for ${image}"
