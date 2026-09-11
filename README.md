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
- Required external dependency: PostgreSQL 15 or newer

Lakekeeper is below version `1.0.0`. A `0.x` minor increment may introduce
breaking API, configuration, or database-schema changes, so this project treats
every upstream minor increment as a qualification event rather than a routine
dependency bump. See [versioning and releases](docs/VERSION.md).

## Intended uses

The first release is being designed for:

- serving the Apache Iceberg REST catalog API to query engines;
- managing warehouse, namespace, and table metadata in PostgreSQL;
- running schema migrations as a separate, auditable step;
- exposing health and metrics endpoints for operations; and
- operating inside controlled networks with inspectable evidence.

Warehouse storage profiles, OIDC authentication, OpenFGA authorization, Kafka
and NATS event publishing, and the Vault secrets backend are **not** in the
first-release boundary. They may be evaluated later without expanding the
default image's trusted computing base. See
[the roadmap](docs/ROADMAP.md#deferred-from-the-first-release).

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
missing or whitespace-only key stops the container before Lakekeeper starts,
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

Two limits worth stating plainly: the guard checks that a key is **present**,
not that it is strong or secret; and it cannot help a catalog that already ran
without one, because credentials stored during that period were encrypted with
the default key and adding a key later does not re-encrypt them.

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
  gates. It is forward-looking; completed work belongs in the changelog and Git
  history.
- [Versioning and releases](docs/VERSION.md) separates container artifact
  versions from repository-only revisions and defines the pre-1.0 upgrade
  policy.
- [External artifact acquisition](docs/ARTIFACT-ACQUISITION.md) defines the
  lock, verification, and hermetic assembly contract, and states the upstream
  trust limitation.
- [Configuration](docs/CONFIGURATION.md) documents the variables this image
  adds, the fail-closed encryption-key guard, and what that guard does not do.
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

To see the admission gate reject tampered inputs:

```console
bash tests/acquisition.sh
```

To confirm the assembled image can actually satisfy the binary, including the
name-resolution modules glibc loads with `dlopen` and the TLS trust bundle:

```console
CONTAINER_RUNTIME=podman IMAGE=localhost/lakekeeper-ubi9:development \
  bash tests/runtime-dependencies.sh
```

The smoke suite starts its own PostgreSQL fixture, generates credentials per
run, exercises migration, the restricted runtime, the catalog and management
endpoints, secret non-disclosure, and the negative startup cases, then removes
everything it created.

A Compose development stack is also provided. It has not yet been exercised in
CI or in the reference contributor environment, which has no Compose provider
installed, so treat it as unverified until that gap is closed. The smoke suite
above is the canonical verified path. To use it, first create a local `.env`;
no credential has a default value:

```console
cat > .env <<'ENVIRONMENT'
POSTGRES_PASSWORD=replace-with-a-unique-value
LAKEKEEPER__PG_ENCRYPTION_KEY=replace-with-a-unique-value
ENVIRONMENT
podman compose up --build
curl --fail http://127.0.0.1:8181/health
```

`.env` is ignored by Git. Generate both values with a password manager or
`openssl rand -base64 32`; do not reuse an example value.

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
