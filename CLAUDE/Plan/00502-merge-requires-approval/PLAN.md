# Plan 00502: merge requires approval

**Status**: Not Started
**Created**: 2026-10-08
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Today the daemon has one merge gate: the `merge_to_main_approval` handler
(rule R-MERGE-TO-MAIN-APPROVAL), switched on by the opt-in boolean
`worktree.merge_to_main_requires_human_approval` (default `false`) and cleared
by a human running `hooks-daemon approve-merge <branch>`. Plan 00367 built it;
Plans 00390, 00407 and 00408 hardened it. The owner has observed that client
projects enable the human gate and that it gets in the way: a human approving a
worktree merge generally makes no sense, because the merge is the routine end of
agent work that has already been verified.

**Owner rulings (2026-10-08, after the v3.69.0 release):**

1. The concept is renamed from "merge to main requires HUMAN approval" to
   "merge requires APPROVAL". The approver is configurable: `human` or `agent`.
2. Agent approval names its approver either as a MINIMUM MODEL (for example
   `opus` or `haiku`: any clean sub-agent at or above that model) or as a
   SPECIFIC PROJECT SUB-AGENT NAME. The encouraged pattern is a project's own
   specialist code-review sub-agent, configured by name.
3. The approval must come from a CLEAN sub-agent (fresh context, not the
   author) and must happen BEFORE the branch or PR is merged.
4. Default: agent approval, minimum model `opus`. Human approval on worktree
   merging generally makes no sense; keep it only for very sensitive projects.
5. The code-review agent itself is project-specific and out of daemon scope; the
   daemon documents and encourages it. The documentation must clearly encourage
   enabling agent approval and defining a specialist review sub-agent.
6. Whether human and agent approval compose (agent first, then human for
   sensitive projects) rather than conflict is left to this plan to settle.
7. Not release-blocking.

Source facts: the merge-approval exploration report (the gate is enforced by
exactly one handler; this repository's own config leaves the key false, so the
gate never fires here; every shipped wording describes the gate as opt-in; the
upgrade manifest `CLAUDE/UPGRADES/config-changes/v3.64.0.yaml` shows the key as
`true` in its `example_yaml`, which is confusing and is fixed in forward-looking
docs only, never by editing a released manifest).

## Goals

- Replace the boolean with a configuration that names an approver kind and, for
  an agent approver, the minimum model or the project sub-agent name.
- Make the agent approval record unforgeable by the merging agent, bound to the
  exact branch tip, and invalidated by any later commit.
- Make agent approval the default, with a minimum model of `opus`.
- Migrate client projects that set the old key without silently weakening or
  silently blocking them, and have the upgrade name the mapping.
- Document and encourage a project specialist review sub-agent.

## Non-Goals

- Shipping or defining a code-review sub-agent: it is project-specific and out
  of daemon scope. The docs encourage it; the daemon only recognises it.
- Changing the child-to-parent merge rule: merges inside linked worktrees are
  never gated, as today.
- Changing `plan_workflow.close_requires_human_approval` or the upgrade-approval
  gate.
- Editing any released upgrade manifest or release note.
- Any code change as part of filing this plan (this plan is the design; the
  tasks below are executed later).

## The core design question

How is an agent approval recorded and verified so that the MERGING agent cannot
forge it?

### What exists to compare

- Human `approve-merge <branch>`: writes a one-shot marker the merge command
  consumes. It relies on the merging agent not running that CLI itself; the
  human-only property is a convention plus the handler guard on the command.
- Upgrade approval (`approve-upgrade`): requires a TTY and a typed
  confirmation phrase, and an `upgrade_approval_guard`/agent-action rule denies
  an agent from running it or writing under `upgrade-approvals/`. That is a
  proof of a human, which an agent approval by definition cannot offer. For an
  agent approver the proof must instead be of WHO produced the verdict and WHAT
  it covered.

### Options

- **A. Agent runs a CLI itself** (`hooks-daemon approve-merge --as-agent`).
  Rejected: the merging agent can run it. Nothing proves a second, clean agent
  was involved.
- **B. Marker written by the daemon at SubagentStop** (recommended). The daemon
  already receives SubagentStart/SubagentStop with the sub-agent type, model and
  final report. When a sub-agent whose type or model meets the configured
  approver stops, the daemon (not the agent) inspects its final message for a
  machine-readable verdict line (for example `MERGE-APPROVAL: APPROVE <branch> <tip-sha>`), checks the branch and tip it names against git, and only
  then writes a marker under the daemon state directory. The merging agent
  cannot write it: the marker path is guarded like `upgrade-approvals/`, and the
  only writer is the daemon's own SubagentStop handler. Clean-context is
  checked from the event: the approving sub-agent must differ from the
  session's authoring agent (its agent id is not one that authored commits on
  the branch, and its transcript is its own).
- **C. Out-of-band reviewer**: a CI or GitHub review decision read at merge
  time. Rejected for the default: needs network and project infrastructure; may
  be offered later as another approver kind.

### Recommendation

Option B. The marker records: branch, tip commit sha at approval, approver
sub-agent type and model, approver agent id, and creation time. Verification at
merge time (inside `merge_to_main_approval.matches/handle`) requires that the
branch tip still equals the recorded sha (any new commit invalidates it), that
the recorded model meets the configured minimum (an ordered model ladder:
`haiku` < `sonnet` < `opus`) or that the recorded sub-agent name equals the
configured name, and that the approving agent id is not the merging agent's.
The marker is consumed by the merge (one-shot, like the human marker). A
missing, stale or under-qualified record denies with the exact next step: run
the configured reviewer on the branch, and re-merge. The handler never polls.

Residual risk to state honestly in the docs: a merging agent that is also able
to spawn the approver can ask it, but cannot make it say APPROVE; a hostile
agent that instructs a sub-agent to lie is out of scope, exactly as for any
agent-written verdict. The model check relies on the model reported in the
SubagentStop event; if the event does not carry it, the task in Phase 2 falls
back to the agent definition's declared model and records which source was used.

## Configuration shape

```yaml
worktree:
  merge_approval:
    approver: agent        # agent | human | both   (default: agent)
    agent:
      min_model: opus      # haiku | sonnet | opus  (default: opus)
      # OR name a project specialist sub-agent (encouraged):
      # subagent: code-reviewer
```

- `min_model` and `subagent` are mutually exclusive; `subagent` wins in docs as
  the encouraged form. With `subagent`, the model floor is the agent
  definition's own, not a second knob.
- `approver: human` keeps today's `approve-merge` behaviour for very sensitive
  projects.
- `approver: both` composes (see the open point below): the agent record must
  exist and be valid AND a human `approve-merge` must follow.
- The model uses Pydantic `extra="forbid"`; the old boolean key stays accepted
  for one deprecation cycle so existing configs still load.

### Migration from the old boolean key

| Old config                                  | New effective config                    | Rationale                                                                                                                                                      |
| ------------------------------------------- | --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| key absent or `false` (the shipped default) | agent approval, `min_model: opus`       | This is the new default. Previously no gate; the new default adds a review step. The upgrade names this change explicitly.                                     |
| key `true`                                  | `approver: human` (unchanged behaviour) | A project that turned the human gate on chose it; it is neither weakened nor silently blocked. The upgrade offers `both` or `agent` as a suggested relaxation. |

Notes the upgrade guide must carry: (1) the old key is deprecated and mapped as
above; (2) projects that set `true` and find the human gate in the way are told
how to move to `agent` (the owner's expectation for most of them); (3) a
config-changes manifest entry for the new key (`recommended: true` for the
default shape) is added in the NEW release's manifest, with a correct example
that does not show the old boolean as `true` (the v3.64.0 example is left
untouched). The `hooks-daemon upgrade` config migration rewrites nothing
silently: it reports the mapping it applied for each project and prints the
new block.

Whether the default for a project with the key absent should be agent approval
ON (owner ruling 4) is taken as decided; the open question below only covers the
transition mechanics for projects with no `worktree:` block at all.

## Open design point: composing human and agent approval

Recommended: they compose, not conflict. `approver: both` means agent approval
first (the cheap, automatic review), then a human `approve-merge` for sensitive
projects. The ordering is enforced by the handler: a human `approve-merge` is
refused (with the reason) until a valid agent record for the same tip exists, so
a human is never asked to approve unreviewed code. Single-approver values keep
their plain meaning.

## Tasks

### Phase 1: Config model and migration (tests first)

- [ ] ⬜ **Task 1.1**: Failing tests for the new `worktree.merge_approval` model:
  defaults (`approver: agent`, `min_model: opus`), `approver` enum, mutually
  exclusive `min_model`/`subagent`, `extra="forbid"`, unknown model rejected.
- [ ] ⬜ **Task 1.2**: Implement the model in `config/models.py`; keep the old
  boolean readable and mapped (`true` to `human`, `false`/absent to default).
- [ ] ⬜ **Task 1.3**: Failing tests then implementation for the upgrade/config
  migration: reports the mapping per project, never rewrites silently, covers
  `true`, `false`, absent and a project with no `worktree:` block.
- [ ] ⬜ **Task 1.4**: Update `.claude/hooks-daemon.yaml.example`, `init_config.py`
  defaults and this repository's own config to the new block.

### Phase 2: Approval record and verification

- [ ] ⬜ **Task 2.1**: Failing tests for the record: written only by the daemon's
  SubagentStop path; fields (branch, tip sha, approver type, model, agent id,
  time); rejects a verdict whose named tip is not the branch tip; rejects the
  merging agent's own id; under-qualified model or wrong sub-agent name.
- [ ] ⬜ **Task 2.2**: Implement the SubagentStop recorder and the verdict-line
  contract; resolve the model from the event, falling back to the agent
  definition's declared model and recording the source.
- [ ] ⬜ **Task 2.3**: Protect the marker path from agent writes (same family as
  the `upgrade-approvals/` guard), with tests that a Write/Edit/Bash write to it
  is denied.
- [ ] ⬜ **Task 2.4**: Failing tests then implementation for invalidation: a new
  commit on the branch, a rebase or a different tip makes the record stale; the
  record is one-shot and consumed by the merge.

### Phase 3: Handler change

- [ ] ⬜ **Task 3.1**: Failing tests then changes in `merge_to_main_approval` for
  the three approver values, including `both` ordering; deny text names the
  configured reviewer and the next step; the handler is no longer dormant by
  default (it is on under the default config); still never applies in a linked
  worktree or to merging the default branch into itself; covers `git merge`,
  `git pull <remote> <branch>` and `gh pr merge` as today.
- [ ] ⬜ **Task 3.2**: Rename rule text and the generated CLAUDE.md section from
  "human approval" to "approval"; update the rule id registry only if the
  explain-rule tests require it, keeping R-MERGE-TO-MAIN-APPROVAL stable.
- [ ] ⬜ **Task 3.3**: Acceptance-test entries for the deny, the agent-approved
  allow and the stale-record deny.

### Phase 4: CLI

- [ ] ⬜ **Task 4.1**: `hooks-daemon approve-merge <branch>` becomes the human
  step only (TTY-gated for `human` and `both`, consistent with the upgrade
  gate's proof of a human); refuses with the reason when `both` has no valid
  agent record.
- [ ] ⬜ **Task 4.2**: A read-only `hooks-daemon merge-approval-status <branch>`
  showing the record, whether it is valid for the current tip, and why not.

### Phase 5: Documentation

- [ ] ⬜ **Task 5.1**: Update `Worktree.core.md` (template and `CLAUDE/core/`
  copy), `docs/guides/CONFIGURATION.md` and `HANDLER_REFERENCE.md`: agent
  approval is the default, the verdict-line contract, the config shape, the
  migration table.
- [ ] ⬜ **Task 5.2**: A clearly marked section encouraging a project to enable
  agent approval and define its own specialist review sub-agent, configured by
  name, with a skeleton agent description and the verdict line it must emit.
  State that defining the agent is the project's job.
- [ ] ⬜ **Task 5.3**: Fix wording that implies the old opt-in-human framing,
  including `CLAUDE/development/IssueSdlc.md` (this repository's own review
  step should name the reviewer sub-agent) and the `unenforced-approval-gate`
  docs-QA check's expectations. Do not edit released manifests.

### Phase 6: Release note and acceptance

- [ ] ⬜ **Task 6.1**: Release-note callout in `CLAUDE/UPGRADES/UNRELEASED/`
  (release-notes and a config-changes manifest entry): the rename, the new
  default (agent, min `opus`), the migration mapping, and how to keep or drop
  the human gate. Call out that the default changes behaviour for projects that
  had no gate.
- [ ] ⬜ **Task 6.2**: Run the targeted QA for every touched area, then the full
  QA gate through the coordinator; daemon restart verified.
- [ ] ⬜ **Task 6.3**: Acceptance: in a scratch worktree project, a merge is
  denied with no record; allowed after a clean `opus` sub-agent approves the
  tip; denied again after a new commit; `human` and `both` behave as specified.

## Success Criteria

- [ ] `worktree.merge_approval` exists with `approver` (agent, human, both) and
  `agent.min_model` or `agent.subagent`; defaults are agent and `opus`.
- [ ] The merging agent cannot create, edit or reuse an approval record; a new
  commit invalidates it; it is consumed by the merge.
- [ ] A client project that set the old key `true` keeps human-gate behaviour
  after upgrade, and the upgrade output names the mapping and the relaxation.
- [ ] Docs clearly encourage agent approval and a project specialist review
  sub-agent, and state that the agent itself is the project's to define.
- [ ] Release note callout present in UNRELEASED; no released manifest edited.
- [ ] All new behaviour is covered by tests written first; QA passes.

## Open questions for the owner

1. **Transition for projects with no `worktree:` block.** Owner ruling 4 makes
   agent approval the default, which newly gates projects that had nothing.
   Recommended: ship it as the new default as ruled, with the release-note
   callout and an explicit one-line opt-out (`approver: none` is NOT offered;
   dropping approval entirely is deliberately not a supported value).
   Alternative: default `agent` only for fresh `init`, and treat absent as
   unchanged on upgrade.
2. **Old key `true` mapping.** Recommended: `human` (behaviour preserved), with
   the upgrade suggesting `agent` or `both`. Alternative: map to `both`.
3. **Composition.** Recommended: `both` is a supported value, agent first, then
   human, with the ordering enforced.
4. **Verdict channel.** Recommended: a machine-readable verdict line in the
   approver's final report parsed at SubagentStop. Alternative: the approver
   runs a daemon CLI that the daemon verifies came from a sub-agent context.
5. **Model ladder.** Recommended: `haiku` < `sonnet` < `opus`, extended only by
   a daemon release when a new tier appears; an unknown configured model is a
   config error, not a pass.
6. **Name matching.** Recommended: exact match on the sub-agent type name from
   the event; no globbing.
7. **Deprecation window for the old boolean.** Recommended: accepted and mapped
   for one minor release cycle, with a deprecation advisory at session start.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00502-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed with the owner rulings recorded; no code changed.
