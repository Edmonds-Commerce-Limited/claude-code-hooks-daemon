# Plan 00625 adversarial review (security and correctness)

Reviewed branch `agent-a5947fd1e83f03452-ba288018` at `1ea9aa161` against
`main`, working from `git diff main...HEAD` rather than the builders' reports.
The reproducers are under `untracked/scratch/rv625/`, which is not tracked, and
each one is described below so it can be rebuilt. Nothing was run against a real
checkout or a real remote. Python tests were run in targeted files only.

## Verdict: FAIL

Two defects in the lock (F1, F2) break the plan's central promise that no two
processes ever modify the daemon checkout at once. Neither is a small patch. Each
needs a design decision on a primitive that is carried byte-identical in two
scripts, so I have reported them and not fixed them. I fixed three smaller
defects (F3, F4 and F5) test-first. F5 was a third way for two processes to hold
the lock at once. Everything else is a minor finding, a residual risk, or an
owner decision.

**What "reproduced" means here.** A finding marked REPRODUCED was demonstrated
by a run. Anything else marked "by reading" was reasoned from the code and was
not run: M1, the two extra routes into F1, the SIGKILL and cross-namespace
expiry routes in F2, M7, M11, M12 and the `lock.d` gap.

## Defects

### F5 MAJOR (fixed, RED then GREEN, REPRODUCED): two holders when /proc belongs to another pid namespace

This happens in a pid namespace whose `/proc` was never remounted, such as
`unshare -p` without `--mount-proc` and some container setups. There `$$` is a
small pid of the new namespace, but `/proc` answers for the parent namespace.
`readlink /proc/self/ns/pid` still reports the new namespace, so two processes
in it judged each other "same boot, same namespace" and trusted `/proc/<pid>`.
When the parent namespace had no process at the holder's pid, the record's
`pid_start` was empty, and a second process judged the **live** holder dead and
took the lock as well.

- **Reproducer** (`same_ns_live.sh` under `unshare -U -r -p -f`): output
  `GOT 4` and then `GOT 32` while 4 was still holding.
- **Fix:** a new `_upgrade_lock_pidns` helper returns the namespace only when
  `/proc/self/stat` names this shell's own `$BASHPID`, meaning `/proc` vouches
  for pids here. Otherwise it returns empty, and the judge falls back to the
  expiry rule.
  - The same-namespace path also now requires a non-empty `pid_start`.
  - The change is applied to both scripts, and the lockstep holds.
- **Test:** `TestAProcThatIsNotThisNamespaces` in
  `tests/integration/test_upgrade_lock.py`. It needs unprivileged pid
  namespaces and skips otherwise. It failed before the fix (`second rc=0`).
  The whole file passed after it, 31 tests.
- **Real separate pid namespaces (REPRODUCED, holding):** a holder in its own
  namespace caused `MISS` both from the host and from a second namespace. A
  holder SIGKILLed in the same namespace was taken over at once, which is
  correct. `--mount-proc` is not permitted on this host, so a properly remounted
  namespace was not exercised.

### F1 BLOCKER (not fixed, REPRODUCED): a stale takeover file lets two processes hold the lock

`_upgrade_lock_takeover` breaks a `<lock>.takeover` file that is older than 60 s.
It checks the file's mtime and then removes it by path (`rm -f "$_take"`). Take
two contenders that both read the old mtime. The first removes the file and
creates its own fresh one. The second then removes the first one's fresh file
and creates its own. Both are now inside the section that is supposed to be
serialised. Both re-read the dead token and run `rm -f "$_lock"`, and both
create the lock in turn. The second removes the first one's new lock before
creating its own. Each process believes it holds the lock.

- **Reproducer** (`race_takeover.sh` + `acq.sh`): a lock whose record names a
  dead pid in this boot and pid namespace, and a `.takeover` file backdated
  120 s. That is the state a taker leaves when it is killed inside its critical
  section. Then 20 concurrent acquirers each hold for 2 s. **Result: 7 of 15
  trials had two simultaneous holders.** With no stale takeover file, double
  holders were not reproduced in 10 trials. That is not proof that it cannot
  happen.

- **The same hole has other routes:** an mtime that looks more than 60 s old
  because of clock or mtime skew (NFS), or a taker that is SIGSTOPped for more
  than 60 s while it holds the takeover file and then resumes.

- **Fix direction (needs a design decision):** any scheme that judges a file by
  its content or mtime and then removes it by path keeps this hole. The only
  compare-and-swap primitive available here is the exclusive create.

  - A plausible route is generation-numbered takeover files
    (`<lock>.takeover.<N>`). A taker creates generation N+1 with O_EXCL. It
    proceeds only while its own generation is the highest that exists. It never
    removes another process's takeover file.
  - Whatever is chosen needs its own race test with a stale generation present.

- **The current race test cannot catch this.**
  `test_exactly_one_of_many_takes_over_a_dead_holders_lock` never seeds a stale
  takeover file.
  `test_a_stale_takeover_file_is_cleared_and_a_fresh_one_is_respected` tests
  only one process.

- **Reproducer, as run.** `acq.sh` sources the block lifted from `upgrade.sh`:

  ```bash
  . lockblock.sh; rc=0
  _upgrade_lock_acquire "$1" test 0 || rc=$?
  if [ "$rc" -eq 0 ]; then echo "GOT $$ $(date +%s.%N)" >> "$3"; sleep "$2"
      echo "REL $$ $(date +%s.%N)" >> "$3"; _upgrade_lock_release
  else echo "MISS $$ rc=$rc" >> "$3"; fi
  ```

  Setup for each trial: write a record with `pid=999999`, this host's `boot_id`
  and `pidns`, and `started=now`. Then run
  `echo crashed > LOCK.takeover; touch -d '-120 seconds' LOCK.takeover`. Start
  20 copies of `acq.sh LOCK 2 LOG &` and compute the maximum overlap of the
  GOT/REL intervals.

### F2 MAJOR (not fixed, REPRODUCED for SIGTERM): the lock is released while Layer 2 is still writing

Liveness is keyed to the pid of Layer 1 (`upgrade.sh`). The writer is Layer 2
(`upgrade_version.sh`), which runs as a child.

- **SIGTERM to Layer 1 alone** runs its EXIT trap, which releases the lock at
  once while Layer 2 keeps running.
- **Reproducer** (`term_parent.sh`): the holder takes the lock, starts a 6 s
  child and receives SIGTERM. 1.5 s later the lock file is gone, the child is
  still running, and a second acquirer takes the lock and reports `GOT`.
- **SIGKILL or an OOM kill** of Layer 1 opens the same hole, and no trap can
  cover it: the pid is gone, the holder is judged provably dead, and the lock is
  taken over.
- **Across pid namespaces**, the heartbeat also dies with Layer 1, so the lock
  expires after 600 s whether or not Layer 2 has finished.
- **Fix direction:**
  - Layer 1 could trap TERM, INT and HUP, forward the signal to the Layer 2 child
    and wait for it before releasing (Layer 2 would run as a background job that
    is `wait`ed on).
  - For SIGKILL, Layer 2 could take over the lock record itself, by writing its
    own pid as an extra owner that the judge also checks, or Layer 2's pid could
    be recorded in the lock.
  - Both are changes to shared design, so they belong to the owner or builder.

### F3 MINOR (fixed, RED then GREEN): the opt-out failed open

`_entry_state` and `auto_upgrade_authorised` treated only a YAML boolean `false`
as the opt-out. All of the following left automatic upgrades **on**, with no
signal to anyone:

- `enabled: "false"` (quoted), `"False"`, `0`, `null`
- an entry with no `enabled` key
- a handler-level `enabled: "false"`
- `authorisations` written as a mapping (`{daemon-auto-upgrade: false}`)

The builders' tests pinned this behaviour (`test_non_boolean_enabled_leaves_the_default`,
`test_malformed_authorisations_leave_the_default`). For an opt-out, failing open
is the wrong direction.

- **Fix:** an entry that names the default-on id counts as a recorded request
  only when it says exactly `enabled: true`. Any other value is OFF. A
  wrong-shaped `options` or `authorisations` value, or a handler `enabled` that
  is not exactly `true`, means not authorised.
- **Files:**
  - `src/claude_code_hooks_daemon/handlers/user_prompt_submit/standing_authorisations.py`
  - `tests/unit/handlers/user_prompt_submit/test_standing_authorisations.py`
    (the two old tests are replaced by parametrised RED tests)
- **Result:** 14 tests failed before the fix, and 119 passed after it across the
  standing-authorisations, auto_upgrade and version_check auto-upgrade test
  files.
- **Residual:** a malformed `authorisations` value is now NOT authorised for the
  upgrade. However, the handler's own injected text still reads `self._authorisations`.
  How `configure` coerces a non-list there is not checked, so in that one case
  the injected text could still say "shipped default". Upgrades fail closed
  either way.

### F4 MINOR (fixed, RED then GREEN): `--lock-wait=08` crashed

The argument check accepts any string of digits, and bash arithmetic reads a
leading zero as octal. As a result, `08` and `09` died with
`value too great for base`.

- **Fix:** `_wait=$((10#$_wait))` inside `_upgrade_lock_acquire`, applied to
  both `scripts/upgrade.sh` and `provision.sh`. `.claude/provision.sh` is a
  symlink to `provision.sh`, so it picks up the change. The lockstep test still
  holds.
- **Test:** `TestWaitSecondsAreDecimal` in `tests/integration/test_upgrade_lock.py`.
  It failed for `08` before the fix.

## Minor findings and residual risks (not fixed)

- **M1, the target is the highest local tag, not the release the notice saw.**
  - `upgrade.sh` with no VERSION picks
    `git tag --list 'v[0-9]*' --sort=-v:refname` in the clone. `fetch --tags --force` never prunes, so a tag that was yanked (deleted) upstream after a
    client fetched it is still installed.
  - Example: the remote's latest is v3.79.0 and the local clone holds a yanked
    v3.80.0. `version_check` invites an upgrade to "3.79.0", and the unattended
    run installs v3.80.0.
  - Suggested fix: when `--unattended`, require the target tag to exist on
    origin (`git ls-remote --exit-code --tags origin refs/tags/$TARGET_VERSION`),
    or have the notice pass the exact version.
- **M2, pre-release tags.** Git's version sort ranks `v3.78.0-rc1` above
  `v3.77.0`; I confirmed this in a scratch repo.
  - The unattended run fails closed: the target is not plain X.Y.Z, so it exits
    5\. `check_eligibility` also refuses ("cannot be compared").
  - Behaviour that already existed before this branch: an rc tag at the top
    makes `version_check` see the newest version as not comparable, which hides
    the real release from everyone.
  - The project publishes no such tags today.
- **M3, a refusal from Layer 1 itself writes no attempt record.** This covers
  every `_needs_human` and `_fail` path before Layer 2, and a kill in the middle
  of a run.
  - The Python pre-check knows only about release-state, the major bump and the
    record. So a dirty tree, a target without unattended support, an unreadable
    installed version or a pre-release target is invited again on every new
    session, and each time it fails closed (exit 5). That costs one agent turn
    per session but changes nothing.
  - This matches DESIGN section 8, which is deliberate, but the per-session cost
    is not stated there.
- **M4, `upgrade.sh --unattended` does not check whether automatic upgrade is
  authorised.** It does not read the opt-out and does not refuse self-install.
  - Only the Python notice checks either.
  - An agent can therefore run `--unattended` in an opted-out project (for
    example, under instructions from injected content), but that gains nothing
    over the attended route, which it could run anyway, and `--unattended`
    adds only refusals.
  - Downgrades are refused, and so are `--release`, `--uv` and branch installs.
- **M5, the authorisation notice can survive when its injected text is hidden.**
  `handlers.user_prompt_submit.disable_tags: [advisory]` disables
  `standing_authorisations` (it is tagged advisory), but
  `project_authorises_auto_upgrade` reads only the handler's own block. The
  SessionStart notice therefore still says "AUTO-UPGRADE AUTHORISED ... This
  project's standing authorisation covers it". The notice does name the opt-out,
  so the agent is still told how to switch it off.
- **M6, a release-state symlink.** `[ -e release-state.json ]` is false for a
  dangling symlink. This is not a realistic attack, because anyone who can plant
  one can already write to the repository.
- **M7, the lock file in the git directory (not exploitable here).**
  - With bash noclobber, an existing non-regular file such as a symlink to
    `/dev/null` is opened without O_EXCL. So a lock path symlinked to
    `/dev/null` lets every caller "acquire" the lock, and a FIFO at that path
    hangs every caller.
  - Both need write access to `.git`, which is already full compromise, and the
    git directory is not world-writable.
- **M8, the lock covers too much across worktrees.** Lock scope is the
  project's git common directory. Worktrees that each have their own daemon
  clone are serialised against each other. This is safe, only slower.
- **M9, the rollback proof uses stubs.** `test_upgrade_unattended_rollback.py`
  asserts markers printed by a stubbed snapshot restore and a stubbed restart.
  No test shows the daemon checkout back on the old tag with the old daemon
  running after a real failure in Step 15 or Step 16. DESIGN section 11 says so
  honestly.
- **M10, a fresh install's text claims a request nobody made (confirmed by
  reading).** `.claude/hooks-daemon.yaml.example` lists
  `{id: daemon-auto-upgrade, enabled: true}`, and `install_version.sh` copies
  the example to make a fresh project's config (`cp "$EXAMPLE_CONFIG" "$TARGET_CONFIG"`). Every fresh install therefore gets the RECORDED wording,
  "STANDING AUTHORISATION (on file for this project) ... This request is
  recorded in ...", although the project recorded nothing. That contradicts the
  honesty rule the plan wrote for itself (Decision 3).
  - Fix options for the OWNER: drop the entry from the example, which leaves the
    shipped-default wording; or ship it commented out; or ship it as
    `enabled: false`.
  - Config preservation on upgrade could carry the new example default into
    existing configs too. That was not verified.
- **M11, local changes in the daemon clone are discarded unattended (by
  reading).** The dirty check reads only the project. Step 6 runs
  `reset --hard` on the gitignored daemon clone, which discards any local edits
  in it with no refusal. The attended route already does this, but unattended
  nobody sees it.
- **M12, the `FROM_VERSION` stamp lets Layer 1 accept a major jump (by
  reading).** When the tracked `.claude/HOOKS-DAEMON.md` stamp is newer than
  the clone (for example a teammate committed `(v4.0.0)` while this clone is on
  3.x), Layer 1 takes FROM from the stamp. Its MAJOR check then passes for a 4.x
  target.
  - The Python pre-check compares the running `__version__`, so it still
    refuses and the agent is not invited.
  - This is a gap in defence in depth, and arguably the team already chose the
    major version.

## Lock properties checked and holding (as far as tested)

- **Free lock:** with 20 racers, exactly one wins (the builders' test, and my
  10 trials with no stale takeover file).
- **Same boot and pid namespace:** a dead pid or a reused pid is taken over; a
  live pid is held for ever. A SIGSTOPped holder is still alive, so the lock is
  held, and nothing expires it, which is correct for a process that is only
  frozen.
- **Foreign namespace or boot:** only silence for more than 600 s expires the
  lock.
  - **Clock skew:** containers share the kernel clock, so skew matters only
    across hosts on shared storage (NFS). There the beat records the writer's
    own `date`, not a server-side mtime, so skew of more than 600 s across hosts
    could expire a live holder or keep a dead one.
  - **Real separate pid namespaces** (`unshare -U -r -p -f`) were exercised;
    see F5. `--mount-proc` was not permitted on this host.
- **Crash between acquire and the first beat:** same namespace, the pid is gone
  and the lock is taken over. Foreign namespace, `started` is more than 600 s
  old and the lock is taken over. No stale lock blocks for ever, except a
  takeover file that is broken by F1.
- **Partial writes:** a record with no pid or `started` is held until its mtime
  is more than 600 s old.
- **provision.sh:**
  - The background sync swapped `lock.d` for the shared lock. It records
    nothing when the lock is held and exits 0, so the sync retries at the next
    session.
  - The foreground route's new `trap ... EXIT` is set only on the branch that
    does not install the background `_provision_background_finish` trap, so no
    trap is overwritten.
  - An older deployed provision.sh still uses `lock.d`. That copy and a new
    `upgrade.sh` from main do not see each other's locks until provision.sh is
    redeployed. This gap lasts for one upgrade cycle.

## Scope 1 and 2: authorisation, trigger, prompt injection

- **The upgrade is started by an agent, never by the daemon.**
  - `version_check` only adds text to the notice. The upgrade happens only when
    an agent runs the skill with `--unattended`.
  - Release notes, issue text and tag names never reach the authorisation
    decision, which reads only the config, local files and the version numbers.
    The version strings are validated against `\d+\.\d+\.\d+` before any branch
    in the code depends on them.
  - A hostile tag name can only fail closed: Layer 1 refuses any target that is
    not plain X.Y.Z, and the attempt-record filename is built only after that
    check.
- **How the latest version is found:** `git ls-remote` against a fixed GitHub
  URL over TLS, with no signature check. A forged tag requires write access to
  the upstream repository, which is the trust the attended route has today.
- **Injected text** is honest about being a shipped default and names the
  opt-out.
- **Turning it on from a file:** a cloned repository's config can only switch
  it on by also being the trusted project config, so this is not an escalation.

## Scope 6: DESIGN decisions (evidence, and who decides)

| Decision                               | Judgement from the evidence                                                                                                                                                                                                                | Owner?                                              |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------- |
| Default-on for existing installs       | Defensible only because the injected text says it is the shipped default and an explicit opt-out works. With F3 fixed, a malformed opt-out now fails closed. It still grants consent the project never gave, which contradicts Decision 3. | **OWNER**                                           |
| Unverified signatures                  | Same trust as the attended route, but unattended removes the human "review the script" step. The builders implemented nothing and flagged it, which is the right call for them.                                                            | **OWNER** (needs a signing key and a rotation rule) |
| Layer 1 from main, not from the tag    | Main is where all the refusals for unattended runs live (dirty tree, major bump, attempt record, lock), so taking main keeps them current. The cost is that unreleased Layer 1 code runs unattended.                                       | **OWNER**                                           |
| Confirmation steps in the skill        | Not settled. The skill says "finish without asking" while step 9 and some post-upgrade tasks say to ask. Left as it is, an unattended agent will either guess or stop.                                                                     | **OWNER** (should be ruled before default-on ships) |
| Shared checkout and dirty-tree refusal | Correctly fails closed. The lock does not cover the skill's later commit, so another agent's edits in the window could be swept into it. `modified_files` scoping reduces that risk.                                                       | **OWNER** (acceptable as is)                        |
| Injected text size                     | The full text is about 900 characters, then a short form on the cadence. That is modest, but it reaches every project's prompts.                                                                                                           | **OWNER**                                           |

## What is left

- **F1 and F2** need a design fix and their own race and signal tests before the
  plan can be merged.
- **M1** (pinning the target to the remote tag) is a small change and worth
  doing in the same pass.
- **M9:** an end-to-end rollback test with real Layer 2 on a scratch clone.
- **M10** (the example config makes fresh installs claim a recorded request)
  needs an owner ruling before merge.
- **Not verified:**
  - scope 4 `kill -9` in the middle of a run (by reading, no attempt record is
    written and the next session invites again)
  - the M1 yanked-tag case
  - a SIGSTOPped taker that holds the takeover file
  - the `lock.d` and older provision.sh coexistence
  - whether config preservation writes the new example entry into existing
    configs
- **Full QA** has not been run here. The coordinator's gate should run over F3,
  F4 and F5. Targeted results:
  - The standing-authorisations, auto_upgrade and version_check auto-upgrade
    tests: 119 passed after F3.
  - `test_upgrade_lock.py`: 31 passed after F4 and F5.
  - `test_provision_sh.py` with `test_upgrade_lock.py`: no failure among the
    117 tests that completed before the 590 s cap stopped the run. The suite was
    NOT finished, so the coordinator should run `test_provision_sh.py` and
    `test_upgrade_sh_unattended.py` in full.
