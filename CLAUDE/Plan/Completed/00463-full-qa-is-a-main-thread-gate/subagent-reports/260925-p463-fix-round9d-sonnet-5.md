# Plan 00463 fix round 9d report (Sonnet 5)

Worktree: `worktree-plan-463-full-qa-gate`. Starting HEAD `497068081`. Final
HEAD `c0d202475`.

## Item 1: the coordinator's ruling on UNSEEN code (implemented)

`handle()` now only DENIES a positively SEEN full run. A script or
substitution `find_full_qa_invocation` could not resolve (`match.fail_closed`
truthy) ALLOWS, carrying an advisory (`RuleFormatter().advisory(_RULE)`,
never a "BLOCKED" headline) that names the construct and says the host-wide
full-QA lock sink will refuse or serialise the command if it turns out to
run the whole suite.

Removed: `_B1_RESIDUAL_UNSEEN`, the branching in
`test_the_repositorys_own_scripts_are_not_full_runs` /
`test_the_qa_scripts_run_as_documented_are_not_full_runs` that used
`_SCRIPTS_THAT_RUN_UNSEEN_CODE` to accept a DENY, and
`TestBinHooksDaemonIsTheB1Residual` (which pinned `bin/hooks-daemon` DENIED).
`_SCRIPTS_THAT_RUN_UNSEEN_CODE` itself stays as a documentation-only
frozenset (not asserted against anywhere) was actually fully deleted, not
kept — see the diff; its content is now prose in the class docstring above
it.

Added: `TestTheUnseenAdvisory` (pins ALLOW + advisory shape + that a
positively-seen full run still denies unchanged), and
`TestUnseenScriptsAreAllowedNotDenied` in the corpus file (keeps the
parser-level `fail_closed` proof for `bin/hooks-daemon`, adds the
decision-level ALLOW proof). `_everyday_commands()`'s script-gathering no
longer skips any script, and now also globs
`.claude/skills/*/invoke.sh`; `test_an_everyday_sub_agent_command_is_allowed`
was switched from asserting `find_full_qa_invocation(...) is None` to
asserting `Decision.ALLOW` at the handler's own `handle()` — so it now
covers UNSEEN-but-not-full-by-design scripts too, which is the "every
executable script ... is allowed unless it positively runs the whole suite"
proof the brief asked for (`bin/`, `scripts/`, `.claude/skills/*/invoke.sh`
covered; `.claude/hooks/*` were not separately enumerated -- see below).

**Backstop proof**: not newly written. `tests/unit/qa/test_full_qa_gate.py`
(round 9b, unmodified this round) already drives a REAL subprocess pytest
through a bash wrapper and a `python -c` exec wrapper -- exactly "a script
this handler cannot see" -- and asserts it is REFUSED without the lock;
`test_full_qa_lock.py::TestSecondAcquisitionIsRefused` proves a second
acquire is refused while a first holder has it. I read both in full rather
than duplicating them; they already satisfy the brief's "must be refused or
serialised by the sink" requirement for an unseen full run.

**Not done**: I did not add `.claude/hooks/*` (the daemon-generated
forwarder scripts) to the corpus. They never mention a full-QA program and
would trivially allow, so I judged the check for `bin/`/`scripts/`/skills
sufficient evidence and left this out rather than pad the corpus with
zero-signal rows. Flagging it explicitly in case the coordinator wants it
literal.

PLAN.md's "Round 9" section has a new "Round 9d: the coordinator's ruling on
UNSEEN code" paragraph recording the ruling and reasoning.

QA on touched files: ruff, black, mypy, pyright all clean. Full
`test_subagent_full_qa_blocker.py` + `..._corpus.py` +
`tests/unit/qa/test_full_qa_gate.py` + `test_full_qa_lock.py`: 1267 passed,
0 failed. Daemon restarted and verified RUNNING before the commit.

## Item 2: M7 (verified, not independently re-fixed)

Built the relay binary (`bash relay/build.sh`) and wrote a **deterministic**
probe: a fake Unix-socket server that accepts the connection, reads the
request to EOF, then never replies, paired with a short `--timeout-ms` on
the relay -- the outcome does not depend on host load, only on the
configured budget.

**Confirmed still fail-open on this branch**: a mid-exchange timeout for a
positively-seen full run (bare `pytest`) exits 0 with empty/`{}` stdout
(`relay/hooks_relay.rs`'s `mid_exchange_fail`, by design per its own doc
comment). Pinned as a permanent test,
`tests/integration/test_relay_mid_exchange_timeout_fails_open.py`, which
will fail once Plan 00466 N24's fail-closed fix lands on this branch --
deliberately, so the merge can't silently drop the finding.

**Not independently re-fixed**: N24 (a separate, much larger, already
8+-review-round-deep effort: relay binary, build/deploy pipeline, CI asset
baking) is the active fix for this exact gap, and PLAN.md's existing "Round
9" text already documents the merge-order dependency ("the plan merges
AFTER Plan 00466's N24 ledger"). A parallel fix here would fork N24's
in-flight work. Recorded the verification and reasoning in PLAN.md.

## Item 3: round 9b's "pre-existing" claims

Both claims do NOT reproduce, and neither file exists on `main` (both are
new on this branch), so "pre-existing" was not a claim provable against
`main` to begin with:

- `TestThePytestOptionGrammar::test_every_value_option_of_the_running_pytest_is_known`
  (round 9b: failed because `--max-warnings`/`--report-chars` were missing
  from `PYTEST_VALUE_OPTIONS`, "apparently from an installed pytest
  plugin's flags"): **passes** in this worktree's own fresh venv
  (`untracked/venv-workspace_untracked_worktrees_worktr-d122-py311-81c29529`)
  -- that venv's installed pytest plugins don't expose those flags, so the
  comparison has nothing to fail on. `tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker.py`
  doesn't exist on `main` (`git cat-file -e` confirms).
- `tests/integration/test_full_qa_gate_is_never_deadlocked.py` (round 9b:
  "pre-existing, left as-is"): **11 passed** in this worktree's venv.
  Doesn't exist on `main` either.

No fix needed; no commit for this item (nothing reproduced to fix).

## Commits

- `abb883197` -- "Plan 00463 round 9d item 2: M7 verified deterministically,
  still fail-open" (PLAN.md + new integration test).
- `c0d202475` -- "Plan 00463 round 9d item 1: UNSEEN code allows with an
  advisory, not a deny" (PLAN.md + handler + both handler test files).

## Left for the next round

- The `.claude/hooks/*` corpus question above (item 1's "not done" note).
- Everything round 9c already left open (the deeper "here" tracker gap for
  `bin/hooks-daemon`'s own two-hop `cd` chain) is unchanged by this round --
  it is now moot for the DENY question (UNSEEN allows either way) but still
  affects the advisory's precision (an UNSEEN script gets an advisory
  instead of silence, which is the intended behaviour either way).
- N24's fail-closed relay fix, tracked on its own branch, still needs to
  land and merge before this plan can close M7 for real.
