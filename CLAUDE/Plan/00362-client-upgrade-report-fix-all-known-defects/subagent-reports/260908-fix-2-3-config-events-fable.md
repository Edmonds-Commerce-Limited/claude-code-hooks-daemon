# Task 2.3 report: config reaches every wired event (D2, D9)

**Branch**: `agent-ab0a7a96306c9c402-0d725519` (worktree
`/workspace/.claude/worktrees/agent-ab0a7a96306c9c402-0d725519`)
**Commits**: `a22fe679` (fix + tests + callout), `44a1f6cc` (Plan 00172 ticks)

## What was wrong

- D2: `HandlersConfig` declared 13 event fields against 31 wired events.
  `_build_handler_config_mapping` (`daemon/cli.py`) iterates `model_fields`,
  and `HandlersConfig` has `extra="allow"`, so a `handlers.<event>:` section
  for any of the other 18 events parsed cleanly as an extra and was then never
  carried to `register_all`. The `field_validator("*")` coercion to
  `HandlerConfig` also only runs for declared fields.
- D9: `PluginConfig.event_type` was an 11-entry hand-written Literal, so a
  plugin targeting `worktree_create`/`worktree_remove` failed validation.

## What changed

`src/claude_code_hooks_daemon/config/models.py`

- `HandlersConfig` declares one `dict[str, Any]` field per wired event, in
  `wired_event_metas()` order (31 fields). Declarations are static because
  pydantic and mypy need real annotations; a module-level
  `_check_wired_event_field_coverage()` raises `RuntimeError` at import if
  the field tuple is not exactly `_EVENT_TYPE_CONFIG_KEYS`, so drift fails
  the daemon loudly instead of dropping config silently.
- `PluginConfig.event_type` is now the catalogue-wide `EventKey` Literal
  (already test-locked to the catalogue), narrowed by a `field_validator` to
  the wired subset derived from the registry. Catalogued-but-unwired events
  (`directory_added`, `pre_model_switch`, `post_model_switch`) are still
  rejected.

`src/claude_code_hooks_daemon/daemon/cli.py`: the
`_build_handler_config_mapping` docstring no longer describes the gap as
open; the function body is unchanged (it already iterates `model_fields`,
which is now the registry mirror). No overlap with Task 1.2's unknown-key
warnings expected beyond adjacent hunks.

## Tests (RED first: 93 failures, then GREEN)

`tests/config/test_models.py`

- `test_every_wired_event_has_a_declared_field` (parametrised x31)
- `test_declared_fields_are_exactly_the_wired_events` (order-exact)
- `test_every_wired_event_coerces_handler_configs` (x31; proves the
  `field_validator("*")` reaches the field)
- `test_event_type_accepts_every_wired_event` (x31) replaces the mirrored
  11-entry list
- `test_event_type_rejects_catalogued_but_unwired_event` (x3)

`tests/unit/daemon/test_cli_handler_config_mapping.py`

- `test_mapping_covers_every_wired_event` (x31)
- `test_disabled_flag_under_any_wired_event_survives_file_load` (x31):
  writes a YAML config with `handlers.<event>.some_handler.enabled: false`,
  loads it via `Config.load`, and asserts the mapping carries `False`. This
  is the end-to-end pin for the previously dropped events.

## Verification

- `pytest tests/config tests/unit/daemon tests/unit/handlers/test_registry.py tests/unit/install tests/unit/test_plugin_loader.py tests/unit/constants`:
  all pass (827 + 2815, 1 skipped).
- `ruff check` and `ruff format --check`: clean on the four touched files.
- `mypy --strict`: clean on `config/models.py`, `daemon/cli.py`,
  `test_cli_handler_config_mapping.py`. `tests/config/test_models.py` carries
  23 pre-existing strict errors on main (pydantic descriptor proxies, str vs
  Literal in old tests); my version has 19, none introduced. The QA gate's
  mypy scope does not fail on them today.
- Daemon NOT restarted (per instructions); no `sed`, no stash.

## Notes for the coordinator

- Release-notes callout: `CLAUDE/UPGRADES/UNRELEASED/release-notes/13-config-reaches-every-wired-event.md`
  (audience `operators`; renumber at merge if 13 collides).
- Plan 00172 Phases 1 and 2 are ticked with `a22fe679`. Phase 3 (schema.py
  stub, generator comments) and Phase 4 (full QA, daemon restart) are left
  for that plan / the Phase 3 verify of 00362.
- The import-time guard means wiring a new event in `constants/events.py`
  without adding the `HandlersConfig` field now breaks import of
  `config.models` with a message naming the missing key. That is deliberate.
- Worktree venv: `scripts/setup_worktree.sh` creates a NEW worktree and
  cannot be run inside an existing one; I ran
  `uv sync --frozen --all-extras --all-groups` into `.venv` in this worktree
  instead (editable install verified to point at this worktree's `src/`).
