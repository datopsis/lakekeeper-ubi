# Lakekeeper on Red Hat UBI 9

`lakekeeper-ubi` builds a security-oriented, rootless
[Lakekeeper](https://github.com/lakekeeper/lakekeeper) container: an Apache
Iceberg REST catalog for query engines such as Spark, Trino, DuckDB, PyIceberg,
and ClickHouse. The project is designed for Podman, Docker-compatible runtimes,
OpenShift-style arbitrary user IDs, and controlled networks that require
inspectable security evidence.

> [!IMPORTANT]
> The project is under initial development. No supported container image has
> been released. Commands, tags, and security claims will be published only
> after their implementations are tested and the applicable roadmap gates are
> complete.

## Version baseline

- Repository and image: `lakekeeper-ubi`
- Planned image location: `ghcr.io/datopsis/lakekeeper-ubi`
- Initial Lakekeeper version: `0.13.4`
- Initial UBI major line: `9`
- Tested catalog database: PostgreSQL 18 from
  [datopsis/postgresql-lakekeeper-ubi](https://github.com/datopsis/postgresql-lakekeeper-ubi)
  (upstream Lakekeeper requires PostgreSQL 15 or newer)

Lakekeeper is below version `1.0.0`. A `0.x` minor increment may introduce
breaking API, configuration, or database-schema changes, so this project treats
every upstream minor increment as a qualification event rather than a routine
dependency bump. See [versioning and releases](docs/VERSION.md).

## Intended uses

The first release is being designed for:

- serving the Apache Iceberg REST catalog API to query engines;
- managing warehouse, namespace, and table metadata in PostgreSQL;
- storing table data in S3-compatible object storage;
- running schema migrations as a separate, auditable step;
- exposing health and metrics endpoints for operations; and
- operating inside controlled networks with inspectable evidence.

S3-compatible warehouse storage is in the first-release boundary and is being
qualified against SeaweedFS. OIDC authentication, OpenFGA authorization, Kafka
and NATS event publishing, ADLS, OneLake, GCS, and the Vault secrets backend
are **not**. See [the roadmap](docs/ROADMAP.md#deferred-from-the-first-release).

## Security design

The planned image contract requires:

- a digest-pinned Red Hat UBI 9 base and verified build inputs;
- a package-manager-free UBI 9 Micro final image;
- a non-root Lakekeeper process with no privileged entrypoint phase;
- an unprivileged listener on port `8181` and metrics on `9000`;
- compatibility with an arbitrary non-root UID in group `0`;
- operation with a read-only root filesystem and **no writable mount at all**;
- all Linux capabilities dropped and `no-new-privileges` enabled;
- database credentials, the secret encryption key, and object-store credentials
  supplied at runtime and never baked into the image;
- structured JSON logs written to the container log streams;
- native AMD64 and ARM64 runtime testing;
- vulnerability scanning with Trivy and Grype;
- SPDX software bills of materials generated with Syft;
- tailored OpenSCAP evidence with documented rule selection and exclusions;
- BuildKit provenance and SBOM attestations; and
- digest-bound, keyless Cosign signatures for releases.

These properties do not make the image, host, orchestrator, database, network,
or application automatically secure. Deployment controls, secrets, network
policy, resource limits, monitoring, patching, database backup, and risk
acceptance remain shared responsibilities.

The project will not claim FIPS validation, STIG certification, OpenShift
support, or compliance with an entire control framework without evidence that
matches the exact claim and assessed boundary.

## Operator responsibilities you cannot skip

Three upstream behaviors make the difference between a reasonable deployment
and an insecure one. The image now enforces the first one by default; the
other two remain deployment responsibilities:

1. **Set `LAKEKEEPER__PG_ENCRYPTION_KEY` to a unique value.** Enforced by this
   image by default, as described below.
2. **Do not expose an unauthenticated catalog.** The default authorization
   backend is `allow-all`.
3. **Control reachability until the catalog is bootstrapped.** A new catalog is
   open for bootstrap, which sets the initial administrator.

See [the security policy](SECURITY.md) for the full statement.

## Secret encryption key

`LAKEKEEPER__PG_ENCRYPTION_KEY` protects the storage credentials Lakekeeper
persists in PostgreSQL. This is encryption **at rest**, and it is unrelated to
TLS: Lakekeeper does not terminate TLS at all. When an operator registers a
warehouse they hand the catalog long-lived storage credentials, and this key is
what encrypts them in the database. Its threat model is a reader of the
database, such as a stolen backup or a read replica, which transport security
does nothing about. See [configuration](docs/CONFIGURATION.md#this-is-encryption-at-rest-not-tls).

**Upstream treats it as optional.** If it is unset, Lakekeeper starts normally,
logs one warning, and encrypts stored credentials with a default key published
in the upstream source. Nothing fails. The service reports healthy and query
engines connect. A deployment can run that way for a long time while every
credential it holds is decryptable by anyone who reads public source code.

**This image fails closed by default instead.** When
`LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY` is `true`, which is the default, a
missing key, a whitespace-only key, or a key set to upstream's published
default stops the container before Lakekeeper starts,
with exit status `78` (`EX_CONFIG`) and a diagnostic naming the variable to
set. The key value itself is never printed or logged.

The behavior is configurable, because a silent security default in either
direction is worse than an explicit one:

| `LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY` | Behavior |
| --- | --- |
| `true` (default) | A missing key is a startup failure. |
| `false` | Upstream behavior: the container starts and warns. |

An unrecognized value is also a startup failure, so a misspelled toggle cannot
quietly disable the control. Informational subcommands such as `version` and
`healthcheck` keep working without a key, so a refused container stays
diagnosable.

The default value matters more than it sounds. Upstream warns only when the
variable is *absent*, so setting it to the published default, which is what a
copied example or a chart default produces, generates no warning at all. This
image rejects that value for the same reason it rejects an empty one.

Two limits worth stating plainly: the guard checks presence and rejects one
known-bad value, but does not judge whether a key is strong or secret; and it
cannot help a catalog that already ran without one, because credentials stored
during that period were encrypted with the default key and adding a key later
does not re-encrypt them.

Full details, including the exact command allowlist and the rotation caveat,
are in [configuration](docs/CONFIGURATION.md).

## Rootless runtime model

Lakekeeper starts directly as a non-root identity and does not attempt to repair
volume ownership. The default profile keeps no local state: metadata lives in
PostgreSQL, and the container runs on a fully read-only root filesystem with no
writable mount. The smoke suite asserts this by running the catalog with the
runtime's automatic writable `tmpfs` disabled.

`serve` requires an already-migrated database. Migration is a separate `migrate`
invocation so that a running server is never the component authorized to
rewrite schema.

## Upstream artifact trust

Lakekeeper publishes release tarballs on GitHub **without a detached signature
or a checksum file**. This project therefore records the archive digest, the
extracted binary digest, sizes, and GNU build IDs in
[`artifacts/lakekeeper.lock.json`](artifacts/lakekeeper.lock.json), and a
reviewed change to that lock is the point at which new bytes are admitted.

That proves every build used exactly the reviewed bytes. It does **not**
independently prove publisher identity, and it is weaker than vendor-signed RPM
provenance. The limitation is stated in full in
[external artifact acquisition](docs/ARTIFACT-ACQUISITION.md) and improving it
is a tracked roadmap item.

The locked binaries require at most glibc `2.34` and link only `libc`, `libm`,
`libresolv`, `libgcc_s`, and the dynamic loader, which is why they run on UBI 9
without rebuilding. CI re-measures this on every image build rather than
assuming it holds for a future upstream release.

## Project documentation

- [First-release roadmap](docs/ROADMAP.md) defines outstanding work and release
  gates, and opens with a
  [where to resume](docs/ROADMAP.md#where-to-resume) section covering the next
  task, the decisions that need a human, and the checks owed at every upstream
  version bump. It is forward-looking; completed work belongs in the changelog and Git
  history.
- [Versioning and releases](docs/VERSION.md) separates container artifact
  versions from repository-only revisions and defines the pre-1.0 upgrade
  policy.
- [External artifact acquisition](docs/ARTIFACT-ACQUISITION.md) defines the
  lock, verification, and hermetic assembly contract, and states the upstream
  trust limitation.
- [Configuration](docs/CONFIGURATION.md) documents the variables this image
  adds, the fail-closed encryption-key guard, and what that guard does not do.
- [Phase A TLS](docs/TLS.md) deploys the catalog on loopback behind the pinned
  nginx proxy, with verified PostgreSQL, S3 and STS connections and explicit CA
  mounts. Login stays off; OpenID belongs to Phase B. Native CI retains each TLS
  assertion separately from the existing plaintext regression tests.
  The [qualification record](docs/TLS.md#evidence-and-scope) contains 112 passing
  assertions on each native architecture, with exact CI and artifact links.
- [Hermetic build](docs/HERMETIC-BUILD.md) describes the network-free assembly
  property, its security value, and the controls it does and does not support.
- [FIPS analysis](docs/FIPS.md) records why this image cannot support a FIPS
  claim today, including why running on a FIPS-enabled host does not confer
  one.
- [Container minimization analysis](docs/MINIMIZATION.md) measures where the
  image's size actually is and what each reduction would cost.
- [Continuous integration](docs/CI.md) documents current automation, local
  checks, and the planned image assurance pipeline.
- [Changelog](CHANGELOG.md) records notable completed changes.
- [Contributing](CONTRIBUTING.md) defines change, validation, pull-request, and
  commit expectations.
- [Security policy](SECURITY.md) provides private vulnerability reporting and
  records deployment-critical upstream behavior.
- [Third-party notices](THIRD_PARTY_NOTICES.md) separates this project's license
  from Lakekeeper, UBI, and component terms.
- [Agent guidance](CLAUDE.md) defines repository implementation and security
  conventions.

Support definitions, threat model, security controls, use cases, logging, and
deployment guides will be added as their associated implementations and evidence
are developed.

## Images and releases

The planned image location is:

```text
ghcr.io/datopsis/lakekeeper-ubi
```

Container releases will use annotated tags in this form:

```text
v<lakekeeper-version>-ubi<ubi-major>-r<YYYYMMDD>.<daily-sequence>
```

For example, `v0.13.4-ubi9-r20260910.1` identifies Lakekeeper 0.13.4 on the UBI
9 product line and the first Datopsis container release created on 2026-09-10
UTC. The example is not a published release.

Image releases and repository revisions are deliberately separate. Production
deployments should pin an immutable OCI digest. Mutable tags such as `latest`
are not published.

## Development status

Build and exercise the current development image with rootless Podman on native
Linux or WSL2:

```console
./scripts/build.sh
./scripts/build-postgres.sh
CONTAINER_RUNTIME=podman IMAGE=localhost/lakekeeper-ubi9:development \
  bash tests/check-runtime-requirements.sh
CONTAINER_RUNTIME=podman IMAGE=localhost/lakekeeper-ubi9:development \
  bash tests/smoke.sh
```

`scripts/build.sh` is a convenience wrapper over three separable phases.
A plain `podman build .` will not work, by design: the image cannot be
assembled from unverified inputs.

```console
./scripts/fetch-artifacts.sh     # network: download and verify against the lock
./scripts/fetch-base-images.sh   # network: pull the digest-pinned UBI images
./scripts/build-image.sh         # verify again, then assemble without pulling
```

They are separate because acquisition and assembly have different trust
properties. CI runs them as distinct steps, and a controlled-network transfer
runs acquisition on a connected host and assembly on a disconnected one. The
bundle enters the build as a named build context, so nothing else in the working
tree can reach the image. Verification requires `binutils` for `readelf`; it is
not skipped when the tool is missing.

Both local assembly and CI set `org.opencontainers.image.revision` to this
repository's full `git rev-parse HEAD` commit SHA, overriding the UBI base's
revision. `io.datopsis.artifact-lock.sha256` is the SHA-256 of the exact bytes
of `artifacts/lakekeeper.lock.json` (or the selected `LOCK_FILE`). Like Trino's
lock, this single file covers both architectures, so its digest is the same
for AMD64 and ARM64; it is not a hash of an architecture subsection or bundle.
Build from a Git checkout; commit image inputs before building an image whose
revision must reproduce them. PR CI labels the tested merge commit.

Inspect and verify a locally built image with:

```console
ARCHITECTURE=amd64 CONTAINER_RUNTIME=podman \
  python3 tests/image-provenance.py
```

Use `ARCHITECTURE=arm64` on ARM64 and `IMAGE` to select a different image tag.
The check compares the inspected labels with the checkout and selected lock.

To see the admission gate reject tampered inputs:

```console
bash tests/acquisition.sh
```

To qualify S3-compatible warehouse storage end to end, which starts its own
SeaweedFS and PostgreSQL fixtures and proves the catalog registers a warehouse,
creates and reads a table, writes its metadata to object storage, and keeps the
storage credential encrypted:

```console
CONTAINER_RUNTIME=podman IMAGE=localhost/lakekeeper-ubi9:development \
  bash tests/storage.sh
```

To confirm the assembled image can actually satisfy the binary, including the
name-resolution modules glibc loads with `dlopen` and the TLS trust bundle:

```console
CONTAINER_RUNTIME=podman IMAGE=localhost/lakekeeper-ubi9:development \
  bash tests/runtime-dependencies.sh
```

The smoke and storage suites start their own PostgreSQL 18 fixture from
[datopsis/postgresql-lakekeeper-ubi](https://github.com/datopsis/postgresql-lakekeeper-ubi).
There is no published image: `scripts/build-postgres.sh` fetches the exact SHA in
[`artifacts/postgresql-lakekeeper.commit`](artifacts/postgresql-lakekeeper.commit)
and invokes that repository's `scripts/build-offline.sh` on the native
architecture. Updating that one-line pin is a reviewed dependency change. The
wrapper verifies Git HEAD, the loaded image's revision label, its RPM lock digest,
and its architecture; CI records the image ID and elapsed build time. It needs
Git, Python 3, GnuPG, and Podman (or `CONTAINER_RUNTIME=docker`). Each native CI
image job builds the database before either suite runs.

Both suites default `POSTGRES_IMAGE` to
`localhost/postgresql-lakekeeper-ubi:development`. The override remains available
for compatible builds that provide this image's paths, UID, and init contract.
They generate separate administrator/application credentials per run and mount
0600 secret files owned by UID 26. PostgreSQL runs as `26:0`, with a read-only
root, dropped capabilities, `no-new-privileges`, a writable data volume and a
restricted `/tmp`. Tests remove their containers and volumes afterwards.

Provisioning explicitly runs the image's `/usr/share/lakekeeper/init.sql` as
`postgres`, via the trusted container-local `/tmp` socket, to create `uuid-ossp`,
`pgcrypto`, `pg_trgm`, `btree_gin`, and `btree_gist` in the `lakekeeper` database.
[`examples/postgres-init.sql`](examples/postgres-init.sql) also creates a separate
`lakekeeper` login and makes it the database owner. Both `migrate` and `serve`
connect as that role over SCRAM-authenticated TCP. No superuser, CREATEDB,
CREATEROLE, replication, BYPASSRLS, role membership, or extra grant is supplied.
Both suites assert the exact five add-ons after migration and check that they
remain owned by `postgres` and that the application remains only a database
owner. The smoke suite retains its encryption-key and unmigrated-database
negative cases; storage retains its independent PyIceberg read/write round trip.

A Compose development stack is also provided. Its complete lifecycle remains
unverified; the native CI test scripts are the canonical integration evidence.
Build both images with the commands above first. For an isolated rootless Podman
example, generate unique local credentials (no trailing newlines in secret
files) and the application environment:

```console
install -d -m 700 secrets
(umask 077
 openssl rand -hex 32 | tr -d '\n' > secrets/postgres-password
 openssl rand -hex 32 | tr -d '\n' > secrets/lakekeeper-password
 printf 'POSTGRES_ADMIN_PASSWORD_FILE=./secrets/postgres-password\nPOSTGRES_APP_PASSWORD_FILE=./secrets/lakekeeper-password\nPOSTGRES_PASSWORD=%s\nLAKEKEEPER__PG_ENCRYPTION_KEY=%s\n' \
   "$(cat secrets/lakekeeper-password)" "$(openssl rand -hex 32)" > .env
)
chmod 0440 secrets/postgres-password secrets/lakekeeper-password
podman compose up -d postgres
# Run once against a fresh volume, after PostgreSQL becomes healthy:
podman compose exec -T postgres psql -X --host=/tmp \
  --username=postgres --dbname=lakekeeper < examples/postgres-init.sql
podman compose up -d migrate lakekeeper
curl --fail http://127.0.0.1:8181/health
```

`.env` and `secrets/` are ignored by Git. The application password in `.env`
must match `secrets/lakekeeper-password`; it is separate from the administrator
password. Lakekeeper still receives its database URL and encryption key as
runtime environment values, which container inspect APIs can expose. PostgreSQL
receives only secret-file paths. Protect both sources accordingly.

Secret files inside PostgreSQL must be owned by UID 0 or 26, with mode 0400/0600,
or mode 0440/0640 with GID 0. Rootless Podman normally maps the invoking user's
UID/GID to container `0:0`; verify mappings on your host. For rootful Docker,
prepare the two files as host `0:0`, mode 0440. File-backed Compose secrets can
preserve host metadata rather than applying a requested mode. Follow the database
image's [credential and TLS guidance](https://github.com/datopsis/postgresql-lakekeeper-ubi/blob/main/docs/CONFIGURATION.md)
for your runtime. This example uses an isolated development network without TLS;
it is not a production deployment or a PostgreSQL major-version upgrade path.
Use a fresh volume: the former PostgreSQL 17 data directory cannot be reused by
PostgreSQL 18. The init SQL deliberately refuses to recreate an existing role;
it is explicit provisioning, not an automatic startup hook.

Repository checks can be run with:

```console
python -m pip install --require-hashes --only-binary=:all: \
  --requirement .github/requirements/pre-commit.txt
pre-commit run --all-files --show-diff-on-failure
```

CI supplies the canonical Linux shell execution and native architecture
evidence. See the [continuous integration guide](docs/CI.md). Until the first
signed release is published, this repository should be treated as development
material rather than a supported production image.

Security concerns must not be disclosed in a public issue. Follow the private
process in [SECURITY.md](SECURITY.md).

## License

Datopsis-authored packaging code and documentation are licensed under the
[Apache License 2.0](LICENSE). Lakekeeper, Red Hat UBI, and installed components
retain their respective licenses and terms; see
[third-party software and terms](THIRD_PARTY_NOTICES.md).
