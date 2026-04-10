# Plan: Generated `.claude/HOOKS-DAEMON.md` + Version Cache Flush Fix

**Status**: Complete (2026-03-09)

## Context

The project root `CLAUDE.md` manually maintains sections about handler config, priority ranges, and supported languages. This drifts from reality when handlers are added/changed.

The real problem: agents in plan mode write to `~/.claude/plans/*.md`, which the `markdown_organization` handler intercepts and redirects to `CLAUDE/Plan/`. This redirect works but is a hack (DENY + secret file write). If agents knew to write directly to `CLAUDE/Plan/`, the redirect becomes just a safety net.

Solution: A `generate-docs` CLI command that produces `.claude/HOOKS-DAEMON.md` from live config + handler metadata. This file is `@` linked from `CLAUDE.md` and gives agents direct plan-writing instructions.

Additionally, a bug report exists at `untracked/hooks-daemon-upgrade-cache-flush.md` — the upgrade script doesn't clear `version_check_cache.json`, causing stale upgrade indicators.

---

## Part A: `generate-docs` CLI Command

### New Files

**1. `src/claude_code_hooks_daemon/daemon/docs_generator.py`**

`DocsGenerator` class following `PlaybookGenerator` pattern:

- Constructor: `(config: dict, config_raw: Config, registry: HandlerRegistry, plugins, project_handlers)`
- `generate_markdown(include_disabled=False) -> str` — main output method
- `_collect_handlers()` — iterates `EVENT_TYPE_MAPPING`, instantiates handlers, reads config enabled/disabled, collects metadata
- `_render_handler_summary()` — table per event type with Priority | Handler | Behavior | Description
- `_render_plan_mode_instructions()` — conditional section when `track_plans_in_project` is configured
- `_render_config_reference()` — config file location, enable/disable syntax

Handler description: first line of class docstring via `inspect.getdoc()`. Behavior: from tags (BLOCKING/ADVISORY/CONTEXT).

**2. `tests/unit/daemon/test_docs_generator.py`**

TDD tests (written first):

- Header contains version and timestamp
- Handlers grouped by event type
- Priority + behavior columns present
- Disabled handlers excluded (unless flag set)
- Plan mode section rendered when `track_plans_in_project` set
- Plan mode section absent when not configured
- Handlers sorted by priority within event type
- Description from docstring

### Modified Files

**3. `src/claude_code_hooks_daemon/daemon/cli.py`**

- Add `cmd_generate_docs(args)` function after `cmd_generate_playbook` (~line 1171)
  - Same pattern: load config, create registry, discover, create generator, write output
  - Default output: `.claude/HOOKS-DAEMON.md` relative to project root
  - Args: `--include-disabled`, `--output`
- Add `generate-docs` subparser after `generate-playbook` (~line 2151)
- Update module docstring (line 1)

**4. `CLAUDE.md` (project root)**

Replace the "Configuration" section's inline YAML handler example and "Priority Ranges" subsection with:

```markdown
## Active Configuration

See @.claude/HOOKS-DAEMON.md for the current active handler summary, generated from live config.
```

Keep all non-config sections (architecture, engineering principles, security, planning, QA, self-install).

**5. `scripts/install_version.sh`** (non-fatal step after install)

Add step to generate docs:

```bash
"$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli generate-docs --project-root "$PROJECT_ROOT" || true
```

### Generated File Template (~100-200 lines)

```markdown
# Hooks Daemon - Active Configuration

> Generated on YYYY-MM-DD by `generate-docs`. Regenerate: `$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-docs`

## Plan Mode

> Write plans DIRECTLY to project version control.

**Plan location**: `CLAUDE/Plan/{number}-{name}/PLAN.md`
**Next number**: Scan `CLAUDE/Plan/` (including `Completed/`) for highest number, increment.
**Workflow docs**: @CLAUDE/PlanWorkflow.md

The redirect handler intercepts `~/.claude/plans/` writes as a safety net only.

## Active Handlers

### PreToolUse (NN handlers)
| Priority | Handler | Behavior | Description |
|----------|---------|----------|-------------|
| 10 | destructive_git | BLOCKING | Block destructive git commands |
| ... | ... | ... | ... |

### PostToolUse (N handlers)
[same table format]

### SessionStart (N handlers)
[same table format]

[...each event type with enabled handlers...]

## Quick Config Reference

**Config file**: `.claude/hooks-daemon.yaml`
**Enable/disable**: Set `enabled: true/false` under handler name
**Handler options**: Set under `options:` key per handler
```

---

## Part B: Version Cache Flush Fix

### Bug

After upgrade, `version_check_cache.json` still has `is_outdated: true` for the old version. `daemon_stats.py:104` reads this and shows stale upgrade indicator.

### Fix

**6. `scripts/upgrade_version.sh`** (~line 617, after successful daemon restart)

Add cache flush between Step 14 (daemon restart) and Step 15 (validation):

```bash
# Clear version check cache to prevent stale upgrade indicators
rm -f "$DAEMON_DIR/untracked/version_check_cache.json"
```

**7. `tests/unit/handlers/session_start/test_version_check.py`** — add regression test verifying cache is invalidated when `current_version` in cache doesn't match `__version__`.

**8. Optionally**: Harden `daemon_stats.py` to also compare `cached.current_version` against `__version__` at read time — if they don't match, ignore the cache. This is defense-in-depth.

---

## Implementation Sequence

| Phase | Task                                                                       |
| ----- | -------------------------------------------------------------------------- |
| 1     | Write failing tests for `DocsGenerator` (TDD RED)                          |
| 2     | Implement `DocsGenerator` class (TDD GREEN)                                |
| 3     | Wire up CLI command in `cli.py`                                            |
| 4     | Run tests, verify green + QA                                               |
| 5     | Fix version cache flush in `upgrade_version.sh` + harden `daemon_stats.py` |
| 6     | Update `CLAUDE.md` with `@` link                                           |
| 7     | Add install script step                                                    |
| 8     | Full QA + daemon restart verification                                      |
| 9     | Generate `.claude/HOOKS-DAEMON.md` for this project                        |

## Verification

```bash
# Unit tests
pytest tests/unit/daemon/test_docs_generator.py -v

# CLI command works
$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-docs
cat .claude/HOOKS-DAEMON.md

# Daemon restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Full QA
./scripts/qa/run_all.sh
```
