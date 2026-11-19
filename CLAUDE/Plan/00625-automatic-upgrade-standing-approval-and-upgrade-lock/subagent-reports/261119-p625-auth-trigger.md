# Plan 00625 Phases 2 and 6: authorisation and trigger (report)

## What changed

- `src/claude_code_hooks_daemon/handlers/user_prompt_submit/standing_authorisations.py`: new id `daemon-auto-upgrade` (full text, shipped-default text, short forms, supervisor name "automatic daemon upgrades"). Per-entry default via `_DEFAULT_ON_IDS`; `_entry_state()` resolves OFF / RECORDED / SHIPPED_DEFAULT (explicit `enabled: false` wins; non-boolean leaves the default). Unlisted entry gets "the daemon's shipped default" wording plus the opt-out line; listed-enabled gets the "recorded in" wording. Pure `auto_upgrade_authorised(handler_config)` added. Docstring Decision 3, `get_claude_md` and the acceptance test updated.
- `src/claude_code_hooks_daemon/install/auto_upgrade.py` (new): `ATTEMPT_DIR_NAME`, `AttemptStatus`, `AttemptRecord`, `attempt_state_path`, `read_attempt_record`, `project_authorises_auto_upgrade(config_path)`, frozen `Eligibility`, `check_eligibility(...)` (reasons: not authorised, self-install, release-state.json, not newer, MAJOR, unparsable, attempt record).
- `src/claude_code_hooks_daemon/handlers/session_start/version_check.py`: `_outdated_context` / `_auto_upgrade_eligibility`. Eligible: AUTO-UPGRADE AUTHORISED advisory. Authorised but refused: today's wording plus "Not automatic: <reasons>" and, for a record, "not retried until a newer release". Not authorised or no project context: unchanged. Cached-outdated path unchanged (still falls through to ls-remote).
- `.claude/hooks-daemon.yaml` (entry `enabled: false`, commented), `.claude/hooks-daemon.yaml.example`, `docs/guides/HANDLER_REFERENCE.md`.
- Tests: `tests/unit/handlers/user_prompt_submit/test_standing_authorisations.py` (extended; `_enable` now switches the default-on entry off so existing assertions keep their meaning), `tests/unit/install/test_auto_upgrade.py` (new, 29), `tests/unit/handlers/session_start/test_version_check_auto_upgrade.py` (new, 8).

## Decisions worth knowing

- A missing, unreadable or non-mapping project config is treated as NOT authorised (an opt-out may be in it); an absent handler block or entry is authorised.
- `upgrade.sh` must write `<daemon untracked dir>/auto-upgrade/v<version>.state` with `status=failed|needs-human`, `target`, `from`, `detail` (unknown status reads as failed).
- `install/auto_upgrade.py` imports the pure function from the handler module (install -> handlers direction); no import cycle observed.

## Commands and results

All run with `PYTHONPATH=<worktree>/src /workspace/.venv/bin/python -m pytest ... --no-cov` (worktree has no `.venv`):

- standing_authorisations tests: 70 passed (RED first: ImportError on the new names).
- test_auto_upgrade.py: 29 passed. version_check tests (`-k version_check`): 98 passed.
- tests/unit/config, user_prompt_submit, session_start, test_auto_upgrade.py: 2110 passed.
- tests/integration test_claude_md_guidance_coverage, test_example_config, test_handler_reference_check: 441 passed.
- mypy and `ruff check` clean on every changed source and test file.

## Not done / found

- `/workspace/CLAUDE.md`'s auto-generated hooksdaemon block and `scripts/qa/declared-invariant-pairs.yaml` need no change (the pair names `_is_automated_prompt`, untouched); `handler_profiles.py` lists handler names only.
- The `v3.76.0` config-changes manifest and release note 003 (another agent's files) should mention the `daemon-auto-upgrade` opt-out snippet; I did not edit them.
- Not run: the whole suite and `llm_qa.py` (coordinator's gate).
