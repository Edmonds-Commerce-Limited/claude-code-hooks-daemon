# Daemon-Shipped Agent Assets

The daemon ships sub-agent definitions into your project's flat
`.claude/agents/` namespace through a generic, version-tracked subsystem
(Plan 00279, `install/agent_assets.py`). Every deployed agent is namespaced
`hooks-daemon-*` so it cannot collide with your own agents.

## Shipped agents

| Agent                            | Gating config key              | Default  | Purpose                                                                                                                                       |
| -------------------------------- | ------------------------------ | -------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `hooks-daemon-plan-dedupe-scout` | `plan_workflow.enabled`        | disabled | Reads still-live plans and reports ones already covering proposed work, before a duplicate plan is filed                                      |
| `hooks-daemon-opus-security`     | `agents.opus_security.enabled` | disabled | Quarantine executor for safeguard-flaggable security work; the caller delegates before reading the sensitive content and gets a clean summary |

## Lifecycle

- **On daemon start** the deployed files are synced with config: an enabled
  agent that is absent or outdated is (re)deployed; a disabled-but-present
  agent produces a removal advisory in the daemon log — the daemon never
  deletes an agent itself.
- **Version tracking**: each shipped file carries a
  `<!-- hooks-daemon-agent-version: X.Y.Z -->` marker, and the daemon keeps a
  ledger of the content md5 of every revision it ever shipped.
- **Customisation detection**: a deployed file matching any shipped revision
  is pristine (upgrades may refresh it); a file matching none is CUSTOMISED
  and is never overwritten or removed — a loud warning names it instead.

**Customising daemon-owned agents is strongly discouraged.** Your edits are
invisible to upgrades, so prompt fixes never reach the file. Copy the agent to
a name of your own (dropping the `hooks-daemon-` prefix) and edit that copy.

## CLI

```
hooks-daemon agents list              # shipped agents, versions, gating keys
hooks-daemon agents status            # absent | current | outdated | customised
hooks-daemon agents install [name]    # config-gated deploy (all, or one agent)
hooks-daemon agents remove <name>     # removes a pristine file; refuses customised
```

## The opus-security agent

`hooks-daemon-opus-security` is an execution space for work that could trip a
caller-side content safety classifier (which can silently substitute a
different model for the rest of the session). The contract:

- The caller delegates the WHOLE flaggable sub-task before reading the
  content ("scouting first is reading first").
- The subagent communicates only via two files: a mandatory
  `<name>-opus-security-SUMMARY.md` (clean, operational language — the only
  file the coordinator reads) and an optional
  `<name>-opus-security-DETAIL.md` (the raw substance; never read by the
  coordinator).
- The subagent owns the entire git cycle for the flaggable files; the
  coordinator confirms CI by status, never by diffing content.

Your project should provide its own delegation-boundary document defining
which of its work is flaggable; the agent honours it when present.
