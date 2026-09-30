"""Plan 00477 Task 5.1 - ``version_check`` names a daemon that is not the expected version.

Someone else upgrades the project and commits; this checkout pulls. The tracked
``daemon.expected_version`` now names a version the running daemon is not at, and
the daemon says nothing. On SessionStart the handler compares the running version
with the key, says so to the human and the agent, names UPGRADE or DOWNGRADE, and
names what a human runs. It never moves the daemon itself, and it never asks the
network: the answer is local.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.session_start.version_check import VersionCheckHandler
from claude_code_hooks_daemon.install.install_stamp import InstallStamp

_MODULE = "claude_code_hooks_daemon.handlers.session_start.version_check"
_RUNNING = "3.60.0"
_BRANCH_STAMP = InstallStamp(
    raw="v3.60.0+main.8d011476", version="3.60.0", ref="main", sha="8d011476"
)


@pytest.fixture
def handler() -> VersionCheckHandler:
    return VersionCheckHandler()


@pytest.fixture
def new_session_input(tmp_path: Path) -> dict[str, Any]:
    return {
        "hook_event_name": "SessionStart",
        "session_id": "s",
        "transcript_path": str(tmp_path / "nonexistent.jsonl"),
        "cwd": "/workspace",
    }


@pytest.fixture
def resume_session_input(tmp_path: Path) -> dict[str, Any]:
    transcript = tmp_path / "resume.jsonl"
    transcript.write_text("A" * 200)
    return {
        "hook_event_name": "SessionStart",
        "session_id": "s",
        "transcript_path": str(transcript),
        "cwd": "/workspace",
    }


def _config(tmp_path: Path, daemon_block: str) -> Path:
    path = tmp_path / "hooks-daemon.yaml"
    path.write_text(f"daemon:\n{daemon_block}")
    return path


def _patched(config: Path, *, self_install: bool = False, stamp: InstallStamp | None = None) -> Any:
    """Patch everything the drift check reads: config path, install mode, version, stamp."""
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch(f"{_MODULE}.ProjectContext.config_path", return_value=config))
    stack.enter_context(
        patch(f"{_MODULE}.ProjectContext.self_install_mode", return_value=self_install)
    )
    stack.enter_context(patch(f"{_MODULE}.__version__", _RUNNING))
    stack.enter_context(patch(f"{_MODULE}.read_install_stamp", return_value=stamp))
    return stack


def _text(result: Any) -> str:
    assert result.context is not None
    return "\n".join(result.context)


class TestAnUpgradeIsNamed:
    def test_names_both_versions_the_source_and_the_direction(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        config = _config(tmp_path, '  expected_version: "3.68.0"\n')
        with _patched(config), patch(f"{_MODULE}.run_git") as run_git:
            result = handler.handle(new_session_input)

        assert result.decision == Decision.ALLOW
        text = _text(result)
        assert "3.60.0" in text and "3.68.0" in text
        assert "daemon.expected_version" in text
        assert "UPGRADE" in text
        assert "DOWNGRADE" not in text
        run_git.assert_not_called()

    def test_names_the_command_a_human_runs(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        config = _config(tmp_path, '  expected_version: "3.68.0"\n')
        with _patched(config):
            text = _text(handler.handle(new_session_input))

        assert "args=upgrade 3.68.0" in text
        assert "/hooks-daemon upgrade 3.68.0" in text

    def test_says_it_changes_nothing_itself(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        config = _config(tmp_path, '  expected_version: "3.68.0"\n')
        with _patched(config):
            text = _text(handler.handle(new_session_input)).lower()

        assert "nothing has been changed" in text or "does not change" in text


class TestADowngradeIsNamedAsOne:
    def test_a_lower_expected_version_is_a_downgrade(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        config = _config(tmp_path, '  expected_version: "3.50.0"\n')
        with _patched(config):
            text = _text(handler.handle(new_session_input))

        assert "DOWNGRADE" in text
        assert "UPGRADE" not in text.replace("DOWNGRADE", "")
        assert "3.50.0" in text and "3.60.0" in text
        assert "args=upgrade 3.50.0" in text

    def test_a_downgrade_asks_for_confirmation_that_it_is_intended(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        config = _config(tmp_path, '  expected_version: "3.50.0"\n')
        with _patched(config):
            text = _text(handler.handle(new_session_input)).lower()

        assert "intended" in text


class TestSilentWhenNothingDrifted:
    def test_an_equal_version_is_silent(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        config = _config(tmp_path, f'  expected_version: "{_RUNNING}"\n')
        with (
            _patched(config),
            patch.object(handler, "_get_latest_version", return_value=_RUNNING),
            patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"),
        ):
            result = handler.handle(new_session_input)

        assert result.context == []

    def test_no_key_is_silent(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        """A branch install never writes the key, so it has nothing to drift from."""
        config = _config(tmp_path, "  log_level: INFO\n")
        with (
            _patched(config),
            patch.object(handler, "_get_latest_version", return_value=_RUNNING),
            patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"),
        ):
            result = handler.handle(new_session_input)

        assert result.context == []

    def test_an_invalid_key_is_silent(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        """An invalid key keeps the state config validation already reports."""
        config = _config(tmp_path, '  expected_version: "latest"\n')
        with (
            _patched(config),
            patch.object(handler, "_get_latest_version", return_value=_RUNNING),
            patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"),
        ):
            result = handler.handle(new_session_input)

        assert result.context == []

    def test_the_daemons_own_repository_never_reports_drift(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        config = _config(tmp_path, '  expected_version: "3.68.0"\n')
        with (
            _patched(config, self_install=True),
            patch.object(handler, "_get_latest_version", return_value=_RUNNING),
            patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"),
        ):
            result = handler.handle(new_session_input)

        assert result.context == []

    def test_a_project_context_that_is_not_ready_is_silent(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        with (
            patch(f"{_MODULE}.ProjectContext.self_install_mode", side_effect=RuntimeError("no")),
            patch(f"{_MODULE}.read_install_stamp", return_value=None),
            patch.object(handler, "_get_latest_version", return_value=_RUNNING),
            patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"),
        ):
            result = handler.handle(new_session_input)

        assert result.context == []


class TestAConfigThatCannotBeReadIsNotGuessedAt:
    def test_unparseable_config_is_silent_and_logged(
        self,
        handler: VersionCheckHandler,
        new_session_input: dict[str, Any],
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text("daemon: [unclosed\n")
        with (
            _patched(config),
            patch.object(handler, "_get_latest_version", return_value=_RUNNING),
            patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"),
            caplog.at_level("WARNING"),
        ):
            result = handler.handle(new_session_input)

        assert result.context == []
        assert "Version drift check skipped" in caplog.text


class TestABranchInstallKeepsItsOwnAdvisory:
    def test_the_branch_advisory_is_not_replaced_by_a_drift_notice(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        config = _config(tmp_path, '  expected_version: "3.68.0"\n')
        with _patched(config, stamp=_BRANCH_STAMP):
            text = _text(handler.handle(new_session_input))

        assert "NON-RELEASE" in text
        assert "DOWNGRADE" not in text and "UPGRADE" not in text


class TestResumedSessions:
    def test_a_resume_matches_only_when_the_version_has_drifted(
        self, handler: VersionCheckHandler, resume_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        drifted = _config(tmp_path, '  expected_version: "3.68.0"\n')
        with _patched(drifted):
            assert handler.matches(resume_session_input) is True

        same = tmp_path / "same.yaml"
        same.write_text(f'daemon:\n  expected_version: "{_RUNNING}"\n')
        with _patched(same):
            assert handler.matches(resume_session_input) is False

    def test_a_resume_reports_the_drift_and_nothing_else(
        self, handler: VersionCheckHandler, resume_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        config = _config(tmp_path, '  expected_version: "3.68.0"\n')
        with _patched(config), patch(f"{_MODULE}.run_git") as run_git:
            text = _text(handler.handle(resume_session_input))

        assert "UPGRADE" in text
        run_git.assert_not_called()

    def test_a_disabled_handler_does_not_match_a_drifted_resume(
        self, handler: VersionCheckHandler, resume_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        config = _config(tmp_path, '  expected_version: "3.68.0"\n')
        handler.configure({"enabled": False})
        with _patched(config):
            assert handler.matches(resume_session_input) is False
