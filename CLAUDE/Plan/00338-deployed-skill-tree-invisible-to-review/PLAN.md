# Plan 00338: deployed skill tree invisible to review

**Status**: Not Started
**Created**: 2026-09-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`.claude/.gitignore` line 3 is the pattern `hooks-daemon/`, and its own comment
states the intent: "Exclude the cloned daemon repository (users install it
themselves)". The target is `.claude/hooks-daemon/`. But the pattern has no
leading slash, so git matches it at **any** depth below `.claude/` — and it
therefore also ignores `.claude/skills/hooks-daemon/`, the deployed
hooks-daemon skill tree, which has nothing to do with the daemon clone.

The consequence is not theoretical. Plan 00336 Task 4.3 found
`.claude/skills/hooks-daemon/references/troubleshooting.md` carrying a `/tmp`
spelling its source under `src/claude_code_hooks_daemon/skills/` had already
moved off. The drift had gone unnoticed because `git status` cannot see that
tree. The sibling deployed skill, `.claude/skills/docs-qa/`, **is** tracked and
its equivalent drift showed up the moment it was redeployed — so the two
deployed skills get opposite treatment, by accident rather than by decision.

The underlying question is the one worth answering, and it is a design
question rather than a one-line fix: should a deployed artefact tree be
tracked at all? Tracking it means drift is visible in review and a stale
deploy is caught at commit time; not tracking it means the repository does not
carry generated content. Both are defensible. What is not defensible is
choosing differently for two adjacent trees because a gitignore pattern was
unanchored.

## Goals

- Establish whether `.claude/skills/hooks-daemon/` being ignored is deliberate
  or an accident of the unanchored pattern.
- Make the treatment of deployed skill trees consistent and stated, in both
  self-install and client-install modes.
- Ensure that whichever treatment is chosen, source-to-deployed drift is
  detectable by something other than a redeploy happening to run.

## Non-Goals

- Changing what the skills contain, or the `deploy_skills` mechanism itself.
- Revisiting whether `.claude/hooks-daemon/` (the daemon clone) is ignored —
  it must stay ignored; that part of the pattern is correct.
- Auditing every other gitignore pattern in the project. If the sweep in
  Task 1.3 finds more, they get recorded, not fixed here.

## Tasks

### Phase 1: Establish the facts

- [ ] ⬜ **Task 1.1**: Confirm the mechanism with `git check-ignore -v` against
  a file in each deployed skill tree, and record which trees are ignored and
  which are tracked. The observation this plan is built on:
  `git check-ignore -v .claude/skills/hooks-daemon/SKILL.md` reports
  `.claude/.gitignore:3:hooks-daemon/`.
- [ ] ⬜ **Task 1.2**: Determine what a CLIENT install produces, which is the
  case that actually matters — `setup_all_gitignores` writes this file for
  every client, so whatever it does is repeated everywhere. Check whether the
  deployed `.claude/skills/` tree is expected to be committed by a client at
  all.
- [ ] ⬜ **Task 1.3**: Sweep the shipped gitignore templates in
  `scripts/install/gitignore.sh` for other unanchored patterns whose comment
  names a specific path. Record findings; do not fix them under this plan.

### Phase 2: Decide, then make it consistent

- [ ] ⬜ **Task 2.1**: Decide the treatment for deployed skill trees — tracked,
  or ignored — with the reason written down. Weigh it on the failure each
  choice permits: an ignored tree hides drift from review; a tracked tree puts
  generated content into diffs and can conflict on merge.
- [ ] ⬜ **Task 2.2**: Implement it. If the answer is "tracked", anchor the
  pattern to `/hooks-daemon/` so it means what its comment says. If the answer
  is "ignored", ignore the skills tree EXPLICITLY and by its own name, so the
  next reader sees a decision rather than a side effect — and stop tracking
  `.claude/skills/docs-qa/` in the same change.
- [ ] ⬜ **Task 2.3**: Pin it with a test. Whichever way it goes, the property
  to hold is that every deployed skill tree is treated the same way.

### Phase 3: Make drift detectable

- [ ] ⬜ **Task 3.1**: A deployed tree that matches its source today can drift
  tomorrow, and the redeploy that reveals it may be months away. Add a check
  that compares each deployed skill tree against its source. Consider whether
  this belongs with the existing `docs_qa` `generated_doc_hand_edit` check,
  which already owns "this file is generated" for individual documents, rather
  than as a new mechanism.

## Success Criteria

- [ ] `git check-ignore` gives the same answer for every deployed skill tree,
  and that answer matches a written decision rather than a pattern's reach.
- [ ] The `.claude/.gitignore` comment and the pattern below it agree about
  what is being excluded.
- [ ] Source-to-deployed drift in a skill tree is reported by a check, not
  discovered by a redeploy.
- [ ] Full QA green (25/25) and the daemon restarted and verified before the
  terminal status flip.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00338-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Source: Plan 00336 Task 4.3, which fixed the drifted file but deliberately
  left the reason it went unnoticed to this plan.
- Dedupe scout checked 45 live plans. Plan 00330 (hooks daemon skill surface
  coherence) is the nearest neighbour — it covers the skill surface an operator
  touches, not gitignore anchoring or deployed-artefact tracking — and nothing
  covers `setup_all_gitignores` behaviour.
