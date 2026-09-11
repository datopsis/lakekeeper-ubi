# Configuration

Lakekeeper is configured through `LAKEKEEPER__*` environment variables defined
by upstream. This image adds a small number of `LAKEKEEPER_UBI_*` variables of
its own. The two namespaces are deliberately distinct: anything starting with
`LAKEKEEPER_UBI_` is a control this packaging adds, is not understood by the
upstream image, and is documented here.

## Image-added variables

| Variable | Default | Effect |
| --- | --- | --- |
| `LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY` | `true` | When true, the container refuses to start unless `LAKEKEEPER__PG_ENCRYPTION_KEY` holds a non-empty value. |

Accepted values are `true`, `1`, `yes`, `on` and `false`, `0`, `no`, `off`, in
any capitalization. Any other value is a startup failure rather than a silent
fallback, because a misspelled toggle must not quietly disable a security
control.

The default is applied by the entrypoint and is deliberately not declared as an
`ENV` in the image, so `podman inspect` and `docker inspect` will not list it
until you set it yourself. Configuration scanners flag any `ENV` whose name
resembles a credential, and this table is a better place to record the default
than a suppression rule that would also hide a real leaked secret.

## Secret encryption key

### This is encryption at rest, not TLS

Three separate things in this project involve cryptography, and mixing them up
leads to the wrong control being configured:

| Concern | Protects | Who provides it |
| --- | --- | --- |
| **Secrets at rest** | Storage credentials Lakekeeper persists in PostgreSQL | `LAKEKEEPER__PG_ENCRYPTION_KEY`, guarded by this image |
| **Inbound TLS** | Connections from query engines to the catalog | Not Lakekeeper. A reverse proxy or ingress in front of it |
| **Outbound TLS** | Connections from the catalog to object storage, identity providers, and PostgreSQL | The binary's built-in Rust TLS stack, using the trust material in the image |

The encryption key has nothing to do with TLS. Lakekeeper does not terminate
TLS, and that does not make the key less important; it makes it important for a
different reason.

When an operator registers a warehouse, they hand Lakekeeper long-lived storage
credentials: an S3 access key, an Azure client secret, a GCS service-account
key. Lakekeeper stores those in its PostgreSQL database so it can vend
short-lived credentials or sign requests later. `LAKEKEEPER__PG_ENCRYPTION_KEY`
is what encrypts them there.

Its threat model is a reader of the database, not a reader of the network: a
stolen or misplaced backup dump, a read replica on a less-controlled host, a
database administrator outside the catalog's trust boundary, or a compromised
PostgreSQL instance. TLS does nothing about any of those. A deployment can have
flawless TLS everywhere and still hand over every warehouse credential the
moment someone copies a database backup, if the key was never set.

### What upstream does

`LAKEKEEPER__PG_ENCRYPTION_KEY` protects storage credentials that Lakekeeper
persists in PostgreSQL. Upstream treats it as optional. If it is unset,
Lakekeeper starts normally and writes a single warning:

```text
THIS IS UNSAFE! Using default encryption key for secrets in postgres, please
set a proper key using LAKEKEEPER__PG_ENCRYPTION_KEY environment variable.
```

It then encrypts stored credentials with a default key that is published in the
upstream source. Nothing else fails. The service reports healthy, the API
works, and query engines connect normally. A deployment can run in that state
for a long time while every credential it holds is decryptable by anyone who
reads public source code. The failure is silent, and it is discovered by
whoever looks first.

### What this image does

By default this image converts that silent degradation into a startup failure.
When `LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY` is `true` and
`LAKEKEEPER__PG_ENCRYPTION_KEY` is unset or contains only whitespace, the
container exits before Lakekeeper starts:

```text
lakekeeper-ubi: LAKEKEEPER__PG_ENCRYPTION_KEY is unset or empty.
lakekeeper-ubi:   Lakekeeper would otherwise start and encrypt stored storage
lakekeeper-ubi:   credentials with a publicly known default key.
lakekeeper-ubi:   Set LAKEKEEPER__PG_ENCRYPTION_KEY to a unique secret value.
lakekeeper-ubi:   To accept upstream behavior instead, set
lakekeeper-ubi:   LAKEKEEPER_UBI_REQUIRE_ENCRYPTION_KEY=false.
```

The exit status is `78`, which is `EX_CONFIG` from `sysexits.h`. A distinct
status lets an operator or orchestrator tell a configuration refusal apart from
a crash or a failed database connection. The key's value is never printed,
logged, or echoed by the guard.

### Choosing a setting

| Setting | Behavior | Use when |
| --- | --- | --- |
| `true` (default) | No key means the container will not start. | Always, unless you have a specific reason not to. This is the point of the control. |
| `false` | Upstream behavior: the container starts and warns. | You are reproducing an upstream issue, running a disposable local experiment, or migrating an existing deployment and need a scheduled window to introduce a key. |

Setting `false` is a deliberate, reviewable choice rather than an accident,
which is the difference between this image and upstream. If you set it,
record why and when it will be reverted.

### Commands that do not require a key

These subcommands never read or write encrypted secrets, so they stay usable
even when the guard would otherwise refuse to start the container. This keeps a
refused container diagnosable:

`version`, `healthcheck`, `help`, `management-openapi`,
`generic-table-openapi`, and the `--help` and `--version` flags.

Any other subcommand, **including one added by a future upstream release**, is
treated as requiring the key. An unrecognized command is not assumed safe.

### Generating a key

Generate a unique, high-entropy value and store it in your secret manager:

```console
openssl rand -base64 32
```

Supply it to the container as an environment variable from that secret store.
Do not commit it, do not reuse it across environments, and do not copy an
example value from this repository or any other.

### Changing the key later

**Rotation is a data operation, not a restart.** Storage credentials already in
the database were encrypted with the previous key. Changing the variable and
restarting gives a server that cannot decrypt its own stored secrets, which
surfaces as warehouse operations failing rather than as a startup error.

Upstream does not currently document a rotation command, and this project has
not tested a rotation procedure, so no supported procedure is published here.
What is known:

- Do not rotate by editing the variable and restarting.
- The safe general shape is to re-register the affected warehouses with their
  credentials under the new key, so the secrets are re-encrypted through normal
  API operations rather than by rewriting rows.
- Rehearse any rotation against a restored backup first, and verify that every
  warehouse still vends credentials afterwards.
- A catalog that ever ran without a key, or with the published default, should
  be treated as having exposed every credential stored during that period.
  Rotating the key does not undo that: those credentials must be revoked and
  reissued at the storage provider.

Publishing and testing a supported rotation procedure is a roadmap item. Until
it exists, do not infer one from this section.

## Configuration values that fail open

The encryption key was the first setting found whose absence degrades security
instead of stopping the service. It was not the only one. This is the inventory
of every such value in the upstream configuration surface, with who is
responsible for each.

A value is listed here when leaving it unset produces a **working but less
secure** deployment. Settings that simply fail when missing are not a hazard,
because the operator finds out immediately.

Classification:

- **Image-enforced**: this image refuses to start, or otherwise prevents the
  unsafe state.
- **Deployment-enforced**: the operator must set it. The image cannot decide,
  usually because any default would be wrong for some legitimate deployment.
- **Accepted**: the unsafe-ish default is reasonable and the risk is recorded.

| Setting | Default | What the default costs | Class |
| --- | --- | --- | --- |
| `LAKEKEEPER__PG_ENCRYPTION_KEY` | A published literal string | Stored storage credentials encrypted with a public key | **Image-enforced** |
| `LAKEKEEPER__AUTHZ_BACKEND` | `allowall` | Every authenticated caller can do everything | Deployment-enforced |
| `LAKEKEEPER__OPENID_PROVIDER_URI` | unset | No authentication at all | Deployment-enforced |
| `LAKEKEEPER__OPENID_AUDIENCE` | unset | Tokens are accepted without checking `aud`, so a token minted for a different application of the same issuer is valid here | Deployment-enforced |
| `LAKEKEEPER__OPENID_ADDITIONAL_ISSUERS` | unset | Safe default; adding issuers widens who can mint valid tokens | Accepted |
| `LAKEKEEPER__PG_SSL_MODE` | unset | The database connection is plaintext, and nothing says so | Deployment-enforced |
| `LAKEKEEPER__PG_SSL_ROOT_CERT` | unset | With TLS enabled but no root certificate, the server certificate is not verified against a known CA | Deployment-enforced |
| `LAKEKEEPER__USE_X_FORWARDED_HEADERS` | `true` | Proxy headers are trusted from any caller, so a directly reachable catalog accepts spoofed client addresses and protocols | Deployment-enforced |
| `LAKEKEEPER__BIND_IP` | `0.0.0.0` | The API and the metrics port listen on every interface | Deployment-enforced |
| `LAKEKEEPER__INSTANCE_ADMINS` | empty | Safe default; the first bootstrap caller becomes administrator instead | Accepted |
| Bootstrap state | open until bootstrapped | Whoever reaches the endpoint first becomes the initial administrator | Deployment-enforced |
| `LAKEKEEPER__ROLE_PROVIDER__<id>__REQUIRE_CONNECTED_ON_STARTUP` | `false` | The server starts even when a role provider is unreachable, and authorizes from cached roles | Deployment-enforced |
| `LAKEKEEPER__ENABLE_AWS_SYSTEM_CREDENTIALS` | `false` | Safe default. Enabling lets a warehouse borrow the server's own cloud identity | Accepted |
| `LAKEKEEPER__ENABLE_AZURE_SYSTEM_CREDENTIALS` | `false` | Safe default, as above | Accepted |
| `LAKEKEEPER__ENABLE_GCP_SYSTEM_CREDENTIALS` | `false` | Safe default, as above | Accepted |
| `LAKEKEEPER__S3_REQUIRE_EXTERNAL_ID_FOR_SYSTEM_CREDENTIALS` | `true` | Safe default. Disabling removes a cross-account confused-deputy protection | Accepted |
| `LAKEKEEPER__PG_ENABLE_STATEMENT_LOGGING` | `false` | Safe default. Enabling can place query content in logs | Accepted |
| `LAKEKEEPER__ALLOW_ORIGIN` | unset | Safe default: no cross-origin access is granted | Accepted |
| `LAKEKEEPER__MAX_REQUEST_BODY_SIZE` | 2 MiB | A bounded default already exists | Accepted |
| `LAKEKEEPER__MAX_REQUEST_TIME` | 30s | A bounded default already exists | Accepted |

### The two that most often go unnoticed

**An explicitly set default key is silent.** Upstream warns when
`LAKEKEEPER__PG_ENCRYPTION_KEY` is *unset*. It does not warn when the variable
is set to the published default value, which is what a copied example or a
chart default produces. That path was measured against the locked version and
produces no warning of any kind. This image rejects that exact value for the
same reason it rejects an absent one.

**A plaintext database connection is silent.** With `LAKEKEEPER__PG_SSL_MODE`
unset, the catalog connects to PostgreSQL without TLS and logs nothing about
it. Everything between the catalog and its database, including the encrypted
secret blobs and every query, crosses the network in the clear. Measured: no
warning is emitted. The image cannot fix this, because a local socket or an
already-encrypted network path is a legitimate deployment, but an operator
should never discover it from a packet capture.

### Why the image enforces only one of these

The encryption key is enforced because there is no legitimate deployment that
wants the published default: every use of it is a mistake. The others all have
deployments where the default is correct. A catalog on a trusted network with
no identity provider is a real evaluation scenario; a catalog behind a proxy
that sets the forwarded headers genuinely should trust them; a database reached
over a local socket does not need TLS.

An image that refuses to start on any of those would be wrong more often than
it was right, and operators would disable the checks wholesale, which is worse
than not having them. Enforcement is reserved for the case where every
occurrence is an error.

## What the guard does not do


Be precise about the boundary:

- It checks that a key is **present**, not that it is strong, unique, or
  secret. A key of `x` passes. Entropy is your responsibility.
- It does not detect a key that was previously absent. If a catalog ever ran
  without a key, credentials stored during that period were encrypted with the
  default key and must be treated as exposed. Adding a key later does not
  re-encrypt them.
- It is part of the image's entrypoint. An operator who overrides the
  entrypoint, for example with `--entrypoint sh`, bypasses it. The guard raises
  the floor for ordinary deployments; it is not a control against a determined
  operator of the container itself.
- It does not address the other two deployment-critical defaults: the
  `allow-all` authorization backend and the pre-bootstrap window. Those remain
  deployment responsibilities described in [the security policy](../SECURITY.md).

## Runtime identity and signals

The entrypoint is not a privilege transition. It runs as whatever unprivileged
identity the container was given, never changes user or group, and replaces
itself with `exec`, so Lakekeeper becomes PID 1 and receives `SIGTERM` directly
for graceful shutdown. The smoke suite asserts that PID 1 is `lakekeeper` and
not a shell.

The container health check invokes the binary directly rather than through the
entrypoint, so a health probe never depends on the configuration guard.

## Upstream configuration

For the `LAKEKEEPER__*` variables themselves, including database connection
settings, the metrics port, authentication, and storage profiles, see
[the upstream configuration reference](https://docs.lakekeeper.io/docs/latest/configuration/).
This project does not restate the upstream surface; it documents only what this
packaging adds or constrains.
