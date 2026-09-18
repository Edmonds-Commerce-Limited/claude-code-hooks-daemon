# Plan 00447: magic constant advisory policy

**Status**: Not Started, BLOCKED ON THE OWNER
**Created**: 2026-09-18
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #49

## Overview

Issue #49 reports an undocumented Claude Code environment variable,
`CLAUDE_CODE_THRIFTY_SONIC`, which gates the harness prompt-injection that
tells an agent to prefer Bash over the `Read`/`Edit`/`Write` tools. It then
asks two further questions: what other such constants exist, and whether this
daemon should check and enforce "optimal config including magic consts,
perhaps by Claude Code version".

**The report's factual core is verified, not assumed.** Against the Claude Code
build installed on the dogfood machine:

- The constant exists.
- It sits immediately beside `bashFirstSessionAssignment` and resolves through
  a `"forced"` / `"none"` / `"cohort"` ladder, with the environment variable
  taking precedence when defined — so it is an OVERRIDE on a per-session cohort
  assignment, not a plain switch.
- It is a **GrowthBook** experiment key (`thrifty_sonic`), one of a family of
  bash-first flags visible in the same string region: `CLAUDE_CODE_COZY_TEAPOT`
  (a `"strict"`/`"relaxed"` steer variant), `CLAUDE_CODE_BASALT_COVE`,
  `CLAUDE_CODE_GORSE_PLOVER`, `CLAUDE_CODE_AMBER_ASTROLABE`,
  `CLAUDE_CODE_LARCH_CISTERN`, alongside `bashActFirstEnabled`.
- The behaviour the reporter describes is directly observable: this repository's
  own sessions receive that injection on essentially every tool call, which is
  why `CLAUDE.md` carries an explicit passage settling the conflict locally.
- **642** distinct `CLAUDE_CODE_*` tokens appear in that build. That is the
  answer to "what other magic consts are there", and it is the number that
  turns the request into a policy question rather than a feature.

**What is NOT established, and cannot be from here**: the accepted VALUE and
type of the variable. Strings extracted from a compiled bundle cannot establish
parser behaviour. This is the identical wall Plan 00428 / issue #46 hit, and
that precedent is what makes this a plan rather than a task.

## The question for the owner

Three decisions, in dependency order. None of them is answerable from inside
this repository, which is why nothing has been built.

**Q1 — Should the daemon advise on undocumented experiment flags at all?**
These are GrowthBook-gated A/B assignments. Advising a fixed value means
advising a user to opt OUT of a live experiment, and the cohort assignment can
change server-side with no release and no signal here. There is a respectable
answer in both directions, which is exactly why it is escalated.

**Q2 — If yes, what evidence standard must a check meet before it ships?**
Plan 00428 is blocked on precisely this and the answer should cover both. The
failure mode is specific and is worse than a broken check: `optimal_config_checker`
is a SessionStart advisory that speaks to every install at every session start,
so a check encoding a guessed semantic does not fall silent when it is wrong —
it confidently advises the wrong thing, and nothing in this repository would
notice.

**Q3 — Should advice be gated on Claude Code version, as #49 suggests?**
Version gating implies this project tracks which flags exist per release. With
642 candidates, changing between releases, that is an ongoing intelligence
commitment rather than a one-off check — and issue #24 ("hooks intelligence
process") is arguably where that belongs, which makes this a cluster question
too.

## Goals

- Get Q1–Q3 answered by the owner, and record the answers where both this plan
  and Plan 00428 can act on them.

## Non-Goals

- **No check is written before Q1 and Q2 are answered.** Shipping one would be
  the failure mode the questions are about.
- No enumeration of all 642 constants as a deliverable. Establishing that the
  number is large was enough to frame the decision; cataloguing them is work
  that Q1 might make pointless.
- No change to the existing six checks.
- No advice to users about setting `CLAUDE_CODE_THRIFTY_SONIC`, in either
  direction, until its value semantics are established rather than inferred.

## Tasks

### Phase 1: blocked

- [ ] ⬜ **Task 1.1**: Owner answers Q1, Q2, Q3.
- [ ] ⬜ **Task 1.2**: Record the answers here and cross-reference Plan 00428,
  whose blocker Q2 subsumes.

## Success Criteria

- [ ] Q1–Q3 answered, or the plan is cancelled with the reasoning recorded.
- [ ] Plan 00428's blocker is either resolved by Q2's answer or explicitly
  re-stated as still open.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00447-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
