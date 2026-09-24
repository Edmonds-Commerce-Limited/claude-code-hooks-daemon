"""The raw (unresolved) half of Bash write-target detection (Plan 00461).

``get_bash_write_targets`` answers "which files does this command plainly
write" and, by contract, DROPS a destination it cannot resolve. A deny guard
also needs the other answer, "which destinations did it name that could not be
placed", so it can fail closed on them. The two answers come from ONE parser:
these tests pin the public raw half, and that the resolved half is built on it.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.core.utils import (
    bash_write_destinations,
    get_bash_write_targets,
    resolve_bash_write_destination,
    split_heredocs,
)


class TestBashWriteDestinations:
    def test_redirect_and_tee_destinations_are_authored(self) -> None:
        destinations = bash_write_destinations("echo x >> a.md && echo y | tee -a b.md")
        assert [(d.destination, d.authored) for d in destinations] == [
            ("a.md", True),
            ("b.md", True),
        ]

    def test_copy_destination_is_a_relocation(self) -> None:
        destinations = bash_write_destinations("cp src.md dest.md")
        assert [(d.destination, d.authored) for d in destinations] == [("dest.md", False)]

    def test_an_expansion_is_kept_raw_rather_than_dropped(self) -> None:
        """The resolved accessor drops this; the raw one must not."""
        destinations = bash_write_destinations("echo x >> dir/00461-Journal-$(date).md")
        assert [d.destination for d in destinations] == ["dir/00461-Journal-$"]

    def test_heredoc_bodies_are_not_scanned(self) -> None:
        command = "cat > notes.md <<'EOF'\necho x > phantom.md\nEOF"
        assert [d.destination for d in bash_write_destinations(command)] == ["notes.md"]


class TestResolveBashWriteDestination:
    def test_resolves_against_cwd(self, tmp_path: Path) -> None:
        (destination,) = bash_write_destinations("echo x > out.md")
        assert resolve_bash_write_destination(destination, str(tmp_path)) == [
            str(tmp_path / "out.md")
        ]

    def test_declines_an_expansion(self, tmp_path: Path) -> None:
        (destination,) = bash_write_destinations("echo x > $OUT")
        assert resolve_bash_write_destination(destination, str(tmp_path)) == []

    def test_the_resolved_accessor_agrees(self, tmp_path: Path) -> None:
        command = "echo x > a.md; cp b.md c.md"
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tmp_path)}
        via_raw = [
            path
            for destination in bash_write_destinations(command)
            for path in resolve_bash_write_destination(destination, str(tmp_path))
        ]
        assert get_bash_write_targets(hook_input) == via_raw


class TestSplitHeredocs:
    def test_pairs_each_body_with_its_opener_line(self) -> None:
        command = "python3 - <<'PY'\nprint(1)\nPY\ncat > n.md <<EOF\nhello\nEOF"

        outside, heredocs = split_heredocs(command)

        assert outside == "python3 - <<'PY'\ncat > n.md <<EOF"
        assert [(h.opener_line, h.body) for h in heredocs] == [
            ("python3 - <<'PY'", "print(1)"),
            ("cat > n.md <<EOF", "hello"),
        ]

    def test_no_heredoc_leaves_the_command_whole(self) -> None:
        assert split_heredocs("echo a\necho b") == ("echo a\necho b", [])
