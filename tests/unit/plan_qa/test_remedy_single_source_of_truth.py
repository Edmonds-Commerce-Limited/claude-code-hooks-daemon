"""Cross-surface DRY guard for the plan-size remedy wording (Plan 00211).

Field report: the "two remedies, and neither is deletion" wording was
hand-copied into three surfaces (``plan_doc_size.py``'s ``Finding``, the
``plan_qa_edit`` CLAUDE.md guidance, the ``plan_workflow`` CLAUDE.md
guidance), and had already drifted — none of the three named EXTRACT.
``plan_qa/remedy.py`` is now the single source of truth. If a future edit
hand-rewrites one surface's wording instead of importing
``remedy_sentence()``/``remedy_markdown_list()``, that surface's rendered
text stops containing the canonical rendering and these tests fail —
closing the drift class the report found.
"""

from claude_code_hooks_daemon.handlers.pre_tool_use.plan_qa_edit import PlanQaEditHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_workflow import PlanWorkflowHandler
from claude_code_hooks_daemon.plan_qa.checks.plan_doc_size import _REMEDY
from claude_code_hooks_daemon.plan_qa.remedy import remedy_markdown_list, remedy_sentence


class TestPlanDocSizeUsesCanonicalRemedy:
    def test_finding_remediation_prefix_is_the_canonical_sentence(self) -> None:
        assert _REMEDY == remedy_sentence()


class TestPlanQaEditUsesCanonicalRemedy:
    def test_claude_md_guidance_contains_the_canonical_sentence(self) -> None:
        guidance = PlanQaEditHandler().get_claude_md()
        assert guidance is not None
        assert remedy_sentence() in guidance


class TestPlanWorkflowUsesCanonicalRemedy:
    def test_claude_md_guidance_contains_the_canonical_markdown_list(self) -> None:
        guidance = PlanWorkflowHandler().get_claude_md()
        assert guidance is not None
        assert remedy_markdown_list() in guidance
