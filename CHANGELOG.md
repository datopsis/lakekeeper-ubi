# Changelog

All notable changes to this project are recorded in this file.

The project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
but container releases use the upstream-derived format documented in
`docs/VERSION.md` rather than Semantic Versioning.

## [Unreleased]

### Added

- Added the Apache License 2.0 for Datopsis-authored work, third-party notices,
  contribution guidance, and a private vulnerability-reporting policy.
- Added Code Owners, a security-aware pull request template, and structured
  public bug-report and private security-reporting routes.
- Established repository guidance for secure, rootless image development and
  review, including the upstream characteristics that make this project differ
  from the organization's RPM-based UBI images.
- Defined the forward-looking first-release roadmap and evidence lifecycle, with
  PostgreSQL as the only catalog backend and warehouse storage, authentication,
  authorization, and event publishing explicitly deferred.
- Defined independent versioning for container releases and repository-only
  revisions, adopted Lakekeeper-version, UBI-major, and UTC release-date
  versioning, prohibited mutable convenience tags, and recorded a pre-1.0
  upstream upgrade policy.
- Added the project overview, intended uses, security design, operator
  responsibilities, rootless runtime model, and release status.
- Added an initial package-manager-free UBI 9 Micro development image built from
  the digest-verified upstream Lakekeeper release binary.
- Added a reviewed artifact lock recording the upstream release tag, archive and
  binary digests, sizes, GNU build IDs, interpreter, highest required glibc
  symbol version, and needed shared libraries for both architectures.
- Added a configuration guide covering the variables this image adds, the
  fail-closed encryption-key contract, the command allowlist, and the explicit
  limits of the guard.
- Added a hardened Compose development stack with a separate one-shot migration
  unit and no default credentials.
- Added a restricted-runtime smoke suite that provisions its own PostgreSQL
  fixture and per-run credentials, and asserts non-root operation, zero
  effective capabilities, `no-new-privileges`, arbitrary-UID operation,
  operation with no writable mount at all, the catalog and management
  endpoints, structured logs, secret non-disclosure, graceful shutdown, and
  actionable negative startup cases.
- Added an artifact-lock consistency check and a runtime-requirement check that
  fails when the shipped binary needs a higher glibc symbol version or a
  different shared-library set than the locked base image provides.
- Added pinned local pre-commit checks for repository hygiene, shell code,
  container build files, GitHub Actions, private keys, and attribution trailers.
- Added least-privilege CI, CodeQL Actions, Trivy configuration, Zizmor, and
  OpenSSF Scorecard workflows with immutable third-party Action references.
- Added grouped Dependabot updates for Actions, pre-commit hooks, and the
  hash-locked CI Python environment.
- Documented the source-independent acquisition, verification, and hermetic
  assembly contract, and stated plainly that upstream publishes no signature or
  checksum file so recorded digests are not publisher verification.

### Security

- Made the image fail closed when the secret encryption key is unset. Upstream
  Lakekeeper starts with a publicly known default key and only warns, so a
  deployment can look healthy indefinitely while every stored storage
  credential is decryptable by anyone reading public source. The container now
  refuses to start in that state, exiting `78` (`EX_CONFIG`) with a diagnostic
  that names the variable and never echoes its value.
- Made that behavior configurable through `LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY`,
  which defaults to `true`. Setting it to `false` restores upstream behavior as
  a deliberate, reviewable choice. An unrecognized value is a startup failure,
  so a misspelled toggle cannot quietly disable the control.
- Kept informational subcommands usable without a key, so a container the guard
  refuses to start remains diagnosable. Any unrecognized subcommand, including
  one added by a future upstream release, is treated as requiring the key.
- Documented what the guard does not do: it checks presence rather than
  strength, it cannot undo exposure from a period when no key was set, and an
  operator who overrides the entrypoint bypasses it.
- Recorded the `allow-all` default authorization backend and the pre-bootstrap
  window as deployment-critical operator responsibilities.
