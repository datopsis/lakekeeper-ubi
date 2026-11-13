# Phase A TLS qualification

Phase A encrypts traffic and verifies server identity. It does **not** add
Lakekeeper login: OpenID remains off, with authentication deferred to Phase B.
Keep the unauthenticated catalog on an enforced trusted network, including
during bootstrap. The encryption-key guard remains enabled and unchanged.
TLS does not replace encryption of stored credentials.

Lakekeeper 0.13.4 has **no native TLS listener**. The deployment contract is:

| Connection | Configuration |
| --- | --- |
| Client → catalog | Verified `https://catalog:8181`, terminated by `datopsis/nginx-ubi`. |
| Proxy → Lakekeeper | `http://127.0.0.1:8182` in the **same network namespace**. |
| Metrics | `127.0.0.1:9000`, not published or proxied by this profile. |
| Lakekeeper serve/migrate → PostgreSQL | Both URLs use `sslmode=verify-full` and an explicit `sslrootcert`. |
| Lakekeeper → S3 and STS | `https://s3:8333`, custom root through `SSL_CERT_FILE`; no verification bypass. |

The only Lakekeeper plaintext exception is the loopback backend/metrics inside
its network namespace. An isolated bridge between proxy and backend is **not**
equivalent. The database's container-local Unix socket is used only for explicit
administrator provisioning; all Lakekeeper database connections use verified
TLS. Network peers must not reach either loopback listener. Only the proxy's
8181 listeners may bind non-loopback addresses in the catalog namespace.

## Deploying the proxy pair

Build PostgreSQL using `bash scripts/build-postgres.sh`, which pins
`0ff367fae85d9685eed9d4851dce9203cccae2b2`. Its TLS profile requires both
`POSTGRESQL_TLS_CERT_FILE=/run/tls/server.crt` and
`POSTGRESQL_TLS_KEY_FILE=/run/tls/server.key`, with protected, read-only mounted
files. This selects TLS 1.2/1.3 and `hostssl` SCRAM authentication. Provision the
five extensions and the restricted database-owner role separately using
`examples/postgres-init.sql`, as in the existing development workflow. See the
[pinned database TLS contract](https://github.com/datopsis/postgresql-lakekeeper-ubi/blob/0ff367fae85d9685eed9d4851dce9203cccae2b2/docs/CONFIGURATION.md).

Build nginx with `bash scripts/build-tls-proxy.sh`. It checks out
`9ef9e822c6b5e508cebef2adff3bb647a206773c`, invokes that repository's artifact
acquisition and **Podman build script**, transfers the result into Docker, and
checks architecture, source revision and artifact-lock labels after loading.
It copies the exact upstream `examples/profiles/lakekeeper/nginx.conf` to
`.tls-fixture/nginx.conf`. The wrapper needs Podman, Docker, Git, Python, RPM
tools and GnuPG on a native Linux host. No nginx image with unverified provenance
is substituted. See the [pinned proxy profile](https://github.com/datopsis/nginx-ubi/blob/9ef9e822c6b5e508cebef2adff3bb647a206773c/examples/profiles/lakekeeper/nginx.conf).

Prepare a private, uncommitted runtime environment file from your secret manager:

```text
LAKEKEEPER__BIND_IP=127.0.0.1
LAKEKEEPER__LISTEN_PORT=8182
LAKEKEEPER__METRICS_PORT=9000
LAKEKEEPER__BASE_URI=https://catalog:8181
LAKEKEEPER__PG_DATABASE_URL_WRITE=postgresql://lakekeeper:<URL-encoded-password>@postgres:5432/lakekeeper?sslmode=verify-full&sslrootcert=/trust/pg-ca.crt
LAKEKEEPER__PG_DATABASE_URL_READ=postgresql://lakekeeper:<URL-encoded-password>@postgres:5432/lakekeeper?sslmode=verify-full&sslrootcert=/trust/pg-ca.crt
LAKEKEEPER__PG_ENCRYPTION_KEY=<unique-secret-from-secret-manager>
SSL_CERT_FILE=/trust/storage-ca.crt
```

Replace placeholders; they are not working credentials. Protect this file as a
secret: runtime inspect access can reveal environment values. Omit the READ URL
when there is no separate reader; it falls back to WRITE. Certificates must have
SANs matching the exact endpoint names (`postgres`, `catalog`, `s3` here).
Do not configure OpenID for this Phase A profile.

For Docker, with an existing `lakehouse` network and provisioned TLS PostgreSQL:

```sh
docker run --rm --network lakehouse --user 999:0 --read-only \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --mount "type=bind,src=${TRUST_DIRECTORY},dst=/trust,readonly" \
  --env-file "${CATALOG_ENV_FILE}" "${LAKEKEEPER_IMAGE}" migrate

docker run -d --name catalog --network lakehouse --network-alias catalog \
  --user 999:0 --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --mount "type=bind,src=${TRUST_DIRECTORY},dst=/trust,readonly" \
  --env-file "${CATALOG_ENV_FILE}" "${LAKEKEEPER_IMAGE}" serve

docker run -d --name catalog-proxy --network container:catalog \
  --user 10001:0 --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
  --mount "type=bind,src=${PROXY_PROFILE},dst=/profile/nginx.conf,readonly" \
  --mount "type=bind,src=${CATALOG_TLS_DIRECTORY},dst=/etc/nginx/tls,readonly" \
  localhost/nginx-ubi:tls -c /profile/nginx.conf -g 'daemon off;'
```

Use absolute mount paths. `TRUST_DIRECTORY` contains **public CA certificates
only**. `CATALOG_TLS_DIRECTORY` contains just the proxy's `server.crt` and
`server.key`, with the key readable by its UID/GID (for rootful Docker, root:0
and mode 0440). Never mount a parent directory holding other services' keys or
any CA signing key. The proxy receives no database/object-store credentials or
catalog encryption key. The catalog receives no proxy private key. Preserve the
same separation for PostgreSQL and object storage. Rootless Podman UID mappings
need their own host qualification; these commands demonstrate Docker semantics.

There are no published host ports above. If a trusted client needs host ingress,
publish **only** 8181 on the network-bearing catalog container; the proxy shares
that namespace. Never publish 8182 or 9000. Compose expresses the same relationship
as `network_mode: service:catalog` on the proxy. Recreate the proxy together with
the catalog; a proxy left attached to an old namespace will not follow a replaced
container. Restart/recovery of the full lakehouse belongs to integration item 7.

The proxy overwrites forwarded headers, preserves the request host/path/body,
disables upstream mutation retries, and exposes no HTTP redirect listener.
Clients must trust the issuing CA and use the external HTTPS URI. For example,
from another container on the network:

```sh
curl --fail --cacert /trust/catalog-ca.crt https://catalog:8181/health
```

## PostgreSQL precedence and failures

WRITE selects the writer pool and migrations. READ selects the reader pool;
when absent, the reader uses WRITE. A configured READ URL does not repair an
invalid WRITE URL. Migration does not use READ.

URLs override separate host/user/password/port fields and the separate
`LAKEKEEPER__PG_SSL_MODE`. **Do not rely on that mode variable to secure a URL.**
Put `sslmode=verify-full` in **each** URL. One exception to URL precedence is
`LAKEKEEPER__PG_SSL_ROOT_CERT`: upstream applies it **after** parsing either URL,
overriding the URL's `sslrootcert`. Prefer one explicit source of CA configuration
and leave that override unset when using the URLs above.

The qualification mutates CA trust, hostname SAN and certificate validity with
fresh migrate/serve processes, requiring a nonzero exit and a TLS-specific
diagnostic. A timeout, authentication failure or a generic failed startup is not
accepted as certificate rejection. The server HBA admits no plaintext TCP, and
live pool connections are checked through `pg_stat_ssl`.

## S3 and actual STS

Set these storage-profile values when registering a warehouse:

```json
{
  "type": "s3",
  "bucket": "warehouse",
  "region": "us-east-1",
  "flavor": "s3-compat",
  "endpoint": "https://s3:8333",
  "sts-endpoint": "https://s3:8333",
  "path-style-access": true,
  "sts-enabled": true,
  "sts-role-arn": "arn:aws:iam::000000000000:role/lakekeeper-vended"
}
```

The example role must be provisioned at the object store with its own trust and
permission policies; it is not an existing AWS account or role. Supply storage
credentials through the API at runtime. Mount the issuing root and set
`SSL_CERT_FILE` **before** Lakekeeper starts; the shared Rust SDK client caches
its trust configuration. Do not assume `AWS_CA_BUNDLE` configures this client.
S3 object locations remain `s3://...`; the endpoint controls HTTPS transport.

The isolated qualification enables STS so Lakekeeper's table credentials API
makes a real authenticated AssumeRole call. It verifies the returned session by
reading actual metadata over HTTPS with the vended credentials. It does not
change the integration harness's static-credential policy. STS authorization,
token expiry, rotation and tenant isolation remain separate qualifications.

The fixture uses upstream SeaweedFS **4.53_large_disk**, multi-architecture digest
`sha256:c272ca3b913a8d9f8f843d42553874f70d41ae0611a1bf8e28d80a7da72d7d51`, the
upstream input recorded by datopsis/seaweedfs-ubi main at
`fd9b0001ee86a432faf773d40ab6f528dbfdad67`. S3 and STS share native HTTPS on 8333
with a per-run CA. No second HTTP port is enabled. This proves Lakekeeper's
outbound clients, **not** Seaweed's complete inter-service TLS/mTLS design;
dispatch item 2 owns that qualification. This fixture's internal control plane
is not a deployment example or evidence of completion of Phase A as a whole.

## Evidence and scope

Each native `image (amd64)` and `image (arm64)` job runs `tests/tls_profile.py`
after the existing smoke/storage regressions and the pinned proxy build.
`tests/tls_policy.py` scans the executable Phase A surface for verification
downgrades and parses the fetched proxy directives. The harness parses all
ordinary database URLs and inspects runtime hardening and listener inventories.

`tls-<commit>-<architecture>` retains `tls-report.json`: exact image identities,
public certificate fingerprints/SANs/dates and individual assertion results.
`complete: false` is a failure, never a passing exemption. A fresh valid control
surrounds each outbound certificate mutation. Missing and wrong roots are tested
separately on S3 metadata reads and on the credentials endpoint's real STS path.
Wrong-root server leaves, correct-CN/wrong-SAN leaves and expired leaves are also
tested. No private keys, credentials, raw response bodies or unsanitized logs
are uploaded. All keys and credentials are generated per run and destroyed.

The existing `compose.yaml` and legacy smoke/storage fixtures are isolated
plaintext regression examples, **not** the Phase A profile. Their checks remain
in place, including the encryption-key guard and independent engine round trip.
Neither a green legacy test nor a source inspection establishes TLS success.
Use the exact PR workflow manifests and logs for architecture-specific results.
No production-support, FIPS, rootless-host, or whole-lakehouse TLS claim follows
from this focused Docker qualification.
