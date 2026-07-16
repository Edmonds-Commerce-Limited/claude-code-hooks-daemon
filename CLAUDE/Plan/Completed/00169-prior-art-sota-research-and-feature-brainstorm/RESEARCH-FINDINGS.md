# Plan 00169 — Research Findings (Prior Art & SOTA)

Consolidated, deduped, sourced synthesis of five parallel research angles
(July 2026). Each section preserves the source URLs. Companion docs:
[GAP-ANALYSIS.md](GAP-ANALYSIS.md) maps these ideas to our handler set;
[FEATURE-BACKLOG.md](FEATURE-BACKLOG.md) ranks the resulting candidate features.

**Scope reminder**: research + ideation only. Nothing here ships from this plan;
survivors graduate into their own implementation plans.

---

## 0. Headline takeaways (the convergent signal)

Five independent angles kept landing on the same handful of themes. Ranked by how
many angles independently surfaced them:

1. **Secret / `.env` protection is our biggest single security gap** — flagged by
   both the community-hooks angle and the policy angle. We block destructive
   *actions* but do nothing to stop an agent reading `.env`/SSH keys or leaking a
   credential into output/commits.
2. **OS sandboxing is the leap from blocklist to deny-by-default** — string
   pattern-matching (what all our PreToolUse blockers do) is a fundamentally
   weaker guarantee than kernel-enforced isolation. Anthropic moved Claude Code
   onto bubblewrap/Seatbelt and cut permission prompts 84%.
3. **The hook layer is a uniquely rich observability vantage** — we see every
   tool call, every guardrail decision *and its reason*. Native Claude Code OTEL
   only records `source: hook`. Guardrail-block analytics + a session scorecard
   are features nobody else can build as well.
4. **allow / ask / deny with glob precedence is the industry-standard permission
   vocabulary** — opencode, Cursor, Codex, Cline, Roo all converged on it;
   allowlist-first beats denylist (Cursor's denylist was shown routable).
5. **Shadow-git per-turn checkpointing** (revert *code* while keeping *context*)
   is the universal "make it reversible" pattern (Cline, Roo, pi-rewind) and our
   clearest capability gap — we *block* destructive git instead of making actions
   undoable.
6. **Context hygiene should be continuous, not a late red-line `/compact`** — SOTA
   clears stale tool *results* early (~30k-token thresholds) and forces a
   save-to-memory before any lossy compaction.
7. **We are already ahead of upstream on auto-resume** — our recovery-cron solves
   what Claude Code users are still filing feature requests for; the native
   `StopFailure` event is a cleaner primitive to build it on.

---

## 1. Community Claude Code hooks (angle: research-hooks)

**What people actually build.** The most common community hooks cluster into:
secrets protection, catastrophic-bash guards, branch/test protection, auto-format/
test-on-save, git auto-stage/checkpoint, outbound notifications, and event-stream
logging/dashboards.

**Concrete ideas worth stealing (gaps in our set):**

- **Secret/`.env` read blocker** — PreToolUse on Read/Edit/Write/Bash denying
  `.env`, SSH keys, AWS creds, `secrets/**`; pair dynamic-hook + deny permission
  rule. <https://www.morphllm.com/claude-code-hooks> ·
  <https://scottspence.com/posts/nopeek-keep-secrets-out-of-claude-code>
- **Output secret scanner** — PostToolUse scans `tool_output` and redacts via
  `updatedToolOutput` before Claude/commits see it.
  <https://github.com/FlorianBruniaux/claude-code-ultimate-guide>
- **CLAUDE.md prompt-injection scan** at SessionStart/InstructionsLoaded.
  <https://www.claudedirectory.org/for/security>
- **Protect-tests** — block edits/deletes of test files so the model can't "pass"
  by deleting the red test. <https://github.com/karanb192/claude-code-hooks>
- **Branch guard**, **auto-checkpoint before risky ops**, **auto-stage**,
  **subagent spawn-budget (PreToolUse:Task)**.
  <https://blakecrosley.com/blog/claude-code-hooks> ·
  <https://karanbansal.in/blog/claude-code-hooks/>
- **Outbound notifications** (Slack/Discord/ntfy/desktop/TTS) on Notification/Stop.
  <https://github.com/disler/claude-code-hooks-mastery>
- **Per-session cost/token logger**, **event-stream dashboard**.
  <https://github.com/disler/claude-code-hooks-multi-agent-observability>
- Novel plugin ideas: `context-hogs`, `dead-rules-audit`, `pr-provenance-stamp`.
  <https://github.com/karanb192/claude-code-hooks>

**Official hook spec — capabilities we may be underusing** (the spec now documents
~31 events, far beyond the classic five). Source: <https://code.claude.com/docs/en/hooks>

- **`StopFailure`** with matchers `rate_limit` / `overloaded` /
  `authentication_failed` / `billing_error` / `max_output_tokens` — a *native*
  trigger for exactly what our recovery-cron polls for.
- **`updatedInput`** (PreToolUse) — rewrite tool args before execution: auto-inject
  `--comments` on `gh pr view`, normalise relative→absolute paths — instead of
  blocking and forcing a retry.
- **`updatedToolOutput`** (PostToolUse) — redact/replace a result before Claude
  sees it.
- **`async` / `asyncRewake`**, **PermissionRequest `permissionRulesToAdd`**
  (learn allow-rules), **`permissionDecision: "defer"`**, **PostToolBatch** (fires
  after a parallel batch — relevant to our batched-cancellation footgun),
  **TaskCreated/TaskCompleted**, **TeammateIdle**, **ConfigChange**,
  **FileChanged/`watchPaths`**, **InstructionsLoaded** (which guidance actually
  loads — feeds a dead-rules audit), **MessageDisplay**, **PostCompact**,
  **WorktreeCreate/Remove**.

Sources: <https://code.claude.com/docs/en/hooks> ·
<https://github.com/hesreallyhim/awesome-claude-code> ·
<https://github.com/karanb192/claude-code-hooks> ·
<https://github.com/disler/claude-code-hooks-mastery> ·
<https://github.com/ColeMurray/claude-code-otel> ·
<https://www.ayautomate.com/blog/best-claude-code-hooks>

---

## 2. Adjacent agentic-CLI guardrails (angle: research-clis)

**Per-tool highlights:**

- **Codex CLI** — the richest model: a **two-axis matrix** of `sandbox_mode`
  (`read-only` / `workspace-write` / `danger-full-access`) × `approval_policy`
  (`untrusted` / `on-request` / `never`), OS-enforced; protected paths
  (`.git`/`.codex`/`.agents`) stay read-only; network opt-in with domain
  allowlisting; a **second-LLM `auto_review`** classifies exfiltration/credential/
  destructive risk before a human is asked. TOML profiles; reads AGENTS.md.
  <https://developers.openai.com/codex/concepts/sandboxing> ·
  <https://learn.chatgpt.com/docs/agent-approvals-security>
- **Gemini CLI** — approval ladder (`default`/`auto_edit`/`yolo`/`plan`) + Seatbelt
  profiles + Docker/Podman/LXC sandboxing; `safeTools` per-command allowlist.
  <https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/sandbox.md>
- **Aider** — weak blocking, strong workflow: `CONVENTIONS.md` rules, auto-commit
  every edit (git = safety net), **auto-lint/auto-test loops that feed errors back
  to the model to self-fix**. <https://aider.chat/docs/usage/lint-test.html>
- **opencode** — clean declarative **allow/ask/deny** with glob command matching
  (last-match-wins), per-tool + per-agent scoping; reads CLAUDE.md.
  <https://opencode.ai/docs/permissions/>
- **Cursor** — `.cursor/rules/*.mdc` (glob-scoped, progressive) + CLI capability
  permissions (`Shell(git)`, `Read(...)`, `Write(...)`, deny-takes-precedence).
  Backslash documented the **auto-run denylist is bypassable** — argues
  allowlist-first. <https://cursor.com/docs/cli/reference/permissions> ·
  <https://www.backslash.security/blog/cursor-ai-security-flaw-autorun-denylist>
- **Windsurf** — `.windsurf/rules/` + **Workflows** (`/workflow-name` codified
  procedures). <https://docs.windsurf.com/windsurf/cascade/workflows>
- **Cline / Roo** — per-capability auto-approve menu, **request cap** (N calls
  before re-approval), **command allow+deny lists**, and **shadow-git checkpoints**
  after every tool call. Roo's open issue #11095: prefix matching is "inherently
  unsafe", pushing for exact-command matching. <https://docs.cline.bot/features/auto-approve>
  · <https://github.com/RooCodeInc/Roo-Code/issues/11095>
- **AGENTS.md** — schema-free markdown rules standard, read by 30+ tools, donated
  to the Linux Foundation's Agentic AI Foundation; the *lingua franca* for agent
  instructions. <https://www.iuriio.com/blog/posts/2026/05/agents-md-field-guide-2026>

**Cross-cutting patterns:** three-state allow/ask/deny; glob/prefix matching with
precedence; allowlist-first > denylist; sandbox tiers decoupled from approval
policy; protected-path carve-outs; shadow-git checkpoints; path-scoped progressive
rules; codified workflows as slash commands; post-edit lint/test self-fix loops;
request/iteration caps; second-LLM risk reviewer.

---

## 3. Policy engines, sandboxing & LLM guardrails (angle: research-policy)

**Policy expression.** OPA/Rego (general, powerful, steep, governance-uncertain
after Apple acquired the maintainers) vs AWS **Cedar** (authz-only, formally
verified, 42–60× faster, embeddable Rust crate). **Verdict for us:** our matchers
do *imperative, fuzzy* shell-string work that policy engines (built for structured
`principal/action/resource` authz) fit poorly. Realistic move is a **hybrid** —
keep Python matchers, externalise the *decision + config* (patterns on/off,
severities, exempt paths, allow/deny lists) into a validated declarative document
(we already do much of this in YAML). Full Rego/Cedar migration = low ROI.
<https://www.cedarpolicy.com/> · <https://www.osohq.com/learn/opa-vs-cedar-vs-zanzibar>

**Sandboxing (the most important finding).** String-blocking is deny-by-blocklist;
sandboxing is deny-by-default OS enforcement that *also constrains child processes
we can't see* (the `npm install` → postinstall → `curl` chain). Mechanisms: macOS
**Seatbelt** (`sandbox-exec`), Linux **bubblewrap**, **Landlock** (self-confinement,
no root/namespaces), **seccomp** (defence-in-depth). Claude Code ships
bubblewrap+Seatbelt with a **network proxy enforcing an allowed-domain list** —
this is how it stops credential/SSH exfil — and reports isolation "safely reduces
permission prompts by 84%". <https://www.anthropic.com/engineering/claude-code-sandboxing>
· <https://code.claude.com/docs/en/sandboxing> ·
<https://docs.kernel.org/userspace-api/landlock.html>

**Secret & supply-chain scanning.** Replace hand-rolled regex with **Gitleaks**
(fast, offline, entropy+regex — ideal for edit/commit-time blocking) at the edge +
**TruffleHog** (live-verifies credentials) on a schedule; **Socket.dev**-style
behavioural dependency analysis catches malicious/typosquat packages *before* a CVE
exists (npm attacks tripled 2022–2025). <https://rafter.so/blog/secrets/gitleaks-vs-trufflehog>
· <https://appsecsanta.com/socket>

**LLM I/O guardrails.** NeMo Guardrails (dialog rails), Guardrails AI (validator
hub), Llama Guard (classifier), **Presidio** (PII detect/redact). Most guard model
*tokens* we don't sit on; the transferable pieces are **PII/secret detection on
file writes** and **prompt-injection awareness**. Framing: our daemon is a
*deterministic guardrail layer at the tool boundary* — the tool-call analogue of
LLM Guard. <https://github.com/microsoft/presidio> ·
<https://guardrailsai.com>

**Prompt-injection defence.** The **Lethal Trifecta** (Simon Willison): danger =
private-data access + untrusted-content exposure + external communication; break one
leg. **Spotlighting** (Microsoft) delimits/encodes untrusted content as opaque data.
**Dual-LLM/CaMeL** (DeepMind) is the strongest architectural defence but *unshipped*
anywhere in 2026. Sobering: a joint OpenAI/Anthropic/DeepMind study found every
published prompt-level defence bypassed >90% under adaptive attack — which is why
**OS sandboxing that breaks the "external communication" leg is the durable
control.** <https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/> ·
<https://learn.microsoft.com/en-us/security/zero-trust/sfi/defend-indirect-prompt-injection>

---

## 4. Agent observability, telemetry & eval (angle: research-observability)

**Standards.** OpenTelemetry **GenAI semantic conventions** are the cross-vendor
standard: `execute_tool` span (maps 1:1 to our PreToolUse/PostToolUse pair),
`gen_ai.tool.name`, `gen_ai.client.operation.duration`, `gen_ai.client.token.usage`.
Naming our tool spans this way makes them ingestible by Phoenix/Langfuse/Datadog for
free. <https://techbytes.app/posts/opentelemetry-genai-agent-semconv-cheat-sheet-2026/>

**Claude Code native OTEL (opt-in, `CLAUDE_CODE_ENABLE_TELEMETRY=1`)** already emits
metrics (`session.count`, `lines_of_code.count`, `cost.usage`, `token.usage`,
`code_edit_tool.decision`, `active_time.total`) and events (`user_prompt`,
`api_request`, `api_error`, `tool_result`, **`tool_decision`** — but only coarse
`source: hook` — `compaction` with pre/post tokens, `hook_execution_*`). **We should
consume, not duplicate, cost/token; and we uniquely know *which* handler blocked and
*why*.** <https://code.claude.com/docs/en/monitoring-usage.md> ·
<https://github.com/ColeMurray/claude-code-otel>

**Platforms' transferable vocabulary.** Langfuse (self-hostable eval primitives),
LangSmith (**trajectory replay + state-diff** — the gem), **Arize Phoenix** (runs
entirely local, no cloud, attaches eval scores back onto traces — the north star for
a privacy-respecting local tool), Braintrust (regression detection). A thriving
**local JSONL-reading ecosystem** already exists (ccusage, claude-session-dashboard,
claude-code-karma, Stop-hook usage dashboards) — proving demand for exactly our
architecture. <https://arize.com/phoenix/> · <https://ccusage.com/> ·
<https://www.toriihq.com/articles/five-claude-code-usage-dashboards-and-monitoring-tools>

**Local-friendly metrics we can compute from events we already see** (all pure
metadata — no prompt/response content needed, matching the privacy-respecting
ethos): tool-call histogram, tool success/error rate (we already classify Bash
errors), per-tool latency, **guardrail-block analytics (unique to us)**,
block→retry-recovery rate, edit/revert code-turnover, time-to-green, test pass rate,
compaction frequency/pressure (we own PreCompact + a context sidecar), subagent
fan-out (already logged), session scorecard, **test-gaming detection**.

---

## 5. Context, memory, checkpoint & orchestration safety (angle: research-context)

**Context/compaction.** The field's vocabulary is *write / select / compress /
isolate*; the enemy is **context rot** (accuracy degrades as tokens accumulate even
when all info is present). SOTA is **continuous, automatic clearing of stale tool
results** (Anthropic `clear_tool_uses_20250919`: trigger ~30k tokens, keep last 3,
cache-friendly; measured +29% alone, +39% with memory, 84% token cut on a 100-turn
eval) — with heavy compaction as a *fallback*, tuned for recall-first. Sub-agents
isolate context and return **1–2k-token distilled summaries**.
<https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents>
· <https://claude.com/blog/context-management>

**Memory.** MemGPT/Letta (tiered core/recall/archival, agent self-pages), Mem0
(extract→consolidate→retrieve), Anthropic **memory tool** (`memory_20250818` — a
directory of files Claude CRUDs, with an *automatic warning to save before a
clearing pass*). Our CLAUDE.md/plan-journal pattern is the deterministic,
git-diffable, auditable end — a strength for a *coding* agent.
<https://rywalker.com/research/letta> · <https://www.anthropic.com/engineering/advanced-tool-use>

**Checkpoint/resume/rewind (our clearest gap).** Ecosystem standardised on
**shadow-git snapshots** (Cline commits file state to a *separate* shadow repo after
every tool use; restore reverts *code* while keeping *conversation/context*) and
**worktree-per-task**. Claude Code has `/rewind`; pi-rewind adds a redo stack.
<https://docs.cline.bot/core-workflows/checkpoints> · <https://github.com/arpagon/pi-rewind>

**Orchestration/autonomy safety.** Anthropic orchestrator-worker uses explicit
objectives + **max-iteration + wall-clock caps**; token usage explains ~80% of eval
variance; multi-agent shines on parallel research, is poor for tightly-coupled
coding. **Runaway cost is the headline failure** (a documented loop cost $47K). The
emerging consensus: **hard per-agent AND per-workflow budgets, circuit breakers that
HALT not retry, graduated 80/90/100% limiting**. Microsoft **Conductor** pulls
control flow into a deterministic engine so non-determinism is bounded to leaf steps.
**We are ahead of upstream on auto-resume** (open Claude Code issues #62788/#36320
still request what our recovery-cron does).
<https://www.anthropic.com/engineering/multi-agent-research-system> ·
<https://dev.to/ricmmartins/budget-enforcement-for-multi-agent-llm-systems-without-a-proxy-3i7n>
· <https://github.com/anthropics/claude-code/issues/62788>

---

## 6. Genuinely novel angles (not obvious in prior art)

Ideas that fall out of *combining* the above with our specific vantage — not seen
packaged anywhere:

- **The daemon as its own eval harness.** Block→escape-hatch/override correlation
  (§4) lets the daemon *measure whether its own guardrails help or annoy* and
  auto-flag false-positive-prone handlers. No other tool has the block-reason data
  to do this.
- **Dead-guidance audit** via `InstructionsLoaded` telemetry — find `.claude/rules/*`
  and CLAUDE.md sections that never actually load/trigger, to prune our (large)
  guidance surface. Directly useful for *this* repo.
- **Cross-tool guardrail daemon.** AGENTS.md interop + reading other tools' event
  formats could reposition the daemon from "Claude Code hooks" to "the guardrail
  layer for any agentic CLI." Strategic reframe.
- **"Deterministic tool-boundary guardrail layer" product framing** — a
  validator-registry (like Guardrails Hub) built on our existing Strategy/registry
  patterns, so new guards plug in as data.

---

## 7. Master source list

All URLs above are the primary references; the five per-angle reports (preserved in
the plan JOURNAL) carry the complete lists. Highest-authority anchors:

- Claude Code hooks spec — <https://code.claude.com/docs/en/hooks>
- Claude Code sandboxing — <https://www.anthropic.com/engineering/claude-code-sandboxing> · <https://code.claude.com/docs/en/sandboxing>
- Claude Code monitoring/OTEL — <https://code.claude.com/docs/en/monitoring-usage.md>
- Context engineering — <https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents> · <https://claude.com/blog/context-management>
- Multi-agent system — <https://www.anthropic.com/engineering/multi-agent-research-system>
- Lethal trifecta — <https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/>
- Cedar vs OPA — <https://www.cedarpolicy.com/> · <https://www.osohq.com/learn/opa-vs-cedar-vs-zanzibar>
- Gitleaks vs TruffleHog — <https://rafter.so/blog/secrets/gitleaks-vs-trufflehog>
- Socket.dev — <https://appsecsanta.com/socket>
- Arize Phoenix — <https://arize.com/phoenix/>
- OTEL GenAI semconv — <https://techbytes.app/posts/opentelemetry-genai-agent-semconv-cheat-sheet-2026/>
- Cline checkpoints — <https://docs.cline.bot/core-workflows/checkpoints>
- opencode permissions — <https://opencode.ai/docs/permissions/>
- Codex sandboxing — <https://developers.openai.com/codex/concepts/sandboxing>
- AGENTS.md — <https://www.iuriio.com/blog/posts/2026/05/agents-md-field-guide-2026>
