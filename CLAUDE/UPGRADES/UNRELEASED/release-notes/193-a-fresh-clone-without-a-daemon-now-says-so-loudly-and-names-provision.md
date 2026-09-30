# Callout: a fresh clone without a daemon now says so loudly and names `provision`

**Plan**: 00477
**Audience**: operators

A fresh clone of a project that uses the daemon has the tracked hooks but not the daemon, so every safety handler is off. Until now the only sign was a generic "Hooks daemon: Not installed" block in the agent's context, pointing at `/hooks-daemon install` and a session restart. Neither was right: `install` adds the daemon to a project and picks a version itself, and no restart is needed after a provision.

The hooks now detect this state (tracked `.claude/hooks-daemon.yaml` and `.claude/provision.sh` present, no daemon clone) using file tests and one small awk read in bash, with nothing from the venv. The answer is one message naming the checkout, the expected version (from `daemon.expected_version`, else the `.claude/HOOKS-DAEMON.md` header, else "unknown"), and the exact command: `bash .claude/provision.sh` or `/hooks-daemon provision`. The human sees it as a `systemMessage` at SessionStart and on every prompt, the agent sees it as `additionalContext`, and the status line prints a one-line version of it in place of "DAEMON FAILED".

A new key, `daemon.unprovisioned_mode`, chooses what else happens: `warn` (the default) blocks nothing; `block` denies every tool call and the Stop hook until the checkout is provisioned, except the provision command on its own and the hooks-daemon `provision` skill call. A command that chains, pipes, pads with flags or merely mentions the provision command is still denied. A project with `ci_enabled: true` keeps its own blocking behaviour, and a clone that is present but has no venv still gets the repair message, not this one.

Under `warn`, the Stop hook no longer blocks in this state (it used to, with the generic message); it shows the same message to the human instead.
