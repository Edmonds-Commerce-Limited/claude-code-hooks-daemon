# Plan 00460 — Implementation Report

**Agent**: python-developer (Sonnet 5)
**Worktree**: `worktree-plan-460-report-size` (branch `worktree-plan-460-report-size`)
**Scope**: Phase 1, Tasks 1.1–1.5 (TDD, in the worktree; Phase 2 merge left for the coordinator)

## Summary

`subagent_report_size_blocker` no longer tells a Write-less subagent to
write its oversized report to a file — it now resolves the stopping
agent's Write capability and, when definitively read-only, asks it to
condense its reply instead, with an explicit warning against writing
around the missing tool via a Bash heredoc/redirect/`tee`.
`dispatch_declaration` separately advises a coordinator whose dispatch
prompt declares a report destination for a `subagent_type` that cannot
write one.

## What was built

- **`src/claude_code_hooks_daemon/utils/subagent_tool_resolution.py`**
  (new): `resolve_agent_can_write(agent_type, project_root, *, home_dir=None) -> bool | None` — the ONE resolver both handlers use.
  Built-in table (`Explore`/`Plan` read-only, `general-purpose`/`claude`
  writable) cited against a freshly vendored
  `remote-docs/code.claude.com/docs/en/sub-agents.md`; `claude-code-guide`
  and `statusline-setup` resolve to `None` (upstream never documents
  their tool sets). Project/user `.claude/agents/*.md` frontmatter
  (`tools`/`disallowedTools`, matched by `name:` not filename) is the
  next tier; plugin agents and anything else resolve to `None`. Also
  exports `resolve_lookup_root` (shared project-root fallback chain).
- **`src/claude_code_hooks_daemon/utils/markdown_format.py`**: new
  `parse_frontmatter_yaml`, reused by the resolver.
- **`subagent_report_size_blocker.py`**: read-only agents get the
  condense-and-reply message; writable/unresolvable agents are
  byte-identical to before (pinned by tests — the fixture's default
  `agent_type` moved from `"Explore"`, now genuinely read-only, to
  `"general-purpose"`).
- **`dispatch_declaration.py`**: new always-advisory (never deny, even
  under strict mode) check, scoped to a DECLARED report destination
  targeting a read-only `subagent_type`.
- Both handlers' `get_claude_md()` and `get_acceptance_tests()` updated.

## Task 1.2 decision: (b), not (a)

Recorded with full evidence in the plan journal (12:16 entry). Condition
1 (full reply available to the daemon) holds; condition 2 (replicating
the same content checks a `Write` would get) does not — `sensitive_content`
/`secret_file_guard`/`markdown_organization`'s checks depend on
per-project config the registry injects onto live instances by
`setattr`, and there is no available route to reach those live instances
(or cheaply re-derive their config) from inside a SubagentStop handler
without duplicating registry plumbing. Per the task's own fallback rule,
chose (b).

## QA

Full `./scripts/qa/llm_qa.py all`: **35/35 PASSED** (25,575 tests, 0
failed, coverage 95.1%). Two error-hiding findings from the new code
were resolved via documented `error_hiding_exclusions.json` entries
(peer-precedented fail-open contracts over hand-edited external agent
files), not by reworking the functions. mypy/black clean throughout.

## Commits (worktree, not merged)

`daf48652` resolver · `b51e63de` blocker T1.2/T1.3 · `16d5904a` dispatch
T1.4 · `d376b940` release note · `feca78c5` QA fixes · `4328fcaf` journal/PLAN
