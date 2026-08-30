# Prior Art: Codex CLI Competitive Analysis + Multi-CLI Bridge Ecosystem

Research for Plan 00292 (codex-cli-dual-host). Two halves: (1) what completed
Plan 00169 already established about Codex CLI, and what has likely moved
since; (2) ecosystem tools that already bridge Claude Code, Codex CLI, and
other agent CLIs — what they abstract, how, and what their existence proves.

---

## Part 1 — What Plan 00169 established, and what has changed

Source: `CLAUDE/Plan/Completed/00169-prior-art-sota-research-and-feature-brainstorm/RESEARCH-FINDINGS.md`
(dated July 2026; §2 "Adjacent agentic-CLI guardrails").

### What 00169 found (as of July 2026)

- Codex CLI was assessed as **"the richest model"** among adjacent CLIs for
  guardrails: a two-axis matrix of `sandbox_mode` (`read-only` /
  `workspace-write` / `danger-full-access`) crossed with `approval_policy`
  (`untrusted` / `on-request` / `never`), OS-enforced (not string-matched).
- Protected paths (`.git`/`.codex`/`.agents`) stay read-only regardless of
  sandbox mode.
- Network access is opt-in with domain allowlisting.
- A **second-LLM `auto_review`** step classifies exfiltration / credential /
  destructive risk before escalating to a human approval prompt.
- Configuration is TOML profiles; Codex reads `AGENTS.md` for project
  instructions.
- Sources cited: <https://developers.openai.com/codex/concepts/sandboxing> ·
  <https://learn.chatgpt.com/docs/agent-approvals-security>

00169 did **not** examine whether Codex CLI has a hooks system at all — at
that time (or at least in that research pass) Codex's programmable
extensibility surface was apparently not on the radar; the write-up frames
Codex purely as a sandbox+approval-policy model, not as a hook-emitting host.
That is the single biggest gap this follow-up research closes (see below).

### What has changed since (as of this research, August 2026)

**1. `approval_policy` enum has shifted.** Per a third-party 2026 guide, the
`untrusted` value from 00169's description was retired in Codex CLI stable
`v0.149.0` (dated August 20, 2026 in the source), and the older `on-failure`
value is deprecated. Current values are `on-request` / `never` (or a granular
object). This is **not independently confirmed against an official OpenAI
changelog** in this pass — treat the specific version number and exact old→new
mapping as uncertain, but the direction (policy enum churn, `untrusted`
retired) is consistent across two independent SmartScope articles surfaced by
search.
(<https://smartscope.blog/en/generative-ai/chatgpt/codex-cli-approval-policy-implementation/>)

**2. Codex CLI now has a hooks system, and it closely mirrors Claude Code's.**
This is the most consequential finding for a "dual-host" plan. Confirmed via
the **official OpenAI docs** (`developers.openai.com/codex/hooks`, which
redirects to `learn.chatgpt.com/docs/hooks`):

- Config file: `.codex/hooks.json` (project-level) or `~/.codex/hooks.json`
  (user-level), also expressible in `config.toml` under a `[hooks]` table, and
  discoverable via plugin-bundled `hooks/hooks.json`.
- **Protocol is deliberately close to Claude Code's**: JSON on stdin
  (`session_id`, `cwd`, `hook_event_name`, `model`, plus event-specific
  fields), JSON on stdout (`continue`, `stopReason`, `systemMessage`,
  `suppressOutput`, plus event-specific fields), and the **same exit-code
  convention**: `0` = success, `2` = blocking decision (reason on stderr),
  other non-zero = error.
- Events: `SessionStart`, `SessionEnd`, `PreToolUse`, `PermissionRequest`,
  `PostToolUse`, `PreCompact`, `PostCompact`, `UserPromptSubmit`,
  `SubagentStart`, `SubagentStop`, `Stop`. `PreToolUse` and
  `PermissionRequest` can deny/rewrite a call (Bash, `apply_patch`, MCP);
  `PostToolUse` cannot undo execution but can give feedback.
- Codex distinguishes **command hooks** (run a script, get the full event
  JSON) from **MCP tool hooks** (invoke a function on a connected MCP server
  with templated args) — MCP tool hooks **cannot block** (their errors don't
  prevent execution), only command hooks can.
- A trust-review flow gates non-managed (project/user-authored) hooks before
  they run; **managed hooks** (from system/MDM/cloud/`requirements.toml`
  sources) are trusted by policy and cannot be disabled from the user hook
  browser — a governance surface Claude Code's hook system does not appear to
  have an equivalent of.
- Official docs source: <https://developers.openai.com/codex/hooks> (redirects
  to <https://learn.chatgpt.com/docs/hooks>).

A secondary source (HookStack, third-party, not officially confirmed) claims
the protocol is close enough that **hook scripts can be byte-for-byte
identical** across Claude Code and Codex when both guarantee a Node.js
runtime, with only the config file location/shape differing
(<https://www.hookstack.app/guides/openai-codex-hooks>). Take the
"byte-for-byte identical" claim as an optimistic simplification, not an
official guarantee — the official docs list slightly different event sets
(Claude Code has more events per 00169 §1, e.g. `StopFailure`,
`FileChanged`/`watchPaths`, `TeammateIdle`, that Codex's list above does not
include) and the exit-code/JSON-shape convergence is real but event-surface
parity is not total.

**3. A third-party comparison (blakecrosley.com, not independently verified)
frames the current state as**: both tools by mid-2026 enforce safety in two
layers — OS-level sandboxing underneath, programmable governance hooks on top
— with Claude Code's hook catalogue described as "broader and more mature"
while Codex's hooks "run alongside the strongest sandbox in the category."
This is an opinionated third-party framing, not a primary source, and should
be read as one blogger's synthesis rather than fact.

### Net effect on the dual-host question

The practical implication for Plan 00292: a hooks daemon built to speak
Claude Code's hook protocol (JSON stdin, exit-code-2 blocking, `hookSpecificOutput`
shapes) is **structurally close** to what Codex CLI now expects, per official
OpenAI docs — same request/response envelope idea, same blocking exit code.
The two concrete adaptation costs are (a) the config file the daemon must
write/read (`.codex/hooks.json` vs `.claude/settings.json`), and (b) the
narrower Codex event set — some of this project's handlers key off events
Codex does not appear to expose (e.g. no `StopFailure`, no `FileChanged`).
Codex's separate command-hook-vs-MCP-tool-hook distinction and its
managed/trust-review layer are new governance concepts this project's design
should account for and do not have a Claude Code analogue in 00169's model.

---

## Part 2 — Ecosystem: tools that already bridge multiple agent CLIs

Search terms covered: hook bridges, shared policy engines, MCP-based
governance layers, guardrail proxies, "Claude Code + Codex CLI" bridges.

### cc-suite (xiaolai/cc-suite)

<https://github.com/xiaolai/cc-suite>

**What it abstracts**: a Claude Code *plugin* that synchronizes Claude Code,
Codex CLI, and Antigravity CLI configuration on the same project so the three
tools stay behaviourally consistent, plus bidirectional task delegation
between Claude Code and Codex.

**How**:

- **Instructions**: declares `AGENTS.md` the single source of truth; `CLAUDE.md`
  becomes a thin import wrapper. Codex/Antigravity read `AGENTS.md` directly.
- **Skills**: symlinks `.agents/skills/` to `.claude/skills/` so all three
  tools share one skill set without duplication.
- **Hooks**: mirrors the shared hook events from `.claude/settings.json` into
  `.codex/hooks.json` so both tools run identical scripts on the same events
  — i.e. it treats the two hook protocols as compatible enough to generate one
  from the other, corroborating the protocol-convergence finding above.
- **MCP servers**: syncs `.mcp.json` into Codex's `.codex/config.toml` and
  Antigravity's `.agents/mcp_config.json`.
- **Delegation**: Claude Code slash commands (`/cc-suite:audit`,
  `/cc-suite:implement`) hand work to Codex via a CLI runner (job tracking,
  background mode, resume). In the other direction, Codex — if it has a
  `claude-code` MCP server registered — can invoke skills like `$claude-review`
  to hand work back to Claude, and can read Claude's session history through
  that same MCP server. Circular delegation is prevented by blocking implicit
  invocations on the Codex side and prepending delegation-boundary markers to
  outbound prompts.

**What its existence proves**: config/hook mirroring across the two tools is
tractable enough that a single OSS plugin does it project-locally (not just a
big platform); bidirectional task handoff between two independent agent CLIs
is being built and shipped, not just theorized; and preventing
delegation loops is a real, named engineering problem (not hypothetical) —
relevant if Plan 00292's dual-host design considers agent-to-agent handoff.

### claude_codex_bridge / CCB (SeemSeam/claude_codex_bridge)

<https://github.com/SeemSeam/claude_codex_bridge>

**What it abstracts**: not config/hooks, but the **terminal session layer** —
a unified multi-pane tmux workspace that runs many different CLI agent
providers (Claude, Codex, Gemini, Kimi, Qwen, Cursor, Copilot, Pi, OpenCode,
"17+ provider families") concurrently, each visible in its own pane, with a
background daemon holding project state alive when the UI closes.

**How**: an inter-agent communication layer manages "collaboration graphs"
(A→B→C, A,B→C handoff patterns) with per-agent isolated authentication and
workspace isolation; a companion mobile app adds cross-provider voice control
and file transfer.

**What it proves possible**: running many heterogeneous agent CLIs side by
side under one coordinating shell is achievable without merging their
internals; workspace/credential isolation between agents in the same project
is solvable without leaking auth across agents; mid-workflow takeover
(a human stepping into an agent's turn) is a demonstrated pattern.

**What it proves hard** (the project's own stated findings, notable because
they're an admission from the tool's own docs rather than marketing):

- **No universal "turn complete" signal** — every provider defines
  turn/session/activation boundaries differently, so CCB needs
  provider-specific mapping logic rather than one abstraction; a would-be
  dual-host daemon should expect the same friction if it tries to unify
  "when is this CLI's turn over" across Claude Code and Codex.
- **Auth isolation is hard** — stopping a managed agent from mutating global
  shell state or another project's credentials is called out as a genuine
  difficulty, not solved trivially.
- **Reliable crash/stale-session recovery** is flagged as unsolved cleanly —
  provider crashes and network failures risk silent data loss or false
  success states.

### MCP-based governance / guardrail proxies (MintMCP and category)

<https://www.mintmcp.com/blog/ai-guardrails-tools-platforms> ·
<https://www.integrate.io/blog/best-mcp-gateways-and-ai-agent-security-tools/>

**What the category abstracts**: rather than embedding guardrail logic
separately inside each CLI (Claude Code, Cursor, Codex, etc.), an **MCP
gateway** sits between agents and tools/connectors as a centralized policy
choke point. MintMCP specifically extends an "Agent Monitor" that watches
"prompts, file access, commands, and MCP tool calls across Claude Code,
Cursor, and other coding agents."

**How**: three layers — (1) a detector for prompt injection / credential
exposure ("Mint Guard"), (2) declarative rules blocking patterns like
filesystem-access scopes or disallowed tool combinations, (3) sandboxed
JS middleware for custom transforms/DLP integration — all applied to every
gateway tool call's arguments *and* results.

**What its existence proves**: the industry's answer to "govern several
different coding-agent CLIs at once" is increasingly to standardize on MCP as
the chokepoint (since, per a second source in this category, "every tool
invocation, regardless of which agent framework called it, traverses the same
JSON-RPC method"), rather than to reimplement hook-level guardrails per CLI.
This is a structurally different strategy from cc-suite's "mirror the native
hook config into each tool" approach and from this project's own
handler-daemon approach (native hooks, per-host). It is evidence that a
**hook-mirroring strategy and an MCP-gateway strategy are the two live
architectural options** for governing multiple agent CLIs, with the MCP
route favoured by enterprise/vendor tooling (because it needs no per-CLI
protocol knowledge — only MCP) and the hook-mirroring route favoured by
project-local OSS tools that want native, protocol-level control (blocking
exit codes, tool-call rewriting) that MCP tool hooks in Codex's own model
explicitly **cannot** do (see Part 1: "MCP tool hooks cannot block").

**Caveat**: none of the MintMCP/Integrate.io material is a primary technical
spec — it's vendor blog content describing product capability, not an
architecture doc with verifiable protocol detail the way the OpenAI hooks
page is. Treat the *category existing* as well-evidenced (multiple
independent vendors converge on "MCP gateway as governance chokepoint") but
treat any specific product claim as marketing until checked against that
vendor's own docs.

### Not investigated in this pass (named in search results, unexplored)

- **Zen MCP Server's `clink` tool** — described in a search hit as a
  "CLI-to-CLI Bridge" (<https://glama.ai/mcp/servers/@BeehiveInnovations/zen-mcp-server/blob/.../clink.md>).
  Not fetched; flagged as a candidate for deeper follow-up if the dual-host
  design wants an MCP-native cross-CLI invocation primitive.
- **Claude Deck's "Agent Bridge"** — discovers/manages local agent CLIs in
  tmux, mixed Claude Code + Codex CLI sessions in one view
  (<https://claudedeck.org/docs/features/agent-bridge>). Not fetched; appears
  adjacent to CCB above (session-layer bridging rather than policy bridging).

---

## Summary table

| Tool/finding | Layer it operates at | Abstracts | Proves possible | Proves hard |
|---|---|---|---|---|
| Codex CLI hooks (official) | native hook protocol | Claude-Code-like stdin/stdout JSON + exit-code-2 blocking | A non-Anthropic CLI adopting a near-identical hook envelope | Full event-set parity (Codex's list is narrower); MCP tool hooks can't block |
| cc-suite | config generation | AGENTS.md/skills/hooks/MCP mirrored across 3 CLIs from one project | Native hook config can be *mechanically translated*, not just conceptually similar | Preventing delegation loops between two independently-running agents |
| claude_codex_bridge (CCB) | terminal/session layer | Many CLIs' turn-taking under one tmux/daemon workspace | Concurrent multi-CLI operation, workspace/credential isolation | No universal "turn complete" signal; crash/stale-session recovery |
| MCP guardrail gateways (MintMCP et al.) | protocol chokepoint | Cross-CLI tool-call policy via the shared MCP JSON-RPC surface | Centralized audit/policy without per-CLI integration work | Cannot block at the same granularity as native PreToolUse hooks (MCP tool hooks are advisory-only per Codex's own docs) |

## Sources

- Plan 00169 dossier: `CLAUDE/Plan/Completed/00169-prior-art-sota-research-and-feature-brainstorm/RESEARCH-FINDINGS.md`, `PLAN.md`
- Codex hooks (official) — <https://developers.openai.com/codex/hooks> (redirects to <https://learn.chatgpt.com/docs/hooks>)
- Codex sandboxing (official, per 00169) — <https://developers.openai.com/codex/concepts/sandboxing>
- Codex approvals/security (official, per 00169) — <https://learn.chatgpt.com/docs/agent-approvals-security>
- Codex approval_policy 2026 changes (third-party, unverified against official changelog) — <https://smartscope.blog/en/generative-ai/chatgpt/codex-cli-approval-policy-implementation/>
- Codex hooks vs Claude Code hooks (third-party) — <https://www.hookstack.app/guides/openai-codex-hooks>
- Claude Code vs Codex 2026 framing (third-party opinion) — <https://blakecrosley.com/blog/claude-code-vs-codex>
- cc-suite — <https://github.com/xiaolai/cc-suite>
- claude_codex_bridge (CCB) — <https://github.com/SeemSeam/claude_codex_bridge>
- MintMCP guardrails — <https://www.mintmcp.com/blog/ai-guardrails-tools-platforms>
- MCP gateway category — <https://www.integrate.io/blog/best-mcp-gateways-and-ai-agent-security-tools/>
- Zen MCP `clink` (unexplored, flagged) — <https://glama.ai/mcp/servers/@BeehiveInnovations/zen-mcp-server/blob/b205d7159b674ce47ebc11af7255d1e3556fff93/docs/tools/clink.md>
- Claude Deck Agent Bridge (unexplored, flagged) — <https://claudedeck.org/docs/features/agent-bridge>
