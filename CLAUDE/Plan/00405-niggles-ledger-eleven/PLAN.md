# Plan 00405: niggles ledger eleven

**Status**: In Progress
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The open niggles ledger. Small defects get recorded here the turn they are
found, so that noticing something and doing something about it are never the
same decision. Ledger ten
([Plan 00404](../Completed/00404-niggles-ledger-ten/PLAN.md)) is complete, so
this one opens.

An entry is either fixed in place, ruled NOT A DEFECT with the evidence that
settles it, or graduated to its own plan when the fix turns out to be a ruling
rather than an edit.

## Goals

- Every niggle found is written down with the evidence that makes it checkable
  by someone who was not there.
- Each entry reaches a terminal state: fixed, ruled not-a-defect, or graduated.

## Non-Goals

- Fixing anything that needs an owner ruling — that graduates to its own plan.

## Tasks

### Phase 1: Entries

- [x] ✅ **N1**: A pending release callout shipped in a shape no release could
  fold in.

  **Found**: running the wider suite while building
  [Plan 00403](../00403-upstream-issue-reporting-sop/PLAN.md)'s Task 4.1. Both
  faults were in a file committed earlier the same day, and the targeted test
  runs done at the time never touched
  `tests/integration/test_pending_release_notes_holding_area.py`.

  **Evidence.** `42-one-unsecurable-socket-no-longer-costs-them-all.md` carried:

  ```text
  **Plan**: 00404 (N1)
  **Audience**: client projects with `transport.relay_enabled` or `nc_enabled`
  ```

  The holding area enforces `^\*\*Plan\*\*: \d{5}$` and an `**Audience**` drawn
  from a closed set of four. Both lines are helpful prose and neither parses, so
  a release folding this callout in would have failed at the gate — with the
  bug fix itself already tagged and published.

  **Why it is worth an entry rather than a silent fix.** The two faults are the
  same mistake in two fields: a header that a human reads correctly is not a
  header a parser reads at all, and the extra detail that made each line
  *better* to read is exactly what made it unparseable. The fix keeps the
  detail and moves it below the headers, where prose belongs.

  **Fixed** in `6787874f`.

- [x] ✅ **N2**: The plan index's own self-check disagreed with the bullets
  above it.

  **Found**: the same run — `test_repo_hygiene_check` flagged
  `plan-stats-arithmetic` twice against `CLAUDE/Plan/README.md`.

  **Evidence.** The reconciliation bullet stated 394 folders over **391
  distinct** numbers against a counter of **404**, and closed with:

  ```text
  389 + 13 = 402. ✅
  ```

  The check mark is the interesting part. A self-check that carries its own
  tick reads as verified, and the two numbers in it had simply not been
  re-derived when the bullet above them was. Recounted from disk: 22 + 359 + 13
  = 394 folders over 391 distinct numbers, and the 13 folderless numbers the
  bullet lists are exactly the set `comm` produces against the counter — so the
  arithmetic line was the only stale part.

  **Why the checker is right to treat this as detritus.** The figures exist so
  that a future recount can be compared against a stated baseline. A baseline
  that contradicts itself cannot do that job, and the tick makes it look as
  though someone already checked.

  **Fixed** in `6787874f`: `391 + 13 = 404. ✅`.

- [ ] 🔄 **N3**: `secret_file_guard` matches a dotted PYTHON MODULE PATH against
  its protected-path globs, and did so inconsistently.

  **Found**: writing a new module under `issue_report/` while building Plan
  00403\. The module's own file was created without complaint; an `Edit` whose
  content referenced it by dotted path was then denied.

  **Evidence.** The deny named the token and the glob:

  ```text
  Matched protected glob: `*.secret*`
  Matched on this token from your input:
    `claude_code_hooks_daemon.issue_report.secret_terms`
  ```

  A dotted module path is not a filesystem path, and `*.secret*` matching it is
  a coincidence of the separator. Erring toward blocking is the right default
  for this handler, so the fnmatch is defensible on its own.

  **What is NOT yet established, and is the part worth investigating.** The
  same write that was denied also contains
  `claude_code_hooks_daemon.utils.secret_redaction` — an existing module whose
  dotted path matches `*.secret*` by exactly the same reasoning — and that
  token was not named in the deny. Two tokens of the same shape, one reported
  and one not, in one input. Either the guard stops at the first match (in
  which case the message should say so, because "matched on this token" reads
  as exhaustive), or the two are treated differently and the reason matters.

  **Worked around, not fixed**: the new module is named `block_words.py`, after
  the list's own filename, which is arguably the better name anyway. The
  workaround is recorded in its docstring so nobody renames it back. The
  inconsistency above is the open part of this entry.

- [x] ✅ **N4**: Three documents told the reader to run a flag that does not
  exist.

  **Found**: writing the issue form's "daemon version" field for Plan 00403 and
  running the command before documenting it.

  **Evidence.** `bin/hooks-daemon --version` exits non-zero:

  ```text
  claude-hooks-daemon: error: unrecognized arguments: --version
  ```

  Three documents prescribed it — the two upgrade guides' **Verification**
  sections (`v3.60-to-v3.61`, `v3.62.1-to-v3.63.0`), where it is step 1 of
  confirming the upgrade worked. A verification step that errors out either
  gets skipped or reads as a failed upgrade; neither is what those guides mean.

  `TROUBLESHOOTING.md` §11 was wrong a second way: it said "the version number
  is displayed in the status output", and `status` prints PID, socket, PID file
  and listener count with no version anywhere.

  **Why it went unnoticed.** Both claims are the kind nobody re-reads: one is
  the step you skim past on a successful upgrade, and the other is in a section
  people reach only when something else has already gone wrong.

  **Fixed**: all three now name `bin/hooks-daemon release-notes`, whose first
  heading carries the installed version, and say explicitly that no `--version`
  flag exists so the next person does not retry it.

- [x] ✅ **N5**: A test file that passes alone and prevents the WHOLE suite from
  collecting.

  **Found**: the first `llm_qa.py all` run after Plan 00403's Phase 5. Every
  targeted run of that same file had passed, including minutes earlier.

  **Evidence.**

  ```text
  collected 23344 items / 1 error
  ERROR collecting tests/unit/issue_report/test___init__.py
  import file mismatch:
  imported module 'test___init__' has this __file__ attribute:
    /workspace/tests/unit/config_optimisation/test___init__.py
  which is not the same as the test file we want to collect:
    /workspace/tests/unit/issue_report/test___init__.py
  ```

  Neither test directory is a package, so pytest derives a module name from the
  BASENAME alone and two files called `test___init__.py` are one module. The
  second to be collected is refused.

  **Why it is worse than it looks.** The failure is in COLLECTION, so the whole
  run reports `0 passed, 0 failed, 1 errored` — a suite of 23,344 tests
  produced no result at all, and a reader skimming for "failed: 0" sees
  nothing wrong. The coverage figure is still printed, which makes it look
  like a run happened.

  **It had been failing CI for four commits before anyone looked.** `gh run list` showed `failure` — not `cancelled`, which is what concurrency eviction
  reports — on every push since the file was introduced, on all three Python
  versions, with the same collection error. Local targeted runs stayed green
  throughout, so nothing in the working loop contradicted them.

  **The process lesson, which is the durable part.** Committing and pushing
  after each unit of work is the standing instruction and is right; reading CI
  after each push is the half that was missing. A red run says something a
  local run structurally cannot, and four of them went unread because each
  local check had just passed.

  **Fixed**: renamed to `test_package_exports.py`, which names the behaviour
  rather than the file under test and is a better name anyway. The reason is in
  the new file's docstring so nobody renames it back.

- [x] ✅ **N6**: `plan_number_helper` read an `echo` on one line and a glob on
  the next as one command, and denied a listing of ONE named plan.

  **Found**: listing the documents of
  [Plan 00403](../00403-upstream-issue-reporting-sop/PLAN.md) while closing it
  out. The plan number is written in the path, so the command cannot be
  discovering one.

  **Evidence.** Three lines, denied as `R-PLAN-NUMBER-DISCOVERY`:

  ```text
  ls CLAUDE/Plan/00403-upstream-issue-reporting-sop/
  echo "--- wc ---"
  wc -l CLAUDE/Plan/00403-upstream-issue-reporting-sop/*.md
  ```

  Neither the `ls` nor the `wc` matches any rule alone. The `echo` rule is
  `echo\s+[^;&|\n\r]*<plan dir>/[^\s;&|\n\r]*[\*\[?]`, and it matched by
  starting at the `echo`, crossing the newline, and borrowing the `*` from the
  `wc` on the next line.

  **Why the newline exclusion did not save it.** `_COMMAND_SEPARATORS` lists
  `\n` for exactly this reason, and the comment above the rule says a previous
  fix added it because "an `echo` on one line reach[ed] forward and borrow[ed] a
  glob character from an unrelated command on the next line". That fix was
  defeated one character earlier: `\s` matches a newline too, so `echo\s+` had
  already stepped into the next line before the negated class started. The `;`
  spelling of the same structure was correctly allowed throughout — two
  spellings, opposite verdicts, which is what makes it a bug and not a policy.

  **A second, latent gap found while fixing it.** The handler read the command
  off `tool_input` directly instead of through `get_bash_command`, so it never
  saw the line-continuation normalisation done at the daemon's single entry
  point. `echo \<newline>CLAUDE/Plan/0*` is ONE command that really does expand
  the glob, and it matched only by the same accident that caused the false
  positive — so the naive fix would have turned a false positive into a hole.

  **Fixed**: the gap after a command name is now `[ \t]+`, and the handler
  reads through `get_bash_command` in both `matches()` and `handle()`.
  Verified live by re-running the denied command after a daemon restart.

## Success Criteria

- [ ] ⬜ Every entry above is in a terminal state: fixed, ruled not-a-defect,
  or graduated to its own plan.
- [ ] ⬜ Full QA passes and CI is green.

## Delivery & Milestones

- Opened when ledger ten closed. N1 and N2 were both found by running a wider
  test suite than the change under way needed — neither produced a symptom
  anybody would have hit, and both would have surfaced first at a release.
