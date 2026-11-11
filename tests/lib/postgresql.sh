#!/usr/bin/env bash
# Shared fixture for smoke/storage. The caller owns its network and cleanup trap.

# Refuse an incomplete caller contract before creating any fixture resources.
: "${runtime:?}" "${prefix:?}" "${postgres_password:?}" "${postgres_image:?}"
: "${readonly_runtime_args[*]:?}" "${no_new_privileges:?}"
: "${database:?}" "${network:?}" "${repository_root:?}"

start_postgres() {
    local admin_password
    local ready=no
    local _
    admin_password="$(head -c 24 /dev/urandom | base64 | tr -d '=+/[:space:]')"
    "${runtime}" volume create "${prefix}-pg-secrets" >/dev/null
    "${runtime}" volume create "${prefix}-pg-data" >/dev/null

    # Write secret files as UID 26 through stdin, not argv/environment. A named
    # volume preserves ownership on Docker and rootless Podman without sudo.
    # Variables inside this shell expand only in the container.
    # shellcheck disable=SC2016
    printf '%s\n%s\n' "${admin_password}" "${postgres_password}" | \
        "${runtime}" run --rm --name "${prefix}-pg-secrets-init" \
            --network none --user 26:0 "${readonly_runtime_args[@]}" \
            --cap-drop ALL --security-opt "${no_new_privileges}" \
            --volume "${prefix}-pg-secrets:/var/lib/pgsql" \
            --interactive "${postgres_image}" sh -eu -c '
                umask 077
                IFS= read -r admin
                IFS= read -r application
                printf %s "${admin}" > /var/lib/pgsql/postgres-password
                printf %s "${application}" > /var/lib/pgsql/lakekeeper-password
            '
    "${runtime}" run --detach --name "${database}" \
        --network "${network}" --user 26:0 \
        "${readonly_runtime_args[@]}" \
        --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
        --cap-drop ALL --security-opt "${no_new_privileges}" \
        --volume "${prefix}-pg-data:/var/lib/pgsql" \
        --volume "${prefix}-pg-secrets:/run/secrets:ro" \
        --env POSTGRES_USER=postgres --env POSTGRES_DB=lakekeeper \
        --env POSTGRES_PASSWORD_FILE=/run/secrets/postgres-password \
        "${postgres_image}" >/dev/null
    # TCP is available only after the temporary init server has stopped.
    for _ in {1..60}; do
        if "${runtime}" exec "${database}" pg_isready --host=127.0.0.1 \
            --username=postgres --dbname=lakekeeper >/dev/null 2>&1; then
            ready=yes
            break
        fi
        sleep 1
    done
    if test "${ready}" != yes; then
        "${runtime}" logs "${database}" >&2
        echo 'The PostgreSQL fixture never became ready' >&2
        return 1
    fi
    test "$("${runtime}" exec "${database}" id -u)" = 26
    "${runtime}" exec "${database}" sh -eu -c '
        grep -Eq "^Uid:[[:space:]]+26[[:space:]]+26[[:space:]]+26[[:space:]]+26$" /proc/1/status
        grep -Eq "^CapEff:[[:space:]]+0000000000000000$" /proc/1/status
        grep -Eq "^NoNewPrivs:[[:space:]]+1$" /proc/1/status
        ! (printf probe > /root-filesystem-probe) >/dev/null 2>&1
    '
    "${runtime}" exec --interactive "${database}" \
        psql -X --host=/tmp --username=postgres --dbname=lakekeeper \
        < "${repository_root}/examples/postgres-init.sql" >/dev/null
}

assert_postgres_contract() {
    local extensions role
    extensions="$("${runtime}" exec "${database}" \
        psql -XAt --set=ON_ERROR_STOP=1 --host=/tmp --username=lakekeeper --dbname=lakekeeper \
        --command "SELECT string_agg(extname, ',' ORDER BY extname) FROM pg_extension WHERE extname <> 'plpgsql';")"
    test "${extensions}" = 'btree_gin,btree_gist,pg_trgm,pgcrypto,uuid-ossp'
    role="$("${runtime}" exec "${database}" \
        psql -XAt --set=ON_ERROR_STOP=1 --host=/tmp --username=lakekeeper --dbname=lakekeeper \
        --command "SELECT NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
            AND (SELECT pg_get_userbyid(datdba) = current_user FROM pg_database WHERE datname = current_database())
            AND NOT EXISTS (SELECT FROM pg_auth_members WHERE member = pg_roles.oid)
            AND NOT EXISTS (SELECT FROM pg_extension WHERE extname <> 'plpgsql' AND pg_get_userbyid(extowner) <> 'postgres')
            FROM pg_roles WHERE rolname = current_user;")"
    test "${role}" = t
    echo 'ok: all five extensions exist, owned by postgres; lakekeeper is only a database owner'
}

cleanup_postgres() {
    "${runtime}" rm --force "${prefix}-pg-secrets-init" >/dev/null 2>&1 || true
    "${runtime}" volume rm "${prefix}-pg-data" "${prefix}-pg-secrets" >/dev/null 2>&1 || true
}
