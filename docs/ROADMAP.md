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

Upstream Lakekeeper starts successfully when
`LAKEKEEPER__PG_ENCRYPTION_KEY` is unset. It falls back to a **default,
publicly known encryption key** and emits only a `WARN` log line. Stored
storage credentials are then encrypted with a key that provides no
confidentiality against anyone who reads the upstream source. This behavior was
observed directly against the locked version.

- [ ] Decide and document whether this image fails closed when the encryption
  key is unset, or preserves upstream behavior and pushes the control entirely
  into deployment. Record the decision, its rationale, and its compatibility
  impact.
- [ ] If failing closed is chosen, implement the check without introducing a
  privileged entrypoint phase or a privilege transition, and test that the
  diagnostic names the variable without echoing any secret value.
- [ ] Add a test that asserts the unsafe-default warning is absent whenever a
  key is supplied, so a regression in configuration plumbing cannot pass
  silently.
- [ ] Inventory every other configuration value whose absence degrades security
  rather than failing, and classify each one as image-enforced,
  deployment-enforced, or accepted with rationale.
- [ ] Verify that the encryption key, database password, and object-store
  credentials never appear in logs, error responses, the management API, or
  image layers.
- [ ] Investigate the observation that `wait-for-db` exited `0` against an
  unresolvable database host. If confirmed, document that it must not be used
  as a readiness gate and report it upstream.

## Package 2: artifact acquisition and hermetic assembly

- [ ] Move the release-archive download out of the builder stage into a
  reviewed acquisition step, and run assembly with networking and image pulling
  disabled.
- [ ] Implement the full verification set in `docs/ARTIFACT-ACQUISITION.md`,
  including archive digest, archive member list, binary digest, GNU build ID,
  ELF architecture, needed shared libraries, and highest glibc symbol version
  against the targeted UBI major version.
- [ ] Add negative tests for a tampered archive, an unexpected extra archive
  member, a wrong-architecture binary, a missing file, and an unmatched lock
  entry.
- [ ] Implement a lock-update workflow that proposes a reviewed change rather
  than resolving releases during ordinary builds.
- [ ] Improve publisher verification beyond a recorded digest: adopt upstream
  artifact attestations if they exist, request upstream signing, or evaluate a
  pinned-toolchain source build with vendored dependencies. Record the outcome
  even if no stronger control is currently available.
- [ ] Decide whether to ship the unstripped upstream binary or strip it,
  weighing image size against incident-analysis value, and record the decision
  with its effect on the recorded binary digest.
- [ ] Record source, redistribution, licensing, support lifecycle, and update
  ownership for every runtime component.
- [ ] Close the SBOM coverage gap. The current Syft inventory resolves 40 UBI
  RPMs and the base image, and **no Lakekeeper crate dependencies**: the
  upstream release binary carries no embedded dependency metadata that a
  scanner can read. A release SBOM that omits the application's own dependency
  tree cannot support vulnerability triage for Lakekeeper itself. Evaluate
  requesting an upstream SBOM, an upstream `cargo auditable` build, or
  generating the inventory from the upstream lockfile at the locked release
  tag, and state the residual gap if none is achievable.
- [ ] Evaluate removing `openssl-libs` from the runtime. The binary links no
  TLS library, so OpenSSL is present only as a transitive dependency of the
  trust-material packages. It currently contributes the image's only High
  finding (CVE-2026-14456, a QUIC server flaw Red Hat has not fixed) against
  code this image never executes. Record why the package is present, whether
  it can be dropped, and the triage rationale either way.

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
- [ ] Define the cryptographic boundary, covering secret encryption at rest and
  transport security, and document why a UBI base does not independently
  establish FIPS validation.
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
- [ ] Replace the development PostgreSQL container in `compose.yaml` with the
  Datopsis `postgresql-ubi` image once it publishes a release.
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
claimed.

- [ ] **Warehouse storage profiles.** Qualify S3-compatible storage first,
  including credential vending, least-privilege bucket policy, server-side
  encryption, and an S3-compatible implementation such as MinIO. Evaluate ADLS
  and GCS only when an environment exists to test them.
- [ ] **OIDC authentication.** Document provider configuration, audience and
  issuer validation, token lifetime, clock skew, and failure behavior. Do not
  claim a qualified profile without an exact tested provider.
- [ ] **OpenFGA authorization.** Adding it introduces a second external
  service, its own data store, its own threat boundary, and a substantially
  larger test matrix. Evaluate only after the core catalog release is stable.
- [ ] **Event publishing.** Kafka and NATS integrations, including transport
  security, credential handling, and failure behavior.
- [ ] **Vault KV v2 secrets backend** as an alternative to PostgreSQL secret
  storage.
- [ ] **Query-engine interoperability matrix.** Exact tested versions for
  engines such as Spark, Trino, DuckDB, PyIceberg, and ClickHouse, including
  the hardened path from the Datopsis ClickHouse images.
- [ ] **Performance, concurrency, and soak baselines.**
- [ ] **Exact OpenShift qualification** if an appropriate cluster is available.
