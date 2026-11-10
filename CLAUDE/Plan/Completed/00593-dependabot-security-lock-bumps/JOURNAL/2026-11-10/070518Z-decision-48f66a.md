## 07:05 · decision · —   — Correction: targeted QA ran no tests on a lock-only change

Correction to the delivery entry (070429Z): the implementer's worktree venv WAS synced to the new lock (`uv sync --frozen --all-extras`, per its report). Its targeted QA passed because a lock-only change maps to no test files, so `llm_qa.py changed --allow-unmapped` ran no tests at all.

Lesson for future lock-bump briefs: targeted QA proves nothing about a dependency bump. Run the test suites that load third-party plugins (pytest option tables, anyio and asyncio fixtures) explicitly, or rely on the main-thread full gate before merge rather than after it.
