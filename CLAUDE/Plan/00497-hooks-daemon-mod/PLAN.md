# Plan 00497: hooks daemon mod

**Status**: Not Started
**Created**: 2026-10-06
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet (build), Opus (design review)
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The build that follows Plan 00494, the Claude Code mods review. The owner approved its proposal on 2026-10-06
([OWNER-RULINGS-261006.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261006.md), A2 and the follow-up):

- the design, as proposed in
  [261006-hooks-daemon-mod-proposal-opus.md](../Completed/00494-claude-code-mods-review/subagent-reports/261006-hooks-daemon-mod-proposal-opus.md);
- the build order;
- the deployment route.

The owner's constraints:

- **One mod.** A single hooks-daemon mod carries every feature, switched on and off from `hooks-daemon.yaml`. There is
  only one thing to install.
- **Not protection.** Protection stays in the hook system. The mod never hooks `tool.call`, `tool.check` or
  `classic.*`.
- **Not the supervisor.** The ccy supervisor stays outside mods.
- **Deployed by the daemon.** `hooks-daemon install` and `upgrade` copy the mod into the project (as skills are
  deployed), so its version always matches the daemon. There is no marketplace.
- **Degrades to today.** With the daemon down, or mods disabled, everything behaves as it does today.

## Goals

- The daemon detects mods, and warns exceptionally loudly about any that can override, silence or alter it.
- Agents can post tasks and questions for the human that do not get lost in scrollback, and the human can tick or
  answer them.
- The human can pick suggested prompts from a list and submit them in one go.
- SessionStart messages can be shown in the mod.

## Non-Goals

- Any change to how guards decide.

## Tasks

### Phase 1: Mod awareness (daemon only, no mod)

- [ ] ⬜ **Task 1.1**: Build the awareness spec from the proposal, TDD:
  - read the `modules` key of plugin `hooks.json` files (today a mod-only plugin is filtered out);
  - grade each mod hook as overrides, silences or alters the daemon;
  - warn exceptionally loudly: at the top of every SessionStart, as a red status-line segment and as a `health` FAIL,
    with an acknowledgement that lapses when the mod changes.
- [ ] ⬜ **Task 1.2**: Correct the five doc locations that still say a daemon deny always wins (listed in the
  proposal), including `CLAUDE/ClaudeCodePlugins.md` and `CLAUDE/ARCHITECTURE.md`.

### Phase 2: The human queue (daemon side, useful without the mod)

- [ ] ⬜ **Task 2.1**: A daemon-held queue of tasks and questions for the human, with a `hooks-daemon human` CLI: post,
  list, tick, answer. An answer is labelled as the human's only after the daemon checks it against the queue. Link it to
  the awaiting-human marker, the stand-in cron and the steps guards leave to the human.

### Phase 3: The mod itself

- [ ] ⬜ **Task 3.1**: The smallest mod: a sidebar pane, the version handshake (`hooks-daemon mod hello`), the feature
  registry, and deployment by `install` and `upgrade`. The daemon warns when a same-named copy shadows it, and tells
  the user to run `/reload-plugins` or start a new session after an upgrade.
- [ ] ⬜ **Task 3.2**: The human queue in the pane: the human ticks tasks and answers questions.
- [ ] ⬜ **Task 3.3**: Suggested prompts (owner, 2026-10-06), mainly at session start:
  - **What a prompt has:** a short title shown to the user, and a verbose prompt they need not see (for example
    "Upgrade the hooks daemon", "Fix the plan QA issues").
  - **Choosing:** the user ticks any number, all or some, and presses submit.
  - **Delivery:** the verbose prompts are injected as one turn through `$.prompt.submit`.
  - **No checkbox exists:** the UI offers `Button`, `Input` and a single-choice `Select`, so multi-select is built from
    toggle buttons plus a submit button.
  - **To decide:** whether the injected text is sent `asUser`, or attributed to the mod with a line saying the human
    chose it.
  - **Where suggestions come from:** daemon-side, such as an upgrade being available or plan QA findings, so they also
    work as plain text without the mod.
- [ ] ⬜ **Task 3.4**: SessionStart messages in the mod, alongside today's hook output at first. They leave the agent's
  context only once this session's mod is confirmed. Anything the agent must act on stays in hooks.

### Phase 4: Session resilience (last; probes first)

The owner called this "maybe" before the proposal, then approved "everything else around the mods" after reading it,
and the proposal lists it as step 5. Reading it as approved is the coordinator's reading, flagged for the owner.

- [ ] ⬜ **Task 4.1**: The two live probes the proposal names: whether a `CronCreate` tick arrives as
  `scheduled-trigger`, and in what order the mod's prompt hook and the daemon's UserPromptSubmit hook run.
- [ ] ⬜ **Task 4.2**: If the probes allow, the mod records what it sees (prompt origin, the model that answered, exact
  usage) for the daemon to decide on. The daemon's state stays authoritative.

## Success Criteria

- [ ] A mod that hooks `tool.check` produces the loud warning at session start, in the status line and in `health`.
- [ ] An agent's question posted to the queue is answered by the human in the pane, and the answer reaches the session
  attributed to the human.
- [ ] Ticking two of three suggested prompts and pressing submit starts one turn containing exactly those two prompts.
- [ ] With mods disabled, or the daemon down, sessions behave exactly as they do without this plan.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00497-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed from the owner's approval of Plan 00494's proposal.
