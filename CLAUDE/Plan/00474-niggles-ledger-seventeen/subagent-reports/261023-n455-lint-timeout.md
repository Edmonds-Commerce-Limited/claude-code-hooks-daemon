# N455: a lint timeout is not lint_on_edit's acceptance verdict

Branch `worktree-n455-lint-timeout-probe`, base d022f1cd7. Code head **d76f1efab** (fix 3cfbfa8dd, QA follow-up
d76f1efab). This report is committed on top of it.

## The signal used

The handler emits no structured timeout field. A timeout reaches the live harness only as response text, and reaches
the in-process contract only as `BlockingResult.context`. So, as the brief allows, the handler module now exports the
advisory's opening as a template:

- `LINT_TIMEOUT_NOTICE` in `src/claude_code_hooks_daemon/handlers/post_tool_use/lint_on_edit.py` is
  `"⚠️ {language} lint check timed out after {budget}s for {file_name}"`. The timeout branch formats its message
  from it, so the user-visible text is unchanged.
- `src/claude_code_hooks_daemon/daemon/playbook_harness.py` builds its regex from that same constant
  (`_template_pattern`, which escapes the literals and turns each field into a named group). No copy of the prose
  exists anywhere else. `lint_timeout(text)` returns `LintTimeout(language, budget)` or `None`.
- `inconclusive_probe(probe, decision, text)` returns an `InconclusiveProbe` only when all three hold: the probe is
  a lint_on_edit probe (`is_lint_probe`, keyed on `LintOnEditHandler.__name__`), the decision was not a refusal, and
  the text carries the timeout. Otherwise the result goes through `verdict` exactly as before.

Both harnesses use it:

- `tests/acceptance/test_playbook_harness.py`: `_run_probe` tries `inconclusive_probe` before `verdict`.
- `tests/integration/test_acceptance_contract.py`: `_drive_executable_probe` takes an optional `inconclusive`
  collector. `_ContractRun` replaces the earlier `(failures, driven)` tuple, and its `settle_inconclusive()` applies
  the guard.

The order in both is: assert there are no failures, then apply the threshold guard, then `pytest.skip` with
`INCONCLUSIVE, not passed: #N LintOnEditHandler: the Swift linter timed out after 15s, ...`. A skip can therefore
never hide a real mismatch.

## The threshold

`MAX_LINT_TIMEOUT_SHARE = 0.2` in `playbook_harness.py`. A run fails as "linter unusable on this runner" when every
lint_on_edit probe in it timed out, or when more than 20% did. The denominator is the lint_on_edit probes the run
actually dispatched.

## Tests

RED was confirmed first (ImportError on the new names), then GREEN.

In `tests/unit/daemon/test_playbook_harness.py`, `TestALintTimeoutIsInconclusive`:

- The recogniser is checked against the handler's own timeout output: a real `LintOnEditHandler` is driven with a
  mocked `TimeoutExpired`.
- Language and budget are extracted.
- Other advisories are not read as a timeout.
- A timed-out deny probe is inconclusive, with a reason naming the probe, the language and the budget.
- A real wrong decision is not inconclusive and still fails `verdict`.
- A refusal is never inconclusive.
- Another handler's probe is never inconclusive.
- One timeout in 20 probes gives a skip, not a failure.
- All lint probes timing out is a failure.
- Just over the declared share fails, and exactly at it does not.
- A run with no timeouts reports nothing.

In `tests/integration/test_acceptance_contract.py`, `TestALintTimeoutIsNotTheHandlersVerdict`:

- A real lint_on_edit deny probe whose linter is made to overrun is collected as inconclusive.
- Without a collector, the same probe still fails.

The live playbook harness needs a running daemon, so it was not run here. Its logic is the unit-tested functions
above, and it passed the type and lint checks in QA.

## Ledger

N455 in `NIGGLES.md` now records the run 39958669305 recurrence and a 🟡 status: the acceptance half is fixed on
this branch, and the timing-bound half (N376 class) is still open. In `STATUS-INDEX.md` the row keeps its 6 pipe
fields and its column widths, and the status cell now reads `🟡 Acceptance half fixed`.

## QA

On a clean committed tree at d76f1efab, run in the foreground:
`FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --range d022f1cd7..HEAD --allow-unmapped`

Result: **`QA: 41/41 PASSED`**.

The first run failed two checks, and both are now fixed without suppressions:

- `magic_values` flagged literal `15` timeouts in the tests. They now use `Timeout.LINT_CHECK`.
- `pyright` flagged Optional and union narrowing in the new unit tests. Explicit narrowing asserts fixed it.
