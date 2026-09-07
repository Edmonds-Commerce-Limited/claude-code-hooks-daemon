---
title: Payload conversion — handler batch A (Task 1.2)
---

# Scope

Files assigned: `comment_size.py`, `validate_instruction_content.py`, `docs_qa_edit.py`,
`plan_qa_edit.py`, `markdown_organization.py`, `british_english.py`,
`plan_time_estimates.py`, `plan_workflow.py`.

# Converted (5 tests across 4 files)

- `validate_instruction_content.py::get_acceptance_tests` — 2 tests converted
  (`implementation_log_probe`, `clean_content_probe`), both `Write` to
  `scratch_path(_FIXTURE_DIR, "CLAUDE.md")` with literal content strings.
- `british_english.py::get_acceptance_tests` — 1 test converted (`probe`),
  `Write` to `scratch_path(_FIXTURE_DIR, "docs", "style-guide.md")`.
- `plan_time_estimates.py::get_acceptance_tests` — 1 test converted (`probe`),
  `Write` to `scratch_path(_FIXTURE_DIR, "Plan", "001-test", "PLAN.md")`; the
  prose's escaped `\n\n` became real newlines in the payload content.
- `plan_workflow.py::get_acceptance_tests` — 1 test converted (`probe`),
  `Write` to `scratch_path(_FIXTURE_DIR, "CLAUDE", "Plan", "099-test", "PLAN.md")`.
- `markdown_organization.py::get_acceptance_tests` — 1 test converted
  (`probe`). This one's `file_path` was `$CLAUDE_PROJECT_DIR/random-notes.md`
  in the original prose, not a `scratch_path(...)` call — `untracked/` is
  itself an ALLOWED markdown location, so putting this fixture under scratch
  would defeat the wrong-location test entirely. Used
  `str(ProjectContext.project_root() / "random-notes.md")` instead (module
  already imports `ProjectContext` at top level), with a comment explaining
  the departure from the `scratch_path` convention.

All five added `ToolPayload` to their `get_acceptance_tests()` imports (either
extending an existing lazy `from claude_code_hooks_daemon.core import (...)`
block, or adding it to `validate_instruction_content.py`'s top-level
`from claude_code_hooks_daemon.core.acceptance_test import (...)` block, which
was the only one of the five NOT using the lazy-import-inside-method style).

# Skipped — describes content in English rather than stating it (Rule 7)

- `comment_size.py:433` — "content has a trailing '#' comment on one line
  longer than 400 characters" (test: "over-long trailing comment on a new
  file is blocked")
- `comment_size.py:462` — "content has an ordinary short '#' comment (well
  under 400 chars, well under 40 lines) explaining a single function" (test:
  "a normal, reasonably-sized comment is allowed")
- `docs_qa_edit.py:312` — "whose body contains a fenced code block
  (`...`)" — also has no concrete file_path, just "a NEW file under
  .claude/rules/"
- `docs_qa_edit.py:330` — "with no broken links and no forbidden rules-file
  elements" — also no concrete file_path, just "a new .md file under CLAUDE/"
- `plan_qa_edit.py:372` — "whose content has a title but NO `**Status**:`
  line" — no concrete file_path either ("a new PLAN.md under the plan
  directory")
- `plan_qa_edit.py:389` — "with a valid `**Status**: Not Started` header and
  template tasks"
- `plan_qa_edit.py:403` — "whose date is YESTERDAY (or any other non-today
  date), not today's" — inherently non-deterministic content by design
  (depends on "today"), can't be stated as a fixed literal anyway
- `plan_qa_edit.py:422` — "dated TODAY" — same non-determinism issue

None of these had a `scratch_path(...)` call to reuse for `file_path` either,
reinforcing that they were never stated concretely to begin with. Left
completely untouched per the instructions.

# Assertions updated

None. Searched the test suites for the literal command strings pre-conversion
(`ProductService.php`, `Project Instructions`, `Estimated Effort.*4 hours`,
`random-notes`, `American spellings in markdown`, `Writing to PLAN.md file`);
the hits found were unrelated fixture content in handler unit tests (their own
`tool_input` construction), not assertions against `get_acceptance_tests()`'s
`command` string.

# Verification

```
.venv/bin/pytest tests/unit/handlers/pre_tool_use/test_comment_size.py \
  tests/unit/handlers/pre_tool_use/test_validate_instruction_content.py \
  tests/unit/handlers/pre_tool_use/test_docs_qa_edit.py \
  tests/unit/handlers/pre_tool_use/test_plan_qa_edit.py \
  tests/unit/handlers/pre_tool_use/test_markdown_organization.py \
  tests/unit/handlers/test_british_english.py \
  tests/unit/handlers/pre_tool_use/test_plan_time_estimates.py \
  tests/unit/handlers/pre_tool_use/test_plan_workflow.py -q
```

Result: 532 passed, 0 failed.

(Note: `test_british_english.py` lives at `tests/unit/handlers/`, not
`tests/unit/handlers/pre_tool_use/` — flagging in case other agents in this
batch hit the same path assumption.)
