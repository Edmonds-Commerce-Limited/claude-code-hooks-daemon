"""Tests for check ``unenforced-approval-gate`` (Plan 00367, DBF net).

Originating instance: the daemon-owned ``PlanWorkflow.core.md`` template told
every agent to "ask user for approval before marking plan complete" while the
daemon's own gates (holding-area criterion, terminal-placement hint, archive
atomicity, the supervisor's "work until complete" goal) all drive an agent
straight through to Complete. An agent either stalls a finished plan on a
human who never asked for the gate, or ignores the doc. Either way the
deployed guidance and the daemon's intended workflow have drifted apart.

The class: a daemon-owned core document that prescribes a human approval
gate without naming the config key that makes the daemon enforce it. The net
reads the core templates and fails on any such instruction; the fix is to
enforce the gate behind a named key, cite that key in the same paragraph, or
delete the instruction.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.docs_qa.checks import unenforced_approval_gate as module
from claude_code_hooks_daemon.docs_qa.checks.unenforced_approval_gate import CHECK_ID, CHECKS
from claude_code_hooks_daemon.docs_qa.context import edit_context, staged_context, sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import build_and_save_corpus
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.types import CheckContext, CheckStage, Finding, Severity

_CORE_REL = Path("CLAUDE") / "core"
_ORIGINATING_LINE = "09. **Ask user for approval** before marking plan complete\n"
_KNOWN_KEY = "plan_workflow.close_requires_human_approval"


def _run(stage: CheckStage, context: CheckContext) -> list[Finding]:
    for spec in CHECKS:
        if spec.stage is stage:
            return spec.run(context)
    raise AssertionError(f"no {stage} check registered")


def _write_core(root: Path, name: str, text: str) -> Path:
    directory = root / _CORE_REL
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")


@pytest.fixture(autouse=True)
def _known_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_key_exists", lambda key: key == _KNOWN_KEY)


class TestRegistration:
    def test_registers_all_three_stages(self) -> None:
        assert {spec.stage for spec in CHECKS} == {
            CheckStage.EDIT,
            CheckStage.STAGED,
            CheckStage.SWEEP,
        }
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)


class TestTheNetFiresOnTheOriginatingInstance:
    def test_the_plan_workflow_line_is_a_block_at_edit(self, tmp_path: Path) -> None:
        path = _write_core(tmp_path, "PlanWorkflow.core.md", "")
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=path,
            file_content="## Guidelines\n\n" + _ORIGINATING_LINE,
            file_exists_before=True,
            file_content_before="## Guidelines\n",
        )
        findings = _run(CheckStage.EDIT, context)
        assert len(findings) == 1
        assert findings[0].check_id == CHECK_ID
        assert findings[0].severity is Severity.BLOCK
        assert findings[0].path == str(_CORE_REL / "PlanWorkflow.core.md")
        assert ":3" in findings[0].message
        assert "config key" in findings[0].remediation

    @pytest.mark.parametrize(
        "line",
        [
            "4. Get stakeholder approval (if needed)",
            "6. Shows plan to user for approval",
            "- ❌ **NOT ALLOWED**: Parent → Main project (requires human approval)",
            "❌ **MUST ask human approval first**",
            "1. ✋ **STOP** - Ask human for approval",
            "# STEP 3: ✋ STOP - Ask human for final approval!",
        ],
    )
    def test_the_other_shapes_found_in_the_sweep_are_instances(
        self, tmp_path: Path, line: str
    ) -> None:
        path = _write_core(tmp_path, "Worktree.core.md", "")
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=path,
            file_content=line + "\n",
            file_exists_before=False,
        )
        assert len(_run(CheckStage.EDIT, context)) == 1


class TestWhatIsNotAnInstance:
    @pytest.mark.parametrize(
        "line",
        [
            "- ✅ **ALLOWED**: Child → Parent worktree (automatic, no approval needed)",
            "git merge worktree-plan  # WRONG - no human approval",
            "### ❌ Merging Without Approval",
            "Filing a non-defect is automatic and needs NO human approval.",
            '7. Report "approved" OR "rejected with specific gaps"',
            "| Action | Approval Required | Cleanup |",
        ],
    )
    def test_a_negation_or_a_report_verdict_is_not_a_gate(self, tmp_path: Path, line: str) -> None:
        path = _write_core(tmp_path, "Worktree.core.md", "")
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=path,
            file_content=line + "\n",
            file_exists_before=False,
        )
        assert _run(CheckStage.EDIT, context) == []

    def test_a_gate_that_names_its_enforcing_key_is_in_sync(self, tmp_path: Path) -> None:
        path = _write_core(tmp_path, "PlanWorkflow.core.md", "")
        content = (
            "09. **Close a plan when it is fully complete.** When the project\n"
            f"    sets `{_KNOWN_KEY}: true` the daemon refuses an agent's\n"
            "    flip and a human closes it; ask the owner for approval then.\n"
        )
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=path,
            file_content=content,
            file_exists_before=False,
        )
        assert _run(CheckStage.EDIT, context) == []

    def test_a_cited_key_the_daemon_does_not_have_is_still_a_finding(self, tmp_path: Path) -> None:
        path = _write_core(tmp_path, "PlanWorkflow.core.md", "")
        content = "Ask the owner for approval first (`plan_workflow.no_such_key`).\n"
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=path,
            file_content=content,
            file_exists_before=False,
        )
        findings = _run(CheckStage.EDIT, context)
        assert len(findings) == 1
        assert "plan_workflow.no_such_key" in findings[0].message

    @pytest.mark.parametrize("rel", ["CLAUDE/AgentTeam.md", "CLAUDE/core/Notes.md"])
    def test_a_document_that_is_not_a_deployed_core_doc_is_not_scanned(
        self, tmp_path: Path, rel: str
    ) -> None:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_ORIGINATING_LINE, encoding="utf-8")
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=path,
            file_content=_ORIGINATING_LINE,
            file_exists_before=False,
        )
        assert _run(CheckStage.EDIT, context) == []

    def test_a_pre_existing_instance_still_blocks_at_edit(self, tmp_path: Path) -> None:
        """No grandfathering: a baseline is the owner's decision, not the check's."""
        path = _write_core(tmp_path, "PlanWorkflow.core.md", _ORIGINATING_LINE)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=path,
            file_content="Intro.\n" + _ORIGINATING_LINE,
            file_exists_before=True,
            file_content_before=_ORIGINATING_LINE,
        )
        findings = _run(CheckStage.EDIT, context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.BLOCK


class TestStagedAndSweep:
    def test_a_new_instance_in_a_staged_core_template_blocks_the_commit(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        _write_core(root, "PlanWorkflow.core.md", "## Guidelines\n\n" + _ORIGINATING_LINE)
        _git(root, "add", "-A")
        context = staged_context(project_root=root, policy=DocumentationPolicy())
        findings = _run(CheckStage.STAGED, context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.BLOCK

    def test_an_instance_already_in_head_still_blocks_when_staged(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _init_repo(root)
        path = _write_core(root, "PlanWorkflow.core.md", _ORIGINATING_LINE)
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "initial")
        path.write_text("Intro.\n" + _ORIGINATING_LINE, encoding="utf-8")
        _git(root, "add", "-A")
        context = staged_context(project_root=root, policy=DocumentationPolicy())
        findings = _run(CheckStage.STAGED, context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.BLOCK

    def test_the_sweep_counts_every_instance_as_advisory(self, tmp_path: Path) -> None:
        _write_core(
            tmp_path,
            "PlanWorkflow.core.md",
            _ORIGINATING_LINE + "\n4. Get stakeholder approval (if needed)\n",
        )
        _write_core(tmp_path, "Clean.core.md", "Close a plan when it is complete.\n")
        policy = DocumentationPolicy()
        corpus = build_and_save_corpus(tmp_path, policy, tmp_path / "untracked" / "index.json")
        context = sweep_context(project_root=tmp_path, policy=policy, corpus=corpus)
        findings = _run(CheckStage.SWEEP, context)
        assert len(findings) == 2
        assert {finding.severity for finding in findings} == {Severity.ADVISE}

    def test_a_core_doc_the_sweep_cannot_read_is_reported_not_skipped(self, tmp_path: Path) -> None:
        """A silent skip would count an unreadable file as a clean one."""
        doc = _write_core(tmp_path, "PlanWorkflow.core.md", _ORIGINATING_LINE)
        policy = DocumentationPolicy()
        corpus = build_and_save_corpus(tmp_path, policy, tmp_path / "untracked" / "index.json")
        doc.unlink()
        context = sweep_context(project_root=tmp_path, policy=policy, corpus=corpus)
        findings = _run(CheckStage.SWEEP, context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE
        assert "could not be read" in findings[0].message


class TestTheKeyResolverReadsTheRealConfig:
    def test_a_real_key_resolves_and_a_missing_one_does_not(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.undo()
        assert module.config_key_exists("plan_workflow.enabled") is True
        assert module.config_key_exists("plan_workflow.qa.edit_mode") is True
        assert module.config_key_exists("plan_workflow.no_such_key") is False
        assert module.config_key_exists("nonsense") is False
