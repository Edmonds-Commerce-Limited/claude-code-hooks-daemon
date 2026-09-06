# Plan Workflow

**Read first:** [CLAUDE/core/PlanWorkflow.core.md](core/PlanWorkflow.core.md) — the daemon's core
guidance for this subject, and the baseline everything below extends.

That file is DAEMON-owned: it is refreshed on every daemon upgrade and
overwritten wholesale, so never edit it and never copy its content here.
Everything below is specific to this repository — the Claude Code Hooks Daemon
project itself — layered on top of that shared baseline.

## Self-install path convention

This repository runs the daemon in self-install mode (`self_install_mode: true`; see [CLAUDE/SELF_INSTALL.md](SELF_INSTALL.md)), so the daemon binary lives at the workspace root rather than at the nested client path. Wherever the core document above shows:

```bash
.claude/hooks-daemon/bin/hooks-daemon <command>
```

use this instead:

```bash
bin/hooks-daemon <command>
```

The subcommands themselves (`plan-qa`, `logs`, `validate-project-handlers`, etc.) are identical — only the prefix changes.

## QA Integration

**Before completing any task, this project's full QA suite must pass.**

```bash
./scripts/qa/llm_qa.py all
```

`scripts/qa/run_all.sh` is the single source of truth for which checks exist — do not trust any written enumeration of them. Full QA policy: [CLAUDE/QA.md](QA.md). The `plan_workflow.qa` policy block that the core document's Plan QA section describes is documented in detail in `docs/guides/HANDLER_REFERENCE.md`.

Individual checks:

```bash
./scripts/qa/run_lint.sh          # Ruff linter
./scripts/qa/run_format_check.sh  # Black formatter
./scripts/qa/run_type_check.sh    # MyPy type checker
./scripts/qa/run_tests.sh         # Pytest with coverage
./scripts/qa/run_autofix.sh       # Black + Ruff --fix
```

## TDD Integration

This project enforces Test-Driven Development for implementation work; follow the Red-Green-Refactor cycle the core document describes.

- Minimum test coverage: 95% (see [CLAUDE/QA.md](QA.md), the source of truth for this figure)
- Coverage reports: `untracked/qa/coverage.json`
- Run the suite with `./scripts/qa/run_tests.sh`, or target a single file, e.g. `pytest tests/unit/handlers/pre_tool_use/test_my_handler.py -v`

## Completed-plan retention window

Where the core document's Plan Completion Checklist says to "pick a retention window that suits this project", this project's window is fixed at the **30 highest-numbered completed plans**, enforced by `tests/integration/test_plan_index_navigability.py`. Rows beyond that window move verbatim — no rewording, no trimming — into `CLAUDE/Plan/Completed/README.md`, in the same commit as the status flip.

## Daemon handler implementation

The core document's "Project Handler Implementation Plan Template" covers a *project-level* handler — a custom handler living in a client project's own repository, layered on top of the daemon. That template also applies here whenever this project dogfoods its own project-handler support (see [CLAUDE/PROJECT_HANDLERS.md](PROJECT_HANDLERS.md)).

Most handler work in this repository is different: it develops the daemon's own **core handlers** — the ones shipped to every client project — which follow this project's conventions rather than the project-handler ones.

### Debug first

Before writing a core handler, capture real event flow rather than guessing at `hook_input`'s shape:

```bash
./scripts/debug_hooks.sh start "Testing [scenario]"
# ... perform actions in a live Claude Code session ...
./scripts/debug_hooks.sh stop
```

See [CLAUDE/DEBUGGING_HOOKS.md](DEBUGGING_HOOKS.md) for the complete guide.

### Plan template deltas

Applying the core document's handler plan template to a core handler in this repository:

- **Priority Range**: pick a band from the Priority Guide: [CLAUDE/HANDLER_DEVELOPMENT.md#priority-guide](HANDLER_DEVELOPMENT.md#priority-guide)
- **Test file**: co-located under the mirrored unit-test tree, `tests/unit/handlers/{event_type}/test_{handler_name}.py`
- **Integration phase**: register the handler in its event-type config, run `./scripts/qa/llm_qa.py all`, test in a live Claude Code session, and update documentation

### Development workflow

1. Identify the scenario ("enforce TDD", "block destructive git", etc.)
2. Capture event flow with `./scripts/debug_hooks.sh`
3. Analyse the captured events to determine event type and available data
4. Write tests first (TDD)
5. Implement the handler
6. Run `./scripts/qa/llm_qa.py all`
7. Debug again to verify the handler intercepts correctly
8. Test in a live Claude Code session
