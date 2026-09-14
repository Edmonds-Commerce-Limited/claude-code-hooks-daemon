# Plan 00405: niggles ledger eleven

**Status**: Complete
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The open niggles ledger. Small defects get recorded here the turn they are
found, so that noticing something and doing something about it are never the
same decision. Ledger ten
([Plan 00404](../00404-niggles-ledger-ten/PLAN.md)) is complete, so
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

- [x] ✅ **N3**: `secret_file_guard` matches a dotted PYTHON MODULE PATH against
  its protected-path globs — ruled NOT A DEFECT once the apparent inconsistency
  was explained.

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

  **The open question was whether two tokens of the same shape were treated
  differently.** The same denied write also contained
  `claude_code_hooks_daemon.utils.secret_redaction`, whose dotted path matches
  `*.secret*` by identical reasoning, and that token was not named.

  **Answer: they were never the same shape.** The exemption in
  `find_protected_mention_detail` is POSITIONAL and keyed on an IMPORT
  STATEMENT — it deletes the span an `import` / `from … import` occupies, so a
  module path is exempt exactly where it is imported.
  `…utils.secret_redaction` sat in that position and still does, at
  `issue_report/block_words.py:42`. The reported token did not.

  Evidence, the verification table and the secondary finding (the scan does
  stop at the first match, so the deny message is non-exhaustive) are in
  [N3-IMPORT-EXEMPTION.md](N3-IMPORT-EXEMPTION.md). Order does not decide which
  token is named; position does.

  **Why leaving it open beat guessing.** First-match-wins was plausible AND
  true, and it was still the wrong answer to the question asked. Writing it
  down while merely plausible would have left the entry reading as settled
  while pointing at the wrong cause, and the positional import exemption —
  the thing an author actually needs to know — would never have been found.

  **Kept**: the module stays `block_words.py`, named after the list's own
  filename, which is the better name regardless. Its docstring records why, so
  nobody renames it back into the glob.

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

- [x] ✅ **N7**: a word split across two lines evaded EVERY blocking handler.

  **Found**: chasing N6's defect class outwards. `daemon_location_guard` reads
  `tool_input` directly rather than through `get_bash_command`, so it gets no
  line-continuation normalisation — and checking what that normalisation
  actually does turned up something much worse than the false positive being
  chased.

  **Evidence** in
  [N7-CONTINUATION-EVIDENCE.md](N7-CONTINUATION-EVIDENCE.md): what bash
  actually does with a backslash-newline, the five spellings that reached the
  real `DestructiveGitHandler` as harmless text, and why the existing tests
  could not see it.

  In short: bash REMOVES a backslash-newline and joins the halves into one
  word; `normalise_line_continuations` substituted a SPACE, which splits it. So
  `git pu\<newline>sh --force` arrived as `git pu sh --force` and matched
  nothing, while bash ran the force push. Every guard reading through
  `get_bash_command` was evadable this way.

  **Fixed**: the continuation is removed rather than replaced, and the converse
  is asserted too — `git\<newline>push` is `gitpush` to the shell, runs
  nothing, and must STOP being reported as a force push. Confirmed in the
  running daemon, not only in tests.

- [x] ✅ **N8**: the same newline blindness, in the other direction — four
  handlers deny an unrelated command on the NEXT line.

  **Found**: the survey that produced N7. Seven sites use a negated separator
  class that omits `\n`, or a `\s+` in front of one, against a RAW multi-line
  command. Four are defects, one is not, one is unaffected — each verified
  against the handler's own `matches()`, with the same control throughout:
  joining the two lines with `&&` reverses the verdict, so it is an
  implementation fact rather than a policy.

  **Graduated to
  [Plan 00406](../../00406-newline-is-a-command-boundary-in-handler-patterns/PLAN.md)**,
  which carries the four sites, what each wrongly denies, the two cleared
  candidates and the ordering constraint. Graduated rather than fixed here
  because it is four blocking handlers, patterns whose loosening has evasion
  consequences, and a fix whose two halves must land in order —
  `daemon_location_guard` must be routed through `get_bash_command` BEFORE its
  gap is tightened, or its false positive becomes the hole N7 just closed.
  Dedupe scout checked 23 live plans: no existing plan covered it.

- [x] ✅ **N9**: a test that passes in its file and fails on its own — and the
  daemon defect hiding underneath it.

  **Found**: running `pytest tests/integration/ -k plan` while closing Plan
  00403, to check the archival had not broken anything.

  ```text
  tests/integration/test_handler_config_blocking.py::
    TestMarkdownOrganizationHandlerIntegration::test_planning_mode_redirect_e2e
  ValidationError: 2 validation errors for Config
    Extra inputs are not permitted [input_value='CLAUDE/PlanWorkflow.md']
    Extra inputs are not permitted [input_value='CLAUDE/Plan']
  ```

  **The defect**: `get_active_secret_terms()` is documented "never raises" and
  is called from every leak-vector site on a live path — the router, the front
  controller's error log, payload capture, the transcript archiver. Its
  resolver caught `OSError` and `RuntimeError`, but pydantic's
  `ValidationError` subclasses `ValueError`, so a config holding one key the
  installed schema does not know — a legacy spelling, or a newer daemon's —
  escaped that boundary and took down the event being ROUTED. Fixed by catching
  `ValueError`, which is the fail-open contract the docstring already promised.

  **Why it hid**: the resolver caches for the process lifetime and no autouse
  fixture resets it, so whichever test routes FIRST pays the cost — in the file
  a predecessor with a valid config, alone this test, which has just written an
  invalid one. That cache, not `ProjectContext`, was the carrier, which is why
  the fixture-reset reading looked wrong. The inverse of N5: both make a green
  run mean less than it appears, and this one made `pytest -k` untrustworthy.

  The stack that settled it, and the six ruled-out hypotheses, are in
  [N9-ORDER-DEPENDENT-TEST.md](N9-ORDER-DEPENDENT-TEST.md).

## Success Criteria

- [x] ✅ Every entry above is in a terminal state. N1, N2, N4, N5, N6, N7 and N9
  fixed; N3 ruled NOT A DEFECT with the mechanism that explains it; N8
  graduated to Plan 00406.
- [x] ✅ Full QA passes and CI is green for every entry closed so far. Re-run
  after N9's source change rather than inherited from before it: full QA 30/30
  and CI `success` both at `03610440`. The earlier 30/30 at `9c332e83` was
  deliberately NOT accepted — it predated the `secret_redaction` fix, so it
  could not have covered it.
- [x] ✅ Every release-bound consequence is in the holding area before this
  plan closes. Three callouts in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`:
  `44-…` (N6, a plan glob on the next line), `45-…` (N7, the security fix for a
  word split across two lines) and `46-…` (N9, an unreadable config no longer
  taking down the event). N1, N2, N4 and N5 are test-only or internal and carry
  nothing a user upgrading would need told.

## Delivery & Milestones

- Opened when ledger ten closed. N1 and N2 were both found by running a wider
  test suite than the change under way needed — neither produced a symptom
  anybody would have hit, and both would have surfaced first at a release.
- **N6 → N7 → N8 is the chain worth remembering.** N6 was one handler denying
  something harmless. Asking whether its SHAPE recurred, rather than just
  fixing it, found four more of the same (N8) and then one of the opposite
  kind: N7, where a word split across two lines evaded every blocking guard.
  The false positive was the visible symptom and the hole was the expensive
  defect, and nothing about N6 suggested the second existed — only surveying
  for the shape did.
- **Two habits did the work, and neither is cleverness**: running the real
  thing rather than reasoning about it (bash settled what a line continuation
  does, against a docstring and an implementation that disagreed), and pairing
  every claim with a control (the `&&` spelling of each N8 command, which turns
  "this block feels wrong" into a fact no judgement call absorbs).
