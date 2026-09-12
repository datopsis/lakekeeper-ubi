#!/usr/bin/env bash
# Qualify S3-compatible warehouse storage against SeaweedFS.
#
# The smoke suite proves the server starts and answers. This proves the thing
# is actually a catalog: that it registers a warehouse, creates namespaces and
# tables, writes their metadata to object storage, and reads them back.
#
# It is also the first test that exercises the secret encryption key against a
# credential that exists. Until a warehouse is registered, nothing has ever
# been encrypted with that key, so the fail-closed guard protects a code path
# no test had used.
set -Eeuo pipefail

runtime="${CONTAINER_RUNTIME:-podman}"
image="${IMAGE:-localhost/lakekeeper-ubi9:development}"
postgres_image="${POSTGRES_IMAGE:-docker.io/library/postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73}"
seaweedfs_image="${SEAWEEDFS_IMAGE:-docker.io/chrislusf/seaweedfs:3.97@sha256:bb05d66d2963b1cc48073190781c3dd29e2c4c88a2ae2986bf58e38c86d89c6e}"
# An independent Iceberg implementation. The catalog agreeing with itself
# proves less than an engine written by somebody else agreeing with it.
engine_image="${ENGINE_IMAGE:-docker.io/library/python:3.13-slim}"
pyiceberg_version="${PYICEBERG_VERSION:-0.12.0}"
pyarrow_version="${PYARROW_VERSION:-25.0.1}"

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
prefix="lakekeeper-ubi9-storage-${RANDOM}-$$"
network="${prefix}-net"
database="${prefix}-db"
storage="${prefix}-s3"
catalog="${prefix}-catalog"
bucket="warehouse"

no_new_privileges="no-new-privileges:true"
readonly_runtime_args=(--read-only)

if grep -qi podman <<< "$("${runtime}" --version 2>&1)"; then
    readonly_runtime_args+=(--read-only-tmpfs=false)
    no_new_privileges="no-new-privileges"
fi

# Every credential is generated per run. None is committed, and none is reused.
postgres_password="$(head -c 24 /dev/urandom | base64 | tr -d '=+/[:space:]')"
encryption_key="$(head -c 24 /dev/urandom | base64 | tr -d '=+/[:space:]')"
access_key_id="$(head -c 12 /dev/urandom | base64 | tr -d '=+/[:space:]')"
secret_access_key="$(head -c 24 /dev/urandom | base64 | tr -d '=+/[:space:]')"
database_url="postgres://lakekeeper:${postgres_password}@${database}:5432/lakekeeper"

cleanup() {
    "${runtime}" rm --force "${catalog}" "${storage}" "${database}" >/dev/null 2>&1 || true
    "${runtime}" network rm --force "${network}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

seaweed_shell() {
    "${runtime}" exec -i "${storage}" weed shell -master=localhost:9333 2>/dev/null
}

api() {
    local method="$1"
    local path="$2"
    shift 2
    curl --silent --show-error --request "${method}" "${base_url}${path}" "$@"
}

start_catalog() {
    "${runtime}" run --detach --name "${catalog}" \
        --network "${network}" \
        "${readonly_runtime_args[@]}" \
        --cap-drop ALL \
        --security-opt "${no_new_privileges}" \
        --publish 127.0.0.1::8181 \
        --env "LAKEKEEPER__PG_DATABASE_URL_WRITE=${database_url}" \
        --env "LAKEKEEPER__PG_ENCRYPTION_KEY=${encryption_key}" \
        "${image}" serve >/dev/null
}

wait_for_catalog() {
    local _
    for _ in {1..60}; do
        if "${runtime}" exec "${catalog}" lakekeeper healthcheck -s >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    "${runtime}" logs "${catalog}" >&2
    echo "the catalog never became healthy" >&2
    return 1
}

"${runtime}" network create "${network}" >/dev/null

# SeaweedFS reads its S3 identities from a config file. The credentials are
# written inside the container so they never reach a committed file.
"${runtime}" run --detach --name "${storage}" \
    --network "${network}" \
    --entrypoint sh \
    "${seaweedfs_image}" -c "
cat > /tmp/s3.json <<'IDENTITIES'
{\"identities\":[{\"name\":\"lakekeeper\",\"credentials\":[{\"accessKey\":\"${access_key_id}\",\"secretKey\":\"${secret_access_key}\"}],\"actions\":[\"Admin\",\"Read\",\"Write\",\"List\",\"Tagging\"]}]}
IDENTITIES
mkdir -p /data
exec weed server -dir=/data -s3 -s3.port=8333 -s3.config=/tmp/s3.json
" >/dev/null

# SeaweedFS auto-creates a plain directory on the first PUT, and that directory
# is not a registered bucket: later metadata lookups fail and HEAD returns
# NotFound, which surfaces as an unhelpful validation error from the catalog.
# The bucket must exist as a bucket before anything writes to it.
bucket_registered="no"
for _ in {1..90}; do
    printf 's3.bucket.create -name %s\n' "${bucket}" | seaweed_shell >/dev/null || true
    if printf 's3.bucket.list\n' | seaweed_shell \
        | grep -qE "(^|[[:space:]])${bucket}[[:space:]]"; then
        bucket_registered="yes"
        break
    fi
    sleep 1
done
test "${bucket_registered}" = "yes" \
    || { echo "the object store never registered the ${bucket} bucket" >&2; exit 1; }

"${runtime}" run --detach --name "${database}" \
    --network "${network}" \
    --env POSTGRES_USER=lakekeeper \
    --env POSTGRES_DB=lakekeeper \
    --env "POSTGRES_PASSWORD=${postgres_password}" \
    "${postgres_image}" >/dev/null
for _ in {1..60}; do
    if "${runtime}" exec "${database}" \
        pg_isready --username lakekeeper --dbname lakekeeper >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

"${runtime}" run --rm \
    --network "${network}" \
    "${readonly_runtime_args[@]}" \
    --cap-drop ALL \
    --security-opt "${no_new_privileges}" \
    --env "LAKEKEEPER__PG_DATABASE_URL_WRITE=${database_url}" \
    --env "LAKEKEEPER__PG_ENCRYPTION_KEY=${encryption_key}" \
    "${image}" migrate >/dev/null

start_catalog
wait_for_catalog
binding="$("${runtime}" port "${catalog}" 8181/tcp)"
base_url="http://127.0.0.1:${binding##*:}"

# A new catalog is open for bootstrap, which sets the initial administrator.
test "$(api POST /management/v1/bootstrap \
    --header 'content-type: application/json' \
    --data '{"accept-terms-of-use":true}' \
    --output /dev/null --write-out '%{http_code}')" = "204"

storage_profile="{\"type\":\"s3\",\"bucket\":\"${bucket}\",\"region\":\"local\",\"sts-enabled\":false,\"flavor\":\"s3-compat\",\"endpoint\":\"http://${storage}:8333\",\"path-style-access\":true}"

# Registering a warehouse with credentials the object store will reject must
# fail. Validation that accepts anything proves nothing about the ones it
# accepts.
rejected_status="$(api POST /management/v1/warehouse \
    --header 'content-type: application/json' \
    --data "{\"warehouse-name\":\"rejected\",\"storage-profile\":${storage_profile},\"storage-credential\":{\"type\":\"s3\",\"credential-type\":\"access-key\",\"access-key-id\":\"wrong\",\"secret-access-key\":\"wrong\"}}" \
    --output /dev/null --write-out '%{http_code}')"
case "${rejected_status}" in
    200 | 201)
        echo "the catalog accepted a warehouse with invalid storage credentials" >&2
        exit 1
        ;;
esac

warehouse_response="$(api POST /management/v1/warehouse \
    --header 'content-type: application/json' \
    --data "{\"warehouse-name\":\"qualification\",\"storage-profile\":${storage_profile},\"storage-credential\":{\"type\":\"s3\",\"credential-type\":\"access-key\",\"access-key-id\":\"${access_key_id}\",\"secret-access-key\":\"${secret_access_key}\"}}")"
warehouse_id="$(python3 -c '
import json
import sys

print(json.load(sys.stdin).get("warehouse-id", ""))
' <<< "${warehouse_response}")"
test -n "${warehouse_id}" \
    || { echo "warehouse registration failed: ${warehouse_response}" >&2; exit 1; }
echo "ok: registered a warehouse backed by S3-compatible storage"

catalog_path="/catalog/v1/${warehouse_id}"

test "$(api POST "${catalog_path}/namespaces" \
    --header 'content-type: application/json' \
    --data '{"namespace":["qualification"]}' \
    --output /dev/null --write-out '%{http_code}')" = "200"

table_schema='{"type":"struct","schema-id":0,"fields":[{"id":1,"name":"id","required":true,"type":"long"},{"id":2,"name":"label","required":false,"type":"string"}]}'
create_response="$(api POST "${catalog_path}/namespaces/qualification/tables" \
    --header 'content-type: application/json' \
    --data "{\"name\":\"measurements\",\"schema\":${table_schema}}")"

metadata_location="$(python3 -c '
import json
import sys

print(json.load(sys.stdin).get("metadata-location", ""))
' <<< "${create_response}")"

# The table is only real if its metadata went to object storage.
grep -q "^s3://${bucket}/" <<< "${metadata_location}" \
    || { echo "table metadata was not written to S3: ${metadata_location}" >&2; exit 1; }
echo "ok: created a table whose metadata lives at ${metadata_location}"

# Reading it back proves the catalog can resolve what it wrote.
loaded="$(api GET "${catalog_path}/namespaces/qualification/tables/measurements")"
python3 -c '
import json
import sys

loaded = json.load(sys.stdin)
metadata = loaded.get("metadata", {})
schemas = metadata.get("schemas") or []
fields = [field["name"] for field in (schemas[0].get("fields", []) if schemas else [])]
if fields != ["id", "label"]:
    raise SystemExit(f"loaded table has unexpected fields: {fields}")
if not metadata.get("table-uuid"):
    raise SystemExit("loaded table has no uuid")
' <<< "${loaded}"
echo "ok: loaded the table back with its schema intact"

# The objects must exist in the object store, not merely be referenced by the
# catalog's own database. Assert the exact prefix the catalog says it wrote,
# so a catalog that recorded a location it never created would fail here.
storage_prefix="${metadata_location#s3://"${bucket}"/}"
storage_prefix="${storage_prefix%%/*}"
object_listing="$(printf 'ls -l /buckets/%s\n' "${bucket}" | seaweed_shell || true)"
grep -Fq "${storage_prefix}" <<< "${object_listing}" \
    || {
        printf '%s\n' "${object_listing}" >&2
        echo "the object store has no ${storage_prefix} prefix under ${bucket}" >&2
        exit 1
    }
echo "ok: the object store holds the table prefix ${storage_prefix}"

# The storage credential must not be readable from the database. A full dump is
# used rather than one table, because a secret that leaks into an audit trail or
# an unexpected column is still a leak.
dump="$("${runtime}" exec "${database}" \
    pg_dump --username lakekeeper --dbname lakekeeper 2>/dev/null)"
if grep -Fq "${secret_access_key}" <<< "${dump}"; then
    echo "the storage secret is readable in plaintext in the database" >&2
    exit 1
fi
echo "ok: the storage secret is not readable in the database"

# Restarting proves the credential survives a decrypt, not just an encrypt.
# Creating a table after the restart requires the catalog to decrypt the stored
# credential and use it against the object store.
"${runtime}" restart "${catalog}" >/dev/null
wait_for_catalog
binding="$("${runtime}" port "${catalog}" 8181/tcp)"
base_url="http://127.0.0.1:${binding##*:}"

test "$(api GET "${catalog_path}/namespaces/qualification/tables/measurements" \
    --output /dev/null --write-out '%{http_code}')" = "200"

test "$(api POST "${catalog_path}/namespaces/qualification/tables" \
    --header 'content-type: application/json' \
    --data "{\"name\":\"after_restart\",\"schema\":${table_schema}}" \
    --output /dev/null --write-out '%{http_code}')" = "200"
echo "ok: the stored credential still decrypts and works after a restart"

# Dropping is part of the lifecycle, and a catalog that cannot drop a table
# leaves storage to grow without bound.
test "$(api DELETE "${catalog_path}/namespaces/qualification/tables/after_restart" \
    --output /dev/null --write-out '%{http_code}')" = "204"
echo "ok: dropped a table"

# Everything so far has spoken to the catalog's own API, which proves the
# catalog agrees with itself. A query engine is an independent implementation
# of the specification, and it is what an operator will actually point at this.
#
# The round trip crosses both stores: rows become Parquet files in object
# storage, while the commit that makes them visible is recorded in PostgreSQL.
# Reading them back therefore depends on both, and on them agreeing.
# The pip command's variables expand in the engine container, not here.
# shellcheck disable=SC2016
run_engine() {
    local mode="$1"
    "${runtime}" run --rm \
        --network "${network}" \
        --volume "${repository_root}/tests/data:/work:ro" \
        --env "CATALOG_URI=http://${catalog}:8181/catalog" \
        --env "WAREHOUSE=qualification" \
        --env "S3_ENDPOINT=http://${storage}:8333" \
        --env "S3_ACCESS_KEY_ID=${access_key_id}" \
        --env "S3_SECRET_ACCESS_KEY=${secret_access_key}" \
        --env "PIP_DISABLE_PIP_VERSION_CHECK=1" \
        --env "PIP_ROOT_USER_ACTION=ignore" \
        --env "PYICEBERG_VERSION=${pyiceberg_version}" \
        --env "PYARROW_VERSION=${pyarrow_version}" \
        --env "MODE=${mode}" \
        "${engine_image}" \
        sh -eu -c 'pip install --quiet --no-input "pyiceberg[s3fs,pyarrow]==${PYICEBERG_VERSION}" "pyarrow==${PYARROW_VERSION}" >/dev/null && exec python /work/roundtrip.py "${MODE}"'
}

engine_output="$(run_engine write)"
printf '%s\n' "${engine_output}"
grep -q "rows round-tripped through PyIceberg" <<< "${engine_output}" \
    || { echo "the engine did not round-trip rows" >&2; exit 1; }
echo "ok: a query engine wrote and read real rows"

# The rows must be Parquet files in the object store, not only a catalog answer.
engine_data_file="$(grep -m1 '^data-file=' <<< "${engine_output}" | cut -d= -f2-)"
test -n "${engine_data_file}" \
    || { echo "the engine reported no data files" >&2; exit 1; }
data_prefix="${engine_data_file#s3://"${bucket}"/}"
data_prefix="${data_prefix%%/*}"
data_listing="$(printf 'ls -l /buckets/%s\n' "${bucket}" | seaweed_shell || true)"
grep -Fq "${data_prefix}" <<< "${data_listing}" \
    || { echo "the object store has no ${data_prefix} prefix for the written rows" >&2; exit 1; }
echo "ok: the written rows are Parquet files in the object store"

# The commit lives in PostgreSQL. Restarting the catalog drops every in-memory
# cache, so reading the same rows afterwards proves the catalog state was
# durable in the database rather than remembered by the process.
"${runtime}" restart "${catalog}" >/dev/null
wait_for_catalog
binding="$("${runtime}" port "${catalog}" 8181/tcp)"
base_url="http://127.0.0.1:${binding##*:}"

reread_output="$(run_engine read)"
grep -q "rows round-tripped through PyIceberg" <<< "${reread_output}" \
    || { echo "the rows did not survive a catalog restart" >&2; exit 1; }
echo "ok: the rows survived a catalog restart, so the commit was durable in PostgreSQL"

# Nothing above may have written a secret to the logs.
catalog_logs="$("${runtime}" logs "${catalog}" 2>&1)"
if grep -Fq "${secret_access_key}" <<< "${catalog_logs}" \
    || grep -Fq "${encryption_key}" <<< "${catalog_logs}" \
    || grep -Fq "${postgres_password}" <<< "${catalog_logs}"; then
    echo "a secret value appeared in the catalog logs" >&2
    exit 1
fi

echo "S3-compatible warehouse storage qualified for ${image}"
