"""``validate-project-handlers`` must flag a decision the event cannot deliver.

A project handler is a supported extension point that lives in a CLIENT's
repository. ``tests/integration/test_every_handler_response_validates.py``
sweeps only ``claude_code_hooks_daemon.handlers``, so for a client this defect
is not unreachable — it is **undetectable** until it silently misfires.

``to_json`` logs it at runtime, but a runtime log arrives once the response is
already being built for a live event: the handler has shipped, and the log is
buried in the daemon's own file. ``validate-project-handlers`` is the surface a
developer actually runs while writing the handler, which is where this belongs.

**Reported as a warning, not a failure.** The scan reads the class's AST, so it
can over-attribute — a handler that merely COMPARES against ``Decision.DENY``
looks like one that returns it. A false failure that breaks a client's
validation command is worse than a false warning, and the runtime guard already
catches the real thing. The warning is loud and names the consequence.
"""

import argparse
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext


@pytest.fixture(autouse=True)
def mock_git_checks(monkeypatch: Any) -> None:
    """Mock git repository checks for tests running in tmp directories."""
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
    """Reset ProjectContext singleton between tests."""
    ProjectContext._initialized = False


def _setup_project(tmp_path: Path) -> Path:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "hooks-daemon").mkdir()
    (claude_dir / "hooks-daemon.yaml").write_text("version: '1.0'\ndaemon:\n  log_level: INFO\n")
    return tmp_path


_HANDLER_TEMPLATE = '''"""Project handler probe."""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision


class ProbeHandler(Handler):
    """Returns {decision_name} on this event."""

    def __init__(self) -> None:
        super().__init__(handler_id="probe-handler", priority=50, terminal=False)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.{decision_name}, reason="probe reason")

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [
            AcceptanceTest(
                title="probe",
                command="echo probe",
                description="probe",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                test_type=TestType.ADVISORY,
            ),
        ]
'''


def _write_handler(project_path: Path, event_dir: str, decision_name: str) -> None:
    handlers_dir = project_path / ".claude" / "project-handlers"
    event_path = handlers_dir / event_dir
    event_path.mkdir(parents=True, exist_ok=True)
    (handlers_dir / "__init__.py").write_text("")
    (event_path / "__init__.py").write_text("")
    (event_path / "probe_handler.py").write_text(
        _HANDLER_TEMPLATE.format(decision_name=decision_name)
    )


def _run(project_path: Path) -> int:
    from claude_code_hooks_daemon.daemon.cli import cmd_validate_project_handlers

    return cmd_validate_project_handlers(argparse.Namespace(project_root=project_path))


class TestAnUndeliverableDecisionIsReported:
    """The gap this closes for client projects."""

    @pytest.mark.parametrize(
        "event_dir", ["session_start", "session_end", "pre_compact", "notification"]
    )
    def test_a_deny_on_an_event_that_cannot_block_is_warned_about(
        self, event_dir: str, tmp_path: Path, capsys: Any
    ) -> None:
        project_path = _setup_project(tmp_path)
        _write_handler(project_path, event_dir, "DENY")

        _run(project_path)

        output = "".join(capsys.readouterr()[:2])
        assert "DROPPED" in output.upper() or "cannot carry" in output, (
            f"a project handler returning DENY on {event_dir} was validated without "
            f"comment, so the client ships a block that never blocks:\n{output}"
        )

    def test_the_warning_names_the_decision_and_the_consequence(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        """A warning nobody can act on is barely better than none."""
        project_path = _setup_project(tmp_path)
        _write_handler(project_path, "session_start", "DENY")

        _run(project_path)

        output = "".join(capsys.readouterr()[:2])
        assert "deny" in output
        assert "SessionStart" in output

    def test_the_warning_is_counted(self, tmp_path: Path, capsys: Any) -> None:
        """It must appear in the summary, not only inline."""
        project_path = _setup_project(tmp_path)
        _write_handler(project_path, "session_start", "DENY")

        _run(project_path)

        output = capsys.readouterr().out
        assert "Warnings:" in output


class TestACorrectHandlerIsNotDisturbed:
    """A guard that cries wolf on correct handlers gets switched off."""

    def test_a_deny_on_pre_tool_use_is_not_warned_about(self, tmp_path: Path, capsys: Any) -> None:
        project_path = _setup_project(tmp_path)
        _write_handler(project_path, "pre_tool_use", "DENY")

        result = _run(project_path)

        output = "".join(capsys.readouterr()[:2])
        assert result == 0
        assert "cannot carry" not in output

    def test_an_allow_on_session_start_is_not_warned_about(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        project_path = _setup_project(tmp_path)
        _write_handler(project_path, "session_start", "ALLOW")

        result = _run(project_path)

        output = "".join(capsys.readouterr()[:2])
        assert result == 0
        assert "cannot carry" not in output


class TestTheExitCodeContractIsUnchanged:
    """Existing clients must not have their pipelines broken by an upgrade."""

    def test_an_undeliverable_decision_does_not_fail_the_command(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        """The AST scan can over-attribute, so this warns rather than fails.

        Exit 1 stays reserved for a handler that genuinely could not be loaded,
        which is what CI pipelines and upgrade scripts already key on.
        """
        project_path = _setup_project(tmp_path)
        _write_handler(project_path, "session_start", "DENY")

        assert _run(project_path) == 0
        capsys.readouterr()
