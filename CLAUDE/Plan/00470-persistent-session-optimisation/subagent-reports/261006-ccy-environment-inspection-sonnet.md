# ccy environment inspection (Plan 00470 Tasks 2.3 and 3.5)

Read-only inspection of this VM's session and the fedora-desktop reference clone
(freshness sweep run; clone at commit 1f0c9eb1, up to date). Nothing was signalled,
restarted or edited. The host is written as "this VM"; IDs are redacted.

## What this session is

- It runs inside a ccy CONTAINER on this VM, not on the VM's own systemd. The
  process tree (`ps`) is: PID 1 `tini` -> `entrypoint.sh claude --dangerously-skip-permissions --continue`;
  PID 2 `python3 /workspace/.claude/ccy/claude-supervise.py --arm -- claude ... --continue` (the PTY host);
  PID 64 `claude` (child of the host); and a `--worker --arm` subprocess (child of the host).
- Env: `CCY_CLAUDE_WRAPPER=python3 /workspace/.claude/ccy/claude-supervise.py --arm --`
  (the in-repo script, run directly; the `claude-supervise` shell launcher is not in
  the chain here), `CCY_HOST_HOSTNAME` is set to the VM's name (the container's own
  `HOSTNAME` is a container id), `CCY_FLAG_COMPACT=1`, lifecycle vars are empty
  (no `--max-age`/`--run-for`), `HOOKS_DAEMON_HOSTNAME` is NOT set.
- The container runs the supervisor from the bind-mounted `/workspace`, so the code is
  this repo's `.claude/ccy/claude-supervise.py`, not a copy installed by fedora-desktop.
  fedora-desktop carries its own, older, differing copy
  (`.claude/ccy/claude-supervise.py`, 359 KB vs 469 KB here; `cmp` differs at line 106)
  that is its own development tree, not what this container executes.

## Q1. How new supervisor code goes live (Task 2.3)

- Mechanism: the in-repo file plus `--worker` hot reload, as in
  `.claude/rules/ccy-supervisor-dogfooding.md` and `CLAUDE/development/CcySupervisor.md`
  lines 65-113 (content hash with mtime pre-check, polled about every 5 s). All
  injection decisions, including the Task 2.3 watchdog, are in the worker
  (`claude-supervise.py:2848-2880`: `_CRON_WATCHDOG_QUIET_SECONDS` = 2 h of PTY quiet,
  every record past 7 days, reads `cron-records.json`). The PTY host (PID 2, started
  three days ago) never reloads, and does not need to for this feature.
- Already reloaded: the file's mtime is 07:25:05 UTC today and the git tree is clean
  for it (HEAD contains the watchdog code, commit message "Task 2.3" at 04:01 UTC).
  The live worker's start time is 07:25:08 UTC, three seconds after the last write,
  so it runs the current on-disk code. No restart is needed.
- Verify without touching anything:
  1. `ps -eo pid,ppid,lstart,args` and find `claude-supervise.py --worker`; its
     `lstart` must be later than `stat -c %y .claude/ccy/claude-supervise.py`.
  2. `git status --short .claude/ccy` must be empty (disk equals HEAD).
  3. `untracked/supervise/decision.log` records `worker died ... respawned` only on a
     kill; a reload leaves a new pid. (This log has no "reload" lines here, so the pid
     and start time are the evidence, not the log.)
     Caveat from the doc: a redeploy that preserves mtime (`cp -p`, `rsync -a`) can
     change content without a reload; in that case the start-time check fails and the
     one-time `kill <worker-pid>` in the doc is the (owner-approved) fix. Not needed now.
- Not verified: that the watchdog has ever fired. It needs 2 h of PTY silence with all
  recorded crons expired, which this busy session has not had.

## Q2. What restarts ccy after a crash or reboot (Task 3.5)

Findings, with fedora-desktop citations (paths under `untracked/repos/fedora-desktop`):

- Reboot: `files/home/.config/systemd/user/ccy-sessions-restore.service` (a `Type=oneshot`
  user unit, `ExecStart=%h/.local/bin/ccy-sessions restore`, `WantedBy=default.target`).
  It is enabled only where `ccy_restore_sessions: true` is declared in host_vars
  (`playbooks/imports/play-claude-yolo.yml:751-819`; headless boxes set
  `RUN_BASH_CCY_RESTORE_SESSIONS=1`), and needs user linger
  (`play-systemd-user-tweaks.yml`). Each restore starts the recorded session detached
  in tmux with the recorded arguments plus `--continue` (`docs/ccy.md:219-250`).
  This is a one-shot at boot, not a supervisor loop.
- Evidence this VM does use it: PID 1's args end in `--continue`, which ccy itself does
  not add on a first launch. I cannot see the host's systemd from the container, so
  whether the unit is enabled is UNVERIFIED from here; the check is on the VM host:
  `systemctl --user is-enabled ccy-sessions-restore.service` and
  `ccy-sessions verify-restore` (`docs/ccy.md:279-283`).
- Crash (the `claude` process or supervisor dies, VM stays up): nothing restarts it.
  `docs/ccy.md:209` states "`claude` exits: container removed ... the tmux session
  closes", the session record is removed when the launcher returns, so a later reboot
  restore does not bring it back either. The only automatic relaunch is the supervisor's
  own exit 75 path (`restart-request.json`), handled by
  `files/var/local/claude-yolo/lib/restart-request.bash`: it relaunches with
  `--resume <session-id>` (it strips any `--continue`, lines 212 and 289-296), at most
  3 per project per hour (`CCY_RESTART_MAX`, `CCY_RESTART_WINDOW_SECONDS`,
  `docs/ccy.md:1343-1347`), and refuses when a prompt has no safe answer.
  `claude-supervise.py` itself never restarts a child that exits.
- `autoContinueAtUsageLimit`: not set. `grep` finds 0 matches in `/root/.claude/settings.json`
  (445 bytes, user scope), `.claude/ccy/settings.json` and `.claude/settings.json`, and
  0 in the whole fedora-desktop tree (excluding plans/tests), so fedora-desktop does not
  provision it either. The RUNBOOK section 1 requirement is therefore unmet on this VM.

What is missing, as steps for an infra agent:

1. Decide whether a ccy crash must self-heal. If yes, add to fedora-desktop a host-side
   watchdog, for example a `systemd --user` timer or a `.service` with `Restart=on-failure`
   plus `RestartSec` and `StartLimitIntervalSec`/`StartLimitBurst` (the backoff the
   RUNBOOK requires), that runs `ccy-sessions restore` (or `ccy --continue` in the project
   directory) when a session record exists but no live tmux session does. Today the
   record is deleted on any clean launcher return, so the watchdog needs either a
   record kept for "should be running" sessions or an explicit project list. Do not
   loop on authentication failure; stop and alert instead.
2. Confirm `ccy_restore_sessions: true` and linger on this VM's host_vars, and run
   `ccy-sessions verify-restore` after a test reboot (rehearse with
   `ccy-sessions restore --dry-run`).
3. Provision `autoContinueAtUsageLimit: true` in USER settings for the container's account
   (`/root/.claude/settings.json` inside the container). Since that file lives in the
   persisted `~/.claude` volume, fedora-desktop's claude-yolo provisioning or the entrypoint
   must merge the key idempotently (never into project settings, which turn it off).
   Requires Claude Code 2.1.234 or later; this session reports 2.1.288.
4. Decide `HOOKS_DAEMON_HOSTNAME` for this VM. It is unset in the container, and fedora-desktop
   only exports `CCY_HOST_HOSTNAME` (`docs/ccy.md:376`; `files/var/local/claude-yolo/lib/common.bash`,
   `scripts/test-ccy-host-hostname.bash`). To set it, add it via the project's
   `.claude/ccy/ccy.env` (a tracked, sourced file; `docs/ccy.md:840-869` says it must be
   `export`ed) or via ccy's env pass-through.
5. Update RUNBOOK section 3 once the above exists: it currently says "owner input" for the
   restart loop and for the spelling of `--continue`; the answer is `ccy-sessions restore`
   adds `--continue` itself, and the supervisor-driven restart uses `--resume <id>`.

## Q3. Other conflicts with this repo's assumptions

- RUNBOOK section 3 says `ccy.env` sets the wrapper to `claude-supervise.py --arm --`; in
  this container the wrapper is the python script directly, and `.claude/ccy/ccy.env`
  (`:37`) points at the `claude-supervise` shell launcher (Python 3.11 gate). Two
  sources set the same variable (project `ccy.env`, and `/root/.claude/ccy.env`
  line 37 which exports it); the effective value is the direct script. Harmless today,
  but a Python below 3.11 would not fall back to "run unsupervised" here.
- Restart wording: with `--continue` in PID 1's args, a ccy-driven restart rewrites it
  to `--resume <session-id>` (`restart-request.bash:212-296`); RUNBOOK section 2 says
  `--continue` only. Both restore crons; note the difference in the runbook.
- Restart cap: the 3-per-hour cap (`CCY_RESTART_MAX`) is an upper bound on the
  `ExitForRestart` loop that RUNBOOK does not mention.
- `.claude/ccy/state/` does not exist yet (no restart request has ever been written),
  so the exit-75 path is untested on this VM.
- No signal handling conflicts were seen. The supervisor injects by typing into the
  PTY (`CcySupervisor.md:26-38`), so any prompt with no safe answer in the pane (SSH
  passphrase, token choice) blocks an unattended restore; on a `server` profile the
  passphrase is supplied from a 0600 file (`docs/ccy.md:261-276`).
- The ccy session is a container: no host systemd is reachable from inside it, so every
  restart-loop item above is host-side work, outside this repository.
