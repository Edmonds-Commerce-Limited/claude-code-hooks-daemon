"""The venv that runs QA must be verified against ``uv.lock`` (Plan 00346 T2.1).

``run_dependency_check.sh`` already gates the lockfile's *freshness* with
``uv lock --check``, which proves ``uv.lock`` agrees with ``pyproject.toml``.
Nothing proved the INSTALLED packages agree with ``uv.lock`` — and that is the
gap the whole plan came out of: ``install_deps`` resolved ``pyproject.toml``
against PyPI, so the lock could be perfectly fresh while the venv running the
tests was off-lock by a whole major version of mypy, and every gate stayed
green.

Task 1.1 removed the way that venv got built. This is the check that notices if
it comes back — by a hand-run ``pip install``, a venv predating the fix, or a
future provisioning path nobody thought to audit.

**The negative case is the whole test.** A gate that only ever runs against a
matching environment passes whether or not it works, so the assertions below
drive a venv that genuinely does not match the lock and require a failure. The
positive case needs no test here: ``run_dependency_check.sh`` calls this on
every QA run, so a green suite is itself the passing assertion.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
VENV_INCLUDE: Final[Path] = REPO_ROOT / "scripts" / "venv-include.bash"

#: `uv sync --check` never installs, so the cost here is a venv creation.
_TIMEOUT_SECONDS: Final[int] = 180


def _make_bare_venv(path: Path) -> Path:
    """A real, empty venv — the cheapest environment that cannot match the lock.

    ``--without-pip`` keeps it fast; the function under test never uses pip, and
    ``uv`` only needs a real interpreter and ``pyvenv.cfg`` to inspect what is
    installed.
    """
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(path)],
        check=True,
        capture_output=True,
        timeout=_TIMEOUT_SECONDS,
    )
    return path


def _run(
    venv_dir: Path, *, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Source the real script against the REAL project and call the function.

    Deliberately not a fake project tree: the point is to check an environment
    against this repository's actual ``uv.lock``, so ``PROJECT_ROOT`` must be
    the real checkout.
    """
    env = os.environ.copy()
    env["HOOKS_DAEMON_VENV_PATH"] = str(venv_dir)
    env["HOOKS_DAEMON_PYTHON"] = sys.executable
    env.update(extra_env or {})

    script = f'source "{VENV_INCLUDE}" >/dev/null 2>&1\nassert_venv_matches_lock\n'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


class TestTheFixtureIsNotVacuous:
    def test_the_bare_venv_is_the_one_checked(self, tmp_path: Path) -> None:
        """Without this, a resolution failure would check the REAL venv.

        That venv does match the lock, so every "it fails on drift" assertion
        below would invert into a false pass.
        """
        venv_dir = _make_bare_venv(tmp_path / "bare")
        env = os.environ.copy()
        env["HOOKS_DAEMON_VENV_PATH"] = str(venv_dir)
        env["HOOKS_DAEMON_PYTHON"] = sys.executable

        result = subprocess.run(
            ["bash", "-c", f'source "{VENV_INCLUDE}" >/dev/null 2>&1; echo "$VENV_DIR"'],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
            timeout=_TIMEOUT_SECONDS,
            check=True,
        )
        assert result.stdout.strip() == str(venv_dir), (
            "the bare venv was not the resolved one, so these tests would be "
            f"checking something else: {result.stdout!r}"
        )


class TestTheGateCatchesDrift:
    def test_a_venv_that_does_not_match_the_lock_fails(self, tmp_path: Path) -> None:
        """The defect in one line: an off-lock venv used to sail through.

        The second assertion is not decoration. A non-zero exit is also what an
        absent function returns (127, ``command not found``), so exit-code-only
        would have passed against no implementation at all — which is exactly
        how it behaved on the RED run.
        """
        result = _run(_make_bare_venv(tmp_path / "bare"))
        combined = result.stdout + result.stderr

        assert result.returncode != 0, (
            "an empty venv was accepted as matching uv.lock, so the check "
            f"cannot detect a toolchain that drifts. stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
        assert "uv.lock" in combined, (
            "the run failed, but not with the gate's own verdict — so this "
            f"asserts nothing about the check: {combined!r}"
        )

    def test_the_failure_says_what_to_run(self, tmp_path: Path) -> None:
        """A gate nobody can act on gets disabled, so the remedy is part of it."""
        result = _run(_make_bare_venv(tmp_path / "bare"))

        combined = result.stdout + result.stderr
        assert (
            "uv sync" in combined
        ), f"the failure does not name the command that fixes it: {combined!r}"

    def test_the_failure_shows_what_differs(self, tmp_path: Path) -> None:
        """uv names the packages and both versions; passing that through is the
        difference between a usable report and 'something is wrong'.

        Separate from the remedy test because they fail independently — a
        message could name ``uv sync`` while swallowing uv's own diff.
        """
        result = _run(_make_bare_venv(tmp_path / "bare"))

        combined = result.stdout + result.stderr
        assert "Would install" in combined, (
            "uv's own account of the difference was swallowed, leaving the "
            f"operator to work out what drifted: {combined!r}"
        )


class TestTheDeliberateOptOutIsHonoured:
    def test_the_unlocked_opt_out_skips_the_check(self, tmp_path: Path) -> None:
        """``HOOKS_DAEMON_ALLOW_UNLOCKED_VENV=1`` is what lets ``install_deps``
        build an off-lock venv on purpose when uv is unavailable.

        Failing that venv here would make the opt-out useless — it would build
        an environment that QA then refuses to run in.
        """
        result = _run(
            _make_bare_venv(tmp_path / "bare"),
            extra_env={"HOOKS_DAEMON_ALLOW_UNLOCKED_VENV": "1"},
        )

        assert result.returncode == 0, (
            "the deliberate off-lock opt-out was rejected, so setting it "
            f"produces a venv QA will not accept. stderr={result.stderr!r}"
        )

    def test_the_skip_is_announced(self, tmp_path: Path) -> None:
        """A skipped safety check that says nothing is how the original bypass
        survived; this one has to be visible."""
        result = _run(
            _make_bare_venv(tmp_path / "bare"),
            extra_env={"HOOKS_DAEMON_ALLOW_UNLOCKED_VENV": "1"},
        )

        combined = result.stdout + result.stderr
        assert (
            "HOOKS_DAEMON_ALLOW_UNLOCKED_VENV" in combined
        ), f"the check was skipped silently: {combined!r}"


class TestWithoutUv:
    def test_a_missing_uv_warns_rather_than_failing(self, tmp_path: Path) -> None:
        """Without uv there is no way to perform the comparison at all.

        Emptying ``PATH`` AFTER sourcing is deliberate: venv resolution shells
        out, so a stripped PATH during sourcing breaks it and the test would
        measure the wrong failure. ``echo`` is a bash builtin, so the branch
        under test still runs.
        """
        venv_dir = _make_bare_venv(tmp_path / "bare")
        env = os.environ.copy()
        env["HOOKS_DAEMON_VENV_PATH"] = str(venv_dir)
        env["HOOKS_DAEMON_PYTHON"] = sys.executable

        script = (
            f'source "{VENV_INCLUDE}" >/dev/null 2>&1\n'
            'export PATH=""\n'
            "assert_venv_matches_lock\n"
        )
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )

        assert result.returncode == 0, (
            "a missing uv failed the gate rather than skipping it, which would "
            f"break every QA run on a machine without uv. stderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert "uv" in combined, f"the skip did not say why: {combined!r}"
