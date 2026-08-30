# Options: Abstraction Architectures for Dual-Host (Claude Code + Codex CLI)

Plan 00292. Research-only — no code changes. Built from `MAPPING-events.md`
and the four `RESEARCH-*.md` docs in this folder; every claim about the
daemon's own code cites those docs' file/line citations rather than
re-reading source, and every claim about Codex carries the same
corroboration tier those docs already assigned (well-corroborated /
single-source / third-party) — this document does not upgrade anyone's
confidence, it inherits it.

**Reading key for confidence**: a claim marked *(well-corroborated)* or
*(single-source)* is carried verbatim from the mapping/research docs' own
tiering. Where this document draws an architectural conclusion **from**
those facts, that inference is this document's own and is stated as such.

---

## The value proposition this whole plan hinges on, restated

Per `RESEARCH-codex-surface.md` §6 and `MAPPING-events.md`'s summary: Codex
CLI hooks are verdict-based, not notify-only, for `PreToolUse`,
`PermissionRequest`, `PostToolUse`, `UserPromptSubmit`, and `Stop`
*(well-corroborated for `deny`; the `ask`/`allow` details are contested or
unimplemented)*. That is the necessary precondition for any of options A–C
below to deliver something worth the daemon's core selling point —
**blocking, not merely advisory, governance**. Option D and the "not worth
it" case in Option E exist because that precondition is currently only
partially true.

Two gaps sit underneath every option in this paper and are not solved by
architecture choice:

1. **Tool-coverage gap** *(well-corroborated via 3 independent open GitHub
   issues: #19385, #18491, #14882)*: Codex's `PreToolUse`/`PostToolUse` fire
   only for Bash/shell, `apply_patch`, and MCP tool calls today — not
   Edit/Write/Read or hosted tools like WebSearch. Per `MAPPING-events.md`
   Table 1, most of the daemon's PreToolUse-keyed handlers
   (`lint_on_edit`, `qa_suppression`, `security_antipattern`,
   `sensitive_content`, `write_clobber_guard`, `plan_qa_edit`,
   `docs_qa_edit`, …) are gated on Edit/Write and would see **no trigger at
   all** on Codex today, regardless of which abstraction option is chosen.
2. **Event-taxonomy gap**: of the daemon's 31 wired events (32 catalogued
   events total per a direct grep of `constants/events.py` at HEAD; 1,
   `DirectoryAdded`, is `wired=False`), only 6 have any Codex counterpart at
   all (all classified PARTIAL, none clean ONE-TO-ONE), and 21 have no
   Codex counterpart found in any of the four research passes
   (`MAPPING-events.md` summary line). No abstraction layer invents events
   Codex does not emit.

Every option below is therefore bounded by the same ceiling: even a perfect
abstraction cannot make Codex behave like Claude Code where Codex simply
does not expose the surface.

---

## Option A — Host-adapter layer at the daemon front controller

**Shape**: keep one daemon, one handler chain, one internal `HookResult`/
`Decision` model. Add a per-host adapter pair at the boundary:
(1) an **input adapter** that parses a host's wire-format hook JSON into the
daemon's existing `HookInput`/`ToolInput` pydantic models, and (2) an
**output adapter** that serializes the daemon's internal verdict into that
host's specific response shape, replacing `hook_result.py`'s
`_build_wire_response`/`_format_*_response` (~450 lines,
`RESEARCH-daemon-couplings.md` §3) with a per-host equivalent. The shared
handler chain (`front_controller.py`'s `dispatch()` — priority-sorted,
terminal/non-terminal handlers, context accumulation, exception→fail-open,
described as "entirely generic policy-engine machinery with no host
assumptions at all", §4) is untouched and reused verbatim.

**What it can deliver**: every handler keyed on an event class that Codex
also emits, at whatever verdict fidelity Codex supports for that event. Per
`MAPPING-events.md` Table 1, that's real for `UserPromptSubmit` (closest to
ONE-TO-ONE) and for `PreToolUse`/`PostToolUse`/`Stop`/`PermissionRequest`
(PARTIAL, with named gaps: `ask` unsupported on `PreToolUse` per issue
#28437, tool coverage limited to Bash/apply_patch/MCP). This is the option
that preserves the daemon's actual selling point — a shared handler chain
that both hosts feed — for the subset of events where both hosts have
comparable expressive power.

**What it cannot deliver**: nothing for the 21 ABSENT-classified events
(no `StatusLine`, `Setup`, `TaskCreated`, `WorktreeCreate`,
`Elicitation`/`ElicitationResult`, `TeammateIdle`, etc. — Table 1). The
`Status` (status-line) handler family specifically has no host surface on
Codex per `RESEARCH-codex-surface.md` §9/`RESEARCH-codex-lifecycle.md` §9
("no primary-source evidence of a Claude-Code-style configurable status
line was found") — an adapter cannot translate what the other side never
emits. Nor does it resolve the transcript-path question: `TranscriptReader`
consumers (`RESEARCH-daemon-couplings.md` §7 names 9 call sites, including
`auto_continue_stop.py` and `idle_housekeeping_advisor.py`) assume a
filesystem JSONL path handed by the host. Codex's rollout JSONL files
*(single-source, corroborated by 2 GitHub discussions, schema stability
explicitly unconfirmed per an unanswered discussion question, #24042)* are a
plausible substitute, but the daemon's own reported `transcript_path` field
on Codex's wire format may be **summarizer-contamination artifact rather
than genuine**, per the header caveat both `RESEARCH-codex-surface.md` and
`MAPPING-events.md` Table 2's transcript-storage row carry forward
unresolved. An adapter built on an unverified field is a real operational
risk, not a design gap this option can architect around.

**Implementation surface touched**: `core/event.py` (extend `HookInput`
parsing, likely additive given `extra="allow"` already, per §2, "medium"),
`core/hook_result.py` (new serializer module per host, "hard" — this is
where the ~450 lines of Claude-Code-specific JSON shape knowledge lives and
"none of it generalizes", §3), a new event-taxonomy table analogous to
`constants/events.py`'s `EventIDMeta` but for Codex's ~11-event union
(§1, "hard" — "the catalogue cannot simply be parameterised... has to be
duplicated or generalised"), a Codex-side forwarder/registration generator
(§5, "fundamental" as a mechanism — Codex needs its own `.codex/hooks.json`
equivalent to `install.py`'s `create_settings_json()`), and a Codex-side
forwarder script family analogous to `.claude/init.sh`/`.claude/hooks/*`
(§6, "medium" — reuse the socket-plumbing wholesale per Plan 00290's
already-host-agnostic transport, §10, but each host needs its own exit-code
convention and stdin/stdout envelope handling).

**Maintenance cost**: ongoing, and asymmetric to the two hosts' release
cadences. Every time Codex's hook schema shifts — and per
`RESEARCH-codex-surface.md` §1 the event set "grew substantially between
March and June 2026" while still gated behind an experimental flag with no
graduation date confirmed — the output-adapter half needs a compatibility
pass, independent of anything happening on the Claude Code side. This
mirrors the daemon's own existing pattern of Claude-Code-version-specific
workarounds (the `stop_hook_active` Sev-1 loop-guard, the exit-code-2
translation for a named Claude Code v2.1.114 regression, §3/§6) — expect a
second, independent stream of that same maintenance category once Codex is
a live target, not a one-time port cost.

**Failure modes**: (1) an adapter silently mis-serializes a verdict Codex
doesn't actually support the way the source docs claimed — concretely, the
`allow`/`PreToolUse` semantics are reported in **direct tension** between
two sources (tied to `updatedInput` vs. simply rejected,
`RESEARCH-codex-surface.md` §6) and this was not resolved; an adapter built
on the wrong reading either silently drops a rewrite the daemon intended, or
crashes on an unsupported shape. (2) a handler written against the daemon's
host-agnostic `Decision` enum silently degrades to a no-op on Codex because
the specific verdict it needs (`ask`, e.g.) errors out
(`"PreToolUse hook returned unsupported permissionDecision:ask"`,
issue #28437) — this needs to surface as a loud misconfiguration, not a
silent downgrade, or an operator believes a handler is blocking when it
isn't. (3) tool-coverage drift: a handler that worked at build time (Codex
covering Bash-only) silently gains or loses coverage as the open GitHub
issues (#19385/#18491/#14882) land — this needs a version pin and a
recheck cadence, not a "ship and forget" adapter.

---

## Option B — Host-specific forwarder/registration generation only (thin)

**Shape**: do *not* touch the daemon's internal event taxonomy or verdict
model at all. Instead, generate a Codex-compatible `.codex/hooks.json` (or
inline `[hooks]` TOML) from the *existing* `_DAEMON_FORWARDER_HOOKS` table
(`install.py:311-345`, already described as "comparatively easy to swap" —
§5) that points each Codex event Codex actually emits at the *same*
front-controller binary the daemon already ships, unmodified. Rely on the
protocol convergence itself — JSON stdin, exit-code-2 blocking, similar
field names — to do double duty without a translation layer, on the theory
(explicitly corroborated as a working pattern by `cc-suite`'s own approach,
`RESEARCH-prior-art.md` Part 2: it "mirrors the shared hook events from
`.claude/settings.json` into `.codex/hooks.json` so both tools run identical
scripts on the same events") that the wire formats are close enough not to
need a real adapter.

**What it can deliver**: the cheapest possible dual-host story — one
generator script, no new serialization code, ships fast, and it is the
approach an independent third-party OSS tool has *already shipped and
users run*, which is real evidence the mechanical translation is tractable
at the config-generation layer (`RESEARCH-prior-art.md`'s own framing:
"config/hook mirroring across the two tools is tractable enough that a
single OSS plugin does it project-locally").

**What it cannot deliver — and this is the load-bearing weakness of this
option**: `RESEARCH-prior-art.md` itself flags that cc-suite's approach has
**not been verified functionally** (`MAPPING-events.md`'s own open-questions
section: "whether that tool's own event-mirroring has been verified
functionally, not just structurally... worth checking before treating it as
proof the mirroring approach works end-to-end"). More concretely, this
option skips exactly the part of the daemon `RESEARCH-daemon-couplings.md`
identifies as the *largest* concentration of host-specific knowledge:
`hook_result.py`'s per-event wire serialization (§3, "hard", ~450 lines,
explicitly described as needing to be "fully replace[d]" per host, "because
none of it generalizes"). A forwarder that points Codex at the daemon's
existing binary **without** a Codex-aware output serializer will emit
Claude-Code-shaped JSON (`hookSpecificOutput.permissionDecision`,
`stop_hook_active`-guard logic, the `WorktreeCreate` raw-stdout convention,
etc.) that Codex may partially tolerate (given the acknowledged schema
compatibility, `RESEARCH-codex-surface.md` §2) but is not guaranteed to
parse correctly for every event — the two research passes disagree on
`allow` semantics precisely because different Codex versions may already
diverge from the shape this option would emit unmodified. This option is
"thin" because it is betting the daemon's *existing* Claude-Code-shaped
verdict serializer already speaks close-enough Codex, which is an
unverified assumption, not a designed adaptation.

**Implementation surface touched**: a Codex-hooks-manifest generator
paralleling `create_settings_json()` (§5, low effort per the table's own
"easy" per-event-data rating), a `.codex/`-targeted forwarder script
(reusing `init.sh` plumbing per §6). Nothing in `core/event.py` or
`core/hook_result.py` changes.

**Maintenance cost**: lowest of the four active options *if the
protocol-compatibility bet holds*; **unbounded** if it doesn't, because a
silent serialization mismatch is discovered by an operator whose blocking
rule silently didn't block, not by a build-time type error. This is a
materially different risk profile from Option A even though the visible
code diff is smaller.

**Failure modes**: (1) the exact failure named above — a verdict is emitted
in Claude-Code shape and Codex either errors opaquely or, worse, silently
treats it as a no-op/allow (per `RESEARCH-codex-surface.md` §6's own
observation that Codex "genuinely parses and acts on a structured verdict"
and that invalid answers now surface a schema error rather than hanging "as
of" a recent release — meaning older versions may have hung or misbehaved
silently, an open risk this option inherits). (2) config-format drift: any
change to `hooks.json`'s discovery order or matcher shape (§5 of
`RESEARCH-codex-lifecycle.md`) breaks registration with no compile-time
signal, since this option has no schema validation layer of its own — it
just writes files and hopes.

---

## Option C — MCP as the common substrate

**Shape**: instead of speaking each host's native hook protocol, expose the
daemon's policy engine as an **MCP server**, and have both hosts consume it
through their respective MCP-client capability (`RESEARCH-codex-lifecycle.md`
§4: Codex is a confirmed MCP client via `mcp_servers` in `config.toml`,
stdio or Streamable HTTP transport; Claude Code has native MCP client
support too). This is the strategy the guardrail-gateway vendor category
(MintMCP and peers, `RESEARCH-prior-art.md` Part 2) has converged on for
governing multiple coding-agent CLIs at once, on the stated theory that
"every tool invocation, regardless of which agent framework called it,
traverses the same JSON-RPC method" — no per-CLI hook-protocol knowledge
needed, only MCP.

**What it can deliver**: the cleanest *architectural* unification — one
server, one protocol, no per-host adapter code at all for the parts of the
daemon's job that map onto "observe/govern a tool call." It also sidesteps
the summarizer-contamination uncertainty hanging over Codex's *native* hook
schema (§ header caveats throughout `RESEARCH-codex-surface.md` and
`MAPPING-events.md`), since MCP's JSON-RPC shape is independently,
stably documented and not itself in dispute.

**What it cannot deliver — and this is decisive, not incidental**: per
Codex's own hooks documentation (`RESEARCH-prior-art.md` Part 1, corroborated
by `RESEARCH-codex-lifecycle.md` §5's "known limitations"), Codex explicitly
distinguishes **command hooks** from **MCP tool hooks**, and **MCP tool hooks
cannot block** — "their errors don't prevent execution, only command hooks
can." This is stated flatly and is the single fact in this research set most
directly fatal to Option C as a *blocking*-governance strategy: routing the
daemon's core verdict channel through MCP on the Codex side would, per
Codex's own documented model, downgrade every one of the daemon's blocking
handlers to advisory-only — exactly the outcome Option D names separately as
a *fallback*, not something Option C should produce as its primary
architecture. `RESEARCH-prior-art.md`'s own summary table makes the same
point about the MCP-gateway vendor category generally: "Cannot block at the
same granularity as native `PreToolUse` hooks (MCP tool hooks are
advisory-only per Codex's own docs)." Additionally, `RESEARCH-codex-lifecycle.md`
§4 flags that Codex's MCP-server-hosting story itself has an unresolved
detail — `codex mcp-server` is reported (search-synthesis only, not
independently confirmed) as **deprecated** in favor of an "app server"
approach, which if true would move the ground under any Option C design
mid-implementation.

**Implementation surface touched**: an MCP server wrapping the daemon's
existing handler chain (`front_controller.py`'s `dispatch()` is already
generic per §4, which helps here), MCP tool/resource definitions replacing
the event-taxonomy work Options A/B need, and **no** forwarder/registration
generation work at all (both hosts' MCP-client config formats are already
their own solved problem, not the daemon's to reinvent). This is genuinely
the smallest *code* surface of the three active options.

**Maintenance cost**: low for the transport/protocol layer (MCP is stable
and shared), but this option does not remove the event-taxonomy or
verdict-semantics problem — it relocates it into "which MCP tool calls
correspond to which governance decision," which is arguably a harder
mapping problem than the native-hook mapping this research already found
incomplete (21 of 31 wired events ABSENT on native hooks; MCP tool-call semantics
were not researched in this pass at all).

**Failure modes**: the primary one is not a bug but a category error —
building Option C expecting it to preserve blocking power, and discovering
only after significant build-out that Codex's own architecture forecloses
that on the MCP path. A secondary failure mode is protocol churn risk on
the `codex mcp-server`/"app server" transition noted above, which is
unconfirmed but would be expensive to be wrong about mid-build.

---

## Option D — Verdict-degradation mode for notify-only hosts

**Shape**: not a competing architecture to A/B/C but a **required companion
mode** to whichever is chosen, and the mode any host defaults to for the
event classes where blocking genuinely isn't available. When the daemon
detects it's talking to a host/event combination that cannot carry a
blocking verdict — Codex's `Notification` analog (`notify`, confirmed
fire-and-forget, return value never consulted, `RESEARCH-codex-lifecycle.md`
§10), MCP tool hooks under Option C, or `PreToolUse`'s currently-broken
`ask` decision (issue #28437) — it downgrades every handler's verdict to
advisory: log/context-inject the finding instead of denying the action,
consistent with how the daemon's own `REFUSAL_CAPABLE_EVENTS`
(`hook_result.py:99-134`, `RESEARCH-daemon-couplings.md` §3) already handles
the *existing*, Claude-Code-side case of an event that structurally cannot
refuse (e.g. `Status`) — this is not a new concept for the codebase, it's
extending an existing one across the host boundary.

**What it can deliver**: honest, safe behavior instead of either (a) a
silently-dropped verdict (the worst outcome — an operator believes a
security handler blocked something it didn't) or (b) a hard crash on an
unsupported response shape. It also gives partial value on today's actual
Codex tool-coverage gap: even where `PreToolUse`/`PostToolUse` do fire
(Bash/apply_patch/MCP), a handler that would have blocked can still surface
its finding as `additionalContext` (confirmed present on both hosts per
`MAPPING-events.md` Table 2's context-injection row) — visible to the model
and the user, just not enforced.

**What it cannot deliver**: the daemon's actual value proposition, for the
specific handlers and events this mode applies to. This is the option that
makes the honest tradeoff explicit rather than hiding it, and it is a
prerequisite for not shipping something worse than doing nothing.

**Implementation surface touched**: a policy switch inside whichever
serializer Option A or C builds (or, for Option B, this mode cannot be
implemented at all without first building Option A's serializer, since
Option B has no per-event awareness to degrade *from*). Minimal net-new
surface beyond a capability table ("which host/event pairs can carry
`deny`") that has to be kept current against Codex's own actively-changing
support matrix (§1's "grew substantially between March and June 2026").

**Maintenance cost**: low in isolation, but its *correctness* is entirely
dependent on the capability table staying accurate as Codex's hook coverage
expands — the open GitHub issues (#19385/#18491/#14882) mean today's
degradation boundary (Bash/apply_patch/MCP-only enforcement) is a moving
target, not a fixed constant to hardcode once.

**Failure modes**: a stale capability table in either direction — treating
an event as blocking-capable after Codex silently narrowed support (false
confidence, the dangerous direction), or treating an event as advisory-only
after Codex added real blocking support (unnecessary value left on the
table, the safe-but-wasteful direction). Bias the table toward the safe
direction and re-verify on a cadence, not once at build time.

---

## Option E — Not worth it: the honest case against

This is not a straw option. The mapping table gives it real support, and it
deserves to be argued on its own terms rather than folded into a
recommendation as an afterthought.

**The core argument**: strip away corroboration-tier optimism and look at
what's actually confirmed to work *today*, on the daemon's own value
proposition (blocking governance across the handler set that exists):

- Of 31 wired daemon events (32 catalogued events total; 1, `DirectoryAdded`,
  is `wired=False`), only 6 have any Codex analog at all, and
  **zero** are clean ONE-TO-ONE — every one of the 6 carries a named
  semantic gap (`MAPPING-events.md` summary).
- Of those 6, the two with the most daemon handlers riding on them
  (`PreToolUse`, `PostToolUse`) are confirmed to exclude Edit/Write/Read —
  i.e. exactly the tool surface most of this project's actual handler
  catalogue polices (`lint_on_edit`, `qa_suppression`,
  `security_antipattern`, `sensitive_content`, `write_clobber_guard`,
  `plan_qa_edit`, `docs_qa_edit`, `comment_changelog`, `comment_size`,
  `tdd_enforcement`, and more — all gated on Edit/Write per this project's
  own live configuration). A Codex integration that cannot see Edit/Write
  calls governs almost none of what this daemon actually does day to day;
  it would only cover the Bash/apply_patch-keyed handler subset
  (`destructive_git`, `sed_blocker`, `pipe_blocker`,
  `dangerous_permissions`, `curl_pipe_shell`, and similar).
- The entire `status_line` handler family (§8, "hard, host-specific
  feature") has no Codex surface at all, confirmed absent across two
  independent research passes.
- `PreToolUse`'s three-way verdict is only two-thirds implemented on
  Codex (`ask` errors outright, `allow` semantics contested) — the daemon's
  richest decision channel is the one Codex supports least completely.
- The single best-corroborated cross-host fact in the whole research set —
  the shared exit-code-2 convention (`RESEARCH-daemon-couplings.md` §6
  Table row 10-adjacent, `MAPPING-events.md` Table 2) — is itself
  Claude-Code-bug-shaped on the daemon's side (`forward_stop_event()` exists
  *only* to work around a named Claude Code v2.1.114 regression); porting it
  to Codex means porting a workaround for a bug Codex may not have, wasted
  motion in either direction.
- Every credible external precedent for cross-CLI governance
  (`RESEARCH-prior-art.md` Part 2) either doesn't attempt blocking at the
  hook level (MCP gateways — architecturally can't, per Option C's finding)
  or is explicit that its own hook-mirroring hasn't been functionally
  verified (cc-suite).

**What this argues for, if adopted**: not "never support Codex," but
"don't build a general abstraction layer speculatively." The 6 events with
any analog, minus their named gaps, is a small enough surface that the
handlers which *would* actually gain something from Codex support today are
countable — the Bash/git/pipe-safety handler family plus
`UserPromptSubmit`-keyed handlers (`standing_authorisations`,
`idle_housekeeping_advisory`). A narrower, honest scope — "wire the handful
of handlers that have a real Codex trigger point today, skip the general
abstraction, revisit when the tool-coverage GitHub issues land" — may
capture most of the achievable value at a fraction of Option A's
implementation and maintenance cost, without pretending dual-host parity
exists where it doesn't.

**What Option E should not be mistaken for**: an argument that Codex's hook
system is bad or won't mature — the opposite is well-supported (multiple
open GitHub issues actively requesting exactly the parity this plan wants,
a maintainer actively expanding the event set through 2026). It is an
argument about **sequencing**: building a general dual-host abstraction now,
against a moving, partially-documented, single-source-heavy target, risks
building the wrong abstraction and re-doing it once the tool-coverage gap
closes — versus waiting for Codex's `PreToolUse`/`PostToolUse` Edit/Write
coverage to land (the open issues suggest this is plausibly near-term) and
then building Option A against a materially more complete target.

---

## Cross-option comparison

| | A: host-adapter | B: thin forwarder-only | C: MCP substrate | D: degradation mode | E: not now |
|---|---|---|---|---|---|
| Preserves blocking where Codex supports it | Yes | Yes, if the protocol-compatibility bet holds (unverified) | **No** — MCP tool hooks cannot block, per Codex's own docs | N/A (companion mode) | N/A (deferred) |
| Covers `status_line` | No (no Codex surface exists) | No | No | No | No |
| Covers Edit/Write-keyed handlers | No (Codex gap, not architecture) | No | Unclear — not researched | No | No |
| New code surface | Largest (§3's ~450 lines duplicated per host + taxonomy table) | Smallest of the active options | Small (MCP wrapper) but relocates the mapping problem | Small, but depends on A or C existing first | None |
| Depends on unverified claims | `transcript_path` field genuineness; `allow` semantics | Whether Claude-Code-shaped JSON is tolerated unmodified by Codex | `codex mcp-server` deprecation status | Codex's actual current support matrix | — |
| External precedent | None found (novel) | cc-suite (unverified functionally) | MCP guardrail-gateway vendor category (advisory-only precedent) | Daemon's own `REFUSAL_CAPABLE_EVENTS` (existing internal pattern) | cc-suite's own hedging, this research's own findings |
| Maintenance shape | Ongoing, symmetric dual-host version churn | Low if bet holds; unbounded risk if not | Low for transport; unresolved for mapping | Low, contingent on capability-table freshness | Zero (no build) |

---

## Recommendation

**Build toward Option A, gated behind Option D, but do not start now.**
Reasoning, drawn directly from the evidence above rather than a general
preference:

1. Option C is foreclosed as a *primary* strategy by Codex's own documented
   architecture (MCP tool hooks cannot block) — it should not be pursued as
   the main path, though it remains worth a second look purely as a
   **complementary, non-blocking observability channel** (audit logging,
   cross-host visibility) alongside whichever of A/B is chosen, since that
   is exactly the role the MCP-gateway vendor category already validated.
2. Option B's cost savings are real but rest on an unverified bet (whether
   Claude-Code-shaped JSON is Codex-tolerant unmodified) that the research
   could not resolve either way — the daemon's own contradictory sources on
   `allow` semantics make this a live, not hypothetical, risk. Treat Option
   B as a **prototype/spike** to empirically test that bet (cheap, fast,
   throwaway-safe) before committing to Option A's larger build — not as
   the shipped architecture.
3. Option A is the only path that actually protects the daemon's value
   proposition for the events where Codex genuinely supports blocking, and
   its cost is concentrated in already-identified files
   (`core/event.py`, `core/hook_result.py`, `constants/events.py`,
   `install.py`, a new `.codex/` forwarder family) rather than being
   open-ended.
4. Option D is not optional — whichever of A/B/C is chosen, ship the
   degradation mode alongside it from day one. Silently dropping a verdict
   is the single worst outcome this research surfaces, and the codebase
   already has the internal vocabulary (`REFUSAL_CAPABLE_EVENTS`) to extend
   rather than invent.
5. Option E's sequencing argument is strong enough that **the honest
   default, absent a business reason to move now, is to wait** for the
   tool-coverage GitHub issues (#19385, #18491, #14882) to resolve one way
   or the other before starting Option A's build — building against
   Bash/apply_patch/MCP-only coverage today means re-doing the
   `HookInput`/`ToolInput` adapter work once Edit/Write coverage lands,
   which multiple open issues suggest is plausibly near-term but is not
   confirmed to have a date.

## Decision points that belong to the owner

These are not this document's to resolve — each is a genuine judgment call
requiring owner priorities this research cannot supply:

1. **Timing**: build now against a partially-documented, actively-changing
   target (Option A/B started today), or wait for the tool-coverage gap to
   close (Option E's sequencing argument) — and if waiting, what signal
   should trigger re-evaluation (a specific GitHub issue closing, a Codex
   version number, a fixed calendar check-in)?
2. **Scope ambition**: a full general abstraction layer (Option A, built to
   cover whatever Codex supports as it grows) versus a narrow, named subset
   of handlers wired directly against Codex's *current* confirmed surface
   (Option E's counter-proposal) — the latter is smaller and correct today,
   the former is more future-proof but riskier to build against moving
   ground.
3. **Risk tolerance for the unverified claims**: is the project willing to
   ship Option B as a spike (cheap, but built on an unconfirmed
   protocol-compatibility bet) to get empirical signal fast, or does the
   project want to insist on raw-source/curl-verified schema facts (per
   both surface docs' own recommendation) before writing any adapter code
   at all?
4. **Whether Option C's non-blocking value is worth pursuing in parallel**
   — a read-only audit/observability MCP layer across both hosts has real
   precedent and doesn't compete for the same implementation slot as
   Option A, but is genuinely separate scope the owner may or may not want
   funded alongside the blocking-governance work.
5. **How much of the daemon's Claude-Code-specific technical debt to port
   versus leave behind** — concretely, whether the `stop_hook_active`
   loop-guard and the exit-code-2 `forward_stop_event()` workaround (both
   confirmed to exist solely because of named Claude Code regressions) get
   copied to the Codex forwarder defensively, or whether the project
   accepts the risk of *not* having them and adds them only if Codex is
   later found to have an equivalent bug — copying defensively costs
   nothing to build but muddies the codebase with workarounds for a bug
   that may not exist on the other host.
6. **What "done" means for this plan's continuation**: whether the next
   step (if any) is a design plan for Option A/B's build, a narrowly-scoped
   implementation plan for Option E's handler subset, or a follow-up
   research pass specifically aimed at resolving the open questions this
   paper inherited unresolved (raw-source schema verification, the
   `codex mcp-server` deprecation status, current tool-coverage as of
   whenever the owner reads this).
