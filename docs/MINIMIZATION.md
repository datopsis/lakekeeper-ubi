# Container minimization analysis

Status: analysis, with measurements from the current development image. No
change is proposed here. Its purpose is to decide what "minimal" should mean
for this image before someone optimizes the wrong thing.

Minimization has two distinct motives that are often conflated:

1. **Reducing attack surface**: fewer executables, libraries, and privileges an
   attacker can use after reaching the container.
2. **Reducing size**: faster pulls, less registry storage, less to transfer
   into a controlled network.

They do not point the same way here, which is the central finding.

## Measured composition

Taken from the current `amd64` development image:

| Component | Size | Share |
| --- | --- | --- |
| Total image | 228.8 MB | 100% |
| The Lakekeeper binary | 167.2 MB | 73% |
| `/usr/lib64` | 10.8 MB | 5% |
| `/usr/share` | 9.7 MB | 4% |
| `/var`, mostly the RPM database | 9.6 MB | 4% |
| `/usr/bin`, 148 executables | 5.0 MB | 2% |

**The application is three quarters of the image.** Every filesystem-trimming
technique available competes for the remaining quarter. Any size discussion
that does not start with the binary is optimizing noise.

Already achieved: resolving runtime packages against the UBI Micro database
rather than an empty root removed a duplicated base system and `openssl-libs`,
taking the image from 246.6 MB to 228.8 MB and eliminating the only High
vulnerability finding. That was a correctness fix whose size benefit was
incidental, which is the pattern worth repeating.

## The largest lever: stripping the binary

Measured, not applied: `strip --strip-all` reduces the upstream binary from
167.2 MB to 125.5 MB, a **41.6 MB saving, about 18% of the image**. Upstream
ships it unstripped.

Arguments against:

- It modifies the exact bytes this project verified. The recorded binary digest
  becomes the digest of an artifact nobody upstream published, which weakens
  the one provenance property this project currently has. The lock would need
  to record both digests and the strip step would become part of the trusted
  build.
- Symbols make a core dump or a profiler output readable. For a data catalog
  holding credentials, incident analysis has real value.

Arguments for:

- 41.6 MB per pull, per node, per controlled-network transfer.
- Symbols are not needed to run, and a debug build can be fetched separately
  when an incident requires one.

Unresolved. The decision belongs with whoever owns incident response, and it
should be recorded with its reasoning rather than made by whoever touches the
Containerfile next.

## The attack-surface question: the shell

The image contains 148 executables in `/usr/bin`, including `bash` and the
coreutils set, inherited from UBI Micro. They total about 5 MB, so removing
them is almost irrelevant to size and significant to attack surface: a shell
turns many limited vulnerabilities into general-purpose ones.

Three things currently depend on that shell, and they must be named before
anyone proposes removing it:

1. **The fail-closed encryption-key guard is a shell script.** Removing the
   shell removes the guard, or requires reimplementing it as a compiled
   wrapper. Choosing a smaller image by silently dropping a security control
   would be a bad trade made by accident.
2. **The smoke suite executes `sh` inside the container** to assert non-root
   operation, zero capabilities, `no-new-privileges`, and the absence of
   package managers. Without a shell those assertions need another mechanism,
   and unverified hardening is worth less than verified hardening.
3. **`ca-certificates` installation pulls in `grep`, `sed`, `findutils`,
   `alternatives`, `libsigsegv`, and `pcre`** for its scriptlets. Six of the
   twelve locked runtime packages exist to support certificate trust, not to
   serve requests.

## Options, with their real costs

| Option | Size effect | Attack surface | Cost |
| --- | --- | --- | --- |
| Strip the binary | −41.6 MB | None | Verified bytes stop matching upstream; harder incident analysis |
| Remove the RPM database | −9.6 MB | None | Breaks SBOM generation and vulnerability scanning. Not worth it |
| Remove the shell and coreutils | −5 MB | Large reduction | Breaks the encryption-key guard and the smoke suite's assertions |
| Ship extracted CA files instead of `ca-certificates` | −2 MB and 6 packages | Small reduction | Loses package provenance and SBOM visibility of trust material |
| Drop `tzdata` | −2 MB | None | Only UTC would work; must be a documented support statement, not a silent change |
| Distroless or `scratch` base | Large | Large reduction | Abandons the digest-pinned UBI base, which is a stated non-negotiable, and the UBI support and CVE-feed relationship |

## What this project should not do

- **Do not remove the RPM database to save 9.6 MB.** It is what lets a scanner
  enumerate the image. Trading evidence for 4% is a bad trade for a project
  whose premise is inspectable evidence.
- **Do not treat a smaller image as automatically safer.** The measured
  reduction from removing every package this image could plausibly drop is
  smaller than stripping one binary, and one of those options removes a
  security control while the other does not.
- **Do not adopt `scratch` or a distroless base for size.** UBI is a stated
  non-negotiable, and the image's size is dominated by the application anyway.

## Open decisions

- [ ] Decide whether to strip the upstream binary. Record the decision, the
  incident-analysis consequence, and, if stripping, how the lock records both
  the upstream digest and the shipped digest so verification still means
  something.
- [ ] Decide whether the shell stays. If it goes, the encryption-key guard must
  be reimplemented as a compiled entrypoint and the smoke suite must obtain its
  assertions another way, both before removal rather than after.
- [ ] Decide whether `tzdata` is in the supported boundary. UBI Micro records
  it as installed while shipping none of its files, so this image reinstalls it
  deliberately. If only UTC is supported, say so and drop it; if local zones are
  supported, keep it and test one.
- [ ] Decide whether certificate trust ships as packages or extracted files,
  which is the same question Package 2c asks about `openssl-libs` provenance.
- [ ] Measure pull time and controlled-network transfer time, rather than
  assuming bytes are the metric that matters to operators.
- [ ] Re-measure after any upstream version change. The binary dominates, so
  upstream's build choices move this image's size more than anything this
  project does.
