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

from claude_code_hooks_daemon.install import core_docs
from claude_code_hooks_daemon.install.core_docs import (
    CORE_DOC_NAMES,
    CORE_SUFFIX,
    core_reference_line,
    core_template_path,
    deploy_core_docs_if_enabled,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Every subsystem that names a core document, switched on. The invariant is
#: about the promise being kept when the guidance is REACHABLE, so the tests
#: that check "is this document deployed" have to enable the guidance first.
_ALL_SUBSYSTEMS_ON = "plan_workflow:\n  enabled: true\ndocumentation:\n  enabled: true\n"


def _write_config(project_root: Path, body: str) -> Path:
    config_path = project_root / "hooks-daemon.yaml"
    config_path.write_text(body, encoding="utf-8")
    return config_path


#: The client-relative documents daemon guidance names, with the surface that
#: names each. Grown whenever guidance starts naming another client document.
#: A path here is a PROMISE the daemon makes to the reader, so it must be one
#: the daemon also keeps.
_GUIDANCE_NAMED_DOCS: tuple[tuple[str, str], ...] = (
    ("CLAUDE/PlanWorkflow.md", "handlers/pre_tool_use/plan_workflow.py"),
    ("CLAUDE/Worktree.md", "handlers/pre_tool_use/worktree_file_copy.py"),
    # Named in a runtime FINDING message, unguarded -- the reader is sent
    # there at the moment a check fires, which is the worst moment for the
    # path to resolve to nothing. The docs_qa engine enforces R1-R13 in every
    # client, so the ruleset had to become something a client actually holds.
    ("CLAUDE/DocumentationStrategy.md", "docs_qa/checks/rules_file_shape.py"),
)


class TestFreshClientInstallHasTheWorkflowDoc:
    """The reproduction, at the level a client actually experiences it."""

    def test_install_creates_the_document_config_points_at(self, tmp_path: Path) -> None:
        """A fresh project, deployed exactly as install does it.

        ``workflow_docs`` points at this path and the handler tells the agent
        to read it, so the install that turns the workflow on must also produce
        the document the workflow is described in.
        """
        deploy_core_docs_if_enabled(tmp_path, _write_config(tmp_path, _ALL_SUBSYSTEMS_ON))

        workflow_doc = tmp_path / "CLAUDE" / "PlanWorkflow.md"

        assert workflow_doc.is_file(), (
            "plan_workflow config points at CLAUDE/PlanWorkflow.md and the "
            "handler tells the agent to read it, but no install path creates "
            "it. A fresh client project enforces a workflow whose "
            "documentation does not exist."
        )

    @pytest.mark.parametrize("name", CORE_DOC_NAMES)
    def test_the_shipped_document_is_not_this_project_s_own(self, name: str) -> None:
        """Every core document must be GENERIC.

        This project's own documents open by naming "the Claude Code Hooks
        Daemon project". Shipping one verbatim would push this repo's identity
        into every client, so each deployed document has to be the genericised
        core rather than a copy of ours.

        Asserted against the BUNDLED TEMPLATE, not the seeded override. The
        override is daemon-written boilerplate that could never carry the
        phrase, so checking it was a guard that could not fail — the template
        is the file a genericisation pass can actually get wrong.
        """
        text = core_template_path(name).read_text(encoding="utf-8")

        assert "Claude Code Hooks Daemon project" not in text, (
            f"the shipped {name} core document names THIS project. It is "
            "deployed into unrelated client repositories, so it must be "
            "genericised."
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
        deploy_core_docs_if_enabled(tmp_path, _write_config(tmp_path, _ALL_SUBSYSTEMS_ON))

        assert (tmp_path / doc_path).is_file(), (
            f"{named_by} tells the agent to read {doc_path}, but no install "
            "path creates it. Either deploy the document or guard the "
            "reference with an existence check, as plan_number_helper does."
        )


class TestTheDeployFollowsTheConfiguredPath:
    """The document must land where the config POINTS, not at a fixed path.

    ``workflow_docs`` is the string the handler quotes to the agent, and it is
    per-project configuration -- a project whose agent-facing doc tree is not
    ``CLAUDE/`` sets it accordingly. Deploying to a hardcoded ``CLAUDE/`` while
    guidance names the configured path recreates the original defect with an
    extra step: the file exists, just never where the reader was sent.

    The precedent is one line away in the same function. ``plan_dir_name`` is
    threaded through ``bootstrap_plan_workflow`` as a parameter whose docstring
    says it MUST be passed the configured value "so the bootstrap honours a
    project that tracks plans elsewhere (single source of truth)". A core
    document is no different, and a second hardcoded directory is how the two
    drift apart.
    """

    @staticmethod
    def _write_config(project_root: Path, workflow_docs: str) -> Path:
        config_path = project_root / "hooks-daemon.yaml"
        config_path.write_text(
            "plan_workflow:\n"
            "  enabled: true\n"
            "  directory: docs/agent/Plan\n"
            f"  workflow_docs: {workflow_docs}\n",
            encoding="utf-8",
        )
        return config_path

    def test_the_document_lands_where_workflow_docs_points(self, tmp_path: Path) -> None:
        config_path = self._write_config(tmp_path, "docs/agent/PlanWorkflow.md")

        deploy_core_docs_if_enabled(tmp_path, config_path)

        assert (tmp_path / "docs/agent/PlanWorkflow.md").is_file(), (
            "the deploy wrote the workflow document to a hardcoded CLAUDE/ "
            "while plan_workflow.workflow_docs names docs/agent/. The handler "
            "quotes the CONFIGURED path to the agent, so the document exists "
            "somewhere the reader is never sent -- the original defect, one "
            "step removed."
        )

    def test_the_core_lands_beside_it(self, tmp_path: Path) -> None:
        """The override's link to its core is relative (``core/X.core.md``),
        so a core deployed to a different tree leaves that link dangling."""
        config_path = self._write_config(tmp_path, "docs/agent/PlanWorkflow.md")

        deploy_core_docs_if_enabled(tmp_path, config_path)

        assert (tmp_path / "docs/agent/core/PlanWorkflow.core.md").is_file()

    def test_nothing_is_written_to_the_default_tree(self, tmp_path: Path) -> None:
        """A project that moved its doc tree should not also acquire a stray
        ``CLAUDE/`` -- ``markdown_organization`` derives the allowed agent tree
        from the same configuration, so files there are in a location the
        daemon's own handler would refuse a write to."""
        config_path = self._write_config(tmp_path, "docs/agent/PlanWorkflow.md")

        deploy_core_docs_if_enabled(tmp_path, config_path)

        assert not (tmp_path / "CLAUDE" / "PlanWorkflow.md").exists()
        assert not (tmp_path / "CLAUDE" / "core").exists()

    def test_a_renamed_document_is_still_deployed(self, tmp_path: Path) -> None:
        """``workflow_docs`` configures a FILE, not just a directory.

        Honouring only the directory would deploy ``PlanWorkflow.md`` beside a
        config naming ``Planning.md`` — the promise still unkept, just harder
        to spot. This is the one core document a project can knowingly rename,
        because it is the only one with a config key of its own.
        """
        config_path = self._write_config(tmp_path, "docs/agent/Planning.md")

        deploy_core_docs_if_enabled(tmp_path, config_path)

        assert (tmp_path / "docs/agent/Planning.md").is_file()

    def test_a_renamed_document_still_points_at_its_core(self, tmp_path: Path) -> None:
        """Renaming the override must not orphan it from the core it extends;
        the core keeps its canonical name, so the link has to survive."""
        config_path = self._write_config(tmp_path, "docs/agent/Planning.md")

        deploy_core_docs_if_enabled(tmp_path, config_path)

        text = (tmp_path / "docs/agent/Planning.md").read_text(encoding="utf-8")

        assert core_reference_line("PlanWorkflow", "docs/agent") in text

    def test_a_top_level_document_lands_at_the_project_root(self, tmp_path: Path) -> None:
        """A bare filename has no directory part. ``PurePosixPath.parent`` is
        ``.`` there, which must join back to the project root rather than
        creating a literal ``./`` directory or raising."""
        config_path = self._write_config(tmp_path, "PlanWorkflow.md")

        deploy_core_docs_if_enabled(tmp_path, config_path)

        assert (tmp_path / "PlanWorkflow.md").is_file()
        assert (tmp_path / "core" / "PlanWorkflow.core.md").is_file()

    def test_the_default_is_unchanged(self, tmp_path: Path) -> None:
        """The overwhelmingly common case must keep working untouched."""
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text("plan_workflow:\n  enabled: true\n", encoding="utf-8")

        deploy_core_docs_if_enabled(tmp_path, config_path)

        assert (tmp_path / "CLAUDE" / "PlanWorkflow.md").is_file()
        assert (tmp_path / "CLAUDE" / "core" / "PlanWorkflow.core.md").is_file()


class TestTheDeployIsNotGatedOnTheWrongSubsystem:
    """A stock install must still get the documents its guidance names.

    ``plan_workflow.enabled`` defaults to FALSE — it is opt-in. Hanging every
    core document off the plan-workflow bootstrap therefore fixed the reported
    client (who had enabled it) and left a stock install exactly as broken:
    ``worktree_file_copy`` ships in the default profile and names
    ``CLAUDE/Worktree.md`` in its rule text unconditionally, so the document
    has to exist whether or not the project tracks plans.

    Each document is gated on the subsystem whose guidance NAMES it, which is
    the only gate that means anything: the promise is made by the surface that
    quotes the path, so that surface decides whether it has to be kept.
    """

    @staticmethod
    def _config(project_root: Path, body: str) -> Path:
        config_path = project_root / "hooks-daemon.yaml"
        config_path.write_text(body, encoding="utf-8")
        return config_path

    def test_a_stock_install_still_gets_the_worktree_document(self, tmp_path: Path) -> None:
        config_path = self._config(tmp_path, "plan_workflow:\n  enabled: false\n")

        deploy_core_docs_if_enabled(tmp_path, config_path)

        assert (tmp_path / "CLAUDE" / "Worktree.md").is_file(), (
            "worktree_file_copy's BLOCKING rule text names CLAUDE/Worktree.md "
            "in every install, but the document was only deployed when the "
            "plan workflow — an opt-in that defaults to off — was enabled."
        )

    def test_the_plan_document_waits_for_its_own_subsystem(self, tmp_path: Path) -> None:
        """Nothing is scattered into a project that did not ask for it: the
        plan-workflow document is guidance for a workflow that is switched
        off, and no surface quotes its path while it is."""
        config_path = self._config(tmp_path, "plan_workflow:\n  enabled: false\n")

        deploy_core_docs_if_enabled(tmp_path, config_path)

        assert not (tmp_path / "CLAUDE" / "PlanWorkflow.md").exists()

    def test_the_docs_ruleset_follows_the_documentation_subsystem(self, tmp_path: Path) -> None:
        """docs_qa names CLAUDE/DocumentationStrategy.md in a runtime finding,
        and docs_qa is switched on by `documentation.enabled` — which is
        independent of the plan workflow entirely."""
        config_path = self._config(
            tmp_path, "documentation:\n  enabled: true\nplan_workflow:\n  enabled: false\n"
        )

        deploy_core_docs_if_enabled(tmp_path, config_path)

        assert (tmp_path / "CLAUDE" / "DocumentationStrategy.md").is_file()
        assert (tmp_path / "CLAUDE" / "core" / "DocumentationStrategy.core.md").is_file()

    def test_a_disabled_subsystem_deploys_no_ruleset(self, tmp_path: Path) -> None:
        config_path = self._config(tmp_path, "documentation:\n  enabled: false\n")

        deploy_core_docs_if_enabled(tmp_path, config_path)

        assert not (tmp_path / "CLAUDE" / "DocumentationStrategy.md").exists()

    def test_nothing_is_created_when_no_document_is_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A project that enables nothing must not acquire empty directories.

        Unreachable with today's roster, because ``Worktree`` is unconditional
        — which is exactly why it needs exercising deliberately rather than
        being left as a branch nobody has ever run. The roster is data; the
        moment every entry becomes conditional this is the code that decides
        whether the project gets a bare ``CLAUDE/core/`` it never asked for.
        """
        monkeypatch.setattr(
            core_docs,
            "CORE_DOCS",
            (core_docs.CoreDoc("PlanWorkflow", lambda config: config.plan_workflow.enabled),),
        )
        config_path = self._config(tmp_path, "plan_workflow:\n  enabled: false\n")

        result = core_docs.deploy_core_docs_if_enabled(tmp_path, config_path)

        assert result.success
        assert not (tmp_path / "CLAUDE").exists(), (
            "a project with no core documents enabled was given an empty "
            "CLAUDE/ tree it never asked for."
        )
        assert result.messages == ["No core documents enabled in config (deployment skipped)"]

    def test_an_absent_config_is_not_an_error(self, tmp_path: Path) -> None:
        """Mirrors ``deploy_plan_workflow_if_enabled``: a missing file yields
        model defaults rather than a failure, so a first install works."""
        result = deploy_core_docs_if_enabled(tmp_path, tmp_path / "nonexistent.yaml")

        assert result.success


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
