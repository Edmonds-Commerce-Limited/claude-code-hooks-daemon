# N330, N331, N332: verification and fixes

Evidence: the changelog at `https://code.claude.com/docs/en/changelog` and the statusline page at `https://code.claude.com/docs/en/statusline`, both fetched with `curl` on 2026-10-03 into `untracked/scratch/`; `claude --version` = 2.1.288; the vendored `remote-docs` tree (which holds neither a statusline nor a memory page, so it could not settle N330 or N331).

## N330 (adopt `rate_limits.spend_limit`): verified, fixed

- The statusline page documents `rate_limits.spend_limit.used_percentage` and `.resets_at` ("Behind a Claude apps gateway ... Requires Claude Code v2.1.251 or later"), plus `used_usd`, `limit_usd` and `period` ("These fields can be absent"). It also says each window "may be independently absent".
- The changelog agrees (the dollar fields arrived in 2.1.284).
- Change: `core/usage_snapshot.py` reads `spend_limit` with the existing `_parse_window`, keeps it in memory and in the host-wide state file, expires it like the other windows, and exposes `UsageSnapshot.spend_limit` (default `None`).
- Not changed (decisions):
  - It is not counted in `highest_used_percentage()`, the ceiling or the pause gate. It is a gateway dollar budget, not subscription usage.
  - A snapshot still exists only when `five_hour` or `seven_day` does. Making a spend-only payload yield a snapshot would make `usage_indicator._render` print an icon with no chips. A consumer that wants gateway-only sessions must handle that first.
  - `used_usd`, `limit_usd` and `period` are not read: no consumer, and they may be absent.
- Absent-field behaviour is unchanged: every existing test passes, and the old "spend_limit is ignored" test is replaced by an unknown-key test plus seven spend_limit tests in `tests/unit/core/test_usage_snapshot.py`.
- Docs: `CLAUDE/Architecture/StatusLine.md` no longer lists the percentage fields as UNUSED.
- Not observed live: no gateway session is available in this container.

## N331 (`.claude/rules` write-time loading): not a defect

- Changelog 2.1.288: "Fixed path-scoped `.claude/rules` and nested CLAUDE.md files not loading when Write or Edit creates or changes a file in their scope (previously only Read loaded them)".
- `CLAUDE/DirectoryRoles.md` says the rule files are "loaded on demand when matching files are touched". That is correct on 2.1.288, so nothing to correct. No other doc in the repo claims "Read only" (searched `*.md` and `*.py` outside Plan, RELEASES and remote-docs).
- Observed in this session: Reading a file under `CLAUDE/` and `CLAUDE/Plan/` delivered the matching `.claude/rules/agent-docs.md` and `plan-dir.md` content as context. Read-time path-scoped loading works. The Write/Edit-time path was not isolated and rests on the changelog entry alone.

## N332 ("run_in_background has no time limit"): verified, fixed

- Changelog 2.1.288: "Changed the background command time limit to apply only in unattended sessions (`-p`, Agent SDK, CI, cloud); terminal, desktop app and VS Code sessions have no limit". An earlier entry (2.1.285 per the review report) added the limit for all sessions: "Changed background Bash and PowerShell commands to stop after a time limit (their `timeout` with `run_in_background`, default 30 min, max 2 h)".
- So "has no time limit" is false for unattended sessions, true for interactive ones. The vendored `interactive-mode.md` sentence "have no time limit" is about subagent-owned commands and is untouched (vendored text is not edited).
- Corrected at source in `handlers/pre_tool_use/self_matching_process_probe.py` (module docstring, the advisory WHY line, the `Rule` `why` and `verbose` text), `utils/process_probe.py` (docstring) and `docs/guides/HANDLER_REFERENCE.md`.
- `CLAUDE.md` row for `R-UNBOUNDED-LIVENESS-LOOP` was regenerated with `./bin/hooks-daemon regenerate-docs` (the daemon auto-committed it as 27e28df77).
- Left alone: `CLAUDE/UPGRADES/config-changes/v3.63.0.yaml` line 70 ("`run_in_background` has no cap"), a frozen release manifest.
- Pinned by `TestAdvises.test_the_loop_advisory_states_the_limit_applies_only_when_unattended`.

## Ledger

`CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md`: N330 and N332 marked Fixed, N331 marked Not a defect with its evidence.
