# Mapping: Daemon-Wired Hook Events → Codex CLI Counterparts

Plan 00292. Research-only — no code changes. Built from the four sibling
research docs (`RESEARCH-codex-surface.md`, `RESEARCH-codex-lifecycle.md`,
`RESEARCH-daemon-couplings.md`, `RESEARCH-prior-art.md`) plus a direct read of
`src/claude_code_hooks_daemon/constants/events.py` at HEAD (read-only, to get
the exact wired-event inventory rather than relying on the coupling doc's
prose examples).

**Classification legend**

- **ONE-TO-ONE** — Codex has a same-named-or-equivalent event at the same
  point in the lifecycle, with comparable expressive power (can carry a
  verdict/blocking decision if the daemon event can).
- **PARTIAL** — Codex has *something* at roughly this point, but semantics,
  scope, tool coverage, or blocking power differ in a named way.
- **ABSENT** — no Codex counterpart was found in any of the four research
  passes; what Codex would need to add is named.

**Corroboration tiering carried forward from the source docs** (do not treat
these as equally reliable): a Codex event/fact is "**well-corroborated**"
when 2+ independent-ish sources agree (docs page + GitHub issue/discussion,
or docs page + third-party article), "**single-source**" when only one fetch
of one docs page reported it. Per `RESEARCH-codex-surface.md`'s own header
caveat, **all Codex findings were obtained via `WebFetch`'s summarizing
model**, which is plausibly contaminated by its own training knowledge of
Claude Code's near-identical schema — no raw/byte-exact JSON was
independently confirmed for anything below. That uncertainty is not resolved
here; it is carried into every row that depends on it.

**Daemon inventory used**: `constants/events.py` at HEAD declares 32
catalogued `json_key=` events (verified by direct grep at HEAD); 31 are
`wired=True` (end-to-end: forwarder + settings + dispatch + schema) and 1
(`directory_added` / `DirectoryAdded`) is catalogued but **not** currently
wired (`wired=False`, Plan 00271). All 32 are listed below for
completeness, with the unwired one flagged.

---

## Table 1 — Event-by-event mapping

| Daemon event (`json_key`) | `can_block` | Codex counterpart | Class | Notes / gap |
|---|---|---|---|---|
| **PreToolUse** | Yes | `PreToolUse` (well-corroborated: docs page, GitHub issue #28437, third-party) | **PARTIAL** | Blocking exists (`permissionDecision`) but is only two-thirds implemented: `deny` confirmed enforced (3 independent fetches); `ask` explicitly **unsupported** as of issue #28437 (opened 2026-06-16, errors `"unsupported permissionDecision:ask"`); `allow` semantics contested between sources (tied to `updatedInput` vs. simply rejected — unresolved). **Bigger gap**: Codex's `PreToolUse`/`PostToolUse` are reported to fire **only for Bash/shell, `apply_patch`, and MCP tool calls** — NOT for Edit/Write/Read or hosted tools like WebSearch (`RESEARCH-codex-lifecycle.md` §5, citing open issues [#19385](https://github.com/openai/codex/issues/19385), [#18491](https://github.com/openai/codex/issues/18491), [#14882](https://github.com/openai/codex/issues/14882)). The daemon's own `PreToolUse` fires for the full Claude Code tool vocabulary (Bash/Read/Write/Edit/Glob/Grep/…), so most of the daemon's PreToolUse-keyed handlers (`lint_on_edit`, `qa_suppression`, `security_antipattern`, `sensitive_content`, `write_clobber_guard`, `plan_qa_edit`, `docs_qa_edit`, etc. — all gated on Edit/Write) would see **no equivalent trigger on Codex today**. |
| **PostToolUse** | Yes | `PostToolUse` (well-corroborated) | **PARTIAL** | `decision: "block"` + `reason` reported to work (feedback only, cannot undo an already-completed action) — same shape as Claude Code's own `PostToolUse` semantics per the lifecycle doc. Same Bash/apply_patch/MCP-only tool-coverage gap as PreToolUse above; daemon handlers keyed on Write/Edit (`markdown_table_formatter`, `goal_injection`, `recovery_cron_advisor` progress-detection) have no trigger on Codex today for non-Bash/MCP tools. |
| **SessionStart** | No | `SessionStart` (well-corroborated: docs page, maintainer comment naming it the *first-ever* hooks event in v0.114, third-party snippet) | **ONE-TO-ONE** (with a scope caveat) | Same point in the lifecycle (session begin), non-blocking, can push `additionalContext` on both hosts. Codex's matcher takes `startup\|resume\|clear\|compact` values — a scope granularity the daemon's `SessionStart` doesn't expose in the same way; treat as a shape difference rather than a power gap. |
| **SessionEnd** | No | `SessionEnd` (single-source: one docs-page fetch only) | **PARTIAL** | Exists per the one source that reported it, but not independently corroborated a second way — flagged in `RESEARCH-codex-surface.md` §3 as possible summarizer contamination from Claude Code's own event list. If real, it carries a documented constraint the daemon's `SessionEnd` does not: Codex `SessionEnd` hooks always run **synchronously**, default timeout 1s, max 3s (`RESEARCH-codex-lifecycle.md` §5) — a much tighter budget than anything documented for the daemon side. |
| **Stop** | Yes | `Stop` (well-corroborated: docs page, maintainer comment — *second-ever* event alongside `SessionStart` in v0.114, third-party snippet) | **PARTIAL** | Blocking (`decision:"block"` + required `reason`) is well corroborated, and Codex reportedly shares the exit-code-2-as-alternative-blocking convention. Gap: the daemon's `Stop` handling carries a **documented Claude-Code-version-specific workaround** — a `stop_hook_active` loop-guard keyed to a named "Sev-1 shipped in v3.31.0" regression, plus `.claude/init.sh`'s `forward_stop_event()` translating JSON verdicts into process exit code 2 because Claude Code v2.1.114 was found to silently demote JSON-stdout `decision:block`. No source in this research set confirms or denies whether Codex has an equivalent stop-loop-reentry bug or field; this is an **open question**, not a confirmed absence. |
| **SubagentStop** | Yes | `SubagentStop` (single-source: docs page only, grouped with `Stop` under "decision:block + reason for refusing/forcing continuation") | **PARTIAL** | Reported to exist and to share `Stop`'s blocking shape, but on the weaker single-source tier — treat the blocking claim for *this specific* event as inherited-by-association from `Stop`'s better corroboration, not independently confirmed. |
| **UserPromptSubmit** | Yes | `UserPromptSubmit` (well-corroborated: docs page, third-party snippet) | **ONE-TO-ONE** (best match after Stop/PreToolUse) | `decision:"block"` + `reason` to refuse a prompt is reported directly analogous to Claude Code's own `UserPromptSubmit`. This is the event the daemon's `standing_authorisations` and `idle_housekeeping_advisory` handlers key on; both would have a real trigger point on Codex if this corroboration holds, though the exact wire payload is still unconfirmed byte-for-byte (see header caveat). |
| **PreCompact** | Yes | `PreCompact` (single-source: docs page only, though corroborated on the config-shape side by a second fetch — `manual\|auto` matcher confirmed twice) | **PARTIAL** | Event existence and matcher shape reasonably solid (2 fetches agree on the matcher), but the *event list itself* (including PreCompact) rests on a single docs-page fetch per `RESEARCH-codex-surface.md` §3's own tiering — flagged as a possible summarizer-contamination risk since Claude Code has exactly this PreCompact/PostCompact pair. |
| **Notification** | No | No dedicated hooks-system event; closest analog is `notify` (config.toml key, **not** part of `hooks.json`) | **PARTIAL** | Both are non-blocking (`can_block=False` on the daemon side; Codex's `notify` is explicitly fire-and-forget, return value never consulted). But `notify` is architecturally a **separate, older mechanism that predates general hooks** (existed before v0.114 per maintainer `etraut-openai`'s 2025-11-30 comment) and is reported to fire on only one event, `"agent-turn-complete"` — narrower than whatever triggers the daemon's `Notification` event. One source claims Codex additionally ignores project-level `notify` config for security reasons, honoring only user-level `~/.codex/config.toml` — single-source, unverified. |
| **PermissionRequest** | Yes | `PermissionRequest` (well-corroborated: docs page, GitHub issue #28437, third-party snippet) | **ONE-TO-ONE** (structurally) | Reported shape `{"decision":{"behavior":"allow"\|"deny","message":"..."}}` with "any deny wins" when multiple hooks fire — structurally close to the daemon's own nested `decision.behavior` PermissionRequest response, including a comparable "multiple opinions, most restrictive wins" idea. **Open question carried forward unresolved**: no source in either research pass explains how Codex's separate, coarser `approval_policy` (`on-request`/`never`/`untrusted`\*/granular, enforced at the same pre-execution checkpoint per `RESEARCH-codex-lifecycle.md` §3) composes with the `PermissionRequest` hook event — does one pre-empt the other, or do they layer? \*`untrusted` is reported — **as of this research's 2026-08-30 fetch date, single third-party source (smartscope.blog) only, unconfirmed against an official OpenAI changelog** — to have been retired in `v0.149.0` (dated 2026-08-20, i.e. only 10 days before this research) in favor of `on-request`/`never`. Treat this as an unverified, recent, single-source claim, not a settled fact — `RESEARCH-codex-lifecycle.md` §3 lists `untrusted` as a plain current value with no such caveat, which is itself a cross-document gap (see that document's own header note added during the Plan 00292 repair pass). |
| **StatusLine** (`status_line`, `raw_stdout=True`) | No | No equivalent found | **ABSENT** | `RESEARCH-codex-lifecycle.md` §9 explicitly states "no primary-source evidence of a Claude-Code-style configurable status line" was found. `tui.notifications` exists but is a different, narrower in-TUI notification feature, not a persistent scriptable status line — flagged as its own open question in that doc (worth one more targeted fetch before concluding absence is final). Codex would need to add a raw-text, host-rendered status surface with an equivalent hook trigger for the daemon's `status_line/*` handler family to have anywhere to run. |
| **Setup** | No | No distinct "Setup" event found in any Codex event list fetched | **ABSENT** (uncertain) | None of the four research docs' Codex event-list fetches (surface doc's table, lifecycle doc §5, prior-art doc) list a `Setup` event. Codex's `SessionStart` matcher does include a `startup` value, which *may* cover overlapping ground conceptually, but nothing confirms it carries the same semantics as Claude Code's separate `Setup` event — treat as absent rather than assume the matcher value substitutes for it. |
| **UserPromptExpansion** | Yes | No equivalent found | **ABSENT** | Not present in any fetched Codex event list. |
| **PermissionDenied** | No | No equivalent found | **ABSENT** | Codex expresses denial via the `PreToolUse`/`PermissionRequest` response itself (`permissionDecision:"deny"`), not via a distinct post-denial notification event — no source describes a separate `PermissionDenied` trigger. |
| **PostToolUseFailure** | Yes | No equivalent found | **ABSENT** | Not present in any fetched Codex event list; Codex's `PostToolUse` payload is reported to include a `tool_response` field but no distinct failure-triggered event was found. |
| **PostToolBatch** | Yes | No equivalent found | **ABSENT** | Not present in any fetched Codex event list. |
| **MessageDisplay** | No | No equivalent found | **ABSENT** | Not present in any fetched Codex event list. |
| **SubagentStart** | No | `SubagentStart` (single-source: docs page only) | **PARTIAL** | Reported to exist at "thread/subagent-start scope," alongside `SessionStart`, but on the weaker single-source corroboration tier per the surface doc's own tiering — same contamination-risk flag as `SessionEnd`/`PreCompact`. |
| **TaskCreated** | Yes | No equivalent found | **ABSENT** | Not present in any fetched Codex event list. |
| **TaskCompleted** | Yes (expresses refusal via `continue:false`) | No hooks-system equivalent; thematically closest is `notify`'s `"agent-turn-complete"` trigger | **ABSENT** (as a hook) | `notify`'s one confirmed trigger, `agent-turn-complete`, is conceptually adjacent to "a task completed," but it is the separate, non-blocking, fire-and-forget `notify` mechanism (see `Notification` row above) — not a hooks-system event with a `continue:false`-style verdict channel. No Codex hooks-system analog to a *blocking* task-completion event was found. |
| **StopFailure** | No | No equivalent found | **ABSENT** | Not present in any fetched Codex event list. |
| **TeammateIdle** | Yes (expresses refusal via `continue:false`) | No equivalent found | **ABSENT** | `RESEARCH-daemon-couplings.md`'s own open questions flag this as possibly Claude-Code/MCP-multi-agent-specific with no general analogue; nothing in the Codex research corroborates a team/multi-agent-idle concept. |
| **InstructionsLoaded** | No | No hook-event equivalent; conceptually covered by Codex's non-hook `AGENTS.md` auto-load | **ABSENT** (as an event) | Codex injects `AGENTS.md` on the first turn automatically (bounded by `project_doc_max_bytes`), which is the closest *concept* match, but this is plain context injection, not a hookable event carrying a verdict — see Table 2's "Context injection" row for the fuller comparison. |
| **ConfigChange** | Yes | No equivalent found | **ABSENT** | Not present in any fetched Codex event list. |
| **CwdChanged** | No | No equivalent found | **ABSENT** | Not present in any fetched Codex event list. |
| **DirectoryAdded** | No (`wired=False` on the daemon side — catalogued but not currently wired end-to-end, Plan 00271) | No equivalent found | **ABSENT** | Lowest-priority row: the daemon itself does not wire this event yet, and no Codex analog was found either. |
| **FileChanged** | No | No equivalent found | **ABSENT** | Not present in any fetched Codex event list; `RESEARCH-prior-art.md` explicitly names `FileChanged`/`watchPaths` as one of the events Claude Code has that Codex's list does not. |
| **WorktreeCreate** (`raw_stdout=True`) | Yes | No equivalent found | **ABSENT** | No worktree/branch-creation hook concept surfaced anywhere in the Codex research. Codex would need both the underlying worktree-creation feature and a hook trigger for it. |
| **WorktreeRemove** | No | No equivalent found | **ABSENT** | Same as above. |
| **PostCompact** | No | `PostCompact` (single-source: docs page only) | **PARTIAL** | Same single-source/contamination-risk caveat as `PreCompact`; if real, reported to pair with `PreCompact` under the same `manual\|auto` matcher scope. |
| **Elicitation** | Yes | No equivalent found | **ABSENT** | No MCP-elicitation-specific hook event found in the Codex research, despite Codex also being an MCP client/server (`RESEARCH-codex-lifecycle.md` §4). One third-party snippet claims Codex normalizes `PreToolUse` into a shared `PermissionRequest` route, but nothing describes an elicitation-specific event or field. |
| **ElicitationResult** | Yes | No equivalent found | **ABSENT** | Same as above. |

**Summary**: of the daemon's 31 wired events (32 catalogued events total, 1 of which — `DirectoryAdded` — is `wired=False`), 6 have well- or reasonably-corroborated Codex counterparts at the same lifecycle point (`PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`, `UserPromptSubmit`, `PermissionRequest` — all **PARTIAL**, none clean **ONE-TO-ONE** once tool-coverage and verdict-completeness gaps are counted, though `UserPromptSubmit` and `PermissionRequest` come closest), 5 more have single-source/weakly-corroborated Codex counterparts (`SessionEnd`, `SubagentStop`, `PreCompact`, `SubagentStart`, `PostCompact`), and the remaining 21 (`Notification`, `StatusLine`, `Setup`, `UserPromptExpansion`, `PermissionDenied`, `PostToolUseFailure`, `PostToolBatch`, `MessageDisplay`, `TaskCreated`, `TaskCompleted`, `StopFailure`, `TeammateIdle`, `InstructionsLoaded`, `ConfigChange`, `CwdChanged`, `DirectoryAdded`, `FileChanged`, `WorktreeCreate`, `WorktreeRemove`, `Elicitation`, `ElicitationResult` — including the one currently-unwired `DirectoryAdded`) have **no Codex counterpart found in any of the four research passes** (6+5+21=32, matching the total catalogued-event count above) — Codex's own official event list is markedly narrower than Claude Code's, a gap `RESEARCH-prior-art.md` names directly ("Claude Code has more events... that Codex's list above does not include").

---

## Table 2 — Non-event surfaces

| Daemon/Claude-Code surface | Codex counterpart | Class | Notes |
|---|---|---|---|
| **Hook registration** (`.claude/settings.json`, `hooks` object keyed by PascalCase event name, `$CLAUDE_PROJECT_DIR`) | `.codex/hooks.json` (project) / `~/.codex/hooks.json` (user) / inline `[hooks]` table in `config.toml`, discovered in order user → project (trust-gated) → plugin-bundled → enterprise `requirements.toml` | **PARTIAL** | Same conceptual mechanism (a manifest mapping event name → command to run), different file location/format/discovery order. Codex layers config are additive ("higher layers don't replace lower ones," reported single-fetch); Claude Code/daemon has no equivalent multi-layer merge documented in the coupling doc. Codex adds two governance concepts with **no Claude Code analogue** per `RESEARCH-prior-art.md`: a hash-based **trust-review gate** for non-managed hooks (managed hooks bypass it), and **command hooks vs. MCP-tool hooks**, where MCP-tool hooks cannot block at all (only command hooks can) — a distinction Claude Code's model does not draw. |
| **Enterprise/managed-hook lockdown** | `requirements.toml` → `allow_managed_hooks_only = true` (corroborated on two separate fetches — the strongest single config detail in the surface research) | **ABSENT** on the Claude Code/daemon side | This is Codex having a governance surface the daemon has no equivalent of, not a gap in Codex — flagged as asymmetric. Relevant to a dual-host design's "can a project enforce its own hook policy against agent tampering" question, since it's the closest Codex analog to that concern. |
| **Context injection** (project instructions auto-loaded at session start: `CLAUDE.md`) | `AGENTS.md`, auto-injected on the first turn, bounded by `project_doc_max_bytes`, alternate filenames via `project_doc_fallback_filenames` | **ONE-TO-ONE** (as a concept) | Both hosts auto-load a root-level markdown doc into context at session start, distinct from (but complementary to) the `SessionStart` hook event's own `additionalContext` push, which both hosts also reportedly support. `cc-suite` (third-party OSS, `RESEARCH-prior-art.md` Part 2) treats this equivalence as solid enough to make `AGENTS.md` the single source of truth and turn `CLAUDE.md` into a thin import wrapper across both tools — external corroboration that this mapping is being relied on in practice, not just theorized here. |
| **Status line** (`handlers/status_line/*`: `settings_reader.py` hardcodes `~/.claude/settings.json`; `model_context.py` hardcodes Claude's model-tier colors and 5-tier effort ladder, reads `hook_input['effort']['level']`) | No confirmed equivalent (see Table 1's `StatusLine` row) | **ABSENT** | The entire `status_line` handler family has no host surface to attach to on Codex per this research. Even if Codex did add a status hook, the *content* (Claude's own model names, color scheme, and 5-tier effort vocabulary) would need a full rewrite — this handler family is doubly host-specific (missing surface + Claude-specific vocabulary), per `RESEARCH-daemon-couplings.md` §8's own "hard, host-specific feature" ranking. |
| **Transcript / session storage** (`transcript_path`: a JSONL file Claude Code writes and hands hooks a *path* to, not content; `TranscriptReader`'s bounded tail-read, `_DEFAULT_TAIL_BYTES = 1_048_576`) | Session ("rollout") files as JSONL under `~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<id>.jsonl`; separate `~/.codex/history.jsonl` | **PARTIAL — carrying real uncertainty forward** | Both hosts persist JSONL conversation history to disk and (per `RESEARCH-codex-lifecycle.md` §5's "Hook stdin payload" list) Codex's hook stdin is reported to include a field literally named `transcript_path`, alongside `session_id`, `cwd`, `hook_event_name` — the *same names* Claude Code uses. This is either genuine, deliberate wire-compatibility (consistent with the acknowledged Claude-Code-schema-porting found elsewhere) **or** exactly the kind of WebFetch-summarizer contamination the surface doc's header caveat warns about, since a summarizing model saturated with Claude Code's own docs would produce precisely this output whether or not it's true of Codex. Neither research pass can resolve which. Separately, and independent of that risk: rollout JSONL schema stability across Codex versions is **explicitly unconfirmed** — a direct question asked in an official-repo GitHub discussion (`openai/codex#24042`) went unanswered. A daemon-side `TranscriptReader` port would need this resolved before depending on rollout-file shape. |
| **`permission_mode` field** (5-value Claude-Code enum: `default`/`plan`/`acceptEdits`/`dontAsk`/`bypassPermissions`, read by `utils/permission_mode.py`, degrades safely to `False` for unrecognized values) | Reported present in Codex's shared hook stdin fields (`RESEARCH-codex-lifecycle.md` §5 lists `permission_mode` alongside `session_id`/`cwd`/etc.) | **PARTIAL** | The field name is reported to exist on Codex's wire format too, but **no source anywhere in this research set enumerates Codex's actual accepted values** for it — unlike Claude Code's confirmed 5-value vocabulary. Note also that Codex's *primary* approval mechanism is the separate, better-documented `sandbox_mode` × `approval_policy` pair (§3 of the lifecycle doc), not a single `permission_mode` string — so even if the field exists on the wire, the daemon's `is_bypass_mode()` logic may be checking the less-authoritative of two overlapping mechanisms on Codex. Given the daemon function already degrades safely (`False`) on any unrecognized value, this is lower-risk than most rows here, but the enum itself is an open question. |
| **Exit-code blocking convention** (`.claude/init.sh`'s `forward_stop_event()`: process exit code 2 as an alternative blocking channel, built specifically to work around a named Claude Code v2.1.114 regression demoting JSON `decision:block`) | Same `0`=success / `2`=blocking-with-stderr-reason / other-nonzero=error convention, reported identically across **three independent sources** (`RESEARCH-codex-surface.md` §2's docs-page fetch, `RESEARCH-codex-lifecycle.md` §5's `PreToolUse`/`PostToolUse` rows, `RESEARCH-prior-art.md` Part 1's own summary) | **ONE-TO-ONE** | This is the single best-corroborated cross-host structural fact in the entire research set. Caveat: the daemon's *specific* exit-2 workaround exists only because of a named Claude Code version bug; nothing suggests Codex has (or needs) that same workaround — the shared convention is real, but the daemon's current implementation of it is Claude-Code-bug-shaped and should not be ported verbatim. |
| **Transport layer** (Plan 00290's per-event socket relay: EOF-delimited byte pump, zero host-specific knowledge, JSON envelope reconstructed server-side from "which listener the connection arrived on") | Codex's `"type":"command"` hooks are reported to be plain external-process invocations receiving JSON on stdin and returning JSON (or exit-code-2 + stderr) on stdout — the same request/response shape the relay already pumps | **ONE-TO-ONE** (transport only) | `RESEARCH-daemon-couplings.md` §10 already concludes this transport would "very likely work unmodified" for a second host; the Codex research in this pass corroborates the precondition (Codex's command hooks are exec-a-script-plus-JSON-stdio, matching what the relay expects to pump) rather than contradicting it. All the actual adaptation work remains in **what** gets serialized onto that transport (Table 1's per-event wire shapes), not **how** the bytes move — consistent with the coupling doc's own framing. |

---

## Uncertainty carried forward (not resolved by this mapping)

These are inherited directly from the source docs' own open-questions
sections, restated here because they bear directly on how much weight the
tables above can carry:

1. **Methodology-level**: every Codex fact above came through `WebFetch`'s
   summarizing model, not a raw/byte-exact fetch. No hook payload schema was
   independently confirmed byte-for-byte. Given Codex's hooks are an
   *acknowledged, deliberate near-port* of Claude Code's own schema, a
   contaminated summary and a genuinely accurate one would look identical —
   this cannot be resolved without a `curl`/`gh`-based raw fetch of the
   actual docs markdown or repo source, which was not available to any of
   the four research passes.
2. **`docs/hooks.md` location unresolved**: `raw.githubusercontent.com/openai/codex/main/docs/hooks.md` 404'd; where (or whether) this file exists in-repo was not determined.
3. **`allow`'s exact `PreToolUse` semantics** are in direct tension between two sources (tied to `updatedInput` vs. simply rejected) — not resolved.
4. **Whether issue #28437 (`ask` unsupported) has since shipped** was not re-checked against current issue status.
5. **How `approval_policy` composes with the `PermissionRequest` hook event** — no source in either pass explains precedence/layering.
6. **Feature-flag key** (`features.codex_hooks` vs. `features.hooks`) reported inconsistently; not confirmed.
7. **Whether hooks have exited experimental/beta status**, and **Windows support status**, are both single-source or unconfirmed.
8. **Rollout JSONL schema stability across Codex versions** — an official-repo GitHub discussion question on this went unanswered.
9. **The claimed `v0.149.0` retirement of `approval_policy: "untrusted"`** (2026-08-20) is third-party-sourced only, not confirmed against an official OpenAI changelog.
10. **Current true tool-coverage of `PreToolUse`/`PostToolUse`** (Bash/apply_patch/MCP only) should be re-verified before this mapping's PARTIAL classifications for those two rows are treated as durable — multiple open GitHub issues (#19385, #18491, #14882) indicate this is actively being expanded, so the gap named in Table 1 may narrow or close on a timescale relevant to Plan 00292.

## Open questions specific to this mapping

- No web research was performed to check whether any of the 21 **ABSENT**
  daemon events in Table 1 have a Codex equivalent that simply wasn't
  surfaced by the docs-page fetches used across these four passes (as
  opposed to genuinely not existing) — a repo-source-level check
  (`codex-rs` source, not docs) would be the way to settle this definitively
  for events like `TeammateIdle`, `Elicitation`/`ElicitationResult`, or
  `WorktreeCreate`, which are plausibly Claude-Code/MCP-specific concepts
  with no reason to exist on Codex at all, versus events like
  `PostToolUseFailure` or `ConfigChange`, which seem like they *could*
  exist under different names and simply weren't found.
- Whether the daemon's internal `HookResult`/`Decision` enum
  (ALLOW/DENY/ASK/CONTINUE/DEFER — host-agnostic per
  `RESEARCH-daemon-couplings.md` §3) is sufficient to express everything a
  Codex-side serializer would need, given Codex's own `ask`-unsupported gap
  and command-hook-vs-MCP-tool-hook distinction, was not assessed here and
  would need a second design pass once (or if) Plan 00292 moves from
  research to design.
- This mapping did not investigate whether cc-suite's (third-party OSS)
  claim of mirroring "the shared hook events from `.claude/settings.json`
  into `.codex/hooks.json`" actually produces *working* hooks on the Codex
  side today, or only produces a config file that Codex accepts without
  erroring — i.e. whether that tool's own event-mirroring has been verified
  functionally, not just structurally. Worth checking before treating it as
  proof the mirroring approach works end-to-end.
