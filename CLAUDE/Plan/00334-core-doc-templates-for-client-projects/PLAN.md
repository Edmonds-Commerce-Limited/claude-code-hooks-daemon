# Plan 00334: core doc templates for client projects

**Status**: In Progress
**Created**: 2026-09-06
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct implementation, with one sub-agent per document
for the genericisation pass

## Overview

The daemon can be configured to enforce a workflow whose documentation it never
creates. `plan_workflow.enabled: true` sets `workflow_docs` to
`CLAUDE/PlanWorkflow.md` (`config/models.py:808-811`), handler guidance tells
the agent to read that file (`plan_workflow.py:78`), and nothing ever deploys
it. A freshly-installed client project therefore enforces a workflow against a
document that does not exist, and instructs its agent to read a path that
resolves to nothing.

Found in a real client install, not by inspection.

It is a class, not an instance:

| Surface                                                    | Names                    | Deployed |
| ---------------------------------------------------------- | ------------------------ | -------- |
| `handlers/pre_tool_use/plan_workflow.py:78`                | `CLAUDE/PlanWorkflow.md` | never    |
| `handlers/pre_tool_use/worktree_file_copy.py:57`           | `CLAUDE/Worktree.md`     | never    |
| `config/models.py:808-811`                                 | `CLAUDE/PlanWorkflow.md` | never    |
| `install/templates/agents/hooks-daemon-docs-qa.md:135-136` | `CLAUDE/PlanWorkflow.md` | never    |

The last is the sharpest: a file the daemon **does** ship cites one it does
**not**. And `plan_number_helper.py:499-503` guards the same kind of reference
with an `.exists()` check first, so the hazard is already known here and the
guard is applied inconsistently.

Two existing facts shape the fix rather than being incidental to it. The
ownership machinery already exists — `install/plan_workflow.py` deploys
`PlanJournalling.md` as a CLIENT-owned seed-once document (`:334-378`) beside
DAEMON-owned always-overwritten `mkplan.bash` (`:379-416`), so a shipped doc
template is not a new concept and `PlanWorkflow.md` is simply the one left out.
And this project's own document cannot ship verbatim: `CLAUDE/PlanWorkflow.md`
(34K) opens by naming "the Claude Code Hooks Daemon project", so shipping it
would push this repo's specifics into every client — the outcome the owner
ruled out.

## Goals

- No daemon-emitted guidance names a client document the daemon does not ensure
  exists.
- A client receives a usable core workflow document on install AND upgrade, and
  keeps its own customisations across both.
- Upstream improvements to a core document reach existing clients on upgrade
  without overwriting anything the client wrote.
- This repository consumes the templates it ships, verifiably rather than by
  convention, so a broken template breaks our own build first.

## Non-Goals

- **Rewriting the documents' content.** Genericisation removes project-specific
  claims; it is not a rewrite of guidance that already works.
- **Shipping every `CLAUDE/*.md` in this repo.** Several are genuinely
  project-specific (`ARCHITECTURE.md`, `AgentTeam.md`, `SELF_INSTALL.md`) and
  would be noise in a client. The set is chosen, not swept.
- **Making `@` a real import.** It is a CLAUDE.md feature; in a referenced
  document it is a convention. This plan VERIFIES the convention is followed
  rather than pretending the mechanism is something it is not (Decision 3).

## Tasks

### Phase 1: Reproduction (RED)

- [ ] ⬜ **Task 1.1**: Failing test proving a fresh client-mode deploy leaves
  `CLAUDE/PlanWorkflow.md` absent while `workflow_docs` points at it.
- [ ] ⬜ **Task 1.2**: Failing test for the general invariant — every client doc
  path named in handler guidance or a config default is either deployed or
  guarded by an existence check. The durable fix for the whole class; it should
  enumerate the four known offenders.

### Phase 2: The core/override mechanism

- [ ] ⬜ **Task 2.1**: `install/templates/core/` as the home for genericised
  core documents, deployed DAEMON-owned and overwritten every run (mirroring
  `mkplan.bash`) into `<project>/CLAUDE/core/`.
- [ ] ⬜ **Task 2.2**: Seed the CLIENT-owned override document once, never
  clobbering it, carrying the `@`-reference to its core document plus an empty
  overrides section (mirroring `_TEMPLATE_.md`).
- [ ] ⬜ **Task 2.3**: Wire both into the existing deploy decision site so
  `deploy-plan-workflow`, install and upgrade all pick them up.

### Phase 3: The first core document

- [ ] ⬜ **Task 3.1**: Genericise `CLAUDE/PlanWorkflow.md` into
  `PlanWorkflow.core.md` — strip this project's identity, keep the workflow.
- [ ] ⬜ **Task 3.2**: Convert this repo's own `CLAUDE/PlanWorkflow.md` to the
  forced-read + overrides form, so the dogfooding is live.
- [ ] ⬜ **Task 3.3**: Fix `worktree_file_copy.py:57` and the shipped
  `hooks-daemon-docs-qa.md` reference — the other two confirmed offenders.

### Phase 4: The remaining core set

- [ ] ⬜ **Task 4.1**: Select the set from the shippable candidates and record
  WHY each is in or out — the roster is a decision, not a sweep.
- [ ] ⬜ **Task 4.2**: Genericise and ship the selected documents, one sub-agent
  per document.

### Phase 5: Verify

- [ ] ⬜ **Task 5.1**: The Phase 1 invariant test passes with no exemptions.
- [ ] ⬜ **Task 5.2**: Full QA gate green; daemon restarts; docs regenerated.
- [ ] ⬜ **Task 5.3**: A simulated fresh client install produces a project whose
  named documents all exist.

## Technical Decisions

### Decision 1: the core document is DAEMON-owned, the override is CLIENT-owned

This is the whole design, and both halves are load-bearing. A single
client-owned document strands every existing client on the version it was
seeded with, because the deploy must never clobber a customised file — upstream
improvements could then never reach anyone. A single daemon-owned document
destroys customisation on every upgrade.

Splitting them stops the refresh path and the customisation path competing:
`CLAUDE/core/X.core.md` is replaced wholesale on every deploy and must never be
hand-edited; `CLAUDE/X.md` is written once and never touched again.

The vocabulary is not invented here — `install/plan_workflow.py` already
distinguishes exactly these two categories and states the rule for each.

### Decision 2: the core document is DEPLOYED into the client, not referenced in the vendored clone

A client install already contains this entire repository at
`.claude/hooks-daemon/`, so the core document could be referenced there instead
of copied. Rejected: that path differs between client mode and self-install
mode, where the daemon root IS the project root. `utils/cli_command` documents
at length what that difference costs — it shipped a documented command that
expanded to `-m: command not found`, and agents concluded the package was not
installed and tried to "repair" working installations.

Deploying a copy makes one path correct in both modes. `directory_role_rules.py`
chose the other option for `DirectoryRoles.md`; this plan does not follow it.

### Decision 3: the forced read is VERIFIED, not assumed

`@path` auto-import is a CLAUDE.md feature. In a document an agent is merely
told to read, `@` is a convention the agent follows — sufficient for the goal,
but not a mechanism, and an unverified convention decays silently.

So a check asserts the override document exists AND still carries its
`@`-reference. That turns "this project dogfoods the template" from a claim in
a plan into a fact the build enforces. Without it this repo's own override
document could drift off its core with nothing noticing — the exact failure
this plan exists to fix, reintroduced one level up.

### Decision 4: guidance must not name a document the daemon does not ensure

The four offenders share one root cause: a guidance string naming a client path
is written by hand, and nothing connects it to the deploy. Task 1.2's invariant
is the durable fix; the individual corrections are only its current instances.

## Success Criteria

- [ ] A fresh client-mode install produces a project where every doc path named
  in handler guidance or a config default exists.
- [ ] An upgrade refreshes core documents and leaves override documents
  byte-identical.
- [ ] This repo's own `CLAUDE/PlanWorkflow.md` is the override form, and a test
  fails if it stops referencing its core document.
- [ ] No shipped file cites a document that is not shipped.
- [ ] Full QA gate green.

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
