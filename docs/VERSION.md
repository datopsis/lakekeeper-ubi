# Versioning and releases

The published container image is versioned independently from repository
history. Git commits identify every repository revision; release versions
identify container artifacts that this project intentionally publishes and
supports.

## Container release format

Annotated release tags use:

```text
v<lakekeeper-version>-ubi<ubi-major>-r<YYYYMMDD>.<daily-sequence>
```

For example, `v0.13.4-ubi9-r20260910.1` would identify:

- Lakekeeper `0.13.4`;
- the UBI 9 runtime product line;
- a Datopsis container release created on 2026-09-10 UTC; and
- the first container release created on that UTC date.

The `r` distinguishes this project's container release from an upstream
Lakekeeper release. The eight-digit date is the UTC date on which the immutable
release tag is created. The sequence is a positive integer beginning at `1` and
increments for every additional container release created on the same UTC date,
regardless of Lakekeeper or UBI major version. Dates must not be backdated.

This upstream-derived format is not Semantic Versioning. The downstream release
suffix communicates release chronology; it does not claim API-compatibility
semantics.

The tag includes the UBI major version because changing that version changes
the runtime product line and its compatibility and support boundary. It
deliberately omits the UBI minor version: package updates can make the runtime
filesystem newer than the original base-image snapshot, and a named minor
version does not identify exact bytes. The exact UBI reference and digest
remain required in OCI metadata, the SBOM, provenance, and release evidence.

Release tags are immutable. Never move or reuse a release tag. Production
deployments should pin the OCI digest; a human-readable tag describes a
release, while its digest identifies exact image content.

The release workflow must accept only tags matching:

```regex
^v[0-9]+\.[0-9]+\.[0-9]+-ubi[1-9][0-9]*-r[0-9]{8}\.[1-9][0-9]*$
```

Pattern matching is only the first check. The workflow must also validate a
real UTC calendar date, the selected Lakekeeper version, the selected UBI major
version, the daily sequence against existing immutable tags, and that the
tagged commit is the protected `main` release commit.

## Upstream is pre-1.0

Lakekeeper is below version `1.0.0`. Under its own versioning, a `0.x` minor
increment may introduce breaking API, configuration, or database-schema
changes. This project therefore treats every upstream minor increment as a
qualification event, not a routine dependency bump:

- re-read the upstream release notes and migration guidance;
- re-run the full image and database test suite, including migration from the
  previously released schema;
- review configuration-key renames and removals against the documented
  profiles; and
- state any consumer-visible break in the changelog entry for the release.

A downstream release tag never implies upstream compatibility. It records which
upstream version this project packaged and when.

## Artifact identity

The annotated Git tag and immutable GHCR image tag use the complete version,
including the leading `v`. OCI metadata records:

- `org.opencontainers.image.version` as the release identifier without the
  leading `v`;
- `org.opencontainers.image.revision` as the full Git commit SHA;
- `org.opencontainers.image.created` as the reproducible UTC creation time;
- the exact UBI base reference and manifest digest;
- the exact upstream Lakekeeper release tag, archive digest, and extracted
  binary digest; and
- the artifact-lock digest used to prepare the build inputs.

The image digest, not any label or tag, is the definitive artifact identity.

## When to change the container version

| Change | Version action |
| --- | --- |
| Change the Lakekeeper version | Use the new Lakekeeper version with the release date and next sequence for that UTC date. |
| Change the UBI major version | Use the new UBI major field with the Lakekeeper version, current UTC date, and next daily sequence. |
| Change only the UBI minor reference or digest | Keep the Lakekeeper and UBI major fields and create a release using the current UTC date and next daily sequence. |
| Change the artifact lock, runtime dependency set, runtime behavior, default configuration, entrypoint, build input, or release metadata | Create a release using the current UTC date and next daily sequence. |
| Deliberately rebuild otherwise unchanged inputs | Create a release using the current UTC date and next daily sequence. |
| Change only documentation, tests, development tooling, policies, examples not copied into the image, issue templates, or analysis workflows | Do not create or change a container release version unless an image is deliberately republished. |

Every newly published image receives a new immutable release tag. If more than
one release occurs on a UTC date, inspect existing tags and use the next unused
daily sequence; never fill an older gap or reuse a failed or withdrawn tag.

## Published tags

The first release publishes only:

- the immutable release tag, such as `v0.13.4-ubi9-r20260910.1`; and
- an immutable `sha-<short-commit>` traceability tag.

Mutable tags such as `latest`, `stable`, `0`, or `0.13` are not published. They
can be considered later only with documented movement, rollback, and
consumer-notification semantics, and a mutable minor tag is especially
misleading while upstream remains pre-1.0. Controlled deployments use an image
digest.

## Repository-only revisions

A repository-only change is identified by its pull request and full Git commit
SHA. It does not become part of an existing supported container release merely
because it is merged to `main`.

This project does not create source-only GitHub Releases or tags. GitHub
Releases represent published container images. Use:

- a full commit SHA for an exact repository revision;
- `git describe --tags --always --dirty` for a convenient local identifier;
- the `Unreleased` section of `CHANGELOG.md` for notable changes intended for
  the next container release.

Not every repository-only change requires a changelog entry. Add one when an
operator, consumer, contributor, or security reviewer would reasonably need to
discover it. At the next image release, move accumulated entries into a dated
section named for the release tag.

## Release requirements

Before an annotated release tag is pushed:

1. Verify that the tag's Lakekeeper version matches
   `artifacts/lakekeeper.lock.json`, that its UBI major version matches the
   locked base images, and that release metadata records the exact UBI
   reference and digest.
2. Convert `Unreleased` changelog entries into a dated section for the tag and
   create a new empty `Unreleased` section.
3. Complete the applicable release gates in `docs/ROADMAP.md`.
4. Merge the reviewed release change to protected `main` with required checks
   passing.
5. Create the annotated tag from that exact `main` commit.
6. Allow the tag workflow to build, scan, attest, sign, publish, and create the
   GitHub Release.
7. Verify the manifest architectures, digest, signature, provenance, SBOM,
   labels, scan evidence, and release assets before announcing support.

The `sha-<short-commit>` tag supplements but never replaces the release tag and
digest.
