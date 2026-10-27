# TencentDB atomic L1 create — session handoff

Last updated: 2026-10-15

## Current state

- Upstream repo clone: `upstream/TencentDB-Agent-Memory/` inside the LifeOS workspace.
- Implementation branch: `feat/atomic-create-approved-memory`, based on upstream `feat/server_team`.
- Commit: `9979d4ee3729bba198b7ef056bff88ad81ba2aa2` (`feat(memory-core): add atomic L1 create endpoint`), DCO sign-off included.
- Draft PR: [#1604](https://github.com/TencentCloud/TencentDB-Agent-Memory/pull/1604)
  - Head: `yubr-zzh:feat/atomic-create-approved-memory`
  - Base: `feat/server_team`
  - The branch was pushed to the user's fork. Do not push to upstream directly.
- Public PR listings still showed #1604 as open when checked on 2026-10-15; direct GitHub PR detail was unavailable in this session. Recheck its state and CI before any further PR action.
- PR description was rewritten in ASCII-only English after the user reported mojibake; API response confirmed `has_non_ascii=false`.
- The nested TencentDB checkout is currently **dirty**: `MemoryCore/src/core/store/sqlite/memory-store.ts`, `MemoryCore/src/core/store/sqlite/memory-store.atomic-create.test.ts`, and `MemoryCore/src/gateway/v2-router.atomic-create.test.ts` have uncommitted changes. The SQLite change filters exact `recordIds` in a fallback query, with tests for distinct IDs. Preserve these edits; do not clean/reset them.

## What the PR implements

- Adds `POST /v3/atomic/create` and TypeScript/Python v3 SDK methods.
- The committed branch HEAD `9979d4ee` implements create-only semantics through optional storage-native insert, not read-then-upsert or a Gateway lease:
  - SQLite uses plain `INSERT` under the primary-key constraint.
  - MongoDB uses `insertOne`; create is enabled only on standalone/replica-set topologies. Sharded topology fails closed because global `_id` uniqueness is not guaranteed unless it is part of the shard key.
  - Stores without the optional atomic-create capability return `501`; no fallback to overwrite-style upsert.
- Same scoped ID + same payload is idempotent; same ID + different payload conflicts; cross-scope records are concealed as not found.
- Updates docs/changelogs and metadata query/search round-trip.
- TCVDB is intentionally unsupported and returns 501 in this PR for now. This is partial backend coverage, not a completed LifeOS TCVDB first-write integration. The current uncommitted SQLite query fix only addresses exact-ID lookups and does not add TCVDB create support.

## Validation

Passed:

- Node 24 `--experimental-strip-types --check` on 17 changed TypeScript files.
- `git diff --check` in both the nested TencentDB repo and outer workspace.

Not run:

- Vitest and TypeScript typecheck: dependencies/node_modules are absent.
- No dependency installation was performed; the user previously asked not to install dependencies.
- No live TCVDB, MongoDB, or Gateway integration test was run.

Do not mark local test verification complete in the PR unless those gates are later run.

## TCVDB open question

Official VectorDB documentation conflicts:

- HTTP `/document/upsert` docs say an existing document with the same ID is replaced: <https://cloud.tencent.com/document/product/1709/95121>
- VectorDB FAQ says insert does not overwrite an existing ID, but does not identify the endpoint/SDK method/version or concurrent atomicity: <https://cloud.tencent.com/document/product/1709/104774>
- This repo's TCVDB client only calls `/document/upsert`. The public Tencent Go SDK API model exposes `UpsertReq` and `UpdateReq`; no distinct document insert request was found: <https://pkg.go.dev/github.com/tencent/vectordatabase-sdk-go/tcvectordb/api/document>

Current conclusion: this adapter has no atomic create implementation. Do not claim the VectorDB service definitively lacks such a primitive; the FAQ wording remains unresolved.

## Next steps

1. Check PR #1604 and CI/reviewer feedback. Confirm whether a related issue exists; no issue number is currently linked in the PR, so do not invent one.
2. Ask maintainers what exact endpoint/SDK method the FAQ's “insert” describes, including version, duplicate-ID response, and concurrent atomicity.
3. Based on the answer, either implement/test TCVDB `createL1` using a verified atomic primitive, or keep the PR explicitly partial and discuss whether maintainers accept the backend limitation.
4. Run focused Vitest and TypeScript typecheck in an environment with dependencies already present. Do not install dependencies without renewed user authorization.
5. Only mark the PR ready after scope and test state are accurate; the PR is currently Draft.

Useful test files:

- `MemoryCore/src/gateway/v2-router.atomic-create.test.ts`
- `MemoryCore/src/core/store/sqlite/memory-store.atomic-create.test.ts`
- `MemoryCore/src/core/store/mongodb/memory-store.atomic-create.test.ts`

Existing broader handoff: [`memory-module-handoff.md`](memory-module-handoff.md). Proposal and issue draft: [`tencentdb-approved-atomic-create-proposal.md`](tencentdb-approved-atomic-create-proposal.md), [`tencentdb-atomic-create-issue-draft.md`](tencentdb-atomic-create-issue-draft.md).
