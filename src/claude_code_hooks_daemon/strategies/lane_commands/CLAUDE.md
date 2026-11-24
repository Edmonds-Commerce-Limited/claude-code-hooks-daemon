# Lane-command Strategy Module

Per-language Strategy Pattern for `host_seat_lane_guard`
(`handlers/pre_tool_use/host_seat_lane_guard.py`, Plan 00635): one
`LaneCommandStrategy` per language, each declaring the test, build, lint and QA
commands a host seat must not run, a registry with `create_default()`, and a
handler that holds no language logic.

**Canonical documentation**:
[CLAUDE/Code/StrategyPattern.md](/CLAUDE/Code/StrategyPattern.md) - the
archetype this module follows (`tdd` is the reference implementation).

## What differs from the TDD archetype

Nothing is keyed by file or project: a Bash command can run any language's
tool, so the handler merges EVERY strategy's `lane_patterns` and matches the
command against all of them through the shared classifier
(`utils/long_running_command.py`), which peels the common wrappers.

## Edit guards (this directory)

- `registry.py`'s `create_default()` is the single source of truth for which
  languages are registered.
- A strategy imports from `common.py` only - never another strategy or the
  handler.
- The lane keeps its own copy of the shared classifier's test, build and QA
  groups. `tests/unit/strategies/lane_commands/test_registry.py` pins the two
  together in both directions, so a new strategy pattern is also listed there.
- A new pattern ends on whitespace or end of string (`(?=\s|$)`), not `\b`, so
  a neighbouring tool name (`rspec-queue`) is not a lane command; give it a
  negative-neighbour test.
- Every strategy MUST return at least one acceptance test - enforced by
  `tests/unit/strategies/lane_commands/test_registry.py` and
  `qa/strategy_pattern_checker.py`.
