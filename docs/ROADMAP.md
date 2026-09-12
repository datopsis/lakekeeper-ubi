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
| Warehouse storage | S3-compatible storage is in scope and must be qualified, tested against SeaweedFS. A catalog with no warehouse cannot hold a table, so excluding storage would leave nothing to release. ADLS, OneLake, and GCS stay out of scope. |
| TLS | Terminated outside the image. Lakekeeper does not terminate TLS, so a deployment needs a reverse proxy or ingress in front of it. |
| Controlled networks | Document connected build, artifact transfer, digest verification, mirrored deployment, local trust, logging, and update procedures. |
| FIPS | Make no FIPS validation claim without a separately defined and evidenced cryptographic boundary. |
| STIG/SCAP | Publish exact tailored image-filesystem results; make no STIG certification claim. |
| Registry | Publish the first release to GHCR. |

Authentication, authorization, and event publishing are deferred as described
under "Deferred from the first release". The first release must state plainly
that a catalog deployed without authentication and authorization is only
appropriate on a trusted network.

Warehouse storage is **not** deferred. An earlier version of this boundary
excluded it, which would have produced a catalog that starts, reports healthy,
and cannot hold a single table. Storage is what makes the Iceberg REST catalog
API a usable thing rather than an endpoint that answers.

## Immediate first-release sequence

Work proceeds in this dependency order. Completed steps stay listed so the
order remains readable, with what closed them.

1. **Done.** Resolve the secret-encryption-key failure mode. The image fails
   closed when the key is absent or set to upstream's published default, with
   a documented opt-out.
2. **Done.** Out-of-build artifact acquisition and network-disabled assembly.
   Assembly runs with `--network=none` and `--pull=never`, consuming only
   digest-verified inputs.
3. **Done.** The runtime test matrix: database fixtures, negative
   configuration cases, arbitrary UID, graceful lifecycle, and runtime
   dependency completeness.
4. **Mostly done.** The minimum catalog profile is qualified against
   SeaweedFS, including a real data round trip through PyIceberg. What remains
   is under "Warehouse storage", and per-warehouse credential isolation is the
   part that matters most.
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

## Where to resume

This section is the entry point for picking the work back up. It records what
to do next and why, so that the choice does not have to be reconstructed from
the rest of this document.

### Recommended next task

**Per-warehouse credential isolation**, under "Warehouse storage". Two
warehouses with distinct prefixes and distinct credentials, proving one cannot
read the other's prefix.

It ranks first because it is a security boundary rather than a feature.
Upstream states the requirement, the storage harness that makes it testable
already exists, and until it is tested the project cannot say whether two
tenants of one catalog are actually separated. Everything else outstanding in
that area extends coverage; this one closes a boundary.

### Alternatives, and why they rank lower

- **Credential vending or remote signing.** A different trust model from the
  one qualified, where the engine supplies its own credentials. Worth doing,
  but it widens the boundary rather than verifying the current one.
- **TLS on the storage path.** Closes the gap that the image's trust bundle is
  validated only by size and certificate count. Small and useful.
- **Cybersecurity control documentation.** The largest remaining body of work
  and the one a reviewer will ask for, but it describes a boundary that is
  still moving.
- **Release rehearsal**, Packages 4 and 7. Premature while the product
  boundary is still being qualified.

### Decisions that need a human

These are not blocked on implementation. They are choices this project should
not make silently, and they are listed here rather than buried in a package so
they do not get decided by whoever edits the file next.

- Require a minimum length or entropy for the encryption key? Rejecting the
  published default was unambiguous; refusing a short key is a policy choice
  that could reject a legitimate deployment.
- Override upstream's `LAKEKEEPER__USE_X_FORWARDED_HEADERS=true` default to
  `false`? Correct behind a proxy, wrong when the catalog is directly
  reachable.
- Strip the upstream binary? Saves 41.6 MB, about 18% of the image, at the
  cost of the shipped bytes no longer matching the bytes this project
  verified.
- What does a crate vulnerability finding block? They are report-only today,
  because this project cannot patch upstream's dependencies.
- Does the first release claim a supported storage *stack*, which would pull
  the Datopsis SeaweedFS image into scope, or only that it works against
  S3-compatible storage tested with SeaweedFS?

### Standing obligations at every upstream version bump

- Re-check the published default encryption key value, which the entrypoint
  compares against a literal.
- Re-measure the highest required glibc symbol version and the needed shared
  library list against the targeted UBI major version.
- Re-check whether the UBI Micro RPM database has drifted further from its own
  filesystem, as it has for `tzdata`.
- Treat a `0.x` minor increment as a qualification event, not a dependency
  bump, because upstream is pre-1.0.

## Package 1: secret and configuration failure modes

The encryption-key contract is implemented and the configuration surface has
been inventoried. The image fails closed when the key is absent **or set to
upstream's published default**, with a documented opt-out; the full inventory
of settings that degrade silently is in `docs/CONFIGURATION.md`.

Three things were measured against the locked version and are worth keeping in
view:

- **Setting the key to upstream's published default is silent.** Upstream warns
  only when the variable is absent, so a copied example or a chart default
  produces no signal at all. This image now rejects that exact value.
- **A plaintext database connection is silent.** With `LAKEKEEPER__PG_SSL_MODE`
  unset the catalog connects without TLS and logs nothing, so every query and
  every encrypted secret blob crosses the network in the clear.
- **Audit tracing is enabled by default in practice**, while the upstream
  configuration reference records the default as `false`. The documentation and
  the behavior disagree.

- [ ] Decide whether to require a minimum length or entropy for the encryption
  key. Rejecting the published default was unambiguous because every use of it
  is a mistake; rejecting a short key is a policy choice that could refuse a
  legitimate deployment, so it needs a decision rather than an implementation.
- [ ] Re-check the published default key value at every upstream version bump.
  The guard compares against a literal recorded in the entrypoint, and a
  silently renamed default would make the check pass for the wrong reason.
- [ ] Publish and test a supported encryption-key rotation procedure. The
  configuration guide currently states what is known and explicitly refuses to
  imply a procedure that has not been tested.
- [ ] Report the audit-tracing default discrepancy upstream, and decide which
  behavior this image documents in the meantime.
- [ ] Decide whether this image should default `LAKEKEEPER__USE_X_FORWARDED_HEADERS`
  to `false`. Upstream defaults it to `true`, which trusts proxy headers from
  any caller; that is correct behind a proxy and wrong when the catalog is
  directly reachable. Changing an upstream default needs the same justification
  the encryption-key guard received.
- [ ] Verify that secrets never appear in error responses, the management API,
  or image layers. The smoke suite currently covers container logs only.
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

Partially implemented. The release now carries a crate inventory: upstream's
`Cargo.lock` is acquired from the pinned release commit, digest-verified on the
same terms as everything else, catalogued with Syft, and scanned report-only.
Two questions were settled by measurement rather than left open:

- **Upstream publishes no artifact attestations.** Queried directly; the API
  returns 404 for the locked archive digest. Attestation verification is
  therefore not an available improvement, and the recorded digest remains the
  only integrity evidence for the binary.
- **The binary carries no embedded dependency metadata.** It has no
  `cargo auditable` section, so no scanner can derive an inventory from the
  shipped artifact. The declared graph from source is the best obtainable
  substitute, and it over-reports, because feature flags exclude crates that
  still appear in the lockfile.

- [ ] Define the triage policy for crate findings. They are report-only today,
  because this project cannot patch upstream's dependencies and blocking on
  them would tie every release to upstream's schedule. Decide what does block a
  release, what gets reported upstream, and how an accepted finding expires.
- [ ] Decide whether the inventory's over-reporting is acceptable for review,
  or whether to narrow it by resolving the feature set upstream actually
  builds. A source build would answer this precisely and is the same decision
  as the FIPS and publisher-verification questions.
- [ ] Ask upstream to publish either artifact attestations or a `cargo auditable`
  build. Both would replace a declared inventory with a derived one. Record the
  request and its outcome so the limitation has a history.
- [ ] Resolve the open decisions in the
  [container minimization analysis](MINIMIZATION.md), starting with whether to
  strip the upstream binary. Measured: stripping saves 41.6 MB, about 18% of
  the image, and is a larger reduction than removing every package the image
  could plausibly drop. It also means the shipped bytes stop matching the bytes
  this project verified, so the lock would have to record both digests. The
  analysis also records that the fail-closed encryption-key guard is a shell
  script, so any proposal to remove the shell removes a security control unless
  it is reimplemented first.
- [ ] Record source, redistribution, licensing, support lifecycle, and update
  ownership for every runtime component, and complete the crate license review
  that the inventory now makes possible.
- [ ] Implement a lock-update workflow that proposes reviewed changes on a
  schedule, covering the Lakekeeper release, the UBI digests, the runtime RPMs,
  and the crate manifest together, so they cannot drift apart.

## Package 3: supported configuration and runtime qualification

### Warehouse storage

Qualified against SeaweedFS. `tests/storage.sh` registers a warehouse backed by
S3-compatible storage, creates a namespace and a table, confirms the table's
metadata was written to the object store under the exact prefix the catalog
reports, loads the table back with its schema intact, drops it, and proves the
stored storage credential is neither readable in a full database dump nor
present in the logs. It then restarts the catalog and creates another table,
which requires decrypting that credential and using it against the object
store. Registering a warehouse with credentials the object store rejects must
fail, so the validation is shown to validate.

This is the first test that exercises the secret encryption key against a
credential that exists: before it, the fail-closed guard protected a code path
no test had used.

It also round-trips real rows through PyIceberg, an independent implementation
of the Iceberg specification, so a disagreement between this catalog and the
specification fails in CI rather than at the first engine an operator points
at it. Three rows are written, read back and compared, confirmed to exist as
Parquet files in the object store, and read again after the catalog is
restarted.

**Both stores are exercised, and the restart is what proves it.** PostgreSQL
holds catalog state: warehouses, namespaces, table registrations, the pointer
to each table's current metadata, and the encrypted storage credentials. The
object store holds Iceberg metadata, manifests, and the Parquet data files. A
commit is a catalog operation recorded in PostgreSQL that publishes files
already written to object storage, so reading rows back after a restart, which
discards every in-memory cache, can only succeed if both stores are correct
and agree.

One behavior worth recording, because it produces a misleading error: SeaweedFS
auto-creates a plain directory on the first PUT, and that directory is not a
registered bucket. Its metadata lookups then fail and HEAD returns NotFound,
which the catalog surfaces as a validation failure that says nothing about
buckets. The bucket must be registered before the catalog ever writes to it.

- [ ] Qualify credential vending. The current profile sets `sts-enabled: false`
  and the catalog holds the credential itself; STS is AWS-specific and remote
  signing is untested here. Decide which model this image documents for
  S3-compatible storage, because they are different trust boundaries rather
  than alternative settings.
- [ ] Test per-warehouse credential isolation: two warehouses with distinct
  prefixes and distinct credentials, proving one cannot read the other's
  prefix. Upstream states this as a requirement, which makes it a cross-tenant
  boundary rather than a tidiness rule.
- [ ] Pin the engine toolchain. The round trip installs PyIceberg and PyArrow
  from PyPI at test time, so the test depends on packages that are pinned by
  version but not by digest. That is a weaker standard than the image inputs
  hold themselves to. It is a test dependency rather than an image input, so
  the requirement differs, but the difference should be deliberate.
- [ ] Add a second engine. PyIceberg agreeing does not prove Spark or Trino
  agree, and engines differ in which parts of the specification they exercise.
- [ ] Exercise the path over TLS, against an S3 endpoint using a certificate
  chain, which closes the gap that the image's trust bundle is still validated
  only by size and certificate count.
- [ ] Record which S3 behaviors SeaweedFS differs on, including path versus
  virtual-host addressing, and whether any Iceberg maintenance operation needs
  behavior it does not implement.
- [ ] Decide whether the Datopsis SeaweedFS image replaces the upstream test
  fixture, and when. Nothing blocks on it: the switch belongs with the same
  change that replaces the upstream PostgreSQL image in `compose.yaml`.

### Remaining runtime qualification

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

Runtime dependency completeness is now checked by
`tests/runtime-dependencies.sh`, which asks the dynamic loader to resolve the
binary inside the image, confirms the name-resolution modules glibc loads with
`dlopen` are present, counts the certificates in the TLS trust bundle, and
confirms time-zone data survived. The measured result is that nothing is
missing: all five needed libraries resolve, NSS is complete, and the bundle
holds 146 certificates. These remain open:

- [ ] Exercise outbound TLS against a real endpoint using the image's own trust
  bundle. The bundle is currently validated statically, by size and certificate
  count, which would not catch a bundle that parses but does not chain. The
  natural vehicle is the S3-compatible storage profile, so this is coupled to
  that work rather than worth a synthetic harness now.
- [ ] Exercise the paths that only appear under real use: a warehouse
  registration that stores and retrieves an encrypted credential, a table
  create and read through a query engine, and a task-queue run. The smoke suite
  proves the server starts and answers; it does not prove the catalog works.
- [ ] Decide whether to detect `dlopen` use in the binary directly rather than
  enumerating known cases. The NSS modules were checked because glibc's
  behavior is known, not because anything measured what the binary loads at
  runtime. A future upstream release could add a plugin path nobody noticed.
- [ ] Run the image under a syscall tracer once, to record which files and
  libraries it actually opens at startup, and compare that against what the
  image provides. That converts the previous item from reasoning into
  measurement.
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

### Cybersecurity control documentation

The indicative mapping in [hermetic build](HERMETIC-BUILD.md) is explicitly not
an assessment, and no control identifier is cited anywhere in this repository
on purpose. Citing one implies an assessment that has not happened. These items
turn that into something an evaluator can use.

- [ ] Publish `docs/SECURITY-CONTROLS.md` defining control ownership across the
  image, the container runtime, the orchestrator, PostgreSQL, the object store,
  the identity provider, the TLS-terminating proxy, the network boundary, and
  the operator. Lakekeeper spreads responsibility across more parties than a
  single-process image does, and an unassigned control is how a gap survives
  review.
- [ ] For each control this image claims to support, record the implementation,
  the configuration required to get it, the restart behavior, the assessment
  method, the evidence artifact, the limitation, and the residual risk. A claim
  without an assessment method is not reviewable.
- [ ] Document the controls this image explicitly does **not** provide, with
  the party that must provide them instead: inbound TLS, authentication,
  authorization, database encryption at rest, backup and restore, network
  policy, and resource limits.
- [ ] Record the controls that hermetic assembly strengthens and the one it
  constrains. Package updates now require a reviewed lock change rather than
  happening automatically; that is intended, and an assessor should read it in
  the documentation rather than infer it from a lock file.
- [ ] Publish a schema-validated OSCAL Component Definition once the control
  set is stable, and generate the human-readable views from that single source
  rather than maintaining them separately.
- [ ] Establish the requirement register that makes any of the above citable:
  publisher, title, revision, retrieval date, URL, digest, and applicability
  decision per requirement, with an independent review of the mappings.

### SCAP scan profile

- [ ] Select the scanner and content, pin both by version and digest, and
  record why that content version applies to this image. An unpinned scanner
  produces results that cannot be compared across releases.
- [ ] Decide what is actually scanned. This image has no init system, no
  sshd, no auditd, no PAM, and no login path, so the large majority of a RHEL
  host profile is not applicable rather than failing. Scan an
  ownership-preserving filesystem export per architecture, not a running
  container, so the results describe the image rather than the test harness.
- [ ] Build the tailoring file by classifying every rule as image-owned,
  deployment-owned, inherited, or not applicable, with a recorded rationale per
  exclusion. An exclusion without a reason is indistinguishable from hiding a
  failure.
- [ ] Keep results report-only until the tailored profile has been reviewed,
  and treat a scanner execution error as blocking even while findings are not.
  A scan that did not run must never look like a scan that passed.
- [ ] Publish the tailoring, the content version, the scanner version, the
  target architecture, and the exact image digest alongside every result, so a
  result can be tied to what produced it.
- [ ] Write the statement that accompanies every published result: it reports
  the selected rules against the evaluated filesystem, and it is not a STIG
  certification, an accreditation, or a statement about a deployment.
- [ ] Reconcile SCAP findings against the runtime evidence the smoke suite
  already produces, so the two do not contradict each other in a review.
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
