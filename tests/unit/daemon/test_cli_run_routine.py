"""``hooks-daemon run-routine`` — Plan 00412 Task 2.3.

The verb is thin on purpose (resolution and the ledger are tested in
``tests/unit/routines/``), so what is pinned here is what only the CLI can get
wrong: the exit codes, the two renamings in the listing, and the refusal to
record a terminal outcome without the interval it covered.

The honest contract this verb implements (D7): a cron PROMPTS a run and the
record PROVES one. The verb opens the record and hands over the procedure. It
cannot execute the procedure, and nothing here should ever make it look as
though it can.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_run_routine
from claude_code_hooks_daemon.routines.ledger import RunState
from claude_code_hooks_daemon.routines.resolver import ROUTINE_DOC

_PROCEDURE_STEP = "Draw a weighted random sample."

_ROUTINE_BODY = f"""# Routine 00001: security review

**Status**: Active

## Procedure

1. {_PROCEDURE_STEP}
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project root with one runnable routine."""
    target = tmp_path / "CLAUDE" / "Routine" / "00001-security-review"
    (target / "RUNS").mkdir(parents=True)
    (target / ROUTINE_DOC).write_text(_ROUTINE_BODY)
    return tmp_path


def _args(project_root: Path, **overrides: object) -> argparse.Namespace:
    """A Namespace shaped like the parser's, with the defaults the parser sets."""
    defaults: dict[str, object] = {
        "identifier": None,
        "list_routines": False,
        "finish": False,
        "outcome": None,
        "from_ref": None,
        "to_ref": None,
        "run_id": None,
        "note": "",
        "project_root": str(project_root),
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestList:
    """The index, and the two labels that are NOT the derived state's name."""

    def test_never_run_is_not_a_state(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """D6: absence of a record is reported from an empty map, not a value.

        If "never run" were a state, a routine nobody had ever run could be
        reported as though something had looked at it.
        """
        assert cmd_run_routine(_args(project, list_routines=True)) == 0

        assert "never run" in capsys.readouterr().out

    def test_an_open_run_reads_as_unfinished_not_failed(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A run in progress and a run that died are identical in the record.

        That indistinguishability is the point of DERIVING the state. But a
        listing is read by someone asking about the world, and calling a
        healthy in-flight run `failed` accuses it of something untrue. Telling
        the two apart needs a grace window, which nothing here has yet.
        """
        cmd_run_routine(_args(project, identifier="00001"))
        capsys.readouterr()

        cmd_run_routine(_args(project, list_routines=True))

        out = capsys.readouterr().out
        assert "unfinished" in out
        assert str(RunState.FAILED) not in out

    def test_empty_project_is_not_an_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Declaring no routines is a valid state of the world."""
        assert cmd_run_routine(_args(tmp_path, list_routines=True)) == 0
        assert "No routines declared" in capsys.readouterr().out


class TestStart:
    """Opening a run."""

    def test_prints_the_procedure(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Handing over the procedure IS the verb's job — it cannot run it."""
        assert cmd_run_routine(_args(project, identifier="00001")) == 0

        assert _PROCEDURE_STEP in capsys.readouterr().out

    def test_records_the_start(self, project: Path) -> None:
        """The record is opened before the work, so an abandoned run is visible."""
        cmd_run_routine(_args(project, identifier="00001"))

        ledger = project / "CLAUDE" / "Routine" / "00001-security-review" / "RUNS"
        assert [path.name for path in ledger.iterdir()]

    def test_unknown_routine_exits_one(self, project: Path) -> None:
        """Naming something that does not exist is an error, not an empty run."""
        assert cmd_run_routine(_args(project, identifier="00009")) == 1

    def test_unfilled_procedure_exits_one(self, project: Path) -> None:
        """A run against a scaffolded placeholder would record work nobody did."""
        routine = project / "CLAUDE" / "Routine" / "00001-security-review"
        (routine / ROUTINE_DOC).write_text(
            "# Routine 00001\n\n## Procedure\n\n<!-- The steps a run performs. -->\n"
        )

        assert cmd_run_routine(_args(project, identifier="00001")) == 1

    def test_no_identifier_and_no_list_exits_one(self, project: Path) -> None:
        """Doing nothing silently would look like a run that found nothing."""
        assert cmd_run_routine(_args(project)) == 1


class TestFinish:
    """Recording the outcome."""

    def test_records_a_clean_run(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Found nothing is an OUTCOME, recorded as loudly as findings."""
        cmd_run_routine(_args(project, identifier="00001"))
        capsys.readouterr()

        exit_code = cmd_run_routine(
            _args(
                project,
                identifier="00001",
                finish=True,
                outcome="clean",
                from_ref="abc123",
                to_ref="def456",
            )
        )

        assert exit_code == 0
        assert "clean" in capsys.readouterr().out

    def test_refuses_a_terminal_outcome_without_an_interval(self, project: Path) -> None:
        """The refusal that protects gap detection.

        A terminal row with no interval composes wrongly and does it silently,
        so the verb will not write one however it is asked.
        """
        cmd_run_routine(_args(project, identifier="00001"))

        assert (
            cmd_run_routine(_args(project, identifier="00001", finish=True, outcome="clean")) == 1
        )

    def test_refuses_a_skip_with_no_reason(self, project: Path) -> None:
        """The reason IS the state — without it this is an unexplained absence."""
        cmd_run_routine(_args(project, identifier="00001"))

        assert (
            cmd_run_routine(_args(project, identifier="00001", finish=True, outcome="skipped")) == 1
        )

    def test_records_a_skip_with_a_reason(self, project: Path) -> None:
        """A deliberate non-run, recorded as such rather than left as a hole."""
        cmd_run_routine(_args(project, identifier="00001"))

        exit_code = cmd_run_routine(
            _args(
                project,
                identifier="00001",
                finish=True,
                outcome="skipped",
                note="release freeze",
            )
        )

        assert exit_code == 0

    def test_finish_without_an_outcome_exits_one(self, project: Path) -> None:
        """A finished run with no outcome would prove a run and say nothing."""
        cmd_run_routine(_args(project, identifier="00001"))

        assert cmd_run_routine(_args(project, identifier="00001", finish=True)) == 1

    def test_ambiguous_finish_requires_naming_the_run(self, project: Path) -> None:
        """Two open runs, so the verb refuses to guess which one ended.

        Guessing would attach an interval to the wrong run, which is the
        pointer bug the interval model exists to prevent.
        """
        cmd_run_routine(_args(project, identifier="00001"))
        cmd_run_routine(_args(project, identifier="00001"))

        assert (
            cmd_run_routine(
                _args(
                    project,
                    identifier="00001",
                    finish=True,
                    outcome="clean",
                    from_ref="abc123",
                    to_ref="def456",
                )
            )
            == 1
        )

    def test_naming_the_run_resolves_the_ambiguity(self, project: Path) -> None:
        """``--run`` is the disambiguator the refusal above points at."""
        cmd_run_routine(_args(project, identifier="00001"))
        cmd_run_routine(_args(project, identifier="00001"))

        exit_code = cmd_run_routine(
            _args(
                project,
                identifier="00001",
                finish=True,
                outcome="clean",
                from_ref="abc123",
                to_ref="def456",
                run_id="2026-001",
            )
        )

        assert exit_code == 0
