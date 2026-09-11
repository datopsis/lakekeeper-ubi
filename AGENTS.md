# Agent guidance

Follow the repository guidance in `CLAUDE.md`, including its security,
verification, documentation, and Git conventions.

Do not weaken the rootless runtime, read-only-root compatibility, locked and
digest-verified artifact policy, migration/serve separation, secret-handling
rules, vulnerability gates, SCAP evidence boundary, or signed-release process
merely to make a test or release pass.

Never present the recorded upstream tarball digests as publisher verification.
Upstream publishes no signature; `docs/ARTIFACT-ACQUISITION.md` states the
resulting limitation and it must stay accurate.

Never add `Co-Authored-By`, AI, assistant, or tool-attribution trailers to
commits. Tool attribution belongs in tool logs, not Git history.
