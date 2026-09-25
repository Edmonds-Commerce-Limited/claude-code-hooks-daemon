"""Tests for the shared bounded shell-expansion primitive (Plan 00466 review 3).

Review 3 found that review 2's B1 fix, and both of its own new M2 sub-fixes,
each independently REINTRODUCED B1's own defect class: a slow SAFETY-guard
scan is a fail-open, because a client socket timeout on the 30 s PreToolUse
budget is an ALLOW for the whole chain. Three per-shape fixes (a bounded
regex here, a DP cap there, a results-cap somewhere else) each missed some
OTHER unbounded path the same shape could still take. This module is the one
place expansion is bounded, so there is only one thing to audit, and every
caller that uses it inherits the same guarantee: past the cap, it gives up
and says so (``TooManyToEnumerateError``), rather than silently degrading to
a smaller-but-still-eager computation.
"""

from __future__ import annotations

import errno
import os
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.shell_expansion import (
    TooManyToEnumerateError,
    bounded_recursive_glob,
    expand_braces,
    iter_brace_words,
    iter_normalised_shell_words,
)


class TestExpandBraces:
    """The lazy, capped, depth-bounded brace expander."""

    def test_word_with_no_brace_group_returns_itself(self) -> None:
        assert expand_braces("plain-word") == ["plain-word"]

    def test_single_group_expands_to_each_alternative(self) -> None:
        assert expand_braces("a{b,c}d") == ["abd", "acd"]

    def test_nested_group_expands_fully(self) -> None:
        # Every real spelling is present, including a harmless duplicate
        # ("ab" reachable via both outer alternatives) -- the pre-existing
        # single-innermost-match recursion (inherited unchanged from
        # secret_file_matching.py's prior `_expand_braces`) does not track
        # which outer alternative a nested group belongs to, so an
        # untouched sibling alternative is re-derived once per inner
        # alternative. Over-inclusion here is a safe direction (more
        # candidate tokens get checked, never fewer) and is out of this
        # fix's scope to correct.
        assert sorted(expand_braces("a{b,c{d,e}}")) == sorted(["ab", "ab", "acd", "ace"])

    def test_sequential_groups_expand_to_the_full_cartesian_product(self) -> None:
        assert sorted(expand_braces("{a,b}{c,d}")) == sorted(["ac", "ad", "bc", "bd"])

    def test_empty_alternative_is_preserved(self) -> None:
        assert sorted(expand_braces("s{ecret,}")) == sorted(["secret", "s"])

    def test_within_cap_stays_under_the_default(self) -> None:
        # 2**8 = 256 spellings, comfortably inside the default cap.
        word = "{a,b}" * 8
        assert len(expand_braces(word)) == 256

    def test_exceeding_the_spelling_cap_raises(self) -> None:
        # 2**22 spellings would be built by naive eager recursion; the lazy
        # generator must never materialise anywhere near that many before
        # giving up.
        word = "{a,b}" * 22
        with pytest.raises(TooManyToEnumerateError):
            expand_braces(word, max_spellings=256)

    def test_exceeding_the_spelling_cap_is_fast(self) -> None:
        """B1-R3 (Plan 00466 review 3): the reviewer's exact blocker shape --
        `{a,b}` x 22 in one ~115-byte word -- must give up in well under 1s,
        not the >45s the eager recursive expander took."""
        word = "{a,b}" * 22
        start = time.monotonic()
        with pytest.raises(TooManyToEnumerateError):
            expand_braces(word, max_spellings=256)
        assert time.monotonic() - start < 1.0

    def test_forty_repetitions_is_also_fast(self) -> None:
        """The reviewer's third brace shape (x40)."""
        word = "{a,b}" * 40
        start = time.monotonic()
        with pytest.raises(TooManyToEnumerateError):
            expand_braces(word, max_spellings=256)
        assert time.monotonic() - start < 1.0

    def test_deeply_nested_group_exceeds_the_depth_cap_and_raises(self) -> None:
        """Own live finding (own RED test, not in the review report): a
        DEEPLY NESTED (not wide) brace group -- `{a,{a,{a,...}}}` -- costs
        recursion DEPTH per character, independent of the spelling-count
        cap, which a purely width-bounded cap would never catch."""
        word = "{a," * 500 + "a" + "}" * 500
        with pytest.raises(TooManyToEnumerateError):
            expand_braces(word, max_spellings=100_000, max_depth=64)

    def test_deeply_nested_group_raise_is_fast(self) -> None:
        word = "{a," * 2000 + "a" + "}" * 2000
        start = time.monotonic()
        with pytest.raises(TooManyToEnumerateError):
            expand_braces(word, max_spellings=100_000, max_depth=64)
        assert time.monotonic() - start < 1.0


class TestIterBraceWords:
    """The bounded brace-word finder shared by every caller -- replaces the
    catastrophically-backtracking ``\\S*\\{[^{}]*\\}\\S*`` regex shape."""

    def test_finds_a_single_brace_word(self) -> None:
        assert list(iter_brace_words("cat {a,b}.txt")) == ["{a,b}.txt"]

    def test_finds_multiple_words(self) -> None:
        assert list(iter_brace_words("cp {a,b} {c,d}")) == ["{a,b}", "{c,d}"]

    def test_no_brace_group_yields_nothing(self) -> None:
        assert list(iter_brace_words("plain command line")) == []

    def test_word_boundary_is_whitespace_not_shell_syntax(self) -> None:
        assert list(iter_brace_words("echo x{a,b}y;next")) == ["x{a,b}y;next"]

    def test_caps_the_number_of_groups_examined(self) -> None:
        """Review 7 MAJOR-1: past the cap this RAISES (fail closed), not a
        silent truncation to the first N words -- superseded by
        ``TestIterNormalisedShellWordsCapsFailClosed``."""
        command = " ".join(f"{{a{i},b{i}}}" for i in range(50))
        with pytest.raises(TooManyToEnumerateError):
            list(iter_brace_words(command, max_words=10))

    def test_adversarial_no_brace_input_is_fast(self) -> None:
        """B1-R3 / M-3 (Plan 00466 review): the 94 KB / 200 KB reproducer --
        a huge run of non-whitespace text carrying no brace at all -- must
        not trigger catastrophic backtracking (the abandoned
        `\\S*\\{[^{}]*\\}\\S*` shape took 15s at 94 KB, >45s at 200 KB)."""
        text = "a" * 200_000
        start = time.monotonic()
        assert list(iter_brace_words(text)) == []
        assert time.monotonic() - start < 1.0


class TestBoundedRecursiveGlob:
    """M-1 (Plan 00466 review 3): the FS walk must be bounded by ENTRIES
    VISITED, not matches yielded -- a `Path.glob("**/…")` whose final
    component matches nothing yields nothing, so a matches-only cap never
    trips and the walk runs to completion however large the tree."""

    def test_refuses_a_recursive_pattern_rooted_at_the_filesystem_root(self) -> None:
        with pytest.raises(TooManyToEnumerateError):
            list(
                bounded_recursive_glob(
                    Path("/"), "**/nonexistent-zq9x-marker", max_entries_visited=100
                )
            )

    def test_refusal_at_the_root_is_immediate(self) -> None:
        start = time.monotonic()
        with pytest.raises(TooManyToEnumerateError):
            list(bounded_recursive_glob(Path("/"), "**/*.se?ret-zq9x", max_entries_visited=100))
        assert time.monotonic() - start < 1.0

    def test_refuses_a_multi_wildcard_pattern_with_no_recursive_marker(self) -> None:
        """n466-n24 review 4, m-1: two or more wildcarded segments trip the
        root refusal even with no literal `**` anywhere in the pattern --
        the own live finding from review 3's docstring, still without its
        own RED pin until now."""
        with pytest.raises(TooManyToEnumerateError):
            list(
                bounded_recursive_glob(
                    Path("/"), "*/*/*/*/*/*/*.se?ret-zq9x", max_entries_visited=100
                )
            )

    def test_root_refusal_with_recursive_marker_is_not_masked_by_a_huge_cap(self) -> None:
        """The refusal must fire from the root check itself, not merely
        because `max_entries_visited` happens to be small -- raise the cap
        far past anything a real walk would hit and confirm it still
        refuses immediately rather than attempting the walk."""
        start = time.monotonic()
        with pytest.raises(TooManyToEnumerateError):
            list(
                bounded_recursive_glob(
                    Path("/"), "**/*.se?ret-zq9x", max_entries_visited=10_000_000
                )
            )
        assert time.monotonic() - start < 1.0

    def test_finds_a_real_match_under_a_small_tree(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "dir"
        target.mkdir(parents=True)
        (target / "findme.zzz-marker-9f2c").touch()
        matches = list(
            bounded_recursive_glob(tmp_path, "**/*.zzz-marker-9f2c", max_entries_visited=100)
        )
        assert any(match.name == "findme.zzz-marker-9f2c" for match in matches)

    def test_a_tree_with_no_match_still_trips_the_visited_cap(self, tmp_path: Path) -> None:
        """The defect this function exists to fix: a wide tree with NOTHING
        matching the final component must still raise past the cap, not
        silently walk to completion and return an empty result."""
        for index in range(50):
            (tmp_path / f"file-{index}.txt").touch()
        with pytest.raises(TooManyToEnumerateError):
            list(
                bounded_recursive_glob(tmp_path, "**/*.se?ret-nomatch-zq9x", max_entries_visited=10)
            )

    def test_prunes_a_named_huge_or_ignored_directory(self, tmp_path: Path) -> None:
        ignored = tmp_path / "node_modules"
        ignored.mkdir()
        for index in range(50):
            (ignored / f"pkg-{index}").mkdir()
        (tmp_path / "real.zzz-marker-9f2c").touch()
        matches = list(
            bounded_recursive_glob(tmp_path, "**/*.zzz-marker-9f2c", max_entries_visited=20)
        )
        assert any(match.name == "real.zzz-marker-9f2c" for match in matches)

    def test_deadline_exceeded_raises_timeout_error(self, tmp_path: Path) -> None:
        for index in range(20):
            (tmp_path / f"file-{index}.txt").touch()
        past_deadline = time.monotonic() - 1.0
        with pytest.raises(TimeoutError):
            list(
                bounded_recursive_glob(
                    tmp_path,
                    "**/*.se?ret-nomatch",
                    max_entries_visited=10_000,
                    deadline=past_deadline,
                )
            )

    def test_a_subdirectory_that_vanishes_mid_walk_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ENOENT on a directory ENTERED during the walk (a race with a
        deletion, or a prefix that plain does not exist) proves there is
        nothing under it -- the walk continues and still finds a real match
        elsewhere (n466-n24 review 4)."""
        (tmp_path / "gone").mkdir()
        (tmp_path / "real.zzz-marker-9f2c").touch()
        real_scandir = os.scandir

        def _fake_scandir(path: str | os.PathLike[str]) -> os.ScandirIterator[str]:
            if Path(path) == tmp_path / "gone":
                raise FileNotFoundError(errno.ENOENT, "No such file or directory")
            return real_scandir(path)

        monkeypatch.setattr(
            "claude_code_hooks_daemon.utils.shell_expansion.os.scandir", _fake_scandir
        )
        matches = list(
            bounded_recursive_glob(tmp_path, "**/*.zzz-marker-9f2c", max_entries_visited=100)
        )
        assert any(match.name == "real.zzz-marker-9f2c" for match in matches)

    def test_a_permission_denied_subdirectory_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A directory that could not be READ (not merely absent) is NOT
        proof of a non-match -- it must propagate, not be treated as
        "contributes nothing" (n466-n24 review 4)."""
        (tmp_path / "locked").mkdir()
        (tmp_path / "real.zzz-marker-9f2c").touch()
        real_scandir = os.scandir

        def _fake_scandir(path: str | os.PathLike[str]) -> os.ScandirIterator[str]:
            if Path(path) == tmp_path / "locked":
                raise PermissionError(errno.EACCES, "Permission denied")
            return real_scandir(path)

        monkeypatch.setattr(
            "claude_code_hooks_daemon.utils.shell_expansion.os.scandir", _fake_scandir
        )
        with pytest.raises(PermissionError):
            list(bounded_recursive_glob(tmp_path, "**/*.zzz-marker-9f2c", max_entries_visited=100))


class TestIterNormalisedShellWordsNestedCommands:
    """n466-n24 review 5 minor-1: a `bash -c '…'`/`sh -c '…'`/`eval '…'`
    ARGUMENT is itself a nested shell command, whose own quotes only
    resolve on a SECOND decode pass -- these tests use a benign word split
    across a mid-word quote splice (``wor'ld`` decodes, on its own, to
    ``world``) so the mechanism is pinned without naming any protected
    pattern; the end-to-end deny is pinned separately, through
    ``find_protected_mention_detail``, in test_secret_file_matching.py."""

    def test_a_dash_c_argument_is_reparsed_as_a_nested_command(self) -> None:
        command = "bash -c 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_an_eval_argument_is_reparsed_as_a_nested_command(self) -> None:
        command = "eval 'echo wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_an_interpreter_with_a_leading_path_is_recognised(self) -> None:
        command = "/bin/bash -c 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_two_levels_of_bash_dash_c_nesting_are_both_reparsed(self) -> None:
        """RED test requested by team-lead: two levels of nesting."""
        inner = "bash -c 'cat wor'\\''ld'"
        # Escape `inner` for embedding inside a single-quoted outer word,
        # the same way a shell requires: close, escaped quote, reopen.
        escaped_inner = inner.replace("'", "'\\''")
        command = f"bash -c '{escaped_inner}'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_mixed_double_and_single_quoting_is_reparsed(self) -> None:
        """RED test requested by team-lead: mixed quoting."""
        command = 'bash -c "cat wor\'ld"'
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_a_long_flag_between_interpreter_and_dash_c_is_recognised(self) -> None:
        """Review 6: closed, not a documented simplification -- a proper
        option walk finds `-c` past a preceding long flag."""
        command = "bash --norc -c 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_a_short_flag_between_interpreter_and_dash_c_is_recognised(self) -> None:
        command = "bash -x -c 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_dash_c_clustered_with_a_preceding_short_flag_is_recognised(self) -> None:
        """`bash -lc '…'` -- `-c` recognised anywhere in a short cluster."""
        command = "bash -lc 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_an_arg_taking_short_option_before_dash_c_is_recognised(self) -> None:
        """`bash -O extglob -c '…'` -- `-O`'s separate-word value is
        consumed as a plain value, not mistaken for the code argument."""
        command = "bash -O extglob -c 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words
        assert "extglob" in words

    def test_a_flag_after_interpreter_with_no_dash_c_does_not_recurse(self) -> None:
        """Control: `bash -x '…'` (no `-c` anywhere) must not treat the
        positional argument as code."""
        command = "bash -x 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" not in words

    def test_unrelated_dash_c_content_is_unaffected(self) -> None:
        command = "bash -c 'echo hello world'"
        words = list(iter_normalised_shell_words(command))
        assert words == ["bash", "-c", "echo hello world", "echo", "hello", "world"]

    def test_excessive_nesting_fails_closed_rather_than_hanging_or_allowing(
        self,
    ) -> None:
        """Bounded by BOTH depth and total re-parsed bytes (whichever is
        hit first) -- past either, this is a nested command that could NOT
        be examined, which must raise (fail closed), not silently stop
        recursing and report nothing wrong."""
        nested = "echo hello"
        for _ in range(12):
            escaped = nested.replace("'", "'\\''")
            nested = f"bash -c '{escaped}'"
        with pytest.raises(TooManyToEnumerateError):
            list(iter_normalised_shell_words(nested))


class TestIterNormalisedShellWordsEvalAndLiteralShellFeeds:
    """n466-n24 review 6: `eval` reassembles ALL its argument words (not
    just the first), and three more literal-content-to-a-shell shapes are
    recognised -- `source <(echo …)`, a here-string, and `echo … | <shell>`.
    A benign quote-split word pins the mechanism without naming a
    protected pattern; the end-to-end deny lives in
    test_secret_file_matching.py."""

    def test_eval_reassembles_two_separate_argument_words(self) -> None:
        """Team-lead's own example shape: `eval cat id_\\'rs\\'a` -- but
        pinned here with a benign word (the protected-pattern end-to-end
        case lives in test_secret_file_matching.py)."""
        command = "eval cat 'wor'\\''l'\\''d'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_eval_after_builtin_prefix_is_recognised(self) -> None:
        command = "builtin eval cat 'wor'\\''l'\\''d'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_eval_after_command_prefix_is_recognised(self) -> None:
        command = "command eval cat 'wor'\\''l'\\''d'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_eval_argument_collection_stops_at_a_command_terminator(self) -> None:
        """`eval echo hi; echo done` -- the SECOND statement must not be
        swallowed into eval's own argument list."""
        command = "eval echo hi; echo done"
        words = list(iter_normalised_shell_words(command))
        assert "done" in words

    def test_source_process_substitution_of_a_literal_echo_is_reparsed(self) -> None:
        command = "source <(echo cat 'wor'\\''l'\\''d')"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_dot_process_substitution_of_a_literal_printf_is_reparsed(self) -> None:
        command = ". <(printf 'cat wor'\\''ld')"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_source_process_substitution_of_a_non_literal_producer_is_scanned(
        self,
    ) -> None:
        """review 6 MAJOR-2: `source <(cat somefile)` -- the substituted
        command is not echo/printf, but its OWN command text is judged like
        any other nested command (no longer failed closed wholesale)."""
        words = list(iter_normalised_shell_words("source <(cat somefile)"))
        assert "somefile" in words

    def test_an_ordinary_source_invocation_is_unaffected(self) -> None:
        """Control: `source file.sh arg1` (no process substitution at all)
        must not raise or trigger any special handling."""
        words = list(iter_normalised_shell_words("source myfile.sh arg1"))
        assert words == ["source", "myfile.sh", "arg1"]

    def test_a_here_string_to_a_shell_is_reparsed(self) -> None:
        command = "bash <<<'wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_a_here_string_to_sh_dash_s_is_reparsed(self) -> None:
        command = "sh -s <<<'wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_a_here_string_is_not_specially_recursed_when_dash_c_is_present(
        self,
    ) -> None:
        """`bash -c 'true' <<<'ignored'` -- `-c` takes precedence over
        stdin, so the here-string content is ordinary data, not a second
        script; only `-c`'s own argument gets the nested-command treatment."""
        command = "bash -c 'true' <<<'ignored'"
        words = list(iter_normalised_shell_words(command))
        assert "ignored" in words

    def test_a_literal_echo_piped_to_a_shell_is_reparsed(self) -> None:
        command = "echo cat 'wor'\\''l'\\''d' | bash"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_a_literal_echo_piped_to_a_non_shell_is_unaffected(self) -> None:
        """Control: piped to `grep`, not a shell -- no special recursion,
        though the words are still scanned individually as ordinary text."""
        command = "echo cat 'wor'\\''l'\\''d' | grep x"
        words = list(iter_normalised_shell_words(command))
        assert "world" not in words


class TestIterNormalisedShellWordsPlusOptions:
    """review 6 MAJOR-1: bash's `+`-form options (`+x`, `+O value`) must not
    stop the option walk before a following `-c` is found."""

    def test_a_plus_flag_before_dash_c_is_recognised(self) -> None:
        command = "bash +x -c 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_a_value_taking_plus_flag_before_dash_c_is_recognised(self) -> None:
        command = "bash +O extglob -c 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words
        assert "extglob" in words


class TestIterNormalisedShellWordsHereStringOperands:
    """review 6 MAJOR-1: the here-string trigger must recognise the operand
    forms bash accepts for "read the script from stdin" -- `-`,
    `/dev/stdin` -- not just bare adjacency or `-s`."""

    def test_dash_operand_before_here_string_is_recognised(self) -> None:
        command = "bash - <<<'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_dev_stdin_operand_before_here_string_is_recognised(self) -> None:
        command = "bash /dev/stdin <<<'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_source_dev_stdin_here_string_is_recognised(self) -> None:
        command = "source /dev/stdin <<<'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_dot_dev_stdin_here_string_is_recognised(self) -> None:
        command = ". /dev/stdin <<<'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words


class TestIterNormalisedShellWordsPipeToShellExtended:
    """review 6 MAJOR-1: pipe-to-shell resolution must survive the shell
    carrying its own flags, a wrapper (`sudo`/`env`) in front of it, and a
    `tee` passthrough stage -- not just bare `producer | shell`."""

    def test_pipe_to_shell_with_a_flag_is_recognised(self) -> None:
        command = "echo cat 'wor'\\''l'\\''d' | bash -s"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_pipe_to_sudo_wrapped_shell_is_recognised(self) -> None:
        command = "echo cat 'wor'\\''l'\\''d' | sudo bash"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_pipe_to_env_wrapped_shell_is_recognised(self) -> None:
        command = "echo cat 'wor'\\''l'\\''d' | env bash"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_pipe_through_tee_to_a_shell_is_recognised(self) -> None:
        command = "echo cat 'wor'\\''l'\\''d' | tee /dev/null | bash"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_pipe_through_tee_with_no_further_shell_drops_content(self) -> None:
        """Control: `tee` not itself followed by a shell -- no recursion."""
        command = "echo cat 'wor'\\''l'\\''d' | tee /tmp/out"
        words = list(iter_normalised_shell_words(command))
        assert "world" not in words

    def test_bash_reading_a_process_substitution_as_its_script_is_recognised(
        self,
    ) -> None:
        """`bash <(echo …)` -- the substitution's own content is the
        script, matching the pipe-to-shell direction."""
        command = "bash <(echo cat 'wor'\\''l'\\''d')"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words


class TestIterNormalisedShellWordsProcessSubstitutionGeneralised:
    """review 6 MAJOR-2: a process substitution's substituted command is
    judged by its OWN command text like any other nested command -- a
    non-literal (non echo/printf) producer is no longer failed closed."""

    def test_non_literal_producer_argument_is_still_scanned(self) -> None:
        """`source <(cat somefile)` -- `cat`'s own argument is scanned like
        any other command's, so a protected-shaped argument is still found."""
        words = list(iter_normalised_shell_words("source <(cat wor'ld)"))
        assert "world" in words

    def test_non_literal_producer_with_no_mention_does_not_raise(self) -> None:
        """The false positive review 6 MAJOR-2 exists to fix: a completion
        setup line must not be denied wholesale."""
        words = list(iter_normalised_shell_words("source <(kubectl completion bash)"))
        assert "kubectl" in words
        assert "completion" in words

    def test_common_completion_lines_do_not_raise(self) -> None:
        for command in (
            "source <(kubectl completion bash)",
            "source <(gh completion -s bash)",
            "source <(helm completion bash)",
            "eval \"$(pip completion --bash)\"",
        ):
            list(iter_normalised_shell_words(command))  # must not raise


class TestIterNormalisedShellWordsMoreShellsAndWrappers:
    """review 6 minor-1: mksh/csh/tcsh/fish, versioned binary names, and the
    wrappers `script -c`, `su -c`, `flock -c`, `watch`."""

    def test_mksh_is_recognised(self) -> None:
        words = list(iter_normalised_shell_words("mksh -c 'cat wor'\\''ld'"))
        assert "world" in words

    def test_csh_is_recognised(self) -> None:
        words = list(iter_normalised_shell_words("csh -c 'cat wor'\\''ld'"))
        assert "world" in words

    def test_tcsh_is_recognised(self) -> None:
        words = list(iter_normalised_shell_words("tcsh -c 'cat wor'\\''ld'"))
        assert "world" in words

    def test_fish_is_recognised(self) -> None:
        words = list(iter_normalised_shell_words("fish -c 'cat wor'\\''ld'"))
        assert "world" in words

    def test_versioned_bash_is_recognised(self) -> None:
        words = list(iter_normalised_shell_words("bash5 -c 'cat wor'\\''ld'"))
        assert "world" in words

    def test_versioned_bash_with_dotted_version_is_recognised(self) -> None:
        words = list(iter_normalised_shell_words("bash5.1 -c 'cat wor'\\''ld'"))
        assert "world" in words

    def test_script_dash_c_is_recognised(self) -> None:
        command = "script -qc 'cat wor'\\''ld' /dev/null"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_su_dash_c_is_recognised(self) -> None:
        command = "su -c 'cat wor'\\''ld' root"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_flock_dash_c_after_a_positional_lockfile_is_recognised(self) -> None:
        command = "flock /tmp/l -c 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_flock_tolerant_scan_does_not_leak_into_the_next_command(self) -> None:
        """The tolerant option walk (flock keeps looking for `-c` past
        positional words) must still stop at a command terminator -- `ls
        -c` in a SECOND statement must not be mistaken for flock's own
        `-c` (which would wrongly recurse into its quoted argument)."""
        command = "flock /tmp/l true; ls -c 'wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" not in words

    def test_watch_implicit_code_is_recognised(self) -> None:
        command = "watch -n1 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_watch_with_long_interval_flag_is_recognised(self) -> None:
        command = "watch --interval 5 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words


class TestIterNormalisedShellWordsProducerEscapes:
    """review 6 MAJOR-1: printf and `echo -e` are NOT literal producers --
    their backslash escapes must be evaluated, not passed through raw."""

    def test_echo_dash_e_decodes_backslash_escapes(self) -> None:
        command = "echo -e 'c\\x61t wor\\x6cd' | bash"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_printf_decodes_backslash_escapes_in_its_format(self) -> None:
        command = "source <(printf 'cat wor\\x6cd')"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_echo_without_dash_e_does_not_decode_escapes(self) -> None:
        """Control: plain `echo` (no `-e`) must NOT interpret `\\n` -- the
        literal backslash-n stays in the text, unlike an actual newline."""
        command = "echo 'a\\nb' | bash"
        words = list(iter_normalised_shell_words(command))
        assert "a\\nb" in words or any("a\\nb" in word for word in words)


class TestIterNormalisedShellWordsCapsFailClosed:
    """Plan 00466 guard-defects review 7 MAJOR-1: past EITHER volume cap,
    the generator must RAISE rather than silently stop -- a caller that
    saw quiet exhaustion and treated it as "no more words" would allow a
    mention placed only past the cap."""

    def test_the_normalised_word_cap_raises_rather_than_stopping(self) -> None:
        command = " ".join(["w"] * 2001)
        with pytest.raises(TooManyToEnumerateError):
            list(iter_normalised_shell_words(command, max_words=2000))

    def test_under_the_normalised_word_cap_does_not_raise(self) -> None:
        command = " ".join(["w"] * 1999)
        words = list(iter_normalised_shell_words(command, max_words=2000))
        assert len(words) == 1999

    def test_the_brace_word_cap_raises_rather_than_stopping(self) -> None:
        text = " ".join(["{a,b}"] * 501)
        with pytest.raises(TooManyToEnumerateError):
            list(iter_brace_words(text, max_words=500))

    def test_under_the_brace_word_cap_does_not_raise(self) -> None:
        text = " ".join(["{a,b}"] * 499)
        words = list(iter_brace_words(text, max_words=500))
        assert len(words) == 499


class TestIterNormalisedShellWordsQuotedHeredocBodyIsSkipped:
    """Team-lead's review 7 follow-up: a quoted-delimiter heredoc body is
    inert DATA handed to a consumer (`cat`, `tee`, `git commit -F-`) --
    real bash expands NOTHING in it, so it cannot itself be a nested
    command, and it can legitimately be large (long prose). Excluded
    entirely from word decoding/counting so an everyday long heredoc does
    not exhaust the volume cap; the raw text is still available to OTHER
    token streams (``_tokenise`` in secret_file_matching) for a literal
    mention."""

    def test_a_long_quoted_heredoc_body_does_not_exhaust_the_word_cap(self) -> None:
        body = " ".join(["word"] * 3000)
        command = f"cat > /tmp/out.txt <<'EOF'\n{body}\nEOF\n"
        words = list(iter_normalised_shell_words(command, max_words=2000))
        assert "word" not in words

    def test_a_long_double_quoted_heredoc_body_does_not_exhaust_the_word_cap(self) -> None:
        body = " ".join(["word"] * 3000)
        command = f'cat > /tmp/out.txt <<"EOF"\n{body}\nEOF\n'
        words = list(iter_normalised_shell_words(command, max_words=2000))
        assert "word" not in words

    def test_a_long_backslash_delimiter_heredoc_body_does_not_exhaust_the_word_cap(
        self,
    ) -> None:
        body = " ".join(["word"] * 3000)
        command = f"cat > /tmp/out.txt <<\\EOF\n{body}\nEOF\n"
        words = list(iter_normalised_shell_words(command, max_words=2000))
        assert "word" not in words

    def test_the_dash_form_strips_tabs_from_the_closing_delimiter(self) -> None:
        body = " ".join(["word"] * 3000)
        command = f"cat > /tmp/out.txt <<-'EOF'\n{body}\n\tEOF\n"
        words = list(iter_normalised_shell_words(command, max_words=2000))
        assert "word" not in words

    def test_a_command_substitution_inside_a_quoted_heredoc_body_is_not_recursed(
        self,
    ) -> None:
        """Real bash expands NOTHING inside a quoted-delimiter heredoc --
        a literal `$(...)` in the body stays literal text, never executed."""
        command = "cat > /tmp/out.txt <<'EOF'\n$(cat wor'ld)\nEOF\n"
        words = list(iter_normalised_shell_words(command))
        assert "world" not in words

    def test_a_command_substitution_outside_the_heredoc_still_recurses(self) -> None:
        """Control: the exclusion is scoped to the heredoc BODY only."""
        command = "x=$(bash -c 'cat wor'\\''ld'); cat > /tmp/out.txt <<'EOF'\nplain\nEOF\n"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_an_unquoted_heredoc_delimiter_is_not_exempt(self) -> None:
        """Control: an UNQUOTED delimiter (`<<EOF`) undergoes expansion in
        real bash, so its body stays fully scanned -- a long one still
        exhausts the cap and raises, the pre-existing (correct) MAJOR-1
        behaviour."""
        body = " ".join(["word"] * 3000)
        command = f"cat > /tmp/out.txt <<EOF\n{body}\nEOF\n"
        with pytest.raises(TooManyToEnumerateError):
            list(iter_normalised_shell_words(command, max_words=2000))


class TestIterNormalisedShellWordsCommandSubstitution:
    """Plan 00466 guard-defects review 7 MAJOR-2: `$(...)` and a backtick
    span are genuine nested COMMANDS -- their body is re-parsed the same
    way `eval`'s argument and a process substitution's body already are,
    not left unexamined behind the `*` their word collapses to."""

    def test_dollar_paren_body_is_reparsed(self) -> None:
        command = "x=$(bash -c 'cat wor'\\''ld')"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_dollar_paren_inside_double_quotes_is_reparsed(self) -> None:
        command = 'echo "$(sh -c \'cat wor\'\\\'\'ld\')"'
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_backtick_body_is_reparsed(self) -> None:
        command = "echo `bash -c 'cat wor'\\''ld'`"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_eval_inside_dollar_paren_is_reparsed(self) -> None:
        command = "x=$(eval 'cat wor'\\''ld')"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_pipe_echo_inside_dollar_paren_is_reparsed(self) -> None:
        command = "x=$(echo cat 'wor'\\''l'\\''d' | bash)"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_a_dollar_var_reference_does_not_raise_or_falsely_match(self) -> None:
        """Control: an ordinary `$VAR` (no parens) is unaffected."""
        words = list(iter_normalised_shell_words("echo $HOME/project"))
        assert any("*" in word for word in words)


class TestIterNormalisedShellWordsWrapperOptionWalk:
    """Plan 00466 guard-defects review 7 MAJOR-3: a pipe-to-shell wrapper's
    OWN options/positionals are walked (not just its bare name), a bare
    interpreter's here-string may sit past an intervening redirect, `-c`
    survives a following `--`/another flag, and more shell/wrapper name
    spellings are recognised."""

    def test_sudo_with_a_user_flag_before_the_shell_is_recognised(self) -> None:
        command = "echo cat 'wor'\\''l'\\''d' | sudo -u root bash"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_env_with_dash_i_before_the_shell_is_recognised(self) -> None:
        command = "echo cat 'wor'\\''l'\\''d' | env -i bash"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_timeout_with_a_duration_before_the_shell_is_recognised(self) -> None:
        command = "echo cat 'wor'\\''l'\\''d' | timeout 5 bash"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_nice_with_an_adjustment_before_the_shell_is_recognised(self) -> None:
        command = "echo cat 'wor'\\''l'\\''d' | nice -n 5 bash"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_cat_passthrough_with_no_trailing_argument_is_recognised(self) -> None:
        command = "echo cat 'wor'\\''l'\\''d' | cat | bash"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_output_process_substitution_is_recognised(self) -> None:
        command = "echo cat 'wor'\\''l'\\''d' > >(bash)"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_cat_here_string_piped_to_a_shell_is_recognised(self) -> None:
        command = "cat <<< 'cat wor'\\''ld' | bash"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_here_string_past_an_intervening_redirect_is_recognised(self) -> None:
        command = "bash 2>/dev/null <<<'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_bash_lt_process_substitution_is_recognised(self) -> None:
        command = "bash < <(echo cat 'wor'\\''l'\\''d')"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_dash_c_survives_a_following_double_dash(self) -> None:
        command = "bash -c -- 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_dash_c_survives_a_following_flag(self) -> None:
        command = "bash -c -x 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_su_long_command_flag_is_recognised(self) -> None:
        command = "su --command 'cat wor'\\''ld' root"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_su_glued_long_command_flag_is_recognised(self) -> None:
        command = "su --command='cat wor'\\''ld' root"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_su_positional_user_before_dash_c_is_recognised(self) -> None:
        command = "su root -c 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_su_dash_positional_user_before_dash_c_is_recognised(self) -> None:
        command = "su - root -c 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_script_long_command_flag_is_recognised(self) -> None:
        command = "script --command 'cat wor'\\''ld' /dev/null"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_script_positional_file_before_dash_c_is_recognised(self) -> None:
        command = "script /dev/null -c 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_flock_long_command_flag_is_recognised(self) -> None:
        command = "flock --command 'cat wor'\\''ld' /tmp/l"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_watch_dash_x_before_bash_dash_c_is_recognised(self) -> None:
        command = "watch -x bash -c 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_env_dash_capital_s_split_string_is_recognised(self) -> None:
        """`env -S`'s value is itself a nested command, re-parsed the same
        way `eval`'s argument is -- a quote split across the word (the
        standard `'...'"'"'...'` idiom) only resolves on that second pass."""
        command = "env -S 'cat wor'\"'\"'ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_rbash_is_recognised(self) -> None:
        words = list(iter_normalised_shell_words("rbash -c 'cat wor'\\''ld'"))
        assert "world" in words

    def test_yash_is_recognised(self) -> None:
        words = list(iter_normalised_shell_words("yash -c 'cat wor'\\''ld'"))
        assert "world" in words

    def test_posh_is_recognised(self) -> None:
        words = list(iter_normalised_shell_words("posh -c 'cat wor'\\''ld'"))
        assert "world" in words

    def test_pdksh_is_recognised(self) -> None:
        words = list(iter_normalised_shell_words("pdksh -c 'cat wor'\\''ld'"))
        assert "world" in words

    def test_dev_fd_0_here_string_is_recognised(self) -> None:
        command = "bash /dev/fd/0 <<< 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words

    def test_source_proc_self_fd_0_here_string_is_recognised(self) -> None:
        command = "source /proc/self/fd/0 <<< 'cat wor'\\''ld'"
        words = list(iter_normalised_shell_words(command))
        assert "world" in words


class TestIterNormalisedShellWordsWrapperFalsePositives:
    """Everyday wrapper usage that must NOT recurse into anything false or
    raise -- a wrapper running an ordinary (non-shell) command."""

    def test_sudo_running_an_ordinary_command_does_not_raise(self) -> None:
        list(iter_normalised_shell_words("sudo -u deploy ls -la /srv"))

    def test_env_setting_a_variable_for_an_ordinary_command_does_not_raise(self) -> None:
        list(iter_normalised_shell_words("env FOO=bar node server.js"))

    def test_timeout_running_an_ordinary_command_does_not_raise(self) -> None:
        list(iter_normalised_shell_words("timeout 30 npm test"))

    def test_nice_running_an_ordinary_build_does_not_raise(self) -> None:
        list(iter_normalised_shell_words("nice -n 10 make -j4"))
