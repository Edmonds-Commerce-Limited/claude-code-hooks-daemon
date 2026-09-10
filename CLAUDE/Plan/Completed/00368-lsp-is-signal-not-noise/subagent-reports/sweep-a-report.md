# Pyright sweep — partition A close-out (Task 3.1)

Resumed from the shutdown handoff at `8d7aeb82`. Merged `origin/main`
(conflict only in the journal day-file, resolved by chronological
reordering of the three interleaved handoff entries), then closed the two
remaining gaps in partition A (everything outside `tests/unit/handlers/`).

## Commits on `worktree-plan-00368b`

- `75e3102d` — merge `origin/main`, journal conflict resolved.
- (this session's fix commit — see journal for hash) — the two src-level
  fixes plus the QA verification below.

## Errors fixed

1. **`src/claude_code_hooks_daemon/strategies/lint/__init__.py`**
   (`reportUnsupportedDunderAll`): `LintStrategyRegistry` is only bound via
   a lazy `__getattr__` (avoids a circular import), so pyright could not
   see it as a real module attribute for the `__all__` re-export check.
   Added a `TYPE_CHECKING`-only import of `LintStrategyRegistry` — this
   only exists for the type checker, never executes at runtime, so the
   `__getattr__` lazy-load path (and the tests in
   `tests/unit/strategies/lint/test_init_lazy_import.py` that pin its
   runtime behaviour) are unaffected. 0 errors after; 243 tests in
   `tests/unit/strategies/` pass; ruff and black clean.

2. **`register_all`'s `config` parameter** (requested by the team lead,
   relaying partition B): was `dict[str, dict[str, dict[str, Any]]]`, but
   the body also reads `enable_tags`/`disable_tags` (list/str values) off
   the same event-level dict `tag_skip_reason`/`handler_is_enabled` already
   type as `Mapping[str, Any]`. Retyped `config` to
   `Mapping[str, Mapping[str, Any]]` — read-only (only ever `.get()`'d in
   this function, never mutated), and now matches the honest
   `Mapping[str, Any]` shape the sibling functions in the same file already
   use for the event-level block. 0 errors after.

3. **`tests/unit/install/test_agent_assets.py::test_outdated`**
   (`reportAssertAlwaysTrue`): `historic = spec.historic_versions[0]`
   (a `tuple[str, str]`, statically always truthy) was asserted for no
   reason — a dead variable left over from refactoring, not used anywhere
   else in the test. The real property it gestured at ("the dedupe agent
   carries historic versions") is already the entire point of the sibling
   test `test_dedupe_agent_carries_historic_versions`, so removed the dead
   variable and its tautological assert rather than keep an assertion that
   checks nothing. 35 tests in the file still pass; pyright/ruff/black
   clean.

## `src/claude_code_hooks_daemon/core/result_types.py` — left as documented, verified by experiment

The file's own docstring already argues against "fixing" the two
`reportIncompatibleVariableOverride` errors by widening the narrowed
`decision: Literal[...]` field back to the base `Decision` enum — that
would delete the entire type-safety guarantee the three `HookResult` tiers
exist to provide (an out-of-tier `Decision` becomes constructible again).

Per the team lead's instruction not to leave this without checking for a
real typed alternative, I tried the one that looked promising —
`Final[Literal[...]]` on the override, which pyright's own override-
compatibility rule exempts from the invariance requirement it applies to
ordinary mutable attributes. I reproduced it in a throwaway pydantic 2.13
model (not committed; deleted after the experiment) matching this file's
shape (`BaseModel`, `validate_assignment=True`, narrowed `Literal` field on
a subclass). Result: pyright does go quiet, but at a cost that is not
acceptable — Pydantic v2 treats a `Final`-annotated field carrying a
default value as a **class variable, not a model field at all**:

- `Narrow(decision=Decision.DENY)` silently ignores the constructor
  argument — the instance still holds the class default. This would make
  `BlockingResult.deny(...)` / `GatingResult.deny(...)` /
  `GatingResult.ask(...)` silently produce results whose `decision` is
  always `ALLOW`, defeating the entire purpose of these types.
- Direct mutation (`result.decision = ...`) raises `AttributeError: 'decision' is a ClassVar ... cannot be set on an instance` — which is
  exactly the mutation path `merge_pseudo_results` depends on (the
  docstring already names this as the second axis the design protects).

So `Final` is not a fix, it is a silent-then-loud double regression. A
read-only `@property` override was the other candidate but was not
prototyped: removing `decision` from Pydantic's field system the same way
would also drop it from `model_dump()`/JSON-schema generation, which is
the same category of regression, and a `Generic[HookResult[D]]` redesign
is a different-sized change entirely (touches every construction site
across the codebase, no bounded blast radius, not a "fix a pyright error"
task). Both are out of scope for this sweep.

**Decision**: leave the two `reportIncompatibleVariableOverride` errors in
`result_types.py` as the sole documented exception to Task 3.1's "every
pyright error" goal. This is pyright disagreeing with mypy (the project's
actual QA gate) about variance on a deliberately covariant-narrowed field,
not an unfixed defect — and the one typed workaround that silences pyright
breaks the feature at runtime, which I verified rather than assumed.

## QA (daemon running throughout the final run)

- `pyright --project .`: 432 errors total, all either the two documented
  `result_types.py` exceptions or under `tests/unit/handlers/` (partition
  B, another branch/agent's scope) — 0 in partition A otherwise.
- `./scripts/qa/llm_qa.py all`: first run (daemon not yet started this
  session) showed 25/26, with the only failure explained by 10 acceptance
  tests erroring at setup because no worktree daemon socket existed yet —
  all 10 pass individually in isolation, confirming this was a daemon-not-
  running precondition, not a real regression. Restarted the daemon
  (`bin/hooks-daemon restart`, confirmed RUNNING, PID 178212), reran
  `./scripts/qa/llm_qa.py all`: **26/26 PASSED** (21,747 tests, 0 failed,
  95.4% coverage). Daemon still RUNNING (same PID) after the run.

## Outcome

Partition A (Task 3.1's scope minus `tests/unit/handlers/`) is at 0
pyright errors except the one documented, now doubly-verified exception in
`result_types.py`. Full QA is green. Ready to merge once partition B lands.
