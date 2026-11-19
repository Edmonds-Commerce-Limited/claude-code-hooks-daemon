# Plan 00625 fix round: handoff

Worktree `/workspace/.claude/worktrees/agent-a5947fd1e83f03452-ba288018`, branch
`agent-a5947fd1e83f03452-ba288018`, main merged at the start of the round.
This seat stopped at a pushed commit because of its context budget. The
relayed owner ruling (DESIGN.md section 11a) is NOT applied yet.

## Done (each committed and pushed)

| Item | Commit      | Evidence                                                                                                                                                                                                                                                                                                                                          |
| ---- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F1   | `d7acda90a` | `TestAStaleTakeoverNeverLetsTwoHold`: 20 racers, 30 trials, crashed takeover seeded. RED on the old block: 6 of 30 trials had two holders (a first 12-trial run caught 1). GREEN after.                                                                                                                                                           |
| F2   | `d7acda90a` | `TestTheWriterHoldsTheLock` (record names the writer; SIGTERM keeps the lock until the writer ends, exit 143; SIGKILL of the owner leaves it held until the writer ends, then free; a writer whose lock is not ours never runs, exit 75). End to end: `TestASignalledLayer1KeepsTheLockForLayer2` fails on the previous `upgrade.sh`, passes now. |
| M10  | `b4ea0fe4a` | The example config leaves `daemon-auto-upgrade` unlisted. The test loads the real example into the handler and asserts "shipped default". It failed before the change.                                                                                                                                                                            |
| Docs | `5d6d5baf2` | DESIGN section 6 (generations, writer) and section 2 (fail-closed opt-out, M10). New section 11a records the relayed ruling as unverified. PLAN.md Task 8.1a and 8.1b.                                                                                                                                                                            |

The F2 block-level tests could only fail by "function not found" before the
fix. The meaningful RED for F2 is the end-to-end SIGTERM test, plus the
reviewer's reproducer.

Targeted results after the fixes:

- `test_upgrade_lock.py`: all GREEN after the last edit, run in two parts
  (the first full run had 3 failures, all fixed before commit).
- `test_upgrade_sh_unattended.py`: 25 of 25 passed.
- `test_provision_sh.py`: see the final line of this file.

## Design in brief

- **Takeover.** It goes through `<lock>.takeover.<N>`. The taker judges the
  top generation like a lock record (60 s expiry) and creates N+1 with
  noclobber. It never removes a file it did not create.
- **Writer.** `_upgrade_lock_run_writer` runs Layer 2 as a subshell that writes
  `writer=`/`writer_start=` into the record and then execs Layer 2.
- **Who keeps the lock alive.** The judge treats the lock as alive while the
  owner OR the writer lives, and the heartbeat beats while either does.
  Release leaves the lock in place while the writer lives.
- **Signals.** `_upgrade_lock_hold_through_signals` traps TERM and HUP. Bash
  defers the trap until the foreground Layer 2 returns. No `kill` is used.
- **Lockstep.** The block lives in `scripts/upgrade.sh` and is copied
  byte-identical into `provision.sh`.
  `untracked/scratch/syncblock.py <worktree>` copies it, and
  `TestLockstep` checks the two are identical.

## Left to do

1. Apply DESIGN section 11a items 2 and 3 together. This also covers M1: pin
   the target to a tag that exists on origin. Then items 4, 5, 1 and 6. Each
   needs its own RED test, then a commit and push.
   - **Items 2 and 3.**
     - **Key:** verify with a key that the installed daemon ships, never one
       taken from the tag being verified or from `main`. Check whether a
       tracked allowed-signers file exists. If none does, mark the key as
       needing the owner before merge.
     - **Test with:** throwaway `ssh-keygen` keys covering signed, unsigned
       and wrong-key tags, plus a missing `ssh-keygen` or an old git. Every
       case except the signed one must refuse.
     - **Run from the tag:** take `scripts/` from the verified tag, using the
       `git archive` pattern near `upgrade.sh` line 742.
   - **Item 5.** Take the list of files the upgrade rewrites from an existing
     source, not a new list. Check the daemon clone's own status, which also
     closes M11.
   - **Item 1.** Keep the "notice shown" marker under the clone's `untracked/`.
     Update Plan 00223's rule wording, tests and docs to name the exception.
   - **Item 6.** The one line must still say "shipped default" and name the
     opt-out. Keep F3's fail-closed tests.
2. Update the release note `003` and the `v3.76.0` config-changes manifest
   for the ruling. Leave the numbering alone, because the coordinator
   renumbers at merge.
3. A fresh independent re-review.

## Owner decisions

They are no longer "unchanged": the coordinator relayed a ruling (DESIGN 11a)
that this seat could not verify. Items 1 and 5 loosen guards and should be
confirmed by the owner directly.

## test_provision_sh.py

Run to completion at `d7acda90a`+ in four chunks: 99 of 99 passed (25, 25,
25, 24; about 5.5 minutes in total, which is why a single run hit 590 s).
