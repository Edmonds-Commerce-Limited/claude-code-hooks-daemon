# Plan 00499 Task 3.1: request for fedora-desktop IaC

A draft for the owner to file on fedora-desktop or hand to a fedora-desktop session. Nothing here has been filed.

## Title

IaC writes the hooks-daemon repository's `.claude/ccy/ccy.env.local` on the sdlc runner VM, readable inside the
container

## Body

The hooks-daemon project ruled (2026-10-06) that `.claude/ccy/ccy.env.local` is written by IaC or a human only, never
by an agent or by the hooks daemon. Agents and ccy may read it. The daemon will enforce the agent side with a
`write_protected_paths` guard (hooks-daemon Plan 00499).

For the hooks-daemon checkout on the always-on sdlc runner VM, IaC should write:

```bash
# Managed by IaC. Do not edit by hand or from an agent.
# based on ccy.env.local.dist <version, once the daemon ships the template>
export HOOKS_DAEMON_HOSTNAME=cchd-sdlc-runner
```

What it does: it gives that session the `cchd-sdlc-runner` role, which turns on the 80% usage ceiling under
`hosts:` in `.claude/hooks-daemon.yaml` and makes the session host the `issue-sdlc` cron (hooks-daemon Plan 00479,
owner ruling D8). ccy 3.80.0+ sources the file after `ccy.env`.

**Readability, found 2026-10-06.** A `ccy.env.local` appeared in that checkout after the agent-written copy was
removed. Inside the container, root cannot stat it (`Permission denied`; `ls -la` prints `?????????`), and it is not
a bind mount. That pattern fits an SELinux label the container is not allowed to read. ccy itself does
source it: after the host reboot the session had `HOOKS_DAEMON_HOSTNAME=cchd-sdlc-runner`. Only the in-container read
fails, so agents cannot read it, though the ruling allows reading.

Please write it with a label and mode the container can read, for example the same context as the sibling
`ccy.env`. Confirm with `cat .claude/ccy/ccy.env.local` inside a ccy session.

**Acceptance:**

- From inside a ccy session, `cat .claude/ccy/ccy.env.local` shows the line above.
- After the next ccy launch, `echo "$HOOKS_DAEMON_HOSTNAME"` inside the session prints `cchd-sdlc-runner`.
- `git status` in that checkout does not show the file (it stays ignored).
