"""Doc-parity guard between internal and client-facing plan guidance (Plan 00211).

DBF (CLAUDE.md Standard 15 — Defence Before Fix): the field report's
sharpest finding was not the missing EXTRACT remedy itself, but that the
CONCEPT it needed — supporting documents in a plan folder — had lived in
this project's own internal ``CLAUDE/PlanWorkflow.md`` (the directory-layout
example) for a long time and never reached the client-facing deployed
guidance (``install/templates/PlanJournalling.md``, seeded verbatim into
every client project) or the injected ``plan_workflow`` CLAUDE.md section.

Fixing the wording once does not stop this recurring: a future internal
convention could drift from client-facing docs the exact same way. This
test is the guard that should have caught the original drift — it pins the
SPECIFIC concepts this defect was about (supporting docs, the ``assets/``
directory) and fails if they are ever removed from the client-facing
surfaces while still present internally. It is deliberately narrow: a
generic "diff all docs for any new concept" checker is a much harder
problem and out of scope here.

Two client-facing surfaces, two scopes: the deployed reference doc
(``PlanJournalling.md``) is detailed and read on demand, so it must carry
every structural concept including folder-layout minutiae like ``assets/``.
The injected CLAUDE.md section is deliberately terse and resident every
session, so only the CORE concept — that a plan folder may hold named
supporting documents at all — needs to reach it; the reference doc it links
to is where the rest lives.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.plan_workflow import PlanWorkflowHandler
from claude_code_hooks_daemon.install.plan_workflow import plan_journalling_doc_path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_INTERNAL_PLAN_WORKFLOW_DOC = _REPO_ROOT / "CLAUDE" / "PlanWorkflow.md"

# Structural concepts this project's OWN plan folders use (per
# CLAUDE/PlanWorkflow.md's directory-layout example). ALL of them must
# reach the deployed reference doc (the detailed, on-demand template every
# client project is seeded with). Only the CORE concept — that a plan
# folder can hold named supporting documents at all — must also reach the
# terse, always-resident CLAUDE.md section: the injected guidance is
# deliberately compact, so folder-layout minutiae like the ``assets/``
# convention belongs in the full reference doc it links to, not repeated
# in every session's context. Grown, never shrunk, as this project adopts
# new structural concepts internally.
_TEMPLATE_CONCEPTS: tuple[str, ...] = ("supporting", "assets/")
_INJECTED_GUIDANCE_CONCEPTS: tuple[str, ...] = ("supporting",)


class TestInternalDocDefinesTheConcepts:
    """Sanity check: the concepts really do live in the internal doc, else
    this guard would silently pass for the wrong reason (nothing to find
    anywhere, rather than parity actually holding)."""

    @pytest.mark.parametrize("concept", _TEMPLATE_CONCEPTS)
    def test_concept_present_internally(self, concept: str) -> None:
        text = _INTERNAL_PLAN_WORKFLOW_DOC.read_text(encoding="utf-8").lower()
        assert concept.lower() in text


class TestClientTemplateHasParity:
    """The deployed template every client project is seeded with."""

    @pytest.mark.parametrize("concept", _TEMPLATE_CONCEPTS)
    def test_concept_present_in_deployed_template(self, concept: str) -> None:
        text = plan_journalling_doc_path().read_text(encoding="utf-8").lower()
        assert concept.lower() in text, (
            f"CLAUDE/PlanWorkflow.md documents {concept!r} but the deployed "
            "client template install/templates/PlanJournalling.md does not "
            "-- this is the exact drift class the plan-size guidance field "
            "report found. Port the concept into the template."
        )


class TestInjectedGuidanceHasParity:
    """The plan_workflow CLAUDE.md section injected into every session."""

    @pytest.mark.parametrize("concept", _INJECTED_GUIDANCE_CONCEPTS)
    def test_concept_present_in_injected_claude_md(self, concept: str) -> None:
        guidance = PlanWorkflowHandler().get_claude_md()
        assert guidance is not None
        assert concept.lower() in guidance.lower(), (
            f"CLAUDE/PlanWorkflow.md documents {concept!r} but the "
            "plan_workflow handler's get_claude_md() (injected into every "
            "client project's resident CLAUDE.md) does not mention it."
        )
