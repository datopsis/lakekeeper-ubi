# Contributing

Contributions are welcome through GitHub pull requests. Security reports must
use the private process in [SECURITY.md](SECURITY.md), not a public issue.

## Before changing the repository

1. Read [the agent and contributor guidance](CLAUDE.md) and the
   [forward-looking roadmap](docs/ROADMAP.md).
2. Keep runtime additions minimal and explain why each package, port, writable
   path, capability, or network permission is required.
3. Pin base images and external inputs. Every upstream artifact change is a
   reviewed edit to `artifacts/lakekeeper.lock.json`, never a build-time
   resolution. Never commit credentials, encryption keys, private CAs, internal
   repository locations, or downloaded release archives.
4. Add or update automated tests, operational guidance, security
   considerations, and support classification together when behavior changes.
5. Record notable completed work under `Unreleased` in `CHANGELOG.md` and
   remove completed work from `docs/ROADMAP.md`; the roadmap remains forward
   looking.

Do not weaken the non-root default, digest verification, the separation of
`migrate` from `serve`, vulnerability gates, read-only-root compatibility, the
dropped-capability and no-new-privileges baseline, or the signed-release process
merely to make a test pass.

## Validate a change

Install and run the pinned repository checks:

```console
python -m pip install --require-hashes --only-binary=:all: \
  --requirement .github/requirements/pre-commit.txt
pre-commit install --install-hooks
pre-commit run --all-files --show-diff-on-failure
```

For image-affecting changes, use the build and smoke commands in `README.md`.
The smoke suite starts its own PostgreSQL fixture and generates its credentials
per run, so it needs a working container runtime and network but no prepared
database. A local success does not replace native architecture CI or
release-candidate platform qualification.

## Pull requests and commits

Keep changes small and dependency ordered. Complete the pull request template,
identify image, runtime, security, documentation, and release impact, and
review logs and retained evidence rather than relying only on green checkmarks.

Use concise Conventional Commit subjects such as `feat:`, `fix:`, `docs:`,
`test:`, `ci:`, `build:`, `refactor:`, or `chore:`. Do not add AI, assistant,
tool-attribution, or `Co-Authored-By` trailers to commits.
