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

## Code review response (260924-plan460-review-opus-5-5.md)

Every finding fixed, minors included, per instruction. Each fix has its own
RED test written first; targeted QA (Plan 00463 rule) run after all fixes,
8/8 PASSED.

| Finding | Fix                                                                                                                                                                                                                                                                                                                                                                                                 |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1      | `.gitignore` (`*`) written into the report directory at first creation (`_ensure_self_ignoring`), verified with a real `git check-ignore` against a fresh repo with no pre-existing ignore rule.                                                                                                                                                                                                    |
| B2      | Auto-saved replies moved to a dedicated `untracked/agent-reports/auto/` subdirectory (`DEFAULT_PERSISTED_REPORT_DIR`); retention only ever prunes `auto/`, never the shared parent a hand-authored report may sit in.                                                                                                                                                                               |
| M1      | `resolve_confined_report_dir` rejects an empty, `.`, absolute or `..`-escaping `report_dir`, confining it under the project root; the persister skips (logs, never raises) rather than writing outside it.                                                                                                                                                                                          |
| M2      | `matches()` now returns `True` unconditionally — the `stop_hook_active` skip is dropped, so a re-entry stop's real final reply is saved too.                                                                                                                                                                                                                                                        |
| M3      | The size blocker's "already saved" deny message no longer claims the persisted copy is content-safe — the persister runs no content checks at all.                                                                                                                                                                                                                                                  |
| M4      | `resolve_agent_can_write` now consults project, then user, agents BEFORE the built-in table, so a project/user agent overrides a built-in of the same name (tested with a writable project `Explore`).                                                                                                                                                                                              |
| m1      | `find_persisted_report` picks the most recent match by `mtime`, not lexicographic filename order (`-`/`.`/digit-width ordering bugs).                                                                                                                                                                                                                                                               |
| m2      | The size blocker only cites a persisted match whose content equals the CURRENT `last_assistant_message` — a stale match for a resumed `agent_id` is no longer cited.                                                                                                                                                                                                                                |
| m3      | `write_new_file_never_overwrite` unlinks a partially-written file on a content-write failure instead of leaving a truncated one behind.                                                                                                                                                                                                                                                             |
| m4      | The read-only-dispatch advisory now gates on `_DESTINATION_PATTERN` (an explicit report destination) instead of `_has_declaration` (which also matched a bare plan-folder mention as context); `handle()` computes the match once and passes it in.                                                                                                                                                 |
| m5      | `resolve_lookup_root` centralised in `path_exclusion.py` next to `resolve_project_root`; `subagent_report_persistence.py`'s exact duplicate now delegates to it. Scoped: `subagent_report_path_verifier.py`/`cron_subagent_stop_enforcer.py` keep their own resolution (documented, deliberately different no-cwd-fallback contract) rather than risk a behaviour change under this review's remit. |
| m6      | The size blocker imports the real `DEFAULT_PERSISTED_REPORT_DIR` instead of a misleadingly-aliased `DEFAULT_REPORT_DIR`, so its lookup/fallback dir tracks the persister's real write target.                                                                                                                                                                                                       |
| m7      | Release note 10 and `.claude/hooks-daemon.yaml.example` updated to match the code: the `auto/` subdirectory split, the runtime-enforced gitignore, content not vetted, pruning scope, re-entry inclusion.                                                                                                                                                                                           |
| m8      | Persisted files/directories created `0600`/`0700` (owner-only), matching hand-authored reports and `retention.cap_log_file`'s convention.                                                                                                                                                                                                                                                           |
| m9      | The persister's acceptance-test producibility test now filters for `TestType.ADVISORY` (matching the handler's own declared test type) and actually runs the handler, asserting the file lands on disk.                                                                                                                                                                                             |
| m10     | Both handlers gained a `_home_dir` test seam (mirroring `_project_root`) so `resolve_agent_can_write` never falls through to the real `Path.home()` in a test — a real risk once M4 makes project/user agents consulted first.                                                                                                                                                                      |
| m11     | `_find_agent_frontmatter` logs an unreadable agent file at debug before continuing, instead of swallowing the `OSError` silently.                                                                                                                                                                                                                                                                   |
