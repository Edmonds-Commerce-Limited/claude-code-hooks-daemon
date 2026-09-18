# Callout: the fence splitter moved out of plan QA, and the direction is now checked

**Plan**: 00439
**Audience**: handler authors

`utils/markdown_links.py` opened by explaining the layering: "It lives in
`utils` rather than in either subsystem so the dependency runs one way: both QA
packages import it, and it imports neither of them." Six lines below that
sentence was `from claude_code_hooks_daemon.plan_qa.model import lines_outside_fences`.

The fenced-code-block splitter — the primitive every line-oriented markdown
check starts with, so that a document QUOTING a checkbox is not read as one
using it — was written for `plan_qa.model` and then acquired callers elsewhere.
It now lives at `claude_code_hooks_daemon.utils.markdown_fences`, with
`_FENCE_RE`, and every caller imports it from there. No re-export was left in
`plan_qa.model`: a second name for the same function is how the ambiguity would
have survived the move. Behaviour is unchanged, and the splitter has direct
unit tests for the first time.

**If you import `lines_outside_fences` from `plan_qa.model`, repoint it** —
that name is gone from `plan_qa.model`.

The new `tests/integration/test_qa_package_dependency_direction.py` checks the
claim rather than trusting the docstring. Writing it turned up six such edges
where one was expected, so it is a ratchet rather than an absolute: the four
that remain (`utils/goal_ledger.py` on `PlanDoc`, `module_doc_budget` on
`plan_qa.types`' tier constants, and two on `plan_qa.gitfacts`) are declared in
an allowlist with the reason each is still there. A new undeclared edge fails;
so does clearing a declared one without striking it off the list.
