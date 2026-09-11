# External artifact acquisition

Status: required design for the first release. The current `Containerfile`
still downloads the locked release archive inside the builder stage and must be
migrated to out-of-build acquisition with networking disabled during assembly.

## What this project actually gets from upstream

Lakekeeper is distributed as a statically named release archive attached to a
GitHub release:

```text
lakekeeper-x86_64-unknown-linux-gnu.tar.gz
lakekeeper-aarch64-unknown-linux-gnu.tar.gz
```

Each archive contains a single dynamically linked, PIE, unstripped
`lakekeeper` executable. The recorded runtime requirements for the locked
version are:

| Property | amd64 | arm64 |
| --- | --- | --- |
| Rust target | `x86_64-unknown-linux-gnu` | `aarch64-unknown-linux-gnu` |
| Highest required glibc symbol version | `2.34` | `2.34` |
| Needed shared libraries | `libresolv`, `libgcc_s`, `libm`, `libc`, loader | `libresolv`, `libgcc_s`, `libm`, `libc`, loader |

UBI 9 provides glibc 2.34, so the locked binaries run on the UBI 9 product
line without rebuilding. This compatibility is a property of the specific
locked build, not a guarantee about future upstream releases. Every lock update
must re-measure the highest required glibc symbol version and the needed
library list, and must fail the update if either exceeds what the targeted UBI
major version provides.

The binary links no TLS library; upstream builds against a Rust TLS stack.
`ca-certificates` is installed for trust material used by object-store and
identity-provider connections, not to satisfy a dynamic link.

## Trust limitation

**Upstream publishes no detached signature and no checksum file for these
assets.** The only publisher-side integrity evidence is the SHA-256 digest
exposed in GitHub release asset metadata, served over an authenticated TLS
connection to GitHub.

This is materially weaker than the vendor-signed RPM provenance used by this
organization's RPM-based UBI images. The honest description of the current
control is:

- this project records the exact archive digest, archive size, extracted
  binary digest, binary size, and GNU build ID in
  `artifacts/lakekeeper.lock.json`;
- a reviewed change to that lock is the human control point at which new bytes
  are admitted;
- every subsequent build proves it used those exact bytes and nothing else.

That defends against a build-time substitution, a mirror rewriting content, a
truncated or corrupted download, and an accidental version drift. It does
**not** independently prove publisher identity, and it does not detect a
compromise that occurred upstream before the digest was first recorded. No
document in this repository may describe the recorded digests as publisher
verification.

Improving this is a tracked roadmap item: adopt GitHub artifact attestation
verification if upstream publishes attestations, request upstream signing, or
move to a source build with a pinned toolchain and vendored dependencies.

## Build contract

The container build must not download archives, keys, repository metadata, or
other files. CI or a local preparation tool acquires and verifies every input
before starting the build. The build then runs with network access disabled and
consumes only local, immutable inputs.

This separates three concerns:

1. **Acquisition** downloads inputs from an approved source.
2. **Verification** proves exact content before an input is admitted to the
   build context.
3. **Assembly** creates the image without network access, credentials, or
   mutable dependency resolution.

The assembly process accepts only a bundle that conforms to the repository's
lock and verification contract. Changing a download location must not silently
change selected artifacts or weaken verification.

## Artifact-source interface

This repository defines source-independent lock, acquisition, verification, and
assembly interfaces. The default source is the official Lakekeeper GitHub
release and the official Red Hat UBI registry. An alternate approved source,
such as an internal mirror for a controlled network, can be selected through
protected CI configuration without changing the artifact identity, lock, or
verification requirements.

The repository must not contain private endpoints, repository identifiers,
credentials, tokens, or private CA material. Environment-specific configuration
belongs in protected variables, secrets, or runner trust.

An intermediary that transfers the files must preserve the original bytes. A
process that rebuilds, re-packs, or re-signs the artifact is a different trust
model and requires its own documented approval and traceability controls.

## Pipeline phases

### 1. Update locked inputs deliberately

Version selection is an update activity, not part of every CI build. A dedicated
lock-update workflow or maintainer command queries the upstream release, records
the complete artifact set, and proposes a change to
`artifacts/lakekeeper.lock.json` for review. Its pull request receives normal
image tests and security review.

An ordinary pull-request, `main`, or release build never selects "latest" and
never re-resolves the upstream release. It consumes only entries already present
in the merged lock.

The lock manifest identifies:

- each base-image registry, repository, tag, and expected manifest digest;
- the upstream release tag, release commit, publication timestamp, and license;
- the archive name, URL, byte size, and SHA-256 digest per architecture;
- the extracted binary path, byte size, SHA-256 digest, and GNU build ID per
  architecture;
- the measured interpreter, highest glibc symbol version, and needed shared
  libraries per architecture;
- the approved artifact-source identifier; and
- the lock schema version and the publisher-verification status.

The lock manifest is reviewable repository content. Credentials, tokens,
private CA keys, and internal endpoints are not.

### 2. Acquire locked files outside the build

The CI runner downloads artifacts into an ephemeral staging directory. Native
amd64 and arm64 jobs acquire only their matching archive. Release resolution
does not occur here or in a `RUN` instruction; it occurred in the reviewed lock
update.

### 3. Verify before admission

Before any bytes enter a build context, the pipeline must confirm:

- the archive size and SHA-256 digest match the lock;
- the archive contains exactly the expected member and no additional entries;
- the extracted binary size, SHA-256 digest, and GNU build ID match the lock;
- the ELF architecture matches the target architecture;
- the highest required glibc symbol version does not exceed the version
  provided by the locked UBI base; and
- the needed shared library list matches the lock.

Negative tests must cover a tampered archive, an unexpected extra archive
member, a wrong-architecture binary, a missing file, and a lock entry with no
matching download.

### 4. Assemble without a network

The image build runs with networking disabled and image pulling disabled
against preloaded, digest-verified base images. It copies the verified binary
into the runtime root. The UBI Micro final stage receives no package manager,
no build cache, and no acquisition tooling.

### 5. Record the evidence

Release evidence binds the image digest to the lock digest, the upstream
release tag, the archive and binary digests, the base-image digests, and the
architecture. That record, not a build log, is the durable artifact-provenance
statement.
