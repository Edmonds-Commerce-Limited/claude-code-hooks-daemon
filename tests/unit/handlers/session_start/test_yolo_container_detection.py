"""Unit tests for YoloContainerDetectionHandler.

Tests cover the refactored handler that uses ``in_container()`` /
``detect_container_runtime()`` from the precise container-detection utility
instead of the removed tautological confidence scorer.

Key regression: desktop Claude Code sessions (CLAUDECODE=1,
CLAUDE_CODE_ENTRYPOINT=cli, but NO container markers) must NOT fire.
"""

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.handlers.session_start.yolo_container_detection import (
    _CFG_SHOW_DETAILED_INDICATORS,
    _CFG_SHOW_WORKFLOW_TIPS,
    _ICON_CONTAINER,
    _ICON_DOCKER,
    _ICON_LXC,
    _RUNTIME_DOCKER,
    _RUNTIME_LXC,
    YoloContainerDetectionHandler,
    _runtime_icon,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Env vars that point to overridable container marker paths (from util)
_ENV_DOCKERENV_PATH = "HOOKS_DAEMON_DOCKERENV_PATH"
_ENV_CONTAINERENV_PATH = "HOOKS_DAEMON_CONTAINERENV_PATH"
_ENV_CGROUP_PATH = "HOOKS_DAEMON_CGROUP_PATH"

# A SessionStart hook_input with no transcript (new session)
_SESSION_START_NEW: dict[str, Any] = {"hook_event_name": "SessionStart"}


def _absent_path(tmp_path: Path, name: str) -> str:
    """Return a path string to a non-existent file inside tmp_path."""
    return str(tmp_path / name)


def _present_path(tmp_path: Path, name: str, content: str = "x") -> str:
    """Create a file in tmp_path and return its path string."""
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


def _container_env(tmp_path: Path, *, runtime: str = "docker") -> dict[str, str]:
    """Build an env override that simulates a container via a marker file.

    For docker → points HOOKS_DAEMON_DOCKERENV_PATH at a real file.
    For podman → points HOOKS_DAEMON_CONTAINERENV_PATH at a real file.
    Both also redirect the other markers and cgroup to absent paths so only
    the intended signal fires.
    """
    dockerenv = (
        _present_path(tmp_path, ".dockerenv")
        if runtime == "docker"
        else _absent_path(tmp_path, ".dockerenv")
    )
    containerenv = (
        _present_path(tmp_path, ".containerenv")
        if runtime == "podman"
        else _absent_path(tmp_path, ".containerenv")
    )
    cgroup = _absent_path(tmp_path, "cgroup")  # no cgroup signal
    return {
        _ENV_DOCKERENV_PATH: dockerenv,
        _ENV_CONTAINERENV_PATH: containerenv,
        _ENV_CGROUP_PATH: cgroup,
        # Ensure the `container` env var does not accidentally signal
        "container": "",
    }


def _desktop_env(tmp_path: Path) -> dict[str, str]:
    """Build an env override that looks like desktop Claude Code (no container markers)."""
    return {
        "CLAUDECODE": "1",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        _ENV_DOCKERENV_PATH: _absent_path(tmp_path, ".dockerenv"),
        _ENV_CONTAINERENV_PATH: _absent_path(tmp_path, ".containerenv"),
        _ENV_CGROUP_PATH: _absent_path(tmp_path, "cgroup"),
        "container": "",
    }


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    """Handler initialises with correct defaults."""

    def test_handler_name(self) -> None:
        handler = YoloContainerDetectionHandler()
        assert handler.name == "yolo-container-detection"

    def test_handler_priority(self) -> None:
        handler = YoloContainerDetectionHandler()
        assert handler.priority == 40

    def test_handler_is_non_terminal(self) -> None:
        handler = YoloContainerDetectionHandler()
        assert handler.terminal is False

    def test_default_show_detailed_indicators(self) -> None:
        handler = YoloContainerDetectionHandler()
        assert handler.config[_CFG_SHOW_DETAILED_INDICATORS] is True

    def test_default_show_workflow_tips(self) -> None:
        handler = YoloContainerDetectionHandler()
        assert handler.config[_CFG_SHOW_WORKFLOW_TIPS] is True


# ---------------------------------------------------------------------------
# configure()
# ---------------------------------------------------------------------------


class TestConfigure:
    """configure() merges options and tolerates unknown keys."""

    def test_override_show_detailed_indicators(self) -> None:
        handler = YoloContainerDetectionHandler()
        handler.configure({_CFG_SHOW_DETAILED_INDICATORS: False})
        assert handler.config[_CFG_SHOW_DETAILED_INDICATORS] is False

    def test_override_show_workflow_tips(self) -> None:
        handler = YoloContainerDetectionHandler()
        handler.configure({_CFG_SHOW_WORKFLOW_TIPS: False})
        assert handler.config[_CFG_SHOW_WORKFLOW_TIPS] is False

    def test_empty_config_preserves_defaults(self) -> None:
        handler = YoloContainerDetectionHandler()
        handler.configure({})
        assert handler.config[_CFG_SHOW_DETAILED_INDICATORS] is True
        assert handler.config[_CFG_SHOW_WORKFLOW_TIPS] is True

    def test_unknown_key_is_tolerated(self) -> None:
        """Legacy min_confidence_score key must not crash the handler."""
        handler = YoloContainerDetectionHandler()
        handler.configure({"min_confidence_score": 5})
        # Stored but ignored — no crash
        assert handler.config.get("min_confidence_score") == 5

    def test_partial_override_keeps_other_defaults(self) -> None:
        handler = YoloContainerDetectionHandler()
        handler.configure({_CFG_SHOW_WORKFLOW_TIPS: False})
        assert handler.config[_CFG_SHOW_DETAILED_INDICATORS] is True  # unchanged


# ---------------------------------------------------------------------------
# REGRESSION: desktop Claude Code session must NOT fire
# ---------------------------------------------------------------------------


class TestDesktopDoesNotFire:
    """Regression: CLAUDECODE=1 + CLAUDE_CODE_ENTRYPOINT=cli, no container markers → False."""

    def test_desktop_session_matches_false(self, tmp_path: Path) -> None:
        """Core regression: desktop Claude Code must never trigger this handler."""
        env = _desktop_env(tmp_path)
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            assert handler.matches(_SESSION_START_NEW) is False

    def test_claudecode_env_alone_not_sufficient(self, tmp_path: Path) -> None:
        """CLAUDECODE=1 alone is not a container signal."""
        env = {
            "CLAUDECODE": "1",
            _ENV_DOCKERENV_PATH: _absent_path(tmp_path, ".dockerenv"),
            _ENV_CONTAINERENV_PATH: _absent_path(tmp_path, ".containerenv"),
            _ENV_CGROUP_PATH: _absent_path(tmp_path, "cgroup"),
            "container": "",
        }
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            assert handler.matches(_SESSION_START_NEW) is False

    def test_entrypoint_cli_alone_not_sufficient(self, tmp_path: Path) -> None:
        """CLAUDE_CODE_ENTRYPOINT=cli alone is not a container signal."""
        env = {
            "CLAUDE_CODE_ENTRYPOINT": "cli",
            _ENV_DOCKERENV_PATH: _absent_path(tmp_path, ".dockerenv"),
            _ENV_CONTAINERENV_PATH: _absent_path(tmp_path, ".containerenv"),
            _ENV_CGROUP_PATH: _absent_path(tmp_path, "cgroup"),
            "container": "",
        }
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            assert handler.matches(_SESSION_START_NEW) is False


# ---------------------------------------------------------------------------
# matches()
# ---------------------------------------------------------------------------


class TestMatches:
    """matches() logic."""

    def test_matches_true_in_docker_container(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            assert handler.matches(_SESSION_START_NEW) is True

    def test_matches_true_in_podman_container(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="podman")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            assert handler.matches(_SESSION_START_NEW) is True

    def test_matches_false_for_non_session_start_event(self, tmp_path: Path) -> None:
        """Even inside a container, non-SessionStart events are ignored."""
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            assert handler.matches({"hook_event_name": "PreToolUse"}) is False

    def test_matches_false_for_post_tool_use(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            assert handler.matches({"hook_event_name": "PostToolUse"}) is False

    def test_matches_false_for_stop_event(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            assert handler.matches({"hook_event_name": "Stop"}) is False

    def test_matches_false_when_hook_input_is_none(self) -> None:
        handler = YoloContainerDetectionHandler()
        assert handler.matches(None) is False

    def test_matches_false_when_hook_input_is_non_dict_string(self) -> None:
        handler = YoloContainerDetectionHandler()
        bad_input: Any = "SessionStart"
        assert handler.matches(bad_input) is False

    def test_matches_false_when_hook_input_is_list(self) -> None:
        handler = YoloContainerDetectionHandler()
        bad_input: Any = ["SessionStart"]
        assert handler.matches(bad_input) is False

    def test_matches_false_when_hook_input_is_int(self) -> None:
        handler = YoloContainerDetectionHandler()
        bad_input: Any = 12345
        assert handler.matches(bad_input) is False

    def test_matches_false_missing_hook_event_name_key(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            assert handler.matches({}) is False

    def test_matches_false_hook_event_name_is_none(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            assert handler.matches({"hook_event_name": None}) is False

    def test_matches_false_hook_event_name_wrong_type(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            assert handler.matches({"hook_event_name": 12345}) is False

    def test_matches_uses_container_env_var(self, tmp_path: Path) -> None:
        """The `container` env var alone (e.g. podman sets container=podman) is sufficient."""
        env = {
            "container": "podman",
            _ENV_DOCKERENV_PATH: _absent_path(tmp_path, ".dockerenv"),
            _ENV_CONTAINERENV_PATH: _absent_path(tmp_path, ".containerenv"),
            _ENV_CGROUP_PATH: _absent_path(tmp_path, "cgroup"),
        }
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            assert handler.matches(_SESSION_START_NEW) is True

    def test_matches_returns_false_on_oserror_from_in_container(self, tmp_path: Path) -> None:
        """OSError from in_container() is caught — returns False (fail safe)."""
        env = _desktop_env(tmp_path)
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            with patch(
                "claude_code_hooks_daemon.handlers.session_start.yolo_container_detection.in_container",
                side_effect=OSError("probe failed"),
            ):
                assert handler.matches(_SESSION_START_NEW) is False

    def test_matches_returns_false_on_runtime_error_from_in_container(self, tmp_path: Path) -> None:
        env = _desktop_env(tmp_path)
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            with patch(
                "claude_code_hooks_daemon.handlers.session_start.yolo_container_detection.in_container",
                side_effect=RuntimeError("unexpected"),
            ):
                assert handler.matches(_SESSION_START_NEW) is False


# ---------------------------------------------------------------------------
# handle() — icon and runtime label
# ---------------------------------------------------------------------------


class TestHandleRuntimeIcon:
    """handle() picks the correct icon and includes the runtime label."""

    def test_docker_container_shows_whale_icon(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            result = handler.handle(_SESSION_START_NEW)
        assert result.decision == "allow"
        assert any(_ICON_DOCKER in line for line in result.context)
        assert any("docker" in line for line in result.context)

    def test_podman_container_shows_box_icon(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="podman")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            result = handler.handle(_SESSION_START_NEW)
        assert result.decision == "allow"
        assert any(_ICON_CONTAINER in line for line in result.context)
        assert any("podman" in line for line in result.context)

    def test_generic_container_shows_box_icon(self, tmp_path: Path) -> None:
        """A `container=oci` env var maps to 'generic' → 📦 icon."""
        env = {
            "container": "oci",
            _ENV_DOCKERENV_PATH: _absent_path(tmp_path, ".dockerenv"),
            _ENV_CONTAINERENV_PATH: _absent_path(tmp_path, ".containerenv"),
            _ENV_CGROUP_PATH: _absent_path(tmp_path, "cgroup"),
        }
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            result = handler.handle(_SESSION_START_NEW)
        assert result.decision == "allow"
        assert any(_ICON_CONTAINER in line for line in result.context)


class TestRuntimeIconLxc:
    """Plan 00127 Phase 4: LXC gets its own distinct icon."""

    def test_runtime_icon_lxc_returns_ice_cube(self) -> None:
        assert _runtime_icon(_RUNTIME_LXC) == _ICON_LXC
        assert _ICON_LXC == "🧊"

    def test_handle_lxc_banner(self) -> None:
        """In an LXC container the banner reads '🧊 Running in a lxc container...'."""
        module = "claude_code_hooks_daemon.handlers.session_start.yolo_container_detection"
        with (
            patch(f"{module}.in_container", return_value=True),
            patch(f"{module}.detect_container_runtime", return_value="lxc"),
        ):
            handler = YoloContainerDetectionHandler()
            assert handler.matches(_SESSION_START_NEW) is True
            result = handler.handle(_SESSION_START_NEW)
        assert result.decision == "allow"
        assert result.context[0].startswith("🧊 Running in a lxc container")


# ---------------------------------------------------------------------------
# handle() — decision and structure
# ---------------------------------------------------------------------------


class TestHandleDecisionAndStructure:
    """handle() always returns ALLOW with list context and no reason."""

    def test_decision_is_allow(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            result = handler.handle(_SESSION_START_NEW)
        assert result.decision == "allow"

    def test_context_is_list(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            result = handler.handle(_SESSION_START_NEW)
        assert isinstance(result.context, list)
        assert len(result.context) > 0

    def test_reason_is_none(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            result = handler.handle(_SESSION_START_NEW)
        assert result.reason is None

    def test_result_is_json_serialisable(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            result = handler.handle(_SESSION_START_NEW)
        payload = {
            "decision": result.decision,
            "reason": result.reason,
            "context": result.context,
        }
        serialised = json.dumps(payload)
        parsed = json.loads(serialised)
        assert parsed["decision"] == "allow"


# ---------------------------------------------------------------------------
# handle() — show_detailed_indicators
# ---------------------------------------------------------------------------


class TestHandleDetailedIndicators:
    """show_detailed_indicators controls the indicator block."""

    def test_indicators_shown_by_default(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            result = handler.handle(_SESSION_START_NEW)
        context_text = "\n".join(result.context)
        assert "Detected indicators:" in context_text

    def test_indicators_suppressed_when_disabled(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            handler.configure({_CFG_SHOW_DETAILED_INDICATORS: False})
            result = handler.handle(_SESSION_START_NEW)
        context_text = "\n".join(result.context)
        assert "Detected indicators:" not in context_text

    def test_indicator_includes_runtime_label(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            handler.configure({_CFG_SHOW_DETAILED_INDICATORS: True})
            result = handler.handle(_SESSION_START_NEW)
        context_text = "\n".join(result.context)
        assert "Container runtime:" in context_text
        assert _RUNTIME_DOCKER in context_text

    def test_indicator_does_not_list_claudecode_env(self, tmp_path: Path) -> None:
        """CLAUDECODE / CLAUDE_CODE_ENTRYPOINT must NOT appear as container indicators."""
        env = {
            **_container_env(tmp_path, runtime="docker"),
            "CLAUDECODE": "1",
            "CLAUDE_CODE_ENTRYPOINT": "cli",
        }
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            handler.configure({_CFG_SHOW_DETAILED_INDICATORS: True})
            result = handler.handle(_SESSION_START_NEW)
        context_text = "\n".join(result.context)
        assert "CLAUDECODE" not in context_text
        assert "CLAUDE_CODE_ENTRYPOINT" not in context_text

    def test_root_uid_shown_in_indicators_when_uid_zero(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            with patch("os.getuid", return_value=0):
                handler = YoloContainerDetectionHandler()
                handler.configure({_CFG_SHOW_DETAILED_INDICATORS: True})
                result = handler.handle(_SESSION_START_NEW)
        context_text = "\n".join(result.context)
        assert "root" in context_text.lower() or "UID 0" in context_text

    def test_root_uid_not_shown_when_non_zero(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            with patch("os.getuid", return_value=1000):
                handler = YoloContainerDetectionHandler()
                handler.configure({_CFG_SHOW_DETAILED_INDICATORS: True})
                result = handler.handle(_SESSION_START_NEW)
        context_text = "\n".join(result.context)
        assert "UID 0" not in context_text

    def test_getuid_attribute_error_does_not_crash(self, tmp_path: Path) -> None:
        """Windows-style missing os.getuid must not crash the handler."""
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            with patch("os.getuid", side_effect=AttributeError("no getuid")):
                handler = YoloContainerDetectionHandler()
                result = handler.handle(_SESSION_START_NEW)
        assert result.decision == "allow"


# ---------------------------------------------------------------------------
# handle() — show_workflow_tips
# ---------------------------------------------------------------------------


class TestHandleWorkflowTips:
    """show_workflow_tips controls the workflow-implications block."""

    def test_workflow_tips_shown_by_default(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            result = handler.handle(_SESSION_START_NEW)
        context_text = "\n".join(result.context)
        assert "Container workflow implications:" in context_text

    def test_workflow_tips_suppressed_when_disabled(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            handler.configure({_CFG_SHOW_WORKFLOW_TIPS: False})
            result = handler.handle(_SESSION_START_NEW)
        context_text = "\n".join(result.context)
        assert "Container workflow implications:" not in context_text

    def test_tips_mention_ephemeral_storage(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            result = handler.handle(_SESSION_START_NEW)
        context_text = "\n".join(result.context)
        assert "ephemeral" in context_text.lower()

    def test_tips_mention_root(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            result = handler.handle(_SESSION_START_NEW)
        context_text = "\n".join(result.context)
        assert "root" in context_text.lower()


# ---------------------------------------------------------------------------
# handle() — resume detection
# ---------------------------------------------------------------------------


class TestHandleResumeSession:
    """handle() uses _is_resume_session to shorten message for resumed sessions."""

    def test_resume_session_brief_message(self, tmp_path: Path) -> None:
        """Resume sessions get a one-liner without the full workflow-tips block."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 200, encoding="utf-8")

        env = _container_env(tmp_path, runtime="podman")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            hook_input: dict[str, Any] = {
                "hook_event_name": "SessionStart",
                "transcript_path": str(transcript),
            }
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        context_text = "\n".join(result.context)
        # Icon and runtime present
        assert _ICON_CONTAINER in context_text
        assert "podman" in context_text
        # No full workflow tips block on resume
        assert "Container workflow implications:" not in context_text

    def test_new_session_is_not_resume(self, tmp_path: Path) -> None:
        """A session with no transcript_path is treated as new (full message)."""
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            result = handler.handle(_SESSION_START_NEW)

        context_text = "\n".join(result.context)
        # Should have workflow tips
        assert "Container workflow implications:" in context_text

    def test_small_transcript_is_not_resume(self, tmp_path: Path) -> None:
        """A tiny transcript (< 100 bytes) does not count as a resume."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 50, encoding="utf-8")

        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            hook_input: dict[str, Any] = {
                "hook_event_name": "SessionStart",
                "transcript_path": str(transcript),
            }
            result = handler.handle(hook_input)

        context_text = "\n".join(result.context)
        assert "Container workflow implications:" in context_text


# ---------------------------------------------------------------------------
# _is_resume_session()
# ---------------------------------------------------------------------------


class TestIsResumeSession:
    """_is_resume_session internal method."""

    def test_returns_true_for_large_transcript(self, tmp_path: Path) -> None:
        handler = YoloContainerDetectionHandler()
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 200, encoding="utf-8")
        assert handler._is_resume_session({"transcript_path": str(transcript)}) is True

    def test_returns_false_for_nonexistent_transcript(self, tmp_path: Path) -> None:
        handler = YoloContainerDetectionHandler()
        assert (
            handler._is_resume_session({"transcript_path": str(tmp_path / "missing.jsonl")})
            is False
        )

    def test_returns_false_for_empty_transcript_path(self) -> None:
        handler = YoloContainerDetectionHandler()
        assert handler._is_resume_session({"transcript_path": ""}) is False

    def test_returns_false_for_missing_transcript_key(self) -> None:
        handler = YoloContainerDetectionHandler()
        assert handler._is_resume_session({}) is False

    def test_returns_false_on_oserror_from_stat(self, tmp_path: Path) -> None:
        handler = YoloContainerDetectionHandler()
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 200, encoding="utf-8")
        with patch("pathlib.Path.stat", side_effect=OSError("Permission denied")):
            assert handler._is_resume_session({"transcript_path": str(transcript)}) is False


# ---------------------------------------------------------------------------
# handle() — error handling
# ---------------------------------------------------------------------------


class TestHandleErrorHandling:
    """handle() converts expected OS/runtime errors to ALLOW-with-warning."""

    def test_oserror_in_is_resume_returns_allow_with_warning(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            with patch.object(
                handler, "_is_resume_session", side_effect=OSError("File system error")
            ):
                result = handler.handle(_SESSION_START_NEW)
        assert result.decision == "allow"
        assert any("detection failed" in c for c in result.context)

    def test_runtime_error_in_is_resume_returns_allow_with_warning(self, tmp_path: Path) -> None:
        env = _container_env(tmp_path, runtime="docker")
        with patch.dict(os.environ, env, clear=False):
            handler = YoloContainerDetectionHandler()
            with patch.object(handler, "_is_resume_session", side_effect=RuntimeError("bad state")):
                result = handler.handle(_SESSION_START_NEW)
        assert result.decision == "allow"
        assert any("detection failed" in c for c in result.context)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    """Handler metadata methods."""

    def test_get_claude_md_returns_none(self) -> None:
        handler = YoloContainerDetectionHandler()
        assert handler.get_claude_md() is None

    def test_get_acceptance_tests_returns_non_empty_list(self) -> None:
        handler = YoloContainerDetectionHandler()
        tests = handler.get_acceptance_tests()
        assert isinstance(tests, list)
        assert len(tests) > 0

    def test_priority_in_workflow_range(self) -> None:
        handler = YoloContainerDetectionHandler()
        assert 36 <= handler.priority <= 55

    def test_acceptance_test_description_does_not_reference_confidence(self) -> None:
        """Acceptance test description must not mention the removed confidence scorer."""
        handler = YoloContainerDetectionHandler()
        for test in handler.get_acceptance_tests():
            assert "confidence" not in test.description.lower()
