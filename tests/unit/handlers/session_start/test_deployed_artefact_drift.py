"""Deployed daemon-owned artefacts are compared against their templates.

Plan 00377 N6. `agents install --force` and `deploy-core-docs` (N4, N5) made a
drifted deployed file REPAIRABLE. Neither made it VISIBLE: nothing compared a
deployed artefact with the template it came from, so a stale copy sat there
until somebody happened to redeploy. Measured while fixing N5 — the same stale
header sentence was in `mkplan.bash` AND in a deployed agent, unreported.

**Presence is the signal, and that is the whole design.** Only artefacts
actually on disk are compared. A core document whose gating config is off is
absent BY DESIGN, so it is never reported — the trap that caught the N5 test
fixture. An absent `mkplan.bash` is `plan_workflow_asset_checker`'s report, not
this one's, so the two handlers cannot both shout about the same project.
"""

from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.handlers.session_start.deployed_artefact_drift import (
    DeployedArtefactDriftHandler,
)
from claude_code_hooks_daemon.install.agent_assets import (
    AGENTS_DIR_PARTS,
    SHIPPED_AGENTS,
    spec_source_path,
)
from claude_code_hooks_daemon.install.core_docs import (
    CORE_DOCS,
    CORE_DOCS_DIR,
    CORE_SUFFIX,
    core_template_path,
)
from claude_code_hooks_daemon.install.plan_workflow import (
    MKPLAN_SCRIPT_NAME,
    mkplan_template_path,
)

_PATCH_TARGET = (
    "claude_code_hooks_daemon.handlers.session_start."
    "deployed_artefact_drift.ProjectContext.project_root"
)


def _session_start_input(transcript: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"hook_event_name": "SessionStart"}
    if transcript is not None:
        payload["transcript_path"] = transcript
    return payload


def _handle(root: Path) -> list[str]:
    handler = DeployedArtefactDriftHandler()
    with patch(_PATCH_TARGET, return_value=root):
        return list(handler.handle(_session_start_input()).context)


def _deploy_agent_verbatim(root: Path, index: int = 0) -> Path:
    spec = SHIPPED_AGENTS[index]
    target = root.joinpath(*AGENTS_DIR_PARTS) / f"{spec.name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(spec_source_path(spec).read_text())
    return target


def _deploy_core_doc_verbatim(root: Path) -> Path:
    name = CORE_DOCS[0].name
    target = root / CORE_DOCS_DIR / f"{name}{CORE_SUFFIX}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(core_template_path(name).read_text())
    return target


def _deploy_mkplan_verbatim(root: Path) -> Path:
    target = root / "CLAUDE" / "Plan" / MKPLAN_SCRIPT_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(mkplan_template_path().read_text())
    return target


class TestNothingToSay:
    def test_an_empty_project_is_silent(self, tmp_path: Path) -> None:
        """Absent is not drifted — and absence already has its own reporter."""
        assert _handle(tmp_path) == []

    def test_pristine_deployments_are_silent(self, tmp_path: Path) -> None:
        _deploy_agent_verbatim(tmp_path)
        _deploy_core_doc_verbatim(tmp_path)
        _deploy_mkplan_verbatim(tmp_path)
        assert _handle(tmp_path) == []

    def test_a_core_doc_whose_gate_is_off_is_not_reported(self, tmp_path: Path) -> None:
        """The N5 fixture trap: not deployed BY DESIGN, so not drift.

        Compared only what is on disk, so a project that never deploys a given
        core document can never be told it drifted.
        """
        _deploy_mkplan_verbatim(tmp_path)
        report = "\n".join(_handle(tmp_path))
        for doc in CORE_DOCS:
            assert doc.name not in report


class TestDriftIsReported:
    def test_a_drifted_core_doc_is_named_with_its_repair(self, tmp_path: Path) -> None:
        target = _deploy_core_doc_verbatim(tmp_path)
        target.write_text("stale\n")
        report = "\n".join(_handle(tmp_path))
        assert target.name in report
        assert "deploy-core-docs" in report

    def test_a_drifted_mkplan_is_named_with_its_repair(self, tmp_path: Path) -> None:
        target = _deploy_mkplan_verbatim(tmp_path)
        target.write_text("#!/bin/bash\n# hand-edited\n")
        report = "\n".join(_handle(tmp_path))
        assert MKPLAN_SCRIPT_NAME in report
        assert "deploy-plan-workflow" in report

    def test_a_drifted_agent_is_named_with_its_repair(self, tmp_path: Path) -> None:
        target = _deploy_agent_verbatim(tmp_path)
        target.write_text("# my own edits\n")
        report = "\n".join(_handle(tmp_path))
        assert SHIPPED_AGENTS[0].name in report
        assert "agents install" in report

    def test_a_customised_agent_is_offered_the_force_escape(self, tmp_path: Path) -> None:
        """A plain install refuses a customised copy — N4's whole point.

        Naming the refusing command alone would repeat the circular
        remediation N4 fixed, so the escape is named here too.
        """
        target = _deploy_agent_verbatim(tmp_path)
        target.write_text("# my own edits\n")
        assert "--force" in "\n".join(_handle(tmp_path))

    def test_every_drifted_artefact_is_listed_not_just_the_first(self, tmp_path: Path) -> None:
        """A report that stops at the first hit trains the reader to redeploy
        once and assume the rest is clean."""
        core = _deploy_core_doc_verbatim(tmp_path)
        core.write_text("stale\n")
        mkplan = _deploy_mkplan_verbatim(tmp_path)
        mkplan.write_text("# hand-edited\n")
        report = "\n".join(_handle(tmp_path))
        assert core.name in report
        assert MKPLAN_SCRIPT_NAME in report


class TestMatching:
    def test_a_resume_session_does_not_match(self, tmp_path: Path) -> None:
        transcript = tmp_path / "t.jsonl"
        transcript.write_text("x" * 200)
        handler = DeployedArtefactDriftHandler()
        assert handler.matches(_session_start_input(str(transcript))) is False

    def test_a_new_session_matches(self) -> None:
        handler = DeployedArtefactDriftHandler()
        assert handler.matches(_session_start_input()) is True
