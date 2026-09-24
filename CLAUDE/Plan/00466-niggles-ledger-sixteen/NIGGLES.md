# Niggles ledger sixteen: write-ups

Newest first. Each entry says how it was found, why it happens, and the
candidate remedies.

### N3 — `goal_injection` treats any edit of an In Progress plan as the plan starting

**Found by the coordinator**, live. The supervisor had set the goal to Plan
00461\. The coordinator then added a table row to this ledger's PLAN.md. That
edit drew `⚠️ GOAL DISPLACED: ... Plan(s) 00461 is now superseded by Plan 00466's goal`, and the handler wrote a goal-intent signal for 00466.

The handler's docstring says it writes the signal "when a plan flips to In
Progress". `handle()` never looks for a flip. It reads the PLAN.md from disk
after the write, and `_STATUS_IN_PROGRESS_RE` matches any plan whose
**Status** line reads In Progress. The once-per-plan-per-session latch is
the only limit. So the first Write or Edit in a session to any plan that is
already In Progress fires, however unrelated to its status. That includes a
ledger row, a task tick or a typo fix. The results:

- The supervisor receives a goal for a plan nobody started. For a rolling
  ledger that goal cannot complete.
- The displacement advisory tells the session that the goal it is really
  working was superseded.
- The ledger now tracks the edited plan as owed work, and the Stop hook
  challenges stops on its behalf.

**Candidate remedy:** fire only on a real transition. For `Edit`, the
`old_string` → `new_string` pair changes the **Status** line to In Progress.
For `Write`, the file's previous content (for example the pre-write copy
`write_clobber_guard` already reasons about, or git's `HEAD` version) did
not read In Progress, or the file is new. An edit that leaves an In
Progress status unchanged emits nothing and displaces nothing. RED tests:
an Edit that adds a table row to an In Progress plan emits no signal and no
advisory; an Edit flipping Not Started to In Progress still emits; a Write
creating a new In Progress plan still emits.

**Remedy shipped in commit `5676772d`.** `GoalInjectionHandler` gained
`_is_real_flip_to_in_progress`: for `Edit` it parses `old_string` with
`PlanDoc.parse` and answers directly from that fragment's own Status line
(absent → this edit never touched it → not a flip; present and not In
Progress → a flip). For `Write` there is no pre-write disk copy left by the
time PostToolUse runs, so git HEAD stands in for "before"
(`_head_plan_text`, via the already-shared `utils.git_facts.GitFactsBase`)
— deliberately not the Write/Edit `tool_response`, whose shape this
codebase has never verified for either tool (see this same folder's
`POSTTOOLUSE_FIXTURE_VERIFICATION.md`). A path absent at HEAD (new or never
committed) reads as nothing to flip FROM, matching the pre-existing
single-plan contract. The once-per-`(plan, session)` latch and the
retirement-refresh path are unchanged. `TestStatusFlipDetection` (8 tests,
3 RED against the old code) pins the contract; the module docstring, the
class docstring and `get_claude_md()` now state it explicitly.

Sibling audit: `recovery_cron_advisor`'s Edit-path completion detection
(`_edit_results_in_status_complete`) already requires the edit's own
`old_string`/`new_string` to assert Complete, so it does not share this
defect. Its Write-path (`_STATUS_COMPLETE_RE.search(content)` against the
whole new file) is state-based in the same way this bug was, but its
dedup (`_should_advise_once`) is a one-shot-ever-per-plan-folder latch, not
a per-session one, and the consequence is a single advisory message —
no ledger record, no goal-slot write, nothing another plan can be displaced
by — so it was left as documented existing behaviour rather than folded
into this fix. `plan_close_approval._is_terminal_flip` was already
transition-based (compares `PlanDoc.parse(current).status` against the
proposed status). `plan_qa_edit.py`'s "In Progress" occurrences are guidance
prose, not status-detection logic.

### N2 — `setup_worktree.sh` tells every agent to run the full suite through `run_all.sh`

**Found by the coordinator** when it set up an integration worktree.
`scripts/setup_worktree.sh` ends with an "Agent prompt template" whose last
line is `Run ./scripts/qa/run_all.sh before committing.`, and a "Run QA" hint
with the same command (lines 389 and 400). Step 7 also treats `run_all.sh` as
the QA entry point (line 343). Two things are wrong with that:

- `enforce_llm_qa` denies `run_all.sh`; `./scripts/qa/llm_qa.py all` is the
  only full-QA entry. An agent that follows the template is denied at once.
- Plan 00463 makes full QA a coordinator gate. A sub-agent runs targeted QA
  only, and the coordinator runs one full pass over the batch of merged
  branches. The template sends every sub-agent to run the full suite, which
  is the concurrent full QA that 00463 exists to stop.

**Candidate remedy:** the template names targeted QA (`llm_qa.py <tools>`
plus the touched tests) and says that full QA is the coordinator's
integration gate. The "Run QA" hint and Step 7 name `llm_qa.py`. A test
checks that the script names no denied QA entry point.

**Graduated to Plan 00463**, which owns the sub-agent QA policy.

### N1 — `resolve_venv_python`'s fallback accepts a venv interpreter that cannot run on this host

**Found by Plan 00457's agent** (#55; recorded in 00457's JOURNAL as a
finding). When the slug-exact venv is absent, `resolve_venv_python` falls
back to globbing `untracked/venv-*/bin/python`, and accepts a candidate on
its executable bit alone. #55 is about a host whose only venv was built
inside a container. That interpreter may be for another architecture or
libc, or may symlink into a path that exists only in the container. It is
executable but cannot run. The fallback would then report "resolved", so
`bin/hooks-daemon` never reaches `_run_venv_free_verb` (the `repair` and
`signal` arms from Plans 00456 and 00457). It would fail when it runs the
interpreter, not with the clear venv-missing path. No test covers it on
either side of #53 or #55.

**Candidate remedies:**

1. The fallback proves a candidate RUNS, e.g.
   `"$candidate" -c 'import sys'` with a short bound, before accepting it.
   It moves on to the next candidate, then to the venv-free path, on
   failure. Test it with a fake executable that exits non-zero, and with a
   dangling symlink.
2. At minimum, a candidate that fails at exec time produces a message
   naming the venv it tried and the `repair` command, not a raw exec error.
