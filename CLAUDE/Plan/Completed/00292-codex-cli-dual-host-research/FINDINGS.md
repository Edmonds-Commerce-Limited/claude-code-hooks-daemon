# FINDINGS: Dual-Host Support (Claude Code + Codex CLI) — Executive Synthesis

Plan 00292. Research-only — no code changes. This document leads with the
answer; depth and citations live in the five linked supporting documents.

## 1. TL;DR

**Can the daemon support Codex CLI today, and at what fidelity? Partially,
and at low fidelity relative to the daemon's actual handler catalogue.**

Codex CLI has a genuine, verdict-based (not merely notify-only) hooks system,
confirmed by official docs and corroborated by a live GitHub issue
(`openai/codex#28437`) and third-party sources
([RESEARCH-codex-surface.md §6](RESEARCH-codex-surface.md#6-can-a-hook-blockdeny-an-action-or-is-it-notify-only--blocking-exists-with-a-live-gap)).
`deny` is confirmed enforced, at differing corroboration strength, across
`PreToolUse`, `PostToolUse`, `PermissionRequest`, `UserPromptSubmit`, and
`Stop` — but only `PreToolUse`'s `deny` carries the strongest tier (three
independent fetches); `PostToolUse`, `PermissionRequest`, `UserPromptSubmit`
and `Stop`'s `decision:block` behavior are each reported via a single
docs-page fetch only, per
[RESEARCH-codex-surface.md §6](RESEARCH-codex-surface.md#6-can-a-hook-blockdeny-an-action-or-is-it-notify-only--blocking-exists-with-a-live-gap)
and preserved as **PARTIAL** (never "confirmed") in
[MAPPING-events.md, Table 1](MAPPING-events.md#table-1--event-by-event-mapping).
That is the necessary precondition for anything in this plan to be worth
building, but it rests on single-source corroboration for four of the five
events.

But two gaps sit under every option and bound the ceiling regardless of
architecture
([OPTIONS-abstraction.md, "the value proposition" section](OPTIONS-abstraction.md#the-value-proposition-this-whole-plan-hinges-on-restated)):

1. **Tool-coverage gap**: Codex's `PreToolUse`/`PostToolUse` fire only for
   Bash/shell, `apply_patch`, and MCP tool calls today — **not**
   Edit/Write/Read or hosted tools like WebSearch (well-corroborated via
   three independent open GitHub issues: #19385, #18491, #14882). Most of
   this daemon's actual handler catalogue is gated on Edit/Write
   (`lint_on_edit`, `qa_suppression`, `security_antipattern`,
   `sensitive_content`, `write_clobber_guard`, `plan_qa_edit`,
   `docs_qa_edit`, `comment_changelog`, `comment_size`, `tdd_enforcement`,
   and more) — **none of these would fire on Codex today.**
2. **Event-taxonomy gap**: of the daemon's 31 wired events (32 catalogued
   events total, per a direct grep of `constants/events.py` at HEAD; only
   `DirectoryAdded` is `wired=False`), only 6 have any Codex counterpart at
   all, and **none are clean one-to-one** once verdict-completeness and
   tool-coverage gaps are counted — 21 events have no Codex analog found in
   any of four independent research passes
   ([MAPPING-events.md, Table 1 summary](MAPPING-events.md#table-1--event-by-event-mapping)).

What *would* work today, at real fidelity: the Bash/git/pipe-safety handler
family (`destructive_git`, `sed_blocker`, `pipe_blocker`,
`dangerous_permissions`, `curl_pipe_shell`, and similar) plus
`UserPromptSubmit`-keyed handlers (`standing_authorisations`,
`idle_housekeeping_advisory`) — the closest-to-one-to-one event, and the one
event family least exposed to the Edit/Write coverage gap.

**A large caveat on the evidence itself**: almost every Codex-side fact in
this research was obtained via `WebFetch`'s summarizing model, not a raw
byte-exact fetch, and Codex's hooks are an *acknowledged, deliberate
near-port* of Claude Code's own schema — meaning a contaminated summary and
a genuinely accurate one would look identical. This uncertainty is not
resolved anywhere in this research set
([RESEARCH-codex-surface.md header caveat](RESEARCH-codex-surface.md); [MAPPING-events.md, "Uncertainty carried forward"](MAPPING-events.md#uncertainty-carried-forward-not-resolved-by-this-mapping)).

## 2. What is possible now vs. what Codex CLI would need to add

**Possible now, if built:**

- A host-adapter layer could deliver real blocking governance for
  `PreToolUse`/`PostToolUse`/`Stop`/`PermissionRequest`/`UserPromptSubmit` —
  but only for the tool surface Codex currently intercepts (Bash/apply_patch/MCP).
- `SessionStart` context injection maps cleanly enough conceptually
  (`AGENTS.md` ≈ `CLAUDE.md`), already relied on in production by a
  third-party OSS tool (`cc-suite`) that treats the two as interchangeable
  ([RESEARCH-prior-art.md, cc-suite](RESEARCH-prior-art.md#cc-suite-xiaolaicc-suite)).
- The exit-code-2-blocking convention (`0`=success, `2`=blocking+stderr
  reason) is the single best-corroborated cross-host structural fact in the
  whole research set — three independent sources agree
  ([MAPPING-events.md, Table 2](MAPPING-events.md#table-2--non-event-surfaces)).
- Plan 00290's per-event socket relay transport is already host-agnostic — a
  pure byte pump with zero Claude-Code-specific knowledge — and would very
  likely work unmodified as the IPC layer for a Codex forwarder family
  ([RESEARCH-daemon-couplings.md §10](RESEARCH-daemon-couplings.md#10-plan-00290s-per-event-socket-relay--host-agnostic-transport-in-favour-of-abstraction)).

**What Codex CLI itself would need to add or confirm before dual-host parity
is meaningful:**

- **Edit/Write/Read tool-call interception** on `PreToolUse`/`PostToolUse` —
  the single highest-leverage gap; three open GitHub issues are tracking
  exactly this (#19385, #18491, #14882).
- **`ask` support on `PreToolUse`'s `permissionDecision`** — currently
  errors outright (`"unsupported permissionDecision:ask"`), tracked in a
  live, well-sourced issue, #28437.
- **Resolved `allow` semantics** — two sources are in direct, unresolved
  tension (tied to `updatedInput` vs. simply rejected).
- **A status-line-equivalent surface** — no primary-source evidence found of
  anything like Claude Code's configurable status line; the entire
  `status_line` handler family has nowhere to run on Codex regardless of
  architecture.
- **Confirmed rollout-JSONL schema stability** across Codex versions — an
  official-repo GitHub discussion asking this went unanswered.
- Graduation of hooks out of experimental/beta status (no graduation date
  found; the event set "grew substantially" between March and June 2026
  while still gated behind a feature flag).

Full event-by-event and non-event-surface detail:
[MAPPING-events.md](MAPPING-events.md).

## 3. Recommended path and rationale

**Build toward Option A (host-adapter layer), gated behind Option D
(verdict-degradation mode for non-blocking-capable host/event pairs), but
do not start now.** Full option definitions, trade-offs, and a
cross-option comparison table: [OPTIONS-abstraction.md](OPTIONS-abstraction.md#recommendation).

Rationale, in order of weight:

1. **Option C (MCP as the common substrate) is foreclosed as a primary
   strategy** — Codex's own docs state flatly that MCP tool hooks cannot
   block ("their errors don't prevent execution, only command hooks can").
   Routing the daemon's core verdict channel through MCP would downgrade
   every blocking handler to advisory-only on Codex, the opposite of the
   daemon's purpose. It remains worth a look as a **complementary,
   non-blocking observability channel** only — a role already validated by
   the MCP guardrail-gateway vendor category (MintMCP and peers).
2. **Option B (thin forwarder generation, no adapter)** is the cheapest
   path and has real precedent (`cc-suite` ships this today), but rests on
   an *unverified* bet — that Claude-Code-shaped JSON is tolerated
   unmodified by Codex — which the research could not resolve either way,
   and which `cc-suite`'s own approach has not been verified to work
   functionally (only structurally). Treat it as a cheap, throwaway-safe
   **spike** to get empirical signal, not the shipped architecture.
3. **Option A is the only path that protects the daemon's actual value
   proposition** — blocking governance — for the event/tool combinations
   Codex genuinely supports today, and its implementation surface is
   already concentrated in named, known files (`core/event.py`,
   `core/hook_result.py`, `constants/events.py`, `install.py`, a new
   `.codex/` forwarder family) rather than open-ended.
4. **Option D is not optional, regardless of which of A/B/C is chosen.**
   Silently dropping a verdict — a handler an operator believes is blocking
   when it is actually a no-op on Codex — is the single worst outcome this
   research surfaces. The codebase already has the internal vocabulary to
   extend (`REFUSAL_CAPABLE_EVENTS`) rather than invent new machinery.
5. **The sequencing argument (Option E) is strong enough that the honest
   default is to wait** — building Option A today against
   Bash/apply_patch/MCP-only coverage means redoing the adapter once
   Edit/Write coverage lands, which multiple open GitHub issues suggest is
   plausibly near-term but has no confirmed date. Absent a business reason
   to move now, wait for a concrete trigger signal (see open questions
   below) before starting the build.

## 4. Open questions for the owner

These are judgment calls this research cannot resolve on its own — see
[OPTIONS-abstraction.md, "Decision points that belong to the owner"](OPTIONS-abstraction.md#decision-points-that-belong-to-the-owner)
for full framing of each:

1. **Timing** — build now against a partially-documented, actively-changing
   target, or wait for the tool-coverage gap to close? If waiting, what
   should trigger re-evaluation (a specific GitHub issue closing, a Codex
   version number, a fixed calendar check-in)?
2. **Scope ambition** — a full general abstraction layer (Option A, built
   to grow with Codex) versus a narrow, named subset of handlers wired
   directly against Codex's current confirmed surface (Option E's
   counter-proposal, e.g. the Bash/git/pipe-safety handlers plus
   `UserPromptSubmit`-keyed handlers)?
3. **Risk tolerance for unverified claims** — is shipping Option B as a
   cheap spike acceptable, or does the project want raw-source/curl-verified
   schema facts before writing any adapter code at all (neither research
   pass had `curl`/`gh` access to Codex's raw docs/source)?
4. **Is Option C's non-blocking value worth pursuing in parallel** — a
   read-only audit/observability MCP layer across both hosts, funded
   separately from the blocking-governance work?
5. **How much of the daemon's Claude-Code-specific technical debt to port**
   — e.g. should the `stop_hook_active` loop-guard and the exit-code-2
   `forward_stop_event()` workaround (both exist solely because of named
   Claude Code regressions) be copied defensively to the Codex forwarder, or
   only added if Codex is later found to have an equivalent bug?
6. **What "done" means for any continuation** — a design plan for Option
   A/B's build, a narrowly-scoped implementation plan for Option E's
   handler subset, or a follow-up research pass aimed specifically at
   resolving this research's open questions (raw-source schema
   verification, `codex mcp-server` deprecation status, current
   tool-coverage as of whenever the owner reads this)?
7. **Is the daemon's internal `HookResult`/`Decision` model actually
   host-neutral?** Option A's adapter design explicitly assumes
   `HookResult`'s internal `Decision` enum and event-agnostic fields
   (`context`/`guidance`) are sufficient as a genuinely host-neutral
   internal model. Both
   [RESEARCH-daemon-couplings.md](RESEARCH-daemon-couplings.md#open-questions)
   and
   [MAPPING-events.md, "Open questions specific to this mapping"](MAPPING-events.md#open-questions-specific-to-this-mapping)
   raise this independently and neither resolves it — whether a second
   host's hook contract (Codex's `ask`-unsupported gap, command-hook-vs-MCP-
   tool-hook distinction) would surface concepts this enum cannot express is
   unassessed. This bears directly on whether Option A's core premise is
   sound and should be settled before committing to that architecture.
8. **Windows support status is unconfirmed and unaddressed by any option
   above.** Whether Codex hooks are disabled on Windows is reported only via
   a search snippet, not independently confirmed
   ([RESEARCH-codex-surface.md §1, §8](RESEARCH-codex-surface.md); also
   listed as an open question in
   [RESEARCH-codex-lifecycle.md](RESEARCH-codex-lifecycle.md#open-questions)).
   Any team running the daemon cross-platform needs this resolved before
   relying on a Codex adapter on Windows.
9. **Does Codex have a tracked-vs-per-developer local config split** —
   anything resembling Claude Code's `settings.json`/`settings.local.json`
   separation? Not investigated by either research pass
   ([RESEARCH-codex-lifecycle.md, open questions](RESEARCH-codex-lifecycle.md#open-questions)).
   This bears directly on whether a dual-host installer can preserve the
   daemon's tracked-vs-local settings separation on the Codex side.

Additionally, the research itself carries forward several **unresolved
factual questions** that any implementation should re-verify before relying
on them — full list in
[MAPPING-events.md, "Uncertainty carried forward"](MAPPING-events.md#uncertainty-carried-forward-not-resolved-by-this-mapping):
whether `transcript_path` genuinely appears on Codex's wire format or is
summarizer contamination; the exact `PreToolUse` `allow` semantics; whether
issue #28437 (`ask` unsupported) has since shipped; how `approval_policy`
composes with the `PermissionRequest` hook event; the exact feature-flag key
gating hooks; whether hooks have exited experimental status; rollout
JSONL schema stability across Codex versions; a docs disagreement on the
exact `history.persistence` enum (`"save-all"`/`"none"` vs. a looser
boolean-like description elsewhere) that
[RESEARCH-codex-lifecycle.md](RESEARCH-codex-lifecycle.md#open-questions)
flags as needing a direct re-fetch; and whether `approval_policy`'s
`"untrusted"` value is still current — as of this research's 2026-08-30
fetch date, one single third-party source (smartscope.blog) claims it was
retired in `v0.149.0` (dated 2026-08-20, only 10 days prior), while
`RESEARCH-codex-lifecycle.md` §3's official-docs source lists it as a plain
current value with no caveat; neither claim was re-verified against an
official OpenAI changelog, so treat this as unresolved rather than
defaulting to either source.

## 5. Supporting documents

| Document | Contents |
|---|---|
| [RESEARCH-codex-surface.md](RESEARCH-codex-surface.md) | Codex CLI's hooks/extension surface: event taxonomy, config format, blocking-vs-notify-only evidence, source-tier caveats |
| [RESEARCH-codex-lifecycle.md](RESEARCH-codex-lifecycle.md) | Codex CLI configuration, execution modes, sandbox/approval model, MCP client/server support, session/transcript storage, `AGENTS.md`, notifications |
| [RESEARCH-daemon-couplings.md](RESEARCH-daemon-couplings.md) | This repo's Claude-Code couplings ranked easy/medium/hard/fundamental: event catalogue, `HookInput` models, verdict/wire contract, front controller, settings.json registration, transcript-path assumptions, status line, Plan 00290's transport layer |
| [RESEARCH-prior-art.md](RESEARCH-prior-art.md) | Plan 00169's earlier Codex analysis revisited; ecosystem tools that already bridge multiple agent CLIs (`cc-suite`, `claude_codex_bridge`, MCP guardrail gateways) |
| [MAPPING-events.md](MAPPING-events.md) | Event-by-event mapping table (one-to-one / partial / absent) for all 32 catalogued daemon events (31 wired, 1 — `DirectoryAdded` — `wired=False`) plus non-event surfaces (registration, context injection, status line, transcript storage, exit-code convention, transport) |
| [OPTIONS-abstraction.md](OPTIONS-abstraction.md) | Five abstraction options (host-adapter, thin forwarder, MCP substrate, degradation mode, not-now) with trade-offs, cross-option comparison, recommendation, owner decision points |
