# RESEARCH: opencode architecture and lifecycle, and the same/different comparison with Claude Code

Plan 00549 Task 1.2. Research only.

## Source baseline (read this first)

- Clone: `untracked/repos/opencode` at HEAD `c93aaae37157d785f76a8e9a9243a6560e286468` (default branch `dev`,
  committed 2026-10-21). All `packages/*/package.json` at HEAD declare version **2.1.2**. The newest release tag is
  `v2.1.2` (2026-10-21). HEAD is 61 commits that are not in `v2.1.2`. **Correction to the shared brief:** the brief
  calls `github-v1.2.27` the latest tag. That tag belongs to the GitHub-action artefact. The product line is **v2**.
- **opencode v2 is a ground-up rewrite.** Most published write-ups, and Plan 00169's survey, describe v1, where the
  code lived in `packages/opencode` and the server was Hono. In v2 the code is split into `packages/core`,
  `packages/server`, `packages/protocol`, `packages/client`, `packages/plugin`, `packages/cli` and `packages/tui`. It
  is built on Effect 4 (`package.json` catalog `"effect": "4.0.1"`). The docs site carries a banner announcing that
  v2 is now available (https://opencode.ai/docs/rules, fetched 2026-10-22, "Last updated: Oct 20, 2026"). Some doc
  pages still describe v1 behaviour (see §7).
- All paths below are relative to the clone root unless stated. Line numbers are at the HEAD above.
- Claude Code citations point at https://code.claude.com/docs/en/\* and at this repo's `CLAUDE/Code/HooksSystem.md`
  and `CLAUDE/ARCHITECTURE.md`.
- Capability vocabulary, as the brief requires: **block**, **rewrite**, **inject context**, **observe only**,
  **absent**.

---

## 1. Process model

### 1.1 Runtime

- The language is TypeScript throughout. There is no Go. The v1 Go TUI is gone: the v2 TUI is
  `@opentui/core` + `@opentui/solid` (`packages/tui/package.json`).
- Bun is the primary runtime, pinned as `packageManager: bun@1.4.2` in the root `package.json`.
  `packages/cli/script/build.ts:173-178` compiles single-file executables with `bun build --compile`. A Node build
  also exists (`packages/cli/script/build-node.ts`, `vite.node.config.ts`). The npm entry is
  `packages/cli/bin/opencode.cjs`.
- Core is runtime-polymorphic. It has `*.bun.ts`, `*.node.ts` and `*.workerd.ts` variants, for example
  `packages/core/src/database/sqlite.{bun,node,workerd}.ts` and `packages/core/src/pty/pty.{bun,node,workerd}.ts`.
  So core is designed to run on Bun, on Node, and on Cloudflare workerd.
- The desktop app is Electron (`packages/desktop/package.json`: `electron`, `electron-builder`,
  `electron-updater`).

### 1.2 Client/server split: one shared background server per user

This is the biggest structural difference from Claude Code.

- **Running `opencode` (the TUI) does not host the agent.** The default handler resolves a server connection, then
  runs the TUI against it (`packages/cli/src/commands/handlers/default.ts:35-52`, `:96`).
- `ServerConnection.resolve` decides where that server is (`packages/cli/src/services/server-connection.ts:21-51`):
  - With `--server <url>`, it connects to a remote or explicit server over basic auth, using `OPENCODE_PASSWORD`
    (`:24-39`).
  - With `--standalone`, or when the service is disabled in config, it starts an in-process standalone server
    (`:41-43`).
  - Otherwise it uses the **managed background service**. `Service.ensure` discovers it, or spawns it and replaces
    a version-mismatched one (`:45-50`, `:74-84`).
- **Service discovery contract.** The service writes a registration file with mode 0600 at
  `$XDG_STATE_HOME/opencode/service.json` (default `~/.local/state/opencode/service.json`). The file holds the url,
  pid, version and a private password (`packages/client/src/effect/service.ts:16-20`, `:141-147`;
  `packages/client/src/service-probe.ts:39-41`). **Any outside process with the user's file permissions can read
  that file and talk to the server.** That is a ready-made attach point for a daemon-side adapter.
- Lifecycle commands: `opencode service start|restart|status|stop|get|set|unset`
  (`packages/cli/src/commands/commands.ts:471-512`). `opencode serve [--hostname --port --cors --service --stdio]`
  starts "the v2 API and web server" (`:550-563`; handler `packages/cli/src/commands/handlers/serve.ts`).
- Other front ends attach to the same server:
  - `mini`, a minimal interactive UI (`commands.ts:340-375`).
  - `run`, which is headless (§1.4).
  - `acp`, an Agent Client Protocol server over stdio (`commands.ts:89-97`; `packages/cli/src/acp/*`).
  - `api`, which makes raw OpenAPI calls to the running server (`commands.ts:98-114`).
  - `pair [--remote]`, which prints one-time links for a browser or app. `--remote` goes through an "OpenTunnel"
    address and "exposes the server to the internet" (`commands.ts:519-549`; `services/remote-tunnel.ts`).
  - The web UI (`packages/app`, `packages/web`; `services/web-ui.ts`) and the desktop app.
- Inside the server, `SessionExecution` is process-global, keyed by session ID, and lets different sessions run
  concurrently. The TUI is only a client. Several TUIs or a web client can watch the same session (`AGENTS.md`,
  "Session Core" bullets; `packages/core/src/session/execution.ts:17-40`). Restart recovery uses a write-ahead
  execution claim: a session that was mid-turn when the process died is resumed at the next server start
  (`execution.ts:73-83`, `:125-132`).

### 1.3 HTTP API and event feed

- The typed API is declared with Effect `HttpApi` in `packages/protocol/src/groups/*.ts` and served by
  `packages/server`. Clients are generated (`packages/client`, `packages/sdk`). Session endpoints live in
  `packages/protocol/src/groups/session.ts:117-827`: `create`, `prompt`, `command`, `synthetic`, `shell`,
  `compact`, `interrupt`, `background`, `fork`, `switchAgent`, `switchModel`, `revert.*`, `context`, `diff`,
  `inbox.list`, `message`, `form.*`, plus experimental `export`, `import`, `wait`, `log`, `stats` and `skill`.
- **Event stream:** `GET /api/event` (`packages/protocol/src/groups/event.ts:44`) is Server-Sent Events. Frames are
  `data: <json>\n\n` (`packages/server/src/event-feed.ts:29-31`). Each subscriber has a 4,096-event buffer, and
  overflowing it ends the subscription (`event-feed.ts:8-13`). **This is observe-only.** An SSE subscriber cannot
  veto anything.

### 1.4 Headless and SDK use

- `opencode run [message..] [-c|-s ID] [--fork] [-m provider/model#variant] [--agent] [--format default|json] [-f file]... [--title] [--thinking]` plus the permission flags (`commands.ts:376-417`; implementation in
  `packages/cli/src/run/noninteractive.ts`). `--format json` is the equivalent of Claude Code's `-p --output-format stream-json`.
- The permission bypass flags are hidden: `--yolo` and `--dangerously-skip-permissions` (`commands.ts:31-35`).
  `default.ts:117` folds them into `auto`.
- `packages/sdk` provides `@opencode/sdk`. Its `src/opencode.ts`, `src/promise.ts` and `src/effect` "compose
  Client, Core, and Server" (`AGENTS.md`). An embedder can therefore host the whole server in-process, which is
  more than the Claude Agent SDK offers, since that SDK drives the CLI binary.
- There is a VS Code extension under `sdks/vscode`.

### 1.5 Persistence

- Storage is **one SQLite database** through Drizzle. The default path is
  `$XDG_DATA_HOME/opencode/opencode.db` (default `~/.local/share/opencode/opencode.db`). Non-stable channels get
  `opencode-<channel>.db`. `OPENCODE_DB` overrides the path, and `:memory:` is allowed
  (`packages/cli/src/database-path.ts:4-13`; XDG roots in `packages/util/src/global-roots.ts:4-19`).
  `opencode debug paths db` prints the path (`commands.ts:120-129`).
- **The model is event-sourced.** Durable events go to the `event` table (`aggregate_id`, `seq`, `type`, JSON
  `data`) with an `event_sequence` table beside it (`packages/core/src/event/sql.ts:4-26`). Projections build the
  read models:
  - `session_v2`: one row per session, holding cost, token totals, agent, model, a permission ruleset, `parent_id`
    for sub-agents, `time_idle`, `idle_outcome`, `time_compacting`, and the `time_suspended` execution claim
    (`packages/core/src/session/sql.ts:23-78`).
  - `session_message`: one row per message, with JSON `data` and `seq` (`:80-99`).
  - `session_inbox` and `session_pending`: the prompt queue (`:101-146`).
  - `instruction_entry`, `instruction_blob` and `instruction_state` (`:148-177`).
- The projector lives in `packages/core/src/session/projector.ts`.
- Other tables: `account`, `credential`, `permission` (saved approvals), `project`, `workspace`, `worktree` and
  `kv` (`packages/core/src/*/sql.ts`).
- Credentials moved from v1's `~/.local/share/opencode/auth.json` into the `credential` table. A migration imports
  the legacy file (`packages/core/src/database/migration/20260805200742_import_legacy_credentials.ts:39`).
- The v1 JSON-file storage is imported by `packages/core/src/database/v1-migration.bun.ts`.

### 1.6 Session sharing

- `session_v2.share_url` still exists (`session/sql.ts:40`). However, **no share or unshare endpoint exists in the
  v2 protocol** (`packages/protocol/src/groups/session.ts` has no `share` route), and the CLI has no `share`
  command.
- Export and import do exist: `opencode session export [--sanitize]` and `opencode session import <file|url>`
  (`commands.ts:444-468`).
- Remote collaboration in v2 means pairing a browser or app to your server (`pair`, `pair --remote`).
- v1-style public share links: **absent in v2 code at this commit.** Whether the hosted share service still exists
  is UNVERIFIED.

---

## 2. Session lifecycle, end to end

The vocabulary is fixed by opencode's own `AGENTS.md` ("Session Core"). A **step** is one LLM call. A **turn**,
reserved for future use, is every step from a prompt until the session would go idle. The drain loop never keeps
tool loops in memory: every step reloads history from the DB.

| #   | Phase                                  | Code                                                                                                                                                                                                            | Events published (bus → SSE)                                                                                                                                                                                                                                                                                 | Plugin hook point                                                                                                                                                                                          | Capability                                                                                                                                                            |
| --- | -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Session create                         | `Session.create` (`session/session.ts`)                                                                                                                                                                         | `session.created` (`packages/schema/src/session-event.ts:49`)                                                                                                                                                                                                                                                | event subscription                                                                                                                                                                                         | observe                                                                                                                                                               |
| 2   | User prompt admission                  | `SessionPrompt.prepare` (`session/prompt.ts:29-89`), then the inbox                                                                                                                                             | `session.inbox.enqueued` (`session-event.ts:230`)                                                                                                                                                                                                                                                            | **`session.prompt`** (`prompt.ts:40-51`): mutable `prompt.text/files/agents/skills`, `metadata`, `delivery`                                                                                                | **rewrite** the prompt, and so **inject context**; block it by emptying or replacing it. No typed deny channel: `NoFailures` (`core/src/plugin/hooks.ts:21-30`)       |
| 3   | Wake and claim                         | `SessionExecution` coordinator `started` (`execution.ts:109-113`)                                                                                                                                               | `session.execution.started` (durable, and writes the claim)                                                                                                                                                                                                                                                  | event                                                                                                                                                                                                      | observe                                                                                                                                                               |
| 4   | Promotion of inbox to message          | `SessionRunner.drain` → `SessionInbox.promote` (`runner/llm.ts:160-176`)                                                                                                                                        | `session.inbox.delivered`                                                                                                                                                                                                                                                                                    | —                                                                                                                                                                                                          | —                                                                                                                                                                     |
| 5   | Auto-compaction check, every step      | `compaction.compact({reason:"auto"})` (`runner/llm.ts:214-219`)                                                                                                                                                 | `session.compaction.started/delta/ended/failed` (`session-event.ts:598-635`)                                                                                                                                                                                                                                 | **`session.compaction`**: may supply `result` and skip the model call (`plugin/src/effect/session.ts:38-49`)                                                                                               | **rewrite** the summary                                                                                                                                               |
| 6   | Build request                          | `context.request.primary` (`runner/llm.ts:228-241`)                                                                                                                                                             | —                                                                                                                                                                                                                                                                                                            | **`session.context`**: mutable `system[]`, `messages[]`, `options`, `tools{}` (`plugin/src/effect/session.ts:25-36`); then `model.request` (headers, baseURL) and `http.request`/`http.response`           | **inject context** on every step; rewrite or remove tool definitions                                                                                                  |
| 7   | Model step streams                     | `steps.attempt` (`runner/step.ts`)                                                                                                                                                                              | `session.step.started/streamed/ended/failed`, `session.text.*`, `session.reasoning.*`, `session.tool.input.*` (`session-event.ts:344-511`)                                                                                                                                                                   | `session.retry` (retry decision)                                                                                                                                                                           | rewrite the retry policy                                                                                                                                              |
| 8   | Tool call                              | `Tool.execute` (`core/src/tool.ts:103-156`)                                                                                                                                                                     | `session.tool.called`, `session.tool.progress` (`session-event.ts:522-535`)                                                                                                                                                                                                                                  | **`tool.execute.before`**: mutable `input`. **The only hook that may fail.** A `Tool.Error` rejects the call before it runs (`tool.ts:103-111`; `plugin/src/effect/tool.ts:20-28,48-52`; `hooks.ts:23-30`) | **block** and **rewrite input**                                                                                                                                       |
| 8a  | Permission check, inside the tool body | Each tool calls `permission.assert({action,resources})`, for example `tool/plugin/shell.ts:138`, `edit.ts:275`, `write.ts:78`, `subagent.ts:138`. `Permission.evaluateInput` (`core/src/permission.ts:160-176`) | `permission.asked` / `permission.replied`                                                                                                                                                                                                                                                                    | **`permission.evaluate`**: mutable `effect` (`allow`/`ask`/`deny`) plus `message` (`plugin/src/effect/permission.ts:10-23`)                                                                                | **block** (set deny), **force an ask**, or **auto-allow**. A config **deny** short-circuits *before* the hook runs (`permission.ts:162`), so a hook cannot un-deny it |
| 8b  | Shell spawn                            | `shell` tool                                                                                                                                                                                                    | `session.shell.started/ended`                                                                                                                                                                                                                                                                                | **`shell.create.before`**: mutable `command`, `cwd`, `timeout`, `shell`, `env` (`plugin/src/effect/shell.ts:1-17`)                                                                                         | **rewrite** the command and environment                                                                                                                               |
| 9   | Tool result                            | `Tool.execute` after (`tool.ts:131-155`)                                                                                                                                                                        | `session.tool.success` / `session.tool.failed` (`session-event.ts:545-566`)                                                                                                                                                                                                                                  | **`tool.execute.after`**: mutable `result` or `error` (`plugin/src/effect/tool.ts:29-45`)                                                                                                                  | **rewrite** the output the model sees, and so **inject context** after the tool. Cannot fail                                                                          |
| 10  | Step end and continuation              | `runStep` returns `needsContinuation` (`runner/llm.ts:267-323`). Automatic continues on an incomplete stream or the output-token limit publish `session.synthetic` (`:281`, `:311`)                             | `session.step.ended`, `session.usage.recorded/updated`                                                                                                                                                                                                                                                       | —                                                                                                                                                                                                          | —                                                                                                                                                                     |
| 11  | Step limit                             | When `agent.steps` is reached, the runner appends `MAX_STEPS_PROMPT` and forces `toolChoice:"none"` (`runner/llm.ts:220-238`)                                                                                   | —                                                                                                                                                                                                                                                                                                            | config `steps` per agent                                                                                                                                                                                   | —                                                                                                                                                                     |
| 12  | Idle, the "turn end"                   | The drain finds no promotable input (`runner/llm.ts:158-159`), then the coordinator `settled` callback (`execution.ts:116-145`)                                                                                 | **`session.execution.succeeded`** / `.failed` / `.interrupted` (durable). The projector sets `time_idle` and `idle_outcome` (`session/projector.ts:425-434`, `:706-708`). The legacy ephemeral `session.idle` / `session.status` are marked deprecated (`packages/schema/src/session-status-event.ts:35-51`) | event subscription only                                                                                                                                                                                    | **observe only, after the fact**                                                                                                                                      |
| 13  | Abort                                  | `SessionExecution.interrupt` (`execution.ts:150-167`); API `POST /api/session/:id/interrupt`                                                                                                                    | `session.execution.interrupted {reason:"user"\|"shutdown"}`                                                                                                                                                                                                                                                  | —                                                                                                                                                                                                          | —                                                                                                                                                                     |
| 14  | Manual compaction                      | `POST .../compact` enqueues a `compaction` inbox control, which the drain handles first (`runner/llm.ts:90-157`)                                                                                                | `session.compaction.*` (`reason:"manual"`)                                                                                                                                                                                                                                                                   | `session.compaction`                                                                                                                                                                                       | rewrite                                                                                                                                                               |
| 15  | Session end                            | There is no "session end" event. Sessions persist. They can be archived (`session.archived`) or deleted (`session.deleted`) (`session-event.ts:143-192`). Closing the TUI does not stop the server              | `session.archived`, `session.deleted`                                                                                                                                                                                                                                                                        | event                                                                                                                                                                                                      | observe                                                                                                                                                               |

### 2.1 Is there a Stop-hook equivalent that can force the agent to continue?

**There is no synchronous "stop" veto.** No hook runs at the idle boundary with a failure channel or a
`decision:"block"`. `SessionHooks` contains `prompt`, `context`, `compaction`, `generate`, `title`,
`model.request`, `http.*`, `experimental.ws.*` and `retry` (`packages/plugin/src/effect/session.ts:139-152`).
`hooks.ts:23-30` lets only `tool.execute.before` fail.

**There is an asynchronous "re-prompt after idle" mechanism.** A plugin's `Context` exposes `event.subscribe()` and
the `session` domain API, which includes `prompt`, `synthetic`, `command`, `interrupt` and `wait`
(`plugin/src/effect/plugin.ts:26-55`; `plugin/src/effect/session.ts:154-174`). A plugin can therefore:

1. watch for `session.execution.succeeded`;
2. inspect the transcript (`session.context`, or the DB);
3. call `session.prompt` or `session.synthetic` with the reason text.

That starts a new busy period. The built-in Plan plugin uses the same subscribe-then-`synthetic` pattern to inject
reminders on `session.created` and `session.agent.selected` (`packages/core/src/plugin/plan.ts:75-96`).

The differences from Claude Code's Stop hook (https://code.claude.com/docs/en/hooks, "Stop") matter:

- The session has already gone idle and published `execution.succeeded`. Clients see the turn end, then a new one
  begin.
- `synthetic` messages are model-visible user-role text, not a system "reason".
- No `stop_hook_active` loop guard is built in. The adapter would have to keep its own.

The inbox "steer" semantics (`AGENTS.md`: "At an idle boundary, steers take priority") also let a prompt sent *while
busy* be folded into the running drain, so the agent continues without going idle. A watcher that sends its prompt
before the final step ends gets genuine continuation. Doing that reliably needs a hook on the last step, and there
isn't one (§4).

### 2.2 Is there a UserPromptSubmit equivalent that can inject context?

**Yes, and it is stronger than Claude Code's.** The `session.prompt` hook gets the prompt *before* admission, with
mutable text, files, agents, skills, metadata and delivery (`session/prompt.ts:40-52`). The `session.context` hook
can change the system prompt and messages on **every step**, which no Claude Code hook can. `plan.ts:57-73` shows
`context` used to splice reminders in. Blocking a prompt outright with a reason shown to the user is not a typed
outcome. A plugin can only rewrite the prompt. Whether failing an Effect inside the `prompt` hook surfaces to the
user as an error is UNVERIFIED; the type is `never`.

### 2.3 Where can an outside (non-plugin) process hook in?

| Channel                                                                     | Direction           | Can block?                                                                                                                       | Ref                                                     |
| --------------------------------------------------------------------------- | ------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| SSE `GET /api/event`                                                        | observe             | no                                                                                                                               | `protocol/src/groups/event.ts:44`                       |
| HTTP API: `prompt`, `synthetic`, `interrupt`, `compact`, permission `reply` | act                 | It can answer permission asks. A **headless permission responder is possible**: listen for `permission.asked` and `POST` a reply | `protocol/src/groups/session.ts`, `permission.ts` group |
| SQLite DB                                                                   | read the transcript | no                                                                                                                               | §1.5                                                    |
| In-process plugin (TS module)                                               | everything in §2    | yes, via `tool.execute.before` and `permission.evaluate`                                                                         | `packages/plugin`                                       |

There is **no out-of-process, synchronous, command-style hook**, that is no equivalent of Claude Code's
`settings.json` `hooks` running a shell command with JSON on stdin. Any blocking policy must be a JS/TS plugin
running inside the server. That plugin could call out to the daemon socket. Task 1.1 has the plugin surface in
detail.

---

## 3. Agents

### 3.1 Built-in agents

`packages/core/src/plugin/agent.ts:52-117` and `plugin/plan.ts:27-42` define:

| id                                   | mode            | Purpose and permissions                                                                                                                      |
| ------------------------------------ | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `build` (default, `Agent.defaultID`) | primary         | "The default agent. Executes tools based on configured permissions." Adds `question:allow`                                                   |
| `plan`                               | primary         | Read-only planning. `edit:* deny` except `edit:~/.opencode/plan/*` allow, and `question` allow                                               |
| `general`                            | subagent        | General-purpose. `question` deny, `subagent` deny, so no nesting                                                                             |
| `explore`                            | subagent        | `*:deny`, then allows `shell`, `grep`, `glob`, `webfetch`, `websearch`, `read` (`.env` set to ask) and `external_directory`. `subagent` deny |
| `compaction`, `title`, `summary`     | primary, hidden | Internal workers. `title` and `summary` are `*:deny`                                                                                         |

**The default permission set is permissive.** `Agent.Info.default` grants `{action:"*",resource:"*",effect:"allow"}`
and only asks for `.env` reads (`packages/schema/src/agent.ts:39-51`). Claude Code is the opposite: by default it
asks before edits and Bash (https://code.claude.com/docs/en/iam, permission modes).

### 3.2 Agent schema and config

- `Agent.Info` fields: `id`, `name`, `model`, `request`, `system`, `description`,
  `mode: "subagent"|"primary"|"all"`, `hidden`, `color`, `steps` (step cap), and `permissions`, an ordered ruleset
  of `{action, resource, effect}` (`schema/src/agent.ts:23-35`).
- Markdown agents are loaded from `{agent,agents}/**/*.md`, which become sub-agents, and from `{mode,modes}/*.md`,
  which become primary agents. These are looked up in the config directories (`.opencode/`, `~/.config/opencode/`).
  The file has frontmatter plus a prompt body, decoded through both the v2 and v1 schemas
  (`core/src/config/plugin/agent.ts:21-27`). JSON agents go under `agents` in `opencode.json`. `disabled: true`
  removes an agent. `default_agent` picks the default (`:88-110`).
- Top-level permission rules are pushed into every agent (`agent.ts:86-91`). A session also carries its own
  ruleset (`session_v2.permission`), merged after the agent's (`core/src/permission.ts:145-150`).

### 3.3 Sub-agents (the `subagent` tool, v1's `task`)

`packages/core/src/tool/plugin/subagent.ts`:

- Input is `{agent, description, prompt, model?, sessionID?, background?}` (`:29-48`). It covers both Claude Code's
  `Task` / `Agent` and its background-agent and resume features.
- Each sub-agent is a **full child session**: `sessions.create({parentID, agent, model})`. It is persisted,
  inspectable, and can be resumed by `sessionID` (`:184-198`, `:153-167`).
- The nesting depth defaults to 1, configurable through `experimental.subagent_depth` (`:129-133`).
- A `primary` agent cannot be called as a sub-agent (`:136-137`).
- Invocation is permission-gated as action `subagent`, resource `<agentID>` (`:138-151`).
- The foreground form blocks until done. The background form returns at once and notifies the parent later
  (`:200-256`; `session/subagent-job.ts`, `session/subagent-completion.ts`).
- The available sub-agent list is injected into the tool description by a `session.context` hook (`:282-309`).
- Because a sub-agent is a session, **every hook and event in §2 fires for it too**, with `parent_id` set. In
  Claude Code a sub-agent is reported to hooks through `SubagentStart`/`SubagentStop` and an `agent_id`. Here it is
  ordinary session events on a child session.

### 3.4 Plan mode: how it works and whether it can be enforced

- Plan is an **agent**, not a harness mode. Switching agents (Tab in the TUI, `POST /api/session/:id/agent`)
  publishes `session.agent.selected`.
- **Enforcement is real, through permissions.** `edit:* deny` blocks the `edit`, `write` and `patch` tools: all
  three call `permission.assert({action:"edit"})` (`tool/plugin/edit.ts:275`, `write.ts:78`, `patch.ts:196`). The
  one carve-out is `~/.opencode/plan/*` (`plan.ts:31-41`).
- A `tool.execute.after` hook rewrites the denial into a helpful message (`plan.ts:44-53`).
- A `session.context` hook re-inserts the reminder after compaction or revert (`plan.ts:55-73`).
- **Gap: `shell` is not denied in plan mode.** The plan agent keeps `shell:*` allow from the default ruleset, so
  `echo > file` through `shell` is not blocked by the plan rules. UNVERIFIED whether the shell tool maps redirects
  to `edit` permission. `core/src/shell/parse.ts` and `scan.ts` exist and suggest command analysis; not traced.
- The plan file directory is **global** (`~/.opencode/plan`), not per project. The daemon's `CLAUDE/Plan/NNNNN-*`
  workflow would need a custom agent, or an override of `plan`'s permissions, to allow `edit` on
  `<repo>/CLAUDE/Plan/**`. This is configurable through agent config permissions (§3.2).
- Compare Claude Code: plan mode is a permission mode (`permission_mode: "plan"` in hook payloads), exited through
  the `ExitPlanMode` tool, and its plan files go to `plansDirectory` (https://code.claude.com/docs/en/settings).

---

## 4. Models, providers, auth and cost

- **Multi-provider.** Providers are implemented as plugins under `packages/core/src/plugin/provider/*.ts`. There are
  more than 35 of them, including openai, chatgpt (subscription), github-copilot, amazon-bedrock, google-vertex,
  azure, openrouter, ollama, lmstudio, vllm, xai, cohere, databricks, snowflake-cortex, gitlab, and `opencode` (the
  hosted "Zen" gateway). The AI SDK is a dependency (`"ai": "6.0.168"` in the catalog). opencode also has its own
  `packages/ai`.
- **Model catalogue.** It is fetched from `https://models.opencode.ai`, which is models.dev rebranded, with a
  committed snapshot `core/src/models-dev/snapshot.txt` as a fallback (`core/src/models-dev.ts:280-282`).
  `opencode models` lists the models (`commands.ts:306`). Model refs take the form `provider/model#variant`.
- **Per-model system prompts:** `core/src/plugin/system-prompt/{anthropic,gpt,gpt-astra,kimi,meta,trinity}.txt`.
- **Auth.** `opencode auth list|connect|logout|export|import|switch` (`commands.ts:145-220`). Credentials live in
  the SQLite `credential` table (§1.5). There is OAuth for MCP (`core/src/mcp/oauth.ts`).
- **Cost tracking is built in.** `calculateCost` handles tiered input, output, reasoning and cache pricing from the
  catalogue (`core/src/session/usage.ts:22-33`). Per-session totals are columns on `session_v2` (`cost`,
  `tokens_*`; `session/sql.ts:46-51`), with events `session.usage.recorded/updated`. `opencode stats [--cost --json]`
  reports them (`commands.ts:310-339`). Claude Code exposes cost to the status line (`cost.total_cost_usd`) and
  `/cost`, but not as a persisted per-session ledger. UNVERIFIED for its latest release.

---

## 5. Built-in tools and their names

Tool IDs come from `packages/core/src/tool/plugin/*.ts` (`export const name`).

| opencode tool                                                                               | Permission action                       | Claude Code counterpart                  | Notes                                                                               |
| ------------------------------------------------------------------------------------------- | --------------------------------------- | ---------------------------------------- | ----------------------------------------------------------------------------------- |
| `read`                                                                                      | `read` (via `FileAccess.authorizeRead`) | `Read`                                   | Also discovers nested `AGENTS.md` files on read and injects them (`read.ts:82-107`) |
| `write`                                                                                     | `edit`                                  | `Write`                                  |                                                                                     |
| `edit`                                                                                      | `edit`                                  | `Edit`                                   |                                                                                     |
| `patch`                                                                                     | `edit`                                  | none (Codex-style `apply_patch`)         | `tool/patch.txt`                                                                    |
| `glob`                                                                                      | `glob`                                  | `Glob`                                   |                                                                                     |
| `grep`                                                                                      | `grep`                                  | `Grep`                                   | ripgrep (`core/src/ripgrep.ts`)                                                     |
| `shell`                                                                                     | `shell`                                 | `Bash`                                   | **Renamed from v1 `bash`.** Hook `shell.create.before`                              |
| `subagent`                                                                                  | `subagent`                              | `Task` / `Agent`                         | **Renamed from v1 `task`**                                                          |
| `todowrite`                                                                                 | `todowrite`                             | `TodoWrite`                              |                                                                                     |
| `webfetch`                                                                                  | `webfetch`                              | `WebFetch`                               |                                                                                     |
| `websearch`                                                                                 | `websearch`                             | `WebSearch`                              |                                                                                     |
| `question`                                                                                  | `question`                              | `AskUserQuestion`                        |                                                                                     |
| `skill`                                                                                     | `skill`                                 | `Skill`                                  |                                                                                     |
| `list_mcp_resources`, `read_mcp_resource`                                                   | `opencode_*_mcp_resource`               | `ListMcpResources`, `ReadMcpResource`    |                                                                                     |
| `opencode` group: `session_rename`, `session_move`, `worktree_create/list/remove`, `models` | various, worktree removal is `edit`     | `EnterWorktree`/`ExitWorktree` (partial) | `tool/plugin/opencode.ts:88-220`                                                    |
| `file-diff`                                                                                 | —                                       | —                                        | `tool/plugin/file-diff.ts`                                                          |
| MCP tools                                                                                   | per tool                                | `mcp__server__tool`                      | `core/src/tool/mcp.ts`                                                              |

Absent from v2 core at this commit: an LSP tool or diagnostics. `edit.ts:205` and `file-mutation.ts:131` carry
"TODO: … after LSP runtime exists", although `schema/src/config/lsp.ts` and the `lsp.updated` event exist. v1
shipped LSP diagnostics after edits, so **this is a v2 regression**. A "codemode" execution layer also exists
(`packages/codemode`, `core/src/codemode/*`); out of scope here.

**Implication for the daemon.** Handler matchers keyed on `Bash`, `Write`, `Edit` and so on would need a name map:
`Bash→shell`, `Task→subagent`, `TodoWrite→todowrite`, and lowercase names generally. Input field names also differ.
For example `read` takes `path`, not `file_path` (`read.ts:17-25`). Task 2.1 should map each one.

---

## 6. Instruction loading

At this commit the code says:

- Only **`AGENTS.md`** is loaded (`core/src/config/plugin/instruction.ts:41-94`):

  - global `~/.config/opencode/AGENTS.md`;
  - project files walking up from the location to the project root, or to home when inside home;
  - nested `AGENTS.md` files discovered lazily on `read` (`read.ts:82-107`).

- `instructions` config entries (globs, absolute paths, `~/`, URLs) are merged in (`instruction.ts:96-130`).

- The files are watched. Changes are diffed and announced to the model ("The instructions from X changed. Here's
  the diff:"; `core/src/instruction-discovery.ts:135-145`), and persisted per session in `instruction_*` tables.

- **`CLAUDE.md` fallback: absent in v2 code.** No `.ts` file under `packages/core/src`, `cli/src`, `server/src` or
  `sdk/src` mentions `CLAUDE.md`.

- **The docs disagree.** https://opencode.ai/docs/rules (fetched 2026-10-22) still documents a `CLAUDE.md`
  fallback, `~/.claude/CLAUDE.md`, and `OPENCODE_DISABLE_CLAUDE_CODE_PROMPT`. **Trust the code:** under v2.1.2 a
  repo with only `CLAUDE.md` gets no project instructions.

- **What v2 does read from `.claude/`:** config discovery collects `~/.claude`, `~/.agents`, and every ancestor
  `.claude/` and `.agents/` directory (`core/src/config/discovery.ts:69-143`). Only their **`skills/`
  subdirectories** are loaded (`core/src/config/plugin/compatibility.ts:39-55`).

- **Opt-outs for that:** config `claude: false` (`core/src/config.ts:49-54`), or `OPENCODE_DISABLE_CLAUDE_CODE` /
  `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS` (`packages/cli/src/server-process.ts:128-129`).

- **Config precedence:**

  1. system `/etc/opencode`, `/Library/Application Support/opencode` or `%ProgramData%\opencode`, plus macOS MDM
     plist `ai.opencode.managed`;
  2. global `~/.config/opencode/opencode.json[c]`;
  3. an explicit file;
  4. `opencode.json[c]` in each ancestor directory;
  5. each ancestor `.opencode/` directory.

  Source: `discovery.ts:12-145`.

Task 1.3 owns the full dual-tool matrix. This section records only the architectural fact.

---

## 7. Transcript and history format

- **Source of truth:** the SQLite `event` table, an append-only per-aggregate log. **Read models:**
  `session_message.data` (JSON per message) and `session_v2` (§1.5). This is not a JSONL file per session, the way
  Claude Code's `~/.claude/projects/<slug>/<session>.jsonl` is
  (https://code.claude.com/docs/en/hooks, `transcript_path`).
- **Outside readers** have four routes:
  1. Open the DB read-only. SQLite allows concurrent readers. The schema is internal and migrates often: 2026
     migrations live under `core/src/database/migration/`.
  2. `GET /api/session/:id/message/:messageID` and `GET /api/session/:id/context` over the service password from
     `service.json`.
  3. `GET /api/experimental/session/:id/export` or `opencode session export`, which gives JSON.
  4. Subscribe to SSE.
- Routes 2–4 are the stable contract. Route 1 is fragile.
- **Implication.** The daemon's transcript-reading handlers, which parse JSONL for the stop-explanation, the
  tool-error re-entry and the subagent report checks, would need a new transcript adapter. There is no file path to
  hand a handler.

---

## 8. SAME vs DIFFERENT: opencode v2.1.2 against Claude Code

| #   | Dimension                    | opencode (v2.1.2 @ c93aaae)                                                                                                                                                                       | Claude Code                                                                                                                                                                                                                            | Verdict                                                                                       |
| --- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| 1   | Licence                      | MIT, open source (`LICENSE`)                                                                                                                                                                      | Proprietary CLI                                                                                                                                                                                                                        | **Different**                                                                                 |
| 2   | Language and runtime         | TypeScript, Bun-compiled binary or Node; Effect 4 (§1.1)                                                                                                                                          | Node/TS single binary, closed source                                                                                                                                                                                                   | Same family, different openness                                                               |
| 3   | Process model                | **Shared background HTTP server per user** with thin clients: TUI, mini, web, desktop, ACP, `run` (§1.2)                                                                                          | One process per session; the CLI hosts the agent loop                                                                                                                                                                                  | **Different, fundamentally**                                                                  |
| 4   | Model lock-in                | More than 35 providers, catalogue from models.dev, any `provider/model#variant` (§4)                                                                                                              | Anthropic models only, through the Anthropic API, Bedrock, Vertex or Foundry (https://code.claude.com/docs/en/third-party-integrations)                                                                                                | **Different**                                                                                 |
| 5   | Hooks model                  | **In-process TS/Effect plugins** with typed mutable hook events. Only `tool.execute.before` can fail (block). `permission.evaluate` can deny. Many hooks can rewrite. No shell-command hooks (§2) | **Out-of-process command, HTTP or prompt hooks** configured in `settings.json`, JSON over stdin/stdout, with `decision`/`permissionDecision`/`additionalContext` (https://code.claude.com/docs/en/hooks; `CLAUDE/Code/HooksSystem.md`) | **Different.** opencode is richer in-process; Claude Code is language-agnostic out-of-process |
| 6   | Stop / continue gate         | Absent as a veto. Approximated with an idle event plus a re-`prompt` or `synthetic` (§2.1)                                                                                                        | `Stop`/`SubagentStop` hook with `decision:"block"` and a `reason`                                                                                                                                                                      | **Different.** Weaker in opencode                                                             |
| 7   | Prompt-submit injection      | `session.prompt` rewrite, plus `session.context` on **every step** (§2.2)                                                                                                                         | `UserPromptSubmit` (block, or `additionalContext`)                                                                                                                                                                                     | Same idea; opencode is stronger                                                               |
| 8   | Permissions                  | Ordered `{action,resource,effect}` rulesets per agent, per session and saved. Default **allow all**. Config deny is final (§3.1, §2 row 8a)                                                       | allow/ask/deny rules in settings plus permission modes; default asks for edits and Bash (https://code.claude.com/docs/en/iam)                                                                                                          | Same concept; **default posture is opposite**                                                 |
| 9   | Sub-agents                   | `subagent` tool. Each one is a persistent child session, resumable by ID, can run in the background, depth-limited (§3.3)                                                                         | `Task`/`Agent` tool, `.claude/agents/*.md`, background agents, `SubagentStart`/`Stop` hooks (https://code.claude.com/docs/en/sub-agents)                                                                                               | **Same** capability; different representation (sessions vs sidechains)                        |
| 10  | Primary agents and modes     | Multiple primary agents (`build`, `plan`, custom `modes/*.md`), switchable mid-session                                                                                                            | One main agent; output styles; permission modes                                                                                                                                                                                        | **Different**                                                                                 |
| 11  | Plan mode                    | `plan` **agent**. Edits denied by permission except under `~/.opencode/plan/*`. Shell not denied (§3.4)                                                                                           | `plan` **permission mode**, `ExitPlanMode` tool, `plansDirectory`                                                                                                                                                                      | Same goal, different mechanism; both enforceable                                              |
| 12  | Compaction                   | Automatic before each step when due, on overflow, or manual. The `session.compaction` hook can replace the summary. Events `session.compaction.*` (§2 rows 5 and 14)                              | Auto and `/compact`; `PreCompact`/`PostCompact` hooks; summary not replaceable                                                                                                                                                         | Same; opencode is more pluggable                                                              |
| 13  | Config files                 | `opencode.json[c]`, `.opencode/` (agents, modes, commands, skills, plugins), system, global, MDM (§6)                                                                                             | `.claude/settings.json`, `settings.local.json`, managed settings, `.claude/{agents,commands,skills}`                                                                                                                                   | **Different** files; opencode reads `.claude/skills`                                          |
| 14  | Instruction files            | `AGENTS.md` only in v2 code, plus `instructions` globs and URLs, with live diffs to the model (§6)                                                                                                | `CLAUDE.md` hierarchy, `@imports`, `.claude/rules/` (https://code.claude.com/docs/en/memory)                                                                                                                                           | **Different**, and v2 dropped the documented CLAUDE.md fallback                               |
| 15  | MCP                          | Built in: stdio and remote, OAuth, `opencode mcp add/list/auth/logout` (`core/src/mcp/*`; `commands.ts:221-260`)                                                                                  | Built in: `.mcp.json`, `claude mcp`                                                                                                                                                                                                    | **Same**                                                                                      |
| 16  | LSP                          | v1 had LSP diagnostics. **v2.1.2 has an LSP config schema but no runtime** ("TODO … after LSP runtime exists", `edit.ts:205`)                                                                     | LSP through code-intelligence plugins (the LSP tool)                                                                                                                                                                                   | Different; v2 regressed                                                                       |
| 17  | Status line                  | No external status-line command. The TUI renders its own status. UNVERIFIED whether TUI plugins (`packages/plugin/src/tui`) can add segments                                                      | `statusLine` command fed with JSON on stdin (https://code.claude.com/docs/en/statusline)                                                                                                                                               | **Different.** The daemon's status line has no direct home                                    |
| 18  | Crons and loops              | None found in core: no cron or `/loop` equivalent. UNVERIFIED, since only core and cli were checked                                                                                               | `CronCreate`/`/loop`, scheduled routines                                                                                                                                                                                               | **Different** (absent in opencode)                                                            |
| 19  | Headless and SDK             | `opencode run --format json`, `opencode serve` HTTP API (OpenAPI), `@opencode/sdk` can embed the server, `opencode api` (§1.4)                                                                    | `claude -p --output-format stream-json`, Agent SDK                                                                                                                                                                                     | Same purpose; opencode's API is more open                                                     |
| 20  | Remote and server mode       | First-class: `serve`, `--server <url>`, `pair --remote` tunnel, password auth (§1.2)                                                                                                              | Remote Control / cloud sessions (managed by Anthropic)                                                                                                                                                                                 | **Different**                                                                                 |
| 21  | IDE integration              | ACP server (`opencode acp`), VS Code extension (`sdks/vscode`), Electron desktop app                                                                                                              | VS Code and JetBrains extensions, desktop app                                                                                                                                                                                          | Same, via different protocols (ACP vs Claude's own)                                           |
| 22  | Transcript storage           | SQLite, event-sourced, under `~/.local/share/opencode/opencode.db` (§1.5, §7)                                                                                                                     | JSONL file per session, path given to hooks                                                                                                                                                                                            | **Different.** Daemon transcript parsers do not port                                          |
| 23  | Tool names                   | lowercase: `shell`, `subagent`, `todowrite`, `patch` and so on (§5)                                                                                                                               | `Bash`, `Task`, `TodoWrite`…                                                                                                                                                                                                           | **Different**; needs a name map                                                               |
| 24  | Cost tracking                | Persisted per session, `opencode stats --cost` (§4)                                                                                                                                               | Status-line cost, `/cost`                                                                                                                                                                                                              | opencode is richer                                                                            |
| 25  | Session sharing              | v1 share links absent in v2 protocol; export and import instead (§1.6)                                                                                                                            | No public share (remote sessions only)                                                                                                                                                                                                 | Roughly the same now                                                                          |
| 26  | Multi-client and concurrency | Many clients per session and many sessions per server; restart-resumable turns (§1.2)                                                                                                             | One terminal per session                                                                                                                                                                                                               | **Different**                                                                                 |

### 8.1 What this means for the daemon (input to Phase 2)

1. **The attach point must be an opencode plugin**, a TS module loaded into the server. A shell-command forwarder
   cannot be one, because opencode has no command-hook mechanism. The plugin would forward hook events to the
   daemon socket and turn the daemon's verdicts into the matching outcome:
   - a `Tool.Error` from `execute.before`;
   - `effect = "deny"` in `permission.evaluate`;
   - mutations for rewrite and inject.
2. **The server is shared and long-lived.** One plugin instance may serve many projects ("Locations") and sessions.
   The daemon's per-project socket model would have to route by `location` or `directory`. Hook registry nodes are
   "Location-scoped" (`plugin/hooks.ts:108`, `makeLocationNode`), which helps.
3. **Stop gates degrade** to "re-prompt after idle" (§2.1). The plan workflow's stop gates can be emulated, but not
   with Claude Code's exact semantics.
4. **Transcript-reading handlers** need a DB- or API-backed adapter (§7).
5. **Plan workflow:** the plan agent's write carve-out is global (`~/.opencode/plan`). Repo-local plan folders need
   a permission override, which config can express.

## Gaps and UNVERIFIED items

- Whether a failing Effect in non-tool hooks (for example `session.prompt`) surfaces to users. The types say these
  hooks cannot fail.
- Whether the `shell` tool maps write redirections to the `edit` permission (`core/src/shell/*` not traced).
- TUI plugin capabilities for status-line-like UI (`packages/plugin/src/tui`, `packages/gui-extensions`).
- Whether hosted session sharing still exists for v2 clients.
- Cron or scheduling anywhere outside `packages/core` and `packages/cli`.
- The `packages/plugin/src/effect/PLAN.md` file (515 lines) describes upcoming plugin API changes. Not read here;
  Task 1.1 should.
