"""Static reading of ``for NAME in WORDS; do ... done`` loops (ledger 00474 N350)."""

import pytest

from claude_code_hooks_daemon.utils import shell_expansion
from claude_code_hooks_daemon.utils.shell_for_loops import (
    LoopBinding,
    active_bindings,
    find_for_loop_bindings,
)

_LOOP = 'for d in repos/* worktrees/*; do git -C "$d" ls-files; done'


def _words(command: str) -> list[str]:
    return list(shell_expansion.iter_normalised_shell_words(command))


class TestFindForLoopBindings:
    def test_a_plain_loop_is_bound_to_its_raw_words_and_body_span(self) -> None:
        (binding,) = find_for_loop_bindings(_LOOP)
        assert binding.name == "d"
        assert binding.raw_values == ("repos/*", "worktrees/*")
        assert _LOOP[binding.body_start : binding.body_end].strip() == 'git -C "$d" ls-files;'

    def test_newline_separated_loop_is_bound(self) -> None:
        (binding,) = find_for_loop_bindings("for d in a b\ndo\n  ls $d\ndone\n")
        assert binding.raw_values == ("a", "b")

    @pytest.mark.parametrize(
        "command",
        [
            "for d in a b; do d=x; ls $d; done",
            "for d in a b; do d+=x; ls $d; done",
            "for d in a b; do ls ${d:=x}; done",
            "for d in a b; do ((d++)); ls $d; done",
            "for d in a b; do read d; ls $d; done",
            "for d in a b; do eval 'd=x'; ls $d; done",
            "for d in a b; do declare d=x; ls $d; done",
            "for d in a b; do printf -v d x; ls $d; done",
            "for d in a b; do unset d; ls $d; done",
            "for d in a b; do ls $d; done <<EOF\nx\nEOF",
            "for d in a $(ls); do ls $d; done",
            "for d in a `ls`; do ls $d; done",
            "for d in a > f; do ls $d; done",
            "for d in a b; do ls $d",
            "for d in a b; do for d in c; do :; done; ls $d; done",
            "for d in ; do ls $d; done",
            "for d; do ls $d; done",
            "for ((i=0;i<3;i++)); do ls; done",
            "for d in $'a\\'b'; do ls $d; done",
        ],
    )
    def test_a_shape_that_cannot_be_read_with_certainty_binds_nothing(self, command: str) -> None:
        assert find_for_loop_bindings(command) == ()

    def test_a_quoted_do_in_the_body_does_not_end_the_search_early(self) -> None:
        command = 'for d in a; do echo "done"; ls $d; done'
        (binding,) = find_for_loop_bindings(command)
        assert "ls $d" in command[binding.body_start : binding.body_end]

    def test_a_comment_is_not_scanned_for_keywords(self) -> None:
        command = "for d in a; do # done\n ls $d\ndone"
        (binding,) = find_for_loop_bindings(command)
        assert "ls $d" in command[binding.body_start : binding.body_end]


class TestActiveBindings:
    def test_only_a_position_inside_the_body_is_bound(self) -> None:
        (binding,) = find_for_loop_bindings(_LOOP)
        assert active_bindings((binding,), 0) == {}
        assert active_bindings((binding,), binding.body_start) == {"d": binding.raw_values}
        assert active_bindings((binding,), binding.body_end) == {}

    def test_binding_is_a_value_object(self) -> None:
        assert LoopBinding("d", ("a",), 1, 2) == LoopBinding("d", ("a",), 1, 2)


class TestWordStreamUsesTheBinding:
    def test_the_loop_variable_is_replaced_by_the_loop_words_not_a_lone_star(self) -> None:
        words = _words(_LOOP)
        assert "*" not in words
        assert words.count("repos/*") == 2
        assert words.count("worktrees/*") == 2

    def test_a_suffix_after_the_variable_is_kept(self) -> None:
        words = _words("for d in a b; do cat $d/x; done")
        assert "a/x" in words
        assert "b/x" in words
        assert "*" not in words

    def test_a_braced_variable_is_replaced(self) -> None:
        assert "a" in _words("for d in a; do cat ${d}; done")

    def test_a_parameter_expansion_operator_stays_a_star(self) -> None:
        assert "*" in _words("for d in a; do cat ${d%/}; done")

    def test_a_use_before_the_loop_stays_a_star(self) -> None:
        assert "*" in _words("cat $d; for d in a; do :; done")

    def test_an_unrelated_variable_stays_a_star(self) -> None:
        assert "*" in _words("for d in a; do cat $other; done")

    def test_a_reassigned_variable_stays_a_star(self) -> None:
        assert "*" in _words("for d in a; do d=x; cat $d; done")

    def test_an_unresolvable_loop_word_still_yields_a_star(self) -> None:
        assert _words("for d in $HOME/x; do cat $d; done").count("*/x") == 2

    def test_a_variable_repeated_past_the_variant_cap_falls_back_to_a_star(self) -> None:
        values = " ".join(f"v{n}" for n in range(9))
        words = _words(f"for d in {values}; do cat $d$d$d; done")
        assert "***" in words
        assert "v0v0v0" not in words
