# Code Review: Plan 00478 Task 2.2a, branch `worktree-478-2a-commit-gates`

Scope: `git diff main...HEAD -- src tests` (17 files, +595/-181), plus the
rule texts, `get_claude_md` and docs that describe the converted routes.

Findings: 1 CRITICAL, 1 IMPORTANT, 1 SUGGESTION.

## CRITICAL 1: a conflict marker already found is discarded when a later git call in the same scan fails (Confidence 90)

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/conflict_marker_commit_gate.py:434-469`
(`_findings`, local `findings` list) and `:369-377` (`_candidate_lines`), consumed at `:593-604` (`handle`).

**Problem:** `_findings()` builds its result in a local list and returns it only
at the end. If any git call after the first positive marker raises
`_GitTimedOut`/`_UnreadableTree`, the exception discards that list, so
`handle()` sees `findings == []` plus an unknown, and returns
`unknown_verdict_allow`. Before this branch the same exception was a deny
(fail closed), so the loss did not matter; now it turns a POSITIVE finding into
an ALLOW. The per-commit `continue` added in `handle()` fixed only the
cross-COMMIT case, not the within-commit, cross-PATH case.

**Concrete failing input (reproduced):** a repo whose index adds `a.md` and
`b.md`, each with a seven-`>` closer on an added line; command `git commit -m x`.
1. `git diff HEAD --unified=0 ... -- b.md` times out (exit `GIT_TIMED_OUT`):
   `a.md`'s marker was fully confirmed (marker found AND on an added line), yet
   the verdict is ALLOW with the `R-CONFLICT-MARKER-SCAN-TIMED-OUT` advisory.
2. The second `git grep --text -l` times out after `git grep -I` already
   returned marker lines: ALLOW.
Control (no failure): DENY. Probe:
`/workspace/untracked/scratch/478-2a-review/test_probe_marker_lost.py` (2 failed,
1 passed on the branch; run with the worktree venv and `PYTHONPATH=<wt>/src:<wt>`).

**Remediation:** make the scan degrade per path, not per source: in `_findings`,
catch `_UnreadableTree` around each per-path step (`_added_line_numbers`,
`_whole_text`) and around each `_grep` chunk, record the unknown, and keep
the findings already gathered; return `(findings, unknowns)` instead of raising.
In `handle()`, deny whenever `findings` is non-empty, regardless of unknowns.
Add the probe's two cases as regression tests in
`tests/unit/handlers/pre_tool_use/test_conflict_marker_commit_gate.py`
(`TestATimedOutScanIsNotAFinding`), plus one where commit 1 times out and
commit 2 carries a marker (only the unplaceable variant is pinned today, `:228-235` of the test diff).

## IMPORTANT 1: docs and a src comment still say the converted routes deny (Confidence 85)

**Location:**
- `docs/guides/HANDLER_REFERENCE.md:2936-2940` — "**Fails closed:** a commit it cannot check is DENIED ... and any git error."
- `src/claude_code_hooks_daemon/constants/rule_ids.py:249-250` — `CONFLICT_MARKER_SCAN_TIMED_OUT` comment: "denied, because nothing was checked".

**Problem:** the handler's `get_claude_md`, rule text, acceptance test and
release note 027 all say ALLOW + advisory; these two still say deny, so an
agent reading the reference doc or the rule-ID SSoT is told the opposite of
the behaviour. (The rest of the doc sweep is Task 2.3; these two describe the
exact routes this branch converted.)

**Remediation:** rewrite HANDLER_REFERENCE.md:2936 as "A commit it cannot check
is ALLOWED with an advisory (log line `UNKNOWN-VERDICT`), naming the reason and
the `git -C` rephrase; a marker found in another commit still denies", and the
rule_ids.py comment as "an advisory, never a deny: nothing was checked and
nothing was found". Grep HANDLER_REFERENCE.md's sensitive_content, staged_lint,
remote_docs, docs_qa and plan_qa sections for any simulation/unreadable-list
deny wording in the same pass.

## SUGGESTION 1: the sensitive_content advisory gives both remedies for either cause, and says "without a check" when part was checked (Confidence 75)

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py:154-158`
(`_UNCHECKED_REPHRASE`), used at `:1736-1741`; wording from `utils/unknown_verdict.py:41-43`.

**Problem:** a Write with an unreadable word list is told to "stage with `git add`
as its own call and commit as a separate command"; a commit whose simulation
failed is told to "restore read access to the secret word list". And the helper's
"ALLOWED this call without a check" is false for the simulation route, where
the commit message and body files WERE scanned.

**Remediation:** carry the rephrase per cause (as conflict_marker's `_Unknown`
does) and join only the rephrases of the causes present; reword the helper to
"could not fully decide ... allowed it; not checked: <cause>".

## Checked and found sound

- sensitive_content: public patterns and terms in the command text / message
  files are still judged before the unknown advisory (`handle` `:1704-1735`);
  unreadable list + public-pattern match still DENIES (pinned); unreadable-list
  advisory carries only `{path} ({strerror})` — `SecretWordListUnreadableError`
  never includes content, and the test asserts the term is absent from both the
  context and caplog. `matches()` no longer has an uncaught
  `SimulationIncompleteError` path (it is caught inside `_bash_haystacks`, the
  only raiser).
- staged_lint / remote_docs / docs_qa / plan_qa: `simulated_staging` raises only
  before `yield`, so no partial result is lost; a positive lint/provenance/QA
  finding cannot be computed inside the converted `except`.
- `git commit -a`, several commits in one command, empty lists: conflict gate
  scans every commit (`continue`), an empty unknowns list returns a plain ALLOW;
  sensitive_content runs one simulation per command, so there is no
  per-commit partial state.
- Every converted route has a test asserting ALLOW + advisory + exactly one
  `UNKNOWN-VERDICT` log line (`tests/support/unknown_verdict_asserts.py`), and the
  positive-match denies remain (`test_a_real_finding_keeps_its_own_rule`,
  message-term deny under a failed simulation, public-pattern deny with an
  unreadable list, the dry-run acceptance counter-test now staged with a real marker).

Considered and not reported (below 70): on a failed simulation, sensitive_content
could still scan the real index as a fallback; not a pure positive finding,
because the command's own `git add` may restage a path without the term.

## Verdict

REQUEST CHANGES — CRITICAL 1 breaks the plan's "a positive match still denies"
invariant and is a merge blocker.
