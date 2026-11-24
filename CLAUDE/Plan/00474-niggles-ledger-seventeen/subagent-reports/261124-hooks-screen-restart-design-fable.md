# hooks-screen, the ccy relaunch, and the two-tier supervisor

Read-only investigation for the owner's question (paraphrased): needing a
session restart to build hooks-screen looks like a bad design; the supervisor
has a two-layer system, so is it still there, and should this use it?

All line numbers are `.claude/ccy/claude-supervise.py` on disk unless a file is
named. Nothing was built, edited, committed or restarted.

## Short answer

- Yes, the supervisor is still two-tier, and the rate-limit answerer already
  uses it: the recogniser and the decision run in the hot-reloaded worker.
- Building `hooks-screen` does not itself need a restart. On the code now on
  disk the host looks for the binary again every 60 s and runs it by path each
  time, so a binary installed later is picked up.
- The restart is needed for one reason only: the host process running in this
  session was started BEFORE the Plan 00523 host code was merged. It has no
  code to render the screen for the worker, and it looked for the binary once,
  at launch. That one relaunch cannot be designed away.
- The design fault is real but narrower than "restart to build": Plan 00523 put
  three pieces of answerer-specific logic in the host that did not have to be
  there. Each later change to them costs another relaunch. They can move.

## 1. Is the supervisor still two-tier?

Yes. Verified in code and in the running processes.

- Design comment: lines 306-318 (Plan 00164 Phase 4; the plan is
  `CLAUDE/Plan/Completed/00164-supervisor-lifecycle-and-upgrade-clarity`).
- Worker spawn: `PolicyWorker.start`, 11511-11545, runs
  `python3 <self> --worker`.
- Reload: `reload_if_stale`, 11606-11615, compares `compute_source_hash`
  (3175-3183, a sha256 prefix of the file) against the hash the worker was
  spawned from. The decider calls it every `_WORKER_RELOAD_CHECK_SECONDS`
  (5 s, line 318) at 13343-13348.
- Worker entry: `main`, 13138-13174.
- Running now: the host is pid 2 (started 23 Nov 12:33:38); its worker is pid
  1295615 (started 23 Nov 22:38:06). The supervisor file's mtime is 22:38:01,
  so the worker reloaded 5 s after the PR 231 merge landed on disk. The
  hot-reload works.

**Doc mismatch found.** `.claude/ccy/CLAUDE.md` and the comment at 356-366 say
the reload has an mtime pre-check, so a `cp -p` redeploy can be missed. The
code has none: `_current_fingerprint` (11490-11495) hashes the file directly,
and there is no `st_mtime` read anywhere in `PolicyWorker`. The `touch` trap
is still true (same content, same hash); the `cp -p` trap is not in this code.
I did not check whether an older revision had the pre-check.

## 2. What hooks-screen is, and what the answerer needs it for

- A small static Rust binary (`screen/src/main.rs`, vendored `vt100` crate)
  that replays raw terminal bytes and prints the rendered screen.
  `screen/build.sh` builds it offline to
  `untracked/screen-build/hooks-screen-<triple>` (build.sh:36-38). The release
  workflow publishes it (`.github/workflows/release-assets.yml:73-93`).
- Lookup order, `resolve_screen_binary` 1252-1275: `$CCY_HOOKS_SCREEN`, then
  `untracked/bin/hooks-screen`, then the build path.
- The answerer needs it because Claude Code draws the menu with cursor
  movement; matching raw bytes is unreliable. The host keeps a 256 KiB copy of
  the child's output (`ScreenBuffer`, 1285-1316), runs
  `hooks-screen --dump` on it (`recent_dump`, 1633-1647), and sends the bottom
  40 rows to the worker as `TickFacts.screen_dump` (12817-12837). The worker
  recognises the dialog in that text (`_rate_limit_dialog_step`, 9082-9224).
- `INERT`: `rate_limit_armed_status` (386-404) prints `INERT` when no binary
  resolves. With no binary the dump is `""`, the worker sees no dialog, and
  nothing is typed. That is fail-safe, not a fault.
- Nobody installs it today. In this checkout neither
  `untracked/bin/hooks-screen` nor `untracked/screen-build/` exists. Plan
  00638 (Not Started) is the automated install.
- "The owner's v2-window action": the reason is NOT recorded. PLAN.md:184-187
  and journal entry `124813Z-action-42c0ca.md` state it; the handoffs
  (`261123-handoff-unit3-opus.md:77`, `261123-handoff-unit2a-opus.md:106`)
  only say "Do NOT build hooks-screen into /workspace". A cargo toolchain is
  present in this container, so it is a ruling, not a technical limit. There is
  no `DESIGN.md` in the plan folder; the design is
  `subagent-reports/261123-handoff-design-opus.md`.

## 3. What needs a relaunch, and whether it had to

### What the running host actually is (verified)

`untracked/supervise/supervisor-status.json` records the host's own source
hash at launch: `eb6d36902d00`, pid 2. That equals the sha256 prefix of the
supervisor file at `42486817b^1`, the commit on main just before PR 223 merged
(merge time 12:47:27; host start 12:33:38). The file on disk now hashes
`f0bc2c259045`.

That older revision has `ScreenFocusCheck` and resolves the binary once at
launch (its line 1471). It has none of: `resolve_binary` (the 60 s re-look),
`screen_dump`, `_rate_limit_host_veto`. The decision log agrees: the session
start at 12:33:46 is followed by `screen check failed open: no hooks-screen binary found` and has no `rate-limit dialog answerer:` line.

So for THIS session: building the binary now changes nothing, and the answerer
is inert, until one relaunch. No design removes that relaunch, because any fix
is itself host code the running host does not have.

### Host-side pieces of Plan 00523, classified by the Plan 00317 audit's test

The audit's test (`AUDIT.md`, summary paragraph): something stays host-side
only if it acts on a byte before it is forwarded, is process-local, or is the
"host injects" plumbing.

| Piece                                                             | Lines                      | Must it be host code?                                                                                                                                                                             |
| ----------------------------------------------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Copy of the child's output                                        | 1285-1316                  | Yes. Only the host reads the PTY.                                                                                                                                                                 |
| Running `hooks-screen` on the copy                                | 1633-1677                  | No. It is a pure function of bytes plus terminal size. The worker could run it if the host sent the bytes.                                                                                        |
| Choosing 40 rows, the 2 s quiet gate, the on/off switch           | 1374-1375, 1645, 1734-1746 | No. Policy.                                                                                                                                                                                       |
| "Is a human key waiting / is child output unread" at apply time   | 12877-12878                | Yes. These are reads of the host's own file descriptors, taken after the worker round trip. Same class as audit item 8.                                                                           |
| Which decisions that check vetoes                                 | 10822-10830                | No. Policy; the host could obey a flag on the outcome.                                                                                                                                            |
| "Enter only if the shipped dump shows the pointer on the target"  | 10831-10835                | No. It re-checks the same dump the worker already required at 9181-9201. It is a second opinion against a worker bug, nothing more.                                                               |
| Take-backs: `enter_takebacks`, `resume_vetoed_at`, phase rollback | 10839-10906                | No. They edit the worker's own state file. The worker could do it on the next tick if the host reported "your last send was vetoed/held". This is why PLAN.md:193-196 says F2-F4 need a relaunch. |
| Typing the key                                                    | `_apply_decision`          | Yes. Audit item 8.                                                                                                                                                                                |
| The `INERT`/`ARMED` line                                          | 12649, 12687               | Printed once at host launch, so it goes stale when a binary is installed later.                                                                                                                   |

Nothing in the list is a byte-before-forward primitive. Only the output copy,
the two readiness reads and the write are forced to be host code.

## 4. Does the binary load lazily?

Yes, on current disk code. `_spawn` (1649-1677) runs the binary by path on
every render; if none resolved, it calls `resolve_screen_binary` again at most
every `_SCREEN_RESOLVE_INTERVAL_SECONDS` = 60 s (1376, 1651-1655). A replaced
binary at the same path is used on the next render with no reload step.

Two gaps:

- A host that found a binary at launch never looks again, so a higher-priority
  path installed later (for example `untracked/bin/` over the build path) is
  ignored until relaunch. Minor.
- Not verified live: no host running this code exists in this session.

## 5. Recommendation

The two-layer approach is already the design. The work is to finish applying
it, so the host carries mechanism only. In order:

1. **One relaunch, with the binary in place first.** Unavoidable. Build or
   install the binary before relaunching so the banner reads `ARMED`. Owner's
   call: when to relaunch, and where the binary is built. No code change.
2. **Worker reports the armed state.** The worker resolves the binary itself
   and logs a decision-log line when the answer changes
   (`INERT` to `ARMED`). Files: the supervisor, its tests,
   `CLAUDE/development/CcySupervisor.md`. Risk: low. Hot-reloads.
3. **Generic apply report (removes the F2-F4 relaunch class).** The outcome
   carries a flag such as "do not type if stdin or child output is pending".
   The host obeys it and puts "last send: typed / vetoed (reason) / held" in
   the next `TickFacts`. The worker does the take-backs itself. Files: the
   supervisor (`TickOutcome`, `TickFacts`, `_apply_worker_outcome`,
   `_rate_limit_dialog_step`, the resume step), tests. Risk: medium. The
   take-back moves one tick later (2 s), and the retry and cap logic of F2-F4
   must be re-proven test-first. Needs one relaunch to ship the generic host
   half; after that, changes to veto and take-back rules hot-reload.
4. **Worker renders the screen (optional).** The host sends the raw buffer
   and terminal size, only when output is quiet and the buffer changed; the
   worker runs `hooks-screen`. Then row count, quiet gate and binary lookup all
   hot-reload. Risk: medium. Up to 256 KiB of base64 over the pipe on a
   changed quiet tick, and the 200 ms render now sits inside the worker's 2 s
   reply budget (line 315). Measure before adopting. Without step 4 the
   remaining host-side screen code is small and stable, so step 4 can wait.
5. **Fix the docs.** Remove the mtime pre-check claim from
   `.claude/ccy/CLAUDE.md` and the comment at 356-366, or add the pre-check.
   Change `CcySupervisor.md:598-602` and release note 025: after the first
   relaunch, installing the binary needs no relaunch. Risk: none.

Steps 2 and 5 can ship before the relaunch. Steps 3 and 4 should land on disk
BEFORE the owner's relaunch, so that one relaunch covers them; otherwise each
costs its own.

What must stay in the host after all of this: the PTY read and write, the
output copy, the two readiness reads at apply time, and the generic
flag-and-report plumbing.

## Not verified

- Any behaviour of the on-disk host code in a live session (lazy binary
  pickup, the dump, the veto). Read from source only.
- Why the build is the owner's "v2-window" action. Not written down.
- Whether an old host could be given the screen some other way. I found none:
  the worker has no access to the child's output, and pressing Enter without
  seeing the highlighted row could confirm a billing option.
- Cost figures for step 4. None were measured.
- The real dialog. Plan 00523 Phase 1 (live capture) is still open, so the
  recogniser itself is unproven whatever tier it runs in.
