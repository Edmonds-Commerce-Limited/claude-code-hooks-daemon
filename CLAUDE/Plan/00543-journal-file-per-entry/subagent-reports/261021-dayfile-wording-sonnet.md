# Day-file wording sweep (Plan 00543)

Branch worktree-543-dayfile-wording. Targeted QA: 40/40 passed (changed_tests 4452 passed).

## Repointed at the per-entry layout and `mkplan.bash --journal`

- recovery_cron_advisor.py: "never an edit of the day-file" now "never a hand-written journal file".
- limit_rebrief.py: rebrief place now "newest entry files of the active plan's JOURNAL/ (newest date folder)".
- validate_instruction_content.py, comment_changelog.py (code string and get_claude_md): "plan journal entry (`mkplan.bash --journal`)".
- plan_qa_edit.py: rule text says "journal file"; the acceptance test for the stale day-file is now "write to an existing legacy journal day-file". It expects `already exists` rather than `not today`, because journal_dayfile_is_today now closes every existing journal file at EDIT. The not-today rule applies only to creating a new legacy day-file. Safety note now says to record the change with `mkplan.bash --journal`.
- plan_journal_guard.py: "creates today's day-file from the template" now "writes the entry as its own file under today's JOURNAL/YYYY-MM-DD/ folder".
- plan_qa checks: journal_entry_with_progress and plan_shrink_without_journal ("stage the new entry file"), journal_append_only STATEMENT (legacy day-file append-only; new entries via `mkplan.bash --journal`), journal_freshness STATEMENT ("newest journal entry"), common.py explanation text ("legacy day-file").

## Left alone

Code comments and strings that describe legacy day-file reading or naming, the plan_journal_guard docstrings, and the plan_qa model/paths/naming code.

## Docs

The `grep -i day-file` over CLAUDE/\*.md, CLAUDE/core, CLAUDE/development and docs found no remaining instruction to write to a day-file; every hit is legacy or read-only wording.

## Tests

No test pinned the changed strings. Affected tests (plan_qa, plan_qa_edit, plan_journal_guard, comment_changelog, validate_instruction_content, recovery_cron_advisor, user_prompt_submit): 1865 passed.

## Generated docs

`bin/hooks-daemon regenerate-docs` was run. It updated .claude/HOOKS-DAEMON.md and the CLAUDE.md `<hooksdaemon>` block.

**Coordinator: restart the main daemon after merge** so the running handlers (and any injected CLAUDE.md block) pick up the new strings.
