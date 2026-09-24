# Plan 00460: report size blocker gives read only agents a way out

**Status**: In Progress
**Created**: 2026-09-24
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration (worktree, TDD)

## Overview

`subagent_report_size_blocker` (SubagentStop) blocks a sub-agent whose final
reply is over its size threshold and tells it to write the full report to a
file at a prescribed path. It gives that instruction to every agent. Some
agent types have no `Write` tool: the built-in `Explore`, `Plan` and
`claude-code-guide`, and this project's `code-reviewer`,
`hooks-daemon-plan-dedupe-scout` and `security-reviewer`. The owner hit it
with an Explore agent, whose 11,015-character report was blocked against a
4,000 limit.

A read-only agent that has Bash then does the one thing left to it. It
writes the file with a `cat <<'EOF'` heredoc or a redirect. CLAUDE.md
states that a Bash write is not seen by the PreToolUse content guards
(sensitive content, secrets, markdown location and the rest). So the
blocker's instruction steers a read-only agent AROUND the guards. It
happened twice in one session: a `code-reviewer` twice wrote a review file
with a heredoc, saying each time "the Write tool is disabled". An agent
without Bash cannot comply at all, and is stuck until it gives up.

The coordinator's own dispatch briefs made it worse by asking read-only
agents to "write your findings to <path>". `dispatch_declaration`, the
handler that asks a coordinator to declare where reports go, does not warn
when the dispatched type cannot write.

## Goals

- The blocker knows whether the stopping agent can use `Write`, and never
  instructs an agent to do something its tool set forbids.
- A read-only agent has a way out that goes through no unguarded channel.
  Two options, decided in Task 1.2: (a) the DAEMON saves the over-long reply
  itself, applying the same content checks a `Write` would, and tells the
  agent to reply with the saved path plus a short summary; or (b) the agent
  condenses its reply under the threshold. Either way, the message
  explicitly forbids writing the file through Bash.
- `dispatch_declaration` warns when a coordinator declares a report path
  for an agent type that cannot write.

## Non-Goals

- Changing the threshold or blocking writable agents differently.
- Giving read-only agent types a `Write` tool.

## Tasks

### Phase 1: TDD in a worktree

- [x] ✅ **Task 1.1**: Resolve an agent type's tools. Built-in types come
  from a constant table: verify each type's tools from Claude Code's own
  documentation (vendor via `remote-docs` if fetched) and cite it.
  Project, user and plugin agents come from `tools:` in their
  `.claude/agents/*.md` frontmatter; no `tools:` means every tool. Unknown
  types keep today's behaviour. There is ONE resolver, used by both
  handlers.
- [x] ✅ **Task 1.2**: Decide (a) vs (b) with evidence. Check what the
  SubagentStop payload carries: whether the full final message is
  available to the daemon, or only a transcript path. For (a), the saved
  file must pass the same checks a `Write` to that path would: sensitive
  content, secret-file rules and markdown location. It must also land
  where the prescribed path already points, and must never overwrite.
  Record the decision in the journal.
- [x] ✅ **Task 1.3**: Implement it in the blocker, with a
  read-only-specific message that names what to do and forbids Bash
  writes. Writable agents are unchanged. Update the acceptance tests.
- [x] ✅ **Task 1.4**: `dispatch_declaration` advises when the dispatched
  `subagent_type` cannot write but the prompt declares a report path.
  Update the handler guidance (`get_claude_md`) for both handlers.
- [ ] ⬜ **Task 1.5**: Release note. Full QA green.

### Phase 2: Deliver

- [ ] ⬜ **Task 2.1**: Merge `--no-ff`, verify ancestry and CI, and restart
  the daemon.

## Success Criteria

- [ ] Test: an `Explore` stop over the threshold never receives "write the
  report to a file" and gets the read-only way out. A
  `general-purpose` stop is unchanged.
- [ ] Test: a project agent whose frontmatter `tools:` lacks `Write` is
  treated as read-only; one with no `tools:` line is not.
- [ ] Test: `dispatch_declaration` advises on a read-only type with a
  declared report path.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00460-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet delivered.
