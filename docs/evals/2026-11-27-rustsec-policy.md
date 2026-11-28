# RustSec policy measurement: 2026-11-27 owner decision

Policy: block **any** advisory on shipped code when `versions.patched` is
non-empty, independent of severity or informational type. Report/track advisories
without patches; report build-only/unselected crates regardless of fix status.
No ignore lists. This changes admission policy, not image bytes or remediation.

The [RustSec schema](https://github.com/RustSec/advisory-db/blob/main/README.md#advisory-format)
defines the patched-version list. For example the
[chrono advisory](https://rustsec.org/advisories/RUSTSEC-2026-0543.html) has no
patched version and recommends alternatives in its text. Neither a replacement
recommendation nor an informational type substitutes for the patched field.

## Real retained cases

Lightweight reclassification of all **48 real shipped findings** (24 per
architecture) and **18 build-only/unselected findings** from
[run 44464460386](https://github.com/datopsis/lakekeeper-ubi/actions/runs/44464460386),
[amd64 artifact 14501828124](https://github.com/datopsis/lakekeeper-ubi/actions/runs/44464460386/artifacts/14501828124),
[arm64 artifact 14501353670](https://github.com/datopsis/lakekeeper-ubi/actions/runs/44464460386/artifacts/14501353670).
These are existing raw cargo-audit reports, not a new local vulnerability scan.
The underlying source is Lakekeeper 0.13.9 at
`a8e013b30e99e5a184486fe166c3ffb3781a7c36`; the reports record RustSec DB
`472a4c9a785030434f15d7da84964d60fbe789ab`.

| Architecture | Shipped RustSec findings | Fixable: BLOCK | No patch: REPORT/TRACK | Build-only/unselected: REPORT |
| --- | --- | --- | --- | --- |
| amd64 | 24 | 21 | 3 | 9 |
| arm64 | 24 | 21 | 3 | 9 |

Per architecture, the blocking group contains 7 vulnerabilities and 14
`unsound` advisories, all with non-empty patched ranges. The three report-only
shipped advisories have empty patched lists:

| Crate | Advisory | Type |
| --- | --- | --- |
| chrono 0.4.45 | RUSTSEC-2026-0543 | unmaintained |
| pin-utils 0.1.0 | RUSTSEC-2026-0441 | unmaintained |
| rustls-pemfile 2.2.0 | RUSTSEC-2025-0134 | unmaintained |

These identities describe the measured data; they are not exemptions or special
cases in the implementation. Both quick-xml advisories remain blocking because
>=0.41.0 is patched. If any currently unpatched advisory gains a patched range,
it automatically becomes blocking while the affected crate remains shipped.
The independent pre-existing yanked-crate control remains; this binary has none.

## Verification boundary

Unit tests cover fixable/no-patch decisions for vulnerability, unsound,
unmaintained, notice and unknown future types; malformed/missing patch data;
unselected and unshipped subjects; and tracking creation, stable-set silence,
new patches, replacement-guidance changes, findings disappearing, duplicate or
incomplete evidence, retry recovery and scheduled-main write restrictions.
Native CI regenerates reports against a fresh DB; future counts may change.

The tracker snapshots all RustSec crate advisories at the scanned DB commit,
including guidance and version data, so previous no-patch identities remain
observable even after they disappear from current findings. Replacement updates
are detected from RustSec text/references, not an inferred list of equivalent
crates or crawling external sites. Unannounced replacements cannot be detected.

No live issue is created by PRs or tests. That behavior is tested with a fake
API; real creation and notification await merge plus scheduled main CI. The
existing scheduled job/permissions are reused, with no settings changes. Image
builds, scans and native runtime suites run only in GitHub Actions; their fresh
results and artifacts are recorded in PR #28 after review.

## Fresh native verification (2026-11-28)

[Run 46086362264](https://github.com/datopsis/lakekeeper-ubi/actions/runs/46086362264),
head `c36363a885a597d9040cf15b73676527944a4bbe`, regenerates the raw audits and
policy decisions against RustSec DB `c5279d0b0c9e8b70df666eb6d1edbabcfd1176bd`.
[amd64](https://github.com/datopsis/lakekeeper-ubi/actions/runs/46086362264/artifacts/15240165492)
and [arm64](https://github.com/datopsis/lakekeeper-ubi/actions/runs/46086362264/artifacts/15239657922)
retain `security-results/rustsec/{policy.json,shipped.json,advisory-catalog.json}`
and all previous provenance/inventory evidence.

| Architecture | Original 24: blocking / report-only | Fresh total | Fresh blocking | Fresh report/track | Build-only reports |
| --- | --- | --- | --- | --- | --- |
| amd64 | 21 / 3 | 27 | 24 | 3 | 9 |
| arm64 | 21 / 3 | 27 | 24 | 3 | 9 |

The additional three findings are **new fixable advisories**, not a change to
classification of the original 24:

- kube-client 4.0.0: RUSTSEC-2026-0600
- url 2.5.8: RUSTSEC-2026-0592
- parquet 58.3.0: RUSTSEC-2026-0595 (`unsound`, still blocks because patched)

Both native jobs fail only at the intended RustSec gate; existing native image,
scanner, UBI gate, smoke, storage and TLS checks pass. No Python traceback or
infrastructure exception was substituted for advisory detection. The tracker
validated both real native inputs and generated a six-row initial issue preview
(three no-patch advisories across two architectures), including chrono's
replacement guidance. Re-rendering an unchanged set retained its fingerprint.
This preview was local, read-only evidence validation; no issue API write or
local vulnerability scan ran. Scheduled issue creation remains unverified until
merge and scheduled main CI, as required by the write restriction.
