"""
Unit tests for container detection utility.

Tests the reusable container detection logic extracted from
yolo_container_detection handler.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from claude_code_hooks_daemon.utils.container_detection import (
    get_container_confidence_score,
    get_detected_indicators,
    is_container_environment,
)


class TestContainerConfidenceScore:
    """Tests for get_container_confidence_score()."""

    def test_score_zero_with_no_indicators(self) -> None:
        """No indicators should return score of 0."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    score = get_container_confidence_score()
                    assert score == 0

    def test_primary_indicator_claudecode(self) -> None:
        """CLAUDECODE=1 should add 3 points."""
        with patch.dict(os.environ, {"CLAUDECODE": "1"}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    score = get_container_confidence_score()
                    assert score == 3

    def test_primary_indicator_entrypoint(self) -> None:
        """CLAUDE_CODE_ENTRYPOINT=cli should add 3 points."""
        with patch.dict(os.environ, {"CLAUDE_CODE_ENTRYPOINT": "cli"}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    score = get_container_confidence_score()
                    assert score == 3

    def test_primary_indicator_workspace_with_claude_dir(self) -> None:
        """Project root at /workspace with .claude/ should add 3 points."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/workspace")
                mock_config_dir = MagicMock()
                mock_config_dir.exists.return_value = True
                mock_ctx.config_dir.return_value = mock_config_dir
                with patch("os.getuid", return_value=1000):
                    score = get_container_confidence_score()
                    assert score == 3

    def test_primary_indicator_workspace_without_claude_dir(self) -> None:
        """Project root at /workspace without .claude/ should add 0 points."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/workspace")
                mock_config_dir = MagicMock()
                mock_config_dir.exists.return_value = False
                mock_ctx.config_dir.return_value = mock_config_dir
                with patch("os.getuid", return_value=1000):
                    score = get_container_confidence_score()
                    assert score == 0

    def test_secondary_indicator_devcontainer(self) -> None:
        """DEVCONTAINER=true should add 2 points."""
        with patch.dict(os.environ, {"DEVCONTAINER": "true"}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    score = get_container_confidence_score()
                    assert score == 2

    def test_secondary_indicator_is_sandbox(self) -> None:
        """IS_SANDBOX=1 should add 2 points."""
        with patch.dict(os.environ, {"IS_SANDBOX": "1"}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    score = get_container_confidence_score()
                    assert score == 2

    def test_secondary_indicator_container_docker(self) -> None:
        """container=docker should add 2 points."""
        with patch.dict(os.environ, {"container": "docker"}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    score = get_container_confidence_score()
                    assert score == 2

    def test_secondary_indicator_container_podman(self) -> None:
        """container=podman should add 2 points."""
        with patch.dict(os.environ, {"container": "podman"}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    score = get_container_confidence_score()
                    assert score == 2

    def test_secondary_indicator_container_other_value(self) -> None:
        """container=other should add 0 points."""
        with patch.dict(os.environ, {"container": "other"}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    score = get_container_confidence_score()
                    assert score == 0

    def test_tertiary_indicator_socket_exists(self, tmp_path: Path) -> None:
        """Socket file existence should add 1 point."""
        # Create socket file
        socket_dir = tmp_path / ".claude" / "hooks-daemon" / "untracked" / "venv"
        socket_dir.mkdir(parents=True)
        socket_file = socket_dir / "socket"
        socket_file.touch()

        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch(
                    "claude_code_hooks_daemon.utils.container_detection.Path"
                ) as mock_path_cls:
                    mock_path_cls.return_value = socket_file
                    with patch("os.getuid", return_value=1000):
                        score = get_container_confidence_score()
                        assert score == 1

    def test_tertiary_indicator_root_user(self) -> None:
        """Running as root (UID 0) should add 1 point."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=0):
                    score = get_container_confidence_score()
                    assert score == 1

    def test_tertiary_indicator_non_root_user(self) -> None:
        """Running as non-root should add 0 points."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    score = get_container_confidence_score()
                    assert score == 0

    def test_multiple_indicators_cumulative(self) -> None:
        """Multiple indicators should accumulate scores."""
        with patch.dict(
            os.environ,
            {
                "CLAUDECODE": "1",  # 3 points
                "DEVCONTAINER": "true",  # 2 points
                "container": "docker",  # 2 points
            },
            clear=True,
        ):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=0):  # 1 point
                    score = get_container_confidence_score()
                    assert score == 8  # 3 + 2 + 2 + 1

    def test_handles_os_error_gracefully(self) -> None:
        """OSError should be handled gracefully."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.side_effect = OSError("Filesystem error")
                with patch("os.getuid", return_value=1000):
                    score = get_container_confidence_score()
                    assert score == 0

    def test_handles_runtime_error_gracefully(self) -> None:
        """RuntimeError should be handled gracefully."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.side_effect = RuntimeError("Context error")
                with patch("os.getuid", return_value=1000):
                    score = get_container_confidence_score()
                    assert score == 0

    def test_handles_attribute_error_gracefully(self) -> None:
        """AttributeError (Windows getuid) should be handled gracefully."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", side_effect=AttributeError("Windows")):
                    score = get_container_confidence_score()
                    assert score == 0


class TestIsContainerEnvironment:
    """Tests for is_container_environment()."""

    def test_returns_true_when_score_equals_threshold(self) -> None:
        """Score exactly at threshold should return True."""
        with patch(
            "claude_code_hooks_daemon.utils.container_detection.get_container_confidence_score",
            return_value=3,
        ):
            assert is_container_environment() is True

    def test_returns_true_when_score_above_threshold(self) -> None:
        """Score above threshold should return True."""
        with patch(
            "claude_code_hooks_daemon.utils.container_detection.get_container_confidence_score",
            return_value=5,
        ):
            assert is_container_environment() is True

    def test_returns_false_when_score_below_threshold(self) -> None:
        """Score below threshold should return False."""
        with patch(
            "claude_code_hooks_daemon.utils.container_detection.get_container_confidence_score",
            return_value=2,
        ):
            assert is_container_environment() is False

    def test_returns_false_when_score_zero(self) -> None:
        """Score of 0 should return False."""
        with patch(
            "claude_code_hooks_daemon.utils.container_detection.get_container_confidence_score",
            return_value=0,
        ):
            assert is_container_environment() is False

    def test_uses_default_threshold_of_3(self) -> None:
        """Default threshold should be 3."""
        with patch(
            "claude_code_hooks_daemon.utils.container_detection.get_container_confidence_score",
            return_value=3,
        ):
            assert is_container_environment() is True

        with patch(
            "claude_code_hooks_daemon.utils.container_detection.get_container_confidence_score",
            return_value=2,
        ):
            assert is_container_environment() is False


class TestGetDetectedIndicators:
    """Tests for get_detected_indicators()."""

    def test_empty_list_with_no_indicators(self) -> None:
        """No indicators should return empty list."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    indicators = get_detected_indicators()
                    assert indicators == []

    def test_claudecode_indicator(self) -> None:
        """CLAUDECODE=1 should be in indicators list."""
        with patch.dict(os.environ, {"CLAUDECODE": "1"}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    indicators = get_detected_indicators()
                    assert "CLAUDECODE=1 environment variable" in indicators

    def test_entrypoint_indicator(self) -> None:
        """CLAUDE_CODE_ENTRYPOINT=cli should be in indicators list."""
        with patch.dict(os.environ, {"CLAUDE_CODE_ENTRYPOINT": "cli"}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    indicators = get_detected_indicators()
                    assert "CLAUDE_CODE_ENTRYPOINT=cli environment variable" in indicators

    def test_workspace_indicator(self) -> None:
        """Workspace with .claude/ should be in indicators list."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/workspace")
                mock_config_dir = MagicMock()
                mock_config_dir.exists.return_value = True
                mock_ctx.config_dir.return_value = mock_config_dir
                with patch("os.getuid", return_value=1000):
                    indicators = get_detected_indicators()
                    assert "Project root is /workspace with .claude/ present" in indicators

    def test_devcontainer_indicator(self) -> None:
        """DEVCONTAINER=true should be in indicators list."""
        with patch.dict(os.environ, {"DEVCONTAINER": "true"}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    indicators = get_detected_indicators()
                    assert "DEVCONTAINER=true environment variable" in indicators

    def test_is_sandbox_indicator(self) -> None:
        """IS_SANDBOX=1 should be in indicators list."""
        with patch.dict(os.environ, {"IS_SANDBOX": "1"}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    indicators = get_detected_indicators()
                    assert "IS_SANDBOX=1 environment variable" in indicators

    def test_container_docker_indicator(self) -> None:
        """container=docker should be in indicators list."""
        with patch.dict(os.environ, {"container": "docker"}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    indicators = get_detected_indicators()
                    assert "container=docker environment variable" in indicators

    def test_container_podman_indicator(self) -> None:
        """container=podman should be in indicators list."""
        with patch.dict(os.environ, {"container": "podman"}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    indicators = get_detected_indicators()
                    assert "container=podman environment variable" in indicators

    def test_socket_indicator(self, tmp_path: Path) -> None:
        """Socket file should be in indicators list."""
        socket_dir = tmp_path / ".claude" / "hooks-daemon" / "untracked" / "venv"
        socket_dir.mkdir(parents=True)
        socket_file = socket_dir / "socket"
        socket_file.touch()

        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch(
                    "claude_code_hooks_daemon.utils.container_detection.Path"
                ) as mock_path_cls:
                    mock_path_cls.return_value = socket_file
                    with patch("os.getuid", return_value=1000):
                        indicators = get_detected_indicators()
                        assert "Hooks daemon Unix socket present" in indicators

    def test_root_user_indicator(self) -> None:
        """Root user should be in indicators list."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=0):
                    indicators = get_detected_indicators()
                    assert "Running as root user (UID 0)" in indicators

    def test_multiple_indicators(self) -> None:
        """Multiple indicators should all be in list."""
        with patch.dict(
            os.environ,
            {
                "CLAUDECODE": "1",
                "DEVCONTAINER": "true",
                "container": "docker",
            },
            clear=True,
        ):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", return_value=1000):
                    indicators = get_detected_indicators()
                    assert len(indicators) == 3
                    assert "CLAUDECODE=1 environment variable" in indicators
                    assert "DEVCONTAINER=true environment variable" in indicators
                    assert "container=docker environment variable" in indicators

    def test_handles_os_error_gracefully(self) -> None:
        """OSError should be handled gracefully."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.side_effect = OSError("Filesystem error")
                with patch("os.getuid", return_value=1000):
                    indicators = get_detected_indicators()
                    assert indicators == []

    def test_handles_runtime_error_gracefully(self) -> None:
        """RuntimeError should be handled gracefully."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.side_effect = RuntimeError("Context error")
                with patch("os.getuid", return_value=1000):
                    indicators = get_detected_indicators()
                    assert indicators == []

    def test_handles_attribute_error_gracefully(self) -> None:
        """AttributeError (Windows getuid) should be handled gracefully."""
        with patch.dict(os.environ, {}, clear=True):
            with patch(
                "claude_code_hooks_daemon.utils.container_detection.ProjectContext"
            ) as mock_ctx:
                mock_ctx.project_root.return_value = Path("/home/user/project")
                with patch("os.getuid", side_effect=AttributeError("Windows")):
                    indicators = get_detected_indicators()
                    # Should still have other indicators, just not root user
                    assert "Running as root user (UID 0)" not in indicators
