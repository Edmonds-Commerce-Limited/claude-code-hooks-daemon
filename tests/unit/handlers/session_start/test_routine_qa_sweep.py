"""``routine_qa_sweep`` — Plan 00412 Task 2.5 (RED first).

The dead-man's switch. Every other part of this system reports what the records
SAY; this one reports what they do not contain. A run that never happened
leaves no record at all, so its absence is not observable from the records
themselves (D6) — something outside them has to go looking, and this is it.

Three properties matter more than the report's wording:

- **silent when clean.** A handler that speaks every session is scenery, and
  scenery is what Plan 00416 exists to fix. This one must produce nothing at
  all when the tree is healthy;
- **opt-in.** Most projects have no Routine tree, and a handler that fires for
  them would be noise on day one;
- **it never raises.** A sweep that dies reports nothing, which is exactly what
  a healthy tree also reports. That ambiguity is the failure this whole plan
  is built to design out, so it must not be reintroduced by the surface that
  does the reporting.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.session_start.routine_qa_sweep import (
    RoutineQaSweepHandler,
)

_NEW_SESSION: dict[str, Any] = {"session_id": "s1"}


def _resumed(tmp_path: Path) -> dict[str, Any]:
    """A payload the project's own resume test recognises.

    A resume is detected from a transcript that already has content, not from
    any ``source`` field — so the double has to be a real file, or this test
    would pass against a handler that never checked at all.
    """
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("x" * 500)
    return {"session_id": "s1", "transcript_path": str(transcript)}


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project root the handler will resolve to."""
    monkeypatch.setattr(ProjectContext, "project_root", staticmethod(lambda: tmp_path))
    return tmp_path


def _routine(project_root: Path, *, status: str = "Active") -> Path:
    """A routine that has never run."""
    folder = project_root / "CLAUDE" / "Routine" / "00001-security-review"
    (folder / "RUNS").mkdir(parents=True)
    (folder / "ROUTINE.md").write_text(
        f"# Routine 00001\n\n**Status**: {status}\n**Trigger**: schedule\n"
        "**Period**: 30 days\n\n## Procedure\n\n1. Review.\n"
    )
    return folder


class TestRegistration:
    """How the handler declares itself."""

    def test_uses_its_own_handler_id(self) -> None:
        """A shared id would make two handlers indistinguishable in config."""
        assert RoutineQaSweepHandler().handler_id == HandlerID.ROUTINE_QA_SWEEP

    def test_runs_before_the_session_actions_directive(self) -> None:
        """That directive counts what is STILL action-required, so it goes last.

        Not tidiness: it tallies after every other handler has run, and one of
        them self-heals inside its own handle(). Anything added to the band
        must sit before it, and this pins that this handler does.
        """
        assert Priority.ROUTINE_QA_SWEEP < Priority.SESSION_ACTIONS_DIRECTIVE

    def test_is_opt_in(self) -> None:
        """Most projects have no Routine tree; firing for them is noise."""
        assert RoutineQaSweepHandler().get_default_enabled() is False

    def test_earns_claude_md_guidance(self) -> None:
        """An advisory an agent may meet deserves an explanation in CLAUDE.md."""
        assert RoutineQaSweepHandler().get_claude_md()


class TestMatches:
    """When the sweep runs at all."""

    def test_fires_on_a_new_session(self, project: Path) -> None:
        """The report is worth one turn at the start of a session."""
        _routine(project)

        assert RoutineQaSweepHandler().matches(_NEW_SESSION) is True

    def test_does_not_fire_on_a_resume(self, project: Path) -> None:
        """A resumed session already saw the report; repeating it is noise."""
        _routine(project)

        assert RoutineQaSweepHandler().matches(_resumed(project)) is False

    def test_does_not_fire_without_a_routine_tree(self, project: Path) -> None:
        """A project that declares no routines has nothing to be failing."""
        assert RoutineQaSweepHandler().matches(_NEW_SESSION) is False


class TestHandle:
    """What the sweep reports."""

    def test_is_silent_when_the_tree_is_clean(self, project: Path) -> None:
        """The property that keeps it worth reading.

        A handler that speaks every session becomes scenery, and an advisory
        nobody reads is worth exactly what no advisory is worth.
        """
        folder = _routine(project, status="Retired")

        result = RoutineQaSweepHandler().handle(_NEW_SESSION)

        assert result.context == []
        assert folder.exists()

    def test_reports_a_routine_that_never_ran(self, project: Path) -> None:
        """The dead-man's switch firing, which is the whole point."""
        _routine(project)

        result = RoutineQaSweepHandler().handle(_NEW_SESSION)

        assert result.context
        assert any("never run" in line for line in result.context)

    def test_names_the_re_check_command(self, project: Path) -> None:
        """A report without a way to re-check it cannot be closed out."""
        _routine(project)

        result = RoutineQaSweepHandler().handle(_NEW_SESSION)

        assert any("routine-qa" in line for line in result.context)

    def test_always_allows(self, project: Path) -> None:
        """Advisory, never blocking: a stale routine must not wedge a session."""
        _routine(project)

        assert RoutineQaSweepHandler().handle(_NEW_SESSION).decision is Decision.ALLOW

    def test_survives_an_unreadable_tree(self, project: Path) -> None:
        """A sweep that raises reports nothing — and so does a healthy one.

        Those two must never be the same outcome, so a broken tree is reported
        rather than thrown. This is the plan's central argument applied to the
        plan's own reporting surface.
        """
        folder = project / "CLAUDE" / "Routine" / "00001-broken"
        folder.mkdir(parents=True)

        result = RoutineQaSweepHandler().handle(_NEW_SESSION)

        assert result.decision is Decision.ALLOW
        assert result.context
