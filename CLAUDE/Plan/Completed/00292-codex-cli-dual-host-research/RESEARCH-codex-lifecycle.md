# Research: Codex CLI Configuration and Session Lifecycle

Plan 00292 — dual-host research. Sources are primary where possible: the
`openai/codex` GitHub repo, and OpenAI's official docs, which as of this
writing live at `developers.openai.com/codex/*` and 308-redirect to
`learn.chatgpt.com/docs/*` (same content, new host — both cited below since
either may be canonical depending on when this is read). Community sources
(blogs, third-party wikis) are used only to triangulate wording and are
flagged as such; every load-bearing claim is backed by a primary fetch.

**Caveat on volatility**: Codex CLI's docs explicitly describe several
features (the MCP JSON-RPC interface, `auto_review`) as experimental/subject
to change, and the hooks system is new enough that even the CLI's own error
strings mention concurrent format churn. Treat version-specific details
(exact flag names, exact JSON field names) as a snapshot, not a permanent
contract — re-verify before building against them.

---

## 1. Config file location and format

- Global config: **TOML** at `~/.codex/config.toml`. `CODEX_HOME` (default
  `~/.codex`) is the root for config, auth, history, logs, and caches.
  [Advanced Configuration](https://learn.chatgpt.com/docs/config-file/config-advanced)
- Project-scoped overrides: `<repo>/.codex/config.toml`, loaded **only when
  the project is trusted** (see §3). Untrusted projects get user/system
  config layers only — project `.codex/` (config, hooks, rules) is ignored
  entirely.
  [Advanced Configuration](https://learn.chatgpt.com/docs/config-file/config-advanced)
- **Profiles**: named config layers in separate files,
  `~/.codex/<profile-name>.config.toml`, layered on top of the base
  `~/.codex/config.toml`. Selected via `codex --profile <name>`. Profile
  names allow letters/digits/hyphens/underscores; a profile file can
  override things like `model_catalog_json`.
  [Advanced Configuration](https://learn.chatgpt.com/docs/config-file/config-advanced)
- Reference doc structure: OpenAI splits config docs into `config-basic`,
  `config-advanced`, and `config-reference`
  ([GitHub `docs/config.md`](https://github.com/openai/codex/blob/main/docs/config.md)
  now just points at these three URLs rather than holding the content
  itself — the in-repo doc has been thinned to a pointer).

## 2. Execution modes: interactive vs. `codex exec`

- **Interactive mode** is the default terminal-loop UX: user steers each
  turn, inspects diffs/commands as they appear, follow-ups stay in the same
  session. [CLI features](https://learn.chatgpt.com/docs/codex/cli)
- **`codex exec`** (short form `codex e`) is the **non-interactive** mode —
  "scripted or CI-style runs that should finish without human interaction,"
  intended for pipelines/automation.
  [CLI features](https://learn.chatgpt.com/docs/codex/cli);
  flag confirmed via
  [community search summary](https://developers.openai.com/codex/developer-commands)
  (not independently fetched in full — treat the exact `codex e` short-form
  spelling as secondary-sourced).
- `codex resume` reopens a recent chat scoped to the current repo, or
  searches across local chats to return to older sessions.
  [CLI features](https://learn.chatgpt.com/docs/codex/cli)

## 3. Approval and sandbox model

Two **independent, composed** layers — this is the architecturally load-
bearing fact for where a policy daemon would sit:

1. **Sandbox mode** — the technical capability boundary (what the process
   is *permitted* to touch), enforced by the OS:
   - `read-only` — read + answer questions only; edits/exec/network need
     approval. Default for **non**-version-controlled folders.
   - `workspace-write` — read, edit, and run commands inside the
     workspace; network access **off by default** (toggle via
     `[sandbox_workspace_write] network_access = true`); `.git`, `.agents`,
     `.codex` stay read-only even in this mode. Default for
     version-controlled folders.
   - `danger-full-access` — no sandbox enforcement at all. Reached via
     `--dangerously-bypass-approvals-and-sandbox` / `--yolo`.
   - Enforcement is platform-native: **macOS** via Seatbelt
     (`sandbox-exec`), **Linux** via `bwrap` + `seccomp`, **Windows** via a
     native sandbox or WSL2 inheritance.
   [Agent approvals & security](https://learn.chatgpt.com/docs/agent-approvals-security)

2. **Approval policy** — when Codex must pause and ask a human/reviewer
   before acting:
   - `on-request` — default for version-controlled folders; approval
     required to escalate the sandbox boundary, hit the network, or run
     destructive app/MCP tool calls.
   - `never` (`--ask-for-approval never` / `-a never`) — no prompts at all;
     composes with whatever sandbox mode is set (sandbox constraints still
     apply — "never ask" is not "no sandbox").
   - `untrusted` — auto-runs only known-safe reads; asks before anything
     mutating or externally-executing (e.g. destructive git ops).
     **Cross-document flag (added during the Plan 00292 repair pass,
     2026-08-30): `RESEARCH-prior-art.md` Part 1 reports, single
     third-party source (smartscope.blog), unconfirmed against an
     official OpenAI changelog, that `untrusted` was retired in
     `v0.149.0` (dated 2026-08-20 — only 10 days before this research)
     in favor of `on-request`/`never`. This section's own official-docs
     source (learn.chatgpt.com, fetch date not separately recorded)
     still lists `untrusted` as current. The two sources disagree and
     neither was re-fetched to settle it; treat `untrusted`'s
     current/retired status as an open question, not as decided by
     whichever of these two you read first.**
   - `auto_review` (`approvals_reviewer = "auto_review"`) — routes eligible
     approval requests to a **separate reviewer agent** instead of a human,
     which evaluates for data exfiltration, credential probing, destructive
     actions. This is the closest analog in Codex's own model to "a policy
     daemon decides instead of a human."
   [Agent approvals & security](https://learn.chatgpt.com/docs/agent-approvals-security)

- **Where the decision is enforced**: "at the point of action
  execution — before shell commands, file modifications outside protected
  zones, network calls, and side-effecting tool invocations complete."
  I.e. enforcement is in-process, right before the syscall/tool-effect,
  not at session boundaries. This is the natural insertion point a
  supervisor/policy daemon would want, and it is exactly the point the
  `PreToolUse`/`PermissionRequest` hooks also sit at (§5) — Codex appears
  to route both its own approval UI *and* hook-based interception through
  the same pre-execution checkpoint.
  [Agent approvals & security](https://learn.chatgpt.com/docs/agent-approvals-security)
- Config keys: `approval_policy = "on-request" | "never" | "untrusted"`,
  `sandbox_mode = "workspace-write" | "read-only" | "danger-full-access"`,
  `approvals_reviewer = "user" | "auto_review"`.
  [Agent approvals & security](https://learn.chatgpt.com/docs/agent-approvals-security)
- Combined CLI preset example given in docs:
  `codex --sandbox workspace-write --ask-for-approval on-request`.
  [Agent approvals & security](https://learn.chatgpt.com/docs/agent-approvals-security)
- Note on `--full-auto`: one third-party source (SmartScope, secondary,
  not independently verified against primary docs) describes it as a
  deprecated compatibility flag superseded by `--sandbox workspace-write`,
  and describes `--dangerously-bypass-approvals-and-sandbox`/`--yolo` as
  requiring sandbox+approval+trust to all be bypassed together as of
  v0.20. **Flag this as secondary/unverified** — I could not independently
  confirm the version-gated behavior from an OpenAI primary source.

## 4. MCP support — Codex as both client and server

- **Codex as MCP client**: `mcp_servers` table in `config.toml` (note:
  key is `mcp_servers`, not `mcpServers`). Per-server config includes
  `command`, `args`, `cwd`, `env`, auth mode (`oauth` or `chatgpt`), tool
  allow/deny lists, approval mode, and timeout.
  [Config reference](https://learn.chatgpt.com/docs/config-file/config-reference);
  structure corroborated by
  [Model Context Protocol docs](https://developers.openai.com/codex/mcp)
  (redirect target not independently re-fetched in full — cross-checked via
  search summary only).
  - Two transports: **stdio** (local child process, stdin/stdout — CLI-based
    servers, LSPs, internal tools) and **Streamable HTTP** (remote server
    over HTTP, optional OAuth/bearer auth — cloud-hosted MCP services).
  - CLI helpers: `codex mcp add` (interactive setup) and
    `codex mcp login <server-name> [--oauth-client-registration cimd|dcr]`
    for OAuth servers. (Sourced from a web-search synthesis over
    `developers.openai.com/codex/mcp` and related pages — not fetched
    verbatim; treat exact subcommand spelling as likely-correct but
    secondary-sourced.)
- **Codex as MCP server**: Codex can run in a server mode exposing its own
  coding-agent capabilities (file editing, command execution, sandboxed
  execution) as MCP tools callable by other agents/orchestrators (e.g. the
  OpenAI Agents SDK). There is also a distinct, explicitly **experimental**
  JSON-RPC-over-MCP-transport interface documented in-repo at
  [`codex-rs/docs/codex_mcp_interface.md`](https://github.com/openai/codex/blob/main/codex-rs/docs/codex_mcp_interface.md)
  for controlling a local Codex engine — "experimental and subject to
  change without notice" per its own framing (not fetched verbatim here;
  flagged from search result, worth a direct fetch if this interface
  becomes load-bearing for the plan).
  - A **`codex mcp-server`** command is reported (via search synthesis,
    not fetched primary) as **deprecated** in favor of an "app server"
    approach — this needs direct confirmation before being relied on.

## 5. Lifecycle hooks — the closest analog to Claude Code's settings.json hooks

This is the single most significant parallel to Claude Code's hook system
found in this research, and is highly relevant to "where a policy daemon
would want to sit."

- **Config locations, in discovery order** (user → project → plugin →
  enterprise-managed):
  - `~/.codex/hooks.json` or inline `[hooks]` tables in `~/.codex/config.toml`
  - `<repo>/.codex/hooks.json` or inline `[hooks]` in `<repo>/.codex/config.toml`
    (project-level; gated on project trust, same as config, §3)
  - plugin-bundled `hooks/hooks.json` at a plugin's root
  - enterprise-managed hooks from `requirements.toml`
  - If both `hooks.json` and inline `[hooks]` exist in the same layer,
    Codex loads **both** and warns.
  - Admins can set `allow_managed_hooks_only = true` (top-level, in
    `requirements.toml`) to make Codex ignore user/project/session hook
    configs entirely and only run managed hooks — this is the enterprise
    lockdown knob.
  [`docs/config.md`](https://github.com/openai/codex/blob/main/docs/config.md);
  [Hooks reference](https://learn.chatgpt.com/docs/hooks)
- **Hook events** (name parity with Claude Code is close but not exact):
  `PreToolUse`, `PostToolUse`, `PermissionRequest`, `PreCompact`,
  `PostCompact`, `SessionStart`, `SessionEnd`, `SubagentStart`,
  `SubagentStop`, `UserPromptSubmit`, `Stop`.
  [Hooks reference](https://learn.chatgpt.com/docs/hooks)
- **Scope**: most events are turn-scoped (`PreToolUse`, `PermissionRequest`,
  `PostToolUse`, `PreCompact`, `PostCompact`, `UserPromptSubmit`,
  `SubagentStop`, `Stop`); `SessionStart` and `SubagentStart` run at
  thread/subagent-start scope. [Hooks reference](https://learn.chatgpt.com/docs/hooks)
- **Config shape** (JSON, `hooks.json` or inline TOML): three levels —
  event name → matcher group → one or more handlers
  (`{"type":"command","command":"...","statusMessage":"...","timeout":N}`).
  TOML equivalent uses `[[hooks.EventName]]` arrays with nested
  `[[hooks.EventName.hooks]]` tables. [Hooks reference](https://learn.chatgpt.com/docs/hooks)
- **Matchers**: regex against tool name for `PreToolUse`/`PostToolUse`
  (e.g. `^Bash$`, `Edit|Write`, `mcp__filesystem__.*`); `manual|auto` for
  `Pre/PostCompact`; `startup|resume|clear|compact` for `SessionStart`;
  `PermissionRequest`/`UserPromptSubmit`/`Stop` take no matcher.
  [Hooks reference](https://learn.chatgpt.com/docs/hooks)
- **Hook stdin payload** (shared fields): `session_id`, `transcript_path`,
  `cwd`, `hook_event_name`, `model`, `permission_mode`, `turn_id` (turn-
  scoped hooks) — plus event-specific fields (`tool_name`, `tool_input`,
  `tool_response`, `source`, `prompt`, ...). This is structurally very
  close to Claude Code's hook JSON contract.
  [Hooks reference](https://learn.chatgpt.com/docs/hooks)
- **Hook stdout/response contract**:
  - Common: `continue: false/true`, `stopReason`, `systemMessage`
    (surfaced as a UI warning), `suppressOutput` (parsed but "not
    implemented" per the doc — i.e. currently inert).
  - `PreToolUse`: `permissionDecision: "deny"` blocks; `"allow"` +
    `updatedInput` rewrites the tool call's arguments; exit code `2` +
    stderr is an alternative blocking mechanism.
  - `PostToolUse`: `decision: "block"` records feedback (cannot undo an
    already-completed action); `continue: false` stops normal result
    processing; exit code 2 + stderr as an alternative.
  - `PermissionRequest`: structured
    `{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow|deny","message":"..."}}}`.
  - `additionalContext`: hooks that support it can inject text into the
    model's context; default budget ~2,500 tokens
    (`additionalContextLimit` to configure); oversized output spills to
    disk and the model gets a preview + file path.
  [Hooks reference](https://learn.chatgpt.com/docs/hooks)
- **Known limitations** (important for anyone building interception
  tooling):
  - **`PreToolUse`/`PostToolUse` currently only fire for Bash/shell,
    `apply_patch`, MCP tool calls, and some local function tools** — NOT
    for Edit/Write/Read or hosted tools like WebSearch. Multiple GitHub
    issues track requests to widen this
    ([#19385](https://github.com/openai/codex/issues/19385),
    [#18491](https://github.com/openai/codex/issues/18491),
    [#14882](https://github.com/openai/codex/issues/14882)) — i.e. Codex's
    own community is actively asking for Claude-Code-hook parity, which
    the project frames explicitly ("clarify Claude-style hook parity").
    This is a live gap, not settled behavior.
  - Multiple matching command hooks for one event run **concurrently** —
    one hook cannot block another from starting.
  - `SessionEnd` hooks always run **synchronously**, default timeout 1s,
    max 3s.
  - Background hooks (`async: true`) cannot block operations; capped at 8
    concurrent background hooks per session.
  - **Trust**: non-managed hooks require explicit trust before they run,
    tracked by a hash of the hook definition — editing a hook requires
    re-review. Manage via the `/hooks` command. Managed hooks (system/MDM/
    `requirements.toml`) bypass this trust gate.
  - Disable all hooks: `[features] hooks = false` in `config.toml`.
  [Hooks reference](https://learn.chatgpt.com/docs/hooks)

**Relevance to a policy daemon**: Codex's hook system is architecturally
the right seam — `PreToolUse`/`PermissionRequest` sit at the same
pre-execution checkpoint as the sandbox/approval enforcement described in
§3, and the payload/response contract (JSON stdin, `permissionDecision`,
`updatedInput`) is expressive enough to build an out-of-process supervisor
against, much like the ccy PTY-supervisor pattern does for Claude Code.
The load-bearing caveat is the tool-coverage gap: as of this research,
interception is Bash/apply_patch/MCP-only, so a Codex-side supervisor
cannot yet observe/gate native Edit/Write/Read the way it can shell-outs —
confirm current coverage before relying on it, since the GitHub issues
above suggest this is actively being expanded.

## 6. Session / transcript storage

- Session ("rollout") files are JSONL, stored under
  `~/.codex/sessions/YYYY/MM/DD/`, named
  `rollout-<timestamp>-<session-id>.jsonl` (session ids look like UUIDs,
  e.g. `019edfd4-fbf0-7100-a982-2ab5bdf125fb`). Filenames and the internal
  `session_id` are auto-generated at session start and cannot be set via
  CLI/config. **This path/naming is corroborated by a native macOS viewer
  project and an official-repo discussion thread, not by a doc page I
  could fetch verbatim** — treat as high-confidence but community-sourced:
  [Discussion #24042](https://github.com/openai/codex/discussions/24042),
  [Discussion #3827](https://github.com/openai/codex/discussions/3827).
  One participant in #24042 explicitly asks whether the JSONL schema is
  stable across versions and gets no confirming answer in the thread —
  **schema stability is unconfirmed**, flag as an open question.
  - Each line reportedly covers the full event stream: prompts, model
    responses, tool calls/results, approval decisions, token-usage
    counters — per the same secondary source
    ([Codex Knowledge Base, "Rollout System"](https://artvandelay.github.io/codex-agentic-patterns/learning-material/18-rollout-system/),
    a community write-up, not primary — treat as directional only).
- Separately, `~/.codex/history.jsonl` holds a running session-transcript
  history (distinct from the per-session rollout files); controlled by
  `history.persistence` (`"save-all"` per config-reference synthesis vs.
  a plain default, docs disagree slightly on the literal default token —
  `"none"` disables it) and `history.max_bytes` (oldest entries dropped
  once the cap is hit).
  [Advanced Configuration](https://learn.chatgpt.com/docs/config-file/config-advanced);
  [Config reference](https://learn.chatgpt.com/docs/config-file/config-reference)
  — **note the two docs pages gave slightly different persistence-value
  vocabulary (`save-all`/`none` vs. described only as boolean-like); this
  is an open question to resolve by reading `config-reference` directly
  again if the exact enum matters.**
- `codex resume` reads back from this session store to reopen or search
  past chats. [CLI features](https://learn.chatgpt.com/docs/codex/cli)

## 7. Environment variables

- `CODEX_HOME` — root directory for config/auth/history/logs/cache,
  defaults to `~/.codex`.
  [Advanced Configuration](https://learn.chatgpt.com/docs/config-file/config-advanced)
- `OPENAI_API_KEY` — credential for the default OpenAI model provider
  (custom providers set their own key via `env_key` in provider config).
  [Advanced Configuration](https://learn.chatgpt.com/docs/config-file/config-advanced)
- `[shell_environment_policy]` in config.toml governs which env vars are
  passed to **spawned commands** (not Codex itself): `inherit = "none"`
  (empty env) or `"core"` (trimmed set); `set` for explicit key/value
  pairs; `filters` for case-insensitive include/exclude glob patterns
  (e.g. `AWS_*`); variables containing KEY/SECRET/TOKEN are auto-excluded
  by default per the config-reference synthesis (worth re-verifying
  verbatim — this exclusion behavior was reported via search summary, not
  fetched as page text).
  [Advanced Configuration](https://learn.chatgpt.com/docs/config-file/config-advanced);
  [Config reference](https://learn.chatgpt.com/docs/config-file/config-reference)

## 8. Session-start context injection: `AGENTS.md`

- Codex reads `AGENTS.md` at the project root and includes it (bounded) in
  the first turn — this is Codex's rough analog to Claude Code's
  `CLAUDE.md` auto-loading, **not** to session-start hook injection per se
  (that's covered by the `SessionStart` hook event in §5, which can also
  push `additionalContext`).
  [Advanced Configuration](https://learn.chatgpt.com/docs/config-file/config-advanced)
- `project_doc_max_bytes` bounds how much is read; `project_doc_fallback_filenames`
  lists alternate filenames used when `AGENTS.md` is absent.
  [Advanced Configuration](https://learn.chatgpt.com/docs/config-file/config-advanced)
- Project root is detected via `.git` presence or custom
  `project_root_markers`. [Advanced Configuration](https://learn.chatgpt.com/docs/config-file/config-advanced)

## 9. Status line — no confirmed equivalent found

I found **no primary-source evidence of a Claude-Code-style configurable
status line** (a user-scriptable line rendered in the TUI reflecting
session/cost/branch state) in Codex CLI's docs. The TUI does have a
`tui.notifications` setting for in-terminal notifications (distinct from
the external `notify` program hook, §7 of Claude-Code-analog features —
see §"Notifications" below), but that is not a status line. **Open
question** — worth a targeted follow-up search on `developers.openai.com/codex`
for `tui` config options before concluding this is truly absent.

## 10. Notifications (`notify`) — distinct from hooks

- `notify` in `config.toml` is an external-program hook fired on Codex
  events (currently `agent-turn-complete`): `notify = ["python3",
  "/path/to/notify.py"]`. The script receives one JSON CLI argument with
  fields like `type`, `thread-id`, `input-messages`,
  `last-assistant-message`. Positioned by the docs as good for
  webhooks/desktop notifiers/CI hooks, as distinct from `tui.notifications`
  (the built-in terminal UI notification feature) and from the `hooks.json`
  lifecycle-hook system in §5 — three separate extension points that are
  easy to conflate.
  [Advanced Configuration](https://learn.chatgpt.com/docs/config-file/config-advanced)

## 11. Third-party integration today

- **MCP** (§4) is the primary sanctioned integration surface, in both
  directions (Codex-as-client, Codex-as-server).
- **Hooks** (§5) are the sanctioned in-process interception surface,
  structurally aimed at the same use cases Claude Code's `settings.json`
  hooks serve (policy daemons, audit logging, tool-call rewriting) but
  currently narrower in tool coverage (Bash/apply_patch/MCP only).
- Community tooling exists around both surfaces (session viewers reading
  the rollout JSONL directly, third-party MCP servers that wrap Codex CLI
  itself as a callable agent — e.g. `tuannvm/codex-mcp-server`,
  `glama.ai`-listed servers) — these read/write the same on-disk
  artifacts (`~/.codex/sessions/...`, `config.toml`) rather than using any
  documented stable API, so they are liable to break on format changes;
  none of this is confirmed as an officially supported integration
  pattern.

---

## Key facts (condensed)

1. Config is TOML at `~/.codex/config.toml` (`CODEX_HOME`, default
   `~/.codex`); profiles are separate `~/.codex/<name>.config.toml` files
   selected with `--profile`; project overrides live in `<repo>/.codex/config.toml`
   and require the project to be **trusted**.
2. Two modes: interactive (default TUI loop) and `codex exec`/`codex e`
   (non-interactive, scripted/CI).
3. Security is two independent layers — **sandbox_mode**
   (`read-only`/`workspace-write`/`danger-full-access`, OS-enforced) ×
   **approval_policy** (`on-request`/`never`/`untrusted`, plus an
   `auto_review` reviewer-agent mode) — enforced right before each
   side-effecting action, the same checkpoint the `PreToolUse`/
   `PermissionRequest` hooks occupy.
4. Codex is both an MCP client (`mcp_servers` in config.toml, stdio or
   Streamable HTTP transport) and can run as an MCP server exposing its
   own agent capabilities; there's also a separate, explicitly
   experimental JSON-RPC/MCP control interface in-repo.
5. Codex has a genuine **lifecycle hooks** system (`hooks.json` or inline
   `[hooks]` in `config.toml`) with events (`PreToolUse`, `PostToolUse`,
   `PermissionRequest`, `SessionStart`, `SessionEnd`,
   `UserPromptSubmit`, `Stop`, `SubagentStart/Stop`,
   `PreCompact`/`PostCompact`) closely paralleling Claude Code's
   `settings.json` hooks — same JSON stdin/stdout contract shape, matcher
   groups, block/allow/rewrite semantics — but currently limited to
   intercepting Bash/apply_patch/MCP tool calls (not Edit/Write/Read), a
   gap the project's own open GitHub issues are actively tracking.
6. Sessions are stored as JSONL "rollout" files under
   `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<id>.jsonl`; a
   separate `~/.codex/history.jsonl` holds transcript history governed by
   `history.persistence`/`history.max_bytes`. Rollout JSONL schema
   stability across versions is not confirmed anywhere I could find.
7. `AGENTS.md` at the project root is Codex's analog to `CLAUDE.md`
   auto-loading (bounded by `project_doc_max_bytes`), injected on the
   first turn — separate from the `SessionStart` hook event.
8. No confirmed status-line equivalent was found; `notify` (external
   program on `agent-turn-complete`) and `tui.notifications` (in-TUI) are
   two different, smaller features that are easy to mistake for one.
9. Enterprise/admin lockdown exists: `requirements.toml` with
   `allow_managed_hooks_only = true` restricts Codex to only run
   managed/system hooks, ignoring user/project/session hook configs.

## Open questions

- **Rollout JSONL schema stability**: is the per-line schema versioned or
  guaranteed stable? An open GitHub discussion question on this went
  unanswered. Needs either an official doc page or direct empirical
  inspection of files across two Codex versions.
- **Exact `history.persistence` enum**: docs sources disagreed slightly on
  vocabulary (`"save-all"`/`"none"` vs. a looser description) — needs a
  direct re-fetch of `config-reference` to pin down the literal accepted
  values.
- **`PreToolUse`/`PostToolUse` tool coverage**: confirmed as of this
  research to exclude Edit/Write/Read and hosted tools like WebSearch, but
  multiple open issues (#19385, #18491, #14882) suggest this is being
  actively worked — re-check current coverage before any supervisor design
  assumes it's fixed.
- **Status line**: not found in the docs I reached; worth one more
  targeted search/fetch pass (e.g. `developers.openai.com/codex` TUI
  config page) before concluding Codex has nothing like it.
- **`codex mcp-server` deprecation and the "app server" replacement**:
  reported via search synthesis only, not fetched from a primary page —
  needs direct confirmation, especially given this could matter for a
  dual-host design that wants Codex to act as an MCP server.
- **Experimental MCP JSON-RPC interface**
  (`codex-rs/docs/codex_mcp_interface.md`): flagged but not fetched in
  full in this pass — worth reading directly if the plan needs a stable
  control-plane API into a running Codex engine.
- **`--full-auto` deprecation / v0.20 trust-gating behavior**: sourced
  from a single secondary (SmartScope) article, not corroborated by an
  OpenAI primary source — treat as unverified.
- Whether Codex has anything resembling Claude Code's `settings.local.json`
  split (tracked vs. per-developer local config) was not investigated in
  this pass.
