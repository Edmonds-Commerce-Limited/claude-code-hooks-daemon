# P475 doc tier sweep (sonnet)

Goal: no doc outside the release documents requires `llm_qa.py all`.

## Edits

- `docs/QA.md`: agents use `llm_qa.py` (`changed` everyday, `all` at release preparation), linking CLAUDE/QA.md.
- `BUG_REPORTING.md`: fix-author runs `llm_qa.py changed` plus touched tests by path; CI runs the full suite on the PR.
- `CLAUDE/LLM-UPDATE.md`: dropped the `llm_qa.py all` line from "Full Verification". The `run_tests.sh` line already is the optional thorough check, and a client project's installed daemon copy is not a place to demand the daemon repo's release gate.
- `PlanWorkflow.core.md` and `Worktree.core.md`: edited in the template source `src/claude_code_hooks_daemon/install/templates/core/` and the deployed copies `CLAUDE/core/` re-copied byte-identical (they were identical before). Every "full QA suite" / "All QA checks pass" / "all QA" became "this project's QA gate for the change", and the QA Integration section says a project may keep its full suite for a release or another step it names.
- `CLAUDE/development/LESSONS.md:361`: "always clear the full gate" became `llm_qa.py changed`, with the whole suite left to CI and the Full tier.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/202-...md`.
- `DocumentationStrategy.core.md`: no QA-suite requirement, unchanged.

## Remaining `llm_qa.py all` hits

See the final reply; each is a release doc, QA.md, or text describing the full tier as a release step.
