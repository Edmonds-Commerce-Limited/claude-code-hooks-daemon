## 13:02 · decision · —

Decisions taken building the ladder (Tasks 1.1 to 1.3, 1.2a, 1.5, 2.1).

- Level: integer percent thresholds, ceiling-rounded, `count >= base` is BLOCK. Where a small base makes thresholds collapse onto the block point the highest reached level wins.
- Base (1.2a): open pool = `wip.cap + wip.creation_grace` (where creation is actually denied); parked and merged = their effective cap. A pool with `mode: off` gives no level.
- Rate limit: warn and strong show once per session per pool and level (shared by the prompt and tool-call handlers); very strong and block are never limited. Counts are read through a 10 second cache on the every-call surfaces, so a pool that drops below 90 percent goes quiet within that window.
- "Unproven or unfinished first" from strong up: the named branch is the oldest one outside the merged and patch-equivalent groups (merged ones are cleared by a sweep and need no decision); at warn the cheapest-to-close comes first as the deny list orders them. Wording refers to the no-value verdict route of Plan 00620 as not yet shipped and invents no command.
- Handlers: PreToolUse advisor priority 20 (early, non-terminal, so a later terminal allow cannot end the chain before it is gathered) and a UserPromptSubmit twin at 44. Both read the project root, not `cd`, and are silent on any git failure. Neither can deny.
- Session start and the main-thread stop add the ladder as context (all levels, no throttle). The stop hold condition and `refuses` in the creation report are untouched.
- Task 1.5: no `--allow-unproven` mention remains in `docs/guides/HANDLER_REFERENCE.md` on this tree (verified by search); the only live mentions are historical release and plan records. Nothing to change.
- Task 2.1: the stop guard keeps resolving the project root. It judges branches the session touched, recorded in the project's repository; following a command into another clone would judge branches this session did not touch. Pinned by a test where the payload cwd is another clone.
