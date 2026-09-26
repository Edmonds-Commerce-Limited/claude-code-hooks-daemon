"""A command the tokeniser cannot read is not a command that writes nothing.

Plan 00466 N120. ``_tokenise`` read the whole outside-bodies text as one string
and returned no targets when shlex raised. Bash runs every complete command
before an unparseable one, so an unbalanced quote on line 2 hid the write on
line 1 from every guard that denies on a write location. The text is now read
one complete command at a time, and whatever still cannot be read is reported
as ``unreadable`` so a denying caller can fail closed on it.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.core.utils import (
    bash_write_destinations,
    get_bash_write_targets,
    get_written_file_paths,
    scan_bash_write_destinations,
    scan_bash_write_targets,
    split_heredocs,
)

#: Shapes where line 1 is a complete write bash runs, and a later line is not
#: something shlex can read.
_WRITE_THEN_UNREADABLE = [
    'echo x > /opt/o.md\nx="u',
    "cat > /opt/n.md <<<'EOF'\n)\"\nEOF",
    "cat > /opt/n.md <<<'EOF'\necho it's",
    'cat > /opt/o.md <<<hi\nx="u',
]

#: Delimiter spellings bash accepts, as (opener word, closing line).
_DELIMITERS = [
    ("'my-notes'", "my-notes"),
    ("EOF-1", "EOF-1"),
    ("END.MD", "END.MD"),
    ("\\EOF", "EOF"),
    ('"EOF-1"', "EOF-1"),
    ('E"O"F', "EOF"),
]


def _bash(command: str) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/repo"}


class TestEveryCompleteCommandIsJudged:
    @pytest.mark.parametrize("command", _WRITE_THEN_UNREADABLE)
    def test_the_write_before_the_unreadable_line_is_named(self, command: str) -> None:
        assert [d.destination for d in bash_write_destinations(command)] == [
            command.split("\n")[0].split("> ")[1].split(" ")[0]
        ]

    @pytest.mark.parametrize("command", _WRITE_THEN_UNREADABLE)
    def test_the_resolved_accessor_names_it_too(self, command: str) -> None:
        assert get_bash_write_targets(_bash(command)) == [
            command.split("\n")[0].split("> ")[1].split(" ")[0]
        ]

    def test_a_quoted_argument_spanning_lines_stays_one_command(self) -> None:
        assert [d.destination for d in bash_write_destinations('echo "a\nb" > /opt/x')] == [
            "/opt/x"
        ]


class TestDelimiterSpellingsKeepProseOutOfTheTokeniser:
    @pytest.mark.parametrize(("opener", "closer"), _DELIMITERS)
    def test_the_introducing_line_is_still_read(self, opener: str, closer: str) -> None:
        command = f"cat > /opt/o.md <<{opener}\nit's done\n{closer}"
        assert [d.destination for d in bash_write_destinations(command)] == ["/opt/o.md"]

    @pytest.mark.parametrize(("opener", "closer"), _DELIMITERS)
    def test_the_body_is_split_off_as_data(self, opener: str, closer: str) -> None:
        command = f"cat > /opt/o.md <<{opener}\nit's done\n{closer}\necho after"
        outside, heredocs = split_heredocs(command)
        assert [(h.body, h.delimiter) for h in heredocs] == [("it's done", closer)]
        assert outside == f"cat > /opt/o.md <<{opener}\necho after"

    @pytest.mark.parametrize(("opener", "closer"), _DELIMITERS)
    def test_nothing_is_left_unreadable(self, opener: str, closer: str) -> None:
        command = f"cat > /opt/o.md <<{opener}\nit's done\n{closer}"
        assert scan_bash_write_destinations(command).unreadable is None


class TestUnreadableTextIsReported:
    @pytest.mark.parametrize("command", _WRITE_THEN_UNREADABLE)
    def test_the_unreadable_remainder_is_reported(self, command: str) -> None:
        scan = scan_bash_write_destinations(command)
        assert scan.unreadable is not None
        assert scan.unreadable.strip() != ""

    def test_an_unterminated_ansi_c_string_is_unreadable(self) -> None:
        scan = scan_bash_write_destinations("echo $'it > /opt/x")
        assert scan.destinations == []
        assert scan.unreadable == "echo $'it > /opt/x"


class TestShlexReadsTheLineAsBashDoes:
    """Plan 00466 N120: two places shlex and bash disagree WITHOUT shlex
    raising, so the rest of the line was silently misread. Both named no
    target on main while bash wrote one."""

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("echo a#b > /opt/o.md", ["/opt/o.md"]),
            ("curl http://x/#frag > /opt/f", ["/opt/f"]),
            ("echo x#y; echo z > /opt/o.md", ["/opt/o.md"]),
            ("echo $'it\\'s' > /opt/x \\'", ["/opt/x"]),
            ("echo $'it\\'s' > /opt/x", ["/opt/x"]),
            ("echo $'it\\'s' && echo '## 14:05' >> /opt/j.md", ["/opt/j.md"]),
            ("echo x > $'/opt/a\\x41'", ["/opt/aA"]),
            ("echo x > $'/opt/q\\'s'", ["/opt/q's"]),
            ("echo x > $'/opt/n\\0ul'", ["/opt/n"]),
        ],
    )
    def test_the_write_bash_performs_is_named(self, command: str, expected: list[str]) -> None:
        scan = scan_bash_write_destinations(command)
        assert [d.destination for d in scan.destinations] == expected
        assert scan.unreadable is None

    @pytest.mark.parametrize(
        "command",
        [
            "echo x # > /opt/o.md",
            "echo x;# > /opt/o.md",
            "# echo x > /opt/o.md",
        ],
    )
    def test_a_real_comment_writes_nothing(self, command: str) -> None:
        scan = scan_bash_write_destinations(command)
        assert scan.destinations == []
        assert scan.unreadable is None

    @pytest.mark.parametrize(
        "command", ["echo 'a #b' > /opt/o.md", 'echo "#" > /opt/o.md', "echo \\#x > /opt/o.md"]
    )
    def test_a_quoted_or_escaped_hash_is_a_character(self, command: str) -> None:
        assert [d.destination for d in bash_write_destinations(command)] == ["/opt/o.md"]

    def test_a_readable_command_reports_nothing_unreadable(self) -> None:
        scan = scan_bash_write_destinations("echo x > a.md\necho y > b.md")
        assert [d.destination for d in scan.destinations] == ["a.md", "b.md"]
        assert scan.unreadable is None

    def test_an_unreadable_heredoc_body_is_not_unreadable_command_text(self) -> None:
        """A body is data; one shlex cannot read costs that body only."""
        command = "cat > a.md <<EOF\nit's > b.md\nEOF"
        scan = scan_bash_write_destinations(command, include_heredoc_bodies=True)
        assert [d.destination for d in scan.destinations] == ["a.md"]
        assert scan.unreadable is None

    def test_the_resolved_scan_carries_it(self) -> None:
        scan = scan_bash_write_targets(_bash('echo x > /opt/o.md\nx="u'))
        assert scan.paths == ["/opt/o.md"]
        assert scan.unreadable == 'x="u'

    def test_a_non_bash_event_is_fully_read(self) -> None:
        scan = scan_bash_write_targets({"tool_name": "Write", "tool_input": {}})
        assert scan.paths == []
        assert scan.unreadable is None


class TestContentGuardsLintOnlyWhatTheyCanName:
    """Plan 00466 N120: ``lint_on_edit`` and ``validate_eslint_on_write`` read
    ``get_written_file_paths``. Unreadable text names no file, so there is
    nothing to lint; the complete command before it is still named."""

    def test_the_readable_write_is_named_and_the_unreadable_tail_is_not(self) -> None:
        hook_input = _bash("echo 'x = 1' > /opt/a.py\necho $'it > /opt/b.py")
        assert get_written_file_paths(hook_input) == ["/opt/a.py"]

    def test_an_ansi_c_string_no_longer_hides_the_write(self) -> None:
        assert get_written_file_paths(_bash("echo $'it\\'s' > /opt/a.py")) == ["/opt/a.py"]
