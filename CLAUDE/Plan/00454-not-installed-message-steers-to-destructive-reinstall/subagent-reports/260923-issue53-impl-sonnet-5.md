# Issue #53 implementation report — Sonnet 5 subagent

**Plan**: 00454
**Worktree**: `untracked/worktrees/worktree-issue-53-venv-missing-message/`
**Model**: claude-sonnet-5 (Sonnet 5)

## What changed

- `init.sh`
  - New flags `_HOOKS_DAEMON_VENV_MISSING` / `_HOOKS_DAEMON_VENV_MISSING_VERSION`,
    declared next to the existing `_HOOKS_DAEMON_*` flags (initialised under
    `set -u`, same pattern as the others).
  - New helper `_daemon_clone_present()` (see "What I found that the brief
    didn't say" below — this is the one real deviation from the brief).
  - `ensure_daemon()`'s diagnosis ladder: between `_detect_stale_clone` and
    the fallback to `NOT_INSTALLED`, a new branch fires when
    `_is_daemon_installed` failed AND `_daemon_clone_present` is true. Sets
    `_HOOKS_DAEMON_VENV_MISSING=true` and reads the clone's own version via
    `_clone_version()`, tolerating a read failure explicitly (`if ! X="$(...)" ; then X=""; fi` — not `|| true`, which `error_hiding_blocker` denies on
    Write/Edit anyway) rather than falling through to `NOT_INSTALLED`.
  - `emit_hook_error()`: new `VENV_MISSING` branch in the `context_msg`
    selection (between `REPO_UNCONFIGURED` and `NOT_INSTALLED`), a new `jq`
    branch (between `CI_ENFORCED` and `NOT_INSTALLED`), and a new branch in
    the jq-less `python3 -c` fallback (`venv_missing` added as a 6th
    positional arg). Both encoders covered and pinned equal by a test.
  - Message content: says the clone is present, explicitly says NOT to use
    install/force and why (`rm -rf` on the whole directory, deleting another
    environment's venv), and names the remedy as
    `Skill tool: skill=hooks-daemon, args=upgrade <clone version>` when the
    version is readable, or a "clone looks damaged, ask a human" message when
    it is not (never a blank version, never a silent fall-through).
  - Stop/SubagentStop get a distinct `decision: block` reason mentioning
    "venv" and explicitly not containing the substring `"not installed"`, so
    it cannot be mistaken for the plain not-installed block.
- `tests/integration/test_init_sh_venv_missing_message.py` — new file, 16
  tests across `TestEnsureDaemonWiresItUp` (ladder wiring, including the
  version-mismatch-wins-over-venv-missing ordering control and the
  fresh-checkout control), `TestTheMessage` (content, including the
  unreadable-version case and valid-JSON), `TestTheStopFamilysBlock`, and
  `TestTheEncodersAgree` (jq vs python3-fallback, both directions).
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/01-the-not-installed-message-no-longer-points-at-rm-rf-when-a-clone-shares-a-mount.md`
  — new callout, operators audience, names the `_daemon_clone_present`
  discovery explicitly since it is the load-bearing detail an operator
  reading the diff would otherwise have to re-derive.
- `CLAUDE/Plan/00454-.../PLAN.md` — Phase 1 tasks (1.1–1.4) checked off.

**Not touched**: `install.sh`, the skill's `install.sh`, `upgrade_version.sh`,
`VERSION_MISMATCH`/`REPO_UNCONFIGURED`/`CI_ENFORCED` bodies or precedence,
`test_ci_passthrough.py` (ran unmodified, still green).

## What I found that the brief didn't say — and had to fix

**The brief's exact discriminator ("directory present") does not hold.**
Verified by direct reproduction before writing any fix: `init.sh` itself
unconditionally does

```
_untracked_dir="${HOOKS_DAEMON_ROOT_DIR}/untracked"
[[ -d "$_untracked_dir" ]] || mkdir -p "$_untracked_dir"
```

on every source — so `HOOKS_DAEMON_ROOT_DIR` exists after `init.sh` has been
sourced even once, on a genuinely fresh checkout with no clone at all. A bare
`[[ -d "$HOOKS_DAEMON_ROOT_DIR" ]]` check (what the brief specified) therefore
cannot distinguish "no clone" from "clone present, venv missing" — it is true
in both, and using it as written would have made every fresh checkout report
`VENV_MISSING` instead of `NOT_INSTALLED`, which is the opposite of Goal 3
("A genuinely absent clone is unchanged").

I found this because my first GREEN attempt (bare `-d` check) made
`test_no_clone_at_all_is_still_not_installed_unchanged` fail with
`venv_missing=true not_installed=false` — reproduced directly with a plain
`bash -c 'source init.sh; ...'` outside pytest to rule out a test-fixture bug
before changing the implementation.

**Fix**: added `_daemon_clone_present()`, which checks for
`$HOOKS_DAEMON_ROOT_DIR/scripts/lib/resolve_venv.sh` instead of the bare
directory. That file ships with a real clone, nothing else creates it, and it
is already the exact path `_resolve_python_cmd()`'s own failure message names
("Reinstall the daemon so scripts/lib/resolve_venv.sh is present") — so it is
not a new concept, just reusing an existing "this is a real clone" signal.
This is a genuine deviation from the brief's wording, flagged per the
"permission to disagree" note — I believe the brief's intent (distinguish a
real clone from a fresh checkout) is unchanged; only the mechanism had to
change, because the literal mechanism specified doesn't work post-source.

The test fixture (`_project()`) was updated to also create this marker file,
and the "no clone at all" control test deliberately does NOT create it —
which is what makes that test an accurate regression pin for the discovery
above (it exercises exactly "directory exists via the mkdir -p side effect,
but no real clone marker").

## RED evidence

Command: `pytest tests/integration/test_init_sh_venv_missing_message.py -q`,
run with the new test file in place but before any `init.sh` change:

```
FAILED ...test_clone_dir_present_no_venv_sets_the_new_flag_not_not_installed
  AssertionError: bash: line 7: _HOOKS_DAEMON_VENV_MISSING: unbound variable
  assert 'venv_missing=true not_installed=false' in ''
FAILED ...test_it_names_the_version_pinned_upgrade_not_install
  assert 'upgrade' in '{...(the plain NOT_INSTALLED message)...}'
FAILED ...test_stop_blocks_and_does_not_say_plain_not_installed
  AssertionError: assert 'venv' in 'hooks daemon not installed at
  /tmp/.../project - protection not active'
13 failed, 3 passed in 0.71s
```

(13 of 16 failed for the right reason — unbound variable / plain
NOT_INSTALLED fallback; the other 3 that passed were incidental, e.g. the
version-mismatch-wins ordering test, which happened to pass because
`_detect_stale_clone` already ran first and both flags were false.)

## GREEN result

After the fix (including the `_daemon_clone_present` correction above):

```
tests/integration/test_init_sh_venv_missing_message.py: 16 passed in 0.75s
tests/integration/test_init_sh_stale_clone_version.py: all passed (unchanged)
tests/integration/test_not_installed_fallback_names_the_checkout.py: all passed (unchanged)
tests/unit/test_ci_passthrough.py: all passed (unchanged)
tests/integration/test_relay_guard_fail_open.py,
tests/integration/test_relay_guard_foreign_checkout.py,
tests/integration/test_forwarder_jq_free.py,
tests/unit/install/test_forwarder_generator_raw_stdout.py: all passed (ran as
  an extra sweep — these are the other files that reach `ensure_daemon`)
```

`bash -n init.sh` and `shellcheck init.sh`: both clean. (One self-inflicted
bug along the way: an apostrophe in a comment inside the `python3 -c '...'`
single-quoted block broke out of the quoting and produced a bash syntax
error — caught immediately by `bash -n`, fixed by rewording.)

## QA_EXIT

First full run (`./scripts/qa/llm_qa.py all`) came back `QA_EXIT=1`,
`33/35 PASSED`:

- `format`: 1 file (`test_init_sh_venv_missing_message.py`) needed
  reformatting — black auto-fixed it in place during that same run;
  `black --check` on the file afterward reports it unchanged.
- `tests`: 10 errored (not failed) — all `ERROR at setup of ...` in
  `test_playbook_harness.py`, `test_stop_hook_hard_block.py`,
  `test_tool_use_error_recovery.py`. The actual error text (read from
  `untracked/qa/tests.json.raw`, since this venv lacks `pytest-json-report`
  and QA fell back to its text-output parser) was a release-gate fixture
  refusing a skip: `"Daemon not running — no live socket found under untracked/. Start it with: ./bin/hooks-daemon restart"` — this self-install
  worktree's own live daemon simply was not running yet when QA started; it
  has nothing to do with `init.sh`'s diagnosis logic (these tests dispatch
  through a REAL running daemon on the happy path, a code path this change
  never touches). Confirmed unrelated three ways: (1) all 10 pass in
  isolation and together before touching the daemon; (2) `./bin/hooks-daemon restart` then rerunning the same 10 makes them pass; (3) a second full
  `llm_qa.py all` run after the restart is fully green.

Second full run, daemon running throughout, exit code captured properly this
time (`echo "QA_EXIT=$?" >> ...` on the same backgrounded command, not a
separate shell call afterward):

```
QA: 35/35 PASSED
QA_EXIT=0
```

## Disagreements / things I changed my mind about mid-task

1. **The discriminator** — covered above. I believe I found a real bug in the
   brief's proposed mechanism, not a disagreement with its intent.
2. Everything else in the brief (message content requirements, the two
   encoders, Stop/SubagentStop handling, the flag-init-under-`set -u`
   warning, not touching install.sh/upgrade scripts) held up as written —
   no other deviations.
