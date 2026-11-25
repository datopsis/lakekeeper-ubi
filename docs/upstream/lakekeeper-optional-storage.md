# Proposal: optional Azure and GCS storage in Lakekeeper

Owner review draft, researched 2026-11-19. **Nothing has been posted upstream.**
This proposes upstream work; it does not change this image's binary, features,
checks, supported storage scope or runtime policy. The image upgrade and blocking
RustSec gate are separately proposed in
[datopsis/lakekeeper-ubi #26](https://github.com/datopsis/lakekeeper-ubi/pull/26).

## Motivation and scope

`datopsis/datopsis-authz` links Lakekeeper 0.13.4 as a library. Its cargo-audit
check finds quick-xml 0.40.1 through the unconditional Azure SDK dependency path,
even when the application uses no Azure storage. A runtime setting that disables
Azure does not remove that code from a Rust library or executable.

Propose default-on `storage-adls` and `storage-gcs` Cargo features at the
Lakekeeper library boundary, forwarded consistently through the binary and
PostgreSQL crates. Keep S3 in the baseline for this first change. Existing default
builds and all-features release binaries continue to support every backend.
Offer an explicit S3-only library/binary build for consumers that need it.
Separately update quick-xml in the Azure SDK fork; optional features are not a
remediation for users who compile Azure in.

## Pinned upstream research

All source citations below refer to main at
[`21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c`](https://github.com/lakekeeper/lakekeeper/tree/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c),
not a moving branch. Main has moved beyond 0.13; do not assume its GCS dependency
layout matches the 0.13.4 library used by authz.

| Layer | Wiring at the pinned commit |
| --- | --- |
| Lakekeeper features | [`crates/lakekeeper/Cargo.toml:19–31`](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/crates/lakekeeper/Cargo.toml#L19-L31): defaults are `s3-signer` and `router`; `all` adds `open-api`; `test-utils` enables in-memory IO/jsonschema; `sqlx-postgres` enables SQL types. There is no cloud-storage selection feature here. |
| Forced cloud edges | [`lakekeeper/Cargo.toml:33–80`](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/crates/lakekeeper/Cargo.toml#L33-L80): direct unconditional `azure_core`, `azure_storage`, `azure_storage_blobs`, and IO with all three cloud storage features. `s3-signer` gates aws-sigv4, not the whole S3 SDK path. |
| Existing IO features | [`io/Cargo.toml:23–63`](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/crates/io/Cargo.toml#L23-L63): `storage-s3`, `storage-adls`, `storage-gcs` already exist and are default on; `all` also enables memory. `object-store` is a separate optional bridge that selects memory. |
| IO implementation | [`io/src/lib.rs:30–55`](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/crates/io/src/lib.rs#L30-L55) and [`189–199`](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/crates/io/src/lib.rs#L189-L199): modules and `StorageBackend` variants are already cfg-gated. The service layer is not. |
| Service profiles | [`service/storage/mod.rs:1–100`](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/crates/lakekeeper/src/service/storage/mod.rs#L1-L100): unconditional az/gcs modules, reexports and backend imports; tagged `StorageProfile` includes ADLS, OneLake, S3, STACKIT and GCS. Azure/OneLake share Azure machinery; STACKIT is S3-derived. |
| Backend-specific service code | [`storage/az/mod.rs:8–44`](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/crates/lakekeeper/src/service/storage/az/mod.rs#L8-L44) imports Azure SAS/storage clients and IO ADLS types; [`storage/gcs/mod.rs:9–41`](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/crates/lakekeeper/src/service/storage/gcs/mod.rs#L9-L41) imports GCS auth/settings/storage and its STS module. Gate credentials, caches and validation dispatch with these implementations. |
| PostgreSQL re-enables IO | [`lakekeeper-storage-postgres/Cargo.toml:43–51`](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/crates/lakekeeper-storage-postgres/Cargo.toml#L43-L51) depends on Lakekeeper and independently selects all IO backends. Changing the library manifest alone cannot produce an Azure-free executable. |
| Binary forwarding | [`lakekeeper-bin/Cargo.toml:18–41`](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/crates/lakekeeper-bin/Cargo.toml#L18-L41): UI/OpenAPI features and Lakekeeper/PostgreSQL dependencies need matching cloud-feature forwarding. |
| Already disciplined consumer | [`iceberg-ext/Cargo.toml:22–31`](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/crates/iceberg-ext/Cargo.toml#L22-L31) disables IO default features. Preserve this. |

The major backend-specific dependency groups are:

| Backend | Selected dependencies and important transitives |
| --- | --- |
| S3/STACKIT | IO feature selects aws-sdk-s3, aws-config, aws-credential-types, aws-smithy-async/http-client, iceberg and webpki-root-certs. Lakekeeper adds aws-sdk-sts and optionally aws-sigv4. AWS shared HTTP/TLS/auth crates remain shared with other application functionality. |
| ADLS/Azure/OneLake | IO selects azure_core, azure_identity, azure_storage, azure_storage_blobs, azure_storage_datalake, iceberg, moka and time. The service additionally needs Azure SAS/Blob clients. The legacy fork's azure_core 0.21.0 selects quick-xml 0.40.1; azure_storage/blobs/datalake reach it transitively. |
| GCS on main | IO selects google-cloud-auth, google-cloud-gax, google-cloud-storage, base64, http, iceberg, moka, serde_json and tonic (`tls-aws-lc`). Official Google SDK auth/gax/storage bring additional transport/auth support. This differs from 0.13's gcloud-auth/gcloud-storage/token-source/gcloud-token ecosystem. |

These dependency groups come from
[IO's feature/dependency declarations](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/crates/io/Cargo.toml#L23-L105)
and [workspace cloud SDK declarations](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/Cargo.toml#L43-L103).
They are not additive exclusive crate counts: shared dependencies survive when
another selected feature needs them. The direct quick-xml 0.41 path also remains
for S3 DeleteObjects XML; removing Azure cannot remove all quick-xml.

### Azure SDK fork pin and remaining quick-xml

The five Azure workspace dependencies use the same full git revision
`bbdb4946ff486feec05506240358a8e4e9a074e8` in
[`lakekeeper/azure-sdk-for-rust`](https://github.com/lakekeeper/azure-sdk-for-rust/tree/bbdb4946ff486feec05506240358a8e4e9a074e8),
with native TLS defaults disabled and reqwest/rustls selected:
[`Cargo.toml:69–88`](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/Cargo.toml#L69-L88).
The [lock's azure_core entry](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/Cargo.lock#L1159-L1187)
records quick-xml 0.40.1, while the
[two quick-xml entries](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/Cargo.lock#L5589-L5608)
record 0.40.1 and 0.41.0. Updating the workspace's direct quick-xml alone does
not update the fork's separate dependency constraint.

Request a separate fork change to quick-xml >=0.41, validate its XML parsing and
SAS/storage operations, then update all five fork rev pins together and refresh
the lock. Remove the now-unnecessary upstream ignores after all affected copies
are gone. Do not hide advisories while waiting for that work.

## Existing upstream discussion checked first

Read-only searches covered issues and PRs, open and closed, for `quick-xml`,
`optional storage`, `storage-adls`, Azure feature flags, and title searches for
optional Azure/GCS/storage and feature/storage. No dedicated default-on optional
backend proposal was identified in the returned results. Search is not proof
that no discussion exists, and should be repeated before the owner posts.

- [#1885](https://github.com/lakekeeper/lakekeeper/pull/1885), merged: upgraded the
  direct signer quick-xml path to 0.41 and expressly left the Azure fork's 0.40.1
  with RUSTSEC-2026-0194/-0195 ignores. It argues Azure response parsing is not
  attacker input. This proposal does not treat that as a shipped-code exemption.
- [#1689](https://github.com/lakekeeper/lakekeeper/issues/1689), closed tracking
  issue: documents official Azure SDK migration gaps including ADLS, shared-key
  support and identity behavior. Closure does not establish the legacy crates
  are gone: the pinned source still uses them.
- [#1822](https://github.com/lakekeeper/lakekeeper/pull/1822), closed: proposed
  object_store ADLS IO and explicitly noted that Lakekeeper still needed legacy
  Azure dependencies for SAS minting. Replacing IO alone is insufficient.
- [#2064](https://github.com/lakekeeper/lakekeeper/pull/2064) concerns the
  object_store bridge, a related abstraction rather than evidence of optional
  storage at the library boundary.
- [#2159](https://github.com/lakekeeper/lakekeeper/pull/2159), merged: moved GCS to
  the official Google SDK on the newer line. Target that current layout when
  proposing upstream work, and discuss any 0.13 backport separately.
- [#45](https://github.com/lakekeeper/lakekeeper/issues/45), dependency dashboard,
  and [#1807](https://github.com/lakekeeper/lakekeeper/pull/1807), open dependency
  update PR, appeared in the quick-xml search; neither replaces a focused fork
  fix or feature proposal.

## Proposed feature contract

At the library layer, make the existing direct Azure dependencies optional,
remove unconditional IO cloud features, and disable IO defaults on that edge.
Keep IO S3 selected; add default-on `storage-adls` and `storage-gcs` forwarding.
`storage-adls` includes both ADLS and OneLake. `storage-gcs` includes GCS IO and
all SDK-dependent credential/STS implementation. Keep existing default
`s3-signer`/`router`; preserve `all` as a superset that also includes both clouds.
Do not conflate `s3-signer` with selecting S3 storage.

Apply the same default-on forwarding to PostgreSQL and the binary, using
`default-features = false` on internal edges wherever otherwise they would
re-enable clouds. Preserve existing SQL/router/OpenAPI requirements explicitly.
Audit integration tests, event/secrets/authz crates and every other Lakekeeper/IO
consumer: Cargo features are additive, so one unnoticed default-enabled edge
undoes the consumer's opt-out. Check resolved normal dependencies, not merely
whether the root manifest says `default-features = false`.

Suggested downstream library selection once implemented:

```toml
lakekeeper = { version = "<release-containing-features>", default-features = false, features = ["router", "s3-signer"] }
```

SDK-independent wire/profile DTOs should retain stable serde tags and database
representations. Split DTOs from SDK-backed operations where necessary. Gate
Azure/GCS modules, credential implementations, STC caches, location conversions,
validation dispatch and OpenAPI references consistently. Keep all-default schemas
unchanged; reduced builds should advertise only usable capabilities and document
how disabled-profile payloads are rejected. Avoid runtime boolean switches that
still link the SDKs.

### Compile-time and runtime errors

For Rust consumers, gate backend-specific operational types/constructors behind
the corresponding feature. Referencing an Azure/GCS implementation without its
feature must fail compilation, with documentation and compile-fail tests naming
`storage-adls`/`storage-gcs`. If a future static profile macro or configuration
embedding API selects a disabled backend, emit a clear `compile_error!` naming
the feature. Do not invent such a macro merely for this proposal.

A JSON profile received over REST or loaded from PostgreSQL is unknown at
compile time. It **cannot** produce a compile-time error. Retain an SDK-free
profile discriminator and validate it before backend construction, network IO,
credential access or persistence. Return an explicit error such as
`StorageBackendNotCompiled: adls requires Cargo feature storage-adls`, naming the
build capability but never credentials. Reject ADLS, legacy `azdls`, OneLake and
GCS consistently when disabled. Do not fall back to S3 or silently ignore them.
At startup, reject any warehouse set the configured reduced binary cannot serve
with a clear diagnostic identifying unsupported warehouse IDs/types. Repeat the
check on persisted profile load and incoming create/update/validation paths.
This covers a database modified later by another default-feature instance.

## Compatibility and tests

Default builds keep backend support, HTTP/JSON/database formats, migrations,
credential protections and existing authz behavior unchanged. All-features
release archives remain feature complete; a smaller official release artifact
would be a separate packaging decision. S3-only custom builds are deliberately
incompatible with Azure/GCS warehouses at runtime, with explicit errors rather
than corruption. Do not delete stored credentials or rewrite profiles. A
reduced-build deployment requires checking its warehouses first and retaining
a default-build rollback artifact.

Tests should cover default/all-features parity, library and executable builds
with both clouds disabled, ADLS-only, GCS-only, and both enabled. For each reduced
build, check resolved target dependencies and assert the disabled SDK packages
are absent. Include a downstream fixture that links both Lakekeeper and its
PostgreSQL backend, catching accidental feature re-enablement.

Add compile-fail tests for disabled operational APIs, JSON/legacy-tag rejection,
startup/read rejection of existing disabled profiles, management create/update/
validation errors, and unchanged enabled-profile serialization/OpenAPI. Exercise
ADLS and OneLake together, GCS token expiry/downscoping, S3 signing and data
round trips, secret/log exclusion and credential validation. Shared DTOs should
not accidentally depend on a removed SDK type or change stored secret formats.

## CI cost, size and attack surface

Retain upstream default/all-features unit, integration and cloud jobs. Add small
feature-selection compile/test fixtures for the four Azure/GCS combinations,
with selected OpenAPI/router/signer toggles; do not multiply every expensive
cloud integration suite by the feature powerset. Run existing live Azure/GCS
suites on cloud-enabled builds only, and require explicit negative assertions in
cloud-disabled builds. Existing GCS secret-dependent qualification is visible in
[`unittests.yml:280–335`](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/.github/workflows/unittests.yml#L280-L335)
and [`472–474`](https://github.com/lakekeeper/lakekeeper/blob/21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c/.github/workflows/unittests.yml#L472-L474).
Keep security scans over shipped crates blocking and report host/build-only
crates separately. An all-features cargo-audit failure must not become a reason
to ignore findings in reduced builds or vice versa.

Expected benefit: remove unused cloud SDK/auth/XML implementation code and
its future advisory obligations from S3-only deployments. Shared HTTP/TLS/crypto
and direct S3 quick-xml survive, so no claim of removing all XML/crypto or all
Azure-related transitive code is justified without measuring the final graph.
Code removal reduces potential attack surface; it does not demonstrate current
exploitability or make the default release clean.

No size delta is claimed. Features do not yet exist at the library boundary;
a comparison would require implementing the proposal and compiling variants.
This task's CI-first policy forbids local builds, and this docs PR adds no
experimental upstream build jobs. Once implemented upstream, build identical
commit/toolchain/target/profile variants in CI, retain their feature/unit graphs
and SBOMs, and compare uncompressed ELF, stripped ELF (analysis copy only),
compressed archive bytes, target crate count, advisory count, build time and
peak memory. Measure native amd64 and arm64 separately; shared dependencies and
link-time optimization make dependency-count estimates unreliable size claims.

## Small reviewable upstream steps

1. Land the Azure fork's quick-xml fix and coordinated rev/lock update separately,
   with XML compatibility tests and no advisory exemptions.
2. Split SDK-free profile/credential DTOs from backend operations, preserving all
   default behavior and schemas. Add parity tests before feature work.
3. Introduce default-on ADLS forwarding end to end, gate Azure/OneLake code and
   add absence/negative/profile-load tests. Review this independently from GCS.
4. Repeat for GCS against the current official SDK; retain S3 baseline and
   existing defaults. Add the downstream PostgreSQL consumer fixture.
5. Add the bounded CI matrix, capability/error documentation and measured size/
   graph evidence. Discuss a 0.13 backport and optional release variants only
   after upstream accepts the contract.

## Draft issue text for owner review

```draft
Title: Make ADLS/Azure and GCS storage optional, default-on Cargo features

Thank you for Lakekeeper. We embed the library in an S3-only authorization
service and would like to avoid compiling unused cloud storage SDKs.

Could we expose default-on storage-adls and storage-gcs features through the
Lakekeeper library, PostgreSQL backend and binary? lakekeeper-io already has
these features, but the upper layers currently select all backends and the
library also depends directly on Azure crates. Existing default/all-features
builds would keep their behavior. Reduced builds would give compile errors for
disabled operational APIs and explicit errors for disabled JSON/database profiles.

We checked #1885, #1689, #1822 and #2159. Separately, could we update quick-xml in
the pinned Azure SDK fork? #1885 fixed the direct signer path, but azure_core
still selects quick-xml 0.40.1 (RUSTSEC-2026-0194/-0195). Optional features would
help consumers omit unused code; they would not fix Azure-enabled builds.

We can implement this in small PRs, starting with the fork dependency update,
then DTO separation and default-on feature forwarding, with reduced-build,
profile rejection and dependency-absence tests. Would that direction fit your
plans, or is there an existing effort we should join?
```
