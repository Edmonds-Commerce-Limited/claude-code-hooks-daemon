# Plan 00279: Generic Agent Install Subsystem

**Status**: In Progress
**Created**: 2026-08-27
**Owner**: Claude (requested by joseph)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration (worktree-isolated implementer)

## Overview

The daemon already ships two kinds of asset into client projects — the
`hooks-daemon` skill (`install/skills.py`) and exactly one agent, the
`hooks-daemon-plan-dedupe-scout`, deployed ad hoc by `install/plan_workflow.py`.
Agent installation should be a FIRST-CLASS, GENERIC subsystem instead: a
registry of daemon-shipped agents, each gated on specific config, deployed and
maintained by shared machinery with versioning and customisation detection.

The first new payload is the `hooks-daemon-opus-security` quarantine agent
(from the imported handover spec in this folder): an execution space for
safeguard-flaggable security work, so a caller model with an API-side content
classifier never ingests the material that trips a session-sticky model
fallback. Related: Plan 00278 (model-downgrade resilience) owns the
detection/advisory handlers; THIS plan owns the deployment machinery and the
agent asset itself.

## Goals

- **Generic registry**: daemon-shipped agents live under a single source dir
  with per-agent metadata: name (namespaced `hooks-daemon-*`), version, the
  config key that gates deployment.
- **Version + customisation tracking**: every shipped agent carries version
  metadata in its deployed file, and the daemon keeps an internal map of
  agent → version → content md5 covering ALL shipped versions — so it can
  tell outdated (md5 matches an older shipped version → safe to overwrite on
  upgrade) from customised (md5 matches NO shipped version → NEVER clobber,
  warn instead; hacking on hooks-daemon agents is strongly discouraged in
  the warning and docs).
- **Config-driven lifecycle**: on daemon start (and config change), agents
  whose gating config is enabled are deployed/updated; agents whose gating
  config is disabled produce a removal advisory (and a removal CLI) — never
  a silent delete, and never any touch of a customised file.
- **CLI**: `hooks-daemon agents list|status|install|remove [name]` — with
  output that tells a project agent exactly what to run; handler guidance
  (`get_claude_md`) points at these commands.
- **First payloads**: migrate `hooks-daemon-plan-dedupe-scout` onto the
  subsystem (behaviour-preserving; still gated on plan_workflow), and add
  `hooks-daemon-opus-security` (gated on its own config, ships disabled).

## Non-Goals

- The delegation-trigger surfaces (flaggable-path advisory, fallback
  detector, git/grep contamination blocking, DETAIL read-boundary
  enforcement) — those are Plan 00278 Phase 3, informed by the same spec.
- Skills deployment rework — `install/skills.py` stays as is; only AGENTS
  get the new subsystem (a later plan can unify).
- Editing agent content per-project — the boundary/config specifics stay
  project-owned (spec §3.5).

## Context & Background

- **Imported spec**: [HANDOVER-opus-security-agent.md](HANDOVER-opus-security-agent.md)
  (generalised) — the full delegation mechanism: why (session-sticky silent
  classifier fallback), the six failure modes (scouting-first, meta-work
  about the classifier, coordinator vocabulary accumulation, briefing-prompt
  contamination, git/grep contamination channel), the two-file
  SUMMARY/DETAIL artefact contract with read-boundary, subagent-owned git
  cycle, lean-pointer prompts, and verbatim agent/skill/rule sources in the
  appendices.
- **Existing machinery to build on**: `install/client_owned_assets.py` (the
  asset registry — provenance, deploy paths, rationale),
  `install/plan_workflow.py` (the dedupe-scout deploy: flat client-owned
  `.claude/agents/` namespace, `hooks-daemon-` name prefix, idempotent
  fill-gaps deploys).
- Config follows the classic clobber-or-extend conventions where list-like
  (Plan 00278 Task 3c.1 alignment).

## Tasks

### Phase 1: Subsystem core (TDD throughout)

- [x] ✅ **Task 1.1**: Agent asset source layout + metadata: agents dir at
  `src/claude_code_hooks_daemon/install/templates/agents/`, per-agent version,
  gating config key; shipped files carry a version marker line.
- [x] ✅ **Task 1.2**: Version/md5 ledger: agent → version → content md5 for
  every shipped version; classification helper returning
  absent | current | outdated | customised.
- [x] ✅ **Task 1.3**: Deploy/update/remove engine: install when gated
  config enabled; overwrite ONLY absent/outdated; customised → loud warning,
  never clobbered; disabled → removal advisory (auto-remove only a
  pristine shipped file, and only via the explicit CLI command).

### Phase 2: Lifecycle wiring

- [x] ✅ **Task 2.1**: Daemon-start detection (controller `initialise` runs
  the sync; a config change takes effect on the restart that applies it):
  enabled + missing/outdated ⇒ deploy; disabled + present ⇒ advisory naming
  the removal command. Registered in `client_owned_assets.py`.
- [x] ✅ **Task 2.2**: CLI `hooks-daemon agents list|status|install|remove`;
  status shows the classification per agent; docs (LLM-INSTALL table,
  docs/guides/AGENT_ASSETS.md, removal advisories) name the commands.
- [x] ✅ **Task 2.3**: Migrate the plan-dedupe scout onto the subsystem
  (same deployed path/name, still gated on plan_workflow; pristine copies
  refreshed exactly as before, customised copies now warned instead of
  clobbered).

### Phase 3: opus-security agent payload

- [x] ✅ **Task 3.1**: Author `hooks-daemon-opus-security.md` generalised
  from the spec's Appendix A: model: opus; quarantine executor; two-file
  SUMMARY/DETAIL contract with the `-opus-security-SUMMARY`/`-DETAIL`
  markers; subagent-owned git cycle; clean-summary rule; estate-specific
  paths/doc names replaced by config/doc placeholders the project fills in.
  Ships gated on config that defaults OFF.
- [x] ✅ **Task 3.2**: Docs: `docs/guides/AGENT_ASSETS.md` (gating keys, CLI,
  discourage-customisation note); config-changes manifest entry for
  `agents.opus_security.enabled`; LLM-INSTALL ownership table updated.
  (No HANDLER_REFERENCE change — no handler options were added.)

### Phase 4: Verification & closure

- [ ] ⬜ **Task 4.1**: Full QA; daemon restart RUNNING; client-mode
  verification via `scripts/dummy-client-repo.sh` (deploy, upgrade
  overwrite, customisation refusal, disable advisory, remove).
- [ ] ⬜ **Task 4.2**: Complete plan (archive, README row, journal closure).

## Dependencies

- Related: Plan 00278 (consumes the deployed opus-security agent from its
  Phase 3 advisories); Plan 00274 (report-only/human-gated conventions).

## Technical Decisions

### Decision 1: md5 ledger across ALL shipped versions

**Context**: distinguishing "outdated but pristine" from "customised".
**Decision**: keep every shipped version's content md5 (usedforsecurity
False; identity only). A deployed file matching any ledger entry is
pristine (overwrite on upgrade allowed); matching none is customised and is
never touched — the warning names the file, the shipped version, and the
strong discouragement of hacking on daemon-owned agents.
**Date**: 2026-08-27

### Decision 2: removal is advisory-first, CLI-executed

**Context**: config disabled while agent deployed.
**Decision**: the daemon never silently deletes from `.claude/agents/` — it
advises with the exact `hooks-daemon agents remove <name>` command; the CLI
removes only pristine files and refuses customised ones.
**Date**: 2026-08-27

## Success Criteria

- [ ] Both agents deploy through one generic subsystem; dedupe-scout
  behaviour unchanged for existing installs.
- [ ] Upgrade path proves: outdated pristine file overwritten; customised
  file left intact with a loud warning.
- [ ] Enable/disable config transitions produce deploy/removal-advisory on
  daemon start; CLI list/status/install/remove all work in the dummy client
  repo.
- [ ] opus-security agent ships disabled-by-default, generalised, and
  deploys cleanly when enabled.
- [ ] All QA green; daemon restarts RUNNING.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). The activity log lives in JOURNAL/. -->

- (pending)
