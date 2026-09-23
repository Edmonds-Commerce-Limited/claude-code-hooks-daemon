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

## Follow-up round: review finding + two cleanups (commit after c58cca62)

Team lead's review confirmed the mkdir claim independently and agreed the
deviation was right, then found `_daemon_clone_present()` alone still left
the harm reachable: a clone that lost `scripts/lib/resolve_venv.sh` but still
holds another view's venv under `untracked/venv-*` reads as no-clone, falls
to NOT_INSTALLED, and gets the install advice — install's `rm -rf` deletes
that venv.

### What changed

- `init.sh`
  - New helper `_daemon_orphan_venv_present()` — checks for any
    `untracked/venv-*` directory (Plan 00099's fingerprint-keyed layout),
    independent of `_daemon_clone_present`. Safe against the same mkdir side
    effect: `mkdir -p untracked/` creates an EMPTY directory, so a fresh
    checkout never has a `venv-*` entry.
  - `ensure_daemon`'s ladder: `elif _daemon_orphan_venv_present` added after
    the `_daemon_clone_present` branch, before the `NOT_INSTALLED` fallback.
    When only the orphan-venv signal fires (no confirmed real clone),
    `_HOOKS_DAEMON_VENV_MISSING_VERSION` is set to `""` unconditionally —
    `_clone_version` is never even attempted. This was a deliberate choice,
    not a default: without `resolve_venv.sh`, the clone is not trusted
    enough to say which of its other files are intact, so the message always
    reads as "damaged clone" rather than risking a version-pinned upgrade
    command built from a file that happened to survive. Matches the lead's
    stated lean, taken as the decision rather than left as a coin flip.
  - The `VENV_MISSING` branch's "version could not be determined" remedy
    text was widened to name BOTH root causes (`version.py` unreadable, OR
    `resolve_venv.sh` itself missing) — the old wording named only the
    first, which would have been an overclaim in the new orphan-venv-only
    path (exactly the paths.py N17 mistake the lead flagged not to repeat).
  - Comments updated throughout (flag declaration, ladder, message branch)
    to describe both discriminators instead of one.
  - New comment on `_daemon_orphan_venv_present`'s glob loop:
    `# canonical-resolver-exempt: ...` — unplanned, found by QA (below), not
    by the review. `scripts/qa/check_canonical_callers.sh` (Plan 00104 Phase
    6\) statically forbids any `for x in .../untracked/venv-*` loop outside
    `scripts/lib/resolve_venv.sh` unless it delegates to
    `resolve_venv_python()` or carries this marker. Delegating doesn't fit:
    `resolve_venv_python()` answers "is there a WORKING interpreter",
    whereas this function deliberately answers "does ANY venv-\* directory
    exist" — a broken/partial venv-\* that `resolve_venv_python()` would
    reject still holds bytes `rm -rf` would destroy, so delegating would
    under-detect the exact case the function exists to catch. Documented
    inline with that reasoning rather than just silencing the check.
- `tests/integration/test_init_sh_venv_missing_message.py`
  - Cleanup 2: removed the dead `_rc()` helper (copied from
    `test_init_sh_stale_clone_version.py`, never called here).
  - Cleanup 3: `test_both_encoders_produce_the_same_pretooluse_answer`'s
    function-local `import pytest` + manual skip replaced with a top-level
    `import pytest` and `@pytest.mark.skipif(shutil.which("jq") is None, ...)`.
  - New fixture `_project_with_orphan_venv()` — a clone dir with an
    `untracked/venv-other-view/bin/python` placeholder and deliberately NO
    `scripts/lib/resolve_venv.sh`, optionally with a readable `version.py`.
  - 4 new tests: ladder wiring for the orphan-venv case, a companion control
    (fresh checkout has no `venv-*` either), and two message tests — one
    pinning "never recommends install" with a stronger assertion than the
    existing ones (see RED evidence below for why), one pinning "gets the
    damaged-clone message even when a version happens to read".

### RED evidence

`pytest tests/integration/test_init_sh_venv_missing_message.py -q`, new tests
added, `init.sh` unchanged from c58cca62:

```
FAILED ...test_an_orphaned_venv_with_no_resolve_venv_sh_still_sets_the_new_flag
  assert 'venv_missing=true not_installed=false' in 'venv_missing=false not_installed=true\n'
FAILED ...test_an_orphaned_venv_never_gets_the_install_advice
  assert 'args=install' not in '{...}'
  'args=install' is contained here:
    s-daemon, args=install)\n\nafter installing, restart your claude session for hooks to activate."
2 failed, 18 passed in 1.05s
```

Worth noting: my first draft of `test_an_orphaned_venv_never_gets_the_install_advice`
used the same weak `"do not" in context` pattern as the earlier round's
tests, and it PASSED on the buggy code — because NOT_INSTALLED's own message
contains the phrase "do not improvise" while still recommending install. That
would have been a false-green RED phase. Caught before running by re-reading
the existing message text, tightened to assert `"args=install" not in context` (the actual thing that must never appear) before running the
checker at all — so the failure output above is from the corrected version.

### GREEN result

```
tests/integration/test_init_sh_venv_missing_message.py: 20 passed in 1.01s
tests/integration/test_canonical_callers_static_check.py: 3 passed
```

Plus the same regression sweep as the first round, all still green:
`test_init_sh_stale_clone_version.py`, `test_not_installed_fallback_names_the_checkout.py`,
`test_ci_passthrough.py`, `test_relay_guard_fail_open.py`,
`test_relay_guard_foreign_checkout.py`, `test_forwarder_jq_free.py`,
`test_forwarder_generator_raw_stdout.py` — 124 passed, 3 skipped (relay
binary not built on this machine, pre-existing and unrelated).

`bash -n init.sh`, `shellcheck init.sh`, `black --check` on the test file:
all clean.

### QA_EXIT

Ran full QA three times this round, daemon restarted before each:

1. `QA_EXIT=1`, 33/35 — `canonical_callers: 1 violation` (`init.sh`, my new
   glob loop, described above) plus its two static-check tests failing as a
   consequence. Fixed with the exempt-marker comment.
2. `QA_EXIT=0`, 35/35, after the fix — confirmed clean, daemon running
   throughout, no daemon-not-running flake this time (unlike the first
   round's transient one).
3. `QA_EXIT=0`, 35/35, repeated once more after a final daemon restart
   immediately before committing, per the daemon-restart-before-commit
   convention.

```
QA: 35/35 PASSED
QA_EXIT=0
```

### Disagreement check for this round

None — the review finding was correct and reproducible (confirmed by
re-deriving the mkdir-side-effect argument myself before touching code), and
the "always show the damaged message when resolve_venv.sh is missing" lean
was adopted as-is rather than the alternative (attempt `_clone_version`
regardless) because it removes a genuine ambiguity at no real cost: the
version-pinned-upgrade command is only ever safe to hand out when the clone
that would run it is already trusted.

## Round 3: pin the headline case with a strong assertion, prove it discriminates

Team lead's third review confirmed the code from round 2 (the orphan-venv
glob, the errexit-safety, the canonical-resolver-exempt marker against
`install.sh:116`'s precedent, the printf arg count) and found one remaining
gap — in the tests, on the case #53 is actually about.

### The gap

`test_it_explicitly_warns_against_install` (the PRIMARY case: a real clone,
a readable version — the everyday second-bind-mounted-view scenario) asserted
only `"do not" in context or "not use" in context or "never" in context`. That
is satisfied by NOT_INSTALLED's own message ("do not improvise") even while
NOT_INSTALLED recommends installing — so a regression that put `args=install`
back into the readable-version VENV_MISSING remedy would pass the WHOLE
suite, including the test whose name claims it guards against exactly that.
Two more tests (`test_an_unreadable_version_still_gets_a_safe_message_not_a_blank`,
`test_an_orphaned_venv_gets_the_damaged_clone_message_even_when_a_version_reads`)
carried the same weak shape.

### What changed

- `tests/integration/test_init_sh_venv_missing_message.py` — added
  `assert "args=install" not in context` to all three tests above, alongside
  the existing weaker checks (kept for readability, per the request). No
  `init.sh` change — the review found a test gap, not a code gap.

### Proof the strengthened assertions discriminate

Per the request, this was proved by TEMPORARILY regressing `init.sh` rather
than trusting the assertion by inspection.

1. Confirmed GREEN on current code first (the strengthened assertions do
   not themselves break anything):

   ```
   tests/integration/test_init_sh_venv_missing_message.py: 20 passed in 0.86s
   ```

2. Added a one-line `args=install` probe to BOTH branches of the
   `_hd_venv_missing_remedy` selection in `init.sh` (the readable-version
   branch and the damaged-clone branch — the orphan-venv test always takes
   the damaged-clone branch by construction, so both needed the probe to
   exercise all three tests). Ran the three targeted tests and got RED:

   ```
   FAILED ...test_it_explicitly_warns_against_install
     assert 'args=install' not in '{\n  "hooks...l"\n  }\n}\n'
     'args=install' is contained here:
       s-daemon, args=install"
   FAILED ...test_an_unreadable_version_still_gets_a_safe_message_not_a_blank
     assert 'args=install' not in '{\n  "hooks...l"\n  }\n}\n'
     'args=install' is contained here:
       s-daemon, args=install"
   FAILED ...test_an_orphaned_venv_gets_the_damaged_clone_message_even_when_a_version_reads
     assert 'args=install' not in '{\n  "hooks...l"\n  }\n}\n'
     'args=install' is contained here:
       s-daemon, args=install"
   3 failed, 17 deselected in 0.30s
   ```

   All three failed on exactly the injected line, confirming the strong
   assertion is what catches the regression the weak one missed.

3. Reverted the temporary `init.sh` change. `git diff init.sh` showed zero
   lines — byte-identical to the a951f210 commit, so nothing temporary was
   left in the tree. Re-ran the full file:

   ```
   tests/integration/test_init_sh_venv_missing_message.py: 20 passed in 0.84s
   ```

`bash -n init.sh`: clean throughout (checked before and after the temporary
edit and after the revert).

### QA_EXIT

Full QA run, daemon restarted immediately before:

```
QA: 35/35 PASSED
QA_EXIT=0
```

Daemon restarted again immediately before this round's commit.

### Disagreement check for this round

None — the gap was real and the fix the lead asked for (strengthen the
assertion in place, prove it with a temporary regression, revert) is exactly
what a test whose name makes a safety claim needs to actually make it.
