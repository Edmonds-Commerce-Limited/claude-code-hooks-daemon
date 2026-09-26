"""Tests for the merge-conflict marker detector (Plan 00466 N211).

Every marker line below is BUILT rather than typed at the start of a source
line, so this file never carries a marker the commit gate would report.
"""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.conflict_markers import (
    DEFAULT_MARKER_SIZE,
    GIT_GREP_PREFILTER,
    ConflictMarker,
    MarkerKind,
    classify_marker_line,
    describe_markers,
    find_conflict_markers,
    find_conflict_markers_in_text,
    git_grep_prefilter,
)
from claude_code_hooks_daemon.utils.markdown_format import format_markdown_text

OPEN = "<" * 7
BASE = "|" * 7
SEP = "=" * 7
CLOSE = ">" * 7
QUOTED_CLOSE = " ".join(">" * 7)
QUOTED_OPEN = " ".join("<" * 7)
# What mdformat makes of a raw opener: it escapes the first `<` of each pair.
ESCAPED_OPEN = "\\<<\\<<\\<<<"
# An unlabelled opener ends in `<`, so the formatter escapes that one too.
ESCAPED_OPEN_UNLABELLED = "\\<<\\<<\\<<\\<"
ESCAPED_SEP = "\\" + SEP


class TestClassifyMarkerLine:
    """One line at a time: which marker shape, raw or disguised, or none."""

    @pytest.mark.parametrize(
        ("line", "kind"),
        [
            (f"{OPEN} HEAD", MarkerKind.OPEN),
            (OPEN, MarkerKind.OPEN),
            (f"{BASE} merged common ancestors", MarkerKind.BASE),
            (SEP, MarkerKind.SEPARATOR),
            (f"{CLOSE} main", MarkerKind.CLOSE),
            (CLOSE, MarkerKind.CLOSE),
            (f"{CLOSE} worktree-n466-superlinear\r", MarkerKind.CLOSE),
        ],
    )
    def test_raw_markers_are_recognised(self, line: str, kind: MarkerKind) -> None:
        assert classify_marker_line(line) == (kind, False)

    @pytest.mark.parametrize(
        ("line", "kind"),
        [
            (f"{QUOTED_CLOSE} main", MarkerKind.CLOSE),
            (QUOTED_CLOSE, MarkerKind.CLOSE),
            (f"{QUOTED_OPEN} HEAD", MarkerKind.OPEN),
            (f"{ESCAPED_OPEN} HEAD", MarkerKind.OPEN),
            (f"# {ESCAPED_OPEN} HEAD ours line", MarkerKind.OPEN),
            (f"| {ESCAPED_OPEN} HEAD |     |", MarkerKind.OPEN),
            # Review 1 M2: the other places the formatter folds an opener.
            (f"# Intro text. {ESCAPED_OPEN} HEAD ours", MarkerKind.OPEN),
            (f"> {ESCAPED_OPEN} HEAD", MarkerKind.OPEN),
            (f"1. # step {ESCAPED_OPEN} HEAD ours", MarkerKind.OPEN),
            (ESCAPED_OPEN_UNLABELLED, MarkerKind.OPEN),
            (f"| a | {ESCAPED_OPEN} HEAD |", MarkerKind.OPEN),
            (f"  {ESCAPED_SEP}", MarkerKind.SEPARATOR),
            (f"  {QUOTED_CLOSE} br", MarkerKind.CLOSE),
        ],
    )
    def test_formatter_disguised_markers_are_recognised(self, line: str, kind: MarkerKind) -> None:
        assert classify_marker_line(line) == (kind, True)

    @pytest.mark.parametrize(
        "line",
        [
            "",
            "plain prose",
            "=" * 8,
            "=" * 6,
            "<" * 8,
            f"{OPEN}x",
            f" {OPEN} indented raw marker is not one git writes",
            "> > > quoted three deep",
            f"see `{QUOTED_CLOSE}` inline",
            f"text {OPEN} mid-line",
            "|---|---|",
            f"the escaped opener `{ESCAPED_OPEN}` quoted inline",
            f"a longer run {ESCAPED_OPEN}< is another size",
            f"glued{ESCAPED_OPEN} to a word",
        ],
    )
    def test_other_lines_are_not_markers(self, line: str) -> None:
        assert classify_marker_line(line) is None


# Review 1 M2: every layout the formatter folds an opener into, run through
# the REAL formatter so a change in its output fails here, not in a commit.
_FORMATTER_LAYOUTS = {
    "a heading swallowing the paragraph above": "Intro text.\n{o} HEAD\nours\n{s}\ntheirs\n",
    "a blockquote": "> {o} HEAD\n> ours\n",
    "a list item": "1. step\n   {o} HEAD\n   ours\n   {s}\n",
    "a bullet item": "- item\n  {o} HEAD\n",
    "an unlabelled opener": "{o}\nours\n",
    "an unlabelled opener after a paragraph": "text\n{o}\nours\n",
    "a table cell": "| a | b |\n|---|---|\n| {o} HEAD | x |\n",
}


class TestTheFormattersOwnDisguisesAreRecognised:
    @pytest.mark.parametrize("layout", sorted(_FORMATTER_LAYOUTS))
    @pytest.mark.parametrize("size", [DEFAULT_MARKER_SIZE, 8, 9, 12])
    def test_the_formatted_opener_is_still_an_opener(self, layout: str, size: int) -> None:
        source = _FORMATTER_LAYOUTS[layout].format(o="<" * size, s="=" * size)
        formatted = format_markdown_text(source)
        assert "<" * size not in formatted, "the formatter no longer disguises this layout"
        kinds = [m.kind for m in find_conflict_markers_in_text(formatted, size=size)]
        assert MarkerKind.OPEN in kinds, formatted


class TestADeepBlockquoteIsACloserOnlyWhereOneCanBe:
    """Review 1 minor 1: an email-style deep quote is not a leftover closer."""

    @pytest.mark.parametrize(
        "line",
        [
            f"{QUOTED_CLOSE} some quoted prose",
            f"{QUOTED_CLOSE} > deeper still",
            " ".join(">" * 8),
            f"{QUOTED_CLOSE} abc1234 (a rebased subject)",
        ],
    )
    def test_alone_it_is_prose(self, line: str) -> None:
        assert find_conflict_markers_in_text(f"intro\n\n{line}\n") == []

    @pytest.mark.parametrize(
        "line", [f"{QUOTED_CLOSE} some quoted prose", f"{QUOTED_CLOSE} abc1234 (subject)"]
    )
    def test_after_an_opener_and_a_separator_it_closes_the_conflict(self, line: str) -> None:
        text = f"{ESCAPED_OPEN} HEAD\nours\n{SEP}\ntheirs\n{line}\n"
        kinds = [m.kind for m in find_conflict_markers_in_text(text)]
        assert kinds == [MarkerKind.OPEN, MarkerKind.SEPARATOR, MarkerKind.CLOSE]

    def test_after_an_opener_without_a_separator_it_is_prose(self) -> None:
        text = f"{ESCAPED_OPEN} HEAD\nours\n{QUOTED_CLOSE} some quoted prose\n"
        kinds = [m.kind for m in find_conflict_markers_in_text(text)]
        assert kinds == [MarkerKind.OPEN]

    @pytest.mark.parametrize("label", ["", " main", " worktree-n466-superlinear"])
    def test_a_branch_labelled_closer_counts_alone(self, label: str) -> None:
        """The N211 leftover: exactly the marker size deep, one-word label."""
        markers = find_conflict_markers_in_text(f"entry\n\n{QUOTED_CLOSE}{label}\n")
        assert [m.kind for m in markers] == [MarkerKind.CLOSE]


class TestConflictMarkerSize:
    """Review 1 minor 2: git's `conflict-marker-size` attribute sets the run length."""

    @pytest.mark.parametrize("size", [3, 9, 12])
    def test_markers_of_the_configured_size_are_found(self, size: int) -> None:
        text = f"{'<' * size} HEAD\nours\n{'=' * size}\ntheirs\n{'>' * size} main\n"
        kinds = [m.kind for m in find_conflict_markers_in_text(text, size=size)]
        assert kinds == [MarkerKind.OPEN, MarkerKind.SEPARATOR, MarkerKind.CLOSE]

    def test_a_run_of_another_size_is_not_a_marker(self) -> None:
        text = f"{OPEN} HEAD\nours\n{SEP}\ntheirs\n{CLOSE} main\n"
        assert find_conflict_markers_in_text(text, size=9) == []

    @pytest.mark.parametrize("size", [0, -1])
    def test_a_size_below_one_is_refused(self, size: int) -> None:
        with pytest.raises(ValueError, match="marker size"):
            find_conflict_markers_in_text("x\n", size=size)


class TestClassifyTakesTheSize:
    def test_a_run_is_a_marker_only_at_its_own_size(self) -> None:
        assert classify_marker_line(f"{'>' * 9} main", size=9) == (MarkerKind.CLOSE, False)
        assert classify_marker_line(f"{'>' * 9} main") is None


class TestFindConflictMarkers:
    """Region logic: openers and closers always count, separators only inside."""

    def test_a_whole_raw_conflict_reports_every_marker(self) -> None:
        text = f"a\n{OPEN} HEAD\nours\n{BASE} base\nold\n{SEP}\ntheirs\n{CLOSE} main\nb\n"
        markers = find_conflict_markers_in_text(text)
        assert [(m.line_number, m.kind) for m in markers] == [
            (2, MarkerKind.OPEN),
            (4, MarkerKind.BASE),
            (6, MarkerKind.SEPARATOR),
            (8, MarkerKind.CLOSE),
        ]
        assert not any(m.disguised for m in markers)

    def test_a_setext_heading_underline_is_not_a_marker(self) -> None:
        text = f"Heading\n{SEP}\n\nprose\n"
        assert find_conflict_markers_in_text(text) == []

    def test_a_setext_underline_between_markers_is_a_separator(self) -> None:
        text = f"{OPEN} HEAD\nHeading\n{SEP}\ntheirs\n{CLOSE} main\n"
        kinds = [m.kind for m in find_conflict_markers_in_text(text)]
        assert kinds == [MarkerKind.OPEN, MarkerKind.SEPARATOR, MarkerKind.CLOSE]

    def test_a_separator_outside_a_closed_region_is_not_reported(self) -> None:
        text = f"{OPEN} HEAD\nx\n{CLOSE} main\nHeading\n{SEP}\n"
        kinds = [m.kind for m in find_conflict_markers_in_text(text)]
        assert kinds == [MarkerKind.OPEN, MarkerKind.CLOSE]

    def test_a_separator_after_an_unclosed_opener_is_not_reported(self) -> None:
        text = f"{OPEN} HEAD\nHeading\n{SEP}\n"
        kinds = [m.kind for m in find_conflict_markers_in_text(text)]
        assert kinds == [MarkerKind.OPEN]

    def test_a_lone_leftover_closer_is_reported(self) -> None:
        """The N211 shape: resolution removed everything except the closer."""
        text = f"entry\n\n{QUOTED_CLOSE} main\n\n### N99\n"
        markers = find_conflict_markers_in_text(text)
        assert markers == [
            ConflictMarker(
                line_number=3,
                kind=MarkerKind.CLOSE,
                disguised=True,
                text=f"{QUOTED_CLOSE} main",
            )
        ]

    def test_numbered_lines_keep_their_own_numbers(self) -> None:
        markers = find_conflict_markers([(40, f"{OPEN} a"), (41, SEP), (97, f"{CLOSE} b")])
        assert [m.line_number for m in markers] == [40, 41, 97]


class TestDescribeMarkers:
    def test_names_line_and_text(self) -> None:
        markers = find_conflict_markers_in_text(f"x\n{QUOTED_CLOSE} main\n")
        description = describe_markers(markers)
        assert "line 2" in description
        assert f"{QUOTED_CLOSE} main" in description
        assert "disguised" in description


class TestGitGrepPrefilter:
    """The prefilter git runs must never drop a line the classifier accepts."""

    def test_the_default_constant_is_the_default_size(self) -> None:
        assert git_grep_prefilter(DEFAULT_MARKER_SIZE) == GIT_GREP_PREFILTER

    @pytest.mark.parametrize("size", [3, DEFAULT_MARKER_SIZE, 9, 12])
    def test_git_grep_returns_every_marker_the_classifier_accepts(
        self, tmp_path: Path, size: int
    ) -> None:
        o, b, s, c = "<" * size, "|" * size, "=" * size, ">" * size
        quoted_close, quoted_open = " ".join(c), " ".join(o)
        escaped_open = format_markdown_text(f"{o} HEAD\n").strip()
        escaped_bare = format_markdown_text(f"{o}\n").strip()
        positives = [
            f"{o} HEAD",
            f"{b} base",
            s,
            f"{c} main",
            f"{quoted_close} main",
            f"{quoted_close} some quoted prose",
            f"{quoted_open} HEAD",
            escaped_open,
            escaped_bare,
            f"# {escaped_open} ours",
            f"# Intro text. {escaped_open} ours",
            f"> {escaped_open}",
            f"1. # step {escaped_open} ours",
            f"| {escaped_open} |  |",
            f"  \\{s}",
            f"  {quoted_close} br",
        ]
        for line in positives:
            assert classify_marker_line(line, size=size) is not None, line
        (tmp_path / "doc.md").write_text("\n".join(["prose", *positives, "tail"]) + "\n")
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        result = subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "grep",
                "--no-index",
                "-n",
                "-E",
                "-e",
                git_grep_prefilter(size),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        matched_lines = {int(row.split(":", 2)[1]) for row in result.stdout.splitlines()}
        assert matched_lines == set(range(2, 2 + len(positives)))

    def test_the_default_prefilter_matches_every_default_marker(self, tmp_path: Path) -> None:
        positives = [
            f"{OPEN} HEAD",
            f"{BASE} base",
            SEP,
            f"{CLOSE} main",
            f"{QUOTED_CLOSE} main",
            f"{QUOTED_OPEN} HEAD",
            f"{ESCAPED_OPEN} HEAD",
            f"# {ESCAPED_OPEN} HEAD ours",
            f"| {ESCAPED_OPEN} HEAD |  |",
            f"  {ESCAPED_SEP}",
            f"  {QUOTED_CLOSE} br",
        ]
        for line in positives:
            assert classify_marker_line(line) is not None, line
        (tmp_path / "doc.md").write_text("\n".join(["prose", *positives, "tail"]) + "\n")
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        result = subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "grep",
                "--no-index",
                "-n",
                "-E",
                "-e",
                GIT_GREP_PREFILTER,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        matched_lines = {int(row.split(":", 2)[1]) for row in result.stdout.splitlines()}
        assert matched_lines == set(range(2, 2 + len(positives)))
