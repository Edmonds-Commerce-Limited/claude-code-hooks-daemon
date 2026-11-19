# Plan 00625 — Design: automatic upgrade standing approval and upgrade lock

Settled before code. The six open design points are ruled in section 11a, and
each ruling there is recorded as settled by a fable sub-agent under the owner's
delegation, 2026-11-19. None of them is the owner's own words, and a later
owner message can overturn any of them. Where an earlier section and section
11a disagree, section 11a wins. The reasoning behind each ruling is in
`subagent-reports/261119-fable-settle-and-threat-model.md`.

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

**Default ON (ruling 1, section 11a), and a loosened guard.** Every other entry
ships disabled (Plan 00223 Decision 3: "the daemon must never assert consent
nobody gave"). This one entry gets a per-entry default of enabled. The default
alone upgrades nothing: an unattended upgrade also needs a release-signing key
that a human added to the project (ruling 2), so the human act that Decision 3
asks for still exists, and it is the key. To keep Decision 3's honesty without
its default:

- the text says, when the entry is not in the project's config, that it is the
  daemon's **shipped default**, not a request the project recorded, and names
  the line that switches it off: `{id: daemon-auto-upgrade, enabled: false}`;
- the other three ids still ship disabled, and their test still asserts it;
- an entry that lists the id counts as a recorded request only when it says
  exactly `enabled: true`; any other value turns it off (review F3, fail
  closed). Unlisted, the shipped default applies. The example config a fresh
  install copies leaves it unlisted (review M10), so a new project's text says
  "shipped default", not "recorded".

**Reverse it** by changing the one per-entry default in
`standing_authorisations.py` to `False`; nothing else changes.

**Existing installs — the default reaches them.** The default lives in code,
not in the config file, so an install that upgrades into this release gets it
on. The first upgrade INTO this release is always a normal agent-run upgrade,
whose release notes and `check-config-migrations` advisory carry the change
and the opt-out snippet (the `v3.76.0` config-changes manifest and release
note `003`). A project that wants it off adds one line. Ruling 1 keeps this
and sets its conditions, including the once-only notice. The rejected
alternative was to write the entry only into new configs (init) so existing
installs stay off.

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

| Never, unattended                                                                         | Enforced in                                     | Exit |
| ----------------------------------------------------------------------------------------- | ----------------------------------------------- | ---- |
| while another upgrade/sync holds the lock                                                 | Layer 1, before fetch                           | 75   |
| while `untracked/release-state.json` exists (release in flight)                           | Layer 1                                         | 5    |
| with uncommitted changes in the upgrade-owned paths or the clone (ruling 5)               | Layer 1                                         | 5    |
| a tag whose signature does not verify against the project's signers file (ruling 2)       | installed entry, then Layer 1 under the lock    | 5    |
| when the project switched the authorisation off, or in the daemon's own repository (R1.5) | installed entry                                 | 5    |
| a release first seen less than 24 hours ago (R1.6)                                        | installed entry                                 | 5    |
| a Layer 1 that is not byte-identical to the verified tag's (ruling 3)                     | Layer 1                                         | 5    |
| a MAJOR version bump                                                                      | Layer 1 (versions) and the gate's escalations   | 5    |
| a version whose earlier unattended attempt failed                                         | Layer 1, from the attempt record                | 5    |
| anything the gate lists under `READ THIS FIRST`                                           | Layer 2, from the verdict file's `escalations=` | 5    |
| a downgrade, a branch install, `--release`, `--uv`                                        | Layer 1 argument check                          | 1    |

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

What the attended route verifies, and unattended inherits: the tag is fetched
from origin over TLS, origin must name one URL and may not be rewritten to
another repository (Layer 1), the checked-out `version.py` must name the tag's
version, and the target's own gate decides. Unattended removes the one human
step the manual route has ("review the script before running it"), so it adds
a check the attended route does not have: **the release tag's SSH signature
must verify against a key a human put in the project**, and the code that runs
is the code that tag signs. The trust model, the key's home, rotation,
revocation and the owner's key step are ruling 2 in section 11a; the route
from the verified tag to the running script is ruling 3. The attended route is
unchanged and still trusts GitHub and the origin URL.

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

**Takeover is serialised by generation files** `<lock>.takeover.<N>` (review
F1). A taker finds the highest generation N, judges it like a lock record
(its creator provably dead, or silent for 60 s), creates N+1 with noclobber,
and goes on only if it created N+1 and no higher generation has appeared. It
then re-judges the lock (it may have been released or retaken meanwhile),
removes the stale lock only if it still carries the token it judged, creates
its own, and removes its OWN generation. **No process ever removes a takeover
file it did not create.** The earlier single `<lock>.takeover` was broken by
path after an age check, which could delete a fresh one another taker had just
created and let two processes hold the lock (7 of 15 trials in the review, 6
of 30 in this branch's RED run). A crashed taker's generation stays on disk and
is passed over; it is a few bytes and only a crash inside the takeover window
leaves one. Known limit: a taker SIGSTOPped inside the window for more than 60 s
in another pid namespace or boot can be judged stale.

**The writer holds the lock too** (review F2). Layer 1 owns the lock but Layer
2 does the writing. Layer 1 runs Layer 2 through `_upgrade_lock_run_writer`: a
subshell writes its own pid and start time into the record as `writer=` /
`writer_start=` (one rename of the record) and then execs Layer 2 under that
same pid. So:

- the judge treats the lock as dead only when the owner AND the writer are
  provably dead, so an outer SIGKILL or OOM kill leaves the lock held while
  Layer 2 runs, and free as soon as it ends;
- the heartbeat beats while either lives, so the cross-namespace expiry does
  not run out under a live Layer 2;
- Layer 1 traps TERM and HUP (`_upgrade_lock_hold_through_signals`). Bash runs
  a trap only after the foreground child returns, so a signalled Layer 1 ends,
  and its EXIT trap releases, after Layer 2 has finished. No process is
  signalled, which keeps Layer 1's no-signal rule;
- a release while the writer is still alive leaves the lock in place for it.

**Release**: the EXIT trap removes the lock only if it still carries this
run's token and its writer, if any, is gone, and stops the heartbeat.

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

## 11a. The six rulings

**Standing of this section.** The owner asked for the automatic upgrade and
delegated the settling of the open points. Every ruling below is settled by a
fable sub-agent under the owner's delegation, 2026-11-19. None is the owner's
own words. A later owner message can overturn any of them. The six points
themselves reached this plan through the coordinator, as the owner's intent.

Each requirement has an id (`R<ruling>.<n>`) that PLAN.md tasks and the tests
in section 13 cite. "Refuse" always means exit 5 with nothing changed, unless
it says otherwise.

### Ruling 1: default ON for existing installs, with conditions

**Ruling: safe as conditioned below, and only together with ruling 2.** The
default by itself upgrades nothing. No install has a release-signing key until
a human adds one to that project, and without a key every unattended run
refuses. So the default states a willingness, and the key is the consent.
That is why Plan 00223's ship-disabled rule can be amended for this one id
without the daemon asserting a consent nobody gave.

- **R1.1 Inert without a key.** While the project has no usable signers file
  (R2.1), `version_check` issues no invitation, the standing-authorisation
  handler injects nothing for this id, and the installed entry refuses. An
  agent is never told about a missing key in a way that invites it to supply
  one.
- **R1.2 Once-only notice, shown whether or not a key exists.** The first
  SessionStart after this release is installed prints one line, recorded in
  `<clone>/untracked/auto-upgrade/default-on-notice-shown`. With no key: the
  feature exists, it is inactive until a human adds a key, and the opt-out
  line. With a key: it is active, and the opt-out line. If a key is added
  later, the active wording is shown once more. Every commit an unattended
  upgrade makes says in its message that it was automatic and names the
  opt-out, so the record survives a session nobody read.
- **R1.3 Never unattended**, each enforced in code:
  - while `untracked/release-state.json` exists, including as a dangling
    symlink (`-e` or `-L`; review M6);
  - a MAJOR bump, with the baseline read from the installed clone, never from
    the tracked stamp; when the stamp names a higher version than the clone,
    refuse (review M12);
  - anything the gate lists under `READ THIS FIRST`, which includes every
    crossed `breaking: true` manifest;
  - a tag that is not strictly newer than the installed version, a
    pre-release, a branch, `--release`, `--uv`;
  - a tag whose signature does not verify (ruling 2).
- **R1.4 Plan 00223 amended for this single id.** The handler docstring, its
  tests, the handler reference and the example config name
  `daemon-auto-upgrade` as the only default-on entry and say why. A test
  fails if a second id becomes default-on.
- **R1.5 The opt-out is enforced where the upgrade starts** (review M4, M5).
  The installed entry asks the installed Python pre-check whether the
  authorisation is in force and refuses when it is off, when the handler is
  disabled by any route including `disable_tags`, when the answer cannot be
  obtained, and in the daemon's own repository.
- **R1.6 Soak period.** A release is installed unattended only when this
  clone first saw it at least 24 hours ago. The first sighting is written by
  `version_check` under the clone's `untracked/auto-upgrade/`. Removing the
  record restarts the wait, so tampering only delays. Together with the
  must-be-on-origin check, a release withdrawn within a day reaches no
  unattended install.
- **R1.7 One attempt per release.** The entry writes a `started` attempt
  record before deploy and removes it on success. A leftover `started` record
  counts as failed, so a run killed outright is not retried (review, "kill
  -9, not verified").

**Residual risks.**

- A project whose human added the key but who never reads session output
  gets upgrades with only the commit message as notice.
- The soak clock is per clone. A fresh clone that first sees a week-old
  release still waits a day; a bad release that is not withdrawn within a day
  is installed.
- A minor release can still change behaviour that a project relied on. The
  gate catches only what a release declares.
- The opt-out lives in a file an agent can edit. A compromised agent can turn
  the feature on, but it still needs a human-added key to do anything with
  it, and it could already run the attended upgrade.

### Ruling 2: signature verification and the trust model

**Ruling: an unattended upgrade installs only a release whose annotated tag
carries an SSH signature that verifies against a key in the project's own
signers file. No key ships with the daemon. Every install starts with no key
and fails closed.**

- **R2.1 Where the trusted keys live.** `.claude/hooks-daemon-release-signers`
  in the project root, in git's allowed-signers format. It is usable only when
  ALL hold: it exists; it has at least one key line; its physical path is
  outside the daemon clone; it is tracked by the project and identical to the
  version in the project's `HEAD` (a key change is therefore a commit, with an
  author and a diff); and no line carries `cert-authority`. There is no
  environment variable, flag or config key that names another file.

- **R2.2 What verifies.** `scripts/lib/release_tag_verify.sh`, the copy in the
  INSTALLED clone, never the target's. Already built: plain `vX.Y.Z` name, the
  tag is on origin and the fetched object is the published one, annotated tag,
  the tag header names the tag, SSH signature only, `git verify-tag` with the
  signers file and the GPG programs forced to fail. To add:

  - `ssh-keygen` is resolved with `command -p`, and a binary inside the
    project root is refused;
  - git older than 2.34 is refused (no SSH verification before it);
  - `GIT_NO_REPLACE_OBJECTS=1`, and `GIT_DIR`, `GIT_WORK_TREE`,
    `GIT_OBJECT_DIRECTORY` and `GIT_ALTERNATE_OBJECT_DIRECTORIES` are unset,
    for the verification and for every later git call that reads the target;
  - the tag must point at a commit, and that commit's `version.py` must name
    the tag's version.

  The lib has not been released, so its cross-version contract starts with
  the release that first ships it; these additions go in before that.

- **R2.3 How the owner supplies a key.** One command, run by a human in their
  own terminal: `hooks-daemon release-signers add <public-key-file>`. It

  - takes the key only from a local file or from standard input, never from a
    URL, and makes no network call;
  - refuses without an interactive terminal;
  - prints the key's SHA256 fingerprint and has the human type its last eight
    characters, which they compare with a copy obtained from somewhere other
    than the repository that publishes the tags;
  - reports whether the key verifies the tag of the release already installed
    (an offline check), and needs `--rotation` to add a key that does not;
  - refuses DSA keys, RSA keys under 3072 bits, certificates and any options
    field; writes `hooks-daemon-release namespaces="git" <type> <key>`;
  - does not commit; it prints the commit command, and R2.1 keeps the key
    unused until the human commits it;
  - clears attempt records that were written for a signature refusal.

  `release-signers list` and `release-signers remove <fingerprint>` complete
  the set. **The key is never taken from a tag, a release, the daemon clone,
  or the account that hosts the repository.** A signed tag embeds its public
  key; reading it from there is the forbidden route, and this plan did not do
  it.

- **R2.4 Agents cannot change the trusted keys through the daemon.** The
  signers path is write-protected by a built-in rule that config cannot
  remove (file tools and Bash: create, change, move onto, delete, truncate),
  and a Bash command that runs `release-signers add` or `remove` is denied.

- **R2.5 Rotation.** Trust is added only by the human step, never by a
  release. The owner adds the new key to each project before the first
  release signed with it; both keys stay listed during the overlap; the old
  line is removed afterwards. A release signed by a key the project does not
  list is refused and recorded `needs-human` for that version, so it is not
  retried every session.

- **R2.6 Revocation.** Revoking a key means removing its line (or listing it
  in a revocation file). `valid-before` is NOT revocation: git checks it
  against the tagger date, which whoever holds the key chooses. A release may
  only ever subtract trust; a release-shipped revoked-keys list is allowed as
  later work, a release-shipped new-keys list is never allowed.

- **R2.7 The daemon's own repository.** Auto-upgrade stays off here
  (`enabled: false` in the tracked config), the entry refuses self-install,
  and no signers file exists. The release procedure gains one gate: the new
  tag must verify against the owner's own allowed-signers file (the owner's
  git `gpg.ssh.allowedSignersFile`, outside the repository) before the release
  is published, so an unsigned or wrongly signed release is caught before
  every install refuses it.

**Residual risks.**

- **An agent with a shell can defeat a hook guard.** R2.4 stops accidents and
  nudged agents, not a compromised one. A compromised agent in the project can
  already run any code, so the signature is not a defence against it. The
  signature defends against a compromised or impersonated upstream: a moved or
  forged tag, a hijacked repository or account, a network attacker.
- **The signing key itself.** Whoever holds it can ship code to every install
  that trusts it, after the soak period. Nothing here limits that.
- **Revocation is per project and manual.** There is no central switch; an
  install whose human does not act keeps trusting a stolen key.
- **First trust is only as good as the channel the human used** to obtain the
  fingerprint. How third parties obtain it is the owner's to publish; it is
  not built here.
- **git names commits by SHA-1.** The signature covers the tag object, which
  names the commit by SHA-1. Git's collision detection is the only defence.
- **A project that does not track `.claude/`** can never satisfy R2.1 and so
  never upgrades unattended.

### Ruling 3: the upgrade script runs from the verified tag

**Ruling: unattended, every script that runs is either the installed
version's or byte-identical to the verified tag's. Nothing is fetched from
`main`.**

- **R3.1 Trust root.** The skill shim, given `--unattended`, runs only the
  installed `scripts/upgrade_unattended.sh` and never downloads. A missing
  entry is a refusal.
- **R3.2 The entry** verifies (ruling 2), extracts `scripts/upgrade.sh` from
  the verified commit by object id into a directory it has just created with
  mode 0700, and runs it. It refuses when `HOOKS_DAEMON_UPGRADE_REF`,
  `HOOKS_DAEMON_UPGRADE_BASE_URL`, `HOOKS_DAEMON_BOOTSTRAP_BASE_URL`,
  `HOOKS_DAEMON_UNSAFE_TRACK_REF` or `HOOKS_DAEMON_CLONE_URL` is set, and it
  sets `HOOKS_DAEMON_SKIP_BOOTSTRAP=1` so no skill script fetches itself from
  `main` during the run.
- **R3.3 The authoritative verification is Layer 1's, under the lock.** Layer
  1 verifies again after taking the lock, with the installed lib, requires
  itself to be byte-identical to `scripts/upgrade.sh` in the verified commit,
  and from then on names the target only by the verified commit id: for the
  Layer 2 capability probe, for the checkout, and for a check that `HEAD` is
  that commit before Layer 2 starts.
- **R3.4 Layer 2 is bound to the same commit.** Layer 1 passes the verified
  commit id to Layer 2, which refuses when the tag name resolves to anything
  else and deploys by the id. Today Layer 2 resolves the tag name again; that
  is the gap between check and use.
- **R3.5 Dependencies** are installed only from the lock file in the verified
  tree (`uv sync --frozen`, hash-pinned). An unattended run refuses any route
  that would resolve dependencies afresh.

**Residual risks.**

- The dependency packages come from the package index. Their hashes are
  signed with the tag; the index's availability and the `uv` binary are not.
- A process with write access to the clone between the byte comparison and
  the end of the run can change files under it. That process could already
  change the installed daemon.
- The attended route is unchanged: it still runs Layer 1 from `main`.

### Ruling 4: a clean stop at any step that asks the user

**Ruling: a question that can be known before deploy stops the run before
deploy, in code. A question met after deploy is left unanswered, recorded
where the next human will see it, and never guessed.** "Leaves the current
version running" is only possible before deploy, so the ruling moves every
knowable question there.

- **R4.1 Marker.** Post-upgrade tasks and upgrade guides gain a metadata
  field, `Requires human: yes|no`. The pre-deploy gate reads it for every
  version crossed and lists a `yes` as an escalation, so the run refuses
  before anything changes. The release checks require the field on every new
  task and guide. A task from before the field existed counts as `no` here
  and is covered by R4.2.
- **R4.2 After deploy.** The skill leaves any step that asks undone, skips
  step 9 (optimise), completes the rest, and prints one line starting
  `AUTO-UPGRADE PAUSED:`. It also appends the item to
  `<clone>/untracked/auto-upgrade/pending-human`, and `version_check`
  reports that file at every SessionStart until a human clears it. The new
  version keeps running: it passed the health check, and rolling back
  because of an open question would trade a working install for a loop.
- **R4.3 No answer is ever invented.** The skill text says so, and its
  acceptance test pins the wording.

**Residual risks.**

- R4.2 depends on the agent following the skill text. No code can tell that a
  sentence in an old task is a question.
- The owner's phrase "leaves the current version running" is met exactly for
  R4.1 and not for R4.2, where the new version is the one running.

### Ruling 5: dirty-tree refusal limited to the daemon's own paths

**Ruling: refuse only when an upgrade-owned path or the clone is dirty; other
work in the project does not block. Retry at the next SessionStart only.**

- **R5.1 Scope.** Dirty means any `git status --porcelain` entry, untracked
  files included, under the upgrade-owned paths (`.claude/hooks-daemon/`,
  `.claude/hooks-daemon.yaml`, `.claude/skills/hooks-daemon/`,
  `.claude/hooks/`, `.claude/settings.json`) or the signers file, or any
  entry in the clone's own status (review M11).
- **R5.2 One list.** The owned-path list exists in Layer 1, in
  `auto_upgrade.py` and in skill step 7. A test holds the three equal.
- **R5.3 The commit takes only the owned paths.** The unattended commit
  names them as a pathspec (`git commit --only -- <paths>`), so nothing
  another agent staged is swept in. It never pushes and never switches
  branch.
- **R5.4 No retry loop.** A dirty refusal writes no attempt record. The
  Python pre-check mirrors the refusal, so the next invitation comes only at
  a later SessionStart whose pre-check passes (review M3). Nothing waits,
  polls or re-runs inside a session.

**Residual risks.**

- An edit another agent makes to an owned path while the upgrade runs is
  committed under the upgrade's name. The window is the length of the run.
- The upgrade commit lands on whatever branch the shared checkout has checked
  out, as the attended route's does.
- In a busy shared checkout an owned path may be dirty at every SessionStart,
  and the upgrade then never happens. It fails safe, and silently apart from
  the SessionStart line.

### Ruling 6: one injected line

**Ruling: the injected text is one line of at most 300 characters, and
nothing is injected while the authorisation is not usable (R1.1).** The line
must say: whether it is the shipped default or a recorded request; that the
only route is the hooks-daemon skill's upgrade with `--unattended`; to stop
at any refusal; and the opt-out. The full list of refusals lives in the
skill, not in the prompt. Review F3's fail-closed tests stay.

Shipped-default wording, to be used as written unless a test shows it too
long: `STANDING AUTHORISATION (the daemon's shipped default, not a request this project recorded): upgrade the hooks daemon to a newer signed release only through the hooks-daemon skill with --unattended, and stop at any refusal. Off: {id: daemon-auto-upgrade, enabled: false}.`

**Residual risks.**

- One line cannot carry the limits. An agent that reads only the line knows
  less than before; the limits hold because the scripts enforce them.
- The line still reaches every prompt cadence of every project with a key.

## 11. Open after the build (for review and the owner)

- **Settled in section 11a:** the skill's confirmation steps (ruling 4), the
  Layer 1 source (ruling 3), shared checkouts and the dirty-tree refusal
  (ruling 5), and the injected text (ruling 6).
- **Still needed from the owner, and not blocking the build:** the
  release-signing public key, added to each project with the R2.3 command;
  and where third parties are to obtain its fingerprint. Until a project has
  the key, its unattended upgrades refuse.
- **A waiter that takes the lock after the holder finished.** With
  `--lock-wait` and no VERSION, it resolves the latest release, which is now
  the installed one, and runs a same-version reinstall: wasteful, not
  harmful. The session-start trigger does not cause it, because the next
  version check reads "up to date". It is not tested.
- **Unproven end to end.** The flag handoff is tested from Layer 1 into a
  stub Layer 2, and Layer 2's refusal from a direct call; no test runs both
  real layers on a `breaking: true` manifest. The unattended rollback is
  tested against stubs of the snapshot restore and the daemon restart.

## 12. Threat model

What is defended: the code an unattended run installs and executes, and the
project's tracked files. Who is trusted: the holder of a release-signing key
the project's human listed, the installed daemon version, and the human who
commits to the project. Not trusted: the repository host, the network, tag
names, release text outside the signed commit, the environment of the agent,
and other agents sharing the checkout. Out of scope: an attacker who already
runs code as the user in the project (they need no upgrade to do harm).

| Threat                                                            | Defence                                                                                                                                                   | What remains                                                                                           |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| T1 Hostile release notes or guides                                | Unattended reads upgrade material only from files inside the verified commit (R6t.1 below); the gate's decisions use manifests, not prose                 | A signed release can still carry bad instructions; that is the signing key's trust                     |
| T2 Tag spoofing: forged, moved or re-pointed tag, hijacked origin | Signature against a project-held key (R2.1, R2.2); the fetched object must be the published one; replace objects off                                      | Theft of the signing key                                                                               |
| T3 Renamed or replayed old signed tag                             | The tag header must name the tag; the commit's `version.py` must name the version                                                                         | None known                                                                                             |
| T4 Downgrade or sideways install                                  | Strictly newer than the installed clone's version (R1.3); baseline never from the tracked stamp                                                           | Withholding the newest tags makes an install take an older, genuine, newer-than-installed release      |
| T5 Freeze: newer tags hidden                                      | None; the install stays where it is                                                                                                                       | Same as today; `version_check` cannot tell                                                             |
| T6 Check-to-use gap between verification and run                  | Verification repeated under the lock; target named by commit id from then on; Layer 1 byte-compared; Layer 2 bound to the id (R3.3, R3.4)                 | A local writer to the clone during the run                                                             |
| T7 Hostile project config switches it on                          | Switching on is inert without a tracked, committed key (R1.1, R2.1); a hostile project that ships both still needs a tag on the daemon's origin it signed | A hostile repository that is opened with hooks enabled already runs its own code; not an escalation    |
| T8 Agent adds its own key                                         | Built-in write guard, denied key command, no terminal (R2.4); key must be committed (R2.1)                                                                | A compromised agent with a shell; out of scope above, stated in ruling 2                               |
| T9 Environment redirection                                        | Entry refuses the redirecting variables (R3.2); git config overrides in the environment removed; `ssh-keygen` from the system path (R2.2)                 | A hostile `git` earlier on `PATH`; that attacker already runs code                                     |
| T10 Lock abuse                                                    | A held or forged lock only stops upgrades (exit 75); the lock grants nothing; a lock path that is not a regular file is refused (R6t.2)                   | Denial of upgrade by anyone who can write the git directory                                            |
| T11 Rollback or retry loop                                        | One attempt per release, `started` record before deploy (R1.7); a failed rollback stops all unattended runs until a human clears it (R6t.3)               | Each new release gets one attempt; a run of bad releases costs one rollback each                       |
| T12 Prompt injection into the agent running the skill             | T1's rule; the commit takes only owned paths (R5.3); no push; version strings validated before use; one fixed injected line (ruling 6)                    | Text in the signed tree is trusted like its code; the agent's other inputs in the session are not ours |
| T13 Unsigned code fetched during the run                          | No fetch from `main`: shim, entry and self-bootstrap (R3.1, R3.2); dependencies from the signed lock file (R3.5)                                          | The package index and the `uv` binary                                                                  |
| T14 A bad, honestly signed release                                | Soak period (R1.6); health check and rollback (section 7); MAJOR and breaking releases never unattended                                                   | A fault that passes the health check and is not withdrawn within a day                                 |

Requirements that arise only from the threat model:

- **R6t.1** Under `--unattended` the skill and the gate read release notes,
  guides, tasks and manifests only from the clone at the verified commit.
  Nothing is read from the hosting site's release page or API, or from `main`.
- **R6t.2** The lock path, its beat file and takeover files must be regular
  files; a symlink or FIFO there is a refusal (review M7).
- **R6t.3** When the unattended rollback itself fails, the run writes
  `<clone>/untracked/auto-upgrade/halted` with the reason. While it exists no
  unattended upgrade of any version is invited or run, and `version_check`
  reports it at every SessionStart.

## 13. Tests that must exist

Each is written first and seen failing. Every one uses scratch repositories,
throwaway keys and fake releases.

| Id  | Test                                                                                                                                                                      | Covers         |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| V1  | No signers file, an empty one, a comment-only one: refusal, `HEAD` unchanged, no attempt record; after a committed key the same version proceeds                          | R1.1, R2.1     |
| V2  | Signers file present but untracked, or modified against `HEAD`, or a symlink into the clone: refusal                                                                      | R2.1           |
| V3  | A `cert-authority` line in the signers file: refusal                                                                                                                      | R2.1           |
| V4  | Tag signed by an unlisted key; unsigned annotated tag; lightweight tag; GPG-signed tag: each refused; the unlisted-key case writes a `needs-human` record                 | R2.2, R2.5     |
| V5  | A validly signed old tag object published under a newer name: refused                                                                                                     | T3             |
| V6  | A tag moved on origin after the entry verified it and before Layer 1 takes the lock: Layer 1 refuses                                                                      | R3.3           |
| V7  | The local tag ref re-pointed between Layer 1's verification and Layer 2: Layer 2 refuses on the commit id                                                                 | R3.4           |
| V8  | A `refs/replace/` entry for the verified commit: the installed tree is still the signed one, or the run refuses                                                           | R2.2           |
| V9  | A fake `ssh-keygen` that always succeeds, first on `PATH` and inside the project: not used                                                                                | R2.2           |
| V10 | Each redirecting environment variable set: the entry refuses                                                                                                              | R3.2           |
| V11 | A release whose `upgrade.sh` differs from the one being run: refused; the shim with `--unattended` makes no network call                                                  | R3.1, R3.3     |
| V12 | `enabled: false`, a malformed entry, `disable_tags`, and self-install: the ENTRY refuses, not only the notice                                                             | R1.5           |
| V13 | A release first seen under 24 hours ago: refused; the same release a day later: proceeds; a deleted sighting record restarts the wait                                     | R1.6           |
| V14 | A leftover `started` record: that version is not invited and is refused                                                                                                   | R1.7           |
| V15 | Same version, older version, pre-release, and a tracked stamp above the clone's version: each refused                                                                     | R1.3           |
| V16 | A release-state file that is a dangling symlink: refused                                                                                                                  | R1.3           |
| V17 | A crossed task marked `Requires human: yes`: the gate escalates and nothing is deployed; the release check fails a new task with no field                                 | R4.1           |
| V18 | The pending-human file is reported by `version_check` until removed                                                                                                       | R4.2           |
| V19 | Unrelated dirty and STAGED files in the project: the upgrade proceeds and its commit holds only owned paths                                                               | R5.1, R5.3     |
| V20 | The three owned-path lists are equal                                                                                                                                      | R5.2           |
| V21 | The once-only notice: shown once without a key, once more when a key appears, never again; nothing injected without a key; the injected line is one line within the limit | R1.1, R1.2, 6  |
| V22 | Only one id is default-on                                                                                                                                                 | R1.4           |
| V23 | `release-signers add`: refuses without a terminal, refuses a URL, refuses weak keys and options, needs `--rotation` for a key that does not verify the installed tag      | R2.3           |
| V24 | The write guard denies file-tool and Bash writes to the signers path, and cannot be configured away; the key command is denied to an agent's Bash                         | R2.4           |
| V25 | A key with `valid-before` in the past and a tag dated before it: record what git does, so R2.6's statement is a tested fact                                               | R2.6           |
| V26 | A lock path that is a symlink or a FIFO: refusal, no hang                                                                                                                 | R6t.2          |
| V27 | A rollback that fails writes the halt file; no version is invited while it exists                                                                                         | R6t.3          |
| V28 | Both real layers end to end on a signed fake release: success; a `breaking: true` manifest; a daemon that will not start (real rollback, old tag back, old daemon up)     | section 11, M9 |
| V29 | The release procedure refuses to publish a tag that does not verify                                                                                                       | R2.7           |
| V30 | An unattended run performs no dependency resolution outside the lock file                                                                                                 | R3.5           |
