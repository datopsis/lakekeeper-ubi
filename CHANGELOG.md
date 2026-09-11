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

- Added separable acquisition and assembly scripts. `scripts/fetch-artifacts.sh`
  downloads the locked release archive and admits it only after its size,
  digest, and member list match; `scripts/verify-bundle.sh` re-checks the bundle
  immediately before assembly; `scripts/build-image.sh` builds without pulling,
  taking the binary from a named build context; and `scripts/build.sh` runs the
  phases in order for local use. The phases are separable because acquisition and
  assembly have different trust properties and, in a controlled network, run on
  different hosts.
- Removed the release-archive download from the container build, and added a
  check that fails if the Containerfile regains the ability to fetch.
- Added `tests/acquisition.sh`, which corrupts a verified bundle one way per case
  and requires the admission gate to refuse each one, including a lock whose
  recorded ELF facts drift from the bytes it names.
- Documented that the secret encryption key is encryption at rest and unrelated
  to TLS, which Lakekeeper does not terminate, along with the threat model it
  actually addresses.

- Made image assembly hermetic. The build runs with no network and no image
  pulling: runtime packages are acquired and digest-verified beforehand, then
  installed with no repository and no dependency resolution, with Red Hat
  signatures checked against the keys already in the base image's RPM database.
- Added `scripts/update-rpm-lock.sh`, which regenerates the runtime package
  manifest as a reviewable lock change rather than resolving dependencies during
  a build.
- Resolved the runtime package set against the UBI Micro RPM database instead of
  an empty root, which is the genuine delta the final stage needs. This removed
  a duplicated base system, reduced the image from 246.6 MB to 228.8 MB, and cut
  the runtime package manifest to 12 packages.
- Extended the admission gate and its negative tests to cover runtime packages,
  including a tampered package, a missing package, an unlocked extra package,
  and a bundle with no packages at all.
- Added a FIPS analysis recording why this image cannot support a FIPS claim,
  and a container minimization analysis measuring where the image's size
  actually is and what each possible reduction would cost.

- Added a crate inventory. Upstream's `Cargo.lock` is acquired from the pinned
  release commit, digest-verified on the same terms as every other input,
  catalogued with Syft, and scanned with Grype report-only, with the counts
  written to the CI job summary. The shipped binary carries no embedded
  dependency metadata, so this is the only inventory of Lakekeeper's own
  dependencies obtainable, and it is the declared graph from source rather than
  a bill of materials derived from the artifact.
- Added `tests/runtime-dependencies.sh`, which asks the dynamic loader to
  resolve the binary inside the assembled image, confirms the name-resolution
  modules glibc loads with `dlopen` are present, validates the TLS trust
  bundle, and confirms time-zone data survived. Static dependency lists cannot
  catch a missing NSS module, which is how a minimized image fails to reach its
  database while passing every other check.
- Documented the hermetic build: what the property is, why it matters, what it
  does not do, and its indicative effect on cybersecurity control areas,
  including the one control it constrains rather than strengthens.
- Added roadmap sections for cybersecurity control documentation and for the
  tailored SCAP scan profile.

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
- Removed `openssl-libs` from the image, and with it the only High vulnerability
  finding, an unfixed OpenSSL QUIC server flaw. The binary links no TLS library,
  so OpenSSL was present only because an empty installroot resolved a full base
  system. The removal was a side effect of resolving the package delta
  correctly, not a targeted exclusion.
- Recorded that the UBI Micro RPM database does not describe its own filesystem:
  it reports `tzdata` as installed while shipping none of its 1872 files. This
  image reinstalls it explicitly. A scanner reading that database can report
  packages whose files are absent, in either direction.
