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

Verified against the official marketplace plugin configs
(`anthropics/claude-plugins-official`'s `.claude-plugin/marketplace.json`,
which carries no `settings`/`initializationOptions` for any language) and
each tool's own docs, never assumed: Python (pyright) and
TypeScript/JavaScript read a real project file (`pyrightconfig.json` /
`tsconfig.json` `exclude`). Go (gopls) has no exclude list at all - the
check is "does a non-project tree hold `.go` files inside the `go.mod`
boundary". Rust (rust-analyzer) also has no exclude list, but workspace
membership IS editable via `Cargo.toml`'s `[workspace] exclude`. PHP
(intelephense) reads no project file whatsoever - client `settings` only -
so the fix is a project-scope LSP plugin re-registering `.php`, scanned
under `.claude/plugins/*/`. See each strategy's own docstring for the
sourced detail.

## Edit guards (this directory)

- `registry.py`'s `create_default()` is the single source of truth for
  which languages are registered.
- A strategy imports from `common.py` only - never another strategy, the
  handler, or daemon path constants directly (the handler resolves those
  into the `required` frozenset every strategy receives as a parameter).
- Every strategy MUST return at least one acceptance test - enforced by
  `tests/unit/strategies/lsp_noise/test_acceptance_tests.py` and
  `qa/strategy_pattern_checker.py`.
