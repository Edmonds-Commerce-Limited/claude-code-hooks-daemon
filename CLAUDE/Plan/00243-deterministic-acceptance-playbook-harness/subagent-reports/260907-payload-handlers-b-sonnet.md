---
title: Task 1.2 — payload conversion, batch B (sonnet)
---

# Files touched

## lsp_enforcement.py — 2 converted

- "Block Grep for class definition" -> `ToolPayload(GREP, {"pattern": "class FrontController"})`
- "Allow Grep for regex pattern" -> `ToolPayload(GREP, {"pattern": "log.*Error"})`
- Left unchanged (already literal shell commands, rule 5): "Block Bash rg for function definition" (`rg "..." src/`), "Allow Bash grep scoped to one named file" (`grep -n ... file.py`).

## project_containment.py — 3 converted

- "Write to a path outside the repository" -> `ToolPayload(WRITE, {"file_path": "/tmp/acceptance-test-containment/probe.md", "content": "# probe"})` (literal `/tmp` path kept per rule 3, it's the point of the test).
- "Bash redirect to a path outside the repository" -> `ToolPayload(BASH, {"command": "echo probe > /tmp/acceptance-test-containment.txt"})`.
- "The same scratch write, inside the repository" -> `ToolPayload(WRITE, {"file_path": str(scratch_path("acceptance-probe.md")), "content": "# probe"})`. Moved the pre-existing "Absolute, unlike..." comment to sit above the `command=` line since the f-string it explained is now inside the payload construction above.

## artifact_publish_blocker.py — 1 converted, 1 skipped

- Converted: "Artifact list is allowed" -> `ToolPayload(ARTIFACT, {"action": "list", "limit": 1})`.
- Skipped (rule 7, describes not states): line 294-298, "Artifact publish is denied" — command is `"Use the Artifact tool to publish any local .html file (no action parameter, which means publish)."`. "any local .html file" names no concrete `file_path`; inventing one would assert something the prose doesn't.

## dispatch_declaration.py — 0 converted, 3 skipped

All three tests describe the dispatch prompt's properties in English rather than stating one, so none were converted (rule 7):

- line 194-195: "a prompt that names neither a plan folder nor a non-plan-work destination"
- line 211-214: same phrasing, strict-mode variant
- line 227: "a prompt naming a CLAUDE/Plan/NNNNN-name/ folder" (a template, not a literal prompt)

## sed_blocker.py — 1 converted, 2 unchanged, rule-8 item not found

- Converted: "Write tool: shell script with sed (strict mode)" -> `ToolPayload(WRITE, {"file_path": "$CLAUDE_PROJECT_DIR/untracked/test_sed_acceptance.sh", "content": '#!/bin/bash\nsed -i "s/foo/bar/g" file.txt'})` (escaped `\\n` in the old prose became a real newline; file_path kept as the literal `$CLAUDE_PROJECT_DIR/...` string the prose used, matching this file's existing unexpanded-env-var convention — no `scratch_path()` call was in the original to reuse).
- Unchanged (already literal shell commands, rule 5): "sed -i with substitution", "sed -e command".
- Rule 8 (test #22, file path as command with real instruction buried in description): **not found**. This file's `get_acceptance_tests()` only returns 3 `AcceptanceTest` objects total (grep-confirmed — 3 `AcceptanceTest(` call sites), none of whose `command` is a bare file path. Either it was already fixed by another pass, or "#22" indexes a cross-file/global audit list rather than this file's local list — flagging back to team lead rather than guessing.

## write_clobber_guard.py — 0 converted, 2 skipped

Both tests describe rather than state (rule 7), no concrete `file_path`:

- line 257-260: "a file that already exists and that you have NOT read in this session (for example a tracked source file)"
- line 275: "a path that does not exist yet"

## daemon_docs_guard.py — 1 converted

- "Read from hooks-daemon CLAUDE dir warns about wrong path" -> `ToolPayload(READ, {"file_path": str(fixture_file)})`.

## web_search_year.py — 1 converted

- "Outdated year in search query" -> `ToolPayload(WEB_SEARCH, {"query": "Python best practices 2024"})`.

## recovery_cron_advisor.py — 3 converted

- "Plan creation..." -> `ToolPayload(WRITE, {"file_path": str(plan_path_abs), "content": "# Plan 99099: Test\n\n**Status**: Not Started"})`
- "Plan progress-update..." -> `ToolPayload(EDIT, {"file_path": str(plan_path_abs), "old_string": "⬜ **Task 1.1**", "new_string": "✅ **Task 1.1**"})`
- "Plan completion..." -> `ToolPayload(WRITE, {"file_path": str(plan_path_abs), "content": "# Plan 99099\n\n**Status**: Complete"})`
- Note: `scratch_dir.py` changed under me mid-task (another agent's concurrent work, Plan 00333) — `scratch_path()` now returns an unexpanded `$CLAUDE_PROJECT_DIR/...` string rather than a resolved absolute path. This doesn't affect my edits: I used `str(scratch_path(...))` exactly as the reference files do, so the payload tracks whatever `scratch_path()` returns.

## user_prompt_submit/goal_injection.py — MISSING

Path does not exist under `src/claude_code_hooks_daemon/handlers/user_prompt_submit/`. Per instructions, skipped without searching elsewhere.

# Verification

All 9 existing files' unit test modules run green after edits:

- test_lsp_enforcement.py: 83 passed
- test_project_containment.py: 76 passed
- test_artifact_publish_blocker.py: 40 passed
- test_sed_blocker.py: 145 passed, 1 xfailed (pre-existing, unrelated)
- test_daemon_docs_guard.py: 22 passed
- test_web_search_year.py: 40 passed
- test_recovery_cron_advisor.py: 80 passed

No assertions in any of the corresponding test files hardcoded the old `command` prose strings, so no test assertions needed updating. `dispatch_declaration.py` and `write_clobber_guard.py` were left byte-for-byte unchanged (no edits at all), so their test modules were not re-run.
