"""Tests for the report file-offload helpers (Plan 00329).

A report command's stdout is a Bash tool result, and a tool result that
exits 1 is delivered head-and-tail with the middle DROPPED past roughly
10,000 characters. So the full report goes to a file and stdout carries a
summary bounded well under that ceiling, whatever the corpus grows to.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.report_offload import (
    SUMMARY_MAX_BYTES,
    bound_summary,
    write_offloaded_report,
)


class TestSummaryBound:
    def test_bound_sits_under_the_failure_path_inline_ceiling(self) -> None:
        # Claude Code delivers an exit-1 result whole only up to ~10,000
        # characters; anything larger is head-and-tail with no file path.
        assert SUMMARY_MAX_BYTES < 10_000
        assert SUMMARY_MAX_BYTES >= 4_000


class TestBoundSummary:
    def test_everything_fits_when_small(self) -> None:
        text = bound_summary(
            head=["Header"],
            items=["a", "b", "c"],
            tail=["Footer"],
            max_bytes=100,
            overflow=lambda n: f"... {n} more",
        )
        assert text == "Header\na\nb\nc\nFooter\n"

    def test_overflow_drops_items_from_the_end_and_names_the_count(self) -> None:
        items = [f"item-{i:03d}" for i in range(200)]
        text = bound_summary(
            head=["Header"],
            items=items,
            tail=["Footer"],
            max_bytes=300,
            overflow=lambda n: f"... {n} more items, all listed in the report file",
        )
        assert len(text.encode("utf-8")) <= 300
        assert text.startswith("Header\nitem-000\n")
        assert text.endswith("more items, all listed in the report file\nFooter\n")
        kept = [line for line in text.splitlines() if line.startswith("item-")]
        assert kept == items[: len(kept)]
        omitted = len(items) - len(kept)
        assert f"... {omitted} more items" in text

    def test_bound_holds_for_multibyte_text(self) -> None:
        items = ["• entré → résumé"] * 500
        text = bound_summary(
            head=["→ head"], items=items, tail=[], max_bytes=1000, overflow=lambda n: f"… {n}"
        )
        assert len(text.encode("utf-8")) <= 1000

    def test_head_and_tail_that_cannot_fit_is_an_error_not_a_silent_cut(self) -> None:
        with pytest.raises(ValueError):
            bound_summary(
                head=["x" * 100], items=["a"], tail=["y" * 100], max_bytes=50, overflow=str
            )


class TestWriteOffloadedReport:
    def test_writes_the_full_text_and_returns_the_path(self, tmp_path: Path) -> None:
        path = write_offloaded_report(tmp_path / "reports" / "nested", "REPORT.md", "full\n")
        assert path == tmp_path / "reports" / "nested" / "REPORT.md"
        assert path.read_text(encoding="utf-8") == "full\n"

    def test_overwrites_a_previous_report_of_the_same_name(self, tmp_path: Path) -> None:
        write_offloaded_report(tmp_path, "REPORT.md", "old\n")
        path = write_offloaded_report(tmp_path, "REPORT.md", "new\n")
        assert path.read_text(encoding="utf-8") == "new\n"

    def test_unwritable_directory_raises_os_error(self, tmp_path: Path) -> None:
        blocker = tmp_path / "file-not-dir"
        blocker.write_text("x")
        with pytest.raises(OSError):
            write_offloaded_report(blocker / "child", "REPORT.md", "text\n")
