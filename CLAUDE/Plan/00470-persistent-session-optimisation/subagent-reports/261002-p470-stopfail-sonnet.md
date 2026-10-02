# Plan 00470 Task 3.1 - StopFailure recorder, resolver and status chip

## What the vendored doc says

`remote-docs/code.claude.com/docs/en/hooks.md`, "StopFailure": runs instead of
`Stop` when the turn ends on an API error. Claude Code ignores its output and
exit code (apart from `terminalSequence`), so the failure can only be made
visible by recording it and showing it elsewhere. Payload: common fields plus
`error`, optional `error_details`, optional `last_assistant_message`. The
`error` values are `rate_limit`, `overloaded`, `authentication_failed`,
`oauth_org_not_allowed`, `account_on_hold`, `billing_error`, `invalid_request`,
`model_not_found`, `server_error`, `max_output_tokens`,
`cloud_credential_error`, `unknown`. The three recorded spellings match exactly.

## Design

- `utils/stop_failure_records.py`: `stop-failures.json` under the daemon
  untracked dir, modelled on `cron_records.py` (atomic write via
  `write_json_atomically`, lock, fail-open, `default_records_path`). A record is
  `session_id`, `error`, `recorded_at`, `resolved_at`. History is bounded by
  count (50, oldest dropped). Only the error type is stored, never
  `error_details` or the API message.
- `handlers/stop_failure/stop_failure_recorder.py` (priority 50, non-terminal):
  matches only the three errors, records, answers `{}`.
- `handlers/user_prompt_submit/stop_failure_resolver.py` (priority 38,
  non-terminal): on every prompt marks that session's unresolved failures
  resolved; writes only when there is one.
- `usage_indicator` gains a red `⚠ <label> HH:MM` chip (labels: `usage limit`,
  `auth failed`, `cloud credential`) from `latest_unresolved`, shown even with
  no usage snapshot, like the pause chip. Extended an existing segment rather
  than adding a handler: it already owns the pause chip and the usage state.

## Resolution signal, and why

A failure is resolved by a later UserPromptSubmit in the same session. A prompt
is the one event every way of continuing passes through (a human, a cron tick,
a resume), and a successful turn always began with one, so a separate
successful-Stop signal adds a third handler and nothing the prompt does not
already imply. A prompt that fails again records a newer, unresolved failure.

Known imprecision: a prompt the failsafe suppressor drops (priority 37,
non-terminal deny) still reaches the resolver, so a suppressed tick resolves the
chip without the model having run. `usage_pause_gate`'s terminal deny (priority
9\) does stop the chain, so a held prompt does not resolve it.

## Wiring

Registry discovery is by directory (`EVENT_TYPE_MAPPING` already had
`stop_failure`); `.claude/settings.json` and `.claude/hooks/stop-failure`
already forward the event, so no settings file needed editing. Added
`HandlerID`/`Priority` constants, `init_config.py` (new `stop_failure` section
and the resolver), `.claude/hooks-daemon.yaml.example`, this repo's
`.claude/hooks-daemon.yaml` (both enabled), and regenerated
`.claude/HOOKS-DAEMON.md`. `tests/daemon/test_init_config.py` counted 12 event
types and discovered handlers from a fixed directory list; both now include
`stop_failure` (13). The worktree event handlers are absent from the init
template, so this is the first new event section there.

Both handlers are silent, so each has a reasoned entry in
`_EXEMPT_FROM_GUIDANCE` in `tests/integration/test_claude_md_guidance_coverage.py`
(an existing mechanism, not a new kind of exemption). No resident guidance:
agents never see the failure, the status line is for the human.

## Not done

- No live end-to-end check of a real StopFailure; the daemon was not restarted.
- Nothing reads the record for the Task 3.2 re-brief; that task owns it.
