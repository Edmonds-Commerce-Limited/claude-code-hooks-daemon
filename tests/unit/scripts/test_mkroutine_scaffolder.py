"""``CLAUDE/Routine/mkroutine.bash`` — Plan 00412 Task 2.2 (RED first).

A Routine is numbered like a Plan and for the same reason: the number is the
stable handle every inbound reference uses. So the number must come from the
git-anchored counter under a lock, never from a folder scan — a scan misses
archived routines and disagrees across branches, which is how two routines end
up sharing a number and the collision only surfaces at the commit gate.

``mkplan.bash`` already solves this, and this script deliberately mirrors it
rather than sharing code with it: that script documents self-containment as a
design property (it is deployed standalone into client projects), so factoring
the algorithm into a sourced library would break the thing that makes it
deployable. The duplication is accepted, and the cost is paid here — the tests
below pin the properties the two must agree on, so a fix applied to one and not
the other fails rather than drifting silently.

The script is exercised in a real ``bash`` against a real temporary git
repository. The behaviour under test is shell semantics and git-config state,
neither of which a Python-level assertion could observe.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

#: Ceiling for one scaffolder run. It does a handful of globs over a tmp_path
#: holding at most a few folders, so this is a wedged-shell guard rather than a
#: budget -- if it is ever approached, failing is right.
_SHELL_TIMEOUT = Timeout.VALIDATION_CHECK

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "CLAUDE" / "Routine" / "mkroutine.bash"

_ROUTINE_COUNTER_KEY = "hooksdaemon.latestRoutineNumber"
_PLAN_COUNTER_KEY = "hooksdaemon.latestPlanNumber"


def _git(repo: Path, *args: str) -> str:
    """Run a git command in ``repo`` and return its stdout, stripped."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=_SHELL_TIMEOUT,
    )
    return completed.stdout.strip()


def _git_config_or_none(repo: Path, key: str) -> str | None:
    """The local git config value for ``key``, or None when it is unset.

    ``git config --get`` exits 1 for an unset key, which is not an error here:
    "unset" is one of the two answers this helper exists to distinguish.
    """
    completed = subprocess.run(
        ["git", "-C", str(repo), "config", "--local", "--get", key],
        capture_output=True,
        text=True,
        check=False,
        timeout=_SHELL_TIMEOUT,
    )
    if completed.returncode == 0:
        return completed.stdout.strip()
    if completed.returncode == 1:
        return None
    raise AssertionError(
        f"git config --get {key} failed unexpectedly "
        f"(exit {completed.returncode}): {completed.stderr}"
    )


@pytest.fixture
def routine_repo(tmp_path: Path) -> Path:
    """A temporary git repo with the real scaffolder in its ``CLAUDE/Routine``.

    The script self-locates from ``BASH_SOURCE``, so copying it in is what
    makes the temporary tree the routine dir -- no environment override, which
    keeps the common deployment path under test.
    """
    routine_dir = tmp_path / "CLAUDE" / "Routine"
    routine_dir.mkdir(parents=True)
    target = routine_dir / _SCRIPT.name
    target.write_bytes(_SCRIPT.read_bytes())
    target.chmod(0o755)

    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "scaffolder@test.invalid")
    _git(tmp_path, "config", "user.name", "Scaffolder Test")
    return tmp_path


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the scaffolder in ``repo`` from an unrelated working directory.

    Run from the repo root rather than the routine dir so a regression that
    reintroduces CWD-dependence is visible.
    """
    return subprocess.run(
        [str(repo / "CLAUDE" / "Routine" / "mkroutine.bash"), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
        timeout=_SHELL_TIMEOUT,
    )


class TestNumbering:
    """The number comes from the git counter, under a lock, never a scan."""

    def test_bootstraps_to_one_in_an_empty_tree(self, routine_repo: Path) -> None:
        """No counter and no routines is a new project, which starts at 00001."""
        result = _run(routine_repo, "security-review")

        assert result.returncode == 0, result.stderr
        assert (routine_repo / "CLAUDE" / "Routine" / "00001-security-review").is_dir()

    def test_takes_the_counter_plus_one(self, routine_repo: Path) -> None:
        """An existing counter is authoritative, even over an empty tree."""
        _git(routine_repo, "config", "--local", _ROUTINE_COUNTER_KEY, "7")

        result = _run(routine_repo, "dependency-audit")

        assert result.returncode == 0, result.stderr
        assert (routine_repo / "CLAUDE" / "Routine" / "00008-dependency-audit").is_dir()

    def test_advances_the_routine_counter(self, routine_repo: Path) -> None:
        """The counter moves only after the folder is successfully created."""
        _git(routine_repo, "config", "--local", _ROUTINE_COUNTER_KEY, "7")

        _run(routine_repo, "dependency-audit")

        assert _git_config_or_none(routine_repo, _ROUTINE_COUNTER_KEY) == "8"

    def test_does_not_touch_the_plan_counter(self, routine_repo: Path) -> None:
        """Routines and Plans number INDEPENDENTLY.

        The guard that matters most here. Both trees live in the same repo and
        both counters live in the same git config, so a copy-paste that left
        the plan key in place would work perfectly -- while silently consuming
        plan numbers, which is unrecoverable once a plan is filed against one.
        """
        _git(routine_repo, "config", "--local", _PLAN_COUNTER_KEY, "412")

        _run(routine_repo, "security-review")

        assert _git_config_or_none(routine_repo, _PLAN_COUNTER_KEY) == "412"

    def test_refuses_when_the_counter_is_behind_disk(self, routine_repo: Path) -> None:
        """A stale counter is refused, not silently worked around.

        Proceeding would assign a number that already exists on disk, or
        mis-order the tree. The script reports how to reconcile instead.
        """
        (routine_repo / "CLAUDE" / "Routine" / "00009-already-here").mkdir()
        _git(routine_repo, "config", "--local", _ROUTINE_COUNTER_KEY, "3")

        result = _run(routine_repo, "security-review")

        assert result.returncode != 0
        assert _ROUTINE_COUNTER_KEY in result.stderr

    def test_counts_archived_routines_in_the_high_water_mark(self, routine_repo: Path) -> None:
        """A routine one level down (``Completed/``) still holds its number.

        This is the exact failure a folder scan of the top level produces, and
        the reason the drift guard scans one level deeper.
        """
        archived = routine_repo / "CLAUDE" / "Routine" / "Completed" / "00012-retired-sweep"
        archived.mkdir(parents=True)
        _git(routine_repo, "config", "--local", _ROUTINE_COUNTER_KEY, "3")

        result = _run(routine_repo, "security-review")

        assert result.returncode != 0
        assert "00012" in result.stderr or "12" in result.stderr


class TestScaffolding:
    """What a new routine folder contains."""

    def test_writes_routine_md(self, routine_repo: Path) -> None:
        """The definition document is the routine's PLAN.md equivalent."""
        _run(routine_repo, "security-review")

        routine_md = routine_repo / "CLAUDE" / "Routine" / "00001-security-review" / "ROUTINE.md"
        assert routine_md.is_file()
        body = routine_md.read_text()
        assert "00001" in body
        assert "security review" in body

    def test_scaffolded_header_parses_as_undeclared(self, routine_repo: Path) -> None:
        """A fresh routine declares nothing, and says so to the parser.

        The scaffolder leaves placeholders rather than a plausible cadence,
        so the model reads the trigger as UNKNOWN and the QA sweep can report
        "this routine has not been configured". Writing a default cadence into
        the skeleton would instead hand every new routine a schedule nobody
        chose — wrong, and silently so.
        """
        from claude_code_hooks_daemon.routines.model import Trigger, parse_routine

        _run(routine_repo, "security-review")

        doc = parse_routine(routine_repo / "CLAUDE" / "Routine" / "00001-security-review")
        assert doc.trigger is Trigger.UNKNOWN
        assert doc.period_days is None

    def test_creates_an_empty_runs_directory(self, routine_repo: Path) -> None:
        """``RUNS/`` exists from the start.

        A routine that has never run and a routine whose runs directory was
        never created are different facts, and only the first is interesting.
        Creating it up front means an absent ledger always means "never ran".
        """
        _run(routine_repo, "security-review")

        runs = routine_repo / "CLAUDE" / "Routine" / "00001-security-review" / "RUNS"
        assert runs.is_dir()
        assert list(runs.iterdir()) == []

    def test_prefers_a_project_template_over_the_built_in_skeleton(
        self, routine_repo: Path
    ) -> None:
        """A tracked ``_TEMPLATE_.md`` wins, so a project owns its own shape.

        Mirrors ``mkplan.bash``: the built-in skeleton is a starting point that
        keeps the script self-contained, not the definition of the document.
        """
        template = routine_repo / "CLAUDE" / "Routine" / "_TEMPLATE_.md"
        template.write_text("# Routine {{ROUTINE_NUMBER}}: {{ROUTINE_TITLE}}\n\nours\n")

        _run(routine_repo, "security-review")

        body = (
            routine_repo / "CLAUDE" / "Routine" / "00001-security-review" / "ROUTINE.md"
        ).read_text()
        assert body.startswith("# Routine 00001: security review")
        assert "ours" in body
        assert "## Procedure" not in body

    def test_substitutes_every_template_placeholder(self, routine_repo: Path) -> None:
        """An unsubstituted placeholder is worse than a missing field.

        It reads as content, survives review, and is only noticed when someone
        greps for the literal braces.
        """
        template = routine_repo / "CLAUDE" / "Routine" / "_TEMPLATE_.md"
        template.write_text("{{ROUTINE_NUMBER}} {{ROUTINE_TITLE}} {{CREATED_DATE}} {{OWNER}}\n")

        _run(routine_repo, "security-review")

        body = (
            routine_repo / "CLAUDE" / "Routine" / "00001-security-review" / "ROUTINE.md"
        ).read_text()
        assert "{{" not in body
        assert "Scaffolder Test" in body

    def test_prints_the_target_path_on_stdout(self, routine_repo: Path) -> None:
        """Stdout is the folder path alone, so a caller can consume it.

        Everything human-facing goes to stderr, exactly as ``mkplan.bash``
        does, so ``dir=$(mkroutine.bash name)`` works.
        """
        result = _run(routine_repo, "security-review")

        assert result.stdout.strip().endswith("CLAUDE/Routine/00001-security-review")


class TestNameHandling:
    """The name becomes a folder, so it is normalised and then validated."""

    def test_normalises_whitespace_to_kebab(self, routine_repo: Path) -> None:
        """A quoted sentence is a legitimate way to name a routine."""
        result = _run(routine_repo, "Quarterly security review")

        assert result.returncode == 0, result.stderr
        assert (routine_repo / "CLAUDE" / "Routine" / "00001-Quarterly-security-review").is_dir()

    def test_rejects_a_name_not_starting_with_a_letter(self, routine_repo: Path) -> None:
        """The number prefix is the script's to assign, never the caller's."""
        result = _run(routine_repo, "00007-security-review")

        assert result.returncode != 0
        assert not list((routine_repo / "CLAUDE" / "Routine").glob("0*-*"))

    def test_rejects_a_missing_argument(self, routine_repo: Path) -> None:
        """No name means no routine, and the usage text explains why."""
        result = _run(routine_repo)

        assert result.returncode != 0
        assert "Usage" in result.stderr


class TestConcurrency:
    """Two runners must never assign the same number."""

    def test_parallel_runs_get_distinct_numbers(self, routine_repo: Path) -> None:
        """The lock closes the multi-process race.

        Without it both runners read the same counter and create folders that
        collide on a number -- the failure mode the git counter exists to
        prevent, which only a concurrent test can observe.
        """
        script = str(routine_repo / "CLAUDE" / "Routine" / "mkroutine.bash")
        processes = [
            subprocess.Popen(
                [script, name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=routine_repo,
            )
            for name in ("first-sweep", "second-sweep")
        ]
        for process in processes:
            process.wait(timeout=_SHELL_TIMEOUT)

        assert all(process.returncode == 0 for process in processes), [
            process.stderr.read() for process in processes if process.stderr is not None
        ]
        created = sorted(path.name for path in (routine_repo / "CLAUDE" / "Routine").glob("0*-*"))
        assert created == ["00001-first-sweep", "00002-second-sweep"] or created == [
            "00001-second-sweep",
            "00002-first-sweep",
        ]
