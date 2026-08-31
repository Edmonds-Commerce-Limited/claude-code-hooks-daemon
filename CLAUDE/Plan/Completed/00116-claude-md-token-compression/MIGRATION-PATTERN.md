# Migration Pattern: verbose-first/terse-after via Rule + DisclosureTracker

Recipe used to migrate `destructive_git` (Plan 00116, Phase 3, Task 3.2), for
the parallel Phase 3 fan-out agents migrating the remaining blocking handlers.
Read this instead of re-deriving the approach from PLAN.md.

## Preconditions (already done, do not redo)

- `core/rule.py` — `Rule` dataclass + `RuleFormatter` (`table_row`/`terse`/`verbose`).
- `constants/rule_ids.py` — `RuleID` constants. **Add your handler's IDs here**
  if they are not already present (check first — several handlers' IDs were
  pre-declared alongside `destructive_git`'s in Phase 2).
- `core/data_layer.py` — `DaemonDataLayer.disclosure` property, backed by a
  `DisclosureTracker()` singleton, reset alongside session/history/transcript
  in `.reset()`. Reach it via `get_data_layer().disclosure` — never construct
  a `DisclosureTracker()` yourself in a handler.
- `handlers/pre_compact/disclosure_reset_pre_compact.py` and
  `handlers/session_start/disclosure_reset_session_start.py` already reset
  disclosure state for the firing agent on PreCompact and SessionStart. You
  do not need to touch reset wiring — it is handler-agnostic (keyed by
  `transcript_path` + `rule_id`, not by handler name).

## Imports

```python
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
```

(`GatingResult` for a `PreToolUseHandlerBase` — use whatever result type your
handler's base already narrows to; the shape below is base-agnostic.)

## Shape

1. **Keep `matches()` and any pattern-matching helpers UNTOUCHED.** The
   no-matching-behaviour-change contract (NG2) applies to *what* is blocked,
   not to the message. If your handler currently derives a message from the
   matched pattern (a `_match_reason`-style method), leave that method alone
   — it is still fine to use for `matches()`'s own logic — and add a
   **parallel, index-aligned mapping to `RuleID`** rather than touching it:

   ```python
   _PATTERN_RULE_IDS: tuple[str, ...] = (
       RuleID.SOME_RULE,
       RuleID.SOME_OTHER_RULE,
       ...  # same length and order as your existing pattern list
   )
   ```

   Zip it onto your compiled patterns once in `__init__`, and add a small
   `_match_rule_id(command)` that mirrors your existing match method exactly
   (same ordered list) so the two can never disagree about what fired first.

2. **Declare one `Rule` per unique `RuleID`** (Decision B: per-rule
   granularity — several raw patterns can share one `RuleID` when they are
   the same conceptual violation, e.g. `destructive_git`'s bare
   `git checkout .` and `git checkout -- file` both map to
   `R-GIT-CHECKOUT-DISCARD`). Build them once in `__init__` from a single
   source-of-truth tuple:

   ```python
   _RULE_DEFINITIONS: tuple[tuple[str, str, str, str], ...] = (
       (RuleID.SOME_RULE, "`the blocked literal`", "Why it's blocked", "The fix"),
       ...
   )
   ```

   `blocked` MUST contain the load-bearing literal **verbatim** (Phase 1.2's
   term-set contract). `why`/`fix` are one-liners — the terse reminder is
   `blocked — why. Fix: fix.` `verbose` is the FULL first-fire teaching
   content: reuse your handler's existing rich block-message prose (safe
   alternatives, consequences, "ask the user") as close to verbatim as the
   static-per-rule shape allows — a `Rule.verbose` has no access to the
   invocation's actual command text, so drop any `Command: {command}`
   interpolation; the agent already has the command it just ran.

3. **`get_rules()`**: `return list(self._rules)` where `self._rules` is built
   once in `__init__` from `_RULE_DEFINITIONS`.

4. **`handle()`** — replace any existing count/ladder-driven verbosity with:

   ```python
   rule_id = self._match_rule_id(command)
   if rule_id is None:
       # defensive fallback for the (should-be-unreachable) case where
       # handle() runs without matches() having gated it first
       ...
   rule = self._rules_by_id[rule_id]

   transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
   tracker = get_data_layer().disclosure

   if transcript_path and tracker.was_disclosed(transcript_path, rule_id):
       message = self._formatter.terse(rule)
   else:
       if transcript_path:
           tracker.mark_disclosed(transcript_path, rule_id)
       message = self._formatter.verbose(rule)

   return GatingResult(decision=Decision.DENY, reason=message)
   ```

   **Fail-toward-verbose is load-bearing** (plan risk table): a missing/falsy
   `transcript_path` must ALWAYS take the verbose branch and must NEVER call
   `mark_disclosed` (there is no key to mark). Do not "fix" this into a
   shared fallback bucket — that would turn "unknown state" into "shared
   disclosure across every agent with no transcript", which is the opposite
   of what Decision G requires.

5. **Delete** the handler's old count-driven ladder methods
   (`_get_block_count`/`_terse_reason`/`_standard_reason`/`_verbose_reason` or
   equivalent) — they are fully replaced.

6. **Do not touch `get_claude_md()`** — Phase 5 (the injector two-tier
   rewrite) owns that; Phase 3 only changes the *block-time* message.

## Tests

- RED first, as always. Delete/rewrite any test asserting the old
  count-driven ladder (`mock_dl.history.count_blocks_by_handler.return_value = N`) — those tests describe removed behaviour.

- **Reset `get_data_layer()` between tests.** It is a process-wide singleton;
  without resetting, one test's `mark_disclosed` leaks into a later test that
  reuses the same `(transcript_path, rule_id)` pair and turns a genuine
  "first fire" into a stale "already disclosed". Add an autouse fixture:

  ```python
  @pytest.fixture(autouse=True)
  def _reset_disclosure_tracker():
      reset_data_layer()
      yield
      reset_data_layer()
  ```

- New/changed assertions to add:

  - `get_rules()` returns the expected count, all unique `rule_id`s, every
    `rule_id` is a `RuleID` constant, every `verbose` is non-empty.
  - Every deny `reason` **starts with** `f"BLOCKED [{RuleID.X}]"` — this is
    the Phase 7 parity contract (every terse/verbose message leads with a
    table `RuleID`).
  - First fire (fresh `transcript_path`) is verbose: your handler's old
    "PERMANENTLY DESTROYS"/"SAFE alternatives"-style markers should now be
    presence-asserted on the FIRST call only.
  - Second fire, same `(transcript_path, rule_id)`, is terse: those same
    markers must be ABSENT.
  - A different rule for the same agent, or the same rule for a different
    `transcript_path`, is independently verbose (multi-agent isolation —
    Decision G's whole reason for keying on `transcript_path` rather than
    `session_id`).
  - Missing `transcript_path` in the hook payload is verbose on every call,
    not just the first.

- Keep every existing `matches()`/pattern test untouched and green — that is
  your proof of NG2 (zero matching-behaviour change).

## Pitfalls hit migrating `destructive_git`

- **Arbitrary length assertions on messages are fragile.** The terse
  reminder now always carries the `Full detail: run the hooks-daemon skill with args '...'` pointer suffix, so a hardcoded `len(reason) < 200` from an
  old test can fail even though the message is genuinely terse. Assert the
  ABSENCE of verbose-only markers instead of a length bound.
- **The singleton leak above is easy to miss** because handler-level unit
  tests historically patched `get_data_layer` per-test (via
  `unittest.mock.patch`) rather than touching the real singleton — once you
  switch even a few tests to calling `handler.handle()` directly against the
  real tracker (which you should, for the multi-fire ladder tests), the
  module-wide autouse reset fixture becomes necessary.
- One handler's rules are entirely independent of every other handler's —
  there is no cross-handler dedupe needed in `RuleID`/`Rule` construction,
  only within your own handler's `_RULE_DEFINITIONS`.

## Reference implementation

`src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py` +
`tests/unit/handlers/test_destructive_git.py` (see
`TestDestructiveGitGetRules` and `TestDestructiveGitDisclosureLadder`).

## Convention: always-shown dynamic suffix (added mid-fan-out, 2026-08-31)

Two kinds of interpolated content in deny messages, treated oppositely:

- Content the agent ALREADY HAS (its own command echoed back): drop from
  Rule.verbose per the original guidance.
- Content the agent NEEDS and does NOT have (a suggested corrected command,
  the matched span, the computed next plan number, dynamic lint findings):
  keep Rule.verbose static (teaching only) and append the dynamic piece as a
  suffix on EVERY fire regardless of disclosure state — a terse repeat-fire
  must still carry the concrete fix/evidence, not just the rule ID.

## Convention: pathspec commits in the shared tree

`git add <mine> && git commit` is NOT safe in a shared index — a sibling's
staged files ride in. Use `git commit -- <explicit paths>` so only the named
paths are committed regardless of what else is staged.
