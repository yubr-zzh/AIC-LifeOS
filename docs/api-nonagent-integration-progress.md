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

1. Vault integration: explain the Obsidian Vault folder model and agree on deployment location before implementing filesystem paths or sync endpoints. The upstream code performs explicit SQLite/Markdown import/export and manual sync; it does not provide an automatic watcher or conflict merge.
2. Settings UI: routing preference is now exposed both in chat and Settings; after the Vault deployment model is chosen, add only Vault controls that map to implemented behavior. Provider settings already exist locally and should not be duplicated.

## Completed slice: Work calendar

- Added a calendar navigation page that reads existing structured entries (daily/phase plans and reviews, diary, insight, feedback) through the existing `/entries` client.
- The annual heatmap summarizes record density. Selecting a day lists its entries and links to the existing page for that entry type; it does not create, alter, or replace structured records.
- Added refresh, year selection, loading/error/empty states, keyboard-native buttons, and responsive/dark theme styling.
- Added a settings control for the chat's default routing policy, sharing the same local-storage preference as the chat composer.
- Validation: frontend `npm run build` passed; full frontend suite passed (97 tests, including 2 WorkCalendar tests); `git diff --check` passed.

## Do not port without review

- Do not merge `origin/api&nonAgent` wholesale; it diverges substantially and removes existing memory/bridge code.
- Do not copy TencentDB adapter work from that branch as teammate code: the relevant adapter commits were authored by the user.
- Do not claim automatic two-way Vault sync unless watcher/conflict semantics are implemented and tested.
