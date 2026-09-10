# LSP-noise Strategy Module

Per-language Strategy Pattern for `lsp_noise_checker`
(`handlers/session_start/lsp_noise_checker.py`, Plan 00368 Task 2.2): one
`LspNoiseStrategy` per language, a registry with `create_default()`, and a
handler that is a thin orchestrator with zero language logic.

**Canonical documentation**:
[CLAUDE/Code/StrategyPattern.md](/CLAUDE/Code/StrategyPattern.md) - the
archetype this module follows (`tdd` is the reference implementation).

## What differs from the TDD archetype

TDD keys strategies by file EXTENSION (one file, one language). This domain
keys by PROJECT: `strategies` exposes every registered strategy, and the
handler asks each one `is_relevant(context)` rather than resolving from a
path. `exclude_finding()` returns `(advisory_lines, config_path)` -
`config_path` anchors the companion R-LSP-SERVER-STALE check, `None` when
there is no file to have gone stale against yet.

## Why the five strategies differ

Each server offers a different project-level knob, or none, so no two
strategies check the same thing — a real project file for Python and
TypeScript, module/workspace membership for Go and Rust, and for PHP a
project-scope LSP plugin because intelephense reads no project file at all.
Every strategy's own module docstring carries the sourced reasoning,
verified against the official marketplace plugin configs and each tool's
docs rather than assumed. Read the strategy, not a summary here.

## Edit guards (this directory)

- `registry.py`'s `create_default()` is the single source of truth for
  which languages are registered.
- A strategy imports from `common.py` only - never another strategy, the
  handler, or daemon path constants directly (the handler resolves those
  into the `required` frozenset every strategy receives as a parameter).
- Every strategy MUST return at least one acceptance test - enforced by
  `tests/unit/strategies/lsp_noise/test_acceptance_tests.py` and
  `qa/strategy_pattern_checker.py`.
