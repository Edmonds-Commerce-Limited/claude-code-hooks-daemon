# TDD Strategy Module — the Strategy Pattern archetype

This module is the **reference implementation** of the daemon's language-aware
Strategy Pattern: a `TddStrategy` Protocol, one `{language}_strategy.py` per
language, a registry keyed by file extension, and shared utilities in
`common.py` — with zero language logic in the handler.

**Canonical documentation**:
[CLAUDE/Code/StrategyPattern.md](/CLAUDE/Code/StrategyPattern.md) — the
single source of truth for the architecture, Protocol-vs-ABC rationale,
method contract semantics, implementation template and rules, the mandatory
acceptance-test provision, the add-a-new-language TDD walkthrough, and the
anti-patterns. Read it BEFORE adding or changing anything here, and follow
it exactly when building a strategy set for any other domain.

## Edit guards (this directory)

- `registry.py`'s `create_default()` is the single source of truth for which
  languages are registered — never maintain a language roster in docs.
- Strategies import from `common.py` only — never from each other, the
  handler, or `LanguageConfig`.
- Strategy classes inherit from nothing (structural typing); every string
  literal is a module-level `_`-prefixed named constant.
- Every strategy MUST return at least one acceptance test from
  `get_acceptance_tests()` — enforced by
  `tests/unit/strategies/tdd/test_acceptance_tests.py` and the
  `qa/strategy_pattern_checker.py` AST check.

Tests live in `tests/unit/strategies/tdd/` (one file per strategy plus
protocol, common, registry and acceptance-test suites).
