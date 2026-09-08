"""A declared-blocking acceptance gate may not skip silently.

`RELEASING.md` Step 12.0 names the acceptance files a release blocks on, and
states the expectation on the line below the command: *0 failed, 0 skipped*.
About one of them it is explicit — "a skip there is itself an abort condition".

Nothing enforced that outside a release. CI ran every one of those files with no
daemon for months and reported the run green, because pytest counts a skip as
neither a pass nor a failure (Plan 00250).

These tests cover the guard that closes it. The guard READS the blocking set
from RELEASING.md's own command line, so the declaration keeps exactly one home
— which means the interesting failure is no longer "the guard forgot a file"
but "the guard can no longer find the declaration and is silently protecting
nothing". Most of what follows is aimed at that.
"""

from __future__ import annotations

import subprocess  # nosec B404 - trusted interpreter, list form, for a nested pytest run
import sys
import textwrap
from pathlib import Path

import pytest

from tests.acceptance.blocking_gate_guard import (
    RELEASING_MD,
    blocking_gate_skip_failure_message,
    declared_blocking_gate_files,
    parse_declared_blocking_gate_files,
    skip_is_an_abort_condition,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE_DIR = REPO_ROOT / "tests" / "acceptance"

_REAL_DECLARATION_LINE = (
    '"$PY" -m pytest tests/acceptance/test_alpha.py tests/acceptance/test_beta.py -v'
)


class TestTheDeclarationIsRead:
    """The blocking set comes from RELEASING.md, and only from there."""

    def test_the_declared_files_all_exist(self) -> None:
        """A rename that misses RELEASING.md must fail here, not silently unguard."""
        missing = [
            name for name in declared_blocking_gate_files() if not (ACCEPTANCE_DIR / name).is_file()
        ]
        assert not missing, (
            f"RELEASING.md Step 12.0 declares {missing} as blocking release "
            f"gates, but no such file exists in {ACCEPTANCE_DIR}. Either the "
            f"file was renamed without updating the declaration, or the "
            f"declaration has a typo — both leave the gate unguarded."
        )

    def test_the_real_declaration_yields_a_plausible_set(self) -> None:
        """Guards against a parser that 'succeeds' by matching the wrong line."""
        declared = declared_blocking_gate_files()
        assert declared, "the blocking set must not be empty"
        assert all(name.startswith("test_") for name in declared)
        assert all(name.endswith(".py") for name in declared)

    def test_a_declaration_the_parser_cannot_find_is_an_error(self) -> None:
        """The whole point: no declaration must never degrade to 'guard nothing'."""
        with pytest.raises(AssertionError, match="exactly one"):
            parse_declared_blocking_gate_files("# a RELEASING.md with no Step 12.0\n")

    def test_two_declarations_are_an_error(self) -> None:
        """Two command lines mean two sources of truth — refuse to pick one."""
        with pytest.raises(AssertionError, match="exactly one"):
            parse_declared_blocking_gate_files(
                f"{_REAL_DECLARATION_LINE}\n{_REAL_DECLARATION_LINE}\n"
            )

    def test_a_declaration_naming_no_files_is_an_error(self) -> None:
        """A command line stripped of its arguments guards nothing, loudly."""
        with pytest.raises(AssertionError, match="no test files"):
            parse_declared_blocking_gate_files('"$PY" -m pytest tests/acceptance/ -v\n')

    def test_the_parser_reads_the_names_off_the_command_line(self) -> None:
        assert parse_declared_blocking_gate_files(_REAL_DECLARATION_LINE) == (
            "test_alpha.py",
            "test_beta.py",
        )


class TestTheGuardKnowsWhichFilesItCovers:
    """Guarding too much is as wrong as guarding too little."""

    def test_every_declared_file_is_guarded(self) -> None:
        for name in declared_blocking_gate_files():
            assert skip_is_an_abort_condition(ACCEPTANCE_DIR / name)

    def test_an_undeclared_acceptance_file_is_not_guarded(self) -> None:
        """`test_transport_toggle_cycle.py` skips 11 times when the relay binary
        is not built. That is a real provisioning gap, tracked separately — but
        the file is not in the blocking set, so this guard must leave it alone.
        """
        undeclared = ACCEPTANCE_DIR / "test_transport_toggle_cycle.py"
        assert undeclared.is_file(), "fixture premise: the file still exists"
        assert undeclared.name not in declared_blocking_gate_files()
        assert not skip_is_an_abort_condition(undeclared)


class TestTheFailureMessageIsActionable:
    """A developer without `uv` gets a failure now; it must say why."""

    def test_the_message_names_the_file_the_declaration_and_the_reason(self) -> None:
        message = blocking_gate_skip_failure_message(
            ACCEPTANCE_DIR / "test_playbook_harness.py", "uv not installed"
        )
        assert "test_playbook_harness.py" in message
        assert "RELEASING.md" in message
        assert "Step 12.0" in message
        assert "uv not installed" in message


class TestASkipInADeclaredGateBecomesAFailure:
    """The conversion actually fires — proven by a real nested pytest run.

    Everything above tests pure functions. Without this, the guard could be
    perfectly correct and still never be reached, which is exactly the defect
    Plan 00250 exists to fix.
    """

    @staticmethod
    def _run_nested_pytest(tmp_path: Path) -> subprocess.CompletedProcess[str]:
        declared_name = declared_blocking_gate_files()[0]

        (tmp_path / "conftest.py").write_text(
            textwrap.dedent(f"""
                import sys

                sys.path.insert(0, {str(REPO_ROOT)!r})

                from tests.acceptance.blocking_gate_guard import (
                    pytest_runtest_makereport,
                )

                __all__ = ["pytest_runtest_makereport"]
                """).lstrip(),
            encoding="utf-8",
        )

        skipping_test = textwrap.dedent("""
            import pytest


            def test_needs_a_daemon():
                pytest.skip("Daemon not running")
            """).lstrip()
        (tmp_path / declared_name).write_text(skipping_test, encoding="utf-8")
        (tmp_path / "test_not_declared.py").write_text(skipping_test, encoding="utf-8")

        return subprocess.run(  # nosec B603 - trusted interpreter, list form
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                f"--rootdir={tmp_path}",
                "-rs",
                str(tmp_path),
            ],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_the_declared_gate_fails_and_the_undeclared_one_still_skips(
        self, tmp_path: Path
    ) -> None:
        result = self._run_nested_pytest(tmp_path)

        assert result.returncode != 0, (
            "a skip of a declared-blocking gate must fail the run\n"
            f"{result.stdout}\n{result.stderr}"
        )
        assert "1 failed" in result.stdout
        assert "1 skipped" in result.stdout
        assert declared_blocking_gate_files()[0] in result.stdout
        assert "Step 12.0" in result.stdout
        assert "Daemon not running" in result.stdout

    def test_the_guard_reports_against_the_real_releasing_md(self) -> None:
        """The nested run reads the same declaration this repo ships."""
        assert RELEASING_MD.is_file()
        assert RELEASING_MD.is_relative_to(REPO_ROOT)
