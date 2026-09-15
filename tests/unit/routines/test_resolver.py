"""Resolving a routine and its procedure — Plan 00412 Task 2.3 (RED first).

The CLI verb is deliberately thin: everything it does that can be wrong lives
here, where it can be tested without argparse. ``cli.py`` is already 9,000
lines, and the last collector that grew inside it had to be extracted so a
directive and a command could not disagree about what they were describing.

Two things this module refuses to guess at. A routine id that matches nothing
is an error rather than an empty result, because the caller named something
specific and silence would look like a routine that has never run. And a
ROUTINE.md with no ``## Procedure`` section is an error too: handing an agent
an empty procedure is how a run gets recorded for work nobody actually did.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.routines.resolver import (
    ProcedureMissingError,
    RoutineNotFoundError,
    find_routine,
    list_routines,
    read_procedure,
    routines_dir,
)

_ROUTINE_BODY = """# Routine 00001: security review

**Status**: Active

## Purpose

Keep the repository reviewed.

## Procedure

1. Draw a sample.
2. Review it.
3. File findings as plans.

## Non-Goals

- Nothing.
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project root with one scaffolded routine."""
    target = tmp_path / "CLAUDE" / "Routine" / "00001-security-review"
    (target / "RUNS").mkdir(parents=True)
    (target / "ROUTINE.md").write_text(_ROUTINE_BODY)
    return tmp_path


class TestRoutinesDir:
    """Where routines live, relative to a project root."""

    def test_is_claude_routine(self, project: Path) -> None:
        """Beside CLAUDE/Plan, which is the point of the naming."""
        assert routines_dir(project) == project / "CLAUDE" / "Routine"


class TestFindRoutine:
    """Naming a routine, the way a cron prompt does."""

    def test_finds_by_number(self, project: Path) -> None:
        """The number is the stable handle; the name can be renamed."""
        assert find_routine(project, "00001").name == "00001-security-review"

    def test_finds_by_unpadded_number(self, project: Path) -> None:
        """Nobody types the leading zeros, and a cron prompt should not have to."""
        assert find_routine(project, "1").name == "00001-security-review"

    def test_finds_by_full_folder_name(self, project: Path) -> None:
        """Pasting the folder name back in is the obvious thing to try."""
        assert find_routine(project, "00001-security-review").name == "00001-security-review"

    def test_unknown_id_raises(self, project: Path) -> None:
        """An error, never an empty result.

        The caller named something specific. Returning nothing would read
        downstream as a routine that exists and has never run, which is a
        different and much quieter kind of wrong.
        """
        with pytest.raises(RoutineNotFoundError, match="00009"):
            find_routine(project, "00009")

    def test_missing_tree_raises_rather_than_returning_nothing(self, tmp_path: Path) -> None:
        """A project with no routines at all still gets a named failure."""
        with pytest.raises(RoutineNotFoundError):
            find_routine(tmp_path, "00001")

    def test_ignores_an_archived_duplicate_of_a_live_routine(self, project: Path) -> None:
        """A live routine wins over an archived folder carrying its number."""
        archived = project / "CLAUDE" / "Routine" / "Completed" / "00001-old-review"
        archived.mkdir(parents=True)

        assert find_routine(project, "00001").name == "00001-security-review"

    def test_finds_an_archived_routine_when_nothing_live_matches(self, project: Path) -> None:
        """An archived routine is still addressable — it is history, not deleted."""
        archived = project / "CLAUDE" / "Routine" / "Completed" / "00004-retired-sweep"
        archived.mkdir(parents=True)

        assert find_routine(project, "00004").name == "00004-retired-sweep"


class TestListRoutines:
    """Enumerating what a project declares."""

    def test_lists_live_routines(self, project: Path) -> None:
        """The index a human asks for before naming one."""
        assert [path.name for path in list_routines(project)] == ["00001-security-review"]

    def test_empty_project_lists_nothing(self, tmp_path: Path) -> None:
        """No tree is not an error here — nothing was named."""
        assert list_routines(tmp_path) == []

    def test_excludes_the_lock_directory(self, project: Path) -> None:
        """The scaffolder's lock is a dotfile, and is not a routine."""
        (project / "CLAUDE" / "Routine" / ".mkroutine.lock").mkdir()

        assert [path.name for path in list_routines(project)] == ["00001-security-review"]


class TestReadProcedure:
    """The section a run actually executes."""

    def test_returns_the_procedure_section(self, project: Path) -> None:
        """Only the procedure — the rest of the document is context, not steps."""
        procedure = read_procedure(find_routine(project, "00001"))

        assert "1. Draw a sample." in procedure
        assert "Keep the repository reviewed." not in procedure

    def test_stops_at_the_next_heading(self, project: Path) -> None:
        """A procedure that swallowed the following section would misinstruct."""
        procedure = read_procedure(find_routine(project, "00001"))

        assert "Non-Goals" not in procedure

    def test_missing_procedure_raises(self, project: Path) -> None:
        """An empty procedure is how a run gets recorded for work nobody did.

        Failing loudly here is the whole reason this is not a "" default: the
        record would otherwise prove a run that consisted of nothing.
        """
        routine = find_routine(project, "00001")
        (routine / "ROUTINE.md").write_text("# Routine 00001\n\n## Purpose\n\nNone.\n")

        with pytest.raises(ProcedureMissingError, match="Procedure"):
            read_procedure(routine)

    def test_an_unfilled_template_procedure_raises(self, project: Path) -> None:
        """A scaffolded-but-unfilled routine is not runnable.

        The skeleton leaves an HTML comment under the heading. A run against
        that would record coverage for an interval nobody reviewed, which is
        exactly the silent-wrongness the interval model exists to prevent.
        """
        routine = find_routine(project, "00001")
        (routine / "ROUTINE.md").write_text(
            "# Routine 00001\n\n## Procedure\n\n<!-- The steps a run performs. -->\n"
        )

        with pytest.raises(ProcedureMissingError):
            read_procedure(routine)

    def test_missing_routine_document_raises(self, project: Path) -> None:
        """A folder with no ROUTINE.md is not a routine."""
        routine = find_routine(project, "00001")
        (routine / "ROUTINE.md").unlink()

        with pytest.raises(ProcedureMissingError):
            read_procedure(routine)
