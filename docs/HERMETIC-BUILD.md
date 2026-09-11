# Hermetic build

The image is assembled with no network access. Every byte that enters it comes
from a local bundle that was verified against `artifacts/lakekeeper.lock.json`
before the build started, or from a digest-pinned base image.

This document explains what that property is, what security value it has, and
which controls it does and does not support. The last part matters most: a
control that is claimed too broadly is worse than one that is not claimed.

## What "hermetic" means here, concretely

Three separate phases, with different trust properties:

| Phase | Network | What it does |
| --- | --- | --- |
| Acquisition | Yes | Downloads exactly what the lock names |
| Verification | No | Admits bytes only if they match the lock |
| Assembly | **No** | Builds from admitted bytes alone |

Assembly runs with `--network=none` and `--pull=never`. Concretely, the build:

- downloads nothing;
- contacts no package repository and reads no repository metadata;
- performs no dependency resolution, so no version can be chosen at build time;
- installs a fixed list of packages recorded in reviewed repository content;
- verifies Red Hat package signatures against keys already present in the base
  image; and
- fails if the bundle is absent, incomplete, altered, or carries anything the
  lock does not name.

The Containerfile is checked for the absence of a fetch or a package-resolution
command, so the build cannot quietly regain either capability.

## Why this matters

**It makes the image a function of reviewed inputs.** Before, two builds of the
same commit could produce different images, because dependency resolution
happened during the build and upstream repositories change. The commit did not
determine the artifact. Now it does, together with the lock.

**It moves version selection into review.** Choosing a package version is now a
pull request against the lock, with a diff, an author, and a reviewer. It is no
longer a side effect of when a build ran.

**It removes build-time trust in availability.** A repository outage, a
hijacked mirror, or a poisoned cache cannot alter a build that does not talk to
one. This does not make the supply chain trustworthy; it narrows the window in
which it must be trusted to the moment of acquisition, which is a reviewed and
recorded event.

**It makes tampering detectable rather than silent.** The admission gate
rejects an altered binary, an altered package, an extra unlocked package, and a
bundle left over from an earlier lock. Each rejection is exercised by a test,
because a gate that has never been observed to reject is not evidence.

**It is what makes controlled-network deployment possible at all.** Acquisition
and assembly run on different hosts. A disconnected environment can receive a
bundle, verify it independently, and build without ever reaching the internet.

## What it does not do

Be precise, because this is where over-claiming starts:

- **It is not reproducibility.** Two hermetic builds of the same inputs still
  produce different image digests: timestamps, file ordering, and layer
  metadata vary. Reproducible builds are a separate, unaddressed property.
- **It does not establish publisher identity for the application.** Upstream
  Lakekeeper publishes no signature and no attestation for its release binary,
  and none exists to verify. The lock records the exact bytes this project
  reviewed; it does not prove who produced them. The runtime RPMs are different:
  those carry Red Hat signatures, which the build does verify.
- **It does not validate the contents of what was admitted.** A hermetic build
  faithfully installs whatever the lock names, including a vulnerable version.
  Hermeticity is an integrity property, not a quality one.
- **It says nothing about runtime security.** The image still has to be run
  non-root, read-only, with capabilities dropped, and with an encryption key
  set. Those are separate controls with separate evidence.
- **It does not cover the base images.** Those are pulled by digest, which
  fixes their content, but they are not part of the verified bundle.

## Effect on cybersecurity controls

This project has not yet built its authoritative requirement register, so the
mapping below is **indicative, not assessed**. It names control areas and states
what evidence exists today. Nothing here is a compliance claim, and no control
identifier is cited, because citing one implies an assessment that has not
happened. Producing the assessed mapping is a roadmap item.

| Control area | Effect | Evidence available today |
| --- | --- | --- |
| Software integrity verification | Strengthened. Inputs are admitted only on a digest match, and package signatures are verified at install | The lock, the admission gate, and its negative tests |
| Supply-chain protection | Strengthened. Version selection is a reviewed change, not a build-time event | Lock history in Git, pull request review |
| Configuration and change control | Strengthened. The artifact is now determined by reviewed content rather than by build timing | Lock diffs, `artifact lock` CI check |
| Least functionality | Partially supported. The final image has no package manager and no build tooling | Smoke suite asserts the absence of package managers |
| Component inventory | Partially supported. Runtime packages are fully enumerated; the application's crate inventory is declared rather than derived | SPDX SBOM, crate inventory, and their stated limitations |
| Vulnerability management | Unchanged by hermeticity. Scanning is a separate control | Trivy and Grype results per architecture |
| Flaw remediation | Slightly constrained. Updating a package now requires a lock change, which is the intended trade | Lock update procedure |
| Non-repudiation of build inputs | Partially supported. The lock records what was admitted; it does not prove who published it | Recorded digests, and the stated absence of upstream signatures |

Two honest qualifications:

1. **Hermeticity constrains flaw remediation slightly.** A package update is no
   longer automatic; it needs a lock change and a review. That is the point, but
   an assessor should see it stated rather than discover it. The compensating
   control is the lock-update procedure and monitored update proposals.
2. **A hermetic build can still produce a vulnerable image.** These controls
   address integrity, not currency. Anyone reading "hermetic" as "secure" has
   read too much into it.

## Where this is verified

| Property | Checked by |
| --- | --- |
| The Containerfile cannot fetch or resolve packages | `.github/scripts/check_artifact_lock.py` |
| The build args match the lock | `.github/scripts/check_artifact_lock.py` |
| Admitted bytes match the lock | `scripts/verify-bundle.sh`, run after acquisition and again before assembly |
| The gate rejects tampering | `tests/acquisition.sh` |
| The assembled image satisfies the binary | `tests/runtime-dependencies.sh` |
| The image behaves correctly at runtime | `tests/smoke.sh` |

CI runs all of these on both supported architectures.
