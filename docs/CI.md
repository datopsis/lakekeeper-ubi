# Continuous integration

The automation protects repository, workflow, and container development. A
green job represents only checks that have an implemented target and an
inspectable result; planned controls are not represented as passing jobs.

## Current workflows

| Workflow | Triggers | Current purpose |
| --- | --- | --- |
| `CI` | Pull requests, `main`, weekly, manual | Run pinned repository checks, audit Actions, scan configuration, verify the artifact lock, and build, test, inventory, and scan native AMD64 and ARM64 images. |
| `Update RPM lock` | Pull requests changing the Containerfile or resolver, manual | Resolve both architectures with the pinned UBI bases and retain a proposed RPM lock and diff for review. |
| `CodeQL` | Workflow changes, `main`, weekly, manual | Analyze GitHub Actions with the security-extended query suite. |
| `OpenSSF Scorecard` | `main`, branch-protection changes, weekly, manual | Publish repository supply-chain findings and SARIF. |

Workflow permissions default to read-only. A job receives a write scope only
when it must publish code-scanning results or, for the scheduled-only tracker,
update its issue. The Scorecard job also receives an OIDC token for authenticated
result publication. Third-party Actions are pinned to full commit SHAs and are
tracked by Dependabot.

## Local repository checks

Install the hash-locked pre-commit environment with Python 3.13 or a compatible
Python version:

```console
python -m pip install --require-hashes --only-binary=:all: \
  --requirement .github/requirements/pre-commit.txt
pre-commit install --install-hooks
pre-commit run --all-files --show-diff-on-failure
/usr/bin/python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The policy tests require the operating system's native RPM Python bindings.
On the Ubuntu CI runners, install `python3-rpm` and use `/usr/bin/python3` as
above; a separate virtual environment may not expose those system bindings.

The configured hooks check text normalization, YAML and JSON syntax, merge
markers, unsafe or broken symlinks, oversized files, private keys, shell code,
container build files, GitHub Actions, and prohibited co-author trailers.

The `commit-msg` hook applies only after `pre-commit install` installs the
configured hook types. CI separately evaluates repository files but cannot
retroactively validate a local commit message that was never pushed.

## Artifact lock verification

To refresh runtime RPMs locally, run `scripts/update-rpm-lock.sh` with Podman.
When local containers are unavailable, the `Update RPM lock` workflow runs the
same command on GitHub. Download its `rpm-lock-<commit>` artifact, review
`rpm-lock.patch`, and copy the generated `artifacts/lakekeeper.lock.json` into
the checkout. Commit the reviewed proposal and require ordinary CI on that
commit. The workflow has read-only permissions and does not commit changes or
provide human approval. Base pins must first match in the Containerfile and
lock; the upstream binary and crate inventory remain independently pinned.

`artifact lock` runs `.github/scripts/check_artifact_lock.py`, which fails when
the build arguments in `Containerfile` drift from
`artifacts/lakekeeper.lock.json`. The lock is the reviewed record of which bytes
may enter an image, so a Containerfile that disagrees with it can consume an
input nobody approved.

Inside the image job, `tests/check-runtime-requirements.sh` extracts the shipped
binary and the runtime's own `libc.so.6` from the built image and fails when:

- the binary requires a higher glibc symbol version than the base image
  provides;
- the measured glibc requirement disagrees with the lock; or
- the binary's needed shared libraries disagree with the lock.

Upstream builds its release binaries on a different distribution than UBI, so
this check is what keeps a future upstream release from producing an image that
builds cleanly and then fails to start.

## Local Podman development

Rootless Podman under native Linux or WSL2 is the primary local container
workflow. Before relying on a result, record both client and engine details:

```console
podman version
podman info
```

Podman Desktop or a remote Podman machine can run a container process as a
non-root UID while its Linux VM engine itself operates rootfully. That proves
the image's non-root process behavior but does not qualify rootless-host user
namespace behavior. Release evidence will distinguish these cases.

Build the database first with `bash scripts/build-postgres.sh`. This uses the
single reviewed SHA in `artifacts/postgresql-lakekeeper.commit`, invokes the
database repository's own offline build script, and verifies source/image
revision, RPM lock digest, and native architecture. `POSTGRES_IMAGE` overrides
the local tag for both the wrapper and test suites.

The smoke and storage suites create their own networks, hardened PostgreSQL
fixtures, secret-file credentials and volumes, then remove them. They explicitly
create extensions as `postgres`, migrate/serve as a separate database owner,
and assert the five extensions and restricted role after migration. They do not
read a committed credential or depend on `compose.yaml`. Each native CI image
job builds the pinned database first; its dedicated step and job summary record
the added acquisition/build/verification time.

## Image assurance

The stable protected check names are `lint`, `configuration security`,
`artifact lock`, and `image`. The aggregate `image` check requires both native
architecture jobs. The implemented image pipeline performs:

1. Trivy build-configuration scanning.
2. Native architecture builds, followed by inspection of the loaded image's
   source revision and artifact-lock labels against the checkout and lock.
3. Runtime-requirement verification against the locked base image, and a
   runtime-dependency check that resolves the binary inside the assembled
   image, confirms the name-resolution modules glibc loads with `dlopen`, and
   validates the TLS trust bundle and time-zone data.
4. Restricted-runtime scenario tests covering the declared and arbitrary runtime
   identities, process privileges, a read-only root with no writable mount,
   migration as a separate unit, catalog and management endpoints, log
   structure, secret non-disclosure, graceful shutdown, and actionable startup
   failures.
5. S3-compatible warehouse storage qualification against SeaweedFS: warehouse
   registration, namespace and table lifecycle, metadata written to the object
   store under the prefix the catalog reports, the storage credential
   unreadable in a full database dump, and that credential still decrypting
   after a restart, and a real data round trip through PyIceberg whose rows
   are read back after a catalog restart.
6. Fail-closed guard tests covering a missing key, a whitespace-only key, an
   unrecognized toggle value, the informational command allowlist, the
   documented opt-out, and the requirement that the entrypoint execs so the
   server runs as PID 1.
7. Full Trivy image vulnerability and secret scanning.
8. SPDX inventory generation with Syft.
9. Full Grype scanning of the Syft SBOM. Both scanners independently feed the
   [installable-fix gate](../SECURITY.md#installable-fix-vulnerability-gate):
   fixable High/Critical findings block unless fresh native UBI queries prove
   the vendor RPM fix is not available. Non-RPM fixes and query errors block.
   Raw reports, full image RPM inventory and repository metadata hashes are
   retained; deferred fixes appear in the job summary with the vendor version.
10. Architecture-specific artifacts and non-pull-request SARIF publication.

Only scheduled main-branch CI maintains the single deferred-fix tracking issue;
it comments only when that set changes. PRs never write tracking issues. Native
RPM ordering and fail-closed policy tests run on both image runners. The normal
lock-update workflow refreshes the requested dependencies and inherited Micro
RPMs using the same pinned builder's repository files; it retains a proposed
lock for review without modifying Git.

Both image jobs additionally build nginx at `artifacts/nginx.commit` through its
own native Podman script, verify provenance after loading into Docker, and run
the [Phase A TLS qualification](TLS.md). PostgreSQL uses the single existing
source pin, now its TLS-profile revision. Every outbound negative uses the real
Lakekeeper process and must report a TLS-specific cause. The sanitized
`tls-<commit>-<architecture>` manifest records each assertion, certificates and
image identities. A failed or incomplete matrix fails the existing aggregate
`image` gate; no new permissions or branch-protection change is needed.

Tailored OpenSCAP evaluation against an ownership-preserving filesystem export
will be inserted after the runtime tests when its profile and result semantics
are reviewed. Branch protection must not require a check until it exists on the
default branch. Once present and proven, `image` becomes a strict, required,
up-to-date check alongside the other repository checks.

## Artifact acquisition

`scripts/build-metadata.sh` supplies the same provenance build arguments to
local assembly and both native CI builds. The revision is this repository's
full checked-out commit SHA (the tested merge commit on pull requests).
The lock digest hashes the complete raw bytes of
`artifacts/lakekeeper.lock.json`, including both architecture entries. This
matches Trino's shared-lock convention; PostgreSQL hashes its separate
`artifacts/locks/<architecture>.json` file the same way.

`tests/image-provenance.py` independently reads Git HEAD and hashes the lock,
then inspects the loaded image with the container runtime. Missing, empty,
inherited, or incorrect labels fail the job. Actual label values, image ID,
and architecture are printed in the job log and summary. Regression tests
exercise rejection cases and exact-byte hashing without a container engine.

Acquisition is a separate phase from assembly. `scripts/fetch-artifacts.sh`
downloads the archive named by the lock and admits it only after its size,
digest, and member list match; assembly then consumes the resulting bundle
through a named build context and does not pull images. The `artifact lock` job
additionally runs `tests/acquisition.sh`, which corrupts a good bundle in one
specific way per case and requires the gate to refuse each one. A gate that has
never been shown to reject is not evidence.

The Containerfile is checked for the absence of a fetch, so the build cannot
quietly regain the ability to download.

Assembly runs with no network. Podman uses `--network=none` and `--pull=never`;
the CI build sets `network: none` on the build action. Everything the image
receives comes from the verified bundle or a digest-pinned base image.

## Crate inventory

The shipped binary carries no embedded dependency metadata, so a scanner
reading the image can say nothing about Lakekeeper's own dependencies. The
`artifact lock` job therefore acquires upstream's `Cargo.lock` from the pinned
release commit, verifies its digest like any other input, catalogues it with
Syft, and scans it with Grype. The counts are written to the job summary so a
reviewer sees them without downloading an artifact.

Those findings are report-only. They are upstream's dependencies: this project
cannot patch them, and blocking on them would tie every release to upstream's
schedule. Defining what does block a release is a roadmap item. The inventory
also over-reports, because it is the declared graph from source rather than a
bill of materials derived from the artifact.

## Not yet implemented

Upstream publishes no signature and no artifact attestation for the Lakekeeper
release; both were checked, and neither exists. The recorded digest remains the
only integrity evidence for the binary. Tracked in [the roadmap](ROADMAP.md).
