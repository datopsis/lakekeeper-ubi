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

## Secret encryption key

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

Rotating this key is not a configuration change alone: existing rows were
encrypted with the previous key. Treat rotation as a planned data operation,
and verify against a restored backup before doing it in production. Key
rotation procedure is a first-release roadmap item and is not yet documented
here; do not infer that it is a simple restart.

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
