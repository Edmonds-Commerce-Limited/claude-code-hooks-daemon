"""Tests for the automatic-upgrade advisory of the version check (Plan 00625)."""

from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.session_start.version_check import VersionCheckHandler
from claude_code_hooks_daemon.install.auto_upgrade import ATTEMPT_DIR_NAME

_MODULE = "claude_code_hooks_daemon.handlers.session_start.version_check"
_RUNNING = "3.75.0"
_LATEST = "3.76.0"

_OPT_OUT = (
    "handlers:\n  user_prompt_submit:\n    standing_authorisations:\n"
    "      options:\n        authorisations:\n"
    "          - id: daemon-auto-upgrade\n            enabled: false\n"
)


@pytest.fixture
def new_session_input(tmp_path: Path) -> dict[str, Any]:
    return {
        "hook_event_name": "SessionStart",
        "session_id": "s-1",
        "transcript_path": str(tmp_path / "none.jsonl"),
        "cwd": "/workspace",
    }


def _patched(tmp_path: Path, *, config_text: str = "", self_install: bool = False) -> ExitStack:
    project = tmp_path / "project"
    config = project / ".claude" / "hooks-daemon.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(config_text)
    stack = ExitStack()
    stack.enter_context(patch(f"{_MODULE}.ProjectContext.config_path", return_value=config))
    stack.enter_context(patch(f"{_MODULE}.ProjectContext.project_root", return_value=project))
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
    stack.enter_context(patch(f"{_MODULE}.read_install_stamp", return_value=None))
    stack.enter_context(patch(f"{_MODULE}.read_expected_version", return_value=None))
    ls_remote = MagicMock(returncode=0, stdout=f"abc\trefs/tags/v{_LATEST}\n", stderr="")
    stack.enter_context(patch(f"{_MODULE}.run_git", return_value=ls_remote))
    return stack


def _handle(handler: VersionCheckHandler, hook_input: dict[str, Any], tmp_path: Path) -> str:
    with patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"):
        result = handler.handle(hook_input)
    assert result.context is not None
    return "\n".join(result.context)


class TestAutoUpgradeAdvisory:
    def test_eligible_says_authorised_and_how_to_run(
        self, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        with _patched(tmp_path):
            text = _handle(VersionCheckHandler(), new_session_input, tmp_path)
        assert f"v{_RUNNING} → v{_LATEST}" in text
        assert "AUTO-UPGRADE AUTHORISED" in text
        assert "args=upgrade --unattended" in text
        assert "{id: daemon-auto-upgrade, enabled: false}" in text

    def test_opt_out_keeps_todays_wording(
        self, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        with _patched(tmp_path, config_text=_OPT_OUT):
            text = _handle(VersionCheckHandler(), new_session_input, tmp_path)
        assert "AUTO-UPGRADE" not in text
        assert "not automatic" not in text
        assert "To upgrade, use the hooks-daemon skill to upgrade" in text
        assert "args=upgrade)" in text

    def test_no_project_context_keeps_todays_wording(
        self, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        with (
            _patched(tmp_path),
            patch(f"{_MODULE}.ProjectContext.config_path", side_effect=RuntimeError("no")),
        ):
            text = _handle(VersionCheckHandler(), new_session_input, tmp_path)
        assert "AUTO-UPGRADE" not in text
        assert "To upgrade, use the hooks-daemon skill to upgrade" in text

    def test_major_bump_is_refused_with_the_reason(
        self, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        with _patched(tmp_path), patch(f"{_MODULE}.__version__", "2.99.0"):
            text = _handle(VersionCheckHandler(), new_session_input, tmp_path)
        assert "AUTO-UPGRADE AUTHORISED" not in text
        assert "To upgrade, use the hooks-daemon skill to upgrade" in text
        assert "Not automatic" in text
        assert "MAJOR" in text

    def test_release_in_progress_is_refused(
        self, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        state = tmp_path / "project" / "untracked" / "release-state.json"
        state.parent.mkdir(parents=True)
        state.write_text("{}")
        with _patched(tmp_path):
            text = _handle(VersionCheckHandler(), new_session_input, tmp_path)
        assert "Not automatic" in text
        assert "release is in progress" in text

    def test_self_install_with_authorisation_is_refused(
        self, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        with _patched(tmp_path, self_install=True):
            text = _handle(VersionCheckHandler(), new_session_input, tmp_path)
        assert "Not automatic" in text
        assert "AUTO-UPGRADE AUTHORISED" not in text

    def test_recorded_attempt_is_reported_and_not_retried(
        self, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        record = tmp_path / "project" / ".claude" / "untracked" / ATTEMPT_DIR_NAME
        record.mkdir(parents=True)
        (record / f"v{_LATEST}.state").write_text(
            "status=failed\ntarget=3.76.0\nfrom=3.75.0\ndetail=health check failed\n"
        )
        with _patched(tmp_path):
            text = _handle(VersionCheckHandler(), new_session_input, tmp_path)
        assert "AUTO-UPGRADE AUTHORISED" not in text
        assert "Not automatic" in text
        assert "failed" in text
        assert "health check failed" in text
        assert "not retried until a newer release" in text
        assert "To upgrade, use the hooks-daemon skill to upgrade" in text

    def test_cached_outdated_result_still_reaches_the_advisory(
        self, new_session_input: dict[str, Any], tmp_path: Path
    ) -> None:
        handler = VersionCheckHandler()
        cache = tmp_path / "cache.json"
        import json
        import time

        cache.write_text(
            json.dumps(
                {
                    "cached_at": time.time(),
                    "current_version": _RUNNING,
                    "latest_version": _LATEST,
                    "is_outdated": True,
                }
            )
        )
        with _patched(tmp_path), patch.object(handler, "_get_cache_file", return_value=cache):
            result = handler.handle(new_session_input)
        assert result.context is not None
        assert "AUTO-UPGRADE AUTHORISED" in "\n".join(result.context)
