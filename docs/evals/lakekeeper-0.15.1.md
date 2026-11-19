# Lakekeeper 0.15.1 evaluation

Report only, 2026-11-19. **Do not upgrade the image or authz dependency from this
report.** The image remains 0.13.9 in #26; #27 is unchanged. Recommendation:
qualify 0.15.1 as a separate integration project, not a patch-level substitute
or a presumed fix for the Azure quick-xml problem.

## Evidence and RustSec

Candidate: [v0.15.1](https://github.com/lakekeeper/lakekeeper/releases/tag/v0.15.1),
commit `10c251cb42f17cd378d86c0d7c54b40fde21c1fc`, published 2026-11-15.
[Evaluation pins](lakekeeper-0.15.1.lock.json) record both official Linux archive
hashes (checked against GitHub asset metadata), extracted binary hashes/build
IDs, exact source archive/Cargo.lock and `nightly-2026-06-28`. Neither ELF has a
cargo-auditable `.dep-v0` section. Recorded hashes establish reviewed bytes,
not independent publisher identity or reproducible binary provenance.

**RustSec count: pending the native PR CI evaluation; not yet a clean result.**
The final report will replace this statement with counts and artifact links.
The separate evaluation step uses the same pinned prebuilt cargo-audit and
exact-release Cargo unit-graph selection as the shipped-code gate, without
compiling Rust or executing build scripts. It audits the downloaded 0.15.1
candidate, never builds/loads it into the test image. Candidate findings are
report-only because this binary is not shipped; errors producing evidence fail
the step. The ordinary 0.13.9 shipped-code gate remains independently blocking.
No advisory ignores are imported. Full-lock/build-only findings are separate.

Comparison reference: 0.13.4 has **38 RustSec findings plus one yanked crate**;
0.13.9 has **24 RustSec findings** (7 vulnerabilities + 17 advisory warnings),
with 9 build-only/unselected findings. Counts include advisory warning classes;
CVE-only counts are not comparable. The direct signer uses quick-xml 0.41, but
Azure's 0.40.1 copy must be checked separately, not assumed fixed by a minor bump.

## Breaking changes versus 0.13

Read both [0.14.0 notes](https://github.com/lakekeeper/lakekeeper/releases/tag/v0.14.0)
and [0.15.0 breaking/upgrade notes](https://github.com/lakekeeper/lakekeeper/releases/tag/v0.15.0),
not just the 0.15.1 patch notes. Some fixes were backported to 0.13.9, so compare
against the actual deployed patch, not only the release-note headings.

| Area | Impact and required work |
| --- | --- |
| Authentication/config | 0.14 tightens OIDC scope/required-claim/provider validation and startup connectivity rules; custom admission gates receive a plain role set and roles apply across projects. Audit `OPENID_SCOPE`, multi-provider keys, `REQUIRE_CONNECTED_ON_STARTUP` and Kubernetes audiences. |
| Defaults/deployment | Default maximum request body rises from 2 MiB to 32 MiB; retain an intentional resource limit. New default-project/schema/cache-invalidation/headless-worker controls require reviewing deployment assumptions, worker lifecycles and DB capacity. `serve` requires migrated schema; this packaging already separates migrate/serve and must keep that separation. |
| Storage/config | S3 system identity rules cover all storage paths (role/external-ID requirements). GCS uses Google's official SDK: file-based credentials, PKCS#8 keys, CA roots, and direct HTTPS reachability to storage.googleapis.com need checking; JSON credentials env behavior changes. Kafka drops GSSAPI. No implication that these deferred backends become qualified in this image. |
| Authorization/API | OpenFGA adds `write`, changes `create` visibility, warehouse checks for registration/soft-deletion bypass and configured model enforcement. Custom Cedar must implement equivalent intended policy rather than inherit an OpenFGA assumption. New tags/grants/namespace-move APIs, changed permission-action vocabulary and STACKIT credential discriminator require client/schema review. New names reject `+`/control characters. |
| View security | Trusted-engine configuration is required for owner-executed views; switching security mode needs authorization, chained invoker behavior changes, and views no longer vend storage credentials. Re-test Trino/dbt create/replace and definer/invoker behavior. |
| Audit/clients | Audit format advances to 1.1 with changed actions/authorization records and event dispatch; update consumers/alerts. Listings, purge-location reservation and task/config responses change. Regenerate management API clients and test exact calls used by authz/integration. |

The upstream [pinned configuration guide](https://github.com/lakekeeper/lakekeeper/blob/10c251cb42f17cd378d86c0d7c54b40fde21c1fc/docs/docs/configuration.md)
and [workspace SQLx patches](https://github.com/lakekeeper/lakekeeper/blob/10c251cb42f17cd378d86c0d7c54b40fde21c1fc/Cargo.toml)
are part of this review. Embedders must carry the matching SQLx patch family at
their workspace root; a transitive crate's patch table is not inherited.

## Concrete datopsis-authz adapter work

The default authz main at `d08a3b6405afc4a076a063c42b56ba2e5c41643b` contains only a
license. Therefore this review uses the actual MVP PR #5 source at
[`8a4aa0c17ba1c63ca790291024c80640149f077d`](https://github.com/datopsis/datopsis-authz/tree/8a4aa0c17ba1c63ca790291024c80640149f077d),
whose [workspace](https://github.com/datopsis/datopsis-authz/blob/8a4aa0c17ba1c63ca790291024c80640149f077d/Cargo.toml#L16-L17)
pins 0.13.4 and whose
[CedarAuthorizer](https://github.com/datopsis/datopsis-authz/blob/8a4aa0c17ba1c63ca790291024c80640149f077d/crates/lakekeeper-authz/src/lib.rs#L45-L55)
implements the upstream trait. No downstream files were changed or compiled.

Against the pinned 0.15.1
[`Authorizer`](https://github.com/lakekeeper/lakekeeper/blob/10c251cb42f17cd378d86c0d7c54b40fde21c1fc/crates/lakekeeper/src/service/authz/mod.rs#L2661-L2920):

- Add associated `TagAction` and required `are_allowed_tag_actions_impl`,
  `create_tag`, `delete_tag`. The existing adapter lacks them, so it cannot be
  treated as source-compatible. Existing batch-check signatures remain the
  same in the inspected traits; `async_trait` remains in use.
- New grant vocabulary/ownership/authority facets have defaults, including
  deny defaults. Decide whether Cedar's external grant store implements
  `ManagesGrants` or explicitly refuses the built-in grant API; an empty
  vocabulary/default hooks do not implement the existing external grant model.
- Implement namespace detach/attach hooks or explicitly disallow namespace
  moves. Leaving new no-op defaults could leave Cedar's resource ancestry stale.
  Keep existing tabular move hooks, ordered batch decisions, denied `for_user`,
  backend-failure denial and audit guarantees intact.
- The adapter forwards `action_descriptor().action_name` to Cedar. Review new
  action vocabulary and context (`write`, storage credential changes, soft
  deletion, view security) against the Cedar schema/policies; compilation alone
  cannot establish correct grants. Preserve the deliberate instance-admin
  bypass prohibition. Recheck provider/admission semantics and event/audit sinks.
- Reconcile the thin binary's startup/configuration, serving builder and
  migration entrypoints against the new extension/task/cache APIs. Do not
  assume every new builder field is required: many have defaults. Refresh the
  full Cargo.lock/SQLx patches and downstream CI only in an approved upgrade.

## Migrations and effort

Static comparison of 0.13.4 **and** 0.13.9 against 0.15.1 finds **13 added SQL
migrations, zero changed existing SQL files** in
[`lakekeeper-storage-postgres/migrations`](https://github.com/lakekeeper/lakekeeper/tree/10c251cb42f17cd378d86c0d7c54b40fde21c1fc/crates/lakekeeper-storage-postgres/migrations):
normalized schemas; tags; warehouse validation endpoints; grants/subtree grants;
namespace move; listing index; table-name signing; normalized/indexed locations;
server grants restricted to users; endpoint names/task schedules; cache change
log; snapshot-table FK. SQL file counts omit Rust data-migration hooks, which
also require review in the
[pinned migration implementation](https://github.com/lakekeeper/lakekeeper/blob/10c251cb42f17cd378d86c0d7c54b40fde21c1fc/crates/lakekeeper-storage-postgres/src/migrations/mod.rs).

Upstream estimates endpoint-statistics conversion at roughly 6 seconds per
million rows and about twice that table's size in free disk; this is upstream's
estimate, not a measured result here. Long transactions/pg_dump can prevent
migration. Rehearse against a restored representative database with migration
privileges, configured schema/search_path, data counts, Cedar parent/ownership
consistency, lock/disk/time budgets and a backup/restore rollback. Do not assume
a binary downgrade can reverse these migrations. No production DB was touched.

Planning estimate, not benchmark: **5–9 engineer-days** for an engineer familiar
with both projects (about 1 day packaging/config inventory, 2–4 days Cedar/API
adaptation, 2–4 days migration/integration/security qualification), plus owner
policy review and scheduling. Re-run native amd64/arm64 hardening, S3, TLS and
authenticated Cedar allow/deny/revocation tests. Broader cloud/engine support
adds effort. This evaluation does not qualify 0.15.1 on UBI, compile the Cedar
port, run a migration rehearsal or measure exploitability/binary-size savings.
