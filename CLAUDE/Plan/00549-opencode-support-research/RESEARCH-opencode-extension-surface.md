# RESEARCH: opencode's extension surface (Plan 00549 Task 1.1)

Source of truth: `/workspace/untracked/repos/opencode` at commit `c93aaae37157d785f76a8e9a9243a6560e286468`
(`git describe`: `github-v1.2.27-52-gc93aaae371`, committed 2026-10-21). Freshness checked with
`bin/hooks-daemon reference-repos` before reading (clone up to date with upstream). Every path below is relative to
that clone. Line numbers refer to that commit.

Sister prior art: `CLAUDE/Plan/Completed/00292-codex-cli-dual-host-research/` asked the same question of Codex CLI.
This document was not checked against it line by line (see Gaps).

---

## 0. The headline you need first: there are TWO opencode plugin APIs, and the docs describe the old one

| Fact                                                                                                                                                                                                                                                                                                                                                                                                                    | Evidence                                                                                                                                                                                                       |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The code in this clone is **OpenCode V2**, package version **2.1.2** (cli, core, sdk, plugin all `2.1.2`).                                                                                                                                                                                                                                                                                                              | `packages/cli/package.json:4`, `packages/core/package.json:3`, `packages/plugin/package.json` (`"version": "2.1.2"`); `CHANGELOG.md:3` "Release notes for OpenCode V2", `CHANGELOG.md:5` "v2.1.2 — 2026-10-21" |
| The tag `github-v1.2.27` is NOT the product version; do not read it as "opencode 1.2.27".                                                                                                                                                                                                                                                                                                                               | `git describe` vs. package versions above                                                                                                                                                                      |
| The plugin package is now `@opencode/plugin` (V2). The V1 package name `@opencode-ai/plugin` appears nowhere in `packages/core`, `packages/plugin`, `packages/cli/src`, `specs`, or `CHANGELOG.md` (grep returned zero hits).                                                                                                                                                                                           | grep over those trees                                                                                                                                                                                          |
| The in-repo docs page `packages/web/src/content/docs/plugins.mdx` (the source of https://opencode.ai/docs/plugins) still documents the **V1** API: `@opencode-ai/plugin`, named exports `async ({ project, client, $, directory, worktree }) => ({ hooks })`, hook keys `"tool.execute.before"`, `"shell.env"`, `"experimental.session.compacting"`, `event`, and V1 event names such as `file.edited`, `session.idle`. | `plugins.mdx:91-99`, `:107-122`, `:131`, `:142-204`, `:243-252`, `:262-269`, `:341-358`                                                                                                                        |
| The V2 loader **rejects** that V1 module shape: it decodes `module.default` and requires `{ id: string, effect: fn }` or `{ id: string, setup: fn }`; anything else fails with `LoadError("Plugin must export a default definition with an id and an effect or setup function.")`.                                                                                                                                      | `packages/core/src/plugin/module.ts:78-91`, `:125-133`                                                                                                                                                         |
| V1 **config** keys are migrated (`plugin` -> `plugins`, `permission` object -> `permissions` rule list, `bash` -> `shell`, `write`/`patch` -> `edit`, `task` -> `subagent`), but V1 **plugin modules** are not adapted.                                                                                                                                                                                                 | `packages/core/src/config/normalize.ts:180-190`; `packages/core/src/v1/config/migrate.ts:17-32`                                                                                                                |

**Docs/code disagreement (trust the code):** anything you read on opencode.ai/docs/plugins about hook keys,
the `(input, output)` callback signature, `$` (Bun shell) in context, or `throw` in `tool.execute.before` describes V1.
A V1 plugin dropped into `.opencode/plugins/` on V2 fails to load. Whether the live website has been updated since
this clone's `packages/web` snapshot is UNVERIFIED (no WebFetch was done in this task).

Implication for the daemon: target the **V2 Promise API** (`@opencode/plugin`); V1 compatibility is not available
in the current code.

---

## 1. Plugin discovery and loading

### 1.1 Sources

1. **Auto-discovered directories.** For every config *directory* entry, the loader lists `<dir>/plugin/` and
   `<dir>/plugins/` (`packages/core/src/plugin/source-directory.ts:7`, `:9-33`). Admitted children: `*.ts`/`*.js`
   files, directories, and symlinks to either (`source-directory.ts:21-31`). Results are sorted by path
   (`:20`).
   Directory entries are the system config dir (`/etc/opencode` on Linux), the global config dir
   (`~/.config/opencode`), and every project `.opencode/` found walking up from the location directory
   (`packages/core/src/config/discovery.ts:28-32`, `:71`, `:77-90`, `:124-128`; `packages/core/src/config.ts:216`,
   `:251`, `:273-275`). `.claude/` and `.agents/` are discovered too, but only as *compatibility roots* for skills,
   not as plugin directories (`discovery.ts:129-143`; see section 6.6).
2. **Configured entries**: `opencode.json[c]` key `plugins` — an array of `string` or `{ package, options? }`
   (`packages/schema/src/config/plugin.ts:6-14`; `packages/schema/src/config.ts:103-105`). V1 `plugin` (string or
   `[name, options]` tuple) is merged in (`normalize.ts:185-190`, `packages/core/src/v1/config/plugin.ts:1-9`).
   - A string beginning `-` is a **remove** operation (`packages/core/src/config/plugin/source.ts:113-120`).
     Explicit config is applied after auto-discovery "so it can remove auto-discovered packages" (`source.ts:158`).
   - `./`, `../` and `file://` targets resolve relative to the config file; a configured local target must be a
     **directory** (a file is logged and skipped) (`source.ts:139-156`).
   - Anything else is an npm specifier, installed via the internal `Npm` service (`module.ts:103-109`).
3. **Embedded hosts**: `OpenCode.create({ plugins })` / `OpenCodeWorkerd.create({ plugins })` seed plugins
   programmatically (`CHANGELOG.md:502`).

### 1.2 Entry points of a plugin package / directory

`Host.resolve` looks for three entry points: `server` (tries `./server`, then the package root/`index`), `tui`, and
`rpc` (`packages/plugin/src/host.ts:17-43`). The server entry is the one loaded into the core
(`module.ts:111-120`). A directory plugin's server entry must resolve inside that directory (`source.ts:168-172`).

### 1.3 Policy gate, hot reload, runtime isolation

- **Managed policy** can veto a plugin: `ManagedPolicy.decision(..., "integration.use", "plugin:<target>")` ===
  `"deny"` -> `{ blocked: true }` (`module.ts:52-59`).
- **Hot reload**: local plugin source files are fingerprinted (sha256) and watched; a change re-imports the graph
  (`packages/plugin/src/source.ts:8-39`, `module.ts:18-38`). Config edits to `plugins` are also watched
  (`config/plugin/source.ts:45-92`).
- **Shared runtime**: plugins must use the host's `effect` and `@opencode/plugin`; a plugin that loads its own copy
  from `node_modules` throws at import (`packages/plugin/src/runtime.ts:28-34`; `packages/plugin/README.md:10-18`).
  Bun is the runtime (`runtime.ts:11`).

### 1.4 Plugin shape and context

Promise API (recommended for a thin bridge), `packages/plugin/src/promise/plugin.ts:26-66`:

```ts
export interface Plugin {
  readonly id: string
  readonly setup: (context: Context) => Promise<Cleanup | void> | Cleanup | void
}
export type Cleanup = () => Promise<void> | void
```

Effect API, `packages/plugin/src/effect/plugin.ts:57-60`:
`interface Plugin<R = Scope.Scope> { id: string; effect: (context: Context) => Effect.Effect<void, never, R> }`.
The Promise form is wrapped into the Effect form by `fromPromise` (`packages/plugin/src/promise/adapter.ts:210-217`;
`module.ts:100`).

`Context` (both APIs, `promise/plugin.ts:26-55`, `effect/plugin.ts:26-55`) carries:
`app`, `location` (directory/project/worktree info), `options` (from the `plugins` entry),
domains `agent`, `aisdk`, `command`, `credential.activate`, `event`, `experimental.terminal.read`, `integration`,
`mcp`, `model`, `generate`, `permission`, `plugin.list`, `provider`, `reference`, `rpc`, `session`, `shell`,
`skill`, `storage`, `tool`, `vcs`, `websearch`, `worktree`.

Most domains are typed as a `Pick<>` of the generated API client (`@opencode/client`), so **a plugin is an
in-process SDK client** with extra `hook` / `transform` / `reload` methods (`packages/plugin/AGENTS.md`).
Not present in V2 context: V1's `$` Bun shell, `project`, `directory`, `worktree` top-level fields, `client`.

---

## 2. The complete hook list (V2)

Two mechanisms (`packages/plugin/src/promise/README.md:25-30`):

- **Runtime hooks** `ctx.<domain>.hook(name, cb)` — intercept live operations; the callback receives a **mutable
  event object** and mutates it in place; the core reads the (possibly mutated) object back.
- **Transform hooks** `ctx.<domain>.transform(editor => ...)` — replayable, synchronous edits to stateful registries
  (agents, commands, tools, MCP, skills, models, providers, references, integrations, vcs, websearch).

The core registry of runtime hook domains is exactly `aisdk`, `session`, `permission`, `shell`, `tool`
(`packages/core/src/plugin/hooks.ts:13-19`). Failure channel: **only `tool.execute.before` may fail**; every other
hook's failure type is `never` (`hooks.ts:23-30`; `packages/plugin/src/effect/tool.ts:48-52`).

### 2.1 Runtime hooks

| Domain.hook                                                  | Fires                                                                                                                                        | Payload (mutable fields in **bold**)                                                                                                          | Block                                                                                | Rewrite                                                                            | Inject context                                                                       | Source                                                                                                                    |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- |
| `tool` `execute.before`                                      | Every tool call, before the tool runs and **before the tool's own permission check**                                                         | **`tool`**, `sessionID`, `agent`, `messageID`, `id`, **`input`**                                                                              | **YES** — fail with `Tool.Error` (Promise: `throw`/reject; converted by `toolError`) | YES — `input` and even `tool` name (used by the built-in tool-input-repair plugin) | Indirectly (the error message goes back as the tool failure)                         | type `effect/tool.ts:20-28`; trigger `core/src/tool.ts:103-111`, `:272-281`; Promise mapping `promise/adapter.ts:631-643` |
| `tool` `execute.after`                                       | After the tool completes or fails (not after a call blocked by `execute.before`)                                                             | `tool`, `sessionID`, `agent`, `messageID`, `id`, `input`, `status`, **`result`** (completed) / **`error`** (error)                            | No                                                                                   | YES — replace `result.content`/`output`/`metadata`, or the `error`                 | YES — rewriting `result.content` is what the model sees                              | `effect/tool.ts:29-45`; `core/src/tool.ts:113-157`                                                                        |
| `permission` `evaluate`                                      | Whenever a tool (or plugin via `ctx.permission.assert`) asks for permission, **after** config deny rules are checked, before any user prompt | `sessionID`, `agent?`, `action`, `resources[]`, `metadata?`, `source?`, **`effect`** (`allow`/`ask`/`deny`), **`message?`**                   | YES — set `effect = "deny"` (with `message`)                                         | YES — `ask` -> `allow` (auto-approve) or -> `deny`                                 | `message` is shown/returned with the request                                         | `effect/permission.ts:10-23`; `core/src/permission.ts:159-175`                                                            |
| `shell` `create.before`                                      | Every shell process spawn (shell tool AND user/TUI shell, PTY path UNVERIFIED) — after the shell tool's permission check                     | **`command`**, **`cwd`**, **`timeout`**, **`shell`**, **`env`**                                                                               | No (failure type `never`; a rejection becomes a defect, see section 7)               | YES — rewrite command, cwd, env (V2 replacement for V1 `shell.env`)                | No                                                                                   | `effect/shell.ts:3-13`; `core/src/shell.ts:265-284`                                                                       |
| `session` `prompt`                                           | When a user/API prompt is accepted into a session, before attachments/skills are resolved                                                    | `sessionID`, `messageID`, **`prompt`** (text, files, agents, skills), **`metadata`**, **`delivery`**                                          | No                                                                                   | YES — rewrite the user's prompt text, attach files/skills                          | YES — append text to the user turn                                                   | `effect/session.ts:14-20`; `core/src/session/prompt.ts:38-50`                                                             |
| `session` `context`                                          | Every primary model request ("immediately before provider dispatch")                                                                         | `sessionID`, `model`, `agent`, **`system: SystemPart[]`**, **`messages: Message[]`**, **`options`**, **`tools`** (name -> description/schema) | No                                                                                   | YES — edit system prompt, history, generation options; delete or re-describe tools | **YES — the strongest injection point (system prompt and message list, every turn)** | `effect/session.ts:25-36`, `:139-152`; `core/src/session/model-request.ts:399-404`; README `promise/README.md:137-148`    |
| `session` `compaction`                                       | When a compaction request is prepared                                                                                                        | as `context` plus **`result?`** (`summary`, `native?`, `metadata?`, `tokens?`)                                                                | No                                                                                   | YES — set `result` to supply your own summary and **skip the model call**          | YES — edit `system`/`messages` of the compaction request                             | `effect/session.ts:38-49`; `model-request.ts:399-405`                                                                     |
| `session` `generate`                                         | `session.generate` auxiliary requests                                                                                                        | as `context`                                                                                                                                  | No                                                                                   | YES                                                                                | YES                                                                                  | `effect/session.ts:51`; `model-request.ts:406`                                                                            |
| `session` `title`                                            | Title generation                                                                                                                             | `SessionRequest` plus **`result?`**                                                                                                           | No                                                                                   | YES — set title, skip model call                                                   | n/a                                                                                  | `effect/session.ts:53-56`; `model-request.ts:407`                                                                         |
| `session` `model.request`                                    | Each model call                                                                                                                              | `sessionID`, `agent`, `model`, `kind` (`primary`/`compaction`/`title`/`generate`), **`baseURL?`**, **`headers`**                              | No                                                                                   | YES — reroute / add headers                                                        | No                                                                                   | `effect/session.ts:62-71`; `model-request.ts:298-312`                                                                     |
| `session` `http.request` / `http.response`                   | Wrap every provider HTTP exchange (only if some hook is registered for the provider)                                                         | **`request: Request`** / **`response: Response`**                                                                                             | No                                                                                   | YES — raw web `Request`/`Response` replacement                                     | Possible (raw)                                                                       | `effect/session.ts:73-88`; `model-request.ts:313-341`                                                                     |
| `session` `experimental.ws.handshake` / `.send` / `.receive` | WebSocket model transport                                                                                                                    | **`url`/`headers`**, **`frame`**                                                                                                              | No                                                                                   | YES                                                                                | Possible (raw)                                                                       | `effect/session.ts:90-126` (marked **Experimental**); `model-request.ts:345-366`                                          |
| `session` `retry`                                            | A model call failed and may be retried                                                                                                       | `error`, `attempt`, **`decision`** (`{retry:false}` or `{retry:true, delay}`)                                                                 | No                                                                                   | YES                                                                                | No                                                                                   | `effect/session.ts:128-137`; `model-request.ts:376`                                                                       |
| `aisdk` `sdk` / `language`                                   | Constructing the AI SDK provider / language model                                                                                            | **`sdk?`**, **`language?`**                                                                                                                   | No                                                                                   | YES — swap SDK or model implementation                                             | No                                                                                   | `effect/aisdk.ts:5-18`                                                                                                    |

`session` and `aisdk` hooks accept `{ providerID }` to scope the hook to one provider
(`effect/registration.ts:5-8`, `:17-23`; `core/src/plugin/hooks.ts:90`).

### 2.2 Transform hooks (registry edits)

`ctx.{agent,command,integration,mcp,model,provider,reference,skill,tool,vcs,websearch}.transform(editor => ...)`
plus `.reload()` (`promise/README.md:89-103`, `:186-200`). Editors are synchronous; "Registry reads rebuild
synchronously ... applying every transform in registration order" (`effect/README.md:48`). Useful for the daemon:

- `tool.transform`: add, update (e.g. re-describe), or **remove** tools globally (`effect/tool.ts:8-18`).
- `agent.transform`: inject per-agent `permissions` rules, system prompts, modes (built-ins do exactly this,
  `packages/core/src/plugin/agent.ts:54-119`).
- `command.transform` / `skill.transform`: provision slash commands and skills programmatically (e.g. plan-workflow
  commands) — capability YES, exact editor shapes not quoted (Gaps).

### 2.3 Event bus (observe only)

`ctx.event.subscribe()` (`effect/event.ts:3`, a `Pick` of the `EventApi` client) yields the same typed stream
served over SSE at `GET /api/event` (`packages/protocol/src/groups/event.ts:44`). Event types defined in
`packages/schema/src/*.ts` at this commit:

agent.updated, command.updated, config.updated, credential.switched, credential.updated, filesystem.changed,
form.cancelled/created/replied, global.disposed, installation.update-available, installation.updated,
integration.updated, location.shutdown, lsp.updated, mcp.resources.changed, mcp.status.changed, mcp.tools.changed,
model.updated, models-dev.refreshed, permission.asked, permission.replied, persistent-pty.added/removed,
plugin.updated, project.updated, provider.updated, pty.created/deleted/exited/updated, reference.updated,
server.connected, session.agent.selected, session.archived, session.compaction.delta/ended/failed/started,
session.created, session.deleted, session.execution.failed/interrupted/started/succeeded, session.forked,
session.idle, session.inbox.cancelled/delivered/delivery.changed/enqueued, session.instructions.updated,
session.message.content.updated, session.metadata.updated, session.model.selected, session.moved,
session.permissions, session.reasoning.delta/ended/started, session.renamed, session.retry.scheduled,
session.revert.cleared/committed/staged, session.shell.ended/started, session.skill.activated, session.status,
session.step.ended/failed/started/streamed, session.synthetic, session.text.delta/ended/started,
session.tool.called/failed/input.delta/input.ended/input.started/progress/success, session.unarchived,
session.usage.recorded/updated, session.viewed, shell.created/deleted/exited, skill.updated, tui.command.execute,
tui.prompt.append, tui.session.select, tui.toast.show, vcs.branch.updated, websearch.updated,
workspace.failed/ready/status, worktree.failed/ready/resolved/updated.

Note there is **no `file.edited`** event in V2 (V1 docs list it); the nearest are `filesystem.changed` and
`session.tool.success` for the `edit`/`write`/`patch` tools. Events are observe-only; reacting requires calling
back into the API (e.g. `session.synthetic`, `session.interrupt`).

### 2.4 Mapping to Claude Code hook events (for the daemon's handler model)

| Claude Code event                         | Nearest opencode V2 surface                                                                                     | Fidelity                                                                                                            |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| PreToolUse (deny/allow/ask, updatedInput) | `tool.execute.before` (block + rewrite) and `permission.evaluate` (allow/ask/deny)                              | High. Two-stage: the hook sees raw tool input; permission sees parsed per-command resources                         |
| PostToolUse (feedback to model)           | `tool.execute.after` (rewrite result)                                                                           | High                                                                                                                |
| UserPromptSubmit (block / add context)    | `session.prompt` (rewrite/append)                                                                               | Rewrite yes; **cannot block** (failure type `never`)                                                                |
| SessionStart / additionalContext          | `session.context` (system/messages each turn); `session.created` event                                          | Injection stronger than CC; no single "start" hook                                                                  |
| PreCompact                                | `session.compaction` (edit or replace the summary)                                                              | Higher than CC                                                                                                      |
| Stop / SubagentStop (block stopping)      | `session.idle` / `session.execution.succeeded` events (observe) + `ctx.session.prompt`/`synthetic` to re-prompt | **No veto**; can only re-drive the session after the fact. UNVERIFIED whether a synthetic message restarts the loop |
| PermissionRequest                         | `permission.evaluate`; `permission.asked` event + `POST /api/session/:id/permission/:requestID/reply`           | High                                                                                                                |
| Notification                              | events (`permission.asked`, `session.idle`, `tui.toast.show`)                                                   | Observe                                                                                                             |

---

## 3. External-process hooks: none. How to reach an external daemon

- `Config.Info` has **no `hooks` key** or any "run this command on event X" setting
  (`packages/schema/src/config.ts:26-114`). There is no equivalent of Claude Code command hooks.
- Config-driven external processes that do exist: `formatter.<name>.command` (runs on edited files),
  `lsp.<name>.command`, `mcp.servers.<name>` local `command` (`schema/src/config/formatter.ts:6-13`,
  `config/lsp.ts:10-19`, `config/mcp.ts:19-22`). None can block or rewrite agent behaviour (a formatter can
  rewrite file contents after an edit; when exactly it runs was not traced — UNVERIFIED).

Viable bridges, best first:

1. **Thin in-process V2 Promise plugin -> daemon Unix socket.** A `setup` that registers `tool.execute.before`,
   `tool.execute.after`, `permission.evaluate`, `session.prompt`, `session.context`, `session.compaction`,
   `shell.create.before` and `event.subscribe`, serialises each event to the daemon's existing socket protocol, and
   applies the verdict by mutating the event / throwing `Tool.Error`. Runs on Bun, so `node:net` sockets are
   available (Bun Node compatibility, UNVERIFIED for this exact use). Shipped as `.opencode/plugins/<dir>/` (project)
   or `~/.config/opencode/plugins/` (global), or an npm package in `plugins`.
2. **Out-of-process via the server API** (observe + act, no synchronous veto on tools): subscribe to
   `GET /api/event` (SSE), answer permission prompts with
   `POST /api/session/:sessionID/permission/:requestID/reply` (`once`/`always`/`reject`), inject with
   `POST /api/session/:sessionID/synthetic`, stop with `POST /api/session/:sessionID/interrupt`
   (`packages/protocol/src/groups/permission.ts:141`, `session.ts:396`, `:685`, `event.ts:44`). Reply schema
   `once | always | reject` (`schema/src/permission.ts:42`). This races the human UI and cannot rewrite tool input.
3. **Reverse direction, plugin RPC**: a plugin may `ctx.rpc.register(definition, handlers)` and emit events; external
   callers reach it at `POST /api/rpc/:rpcID/:method` (`plugin/src/effect/rpc.ts:24-29`;
   `protocol/src/groups/rpc.ts:14`). Lets the daemon *query* opencode state through the plugin.

---

## 4. Permission system

- **Config shape (V2):** `permissions: Array<{ action, resource, effect: "allow"|"deny"|"ask" }>` at top level and
  per agent (`agents.<id>.permissions`) (`schema/src/permission.ts:56-66`; `schema/src/config.ts:55-57`;
  `schema/src/config/agent.ts:25`). V1 object form (`permission: { bash: { "git *": "allow" } }`) is migrated to
  rules with `bash -> shell`, `write/patch/apply_patch -> edit`, `task -> subagent`
  (`core/src/v1/config/migrate.ts:17-32`; `config/normalize.ts:180-183`).
- **Evaluation:** last matching rule wins, wildcard on both `action` and `resource`; no match -> `ask`
  (`core/src/permission.ts:74-84`). Effective ruleset = agent permissions ++ session permissions
  (`permission.ts:145-150`); an unknown agent gets `*:*:deny` (`:19`). Saved "always" approvals are appended as
  allow rules (`:136-144`, `:163`).
- **Defaults:** every agent starts with `*:* allow`, `read *.env ask`, `read *.env.* ask`,
  `read *.env.example allow` (`schema/src/agent.ts:46-51`); built-ins add more (`explore` is deny-by-default with an
  allow list; `title`/`summary` deny all) (`core/src/plugin/agent.ts:54-119`). Top-level config rules are appended
  to every agent, then per-agent rules (`core/src/config/plugin/agent.ts:82-122`).
- **Actions** are tool names: `shell` (resources = each parsed sub-command), `edit` (write/patch/edit), `read`,
  `grep`, `glob`, `webfetch`, `websearch`, `subagent`, `skill`, `question`, `todo`, `external_directory`, MCP
  resource actions (`core/src/tool/plugin/*.ts`, e.g. `shell.ts:136-144`, `edit.ts:276`, `write.ts:79`). Shell
  commands are parsed (tree-sitter style scanner, `experimental.portable_shell_scanner`) so bash globs apply per
  command, not per raw string (`tool/plugin/shell.ts:121-144`; `schema/src/config/experimental.ts:8-10`).
- **Programmatic decisions:** YES. `permission.evaluate` hook can turn `ask` into `allow` or `deny` and attach a
  `message` — **but config `deny` short-circuits before the hook** (`permission.ts:162` returns before `:166`), so a
  plugin can tighten anything and loosen only `ask`/`allow`. Plugins can also call `ctx.permission.assert(...)` to
  run the native rules + approval prompt for their own actions (`effect/permission.ts:25-33`; `CHANGELOG.md:359`),
  and `ctx.permission.reply` to answer pending requests (`effect/permission.ts:25`).
- **Managed policies** (`policies`, MDM plist, `/etc/opencode`) gate providers, tools and integrations including
  plugins (`schema/src/config.ts:58-60`; `config/discovery.ts:27-57`; `module.ts:52-59`).

---

## 5. Ordering, sync/async, errors, timeouts

- **Ordering:** callbacks for one hook run **sequentially in registration order**, each seeing earlier mutations
  (`core/src/plugin/hooks.ts:88-95`; `effect/README.md:107`). Registration order follows plugin load order;
  auto-discovered paths are sorted lexically (`source-directory.ts:20`); config entries come after discovered ones
  (`config/plugin/source.ts:158-159`). Whether plugins *activate* serially in that order was not traced (Gaps).
- **Sync vs async:** runtime hooks are awaited (Promise API `callback: (input) => Promise<void> | void`,
  `promise/registration.ts:10-19`); the operation does not proceed until every hook resolves. Transform editors are
  synchronous (`promise/README.md:32-34`, `:75-76`).
- **Errors:**
  - `tool.execute.before`: a thrown error/rejection becomes `Tool.Error` and fails that call only
    (`promise/adapter.ts:631-643`).
  - All other Promise hooks are wrapped in `Effect.promise(...)` (`adapter.ts:305-307`, `:449-450`, `:592-594`,
    `:614-615`, `execute.after` at `:643`): a rejection is an Effect **defect**, not a handled failure. What a defect
    does to the turn (likely fails the step/session request) is UNVERIFIED — a bridge plugin must catch everything
    itself and fail open/closed deliberately.
  - Errors in a plugin's async `setup` after registration are logged (`adapter.ts:113`). Load errors produce
    `PluginModule.LoadError` (`module.ts:93-96`, `:118`).
- **Timeouts:** no per-hook timeout exists in `PluginHooks.trigger` (`hooks.ts:88-95`) — a hung hook stalls the
  tool call / model request indefinitely. The bridge must impose its own socket timeout. (Contrast: Claude Code
  command hooks have a configured timeout.)
- **Scope/cleanup:** registrations are owned by the plugin scope and disposed on unload/replace; `setup` may return
  a cleanup (`promise/README.md:53-71`; `hooks.ts:69-86`).

---

## 6. Other extension points

### 6.1 Custom tools

Only via plugins: `ctx.tool.transform(t => t.add({ name, description, input: Schema, output, execute }))`
(`promise/README.md:150-165`; `promise/tool.ts:16-36`). V1's standalone `.opencode/tool/*.ts` custom-tool files: no
`tool`/`tools` source-directory loader was found in `core/src/config/plugin/` (the per-directory loaders are
`agent|agents|mode|modes`, `command|commands`, `plugin|plugins`, `skill|skills`) — treat V1 custom tools as
UNVERIFIED/likely unsupported. Rejected Promise tool executions become normal tool failures (`CHANGELOG.md:439`).

### 6.2 MCP

`mcp: { timeout?, servers: { <name>: local {command, cwd, environment} | remote {url, headers, oauth} } }`
(`schema/src/config/mcp.ts:19-22`; V1 migration `v1/config/migrate.ts:77-106`). Plugins can edit via
`ctx.mcp.transform`. MCP gives the daemon **tools** the model can call, not interception.

### 6.3 LSP and formatters

`lsp: boolean | { <name>: { command[], extensions[], env, initialization } | { disabled: true } }` and
`formatter: boolean | { <name>: { command[], environment, extensions[] } }`
(`schema/src/config/lsp.ts:10-19`; `config/formatter.ts:6-13`). External processes; not hooks.

### 6.4 Commands

Config `commands: { <name>: { template, description?, agent?, model?, subagent? } }`
(`schema/src/config/command.ts:7-14`) plus markdown files under `<configdir>/command(s)/`
(`core/src/config/plugin/command.ts:140`). Programmatic: `ctx.command.transform`.

### 6.5 Agents

Config `agents: { <id>: { model, system, description, mode: subagent|primary|all, hidden, steps, disabled, permissions } }` (`schema/src/config/agent.ts:13-26`) plus markdown files under `agent|agents|mode|modes/`
(`core/src/config/plugin/agent.ts:26`). Programmatic: `ctx.agent.transform`.

### 6.6 Skills — YES, opencode reads `.claude/skills` and `.agents/skills`

- Native: `skills` config paths/URLs plus `<configdir>/skill(s)/` (`core/src/config/plugin/skill.ts:87-101`);
  a skill is a directory containing `SKILL.md` (`config/plugin/skill-scan.ts:29`).
- Compatibility plugin `opencode.config.compatibility` loads `<root>/skills/**/SKILL.md` for every `.claude` and
  `.agents` root: `~/.claude`, `~/.agents`, and each `.claude/` / `.agents/` found walking up from the project
  (`core/src/config/plugin/compatibility.ts:13-77`, esp. `:42-43`; roots from `config/discovery.ts:69-70`,
  `:85`, `:129-143`). Watched and hot-reloaded. Can be disabled via the `claude: false` discovery option
  (`discovery.ts:130`; how a user sets it was not traced).
- Instructions: `AGENTS.md` (global `~/.config/opencode/AGENTS.md` and walked up the tree) plus `instructions`
  config paths/URLs (`core/src/config/plugin/instruction.ts:41`, `:55`, `:87`). `CLAUDE.md` is **not** read by
  the instruction loader at this commit (zero matches for "claude" in `instruction.ts`).

### 6.7 TUI plugins and themes

A package's `tui` entry point exports `{ id, setup(context) }` (`packages/plugin/src/tui/plugin.ts:7-14`); the TUI
context API is `packages/plugin/src/tui/context.ts` (560 lines, not analysed — Gaps). Themes are the
`@opencode/theme` package (optional peer). Not relevant to enforcement.

### 6.8 Server HTTP API and SDK

The core runs as an HTTP server (`packages/server`), with routes generated from `packages/protocol/src/groups/*`
(session, permission, event SSE, plugin list/check/update, rpc, pty, shell, fs, config, ...). Generated Promise and
Effect clients (`@opencode/client`, `packages/sdk`) wrap it. `specs/v2/event-stream-architecture.md:1-30` describes
the SSE feed (one shared encoded feed, per-connection bounded queue — a slow consumer can drop events; see that spec's
"Capacity" section). `V2_HTTP_API_AUDIT.md` at repo root exists (not read).

---

## 7. Closing table

Stability key: **stable** = public V2 API, documented in package README; **experimental** = named/marked
experimental in source; **churning** = V2 contracts changed in a minor release (v2.1 intentionally broke plugin
contracts, `CHANGELOG.md:73`, `:87`), so pin a version.

| Extension point                                                                                                   | Block                                        | Rewrite                                 | Inject context                               | Observe                    | Stability                                       |
| ----------------------------------------------------------------------------------------------------------------- | -------------------------------------------- | --------------------------------------- | -------------------------------------------- | -------------------------- | ----------------------------------------------- |
| `tool.execute.before`                                                                                             | YES (`Tool.Error`)                           | YES (input, tool name)                  | via error text                               | yes                        | stable (V2), churning                           |
| `tool.execute.after`                                                                                              | no                                           | YES (result/error)                      | YES (tool result)                            | yes                        | stable, churning                                |
| `permission.evaluate`                                                                                             | YES (`deny`)                                 | YES (`ask`->`allow`/`deny`, message)    | message                                      | yes                        | stable, churning; cannot override config `deny` |
| `ctx.permission.assert` / `.reply`                                                                                | YES (plugin's own actions) / answers prompts | —                                       | —                                            | —                          | stable (added v2.0.x, `CHANGELOG.md:359`)       |
| `shell.create.before`                                                                                             | no (failure = defect)                        | YES (command, cwd, env, shell, timeout) | no                                           | yes                        | stable                                          |
| `session.prompt`                                                                                                  | no                                           | YES (prompt text/files/skills)          | YES (user turn)                              | yes                        | stable                                          |
| `session.context`                                                                                                 | no                                           | YES (system, messages, tools, options)  | **YES (every turn)**                         | yes                        | stable                                          |
| `session.compaction`                                                                                              | no                                           | YES (or replace summary)                | YES                                          | yes                        | stable; `native` renamed in v2.1                |
| `session.generate` / `title`                                                                                      | no                                           | YES                                     | YES / n.a.                                   | yes                        | stable                                          |
| `session.model.request` / `http.*` / `retry`                                                                      | no                                           | YES                                     | raw                                          | yes                        | stable                                          |
| `session.experimental.ws.*`                                                                                       | no                                           | YES                                     | raw                                          | yes                        | **experimental**                                |
| `aisdk.sdk` / `language`                                                                                          | no                                           | YES (swap SDK/model)                    | no                                           | yes                        | stable                                          |
| `*.transform` (agent, command, tool, mcp, skill, ...)                                                             | remove tools/agents                          | YES (registries)                        | YES (agent system prompts, skills, commands) | —                          | stable                                          |
| `ctx.event.subscribe` / `GET /api/event`                                                                          | no                                           | no                                      | no                                           | **YES (~110 event types)** | stable; bounded queue may drop                  |
| HTTP API (`synthetic`, `interrupt`, `permission reply`, `prompt`)                                                 | interrupt / reject only                      | no                                      | YES (synthetic messages)                     | —                          | stable; some routes under `/api/experimental/`  |
| Plugin RPC (`/api/rpc/:rpcID/:method`)                                                                            | —                                            | —                                       | —                                            | daemon -> plugin calls     | stable                                          |
| Config `permissions` rules                                                                                        | YES (deny)                                   | no                                      | no                                           | —                          | stable                                          |
| MCP servers                                                                                                       | no                                           | no                                      | adds tools                                   | —                          | stable                                          |
| Formatter / LSP commands                                                                                          | no                                           | formatter rewrites files                | LSP diagnostics                              | —                          | stable                                          |
| `.claude/skills`, `.agents/skills`, `AGENTS.md`                                                                   | —                                            | —                                       | YES (skills, instructions)                   | —                          | stable (compatibility plugin)                   |
| Config-declared shell-command hooks                                                                               | **ABSENT**                                   | ABSENT                                  | ABSENT                                       | ABSENT                     | —                                               |
| V1 plugin API (`@opencode-ai/plugin`, `tool.execute.before` keys, `shell.env`, `experimental.session.compacting`) | —                                            | —                                       | —                                            | —                          | **not loadable in V2** (docs still describe it) |

---

## Gaps

- No WebFetch of https://opencode.ai/docs this pass; docs claims are from `packages/web/src/content/docs/*.mdx` in the
  clone. Whether the live site documents V2 is UNVERIFIED.
- Did not trace: what a defect (rejected non-tool Promise hook) does to the session turn; whether plugins activate
  serially; when formatters run; whether `shell.create.before` also covers user PTYs; how the `claude: false` option
  is set by users; the exact `command`/`skill`/`agent` editor method signatures; the TUI plugin context
  (`packages/plugin/src/tui/context.ts`).
- Did not read Plan 00292 (Codex CLI) to align section structure; the coordinator may want to reconcile headings.
- `packages/plugin/src/effect/PLAN.md` (515 lines, the V2 plugin design plan) and `V2_HTTP_API_AUDIT.md` not read;
  they may flag planned changes to hook names.
