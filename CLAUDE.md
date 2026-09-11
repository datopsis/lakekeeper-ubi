# CLAUDE.md

This file provides guidance to coding agents working in this repository.

## Project overview

This repository builds a security-oriented, rootless Lakekeeper container on
Red Hat UBI 9. Lakekeeper is an Apache Iceberg REST catalog. The intended uses
include serving the Iceberg REST catalog API to query engines, managing
warehouse and namespace metadata in PostgreSQL, vending storage credentials,
and operating in controlled networks.

Preserve these non-negotiable properties:

- the final image is based on a digest-pinned Red Hat UBI 9 image;
- the final runtime has no package manager;
- Lakekeeper starts and remains non-root, with no entrypoint privilege
  transition;
- the default listeners use unprivileged ports;
- the image supports a read-only root filesystem with no writable path required
  by the default profile;
- the runtime needs no Linux capabilities and enables `no-new-privileges` in
  documented deployments;
- the upstream release binary is admitted only after its archive digest and
  extracted binary digest match `artifacts/lakekeeper.lock.json`;
- database credentials, the secret encryption key, object-store credentials,
  and identity-provider configuration are supplied by the operator at runtime
  and never baked into the image or an example;
- the image refuses to start without a secret encryption key unless an
  operator explicitly opts out, and the opt-out stays available and
  documented;
- CI produces reviewable vulnerability, SBOM, and tailored SCAP evidence;
- release images are multi-architecture, immutable, attested, and signed;
- documentation does not claim FIPS validation, STIG certification, or broad
  platform support without matching qualification evidence.

The first release boundary and ordered work packages are defined in
`docs/ROADMAP.md`. Version rules are defined in `docs/VERSION.md`.

## Upstream characteristics that change how this project works

Lakekeeper differs from this organization's RPM-based UBI images in ways that
must not be papered over:

- **There is no RPM and no vendor signature.** Upstream publishes only release
  tarballs on GitHub, without a detached signature or a checksum file. The
  digests in `artifacts/lakekeeper.lock.json` are this project's reviewed
  record of exact bytes, not proof of publisher identity. Treat that as a
  stated trust limitation, documented in `docs/ARTIFACT-ACQUISITION.md`, and
  never describe it as equivalent to vendor-signed package provenance.
- **Upstream is pre-1.0.** A `0.x` minor bump may contain breaking changes.
  Never assume minor upgrades are compatible; qualify each one.
- **`serve` requires an already-migrated database.** Migration is a separate
  `migrate` invocation, not a server startup side effect. Do not introduce an
  entrypoint that silently migrates, because that gives a running server the
  authority to rewrite schema.
- **PostgreSQL is a required external dependency**, version 15 or newer, with
  the `uuid-ossp`, `pgcrypto`, `pg_trgm`, `btree_gin`, and `btree_gist`
  extensions. Image tests need a real database fixture.
- **The service holds secrets.** `LAKEKEEPER__PG_ENCRYPTION_KEY` protects
  stored storage credentials. Upstream gives it a publicly known default and
  only warns when it is unset, so this image adds a fail-closed guard in its
  entrypoint, controlled by `LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY` and
  documented in `docs/CONFIGURATION.md`. The key must never appear in an
  example, a committed fixture, a log line, or an error message. Variables this
  packaging adds use the `LAKEKEEPER_UBI_` prefix so they can never collide
  with the upstream `LAKEKEEPER__` namespace.

## Development and verification

Use Podman for the primary local workflow where it is available. Docker
compatibility is tested independently and is not evidence of identical Podman
or OpenShift behavior.

For image-affecting work, verification must cover at least:

- the configured runtime identity is non-root;
- the running processes remain non-root;
- startup succeeds with a read-only root filesystem;
- startup succeeds with all capabilities dropped and `no-new-privileges`
  enabled;
- the catalog answers its health, management, and Iceberg REST endpoints
  against a real PostgreSQL instance;
- the reported server version matches the locked upstream version;
- missing or invalid required configuration fails with a useful diagnostic
  rather than starting in a degraded state;
- the entrypoint execs, so the server runs as PID 1 and receives signals
  directly, and no entrypoint phase changes user or group;
- secrets do not appear in logs, error bodies, or image layers;
- both supported architectures receive native-runtime evidence before a
  supported release.

Generated SBOM, SARIF, SCAP result, certificate, private-key, and scanner-cache
files must not be committed. Downloaded release archives and extracted binaries
must not be committed. Retain release evidence in CI, the OCI registry, or
GitHub Releases as defined by the roadmap.

## Security and documentation conventions

Treat examples as deployable security guidance. Examples must not contain
default passwords, embedded encryption keys, embedded object-store credentials,
permissive catch-all trust, disabled certificate verification, world-writable
directories, or a root runtime.

Keep product behavior separate from deployment responsibility. Clearly state
which controls belong to the image, the container runtime, the orchestrator,
the database, the object store, the identity provider, the network boundary,
and the operator.

SCAP results describe only the selected rules, content version, scanner
version, target filesystem, architecture, and configuration that were
evaluated. Never translate a passing tailored scan into a claim that the image
or deployment is STIG certified.

When adding a use case, add or update its automated test, example
configuration, operational guidance, security considerations, and support
classification together.

## Git conventions

Keep changes small and reviewable. Prefer one dependency-ordered roadmap
increment per pull request. Start work from current `main`, require protected
checks before merge, and do not force-push or move release tags.

Use concise Conventional Commit subjects such as `feat:`, `fix:`, `docs:`,
`test:`, `ci:`, `build:`, `refactor:`, and `chore:`.

Do not add `Co-Authored-By`, AI, assistant, or tool-attribution trailers to
commit messages. Commits are the human-reviewed record of intent; tool
attribution belongs in tool logs.

Container release tags and repository revisions are intentionally distinct.
Do not create a source-only release or tag for documentation, test, policy,
development-tool, or analysis-workflow changes. Follow `docs/VERSION.md`.
