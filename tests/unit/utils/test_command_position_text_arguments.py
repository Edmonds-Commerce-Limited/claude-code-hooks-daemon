"""Quoted text arguments of `git` and `awk` are data, and loop/gh heredocs are read.

Plan 00483 Task 3.2 batch (b). Companion to the handler-level tests in
tests/unit/handlers/pre_tool_use/test_git_guards_command_shapes.py.
"""

import pytest

from claude_code_hooks_daemon.utils.command_position import (
    blank_printed_substitutions,
    blank_quoted_text_arguments,
    command_position_argument_segments,
)
from claude_code_hooks_daemon.utils.shell_segmentation import strip_quoted_heredoc_bodies


class TestBlankQuotedTextArguments:
    @pytest.mark.parametrize(
        ("segment", "expected"),
        [
            ("git log --grep='git reset --hard'", "git log --grep='_'"),
            ("git log -S'git stash'", "git log -S'_'"),
            ('git log --grep="a b"', 'git log --grep="_"'),
            ("awk '/git stash/ {print}' f", "awk '_' f"),
            ("sudo git log --grep='a b'", "sudo git log --grep='_'"),
        ],
    )
    def test_a_spaced_quoted_span_is_blanked(self, segment: str, expected: str) -> None:
        assert blank_quoted_text_arguments(segment) == expected

    @pytest.mark.parametrize(
        "segment",
        [
            'git "stash"',
            "git -c alias.n='!git reset --hard' n",
            "awk 'BEGIN {system(\"git stash\")}'",
            "awk '{print | \"sh\"}' f",
            'git log --grep="$(git stash)"',
            'git log --grep="a `b` c"',
            "bash -c 'git stash'",
            "eval 'git stash'",
            "ls 'a b'",
            "git submodule foreach 'git stash'",
            "git rebase -x 'git clean -fd'",
            "git -c 'alias.n=!git reset --hard' n",
            "git commit -m 'a b'",
        ],
    )
    def test_anything_runnable_or_unplaced_is_kept(self, segment: str) -> None:
        assert blank_quoted_text_arguments(segment) == segment

    def test_a_lone_quote_is_kept(self) -> None:
        assert blank_quoted_text_arguments("git log --grep=it's") == "git log --grep=it's"

    def test_segments_are_blanked_one_by_one(self) -> None:
        segments = command_position_argument_segments("git log -S'a b' && git stash")
        assert [segment.strip() for segment in segments] == ["git log -S'_'", "git stash"]


class TestAwkDollarIsDataOptIn:
    PROGRAM = "awk '{print \"git worktree remove \" $1}'"

    def test_default_keeps_a_program_holding_a_dollar(self) -> None:
        assert blank_quoted_text_arguments(self.PROGRAM) == self.PROGRAM

    def test_opt_in_blanks_it(self) -> None:
        assert blank_quoted_text_arguments(self.PROGRAM, awk_dollar_is_data=True) == "awk '_'"

    @pytest.mark.parametrize(
        "segment",
        [
            'awk \'{print "git worktree remove " $1 | "sh"}\'',
            "awk '{system(\"git worktree remove \" $1)}'",
            'awk "{print \\"git worktree remove \\" $1}"',
            'awk \'{print "git worktree remove " $1 > "s.sh"}\'',
            "git log --grep='git reset $1'",
            "ls 'a $b'",
        ],
    )
    def test_opt_in_keeps_everything_that_can_run_or_is_not_awk_single_quoted(
        self, segment: str
    ) -> None:
        assert blank_quoted_text_arguments(segment, awk_dollar_is_data=True) == segment

    def test_segments_option_is_passed_on_and_a_piped_run_is_kept(self) -> None:
        piped = f"{self.PROGRAM} | sh"
        assert command_position_argument_segments(piped, awk_dollar_is_data=True)[0].strip() == (
            self.PROGRAM
        )
        assert command_position_argument_segments(self.PROGRAM, awk_dollar_is_data=True) == [
            "awk '_'"
        ]

    def test_a_script_an_earlier_segment_wrote_keeps_the_program(self) -> None:
        command = f"{self.PROGRAM} > s.sh && sh s.sh"
        joined = " ".join(command_position_argument_segments(command, awk_dollar_is_data=True))
        assert "git worktree remove" in joined


class TestHeredocReceivers:
    BODY = "\ngit reset --hard\nEOF"

    @pytest.mark.parametrize(
        "opener",
        [
            "gh pr comment 1 --body-file - <<'EOF'",
            "gh issue create --body-file - <<'EOF'",
            "gh api repos/x/y --input - <<'EOF'",
            "while read l; do echo \"$l\"; done <<'EOF'",
            "for f in a b; do read l; echo $l; done <<'EOF'",
            "while read l; do printf '%s' \"$l\" | wc -c; done <<'EOF'",
        ],
    )
    def test_a_data_reading_receiver_blanks_the_body(self, opener: str) -> None:
        assert "git reset" not in strip_quoted_heredoc_bodies(opener + self.BODY)

    @pytest.mark.parametrize(
        "opener",
        [
            "gh extension exec x <<'EOF'",
            "gh <<'EOF'",
            "gh pr view 1 <<'EOF' | bash",
            "gh pr view 1 <(x) <<'EOF'",
            "while read l; do eval \"$l\"; done <<'EOF'",
            "while read l; do $l; done <<'EOF'",
            "while read l; do bash -c \"$l\"; done <<'EOF'",
            "git status && while read l; do echo $l; done <<'EOF'",
            "while read l; do echo $l; done <(x) <<'EOF'",
            "while read l; do echo $l; done > >(bash) <<'EOF'",
            "while read l; do echo $l; done 3<<'EOF'",
        ],
    )
    def test_an_executing_or_unreadable_receiver_keeps_the_body(self, opener: str) -> None:
        assert "git reset" in strip_quoted_heredoc_bodies(opener + self.BODY)


class TestBlankPrintedSubstitutions:
    """A print-only substitution that stays data is replaced; anything else is kept."""

    def test_an_assignment_printed_later_is_blanked(self) -> None:
        assert (
            blank_printed_substitutions("m=$(printf 'git reset --hard'); echo \"$m\"")
            == 'm=_; echo "$m"'
        )

    @pytest.mark.parametrize(
        "command",
        [
            "m=$(printf 'x'); eval \"$m\"",
            "$(printf 'x')",
            "echo \"$(printf 'x' | sh)\"",
            "echo \"$(printf 'x' $(id))\"",
            'echo "$(printf \'a\\"b\')"',
            "echo $(printf",
            "echo '$(printf x)'",
        ],
    )
    def test_it_is_kept(self, command: str) -> None:
        assert blank_printed_substitutions(command) == command
