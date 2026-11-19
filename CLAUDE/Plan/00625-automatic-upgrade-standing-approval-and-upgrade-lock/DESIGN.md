# Plan 00625 — Design: automatic upgrade standing approval and upgrade lock

Settled before code. Items marked **OWNER DECISION** are choices this plan made
on the owner's behalf and that the owner should confirm or reverse; each says
how to reverse it.

## 1. What exists today (studied, extended, not replaced)

- **Detection**: SessionStart `version_check` lists the remote tags
  (`git ls-remote`, cached 24 h) and, when a newer release exists, tells the
  agent to run the `hooks-daemon` skill's upgrade. The status line shows
  `📦 vX → vY`. Nothing upgrades without someone running the skill.
- **The upgrade is an agent workflow, not a script.** The skill runs Layer 1
  (`scripts/upgrade.sh`, fetched from `main`), which checks the target tag out
  and runs the target's Layer 2 (`scripts/upgrade_version.sh`), and then the
  agent reconciles truth-changes, runs the post-upgrade tasks and commits the
  tracked files. A hook cannot do the second half, so "automatic" here has to
  mean "the agent does it without being asked", which is the job standing
  authorisations already do.
- **Pre-deploy gate** (`install/upgrade_gate.py`): exit 3 until the reader
  confirms the listing with its digest. `escalations` are the `READ THIS FIRST` reasons: a MAJOR bump, a crossed `breaking: true` manifest, a
  `critical` pre-upgrade task with hits, an installed version it cannot read.
- **Rollback**: Layer 2 snapshots state and rolls back on any failure, EXCEPT
  at Step 15 (the daemon does not start) and Step 16 (post-upgrade validation
  fails). There it deliberately keeps the new code (`UPGRADE_STARTED=false`)
  for a human to fix the config. **That gap matters once nobody is watching.**
- **Locks**: `upgrade.sh` has none. `provision.sh --background` has a
  noclobber lock file under the clone's `untracked/background-sync/`, judged
  live by `kill -0 <pid>`. Two defects for the shared-folder case:
  1. a holder in another container's PID namespace reads as dead (its pid is
     not visible), so a second container takes the lock over mid-sync, and a
     reused pid in this namespace can read as alive for ever;
  2. the lock lives inside the clone it protects, and the sync's switch moves
     the clone's `untracked/` aside, so the lock path is briefly empty.
     The takeover (`rm -rf` then re-create) is also racy between two takers.
- **Tags are SSH-signed** (`git cat-file -t v3.75.0` is `tag`, carrying an
  `SSH SIGNATURE` block), but nothing anywhere verifies a signature, and no
  allowed-signers file is shipped.

## 2. The standing authorisation

New built-in id **`daemon-auto-upgrade`** in
`handlers.user_prompt_submit.standing_authorisations.options.authorisations`.
Its text: the project has authorised the agent to upgrade the hooks daemon to
the latest PUBLISHED release, without asking, by running the hooks-daemon
skill's upgrade with `--unattended`, and to finish the skill's steps (truth
changes, post-upgrade tasks, commit). It also says what it does NOT cover
(section 4), and where to switch it off.

**Default ON — OWNER DECISION, and a loosened guard.** Every other entry ships
disabled (Plan 00223 Decision 3: "the daemon must never assert consent nobody
gave"). This one entry gets a per-entry default of enabled, at the owner's
request. To keep Decision 3's honesty without its default:

- the text says, when the entry is not in the project's config, that it is the
  daemon's **shipped default**, not a request the project recorded, and names
  the line that switches it off: `{id: daemon-auto-upgrade, enabled: false}`;
- the other three ids still ship disabled, and their test still asserts it;
- only an explicit `enabled: false` turns it off; an entry with any other
  value, or none, leaves the default.

**Reverse it** by changing the one per-entry default in
`standing_authorisations.py` to `False`; nothing else changes.

**Existing installs — the default reaches them.** The default lives in code,
not in the config file, so an install that upgrades into this release gets it
on. The first upgrade INTO this release is always a normal agent-run upgrade,
whose release notes and `check-config-migrations` advisory carry the change
and the opt-out snippet (the `v3.76.0` config-changes manifest and release
note `003`). A project that wants it off adds one line. **OWNER DECISION**: the
alternative is to write the entry only into new configs (init) so existing
installs stay off; that is one change in `init_config` plus flipping the
code default.

**This repository (self-install).** Auto-upgrade does not apply: Layer 2 and
`provision.sh` already refuse in the daemon's own repository, the source here
IS the latest version, and `version_check` reports no upgrade in self-install
mode. `.claude/hooks-daemon.yaml` lists the entry with `enabled: false` and a
comment, so the default is not silently asserting something that cannot
happen here.

## 3. What triggers "auto"

**The SessionStart `version_check`**, nothing new: the same once-a-day
`ls-remote` (no new network traffic, no new schedule). When it finds a newer
release AND the authorisation is in force AND the local pre-check (section 4)
passes, its advisory changes from "to upgrade, use the skill" to "AUTO-UPGRADE
AUTHORISED: run the hooks-daemon skill upgrade with `--unattended` now". The
UserPromptSubmit replay of the authorisation keeps the permission in force
across compactions, as for the other entries.

Rejected: a cron (adds a schedule and wakes idle sessions); a hook that runs
the upgrade (a hook cannot do the skill's tracked-file and commit steps, and a
background upgrade of tracked files under a live agent is worse than the race
this plan fixes). The existing `provision.sh --background` sync stays scoped
to `daemon.expected_version` drift.

## 4. What it never does without a human

Text authorises; **code enforces.** `upgrade.sh --unattended` (forwarded to
Layer 2) adds restrictions and never removes one. Each "never" below is a
refusal in the scripts, not only a sentence in the authorisation:

| Never, unattended                                               | Enforced in                                     | Exit |
| --------------------------------------------------------------- | ----------------------------------------------- | ---- |
| while another upgrade/sync holds the lock                       | Layer 1, before fetch                           | 75   |
| while `untracked/release-state.json` exists (release in flight) | Layer 1                                         | 5    |
| with uncommitted changes in the project                         | Layer 1                                         | 5    |
| a MAJOR version bump                                            | Layer 1 (versions) and the gate's escalations   | 5    |
| a version whose earlier unattended attempt failed               | Layer 1, from the attempt record                | 5    |
| anything the gate lists under `READ THIS FIRST`                 | Layer 2, from the verdict file's `escalations=` | 5    |
| a downgrade, a branch install, `--release`, `--uv`              | Layer 1 argument check                          | 1    |

Exit `5` means **needs a human**: nothing was changed, the reason is printed
and recorded, and the version is not retried unattended. The ordinary reading
stop (exit 3, upgrade guides and pre-upgrade tasks with hits) is NOT a human
stop: reading it and confirming with the digest is exactly what the skill's
agent does today, and the authorisation covers it, provided the listing has no
`READ THIS FIRST`. (The gate's verdict file gains an `escalations=<n>` line so
Layer 2 can tell the two apart without parsing prose.)

A target release older than this one has no `--unattended` in its Layer 2;
Layer 1 refuses an unattended run when the target's Layer 2 does not accept
the flag (exit 5), so an unattended upgrade can only ever land on code that
enforces the rules above.

## 5. Supply-chain trust

What is verified today, and unattended inherits exactly this: the tag is
fetched from the fixed origin URL over TLS, origin must name one URL and may
not be rewritten to another repository (Layer 1), the checked-out
`version.py` must name the tag's version, and the target's own gate decides.
**No signature is verified.** Unattended removes the one human step the
manual route has ("review the script before running it").

**OWNER DECISION, not implemented here:** verify the tag's SSH signature in
unattended mode against an allowed-signers file shipped in the daemon (and in
`upgrade.sh`, which is fetched alone), failing closed. It needs the release
signing public key committed and a rotation rule, which only the owner can
supply. Until then the docs say plainly that unattended upgrades trust GitHub
and the origin URL, as manual ones do.

## 6. The upgrade lock

**One lock, taken by every route that changes the daemon clone**: Layer 1
(`upgrade.sh`, attended or not) before it fetches or checks anything out, and
`provision.sh` (foreground and background sync) before its switch. Layer 1
holds it across Layer 2 (its child). `provision.sh`'s own pid-only
`lock.d` is replaced by it.

**Where**: `<git common dir>/hooks-daemon-upgrade.lock` (that is
`.git/hooks-daemon-upgrade.lock` in a plain checkout). On the shared
filesystem with the project, never tracked, never in `git status` (so the
clean-tree checks are unaffected), outside the clone the switch moves, and the
same file for every worktree of the repository (a superset of what is needed:
upgrades of one repository are serialised even across worktrees).

**Acquire**: create with bash noclobber (`set -C`, `O_CREAT|O_EXCL`), never
`mkdir` (Plan 00474 N568: uutils `mkdir` let two callers create one
directory). The file holds the owner record: `token` (random), `host`,
`boot_id` (`/proc/sys/kernel/random/boot_id`), `pidns`
(`readlink /proc/self/ns/pid`), `pid`, `pid_start` (field 22 of
`/proc/<pid>/stat`), `started` (epoch), `purpose`.

**Heartbeat**: the owner rewrites `<lock>.beat` (epoch seconds) every 20 s from
a background loop that exits as soon as its owner process is gone, so a killed
owner stops beating.

**Stale rule — takeover only when provably dead or expired:**

- **Provably dead**: the owner record has the SAME `boot_id` and `pidns` as the
  judge, and the pid is gone or its `pid_start` differs (pid reuse). Only then
  is the pid meaningful: same kernel, same namespace.
- **Expired**: otherwise (another container, another host, or no `/proc`), the
  newest of `<lock>.beat` and `started` is older than 600 s.
- Anything else is **held**: the caller waits (`--lock-wait=SECONDS`, polling)
  or skips. A skipping unattended run exits 75 with nothing changed; the
  holder's restart is then seen by the waiter's next session start as "up to
  date".

**Takeover is serialised** by a second noclobber file, `<lock>.takeover`: the
taker creates it, re-judges the lock under it (it may have been released or
retaken meanwhile), removes the stale lock, creates its own, and removes the
takeover file. A takeover file older than 60 s is itself stale (its creator
died inside a few-millisecond window) and is removed.

**Release**: the EXIT trap removes the lock only if it still carries this
run's token, and stops the heartbeat.

**Filesystems**: correct where `O_EXCL` create is atomic and all parties share
one view of the file: a local filesystem, a bind mount or Docker volume shared
by containers on one host (the case asked about), NFSv3 and later.
**Caveats**: NFSv2 and some FUSE/SMB mounts do not make `O_EXCL` atomic;
expiry across hosts compares the writer's clock with the reader's, so host
clocks must agree to well within 600 s (NTP); attribute caching can delay a
reader seeing a fresh heartbeat by its cache time (seconds, far below the
expiry).

**No half-upgraded tree**: the lock is taken before Layer 1 touches the clone
and released after Layer 2 has finished or rolled back, and every other route
that moves the clone takes the same lock; a run killed outright leaves Layer
2's snapshot and `provision.sh`'s switch recovery as today, and the next lock
holder starts from whatever that recovery left.

## 7. Health check and rollback

Unattended, a daemon that does not start after the upgrade (Step 15) or fails
post-upgrade validation (Step 16) is **rolled back** to the snapshot and the
previous daemon restarted, instead of being left for a human: nobody is there
to "fix the config manually". Attended runs keep today's behaviour.

## 8. No upgrade loop

Layer 1 writes an attempt record per target,
`.claude/hooks-daemon/untracked/auto-upgrade/v<version>.state` (key=value:
`status` = `failed` | `needs-human`, `target`, `from`, `detail`; same shape
as `background-sync/v<version>.state`), whenever the unattended run's Layer 2
ends in a rollback, a failure or a needs-human stop (any exit but 0, 3 or 75).
Layer 1's own refusals write no record: a dirty tree or a release in flight
is transient, and a MAJOR bump or a missing Layer 2 capability is found again
on every run. It is under the clone's
gitignored `untracked/`, which neither the snapshot restore nor the rollback
touches. While a record exists for the latest release, `version_check` does
not invite an unattended upgrade, and reports the record instead; Layer 1
refuses that version unattended (exit 5). A newer release has no record, so it
is tried. A human (or an attended skill run) can still upgrade to the
recorded version; a successful upgrade removes records for versions it has
reached.

## 9. Running sessions mid-upgrade

Unchanged from a manual upgrade: Layer 2 stops and restarts the daemon, other
sessions' hooks may meet a short restart window, and `daemon_upgrade_detector`
tells each other session the installed version changed. New hook event types
still need a Claude Code session restart; an unattended run cannot do that,
so it says so in its report (as the skill does today).

## 10. Release-in-progress and merge freeze

Never while `untracked/release-state.json` exists in the project root (section
4). In practice that file exists only in the daemon's own repository, where
auto-upgrade does not apply anyway; the check costs nothing and keeps the
rule true if a client project ever adopts the same release workflow.

## 11. Open after the build (for review and the owner)

- **OWNER DECISION, skill confirmation steps.** The skill's step 9
  (`/hooks-daemon optimise`) applies changes "on your confirmation", and some
  post-upgrade tasks say to ask the user. The skill text tells an unattended
  run to finish the steps without asking; it does not yet say what to do at
  those two points. A likely ruling: unattended defers optimise and stops at a
  task that says to ask.
- **OWNER DECISION, Layer 1 source.** The skill's shim runs `upgrade.sh` from
  `main`, not from the published tag. So an unattended run executes
  unreleased Layer 1 code, as an attended one does. Pinning it to the target
  tag is possible (the shim's offline recovery already shows how) but changes
  the attended route too.
- **OWNER DECISION, shared checkouts.** The dirty-tree refusal will often
  block the many-agents-one-folder case, because one of the agents usually has
  work in progress. The lock covers Layer 1 and Layer 2, not the skill's
  later commit of the tracked files.
- **OWNER DECISION, injected text.** Default-on means every project's
  prompts now carry the authorisation text on the standing-authorisations
  cadence.
- **A waiter that takes the lock after the holder finished.** With
  `--lock-wait` and no VERSION, it resolves the latest release, which is now
  the installed one, and runs a same-version reinstall: wasteful, not
  harmful. The session-start trigger does not cause it, because the next
  version check reads "up to date". It is not tested.
- **Unproven end to end.** The flag handoff is tested from Layer 1 into a
  stub Layer 2, and Layer 2's refusal from a direct call; no test runs both
  real layers on a `breaking: true` manifest. The unattended rollback is
  tested against stubs of the snapshot restore and the daemon restart.
