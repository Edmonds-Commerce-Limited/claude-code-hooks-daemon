"""Verifying the source citation a report claims to have read (Plan 00403 Task 3.3).

The owner asked that a reporter "can and should read the hooks daemon source"
before deciding there is a defect. Nothing can verify that someone READ
something — but a citation is a checkable artefact, and this turns the
unverifiable claim into one.

What it catches is worth being precise about, because it is not honesty
policing:

``a citation that does not resolve was read somewhere else``
    A `file:line` that does not exist in the INSTALLED version means the
    reporter was looking at a different version, at a fork, or at nothing. All
    three change how a maintainer should read the rest of the report, and none
    of them is visible from the citation alone.

``it is a lower bound, not a proof``
    A resolving citation proves the line exists, not that anybody understood
    it. That is fine: the cost of a wrong citation is a misleading report, and
    catching the wrong ones is worth more than pretending to catch everything.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.issue_report.citation import check_source_citation


@pytest.fixture()
def daemon_root(tmp_path: Path) -> Path:
    source = tmp_path / "src" / "claude_code_hooks_daemon" / "handlers"
    source.mkdir(parents=True)
    (source / "thing.py").write_text("\n".join(f"line {n}" for n in range(1, 21)))
    return tmp_path


class TestAResolvingCitation:
    def test_a_line_inside_the_file_resolves(self, daemon_root: Path) -> None:
        verdict = check_source_citation(
            "src/claude_code_hooks_daemon/handlers/thing.py:10", daemon_root=daemon_root
        )

        assert verdict.resolved

    def test_the_last_line_resolves(self, daemon_root: Path) -> None:
        """An off-by-one here refuses a correct citation, which is the worse error."""
        verdict = check_source_citation(
            "src/claude_code_hooks_daemon/handlers/thing.py:20", daemon_root=daemon_root
        )

        assert verdict.resolved


class TestACitationThatDoesNotResolve:
    def test_a_line_past_the_end_is_refused(self, daemon_root: Path) -> None:
        verdict = check_source_citation(
            "src/claude_code_hooks_daemon/handlers/thing.py:500", daemon_root=daemon_root
        )

        assert not verdict.resolved

    def test_the_refusal_says_how_long_the_file_actually_is(self, daemon_root: Path) -> None:
        """'Does not resolve' is not actionable; 'the file has 20 lines' is."""
        verdict = check_source_citation(
            "src/claude_code_hooks_daemon/handlers/thing.py:500", daemon_root=daemon_root
        )

        assert "20" in verdict.detail

    def test_a_missing_file_is_refused(self, daemon_root: Path) -> None:
        verdict = check_source_citation(
            "src/claude_code_hooks_daemon/handlers/absent.py:1", daemon_root=daemon_root
        )

        assert not verdict.resolved

    def test_the_refusal_names_the_version_question(self, daemon_root: Path) -> None:
        """The useful reading of a dead citation is 'you read another version'."""
        verdict = check_source_citation(
            "src/claude_code_hooks_daemon/handlers/absent.py:1", daemon_root=daemon_root
        )

        assert "version" in verdict.detail.lower()


class TestTheCitationMustBeDaemonSource:
    def test_a_client_path_is_refused(self, daemon_root: Path) -> None:
        """Reading your own code is not reading the daemon's."""
        verdict = check_source_citation("app/Services/Payroll.php:12", daemon_root=daemon_root)

        assert not verdict.resolved

    def test_an_absolute_path_is_refused(self, daemon_root: Path) -> None:
        """It would carry the project root into the report as well as escaping the root."""
        verdict = check_source_citation("/etc/passwd:1", daemon_root=daemon_root)

        assert not verdict.resolved

    def test_a_traversal_is_refused(self, daemon_root: Path) -> None:
        verdict = check_source_citation(
            "src/claude_code_hooks_daemon/../../../etc/passwd:1", daemon_root=daemon_root
        )

        assert not verdict.resolved


class TestMalformedCitations:
    @pytest.mark.parametrize(
        "citation",
        [
            "",
            "   ",
            "src/claude_code_hooks_daemon/handlers/thing.py",
            "src/claude_code_hooks_daemon/handlers/thing.py:",
            "src/claude_code_hooks_daemon/handlers/thing.py:abc",
            "src/claude_code_hooks_daemon/handlers/thing.py:0",
            "src/claude_code_hooks_daemon/handlers/thing.py:-3",
        ],
    )
    def test_a_malformed_citation_is_refused_not_raised(
        self, citation: str, daemon_root: Path
    ) -> None:
        """Never raises: the caller is a report generator."""
        assert not check_source_citation(citation, daemon_root=daemon_root).resolved

    def test_the_expected_shape_is_stated(self, daemon_root: Path) -> None:
        verdict = check_source_citation("thing.py", daemon_root=daemon_root)

        assert "file:line" in verdict.detail


class TestADirectoryIsNotASourceLine:
    def test_a_directory_citation_is_refused(self, daemon_root: Path) -> None:
        """`read_text` on a directory raises; the check must report, not crash."""
        verdict = check_source_citation(
            "src/claude_code_hooks_daemon/handlers:1", daemon_root=daemon_root
        )

        assert not verdict.resolved
