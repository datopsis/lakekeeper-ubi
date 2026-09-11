# First-release roadmap

This roadmap is the release gate for the first supported `lakekeeper-ubi`
image. The immediate objective is a small, usable rootless Apache Iceberg REST
catalog image without postponing controls that are difficult to retrofit
safely.

A checked item requires reviewable evidence in a pull request, workflow run,
release asset, or qualification record. Automated success is not sufficient
where an item requires human analysis, an external environment, or a support
decision.

## Evidence lifecycle

Evidence has three levels:

1. **Development evidence** comes from a proposed revision or pull request.
2. **Integration evidence** comes from the exact revision merged to `main`.
3. **Release-candidate evidence** is regenerated after the final
   image-affecting change and bound to the candidate commit, image digest,
   architecture, configuration profile, scanner inputs, and platform versions.

Changing the Lakekeeper or UBI inputs, image contents, default configuration,
entrypoint, scanner content, SCAP tailoring, or qualification procedure
invalidates the affected release-candidate evidence.

## Working first-release boundary

These are initial positions, not support claims, until qualification closes the
corresponding gates.

| Area | Working first-release position |
| --- | --- |
| Architectures | Support native `linux/amd64` and `linux/arm64`. |
| Primary runtime | Qualify a documented rootless Podman version on an exact Red Hat host baseline. |
| Docker | Retain compatibility evidence without implying the same production-support boundary as Podman. |
| OpenShift | Test restricted-SCC arbitrary-UID operation; call it preview until an exact cluster release is qualified. |
| Catalog backend | PostgreSQL 15 or newer only. The Vault KV v2 secrets backend is out of scope. |
| Core uses | Iceberg REST catalog API, management API, health and metrics endpoints, and database migration, all against an operator-managed PostgreSQL instance. |
| Authorization | `allow-all` only, with the boundary stated explicitly. OpenFGA is out of scope. |
| Authentication | Out of scope for a qualified profile; OIDC is documented as preview at most. |
| Warehouse storage | Out of scope for a qualified profile. |
| TLS | Terminated outside the image. Lakekeeper does not terminate TLS, so a deployment needs a reverse proxy or ingress in front of it. |
| Controlled networks | Document connected build, artifact transfer, digest verification, mirrored deployment, local trust, logging, and update procedures. |
| FIPS | Make no FIPS validation claim without a separately defined and evidenced cryptographic boundary. |
| STIG/SCAP | Publish exact tailored image-filesystem results; make no STIG certification claim. |
| Registry | Publish the first release to GHCR. |

Warehouse storage profiles, authentication, authorization, and event publishing
are deferred as described under "Deferred from the first release". They must not
delay the core first release, and the first release must state plainly that a
catalog deployed without authentication and authorization is only appropriate
on a trusted network.

## Immediate first-release sequence

Work proceeds in this dependency order:

1. Resolve the secret-encryption-key failure mode, because it changes the
   image contract.
2. Implement out-of-build artifact acquisition and network-disabled assembly
   driven by the reviewed lock.
3. Close the runtime test matrix: database fixtures, negative configuration
   cases, arbitrary UID, and graceful lifecycle.
4. Qualify the minimum catalog profile needed for the first supported image.
5. Complete the repository policy files, support boundary, threat model,
   requirement analysis, control ownership, vulnerability policy, tailored
   SCAP evidence, and deployment cyber package needed for review.
6. Qualify standalone rootless Podman/Quadlet deployment with an external
   PostgreSQL instance, systemd lifecycle, journald collection,
   controlled-network operation, and rollback on an exact supported host.
7. Rehearse the multi-architecture publish, provenance, SBOM, signing, and
   verification workflow from an untagged release candidate.
8. Freeze inputs, regenerate release-candidate evidence, approve findings,
   create the immutable tag, publish by digest, and verify the release.

## Package 1: secret and configuration failure modes

The encryption-key decision is made and implemented: the image fails closed by
default, with a documented opt-out. See `docs/CONFIGURATION.md`. The items
below are what remains.

- [ ] Inventory every other configuration value whose absence degrades security
  rather than failing, and classify each one as image-enforced,
  deployment-enforced, or accepted with rationale. The encryption key was the
  first such value found, not necessarily the only one.
- [ ] Decide whether the guard should also reject a key that matches the known
  upstream default value, and whether to require a minimum length or entropy.
  It currently checks presence only, which is deliberate but weak.
- [ ] Document the encryption-key rotation procedure. Rotation is a data
  operation, not a restart, because existing rows were encrypted with the
  previous key. Until this is written and tested, `docs/CONFIGURATION.md` must
  keep telling operators not to assume otherwise.
- [ ] Verify that the encryption key, database password, and object-store
  credentials never appear in logs, error responses, the management API, or
  image layers. The smoke suite covers container logs; the other surfaces are
  not yet covered.
- [ ] Investigate the observation that `wait-for-db` exited `0` against an
  unresolvable database host. If confirmed, document that it must not be used
  as a readiness gate and report it upstream.

## Package 2: artifact acquisition and hermetic assembly

The goal is that assembly consumes only reviewed local bytes, with the build
running under `--network=none`. Two measurements shape how that is reached.

**The builder makes two network calls, not one.** It downloads the release
archive, and it runs `dnf --installroot` against the Red Hat CDN. Removing only
the first does not make the build hermetic.

**Stock UBI 9 Micro already provides the entire shared-library closure** the
binary needs: `libc`, `libm`, `libresolv`, `libgcc_s`, and the loader. Because
`--installroot` targets an empty root, `dnf` currently resolves and installs a
full base system of roughly three dozen packages, nearly all of which the final
stage already has. The genuine delta is `ca-certificates` and `tzdata`, plus the
trust chain the former requires.

That reduces the hardest part of this package from locking a full RPM closure to
locking a small, reviewable set.

### 2a: take the release archive out of the build

Implemented. The build no longer downloads the Lakekeeper binary:
`scripts/fetch-artifacts.sh` acquires and verifies it, `scripts/verify-bundle.sh`
re-checks it immediately before assembly, and the binary enters through a named
build context. `tests/acquisition.sh` proves the gate rejects a tampered binary,
a truncated binary, an extra file, a missing binary, a missing manifest, a
bundle left over from an older lock, and a lock whose recorded ELF facts drift
from the bytes it names. The Containerfile is checked for the absence of a
fetch.

- [ ] Fetch and verify both architectures in one place so the architecture
  confusion case in `tests/acquisition.sh` stops being skipped. Each CI runner
  currently fetches only its own architecture, so that case never executes.
- [ ] Decide whether a release build should require a second, independent
  verification of the bundle by a different implementation, rather than the same
  script twice.

### 2b: take the RPMs out of the build

Implemented. Assembly now runs with `--network=none` and `--pull=never`. The
runtime package delta is resolved against the UBI Micro RPM database rather
than an empty root, so it is 12 packages instead of a duplicated base system.
`scripts/update-rpm-lock.sh` regenerates the manifest as a reviewable change,
`scripts/fetch-artifacts.sh` acquires and digest-verifies the packages, and the
build installs them with no repository and no dependency resolution, checking
Red Hat signatures against the keys already in the Micro database. The
Containerfile is checked for the absence of any fetch or package resolution.

Two findings came out of it and are recorded because they are not obvious:

- **UBI Micro's RPM database does not describe its filesystem.** It records
  `tzdata` as installed, owning 1872 files, while shipping none of them. This
  image therefore reinstalls `tzdata` deliberately. The general problem is
  worse than the specific one: a scanner reading that database will report
  packages whose files are absent, in either direction.
- **Removing the duplicated base removed `openssl-libs`**, and with it the
  image's only High vulnerability finding. The binary links no TLS library, so
  OpenSSL was only ever present because an empty installroot pulled in a full
  base system.

- [ ] Decide how to detect that UBI Micro's recorded package set has drifted
  from its actual filesystem in some new way at the next base-image update.
  The `tzdata` case was found by accident, not by a check.
- [ ] Docker's build backend has no per-build network flag equivalent to
  Podman's `--network=none`; CI sets `network: none` on the action instead.
  Confirm the two are equivalent in effect, or record where they differ.

### 2c: provenance and inventory

- [ ] Implement a lock-update workflow that proposes a reviewed change rather
  than resolving releases or dependencies during ordinary builds.
- [ ] Improve publisher verification beyond a recorded digest: adopt upstream
  artifact attestations if they exist, request upstream signing, or evaluate a
  pinned-toolchain source build with vendored dependencies. Record the outcome
  even if no stronger control is currently available.
- [ ] Resolve the open decisions in the
  [container minimization analysis](MINIMIZATION.md), starting with whether to
  strip the upstream binary. Measured: stripping saves 41.6 MB, about 18% of
  the image, and is a larger reduction than removing every package the image
  could plausibly drop. It also means the shipped bytes stop matching the
  bytes this project verified, so the lock would have to record both digests.
  The analysis also records that the fail-closed encryption-key guard is a
  shell script, so any proposal to remove the shell removes a security control
  unless it is reimplemented first.
- [ ] Record source, redistribution, licensing, support lifecycle, and update
  ownership for every runtime component.
- [ ] Close the SBOM coverage gap. The current Syft inventory resolves the UBI
  RPMs and the base image, and **no Lakekeeper crate dependencies**: the upstream
  release binary carries no embedded dependency metadata that a scanner can read.
  A release SBOM that omits the application's own dependency tree cannot support
  vulnerability triage for Lakekeeper itself. Evaluate requesting an upstream
  SBOM, an upstream `cargo auditable` build, or generating the inventory from the
  upstream lockfile at the locked release tag, and state the residual gap if none
  is achievable.
- [ ] Resolve the `openssl-libs` question. The binary links no TLS library, but
  OpenSSL is not simply removable: it enters through the `ca-certificates` trust
  chain, which is the one thing the final stage genuinely needs. It contributes
  the image's only High finding (CVE-2026-14456, an unfixed QUIC server flaw)
  against code this image never executes. Decide between keeping RPM-managed
  trust material with a documented triage rationale, or shipping only extracted
  trust files and accepting the loss of package provenance and SBOM visibility.
  Do not treat the second option as obviously better.

## Package 3: supported configuration and runtime qualification

- [ ] Qualify the minimum catalog profile: migration, server startup, health,
  management info, Iceberg REST endpoints, and graceful shutdown against a
  supported PostgreSQL version.
- [ ] Test PostgreSQL 15 through the current supported major version, including
  the required extensions, a least-privilege database role, and the behavior
  when an extension is unavailable.
- [ ] Define and test the migration contract: running `migrate` separately from
  `serve`, running `serve` against an unmigrated or partially migrated
  database, re-running `migrate`, and rolling an image back across a schema
  change.
- [ ] Establish safe deployment defaults for listener exposure, the metrics
  port, CORS, request limits, and the bootstrap endpoint, and document the
  window in which an unbootstrapped catalog is exposed.
- [ ] Document configuration, validation, troubleshooting, rollback, and secret
  redaction, including the full environment-variable surface this project
  supports.
- [ ] Implement and test structured logging guidance covering request
  correlation, audit events, error responses, and sensitive-value exclusion.
- [ ] Support and test split read/write database URLs
  (`LAKEKEEPER__PG_DATABASE_URL_READ` alongside `..._WRITE`), which upstream
  recommends for production so writes reach the primary and reads spread across
  replicas. The image and smoke suite currently exercise only the write URL.
- [ ] Document and test connection-pool sizing
  (`LAKEKEEPER__PG_READ_POOL_CONNECTIONS`, `LAKEKEEPER__PG_WRITE_POOL_CONNECTIONS`)
  and the pool-exhaustion signal, `lakekeeper_catalog_pg_pool_acquire_timeouts_total`.
- [ ] Qualify the metrics listener. Upstream binds `LAKEKEEPER__BIND_IP` to
  `0.0.0.0` by default, so port 9000 is exposed on every interface unless an
  operator restricts it. Decide whether this image changes that default,
  document the exposure, and test `/metrics` on port 9000.
- [ ] Document the exact `/health` contract for probes: it returns 503 only when
  PostgreSQL is unreachable, and deliberately **not** when a role provider is
  down, so a provider outage keeps serving from cached roles. A reader who
  assumes 200 means fully healthy will misconfigure alerting.
- [ ] Document and test log-level control through `RUST_LOG`, including reducing
  dependency noise, and `LAKEKEEPER__DEBUG__EXTENDED_LOGS`.
- [ ] Treat audit logs as personal data. Entries with `"event_source": "audit"`
  carry user identities, unlike error-response logs. Document retention, access
  control, and `LAKEKEEPER__AUDIT__TRACING__ENABLED=false`, and state the
  consequence of disabling the audit trail.
- [ ] Define the upgrade contract: upstream requires running `lakekeeper migrate`
  before each upgrade, after a database backup, because it updates both the
  schema and the authorization model. Test an upgrade and a rollback across a
  schema change.

## Package 4: CI and supply-chain controls

- [ ] Add a least-privilege release workflow with strict tag validation, native
  multi-architecture publishing, SBOM and provenance attestations, digest-bound
  signing, and retained verification evidence.
- [ ] Add monitored update proposals for the Lakekeeper release, UBI image
  digests, runtime RPMs, and assurance tools.
- [ ] Prove that release assembly cannot pull images, reach package networks,
  recalculate dependencies, or expose acquisition credentials.

## Package 5: security engineering and cyber-review package

- [ ] Establish the authoritative requirement-source register with publisher,
  title, release, date, retrieval date, URL, SHA-256, status, and license.
- [ ] Compare applicable NIST SP 800-53/53A, DISA Container Platform and
  application-services guidance, RHEL 9 STIG content, and product behavior;
  require independent review of applicability and mappings.
- [ ] Classify each requirement as image-owned, deployment-supported,
  inherited, not applicable, unsupported, or research required, with rationale
  and residual risk.
- [ ] Publish a schema-validated NIST OSCAL Component Definition and generate
  deterministic CSV and human-readable control views from the same source.
- [ ] Give every supported control an examine/test/interview assessment method,
  owner, defaults, configuration and restart behavior, dependencies, impact,
  loss-of-function statement, limitations, and evidence pointer.
- [ ] Perform discovery with pinned OpenSCAP and ComplianceAsCode content
  against a root-owner-preserving export of each architecture image.
- [ ] Select only image-owned rules, document every inclusion and exclusion,
  publish tailoring, and distinguish failures from not-applicable or
  deployment-owned controls.
- [ ] Keep findings report-only until the selected profile is reviewed and a
  blocking policy is approved; scanner execution errors always block.
- [ ] Create architecture, assurance-pipeline, runtime data-flow, trust, and
  control-ownership diagrams, including the catalog's relationship to the
  database, object store, identity provider, and query engines.
- [ ] Publish a threat model covering build inputs, CI, registry, image
  integrity, runtime identity, configuration, the unauthenticated default
  posture, the bootstrap window, credential vending, stored storage secrets,
  database compromise, logs, denial of service, and evidence integrity.
- [ ] Publish a control matrix mapping requirements, implementation,
  configuration, validation, evidence, owner, limitations, and residual risk.
- [ ] Act on the [FIPS analysis](FIPS.md). It records the decisive finding:
  the upstream binary statically links its own cryptography and uses no system
  OpenSSL, so running on a FIPS-enabled host places none of this image's
  cryptography inside a validated boundary. Any FIPS requirement applied to
  this component is currently **not met** and must be recorded as such rather
  than deferred or implied. Closing it depends on the crate inventory that
  Package 2c is still missing.
- [ ] Document vulnerability triage for both UBI packages and the Rust
  dependency tree, patch SLAs, exceptions with expiry, incident response,
  backup/restore responsibilities, logging integration, monitoring, resource
  limits, network policy, disconnected deployment, and decommissioning.
- [ ] Maintain a qualification ledger keyed by commit, image digest,
  architecture, inputs, runtime/platform versions, configuration, scanner
  versions/databases, result, limitations, evidence level, and artifact.

## Package 6: deployment and platform qualification

- [ ] Publish supported, compatible, preview/unqualified, and unsupported
  definitions plus an exact matrix for architecture, host, Podman/OCI runtime,
  Docker compatibility, OpenShift, PostgreSQL versions, configuration profiles,
  controlled-network operation, SCAP, and FIPS claims.
- [ ] Qualify a rootless standalone-host Quadlet deployment with an external
  PostgreSQL instance on an exact supported RHEL 9 baseline, including cgroup
  v2, SELinux enforcing, subordinate IDs, lingering, boot, restart throttling,
  health, graceful stop, update, and rollback.
- [ ] Define database backup, restore, and point-in-time-recovery
  responsibility, and test catalog behavior during database failover,
  connection exhaustion, and restore.
- [ ] Qualify journald persistence, rate and capacity limits, access control,
  restart correlation, authenticated forwarding, storage pressure, retention,
  and disposal without sensitive-data leakage.
- [ ] Test every supported configuration with positive, negative, restricted-
  runtime, load/failure, and logging cases on each claimed platform.
- [ ] Decide the OpenShift first-release support boundary from exact restricted-
  SCC qualification; retain preview status if the required cluster evidence is
  unavailable.
- [ ] Document TLS termination as an external responsibility. Lakekeeper does
  not terminate TLS itself, so a deployment needs a reverse proxy or ingress in
  front of it. The Datopsis `nginx-ubi` image is the intended partner for the
  standalone profile; qualify that pairing rather than describing it
  hypothetically.
- [ ] Qualify a high-availability shape: several catalog instances against one
  external high-availability PostgreSQL, including rolling restart, and confirm
  no instance holds local state that makes it non-interchangeable.
- [ ] Define and test database backup and restore ownership, including restoring
  into a running catalog and verifying that encrypted secrets remain decryptable
  with the operator-held key.
- [ ] Qualify resource limits and the behavior of the catalog under connection
  exhaustion and database failover.
- [ ] Replace the development PostgreSQL container in `compose.yaml` with the
  Datopsis `postgresql-ubi` image once it publishes a release. Compose work is
  deliberately last: the stack is unverified until that image exists, and
  pinning an upstream PostgreSQL image in the meantime would create a
  dependency this portfolio intends to replace.
- [ ] Exercise `compose.yaml` in the reference contributor environment and in
  CI. It is currently unverified: the reference environment has no Compose
  provider installed, so the file's service ordering, credential requirements,
  and hardening options have not been executed end to end.

## Package 7: signed first release

- [ ] Implement and test the approved
  `v<lakekeeper-version>-ubi<ubi-major>-r<YYYYMMDD>.<daily-sequence>` tag
  contract, version matching against the artifact lock, UTC date and sequence
  validation, immutable release and commit tags, and OCI metadata.
- [ ] Define the first-release support lifetime, the upstream pre-1.0 upgrade
  policy, and the superseded-release policy.
- [ ] Freeze the final upstream versions and digests only after image-affecting
  work is complete.
- [ ] Review all fixed and unfixed scanner findings, for both UBI packages and
  Rust dependencies, against authoritative advisories; document every
  time-bounded acceptance.
- [ ] Complete license and third-party notice review, including the Rust
  dependency license inventory.
- [ ] Regenerate native architecture, rootless Podman, database, controlled-
  network, standalone Quadlet/systemd/journald, and tailored SCAP
  release-candidate evidence from the exact candidate.
- [ ] Rehearse tag validation and the entire release workflow without granting
  broader permissions than production needs.
- [ ] Publish an AMD64/ARM64 manifest to GHCR with BuildKit provenance and
  SBOM, a complete SPDX release asset, digest-bound Cosign keyless signature
  and attestation, and a GitHub Release.
- [ ] Verify published digests, platforms, labels, signatures, attestations,
  SBOMs, scan artifacts, documentation links, and rollback instructions.

## Assurance completeness gate

Before release, review this repository against the complete assurance model and
record any intentionally omitted item with a Lakekeeper-specific rationale. The
review must cover evidence lifecycle, support semantics, qualification ledger,
architecture and trust-boundary diagrams, rootless runtime and platform
qualification, use-case profiles, the cryptographic boundary, authoritative
requirement analysis, control ownership and OSCAL export, tailored SCAP,
vulnerability and exception management, licensing and notices, supply-chain
evidence, controlled-network procedures, production go-live evidence, release
rehearsal, failed-candidate handling, rollback, incident response, and evidence
retention. Because the catalog depends on an external database, the review must
also cover database storage, availability, backup, and restore ownership.

## Deferred from the first release

These are deliberately outside the first-release boundary. Each needs its own
threat boundary, test matrix, and maintenance commitment before it can be
claimed. The list is drawn from the upstream feature surface, so it also serves
as the record of what this image does *not* yet support.

### Warehouse storage

- [ ] **S3 and S3-compatible storage.** Qualify first, with an S3-compatible
  implementation such as MinIO using the `s3-compat` flavor. Cover access-key
  credentials, STS temporary credentials, and AWS system identities.
- [ ] **Credential vending versus remote signing.** These are two different trust
  models: vending hands the client temporary credentials, while remote signing
  keeps the credentials server-side and signs client-prepared requests. They are
  selectable per warehouse and per request through the
  `X-Iceberg-Access-Delegation` header. Document which one a deployment should
  prefer and why; do not present them as interchangeable.
- [ ] **Warehouse isolation.** Upstream requires that every warehouse use a
  distinct storage location or prefix and distinct credentials scoped to only
  that prefix. Test the failure mode where two warehouses share credentials,
  because that is a cross-tenant data-access boundary, not a tidiness rule.
- [ ] **ADLS Gen 2, OneLake, and GCS**, including client credentials, Azure and
  GCP system identities, and the required role assignments. Evaluate only when an
  environment exists to test each one.

### Authentication and authorization

- [ ] **OIDC authentication.** `LAKEKEEPER__OPENID_PROVIDER_URI` with audience
  validation, and an explicit `LAKEKEEPER__OPENID_SUBJECT_CLAIM`, which upstream
  says must be set deliberately per provider. Cover token lifetime, clock skew,
  and failure behavior.
- [ ] **Kubernetes authentication** through
  `LAKEKEEPER__ENABLE_KUBERNETES_AUTHENTICATION`, relevant to any future
  OpenShift qualification.
- [ ] **OpenFGA authorization**, including its own data store, cache tuning, and
  the co-location upstream recommends for latency. This introduces a second
  external service and its own threat boundary.
- [ ] **Role providers.** Monitor `lakekeeper_role_provider_up` and understand
  that a provider outage is deliberately not a health failure, so authorization
  continues from stale cached roles. Define how long that is acceptable.
- [ ] **Query-engine trust.** Upstream warns that root access to a centrally
  managed engine such as Trino, via the OPA bridge, undermines catalog
  authorization. Document that boundary.

### Catalog behavior

- [ ] **Soft deletion and tabular expiration.** Deleted tables stay recoverable
  for a configured period, and clients must avoid `PURGE` while it is enabled.
  Document the recovery window as a data-retention control.
- [ ] **Table maintenance**, such as `expire_snapshots`, which requires an
  explicit `s3.delete-enabled: true` override when the storage profile disables
  deletion.
- [ ] **Task queues.** The server runs `tabular_expiration`, `tabular_purge`, and
  `task_log_cleanup` workers. Define their failure behavior, observability, and
  what happens when several instances run concurrently.
- [ ] **Projects.** Upstream recommends a single project for a single company.
  Decide and document this image's position before multi-project deployments
  exist, because changing it later is a data-model migration.
- [ ] **Bootstrap.** Define the intended bootstrap procedure, the exposure of the
  pre-bootstrap window, and the meaning of `reopen-bootstrap`.
- [ ] **Endpoint statistics** and `LAKEKEEPER__ENDPOINT_STAT_FLUSH_INTERVAL`.

### Integration and operations

- [ ] **Event publishing.** Kafka and NATS, including transport security,
  credential handling, and failure behavior.
- [ ] **Vault KV v2 secrets backend** as an alternative to PostgreSQL secret
  storage, which would also change the encryption-key contract.
- [ ] **Prometheus metrics guidance.** Cache hit ratios, `axum_http_requests_*`,
  pool metrics, and the Tokio runtime metrics, with the caveat that some are
  unstable.
- [ ] **Query-engine interoperability matrix.** Exact tested versions for Spark,
  Trino, DuckDB, PyIceberg, and ClickHouse, including the hardened path from the
  Datopsis ClickHouse images.
- [ ] **Performance, concurrency, and soak baselines.**
- [ ] **Exact OpenShift qualification** if an appropriate cluster is available.
