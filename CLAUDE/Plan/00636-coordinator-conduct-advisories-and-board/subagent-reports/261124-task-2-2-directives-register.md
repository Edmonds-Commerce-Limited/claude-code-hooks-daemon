# Task 2.2 report: s3 directives register

Handler `owner_directives_register` (UserPromptSubmit, priority 54, advisory, never denies, never terminal).

Built (settled, deterministic):

- `options.directives`: list of `{id, text}`; a repeated id or wording is recorded once (`utils/owner_directives.py`). Bounded (20 entries, 400 chars); a malformed entry or option is skipped with a WARNING.
- Replay on the first human prompt of a session and every `prompt_interval` (default 10) human prompts. Machine turns neither count nor deliver (`utils/automated_prompt.py`, now shared with `standing_authorisations`, whose tests still pass).
- Gate follows `owner_wait_stop_guard`: declared coordinator, coordinator duty, unreadable role or unresolved probe replay; declared worker, no team, sub-agent are untouched. Choice to state: unknown role stays armed (guard parity, PR 226 F4), which for an advisory only adds text. A raising resolver is logged and counts as armed. An empty register never probes.
- Replay text: recorded request, not a fresh human instruction, not a citable approval; no ignore/override wording (tested).
- Paperwork: constants, init_config, example and repo yaml, HANDLER_REFERENCE, config-changes v3.77.0, release note 096, guidance-coverage table (no resident guidance, reason recorded), PLAN.md.

Left out and why:

- Detecting a repeated owner directive from the bus: pingbus v1 history has no author kind; HUMAN verification is Plan 00634.
- Writing a directive into the register (CLI or auto-record): an agent could forge an owner directive.
- Detecting that a seat re-asked a directive: needs bus reads and judgement.
- Config versus a tracked file (lts-infra uses `CLAUDE/owner-directives.md`): owner decision.

DESIGN.md has only one table row for s3 (00630 DESIGN.md section 19); no further s3 text exists.

Tests: new unit tests for the util, the shared helper and the handler; targeted integration/registry/config tests pass (1394). No full QA run.
