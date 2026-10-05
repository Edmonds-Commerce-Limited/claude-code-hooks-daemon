"""Test helper: give a throwaway directory the protected-file index a guard consults.

The guards judge recursive reads and globs against the cached index of protected
files (``utils.protected_file_index``), which is built from ``git ls-files``. A
test that wants a guard to see the files it created under ``tmp_path`` makes the
directory a git repository, builds the index and registers it here.
"""

import subprocess  # nosec B404 - fixed git argv in a tmp repository
from pathlib import Path

from claude_code_hooks_daemon.utils import protected_file_index
from claude_code_hooks_daemon.utils.protected_file_index import ProtectedFileIndex


def index_project(root: Path, patterns: tuple[str, ...]) -> ProtectedFileIndex:
    """Index ``root`` (made a git repository if it is not one) and serve it to the guards."""
    if not (root / ".git").exists():
        subprocess.run(
            ["git", "-C", str(root), "init", "-q"], check=True, capture_output=True
        )  # nosec B603 B607
    index = protected_file_index.build_index(root, tuple(patterns))
    assert index is not None
    protected_file_index.remember(index)
    return index
