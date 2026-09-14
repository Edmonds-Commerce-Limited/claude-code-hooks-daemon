"""Orchestrating the checks into one report (Plan 00403 Task 2.1/3.1/3.3).

`assemble_report` builds the document; this layer decides whether it may be
built at all. It runs the verification gates — version currency, the source
citation — and refuses with every reason at once rather than one per round
trip.

One consequence is worth stating because it looks like a bug and is the rule
working. An install BEHIND the newest release cannot answer the currency
question offline: the release notes that shipped with it stop at its own
version, so the notes for the versions in between are exactly what it does not
have. `assess_currency` therefore refuses, and the remedy is to upgrade —
which is the owner's rule ("ensure that they are running the latest version")
arrived at mechanically rather than asserted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.issue_report.build import build_report

_REPRODUCTION = "1. mkdir -p untracked/scratch/repro\n2. Write untracked/scratch/repro/a.py\n"


@pytest.fixture()
def daemon_root(tmp_path: Path) -> Path:
    source = tmp_path / "src" / "claude_code_hooks_daemon" / "handlers"
    source.mkdir(parents=True)
    (source / "thing.py").write_text("\n".join(f"line {n}" for n in range(1, 51)))
    return tmp_path


def _fields(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "summary": "thing.py denies a read-only command",
        "handler": "sed_blocker",
        "expected": "A read-only pipeline is allowed.",
        "observed": "It is denied.",
        "reproduction": _REPRODUCTION,
        "config_considered": [
            {
                "option": "handlers.pre_tool_use.sed_blocker.enabled",
                "why_insufficient": "Disabling removes the protection entirely.",
            }
        ],
        "source_citation": "src/claude_code_hooks_daemon/handlers/thing.py:10",
    }
    data.update(overrides)
    return data


def _build(daemon_root: Path, **overrides: object):
    return build_report(
        _fields(**overrides),
        project_root=daemon_root,
        daemon_root=daemon_root,
        daemon_version="3.28.0",
        install_mode="normal",
        platform_text="Linux x86_64, Python 3.12.3",
        generated_at="2026-09-14",
        release_notes={"3.28.0": "Docs only."},
    )


class TestAGoodReport:
    def test_it_is_produced(self, daemon_root: Path) -> None:
        assert _build(daemon_root).problems == ()

    def test_the_document_carries_the_currency_finding(self, daemon_root: Path) -> None:
        """A maintainer must see the check ran, not infer it from the report existing."""
        assert "newest release" in _build(daemon_root).document

    def test_the_document_carries_the_citation_finding(self, daemon_root: Path) -> None:
        assert "resolves in the installed version" in _build(daemon_root).document


class TestTheGatesRefuse:
    def test_a_dead_citation_refuses(self, daemon_root: Path) -> None:
        report = _build(
            daemon_root,
            source_citation="src/claude_code_hooks_daemon/handlers/thing.py:9999",
        )

        assert report.problems
        assert report.document == ""

    def test_a_missing_citation_refuses(self, daemon_root: Path) -> None:
        assert _build(daemon_root, source_citation=None).problems

    def test_a_behind_install_refuses_because_it_cannot_answer_offline(
        self, daemon_root: Path
    ) -> None:
        """Not a bug: the notes for the versions in between are what it lacks."""
        report = build_report(
            _fields(),
            project_root=daemon_root,
            daemon_root=daemon_root,
            daemon_version="3.20.0",
            install_mode="normal",
            platform_text="Linux",
            generated_at="2026-09-14",
            release_notes={},
            latest_version="3.28.0",
        )

        assert report.problems

    def test_a_subsystem_that_changed_since_refuses(self, daemon_root: Path) -> None:
        report = build_report(
            _fields(),
            project_root=daemon_root,
            daemon_root=daemon_root,
            daemon_version="3.26.0",
            install_mode="normal",
            platform_text="Linux",
            generated_at="2026-09-14",
            release_notes={"3.27.0": "Reworked the sed blocker's exemptions."},
            latest_version="3.27.0",
        )

        assert report.problems

    def test_every_reason_is_returned_not_just_the_first(self, daemon_root: Path) -> None:
        """One refusal per round trip teaches the rule one refusal at a time."""
        report = _build(daemon_root, summary="", source_citation="nonsense")

        assert len(report.problems) >= 2


class TestMalformedInput:
    def test_a_missing_required_field_is_reported_not_raised(self, daemon_root: Path) -> None:
        """The caller is a CLI; a KeyError here is a stack trace, not a message."""
        data = _fields()
        del data["summary"]

        report = build_report(
            data,
            project_root=daemon_root,
            daemon_root=daemon_root,
            daemon_version="3.28.0",
            install_mode="normal",
            platform_text="Linux",
            generated_at="2026-09-14",
            release_notes={"3.28.0": "Docs only."},
        )

        assert report.problems
        assert "summary" in " ".join(p.reason for p in report.problems)

    def test_a_malformed_config_entry_is_reported(self, daemon_root: Path) -> None:
        report = _build(daemon_root, config_considered=["not-a-mapping"])

        assert report.problems

    def test_a_config_entry_missing_its_reason_is_reported(self, daemon_root: Path) -> None:
        report = _build(daemon_root, config_considered=[{"option": "some.key"}])

        assert report.problems
