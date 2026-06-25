"""Tests for the `regenerate-docs` CLI command (cmd_regenerate_docs).

The command force-regenerates BOTH generated-doc artifacts in one shot:

1. ``.claude/HOOKS-DAEMON.md`` — via the same DocsGenerator path as ``generate-docs``.
2. The ``<hooksdaemon>`` guidance block inside the project ``CLAUDE.md`` — via the same
   ClaudeMdInjector path the daemon runs at startup.

This is the explicit, no-restart way to canonicalise both artifacts — useful when
resolving a git merge conflict that left stale or conflict-marked generated content.
"""

import argparse
import subprocess
from pathlib import Path

from claude_code_hooks_daemon.daemon.cli import cmd_init_config, cmd_regenerate_docs


def _init_git_repo(path: Path) -> None:
    """Init a git repo with a remote origin (ProjectContext FAIL-FASTs without one)."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.com/acme/demo-project.git"],
        cwd=path,
        capture_output=True,
        check=True,
    )


def _scaffold_project(tmp_path: Path) -> Path:
    """Create a git-backed project with a full hooks-daemon.yaml and return its root."""
    _init_git_repo(tmp_path)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "hooks-daemon").mkdir()

    init_args = argparse.Namespace(project_root=tmp_path, minimal=False, force=False)
    assert cmd_init_config(init_args) == 0
    assert (claude_dir / "hooks-daemon.yaml").exists()
    return tmp_path


def _regen_args(project_root: Path) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=project_root,
        include_disabled=False,
        output=None,
    )


class TestCmdRegenerateDocs:
    """Behaviour of the regenerate-docs command."""

    def test_writes_hooks_daemon_md(self, tmp_path: Path) -> None:
        """Regenerates .claude/HOOKS-DAEMON.md from live config + handler metadata."""
        project = _scaffold_project(tmp_path)

        result = cmd_regenerate_docs(_regen_args(project))

        assert result == 0
        hooks_doc = project / ".claude" / "HOOKS-DAEMON.md"
        assert hooks_doc.exists()
        assert "Hooks Daemon" in hooks_doc.read_text()

    def test_injects_hooksdaemon_block_into_claude_md(self, tmp_path: Path) -> None:
        """Regenerates the <hooksdaemon> block, preserving surrounding user content."""
        project = _scaffold_project(tmp_path)
        claude_md = project / "CLAUDE.md"
        user_content = "# My Project\n\nImportant user instructions that must survive.\n"
        claude_md.write_text(user_content)

        result = cmd_regenerate_docs(_regen_args(project))

        assert result == 0
        updated = claude_md.read_text()
        assert "<hooksdaemon>" in updated
        assert "</hooksdaemon>" in updated
        # User content outside the block is preserved.
        assert "Important user instructions that must survive." in updated

    def test_force_replaces_stale_or_conflicted_block(self, tmp_path: Path) -> None:
        """A pre-existing (stale/conflict-marked) block is fully replaced — exactly one remains.

        Models the git-merge-conflict recovery use case: the generated block is left in a
        broken state and must be force-regenerated to the canonical form.
        """
        project = _scaffold_project(tmp_path)
        claude_md = project / "CLAUDE.md"
        stale = (
            "# My Project\n\n"
            "<hooksdaemon>\n"
            "<<<<<<< HEAD\n"
            "## Stale guidance from branch A\n"
            "=======\n"
            "## Stale guidance from branch B\n"
            ">>>>>>> other\n"
            "</hooksdaemon>\n\n"
            "Trailing user content.\n"
        )
        claude_md.write_text(stale)

        result = cmd_regenerate_docs(_regen_args(project))

        assert result == 0
        updated = claude_md.read_text()
        # Conflict markers and stale headings are gone.
        assert "<<<<<<<" not in updated
        assert "Stale guidance from branch A" not in updated
        assert "Stale guidance from branch B" not in updated
        # Exactly one regenerated block, user content intact.
        assert updated.count("<hooksdaemon>") == 1
        assert updated.count("</hooksdaemon>") == 1
        assert "Trailing user content." in updated

    def test_missing_config_returns_one(self, tmp_path: Path) -> None:
        """With no hooks-daemon.yaml present, the command fails cleanly (exit 1)."""
        (tmp_path / ".claude").mkdir()

        result = cmd_regenerate_docs(_regen_args(tmp_path))

        assert result == 1
