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
entries carried in the sections below. Plan 00483's dismissals and no-change
rulings for these entries are recorded in the next section.

### Plan 00483 write-back for the 00466 entries (Task 2.3)

Plan 00483 triaged the 67 entries open in archived ledger 00466
([TRIAGE-ledger-466.md](../00483-threat-model-conformance-audit/TRIAGE-ledger-466.md)).
Ledger 00466 is archived, so its dispositions are recorded here. The dismissals are
verdicts of that triage (classified under the two-part test, checked by the
coordinator); none is an owner ruling. The command-shaped ones have a
`UNCOVERED-accepted` row in `scripts/qa/dangerous-invocation-corpus.yaml`.

**Dismissed (threat model):**

- **N45** — limb 2: a NUL byte in `secret_word_list_path`; no working purpose, and no careless edit produces it. No command, so no corpus row. The `except (OSError, ValueError)` hardening noted in the triage needs no plan.
- **N57** — limb 1: `V=...; bash -c "$V"`, `eval "$V"`, an alias, or a file written then run; the operative text is not visible at the call. Corpus row `dismissed-n57-variable-body-in-bash-c`. Same ground as dismissed N135 and N189.
- **N68** — limb 2: a moved-away daemon checkout reads NOT_INSTALLED and fails open; the ruling's "anything that stops or routes around the daemon". No command, so no corpus row.
- **N71** — limb 1: a script rewritten between judgement and run; its text comes from a file. The Plan 00464 script walker it concerned is absent from main. No corpus row (a script file is not a command string).
- **N72** — limb 1: `python3 s.py` building a git argv at run time; same absent walker. No corpus row.
- **N77** — limb 1: `x=...; bash -c "$x"`, `eval "$x"`, an in-command alias, a script written then run. Corpus row `dismissed-n77-variable-body-in-eval`.
- **N78** — limb 2: a trailing `#c` after a key name and backslash-octal in an unquoted word. No corpus row: main denies the representative command (`cat $'\151d_rsa'` is denied by `secret_file_guard`), so no allowed command exists to pin. The one prose false positive the entry mentioned was never identified.
- **N89** — limb 2: `cat() { bash; }; cat <<'E'` and `alias cat=bash`; no ordinary work redefines `cat` as `bash`. Corpus row `dismissed-n89-redefined-data-sink`.

**No change:**

- **N62** — subagent context and concurrency budgets stay with the harness knob `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` and the Plan 00479 usage ceiling. Source: a ruling the owner delegated to a Fable subagent, extended to N62 by the coordinator ([RULINGS-owner-delegated-fable.md](../00483-threat-model-conformance-audit/RULINGS-owner-delegated-fable.md)), confirmed by a coordinator call on 2026-10-05, which is not an owner ruling. Re-open trigger: if the 00479 pause fires routinely because of subagent context, build the concurrency cap first.
- **N74** — `grep -r` over an ancestor of a protected path. Source: the same Fable ruling, "no change, accepted residual". The owner ruling A2 of 2026-10-05 ([OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md)) settled N74 through the cached protected-file index, merged as dc5c9263b. Corpus row `recursive-search-grep-r-whole-checkout` is `COVERED`, so there is no `UNCOVERED-accepted` row.
- **N240** (carried list) — the two `script` log shapes now have their corpus rows, `no-change-n240-script-typescript-log` and `no-change-n240-script-log-option`; they were promised by the Fable ruling but missing from the corpus.

**Still open, residuals stated precisely (not dismissed):**

- **N124** — the grep/rg pattern shapes are fixed; the `find -regex`/`-iregex` operand is still read as a path (see its entry in [CARRIED-REFIX-BRANCHES.md](CARRIED-REFIX-BRANCHES.md)).
- **N222** — the guard half is changed, not removed: `SCAN_DEADLINE_SECONDS` is still used at `secret_file_guard.py` lines 1403 and 1616, but A1 (merge dc5c9263b) made the timeout outcome allow with an advisory instead of deny. What remains is the test half: about 15 tests that assert wall-clock bounds and fail on a loaded host. Remedy: switch them to the load-scaled helper N95 already uses.
- **N260** — the `sys.path` half is fixed (257847b51). Still open, direction corrected: `.github/workflows/qa.yml` (line 498) passes only `--import-mode=importlib`, while the local runner (`daemon/cli.py`, lines 6384-6396) passes that plus `-p no:claude_code_hooks_daemon.qa.full_qa_gate`. CI therefore loads the full-QA gate plugin and the local run does not, so a run can be green locally and red on CI.

**Fixed, not yet marked in the 00466 index:** N170, N130 and N136 (statuses corrected in CARRIED-REFIX-BRANCHES.md, merges 9b2e15be1 and 012915bd9/dc5c9263b); N79 (the ordinary-command corpus is 391 rows now, above the 200 asked).

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

**Investigation** (report `subagent-reports/261002-n280-claude-md-writer-sonnet.md`, merged
c55cb56e0):

- **Lead 1 ruled out.** The only writer of the guidance block is `ClaudeMdInjector`, run by
  `DaemonController.initialise()` with an explicit `workspace_root`, and it already skips a
  linked worktree. No writer resolves its root through `--git-common-dir`.
- **No reproduction.** Three test runs from a worktree (2,673, 781 and a writer-adjacent
  re-run) left main's `CLAUDE.md` mtime and content unchanged.
- **Lead 2 neither confirmed nor excluded.**
- **New candidate, unproven.** The `no_test_writes_tracked_generated_docs` fixture in
  `tests/conftest.py` restores each protected file to its per-test START baseline. A
  legitimate regeneration that lands mid-test, such as a daemon restart or a merge, would be
  reverted to older bytes. That fits "older than main, repeated, pid unchanged". It does not
  clearly fit the preserved copy holding the old text.

**Status**: ⬜ Open, cause not found. The working rule "never restart the daemon while a test
run is in progress" already prevents the candidate sequence. Changing the fixture to skip the
restore when the post-test bytes equal `HEAD` would weaken a guard, so it is left as a
proposal rather than made.

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

**Status**: 🔄 Graduated to Plan 00475 Task 4.2, a merge-time advisory for a head with no
recorded green `changed` run. `main` is repaired. The interim rule is already written down in
`CLAUDE/QA.md` under "Before Merging: the Coordinator's Check". Built on
`worktree-p475-merge-qa-advisory` (`merge_qa_advisor`, advisory only), awaiting merge.

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

**Status**: N244, N245 and N246 fixed (merges 52fd9cd9b, 17b0aa491, 530ffc83d); N135, N176, N177 and N189 dismissed. See below.

- **N244**: **Fixed** (merge 52fd9cd9b). On a bare `git commit`, plan QA now scans
  the INDEX instead of the disk. It uses one `ls-files -s` and one `cat-file --batch`
  per commit. The row-to-folder check asks that same tree. An index git cannot read
  falls back to the disk. Still read from the disk: the pathspec form (N245), a
  `git add` in the same command (N246), and the checks that open files themselves
  (`path-existence`, `plan-doc-size`, `journal-entry-ordering`, `same-commit-plan-doc`,
  and the journal lookups in `checks/common.py`). Report:
  [subagent-reports/261002-n244-committed-tree-sonnet.md](subagent-reports/261002-n244-committed-tree-sonnet.md).

- **N245**: **Fixed** (merge 17b0aa491). A pathspec commit (`git commit -m x a.txt`,
  `--only`, `--include`) is judged on the named paths only, in `sensitive_content`,
  `staged_lint_gate`, `remote_docs_commit_gate`, `guard_config_commit_gate` and docs QA.
  Plan QA keeps reading the disk for the pathspec form; round 3 found the index read
  regressed it, so that part was taken out rather than opening a fourth round. Three Opus
  review rounds. The branch's `llm_qa changed` run was red on two items, both
  checked: generated-doc drift that main had already fixed (none after the merge), and
  four files `changed_tests` calls too broad to map. All 2632 selected tests passed, and
  the 638 touched tests pass on merged main. Round 3's follow-ups are N299–N301. Report:
  [subagent-reports/261002-n245-pathspec-sonnet.md](subagent-reports/261002-n245-pathspec-sonnet.md).

- **N246**: **Fixed** (merge 530ffc83d; Opus review MERGE-WITH-FIXES, fixed in round 2). A `git add`
  before the commit in the same command is run against a copy of the index and a scratch object
  directory (`utils/staging_simulation.py`), and `sensitive_content`, `staged_lint_gate`, docs QA, plan QA and
  `remote_docs_commit_gate` read that index. An add whose scope cannot be read is applied as
  `git add -A --ignore-errors`; a simulation that cannot finish (timeout, fatal) denies with "run `git add`
  as its own call". It runs with `core.splitIndex=false`. `guard_config_commit_gate` (advisory only) still
  reads the real index for the add. Still not done: one shared simulation per dispatch (five gates each
  simulate, so a timing-out add costs up to 5s per gate), and `git apply --cached` /
  `update-index --add` are not simulated (as before the merge). Reports:
  [subagent-reports/261002-commit-gate-same-cmd-sonnet.md](subagent-reports/261002-commit-gate-same-cmd-sonnet.md),
  [subagent-reports/261002-commit-gate-round2-sonnet.md](subagent-reports/261002-commit-gate-round2-sonnet.md).

- **N135, N176, N177, N189: ✅ Dismissed. They are out of scope under the owner's
  threat-model ruling**
  ([ARCHITECTURE.md § Threat model](../../ARCHITECTURE.md#threat-model-the-agent-is-careless-not-hostile)).
  The daemon helps a careless agent and does not defend against a hostile one, which
  could simply stop the daemon. Each of these commits is reached only through a shape an
  adversary writes:

  - text run by `bash -c "$X"` or `eval`;
  - a git alias;
  - `builtin cd`;
  - a commit nested in `$(( $(…) ))`;
  - a `case` inside `function f {` inside `$( )`.

  Neither remedy is wanted: not the dropped branch's shell walk, and not a git
  `pre-commit` hook built to catch these shapes.

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

**Status**: ✅ Fixed. The six sites call `path_relative_to`/`path_is_relative_to`
(9342fa898, merged a1f96fdc0); `upgrade_gate_standalone.py` loads `path_containment.py`
before the gate's modules, since the gate now imports it. The venv was re-synced, and
`semgrep` and `dependencies` both pass on main. The gap is closed for `semgrep`, which
Plan 00475 Task 2.1 (b2984b70a) puts in `changed`. `dependencies` stays out of `changed`
because it judges the local venv rather than the tree, so only `all` runs it.

### N288 — an event-socket test fails wherever the pytest process exports a hostname override

**Found**: by the Plan 00475 Task 4.1 agent, then reproduced on main.
`tests/unit/daemon/test_event_socket_listeners.py::TestEofFraming::test_event_socket_dispatches_through_same_controller`
fails in this container and passes in CI.

**Cause**: Plan 00470 Task 6.1 stamps `hooks_daemon_hostname` on each payload, read from the
environment of the process at the other end of the socket. This test's client is the pytest
process itself. The container exports `CCY_HOST_HOSTNAME` and CI exports nothing, so only
this container sees an extra key in the exact-equality assertion. Deleting the variable with
`monkeypatch.delenv` would not help, because the daemon reads the peer's
`/proc/<pid>/environ`, which still holds the environment the process started with.

**Status**: ✅ Fixed on main. The test replaces `server._peer_hostname` with a peer that
exported no override. The stamp itself keeps its own coverage in
`test_event_socket_session_hostname.py`, whose client is a separate process with a
controlled environment.

### N289 — in this repository the slow SessionStart sweeps appear never to reach a session

**Found**: by the coordinator while live-probing Plan 00475 Task 4.1 on main at d6caefded.
Load average was about 1.4. Every `bin/hooks-daemon probe SessionStart` (source `startup`)
took 20.4 s and ended "Chain cut short: exceeded its 20.00s dispatch budget; the output of
the 21 handler(s) that finished is kept". The log shows `bounded_dispatch` warning that the
chain "keeps running in the background".

**Why it matters**: N276 (aa557cc12) made the slow sweeps run last and kept the cheap
handlers' output when the chain overruns. Those sweeps are tagged slow: `git_upstream_checker`,
`docs_qa_sweep`, `plan_qa_sweep`, `reference_repo_sweep`, `gitignore_safety_checker` and
`secret_file_hygiene_checker`. If the chain always overruns here, their findings may never
reach a session, and none of their output appears in this session's SessionStart context.
Nothing reports that they were dropped. Not yet established: each sweep's own time, and
whether a sweep that finishes in the background is delivered later.

**Part 1** (06f04f7de, merged 7c5dfe294; report
`subagent-reports/261002-n289-sessionstart-sweeps-sonnet.md`):

- **Late output is discarded.** `BoundedDispatcher` only logs it.
- **The cut-off note now names the handlers that did not finish**, so the drop is no longer
  silent.
- **Two speed-ups.** The three path-protection sweeps resolve each path once, and a glob whose
  literal parts are absent from a path is skipped before the full match.
- **The live overrun remains.** The agent measured on a fresh worktree, where the sweeps took
  about 1.6 s each.

**Real cost**: in the main checkout, `gitignore-safety-checker` and
`secret-file-hygiene-checker` each take about 35 s, and the chain totals 76 s run in-process.
They walk the gitignored `untracked/` tree, which holds the venvs and the nested worktree
checkouts.

**Part 2** (a9de781ff, merged 76cf82266; report
`subagent-reports/261002-n289b-sweep-scope-sonnet.md`):

- **What git lists**: `git ls-files` lists 532,000 paths in the main checkout, of which
  527,748 are ignored. About 456,000 sit under `untracked/scratch`, mostly whole-repository
  probe copies left by earlier review runs (13 GB), and about 70,000 are in virtualenvs.
  Nested worktrees cost nothing, because git lists each as one entry.
- **Pruning**: ignored untracked files under a `pyvenv.cfg` directory or `node_modules` are
  no longer judged; tracked files there still are.
- **Shared scan**: the two sweeps share one scan and one set of protection verdicts per
  event.
- **Result**: the two sweeps together went from about 71 s to 8.2 s on main.

**Live result**: after the daemon restart at ee58adb7c, a `SessionStart` probe (source
`startup`) completed in 14.0 s with no cut-off. Before part 1 it took 20.4 s and was cut
off.

**Status**: ✅ Fixed. Most of the remaining sweep cost is the scratch probe copies under
`untracked/scratch` (13 GB). Deleting them is the owner's call, since that is a bulk deletion
of earlier runs' evidence.

**Owner ruling (2026-10-05):** resolved: yes, clean up (keep anything a live worktree or an open report points at), and add a housekeeping step to the release process — see [OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md) (D3).

**Clean-up done (coordinator, 2026-10-06):** removed 3,247 stale entries (12.1 GB) from `untracked/scratch`,
which went from 14 GB to 294 MB. Kept every entry modified in the last 48 hours and every entry a live (non-Completed)
plan folder cites. The release housekeeping step is RELEASING.md Step 15.1.

### N290 — the coordinator stated a confident, unverified, false claim about the codebase

**Found**: by the owner ("supervisor lives outside this repository?? what????"). While
filing Plan 00479, the coordinator wrote that the ccy supervisor "is outside this
repository", in the plan's Non-Goals, in Task 4.5 and in its message to the owner. No search
backed it. The supervisor is `.claude/ccy/claude-supervise.py`, with tests under
`tests/unit/supervise/` and docs in `CLAUDE/development/CcySupervisor.md`. The guess came from
a remembered constraint ("never touch the live supervisor") being restated as a fact about
where the code lives. It changed the design of Task 4.5 until the owner caught it
(corrected in f1592f146).

**Why nothing caught it**: `nitpick.hedging_language` flags uncertain wording. A confident
false claim has none, and it is the more dangerous case. The owner reports this as a pattern
in the current model: confidently stating guesses.

**Candidate remedy**, proposed to the owner: a Stop-time check, and the same check on
PLAN.md commits.

- **What it flags**: negative-existence and location claims about the codebase, such as "X is
  outside this repository", "nothing does Y", "there is no Z" and "only W reads it".
- **When it blocks**: when the turn ran no search (Grep, Glob, LSP, or a search command) that
  could support the claim.
- **What it asks for**: verify the claim, or mark it as unverified.
- **First failing fixture**: this sentence.

Also proposed:

- a verifier-agent pass that tries to disprove each factual claim in a new plan;
- a guidance rule that a claim about repository structure cites a path or a command.

**Status**: 🔄 Graduated to Plan 00480. The owner chose the verifier-agent remedy ("anything
else is really hit and miss"): a Sonnet fact itemiser and verifier wired into plan QA through
a first-class debounce. The plan workflow core doc gained principle 1, "Always Verify, Never
Assume" (51d3ad812).

### N291 — `secret_file_guard` reads a double-quoted grep regex as a protected-path mention

**Found**: by the coordinator while merging Plan 00479's status line work. A Bash command
that filtered a scratch list of file names was denied with R-SECRET-BASH-MENTION. The
command was `grep "^tests/.*test_.*\.py$" untracked/scratch/p479-py.txt`, assigned to a
variable. The guard reported "Matched protected glob: `.vault-pass*`", "Matched on this
token: `^tests/.*test_.*\.py`". The token is a regular expression applied to a file's
CONTENT, and names no path. Its `.*` runs make it match any glob, so the guard reads it as
possibly naming a protected file.

**Related**: N269 fixed the single-quoted form, where a grep regex was expanded as a
filename glob.

**Reproduced with `bin/hooks-daemon probe`**: the trigger is the `$( )` assignment, not the
quoting. `x=$(grep '<regex>' f)` and `x=$(grep "<regex>" f)` are both denied
(R-SECRET-BASH-MENTION), while the bare `grep "<regex>" f` is allowed. N269's pure text
consumer exemption is therefore not applied to a command inside a command substitution.
The payloads are `untracked/scratch/n291_probe_{plain,assign,single_assign}.json`.

**Worked around**: by splitting the filter into two literal prefix greps (`"^tests/"`, then
`"/test_"`).

**Status**: ✅ Fixed (merge 4a30b9248, rework c8232ca80).

- **Allowed**: inside a substitution, only `grep`/`egrep`/`fgrep` operands are relaxed.
- **Still judged**: `echo`, `printf`, `rg -r` and awk print literals. Their operands reach the
  output, so they stay judged.
- **Also closed**: the merge closes `x=$(true; echo 'P*'); cat $x`, which main allowed before it.
- **Now allowed**: a quoted glob given to grep as a FILE operand, such as
  `$(grep -l x '<prefix>*')`. This is harmless: grep opens that literal name, which matches
  no protected file.
- **Live**: probed after a restart, both reproductions are allowed.

The first attempt, commit 2a3347f6a, was rejected: it relaxed `echo`/`printf` operands inside a substitution, so
`cat $(echo '<protected-prefix>*')` went from denied to allowed. The output of an
unquoted substitution is glob-expanded. Only operands that cannot reach the
substitution's output (a grep, rg or awk pattern) may be relaxed. Probe:
`untracked/scratch/n291_bypass.py <src dir>`.

### N292 — `upgrade_approval_guard` denies a plain interpreter run with `PYTHONPATH`

**Found**: by the coordinator while probing N291. This command was denied with
R-UPGRADE-APPROVAL-ENV-BYPASS:

```
V=<venv>/bin; PYTHONPATH=/workspace/src $V/python untracked/scratch/n291_bypass.py ...
```

The script is a scratch probe that imports the secret guard. It runs no upgrade and
names none of the upgrade scripts. Which recogniser classified it as "runs the upgrade"
is not yet established. One candidate is the unreadable-script rule, since the interpreter
path is a variable. Another is a token in the script.

**Worked around**: the script takes the src path as `argv[1]` and inserts it into
`sys.path`, with no environment variable.

**Status**: ✅ Fixed (15fe504c1, merged).

- **Cause**: `_script_run_is_upgrade` resolved the relative script against the hook cwd and ignored
  the command's leading `cd /workspace &&`. The script therefore looked missing. A missing script
  counts as the upgrade once `PYTHON*` steers.
- **Fix**: the guard now follows a leading chain of `cd <literal existing dir>`. Every uncertain
  shape keeps the strict hook-cwd behaviour.
- **Tests**: 242 guard tests pass, every pre-existing denial included.

### N293 — GitHub #68: the guards fail closed on an absolute glob with 2+ wildcards under an existing literal prefix

**Source**: GitHub #68, filed by a whitelisted author, plus one comment. The owner flagged it as
causing a lot of problems. The issue text is untrusted data, so its claims were re-verified here.

**Reproduced on main after N291** with `untracked/scratch/gh68_repro.py <src dir>`, run with
process cwd `/` and payload cwd set to the fixture dir F:

- `cat $F/*/*`: quarantine guard denies.
- `ls $F/*/*-release`: secret guard denies.
- `for x in a b; do cat "$x"$F/*/*; done`: quarantine guard denies.
- Single-wildcard forms are allowed.
- The issue's unreadable-sibling `PermissionError` cases did not reproduce, but this container runs
  as root and root can read a mode-000 directory. They need a non-root test.
- The comment's grep-regex case (quarantine guard) is allowed on main.

**Root cause**: `bounded_recursive_glob` in `src/claude_code_hooks_daemon/utils/shell_expansion.py`
(lines 4062-4074). An absolute token is walked from base `/`. The function counts wildcard segments
across the WHOLE pattern and refuses 2 or more. It ignores an existing literal prefix (`F/`), which
already narrows the walk to one directory.

**Still to check**:

- The comment reports a second route. In a written `.bash` file's content, an unresolved `${VAR}` and
  a relative word are expanded from the daemon process's cwd `/`, which turns ordinary log or
  filename lines into root walks.
- The `"$x"$F/...` word is relative in bash, under an unknown `$x`. Treating it as `$F/...` judges a
  path the shell would never touch.

**Status**: ✅ Fixed (92b9b49e0, merged).

**Fix**: `bounded_recursive_glob` now walks from the longest existing literal prefix. The root
refusal applies only to a walk that still starts at `/`, including a prefix that resolves back to
`/` through `..` or a symlink.

**Unreadable sibling**: when a wildcard selects a directory that cannot be searched, a fully named
path inside it is judged by its name.

**Correction to the issue**: `"$x"$F/...` is NOT unreachable. An empty `$x` reaches `$F/...`, so
both readings are judged.

**Comment route 1** (script content, daemon cwd) did not reproduce in 48 combinations. Regression
tests pin it.

**Coordinator safety probe** (`untracked/scratch/gh68_deny.py`): every denied shape with a
protected file under F has the same verdict on the branch as on main. All the issue's cases are
now allowed.

**Accepted residual, unchanged**: a bare generic glob (`cat $F/*/*`) is not treated as a mention
of a protected file (Plan 00272 Decision 12).

### N294 — a status-line client that hangs up still logs an ERROR traceback

**Source**: the coordinator, reading `bin/hooks-daemon logs` after the N244 restart.

**Evidence**: five `[ERROR] asyncio: Task exception was never retrieved ... BrokenPipeError`
records within 0.5 s, all on Status events. Each one comes straight after the daemon's own
`Client disconnected before its response was delivered.` debug line. That line shows the
`except (BrokenPipeError, ConnectionResetError)` branch in `HooksDaemon._handle_client`
(`daemon/server.py`) already classified the lost peer. The `finally` block then calls
`await writer.wait_closed()` (line 2181), and that call raises the same `BrokenPipeError`
outside every handler. The task dies with an unretrieved exception, so the noise the branch was
written to remove comes back at ERROR level, in the channel the docs point at
(`logs | grep -i error`).

**Trigger**: the status line re-renders faster than the slow chip in N295 replies, so Claude Code
drops superseded renders.

**Status**: ✅ Fixed (merge fc6782bf1).

Both client handlers now close through one helper, `HooksDaemon._close_writer`. It closes the
writer, then awaits `wait_closed()`. A `BrokenPipeError` or `ConnectionResetError` from that wait
is recorded at DEBUG and goes no further. Any other error still surfaces. The request counter is
decremented before the close, so it always runs. The per-event handler had the same pattern and
uses the same helper. Tests are in `tests/unit/daemon/test_server_dead_peer_logging.py`.

### N295 — the prompt-cache chip re-reads every sub-agent's sidecar file on every render

**Source**: the coordinator, timing handlers in `bin/hooks-daemon logs`.

**Evidence**: across 18 renders, `status-prompt-cache-indicator` took 84–427 ms (median about
95 ms). Every other status handler took under 3 ms. The `⑂`/`Σ` chips call
`read_subagent_cache_totals` (`handlers/subagent_stop/subagent_cache_aggregator.py`), which globs
and `json.loads` every file in `untracked/cache-sidecar/<session>/`. This session's directory holds
3,369 files (14 MB), one per sub-agent that ever stopped. The cost grows with every agent the
session runs and is paid on every render, so a long-lived orchestrator session pays the most. The
slowness also makes Claude Code abandon renders (N294).

**Status**: ✅ Fixed (merge b44e395a5). Live after the restart: 17 renders took 0–3 ms each,
against 84–427 ms before, and the logs held no unretrieved task exception (N294). The reader now
remembers each session's totals in memory and checks one thing per render: the session directory's
modification time. Every sub-agent write is a rename into that directory, which changes it, so an
unchanged time means no agent was added, rewritten or removed. A time younger than two seconds is
not trusted (a second write in the same timestamp tick would leave it unchanged), so a fresh write
always triggers a rescan; a rescan re-parses only files whose inode, mtime or size moved, so a
rewritten agent file replaces its old figures rather than adding to them. Measured on a copy of the
real 3,371-file directory: before, 92 ms median per render (134 ms worst); after, 0.010 ms median
(0.07 ms worst), with identical totals. The first read after a daemon restart still pays one full
scan (about 150-220 ms), once.

The agent wrote the code before the tests. The coordinator therefore ran the branch's cost tests
against main's unfixed reader. `test_repeated_reads_parse_nothing_after_the_first` and
`test_a_newly_stopped_agent_shows_on_the_very_next_read` both fail there, so the tests do detect
the defect.

### N296 — the error-hiding audit sees log-and-continue only when the log call is written inline

**Source**: the coordinator, reviewing the N294 fix.

**Evidence**: `ErrorHidingVisitor._is_log_and_continue` in `scripts/qa/audit_error_hiding.py`
flags an `except` body only when it is a single `<x>.error|warning|info|debug(...)` call. The
same handling written as one call to any other function passes, for example `_record(exc)`,
where the helper does the logging. The N294 agent wrote it that way because the inline form
was flagged. In N294 the handling is correct: a peer that has hung up leaves nothing to do, and
the pre-existing `_log_lost_peer` branch uses the same shape. But the detector cannot tell a
deliberate, justified case from one that hides a real failure behind a helper.

The gap is wider than helpers. The rule fires only when the body is exactly ONE statement, so
a log call followed by `continue`, `return {}` or any other statement also passes. The N295
agent reported reworking three flags this way. Its merged reader logs at DEBUG, then skips one
unreadable file or returns empty totals. That is the documented fail-silent contract for
status-line reads, so the handling is correct there. But the audit can neither confirm nor
reject it.

**Open question**: what should a justified log-and-continue look like? Two options: one
recognised, reviewable marker, or a named helper that the audit allowlists. A helper that
merely moves the call out of sight is neither. Changing the audit, or adding allowlist
entries, needs the owner.

**Owner ruling (2026-10-05):** resolved: one named helper with a required reason argument, and the audit widened to catch log-then-continue bodies — see [OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md) (B4).

**Status**: ✅ Fixed (d7ec3ff9b through e90cbd63c). The named helper
`utils/deliberate_swallow.log_and_continue(logger, exc, *, reason, level=WARNING)` exists, and the
audit's `log-and-continue` rule flags any non-raising handler body that logs (inline or by passing
the exception to a helper) and then continues, passes, breaks or returns a fallback. The sanctioned
form is the helper called with a specific `reason`. Console reports (`print`, `sys.stderr.write`), a
report's own `self.output(...)` line, failures recorded on a list or future, stderr/stdout stream
writes and logging `handleError` count as surfacing, and the exception counts as handed to a logger
only when it is passed as a value. Every site is converted: 166 remained at 22c33d242, and
009a7c9b4 and e90cbd63c finish them. No `log-and-continue` entry is left in
`error_hiding_exclusions.json`, and the audit and `TestRealRepoSelfScan` are green. Two sites
could not take the helper as it stood: `measure_instruction_footprint.py` now raises when the
handler package cannot be imported instead of reporting an empty footprint, and the venv-free
upgrade gate loads `escape_hatch` and `deliberate_swallow` by path.

### N297 — the coordinator merged the merge advisor itself without a targeted QA run, and main broke twice

**Source**: the coordinator, finding its own mistake.

**Evidence**: the Plan 00475 Task 4.2 merge (301805f1f) added `merge_qa_advisor`. The
coordinator merged it on static checks and the handler's own tests, and did not run
`llm_qa.py changed`. Two of its effects were outside those tests:

- Its priority (56) collided with the `orchestrator-simulate` project handler, so their order
  was arbitrary. `test_project_handler_priority_collisions` failed.
- It was not classified in `test_claude_md_guidance_coverage`.

Both were found later, by targeted runs over other merges (N231, and the pause-gate branch).
This is the N278 failure again: a branch merged with its targeted QA never run. The advisor
built to catch that was not loaded yet when it merged.

**Status**: ✅ Fixed. The priority is now 59 (47ae8e2c7) and the handler is classified
(3dadb3d8c). The priority fix itself then repeated the mistake: it changed the handler set
without regenerating `.claude/HOOKS-DAEMON.md`, so `generated_doc_drift` failed on main until
1dc459a7a. The advisor is now live and fired on every merge since. The coordinator now runs
`llm_qa.py changed` over each merge whose touched code reaches a core or cross-cutting file.

### N298 — `R-PLAN-NUMBER-DISCOVERY` denies read-only listings of plan files, even inside quoted text

**Source**: two Plan 00483 triage agents found it independently, and the coordinator
reproduced it.

**Evidence**: `plan_number_helper` denies these with `R-PLAN-NUMBER-DISCOVERY`:

- `ls CLAUDE/Plan/*/PLAN.md` and `ls CLAUDE/Plan/*/release-notes*`. These list files; they do
  not look for the next number.
- A `printf '%s' '{…"command":"ls CLAUDE/Plan/*/PLAN.md"…}' > payload.json`, which runs no
  `ls` at all. The text is a quoted argument written to a file.

Under the threat model these are ordinary commands and a false positive is in scope. The rule
exists to stop a scan that derives the next plan number (`ls | sort | tail`). A plain listing,
or quoted text, is neither.

**Status**: ✅ Fixed (merge of worktree-quoted-text-fps). `plan_number_helper` judges
the `ls`, `find` and `grep` rules on the command-position view, and the `ls` glob rule per command:
a glob naming a specific plan, or one followed by a path (`*/PLAN.md`), is a lookup unless the
command also keeps only the last entry.

### N299 — `sensitive_content` resolves a pathspec from the repository root after a `cd`

**Source**: N245 review round 3
([subagent-reports/261002-n245-review3-opus.md](subagent-reports/261002-n245-review3-opus.md)).

**Evidence**: `cd sub && git commit -m x f.txt` is denied when the ROOT-level `f.txt` holds
a term, although the commit records `sub/f.txt`. Main allowed it before N245. This is an
ordinary command shape, so the false positive is in scope.

**Status**: ✅ Fixed (merge 37b9a8020; 2 rounds). The coordinator re-ran the round-1 reviewer's
26-row probe, which checks each verdict against what git actually records. Every commit main
denies is still denied, and 11 that main allowed now are too. Two still pass on both, and both
were already wrong on main: N306 (`cd a || cd b`) and N307 (a second commit). `commit_facts` and
the docs/plan QA gates read the pathspec from the directory the command's `cd`/`pushd`/`-C` lands
in (`pathspec_directory`). Round 2: a `cd` that may fail, be skipped or be backgrounded
(`;`, `&`, `||`, a pipeline stage) is judged from both the moved and the hook directory
(`unmoved_directories`), in every gate. `guard_config_commit_gate` still compares pathspecs to the root as text
(see [subagent-reports/261002-n299-followups-sonnet.md](subagent-reports/261002-n299-followups-sonnet.md)).

### N300 — `remote_docs_commit_gate` does not stand down for a commit in a nested worktree

**Source**: N245 review round 3.

**Evidence**: when the commit runs inside a nested worktree (another repository from the
daemon's point of view), `staged_lint_gate` stands down and `remote_docs_commit_gate`
judges it against this repository. Main had the same wrong-repository behaviour, so N245
did not cause it.

**Status**: ✅ Fixed (merge 37b9a8020): the gate stands
down when the hook `cwd`, after any `cd`/`-C` move, is in another repository. Round 2: a `cd` that
may not take effect stands down only if both the hook directory and the moved one are another
repository.

### N301 — the "every pathspec matches" check costs two git calls per path, in every gate

**Source**: N245 review round 3.

**Evidence**: each commit gate runs its own match check, two git calls per named path. That
is about 0.25 s per gate for 60 paths on a tiny repository, multiplied by the number of gates.

**Status**: ✅ Fixed (merge 37b9a8020): one
`ls-files --error-unmatch` call answers for every path; each gate still asks once (no
cross-gate cache).

### N302 — the full-QA advisory reads `grep -c` and `awk -e` as inline interpreter code

**Source**: the Plan 00483 triage agent and the Fable rulings agent each saw it independently.

**Evidence**: `subagent_full_qa_blocker` emits "UNSEEN: unrecognised-interpreter-inline-code"
on read-only `grep -c`, `awk`, `--help` and `bin/hooks-daemon … 2>&1` commands from a subagent
(seen by three agents now, the third in the Plan 00484 assessment). It treats `-c` and `-e` as an
interpreter's inline-code flag whatever the command is. It is advisory only, but it fires
on ordinary reads and teaches agents to ignore it.

**Status**: ✅ Fixed (merge 1078e4291). `_runs_inline_code` now skips a named set of
search and text tools (`grep`, `egrep`, `fgrep`, `rg`, `awk` family, `wc`, `sort`, `head`, `tail`,
`cut`, `jq`), by exact program name. The alternative, an allowlist of known interpreters, would
have undone the round-10 decision that an unknown program run with `-e` stays UNSEEN; the exclusion
list keeps `node -e`, `perl -e`, `foo -c '…'` and the rest as they were. `awk` is excluded because
its program is a positional argument that is not judged either, so flagging `awk -e` protected
nothing. Pinned by `TestInlineCodeFlagIsNotReadOnSearchAndTextTools`.

### N303 — the pause-gate merge left `UsagePauseToolGateHandler` unclassified; main was red

**Source**: the N299 agent's `llm_qa changed` run, then the coordinator reproduced it on main.

**Evidence**: `test_blocking_handler_evasion.py::TestEveryHandlerIsClassified` failed on main
from merge 506fd3f5e (Plan 00479 Phase 4) until 1c4f8e25f. The new PreToolUse handler was
never triaged for command-respelling evasion. This is N278 and N297 again: a merge that adds a
handler reached main without a green targeted run on the merged head.

**Status**: ✅ Fixed (1c4f8e25f; classified as not command-anchored, verified that the handler
never reads `tool_input`). The coordinator then ran `llm_qa changed --range 4440d58cf..HEAD`
over everything merged since. Result: 36/37 checks green, 9867 tests passed, 0 failed. The
one red check is the 15 core files `changed_tests` calls too broad to map (left to the release
gate by design). Nothing else broke. The lasting remedy (a merge that adds a handler cannot land without a
green run) is Plan 00475 Task 4.2, which waits on the owner.

### N304 — `guard_config_commit_gate` compares pathspecs to the config path as root-relative text

**Source**: N299 agent.

**Evidence**: `_pathspec_covers` compares each pathspec to `.claude/hooks-daemon.yaml` as text from
the repository root, so `cd .claude && git commit -m x hooks-daemon.yaml` is not seen as covering
the config, and the gate reads no config change. This is an existing miss, not something N299 caused.

**Status**: ✅ Fixed on worktree-n304-n305-gate-dirs. `recorded_config_source` resolves each
pathspec against every directory its commit may run in (`run_directories`, as N299 did for the other
gates), handling `./`, `..` and `:/` / `:(top)`.

### N305 — `staged_lint_gate._is_foreign_repo` ignores the command's own `cd` / `-C`

**Source**: N299 agent.

**Evidence**: the stand-down looks at the hook's working directory only. A `cd other-repo && git commit` from this checkout is linted as this repository's commit. N300 fixed the same gap in
`remote_docs_commit_gate`.

**Status**: ✅ Fixed on worktree-n304-n305-gate-dirs. The N300 post-move check moved to the shared
`git_facts.commit_runs_in_foreign_repo`, which `staged_lint_gate`, `remote_docs_commit_gate`,
`plan_qa_commit_gate` and `docs_qa_commit_gate` all call (all four gates share the check; the
local hook-cwd-only copies are deleted).

### N306 — the commit-move reader records both directories of `cd a || cd b`

**Source**: N299 review
([subagent-reports/261002-n299-review-opus.md](subagent-reports/261002-n299-review-opus.md)).

**Evidence**: with `cd a || cd b && git commit …`, only one `cd` runs, but the reading records
both as moves taken. This was already wrong on main. N299 round 2 handles it by treating any
uncertain move as unknown and judging both directories.

**Status**: ✅ Fixed (merge 530ffc83d). Every directory
any `cd` in the chain may land in is judged (`landing_directories`), and the hook directory as well. The
price is a fail-closed false positive the shell would not make: `cd x || cd sub; git commit f.txt`
also judges `sub/f.txt` when `cd x` succeeds. N299 round 2 did NOT close it. The probe row `cd sub || cd x; git commit -m x f.txt`, with the term in `sub/f.txt`, still records the term on both main and 37b9a8020.
The uncertain-move union judges the hook directory and the LAST recorded move (`x`), but not
every candidate directory (`sub`). Remedy: judge every directory any `cd` in the chain could
land in.

### N389 — the development host's real name is in tracked plan files

**Source**: the coordinator, 2026-10-09, while implementing N388. The N388 entry, as first committed in 3d1fa0ad6,
used the development host's real name as its example. The project rule is that no real hostname goes in a public
place.

**Evidence**: `git grep` over the tree found five tracked occurrences in four files. Three are now replaced:

- the N388 example, now `build-box`;
- `Completed/00413-niggles-ledger-thirteen/NIGGLES.md`;
- `00470-persistent-session-optimisation/subagent-reports/260930-p470-cron-hosts-sonnet-5-5.md`.

Two remain, in `Completed/00413-niggles-ledger-thirteen/JOURNAL/00413-Journal-26-09-15.md`. Journal entries are not
hand-edited (R-JOURNAL-HAND-WRITTEN-ENTRY). The name also stays in published history, which only a rewrite the owner
runs could remove. Nothing stops it recurring: the secret word list is the mechanism for that, and only a human edits
it.

**Status**: ⬜ Open, for the owner. To decide: whether the two journal lines may be edited in place, whether to add
the host name to the secret word list, and whether history matters for this name.

### N388 — the host segment does not show the session's role override

**Source**: owner request, 2026-10-09. When a session exports `HOOKS_DAEMON_HOSTNAME`, the status bar should read
`<role>@<host>`. A role over 15 characters shows its first 10 followed by `...`; for example
`github-softwaredev-lifecycle-unattended` on `build-box` shows `github-sof...@build-box`.

**Evidence**: before the fix, `handlers/status_line/host_hostname.py` rendered only `@<host>` (with `@~` when the host name is
inferred). The session's effective hostname reaches the daemon on the payload, under
`HookInputField.SESSION_HOSTNAME`. `init.sh` (around lines 3326-3333) stamps the first non-empty of
`HOOKS_DAEMON_HOSTNAME` and `CCY_HOST_HOSTNAME`, so the stamp alone cannot tell a role from the host's own name.

**Status**: ✅ Fixed on main, as designed below. The tests were written red first (11 new cases, including a role of
exactly 15 characters, the stamp winning over the environment, and the role being read on every render while the host
stays cached). Release note 010. Design:

- The role is the stamped value, falling back to `cron_hosts.hostname_override(os.environ)`, and is shown only when it
  differs from `resolve_host_name().name`. When nothing is overridden, the stamp is `CCY_HOST_HOSTNAME`, which equals
  the host, so no role shows.
- Never fall back to `socket.gethostname()`, so a container id is never rendered as a role.
- Rendering: `f"| {cyan}{role}{_ICON}{marker}{host}{reset}"`, with the role truncated to 10 characters plus `...` when
  it is over 15.
- Update `explain_segment`.
- Tests go in `tests/unit/handlers/status_line/test_host_hostname.py`, with these cases: no role, a short role, a
  long role, a role equal to the host, and the inferred marker with a role.

### N387 — the inline-suppression detector judged gitignored third-party code

**Source**: the coordinator, 2026-10-09. The range QA over the Plan 00484 batch 3.1b merge (1d0037601) reported 87
violations on main that the branch's own run never saw.

**Evidence**: every one was in `.claude/ccy/plugins/marketplaces/`, a gitignored plugin cache that git does not
track. `scripts/qa/check_inline_suppressions.py` skipped a hand-written list of directories rather than asking git
what it ignores. A fresh worktree has no such cache, so the branch scored 0. Same shape as N380 and N382: a whole-tree
check that a branch run cannot fail.

**Status**: ✅ Fixed on main. The detector drops any file `utils/git_file_states.scan_git_file_states` reports as
ignored, and it fails closed: when git cannot answer, nothing is dropped. Tests with a temporary repository were
written red first. On main: 0 violations in 113 suppressions.

### N386 — the self-install rule is copied four times outside its one definition

**Source**: the owner, 2026-10-09, on N384's first fix, which hand-rolled a fifth copy: "it should be a single source of
truth that's simple and proven already". The canonical rule is `daemon/install_layout.is_self_install_mode(project_path)`
(Plan 00457): standard-library only, so it can be loaded without the package. `ProjectContext` and `daemon/paths.py`
already delegate to it, and N384 now does too.

**Evidence**: seven other places re-derive the same decision from `src/claude_code_hooks_daemon`, and they have
drifted. The four Python sites split three `.exists()` to one `.is_dir()`:

- `daemon/cli.py:2645` (`.exists()`) re-implements `install_layout.get_untracked_dir()` whole.
- `install/client_validator.py:240` (`.exists()`) refuses a client install into the daemon repository.
- `utils/ccy_supervisor.py:45,136` (`_SELF_INSTALL_MARKER_PARTS`, `.exists()`).
- `scripts/debug_info.py:275` (`.is_dir()`) also re-implements `get_untracked_dir()`.

Three shell scripts test `[ -d src/claude_code_hooks_daemon ]` themselves:

- `scripts/setup_worktree.sh:184`.
- `scripts/install/mode_guard.sh:66`, a stricter variant.
- `scripts/health_check.sh:169`, which also re-checks the config-driven flag.

`daemon/validation.py:105-125` decides "is this the daemon repository" from `pyproject.toml`, a different marker. It is
a related question, and the remedy should say whether it merges into the one rule.

**Status**: ⬜ Open. Remedy:

- Each site calls `install_layout.is_self_install_mode` or `get_untracked_dir`. For a script that must run without the
  package, load `install_layout.py` by path, the way `daemon/signal_standalone.py` does.
- The shell scripts share one shell function for the test (the shell has no access to the Python one), kept in step with
  `install_layout.py` by a parity test.
- Add a QA detector, covering Python AND shell, so that no file except those two definitions tests for that marker to
  decide the install mode. Building a path in order to scan the source tree is not a decision, and stays allowed.
  Fact-check: `subagent-reports/261009-fact-check-n386-sonnet.md`.

### N385 — careless spellings the raw-text guards allow on main

**Source**: the Plan 00483 batch (c) review, round 1 (2026-10-09). Every probe called `matches()` directly on main;
the evidence is in `untracked/scratch/batchc-review/`. None of these came from batch (c), and each is allowed on main.

**Evidence**, by guard:

- **curl_pipe_shell**:
  - `sh -c "$(curl …)"`, which is Homebrew's documented install form and the most important item here;
  - `bash <(curl …)`;
  - `curl url -o x.sh && bash x.sh`;
  - `| env python3`;
  - `| sudo -u bob python3`;
  - `| node`.
- **worktree_file_copy**:
  - `cp -r <wt>/src .` and `rsync -a <wt>/ ./`, a whole-tree copy into the main checkout;
  - `cd /workspace; cp -r <wt>/src .` and `(cp …)`;
  - copies behind a wrapper: `command cp`, `nice cp` and `xargs cp`;
  - `cp -t src/ <wt>/…`;
  - `find -exec cp`.
- **root_recursion_guard**:
  - `bash -c 'grep -r x /'` and `time grep -r x /`;
  - `sudo find / …`;
  - `grep -rm1 x /`, where the clustered option hides the root;
  - `du -sh /` and `ls -R /`;
  - `rg x /home/user`.

Each is a spelling a careless agent writes, so all are in scope under the 00483 threat model. Out of scope (hostile, by the reviewer's call, which the coordinator accepts): a local program whose only job is to run stdin, such as `python3 -c 'exec(sys.stdin.read())'`.

**Status**: ⬜ Open. Remedy: one branch per guard, each shape a red test first and a must-deny gate row. The shared wrapper and `-c`-body readers that batch (b) and (c) reuse should cover most of the wrapper cases.

### N384 — `/hooks-daemon optimise` recommends the `daemon_stats` health line to every project

**Source**: the owner, 2026-10-09: "daemon stats is only useful in this repo, normal projects should not have it
enabled".

**Evidence**: `DaemonStatsHandler` (`handlers/status_line/daemon_stats.py`) did not override `get_relevance()`, so it
inherited `Relevance.always()`. The optimise review recommends enabling every relevant handler whatever its default,
so it told every client project to turn on a daemon developer's diagnostic (uptime, memory, log level, error count).
`default_enabled = False` kept it off at install, but the review then overrode that.

**Status**: ✅ Fixed on main. `get_relevance()` is applicable only in a self-install checkout, decided by the one
rule `daemon/install_layout.is_self_install_mode` (the first fix hand-rolled its own marker, which is N386); elsewhere the review lists it as "not applicable here". The
tests were written red first in `tests/unit/handlers/status_line/test_daemon_stats.py`. The optimise doc names it
among the non-universal handlers, and release note 008 tells clients they can switch it off.

### N383 — a quoted git global-option value with a space hides a destructive subcommand

**Source**: the Plan 00483 batch (b) review round 2 (2026-10-09, merged at fe54af5e6).

**Evidence**: the review probed these shapes on main and on the batch (b) tip, and every one was allowed:

- `git -C 'my dir' reset --hard`, also with `"my dir"` and `my\ dir`;
- the same with `stash`, `clean -fd` and `checkout -- f`;
- `git -c 'user.name=A B' reset --hard`.

The batch (b) round-1 tip denied them only by accident. A directory with a space is an ordinary careless spelling, so the shape is in scope under the 00483 threat model. The probe is `untracked/scratch/00483-review-batch-b-probe4.py` (its output is `00483-r2-probe4-main.txt`).

**Status**: ⬜ Open. Remedy: the shared `_GIT_GLOBAL_OPTION` (`utils/command_evasion.py:62`, behind `GIT_INVOCATION`, which both destructive_git and git_stash use) accepts a quoted or escaped option value for `-C`/`-c`/`--git-dir`/`--work-tree`, and these shapes are added to the must-deny tests. Also from that review, as NITs: the handler guidance omits `-e` from the data-valued options, and `_git_grep_pattern_spans` duplicates the new reader.

### N382 — `changed --range` does not select tests that discover handlers by scanning the package

**Source**: the coordinator, 2026-10-09. The Plan 00484 batch 3.1a agent reported a failing test that also failed on
main.

**Evidence**: `tests/integration/test_bash_write_blindness_coverage.py::TestEveryKeyedHandlerHasAVerdict` failed on
main after the 00499 Phase 1b merge (64823600a): `WriteProtectedPathsHandler` keys on Write/Edit and had no recorded
verdict. `llm_qa.py changed --range 0ef4ce3942a9..HEAD --allow-unmapped` reported 38/38 green over that merge, so it
never selected the test. The test finds its handlers with `pkgutil` and a source scan, not by importing the changed
module, so an import-based selector cannot reach it. This is the same shape as N380: a whole-repo property test that
lives far from the module that breaks it.

**Status**: 🔄 The regression is fixed on main (a PARTIAL verdict row, with its reason). Still open: the selector
should always run the tests that enumerate every handler whenever any file under `handlers/` changes. Two walk the
package with `pkgutil.walk_packages` (blindness coverage, guidance coverage), and template consistency enumerates
through `HandlerRegistry.discover()`. The selector's map sends `handlers/pre_tool_use/*.py` only to
`test_ordinary_command_regression_gate.py`. A pinned list in `scripts/qa/` is one remedy, with a test that each listed
file really enumerates the handlers. Fact-check: `subagent-reports/261009-fact-check-n382-sonnet.md`.

### N381 — `test_subagent_full_qa_blocker` fails under the pytest a fresh venv installs

**Source**: the Plan 00484 batch 3.1a review (2026-10-09,
`subagent-reports/261009-00484-3.1a-review-r1-opus.md` in Plan 00484 once committed).

**Evidence**: the file passes on main with the shared venv. In a worktree whose venv was built fresh, it fails
because the full-QA blocker does not recognise a newer pytest's options. So the blocker's table of pytest options
is pinned to one pytest version, while the venv resolves whatever version is current.

**Status**: ⬜ Open. Remedy: find the options the newer pytest added, and either pin pytest in `uv.lock` /
`pyproject.toml` or make the blocker treat an unknown option conservatively. Add a test run against the lock's pytest
version.

### N380 — agent branches pass their targeted tests and break the cross-cutting ones

**Source**: the coordinator, 2026-10-09. After N379, `llm_qa.py changed --range 85c4c73b1..HEAD` was run over every
merge since the last green gate.

**Evidence**: 6 tests fail on main that no agent ran:

- **00499 Phase 1:** the priority-band check, the default-enabled template consistency check (x2), and registry
  option injection for `write_protected_paths`.
- **00470 Task 6.4:** the `HookInputField` single-source check, and the event-socket enrichment "left untouched" test.

Each test guards a property that every handler or every payload read must satisfy. None of them lives near the
changed module, so a targeted run by name or import never selects them. Two more points:

- `changed` with no `--range` on main refuses to run, because HEAD is the base itself
  (`scripts/qa/run_changed_tests.py:1031-1038`). The advice "run `changed` on the merged head" therefore checks
  nothing on main.
- Agents CAN run `llm_qa.py changed`. R-SUBAGENT-FULL-QA blocks only `all` and `tests`
  (`.claude/hooks-daemon.yaml:524-528`). The coordinator had told every agent not to run `llm_qa.py` at all, to keep
  them off the host-wide QA lock while the full gate ran. That is why no branch carried a green `changed` record, and
  `changed` would have run these whole-repo checks.

**Status**: 🔄 Fixing. The six regressions are on a worktree branch, after a fact-check refuted two of this entry's
first-draft claims. The remedies:

1. Done in 8c9ac4cf4: `merge_qa_advisor` prints the exact `--range <pre-merge head>..HEAD` command.
2. Agents run `llm_qa.py changed` on their own branch before handing off, except while the coordinator's full gate
   holds the lock.
3. The coordinator runs `changed --range <pre-merge>..HEAD` after every merge onto main.

### N379 — a branch merged after a green gate that never saw it

**Source**: the coordinator, 2026-10-09. The B4 full gate ran on main at 85c4c73b1. The N359 and 00499 branches
were merged after it went green (7aa463588, 8887b2435). Their agents had run only targeted tests, so the
whole-repo checkers never saw their code before the merges.

**Evidence**: `llm_qa.py changed` after the merges reported three new failures:

- `error_hiding`: two `return-none-on-error` findings in `utils/plan_fact_check.py` `_take`, from N359.
- `security`: bandit B105, from 00499 (`core/utils.py`, `token == "--"`).
- `generated_doc_drift`: 416 lines in `.claude/HOOKS-DAEMON.md`, a stale copy committed on the 00499 branch.

`merge_qa_advisor` did not fire on either merge. The gate's result was green, but it described a different tree.
The advisor was silent because it matched only `worktree-*` branches (`WORK_BRANCH_PREFIX` in
`branch_count_advisor`). An `isolation: worktree` agent dispatch names its branch `agent-<hex>-<hex>`, so every
agent branch was merged unadvised, and `branch_count_advisor` left agent branches out of the WIP count too.

**Status**: ✅ Fixed. The failures were fixed forward in 06ab3658e. Both handlers now take their branch shapes from
`git_repo.WORK_BRANCH_PREFIXES` (`worktree-`, `agent-`), with tests through each handler and release-note callout
004\. The process remedy is the coordinator's: run the full gate on a tree that holds the branches to be merged
(merge them into a candidate first), or follow every merge onto main with `llm_qa.py changed` before calling it
done.

### N378 — the `[awaiting-human]` marker is one project-wide file, cleared by any session's prompt

**Source**: the Opus session-modes design review for Plan 00501 (2026-10-08,
`untracked/agent-reports/261008-session-modes-design-opus.md`, findings F1–F3).

**Evidence**: the marker is `untracked/human-input-blockage-marker.json` (`utils/blockage_marker.py:41`), one file
for the project, so whichever session writes last wins. The suppressor clears it on any prompt that is not a
`[tick:...]` cron tick (`classify_tick`), so the ccy supervisor's own typed `continue` or `/goal` lines (which start
with `🤖 [ccy-supervisor`) count as the owner returning. The supervisor never reads the marker, and the existing
`utils/human_presence.py` check is not used here. All three fail open: ticks are delivered when they need not be.

**Status**: ⬜ Open, owner ruling 2026-10-08: fine to leave, because session modes (Plan 00501) may replace the
marker with a per-session mode. Close it with 00501, or fix it alone if 00501 keeps the marker.

### N377 — synthetic sessions still read the account's live usage in three more places

**Source**: the v3.69.0 Step 8 gate. The account went over this host's usage ceiling mid-gate, and every synthetic
session routed through the real chain was paused. Fixed for the playbook harness, `test_tool_use_error_recovery`,
`test_full_qa_gate_is_never_deadlocked` and the dangerous-invocation corpus check by
`utils/usage_pause.synthetic_session_exemption` (c2195729b).

**Evidence**, still open:

- `hooks-daemon probe` with a fresh session id is denied by `R-USAGE-PAUSE-TOOL` while the account is over the
  ceiling (seen in the 3.69.0 manual test #353, which had to probe as the owner-overridden session).
- Pause records for the synthetic ids `smoke-test-probe` and `socket-stdin-*` were left in
  `untracked/context-sidecar/` during the gate. Their checks passed, but they read live usage and can fail the same
  way.

**More evidence**: the B4 merge gate (b3ee935aa) failed on exactly these sites:
`test_stop_hook_hard_block::test_stop_hook_exits_2_on_block` and
`test_forwarder_socket_stdin::test_stop_forwarder_exits_2_on_block_with_socket_stdin`, on both interpreters (the daemon
answered `{}` instead of the Stop block, because the probe session was paused).

**Status**: ✅ Fixed at the source rather than per site. `usage_pause_gate.try_start_pause` now never pauses synthetic
traffic (`synthetic_traffic.is_synthetic_event`: the `synthetic_source` marker, or a known synthetic session shape).
That covers `hooks-daemon probe` (`manual-probe`), the smoke test and every marked test probe in one place. A real
Claude Code payload carries no marker and a UUID session id, so it is still paused. The per-site
`synthetic_session_exemption` wrappers stay: they also clear a pause record left from before this fix.

### N375 — the hook contract is audited at Claude Code 2.1.272 and the upstream hooks doc has changed since

**Source**: v3.69.0 release Step 1c. `bin/hooks-daemon contract-status` returned CHANGED: recorded sha256 `0dc5622c…`
(322902 bytes, audited v2.1.272), upstream `403645d3…` (250548 bytes). The release host ran 2.1.293.

**Evidence**: `tests/integration/test_claude_code_version_record.py::TestAgreesWithContractMeta` requires the newest
recorded `claude_code_version` to equal `META.json`'s `last_audited_claude_code_version`, so v3.69.0 is recorded as
`unknown` with `reviewed_through: 2.1.293`, as v3.68.0 was. The changelog reviews for 2.1.272 to 2.1.293 found nothing
that changes hook payloads or output, but nobody has re-read the hooks doc itself against the vendored per-event JSON.

**Status**: Open. Follow `docs/guides/HOOK-CONTRACT-REFRESH.md` from "Manual steps for a CHANGED verdict" (RAW text
only), including the input side, then record the audited version in `claude-code-versions.yaml`.

### N374 — v3.69.0 release code review: non-blocking findings to work through

**Source**: the v3.69.0 release code review gate (three reviewers over `git diff v3.68.0..HEAD -- src/`):
[pre-tool-use](subagent-reports/261007-v369-review-pre-tool-use-opus.md),
[core/daemon/handlers](subagent-reports/261007-v369-review-core-daemon-handlers-opus.md),
[utils/install/rest](subagent-reports/261007-v369-review-utils-install-rest-opus.md). Each report gives file:line,
evidence and a fix; several have probe scripts under `untracked/scratch/review-v369/`, `untracked/scratch/rev/` and
`untracked/scratch/review-rest/`, which are not kept across a container reset.

**Evidence** (all judged non-blocking for the release; the most security-relevant first):

01. `rg -r X needle` is parsed as searching root `needle`, not `.`: `-r`/`--replace` takes a value the recursive
    search parser does not consume, so protected files under `.` are missed (`utils/recursive_search.py:62-69, 189-201`).
02. A glob that reaches a protected file is allowed silently while the protected-file index is still building after a
    restart; the docs promise an advisory (`secret_file_guard.py:1394`, `quarantine_artefact_read_guard.py:337`).
03. `git push --mirror` and `git push --prune` delete remote refs but miss the human-only remote-delete rule
    (`destructive_git.py:113`).
04. `host_command_guard` misses `docker run -itv /:/host` and `docker compose run -v /:/h`
    (`host_command_guard.py:178-245`); it denies `gh auth token > /dev/null` and treats `pypi.python.org` as non-PyPI
    (`:294-312`, `:51`).
05. Plan fact-check delivery has no lock: two concurrent events can deliver one check twice, and an unreadable record
    can raise `FileNotFoundError`; it goes to whichever session or sub-agent calls next
    (`utils/plan_fact_check.py:250-259, 349-376`, `plan_fact_check_feed.py:97-124`).
06. `daemon_sync_after_merge.py:197-198` takes the LAST effective cwd as the merge directory.
07. `check-effective-handlers` exits 1 on malformed YAML, which `scripts/upgrade.sh` reads as "handlers change
    state"; its exit codes are untested (`cli.py:4263-4297`).
08. The upgrade rewrites a `CCY_CLAUDE_WRAPPER` line pointing at a custom directory, possibly to a missing file
    (`install/ccy_supervisor.py:244-258`).
09. `find_under` runs `git check-ignore` once per ignored protected file in one PreToolUse call
    (`utils/protected_file_index.py:136-142, 187-200`); its `index_for` docstring says 600 s where the code retries
    at 30 s (`:331-333`).
10. The open-issue listing stops at 100 without saying so (`utils/github_issue_validity.py:75, 486-509`).
11. Smaller: autonomy re-detects the container runtime per event (`utils/autonomy.py:57-59`); a hard-coded
    `"completed"` and duplicated pattern compilation in `cli.py:3925, 7751-7756`; the fallback response schema would
    reject a top-level `decision` (`core/response_schemas.py:451`); an unreadable doc is logged only at DEBUG
    (`docs_qa/checks/unlisted_fake_value.py:123`); repeated literals in `destructive_git.py:502-536`;
    `sensitive_content` re-reads `.claude/fake-values.yaml` on every matching write.

**Status**: Defects ✅ fixed before the v3.69.0 tag (RELEASING.md: a release carries no known defect), merged at
9028bc3a1, one commit each, test-first ([report](subagent-reports/261008-v369-review-defect-fixes-sonnet.md)): items 1
to 8, the docstring and 100-issue halves of 9 and 10, the unreadable-doc logging in 11, the destructive_git named
constants, `bash_safe_mode` gaining `validate_options` (the N373 class), and two items from the Step 1c Claude Code
review: Grep targets named in `file_path` are now judged like `path` (a guard bypass since Claude Code 2.1.292), and
report filenames stay under the filename limit with 256-character agent names. Still open, non-defects (cost and
refactoring): the per-file `git check-ignore` calls in `find_under`, autonomy re-detecting the runtime per event, the
hard-coded `"completed"` and duplicated pattern compilation in `cli.py`, the latent fallback-schema trap in
`core/response_schemas.py:451`, and `sensitive_content` re-reading `.claude/fake-values.yaml`. Known residual of item 2:
with a cold index, a glob carrying name text (`cat report-*.txt`) still gets no advisory, to keep
`test_an_unrelated_star_bearing_token_stays_allowed` intact.

### N376 — four tests fail under the full gate's concurrent load and pass alone

**Source**: the v3.69.0 release gates.

**Evidence**: each failed in one gate run and passed repeatedly alone:
`test_safety_handlers_hostile_input_performance.py::TestCombinatorialSmallInputShapesStayLinear` (blaming a different
handler each time, 2 of 5 alone-runs failing before the fix), `tests/unit/core/test_chain.py::...::test_deadline_exceeded_denies_when_a_slow_handler_exhausts_the_whole_chain`,
and `tests/unit/supervise/test_abandoned_input_flush.py::TestSuperviseEndToEndAbandonedFlush::test_abandoned_message_is_submitted_then_compacted`.
The scaling sweep now takes the minimum of CPU-time samples and the chain deadline tests use a manual clock (merge
9a9d5e6f6, thresholds unchanged), but the sweep still failed once more under load (`host-command-guard`,
`deep_bash_c_nesting`, 5/5 alone): CPU time per operation inflates on shared cores while three legs run at once.

**More evidence** (the v3.69.0 Step 8 gate, host load about 20; each passed on `--resume` or alone):
`tests/unit/core/test_router.py::TestEventRouter::test_route_passes_deadline_seconds_through_to_the_chain` (a
2-second wall-clock poll for a straggler thread; it needs the manual clock `test_chain` now uses), the `[nesting]` sweep
(`UpgradeApprovalGuardHandler` 25x for 8x input in-suite, 3 of 3 passes alone on py3.12), the `[.md]` deep-path
sweep (`RemoteDocsProvenanceHandler` 73x for 8x) and `test_client_owned_asset_lint`'s 120-second shellcheck timeout.

**Status**: Open. Run the performance sweeps outside the concurrent phase (their own serial shard or marker), and make
the supervisor end-to-end test wait on its event rather than a fixed time. Never loosen a threshold.

### N373 — an invalid `stand_in_delay_hours` silently unregisters the whole Stop enforcement handler

**Source**: the v3.69.0 release code review gate
([report](subagent-reports/261007-v369-review-core-daemon-handlers-opus.md)), graded BLOCKER.

**Evidence**: the option setter in `handlers/stop/auto_continue_stop.py:653-667` raises on 24, 0 or `"3"`, and
`handlers/registry.py:350-366, 948-949` catches that around the whole handler, so `AutoContinueStopHandler` (the
`STOPPING BECAUSE:` enforcement and the awaiting-human marker) is dropped with only a WARNING log. Nothing reaches
`option_failures`, so the session-start alert stays silent.

**Status**: ✅ Fixed before the v3.69.0 release (commit f4d3c34a6, merged to main). `AutoContinueStopHandler` gained
a `validate_options` like `IdleHousekeepingAdvisoryHandler`'s, so the registry withholds a bad value, reports it on
`option_failures` and keeps the handler on its 3-hour default. Tests in
`tests/unit/handlers/test_registry_option_validation.py` register through `register_all` with 24, 0, -1, `"3"`,
`True` and NaN. Same class, not fixed: `bash_safe_mode`'s `mode` and `exempt_patterns` setters raise and drop the
handler. Those setters are unchanged since v3.68.0, and the docstrings describe the rejection at load as intended; whether it should
report through `option_failures` instead is open.

### N372 — the daemon-docs guard warns on the project's own `CLAUDE/` when the repo folder ends in `hooks-daemon`

**Found**: by the owner's desktop session, 2026-10-07. Reading `CLAUDE/Plan/README.md` in a clone named
`claude-code-hooks-daemon/` drew the warning that it was "the hooks-daemon's internal docs copy".
`daemon_docs_guard.py:20` matches any path containing `hooks-daemon/CLAUDE/`, so every project folder whose name ends
in `hooks-daemon` trips it. It should match only the `.claude/hooks-daemon/CLAUDE/` segment. Same class as the loose
path matching fixed in Plan 00458.

**Status**: ✅ Fixed on this branch (merge pending). The guard now uses `matches_path_segment` from
`utils/path_segments.py` with `.claude/hooks-daemon/CLAUDE/`. Tests in
`tests/unit/handlers/pre_tool_use/test_daemon_docs_guard.py`:
`test_not_matches_project_folder_ending_in_hooks_daemon` (five parametrised paths) and
`test_matches_daemon_install_inside_project_named_hooks_daemon`.

### N371 — the plan counter is per clone, so a second clone of this repository would reuse plan numbers

**Found**: by the owner's desktop session, 2026-10-07 (Plan 00498 desktop check). In the desktop clone
`git config --local hooksdaemon.latestPlanNumber` read 489, while plan folders up to 00499 exist on main and the
container clone reads 499. The counter lives in each clone's local git config. `mkplan.bash` already scans the
plan folders (including `Completed/`) and dies when they run ahead of the counter (lines 764-766), so with
00490–00499 pulled it refuses rather than reusing a number. It reuses one only when the clone's folders are stale
too. The daemon's `counter + 1` path (`plan_numbering.py:180`) does not look at the disk. The guidance says "the
daemon keeps it correct across branches"; nothing says across clones. Remedy: `mkplan.bash` advances the counter to
the highest plan number on disk instead of dying on that drift, and the daemon's path checks the disk the same way.

**Status**: ⬜ Open.

### N370 — the sed guard denies a `git -C <dir> commit -m` message that mentions an in-place sed edit

**Found**: by the coordinator, 2026-10-06. `git -C /workspace add <dir> && git -C /workspace commit -q -m '… sed -i …'`
was denied as `R-SED-FILE-MODIFICATION`. The guidance exempts "a `git commit` message mentioning sed (sed must follow
`git commit` with no command separator between)". Here sed did follow the commit with no separator, but the commit
was spelled `git -C <dir> commit`, so the exemption appears to match only the literal `git commit` adjacency. The
same message without the sed word was allowed.

**Fix**: recognise the commit subcommand after git's global options (`-C <dir>`, `-c k=v`, `--git-dir`,
`--work-tree`), the way the other git-aware guards parse it. Test both spellings.

**Status**: ⬜ Open.

### N369 — a forwarder integration test fails inside every worktree and passes on main

**Found**: by the coordinator, 2026-10-06, in Plan 00495 Task 2.7's branch QA.
`tests/integration/test_forwarder_socket_stdin.py::test_stop_forwarder_exits_2_on_block_with_socket_stdin` failed
with a 15 s "Daemon startup timeout" in the worktree, failed the same way on the branch's parent commit, and passed on
main (61 of 61 for the forwarder and status-line files after the merge). Each worktree carries an untracked
`.claude/hooks-daemon.env` copied from main, with `HOOKS_DAEMON_ROOT_DIR="/workspace"`, so a test run from a worktree
resolves main's root rather than its own.

**Fix**: find where the worktree gets that file. Either point its `HOOKS_DAEMON_ROOT_DIR` at the worktree, or make the
test hermetic against an inherited root. Then confirm the test passes inside a worktree.

**Status**: ⬜ Open.

### N368 — the plan fact-checker marked claims unverifiable while the reference clone that settles them was on disk

**Found**: by the owner, 2026-10-06. A fact-check of Plan 00487's live-test checklist reported 7 claims about ccy and
fedora-desktop as UNVERIFIABLE-HERE, saying there was no fedora-desktop clone under `untracked/`. The governed
reference clone was at `untracked/repos/fedora-desktop` all along. A re-check against it verified all 7 and REFUTED 2
more: F1 was already fixed on F44 in ccy 3.82.1, so the checklist was telling the owner to use a superseded branch.

**Fix**: the `plan-fact-checker` agent definition should list the governed reference clones (from the
`reference_repos` config) and require a claim about an external repository to be checked there before it is
called unverifiable. The coordinator should name the clone in the dispatch too.

**Status**: ✅ Fixed on this branch (merge pending). `.claude/agents/plan-fact-checker.md` now names the governed
reference clones and requires a check there first. The coordinator naming the clone in the dispatch is still on the
coordinator.

### N367 — the coordinator's branch-QA venv recipe installs off-lock tool versions, so three tests fail falsely

**Found**: by the coordinator, 2026-10-06, in B2's uncapped test run (4 failed, 8469 passed). The recipe it uses to give
a worktree its own venv is `bin/hooks-daemon repair`, then `uv pip install -e ".[dev]"`. That second step resolves
the dev extras from `pyproject.toml`, not `uv.lock`, so the worktree venv got pytest 9.1.1 and ruff 0.16.10 while the
lock (and main's venv) pins pytest 9.0.3 and ruff 0.15.11. Three tests then failed for the toolchain, not the code:

- `test_client_owned_asset_lint.py::TestPythonAssetsAreCleanUnderRuffDefaults`: ruff 0.16 adds ISC004, SIM102 and
  SIM103 findings in `.claude/ccy/claude-supervise.py`.
- `test_subagent_full_qa_blocker.py::TestThePytestOptionGrammar`: pytest 9.1 adds `--max-warnings` and
  `--report-chars` (the same failure as N270).
- `test_corpus.py::TestRevalidateCorpus::test_a_steady_state_revalidation_logs_nothing`: `markdown_it` debug records
  are captured under the newer pytest.

All three passed (19 of 19) on main's lock-matched venv against B2's code. The fourth failure was a 120 s shellcheck
timeout under host load (N344's class).

**Fix**:

- Build branch-QA venvs from the lock (`uv sync --frozen --all-extras` into the resolved venv), never with
  `uv pip install -e`.
- Separately, the three tests will fail for everyone once the lock moves to pytest 9.1 and ruff 0.16. Fix the
  supervisor findings and add the two options before bumping the lock.

**Status**: ⬜ Open.

### N364 — a read-only `git config --get-regexp` naming `user.name` is judged as an identity write

**Found**: by the Plan 00487 host agent on 2026-10-06. `cd <clone> && git config --show-origin --get-regexp '^(commit\.gpgsign|…|user\.name|user\.email|…)$'; git log …` was denied as `R-SENSITIVE-SECRET-TERM` (a secret word
list entry matched elsewhere on the command line). `--get-regexp` only reads. The handler's own guidance says only
commands that WRITE metadata are candidates and reading is never blocked, and `git config user.name|user.email` is
listed as a surface only because it sets the author identity.

The read exemption is exact-token membership against `--grep --list -l --get` (`sensitive_content.py:164`, `:1294`),
and the whole `config` subcommand is a write surface (`_GIT_METADATA_WRITE_SUBCOMMANDS`), so `--get-regexp`,
`--get-all`, `--show-origin` and a bare `git config user.name` read are all judged as writes
([fact-check](subagent-reports/261006-n364-fact-check-sonnet.md)). A second shape points the same way: `cd <clone> && git switch -c fix/ccy-lifecycle-daemon-launcher origin/F44` was denied on the same entry, and the identical `git switch -c` with no `cd` in the command was allowed. So the term matched the `cd` path, not the branch name: once a metadata
surface is present, the whole command line is scanned, not the metadata value.

**Fix**: scan only the metadata value (the message, tag, branch name or identity value), never the rest of the command
line. Treat `git config` as an identity write only when it assigns a value (`git config [--scope] user.name <value>`, `--add`, `--replace-all`), never for `--get`, `--get-all`, `--get-regexp`, `--list`/`-l` or `--show-origin`
reads. Test both sides through the real handler.

**Status**: ⬜ Open.

### N366 — claiming an issue ADDS an assignee, so an issue can end up with two, and that state reads as OK

**Found**: owner ruling, 2026-10-06: "hooks daemon agents only ever SWITCH assignee — we don't want a single issue
with multiple assignees, or we're back to square one with it being ambiguous who can work on it."

In `src/claude_code_hooks_daemon/utils/github_issue_validity.py` (`AssigneeCheck.evaluate`):

- **The claim adds.** It is `gh issue edit N --add-assignee @me` (line 263). Two agents claiming the same unassigned
  issue close together both get added.
- **Several assignees read as OK.** Line 252 returns OK whenever the signed-in account is AMONG the assignees, so
  `[someone-else, me]` is accepted.

No open issue had two assignees when this was recorded, so the fix is prevention.

**Fix**:

- **The claim switches.** It sets the assignees to exactly the signed-in account (`--add-assignee @me` plus
  `--remove-assignee` for anyone listed). It then re-reads the issue, and succeeds only if the assignees are exactly
  `[me]`. In a race the last switch wins and the other claimant's verification fails, so it backs off.
- **Two or more assignees are BLOCKING (ambiguous)**, even when one of them is the signed-in account. The message
  asks a human to leave exactly one.
- **Unchanged:** an issue assigned only to someone else stays BLOCKING. An agent never switches an issue away from
  another assignee.

Test each case through `issue-validity` and the guard.

**Status**: Fixed on branch agent-a39b84caa49481833-8f3c52ec at 88f41369e.

### N365 — an `[awaiting-human]` token quoted inside a fenced block is read as the stop's own declaration

**Found**: by the coordinator, 2026-10-06. Its stop message gave the owner a fenced copy-paste block for ANOTHER
session, and that block contained the `[awaiting-human]` token. The coordinator's own `STOPPING BECAUSE:` line did not
declare it, and background QA was still running. The Stop hook nevertheless treated the stop as awaiting-human and
denied it until a stand-in cron was created. The token should count only where the stop declares it (immediately
after the `STOPPING BECAUSE:` prefix), never inside fenced or quoted text.

**Status**: ✅ Fixed on this branch (merge pending). `_declaring_lines` in `auto_continue_stop.py` drops fenced,
blockquoted and indented lines before the sentinel and the older phrasings are matched. Tests:
`TestOnlyTheStopsOwnDeclarationCounts::test_a_quoted_declaration_demands_no_stand_in` (six shapes),
`test_a_fence_before_the_real_declaration_does_not_hide_it`, `test_an_older_phrasing_in_the_stop_line_still_declares`
in `tests/unit/handlers/stop/test_auto_continue_stop_stand_in.py`.

### N363 — a pipe inside a `bash -c` string is blamed on `bash`, not on its real producer

**Found**: by the coordinator, twice on 2026-10-06.
`bash -c '… grep … | sort … | tail -n 2'` and `bash -c '… V=$(ls -d … | head -n 1) …'` were denied as
"R-PIPE-TO-TAIL/HEAD — bash unrecognized". `sort`, `grep` and `ls` are whitelisted producers. The handler's guidance
says every pipe is judged on its own producer, and that a pipe inside `$( )` belongs to the command inside it. The
`bash -c` string should be parsed the same way; instead the whole thing is judged as a pipe from `bash`.

**Status**: ⬜ Open.

### N362 — deleting a MERGED remote branch is denied; only an unmerged delete should be human-only

**Found**: owner ruling D11 of 2026-10-06
([OWNER-RULINGS-261006.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261006.md)), amending A6. Deleting a
branch whose tip is already contained in the default branch is lossless housekeeping, and any agent may do it.
`R-GIT-PUSH-DELETE-REMOTE` (`destructive_git`) denies every `git push --delete` and `git push <remote> :<name>`.

**Fix**: allow the delete when every named branch's remote tip is an ancestor of the remote default branch (after a
fetch); keep the deny, with the same message, otherwise. Tags are out of scope. Test both sides through the real chain.

**Status**: ✅ Fixed on branch `agent-a7777897724c1db4b-1ed0e9c0` (merge pending). `destructive_git` allows a
`git push <remote> --delete|-d <branch>` / `:<branch>` when `refs/remotes/<remote>/<branch>` is an ancestor of the
default branch (`git merge-base --is-ancestor`) and `git ls-remote <remote> refs/heads/<branch>` reports a tip equal
to it (a stale tracking ref, an absent remote branch, a failure or a timeout is denied with "run `git fetch` and
retry"; the handler never fetches); tags, the default branch, a missing ref,
a tag-named branch, substitutions and any git failure stay denied, and every ref in the command must pass. Tests in
`tests/unit/handlers/pre_tool_use/test_destructive_git_remote_delete_merged.py`:
`test_deleting_a_merged_remote_branch_is_allowed` (five spellings),
`test_deleting_an_unmerged_remote_branch_is_denied_and_says_so`, `test_a_missing_remote_tracking_ref_is_denied`,
`test_deleting_a_tag_stays_denied`, `test_a_branch_sharing_its_name_with_a_tag_is_denied`,
`test_the_default_branch_is_never_deletable`, `test_every_ref_must_be_merged`, `test_several_merged_refs_are_allowed`,
`test_a_merged_delete_cannot_carry_a_force_push_along`, `test_a_merged_delete_chained_with_an_unmerged_one_is_denied`,
`test_a_substitution_is_not_trusted`, `test_an_unknown_directory_is_denied`, `test_a_stale_tracking_ref_is_denied_and_says_to_fetch`,
`test_a_fetched_tracking_ref_that_is_now_unmerged_is_denied`, `test_a_branch_already_gone_from_the_remote_is_denied`,
`test_an_unreachable_remote_is_denied`,
`test_the_rule_documentation_describes_the_merged_exception`.

### N361 — the fake-values registry is not pre-filled, and nothing says its entries must look fake

**Found**: owner ruling C7 of 2026-10-06. `.claude/fake-values.yaml` (Plan 00492) lets a listed value pass
`sensitive_content`, and only an agent in this repository writes it. The owner's defence:

- one concerted brainstorm pre-fills it with fakes for every kind that docs might need;
- a big, clear header comment says any change must be a clear fake;
- values look visibly fake: long runs of a repeated letter, `fakefakefake`, and similar shapes that never occur in real
  life.

Worth weighing: a docs-QA or commit check that a new entry matches a "visibly fake" shape.

**Status**: ⬜ Open.

### N360 — an upgrade should keep running the opt-in handlers that were running before it

**Found**: owner ruling C6 of 2026-10-06, following Plan 00493 (archived). The upgrade should write `enabled: true` for
each opt-in handler that was running before, so the project's real configuration carries across upgrades. It should
then tell the agent what it did, why, and how to change it. Plan 00493's report found the losses but did not restore
them.

**Status**: ⬜ Open.

### N359 — the plan fact-check feed points at the wrong files, diffs whole folders, and can consume a check unseen

**Found**: by the coordinator in the Plan 00480 Task 4.4 live run, after the daemon restart that loaded N358
(merged `87c02719a`). Four owed checks arrived together on the next PostToolUse; then a deliberate false claim was added
to `CLAUDE/Plan/00480-plan-fact-checker-and-debounce/PLAN.md`.

**Four defects seen live**:

- **Worktree paths.** Two delivered instructions named a PLAN.md inside a sub-agent's worktree
  (`.claude/worktrees/agent-…/CLAUDE/Plan/00483-…/PLAN.md` and `…/00484-…/PLAN.md`), both worktrees already removed.
  A sub-agent's plan edit in its own worktree feeds the coordinator's debouncer under the worktree path.
- **Archived plans.** The 00493 instruction named `CLAUDE/Plan/00493-…/PLAN.md` after the plan had moved to
  `Completed/`.
- **First check diffs the whole folder.** A plan with no checked content yet is diffed against nothing, so the first
  instruction carries the whole plan folder: 290 KB for 00474 and 500 KB for 00483, NIGGLES and reports included.
  The first sighting should record a baseline and deliver nothing.
- **A delivery consumed unseen.** The check for the false claim fired at 09:22:29 (UTC, 2026-10-06): the diff file
  holds the claim and the plan was recorded as checked, but no "PLAN FACT-CHECK OWED" text reached the session on that
  tool call, while the earlier batch had. The cause is not established; the in-memory log no longer held that window.
  Because delivery advances the checked content before anything confirms the text arrived, a lost message loses the
  check for good.

**Remedies to weigh**: ignore (or map to the main root) edits under a worktree path; resolve the plan folder at
delivery time and drop records for archived plans; baseline on first sight; and only advance the checked content once
the delivery is known to have been emitted (or re-offer an undelivered check on the next event).

Also stale, found by the fact checker on the corrected plan: the template comments at `.claude/hooks-daemon.yaml.example`
(the `plan_fact_check_feed` block) and `src/claude_code_hooks_daemon/daemon/init_config.py` (the same handler) still
say delivery is not built.

**Fifth, seen later the same day: a correction loop.** Fixing a fact checker's finding in a plan is itself a plan edit,
so it owes another check, whose finding prompts another edit. On Plan 00480 this went edit, check, one-line
correction copied from the checker's own report, then a third check owed. The coordinator skipped the third and
recorded it here. A remedy to weigh: run one check per burst plus its corrections, for example by widening the
quiet period, or by not re-offering a check whose diff only restates the last report's findings.

**Status**: Fixed on branch agent-a2c1639ebf327c0d2-c58056dc (merge pending). Tests:
`TestWorktreePaths`, `TestFirstSight` and `TestDelivery::test_an_archived_plan_is_delivered_under_its_existing_path`,
`test_delivery_alone_does_not_advance_the_checked_content`,
`test_dispatching_the_fact_checker_with_the_diff_confirms_the_check` in
`tests/unit/handlers/post_tool_use/test_plan_fact_check_feed.py`; and `TestProcessQuietPlan::test_first_sight_records_a_baseline_and_owes_nothing`,
`TestDelivery::test_delivery_does_not_advance_checked_until_the_dispatch_is_seen`, `test_an_undelivered_check_is_re_offered_after_the_wait`,
`test_re_offer_stops_after_the_cap_without_losing_the_content`, `test_archived_plan_is_delivered_under_its_resolved_path`,
`test_a_vanished_plan_drops_the_record` and `TestCorrectionLoop` in `tests/unit/utils/test_plan_fact_check.py`.
Plan 00480 Task 4.4 can be re-run once merged.

### N358 — one pending fact-check record from the pre-delivery build stops every delivery

**Found**: by the coordinator, in `bin/hooks-daemon logs -l WARNING` after the daemon restart that loaded Plan 00480
Tasks 4.2–4.3 (merged `accde1c23`). This repository's dogfood config had `plan_fact_check_feed` enabled, and
`untracked/plan-fact-check/` held 14 `*.pending.json` records written by the earlier build, which stored no `files`.

**What happens**: `deliver_pending` reads the pending records in turn, and `read_pending` raises
`PlanFactCheckStateError: malformed pending state …: no files` on the first old one. The handler catches it, logs an
ERROR with a traceback ("owed fact-check unreadable; delete it to reset") and allows. The error ends the delivery
loop, so no record after it is ever delivered, and the same ERROR repeats on every PostToolUse until someone deletes
the file by hand. Release note 037 calls this "logged, never blocking", which is true but hides that delivery stops.
The branch agent also reported the handler as off in this repository's config; it was on.

**Why tests missed it**: the tests write pending records only in the new format.

**Remedy**: a record that cannot be read is discarded (renamed aside, or deleted) with one WARNING naming it, and the
loop goes on to the next record. Then re-enable the dogfood handler and run Task 4.4's live check. Meanwhile the dogfood
config has the handler off.

**Status**: ✅ Fixed (f0f3f05e5) — `deliver_pending` renames an unreadable pending record to `<name>.pending.json.unreadable` with one WARNING and carries on; dogfood handler re-enabled.

### N355 — the protected-file index never becomes available in the live daemon

**Source**: the coordinator, 2026-10-05, right after merge dc5c9263b of Plan 00483 Phase 2.

**Evidence**: more than 10 minutes after `bin/hooks-daemon restart`, every recursive search still drew the "index of protected files is not available yet" advisory from both guards, and the daemon log said nothing. Out of the daemon the same build worked. On `/workspace`, `git ls-files --others --ignored --exclude-standard` alone takes 3.4 s idle (more under hook load), against the 5 s `Timeout.GIT_CONTEXT` that `scan_git_file_states` inherited through `run_git`. A listing past the bound returns exit 124, the scan returns None, and `_build_and_remember` recorded the failure for `REFRESH_AFTER_SECONDS` (600 s) without logging; an exception in the thread went to stderr only.

**Impact**: high. Plan 00483 A2's recursive-search and glob checks were advisory-only for the daemon's whole life on any large tree.

**Status**: ✅ Fixed (this branch, commit recorded at merge). The scan takes a timeout and the index build passes `Timeout.INDEX_BUILD_GIT` (120 s); a failed listing or a raising build is logged with its reason; a failed build retries after `RETRY_AFTER_FAILURE_SECONDS` (30 s); the controller pre-warms each guard's index at startup (`prewarm_index`). Reproduced first by `TestTheBuildUnderTheDaemon` in `tests/unit/utils/test_protected_file_index.py`. The deleted variable-target containment pin is restored in `test_heredoc_grammar_chain.py`.

Second part: an index build started by one test leaked into later tests. Its thread ran `git` through `subprocess.run` while a later test had patched that with a `side_effect` list, so the thread consumed the effects and the test's own call raised `StopIteration` in fixture setup (the gate's `ls-star-py` row; order-dependent, passes alone). Fixed by an autouse fixture in `tests/conftest.py` that runs `reset_index_cache()` (waits for in-flight builds, clears the cache and `_failed_at`) after every test, and by moving the startup pre-warm out of `DaemonController.initialise()` into the serving path (`controller.prewarm_indexes()` in `cli.py`), so building a controller never starts git work. Pinned by `tests/unit/test_index_build_isolation.py` (red without the fixture).

Third part: with the bound raised the index still never built in the live daemon. On `/workspace` the `git ls-files --others --ignored --exclude-standard` listing is 554,332 paths (58 MB: virtualenvs and worktrees under the ignored `untracked/`); the daemon log showed "failed with exit 124 (124 = timed out after 120s)" and "could not be built ... retrying in 30s" on every attempt, and each attempt read and decoded tens of MB in a thread, which is the likely cause of a 30 s hook socket timeout right after a restart. The listing filtered by pathspec prints about 1,300 lines (72 KB). Fixed by `utils/protected_pathspecs.py` (`git_pathspecs`): the index build hands git each protected glob as a `:(glob)` pathspec through the new `pathspecs` parameter of `scan_git_file_states`, which narrows only the untracked-and-ignored listing (plus `**/pyvenv.cfg`, so the foreign-tree rule still drops virtualenv trees). The narrowing must be a SUPERSET of what `first_matching_glob` selects, so it answers `None` (list everything) for `[`, `\`, a leading `:`, a `**` that is not a whole segment, the vendor token, and any multi-segment pattern whose first segment can match a directory above the project root (the matcher also tries the absolute path). Pinned against real git by `tests/unit/utils/test_protected_pathspecs.py` and `TestBuildAsksGitOnlyForCandidates`. Measured against `/workspace` (default patterns): 554,347 lines / 57.8 MB in 5.5 s unfiltered, 1,300 lines / 72 KB in 7.7 to 8.7 s filtered (git still walks the tree and matches each entry; the saving is the transfer, decode and set-building in the daemon, not git's walk). Known gap, not closed: an ignored, untracked symlink whose own name matches no glob but whose target does is not listed (tracked symlinks are, as the tracked listing is whole). The SessionStart sweeps (`secret_file_hygiene_checker`, `gitignore_safety_checker`) make the same unnarrowed four listings through `scan_git_file_states_for_event`; they were left as they are.

### Owner ruling A4: R7 dispositions for N28, N75, N76, N229

The owner accepted the effort review's R7 keep/narrow/drop list (Plan 00483, `OWNER-RULINGS-261005.md`). Four items from the archived ledger 00466 are closed as follows; the 00466 index rows carry the matching status.

- **N76 — dismissed (no code).** A script that launches a shell to read a protected file is far from careless use, so it is out of the threat model.
- **N28 — deferred (no code).** Containment is not secret protection. The only reusable tracker is `simple_commands`/`_walk` in `utils/git_commit_parsing.py`, which gives a `cd` directory per simple command. `project_containment` takes its targets from three routes (the shared redirect scan, `_destination_targets` and the tool field) that do not carry a segment, so using the tracker means mapping each target back to its command: a new walker, not a few lines. `find_command_placements` named in the write-up exists only on the dropped 00464 branch.
- **N229 — narrowed, ebaa51151.** `_with_option_value_forms` in `utils/secret_file_matching.py` adds a leading-`@` form and a single-dash option's tail (`-fFILE`, `-e@FILE`) to the mention scan, about 12 lines. The wider remedy on the dropped 00421 branch is not carried. Five rows in `tests/fixtures/ordinary_command_corpus.yaml` (`a4-*`) pin that `@` and attached options naming no protected path stay allowed.
- **N75 — narrowed, ebaa51151.** `.pyw`, `.pm`, `.cjs`, `.mts`, `.tsx`, `.kt`, `.swift` and `.ps1` join `_SCRIPT_EXTENSIONS` in `secret_file_guard`, the one list the content route reads. The per-language call shapes, the span cap, the unknown-extension shell-text scan and the config-file shapes are dropped.

Release note 040 records the behaviour change. Targeted tests: 1371 passed.

### N357 — `simple_commands` inlined `eval`/`sh -c` with no depth cap, so nested evals cost quadratic time

**Source**: the coordinator, 2026-10-06, in the full post-merge run after the Plan 00483 A6 merge (745dc2d68).

**Evidence**: `tests/unit/handlers/test_safety_handlers_hostile_input_performance.py::TestCombinatorialSmallInputShapesStayLinear::test_bash_command[deep_eval_nesting]`
failed deterministically on main: "host-command-guard cost grew 26x for 8x input" (`"eval " * depth + "true"`, depths
5 and 40). `_walk` in `utils/git_commit_parsing.py` recursed into every evaluated string with no limit, and each level
re-lexes the whole remaining text. `host_command_guard`, new in the A6 merge, calls `simple_commands` on every Bash
command, which exposed it.

**Impact**: medium. A deeply nested `eval` chain made every Bash command through that guard cost quadratic time.

**Why A6's changed QA missed it**: `scripts/qa/changed_tests_map.yaml` has no rule mapping `handlers/pre_tool_use/*.py`
(or `utils/git_commit_parsing.py`) to the hostile-input performance test; its only rule for those paths names the
ordinary-command regression gate. That test finds handlers through the registry, so the name/import inference does not
reach it for a new handler file. Checked in the map and the test, not by replaying A6's run. Candidate remedy, not done
here: add a map rule for `handlers/pre_tool_use/*.py` naming the performance test.

**Status**: ✅ Fixed (commit 4b2235800). `_walk` takes a `depth` and inlines an evaluated string only while
`depth < MAX_EVAL_NESTING` (4, the nested-shell cap the performance test's shapes are built around); past it the
command stays one ordinary step and its body goes unjudged, per ruling A1. Pinned by `TestEvalNestingIsCapped` in
`tests/unit/utils/test_git_commit_parsing.py`.

### N356 — a grep regex inside a quoted `bash -c` string is read as a protected-path glob

**Source**: the coordinator, 2026-10-05, after the Plan 00483 Phase 2 merge (dc5c9263b).

**Evidence**: `bash -c 'set -o pipefail; … | grep -a -E "^(src|tests)/.*:[0-9]+|StopIteration" | …'` was denied as
R-SECRET-BASH-MENTION, "Matched on this token from your input: `/.*:[0-9]+`" against a protected `.vault-pass*`
glob. The token is a regular expression passed to `grep -E`, inside double quotes inside a single-quoted `bash -c`
program. It names no file. Ruling A1 says deny only on a positive finding; a regex fragment whose `.*` could
glob-match a hidden protected name is not one.

**Impact**: medium. Searching test output for `path:line` is an ordinary debugging command. The ordinary-command
gate has no row for a regex containing `/.*` as a grep pattern.

**Status**: ✅ Fixed (this branch, commit recorded at merge). Root cause: the N269/N291 text-operand view
(`_without_text_operands` in `utils/secret_file_matching.py`) segmented the top level and each substitution, but not the
program string of `bash -c '...'`, which is one quoted word at top level; a grep pattern inside it kept its glob
characters and `/.*:[0-9]+` matched the protected dotfile glob. The plain `grep -E "..." file` and `rg` shapes were
already allowed. Fix: `_text_operand_spans` also descends (three layers) into the content of a single-quoted `-c`
program of `bash`/`sh`/`dash`/`zsh`/`ksh` (`_shell_dash_c_program_span`; single quotes keep offsets exact, so a
double-quoted program is left to the ordinary scan), so grep/rg/echo operands there are text. A grep FILE operand that
names or globs to a protected path stays denied, as does a protected path read anywhere else in the program. Not
covered: a `FOO=1 bash -c` prefix (the command word is unresolved, so it fails closed). Pinned by
`tests/unit/utils/test_bash_c_text_operands.py` (red before the fix) and four gate rows (`n356-*`).

### N354 — the upgrade-approval guard denies a `PYTHONPATH=… python -c` probe that runs no upgrade

**Source**: the coordinator, 2026-10-05, probing a worktree branch's handler code from the main checkout.

**Evidence**: `PYTHONPATH=<worktree>/src /workspace/.venv/bin/python -c "…import ProjectContainmentHandler…"` was
denied as R-UPGRADE-APPROVAL-ENV-BYPASS. The command runs no upgrade: no `upgrade.sh`, `upgrade_version.sh`, gate
script, `--project-root` or `.claude/hooks-daemon` clone path appears in it. The likely trigger is the "script that
cannot be read" limb treating an inline `python -c` program as an unreadable upgrade script, with `PYTHON*` set.

**Impact**: medium for this repository. Running branch code with `PYTHONPATH` is an ordinary development idiom. The
workaround is a script file under `untracked/scratch/` with `sys.path.insert`.

**Status**: ✅ Fixed (this branch, commit recorded at merge). Root cause: not the "script that cannot be read" limb but
its sibling for interpreters, `_variable_program_is_upgrade` in `handlers/pre_tool_use/upgrade_approval_guard.py`: any
`-c` flag returned `_cannot_tell_script`, which is "the upgrade" once a steering assignment (`PYTHONPATH`) is present,
even when the program text was literal. Fix: `_inline_program_is_upgrade` judges a literal `-c` program by the
upgrade's own signals (`upgrade.sh`, `upgrade_version.sh`, `upgrade_gate_standalone.py`, `--project-root`, the
`.claude/hooks-daemon` clone path); a program with `$` or a backtick, or no text, stays "cannot tell". Three existing
rows that pinned `-c 'import os'` under a steering variable as denied were changed to `-c "$CODE"` (still denied) and
a literal program naming `scripts/upgrade.sh` (still denied); the literal `import os` shape is now pinned allowed in
`TestSteeredLiteralInlineProgramNamesNoUpgrade`, plus gate row `n354-pythonpath-python-c-probe`. Residual, by the
threat model's limb-1/limb-2 rule: a literal program that builds the upgrade's name at run time is not seen.

### N353 — the dismissive-language advisory flags a citation of the threat model's own scope rule

**Source**: the coordinator, 2026-10-05, on a stop that asked the owner the guard-review questions.

**Evidence**: the Stop advisory "Dismissive language detected (out of scope)" fired on a message whose only match was
"The threat model already treats that kind of deliberate evasion as out of scope." That sentence stated the real risk
of the owner's decision A1 (Plan 00483 R3). It cited the threat model's limb-1/limb-2 scope rule, which this
repository uses as a term of art in plans, rulings and handler guidance. It did not deflect any work.

**Impact**: low. The advisory never blocks. But it nudges the agent to soften or drop an accurate risk statement, and
in this repository "out of scope" is mostly that technical sense, so the advisory is mostly noise here.

**Status**: ⬜ Open. Remedy candidates:

- do not flag "out of scope" when the same sentence names the threat model, a plan's Non-Goals or a limb;
- or make the phrase configurable per project, so this repository can exempt its term of art.

This touches no guard in the frozen secret-guard area.

### N352 — an ordinary Python heredoc is denied when the host is busy (scan deadline)

**Source**: the coordinator's post-merge full run for the N130 merge (012915bd9), 2026-10-04.

**Evidence**: three tests failed in the full run (3 h 15 min, against 2 h 47 min for the previous full run).

- `test_secret_file_guard.py::TestRoundThreeFindingsAreClosed::test_an_inert_sibling_keeps_the_exemption[echo "$(pwd)"]`
  was denied as R-SECRET-SCAN-INCOMPLETE. The 5 s scan deadline passed while the guard judged `echo "$(pwd)"` followed
  by a Python heredoc with code braces. It passes when re-run with nothing else running.
- `test_safety_handlers_hostile_input_performance.py::…[wildcards]` reported superlinear. It passes when re-run alone.
- The playbook probe for RootRecursionGuardHandler (#108, `grep -rl … /`) is now denied first by secret_file_guard's tree
  walk, as R-SECRET-READ, instead of by the root guard. This is deterministic. The fix is to run the root guard before
  the secret guard. That fix is now merged: root_recursion_guard has priority 13. After the restart a live probe denies
  as R-ROOT-RECURSION-CATASTROPHIC in 0.5 s, where it took 1.9 s before.

**Impact**: the first item is a load-dependent verdict on a command that names no protected path, the N101 shape
again. A real session on a busy host gets the same deny.

**Status**: ✅ Fixed by Plan 00483 (owner rulings A1/A2): a deadline or cap running out now allows with an advisory
instead of denying, and the tree walk is gone. See release-note callout 027.

### N351 — the full-QA lock file names a dead holder while `run_tests.sh` holds the lock

**Source**: coordinator, 2026-10-04, during a post-merge full run.

**Evidence**: `run_tests.sh` held `.git/hooksdaemon-full-qa.lock`. The file contained `pid=3241890` and
`checkout=…/worktree-p470-queue`. That process had exited hours earlier and its worktree had been deleted. Meanwhile
another agent's `llm_qa.py changed` was queued behind the real holder. The bash route,
`scripts/qa/acquire_full_qa_lock.bash` `acquire_full_qa_lock_or_die`, takes the `flock` and writes nothing into the
file. The Python route writes `pid=`/`checkout=` and leaves it there after it releases the lock. The bash
give-up message reads the holders from `/proc`, so the waiter's report is right; only the file's content misleads.

**Impact**: a person or agent who diagnoses a stuck queue by reading the lock file is told the holder is a process
that no longer exists, and may conclude the lock is stale and try to break it.

**Status**: ✅ Fixed in 1999db05c. Both routes write their own `pid=`/`checkout=`/`started=` lines once they hold the
flock, and every acquirer overwrites the whole file. `llm_qa.py` also empties the file on release. The bash route
(`run_tests.sh`) does not clear on exit: the kernel drops the flock when the shell dies, and an EXIT trap would clobber
the caller's own, so a stale line from a finished bash holder names a dead pid, which `describe_holder` reads as "no
holder", until the next acquirer overwrites it. The file is never unlinked.

### N350 — a `for … in dir/*` loop was denied on a lone `*` token

**Source**: the N130/N348 design agent (Opus) on 2026-10-04, while it was measuring. This is side observation S2 in
`CLAUDE/Plan/00483-threat-model-conformance-audit/subagent-reports/261004-n130-n348-capped-walk-design-opus.md`.

**Evidence**: secret_file_guard denied
`cd untracked; for d in repos/* worktrees/* fd-worktrees/*; do … git -C "$d" ls-files …; done` as
R-SECRET-BASH-MENTION. The matched token it reported was a lone `*`. The agent believes none of the three globs
reaches a protected file. A lone `*` suggests a tokenisation artefact: the `*` was split out of the loop list and
expanded from the `untracked/` cwd, where a protected file does sit. No one has reproduced this with
`hooks-daemon probe` yet.

**Status**: ✅ Fixed by Plan 00483 (owner rulings A1/A2): an unresolved `$VAR` no longer becomes `*` and the
bare-glob filesystem expansion is replaced by a protected-file index. The original analysis follows. The cause is wider than the loop list. The
word scanner turns every unresolved `$VAR`, including a loop's `"$d"`, into a lone `*`, and the bare-glob route
expands that `*` against the cwd. So `cd untracked; for d in repos/one; do ls "$d"; done` is denied whenever the cwd
holds a protected file.

A 286-line fix exists, substituting loop words inside the loop's body. It is on branch
`agent-a388f9611b6f8f3d1-1f7c8c8f` (cb8dc34ab). It is not merged, because it is the kind of growth the guard-effort
review (Plan 00483 open question 4) argues against. The review's R4 would remove the bare-glob filesystem expansion,
and that removes this false positive at no extra cost. Wait for the owner's ruling on R3/R4 before choosing a fix.

### N349 — the linear-scaling harness divides by zero when both timings read 0 CPU seconds

**Source**: the Plan 00483 batch H agent's targeted QA on `worktree-p483-recur`, 2026-10-04.

**Evidence**:
`tests/unit/handlers/test_safety_handlers_hostile_input_performance.py::TestBashCommandShapesStayLinear::test_every_safety_handler_stays_linear[backslashes]`
raised `ZeroDivisionError: float division by zero` at `tests/scaling.py:75`. That line is
`large / max(small, linear_baseline_seconds(large_text))`. Both `small` and the baseline are `min_cpu_seconds(...)`
readings, which can be 0.0 when the process CPU clock's resolution is coarser than the work. The same file passed
41/41 twice on main and twice on the branch shortly afterwards. In the same QA runs, different `stays_linear` cases
failed on their ratio and then passed on re-run.

**Impact**: a flaky failure in a gate test that is meant to catch super-linear guards. A reader cannot tell a real
regression from clock resolution, so a branch's QA needs re-runs that prove nothing.

**Status**: ✅ Fixed (d97464d6e). `tests/scaling.py` now floors the `scaling_ratio` denominator at
`clock_resolution_seconds()`, one tick of `time.thread_time` measured by spinning across two consecutive advances
(falls back to `clock_getres`, then 16 ms). `clock_getres` alone was not used because it reports 1 ns on a coarse
clock. A measurable denominator is unchanged, so `SUPERLINEAR_RATIO` and the measured inputs are untouched.
`counted_ratio` divides by an integer count floored at 1 and had no hazard. Harness tests: `tests/unit/test_scaling.py`.

### N348 — the secret guard's bare-glob cap denies ordinary deep globs as a repository grows

**Source**: coordinator review of Plan 00483 batch G (N220, branch `worktree-p483-glob` at bbabec672) on 2026-10-04.

**Evidence**: on this repository, with the guard as fixed in review round 1:

- `ls */*/*` expands to 4530 bash-visible paths and is allowed, 470 under the 5000-path cap.
- `ls */*/*/*` expands to 18373 paths and is denied, failing closed past the cap. None of those paths needs to be
  protected for the deny to happen.

**Impact**: the verdict on an ordinary read-only glob depends on how big the tree is, not on what the glob reaches.
About 470 more files at depth 3 and `ls */*/*` is denied too. Failing closed past the cap is correct for a guard
that could not finish reading, but the deny reason should say "too many paths to check", not "mentions a protected
path".

**Status**: 🟡 Partly fixed. The reason and rule part is fixed on worktree-n346-capmsg (commit 495217e2c): a scan
past its cap or deadline is denied as `R-SECRET-SCAN-INCOMPLETE`, whose reason says what ran out (the cap of examined
paths, or the scan deadline), that no protected path was found, and to narrow the glob or search root or name the
files, or retry after a deadline. A real finding keeps `R-SECRET-BASH-MENTION` or `R-SECRET-READ`.

**Status update**: ✅ Fixed on worktree-n130-walk (Addresses ledger 00474 N348 and 00483 N130): fixed: fail closed past
a measured cap; git listings for git-shaped tools. The bare-glob cap is 100000 examined paths (about 0.3 s per 30k
paths), and a literal screen runs before the glob matcher, so `ls */*/*/*` (18373 paths here) is judged on what it
reaches and no longer denied for its size. The recursive-search scan (`utils/protected_tree_scan.py`) raises past 250000
entries or the deadline and is denied as `R-SECRET-SCAN-INCOMPLETE` (`R-QUARANTINE-SCAN-INCOMPLETE` in the quarantine
guard); `rg`, `ag` and `git grep` read git's file lists, so ignored bulk is not counted. The "check each pattern against
the glob" idea was analysed and rejected: an unanchored name pattern, which every shipped default is, can match in any
directory, so no pattern-side check bounds the walk. Report:
[261004-n130-n348-implementation-sonnet.md](../00483-threat-model-conformance-audit/subagent-reports/261004-n130-n348-implementation-sonnet.md).

### N347 — the plan-folder mkdir guard read `mkdir` inside a branch name as a command

**Source**: coordinator, resolving the batch D merge on 2026-10-04.

**Evidence**: the command `git show worktree-p483-mkdir:CLAUDE/Plan/00483-…/JOURNAL/<day-file>` was denied as
R-PLAN-FOLDER-MKDIR, naming `mkdir :CLAUDE/Plan/00483-…`. The `mkdir` inside the ref word was read as a command
word. `hooks-daemon probe` reproduced it on main at e7e92a430. The same probe is allowed on main at c953b0c62, which
includes batch D (merge 76bf848aa), because that change judges real `mkdir` commands only.

**Impact**: a false positive on any read-only command whose word contains `mkdir`, such as a branch name, a ref or a
path.

**Status**: ✅ Fixed incidentally by 76bf848aa and pinned in 63163f185 by a unit test in
`test_plan_number_helper.py` that allows `git show <x>-mkdir:CLAUDE/Plan/NNNNN-name/PLAN.md`.

### N346 — commit-time gates with a fixed subprocess timeout deny ordinary commits under host load

**Source**: the Plan 00483 batch F agent, committing on `worktree-p483-paths` on 2026-10-04 while the host load
average was about 45.

**Evidence**: `conflict_marker_commit_gate` denied several ordinary commits after its 5 s `git grep --cached` timed
out. The same commits passed unchanged once load dropped. In the same window, `llm_qa.py changed` failed on
`project_handlers` and `semgrep` only through their 300 s-or-longer timeouts, and both passed when re-run alone at
the same HEAD.

**Impact**: a deny that depends on host load and not on the staged content. A careful agent re-tries. A careless
one may read the deny as a real conflict marker and edit content that is fine. This is the commit-gate twin of N344.

**Status**: ✅ Fixed on worktree-n346-capmsg (commit f24046993). `run_git` reports a timeout as its own status
(`GIT_TIMED_OUT`, 124), and `conflict_marker_commit_gate` denies it as `R-CONFLICT-MARKER-SCAN-TIMED-OUT`: the reason
names the 5 s limit, says no marker was found and the content needs no edit, and says to retry the same commit. The
bound is unchanged and the gate still fails closed. The sibling commit gates were checked: `sensitive_content`'s
staged-diff reads and `staged_lint_gate` stand down (allow) on a git or tool timeout, and the docs, plan and
remote-docs QA gates deny with the staging simulation's own message, which already names the failed `git add`
and is not a finding.

### N345 — a merge conflict in a past journal day-file has no sanctioned resolution

**Source**: coordinator, merging Plan 00483 batches B and C on 2026-10-04. Each branch had added an entry to
`00483-Journal-26-10-03.md`, as had main, so both merges conflicted in that day-file.

**Evidence**: these resolutions were all refused:

- `Edit` to remove the markers: `plan_qa_edit` refused it under `journal-dayfile-is-today`, because the file is
  dated yesterday.
- `cp` of a `git merge-file --union` result: `plan_journal_guard` refused it as R-JOURNAL-HAND-WRITTEN-ENTRY.

`git checkout --ours <day-file>` was allowed and wrote the day-file. So the guards block the careful route, a union
of both sides, but let through the route that discards one side. The coordinator kept main's side and re-recorded
each branch's entry in today's file with `mkplan.bash --journal`, so the history now carries the entries under the
wrong day, with a pointer.

**Impact**: any parallel work that journals the same plan on the same day and merges after midnight hits this.
Worktree agents met the same conflict before midnight and could resolve it.

**Status**: ✅ Fixed on worktree-n345-jconf (commits 0f72d5238 and 662a8013c): `mkplan.bash --resolve-conflict <day-file>` writes the union of both sides in time order and stages it, and `git checkout|restore --ours|--theirs` of
a day-file draws an advisory from `plan_journal_guard` (not a deny: the discarded entries survive in the other commit,
and keeping one side is sometimes right). Neither guard judges the mode, which is a Bash command that writes no
day-file by any route they know; `plan_qa_edit` only judges Edit/Write. Original remedy text: let both guards accept
an edit that only removes conflict markers from a day-file and
keeps every entry from both sides. The test is that the result equals the union of the two stages. Alternatively,
give `mkplan.bash` a `--resolve-conflict <day-file>` mode that writes the union in time order. Also decide whether
`git checkout --ours/--theirs` into a JOURNAL path should be judged at all.

### N344 — integration tests with fixed wall-clock timeouts fail falsely under host load

**Source**: coordinator, post-merge `tests/integration` on main at 2c0d76087 and later, 2026-10-03/04, while the host
load average reached 55 on 8 CPUs.

**Evidence**: the run reported 1 failed and 6 errors, all `subprocess.TimeoutExpired`:

- six fixtures in `test_upgrade_pre_deploy_phase_runs_on_layer1.py` hit the 120 s limit on `git add -A --force`;
- the N326 test `test_suite_passes_on_a_released_unreleased_tree.py` hit its run timeout.

Re-run at load average 17, both files passed 19/19, but took 25 minutes. The full integration suite took 1:47:48
against its usual 27 minutes. This is the N222 class in Plan 00483's triage: a verdict that depends on host load.

It happened again in the post-merge run on main at 9b2e15be1 (load average about 45). The same two files failed, plus
`test_venv_bootstrap_driver.py::TestTheWatchdogNeverOutlivesItsBuild::test_a_killed_build_process_takes_its_watchdog_with_it`.
That third test asserted that a list of surviving pids was empty, rather than timing out.

A fourth file timed out in the post-merge run on main at aace64fb4, with a load average of about 13 to 20:
`test_doc_truth_check.py::test_real_repository_docs_are_truthful`. Re-run alone, the file passed 17/17 in 37 s.

**Impact**: a post-merge or CI run on a busy host reports false failures, and each one costs a manual re-run to
tell load from a regression. The N326 test is the heaviest single test in the suite.

**Status**: ✅ Fixed on worktree-n344-load (eaab931b9). `tests/load_scaling.py` gives `scaled_seconds(base)`, the idle
budget times the larger of the 1 and 5 minute load averages per CPU (floor 1, cap 16), with unit tests. The four
named files use it for their hang-guard timeouts. The watchdog test polls up to a load-stretched build bound; the
first scaling attempt failed under synthetic load (24 spinners on 8 CPUs) because the orphaned job's venv work
outlasted a deadline derived from the lagging load average, so the bound itself now carries the stretch. Passed
under that load afterwards. The N326 test is not restricted to changed files: it exists to catch a dependency on
staged content in a test nobody touched, so a changed-files filter would hide exactly that case; CI-only would
move the failure to release time, which is what N326 was written to prevent. Other integration files with fixed
`timeout=` values were out of scope and are not scaled.

### N343 — agents add entries under an already-released CHANGELOG section

**Source**: coordinator, 2026-10-03. The Plan 00483 batch B and batch C agents
(`worktree-p483-segment`, `worktree-p483-config`) each added their release note under `## [3.68.0]` in
`CHANGELOG.md`. v3.68.0 was tagged and published days earlier. Each brief asked for a callout under
`CLAUDE/UPGRADES/UNRELEASED/release-notes/` instead. Both were caught at coordinator review and sent back.

**Evidence**: two independent agents made the same mistake in one batch, so the cause is the environment and not
the individual agents. Nothing stops an edit to a released section. An agent that looks for "where release notes go"
finds the newest section at the top of `CHANGELOG.md` and appends to it.

**Status**: ✅ Fixed. The `released_changelog` QA tool (`scripts/qa/check_released_changelog.py`, run by `llm_qa.py changed`) fails when a section present in the latest `v*` tag's `CHANGELOG.md` differs in the working tree. Its message
names `CLAUDE/UPGRADES/UNRELEASED/release-notes/`. A new section is allowed, so the release process passes. No doc
tells contributors to edit `CHANGELOG.md`; `RELEASING.md` already forbids it outside `/release`.

### N338–N342 — false positives and a setup limit met by the Plan 00487 host agent

**Source**: Plan 00487 host agent, Task 3.1, working on this repository and on a fedora-desktop clone under
`untracked/work/`. Each row was seen once, in one session, and was not reduced to a test. Each needs a
reproduction before it is fixed.

| Id   | Finding                                                                                                                                                                                                                                                                                                                                                   | Status                             |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| N338 | `project_containment` follows only the first `cd`: `cd <in-repo clone> && … && cd extensions && npm ci > ../untracked/scratch/x.txt` was denied as a write to `<repo>/../untracked/scratch/x.txt`, resolved from the root after the first `cd` instead of from `extensions/`.                                                                             | ⬜ Open                            |
| N339 | `bash_safe_mode` denies a fully gated group: `cd X && mkdir -p d && { ./qa.bash > d/o.txt 2>&1 && echo "exit=0" \|\| echo "exit=$?"; }`. The `;` that closes the `{ }` group is read as unguarded sequencing.                                                                                                                                             | ✅ Fixed on worktree-n339-compound |
| N340 | The "WRONG CLAUDE/ DIRECTORY" advisory fires on every Read of this repository's own `CLAUDE/Plan/...` files. In self-install mode the project's `CLAUDE/` is the authoritative copy, not "the daemon's internal docs copy".                                                                                                                               | ⬜ Open                            |
| N342 | `setup_worktree.sh` cannot create ANY worktree from a host checkout at `/home/<user>/Projects/EC/claude-code-hooks-daemon`: the socket path up to the branch name is already 103 bytes against the 104-byte AF_UNIX limit, so even the mandatory `worktree-` prefix does not fit. The merge rule "work happens in worktrees" is unsatisfiable from there. | ⬜ Open                            |
| N341 | `sensitive_content` denied `cd /home/<user>/... && git worktree remove … && git branch -d <name>`. The secret term was in the `cd` path, not in the branch name the branch-name surface exists to check; the matched text was redacted as part of the home path.                                                                                          | ⬜ Open                            |

**N339, second reproduction** (coordinator, this container, 2026-10-03): `… && for b in a b c; do git -C x/$b rev-parse HEAD || exit 1; done` was denied as having no safety prelude. Every step in it is gated, but the `;` inside the loop syntax (`do … ; done`) was read as unguarded sequencing. This is the same class as the `{ …; }` group above. A fix should parse compound-command syntax (`{ }`, `for/while … do … done`, `if … fi`) rather than treat each `;` as a separator.

### N330–N337 — findings from the Plan 00486 backfill changelog review (Claude Code 2.1.272 to 2.1.288)

**Source**: Plan 00486 Task 1.4,
`CLAUDE/Plan/Completed/00486-claude-code-version-tracking/subagent-reports/261003-task-1.4-backfill-review-sonnet.md`.
The report filtered the 2.1.273 to 2.1.285 entries by keyword
and did not read them in full, so each item below has to be verified before anyone acts on it.

| Id   | Finding                                                                                                                     | Status                                                                                                                                   |
| ---- | --------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| N330 | Read `rate_limits.spend_limit` in `core/usage_snapshot.py` (adopt).                                                         | ⬜ Open — verified (statusline docs list rate_limits.spend_limit, 2.1.251+); adopt when a consumer is wanted (owner call)                |
| N331 | Verify `.claude/rules` write-time loading on 2.1.288 and correct `CLAUDE/DirectoryRoles.md` if it changed.                  | ❌ Not a defect — `DirectoryRoles.md` says "when matching files are touched", which 2.1.288 made true for Write and Edit as well as Read |
| N332 | Guidance claims "run_in_background has no time limit"; reported false for unattended sessions since 2.1.285.                | ✅ Fixed                                                                                                                                 |
| N333 | Define how `usage_pause` interacts with Claude Code's "Continue automatically at usage limit" wait.                         | ⬜ Open                                                                                                                                  |
| N334 | Re-check the supervisor's post-compaction `/goal` and `continue` re-injection against the 2.1.274 fix (possibly redundant). | ⬜ Open                                                                                                                                  |
| N335 | Compare `/doctor prompt-audit` with `skill_scan` and `docs_qa` (possible overlap).                                          | ⬜ Open                                                                                                                                  |
| N336 | Make the supervisor's red-zone `/compact` aware of the `/autocompact` window.                                               | ⬜ Open                                                                                                                                  |
| N337 | Gate the supervisor's idle `/compact` on `prompt_cache.warm`, so that compaction does not run against a cold cache.         | ⬜ Open                                                                                                                                  |

Idle compaction: the review found none in the Claude Code changelog or the vendored prompt-caching docs, so the
owner's report is unconfirmed. Claude Code compacts by window size. The idle-gated `/compact` seen in sessions is the
ccy supervisor's own.

### N329 — the N323 merge added a root-conditioned skip, and main carried it until the next post-merge integration run

**Source**: coordinator, post-merge `tests/integration` on 62d9e6292, the N328 merge.

**Evidence**: `tests/integration/test_no_root_conditioned_skips.py` failed on `tests/unit/install/test_upgrade_gate.py`. N323 (b8b99c007, merged in 954dde9f1) added `skipif(os.geteuid() == 0)` to a mode-000 marker test. Its sibling test already monkeypatches the read to raise `PermissionError`, so the case was covered as root. The branch's `changed` run never ran `tests/integration`. After 954dde9f1 merged, the coordinator ran only `tests/acceptance`, because integration had passed on the earlier 744125f1a. This is a process gap: a post-merge integration run counts only for the merge it ran after.

**Status**: ✅ Fixed on main. The skipped test is removed, and the monkeypatched sibling stays. The gate tests and the guard pass, 1598 tests in total. From now on, each merge gets its own post-merge integration run, and a run on an earlier merge does not count.

### N328 — `set -e` has no effect in the Claude Code Bash tool, so the prelude `bash_safe_mode` asks for protects nothing

**Source**: coordinator, 2026-10-03. Twice in one session a `set -euo pipefail` command kept running after a
failing step: semgrep ran after pytest failed, and a commit ran after `mkplan.bash --journal` exited 1.

**Evidence**: probes run through the Bash tool:

| Probe                                          | Result                 |
| ---------------------------------------------- | ---------------------- |
| `set -euo pipefail; false; echo STILL RUNNING` | prints `STILL RUNNING` |
| `bash -c 'set -e; false; echo x'`              | stops, exit 1          |
| `( set -e; false; echo x )`                    | prints `x`             |
| `false && echo x`                              | stops                  |
| `set -o pipefail; false \| cat; echo $?`       | `1` (pipefail works)   |

The harness runs each command as `… && eval '<command>' < /dev/null && pwd -P >| …`. Bash ignores errexit
for any command that is part of an `&&` list, and this includes everything inside the `eval` and inside
subshells. Only a fresh `bash -c` process or explicit `&&` / `|| exit` gating stops on a failure.

**Impact**: `bash_safe_mode` (R-BASH-SAFE-MODE-PRELUDE-MISSING) is strict by default since v3.68.0. Its
fix line says "add `set -euo pipefail` at the top", and the prelude satisfies the gate, but under this
harness it gives no protection. The guard therefore produces a false sense of safety. `pipefail` and `-u`
still work; only `-e` is lost. Whether the harness behaviour is intended upstream is unverified.

**Status**: ✅ Fixed on worktree-n328-errexit-harness. `verification_result_gate` no longer stands down for a
top-level `set -e` (only a fresh `bash -c` / interpreter-heredoc script that sets errexit), and `bash_safe_mode`
still accepts the prelude but its deny text, fix line and guidance now lead with `&&`, `|| exit 1` and the
`bash -c 'set -euo pipefail; …'` wrapper and state that a top-level `set -e` does not stop the command under the
current Claude Code Bash tool.

### N327 — a fresh install of v3.68.0 leaves no gated-install record, so its same-version re-run is stopped for the owner

**Source**: coordinator, post-merge `tests/acceptance` on e82a57a4a once v3.68.0 was the newest published tag
(`test_upgrade_metadata_emission.py` x2, `test_skill_upgrade_end_to_end.py`,
`test_skill_upgrade_legacy_shim_end_to_end.py`). Report:
[subagent-reports/261003-n327-fresh-install-gate-record-sonnet.md](subagent-reports/261003-n327-fresh-install-gate-record-sonnet.md).

**Evidence**: `scripts/install_version.sh` stamps the venv (`ensure_venv`) but never calls the gate, and
`upgrade_gate.record_gated_install` runs only from `upgrade_gate.main` on a PROCEED. So a fresh install has a venv
stamp and no receipt. `evaluate_gate` (`upgrade_gate.py`, the `installed_stamp == target_stamp` branch, line 611)
then reads "stamped, not gated" as an unknown history (the Plan 00376 fresh-review MAJOR 1 defence against checkout
plus `repair`) and stops with exit 3, listing 11 guides back to v2.0. The gate that runs is the TARGET tag's own
copy: `upgrade.sh` on main hands over to the checked-out `scripts/upgrade_version.sh`, which runs that tree's
`upgrade_gate_standalone.py`. A fix on main therefore does not change what a v3.68.0 install does.

**Impact**: only the SAME-version re-run (v3.68.0 onto v3.68.0). An upgrade to any other release has a stamp that
differs from the target, takes the normal range path with the stamp as a trusted FROM, and records itself on PROCEED,
so it is not stopped by this and it heals the install. An install that upgraded INTO v3.68.0 through the gate has
the record; a fresh one does not.

**Decision for existing v3.68.0 installs without the record**: unchanged, still stopped for the owner. The record is
the only thing that tells a gated install from a stamp a manual checkout plus `repair` wrote, and an agent could use
that equality to land a MAJOR without approval; a missing record is exactly that unknown history. The remedy for an
affected project is an upgrade to the next release or `hooks-daemon approve-upgrade`. Nothing in this repository can
reach the v3.68.0 copy of the gate, so a patch release would only help NEW installs.

**Status**: ✅ Fixed on worktree-fix-gate-fresh-install. `install_version.sh` records the install through
`upgrade_gate_standalone.py record-install`, only when no venv stamp existed before it (a pre-existing stamp may be a
repair's). The acceptance fixture tags the clone's HEAD as the next patch inside the throwaway clone while the newest
published tag's installer lacks `record-install`, so those four tests exercise the fixed code; they run against the
real tag once a release carries the fix. Residual: whoever can delete the venv and run the installer can mint a record.

### N326 — release prep exposed tests that pass only while `UNRELEASED/` holds content

**Source**: coordinator, v3.68.0 release prep (CI run on 072a4da2f).

**Evidence**: Step 6 of a release empties `CLAUDE/UPGRADES/UNRELEASED/` into the versioned guide. `tests/acceptance/test_guarded_branch_install.py` then failed, because the pre-deploy gate it drives found nothing staged to stop on. Its expectation depended on the repository's own `UNRELEASED/` contents, not on a fixture. The manifest example test had the same dependency. Both were found only at release time, because between releases `UNRELEASED/` is never empty. Fixed for the guarded install in 3f0311e8e: the test commits its own staged callout and manifest into the clone.

**Status**: ✅ Fixed on worktree-n326-unreleased-dependency. `tests/integration/test_suite_passes_on_a_released_unreleased_tree.py` runs every test file that mentions the holding area against a clone whose `UNRELEASED/` holds README scaffolding only, so a dependency on staged content fails between releases.

### N325 — `staging_simulation` warns "add -A" when the command ran `add -u`

**Source**: v3.68.0 release code review, round 3 (a non-defect suggestion).

**Evidence**: when the simulation degrades, its warning text names `git add -A` even when the command it simulated was `git add -u`. Only the wording is wrong; the staged-set computation is right.

**Status**: ✅ Fixed in 1ca156987. The warning now names the flags the add actually ran (`add -u`, or `add -A --ignore-errors`).

### N324 — the CI-run lookup does not say which run it read when HEAD has several

**Source**: v3.68.0 release code review (a non-defect suggestion).

**Evidence**: `release-slate-check` reads the `qa.yml` run for HEAD. HEAD can have more than one run: a push tier run plus a dispatched full-matrix run, or a cancelled run plus its re-run. Which one wins should be explicit (the newest completed full-matrix run), and the check should name it.

**Status**: ✅ Fixed on worktree-n324-ci-run-lookup. The lookup now picks the newest completed, non-cancelled run that carries the matrix jobs (a newer failure is not hidden by an older green), and the slate output names that run's id.

### N323 — `check_approval` should report INVALID on an unreadable approval marker

**Source**: v3.68.0 release code review (a non-defect suggestion).

**Evidence**: an approval marker under `upgrade-approvals/` that exists but cannot be read is treated like a missing one. The gate still fails closed, but the message sends the owner to approve again, when what needs fixing is the file's permissions.

**Status**: ✅ Fixed in b8b99c007. A distinct `ApprovalState.UNREADABLE` (fail-closed, read through `path_predicates`) whose gate message points at the file's permissions; the standalone gate loader now loads `utils/path_predicates.py`.

### N322 — `usage_snapshot` can leave its temp file behind when the rename fails

**Source**: v3.68.0 release code review (a non-defect suggestion).

**Evidence**: the snapshot writer writes a temp file and renames it into place. If the rename raises, the temp file stays in the state directory. Nothing reads it, but it accumulates.

**Status**: ✅ Fixed in 4b0c3dcd5. The writer unlinks its temp file when the write or rename fails, and a test drives the failed rename.

### N321 — strict-by-default left four acceptance probes denied, and merge checks never ran `tests/acceptance/`

**Source**: coordinator, release prep full QA (`llm_qa.py all`) on c818d43e5.

**Evidence**: `tests/acceptance/test_playbook_harness.py` failed with 4 of 241 probes denied by
`R-BASH-SAFE-MODE-PRELUDE-MISSING`. Three were `self_matching_process_probe` ALLOW probes (`… & wait $!`, an `until …; do …; done` loop) and one was `verification_result_gate`'s newline-separated
pair. Their commands were written before `bash_safe_mode` became strict by default, which denies
any unguarded sequence before those handlers speak. The coordinator's per-merge check ran
`tests/integration/` in full but never `tests/acceptance/`, so the break surfaced only at release.
Sixth instance of the N310 class: a suite the merge routine does not run went red silently.

**Status**: ✅ Fixed on main. The sequenced allow probes carry `set -euo pipefail;`, and the
verification-gate probe declares `MUST_SKIP_SAFE_MODE_BECAUSE`, because a prelude would make the
gate stand down. Harness 5/5 green. Remaining: the merge routine runs `tests/acceptance/` beside
`tests/integration/`. The v3.68.0 release added a lesson: the merge routine also needs
`llm_qa.py semgrep`. The N317 semgrep finding and the merge_qa_advisor EACCES finding both
reached main past the per-merge checks and surfaced only in the release's full QA and CI. Since
the release, the coordinator runs `tests/integration`, `tests/acceptance`, `semgrep` and
`dangerous_invocation_corpus` on main after each core merge. The routine itself still has to say
so (Plan 00475 Task 4.2).

### N320 — `D=path && cmd > $D/f` is denied as a write outside the project; the `;` form is allowed

**Source**: coordinator, a live deny while probing after the Plan 00483 batch 2 merge.

**Evidence**: `project_containment` on merged main (9d182f299), project root `/repo`:
`D=untracked/scratch/q; python p.py > $D/a.json` is allowed, but the same command with `&&`
after the assignment is denied, quoted or not. `known_variables` resolves an assignment followed by
`;` but not one followed by `&&`. Strict mode (`bash_safe_mode`, block by default) tells agents to
chain with `&&` or add `set -euo pipefail`, so the rule's own advice leads into this deny. The deny
message itself suggests `OUT=…; … "$OUT"`. In scope: a literal assignment, visible at call time,
written the way the strict-mode guidance asks.

**Status**: ✅ Fixed (merge of worktree-n320-and-assignment, verified on main with the probe). `known_variables` now reads the literal assignments that lead an `&&` chain as known (`||` and an assignment after a command in the chain stay unknown), so `D=untracked/scratch/q && cmd > $D/a` allows and `D=/tmp && echo x > $D/a` still denies; `cd /repo && D=… && cmd` stays unresolved. That is deliberate: after a `cd`, the guard cannot place a relative path, so it fails closed.

### N319 — a stale local relay build fails 29 relay tests instead of being rebuilt or skipped

**Source**: coordinator, the full `tests/integration` run on main after the N310 lesson.

**Evidence**: 29 tests in `tests/integration/test_relay_guard_fail_open.py` failed on main, in a
full run and again alone. They read the gitignored build
`untracked/relay-build/hooks-relay-x86_64-unknown-linux-musl`, which is used whenever it exists.
That file was older than `relay/hooks_relay.rs`: `grep -a 'is over the cap'` found the message in
the source and not in the binary. After `bash relay/build.sh`, the relay suites passed (129).
Nothing tells a developer the binary is stale, so the failures look like a relay regression.

**Status**: ✅ Fixed (merge ae3230744). `relay/build.sh` writes a `<binary>.source-sha256`
sidecar and the `fresh_relay_build` fixture in `tests/relay_gate_guard.py` fails (never skips) with
"rebuild with `bash relay/build.sh`" when it is missing or differs from the source hash.

### N318 — N314's merge left main red: `check_module_length.py` was never classified as a walker

**Source**: coordinator, red main after merge 1078e4291.

**Evidence**: `tests/integration/test_qa_walkers_examine_files_from_any_checkout.py::test_every_check_is_classified`
failed with `unclassified: ['check_module_length.py']`. The script also enumerated with
`rglob`, passed on an empty `src/` having measured nothing, and used `Path.relative_to`, which
semgrep's `pathlib-quadratic-containment` reports. The sixth/fifth instance of the N310 class: a
new QA script lands without the pins that every other walker already meets.

**Status**: ✅ Fixed (merge 9377f68af; both tests green on main). The script walks through
`scan_scope.walk_files`, exits 2 when it examined nothing, reports `files_scanned`, uses
`path_relative_to`, and is classified in `WALKERS` and `ROOT_OPTIONS`. Findings stay report-only.
A second red test of the same class: merge bf8d40aa9 made `bash_safe_mode` block-by-default and
gave it a deny acceptance test, so its `_EXEMPT_FROM_DENY_TEST` entry in
`tests/integration/test_acceptance_test_coverage.py` became obsolete and failed
`test_an_exemption_is_dropped_once_it_becomes_untrue`. The entry is deleted; the affected suite
had not been run before that merge.

### N317 — plan QA says "stages no journal entry" when the same command writes and stages it

**Source**: coordinator, commit ea1a8e7ff.

**Evidence**: one Bash command ran `mkplan.bash --journal 483 …`, then `git add <plan folder>`,
then `git commit`. The commit holds `JOURNAL/00483-Journal-26-10-02.md`
(`git show --stat HEAD`), yet the PreToolUse advisory reported `journal-entry-with-progress`: no
journal entry staged. The gate judges before the command runs, so the day-file the command is
about to create does not exist yet. That is the N246 class: the staging simulation copies the
working tree as it is now, and a file a prior statement creates is invisible to it. Advisory
only. Following the advisory's own instruction in one command produces the false report.

**Status**: ✅ Fixed (merge 10dd29758). `plan_qa/command_journal.py` counts a plan as journalled
when an `&&`-chained `mkplan.bash --journal <N>` precedes a real `git add` covering that plan's
`JOURNAL/`, judged in the directory each statement runs in (the shared `simple_commands` parse
tracks `cd` and `-C`), and the commit's pathspecs do not exclude it. The exemption lives in
`has_staged_journal_entry`, so all three journal checks honour it; it stays advisory. The review
round's findings (cd ignored, sibling checks, pathspec commits, dry-run adds, `;` sequencing) were
fixed before merge.

### N316 — docs QA `pointer-resolves` reads a link shape inside an inline code span

**Source**: coordinator, landing Plan 00483's INVENTORY.md.

**Evidence**: a line quoting the `curl_pipe_shell` regex in one backtick span drew "Link target
does not exist" with the interpreter alternation as the target. The span held a square-bracketed
`path/` group immediately followed by the parenthesised `bash|sh|…` group, which is the inline-link
shape. Text inside inline code is never a link in Markdown. In INVENTORY.md it was `advise`. Quoting
the same span in this entry drew `[block]` (the edit was not refused). Both lines were reworded to
prose.

**Status**: ✅ Fixed on worktree-n315-n316-docs-qa. The shared link extractor now drops inline
code spans, as well as fenced blocks, before scanning for links.

### N315 — the post-commit docs QA report judges a vendored remote-docs page that lint and sweep exclude

**Source**: coordinator, committing Plan 00470 Task 1.1 (81338abb3).

**Evidence**: the commit staged `remote-docs/code.claude.com/docs/en/scheduled-tasks.md`, vendored
by `remote-docs add`. The PostToolUse "Docs QA drift report" then listed 19 `[block]`
`pointer-resolves` findings for its site-relative links (`/docs/en/mcp`, `/docs/en/goal`, …). The
commit itself was not blocked. The same file is out of scope everywhere else:
`docs-qa --lint <file>` exits 2 with "not a documentation file", and `docs-qa --sweep` reports 0
findings for the tree. The fidelity rule forbids editing vendored text, so a finding there can never
be acted on. A `[block]` label the gate did not enforce also misreports what happened.

**Status**: ✅ Fixed on worktree-n315-n316-docs-qa. The STAGED view now admits a path only through
the shared lint scope predicate, so `remote-docs/` pages never reach the post-commit report.

### N314 — no QA check bounds a module's size, so a handler reached 5,301 lines unnoticed

**Source**: owner-delegated Fable ruling on 00466 N96
([RULINGS-owner-delegated-fable.md](../00483-threat-model-conformance-audit/RULINGS-owner-delegated-fable.md#n96--subagent_full_qa_blockerpy-is-one-5301-line-handler)).

**Evidence**: `subagent_full_qa_blocker.py` grew to 5,301 lines (14 classes) through review rounds
that never flagged the size, and the N302 misclassification sat inside it. Nothing in
`scripts/qa/` measures module length.

**Status**: ✅ Fixed (merge 1078e4291; `scripts/qa/check_module_length.py`, bound 1000 lines,
report-only; making it a gate awaits an owner decision on the exception list).
`scripts/qa/check_module_length.py` reports every module under `src/` over 1000 lines (672
modules: median 170, p90 558, p95 848; 26 over the bound) and always exits 0. A gate would need an
exception list for today's outliers, which is an allowlist and needs owner approval. It is not
wired into `llm_qa.py`: no report-only tool exists there, and a passing tool shows nothing, so the
report would never be read. The split of the file itself is a separate, sequenced pure-refactor plan.

**Owner ruling (2026-10-05):** resolved: not just a size gate; a new plan, `code-quality-and-architecture-review`, covers module size, DRY, architecture and code quality, and N314 folds into it — see [OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md) (B5).

### N313 — `git_stash` denies a `grep` naming `git stash` when its output goes into `awk`

**Source**: coordinator, live, while reading a test file.

**Evidence**: `grep -n -B2 -A8 'a quoted heredoc body naming git stash\|…' tests/….py | awk 'NR<=50'`
was denied with R-GIT-STASH-PUSH. The same grep with no pipe is allowed. The command-position view
(N241) keeps a data head's arguments unless every downstream stage is an inert sink, and `awk` is
not one (it can `system()`), so the quoted pattern is judged as a command. A `python -c` script whose
string names `git stash` is denied the same way; that one is defensible, since the interpreter could
run it.

**Status**: ✅ Fixed (merge 22429c3a5; verified live after restart). An `awk` stage is an inert pipeline stage when
its program is ONE single-quoted literal with no `system`, `getline`, `|`, `>` or `@`, no option of any
kind (`-f`, `-v`, `--`), no `name=value` operand and no substitution; redirects are judged as for a
sink. `awk -f`, `awk "$p"`, `print | "sh"` and `system()` stay judged as commands.

### N312 — `split_statements` counted a heredoc's body and terminator as separate statements

**Source**: coordinator, main red on `tests/integration/test_handlers_do_not_match_prose.py`.

**Evidence**: `split_statements("cat > notes.md <<'EOF'\nnever run x\nEOF")` returned three
statements (the opener, the `HEREDOC_BODY` placeholder, `EOF`). With `bash_safe_mode` blocking by
default, every one-command heredoc write was denied for lacking `set -euo pipefail`. Two prose
cases failed: a literal inside a quoted heredoc, and a quoted heredoc body naming `git stash`.

**Status**: ✅ Fixed (merge d719ccac0; verified live after restart). A heredoc (opener line, body,
terminator) is one statement, quoted or unquoted delimiter, `<<-` included; `bash <<'EOF'` counts as
one outer statement because the outer `set -e` does not govern the inner shell. `<<<` is not a
heredoc. The callers that look for a command INSIDE an executed body
(`verification_result_gate`, `flaggable_content_channel_guard`, `quarantine_artefact_read_guard`)
pass `heredoc_bodies_executable=True` and keep the previous reading.

### N311 — `upgrade_approval_guard` denies a `PYTHONPATH=` pytest run inside a subshell

**Source**: the strict-mode agent. The coordinator reproduced it with `hooks-daemon probe`.

**Evidence**: `(PYTHONPATH=/tmp/src /workspace/untracked/venv-…/bin/python -m pytest tests/x.py -q)`
is denied with R-UPGRADE-APPROVAL-ENV-BYPASS. The same command without the parentheses is allowed.
It runs no upgrade, so this is a false positive on an ordinary shape. N285 and N292 fixed the
unparenthesised forms; the subshell form was missed. The heredoc-fix agent reports a second shape
denied with the same rule: `export PYTHONPATH=<worktree>/src && python -m pytest …` (reported, not
yet reproduced by the coordinator).

**Status**: ✅ Fixed (merge 22429c3a5; export form verified live after restart). Two causes. A subshell `(` made the first word
`(PYTHONPATH=…`, which the guard read as neither assignment nor command; stage segments now drop their
grouping parentheses (which also closes a hole: `(PYTHONPATH=x bash -c …)` and `(PYTHONPATH=x ./run.sh)`
were ALLOWED before and are denied now). And a path-named interpreter (`.venv/bin/python`, missing or
relative) was judged as a script that must be readable, so the `export` form was denied; it is now
judged by what it runs, as `$PY` is (N285): a literal non-daemon `-m` module or a readable non-upgrade
script is allowed, `-c`, stdin, a computed or missing script and the daemon's own CLI keep the deny.

### N310 — "unmapped [too-broad]" was treated as benign, and main stayed red twice

**Source**: the strict-mode agent's `llm_qa changed`. The coordinator reproduced it on main.

**Evidence**: two tests failed on main from 47ae8e2c7 and 506fd3f5e until 2be30049c:

- `tests/daemon/test_init_config.py::test_all_pre_tool_use_handlers_in_config` failed because
  `usage_pause_tool_gate` was missing from the init template.
- `tests/integration/test_template_priorities_match_the_constants.py` failed because the template
  shipped `merge_qa_advisor` at 56 against the constant's 59.

The coordinator's range QA over those merges reported "0 failed", because `constants/priority.py`,
`constants/handlers.py` and the handler set are "unmapped [too-broad]", so their tests are never
selected. Every merge since was accepted with "too-broad is the expected non-defect, the full gate
covers it". No full gate runs between releases, so main can stay red until release prep. N303 was
the same mechanism.

A third instance followed. The strict-mode merge (bf8d40aa9) turned the corpus row
`dismissed-n178-variable-command-word` stale, because bash-safe-mode now denies its `;` spelling.
The coordinator had not run `check_dangerous_invocation_corpus.py` on that merge, and a
sub-agent's `changed` run caught it.

A fourth instance came from the same merge: `tests/integration/test_handlers_do_not_match_prose.py`
failed two cases because bash-safe-mode counted heredoc lines as statements (N312, fixed by
d719ccac0). That suite is now on the coordinator's by-hand list too.

A fifth instance followed (N318): `test_every_check_is_classified` and the stale
`BashSafeModeHandler` exemption in `test_acceptance_test_coverage.py`. Hand-picked suites keep
missing reds, so on a merge touching core code the coordinator now runs all of
`tests/integration`.

That practice caught a sixth instance at once. The Plan 00480 Task 4.1 merge added a handler that
is off by default, and `test_dogfooding_config.py::test_all_production_handlers_are_enabled`
failed because this repository's own config did not enable it. Fixed in 7da15e4de by enabling it
in the dogfood config, not by adding an opt-in exemption.

**Status**: ✅ Fixed for all four (2be30049c: all three usage-pause handlers are in the
template and the priority is 59; the commit that records this entry rewrites the corpus row
with `&&`, keeping UNCOVERED-accepted, because the plan-folder axis is still open). ⬜ Open as a class. A "too-broad" verdict must not mean that no tests
run. When the unmapped set touches constants, handler registration or templates, `changed`
should also run the invariant suites that guard them: template/handler-set, priority,
guidance-coverage and evasion classification. The coordinator runs those by hand on such merges
until it does. This belongs with Plan 00475 Task 4.2.

### N309 — a docs page with an example session UUID cannot be vendored

**Source**: Plan 00479 Task 1.1 agent.

**Evidence**: `bin/hooks-daemon remote-docs add https://code.claude.com/docs/en/statusline`
exits 1: "the fetched content matches the sensitive-content pattern `session-uuid`. Nothing was
written." The page's example payload carries a UUID-shaped `session_id`, which the pattern cannot
tell from a real one. The remote-docs fidelity rule forbids changing vendored text, so the
two rules conflict, and neither can be bent by an agent.

**Second instance (Plan 00486 Task 1.3)**: `remote-docs add https://code.claude.com/docs/en/changelog` is refused
on the same pattern, even with `--verbatim`. The check runs before any capture exists, so the stand-down that
`RemoteDocs.md` describes for unaltered captures never applies. This now also blocks Plan 00486 Task 1.3.

**Status**: ✅ Fixed by Plan 00492 (the owner's registry route; options (a) to (c) superseded). Both pages are now
vendored, each with its one swap recorded in its provenance.

**Owner ruling (2026-10-05):** resolved: a single registry of approved FAKE values; docs may use any listed fake, and an unlisted fake-looking value is swapped for a listed one or the list is extended. Work: plan `docs-fake-values-registry` — see [OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md) (D1).

### N308 — unguarded `;` chaining is only advised against, not blocked

**Source**: owner ruling, verbatim: "we should be blocking ; command chaining — either use set
-e and/or force && chaining".

**Evidence**: `bash_safe_mode` already implements the rule, but this repository runs it in warn
mode, scoped to mutator-bearing commands (`only_with_mutator: true`). So `cd nosuch; git commit`
and any other `;`-sequenced command run with no prelude. The coordinator's own commands drew the
advisory all session.

**Status**: ✅ Fixed (merge bf8d40aa9), then REVERSED by owner ruling A3 (2026-10-05): `only_with_mutator` is `true`
again, in the shipped default and in this repository. Historical record of the original fix follows. This repository ran
`mode: block` with `only_with_mutator: false`. A second owner ruling, verbatim: "lets make the bash strict mode
on by default - it should be harmless and provides a LOT of safety". Under it, the SHIPPED default is
now enabled and blocking: a config-changes entry, release note 215, and templates updated. The
acceptance tests follow the configured mode. Live once the daemon restarts.

**Owner ruling (2026-10-05):** reverses the second ruling above for this repository's config: `bash_safe_mode` goes back to `only_with_mutator: true` (R6) — see [OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md) (A3).

### N307 — the second commit in one command has its pathspecs left unscanned

**Source**: N299 review.

**Evidence**: when one Bash command runs two `git commit`s, only the first commit's pathspecs are
judged. A `git commit -m a x.txt && git commit -m b y.txt` never scans `y.txt` as a pathspec
commit. This was already wrong on main, and it is an ordinary shape.

**Status**: ✅ Fixed (merge 530ffc83d). The reading carries
every commit (`CommitReading.runs`), each with its own form, moves and `-a`; the gates judge every
commit's pathspecs from the directory that commit runs in (`commit_scopes`).
