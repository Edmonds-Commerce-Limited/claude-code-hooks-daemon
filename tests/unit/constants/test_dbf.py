"""Tests for the Defence Before Fix constants."""

from __future__ import annotations

from claude_code_hooks_daemon.constants.dbf import DefenceBeforeFix


class TestDefenceBeforeFix:
    def test_url_is_the_published_home(self) -> None:
        assert DefenceBeforeFix.URL == "https://defence-before-fix.github.io"

    def test_explain_line_is_one_line_naming_the_method_and_link(self) -> None:
        assert "\n" not in DefenceBeforeFix.EXPLAIN_LINE
        assert "Defence Before Fix" in DefenceBeforeFix.EXPLAIN_LINE
        assert DefenceBeforeFix.URL in DefenceBeforeFix.EXPLAIN_LINE
