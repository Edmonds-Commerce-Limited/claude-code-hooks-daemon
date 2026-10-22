# RESEARCH: opencode vs Codex CLI vs Claude Code, and subscription lock-in (Plan 00549 Task 4.1)

The owner asked: "can we also do a comparison of opencode vs codex. My understanding is that OpenAI don't lock you
into their Codex CLI and you could use opencode with an OpenAI subscription?"

**Short answer: yes, and it is now official.** Since about 2026-09-29 OpenAI runs "Sign in with ChatGPT" for third-party
tools, and opencode ships it as a built-in sign-in method. A ChatGPT Plus or Pro plan can drive opencode, and the usage
counts against the same Codex allowance (§1.1). Anthropic is the opposite: Claude Free/Pro/Max subscription login in a
third-party tool is prohibited by its terms, and opencode has removed it, so opencode reaches Claude by API key only
(§1.2). Codex is open source (Apache-2.0) and can use other providers, but only ones that speak OpenAI's Responses API
(§1.3).

For the daemon, **Codex is now the easier second host**: its hooks are stable, on by default, command-based, a near-port
of the Claude Code schema, and they now cover file edits (§3).

## 0. Baseline and method

| Subject     | Version read                                                                                                                                                                                                                                                                    |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| opencode    | Clone `untracked/repos/opencode` at `c93aaae37157d785f76a8e9a9243a6560e286468` (product V2 2.1.2; ARCH "Source baseline"). Full history is present, so the commit citations below are verifiable.                                                                               |
| Codex CLI   | Fresh shallow clone `untracked/repos/codex` at `b337fe06b7d8d6e5b42295e04c5e92c2b9c46567` (committed 2026-10-22). The latest stable release is `rust-v0.163.0` (2026-10-15). `0.164.0-alpha.*` builds ship several times a day (`gh release list -R openai/codex`, 2026-10-22). |
| Claude Code | The docs at https://code.claude.com/docs (fetched 2026-10-22) and this plan's earlier documents.                                                                                                                                                                                |

Plan 00292 (Completed) is about two months old and has been **superseded on several points**: Codex hooks are now stable,
and they now fire on `apply_patch` edits (§2.1). Every Codex fact used here was re-read from the source at the commit
above. 00292 had relied on `WebFetch` summaries. Paths without a prefix are relative to each clone's root.

Short names follow `FINDINGS.md` (ARCH, SURFACE, MAP, OPTIONS, COUP, PLANWF, AMD).

---

## 1. Model, provider and subscription lock-in

### 1.1 opencode with a ChatGPT subscription: yes, officially supported, built in

opencode V2 ships **two** ways to use ChatGPT-plan credentials. Both are core provider plugins, so no community plugin
is involved.

1. **"Sign in with ChatGPT" (token sharing), the current official route.**
   `packages/core/src/plugin/provider/chatgpt.ts`:

   - Method label `"Sign in with ChatGPT"`, id `chatgpt-token-sharing` (`:29`, `:96-100`).
   - OAuth with PKCE against `https://auth.openai.com`, using **dynamic client registration**: "First-time sign-in
     registers a user-owned client; OpenAI returns its issued client ID on the callback" (`:20-24`). The agent name
     hint is `OpenCode` (`:22`, `:528-543`).
   - Scope `chatgpt.tokens.use.direct` (`:26`, `:537`). Sign-in fails unless the user grants token sharing (`:176-180`).
   - Requests go to the public `https://api.openai.com/v1` (`:25`, `:292`), and the plugin zeroes the per-model cost
     because the usage is plan-billed (`:325`).
   - It understands OpenAI's sharing error codes (`subscription_sharing_usage_limit_exceeded`, `_user_not_eligible`,
     and so on; `:49-57`) and stops retrying on them (`:260-268`).
   - "pro" reasoning models are disabled on this route (`:317-319`).

   History: `4d9090790b` "add separate ChatGPT token-sharing OAuth method" (2026-09-29); `0f83038253` "align ChatGPT
   token sharing with updated partner guide"; `209346a0fe` (2026-10-05) "temporarily stop syncing w/ /models api …
   due to openai bugs". **The programme is weeks old and still settling.**

2. **"Codex browser (legacy)" / "Codex device code (legacy)", the older route.**
   `packages/core/src/plugin/provider/openai.ts`:

   - Labels at `:59` and `:178`.
   - It uses **the Codex CLI's own OAuth client ID** `app_EMoamEEZ73f0CkXaXp7hrann` (`:16`). That is byte-identical to
     Codex's `CLIENT_ID` (`codex-rs/login/src/auth/manager.rs:1784`).
   - Requests go to `https://chatgpt.com/backend-api/codex` (`:23`), the Codex backend, with `originator: opencode`
     (`:272`, `:318`) and a Codex-eligible model allow-list (`:26-28`, `:280-294`).
   - opencode relabelled both methods as "legacy" on 2026-10-05 (`48b295aef4`).

**OpenAI's position (official docs):**

- https://developers.openai.com/siwc/quickstart (fetched 2026-10-22): Sign in with ChatGPT "lets users sign in to your
  app with their ChatGPT account and, when eligible, use their ChatGPT plan for AI requests". "ChatGPT plan usage is
  available to all open-source partners and selected private clients". For open-source clients, the flow "registers
  your client and issues OAuth credentials for eligible Responses API requests" with no client secret. It "doesn't
  grant access to the user's API key or conversations".
- Help article https://help.openai.com/articles/20001542, "Using your ChatGPT plan in other apps and sites". **Direct
  fetch returned 403**, so the following is from search-result extracts only (UNVERIFIED verbatim): only **Plus and
  Pro** can use their plan, while any user can sign in. Usage "count[s] toward the ChatGPT Work and Codex usage
  included in your plan". Users can set a weekly cap per app, and credits are used only if explicitly allowed.
- Secondary coverage dates the launch to DevDay, 2026-09-29, with opencode among about 16 launch partners
  (https://daily.dev/posts/openai-makes-sign-in-with-chatgpt-a-way-to-use-your-subscription-in-third-party-developer-tools-7ewaoo6ze,
  https://flaviocopes.com/sign-in-with-chatgpt/). This is consistent with opencode's commit dates. The partner list
  itself is UNVERIFIED.

**Caveats:**

- **Team/Business, Enterprise and Edu plans:** the search extract names only Plus and Pro for plan usage.
  `chatgpt.ts` itself is plan-agnostic, and the server decides eligibility (`subscription_sharing_user_not_eligible`).
  Treat Team as **not supported** until the help article is read directly (UNVERIFIED).
- **Legacy route terms:** no OpenAI document found either authorises or forbids a third party reusing the Codex CLI's
  client ID against the Codex backend. Now that an official route exists, **recommend the token-sharing method** and
  treat the legacy one as unsupported by OpenAI (UNVERIFIED either way).
- A shared allowance means opencode usage and Codex CLI usage on the same plan **draw down the same pool**.

### 1.2 opencode with a Claude Pro/Max subscription: no. Prohibited, and removed from opencode

- **Anthropic's terms.** https://code.claude.com/docs/en/legal-and-compliance, "Authentication and credential use"
  (fetched 2026-10-22), says OAuth "is designed to support ordinary use of Claude Code and other native Anthropic
  applications". It goes on: "Anthropic does not permit third-party developers to offer Claude.ai login into their own
  applications, or to route requests through Free, Pro, or Max plan credentials on behalf of their users … developers
  may not collect, store, or intermediate Claude.ai credentials or session tokens". It ends: "Anthropic reserves the
  right to take measures to enforce these restrictions … without prior notice." The underlying terms are the Consumer
  Terms (https://www.anthropic.com/legal/consumer-terms) for Free, Pro and Max.

- **opencode's code at the baseline commit.**

  - No Anthropic OAuth provider exists. There is no `anthropic.ts` under `packages/core/src/plugin/provider/`.
    `chatgpt.ts` and `openai.ts` are the only subscription OAuth providers for model access.
  - Commit `54f2356166` (2026-09-17) "remove Anthropic Pro and Max copy" deleted `provider.connect.title.anthropicProMax`
    ("Sign in with Claude Pro/Max") in 63 locales. It changed the provider note to "Direct access to Claude models via
    API key".
  - A legacy v1 `auth.json` OAuth entry would still be imported by
    `database/migration/20260805200742_import_legacy_credentials.ts:104-108` (method id `oauth`). No provider consumes
    it.

- **Timeline (secondary sources only, UNVERIFIED):**

  - Server-side rejection of third-party OAuth tokens from about 2026-01-09.
  - A written terms clause on 2026-02-19, the same day opencode removed its Claude OAuth code citing "Anthropic legal
    requests".
  - Full cutoff around April 2026.

  Sources: https://winbuzzer.com/2026/02/19/anthropic-bans-claude-subscription-oauth-in-third-party-apps-xcxwbn/,
  https://www.zbuild.io/resources/news/opencode-blocked-anthropic-2026. The full v1 history is outside this clone's V2
  tree and was not traced.

- **Community plugins that re-add Claude OAuth to opencode would breach the terms above.** Do not recommend them.

- **What is permitted:** opencode with an Anthropic API key (Console), or Claude through Bedrock, Vertex or Foundry.
  The same terms allow "an end user … signing in to the **unmodified** Claude Code binary with their own Claude
  subscription".

### 1.3 Codex CLI with non-OpenAI providers: yes, but only through the Responses API

- **Licence:** Apache-2.0 (`LICENSE`). The CLI is free. A model needs either ChatGPT sign-in or an API key (`docs/authentication.md`).
- **Built-in providers** (`codex-rs/model-provider-info/src/lib.rs:662-693`): `openai`, `amazon-bedrock`,
  `amazon-bedrock-runtime`, `ollama` (port 11434), and `lmstudio` (port 1234). The comment at `:673` reads "open source
  ('oss') providers".
- `--oss` / `--local-provider` select a local provider (`cli/src/main.rs:4185`; `exec/src/lib.rs:115-116`). The old
  `ollama-chat` provider is gone ("`ollama-chat` is no longer supported"; `:103-104`).
- **Custom providers** go in `[model_providers.<id>]` in `config.toml` (`docs/config.md`). However,
  **`WireApi` has a single variant, `Responses`** (`:109-113`). The Chat Completions wire format has been removed, so a
  provider must expose an OpenAI-compatible `/v1/responses` endpoint.
  - Ollama and LM Studio do.
  - Anthropic's native API does not, so **Claude in Codex needs a Responses-compatible gateway**. Whether any gateway
    (OpenRouter, LiteLLM and so on) works well with Codex today is UNVERIFIED.
  - Bedrock support is for OpenAI models hosted on Bedrock (`openai.gpt-5.5` …; `:87-97`), not Claude on Bedrock.
- **Practical reading:** Codex is open but **OpenAI-shaped**. opencode is provider-neutral, with 35+ providers through
  the AI SDK (ARCH §4). Claude Code is Anthropic-model-only (ARCH §8 row 4).

### 1.4 Lock-in summary

| Pairing                                    | Possible?                            | Official?                                                    | Terms constraint                                                      |
| ------------------------------------------ | ------------------------------------ | ------------------------------------------------------------ | --------------------------------------------------------------------- |
| opencode + ChatGPT Plus/Pro plan           | Yes                                  | **Yes**: OpenAI's Sign in with ChatGPT, opencode core (§1.1) | Plus/Pro only (UNVERIFIED extract); shares the Codex allowance        |
| opencode + ChatGPT via legacy Codex auth   | Yes, at the baseline commit          | No OpenAI document found; opencode labels it legacy          | UNVERIFIED; prefer token sharing                                      |
| opencode + Claude Pro/Max plan             | **No**                               | Removed from opencode                                        | **Prohibited** by Anthropic's terms (§1.2)                            |
| opencode + Anthropic API key               | Yes                                  | Yes                                                          | Commercial/API terms                                                  |
| Codex + ChatGPT plan                       | Yes                                  | Yes (native)                                                 | Plan allowance                                                        |
| Codex + Ollama, LM Studio, Bedrock(OpenAI) | Yes                                  | Yes (built in)                                               | None found                                                            |
| Codex + Claude                             | Only through a Responses-API gateway | No                                                           | Needs an API key; gateway support UNVERIFIED                          |
| Claude Code + Claude plan                  | Yes                                  | Yes                                                          | "ordinary, individual usage" (legal-and-compliance, "Acceptable use") |
| Claude Code + OpenAI/other models          | No (Anthropic models only)           | —                                                            | —                                                                     |

**The owner's understanding is correct.** OpenAI does not lock a ChatGPT subscription to the Codex CLI. Anthropic does
lock a Claude subscription to Claude Code and its own apps.

---

## 2. Side by side: opencode V2 vs Codex CLI vs Claude Code

### 2.1 What changed in Codex since Plan 00292

| 00292 said (2026-08-30)                                              | Now (source at `b337fe06`)                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Hooks experimental, behind a feature flag                            | `Feature::CodexHooks`, key `hooks`, `Stage::Stable`, `default_enabled: true` (`codex-rs/features/src/lib.rs:1393-1397`). Docs: "Hooks are enabled by default" (https://learn.chatgpt.com/docs/hooks, fetched 2026-10-22)                                                                                                                                                                                                                                                     |
| PreToolUse fires only for Bash, `apply_patch` and MCP; no Edit/Write | Codex has **no** separate Edit, Write or Read tools: edits are `apply_patch` and reads go through the shell. `apply_patch` fires PreToolUse and PostToolUse with matcher aliases **`Write` and `Edit`** (`core/src/tools/hook_names.rs:28-39`). **Every local function tool** fires PreToolUse by default (`core/src/tools/registry.rs:150-159`). `spawn_agent` is aliased `Agent` (`hook_names.rs:41-51`). Hosted tools such as web search are still not intercepted (docs) |
| 6 events                                                             | **14** in `HookEventName` (`codex-rs/protocol/src/protocol.rs:1699-1714`): PreToolUse, PermissionRequest, PostToolUse, PreCompact, PostCompact, SessionStart, SessionEnd, UserPromptSubmit, SubagentStart, SubagentStop, Stop, Interrupt, PreModelRequest, PostModelRequest. The docs list 12; the two ModelRequest events are undocumented                                                                                                                                  |
| `ask` unsupported (#28437)                                           | **Still unsupported**: "PreToolUse hook returned unsupported permissionDecision:ask" (`hooks/src/engine/output_parser.rs:447-449`)                                                                                                                                                                                                                                                                                                                                           |
| `allow` semantics unclear                                            | Resolved: `allow` is valid **only with `updatedInput`** (a rewrite). A bare `allow` is reported invalid and fails open (`output_parser.rs:437-446`; test `permission_decision_allow_without_updated_input_fails_open`, `hooks/src/events/pre_tool_use.rs:443-465`)                                                                                                                                                                                                           |

### 2.2 Comparison table

| Dimension                  | opencode V2 (2.1.2)                                                                    | Codex CLI (0.163 / `b337fe06`)                                                                                                                                                                                                                                                                                                                                                                  | Claude Code                                                                                                  |
| -------------------------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Licence                    | MIT                                                                                    | Apache-2.0 (`LICENSE`)                                                                                                                                                                                                                                                                                                                                                                          | Proprietary                                                                                                  |
| Language and runtime       | TypeScript on Bun or Node, Effect 4 (ARCH §1.1)                                        | Rust (`codex-rs/`, about 120 crates); npm wrapper `codex-cli/`                                                                                                                                                                                                                                                                                                                                  | Closed Node/TS binary                                                                                        |
| Models                     | 35+ providers (ARCH §4)                                                                | OpenAI, Bedrock (OpenAI models), Ollama, LM Studio, and custom providers on the Responses API only (§1.3)                                                                                                                                                                                                                                                                                       | Anthropic models only                                                                                        |
| Process model              | One shared background HTTP server per user; thin clients (ARCH §1.2)                   | One process per session, plus an optional `app-server` (JSON-RPC, used by IDE clients; `codex-rs/app-server*`) and an `app-server-daemon` crate. A shared-server mode exists but is not the default (UNVERIFIED depth)                                                                                                                                                                          | One process per session                                                                                      |
| Hook mechanism             | **In-process TS plugins** with typed mutable events (SURFACE §2)                       | **Out-of-process command hooks**: JSON on stdin; exit 2 or stdout JSON. Configured in `hooks.json` or `[hooks]` in `config.toml`, in `~/.codex/`, `<repo>/.codex/`, plugins, or managed `requirements.toml` (docs; `hooks/src/engine/discovery.rs`). An `mcp_tool` handler type exists. `prompt` and `agent` types are parsed but skipped: "not supported yet" (`discovery.rs:676-692`)         | Out-of-process command, HTTP, prompt and agent hooks (https://code.claude.com/docs/en/hooks)                 |
| Hook trust                 | Plugins load from config; a failed load is only logged (SURFACE §7)                    | "Before a non-managed hook can run, Codex requires you to review and trust the exact hook definition"; project hooks need a trusted `.codex/` layer (docs; `HookTrustStatus`, `discovery.rs`). `allow_managed_hooks_only` exists (`discovery.rs:95-102`)                                                                                                                                        | Hooks from settings; `allowManagedHooksOnly` in managed settings                                             |
| Hook schema vs Claude Code | Entirely different                                                                     | **Near-port**: `hookSpecificOutput.permissionDecision`, `permissionDecisionReason`, `updatedInput`, `additionalContext`, legacy `decision:"block"`, `continue`/`stopReason`, `stop_hook_active`, `transcript_path` (nullable), `tool_use_id` (`pre_tool_use.rs:168-190`; `events/stop.rs:35`)                                                                                                   | Reference                                                                                                    |
| Block a tool               | `tool.execute.before` throws; `permission.evaluate` denies (MAP)                       | PreToolUse `deny` with a reason, or exit 2 with stderr (`pre_tool_use.rs:242-275`)                                                                                                                                                                                                                                                                                                              | PreToolUse deny                                                                                              |
| Rewrite a tool call        | Mutate the hook input                                                                  | `allow` + `updatedInput`; the last completed hook wins (`pre_tool_use.rs:153-166`)                                                                                                                                                                                                                                                                                                              | `updatedInput`                                                                                               |
| `ask`                      | Permission rules can ask                                                               | **Not from hooks** (§2.1); approval policy instead                                                                                                                                                                                                                                                                                                                                              | Yes                                                                                                          |
| Stop gate                  | **None**: re-drive after idle (PLANWF §1)                                              | **Real veto**: `Stop` `decision:block` + reason becomes a continuation prompt (`events/stop.rs:294-301`); `SubagentStop` likewise (`output_parser.rs:300`)                                                                                                                                                                                                                                      | Real veto                                                                                                    |
| Context injection          | `session.context` on every step (MAP)                                                  | `additionalContext` on SessionStart, SubagentStart, UserPromptSubmit, PreToolUse and PostToolUse. It spills to disk past about 2,500 tokens unless `additionalContextLimit` is set (`codex-rs/config/src/hook_config.rs:192-201`)                                                                                                                                                               | `additionalContext`                                                                                          |
| Hook timeout               | None (FINDINGS §2)                                                                     | Per-hook `timeout` (`hook_config.rs:186-187`); `async` option                                                                                                                                                                                                                                                                                                                                   | Per-hook                                                                                                     |
| Permissions and sandbox    | Ordered allow/ask/deny rules, **default allow all**; no OS sandbox (ARCH §8 row 8)     | **OS sandbox** for commands: Seatbelt on macOS, bubblewrap/Landlock on Linux, a Windows sandbox (`codex-rs/linux-sandbox`, `bwrap`, `sandboxing`; `docs/sandbox.md`). Modes `read-only`, `workspace-write`, `danger-full-access`, plus an approval policy and `execpolicy` rules (`docs/execpolicy.md`). The docs warn tool hooks are "a useful guardrail, not a complete enforcement boundary" | allow/ask/deny rules, permission modes; optional sandboxed Bash (https://code.claude.com/docs/en/sandboxing) |
| Instruction files          | `AGENTS.md` only; global plus walk-up plus nested-on-read; no size cap found (ARCH §6) | `AGENTS.md` (and `AGENTS.override.md`) from the git root down to cwd, concatenated, **capped at 32 KiB** in total by default (`project_doc_max_bytes`; `codex-rs/config/src/config_toml.rs:75`; `core/src/config/mod.rs:255`). `project_doc_fallback_filenames` can add e.g. `CLAUDE.md` (`mod.rs:959`; `docs/agents_md.md`)                                                                    | `CLAUDE.md` tree; `AGENTS.md` only as a fallback (AMD §4)                                                    |
| Skills                     | Reads `.claude/skills` and `.agents/skills` (FINDINGS §2)                              | Agent Skills `SKILL.md` under `.agents/skills` and others (`codex-rs/skills/src/lib.rs:61`; https://developers.openai.com/codex/skills)                                                                                                                                                                                                                                                         | `.claude/skills`                                                                                             |
| Sub-agents                 | `subagent` tool; persistent child sessions                                             | `spawn_agent` multi-agent tools, v1 and v2 (`core/src/tools/handlers/multi_agents*.rs`; `codex-rs/agent-roles`); SubagentStart and SubagentStop hooks                                                                                                                                                                                                                                           | `Task`/`Agent`; SubagentStart and SubagentStop                                                               |
| MCP                        | Client                                                                                 | Client (`rmcp-client`, `codex-mcp`); MCP tool calls are hooked                                                                                                                                                                                                                                                                                                                                  | Client                                                                                                       |
| Headless and SDK           | `run`, `serve` (OpenAPI), SDK                                                          | `codex exec` (`codex-rs/exec`), `app-server` JSON-RPC, TypeScript and Python SDKs (`sdk/typescript`, `sdk/python`)                                                                                                                                                                                                                                                                              | `claude -p`, Agent SDK                                                                                       |
| Session storage            | SQLite, event-sourced (ARCH §7)                                                        | Rollout JSONL files (`codex-rs/rollout`) plus a state DB (`codex-rs/state`); `transcript_path` is handed to hooks and may be null                                                                                                                                                                                                                                                               | JSONL per session                                                                                            |
| Plan mode                  | `plan` agent with permission rules (ARCH §3.4)                                         | "Collaboration modes": `Default` and `plan` templates (`codex-rs/collaboration-mode-templates/templates/{default,plan}.md`); enforcement details not read (UNVERIFIED)                                                                                                                                                                                                                          | Permission mode plus `ExitPlanMode`                                                                          |
| Status line, cron          | None found (FINDINGS §2)                                                               | Not investigated here; 00292 found no status line                                                                                                                                                                                                                                                                                                                                               | Both                                                                                                         |
| Churn                      | V2.1 broke plugin contracts in a minor release                                         | Alphas several times a day; a stable release every week or so                                                                                                                                                                                                                                                                                                                                   | Stable hook protocol                                                                                         |

---

## 3. What it means for this daemon

### 3.1 Codex is now an easier target than opencode, for most of the daemon

- **The same attach model as Claude Code.** Codex hooks are command hooks with Claude-shaped JSON. The daemon's
  forwarder and relay (host-agnostic per 00292 COUP §10) can serve Codex with a thin per-host shim. opencode needs a
  TypeScript plugin inside a shared server, plus Bun in CI (OPTIONS §2 B; M3).
- **Edit-time guards now fire.** The Codex half of 00292's biggest gap is closed: `apply_patch` is hooked, matching
  `Write|Edit`. The daemon still needs a **patch-envelope parser**, because `tool_input` is `{ "command": <patch text> }`
  rather than `file_path`/`content`. opencode's `patch` tool is "Codex-style `apply_patch`" (ARCH §5), so **one parser
  serves both hosts**. It is already planned for plan 3 (FINDINGS §5).
- **Stop gates keep their meaning.** Codex has a real `Stop`/`SubagentStop` veto with `stop_hook_active`, so the
  stop-explanation and autonomy handlers port at full fidelity. opencode only re-drives (FINDINGS §2). This is the
  largest difference between the two hosts.
- **Codex is weaker or different in these places:**
  1. No `ask` from hooks. A Claude-side `ask` must degrade to `deny` or pass through to the approval policy, and the
     daemon must declare which.
  2. A bare `allow` is invalid, so the serializer must emit nothing rather than `allow`.
  3. `PermissionRequest` cannot rewrite.
  4. Hosted tools are unhooked.
  5. **Hook-trust review.** A provisioned `.codex/hooks.json` does not run until the user trusts that exact definition,
     so installs and upgrades need a "trust pending" fail-loud report. Managed `requirements.toml` hooks bypass this for
     organisations.
  6. Reads go through the shell, so Read-keyed handlers become `Bash`-command handlers.
  7. No status line (per 00292; not re-checked).
- **Codex's OS sandbox is a stronger floor than either opencode's rules or the daemon's guards.** The fail-loud baseline
  for Codex should be `workspace-write` plus an approval policy, not hooks alone.

**Net:** Codex covers the safety half and most of the autonomy half with less new machinery. opencode covers the safety
half with a new plugin and loses the stop veto. The UNVERIFIED parts for Codex are smaller (no live run in either case).

### 3.2 Which shared abstraction serves both

From OPTIONS-support:

- **Option A (tool-neutral layer)** serves all three hosts unchanged:

  - git-hook commit gates (plan 1);
  - `AGENTS.md` as the canonical instruction file (plan 2);
  - `.agents/skills` as the shared skill location, read by opencode and Codex.

  Plan 2's size budget already targets Codex's 32 KiB cap.

- **Option B's Python half (plan 3)** is the shared core: the host field, the host-neutral verdict, the per-host
  capability table, tool-name and field maps, the patch parser, and a host-supplied session key. **Codex is the better
  proof that plan 3 is genuinely host-neutral**, because its contract differs from Claude Code's in small, precise ways
  (no `ask`, `allow` only with a rewrite, nullable `transcript_path`, `apply_patch`/`spawn_agent` names). Those are
  exactly the cases a neutral verdict model must express (00292 FINDINGS open question 7).

- **Option B's transport half splits by host:**

  - Codex gets a generated `.codex/hooks.json` pointing at the existing forwarder, with a Codex serializer.
  - opencode gets the TypeScript bridge plugin (plan 4).

- **Option D (rendering)** gains a Codex target: `.codex/hooks.json` and `config.toml` keys (sandbox, approval,
  `project_doc_max_bytes`).

### 3.3 Proposed changes to the epic if Codex is a third host

1. **Plan 0 (spike):** add a Codex leg. A pinned Codex release with a command hook to the daemon socket. Confirm that
   `apply_patch` and `Write|Edit` matching, `Stop` block continuation, trust-review friction and `additionalContext`
   spilling behave as the source reads. It is cheap: no Bun, no TypeScript.
2. **Plan 3 (host abstraction):** design it for N hosts. Use Codex as the first non-Claude consumer in its tests,
   because it is reachable without new transport. Add a `codex` value to the M4 `hosts:` key, and give the capability
   table the `ask→?` and `allow-requires-rewrite` cells.
3. **New plan 4b: Codex adapter.** Generate `.codex/hooks.json`, write the Codex serializer, report trust pending, and
   declare degradations. It depends on plan 3 only. **Consider sequencing it before plan 4 (opencode plugin):** it
   delivers a second host sooner, at lower risk, and validates plan 3 before the TypeScript work.
4. **Plan 5 (rendering):** add the Codex target (§3.2).
5. **M2 (version pin and Routine):** extend it to Codex. The alpha cadence is faster than opencode's, so pin to stable
   `rust-v*` tags.
6. **Plan 6 (autonomy):** for Codex this is mostly porting. The re-drive design stays opencode-only.
7. **Product framing (open M5):** three hosts tip the balance towards option (b), "multi-host enforcement daemon". It
   remains the owner's call.

---

## Gaps

- No live run of opencode or Codex. Every hook behaviour comes from reading the source.
- help.openai.com returned 403. The Plus/Pro-only eligibility and the Team/Business exclusion come from search
  extracts (UNVERIFIED).
- Whether the legacy Codex-client-ID route in opencode is permitted by OpenAI's terms: UNVERIFIED.
- Anthropic enforcement dates come from secondary sources only. The current terms text was fetched directly.
- Codex: not re-read at this commit:
  - plan-mode enforcement;
  - status line;
  - Windows hook behaviour (only `commandWindows` and `windows_managed_dir` were seen in the docs);
  - rollout schema stability;
  - the shared `app-server-daemon` mode;
  - whether a Responses-API gateway can serve Claude models to Codex.
- `PreModelRequest`/`PostModelRequest` exist in the source but are undocumented. Their semantics were not read.
