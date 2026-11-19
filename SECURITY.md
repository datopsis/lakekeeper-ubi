# Security policy

## Supported versions

No supported image has been published. Repository revisions and development
images are available for evaluation but receive no security-support commitment.
Each future release will document its exact support status and supersession
policy; support must not be inferred from a tag, branch, successful build, or
scanner result.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use the repository's
**Security** tab and select **Report a vulnerability** to submit a private
security advisory:

<https://github.com/datopsis/lakekeeper-ubi/security/advisories/new>

Include the affected image tag and digest when available, architecture, runtime
and host versions, PostgreSQL version, configuration profile, reproduction
steps, and whether the issue appears to originate in this packaging, Lakekeeper
itself, or UBI. Remove the secret encryption key, database credentials,
object-store credentials, tokens, internal hostnames, customer data, and other
secrets.

Upstream vulnerabilities should also follow the applicable upstream process:

- Lakekeeper: <https://github.com/lakekeeper/lakekeeper/security>
- Red Hat: <https://access.redhat.com/security/team/contact>

## Handling and disclosure

Maintainers will acknowledge a private report when practical, validate its
scope, coordinate with upstream suppliers when appropriate, and agree on a
disclosure plan before publishing details. No response or remediation SLA is
promised until the first supported release defines one.

## Known deployment-critical behavior

These are properties of upstream Lakekeeper that operators must handle. They
are documented here because a deployment that ignores them is insecure even
when the image itself is current.

- **The secret encryption key has an insecure upstream default.** If
  `LAKEKEEPER__PG_ENCRYPTION_KEY` is unset, upstream Lakekeeper starts anyway,
  logs a warning, and encrypts stored storage credentials with a publicly known
  default key. Setting the variable *to* that published default is equally
  unsafe and upstream does not warn about it at all, which is the state a copied
  example or a chart default produces. **This image refuses to start in either
  case**, which can be turned off with
  `LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY=false`. The guard checks presence and
  rejects that one known value; it does not judge whether a key is strong, and
  it cannot undo exposure. Treat a catalog that ever ran without a key, or with
  the default, as having exposed every credential stored during that period:
  adding a key later does not re-encrypt existing rows, and those credentials
  must be revoked and reissued at the storage provider. See
  [configuration](docs/CONFIGURATION.md).
- **The default authorization backend is `allow-all`.** A catalog deployed
  without authentication and authorization must not be reachable from an
  untrusted network.
- **A new catalog is open for bootstrap.** Until it is bootstrapped, the
  bootstrap endpoint sets the initial administrator. Control network reachability
  during that window.

Scanner matches require vendor context. Red Hat can backport corrections
without adopting the upstream version number a scanner expects. Review the exact
RPM build and Red Hat advisory data before classifying a match. Findings against
the Rust dependency inventory must be reviewed against the upstream Lakekeeper
release rather than assumed exploitable in this packaging.

## Installable-fix vulnerability gate

Native AMD64 and ARM64 image CI retains complete Trivy and Grype reports and
blocks fixable HIGH/CRITICAL findings. For RPMs only, a finding is deferred when
fresh, successful queries find no package at or above the scanner's vendor fixed
epoch:version-release in the build's configured UBI repositories. This implements
the owner-approved organization rule from 2026-11-12, following
[nginx-ubi #61](https://github.com/datopsis/nginx-ubi/pull/61).

The gate and `scripts/update-rpm-lock.sh` use the original repository files from
the same digest-pinned UBI Minimal builder, releasever 9, and the target RPM
architecture (including noarch). All three enabled UBI repositories must be
present and populated. Fresh metadata is mandatory; skip-if-unavailable is
disabled. Native RPM comparison includes epoch and release; lexical or semantic
version ordering is not used. The gate checks scanner identities against the
built image's full RPM database, including the pinned Micro base and locked delta.
Repo-file/metadata hashes, available versions, inventory and per-finding decisions
are retained with the raw reports in each architecture's security artifact.

An available fix blocks. Query/setup errors, timeouts, missing repositories,
invalid reports and unparsable RPM versions block. Fixable HIGH/CRITICAL non-RPM
findings (including language modules) and HIGH/CRITICAL secrets still block;
there are no CVE, package or date exemptions. Unfixed findings remain visible.
A deferral is **not remediation**: the job summary names the vendor fixed
version, and publication of that fix makes the next gate block until it is
applied. The normal lock updater now includes upgrades to inherited Micro RPMs
as well as the requested runtime dependencies; assembly remains offline and
signature/digest verified.

The weekly scheduled CI maintains one tracking issue and comments only when the
deferred set changes. Issue writes cannot run on PRs, pushes or manual runs.
Missing, duplicate or erroneous native evidence fails tracking rather than
claiming resolution. First issue creation and later GitHub issue updates require
a scheduled run on main; tests exercise the API behavior without writing issues.

This rule applies to the existing image vulnerability gate. The separate declared
upstream Cargo.lock inventory remains report-only, as before: it is not evidence
of the dependencies actually compiled into the shipped binary. Its findings
remain retained and summarized under the existing
[artifact-acquisition boundary](docs/ARTIFACT-ACQUISITION.md). This change neither
converts that inventory into artifact provenance nor hides its findings.

## Phase A transport boundary

Lakekeeper has no native TLS listener. The [Phase A profile](docs/TLS.md) requires
REST on `127.0.0.1:8182` and metrics on `127.0.0.1:9000`, with the pinned
`datopsis/nginx-ubi` proxy sharing only the network namespace and terminating
verified HTTPS on 8181. Plaintext is permitted only on that namespace's loopback
hop/metrics. A private container bridge is not this exception. PostgreSQL's
container-local administration socket is a separate narrow provisioning exception;
both migrations and the server connect over verified TLS, with an explicit CA.

Phase A covers encryption and server identity only. Login remains off and
OpenID is deferred to Phase B; TLS does not authorize callers or close the
bootstrap window. Network access controls remain mandatory. The encryption-key
guard, its documented opt-out, and the login policy are unchanged.

Mount public roots separately from each listener's own private key. The catalog
must never receive the proxy's key, and the proxy must never receive database,
S3/STS or catalog-encryption credentials. No CA signing key belongs in a runtime
container. S3 and actual STS AssumeRole must use verified HTTPS with the custom
root loaded before process startup. Qualification evidence is scoped to the
exact client paths and native architecture recorded in the CI TLS manifest;
it does not qualify the whole Seaweed control plane or the full integration stack.
