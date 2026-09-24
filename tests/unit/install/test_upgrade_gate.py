"""The pre-deploy upgrade gate (Plan 00376 Phase 3).

The gate decides, once the daemon checkout sits on the target and before
anything is deployed, whether the upgrade may go on. It never asks whether a
terminal is attached: a caller with something to read stops until it passes
``--skip-reading-confirmation``, and a change that breaks the project (a MAJOR
bump, a crossed manifest declaring ``breaking: true``, or a ``critical``
pre-upgrade task detected in the project) also needs the owner's one-shot
approval.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.upgrade_gate import (
    APPROVAL_SUBDIR,
    GateReport,
    GateVerdict,
    approval_key,
    breaking_manifests,
    evaluate_gate,
    format_gate_report,
    main,
)
from claude_code_hooks_daemon.utils.one_shot_approval import OneShotApprovalStore

_TASK = """# Task: {title}

**Type**: workflow-change
**Severity**: {severity}
**Applies to**: all
**Idempotent**: yes
**Detect**: `{pattern}`
**Detect in**: `*.sh`

## Why

Because.

## How to detect if this applies to you

Look.

## How to handle

Do it.

## How to confirm

Check it.
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def daemon_dir(tmp_path: Path) -> Path:
    root = tmp_path / "daemon"
    (root / "CLAUDE" / "UPGRADES" / "config-changes").mkdir(parents=True)
    return root


@pytest.fixture
def upgrades(daemon_dir: Path) -> Path:
    return daemon_dir / "CLAUDE" / "UPGRADES"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    _write(root / "tools" / "qa.sh", "set -e\nhooks-daemon plan-qa --json | jq .level\n")
    return root


@pytest.fixture
def untracked(tmp_path: Path) -> Path:
    return tmp_path / "untracked"


def _guide(upgrades: Path, name: str) -> Path:
    major = name.split(".")[0]
    return _write(upgrades / major / name / f"{name}.md", f"# {name}\n")


def _pre_task(
    upgrades: Path, guide: str, name: str, *, severity: str = "recommended", pattern: str
) -> Path:
    major = guide.split(".")[0]
    return _write(
        upgrades / major / guide / "pre-upgrade-tasks" / name,
        _TASK.format(title=name, severity=severity, pattern=pattern),
    )


def _gate(
    daemon_dir: Path,
    project: Path,
    untracked: Path,
    frm: str,
    to: str,
    *,
    acknowledged: bool = False,
    include_unreleased: bool = False,
) -> GateReport:
    return evaluate_gate(
        daemon_dir=daemon_dir,
        project_root=project,
        from_version=frm,
        to_version=to,
        include_unreleased=include_unreleased,
        acknowledged=acknowledged,
        untracked_dir=untracked,
    )


class TestNothingToRead:
    def test_proceeds_silently(self, daemon_dir: Path, project: Path, untracked: Path) -> None:
        report = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.verdict is GateVerdict.PROCEED
        assert report.guides == []
        assert "No upgrade guides" in format_gate_report(report)

    def test_a_pre_task_that_detects_nothing_stays_silent(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _pre_task(upgrades, "v3.64.0-to-v3.65.0", "01-quiet.md", pattern="absent-token")
        report = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.verdict is GateVerdict.PROCEED
        assert "01-quiet.md" not in format_gate_report(report)


class TestReadingNeedsAcknowledgement:
    def test_a_crossed_guide_stops_an_unacknowledged_caller(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        guide = _guide(upgrades, "v3.64.0-to-v3.65.0")
        report = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        text = format_gate_report(report)
        assert str(guide) in text
        assert "--skip-reading-confirmation" in text

    def test_the_flag_lets_it_through(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _guide(upgrades, "v3.64.0-to-v3.65.0")
        report = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0", acknowledged=True)
        assert report.verdict is GateVerdict.PROCEED

    def test_a_detected_pre_task_is_named_at_file_and_line(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _pre_task(upgrades, "v3.64.0-to-v3.65.0", "01-rename.md", pattern="plan-qa[^\\n]*--json")
        report = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        text = format_gate_report(report)
        assert "01-rename.md" in text
        assert "tools/qa.sh:2" in text

    def test_staged_documents_count_on_a_branch_install(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _write(upgrades / "UNRELEASED" / "release-notes" / "01-note.md", "# note\n")
        release = _gate(daemon_dir, project, untracked, "3.66.0", "3.66.0")
        branch = _gate(daemon_dir, project, untracked, "3.66.0", "3.66.0", include_unreleased=True)
        assert release.verdict is GateVerdict.PROCEED
        assert branch.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT

    @pytest.mark.parametrize(
        ("frm", "to"), [("unknown", "3.65.0"), ("3.64.0", "0123abc"), ("unknown", "unknown")]
    )
    def test_a_range_it_cannot_read_cannot_be_waved_through(
        self, daemon_dir: Path, project: Path, untracked: Path, frm: str, to: str
    ) -> None:
        stopped = _gate(daemon_dir, project, untracked, frm, to)
        assert stopped.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        assert "cannot tell which upgrade guides" in format_gate_report(stopped)
        acknowledged = _gate(daemon_dir, project, untracked, frm, to, acknowledged=True)
        assert acknowledged.verdict is GateVerdict.PROCEED

    def test_a_downgrade_crosses_no_guide(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _guide(upgrades, "v3.64.0-to-v3.65.0")
        report = _gate(daemon_dir, project, untracked, "3.65.0", "3.64.0")
        assert report.verdict is GateVerdict.PROCEED
        assert "downgrade" in format_gate_report(report)


class TestEscalation:
    def test_a_major_bump_needs_the_owner(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        report = _gate(daemon_dir, project, untracked, "3.66.0", "4.0.0", acknowledged=True)
        assert report.verdict is GateVerdict.NEEDS_APPROVAL
        assert any("MAJOR" in reason for reason in report.escalations)
        text = format_gate_report(report)
        assert "approve-upgrade 4.0.0" in text
        assert str(OneShotApprovalStore(APPROVAL_SUBDIR).path(untracked, "4.0.0")) in text

    def test_a_crossed_breaking_manifest_needs_the_owner(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _write(upgrades / "config-changes" / "v3.65.0.yaml", 'version: "3.65.0"\nbreaking: true\n')
        report = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0", acknowledged=True)
        assert report.verdict is GateVerdict.NEEDS_APPROVAL
        assert any("v3.65.0.yaml" in reason for reason in report.escalations)

    def test_a_critical_pre_task_with_hits_needs_the_owner(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _pre_task(
            upgrades,
            "v3.64.0-to-v3.65.0",
            "01-rename.md",
            severity="critical",
            pattern="plan-qa[^\\n]*--json",
        )
        report = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0", acknowledged=True)
        assert report.verdict is GateVerdict.NEEDS_APPROVAL
        assert any("01-rename.md" in reason for reason in report.escalations)

    def test_a_critical_pre_task_without_hits_does_not_escalate(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _pre_task(
            upgrades, "v3.64.0-to-v3.65.0", "01-rename.md", severity="critical", pattern="absent"
        )
        report = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.escalations == []

    def test_the_owners_approval_is_consumed_by_the_upgrade_it_lets_through(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        store = OneShotApprovalStore(APPROVAL_SUBDIR)
        marker = store.record(untracked, "4.0.0")
        report = _gate(daemon_dir, project, untracked, "3.66.0", "v4.0.0", acknowledged=True)
        assert report.verdict is GateVerdict.PROCEED
        assert report.approval_consumed
        assert not marker.exists()

    def test_an_approval_is_not_spent_while_reading_is_unacknowledged(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        marker = OneShotApprovalStore(APPROVAL_SUBDIR).record(untracked, "4.0.0")
        report = _gate(daemon_dir, project, untracked, "3.66.0", "4.0.0")
        assert report.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        assert marker.exists()


class TestBreakingManifests:
    def test_only_the_crossed_range_counts(self, upgrades: Path) -> None:
        for version in ("3.64.0", "3.65.0", "3.66.0"):
            _write(upgrades / "config-changes" / f"v{version}.yaml", "breaking: true\n")
        _write(upgrades / "config-changes" / "v3.65.1.yaml", "breaking: false\n")
        found = breaking_manifests(upgrades, "3.64.0", "3.65.1", include_unreleased=False)
        assert [path.name for path in found] == ["v3.65.0.yaml"]

    def test_staged_manifests_count_on_a_branch_install_whatever_their_name(
        self, upgrades: Path
    ) -> None:
        _write(upgrades / "UNRELEASED" / "config-changes" / "v3.67.0.yaml", "breaking: true\n")
        assert breaking_manifests(upgrades, "3.66.0", "3.66.0", include_unreleased=False) == []
        found = breaking_manifests(upgrades, "3.66.0", "3.66.0", include_unreleased=True)
        assert [path.name for path in found] == ["v3.67.0.yaml"]


class TestApprovalKey:
    @pytest.mark.parametrize("raw", ["4.0.0", "v4.0.0", "4.0.0+main.abc1234", "v4.0"])
    def test_every_spelling_of_a_release_shares_one_key(self, raw: str) -> None:
        assert approval_key(raw) == "4.0.0"


class TestVerdictExitCodes:
    def test_each_verdict_has_its_own_exit_code(self) -> None:
        codes = {verdict.exit_code for verdict in GateVerdict}
        assert len(codes) == len(GateVerdict)
        assert GateVerdict.PROCEED.exit_code == 0
        assert 1 not in codes
        assert 2 not in codes


class TestMain:
    def _argv(self, daemon_dir: Path, project: Path, untracked: Path, *extra: str) -> list[str]:
        return [
            "--daemon-dir",
            str(daemon_dir),
            "--project-root",
            str(project),
            "--untracked-dir",
            str(untracked),
            *extra,
        ]

    def test_the_exit_code_is_the_verdict(
        self,
        daemon_dir: Path,
        upgrades: Path,
        project: Path,
        untracked: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _guide(upgrades, "v3.64.0-to-v3.65.0")
        argv = self._argv(daemon_dir, project, untracked, "--from", "v3.64.0", "--to", "3.65.0")
        assert main(argv) == GateVerdict.NEEDS_ACKNOWLEDGEMENT.exit_code
        assert "REQUIRED READING" in capsys.readouterr().err
        assert main([*argv, "--acknowledged"]) == 0

    def test_include_unreleased_is_an_explicit_flag(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _write(upgrades / "UNRELEASED" / "release-notes" / "01-note.md", "# note\n")
        argv = self._argv(daemon_dir, project, untracked, "--from", "3.66.0", "--to", "3.66.0")
        assert main(argv) == 0
        assert main([*argv, "--include-unreleased"]) == GateVerdict.NEEDS_ACKNOWLEDGEMENT.exit_code
