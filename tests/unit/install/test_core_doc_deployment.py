"""Guidance must not name a client document the daemon never creates (Plan 00334).

Found in a real client install. ``plan_workflow.enabled: true`` makes
``workflow_docs`` default to ``CLAUDE/PlanWorkflow.md``
(``config/models.py``), the handler's guidance tells the agent to read that
file, and no install path ever deploys it. The project ends up enforcing a
workflow against a document that does not exist, and instructing its agent to
read a path that resolves to nothing.

It is a CLASS, not an instance: ``worktree_file_copy`` names
``CLAUDE/Worktree.md`` the same way, and a shipped agent template cites
``CLAUDE/PlanWorkflow.md`` while itself being deployed. Meanwhile
``plan_number_helper`` guards the same kind of reference with an ``.exists()``
check first — so the hazard is already known here and the guard is applied
inconsistently. That inconsistency is what
:class:`TestNamedClientDocsAreEnsured` pins.

Not the same defect as Plan 00211's parity guard, though they are neighbours.
That test pins named CONCEPTS travelling from this repo's internal document
into the deployed one, and its docstring records that a general drift checker
was out of scope. This one pins that the deployed document EXISTS AT ALL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.core_docs import (
    CORE_DOC_NAMES,
    CORE_SUFFIX,
    core_reference_line,
    core_template_path,
)
from claude_code_hooks_daemon.install.plan_workflow import bootstrap_plan_workflow

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: The client-relative documents daemon guidance names, with the surface that
#: names each. Grown whenever guidance starts naming another client document.
#: A path here is a PROMISE the daemon makes to the reader, so it must be one
#: the daemon also keeps.
_GUIDANCE_NAMED_DOCS: tuple[tuple[str, str], ...] = (
    ("CLAUDE/PlanWorkflow.md", "handlers/pre_tool_use/plan_workflow.py"),
    ("CLAUDE/Worktree.md", "handlers/pre_tool_use/worktree_file_copy.py"),
)


class TestFreshClientInstallHasTheWorkflowDoc:
    """The reproduction, at the level a client actually experiences it."""

    def test_bootstrap_creates_the_document_config_points_at(self, tmp_path: Path) -> None:
        """A fresh project, bootstrapped exactly as install does it.

        ``workflow_docs`` defaults to this path and the handler tells the agent
        to read it, so the bootstrap that turns the workflow on must also
        produce the document the workflow is described in.
        """
        bootstrap_plan_workflow(tmp_path)

        workflow_doc = tmp_path / "CLAUDE" / "PlanWorkflow.md"

        assert workflow_doc.is_file(), (
            "plan_workflow config points at CLAUDE/PlanWorkflow.md and the "
            "handler tells the agent to read it, but no install path creates "
            "it. A fresh client project enforces a workflow whose "
            "documentation does not exist."
        )

    def test_the_deployed_document_is_not_this_project_s_own(self, tmp_path: Path) -> None:
        """The core document must be GENERIC.

        This repo's own ``CLAUDE/PlanWorkflow.md`` opens by naming "the Claude
        Code Hooks Daemon project". Shipping it verbatim would push this repo's
        identity into every client, so the deployed document has to be the
        genericised core, not a copy of ours.
        """
        bootstrap_plan_workflow(tmp_path)

        workflow_doc = tmp_path / "CLAUDE" / "PlanWorkflow.md"
        pytest.importorskip("claude_code_hooks_daemon")

        assert workflow_doc.is_file()
        text = workflow_doc.read_text(encoding="utf-8")

        assert "Claude Code Hooks Daemon project" not in text, (
            "the deployed workflow document names THIS project. It is seeded "
            "into unrelated client repositories, so it must be genericised."
        )


class TestNamedClientDocsAreEnsured:
    """The durable guard for the whole class.

    Correcting the four known offenders one by one fixes today's instances and
    nothing else -- the root cause is that a guidance string naming a client
    path is written by hand, with nothing connecting it to the deploy. This
    test is that connection.
    """

    @pytest.mark.parametrize(("doc_path", "named_by"), _GUIDANCE_NAMED_DOCS)
    def test_a_named_document_is_deployed(
        self, tmp_path: Path, doc_path: str, named_by: str
    ) -> None:
        bootstrap_plan_workflow(tmp_path)

        assert (tmp_path / doc_path).is_file(), (
            f"{named_by} tells the agent to read {doc_path}, but no install "
            "path creates it. Either deploy the document or guard the "
            "reference with an existence check, as plan_number_helper does."
        )


class TestThisRepoConsumesWhatItShips:
    """The dogfooding, verified rather than claimed.

    The reference is a markdown link, not an ``@``-import: R6 prohibits those
    outside the resident set, and the allowlist escape hatch is expressly for
    "a deliberately always-loaded file", which a read-on-demand core document
    is not. Either spelling would have been a convention rather than a
    mechanism anyway -- ``@`` auto-resolves only inside a CLAUDE.md chain, and
    these documents sit outside one.

    So the enforcement is here. An unverified convention decays silently, and
    this repo's document drifting off the shipped template with nothing
    noticing is the very failure the plan exists to fix, one level up.
    """

    @pytest.mark.parametrize("name", CORE_DOC_NAMES)
    def test_our_doc_references_the_core(self, name: str) -> None:
        our_doc = _REPO_ROOT / "CLAUDE" / f"{name}.md"
        text = our_doc.read_text(encoding="utf-8")

        assert core_reference_line(name) in text, (
            f"this repo's CLAUDE/{name}.md no longer points at the core "
            "document it is supposed to extend, so we have stopped consuming "
            "the template we ship and it can rot unnoticed."
        )

    def test_the_core_document_exists_here_too(self) -> None:
        """Self-install mode receives the same deployment a client does; that
        is what makes the dogfooding real rather than a parallel copy."""
        core_doc = _REPO_ROOT / "CLAUDE" / "core" / "PlanWorkflow.core.md"

        assert core_doc.is_file(), (
            "the core document is not deployed into this project, so our own "
            "override references a file that is not there -- the exact defect "
            "this plan fixes for clients."
        )

    @pytest.mark.parametrize("name", CORE_DOC_NAMES)
    def test_our_deployed_copy_matches_the_bundle(self, name: str) -> None:
        """A tracked copy of a generated file needs a drift guard.

        ``CLAUDE/core/`` is committed so a fresh clone has it and our override
        documents are not left pointing at nothing. That makes it a tracked
        artefact generated from ``install/templates/core/``, and the standing
        hazard for those is that someone edits the copy: the edit works
        locally, survives review, and is then silently discarded by the next
        deploy. Comparing the two is what turns that into a build failure.
        """
        deployed = _REPO_ROOT / "CLAUDE" / "core" / f"{name}{CORE_SUFFIX}"

        assert deployed.is_file()
        assert deployed.read_text(encoding="utf-8") == core_template_path(name).read_text(
            encoding="utf-8"
        ), (
            f"CLAUDE/core/{name}{CORE_SUFFIX} has drifted from the template it "
            "is deployed from. It is DAEMON-owned: edit "
            f"install/templates/core/{name}{CORE_SUFFIX} and redeploy, because "
            "an edit to the deployed copy is discarded by the next deploy."
        )
