# RustSec gate and 0.13.9 upgrade

The shipped release is 0.13.9, not 0.15.x. No Lakekeeper source is patched.
Trivy, Grype, the UBI installable-fix policy, required job names and runtime
hardening remain unchanged. A separate RustSec gate blocks every vulnerability
and advisory warning in the reconstructed shipped crate inventory, including
advisories without CVE aliases. There are no advisory ignores or exemptions.

## Inventory and trust boundary

Both locked 0.13.4 and 0.13.9 Linux binaries were downloaded, their archive
hashes compared to GitHub asset metadata, and their ELF sections inspected on
2026-11-19. Neither architecture has `.dep-v0` cargo-auditable metadata.
The archives have no publisher signature. SHA-256 pins establish exact bytes,
not independent publisher identity or reproducible source-to-binary provenance.

Consequently CI reconstructs the dependency selection from the exact release
commit, exact Cargo.lock, upstream nightly pin, RUSTFLAGS and release command:
`cargo build --all-features --release --locked --target <native target>`.
Cargo's `--unit-graph` resolves this command without compiling Rust or executing
build scripts. It distinguishes target/host units and feature selections.
Traversal begins at the shipped `lakekeeper` executable and stops at build
scripts and proc macros, including their dependency subtrees. A crate also used
by a target library stays in the blocking set. Unselected, dev-only and host-only
packages from the full lock are reported separately. Inventory lockfiles preserve
package name, version, source and checksum; their edges are intentionally omitted
because they are audit inventories, never build inputs.

This is source-based reconstruction under upstream's published build recipe,
not artifact-derived proof. Embedded metadata appearing in a future artifact
fails this fallback closed so it can be replaced with a direct binary audit.
Missing roots, unknown package identities, lock drift, fetch failures, malformed
reports and tool failures block; none can be treated as a clean result.

`artifacts/cargo-audit.lock.json` pins official cargo-audit 0.23.0 prebuilt
archives for both native architectures by SHA-256 from GitHub asset metadata.
The tool is not compiled. It runs outside upstream's source directory so the
upstream ignore configuration is not applied. A fresh RustSec DB is cloned per
scan, and both inventories use the same recorded DB commit. All severities and
warnings are blocking for shipped code, regardless of CVE alias or fix status.
Yanked crates are checked too. Full JSON, stderr, unit graph, metadata, both
inventory locks, ELF sections and provenance are retained under
`security-results/rustsec/` in each native image-security artifact.

Historical 0.13.4 evidence is generated separately under
`security-results/rustsec-historical/` from its pinned archive, source and lock.
Its findings are historical reports, not admission decisions for the new image;
failures to produce the evidence still fail the job. Only the current shipped
0.13.9 inventory determines the new RustSec gate. The existing full-lock
Syft/Grype inventory remains report-only and retained as before.

## quick-xml exposure

The exact locks for 0.13.4 (`9bd377162345b64a716f0a4fcffe4e7e7f3c7534`),
0.13.9 (`a8e013b30e99e5a184486fe166c3ffb3781a7c36`) and researched main
(`21c94e7f597f61dbf9a3d7dad125c1bd66d0b87c`) each contain quick-xml 0.40.1
and 0.41.0. `azure_core` 0.21.0 uses 0.40.1; Lakekeeper's direct signer XML
path uses 0.41.0. Azure is an unconditional Lakekeeper dependency and ADLS is
selected by the release's all-features build. Therefore 0.40.1 is in the
shipped source dependency set, even when an operator configures only S3.

[Upstream PR #1885](https://github.com/lakekeeper/lakekeeper/pull/1885)
explicitly describes this remaining Azure dependency and its upstream advisory
ignores. We do not adopt its reachability exemption. The two HIGH advisories
[RUSTSEC-2026-0194](https://rustsec.org/advisories/RUSTSEC-2026-0194.html) and
[RUSTSEC-2026-0195](https://rustsec.org/advisories/RUSTSEC-2026-0195.html)
concern CPU and namespace-allocation denial of service, respectively, and require
quick-xml >=0.41.0. Library presence is not a demonstration of an exploitable
Lakekeeper endpoint. It is sufficient to block under the shipped-code rule.
**The new gate is expected to stay red until upstream fixes shipped code.**

## Existing scanner gap: actual baseline reports

[CI run 43428926884](https://github.com/datopsis/lakekeeper-ubi/actions/runs/43428926884)
passed both native jobs. Its retained report artifacts are
[amd64 14040026111](https://github.com/datopsis/lakekeeper-ubi/actions/runs/43428926884/artifacts/14040026111),
[arm64 14040425144](https://github.com/datopsis/lakekeeper-ubi/actions/runs/43428926884/artifacts/14040425144)
and [crate inventory 14039515035](https://github.com/datopsis/lakekeeper-ubi/actions/runs/43428926884/artifacts/14039515035).
Each Trivy image report has only the redhat OS target (15 findings); each
Grype image report has 18 matches. Neither image report contains quick-xml or a
RustSec ID. The full-lock Grype report has 12 matches and no quick-xml match or
RustSec ID, despite the Syft inventory including quick-xml 0.40.1.

Thus the current gate did not detect these CVE-less RustSec advisories in this
actual evidence. This does not claim that every future Trivy/Grype version or
feed is incapable of matching any CVE-less advisory. Image binary inventory
absence and feed coverage are distinct gaps; scanning the source lock alone
did not close either admission gap. The added native RustSec reports provide
the independent positive detection control.

## Security-relevant changes since 0.13.4

These are release-note claims, not fresh exploit tests:

| Release notes | Security-relevant changes |
| --- | --- |
| [0.13.5](https://github.com/lakekeeper/lakekeeper/releases/tag/v0.13.5) | rustls 0.23.45 and chacha20 0.10.2 dependency updates; notes do not identify advisory IDs. |
| [0.13.6](https://github.com/lakekeeper/lakekeeper/releases/tag/v0.13.6) | Identity-specific private/cache-vary responses; non-ASCII data-access panic fix; IO connect timeouts and bounded batch-delete memory; tighter S3 signing behavior. |
| [0.13.7](https://github.com/lakekeeper/lakekeeper/releases/tag/v0.13.7) | S3 remote-signing/copy and expired-metadata deletion constrained to table locations; unknown signing headers/parameters and mismatched encryption keys refused; legacy external data-path properties rejected; connection-pool exhaustion reduction; rustls/quinn-proto/xxhash-rust fixes for RUSTSEC-2026-0338–0342, -0346–0349 and GHSA-6g2r-675j-hx59. |
| [0.13.8](https://github.com/lakekeeper/lakekeeper/releases/tag/v0.13.8) | Correct GCS vended-token expiry; webpki/ctutils/tokio updates and crypto-bigint removal for RUSTSEC-2026-0381–0383 and -0385–0387. |
| [0.13.9](https://github.com/lakekeeper/lakekeeper/releases/tag/v0.13.9) | libz-sys 1.1.31 for RUSTSEC-2026-0418; zstd-sys/async-compression updates; sqlx cancelled-BEGIN transaction fix; Azure workload-identity credential refresh; no reuse of read signatures. |

0.13.9 also adds upstream ignores for remaining zstd advisories, build-only zip
(RUSTSEC-2026-0429), parquet/thrift (RUSTSEC-2026-0435), and unmaintained
pin-utils (RUSTSEC-2026-0441). **Ignores are not security fixes** and are not
inherited by this gate. CI reports the full current advisory set and its exact
compiled/build-only classification rather than assuming these changes make the
release clean.

## Why 0.15 is a separate decision

[0.15.0](https://github.com/lakekeeper/lakekeeper/releases/tag/v0.15.0) changes
OpenFGA privileges/model enforcement, view security/credentials, audit records
(format 1.1), GCS to Google's official SDK, caches and task-worker behavior.
It includes breaking behavior and upgrade instructions. Read those alongside
[0.15.1](https://github.com/lakekeeper/lakekeeper/releases/tag/v0.15.1), which
adds console/managed-warehouse changes, listing/purge/concurrency corrections,
GCS HNS fixes and quinn-udp's RUSTSEC-2026-0538 update. A pre-1.0 minor jump
requires owner approval and requalification, including the authz library's
integration. It is outside this patch upgrade.

## Qualification

Local checks are lint, unit tests, YAML validation and LF checks only. No image
build, vulnerability scan or native runtime suite runs locally. The existing
GitHub Actions jobs supply all build/scan/native evidence; their exact results
and any unresolved failures are recorded in the PR. Both new binaries were
measured to require at most glibc 2.34 and the unchanged libc/libm/libresolv/
libgcc_s/loader set. The published default encryption key is unchanged in source;
CI retains the existing guard, hardening, provenance, smoke, S3 and TLS tests.
Source review found a pre-existing guard limitation: upstream's
`DEFAULT_ENCRYPTION_KEY` includes surrounding angle brackets, whereas this
repository's `UPSTREAM_DEFAULT_KEY` literal does not. The guard's known-value
comparison therefore does not cover that exact upstream literal. Its missing-key
check remains in place. This PR leaves the guard/tests unchanged as requested;
this finding requires follow-up and must not be represented as qualified
rejection of upstream's exact default.
The older TLS qualification record remains historical 0.13.4 evidence, not
qualification of 0.13.9.

## Separate 0.15.1 evaluation

The report under [docs/evals](evals/lakekeeper-0.15.1.md) concerns an unshipped
candidate, not a version upgrade. The explicit `--evaluate-0151` mode uses a
separate pinned manifest and report directory. Its findings are report-only;
errors still fail the step. The default shipped 0.13.9 gate is unchanged and
remains blocking with no ignores. Candidate evidence cannot admit image bytes.
