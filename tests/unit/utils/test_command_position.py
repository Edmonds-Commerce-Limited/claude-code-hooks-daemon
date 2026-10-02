"""Tests for the command-position view used by the git guards (ledger N241)."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.command_position import (
    command_position_segments,
    command_position_view,
    is_plain_data_command,
)


class TestDataHeadsAreBlanked:
    @pytest.mark.parametrize(
        "command",
        [
            "echo 'git stash'",
            "grep -n 'git stash' file.md",
            "printf '%s' 'git reset --hard'",
            "rg 'git stash' src",
            "sudo grep 'git stash' f",
        ],
    )
    def test_arguments_of_a_data_head_vanish(self, command: str) -> None:
        view = command_position_view(command)
        assert "git" not in view

    def test_a_command_beside_a_data_head_survives(self) -> None:
        assert "git stash" in command_position_view("echo hi; git stash")
        assert "git stash" in command_position_view("echo hi & git stash")
        assert "git stash" in command_position_view("echo hi\ngit stash")

    def test_an_expansion_in_the_arguments_keeps_them(self) -> None:
        assert "git stash" in command_position_view("echo $(git stash)")
        assert "git stash" in command_position_view("echo `git stash`")

    @pytest.mark.parametrize("receiver", ["bash", "sh", "xargs", "eval"])
    def test_data_piped_into_an_executor_is_kept(self, receiver: str) -> None:
        assert "git stash" in command_position_view(f"echo 'git stash' | {receiver}")


class TestNestedShellBodies:
    def test_a_literal_c_body_is_judged_as_a_command(self) -> None:
        assert "git stash" in command_position_view("bash -c 'git stash'")

    def test_a_message_inside_a_c_body_is_blanked(self) -> None:
        view = command_position_view("bash -c 'git commit -m \"document --amend\"'")
        assert "--amend" not in view
        assert "git commit" in view

    def test_a_data_head_inside_a_c_body_is_blanked(self) -> None:
        assert "git" not in command_position_view("bash -c \"echo 'git stash'\"")

    def test_an_expanding_c_body_is_left_alone(self) -> None:
        assert "git stash" in command_position_view('bash -c "$(echo git stash)"')


class TestGhProse:
    def test_title_and_body_values_vanish(self) -> None:
        view = command_position_view("gh pr create --title 'git stash' --body='git reset --hard'")
        assert "git" not in view

    def test_other_gh_subcommands_keep_their_arguments(self) -> None:
        assert "reset" in command_position_view("gh api --body 'git reset --hard'")


class TestSegments:
    def test_segments_split_on_every_separator(self) -> None:
        segments = command_position_segments("a; b && c || d | e & f\ng")
        assert [s.strip() for s in segments] == list("abcdefg")

    def test_a_quoted_separator_does_not_split(self) -> None:
        assert command_position_segments("git commit -m 'a;b'") == ["git commit -m <REDACTED>"]

    def test_a_backslash_does_not_escape_inside_single_quotes(self) -> None:
        segments = command_position_segments("git commit -m 'x\\' ; git reset --hard ; echo 'y'")
        assert any("git reset --hard" in s for s in segments)


class TestIsPlainDataCommand:
    """One bare data head over plain words, optionally written to a plain file (N49)."""

    @pytest.mark.parametrize(
        "command",
        [
            "echo 'git stash'",
            "printf 'a note\\n' >> notes.txt",
            'echo "plain text" > out.txt',
            "grep -rn 'git stash' docs/",
            "rg 'x' src",
            "  echo hi",
        ],
    )
    def test_plain_commands(self, command: str) -> None:
        assert is_plain_data_command(command) is True

    @pytest.mark.parametrize(
        "command",
        [
            "",
            "ls 'x'",
            "env echo hi",
            "/bin/echo hi",
            "echo hi; echo hi",
            "echo hi | cat",
            "echo $(date)",
            'echo "$HOME"',
            'echo "a!"',
            "echo `date`",
            "echo * ",
            "echo ~",
            "echo hi 2>&1",
            "echo hi < f",
            "echo hi > >(cat)",
            "echo hi >",
            "echo 'unbalanced",
            "echo 'a\nb'",
            "printf -v x 'y'",
            "printf -- '%s' x",
            "rg --pre cmd x",
            "echo $((1))",
        ],
    )
    def test_everything_else_is_not_vouched_for(self, command: str) -> None:
        assert is_plain_data_command(command) is False
