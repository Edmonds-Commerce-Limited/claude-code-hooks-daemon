"""Assembling a report from controlled fields (Plan 00403 Task 2.1).

The difference between this and `bin/hooks-daemon bug-report` is the whole
point, and it is a difference in KIND rather than in degree.

`bug-report` collects everything a diagnostician might want — the config file,
the environment, a log window — and then scrubs what it collected. That order
leaks the first field somebody forgets, and Plan 00403 Phase 1 found three such
fields in a tool whose output the docs told people to paste into a public
issue.

This assembles a report from a fixed set of fields it asks for by name. The
hostname is not scrubbed out of it; the hostname is never collected. Scrubbing
still runs, but as a backstop over the free-text fields rather than as the
mechanism.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.issue_report.assemble import (
    ConfigConsideration,
    ReportFields,
    assemble_report,
)
from claude_code_hooks_daemon.issue_report.provenance import verify_document


def _base() -> ReportFields:
    return ReportFields(
        summary="sed_blocker denies a read-only pipeline",
        handler="sed_blocker",
        expected="A pipeline that cannot write is allowed.",
        observed="It is denied with R-SED-FILE-MODIFICATION.",
        reproduction=(
            "1. mkdir -p untracked/scratch/repro\n"
            "2. Run the pipeline against untracked/scratch/repro/a.txt\n"
        ),
        config_considered=(
            ConfigConsideration(
                option="handlers.pre_tool_use.sed_blocker.enabled",
                why_insufficient="Disabling the handler removes the protection entirely.",
            ),
        ),
        source_citation="src/claude_code_hooks_daemon/handlers/pre_tool_use/sed_blocker.py:210",
        daemon_version="3.27.0",
        generated_at="2026-09-14",
        platform="Linux x86_64, Python 3.12.3",
        install_mode="normal",
    )


def _fields(**overrides: Any) -> ReportFields:
    return replace(_base(), **overrides)


class TestTheReportCarriesWhatAMaintainerNeeds:
    def test_the_summary_is_present(self) -> None:
        assert "sed_blocker denies a read-only pipeline" in assemble_report(_fields()).document

    def test_the_daemon_version_is_present(self) -> None:
        assert "3.27.0" in assemble_report(_fields()).document

    def test_the_source_citation_survives(self) -> None:
        """A daemon path IS the substance; scrubbing must not eat it."""
        document = assemble_report(_fields()).document

        assert "handlers/pre_tool_use/sed_blocker.py:210" in document

    def test_the_config_considered_is_reported_with_its_reason(self) -> None:
        document = assemble_report(_fields()).document

        assert "handlers.pre_tool_use.sed_blocker.enabled" in document
        assert "removes the protection entirely" in document

    def test_the_reproduction_is_reported(self) -> None:
        assert "untracked/scratch/repro" in assemble_report(_fields()).document


class TestTheDocumentIsFilable:
    def test_it_carries_a_valid_provenance_header(self) -> None:
        assert verify_document(assemble_report(_fields()).document) == ()

    def test_a_good_report_has_no_problems(self) -> None:
        assert assemble_report(_fields()).problems == ()


class TestWhatIsNeverCollected:
    """The hostname is not scrubbed out of this report; it is never asked for.

    `ReportFields` is the entire input surface, so a field that is not on it
    cannot reach the document by being forgotten somewhere downstream.
    """

    @pytest.mark.parametrize(
        "banned", ["hostname", "git_remote", "env", "config_dump", "logs", "transcript"]
    )
    def test_the_field_does_not_exist(self, banned: str) -> None:
        assert banned not in ReportFields.__dataclass_fields__


class TestFreeTextIsStillScrubbed:
    """Scrubbing is the backstop over free text, not the mechanism.

    `summary`, `expected` and `observed` are written by a human or an agent, so
    an absolute path can land in them the same way it can in a reproduction —
    and unlike the reproduction these are not refused outright, because prose
    is where a report explains itself.
    """

    def test_a_project_root_in_prose_is_replaced(self) -> None:
        report = assemble_report(
            _fields(observed="It fails under /home/jbloggs/acme-payments every time."),
            project_root=Path("/home/jbloggs/acme-payments"),
        )

        assert "acme-payments" not in report.document

    def test_a_home_directory_in_prose_is_replaced(self) -> None:
        report = assemble_report(
            _fields(expected="Should read /home/jbloggs/.cache/thing"),
            project_root=Path("/srv/app"),
            home=Path("/home/jbloggs"),
        )

        assert "jbloggs" not in report.document

    def test_the_digest_matches_the_scrubbed_body_not_the_raw_one(self) -> None:
        """Scrub first, then hash — the other order fails every verification."""
        report = assemble_report(
            _fields(observed="fails under /home/jbloggs/acme every time"),
            project_root=Path("/home/jbloggs/acme"),
        )

        assert verify_document(report.document) == ()


class TestARefusedReport:
    def test_a_leaking_reproduction_is_refused(self) -> None:
        assert assemble_report(_fields(reproduction="Edit /home/jbloggs/acme/app.py")).problems

    def test_a_refused_report_produces_no_document(self) -> None:
        """A document that exists is a document that can be filed by mistake."""
        report = assemble_report(_fields(reproduction="Edit /home/jbloggs/acme/app.py"))

        assert report.document == ""

    def test_a_missing_summary_is_refused(self) -> None:
        assert assemble_report(_fields(summary="  ")).problems

    def test_a_report_with_no_config_considered_is_refused(self) -> None:
        """Ruling configuration out is the first thing the SOP asks for.

        The generator cannot know whether the reporter really thought about it.
        It CAN require them to name an option and say why it is insufficient,
        which is the move the remote-docs provenance frontmatter already makes
        here: turn an unverifiable claim into a checkable artefact.
        """
        assert assemble_report(_fields(config_considered=())).problems

    def test_the_refusal_explains_rather_than_just_failing(self) -> None:
        reasons = " ".join(p.reason for p in assemble_report(_fields(summary="")).problems)

        assert reasons.strip()
