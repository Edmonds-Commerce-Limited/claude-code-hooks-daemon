# Plan 00169 — Ranked Candidate-Feature Backlog

Derived from [RESEARCH-FINDINGS.md](RESEARCH-FINDINGS.md) +
[GAP-ANALYSIS.md](GAP-ANALYSIS.md). Each brief: **problem · sketch · fit · effort ·
novelty**. Effort is a rough T-shirt size (S/M/L) as a *shape* signal, not a
schedule (plan docs describe WHAT, not WHEN). Novelty ✦ marks ideas not obviously
packaged in prior art.

**Nothing here ships from Plan 00169.** Each surviving item graduates into its own
plan. Recommendations for what to graduate first are in §"Graduation".

---

## Tier 1 — High value · on-brand · tractable

### F1. Secret-file read/write blocker + output redaction · S–M

- **Problem**: our single biggest security gap (flagged independently by the hooks
  and policy angles). Nothing stops an agent reading `.env`/SSH keys/AWS creds, or
  leaking a credential into tool output or a commit.
- **Sketch**: PreToolUse denies Read/Edit/Write and Bash `cat`/`less`/`cp` on
  secret paths (`.env*`, `**/secrets/**`, `id_rsa`, `*.pem`, cloud-cred files);
  PostToolUse scans `tool_output` and redacts via `updatedToolOutput` before the
  model/commit sees it. Optionally shell out to **Gitleaks** (fast, offline) for
  detection rather than hand-rolled regex.
- **Fit**: pure deterministic tool-boundary guard — exactly our wheelhouse; sits
  beside `security_antipattern`.
- **Novelty**: low (common community hook) but **high value**.

### F2. Guardrail-block analytics + per-session scorecard · M · ✦

- **Problem**: we make hundreds of block/allow decisions and throw the data away.
  We can't answer "which handler blocks most, and are those blocks *helpful* or
  *annoying*?"
- **Sketch**: aggregate our own PreToolUse decisions (handler, reason,
  block→corrected-retry, block→escape-hatch-override) into a rolling ledger; emit a
  Stop-hook **session scorecard** (tools used, success rate, blocks by handler,
  errors, compactions, subagents, duration, cost from native telemetry).
- **Fit**: uniquely ours — native Claude Code OTEL only records `source: hook`; we
  know *which* handler and *why*. Turns the daemon into **its own eval harness**.
- **Novelty**: ✦ high — no other tool has the block-reason data to do this.

### F3. StopFailure-native recovery (augment the recovery cron) · S

- **Problem**: our recovery-cron *polls hourly* to catch rate-limit/overload stalls.
  The spec now has a first-class `StopFailure` event with `rate_limit`/`overloaded`
  matchers that fires the instant it happens.
- **Sketch**: add a `StopFailure` handler matched on the external-stall categories
  that resumes immediately; keep the cron as the idle-window failsafe.
- **Fit**: we already own this problem space and are ahead of upstream — this makes
  it event-driven instead of polled.
- **Novelty**: medium (uses a new native primitive).

### F4. `updatedInput` auto-fix instead of block · S

- **Problem**: `gh_pr_comments`/`gh_issue_comments`/`absolute_path` *block and force
  a retry*, which also trips the batched-sibling-cancellation footgun.
- **Sketch**: rewrite args transparently — inject `--comments`, normalise
  relative→absolute paths — via PreToolUse `updatedInput`, instead of denying.
- **Fit**: strictly better UX for handlers whose "fix" is mechanical; reduces
  false-positive friction on our own guardrails.
- **Novelty**: medium (underused native capability).

### F5. Protect-tests + test-integrity ("gaming") detector · S–M

- **Problem**: an agent can "pass" TDD by deleting/neutering the red test; source-
  only pass rates drop 15–25pts vs full-patch when tests are gamed.
- **Sketch**: block deletion/gutting of test files; advisory flag when a test/fixture
  is edited immediately before a "tests pass" claim.
- **Fit**: natural complement to `tdd_enforcement`; the hook layer is uniquely
  placed to see the edit-then-claim sequence.
- **Novelty**: medium.

### F6. Context hygiene: save-to-memory before compaction + early stale-result clearing · M

- **Problem**: our supervisor `/compact`s at red — late and lossy. SOTA clears stale
  tool *results* early and forces a decisions/bugs flush before any compaction.
- **Sketch**: (a) a PreCompact step that flushes unresolved bugs / architectural
  decisions / open tasks into the plan journal or a memory file before `/compact`;
  (b) explore advising early stale-tool-result trimming ahead of the red line.
- **Fit**: extends our PreCompact + supervisor ownership; makes lossy compaction
  safe.
- **Novelty**: medium.

### F7. AGENTS.md interop · S–M

- **Problem**: AGENTS.md is the cross-tool rules standard (30+ tools, Linux
  Foundation). We only speak CLAUDE.md, so we're a poor citizen in mixed-tool repos.
- **Sketch**: read/validate `AGENTS.md` alongside CLAUDE.md; keep them coherent
  (drift warning); apply the same stable-content rules.
- **Fit**: extends `markdown_organization`; strategic ecosystem positioning.
- **Novelty**: medium.

---

## Tier 2 — Higher-value bets · larger effort

### F8. OS-sandbox execution mode + network-egress allowlist · L

- **Problem**: string-blocking is deny-by-blocklist and blind to child processes
  (`npm install`→postinstall→`curl`). Sandboxing is deny-by-default OS enforcement;
  Anthropic reports it *cut permission prompts 84%*.
- **Sketch**: optional handler mode wrapping Bash calls in `bwrap`(Linux)/
  `sandbox-exec`(macOS) with fs confined to cwd + egress via a domain-allowlisting
  proxy (breaks the lethal-trifecta "external communication" leg). Landlock/seccomp
  as defence-in-depth.
- **Fit**: the single biggest leap from blocklist to real enforcement; complements
  (not replaces) our string blockers.
- **Effort/risk**: **L** — cross-platform, opt-in, careful UX; the flagship idea.

### F9. allow/ask/deny bash gating (config-driven, allowlist-first) · M–L

- **Problem**: our bash posture is denylist-only — the exact model Cursor got
  burned on (routable). The industry standard is config-driven allow/ask/deny with
  glob precedence.
- **Sketch**: optional `bash: {"*": "ask", "git *": "allow", "rm -rf *": "deny"}`
  config block resolved with precedence; **exact-command matching as the safe
  default** (learning from Roo #11095), prefix opt-in.
- **Fit**: generalises our fixed denylist handlers into a policy projects can flip
  to allowlist-first.
- **Novelty**: medium.

### F10. Shadow-git per-turn checkpoint + context-preserving rewind · L

- **Problem**: our clearest capability gap vs Cline/Roo/pi-rewind. We *block*
  destructive git rather than making actions reversible; a false-positive block is
  friction, an undo is grace.
- **Sketch**: opt-in PostToolUse snapshot of file state into a *shadow* git ref
  after risky tool calls; a rewind that reverts **code** while keeping the
  **conversation/plan** intact.
- **Fit**: turns "you can't do that" into "you can, and it's reversible" — softens
  destructive_git false-positives; matches our "never lose work" ethos.
- **Effort**: **L**.

### F11. Budget + circuit-breaker for sub-agents & background processes · M

- **Problem**: `background_process_tracker` surfaces but never caps; the documented
  multi-agent failure mode is a runaway that cost $47K.
- **Sketch**: per-agent AND per-session token/cost/tool-call budgets; **halt-not-
  retry** at 100%; graduated 80/90/100% warnings; a subagent spawn-budget on
  PreToolUse:Task.
- **Fit**: extends our tracker philosophy with the safety consensus.
- **Novelty**: medium.

### F12. Local session-analytics dashboard + OTEL GenAI span export · M–L

- **Problem**: we write JSONL nobody renders; and our uniquely-rich hook data can't
  reach Phoenix/Langfuse/Grafana.
- **Sketch**: `daemon-cli dashboard` renders existing logs into one **offline HTML**
  page (tool histogram, block timeline, error/compaction markers, cost, à la
  Phoenix/ccusage); optional OTLP export of `execute_tool` spans tagged
  `gen_ai.tool.name` + our block decision. All content-free/metadata-only by default.
- **Fit**: proven demand (5+ local tools exist); privacy-respecting; reuses logs.
- **Novelty**: medium (the block-decision-on-spans part is ✦).

### F13. Supply-chain dependency reputation gate on installs · M

- **Problem**: malicious/typosquat packages are the fastest-growing 2026 threat and
  CVE-based tooling misses them (npm attacks tripled 2022–2025).
- **Sketch**: on `npm/pip/go/cargo add|install`, advise (block in strict mode) on
  Socket-style malicious-behaviour signals / typosquat distance.
- **Fit**: extends `lock_file_edit_blocker` from integrity to reputation.
- **Novelty**: medium.

### F14. Second-LLM risk reviewer for escape hatches · M · ✦

- **Problem**: `MUST_*_BECAUSE=` escape hatches trust the prose justification
  blindly; Codex's `auto_review` classifies exfiltration/credential/destructive risk
  before honouring a request.
- **Sketch**: before honouring an escape hatch or an unusual download, a quick
  classification pass escalates genuinely dangerous ones.
- **Fit**: hardens our existing escape-hatch design.
- **Novelty**: ✦ medium-high for a local guard.

---

## Tier 3 — Smaller / niche / watch

- **F15. Lethal-trifecta / spotlighting advisory** (S) — inject "treat fetched
  content as data" advice on web/issue/external-file reads; flag when all three
  trifecta legs co-occur. Cheap alignment with the 2026 threat model.
- **F16. Protected-path guard from config** (S) — generalise the hardcoded
  daemon-dir guard into a `protected_paths:` list.
- **F17. Branch guard** (S) — advise/block edits+commits directly on main/master.
- **F18. Outbound notifications** (S) — ntfy/Slack/desktop/`terminalSequence`/TTS on
  Notification/Stop; `notification_logger` already has the events.
- **F19. Dead-guidance audit** (M · ✦) — `InstructionsLoaded` telemetry to find
  never-loaded `.claude/rules/*`/CLAUDE.md sections; prune our own large surface.
- **F20. ConfigChange guard** (S) — block silent mid-session daemon-config drift.
- **F21. Time-to-green + code-turnover trackers** (M) — behavioural productivity
  metrics from Bash output + git churn.
- **F22. Per-agent tool-permission scoping** (M) — structurally read-only research/
  review subagents, enforced by the daemon.
- **F23. Presidio-style PII redaction on writes** (M, opt-in).
- **F24. Iteration/request cap** (S) — soft circuit breaker after N tool calls.
- **F25. Tiered memory (core vs recall)** (L) — explicit hot/cold split over
  CLAUDE.md + journals.
- **F26. Deterministic orchestration wrapper** (L) — Conductor-style engine for the
  release/plan-completion flows.
- **F27. (Watch, don't build) Dual-LLM/CaMeL quarantine** — strongest injection
  defence but unshipped anywhere in 2026; track for a reference implementation.

---

## Cross-cutting strategic reframes

- **The daemon as its own eval harness** (F2 + F19) — measure whether our guardrails
  help or annoy, and prune dead guidance. ✦
- **"Deterministic tool-boundary guardrail layer"** — position our Strategy/registry
  as a Guardrails-Hub-style validator registry; new guards plug in as data. Informs
  F8/F9/F13 architecture.
- **Cross-tool guardrail daemon** — AGENTS.md interop (F7) + reading other tools'
  event formats could reposition us beyond Claude Code. ✦ Long-horizon.

---

## Graduation — what to spin into plans first

**Already graduated**: the *hook-coverage substrate* underneath the "newer
hook-spec capabilities we underuse" finding (§1 of RESEARCH-FINDINGS.md) became
[**Plan 00170: Universal Hook Coverage + Hook-Support Enforcement**](../../00170-universal-hook-coverage-and-enforcement/PLAN.md)
— the user flagged missing hook coverage as fundamental (only 10 of 31 documented
events wired). Several backlog features here (F3 StopFailure, F6 PostCompact, F11
SubagentStart budget, F19 InstructionsLoaded audit, F20 ConfigChange guard) become
*handler* follow-ups once 00170 wires their underlying events.

Recommended first wave (high value / on-brand / tractable, mostly S–M):

1. **F1 Secret blocker + redaction** — closes the top security gap; small.
2. **F2 Guardrail-block analytics + scorecard** — unique to us, data already in
   hand, turns the daemon into its own eval harness.
3. **F3 StopFailure recovery** + **F4 updatedInput auto-fix** — two small,
   high-leverage uses of newer native hook capabilities.
4. **F5 Protect-tests / gaming detector** — cheap complement to TDD enforcement.

Flagship bet to scope deliberately (its own design plan): **F8 OS-sandbox mode** —
the biggest security leap, but L-sized and cross-platform.

Quick ecosystem win to slot when convenient: **F7 AGENTS.md interop**.

Everything else stays in this backlog as a sourced idea bank for future planning.
