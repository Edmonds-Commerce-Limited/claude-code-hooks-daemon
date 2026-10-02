# Plan 00479 finish: Tasks 2.3, 1.1, 5.1

## Task 2.3 (done, TDD)

Red run before the change: `tests/unit/handlers/status_line/test_usage_indicator.py`
gave `5 failed, 49 passed`. The five `TestCeilingSegment` cases failed on missing
`⛔`, for example `assert '| 📈 5h|7d' == '| 📈 5h|7d ⛔ 80%'`.

Implementation in `handlers/status_line/usage_indicator.py`: the ceiling comes from
`utils.usage_pause_gate.session_ceiling(config, hook_input)`, which wraps
`resolve_host_usage_ceiling` and `effective_hostname`; the config comes through the
injectable `_config_loader` (default `load_project_config`).

Decision on per-window overrides: one figure when both windows share a limit
(`⛔ 80%`), otherwise each limited window labelled (`⛔ 5h 80% 7d 95%`, or
`⛔ 7d 90%` for a single-window ceiling). It is plain text with no background, so
it does not compete with the usage chips' colour bands. It is shown only beside the
usage chips (no usage data hides the whole segment, as before) and is hidden when
no ceiling applies. Green after: `tests/unit/handlers/status_line/` 654 passed.

## Task 1.1 (NOT done: blocked by the tool)

`bin/hooks-daemon remote-docs add https://code.claude.com/docs/en/statusline` exited 1:

> refusing to vendor https://code.claude.com/docs/en/statusline: the fetched content
> matches the sensitive-content pattern `session-uuid`. Nothing was written.

The page's example payload carries a session UUID. The file was not hand-authored
and no exclusion was added. `CLAUDE/Architecture/StatusLine.md` now records that
`rate_limits` is read (usage snapshot, `usage_indicator`, the usage-pause gates)
and names the URL plus why it is not vendored. The task stays unticked, with the
reason noted in PLAN.md; it needs an owner decision (a narrower pattern, or an
accepted redaction).

## Task 5.1 (done)

- `docs/guides/CONFIGURATION.md` (canonical home for `hosts:` and the pause) already
  documented the ceiling; corrected stale text (one-shot UTC cron became recurring
  `*/10 * * * *`; allowed tools now include `SendMessage`/`TaskStop`; a subagent over
  the ceiling does start the pause but its calls are never denied; new subagents
  refused) and added the `⛔` segment and the missing-data rule.
- Handler guidance: `get_claude_md()` of `usage_pause_gate`, `usage_pause_tool_gate`
  and `usage_pause_stop_gate` checked, current; no change.
- Release notes (`CLAUDE/UPGRADES/UNRELEASED/release-notes/`): 212 hosts callout no
  longer says nothing enforces a ceiling; 211 usage-segment callout gains the `⛔`
  paragraph. The 213 pause callout already covers `usage-pause clear`, the owner
  rulings and missing data. The config-changes manifest already has the `hosts:`
  entry.
