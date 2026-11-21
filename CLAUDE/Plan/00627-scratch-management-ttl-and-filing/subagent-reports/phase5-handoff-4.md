# Phase 5 handoff 4 (Task 5.4 done)

## Done

- PreToolUse `scratch_cap_guard` (`handlers/pre_tool_use/scratch_cap_guard.py`, priority 19, `R-SCRATCH-CAP`). Matches only a Bash command that creates a directory under a scratch root (`creates_directory_under`); a Write or a redirect never matches. Reads `untracked/scratch-inventory.json` only; missing/unreadable inventory = allow. At block: deny naming the over-cap keys, the 5 largest entries and `bin/hooks-daemon scratch-sweep --apply`. Never-stranded: if the entries other than LIVE/KEPT/PROTECTED are by themselves below block, it allows with an advisory listing those entries. `caps.mode: advise` allows with an advisory.
- `utils/scratch_dir_creation.scratch_roots(project_root)`: default root plus `resolve_sweep_root(...).path`; the refresher now uses it too (the earlier default-root-only limitation is fixed).
- Registered: `constants/{handlers,priority,rule_ids}.py`, `init_config.py`, both yaml files. This repo's `.claude/hooks-daemon.yaml` now has top-level `scratch: caps: mode: advise` (DESIGN section 8 rollout, until Task 8.3).
- Guidance verdicts added in `tests/integration/test_claude_md_guidance_coverage.py` (guard earns T1; refresher exempt).
- Tests: `tests/unit/handlers/pre_tool_use/test_scratch_cap_guard.py`. Targeted tests, ruff, black, mypy pass. Run pytest with `PYTHONPATH=src /workspace/.venv/bin/python -m pytest` (the worktree has no venv; without PYTHONPATH the source-tree guard aborts).

## Known pending (not a code defect)

- `test_every_earning_handler_has_a_section_in_claude_md` fails until the daemon restarts on this code and regenerates the CLAUDE.md handler block; also regenerate `.claude/HOOKS-DAEMON.md` and `docs/guides/HANDLER_REFERENCE.md` (scratch_cap_guard entry, R-SCRATCH-CAP row) after the merge, as was done for earlier handlers.

## Next

- Task 5.6: must-do item through `session_actions_directive` when anything is due or a cap is at warn: "run `scratch-sweep --apply`" (DESIGN section 10 table). Source data: `read_inventory` + `inventory_caps` (as `handlers/session_start/scratch_sweep.py` does).
- Task 5.5: pressure mode for `scratch-sweep --apply` (DESIGN section 8): only at block, also pack entries NOT yet due, largest directory count first, never LIVE/KEPT/PROTECTED, only those idle for `scratch.caps.pressure_idle_minutes` (default 30); an archive so packed expires no sooner than the entry's TTL plus its verdict's retention. The TTY-confirm gate stays; no other safety rule is relaxed.
