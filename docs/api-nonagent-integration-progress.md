# api&nonAgent Integration Progress

Target branch: `feat/agent-memory-integration`. This is a selective port, not a branch merge.

## Completed slice: Agent necessity routing

- Added `auto`, `force_self_plan`, and `force_agent` routing policies to `/chat`.
- Clear content requests use the active model for a normal text answer without entering the execution Agent. Unexpected tool calls on this path are blocked before permission review.
- Clear side-effect requests route to the execution Agent. Ambiguous requests use the active model for one routing assessment; on router failure, the runtime conservatively falls back to text-only.
- Responses include route source, reason, confidence, signals, side-effect flag, and optional planning steps. The chat composer exposes the routing choice and renders route metadata.
- This routing decision is not an authorization grant: execution tools remain subject to the existing permission manager.
- Validation: 38 selected backend tests passed; frontend `npm run typecheck` passed; frontend `npm test` passed (95 tests); `git diff --check` passed.

## Pending slices

1. Calendar UI: inspect and selectively adapt the calendar view to the existing structured-entry API and navigation without replacing existing planning/review pages.
2. Vault integration: wait for the user to choose the Vault's deployment location before implementing a filesystem path or sync endpoint. The upstream code performs explicit SQLite/Markdown import/export and manual sync; it does not provide an automatic watcher or conflict merge.
3. Settings UI: after the Vault deployment model is chosen, add only the controls that map to implemented behavior. Provider settings already exist locally and should not be duplicated.

## Do not port without review

- Do not merge `origin/api&nonAgent` wholesale; it diverges substantially and removes existing memory/bridge code.
- Do not copy TencentDB adapter work from that branch as teammate code: the relevant adapter commits were authored by the user.
- Do not claim automatic two-way Vault sync unless watcher/conflict semantics are implemented and tested.
