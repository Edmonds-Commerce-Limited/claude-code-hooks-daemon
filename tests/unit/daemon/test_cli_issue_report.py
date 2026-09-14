"""The `issue-report` CLI verb (Plan 00403 Task 2.1).

The verb that produces a filable upstream issue body. Its contract differs from
`bug-report` in the way that matters: `bug-report` writes a LOCAL diagnostic
and scrubs what it collected, while this collects only what
`issue_report.ReportFields` names and refuses outright when a check fails.

The refusal path carries the load here. A refused report must leave NO file
behind — a document that exists is a document that can be filed by mistake, and
a public issue cannot be retracted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import cmd_issue_report
from claude_code_hooks_daemon.version import __version__

_REPRODUCTION = "1. mkdir -p untracked/scratch/repro\n2. Write untracked/scratch/repro/a.py\n"


@pytest.fixture(autouse=True)
def mock_git_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tmp_path project is not a git checkout, and config validation insists.

    The same shim the bug-report suite uses, for the same reason.
    """
    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_repo_name",
        lambda project_root: "test-repo",
    )
    monkeypatch.setattr(
        "claude_code_hooks_daemon.core.project_context.ProjectContext._get_git_toplevel",
        lambda project_root: project_root,
    )


@pytest.fixture(autouse=True)
def reset_project_context() -> None:
    """The context is a singleton; leaving it set leaks one test's root into the next."""
    ProjectContext._initialized = False


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A client project: `get_project_path` requires a real `.claude/`."""
    root = tmp_path / "client"
    (root / ".claude" / "hooks-daemon" / "untracked").mkdir(parents=True)
    (root / ".claude" / "hooks-daemon.yaml").write_text(
        "version: '1.0'\ndaemon:\n  log_level: INFO\n"
    )
    return root


def _fields_file(tmp_path: Path, **overrides: object) -> Path:
    data: dict[str, object] = {
        "summary": "sed_blocker denies a read-only pipeline",
        "handler": "sed_blocker",
        "expected": "A pipeline that cannot write is allowed.",
        "observed": "It is denied.",
        "reproduction": _REPRODUCTION,
        "config_considered": [
            {
                "option": "handlers.pre_tool_use.sed_blocker.enabled",
                "why_insufficient": "Disabling removes the protection entirely.",
            }
        ],
        "source_citation": "src/claude_code_hooks_daemon/version.py:1",
    }
    data.update(overrides)
    path = tmp_path / "fields.json"
    path.write_text(json.dumps(data))
    return path


def _args(project: Path, fields: Path, **overrides: object) -> argparse.Namespace:
    namespace = argparse.Namespace(
        fields=str(fields),
        output=str(project / "report.md"),
        latest=None,
        project_root=str(project),
    )
    for key, value in overrides.items():
        setattr(namespace, key, value)
    return namespace


class TestAGoodReport:
    def test_it_exits_zero(self, project: Path, tmp_path: Path) -> None:
        assert cmd_issue_report(_args(project, _fields_file(tmp_path))) == 0

    def test_it_writes_the_document(self, project: Path, tmp_path: Path) -> None:
        cmd_issue_report(_args(project, _fields_file(tmp_path)))

        assert (project / "report.md").exists()

    def test_the_document_verifies_against_its_own_provenance(
        self, project: Path, tmp_path: Path
    ) -> None:
        from claude_code_hooks_daemon.issue_report.provenance import verify_document

        cmd_issue_report(_args(project, _fields_file(tmp_path)))

        assert verify_document((project / "report.md").read_text()) == ()

    def test_it_records_the_running_version(self, project: Path, tmp_path: Path) -> None:
        cmd_issue_report(_args(project, _fields_file(tmp_path)))

        assert __version__ in (project / "report.md").read_text()


class TestARefusedReport:
    def test_a_leaking_reproduction_exits_nonzero(self, project: Path, tmp_path: Path) -> None:
        fields = _fields_file(tmp_path, reproduction="Edit /home/jbloggs/acme/app.py")

        assert cmd_issue_report(_args(project, fields)) != 0

    def test_a_refusal_leaves_no_file(self, project: Path, tmp_path: Path) -> None:
        """A document that exists is a document that can be filed by mistake."""
        fields = _fields_file(tmp_path, reproduction="Edit /home/jbloggs/acme/app.py")

        cmd_issue_report(_args(project, fields))

        assert not (project / "report.md").exists()

    def test_the_refusal_is_explained(
        self, project: Path, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        fields = _fields_file(tmp_path, reproduction="Edit /home/jbloggs/acme/app.py")

        cmd_issue_report(_args(project, fields))

        assert "untracked/scratch" in capsys.readouterr().out

    def test_a_dead_citation_is_refused(self, project: Path, tmp_path: Path) -> None:
        fields = _fields_file(
            tmp_path, source_citation="src/claude_code_hooks_daemon/version.py:99999"
        )

        assert cmd_issue_report(_args(project, fields)) != 0


class TestMalformedInput:
    def test_a_missing_fields_file_is_reported_not_raised(
        self, project: Path, tmp_path: Path
    ) -> None:
        args = _args(project, tmp_path / "absent.json")

        assert cmd_issue_report(args) != 0

    def test_invalid_json_is_reported_not_raised(self, project: Path, tmp_path: Path) -> None:
        path = tmp_path / "fields.json"
        path.write_text("{not json")

        assert cmd_issue_report(_args(project, path)) != 0

    def test_a_json_list_is_rejected_rather_than_treated_as_fields(
        self, project: Path, tmp_path: Path
    ) -> None:
        """`json.loads` happily returns a list; `.get` on it would raise."""
        path = tmp_path / "fields.json"
        path.write_text("[1, 2, 3]")

        assert cmd_issue_report(_args(project, path)) != 0


class TestWhatIsNeverWritten:
    def test_the_hostname_does_not_appear(self, project: Path, tmp_path: Path) -> None:
        """Not scrubbed out — never collected. See `ReportFields`."""
        import socket

        cmd_issue_report(_args(project, _fields_file(tmp_path)))
        report = (project / "report.md").read_text()
        hostname = socket.gethostname()

        if len(hostname) >= 4:
            assert hostname not in report
