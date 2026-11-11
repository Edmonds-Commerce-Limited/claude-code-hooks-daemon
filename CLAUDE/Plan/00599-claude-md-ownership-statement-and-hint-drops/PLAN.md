# Plan 00599: claude md ownership statement and hint drops

**Status**: In Progress
**Created**: 2026-11-11
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The model responds closely to what its prompt says about who owns the code. A single
sentence, "This codebase is yours: what it's for and how it's built are your call, and
you'll keep building on it.", made it merge repeated code in about half of tries (under a
tenth without it) and fix nearby problems rather than only report them. This plan adds a
`claude_md.ownership` setting that leads the injected `CLAUDE.md` block with that sentence,
and one-line hint drops in existing handlers that say the same thing at the moment it
matters.

The owner decided: file it as a plan, ship the toggle ON by default, and build it. The
costs Anthropic measured are recorded beside the option and in the release note, because
they are the reason the toggle exists: about 1.5 times the output tokens, several
unrequested changes (mostly new tests and docs), an existing feature's behaviour changed in
one try in six to ten, closing summaries that omit small changes (review the diff, not the
summary), and a scope rule such as "no drive-by refactors" does not cancel the sentence
(still merged about a third of the time). The guide says to leave the sentence out where
the user owns the code and wants minimal change; `ownership: off` is that.

## Goals

- `claude_md.ownership` with modes `own` (default), `off`, `custom` and `claude_md.ownership_text`.
- The sentence (or the custom text) leads the injected block; `off` writes none.
- Hint drops, each at most once per session or report: plan/ledger edits, a lint failure,
  owned-branch advice, the sub-agent dispatch brief; plus a counter-hint wherever foreign
  branches are listed. All silenced by `off`.
- The setting documented in the init-config template and `docs/guides/CONFIGURATION.md`,
  with the measured costs; a release note.

## Non-Goals

- Rewording any handler's existing guidance or changing what it blocks.
- A per-handler switch for each hint: one setting governs all of them.
- Changing foreign-branch handling itself (Plan 00594 owns it).

## Tasks

### Phase 1: Setting and statement

- [x] ✅ **Task 1.1**: tests first, then `ClaudeMdConfig.ownership` / `ownership_text` with validation
- [x] ✅ **Task 1.2**: `core/ownership.py` (sentence, hint texts, once-per-session state) and the injector writing the sentence under the block heading
- [x] ✅ **Task 1.3**: controller wiring; init-config template; this repository's `.claude/hooks-daemon.yaml`; `docs/guides/CONFIGURATION.md`

### Phase 2: Hint drops

- [x] ✅ **Task 2.1**: `plan_workflow` (plan, ledger, index edits), `lint_on_edit` (failure), `agent_isolation_advisor` (dispatch brief)
- [x] ✅ **Task 2.2**: branch summary, pool report and `branch-sweep` owned-branch hint; foreign counter-hint in `branch-sweep`

### Phase 3: Delivery

- [x] ✅ **Task 3.1**: release note 055 with the measured costs
- [ ] ⬜ **Task 3.2**: regenerate this repository's `CLAUDE.md` block on the home branch after merge (`bin/hooks-daemon regenerate-docs`; a worktree never writes it)
- [ ] ⬜ **Task 3.3**: independent review and merge

## Success Criteria

- [x] `claude_md.ownership` accepts own, off, custom; custom needs text; text is rejected otherwise
- [x] The block leads with the sentence under `own` and with nothing under `off`
- [x] Every hint is silent when the mode is `off`, and speaks at most once per session
- [x] The measured-cost caveats are in `docs/guides/CONFIGURATION.md` and the release note
- [x] Release-bound consequences are in the holding area: release note 055 in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
- [ ] Reviewed and merged

## Delivery & Milestones

- Built on branch `plan-00599-ownership`; not yet merged.
