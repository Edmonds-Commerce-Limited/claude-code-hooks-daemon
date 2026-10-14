# N463 report: registry-wide handler invariants in targeted QA

Plan folder: CLAUDE/Plan/00474-niggles-ledger-seventeen/

## Disagreement with the brief

The selection logic needed no change. `scripts/qa/changed_tests_map.yaml` already
carries one declared rule (N382) that pins the registry-wide handler tests for
any change under `src/claude_code_hooks_daemon/handlers/*`, and
`tests/unit/qa/test_handler_enumerating_tests_are_selected.py` guards that list.
The defect was in the DATA, in two places:

1. The list did not contain `tests/unit/handlers/test_pretooluse_fail_closed_tagging.py`
   (the test that failed CI), because the guard's regexes only recognise
   `walk_packages` and `HandlerRegistry...discover()`, not
   `iter_builtin_handler_classes()`.
2. Nothing selected the list for an edit to the constants a new handler also
   touches (`constants/handlers.py`, `priority.py`, `rule_ids.py`).

The brief's "keep the list in ONE place" is met by a YAML anchor
(`&handler_invariants`) on the existing list; the three constants rules alias it.

## Changes

- `scripts/qa/changed_tests_map.yaml`: list gains
  `test_pretooluse_fail_closed_tagging.py`, `test_config_key_consistency.py` and
  `tests/integration/test_skill_surface_coherence.py` (found by the widened
  rot guard: it checks the optimise checklist covers the whole registry, and was
  also unpinned). Three new rules (constants `handlers.py`, `priority.py`,
  `rule_ids.py`) alias the same list.
- `tests/unit/qa/test_handler_enumerating_tests_are_selected.py`: `DISCOVERS_HANDLERS`
  now also matches `iter_builtin_handler_classes()` (counted for tests under
  `tests/integration`, and for any listed file); new class
  `TestAddingAHandlerSelectsTheRegistryWideInvariants`.
- `scripts/qa/run_changed_tests.py` and `CLAUDE/QA.md`: untouched (QA.md does not
  document this mapping).

## RED (before the YAML change)

```
FAILED ...::test_a_handler_constants_change_selects_the_pinned_tests[.../constants/handlers.py]
FAILED ...::test_a_handler_constants_change_selects_the_pinned_tests[.../constants/priority.py]
FAILED ...::test_a_handler_constants_change_selects_the_pinned_tests[.../constants/rule_ids.py]
FAILED ...::test_a_new_stop_handler_selects_the_fail_closed_tagging_test
FAILED ...::test_the_known_invariants_are_pinned_and_exist
5 failed, 7 passed
```

The negative case (`constants/timeout.py` selects none of them) passed both before
and after, so ordinary runs stay small.

## GREEN

`test_handler_enumerating_tests_are_selected.py`, `test_run_changed_tests.py` and
`test_glob_readers_are_declared.py`: 147 passed. The widened rot guard first
failed on `test_skill_surface_coherence.py` (unpinned); pinning it made it pass.

## Runtime

The full pinned list (22 files, 1913 tests) runs in 71 s. The three additions are
about 7 s of that (the two unit files, 250 tests, take 4 s). The other 19 files
were already selected for any handler change.

## Release note

None. `scripts/qa/` and `tests/` are this repository's own tooling and do not ship
to client installs.

## No QA exclusion or allowlist entry was added.
