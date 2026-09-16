"""The shared message-file reader — Plan 00412 D-PUB-2.

Two handlers had near-identical copies of this: `github_auto_close_keywords`
read `git commit -F <file>`, and `sensitive_content` read a `gh --body-file`.
Same flags, same 64 KiB bound, same encoding, same stdin skip — and the second
copy was wired only into its `gh` branch, so a term in a git message FILE was
never scanned while the same term inline was denied.

Two spellings of one concept is what let them drift, so the concept gets one
home and both callers reach it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.utils import message_files
from claude_code_hooks_daemon.utils.message_files import (
    MAX_MESSAGE_FILE_BYTES,
    MessageFile,
    read_message_files,
)


class TestWhichFlagsNameAFile:
    def test_it_reads_every_flag_both_handlers_recognised(self, tmp_path: Path) -> None:
        body = tmp_path / "msg.txt"
        body.write_text("the payload\n")

        for flag in ("-F", "--file", "--body-file"):
            for joiner in (" ", "="):
                found = read_message_files(f"git commit {flag}{joiner}{body}", None)
                assert [f.text for f in found] == ["the payload\n"], f"{flag}{joiner}"

    def test_a_quoted_path_is_read(self, tmp_path: Path) -> None:
        body = tmp_path / "with space.txt"
        body.write_text("quoted\n")

        assert read_message_files(f'git commit -F "{body}"', None)[0].text == "quoted\n"
        assert read_message_files(f"git commit -F '{body}'", None)[0].text == "quoted\n"

    def test_every_named_file_is_returned_not_just_the_first(self, tmp_path: Path) -> None:
        first = tmp_path / "a.txt"
        first.write_text("one\n")
        second = tmp_path / "b.txt"
        second.write_text("two\n")

        found = read_message_files(f"gh issue create -F {first} --body-file {second}", None)
        assert [f.text for f in found] == ["one\n", "two\n"]

    def test_a_command_naming_no_file_yields_nothing(self) -> None:
        assert read_message_files("git commit -m 'inline'", None) == []


class TestWhatIsSkipped:
    def test_stdin_is_skipped_because_it_names_no_file(self, tmp_path: Path) -> None:
        """`-F -` is a heredoc or a pipe; there is no path to open."""
        assert read_message_files("git commit -F -", str(tmp_path)) == []

    def test_a_missing_file_is_skipped_rather_than_raising(self, tmp_path: Path) -> None:
        """git fails on it itself; that failure is not this reader's to report."""
        assert read_message_files(f"git commit -F {tmp_path / 'gone.txt'}", None) == []

    def test_an_oversized_file_is_skipped(self, tmp_path: Path) -> None:
        big = tmp_path / "big.txt"
        big.write_text("x" * (MAX_MESSAGE_FILE_BYTES + 1))

        assert read_message_files(f"git commit -F {big}", None) == []

    def test_a_file_at_the_bound_is_still_read(self, tmp_path: Path) -> None:
        """The bound is a limit, not an off-by-one trap."""
        edge = tmp_path / "edge.txt"
        edge.write_text("x" * MAX_MESSAGE_FILE_BYTES)

        assert len(read_message_files(f"git commit -F {edge}", None)) == 1

    def test_a_directory_is_not_a_message_file(self, tmp_path: Path) -> None:
        assert read_message_files(f"git commit -F {tmp_path}", None) == []


class TestHowThePathIsResolved:
    def test_a_relative_path_resolves_against_the_given_cwd(self, tmp_path: Path) -> None:
        (tmp_path / "msg.txt").write_text("relative\n")

        found = read_message_files("git commit -F msg.txt", str(tmp_path))
        assert [f.text for f in found] == ["relative\n"]

    def test_a_relative_path_with_no_cwd_is_left_alone(self, tmp_path: Path) -> None:
        """No cwd means no way to resolve it, and inventing one would be a guess."""
        (tmp_path / "msg.txt").write_text("relative\n")

        assert read_message_files("git commit -F msg.txt", None) == []

    def test_the_absolute_path_is_reported_so_a_caller_can_name_it(self, tmp_path: Path) -> None:
        """`sensitive_content` names the file in its deny, never the line."""
        (tmp_path / "msg.txt").write_text("relative\n")

        found = read_message_files("git commit -F msg.txt", str(tmp_path))
        assert found == [MessageFile(path=tmp_path / "msg.txt", text="relative\n")]


class TestAReadThatFailsAfterTheCheck:
    """Statting a file is not reading it, and the gap raises.

    `sensitive_content` had learned this and caught the failure; the sibling
    copy pre-checked with `os.access` and did not. Both checks stat, and a
    file whose mode denies read — or one unlinked between the check and the
    read — stats perfectly well. Letting that escape takes the calling guard
    down with it.
    """

    @pytest.mark.parametrize("failure", [PermissionError, FileNotFoundError])
    def test_the_read_failure_is_skipped_and_logged_not_raised(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        failure: type[OSError],
    ) -> None:
        body = tmp_path / "msg.txt"
        body.write_text("the payload\n")

        with caplog.at_level(logging.DEBUG, logger=message_files.__name__):
            with patch.object(Path, "read_bytes", side_effect=failure(13, "denied")):
                assert read_message_files(f"git commit -F {body}", None) == []

        assert str(body) in caplog.text

    def test_one_unreadable_file_does_not_hide_a_readable_one(self, tmp_path: Path) -> None:
        """The caller still needs every file it CAN judge."""
        readable = tmp_path / "ok.txt"
        readable.write_text("judged\n")
        vanished = tmp_path / "gone.txt"
        vanished.write_text("never read\n")
        vanished.unlink()

        found = read_message_files(f"git commit -F {vanished} --body-file {readable}", None)
        assert [f.text for f in found] == ["judged\n"]


class TestUndecodableBytes:
    def test_invalid_utf8_is_replaced_rather_than_raising(self, tmp_path: Path) -> None:
        """A guard that crashes on a binary file is a guard that is removed."""
        body = tmp_path / "msg.txt"
        body.write_bytes(b"before \xff\xfe after")

        text = read_message_files(f"git commit -F {body}", None)[0].text
        assert text.startswith("before ")
        assert text.endswith(" after")
