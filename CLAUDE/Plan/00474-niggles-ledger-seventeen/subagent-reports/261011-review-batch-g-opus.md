STOPPING BECAUSE: review complete. Verdict below.

# Review: Batch G (branch agent-a5313785be3bc54d9-56f41b13, tip 7e4fef412)

**Verdict: CHANGES REQUIRED.** There is one narrow change, to the N353 exemption. The fixes for N340 and N367 and the ledger entry for N369 are acceptable.

## Targeted tests
- Branch: 62 passed, 3 failed. The 3 failures are all in `TestSemgrepGateFailsClosed`, and they come from the environment, not from this branch. The worktree has no venv (`resolve_venv: no usable venv found under <worktree>/untracked/`). The same tests pass on main. The 11 new tests pass.

## Required change (N353, confidence 80%)
**Location:** `src/claude_code_hooks_daemon/handlers/nitpick/dismissive_language.py:100-110`

The exemption covers too much in two ways. I checked both with the probe at `/workspace/untracked/scratch/review-batch-g/probe_n353.py`:
- **A passing mention of a plan.** `\bper (?:the )?plan\b` can appear anywhere in the sentence, so "Per the plan I ran the tests, and the lint failure is out of scope." is dropped and never flagged. That is an ordinary deflection, and the "per plan" in it has nothing to do with scope. A passing `limb 2` does the same thing ("That failing test is out of scope (limb 2 of the fix was mine)" is dropped).
- **Clauses joined by a semicolon.** `_SENTENCE_BREAK` only splits on `.!?` and newlines. So "The threat model is documented; that failing test is out of scope." is exempt. That contradicts the code comment at lines 97-98, which says a reason elsewhere never excuses a bare "out of scope". The branch's own laundering test only uses a full stop.

**Fix:**
1. Add `;` to `_SENTENCE_BREAK`.
2. Make `per (the )?plan` require a plan id (`per (?:the )?plan\s+\d{3,5}\b`), or drop it. The case "per the plan's Non-Goals" is already covered by `non-?goals?`.
3. Add tests that the two probe sentences above still fire.

## Test gaps (non-blocking, file as plan tasks)
- `tests/unit/handlers/nitpick/test_dismissive_language.py:95-124`: no test covers the `limb N`, `owner decision` or `per ruling` alternatives. Removing any of them from the regex would keep the suite green. Add one fire-suppression test per alternative.
- `tests/unit/qa/test_run_semgrep_check.py:81-87`: the test only checks that the text exists anywhere in the script, which is weak. It would still pass if the string moved into a comment. It is acceptable as a regression pin. A stronger version would run the wrapper with a stubbed `resolve_venv` that points at a directory with no semgrep, and assert on stderr.

## Suggestions (non-blocking)
- `dismissive_language.py:116`: `("out_of_scope", ...)` repeats the literal that `_OUT_OF_SCOPE_CATEGORY` (line 99) defines. Use the constant there so a rename cannot silently turn the exemption off.
- `scripts/qa/run_semgrep_check.sh:51`: the remedy uses `\$(dirname \$(dirname ${VENV_PYTHON}))` without quotes. Pasted as printed, it breaks on a path containing spaces. Quote the inner expansions, or print the resolved directory directly.

## Checked and fine
- **N340** (`daemon_docs_guard.py:76-98`):
  - The stand-down comes after the path match. An unresolvable context falls back to client mode, which is DEBUG-logged through `log_and_continue`.
  - The exception set (`RuntimeError`, `OSError`) matches what `ProjectContext.self_install_mode` raises.
  - The `self_install_reader` seam follows the `issue_filing_gate` precedent.
  - The tests cover self-install, client install and the failure fallback. The existing fixture is pinned to the client case, so the older tests still mean what they did.
  - No dead code.
- **Comments** describe the current state, with no changelog narrative.
- **NIGGLES.md** (19 added / 4 deleted, 4 hunks): every changed line is inside the four entries.
  - Status lines for N369 (around line 2300), N367 (2347) and N353 (2658).
  - The single N340 table row (2906).
  - None of the other table rows were realigned, contrary to what the agent said about pipes. The changes should not cause churn conflicts with other branches.
- **N369** is left Open with concrete evidence and a remaining fix. The note is plausible and does not overclaim ("not run here").