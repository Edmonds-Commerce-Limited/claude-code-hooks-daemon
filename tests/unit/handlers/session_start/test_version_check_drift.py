"""Plan 00477 Task 5.1 - ``version_check`` names a daemon that is not the expected version.

Someone else upgrades the project and commits; this checkout pulls. The tracked
``daemon.expected_version`` now names a version the running daemon is not at, and
the daemon says nothing. On SessionStart the handler compares the running version
with the key, says so to the human and the agent, names UPGRADE or DOWNGRADE, and
names what a human runs. It never moves the daemon itself, and it never asks the
network: the answer is local.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.session_start.version_check import VersionCheckHandler
from claude_code_hooks_daemon.install.background_sync import state_path
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


def _patched(
    config: Path,
    *,
    self_install: bool = False,
    stamp: InstallStamp | None = None,
) -> Any:
    """Patch everything the drift check reads: config path, install mode, version, stamp.

    The project's ``.claude`` directory is the config's own, its root the one
    above, and the daemon's untracked directory ``untracked`` beside the config.
    """
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch(f"{_MODULE}.ProjectContext.config_path", return_value=config))
    stack.enter_context(patch(f"{_MODULE}.ProjectContext.config_dir", return_value=config.parent))
    stack.enter_context(
        patch(f"{_MODULE}.ProjectContext.project_root", return_value=config.parent.parent)
    )
    stack.enter_context(
        patch(
            f"{_MODULE}.ProjectContext.daemon_untracked_dir",
            return_value=config.parent / "untracked",
        )
    )
    stack.enter_context(
        patch(f"{_MODULE}.ProjectContext.self_install_mode", return_value=self_install)
    )
    stack.enter_context(patch(f"{_MODULE}.__version__", _RUNNING))
    stack.enter_context(patch(f"{_MODULE}.read_install_stamp", return_value=stamp))
    return stack


def _text(result: Any) -> str:
    assert result.context is not None
    return "\n".join(result.context)


def _provision_sh(config: Path) -> Path:
    """The tracked .claude/provision.sh a project carries since provision shipped."""
    script = config.parent / "provision.sh"
    script.write_text("#!/bin/bash\n")
    return script


def _record(config: Path, version: str, text: str) -> Path:
    """A state provision.sh --background left for ``version``."""
    path = state_path(config.parent / "untracked", version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


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

        assert "bash .claude/provision.sh" in text
        assert "args=upgrade 3.68.0" not in text, "a sync is provision, not an upgrade"
        assert "/hooks-daemon upgrade" not in text

    def test_tells_a_sync_apart_from_moving_the_project(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        config = _config(tmp_path, '  expected_version: "3.68.0"\n')
        with _patched(config):
            text = _text(handler.handle(new_session_input))

        assert "pre-deploy gate" in text
        assert "refuses a clone with local changes" in text
        assert f"puts v{_RUNNING} back" in text
        assert "args=upgrade <version>" in text

    def test_without_provision_sh_it_changes_nothing_itself(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        """A project that predates the tracked provision.sh has nothing to start."""
        config = _config(tmp_path, '  expected_version: "3.68.0"\n')
        with _patched(config):
            text = _text(handler.handle(new_session_input)).lower()

        assert "nothing has been changed" in text
        assert "background sync" not in text


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
        assert "bash .claude/provision.sh" in text
        assert "args=upgrade 3.50.0" not in text

    def test_a_downgrade_asks_for_confirmation_that_it_is_intended(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        config = _config(tmp_path, '  expected_version: "3.50.0"\n')
        with _patched(config):
            text = _text(handler.handle(new_session_input)).lower()

        assert "intended" in text

    def test_a_downgrade_is_never_synced_in_the_background(
        self, handler: VersionCheckHandler, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        config = _config(tmp_path, '  expected_version: "3.50.0"\n')
        _provision_sh(config)
        with _patched(config):
            text = _text(handler.handle(new_session_input)).lower()

        assert "nothing has been changed" in text
        assert "background sync" not in text


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
        _provision_sh(config)
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


_EXPECTED = "3.68.0"


@pytest.fixture
def upgrade_config(tmp_path: Path) -> Path:
    """A project that pulled a newer expected version and carries provision.sh."""
    config = _config(tmp_path, f'  expected_version: "{_EXPECTED}"\n')
    _provision_sh(config)
    return config


class TestAPulledUpgradeIsReportedAsSyncingInTheBackground:
    """Plan 00477 Task 5.2: the session-start forwarder starts the sync; this reports it."""

    def test_the_first_session_says_the_sync_has_been_started(
        self,
        handler: VersionCheckHandler,
        new_session_input: dict[str, Any],
        upgrade_config: Path,
    ) -> None:
        log = upgrade_config.parent / "untracked" / "background-sync" / "v3.68.0.log"
        with _patched(upgrade_config):
            text = _text(handler.handle(new_session_input))

        assert "BACKGROUND SYNC STARTED" in text
        assert str(log) in text
        assert f"v{_RUNNING} keeps serving" in text
        assert "nothing has been changed" not in text.lower()

    def test_a_sync_under_way_says_so(
        self,
        handler: VersionCheckHandler,
        new_session_input: dict[str, Any],
        upgrade_config: Path,
    ) -> None:
        _record(upgrade_config, _EXPECTED, f"status=running\npid={os.getpid()}\n")
        with _patched(upgrade_config):
            text = _text(handler.handle(new_session_input))

        assert "UNDER WAY" in text

    def test_a_failed_sync_is_reported_loudly_with_the_command_and_not_retried(
        self,
        handler: VersionCheckHandler,
        new_session_input: dict[str, Any],
        upgrade_config: Path,
    ) -> None:
        state = _record(
            upgrade_config,
            _EXPECTED,
            "status=failed\nfrom=3.60.0\ndetail=the venv for v3.68.0 could not be built\n",
        )
        with _patched(upgrade_config):
            text = _text(handler.handle(new_session_input))

        assert f"BACKGROUND SYNC TO v{_EXPECTED} FAILED" in text
        assert "the venv for v3.68.0 could not be built" in text
        assert f"v{_RUNNING} is still running" in text
        assert "bash .claude/provision.sh" in text
        assert str(state) in text, "names the marker to delete for a retry"

    def test_a_sync_that_stopped_for_the_reading_list_says_what_to_run(
        self,
        handler: VersionCheckHandler,
        new_session_input: dict[str, Any],
        upgrade_config: Path,
    ) -> None:
        _record(upgrade_config, _EXPECTED, "status=needs-reading\ndetail=read the guides\n")
        with _patched(upgrade_config):
            text = _text(handler.handle(new_session_input))

        assert f"BACKGROUND SYNC TO v{_EXPECTED} STOPPED" in text
        assert "--skip-reading-confirmation" in text
        assert "bash .claude/provision.sh" in text

    def test_a_recorded_success_that_left_this_version_running_is_not_hidden(
        self,
        handler: VersionCheckHandler,
        new_session_input: dict[str, Any],
        upgrade_config: Path,
    ) -> None:
        _record(upgrade_config, _EXPECTED, "status=synced\n")
        with _patched(upgrade_config):
            text = _text(handler.handle(new_session_input))

        assert "recorded success" in text
        assert "bash .claude/provision.sh" in text
