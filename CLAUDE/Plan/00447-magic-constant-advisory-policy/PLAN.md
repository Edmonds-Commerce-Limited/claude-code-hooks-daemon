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

## Issue #50 — the worked example that CLEARS the Q2 bar

Issue #50 proposes advising `subagentPromptCacheTtl: "1h"` in
`~/.claude/settings.json`. It arrived after this plan was filed and belongs
here rather than in its own plan, because it is the same request shape — and
because it is the first candidate that answers Q2 in the affirmative.

**Unlike #49 and #46, the semantics ARE establishable from here**, because the
setting self-documents in the bundle's own schema rather than having to be
inferred:

- Accepted values are stated: `"5m"` or `"1h"`.
- The reporter's premise is confirmed verbatim: *"Unset = automatic (5 minutes
  unless `ENABLE_PROMPT_CACHING_1H=1`)"*. Subagents really do default to 5m.
- The precedence chain is readable in full: `FORCE_PROMPT_CACHING_5M` →
  `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL` → the setting → agent frontmatter
  `experimental.cacheTtl` → `ENABLE_PROMPT_CACHING_1H`.
- It is NOT a GrowthBook experiment gate, so Q1's objection does not apply.

**The asymmetry is the actual finding**, and neither the reporter nor this
project had noticed it: `promptCacheTtl` (main conversation) is documented as
*"1 hour on a Claude subscription within its usage limits, 5 minutes on an API
key, Bedrock, Vertex or Foundry"*, while `subagentPromptCacheTtl` is 5 minutes
for everyone. A subscription user therefore gets 1h on the main thread and 5m
on every subagent, by default and silently.

**But it introduces a dimension the other two did not have: COST.** The same
schema states that *"1-hour cache writes are billed at a higher rate"*, and the
per-agent description adds that `"1h"` is *ignored while a Claude subscription
is in overage*. So the advice is only net-positive on workloads that actually
reuse the cache across gaps — which is precisely the qualifier in #50's own
title ("if your agents regularly run long commands"). A blanket SessionStart
advisory to set `1h` would cost money for users whose subagents are short and
cache-cold.

That is why this is still an owner decision even though it passes Q2: the
blocker is no longer verifiability, it is whether this project should issue
advice with a billing consequence that depends on a workload it cannot see.
Call that **Q4**, below.

## The question for the owner

Four decisions, in dependency order. None of them is answerable from inside
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

**Q4 — May this project issue advice that has a BILLING consequence, when the
workload that decides whether it pays off is invisible from here?** Raised by
issue #50, which passes Q2 but hits this instead. `1h` cache writes cost more;
they only pay for themselves when the cache is reused across gaps. The honest
options are a check that advises unconditionally, one that explains the
trade-off without recommending, or none. This generalises past #50: any future
performance setting will have the same shape.

## Goals

- Get Q1–Q4 answered by the owner, and record the answers where this plan,
  Plan 00428, and issue #50 can all act on them.

## Non-Goals

- **No check is written before Q1 and Q2 are answered.** Shipping one would be
  the failure mode the questions are about.
- No enumeration of all 642 constants as a deliverable. Establishing that the
  number is large was enough to frame the decision; cataloguing them is work
  that Q1 might make pointless.
- No change to the existing six checks.
- No advice to users about setting `CLAUDE_CODE_THRIFTY_SONIC`, in either
  direction, until its value semantics are established rather than inferred.
- No `subagentPromptCacheTtl` check before Q4. The facts are established; what
  is missing is permission to give costed advice, not evidence.

## Tasks

### Phase 1: blocked

- [ ] ⬜ **Task 1.1**: Owner answers Q1, Q2, Q3, Q4.
- [ ] ⬜ **Task 1.2**: Record the answers here and cross-reference Plan 00428
  (whose blocker Q2 subsumes) and issue #50 (which Q4 gates).

## Success Criteria

- [ ] Q1–Q4 answered, or the plan is cancelled with the reasoning recorded.
- [ ] Plan 00428's blocker is either resolved by Q2's answer or explicitly
  re-stated as still open.
- [ ] Issue #50 is either implemented under Q4's answer or closed with it.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00447-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
