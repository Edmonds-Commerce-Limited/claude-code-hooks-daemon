# Plan 00477 Phase 3 (Tasks 3.1-3.3) and Task 4.1: loud detection

Branch `worktree-p477-loud-detection`. Not merged.

## What the human and the agent see

The state is `_HOOKS_DAEMON_NEEDS_PROVISION`, set by `ensure_daemon` in `init.sh` only inside the existing
NOT_INSTALLED branch (no daemon running, no clone, no leftover venv) and only when `.claude/hooks-daemon.yaml`
and `.claude/provision.sh` are tracked-present and the project root has no `src/claude_code_hooks_daemon/version.py`.
CI enforcement, "still starting", CI passthrough, version mismatch and venv-missing are all decided earlier and
keep their own answers. `emit_hook_error` routes every named event to `_hooks_daemon_emit_needs_provision`.

| Event                          | warn (default)                                                             | block                                        |
| ------------------------------ | -------------------------------------------------------------------------- | -------------------------------------------- |
| SessionStart, UserPromptSubmit | `systemMessage` (human) and `hookSpecificOutput.additionalContext` (agent) | same                                         |
| PreToolUse                     | `additionalContext`, no deny                                               | `permissionDecision: deny`, except provision |
| Stop, SubagentStop             | `systemMessage`, no block                                                  | `decision: block`                            |
| any other event                | `additionalContext`                                                        | `additionalContext`                          |
| status line (raw text)         | `⚠️ HOOKS DAEMON NOT PROVISIONED - run: bash .claude/provision.sh`         | same                                         |

Message: names the checkout, the expected version and where it came from (config, tracked-doc, or "unknown" with
the reason, including an invalid key), says all handlers are INACTIVE, gives `bash .claude/provision.sh` and the
skill call, says no restart and no tracked-file change, and states the mode. An unusable mode value is treated as
warn and named in the message. Shapes follow `contracts/claude-code-hooks/` (`systemMessage` is universal;
SessionStart/UserPromptSubmit/PreToolUse list `additionalContext`).

Status line: the forwarder already sourced `init.sh` and printed `⚠️ DAEMON FAILED` with no daemon, so the path runs.
The generator (`forwarder_generator.py`) now renders `echo "${_HOOKS_DAEMON_STATUS_DOWN_TEXT:-⚠️ DAEMON FAILED}"`;
`init.sh` sets the variable only in this state. The deployed `.claude/hooks/status-line` was updated to match.

## Config key (Task 3.3)

`daemon.unprovisioned_mode: warn|block`, default warn. Read in bash by `_config_daemon_key_raw` (the awk that
`_config_expected_version_raw` used, now parametrised by key; the old function is a one-line wrapper). Added to
`DaemonConfig` as `Literal["warn", "block"]` and to `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.68.0.yaml`.
`ci_enabled: true` is untouched and outranks the mode (tested).

## Block-mode exemption

`_hooks_daemon_stdin_is_provision_command` (system python3, no venv) allows exactly:

- Bash whose whole command is `bash .claude/provision.sh` (spaces/tabs padding only), and only when the cwd in the
  hook input is absolute and `cwd/.claude/provision.sh` resolves to this project's script; or `bash <absolute path to this project's .claude/provision.sh>`;
- Skill with `skill == "hooks-daemon"` and `args` exactly `provision`.

Denied (tested): chained (`&&`, `;`, `|`, newline), extra args, `echo`/`cat` mentions, `$(...)`, backticks, `sh`,
`bash -x`, `BASH_ENV=` prefix, `./.claude/...`, another cwd holding its own script, other skill args, other skills,
non-Bash/Skill tools. With neither jq nor python3 a constant deny is emitted and nothing is exempt.

## Hook-path cost

All the new work sits behind the NOT_INSTALLED branch, so every other state pays nothing (a test asserts awk is not
run outside it). On the no-daemon path (session-start forwarder, fresh-clone fixture, child CPU time because wall
time was dominated by other agents' load on this host, 5 rounds of 40 runs each):

- before: median 73-75 ms CPU per hook; after: median 83-84 ms. Added: about 8-10 ms CPU.
- pieces: expected-version resolve about 4-5 ms (one awk and a subshell), mode read about 2 ms (subshell; awk is skipped
  by a bash-builtin substring prefilter when the key is absent), remainder message build and encoding.

That is more than file-existence tests; the awk read of the config is the bulk of it. It is paid once per hook in
an already-degraded state that also runs a failed start attempt, but it is not negligible.

## Not verified

- Real Claude Code rendering of `systemMessage` (only the JSON shape against the contract; not a live session).
- Behaviour with bash 3.2 / macOS (no bash 4 features were used, but it was not run there).
- The `hooks-relay` fallback path in a fresh clone (relay is absent there; not exercised).
- Under `block`, the skill's own follow-up Bash calls (what the agent runs after the Skill call) are not exempt;
  the message tells the agent to run `bash .claude/provision.sh` directly.

## Docs (Task 4.1)

`CLAUDE/LLM-INSTALL.md`, both copies of the skill's `install.md` (identical, diff clean) and
`docs/guides/TROUBLESHOOTING.md` route a fresh clone to provision; `install.md` no longer calls itself the
fresh-clone command. Release note 193 added; note 187's "a later change" sentence now points at it.

## QA

- New tests: `tests/integration/test_init_sh_needs_provision.py` (64), `tests/unit/config/test_unprovisioned_mode_config.py`
  (8), one in `tests/unit/install/test_forwarder_generator_raw_stdout.py`. Red run before the code: 49 failed, 14
  passed (the 14 were the negative cases).
- Touched test files by path: 373 passed (needs_provision, expected_version, hook_event_names, venv_missing_message,
  pretooluse_fail_closed, repo_guard, stale_clone_version, provision_sh, provision_install_wiring, forwarder raw
  stdout, unprovisioned_mode config).
- ruff, black, mypy on touched Python: clean. `shellcheck -x init.sh .claude/hooks/status-line`: clean.
  `audit_error_hiding.py` and `check_input_contract.py`: exit 0.
- `llm_qa.py changed --base main --allow-unmapped`: first run 25/28 (pyright in the new test, skill_refs on a
  `/hooks-daemon` string in init.sh, live-probe marking of the new test payloads); all fixed; second run 28/28
  PASSED. `changed_tests`: 1656 passed, 0 failed, 67 skipped, 43 test files from 15 changed files (3 unmapped:
  `.claude/hooks/status-line`, `init.sh`, `config/models.py`, all covered by the by-path runs above).

No QA suppressions, no exclusion or allowlist entries, no `|| true`.
