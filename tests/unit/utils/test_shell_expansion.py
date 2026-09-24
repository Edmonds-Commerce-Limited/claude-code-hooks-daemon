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

import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.shell_expansion import (
    TooManyToEnumerateError,
    bounded_recursive_glob,
    expand_braces,
    iter_brace_words,
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
        command = " ".join(f"{{a{i},b{i}}}" for i in range(50))
        words = list(iter_brace_words(command, max_words=10))
        assert len(words) == 10

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
