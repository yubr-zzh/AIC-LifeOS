# TencentDB Agent Memory upstream issue draft

> 状态更新（2026-10-15）：同一能力已提交为 [PR #1604](https://github.com/TencentCloud/TencentDB-Agent-Memory/pull/1604)，公开 PR 列表仍显示 open。本 issue 草稿暂不应重复发布；PR 中 SQLite/Mongo 已有 create-only 路径，但 TCVDB 当前不支持，Gateway 部署与真实服务行为仍待核验。若 PR 被拒或维护者要求拆分，再基于本文补充 TCVDB 专项问题。

## Title

`[Feature] Add a create-only API for caller-approved L1 atomic memories`

## Body

### Use case

An external memory system may already have extracted and reviewed an atomic memory and need to persist that exact record in TencentDB L1. Sending the source conversation through the extraction pipeline is not equivalent: it may re-extract, merge, or alter the approved memory.

### Current behavior

- The current default branch (`feat/server_team`) routes L1 `update`, `query`, `search`, `delete`, and `count`; it has no `atomic/add` or `atomic/create` route.
- `atomic/update` requires an existing ID and returns 404 when it is missing.
- The official TypeScript and Python v3 clients expose update/query/search/delete/count, but no L1 create method.
- `IMemoryStore` exposes `upsertL1`, not create-only insertion. The TCVDB store calls VectorDB `/document/upsert`, whose HTTP docs say an existing document with the same ID is replaced. The official FAQ separately says insert does not overwrite an existing ID, but does not identify the corresponding endpoint/SDK method or its concurrent atomicity. The public Go SDK API model documents `UpsertReq` and `UpdateReq`, but no distinct document insert request. Please clarify which current API/SDK operation the FAQ describes and whether duplicate-ID rejection is atomic under concurrent writes.

There is also a documentation mismatch: `README.deployment.md` lists `POST /v2/atomic/add` and describes an E2E that adds L1 on one Gateway and queries it from another, but that route and the named E2E script are absent from the current default-branch checkout. Could maintainers clarify whether the route/test were removed, renamed, or documented prematurely?

### Requested capability

Please add a supported direct L1 creation path for a caller-provided atomic memory, separate from `atomic/update` and from LLM extraction. It should preserve the established tenant isolation fields and memory fields, and be available through the intended public API/SDK surface.

Before implementation, guidance is needed on the write contract:

1. Should the endpoint be named `/v3/atomic/add` (matching the deployment guide) or `/v3/atomic/create` (explicit create-only semantics)?
2. What is the supported atomic conflict behavior across SQLite, MongoDB, and especially TCVDB, where the underlying document upsert replaces an existing ID?
3. Should callers supply a stable ID, and if so, should an identical retry be idempotent while a different payload for the same ID returns conflict? If the backend cannot guarantee this, what retry contract is preferred?
4. Which existing `MemoryRecord` fields should be writable by callers, and which must remain server-derived?

### Suggested acceptance criteria

- A direct create call persists the supplied L1 record without invoking LLM extraction or dedup/merge.
- `/v3` isolation remains enforced; callers cannot create records under another tenant’s coordinates.
- Create never silently overwrites an existing record. Conflict/retry semantics are explicit and tested across supported stores.
- A created record is queryable/searchable with its supported metadata and provenance fields preserved.
- TypeScript/Python SDKs, API docs, and tests match the implemented route.
- The deployment guide’s existing `/v2/atomic/add` and Service E2E claims are corrected or backed by the actual route/test.

### Environment / evidence

- Repository: `TencentCloud/TencentDB-Agent-Memory`
- Branch checked: current default branch `feat/server_team`
- Relevant code: `MemoryCore/src/gateway/v2-router.ts`, `MemoryCore/src/core/store/types.ts`, `MemoryCore/src/core/store/{sqlite,mongodb,tcvdb}/memory-store.ts`, and SDK clients under `sdk/memory-core`.
- No actual Gateway deployment or personal data was used for this review.
