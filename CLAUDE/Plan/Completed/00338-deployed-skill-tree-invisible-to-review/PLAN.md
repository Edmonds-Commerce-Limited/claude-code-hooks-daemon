# Plan 00338: deployed skill tree invisible to review

**Status**: Complete
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

- [x] ✅ **Task 1.1**: **Confirmed, and the picture is one-sided.** Six deployed
  skill trees; `git check-ignore -v` reports only `hooks-daemon` as ignored,
  by `.claude/.gitignore:3:hooks-daemon/`. `acceptance-test`, `configure`,
  `docs-qa`, `mode` and `release` are all TRACKED. So "tracked" is not a
  choice to be made — it is the established treatment, and `hooks-daemon` is
  the single outlier, excluded only because an unanchored pattern happens to
  share its name.

- [x] ✅ **Task 1.2**: **No client is affected.** `ensure_claude_gitignore`
  writes `hooks-daemon/untracked/`, not the bare `hooks-daemon/`; a two-segment
  pattern cannot match `.claude/skills/hooks-daemon/`. The bare line exists in
  exactly one file in the world — this repo's own `.claude/.gitignore`, from
  the initial commit — so the defect is local to the self-install checkout and
  the fix needs no installer change.

- [x] ✅ **Task 1.3**: **Swept; nothing to fix, one thing to note.**
  `DAEMON_GITIGNORE_ENTRY` (`.claude/hooks-daemon/`) contains a slash, so git
  anchors it to the file's own directory — correct. `UNTRACKED_GITIGNORE_ENTRY`
  (`/untracked/`) is explicitly anchored. `INJECT_BACKUP_GITIGNORE_ENTRY`
  (`.CLAUDE.md.pre-inject`) is unanchored deliberately: that artefact is the
  same artefact wherever it appears.

  Noted, not fixed (Non-Goals): the client-facing `hooks-daemon/untracked/`
  would be better as `/hooks-daemon/untracked/`. Its blast radius today is nil
  — no second `hooks-daemon/untracked/` path exists — which is why it is
  recorded rather than filed as work. This same file has already been bitten
  once by an unanchored blanket (`38defcb3`, "removing blanket ccy/ ignore
  rule"), so the pattern of failure is established even where this instance is
  harmless.

### Phase 2: Decide, then make it consistent

- [x] ✅ **Task 2.1**: **TRACKED.** Task 1.1 settles it: five of six deployed
  trees already are, so "ignored" is not a live option — choosing it would mean
  UNTRACKING five trees to match one accident. The tracked side's cost
  (generated content in diffs, merge conflicts on redeploy) is real but already
  being paid for `docs-qa`, and the ignored side's cost is the one this plan
  exists because of: drift that no review and no commit gate can see.
- [x] ✅ **Task 2.2**: **Anchored to `/hooks-daemon/`**, with the reason in the
  comment beside it. The 21-file `.claude/skills/hooks-daemon/` tree is now
  tracked; it was byte-identical to its source at the time, so the commit adds
  no drift. `.claude/hooks-daemon/` — the clone the comment is actually about —
  stays ignored, which is pinned by its own test.
- [x] ✅ **Task 2.3**: **Pinned**, in
  `tests/integration/test_deployed_skill_trees.py`. The property is stated
  over the trees that EXIST rather than a hardcoded list, so a skill added
  later is covered without anyone remembering to add it.

### Phase 3: Make drift detectable

- [x] ✅ **Task 3.1**: **Done as an integration test, not a `docs_qa` check.**
  `generated_doc_hand_edit` owns "this DOCUMENT is generated" and is keyed by a
  manifest of globs; a skill tree is not a document — it holds `.sh` scripts
  too — and the property is whole-tree equality (file set AND contents), which
  a per-file manifest cannot state. A new entry in the 25-check QA suite was
  the other candidate and was rejected as disproportionate for one structural
  invariant. The test runs in the same QA suite via pytest and fails with the
  drifted paths listed, which is what the criterion asks for.

## Success Criteria

- [x] `git check-ignore` gives the same answer for every deployed skill tree,
  and that answer matches a written decision rather than a pattern's reach.
- [x] The `.claude/.gitignore` comment and the pattern below it agree about
  what is being excluded.
- [x] Source-to-deployed drift in a skill tree is reported by a check, not
  discovered by a redeploy.
- [x] Full QA green (25/25) and the daemon restarted and verified before the
  terminal status flip (daemon PID 610832; 18,273 tests, coverage 95.2%).

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
