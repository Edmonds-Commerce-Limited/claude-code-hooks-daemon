# Plan 00463 fix round 9c report (Sonnet 5)

Worktree: `worktree-plan-463-full-qa-gate`. Starting HEAD `0303952d4`. Final
HEAD `8c2dbd8d3`.

## Item 1: the B1 residual is not accepted

Done, partially -- see PLAN.md's updated "B1 residual" note for the full
account. Summary:

- Implemented `_with_resolved_symlink_source`/`_is_self_readlink_reassignment`
  in `subagent_full_qa_blocker.py`: recognises the
  `while [ -L "$VAR" ]; do ... readlink ...; done` self-location loop
  STRUCTURALLY (condition + body signature), removes it, and substitutes
  every later reference to its variable with `os.path.realpath(script)`.
  A look-alike loop whose body reassigns the variable some other way is left
  untouched (stays unseen, proven by a dedicated test).
- Implemented `_BASH_SOURCE_DIRNAME_TRIM`: resolves `${BASH_SOURCE[0]%/*}`
  (the coreutils-free dirname spelling used by `scripts/lib/resolve_venv.sh`
  and others) the same way `$(dirname "${BASH_SOURCE[0]}")` already was.
- Both are proven by new tests: `TestSelfLocationSymlinkLoopIsResolved`
  (three cases: benign sourced file allowed, full-suite sourced file still
  caught, look-alike loop still denied) and
  `TestBashSourceDirnameTrimIsResolved`, in
  `tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker.py`.

**What this does NOT fix**: `bin/hooks-daemon` itself, and every repo script
that shells out to it (`run_canonical_callers_check.sh`,
`run_semgrep_check.sh` via `resolve_venv.sh`, `check_generated_doc_drift.py`
via a docstring mention misread as an invocation), remain DENIED -- now for
a DIFFERENT, narrower reason than the loop: `bin/hooks-daemon` builds
`DAEMON_DIR` from `BIN_DIR` via a SECOND `cd` inside a nested `$(...)`
substitution (`DAEMON_DIR="$(cd -P "$BIN_DIR/.." && pwd)"`), and this
handler's nested-substitution recursion has no visibility into `BIN_DIR`'s
own top-level assignment earlier in the SAME script -- so the "here" (cwd)
this handler tracks goes opaque before `source "$RESOLVE_LIB"` (further down
the same script) is reached, and the file resolve_venv.sh sources
(`python_discovery.sh`) is judged unseen.

I attempted a fix (threading the enclosing script's own variables into the
nested `_invocations()` recursion via a new `outer` parameter). It DID fix
`run_canonical_callers_check.sh`'s own two-hop `SCRIPT_DIR`/`PROJECT_ROOT`
chain (proven: went from denied to allowed). But it also newly denied
`scripts/qa/run_smoke_test.sh`, which was previously ALLOWED only because
`${PROJECT_ROOT}/bin/hooks-daemon` stayed a wholly opaque word (treated
leniently as "absent", never read) -- making `PROJECT_ROOT` resolvable
exposed `bin/hooks-daemon`'s content to being read, which then hit the SAME
underlying "here" gap. Net: one script fixed, one new regression, with no
guarantee no OTHERS exist across the repo (I could only spot-check a
handful). Reverted rather than ship an unverified net change; confirmed by
re-running the full unit + corpus suite (1232 passed) with the revert in
place -- zero regressions from the two idiom fixes alone.

`_B1_RESIDUAL_UNSEEN`, `_SCRIPTS_THAT_RUN_UNSEEN_CODE` and
`TestBinHooksDaemonIsTheB1Residual` are all updated (not removed) to name
the CURRENT cause, not the old one. `run_semgrep_check.sh` has its own
additional, separate reason: it builds its program path by calling a bash
FUNCTION (`resolve_venv_python`), genuinely uncomputable without running it.

**Follow-up needed** (not done, sits in code this round touched, so per the
owner's rules it is not a closable residual): give the "here" tracker
visibility into a script's own top-level variable assignments when walking
a `cd` inside a nested `$(...)` substitution of THAT SAME script, without
reintroducing the `run_smoke_test.sh` regression -- likely needs
branch-aware modelling (the `if`/`case` around `bin/hooks-daemon`'s
client-install detection is processed unconditionally, "no branch
awareness", same root class as the loop this round fixed but for `if`, not
`while`).

QA on touched files: ruff, black (reformatted, applied), mypy, pyright all
clean. Full `test_subagent_full_qa_blocker.py` +
`test_subagent_full_qa_blocker_corpus.py` run: 1232 passed, 0 failed.
Daemon restarted and verified RUNNING before the commit.

## Item 2: M7 (PreToolUse chain timeout fail-closed check)

Not started -- ran out of context budget after item 1's investigation (the
B1 residual required much deeper tracing than the brief's technical
direction anticipated, to avoid shipping either an incomplete fix or an
undiscovered regression). Left for the next round.

## Commit

`8c2dbd8d354eb35b80d7b53f8f71bdb004fa26f5` -- "Plan 00463 round 9c item 1:
resolve the self-location symlink loop and BASH_SOURCE trim idiom".
