# Claude Code plugins alongside the daemon

This is the canonical home for how the hooks daemon and **Claude Code plugins**
coexist in one project: which scope to install a plugin at, the trust gate,
how plugin hooks interact with the daemon's, and how plugin agents and skills
are named. Other documents link here rather than restating it.

Every upstream claim below cites the vendored copy of the Claude Code
documentation under [`remote-docs/code.claude.com/docs/en/`](../remote-docs/code.claude.com/docs/en/),
captured with `remote-docs add` (see [RemoteDocs.md](RemoteDocs.md)). When one
of those pages is past its `stale_after` date, refresh it before relying on a
claim here.

## Two meanings of "plugin"

The word names two unrelated things in this project, so always qualify it:

| Term                               | What it is                                                                                                                                                                                                                                           | Configured in                                                                                     |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| **daemon plugin (handler module)** | A Python handler module the daemon loads from the `plugins:` block of `.claude/hooks-daemon.yaml` (`src/claude_code_hooks_daemon/plugins/loader.py`). It runs inside the daemon, like a built-in handler. Project handlers are usually a better fit. | `.claude/hooks-daemon.yaml` — see [docs/guides/CONFIGURATION.md](../docs/guides/CONFIGURATION.md) |
| **Claude Code plugin**             | A package that Claude Code itself installs from a marketplace, bundling skills, agents, hooks, MCP servers or LSP servers. The daemon does not load it; Claude Code does.                                                                            | `enabledPlugins` in a Claude Code settings file, or `/plugin`                                     |

The rest of this document is about Claude Code plugins.

## Choosing a scope

A Claude Code plugin is enabled at one of four scopes, each writing
`enabledPlugins` into a different settings file
([plugins-reference.md § Plugin installation scopes](../remote-docs/code.claude.com/docs/en/plugins-reference.md#plugin-installation-scopes)):

| Scope     | Settings file                 | Who gets the plugin                                         |
| --------- | ----------------------------- | ----------------------------------------------------------- |
| `user`    | `~/.claude/settings.json`     | You, in every project (the `claude plugin install` default) |
| `project` | `.claude/settings.json`       | Every collaborator who clones the repository                |
| `local`   | `.claude/settings.local.json` | You, in this repository only                                |
| `managed` | Managed settings              | Everyone the administrator's policy covers; read-only       |

**Project scope is a team decision, not a personal one.** It writes to the
same committed `.claude/settings.json` that holds the daemon's own hook
registrations, so it reaches every collaborator who has the commit
([discover-plugins.md § Install plugins](../remote-docs/code.claude.com/docs/en/discover-plugins.md#install-plugins)).
Treat it like any other change to shared settings: put it through review. Two
consequences follow for collaborators:

- A project-enabled plugin from an external source (a GitHub repository or an
  npm package) does not load until each collaborator installs it. Claude Code
  reports it as not installed and prints the `claude plugin install` command
  ([discover-plugins.md § Configure team marketplaces](../remote-docs/code.claude.com/docs/en/discover-plugins.md#configure-team-marketplaces)).
- A collaborator who does not want it can, when uninstalling it, choose to
  disable it for themselves only. Claude Code writes that override to their
  `.claude/settings.local.json` and leaves the shared file alone
  ([discover-plugins.md § Manage installed plugins](../remote-docs/code.claude.com/docs/en/discover-plugins.md#manage-installed-plugins)).

Choose `local` to try a plugin without committing anyone else to it, and
`user` for a plugin you want in every project.

**This repository enables its own dogfood plugins at local scope.** Its
`.claude/settings.json` is the template the daemon's installer and upgrader
deliver to client projects, so a plugin enabled there would be enabled in
every client.

## The trust gate

Project-scoped plugin content comes from the repository rather than from you,
so Claude Code holds it behind the workspace trust dialog:

- Marketplaces that a project's `.claude/settings.json` declares under
  `extraKnownMarketplaces` are added only once the collaborator trusts the
  repository folder
  ([discover-plugins.md § Configure team marketplaces](../remote-docs/code.claude.com/docs/en/discover-plugins.md#configure-team-marketplaces)).
- A plugin checked into the repository's `.claude/skills/` loads only after the
  trust dialog is accepted for that folder. Trusting a parent folder, or
  running with `-p`, is not enough. Its MCP servers still need per-server
  approval, its LSP servers start only once the workspace is trusted, and its
  background monitors do not load
  ([plugins-reference.md § Skills-directory plugins](../remote-docs/code.claude.com/docs/en/plugins-reference.md#skills-directory-plugins)).

Trust is a gate on loading, not a review of content. Upstream is explicit that
plugins "can execute arbitrary code on your machine with your user privileges"
([discover-plugins.md § Security](../remote-docs/code.claude.com/docs/en/discover-plugins.md#security)).
Read a plugin's hooks before you enable it, for the reasons below.

## Plugin hooks run in parallel with the daemon's

A plugin can ship hooks in `hooks/hooks.json`. When the plugin is enabled,
those hooks merge with the user and project hooks, the daemon's registrations
among them
([hooks.md § Hook locations](../remote-docs/code.claude.com/docs/en/hooks.md#hook-locations)).
Claude Code then runs every matching hook in parallel
([hooks.md § Hook handler fields](../remote-docs/code.claude.com/docs/en/hooks.md#hook-handler-fields)),
inside subagents as well as in the main conversation.

What that means in practice:

- **The daemon never sees a plugin hook.** A plugin hook is a separate process
  that Claude Code runs itself. None of the daemon's handlers, its hook
  registration policy or its verdict log applies to it.
- **Neither hook sees the other's verdict.** Both receive the same event
  payload and answer independently. Claude Code combines the answers afterwards.
- **Latency is set by the slowest hook.** The hooks do not add up, but the
  tool call waits for the last to finish (see
  [ARCHITECTURE.md § Configuration Locations](ARCHITECTURE.md#configuration-locations)).

### A plugin `PreToolUse` hook can replace input the daemon judged

For `PreToolUse`, Claude Code combines parallel decisions by precedence
([hooks.md § PreToolUse decision control](../remote-docs/code.claude.com/docs/en/hooks.md#pretooluse-decision-control)):

> When multiple PreToolUse hooks return different decisions, precedence is `deny` > `defer` > `ask` > `allow`.

So a daemon deny always wins: no plugin hook can overrule it.

The gap is `updatedInput`. The same section says a hook's `updatedInput`
"Replaces the entire input object", and that Claude Code evaluates permission
rules against "the input your hook returns, not the input Claude sent". When
the daemon allows a call and a plugin's `PreToolUse` hook returns
`updatedInput`, the tool runs with the plugin's input. The daemon's guards
judged the original input, never the replacement. Only Claude Code's own
permission rules are evaluated again.

Treat any plugin that ships a `PreToolUse` hook as able to run a tool call the
daemon never approved. Enable one only when you trust it at that level.

## Plugin agents and skills are namespaced

- **Skills** are always prefixed with the plugin name:
  `/<plugin-name>:<skill-name>`. A plugin skill never overrides a project skill
  of the same bare name; both stay available
  ([plugins.md](../remote-docs/code.claude.com/docs/en/plugins.md)).
- **Agents** take a scoped name made from the plugin name, any subfolder names
  under `agents/`, and the file name, joined with colons. For example
  `agents/review/security.md` in `my-plugin` becomes
  `my-plugin:review:security`
  ([plugins-reference.md § Agents](../remote-docs/code.claude.com/docs/en/plugins-reference.md#agents)).
  A same-named agent in the project's or user's `.claude/agents/` overrides the
  plugin's.
- A plugin agent's frontmatter `hooks`, `mcpServers` and `permissionMode` are
  ignored for security reasons (same section).

The scoped name is what a hook payload carries, as the Agent tool's
`subagent_type` and as `agent_type` inside a subagent
([hooks.md § Common input fields](../remote-docs/code.claude.com/docs/en/hooks.md#common-input-fields)).
Anything that names a plugin agent or skill, such as a hook matcher or an
Agent call's `subagent_type`, must use the scoped name, never the bare file
name.

## Plugin environment variables

Claude Code exports `CLAUDE_PLUGIN_ROOT` (the plugin's install directory) and
`CLAUDE_PLUGIN_DATA` (its persistent data directory,
`~/.claude/plugins/data/<id>/`) to plugin hook processes and to plugin MCP and
LSP servers. Neither is set in the Bash tool's environment
([plugins-reference.md § Environment variables](../remote-docs/code.claude.com/docs/en/plugins-reference.md#environment-variables)).
The daemon's own hook registrations are not plugin hooks, so the daemon never
receives either variable. The full hook environment table is in
[Code/HooksSystem.md § Environment Variables](Code/HooksSystem.md#environment-variables).

## Daemon support for Claude Code plugins

The daemon works out which Claude Code plugins are enabled for a project with
one resolver, `utils/claude_plugins.resolve_enabled_plugins()`. It reads:

- the Claude config dir: `$CLAUDE_CONFIG_DIR`, else `~/.claude`
  (`utils/claude_config.claude_config_dir()`). This is the daemon's own
  environment, fixed when it starts; a hook payload carries neither
  `CLAUDE_CONFIG_DIR` nor `HOME`.
- `plugins/installed_plugins.json` there. A `project` or `local` install counts
  only when its `projectPath` is this project's root.
- `enabledPlugins` from the four settings scopes, in the order managed, local,
  project, user. Only file-based managed settings are read. With no entry
  anywhere, the plugin's `defaultEnabled` applies.
- each plugin's manifest and marketplace entry, for its agents, skills,
  commands, hooks and LSP servers.

Plugins from `@skills-dir`, `@synced` or `--plugin-dir`, and settings from MDM
or a server, are not resolved. They are reported as unresolved, not guessed.

What uses it:

- The read-only dispatch logic (`dispatch_declaration`,
  `subagent_report_size_blocker`) resolves a scoped `<plugin>:<agent>` id after
  project, user and built-in agents. A plugin agent with no readable
  frontmatter counts as able to write, because Claude Code then gives it every
  tool.
- `agent_isolation_advisor` stays quiet for an agent whose file declares
  `isolation: worktree`.
- `skill-scan` does not propose a skill that an enabled plugin, or your
  personal skills, already cover.
- `tool-report` shows each enabled plugin's always-on listing cost.
- `lsp_noise_checker` asks for the config dir's `plugins/` tree to be excluded
  when that dir is inside the project.

Remaining work is tracked in
[Plan 00468](Plan/00468-claude-code-plugins-are-supported-properly/PLAN.md).
