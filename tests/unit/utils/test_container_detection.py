"""
Unit tests for container detection utility.

Tests the new precise container-detection API introduced in the tautological-
signal refactor.  The old confidence-score symbols
(get_container_confidence_score, get_detected_indicators,
DEFAULT_CONFIDENCE_THRESHOLD) have been removed; this file tests only the new
API.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from claude_code_hooks_daemon.utils.container_detection import (
    detect_container_runtime,
    in_container,
    is_container_environment,
    is_yolo_sandbox,
    running_under_claude_code,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Override paths so the tests are hermetically isolated from the real container
# this test-runner is inside.  Point every marker at a nonexistent path.
_ABSENT_DOCKER = "/tmp/_test_nonexistent_dockerenv_99999"
_ABSENT_CONTAINERENV = "/tmp/_test_nonexistent_containerenv_99999"
_ABSENT_CGROUP = "/tmp/_test_nonexistent_cgroup_99999"

_NEUTRAL_ENV_OVERRIDES = {
    "HOOKS_DAEMON_DOCKERENV_PATH": _ABSENT_DOCKER,
    "HOOKS_DAEMON_CONTAINERENV_PATH": _ABSENT_CONTAINERENV,
    "HOOKS_DAEMON_CGROUP_PATH": _ABSENT_CGROUP,
}


def _clean_env(**extra: str) -> dict[str, str]:
    """Build a clean env dict that neutralises all container markers.

    Caller can pass extra keys to simulate specific signals.
    """
    env: dict[str, str] = dict(_NEUTRAL_ENV_OVERRIDES)
    # Remove all known container / Claude Code env vars so nothing leaks in.
    for key in (
        "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT",
        "container",
        "IS_SANDBOX",
        "DEVCONTAINER",
    ):
        env[key] = ""  # will be cleared by clear=True in patch.dict
    env.update(extra)
    return env


# ---------------------------------------------------------------------------
# THE CRITICAL REGRESSION TEST
# "Desktop Claude Code session" must NOT be classified as a container.
# ---------------------------------------------------------------------------


class TestDesktopClaudeCodeSessionIsNotAContainer:
    """Regression tests for the tautological-signal bug.

    CLAUDECODE=1 and CLAUDE_CODE_ENTRYPOINT=cli are always set in production
    but are NOT evidence of a container.  They must never cause in_container()
    or is_container_environment() to return True.
    """

    def test_desktop_claude_code_session_not_in_container(self) -> None:
        """Desktop session: CLAUDECODE=1 + ENTRYPOINT=cli, no container markers.

        This is the primary regression test.  Before the fix every Claude Code
        session (desktop included) was mis-classified as a container because
        CLAUDECODE=1 alone scored 3 points and the threshold was also 3.
        """
        env = _clean_env(
            CLAUDECODE="1",
            CLAUDE_CODE_ENTRYPOINT="cli",
        )
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() is None
            assert in_container() is False
            assert is_container_environment() is False

    def test_claudecode_alone_is_not_a_container(self) -> None:
        """CLAUDECODE=1 alone must not classify as container."""
        env = _clean_env(CLAUDECODE="1")
        with patch.dict(os.environ, env, clear=True):
            assert in_container() is False

    def test_entrypoint_alone_is_not_a_container(self) -> None:
        """CLAUDE_CODE_ENTRYPOINT=cli alone must not classify as container."""
        env = _clean_env(CLAUDE_CODE_ENTRYPOINT="cli")
        with patch.dict(os.environ, env, clear=True):
            assert in_container() is False


# ---------------------------------------------------------------------------
# running_under_claude_code()
# ---------------------------------------------------------------------------


class TestRunningUnderClaudeCode:
    """Tests for running_under_claude_code()."""

    def test_true_when_claudecode_is_one(self) -> None:
        """CLAUDECODE=1 is sufficient for running_under_claude_code."""
        with patch.dict(os.environ, {"CLAUDECODE": "1"}, clear=True):
            assert running_under_claude_code() is True

    def test_true_when_entrypoint_is_cli(self) -> None:
        """CLAUDE_CODE_ENTRYPOINT=cli is sufficient for running_under_claude_code."""
        with patch.dict(os.environ, {"CLAUDE_CODE_ENTRYPOINT": "cli"}, clear=True):
            assert running_under_claude_code() is True

    def test_true_when_both_set(self) -> None:
        """Both vars set → still True."""
        with patch.dict(
            os.environ,
            {"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli"},
            clear=True,
        ):
            assert running_under_claude_code() is True

    def test_false_when_neither_set(self) -> None:
        """Neither var → False."""
        with patch.dict(os.environ, {}, clear=True):
            assert running_under_claude_code() is False

    def test_false_when_claudecode_is_not_one(self) -> None:
        """CLAUDECODE=0 should not count."""
        with patch.dict(os.environ, {"CLAUDECODE": "0"}, clear=True):
            assert running_under_claude_code() is False

    def test_false_when_entrypoint_is_not_cli(self) -> None:
        """CLAUDE_CODE_ENTRYPOINT=other should not count."""
        with patch.dict(os.environ, {"CLAUDE_CODE_ENTRYPOINT": "other"}, clear=True):
            assert running_under_claude_code() is False


# ---------------------------------------------------------------------------
# detect_container_runtime() — container env var
# ---------------------------------------------------------------------------


class TestDetectContainerRuntimeEnvVar:
    """Tests for container env-var branch in detect_container_runtime()."""

    def test_container_podman_returns_podman(self) -> None:
        """container=podman → 'podman'."""
        env = _clean_env(container="podman")
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() == "podman"

    def test_container_docker_returns_docker(self) -> None:
        """container=docker → 'docker'."""
        env = _clean_env(container="docker")
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() == "docker"

    def test_container_oci_returns_generic(self) -> None:
        """container=oci → 'generic'."""
        env = _clean_env(container="oci")
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() == "generic"

    def test_container_crio_returns_generic(self) -> None:
        """container=crio → 'generic'."""
        env = _clean_env(container="crio")
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() == "generic"

    def test_container_unknown_value_skips_to_next_check(self) -> None:
        """container=something-unknown → falls through to None (no marker files)."""
        env = _clean_env(container="something-unknown")
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() is None

    def test_container_var_case_insensitive_after_lowercase(self) -> None:
        """Env var value is lowercased before matching; 'Docker' still matches."""
        env = _clean_env(container="Docker")
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() == "docker"

    def test_container_var_strips_whitespace(self) -> None:
        """Leading/trailing whitespace is stripped."""
        env = _clean_env(container="  podman  ")
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() == "podman"


# ---------------------------------------------------------------------------
# detect_container_runtime() — marker file branches
# ---------------------------------------------------------------------------


class TestDetectContainerRuntimeMarkerFiles:
    """Tests for marker-file branches in detect_container_runtime()."""

    def test_docker_marker_file_returns_docker(self, tmp_path: Path) -> None:
        """/.dockerenv present → 'docker'."""
        docker_marker = tmp_path / ".dockerenv"
        docker_marker.touch()

        env = _clean_env(
            HOOKS_DAEMON_DOCKERENV_PATH=str(docker_marker),
            HOOKS_DAEMON_CONTAINERENV_PATH=_ABSENT_CONTAINERENV,
            HOOKS_DAEMON_CGROUP_PATH=_ABSENT_CGROUP,
        )
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() == "docker"

    def test_podman_marker_file_returns_podman(self, tmp_path: Path) -> None:
        """/run/.containerenv present → 'podman'."""
        podman_marker = tmp_path / ".containerenv"
        podman_marker.touch()

        env = _clean_env(
            HOOKS_DAEMON_DOCKERENV_PATH=_ABSENT_DOCKER,
            HOOKS_DAEMON_CONTAINERENV_PATH=str(podman_marker),
            HOOKS_DAEMON_CGROUP_PATH=_ABSENT_CGROUP,
        )
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() == "podman"

    def test_docker_marker_takes_priority_over_podman_marker(self, tmp_path: Path) -> None:
        """When both markers exist, docker env-var check comes first.

        In practice the env var is checked before marker files; marker file
        order is docker before podman per spec.
        """
        docker_marker = tmp_path / ".dockerenv"
        docker_marker.touch()
        podman_marker = tmp_path / ".containerenv"
        podman_marker.touch()

        env = _clean_env(
            HOOKS_DAEMON_DOCKERENV_PATH=str(docker_marker),
            HOOKS_DAEMON_CONTAINERENV_PATH=str(podman_marker),
            HOOKS_DAEMON_CGROUP_PATH=_ABSENT_CGROUP,
        )
        with patch.dict(os.environ, env, clear=True):
            # Docker marker file is checked first after container env var
            assert detect_container_runtime() == "docker"

    def test_no_marker_files_returns_none(self) -> None:
        """When no markers are present, returns None."""
        env = _clean_env()
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() is None


# ---------------------------------------------------------------------------
# detect_container_runtime() — cgroup branch
# ---------------------------------------------------------------------------


class TestDetectContainerRuntimeCgroup:
    """Tests for cgroup parsing branch in detect_container_runtime()."""

    def _write_cgroup(self, tmp_path: Path, content: str) -> Path:
        cgroup_file = tmp_path / "cgroup"
        cgroup_file.write_text(content)
        return cgroup_file

    def test_cgroup_containing_docker_returns_docker(self, tmp_path: Path) -> None:
        """cgroup with 'docker' → 'docker'."""
        cgroup = self._write_cgroup(tmp_path, "12:devices:/docker/abc123\n")
        env = _clean_env(HOOKS_DAEMON_CGROUP_PATH=str(cgroup))
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() == "docker"

    def test_cgroup_containing_libpod_returns_podman(self, tmp_path: Path) -> None:
        """cgroup with 'libpod' → 'podman'."""
        cgroup = self._write_cgroup(tmp_path, "12:devices:/libpod/abc123\n")
        env = _clean_env(HOOKS_DAEMON_CGROUP_PATH=str(cgroup))
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() == "podman"

    def test_cgroup_containing_podman_returns_podman(self, tmp_path: Path) -> None:
        """cgroup with 'podman' → 'podman'."""
        cgroup = self._write_cgroup(tmp_path, "12:devices:/podman/abc123\n")
        env = _clean_env(HOOKS_DAEMON_CGROUP_PATH=str(cgroup))
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() == "podman"

    def test_cgroup_containing_containerd_returns_generic(self, tmp_path: Path) -> None:
        """cgroup with 'containerd' → 'generic'."""
        cgroup = self._write_cgroup(tmp_path, "12:devices:/containerd/abc123\n")
        env = _clean_env(HOOKS_DAEMON_CGROUP_PATH=str(cgroup))
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() == "generic"

    def test_cgroup_containing_lxc_returns_generic(self, tmp_path: Path) -> None:
        """cgroup with 'lxc' → 'generic'."""
        cgroup = self._write_cgroup(tmp_path, "12:devices:/lxc/abc123\n")
        env = _clean_env(HOOKS_DAEMON_CGROUP_PATH=str(cgroup))
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() == "generic"

    def test_cgroup_containing_kubepods_returns_generic(self, tmp_path: Path) -> None:
        """cgroup with 'kubepods' → 'generic'."""
        cgroup = self._write_cgroup(tmp_path, "12:devices:/kubepods/abc123\n")
        env = _clean_env(HOOKS_DAEMON_CGROUP_PATH=str(cgroup))
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() == "generic"

    def test_cgroup_with_no_known_token_returns_none(self, tmp_path: Path) -> None:
        """cgroup with no known container tokens → None."""
        cgroup = self._write_cgroup(tmp_path, "11:memory:/system.slice/sshd.service\n")
        env = _clean_env(HOOKS_DAEMON_CGROUP_PATH=str(cgroup))
        with patch.dict(os.environ, env, clear=True):
            assert detect_container_runtime() is None

    def test_cgroup_oserror_returns_none(self) -> None:
        """OSError reading cgroup → fail-safe None (no exception raised)."""
        env = _clean_env(HOOKS_DAEMON_CGROUP_PATH=_ABSENT_CGROUP)
        with patch.dict(os.environ, env, clear=True):
            # Absent file → OSError on open → should return None gracefully
            result = detect_container_runtime()
            assert result is None


# ---------------------------------------------------------------------------
# in_container() and is_container_environment()
# ---------------------------------------------------------------------------


class TestInContainerAndIsContainerEnvironment:
    """Tests for in_container() and is_container_environment() wrappers."""

    def test_in_container_true_when_runtime_detected(self) -> None:
        """in_container() is True when detect_container_runtime() returns a string."""
        with patch(
            "claude_code_hooks_daemon.utils.container_detection.detect_container_runtime",
            return_value="docker",
        ):
            assert in_container() is True

    def test_in_container_false_when_no_runtime(self) -> None:
        """in_container() is False when detect_container_runtime() returns None."""
        with patch(
            "claude_code_hooks_daemon.utils.container_detection.detect_container_runtime",
            return_value=None,
        ):
            assert in_container() is False

    def test_is_container_environment_delegates_to_in_container(self) -> None:
        """is_container_environment() is a precise alias for in_container()."""
        with patch(
            "claude_code_hooks_daemon.utils.container_detection.detect_container_runtime",
            return_value="podman",
        ):
            assert is_container_environment() is True

        with patch(
            "claude_code_hooks_daemon.utils.container_detection.detect_container_runtime",
            return_value=None,
        ):
            assert is_container_environment() is False


# ---------------------------------------------------------------------------
# is_yolo_sandbox()
# ---------------------------------------------------------------------------


class TestIsYoloSandbox:
    """Tests for is_yolo_sandbox()."""

    def test_true_when_is_sandbox_one(self) -> None:
        """IS_SANDBOX=1 → True."""
        with patch.dict(os.environ, {"IS_SANDBOX": "1"}, clear=True):
            assert is_yolo_sandbox() is True

    def test_true_when_devcontainer_true(self) -> None:
        """DEVCONTAINER=true → True."""
        with patch.dict(os.environ, {"DEVCONTAINER": "true"}, clear=True):
            assert is_yolo_sandbox() is True

    def test_true_for_workspace_project_with_claude_config_dir(self) -> None:
        """Project root /workspace + .claude/ present → True."""
        with patch.dict(os.environ, {}, clear=True):
            mock_config_dir = MagicMock()
            mock_config_dir.exists.return_value = True
            with (
                patch(
                    "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
                    ".project_root",
                    return_value=Path("/workspace"),
                ),
                patch(
                    "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
                    ".config_dir",
                    return_value=mock_config_dir,
                ),
            ):
                assert is_yolo_sandbox() is True

    def test_false_for_non_workspace_project(self) -> None:
        """Project root /home/user → False (no SANDBOX/DEVCONTAINER either)."""
        with patch.dict(os.environ, {}, clear=True):
            mock_config_dir = MagicMock()
            mock_config_dir.exists.return_value = True
            with (
                patch(
                    "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
                    ".project_root",
                    return_value=Path("/home/user/myproject"),
                ),
                patch(
                    "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
                    ".config_dir",
                    return_value=mock_config_dir,
                ),
            ):
                assert is_yolo_sandbox() is False

    def test_false_for_workspace_without_claude_config_dir(self) -> None:
        """Project root /workspace but .claude/ absent → False."""
        with patch.dict(os.environ, {}, clear=True):
            mock_config_dir = MagicMock()
            mock_config_dir.exists.return_value = False
            with (
                patch(
                    "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
                    ".project_root",
                    return_value=Path("/workspace"),
                ),
                patch(
                    "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
                    ".config_dir",
                    return_value=mock_config_dir,
                ),
            ):
                assert is_yolo_sandbox() is False

    def test_false_purely_from_claudecode_env_var(self) -> None:
        """CLAUDECODE=1 alone MUST NOT trigger is_yolo_sandbox().

        This is a key separation-of-concerns test: running_under_claude_code
        and is_yolo_sandbox are orthogonal concepts.
        """
        with patch.dict(os.environ, {"CLAUDECODE": "1"}, clear=True):
            mock_config_dir = MagicMock()
            mock_config_dir.exists.return_value = False
            with (
                patch(
                    "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
                    ".project_root",
                    return_value=Path("/home/user/project"),
                ),
                patch(
                    "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
                    ".config_dir",
                    return_value=mock_config_dir,
                ),
            ):
                assert is_yolo_sandbox() is False

    def test_false_purely_from_entrypoint_env_var(self) -> None:
        """CLAUDE_CODE_ENTRYPOINT=cli alone MUST NOT trigger is_yolo_sandbox()."""
        with patch.dict(os.environ, {"CLAUDE_CODE_ENTRYPOINT": "cli"}, clear=True):
            mock_config_dir = MagicMock()
            mock_config_dir.exists.return_value = False
            with (
                patch(
                    "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
                    ".project_root",
                    return_value=Path("/home/user/project"),
                ),
                patch(
                    "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
                    ".config_dir",
                    return_value=mock_config_dir,
                ),
            ):
                assert is_yolo_sandbox() is False

    def test_failsafe_on_project_context_oserror(self) -> None:
        """ProjectContext raising OSError → fail-safe False, no exception."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext" ".project_root",
                side_effect=OSError("filesystem error"),
            ):
                result = is_yolo_sandbox()
                assert result is False

    def test_failsafe_on_project_context_runtime_error(self) -> None:
        """ProjectContext raising RuntimeError → fail-safe False, no exception."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext" ".project_root",
                side_effect=RuntimeError("context error"),
            ):
                result = is_yolo_sandbox()
                assert result is False
