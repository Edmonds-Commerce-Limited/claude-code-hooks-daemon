"""Tests for core.utils targeting branch coverage."""

from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.core.utils import get_workspace_root


class TestGetWorkspaceRoot:
    """Tests for get_workspace_root function targeting branch coverage."""

    def test_get_workspace_root_fallback_to_project_context(
        self, tmp_path: Path, monkeypatch: any
    ) -> None:
        """Falls back to ProjectContext when no .git/CLAUDE markers found (line 76 branch)."""
        # Create a directory without .git or CLAUDE
        test_dir = tmp_path / "isolated"
        test_dir.mkdir()

        # Change cwd to this isolated directory
        monkeypatch.chdir(test_dir)

        # Mock __file__ to point to isolated directory and mock ProjectContext
        with patch("claude_code_hooks_daemon.core.utils.__file__", str(test_dir / "utils.py")):
            with patch(
                "claude_code_hooks_daemon.core.utils.ProjectContext.project_root"
            ) as mock_root:
                mock_root.return_value = test_dir
                # Should fall back to ProjectContext.project_root() (line 76)
                result = get_workspace_root()
                assert result == test_dir
                mock_root.assert_called_once()
