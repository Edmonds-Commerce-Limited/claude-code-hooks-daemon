# Plan 00368 Phase 3 — zero-close-out report

**Branch**: `worktree-plan-00368d` (from `main` after every prior 00368
branch merged). Pushed through `abec1081d`.

## Result

`pyright --project .` is 0 errors across the whole tree. `mypy src/` is 0
errors. Full QA (`./scripts/qa/llm_qa.py all`) is 27/27 PASSED, including
22054+ tests, 0 failed. Daemon confirmed RUNNING after every restart. PLAN.md
Phase 3 tasks and Success Criteria ticked, `**Status**: Complete`.

## The three error groups (141 measured on main)

1. **135 errors — `.claude/ccy/plugins/marketplaces/` (vendored third-party
   Claude Code plugin code)**. Added `ProjectPath.CCY_PLUGINS_DIR`
   (`constants/paths.py`) as the single source both `pyrightconfig.json`'s
   exclude and `lsp_noise_checker`'s `required_excludes()` read, so every
   language's LSP-noise strategy learns about it too (confirmed each
   strategy receives the shared `required` frozenset as a parameter, no
   separate per-language list to update). This tree doesn't exist in a fresh
   worktree checkout (it's `.claude/ccy/`-runtime, gitignored), which is why
   the local baseline measured only 6 errors, not 141.
2. **4 errors — `test_dependency_system.py`**. `router.get_chain(...).handlers`
   elements typed as the generic `Handler` accessed
   `_close_requires_human_approval`/`_merge_to_main_requires_human_approval`.
   Fixed with `assert isinstance(gate, PlanCloseApprovalHandler)` /
   `MergeToMainApprovalHandler` at all 4 sites — never `getattr`, never `cast`.
3. **2 errors — `result_types.py`'s `reportIncompatibleVariableOverride`**.
   `AdvisoryResult`/`BlockingResult` each re-declared `decision: Literal[...] = Decision.ALLOW`, overriding the base's mutable field —
   pyright demands invariance there, mypy only a subtype (why this survived
   under mypy-only QA). `Final[Literal[...]]` was already ruled out
   (pydantic v2 treats it as a `ClassVar`, silently dropping the constructor
   arg). Fix: `HookResult` is now `Generic[DecisionT]`
   (`typing_extensions.TypeVar`, PEP 696 `default=Any` — NOT `default=Decision`,
   which was tried first and found to make every one of the ~103 existing
   bare `HookResult` usages across `src/` invariant-reject a narrowed tier
   instance, reopening the exact "escape the tier" hole Plan 00265 exists to
   close, just at every polymorphic call site instead of 2 named ones); each
   tier now parameterises `HookResult[Literal[...]]` instead of re-declaring
   the field. Verified against both type checkers AND at runtime
   (construction, mutation, `decisions_of()`'s field introspection,
   `tests/integration/test_static_type_safety_is_enforced.py`'s real-mypy
   fixture run — including the override-widening scenario — unchanged).
   Added `typing-extensions` as an explicit `pyproject.toml` dependency
   (`uv add`/`uv lock`, not a hand-edited lock file).

A `git merge origin/main` partway through (Plans 00369–00372 landed)
surfaced 4 more pyright errors and 1 black-format drift in code this plan
never touched — fixed anyway (frozen-dataclass test via non-literal
`setattr()`, a status-line handler-classes helper narrowed with
`issubclass`), since they now blocked this branch's own zero-errors gate.

## Full detail

Journal: `CLAUDE/Plan/00368-lsp-is-signal-not-noise/JOURNAL/00368-Journal-26-09-10.md`
(entries from 13:19 onward) — includes the generic-`HookResult` prototyping
trail (what was tried, what broke, what held) before touching the real file.

## Files changed

- `pyrightconfig.json`, `src/claude_code_hooks_daemon/constants/paths.py`,
  `src/claude_code_hooks_daemon/handlers/session_start/lsp_noise_checker.py`,
  `tests/unit/handlers/session_start/test_lsp_noise_checker.py`,
  `tests/unit/test_pyright_config.py` (ccy-plugins exclude)
- `tests/unit/handlers/test_dependency_system.py` (isinstance narrowing)
- `pyproject.toml`, `uv.lock`,
  `src/claude_code_hooks_daemon/core/hook_result.py`,
  `src/claude_code_hooks_daemon/core/result_types.py` (generic `HookResult`)
- `tests/unit/core/test_claude_md_injector.py`,
  `tests/unit/core/test_segment_explanation.py`,
  `tests/unit/handlers/status_line/test_explain_segment_completeness.py`
  (post-merge fallout, unrelated to this plan's own work)
- `CLAUDE/Plan/00368-lsp-is-signal-not-noise/PLAN.md`,
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/19-lsp-output-is-signal-not-noise.md`,
  `CLAUDE/Plan/00368-lsp-is-signal-not-noise/JOURNAL/00368-Journal-26-09-10.md`

No `# type: ignore`, `# pyright: ignore`, `noqa`, or rule downgrade anywhere
in this branch's diff.
