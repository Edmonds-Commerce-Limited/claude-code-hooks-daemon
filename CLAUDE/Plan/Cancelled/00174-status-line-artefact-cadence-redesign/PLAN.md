# Plan 00174: Status-Line Artefact + Per-Segment Cadence Redesign

**Status**: Superseded
**Superseded By**: Plan 00175 (statusline refresh interval first class)
**Created**: 2026-07-17
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**Type**: Design brainstorm → looped audit/refine (NOT implementation-ready yet)

## Overview

Today the status line is **fully recomputed on every render**: Claude Code calls
`.claude/hooks/status-line` repeatedly, each call runs the WHOLE `status_line`
handler chain in priority order, every handler re-derives its segment, and
`hook_result.to_json` joins the fragments. Cost is 10–60 ms per render dominated
by the `git` subprocess; several handlers already bolt on ad-hoc caches
(`git_branch` TTL cache from Plan 00155, container runtime cached at daemon
startup, `settings_reader` mtime cache, `supervisor_indicator` negative cache).
Plan 00173 added a file-backed transient message (Ctrl+Z notice): the supervisor
WRITES a file, the handler READS it — a proto-"artefact" for one segment.

**The idea (user, Plan 00173 follow-up):** make the assembled status line a
persistent **artefact** (a cached per-segment state store) rather than something
recomputed from scratch each render. Decouple three cadences that are currently
fused into one:

1. **Render cadence** — how often Claude Code repaints the bar. Make each
   repaint *cheap* (assemble cached segment values) so a *fast*
   `statusLine.refreshInterval` is affordable.
2. **Per-segment update cadence** — each segment refreshes on its OWN schedule:
   container/user ≈ near-static (minutes), time ≈ per-minute, git ≈ quick-ish
   (seconds), daemon stats ≈ seconds. Configurable, not hardcoded.
3. **Event-driven updates** — some segments are pushed instantly by events (a
   Ctrl+Z writes the notice immediately; a git commit could push a branch
   refresh) independent of any timer.

The pay-offs: cheaper renders (no full chain per paint), lower latency for
event-driven notices (fast repaint of a cheap artefact), and a clean, uniform
model replacing today's scattered per-handler caching hacks.

## The Central Constraint: TWO axes — derivation AND scope (Round-1 correction)

The first draft split segments only into payload-derived vs system-derived and
implicitly treated "system-derived" as "safe to cache globally". **The Round-1
concurrency review showed that is the wrong safety boundary** and is the plan's
#1 correctness risk. There are TWO independent axes:

**Axis 1 — derivation** (can it be cached at all?):

- **Payload-derived (live, never cache):** `model_context` (model/context%/effort)
  and `working_directory` read `hook_input` — they exist ONLY in each Status
  call's JSON and change per render (a session-only `/effort` override is visible
  *only* live). Always read live; caching them is meaningless.
- **System/disk-derived (cacheable):** everything else — read from system/disk,
  not the payload.

**Axis 2 — scope** (WHO may see a cached value?): a value is only safe in a
SHARED cache file if it is identical for every session the daemon serves.
Under Plan 00127 **many sessions share one daemon**, so:

- **Global scope:** container, current time, daemon stats, upgrade notifier,
  account/user, supervisor state — identical across sessions → shareable.
- **Per-session scope:** `git_branch`, `git_repo_name`, `working_directory`,
  `multithread` rank, terminal width — system-derived BUT depend on the calling
  session's working dir / thread / terminal. Caching these to a project-scoped
  shared file **leaks one session's value into another's status bar.** They must
  be keyed by session (`session_id` / `working_dir`), never shared.

**The cache key is therefore `(segment, scope)`**, `scope ∈ {global, session_id, working_dir}`. The render = **read live payload for payload segments + read the
correctly-scoped cache for system segments + assemble.**

### Segment classification (corrected)

| Segment                 | Derivation | Scope       | Refresh cost       | Natural cadence   | Event push?              |
| ----------------------- | ---------- | ----------- | ------------------ | ----------------- | ------------------------ |
| `model_context`         | payload    | live        | ~0                 | per-render        | n/a (always live)        |
| `working_directory`     | payload    | live        | ~0                 | per-render        | n/a                      |
| `git_branch`            | system     | per-session | HIGH (5–50 ms git) | seconds           | git hook (post-checkout) |
| `git_repo_name`         | system     | per-session | medium             | session-static    | git                      |
| `multithread_indicator` | system     | per-session | low (file read)    | seconds           | thread-registry write    |
| `current_time`          | system     | global      | ~0                 | 60 s              | none                     |
| `environment_indicator` | system     | global      | ~0 (startup cache) | session-static    | none (startup)           |
| `account_display`       | system     | global      | low (file)         | session-static    | none                     |
| `daemon_stats`          | system     | global      | low                | seconds           | none                     |
| `upgrade_notifier`      | system     | global      | low (cache file)   | very slow         | `version_check` writes   |
| `supervisor_indicator`  | system+evt | global      | low                | state s / msg evt | Ctrl+Z push (Plan 00173) |
| `startup_cleanup`       | system     | global      | ~0                 | one-shot          | daemon start             |

**Key takeaway:** the ONLY genuinely expensive segment is `git_branch` (a
subprocess) — and it is **per-session**, so a background thread (no session
payload) cannot warm it; only the render can. Everything else is already ~0
(payload / startup-cached) or a cheap file read. This single fact drives the
whole design decision below.

## The Other Central Constraint: the daemon is not an always-on scheduler

The daemon runs handler chains **only when a hook fires**. Between hooks it is an
idle socket server — there is no built-in timer loop refreshing segments in the
background (the ccy supervisor IS a separate always-on process, but most projects
do not run it). This forces a design choice for "update at a cadence":

- **(A) Lazy per-segment TTL (pull, evolutionary):** on each render a segment is
  recomputed only if its TTL expired, else the cached value is reused. Cheap, no
  new threads, no always-on requirement. This is what `git_branch`/container/
  `settings_reader` already do ad-hoc — Phase work would *generalise* it into one
  cadence abstraction. Downside: the FIRST render after a TTL lapse still pays the
  refresh cost (e.g. the git subprocess), so worst-case per-render latency is
  unchanged; only the *average* improves.
- **(B) Background refresh threads (push, true decoupling):** the daemon spawns
  timer thread(s) that refresh slow segments off the render path, so even the
  first post-idle render reads a warm artefact. Removes refresh cost from ALL
  renders but adds a background-thread lifecycle, shutdown/^C handling, and
  cross-session concurrency (Plan 00127: many sessions share one daemon — who
  owns the refresher?).
- **(C) Event-driven push:** producers write the artefact when the underlying
  fact changes (Ctrl+Z → notice now; a git hook → branch; SessionStart →
  container/user). Best latency, but needs a trigger for each fact and a fallback
  for facts with no event.

**Round-1 decision (all three reviewers concur):** **(A) lazy per-segment TTL,
pull-on-render** is the backbone; **(C) event-invalidation** for the few facts
that already have an event (Ctrl+Z today; git via a hook later); **(B) background
threads is REJECTED.** The decisive reason is in the classification table above:
the only expensive segment (`git_branch`) is *per-session*, and a background
thread owns no session payload, so it literally *cannot* refresh the one fact
that would justify it — it could only refresh already-free global facts. B adds a
thread lifecycle + cross-session ownership questions to warm things that are
already ~0 ms. Only the render carries the session's identity, so pull-on-render
is the *only* mechanism that can warm per-session caches at all.

## Goals

- A single, uniform **cadence abstraction** for status segments replacing the
  scattered ad-hoc caches (`git_branch` TTL, container startup cache,
  `settings_reader` mtime, `supervisor_indicator` negative cache), each segment
  declaring its refresh policy (TTL / event-driven / per-render-live).
- A persistent, concurrency-safe **artefact store** of last-known system-segment
  values (+ their timestamps) that the render assembles cheaply.
- Cheaper average render (system segments served from cache), with a documented
  worst-case story.
- Lower latency for event-driven notices (Ctrl+Z), realised together with a
  documented `statusLine.refreshInterval` recommendation.
- Per-segment cadence is **config-driven with sensible defaults** — nothing
  hardcoded (container 300 s, user 300 s, time 60 s, git ~5 s, supervisor message
  event-driven/always-fresh, etc.), overridable in `hooks-daemon.yaml`.
- Full backward-compat: payload-derived segments (model/context/effort) keep
  reading the live payload; a project that changes nothing sees identical output.

## Non-Goals

- NOT converting the status line into a claude.ai web **Artifact** (hosted HTML).
  "Artefact" here means a persistent on-disk cached state store, rendered in the
  terminal exactly as today.
- NOT making Claude Code repaint faster on its own — repaint cadence is Claude
  Code's (`statusLine.refreshInterval`); we only make each repaint cheap.
- NOT moving payload-derived segments (model/context/effort) into a timer cache —
  they are structurally live-per-render.
- NOT a rewrite of the handler/priority/`to_json` assembly contract unless the
  audit shows it necessary; prefer evolving it.
- NOT (initially) mandating an always-on background refresher for every install —
  option (B) is opt-in, not the default.

## Open Questions — ANSWERED by Round 1

1. **Artefact granularity → per-segment files, in-memory-first.** No cross-segment
   invariant exists, so a torn-across-files read is harmless — which affirmatively
   permits per-segment files (independent cadence + isolation, à la Plan 00173).
   BUT the primary cache is **in-daemon in-memory** keyed by `(segment, scope)`;
   an on-disk file per segment is needed ONLY for values that must survive across
   the daemon's separate reader-processes or be pushed by an external writer (the
   supervisor's Ctrl+Z file). Most segments never need a file at all — the daemon
   is one long-lived process, so an in-memory dict with TTL covers them and avoids
   N stat+read per paint.
2. **Ownership → moot; (A) sidesteps it.** Plan 00127 already guarantees ONE
   daemon per `(hostname, project root)`, so there is a single owner and no
   election race. But that is the wrong question: a background refresher owns no
   session payload and so cannot refresh per-session facts. Lazy TTL pull-on-render
   sidesteps ownership entirely — chosen.
3. **Staleness → per-segment TTL + event-invalidation; clocks must not mix.**
   In-daemon TTL uses the **monotonic** clock; any cross-process timestamp (a file
   written by the supervisor and read by the daemon) uses the **wall** clock —
   never mix them (the exact trap Plan 00173 hit with `expires_at`). Costly/mutable
   facts (git) get a low TTL (~2–5 s) PLUS optional event-invalidation; near-static
   globals (container/account) get a long TTL. No explicit "stale" affordance
   needed — a low-enough TTL is the honesty mechanism.
4. **Worst-case latency → (A) fixes COST not LAG; be honest.** Lazy TTL only
   improves the *average* render (a within-TTL git segment is served from cache);
   the first post-TTL render still pays the git subprocess. It does **not** fix the
   user's LAG — see the LAG-vs-COST split below.
5. **refreshInterval → the actual lag lever; owned by Plan 00158.** A fast
   `statusLine.refreshInterval` is what makes an event notice appear promptly; the
   cache is what makes affording that interval cheap. The concrete interval value
   - Claude Code's floor is Plan 00158's scope — coordinate, don't duplicate.
6. **Full artefact store → NOT worth it (gold-plating). Do the minimal.** All three
   reviewers concur. The one expensive segment (git) is already TTL-cached (Plan
   00155\) and is per-session (background threads can't help it); every other
   segment is already ~0 ms or a cheap read. A general "artefact store + per-segment
   cadence config + background refresh" spends complexity on render-COST — the axis
   the user did NOT complain about — while the LAG they DID complain about is a
   `refreshInterval` + event-push story needing almost none of that machinery.
7. **Flicker → non-issue under (A).** Segments are assembled fresh each render from
   cache; nothing updates a visible value between renders except an event push
   (already coalesced by Plan 00173's rate-limit). No separate coalescing needed.

## LAG vs COST — the honest separation (the crux)

- **LAG** (what the user actually reported): an event notice (Ctrl+Z) appears/clears
  only on the next Claude Code repaint. Fixed by **(i)** a fast
  `statusLine.refreshInterval` + **(ii)** event-push writing the value immediately
  (Ctrl+Z already does this). Needs **none** of the artefact-store machinery.
- **COST** (what the artefact would optimise): the per-render CPU of re-deriving
  system segments. Already largely mitigated by existing per-segment caches; the
  only expensive segment (git) is per-session and already TTL-cached. Marginal
  upside; real added complexity.

Conflating the two is the trap. This plan's redesign chiefly targets COST; the
user's pain is LAG. So the recommended path is the **minimal** one.

## Revised Minimal Design (post-Round-1)

The smallest thing that delivers the user's real intent — rapid cheap repaint +
per-segment freshness + instant Ctrl+Z notice:

1. **Recommend/set a fast `statusLine.refreshInterval`** (value + Claude Code floor
   via Plan 00158). This alone fixes the notice lag.
2. **Formalise the existing ad-hoc per-segment caches into one tiny helper** — a
   `(segment, scope)`-keyed, monotonic-TTL, in-memory cache used by `git_branch`,
   `container`, `settings_reader`, `supervisor_indicator` — replacing four bespoke
   caches with one audited pattern. **Scope-keying is mandatory** so per-session
   facts never leak across the shared daemon (Plan 00127). No new files for
   in-memory-cacheable segments.
3. **Keep + generalise event-push** for the facts that have events: the Ctrl+Z
   file (done, Plan 00173) and optionally a git post-checkout hook that invalidates
   the git segment's cache. Cross-process values keep the atomic-write + wall-clock
   rules; a per-segment monotonic sequence + one in-process write lock guards the
   refresh-vs-event lost-update race.

Deferred as gold-plating (only if a concrete need appears): a general on-disk
"artefact store", per-segment cadence CONFIG surface, and any background refresh
thread. Complexity delta: minimal design ≈ one small helper + a config note vs the
full vision's new store + threads + config schema + shared-daemon ownership.

## Tasks

> These are DESIGN spikes; implementation phases are deliberately deferred until
> the looped audit/refine converges on an approach.

### Phase 1: Ground + frame

- [x] ✅ **Task 1.1**: Capture the current pull-per-render architecture, the
  derivation split, the not-a-scheduler constraint, and the existing ad-hoc
  caches (this document).
- [x] ✅ **Task 1.2**: Enumerate + classify every current status segment — done in
  the corrected two-axis classification table (derivation × scope × cost × cadence
  × event).

### Phase 2: Looped audit / refine (this plan's core deliverable)

- [x] ✅ **Task 2.1**: Round 1 — three parallel adversarial reviewers
  (architecture/feasibility, concurrency/shared-daemon, YAGNI/simplicity). All
  findings folded into the corrected taxonomy, the answered Open Questions, the
  LAG-vs-COST split, and Technical Decisions 1–4.
- [x] ✅ **Task 2.2**: Decided — (A) lazy-TTL pull-on-render + (C) event-invalidation;
  (B) rejected (Technical Decision 1).
- [x] ✅ **Task 2.3**: Decided — per-segment where a file is needed, but in-memory-first
  and scope-keyed; converged on the MINIMAL design over the full artefact store
  (Technical Decisions 2–4).

### Phase 3: Follow-up implementation plan (hand-off)

- [ ] ⬜ **Task 3.1**: Spin a focused follow-up plan to implement the minimal design:
  (i) `refreshInterval` recommendation (coordinate with Plan 00158), (ii) the one
  scope-keyed monotonic-TTL cache helper generalising the four ad-hoc caches,
  (iii) generalise event-push (git post-checkout invalidation). Fold the temp-name
  hardening into / align with Plan 00159 (see Dependencies).
- [ ] ⬜ **Task 3.2** (optional): Prototype-measure the helper on `git_branch`
  (costly, per-session) + `current_time` (cheap, global) to confirm the cost model
  before broader rollout.

## Success Criteria (for THIS plan — a refined, decided design)

- [x] Every open question answered or explicitly deferred with a reason.
- [x] A recorded decision on the cadence mechanism + scoping + granularity, with
  the simplest design that delivers the user's intent (Technical Decisions 1–4).
- [x] A clear, honest LAG (`refreshInterval` + event-push) vs COST (cache) split —
  no conflation.
- [x] A hand-off outline for a follow-up implementation plan, with the reasoned
  decision that the minimal path (not the full artefact store) is correct.

## Technical Decisions

### Decision 1: Cadence mechanism = (A) lazy TTL pull-on-render + (C) event-invalidation; (B) rejected

**Context**: the daemon is not an always-on scheduler; segments have different
freshness needs. **Options**: (A) lazy per-render TTL, (B) background refresh
threads, (C) event push. **Decision**: (A) as the backbone + (C) for facts with
an event; **reject (B)**. **Rationale**: the only expensive segment (`git_branch`)
is per-session, and a background thread owns no session payload, so it cannot warm
the one fact that would justify it; only the render carries session identity.
Unanimous across all three Round-1 reviewers.

### Decision 2: Cache key = `(segment, scope)`, scope ∈ {global, session_id, working_dir}

**Context**: a shared daemon serves multiple sessions (Plan 00127). **Decision**:
never cache a value in a scope broader than the set of sessions it is valid for.
Per-session segments (git branch/repo, working dir, thread rank, terminal width)
are keyed by session/working-dir; only container/time/daemon-stats/upgrade/account/
supervisor-state are `global`. **Rationale**: caching a per-session fact to a
shared file/key leaks one session's status into another — the #1 correctness risk
the concurrency review surfaced.

### Decision 3: In-memory-first; on-disk files only for cross-process / externally-pushed values

**Context**: the daemon is one long-lived process; most segments need no on-disk
persistence. **Decision**: primary cache is an in-daemon in-memory dict keyed by
`(segment, scope)` with a monotonic-clock TTL; use an on-disk per-segment file
ONLY when a value must cross the daemon↔external-writer boundary (the supervisor's
Ctrl+Z file). Files keep atomic-replace + pid+tid temp names + wall-clock stamps +
`.*.tmp` skip. **Rationale**: avoids N stat+read per paint for facts that never
leave the daemon; reserves the file machinery for the genuine cross-process case.

### Decision 4: Scope the plan to the MINIMAL design; defer the general artefact store

**Context**: the user's pain is LAG, not render COST. **Decision**: ship the
minimal design (fast `refreshInterval` + one scope-keyed TTL-cache helper + keep
event-push); DEFER the general on-disk artefact store, per-segment cadence config
surface, and background refresh until a concrete need appears. **Rationale**: the
big design targets COST (already mostly cached) and adds shared-daemon hazards for
marginal gain; YAGNI/PROPER-NOT-QUICK.

## Dependencies

- Builds on Plan 00173 (the Ctrl+Z message file is the first event-driven cache
  segment) and Plan 00167 (width-aware assembly in `to_json`).
- Builds on Plan 00155 T4 (the `git_branch` per-cwd TTL cache) — the prototype of
  the helper this plan would generalise.
- **Aligns with Plan 00159 (Status Writers Thread-Safe Tmp Naming)** — the Round-1
  concurrency review independently rediscovered exactly its finding: the status
  writers' temp paths are `.{stem}.{pid}.tmp` (no `tid`) vs the supervisor's
  `.{name}.{pid}.{tid}.tmp`. Any on-disk cache file this plan adds MUST use pid+tid
  temp names; fold that hardening into Plan 00159 rather than duplicating it.
- Related: Plan 00158 (`refreshInterval` / `subagentStatusLine`) — the LAG lever
  lives there; coordinate so the two plans do not collide.
- Respects Plan 00127 (shared daemon): the scope-keying rule (Decision 2) exists
  precisely because one daemon serves many sessions.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is SSoT for "when"). -->

- Plan scaffolded + first draft written; entered the looped audit/refine phase.
- Round 1 audit complete (3 parallel adversarial reviewers); design DECIDED —
  minimal scope-keyed lazy-TTL cache + `refreshInterval` + event-push; general
  artefact store deferred as gold-plating. Ready to hand off to an implementation
  follow-up plan (Task 3.1).

## Notes & Updates

- Failsafe recovery cron: `6ac90b2d` (hourly at :23, non-durable, session-only).
- **Round-1 verdict**: the user's "artefact" instinct was right about *decoupling
  cadence*, but the honest analysis is that the LAG they felt is a
  `refreshInterval` + event-push fix (needs almost no new machinery), while a full
  artefact store optimises render COST that is already largely cached. Recommended
  path = the minimal design. Open to a Round 2 if the user wants to push back on
  the "defer the full store" call.
