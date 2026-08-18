# Plan 00259: block artefact publishing by default

**Status**: Not Started
**Created**: 2026-08-18
**Owner**: Claude (Opus 5)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The `Artifact` tool publishes a page to claude.ai and returns a URL. The page
starts private, but it is hosted OUTSIDE the project and the whole point of the
URL is that a human can then share it. That is an egress path the repository
cannot see, cannot audit and cannot retract: once content has left, deleting the
artefact does not un-share a link somebody already opened.

This project already refuses to let an agent self-authorise disclosure — the
secret word list, `delete-branch --allow-unproven` requiring an interactive
human, and `standing_authorisations` shipping every entry disabled are all the
same principle. Artefact publishing is currently the one disclosure path with no
guard at all.

So: a PreToolUse handler, **on by default**, that denies artefact publishing and
tells the agent that only the HUMAN can lift the block.

## Goals

- An agent cannot publish an artefact in a default-configured project.
- The deny message names the exact config change, and states plainly that the
  agent must ask rather than apply it.
- Read-only `action: "list"` stays allowed — enumerating is not disclosure.
- Shipping this does not silently change behaviour for existing installs
  without saying so.

## Non-Goals

- Not blocking the human from publishing through the claude.ai UI. The daemon
  sees tool calls, not browser clicks — the same honest limitation
  `ancestry_preserving_merge` records about the GitHub merge button.
- Not scanning artefact CONTENT for sensitive material. `sensitive_content`
  already scans the file at Write time; this handler is about the act of
  publishing, not what is in the page.
- Not an agent-side escape hatch. Deliberate — see Decision 2.

## Context & Background

The `Artifact` tool takes an optional `action`: absent or `"publish"` renders a
local file to a hosted page; `"list"` enumerates existing artefacts. Only the
first creates or updates anything.

Relevant precedent in this codebase:

| Guard                       | What it refuses to let the agent self-authorise       |
| --------------------------- | ----------------------------------------------------- |
| `sensitive_content`         | writing a term the human marked secret                |
| `delete-branch`             | destroying unproven work (needs an interactive human) |
| `standing_authorisations`   | asserting consent the project never recorded          |
| `ask_user_question_blocker` | pausing the session without a declared reason         |

## Tasks

### Phase 1: Design confirmation

- [ ] ⬜ **Task 1.1**: Confirm the daemon actually receives `Artifact` tool
  calls as PreToolUse with `tool_name: "Artifact"`, and capture a real payload
  with `scripts/debug_hooks.sh` rather than assuming the shape. Record the
  observed `tool_input` keys (`file_path`, `action`, `url`, `title`, …).
- [ ] ⬜ **Task 1.2**: Fix the handler id, config key and priority. Proposed
  `artifact_publish_blocker` at priority 14, sitting with `sensitive_content`
  (14) and `security_antipattern` (14) in the disclosure/safety band.

### Phase 2: TDD implementation

- [ ] ⬜ **Task 2.1**: RED — tests for `matches()`: fires on `Artifact` with no
  `action`, fires on `action: "publish"`, does NOT fire on `action: "list"`,
  does NOT fire on any other tool.
- [ ] ⬜ **Task 2.2**: RED — tests for `handle()`: `Decision.DENY`, and the
  reason names the config key AND states the agent must ask a human.
- [ ] ⬜ **Task 2.3**: GREEN — implement the handler, terminal, in
  `handlers/pre_tool_use/`.
- [ ] ⬜ **Task 2.4**: `get_claude_md()` — resident guidance, since a blocking
  handler with no guidance is exactly what the coverage gate catches.
- [ ] ⬜ **Task 2.5**: `get_acceptance_tests()` — a DENY case and an ALLOW case
  (`action: "list"`), because a positive-only suite cannot catch over-broad
  matching (the `find_deny_capable_handlers_without_allow_case` rule).

### Phase 3: Wiring and disclosure

- [ ] ⬜ **Task 3.1**: Register in config defaults as `enabled: true`, and add
  it to this project's own `.claude/hooks-daemon.yaml` (dogfooding).
- [ ] ⬜ **Task 3.2**: `config-changes` manifest entry for the new key.
- [ ] ⬜ **Task 3.3**: A `truth-changes` entry. This one matters: a project
  whose own docs say "publish a report as an artefact and share the link" now
  has a false instruction, and truth-changes is the channel that renders
  unconditionally on upgrade.
- [ ] ⬜ **Task 3.4**: Full QA, daemon restart RUNNING, and run the handler's
  own acceptance tests live.

## Technical Decisions

### Decision 1: block the ACT of publishing, not the content

**Context**: the handler could scan what is being published instead.
**Decision**: block the act. Content scanning is `sensitive_content`'s job and
it already ran when the file was written; duplicating it here would be a second
source of truth for "what is sensitive", and the two would drift. The risk being
managed is not "this page contains a secret" but "a URL now exists outside the
repository".

### Decision 2: no agent-side escape hatch

**Context**: several handlers accept `MUST_..._BECAUSE="reason"` inline.
**Decision**: NOT here. Those hatches let the agent declare intent for an action
whose consequences stay inside the repository. Publishing leaves it. An agent
that can type its own justification has self-authorised disclosure, which is the
precise thing this handler exists to prevent — the same reason
`delete-branch --allow-unproven` still demands an interactive human. Lifting the
block is a config edit, made by a human, visible in review.

## Success Criteria

- [ ] Publishing an artefact is denied in a default-configured project
- [ ] `action: "list"` is not denied
- [ ] The deny reason names the config key and says to ask a human
- [ ] Handler carries `get_claude_md()` and both acceptance-test cases
- [ ] QA green, daemon restart RUNNING
- [ ] config-changes and truth-changes entries staged

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Requested during the v3.54.0 release; deliberately NOT added to that bundle
  (see JOURNAL for the sequencing reasoning).
