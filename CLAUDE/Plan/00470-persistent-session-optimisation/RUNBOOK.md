# Plan 00470 runbook: running an always-on session

How to keep one Claude Code session running on a server. Each fact cites its
source; anything not verified from this repository or the vendored docs is
marked as an owner input.

## 1. Continue automatically after a usage limit

Set `autoContinueAtUsageLimit: true` in the **user** settings file of the
account the session runs as (or in managed settings, or a `--settings` file).

- Source: `remote-docs/docs.claude.com/en/docs/claude-code/settings-reference.md`,
  section `autoContinueAtUsageLimit`. It requires Claude Code v2.1.234 or later.
- **Do not put it in the project's `.claude/settings.json`.** The key is read
  only from user, managed and `--settings` scope. When none of those sets it, a
  project or local settings file that sets it turns the feature **off**.
- `/config autoContinueAtUsageLimit=false` can turn it off but never on, because
  the setting grants unattended execution. Turn it on in `/config` (**Continue
  automatically at usage limit**) or by editing the user settings file.
- The wait can end without continuing when the reset is far away, which a weekly
  limit can be (Notification `quota_auto_resume_disabled`; the exact rule is in
  `remote-docs/code.claude.com/docs/en/hooks.md`). The failsafe cron is then
  the only recovery, and it needs a live session.
- A wait that spans a long host sleep stops for an `Enter` instead
  (`quota_auto_resume_stale`, same doc). Keep the server awake.
- Sub-agents in flight at the limit are not re-dispatched (RESEARCH.md §4
  probe 3). Task 3.3's work queue covers that.

## 2. Restart with `--continue`

Restart the session with `claude --continue` so it resumes the most recent
conversation in that directory.

- `--continue` and `--resume` restore unexpired `CronCreate` jobs, and nothing
  else does (`remote-docs/code.claude.com/docs/en/scheduled-tasks.md`). A plain
  `claude` start loses every cron. `persistent_cron_assertor` then asks for the
  declared ones again at SessionStart.
- Recurring crons still expire (the limit is in the same doc).
  `cron_stop_enforcer` denies a stop once a declared job is older than
  `refresh_after_days`, naming the CronDelete and CronCreate that refresh it.

## 3. Under the ccy supervisor

This project's `.claude/ccy/ccy.env` sets `CCY_CLAUDE_WRAPPER` to
`claude-supervise.py --arm --`, so ccy launches `claude` as the supervisor's
child. The supervisor returns the child's exit code (`main()` in
`.claude/ccy/claude-supervise.py`). It does not restart a child that exits.

**Owner input:** the restart loop around ccy on the host (a systemd unit with
`Restart=always`, or a shell loop) is outside this repository, and so is the
spelling of ccy's `--continue` pass-through. Record the unit used on the
server here once it exists. Requirements for it:

- It passes `--continue` on every restart after the first.
- It sets `HOOKS_DAEMON_HOSTNAME=cchd-sdlc-runner` when the session is the SDLC
  runner, so the `issue-sdlc` job's `hosts:` filter declares it (PLAN.md
  Task 6.2).
- It backs off between restarts. A session that dies at once on start, for
  example on an authentication failure, must not spin.
- A usage ceiling (Plan 00479), if wanted, goes in that host's `hosts:` entry,
  never in this repository's tracked config.

## 4. After any restart

- Run `bin/hooks-daemon status`. The daemon starts on the first hook call;
  the status confirms it runs the current code.
- CronList, and reconcile against the declared jobs the SessionStart context
  lists.
- Re-brief lost agents from their worktrees. This step stays manual until
  Task 3.3's queue exists.
