"""Tests for the merge-conflict marker detector (Plan 00466 N211).

Every marker line below is BUILT rather than typed at the start of a source
line, so this file never carries a marker the commit gate would report.
"""

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.conflict_markers import (
    GIT_GREP_PREFILTER,
    ConflictMarker,
    MarkerKind,
    classify_marker_line,
    describe_markers,
    find_conflict_markers,
    find_conflict_markers_in_text,
)

OPEN = "<" * 7
BASE = "|" * 7
SEP = "=" * 7
CLOSE = ">" * 7
QUOTED_CLOSE = " ".join(">" * 7)
QUOTED_OPEN = " ".join("<" * 7)
# What mdformat makes of a raw opener: it escapes the first `<` of each pair.
ESCAPED_OPEN = "\\<<\\<<\\<<<"
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
        ],
    )
    def test_other_lines_are_not_markers(self, line: str) -> None:
        assert classify_marker_line(line) is None


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

    def test_git_grep_returns_every_marker_the_classifier_accepts(self, tmp_path: Path) -> None:
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
