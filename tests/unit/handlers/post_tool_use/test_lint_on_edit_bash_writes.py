"""`lint_on_edit` sees files a Bash command AUTHORED, not just Write/Edit ones.

Plan 00260 Task 3.5. Until this, `cat > x.py <<'EOF'` put unparseable Python on
disk in silence while the identical content through `Write` was denied — so the
route that looked safest, because nothing complained, was the only unguarded
one. That is the inversion this closes.

Two properties matter more than the happy path, and both are pinned here:

- **Relocation is never linted.** `cp broken.py copy.py` writes a file, and the
  memory-path guard must see it. This handler must not: the bytes were already
  on disk and already broken, so denying the copy reports a defect the command
  did not introduce and leaves the agent repairing a file it never wrote.
- **A predicted path that does not exist is never linted.** For Write/Edit the
  file is certainly there. For Bash the target is inferred from the command
  text, and a command that failed leaves nothing — linting it would manufacture
  an error no edit can clear.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import LintOnEditHandler


def _bash(command: str, cwd: Path) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


class TestBashAuthoredFilesAreLinted:
    def test_a_heredoc_authoring_python_matches(self, tmp_path: Path) -> None:
        target = tmp_path / "authored.py"
        target.write_text("import os\n")
        command = f"cat > {target} <<'EOF'\nimport os\nEOF"

        assert LintOnEditHandler().matches(_bash(command, tmp_path)) is True

    def test_a_plain_redirect_authoring_python_matches(self, tmp_path: Path) -> None:
        target = tmp_path / "authored.py"
        target.write_text("import os\n")

        assert LintOnEditHandler().matches(_bash(f"echo x > {target}", tmp_path)) is True

    def test_tee_authoring_two_python_files_matches(self, tmp_path: Path) -> None:
        first = tmp_path / "one.py"
        second = tmp_path / "two.py"
        first.write_text("import os\n")
        second.write_text("import sys\n")
        command = f"echo x | tee {first} {second}"

        handler = LintOnEditHandler()
        assert handler.matches(_bash(command, tmp_path)) is True
        # Both are in scope, not just the first -- a command can author several.
        assert handler._lintable_paths(_bash(command, tmp_path)) == [str(first), str(second)]


class TestRelocationIsNeverLinted:
    """The distinction that makes this safe to enable by default."""

    def test_a_copy_does_not_match_even_though_it_writes(self, tmp_path: Path) -> None:
        source = tmp_path / "source.py"
        destination = tmp_path / "copy.py"
        source.write_text("import os\n")
        destination.write_text("import os\n")

        command = f"cp {source} {destination}"
        assert LintOnEditHandler().matches(_bash(command, tmp_path)) is False

    def test_a_move_does_not_match(self, tmp_path: Path) -> None:
        destination = tmp_path / "moved.py"
        destination.write_text("import os\n")

        command = f"mv {tmp_path / 'gone.py'} {destination}"
        assert LintOnEditHandler().matches(_bash(command, tmp_path)) is False


class TestPathsThatCannotBeLinted:
    def test_a_predicted_target_that_does_not_exist_does_not_match(self, tmp_path: Path) -> None:
        missing = tmp_path / "never-written.py"

        assert LintOnEditHandler().matches(_bash(f"echo x > {missing}", tmp_path)) is False

    def test_an_unknown_language_does_not_match(self, tmp_path: Path) -> None:
        target = tmp_path / "notes.xyz"
        target.write_text("whatever\n")

        assert LintOnEditHandler().matches(_bash(f"echo x > {target}", tmp_path)) is False

    def test_prose_containing_an_arrow_does_not_match(self, tmp_path: Path) -> None:
        assert LintOnEditHandler().matches(_bash("echo 'an arrow > thing'", tmp_path)) is False


class TestTheOptOut:
    """A project can decline the new surface without disabling the handler."""

    def test_disabling_bash_linting_stops_matching_bash(self, tmp_path: Path) -> None:
        target = tmp_path / "authored.py"
        target.write_text("import os\n")

        handler = LintOnEditHandler()
        handler._lint_bash_writes = False

        assert handler.matches(_bash(f"echo x > {target}", tmp_path)) is False

    def test_disabling_bash_linting_leaves_write_untouched(self, tmp_path: Path) -> None:
        target = tmp_path / "authored.py"
        target.write_text("import os\n")

        handler = LintOnEditHandler()
        handler._lint_bash_writes = False

        payload = {"tool_name": "Write", "tool_input": {"file_path": str(target)}}
        assert handler.matches(payload) is True
