"""Tests for core.utils targeting branch coverage."""

from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.core.utils import get_workspace_root


class TestGetWorkspaceRoot:
    """Tests for get_workspace_root function targeting branch coverage."""

    def test_get_workspace_root_fallback_to_cwd(self, tmp_path: Path, monkeypatch: any) -> None:
        """Falls back to cwd when no project root found (line 74 branch)."""
        # Create a directory without .git or CLAUDE
        test_dir = tmp_path / "isolated"
        test_dir.mkdir()

        # Change cwd to this isolated directory
        monkeypatch.chdir(test_dir)

        # Mock __file__ to point to isolated directory
        with patch("claude_code_hooks_daemon.core.utils.__file__", str(test_dir / "utils.py")):
            # Should fall back to cwd (line 74)
            result = get_workspace_root()
            assert result == test_dir
