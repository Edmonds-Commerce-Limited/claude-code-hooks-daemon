## 08:00 · correction · 07:01 — Resume behaviour is inferred; QA fixes; more stale docs fixed

Correction to the 070124Z entry. It said a compact is silent and a clear fires, but that was inferred from `is_resume_session` (transcript size) and never measured. What is known: a startup with no transcript or a small one fires, and a transcript over 100 bytes is silent.

Targeted QA (`llm_qa.py changed`, after a ~10 minute wait for the host lock) found two problems. Both are fixed in 3640c2adb. First, `workflow_linter_advisor` had no recorded `get_claude_md()` verdict; it is now classified T4 in the guidance-coverage test. Second, the Task 1.1 real-linter probe test used a magic 120s timeout; it now uses `Timeout.QA_TEST_TIMEOUT`. Every other check passed.

The tree-wide search then found more stale text in `docs/guides/HANDLER_REFERENCE.md`: the `staged_lint_gate` section, its summary row, and the missing-linter sentence. All three are fixed. The truth-change `UNRELEASED/truth-changes/v3.76.0.yaml` is added as a standalone entry. It does not share the v3.55.0 Ansible entry's id, because that entry covers far more than workflows. The advisory now says how to silence it. DESIGN.md 4.1 records the builder's unflagged decisions.
