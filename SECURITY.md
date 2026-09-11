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
