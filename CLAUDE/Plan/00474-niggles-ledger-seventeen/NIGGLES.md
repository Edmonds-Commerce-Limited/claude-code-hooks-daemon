# Niggles ledger seventeen: write-ups

Newest first. Each entry says how it was found, why it happens, and the
candidate remedies. Numbering continues from
[ledger sixteen](../Completed/00466-niggles-ledger-sixteen/NIGGLES.md).

### 65 entries still open in the archived ledger 00466

Ledger 00466 was archived as Superseded by this one. Its PLAN.md index holds 157
entry rows, 65 of them not in a terminal state. They stay open, are not copied
here, and are tracked from this ledger by reference to that
[index](../Completed/00466-niggles-ledger-sixteen/PLAN.md). Its branches are all
resolved: landed (n101, n211, lifecycle, d-00376) or dropped, their branch-only
entries carried in the sections below. Nothing is dismissed or deferred.

### 55 entries carried from the six dropped re-fix branches

Ledger 00466's cleanup judged six branches too tangled to merge
(`worktree-upgrade-scripts`, `worktree-d-00421`, `worktree-plan-464-commit-gate-repo`,
`worktree-n466-small-a`, `worktree-p422-close` and the N38 branch
`agent-aa0e5105724aa123b-b9ce2f39`). Their defects stay open, to be fixed fresh
on `main` in small batches. 55 entries existed only on those branches. They are
kept, with verbatim write-ups where the branch had one, in
[CARRIED-REFIX-BRANCHES.md](CARRIED-REFIX-BRANCHES.md). Some numbers come from
other ledgers' numbering (00422 for `p422-close`, 00421's plan for `d-00421`).

**Status**: ⬜ Open (all 55).

### N285 — a sub-agent reports `PYTHONPATH=… pytest` denied as an upgrade-approval bypass

**Found**: the N283 agent reported that setting `PYTHONPATH` in a test command
was denied as R-UPGRADE-APPROVAL-ENV-BYPASS. It then ran its tests through a
scratch runner that edits `sys.path` instead. Its report does not keep the
exact command.

**Not reproduced**: on the main thread,
`PYTHONPATH=<worktree>/src <venv>/bin/python -c 'import …'` was allowed (the
coordinator, `f966b402b`). So the deny is either sub-agent-scoped, or set off by
something else in the agent's command (pytest, a path naming "upgrade").

**Why it matters**: a worktree's tests import `/workspace/src` through the
editable venv. So `PYTHONPATH` is the plain way for an agent to test its own
branch, and denying it pushes agents to write runners around the guard.

**Corroborated**: the Plan 00475 slate agent, a second sub-agent, also reported
`PYTHONPATH` blocked by the upgrade-approval guard. It used
`pytest -o pythonpath="src ."` instead.

**Trigger narrowed** by the N284 agent, which kept the deny text: a single
command with a literal interpreter path and `PYTHONPATH=$PWD/src` was allowed.
Two other shapes were denied as R-UPGRADE-APPROVAL-ENV-BYPASS:

- `PY=…; PYTHONPATH=$PWD/src $PY/python -m pytest …`;
- a `;` chain running `PYTHONPATH=$PWD/src $P scripts/qa/audit_error_hiding.py`,
  where `$P` held the interpreter.

So the rule fires on `PYTHONPATH=` before an interpreter named by a variable,
whatever that interpreter then runs. It is not specific to sub-agents. None of
those commands was an upgrade.

**Cause**: `_segment_runs_upgrade` sent any segment whose head word began with
`$` to `_script_run_is_upgrade`, which cannot read a `$`-path and so answers
"cannot tell". Once `PYTHONPATH` (matched by `PYTHON*`) steered the command,
"cannot tell" counted as the upgrade, whatever the arguments named.

**Fix**: a variable program is judged by its arguments
(`_variable_program_is_upgrade`). A literal `-m <module>` outside the daemon's
own package is allowed; a literal script path is read and judged by content
like any other script. `-c`, stdin, no operand, a computed module or script, a
script that cannot be found, and `-m claude_code_hooks_daemon...` keep the
deny. Upgrade entry points by name, `--uv` and the handoff variable are caught
before this and unchanged.

**Not changed**: `PYTHONPATH=x eval "$X"` was already allowed (eval is only
suspect beside a command that runs the upgrade); a literal interpreter running
`-m claude_code_hooks_daemon...` is also still allowed.

**Status**: ✅ Fixed on worktree-n285-env-bypass-scope.

### N284 — the pipe blocker reads `\|` inside a double-quoted grep pattern as a pipe

**Found**: the coordinator ran a `grep -rn` whose double-quoted pattern held the
alternation `\|`, followed by an alternative beginning `HEAD:`. A real pipe to
`cut` followed. The command was denied as R-PIPE-TO-HEAD. The blocker named
the quoted pattern text as the pipe's producer, and the alternative's leading
word `HEAD` as `head`.

**Why**: inside double quotes, `\|` is two literal characters, not a pipe. The
segmenter splits on it, and the head match is case-insensitive or ignores the
`:` that follows.

**Workaround**: spell alternations as `-e A -e B`.

**Outcome**: the segmenter was not at fault. `_pipe_pattern` is a plain regex
over the raw command: it matched the bar of `\|` and then `HEAD` because the
pattern was compiled `re.IGNORECASE`. Producer extraction then correctly
returned the text before that bar, which is how the quoted pattern came to be
named as the producer. Fixed in `pipe_blocker.py`: the pattern is
case-sensitive (a Linux command word is), and `_pipe_matches` drops a bar
preceded by an odd run of backslashes, which is a literal character both in
double quotes and unquoted. An even run (`\\|`) is still a real pipe. Tests:
`test_pipe_blocker_literal_pipe_text.py`, incl. the field command and the
must-stay-blocked list (`$( )` and backticks in double quotes, `pytest|head`).
Two assertions of case-insensitive matching in
`test_pipe_blocker_comprehensive.py` were inverted. A bar inside plain quotes
with no backslash (`"a | head"`) is still judged, as before.

**Status**: ✅ Fixed on worktree-n284-pipe-quoted-alt.

### N283 — `secret_file_guard` misses a protected name in git's `rev:path` syntax at the repository root

**Found**: the N253 branch's analysis
([260929-n253-opus-5-5.md](subagent-reports/260929-n253-opus-5-5.md),
candidate 1) flagged it as urgent, but it was never ledgered. The coordinator
re-confirmed it live on `main` (`dafd800ff`, daemon restarted):
`git show HEAD:.vault-pass-probe-nonexistent` was allowed and reached git.
The name does not exist, so nothing printed.

**Why**: the token keeps its `HEAD:` prefix, so its basename never matches an
anchored pattern such as `.vault-pass*`. `HEAD:config/.vault-pass` is denied
because the basename after the last `/` is clean. The same miss applies to
`git cat-file -p HEAD:<name>`, and probably to `:<name>` (index) and
`<rev>:<name>` in other git commands.

**Why it matters**: it prints a committed protected file, which is the
disclosure this guard exists to stop.

**Fix**: `_normalised_token_forms` in `utils/secret_file_matching.py` now also
yields the path after each `:` of a token (the first eight colons and the last,
to bound a colon-stuffed token), each then given the existing home/`./`
stripping. The whole token is still judged, so nothing denied before is
allowed. This covers `HEAD:<p>`, `<sha>:<p>`, `HEAD~2:<p>`, `HEAD^{tree}:<p>`,
`:<p>`, `:0:<p>`, `<rev>:./<p>` and the same token shape in `scp host:<p>` and
`rsync host:<p>`. Read/Grep take filesystem paths and are untouched. Release
note 203.

**Status**: ✅ Fixed on worktree-n283-rev-path

### N282 — the N264 cross-worktree guard judges an in-process teammate by the coordinator's working directory

**Found**: the n253 teammate, working in its assigned worktree
`worktree-n253-open-option-lists`, had its Write/Edit denied by
R-SUBAGENT-CROSS-WORKTREE-WRITE partway through the task. It reported that the
harness had switched its primary working directory to the n254 worktree. That
switch matches the moment the coordinator ran a Bash `cd` into the n254 worktree
to review it, and the coordinator's own environment notice changed at the same
time. The teammate's earlier writes into n253 had passed.

**Why**: `subagent_worktree_write_guard._crossing` takes "own checkout" from
the payload's `cwd`. An in-process teammate seems to share the session's working
directory with the coordinator. If so, the guard has two failure modes:

- a false deny whenever the coordinator stands in another worktree;
- no protection at all while the coordinator stands in the main tree, because a
  main-tree cwd is not judged.

The second is the N264 incident's own shape.

**Not yet established**: whether the payload `cwd` for an in-process teammate
is always the shared one, or only after a coordinator `cd`. Reproduce with a
teammate that writes into its own worktree and then into another while the
coordinator stays in `/workspace`, and log the payload `cwd`.

**Remedies to weigh**: key "own checkout" on something the teammate owns (its
spawn worktree, recorded at dispatch) rather than the shared cwd. Meanwhile, the
coordinator reviews worktrees with `git -C`/absolute paths and never `cd`s into
them.

**Phase A findings** (branch `worktree-n282-teammate-own-checkout`,
[report](subagent-reports/261002-n282-own-checkout-sonnet.md)):

- Observed: the PreToolUse contract and the daemon's scope module list the
  fields a teammate's payload can carry: `session_id`, `transcript_path`, `cwd`,
  `agent_id` (30 characters for a teammate), `agent_type`. None names an assigned
  worktree. `transcript_path` is the session's, `cwd` is the session's working
  directory (Plan 00464 saw `/workspace` on a teammate working in a worktree).
- Observed: the harness reports that an Agent thread's own Bash `cd` is reset
  between calls, so a teammate has no persistent cwd of its own to report.
- Observed: `WorktreeCreate` carries `name`, `cwd`, `session_id` and no
  `agent_id`, and a coordinator-assigned worktree (the usual case here) fires no
  such event at all, so no spawn-time record exists to read.
- NOT observed: a live teammate PreToolUse payload. Payload capture is off and
  the shared daemon was not to be reconfigured or restarted; the worktree's own
  `hooks-daemon logs` reported no daemon. So whether `cwd` is always the shared
  one, or follows a coordinator `cd`, stays inferred, as the question above says.
- Decision: no reliable per-agent own-worktree signal exists in the payload, so
  the guard is unchanged. Three characterisation tests pin the current behaviour.

**Design options** (none implemented):

1. Trust on first use: bind `agent_id` to the checkout of its first write (or
   Bash `cd`) and judge later writes against it. Needs state, and a teammate
   whose first write is the wrong one is bound wrong. Reverses N264's "never
   reads agent_id" for a stated reason: cwd cannot carry the role-local fact.
2. Dispatch declaration: the coordinator names each teammate's worktree in the
   Agent prompt and `dispatch_declaration` (already on PreToolUse Agent) records
   `agent_id -> worktree` when it can be matched. The harness gives no agent_id
   at dispatch, so the match is by prompt text; fragile.
3. Fail-open on disagreement: allow when cwd is a linked worktree that the
   teammate has not been shown to own. Removes the false deny, widens the gap.
4. Process: the coordinator never `cd`s into worktrees (`git -C`/absolute paths);
   removes the false deny at no code cost, leaves the fail-open direction.
5. Ask upstream for a per-agent `cwd` or worktree field in the payload; the only
   option that fixes both directions reliably.

**Decision** (the coordinator's ruling, reversible by the owner): option 1, plus
the process rule of option 4 that the coordinator never `cd`s into a worktree
(`git -C` and absolute paths instead). Each sub-agent `agent_id` is bound to the
linked worktree of its first Write/Edit/NotebookEdit; later writes are judged
against that binding.

**Outcome**: `subagent_worktree_write_guard` holds an in-memory,
lock-guarded, least-recently-used map (capped at 256) of `agent_id` to linked
worktree. Bound to W, a write into W is allowed whatever the payload cwd says
(the false deny is gone) and a write into any other checkout of the repository is
denied with R-SUBAGENT-CROSS-WORKTREE-WRITE even from a main-tree cwd (the
fail-open is gone); the deny names the bound worktree and the target and says the
binding came from the first write. A first write the cwd rule denies, or one into
the main tree, binds nothing. No `agent_id`, or no binding, keeps the cwd rule.
`agent_id` is only the map key, never the role test. A daemon restart forgets the
bindings. Residual: trust on first use, so a wrong first write binds wrong, and
the remaining unbound window denies a teammate whose first write is made while the
shared cwd is a sibling worktree. Option 5 (a per-agent payload field) would still
be the reliable fix.

**Status**: ✅ Fixed on worktree-n282-bind-agent-checkout

### N281 — a hostile-input sweep measured host speed: the 100,000-character scan timed out (and denied) on slow runners

The "Found" and "Why it matters" paragraphs below were written before the
cause was known, and read the message's sizes the wrong way round; the Cause
paragraph corrects them.

**Found**: main CI run 36783643933 (head `9df587f09`), Python 3.11 and 3.12;
3.13 passed. `test_safety_handlers_hostile_input_performance.py` reported
`SecretFileGuardHandler takes another path at 100000 than at 12500 (matched, decision, logged a warning): (True, 'deny', False) vs (False, None, False) on shape='wildcards'`. The same file passed locally on `a6000e2d4`, which carries
the N265 speed-up.

**Why it matters**: a guard whose `matches()` stops matching on the larger
input lets that input through. If the cause is time (the slower runners ran out
of budget at 100,000 characters) it is a fail-open under load, the direction a
safety handler must never take.

**Cause (established, not a fail-open)**: the failing side is the LARGE one
(the message prints `large vs small`): 100,000 characters returned
`(True, 'deny')`, 12,500 returned `(False, None)`. The guard's whole-scan
deadline (`sfm.SCAN_DEADLINE_SECONDS`, 5s) raises `TimeoutError`, which
`_matched_pattern_and_route` turns into a deny ("could not be verified"), so a
scan that runs out of time is denied, never allowed. The 100,000-character
wildcard command scans in about 1.7s on a development host (12,500 in 0.2s,
linear), so a runner about three times slower crosses the 5s deadline at the
large size only. With the clock forced past the deadline, both sizes return the
same could-not-finish deny. The sweep's same-path check therefore measured host
speed.

**Fix**: the sweep injects a deadline no host crosses
(`_host_independent_scan_deadline`, the same device
`test_secret_file_guard.py` already uses for N101/N265), and
`TestSweepVerdictIsHostIndependent` pins that an expired deadline denies a
wildcard command at both sizes. Test-only; no behaviour change.

**Status**: ✅ Fixed (test determinism; the guard was already fail-closed).

### N280 — something wrote an older `CLAUDE.md` guidance section into the main checkout during a test run

**Found**: by the coordinator. A pytest run of 1743 targeted tests had three
teardown errors from the conftest guard ("This test rewrote tracked generated
doc(s): CLAUDE.md"), in three unrelated files, over about four minutes. The pid
file of this checkout's daemon did not change during the run, and only that one
daemon was running afterwards. The guard's preserved copy
(`untracked/rejected-writes/CLAUDE.md.rejected`) differs from `HEAD` in one
line: the `R-UPGRADE-APPROVAL-ENV-BYPASS` row carries its text from before the
N271 merge, which added "or passes `--uv <path>`". So the writer ran code older
than `main`, three separate times.

**Leads**, both unconfirmed:

1. More likely: a test or QA run inside a sub-agent's worktree, on that
   worktree's older code, resolves "the real repository" through git's common
   directory (`/workspace/.git`, shared by every worktree) rather than the
   worktree's own top level, and so injects its guidance into the MAIN
   checkout. Sub-agents were running `llm_qa.py changed` in worktrees at the
   time, the host-wide QA lock was held by a process in one of them, and no
   daemon ran in any worktree (sub-agents' hooks use the coordinator's daemon).
   The conftest guard only protects the checkout the test run itself belongs to.
2. Less likely: a daemon from a worktree removed shortly before, whose project
   root resolves to the enclosing repository once its directory is gone.

**Reproduction to try**: in a worktree at an older commit, run the targeted
tests while watching the main checkout's `CLAUDE.md` mtime (for example with
`inotifywait`), and note which test's window it changes in.

**Status**: ⬜ Open.

### N279 — `changed_tests` once selected 50 test files, ran 0 tests and did not fail

**Found**: by the Plan 00477 provision agent. One `llm_qa.py changed --base main --allow-unmapped` run reported `changed_tests` as 0 passed, 0 failed, 0 skipped
over 50 selected files, and the check did not fail. That run had waited more
than 300 s for the host-wide QA lock. The same selection collected 1343 tests
with `--collect-only`. A run with no wait ran 1298, and a later run that waited
1143 s ran 1343. The zero run's `changed_tests.json` was overwritten before
anyone read it.

**Why it matters**: a check that runs nothing and passes reads exactly like a
green run. Plan 00475's tiers lean on this check.

**Candidate remedy**: `changed_tests` fails when it selected files but executed
zero tests, naming the pytest exit code and the tail of its output. Then find the
cause: the lock wait preceding the pytest step is the lead. The full-QA gate
plugin refusing the run, or a timeout budget spent while waiting, would both fit.

**Findings**: `build_report` already failed a run that selected files and
counted zero tests (`total > 0` is part of `tests_green`), so the verdict was
not the gap; the gap was the silence. The red line read `0 passed, 0 failed, 0 skipped` with no reason, which is what the zero run looked like. The report
now carries `summary.error` naming the exit code, the files selected and the
last 15 lines of pytest's output, and `llm_qa.py` prints it.
Cause ruled out by test and reading: the pytest timeout (1800 s) starts in
`run_pytest`, after the lock is taken, so the wait is not spent from it; a
gate refusal exits 1 with no summary and now fails naming `REFUSED`, and 50
files is 4% of the suite against the 25% threshold; the lock is taken before
any tool starts, so the wait cannot change what the child runs. Not found:
why that one run executed zero tests. Its `changed_tests.json` is gone, so the
pytest output that would say is gone too. If it recurs the report now holds it.

**Status**: 🟡 Detection fixed, cause not found. The failing run now names why;
the original zero-test run is not reproduced.

### N278 — a branch merged with its targeted QA never run, and main took three static-check failures

**Found**: the hostname-cron branch (Plan 00470 Tasks 6.1, 6.2) was merged
while its `llm_qa.py changed` run was still queued behind the host-wide QA lock.
The coordinator's post-merge check ran only the touched tests with pytest, so
no static check ran. Main took three failures: `error_hiding` (a `None` return
from an `except` in two peer readers), `input_contract` (the daemon-stamped
`hooks_daemon_hostname`) and `format` (from the CI-timeouts merge). The N276
agent's run found them. Fixed on main in feef4bce1.

**Why**: with three agents queueing on one lock, a targeted run can wait longer
than the agent's own time budget. Nothing stops a merge that has no recorded
pass.

**Candidate remedy**: the merge step requires a recorded `llm_qa.py changed`
pass for the branch head, or runs one itself before merging. Candidates for
enforcement: a recorded pass per head, read by a merge-time check (Plan 00475
Phase 4 territory). Until then, the coordinator runs the cheap static checks
(`format lint type_check error_hiding input_contract`) itself before any merge
whose targeted run is missing.

**Status**: ⬜ Open (main repaired; the process gap stands).

### N277 — `_resolve_python_cmd` in `init.sh` reports success after a failed resolve

**Found**: by the Plan 00477 provision agent, reading `init.sh`. The function
ends with:

```bash
if PYTHON_CMD="$(resolve_venv_python "$HOOKS_DAEMON_ROOT_DIR")"; then
    return 0
fi
local rv=$?
PYTHON_CMD=""
return "$rv"
```

An `if` with no `else` whose condition fails leaves `$?` at 0, so `rv` is always
0\. A failed resolve returns success with `PYTHON_CMD` empty, and any caller that
trusts the status goes on to run an empty interpreter. `provision.sh` works
around it by judging `PYTHON_CMD` instead of the status.

**Candidate remedy**: capture the status in an `else` branch
(`else local rv=$?`), or from the assignment on its own line. Add a bash test
that a failing resolver makes the function return non-zero. Then audit its
callers for any that already depend on the wrong status.

**Status**: ✅ Fixed in 9f5426f84 (branch `worktree-p477-drift-detect`). The status is
captured from the assignment itself; `tests/integration/test_init_sh_resolve_python_cmd_status.py`
reproduces it with the canonical library present and its resolver failing. The
audit of callers found none depending on the wrong status: `validate_venv` and
the CLI-helper runner both already treat a non-zero status as a failure, and
`provision.sh` judges the interpreter as well, which stays correct.

### N276 — the SessionStart chain overruns its 20 s budget, so declared crons are never asked for

**Found**: this session's own SessionStart reply was only "Chain skipped:
exceeded its 20.00s dispatch budget". Four probes that piped a real SessionStart
payload through the deployed `.claude/hooks/session-start` got the same reply,
with any combination of `HOOKS_DAEMON_HOSTNAME` and `CCY_HOST_HOSTNAME`. The
host's load average was about 33, with three agents' QA running. A skipped chain
runs none of its handlers, `persistent_cron_assertor` included, so a session
started under load is never told to create its declared crons. The Stop
enforcer still names them at the first stop, which is the only reason the jobs
are not lost.

**Why it matters now**: the owner's dogfood of hostname-matched crons restarts a
session as `cchd-sdlc-runner` and expects the assertor to ask for `issue-sdlc` at
start.

**Candidate remedy**: measure each SessionStart handler's time under load, and
find which one spends the budget. Then either make it cheaper, or dispatch the
assertor (a pure config read) ahead of the slow handlers so a budget overrun
cannot starve it.

**Status**: ✅ Fixed in aa557cc12. Measured: no single handler overran. The
serial chain took 33 to 44 s under load, and the repo-walking sweeps (gitignore,
secret hygiene, docs QA, git upstream, plan QA, reference repos) spent about
30 s of it, while the assertor needs 0.5 s but sat behind them. A `slow-sweep`
tag now orders those six after every untagged handler. A chain with no
SAFETY+BLOCKING handler that overruns keeps the output of the handlers that
finished, marked "Chain cut short", and that output shares no objects with the
abandoned thread. SAFETY+BLOCKING chains still fail closed, and the budget is
unchanged. Proven live at load 22: a real SessionStart names `issue-sdlc`
exactly when the session presents as `cchd-sdlc-runner`. The sweeps still cost
about 30 s under load, so their own advisories can still be cut short.

### N275 — `secret_file_guard` judges an Edit of a YAML file as an unreadable shell command

**Found**: an `Edit` of `.github/workflows/qa.yml` whose `old_string` held the
line `name: QA (Python${{ matrix.python-version }})` was denied
R-SECRET-COMMAND-UNREADABLE ("quoting inside `${...}` whose extent is
ambiguous"). The same edit anchored on neighbouring lines without `${{` was
allowed. GitHub Actions expressions are not shell, and a workflow file is not a
command.

**Candidate remedy**: find which route reads Edit content through the Bash
command reader, and limit it to content that is a shell script (by extension or
shebang), or treat an unreadable span in non-shell content as text.

**Status**: ✅ Fixed on `worktree-n275-yaml-edit`. The route is the ADDED text
only: `_script_content_mention` scans `new_string`/`content` (a workflow is
scanned whole as shell, `context="bash"`); `old_string` is never read. The
wider defect: even `context="content"` runs the shell brace reader, so any
non-shell file (`.py`, `.ts`, Makefile) holding `${{` was denied too. Fix: a
workflow's `${{ ... }}` expressions are neutralised before the scan (so `run:`
steps stay shell-scanned), and only a file not scanned as shell at all
(`.py`, `.ts`, ...) has an unreadable scan repeated literally instead of
denied. Everything scanned as shell (`.sh`/`.bash`, shebang, Makefile, CI
YAML) keeps failing closed. Release note 196.

### N274 — `AskUserQuestion` is denied as "unattended" while the owner is at the keyboard

**Found**: the owner typed "human here - take me through decisions/blockers one
at a time". The coordinator's next call, an `AskUserQuestion` offering four
options, was denied R-ASK-USER-QUESTION-UNJUSTIFIED: "This project is running
UNATTENDED: no human is reading this session". The question was asked in plain
text instead. Whatever signal the handler uses to decide the session is
unattended did not see a real prompt that had just arrived.

**Candidate remedy**: find the handler's unattended signal, and treat a genuine
user prompt within the current turn (or the last few minutes) as proof a human
is present.

**Status**: ✅ Fixed (branch `worktree-n274-attended-signal`). The unattended
mode is a declared option, and the handler never looked at the session. It now
reads the transcript tail and, when a genuine human prompt arrived in this
session within `human_presence_minutes` (default 30), judges the question by the
attended rules (prefix required) instead of denying it. Ticks, supervisor lines, teammate messages, task notifications and other sessions'
prompts do not count. The deny says what it judged. Release note 192.

### N273 — a stalled CI job holds main's queue for up to six hours

**Found**: main run 36729884166 (`ae37690a3`). Its Shell job, normally a
minute or two, stayed `in_progress` from 14:50 to past 17:40 UTC, with no log
available (the log API answers BlobNotFound). Because the workflow's
concurrency group keeps one run queued, the run carrying the main-red fix waited
behind it the whole time, and was only released when the coordinator cancelled
the stale run. No job in `.github/workflows/qa.yml` sets `timeout-minutes`, so
GitHub's six-hour default applies.

**Candidate remedy**: set `timeout-minutes` on every job, sized a margin above
its measured duration (the full-tier pytest jobs run about an hour; Shell, Daemon
load and Classify take minutes).

**Status**: ✅ Fixed (merge of `worktree-n273-ci-timeouts`). Timeouts: Classify
10, the docs/code tier 120, each full-tier Python 150, Shell and Daemon load 15
minutes. `tests/integration/test_ci_job_timeouts.py` fails a job with no timeout
or one over 180 minutes.

### N272 — one `llm_qa changed` run reported `project_handlers` as 0 tests collected

**Found**: the targeted run over the p475-t23 merge (`8f2cd8bc8`) failed only
`project_handlers`, with "0 tests collected - the suite did NOT run" and an empty
`tests` list. Run on its own straight afterwards, the same check passed 232. The
run before the merge had also passed 232. A sub-agent was running pytest in
another worktree at the same time, so contention is the leading suspect, but it
is not established.

**Candidate remedy**: when it recurs, capture the pytest stderr that
`check_project_handler_tests.py` discards. A collection of zero is already
reported as a failure, correctly, so nothing is hidden meanwhile.

**Status**: ✅ Fixed (merge of `worktree-n272-ph-reason`). It recurred on the #63
branch's run. The likely cause is nested timeouts: `test-project-handlers` killed
its pytest child at 120 s, and the gate allowed 300 s, so a killed run printed only
a timeout line and parsed as zero tests. The suite measured 70 s of pytest time
(82 s wall) at host load 27, against about 5 s idle. The child now gets 300 s and
the gate 360 s, and a run that collected nothing reports the last 40 lines of the
runner output as its reason. The two original runs cannot be confirmed, because
their output was discarded.

### N271 — an upgrade fails "uv not found" when the only uv is outside the trusted PATH

**Found**: main CI was red from 2026-09-17, with seven upgrade tests failing on
all three Pythons. Layer 2 (`scripts/upgrade_version.sh`) resets PATH to trusted
locations, and `_venv_uv` falls back only to `~/.local/bin/uv`. CI installed uv
with `pip install uv`, into the setup-python toolchain bin, which neither reads.

**Handled**: a sub-agent's first fix made Layer 2 run the uv the caller's PATH
named. The coordinator reverted that, because what builds the venv decides what
code the daemon runs, and the PATH reset exists so the caller cannot pick it. CI
now installs uv with `--user` into `~/.local/bin`, and a test pins that a uv only
on the caller's PATH is never run (merge of `worktree-main-red-upgrade`).

**Open for the owner**: a client whose only uv is somewhere else, such as a
Homebrew prefix or `~/.cargo/bin`, hits the same "uv not found" on upgrade. The
options are a documented requirement (uv in `~/.local/bin` or a trusted system
directory), a message naming the fix, or more trusted locations. Widening what
Layer 2 trusts is a security decision, so it is not made here.

**Owner ruling (2026-09-30)**:

- Trust more fixed locations, including Homebrew's prefixes and pipx's bin
  directory. pipx's default is `~/.local/bin`, already trusted; honour
  `$PIPX_BIN_DIR` when it is set.
- Allow the uv path to be passed explicitly when needed, as a per-run upgrade
  argument (`--uv <path>`).
- Never a repo-level config key, because a repository cannot carry
  environment-specific configuration.
- The owner questioned the threat model. The PATH reset guards against an agent
  steering an upgrade, not the human, who already controls their own PATH.

**Handled (ruling implemented)**: Layer 2 searches `$PIPX_BIN_DIR` and the
Homebrew prefixes after the trusted `PATH` and `~/.local/bin`, each needing root
or own-user ownership and no group/world write. `upgrade.sh --uv <path>` names a
uv for one run, passed to Layer 2 as an argument and validated in both. The
not-found error names both fixes, and `upgrade_approval_guard` denies an agent
passing `--uv` or setting `PIPX_BIN_DIR` on an upgrade. Release note 191;
described in `CLAUDE/LLM-UPDATE.md`.

**Status**: ✅ Fixed (branch `worktree-n271-uv-locations`, merge pending).

### N270 — the workspace venv has drifted from `uv.lock`

**Found**: `test_subagent_full_qa_blocker.py::TestThePytestOptionGrammar::test_every_value_option_of_the_running_pytest_is_known`
fails locally (`['--max-warnings', '--report-chars']` unknown) but passes in CI.
The workspace venv runs pytest 9.1.1 while `uv.lock` pins 9.0.3, so local runs
test a different toolchain from CI.

**Candidate remedy**: re-sync the venv from the lock (`uv sync --frozen`) when no
agent is running tests on it, and find what installed the newer pytest.

**Resolution**: the drifted venv was the legacy `.venv` at the repository root,
which no resolver uses; the fingerprint-keyed `untracked/venv-*` the daemon and
`llm_qa.py` run on already matched the lock. The drift was wider than pytest: a
`UV_PROJECT_ENVIRONMENT=.venv uv sync --frozen --all-extras` uninstalled 58
packages and installed 54. The cited test then passed (7 of 7). What installed
the off-lock versions was not found; `.venv` predates this ledger. A hand-run
check that uses `.venv` tests a different toolchain from CI whenever it drifts,
so prefer the resolved venv (`scripts/lib/resolve_venv.sh python .`).

**Status**: ✅ Fixed (environment re-synced; no code change).

### N269 — `secret_file_guard` expands a single-quoted grep regex as a filename glob

**Found**: after the N101 merge, a Bash command whose `grep -E` pattern was a
single-quoted regex containing `[a-z_/]+\.py` was denied as R-SECRET-READ with
"a glob or scan in it did not finish within its entry cap or deadline
(TooManyToEnumerateError)". A single-quoted word is never glob-expanded by bash,
so there was nothing to enumerate. Worked around by moving the search into a
Python script file.

**Candidate remedy**: reproduce with `bin/hooks-daemon probe`, then stop the
enumeration from treating a quoted argument (at least a `grep`/`rg`/`awk`
pattern operand) as a glob. Related: N256 (quoted heredoc bodies) and N265 (scan
cost).

**Status**: ✅ Fixed in two steps. Step 1 (b39b8f8fc): glob expansion is based on
the project root and the payload's cwd, never the daemon's own. Step 2
(a7ebcae9b): a quoted word that a pure text consumer (`grep`, `rg`, `awk`,
`echo`, `printf`, a `gh` body or title) receives is judged by the literal check
only, never by the glob heuristics. The owner's checklist review found all 12
file-reading shapes (`grep -f`, `rg --pre`, `awk -f`, wrappers, here-strings,
heredoc bodies and others) still denied, on the branch and on the base. N256 is
related but separate, and stays open until it is checked on its own.

### N268 — a symlinked-project daemon test's teardown refuses a daemon that is exiting

**Found**: main's full-tier CI run 36706198921 (`bacfb6138`) failed on Python 3.13
only, with 35,888 passed and one teardown error in
`tests/integration/test_a_daemon_of_a_symlinked_project_is_stoppable.py`
(`_stop_every_daemon`, line 97): `stop_verified_daemon` raised
`RefusedSignalTarget: pid 15809 is not a daemon server: []`. The empty command
line is a process that is already exiting, so the teardown races the daemon's own
shutdown. The test arrived with the lifecycle merge (ledger 00466 N67-N70).

**Candidate remedy**: the teardown treats a process that is gone or already
exiting (empty command line, zombie) as stopped, while still refusing a live
process that is not a daemon.

**Status**: ✅ Fixed in 1a61af7d0. A shared `tests/daemon_teardown.py` treats a
process that is gone, a zombie, or showing an empty command line as stopped, and
the daemon tests' teardowns use it.

### N267 — dropping a stale branch always needs a human, even when nothing can be lost

**Found**: the ledger 00466 cleanup dropped 18 unmerged branches. Their ledger
entries were carried to `main`, WIP was committed and pushed, and every remote
copy was deleted by the agent. But the local `git branch -D` is denied for every
branch by `destructive_git` (R-GIT-BRANCH-FORCE-DELETE, "ask the user for -D"), so
the owner had to run it by hand. **Owner ruling**: clearing up worktree branches
must not require human intervention; this is a defect.

**Why the rule exists**: `-D` deletes a branch without checking it is merged, so an
unpushed branch's commits become reachable only from the reflog.

**Remedy**: allow `git branch -D <name>` when every named branch's tip is reachable
from a remote-tracking ref (its commits survive on the remote), and keep denying it
otherwise, naming the branch that is not pushed and saying to push it first.

**Status**: ✅ Fixed in 74dbdc970. `destructive_git` allows `git branch -D` when a
remote-tracking ref holds every named tip, and still denies it otherwise, naming
the unpushed branch. The merged `worktree-n267` branch itself was then removed with
no human step.

### N266 — `flaggable_content_channel_guard` denies greps that never touch a flagged path

**Found**: twice in one session, a content search was denied as
R-FLAGGABLE-CONTENT-CHANNEL with the matched glob `tests/fixtures/cyber-flag/**`,
though neither command named or reached that directory:

- a `grep -n` over `.github/workflows/qa.yml` alone;
- a `grep -rhoE` over `src/claude_code_hooks_daemon/utils/*.py` plus a grep of a
  scratch file.

**Why it matters**: the deny message says to delegate the whole file to the
quarantine agent, which is the wrong remedy for an ordinary source file, and the
work went round it with `Read` or a sub-agent.

**Candidate remedy**: reproduce each command with `bin/hooks-daemon probe`, and
find why a path outside the glob matches (for example a recursive flag treated
as searching the whole tree).

**Status**: ✅ Fixed on `worktree-n266-flaggable-grep`; the two reported commands could
not be reproduced. The guard's flaggable-path match is a text match on the command
(`secret_file_matching.find_protected_mention`), and on current code neither command
as described is denied, nor is any variant that only names paths off the flagged tree
or carries a quoted regex. The likely cause is the quoted-regex-as-glob defect N269
(`e9281dfda`, the same day), which judged a grep pattern's glob-like text as a path;
that is not proven, because the original patterns were not recorded. Testing found the
opposite gap: a recursive `grep -r` or `rg` rooted at `.`, at `tests/`, or with no
path was never denied, because nothing modelled where a search descends. The guard
now resolves each recursive search's roots (`grep -r`, `rg`, `git grep`) against the
payload cwd and project root and denies any root that is an ancestor of, or inside,
a flagged directory, or that cannot be placed; a named path off the flagged tree stays allowed.
Review round 1: such a search is allowed when it explicitly excludes the flagged directory
(`grep --exclude-dir=<name>`, `rg -g '!<path>/**'`, `git grep -- ':!<path>'`), and the deny
message prints the exact flag for the tool used instead of the quarantine-delegation text.

### N265 — `secret_file_guard` spends about 2.2 s of CPU on one realistic Python program

**Found**: CI on the N101 merge (`5f9600fb2`, run 36689213931) denied
`test_a_realistic_dict_and_f_string_program_stays_allowed` on all three Pythons: the
guard's scan did not finish within its 5 s production deadline, so it failed closed.
The fix agent measured the scan at about 2.2 s of CPU on that input, so a runner
about twice as slow as this host crosses the deadline. The test now injects a 120 s
deadline (`d8b240179`), which keeps it honest about the verdict but hides the cost.

**Why it matters**: a guard that runs before every Bash call and takes seconds on
ordinary input slows every agent, and on a loaded host it denies safe commands.
Whether N101's merge made the scan slower is not established.

**Candidate remedy**: profile the scan on that input and bound the cost of the
expensive step. Add a performance test with a budget relative to a baseline,
not a wall-clock bound (the N222 lesson).

**Fix**: the hot spot was `_globs_can_intersect` in `secret_file_matching.py`: 48,600
DP calls (about 807,000 grid cells for a 30-event program) because each token's bracket
expansions, such as `["tool_name"]` into nine spellings, were each run against all 54
protected patterns. A spelling with no wildcard is now one cached regex match. Two
smaller quadratic steps were also removed (`_outside_every_span` rebuilt its start list
per call; `split_unquoted_spans` scanned every separator at every character). Tests count
DP cells against command length, not seconds. Report:
[subagent-reports/260930-n265-guard-cost-sonnet.md](subagent-reports/260930-n265-guard-cost-sonnet.md).

**Status**: ✅ Fixed (branch `worktree-n265-guard-cost`, not yet merged).

### N135, N176, N177, N189, N244–N246 — carried from the dropped N53 branch

Recorded only on `worktree-n466-n53`, which was dropped. Their write-ups are kept
verbatim in [CARRIED-N53-BRANCH.md](CARRIED-N53-BRANCH.md). Five were remedied on
that branch only, so all seven are open on `main`.

**Status**: ⬜ Open (all seven).

### N253–N256 — carried from ledger 00466, their branch dropped

These four were numbered and fixed on `worktree-n466-n253` but never recorded on
`main`. The branch was dropped under Plan 00475's small-batches rule: merging
current `main` conflicted in 6 files (18 hunks), because the N101 merge rewrote the
same heredoc and glob-walk code. The defects stay open, to be fixed fresh on
`main`. The branch's analysis is kept in
[subagent-reports/260929-n253-opus-5-5.md](subagent-reports/260929-n253-opus-5-5.md).
The landing agent judged that N253 and N254 may port cleanly on their own, and
that N255 and N256 need redoing against the N101 code.

- **N253**: `secret_file_guard` exemptions parse options from open lists, so
  `grep --rege=. <key>`, ugrep `--and=.` and `git -c core.fsmonitor=…` print the file.
  **Fixed** on `worktree-n253-open-option-lists`: the grep, `git rm --cached`,
  encrypted-target git and consumer exemptions now read options from closed lists
  (full names only); `git -c`, `--config-env` and unknown options void the exemption.
  Report: [subagent-reports/261001-n253-option-lists-sonnet.md](subagent-reports/261001-n253-option-lists-sonnet.md).
- **N254**: `sensitive_content` and the redaction sinks resolve
  `secret_word_list_path` differently (absolute path, `{REPO_ROOT}` token).
  **Fixed** on `worktree-n254-word-list-path`: the handler now calls
  `secret_redaction.resolve_secret_word_list_path` like every other reader
  (docs semantics: repo-relative, optional `{REPO_ROOT}/`, absolute degrades to the
  default). Report: [261001-n254-word-list-path-sonnet.md](subagent-reports/261001-n254-word-list-path-sonnet.md).
- **N255**: `git commit -F - <<'EOF'` is denied as R-SECRET-EVALUATION-ERROR:
  ENAMETOOLONG from a glob in apostrophe-quoted prose on Python 3.11.
  **Does not reproduce on current `main`** (rechecked on 3.11.2 on
  `worktree-n255-n256-heredoc`): N101 replaced `Path.glob` with a walk that reads each
  lookup itself, and `_GlobWalk._record` treats ENAMETOOLONG on a component past
  the filesystem's name limit as proof of absence. A joined path past PATH_MAX is
  still a deliberate deny (review 8). Regression tests added: six token shapes
  through `_expand_glob_token`, a forced `stat`/`lstat` raise, and the commit-message
  shape through the handler.
- **N256** (part 1): `secret_file_guard` glob-walks and judges quoted heredoc bodies
  fed to text readers. **Fixed** on `worktree-n255-n256-heredoc`:
  `strip_quoted_heredoc_bodies(text_readers_only=True)` blanks a body whose every
  receiver reads it as text (`TEXT_READING_SINKS`, or `git commit`/`git tag` with
  `-F -`/`--file=-` and no `--pathspec*`), and the guard's Bash route scans the
  blanked command. A prose mention of a protected name in a commit message no longer
  denies. Executors and path readers (`bash`, `xargs`, `git update-index`, `patch`,
  `jq`, a substitution, an unquoted delimiter) keep their body. Part 2, the
  enumeration cap verdict, is NOT done here: it has a separate owner ruling.
  Report: [subagent-reports/261001-n255-n256-heredoc-sonnet.md](subagent-reports/261001-n255-n256-heredoc-sonnet.md).
  Coordinator review note: `wc` has no closed option list, so a body fed to
  `wc --files0-from=-` is blanked. Real exposure is nil: every heredoc body ends
  in a newline, so the name `wc` reads matches no real file, and `wc` prints
  only counts. Close it if `wc` ever gets an option list.

**Status**: ✅ N253 (dbb744f26), N254 (9b589c4fc) and N256 part 1 (efe0ec517)
merged; N255 not reproducible, regression-tested. N256 part 2, the enumeration
cap, moves to [Plan 00478](../00478-unknown-guard-verdicts-warn/PLAN.md).

### N264 — a sub-agent's edits landed, uncommitted, in another branch's worktree

**Found**: dispatching a Sonnet agent to land `worktree-n466-n253`, its clean-tree
check failed. Three files in that worktree (`secret_file_guard.py`,
`secret_file_matching.py`, `test_secret_file_guard.py`) held 253 added lines,
all written in the same second, 08:22:51 UTC on 2026-09-30. The branch's reflog
had not moved for 20 hours, the shared stash was empty, and only this session's
`claude` process was running. So the writer was a sub-agent of this session. The
only one active then was the agent landing `worktree-n466-n101`, which was
working on the same guard in its own worktree. Which tool call wrote them is not
established.

**Why it matters**: the edits were the unapproved "warn, don't block" change for
`secret_file_guard`, with a dated owner-ruling comment. Committed by the next
landing agent, they would have reached `main` under the wrong branch's name.
Nothing in the daemon stops a sub-agent writing outside the worktree it was
given.

**Handled**: the edits are kept as `untracked/briefs/n253-unattributed-warn-dont-block.diff`
and reverse-applied, so the worktree matched its branch again. The landing brief
now says to write only inside the agent's own worktree.

**Candidate remedy**: a PreToolUse guard that, for a sub-agent whose working
directory is a linked worktree, denies a Write/Edit into a DIFFERENT linked
worktree of the same repository.

**Fixed on branch `worktree-n264-cross-worktree-write`** (not yet merged): the
`subagent_worktree_write_guard` handler (`R-SUBAGENT-CROSS-WORKTREE-WRITE`,
on by default, scope SUB, priority 14) denies a sub-agent's Write/Edit/
NotebookEdit from a linked worktree into a different linked worktree or the
main working tree of the same repository. Worktree membership is read from
git's own `.git` markers (nearest marker above the resolved path, shared
`commondir`), so a worktree nested inside the main tree is attributed to
itself; no subprocess runs. Anything unreadable allows with a debug log. Not
covered: writes made through Bash (`>`, `tee`, `cp`), which this guard does
not judge. Report:
`subagent-reports/260930-n264-cross-worktree-sonnet.md`.

**Status**: ✅ Fixed (branch `worktree-n264-cross-worktree-write`, merge pending).

### N263 — the release empties UNRELEASED/post-upgrade-tasks/ but not its README's task index

**Found**: CI on the v3.67.0 release commit `e55c2ea28` (run 36662494834) failed
on all three Python versions, in two tests in
`tests/integration/test_repo_hygiene_check.py`, both rule `post-upgrade-index-drift`.
Step 6 moved the five `NN-*.md` task files out of
`CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/`, but that directory's
README kept its five index rows, which now named files that are not there.
RELEASING.md Step 6 said how to fill the versioned guide's index, but not to empty
the UNRELEASED one. No QA run between Step 6 and the tag caught it.

**Consequence**: the `v3.67.0` tag carries the stale index. It is a documentation
row in the repository, not daemon behaviour, and the published assets are
unaffected. The tag is not moved.

**Status**: ✅ Remedied. The UNRELEASED README's index is back to the
`_No tasks are queued for the next release._` placeholder, and RELEASING.md Step 6
now has an "Empty the UNRELEASED task index" step, with the hygiene test added to
its Verify block. The hygiene test already pins the invariant; the gap was procedural.

### N262 — the release procedure has no check that the notes fit a GitHub release body

**Found**: publishing v3.67.0, `gh release create --notes-file RELEASES/v3.67.0.md`
failed with HTTP 422, "body is too long (maximum is 125000 characters)". The notes
were 126,003 bytes because Step 5 folds every holding-area callout into the notes
verbatim, and this release carried 97 of them. Nothing in RELEASING.md, the release
agent or `invoke.sh` measures the notes against that cap, so the first sign is a
failure at publish time, after the tag is already pushed.

**Handled for this release**: the GitHub body is the notes with the verbatim
Highlights replaced by a link to that section at the tag (14,301 characters). The
committed `RELEASES/v3.67.0.md` is unchanged. Every callout is also a **Changes** entry.

**Candidate remedy**: the release agent writes the GitHub body itself, with the same
substitution once the notes pass the cap, and a test pins the body under 125,000
characters before Step 14 runs.

**Status**: ✅ Remedied in `ea8dcd542`. `scripts/release/build_github_release_body.py`
writes the body (notes unchanged when they fit, Highlights replaced by a link when they
do not, exit 1 if still over 125,000). RELEASING.md Step 14 and the Manual Release
block, the release skill's `invoke.sh` and the release agent run it BEFORE the tag and
give `gh release create` its output. Pinned by
`tests/integration/test_build_github_release_body.py`.

### N286 — main CI red after N264/N266: three tests

**Found**: main's full CI (run 36797037729, all three Pythons) failed three tests, all
from the N264 (`subagent_worktree_write_guard`) and N266 (`flaggable_content_channel_guard`
resolves recursive roots, fails closed on an unplaceable one) merges. **Cause**: both
merged on targeted QA only; the tests that cross-check every handler (the blindness
census, the skip-list checker's whole-tree scan, the live playbook) are full-suite tests.

1. `tests/acceptance/test_playbook_harness.py`: the `RootRecursionGuardHandler` probe
   `false && grep -rl "needle" "$CLAUDE_PROJECT_DIR"` expects ALLOW, but the full daemon
   now denies it via R-FLAGGABLE-CONTENT-CHANNEL (an expanded root cannot be placed, so the
   guard fails closed). No field exists for "another handler legitimately denies this
   probe", so the probe became `false && grep -rl "needle" src`: a project-relative literal
   root that reaches no flaggable path. The variable root stays pinned by the handler's
   unit tests.
2. `tests/integration/test_bash_write_blindness_coverage.py`: the new handler keys on
   Write/Edit/NotebookEdit and had no verdict. Recorded BLIND (a Bash redirect/tee/heredoc/
   cp into a sibling worktree produces no event it sees); its resident guidance now names
   the three tools it judges and says a clean Bash write proves nothing.
3. `tests/unit/scripts/test_skip_list_substring_checker.py::TestTheCurrentTree`:
   `any(char in path for char in _SHELL_EXPANSION_CHARS)` matched the checker's
   list-entry-in-path shape. It is a character-class test, not a skip list; replaced by a
   compiled `[$`\]`pattern's`.search(path)\`, same behaviour.

**Status**: ✅ Remedied on `worktree-ci-red-n264-n266`.

### N287 — `semgrep` and `dependencies` fail on main; nothing runs them

**Found**: timing the checks outside `changed` for Plan 00475 Task 1.1. Run directly on
main at 39451c461, `llm_qa.py semgrep` exits 1 with six `pathlib-quadratic-containment`
findings: `install/upgrade_gate.py` (two), `install/upgrade_guides.py`,
`install/upgrade_tasks.py` and `scripts/qa/check_daemon_dir_cd_in_docs.py`, all calling
`Path.relative_to`/`is_relative_to` directly instead of the `utils/path_containment.py`
helpers. `llm_qa.py dependencies` exits 1 because the workspace venv's installed metadata
says 3.66.0 while the project is 3.67.0.

**Cause**: neither check is in the CI workflow or in the `changed` tier, so only `all`
runs them, and `all` runs only at release preparation. The violations arrived with Plan
00376's upgrade work and sat unseen.

**Status**: 🔄 The six findings are being fixed on `worktree-n287-semgrep-containment`.
The venv needs a re-sync. The gap itself belongs to Plan 00475 Task 2.1, which puts the
cheap checks, `semgrep` included, into `changed`.
