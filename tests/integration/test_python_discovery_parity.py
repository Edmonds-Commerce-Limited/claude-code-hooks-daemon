"""Plan 00110 Phase 6 Tasks 6.1+6.2 — bash↔python parity tests.

The bash helper (``scripts/lib/python_discovery.sh::find_latest_python``)
and the python helper (``daemon/paths.py::find_latest_python``) MUST
return the same interpreter for the same ``$PATH`` layout. Plan 00110
made them independent on purpose (the bash helper runs during skill
bootstrap BEFORE any python is guaranteed to be installed), so we need
a parity test to catch any drift between the two.

This module:

  1. Loads curated fixtures from ``tests/fixtures/python_discovery/*.json``
     (Task 6.1). Each fixture pins one interesting case: host-a
     baseline, only-old-python failure, double-digit-minor numeric sort,
     exact-floor match, etc.

  2. Generates 50 randomised fixtures (Task 6.2) covering arbitrary
     ``$PATH`` layouts with random interpreter sets and random floors.

For every fixture, the test:

  - Builds a fake ``$PATH`` directory with shell-script interpreters
    that print ``Python X.Y.Z`` to ``--version``.
  - Invokes both helpers against that PATH.
  - Asserts they agree: same selected interpreter, or both fail.

Drift in either implementation breaks parity and fails the test —
exactly the regression class Plan 00110 set out to prevent.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "python_discovery"
BASH_HELPER = REPO_ROOT / "scripts" / "lib" / "python_discovery.sh"
BASH = shutil.which("bash") or "/bin/bash"

_FAKE_PYTHON_TEMPLATE = """\
#!/bin/sh
case "$1" in
    --version) echo "Python {version}" ;;
    -c) shift; eval "echo 'Python {version}'" ;;
    *) echo "Python {version}" ;;
esac
"""


@dataclass(frozen=True)
class Fixture:
    """A PATH layout + floor + expected outcome.

    ``interpreters`` is a list of ``(command_name, version_string)`` pairs.
    ``floor`` is ``(major, minor)``. ``expected_outcome`` is "selected"
    or "failed"; ``expected_interpreter_name`` is the basename of the
    chosen interpreter when outcome is "selected".
    """

    name: str
    interpreters: tuple[tuple[str, str], ...]
    floor: tuple[int, int]
    expected_outcome: str
    expected_interpreter_name: str | None

    @classmethod
    def from_json(cls, path: Path) -> Fixture:
        data = json.loads(path.read_text())
        return cls(
            name=data["name"],
            interpreters=tuple((entry["name"], entry["version"]) for entry in data["interpreters"]),
            floor=(data["floor"][0], data["floor"][1]),
            expected_outcome=data["expected"]["outcome"],
            expected_interpreter_name=data["expected"].get("interpreter_name"),
        )


def _materialise_fixture(fixture: Fixture, bin_dir: Path) -> None:
    """Create fake interpreter shell scripts in ``bin_dir`` from a fixture."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, version in fixture.interpreters:
        path = bin_dir / name
        path.write_text(_FAKE_PYTHON_TEMPLATE.format(version=version))
        path.chmod(0o755)


def _invoke_bash_helper(bin_dir: Path, floor: tuple[int, int]) -> tuple[int, str, str]:
    """Source the bash helper in a clean subshell with PATH=$bin_dir and
    invoke ``find_latest_python <floor>``. Returns (exit_code, stdout, stderr).
    """
    env = {
        "PATH": str(bin_dir),
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    floor_arg = f"{floor[0]}.{floor[1]}"
    script = f'set -u; . "{BASH_HELPER}"; find_latest_python "{floor_arg}"'
    result = subprocess.run(
        [BASH, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=Timeout.LINT_CHECK,
    )
    return result.returncode, result.stdout.strip(), result.stderr


def _invoke_python_helper(
    bin_dir: Path, floor: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> Path | None:
    """Invoke ``daemon.paths.find_latest_python`` with PATH monkeypatched
    to ``bin_dir`` only. Returns the chosen Path, or None on failure.
    """
    # Import lazily so the test module loads even if paths.py is being
    # edited mid-development (no parity test until the helper exists).
    from claude_code_hooks_daemon.daemon import paths as paths_mod

    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.delenv("HOOKS_DAEMON_PYTHON", raising=False)
    return paths_mod.find_latest_python(floor)


def _assert_parity(fixture: Fixture, bin_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run both helpers against the fixture and assert they agree."""
    _materialise_fixture(fixture, bin_dir)

    bash_rc, bash_stdout, bash_stderr = _invoke_bash_helper(bin_dir, fixture.floor)
    py_result = _invoke_python_helper(bin_dir, fixture.floor, monkeypatch)

    bash_succeeded = bash_rc == 0 and bash_stdout != ""
    py_succeeded = py_result is not None

    # Outcome agreement is the primary invariant — both must succeed or
    # both must fail. Drift in EITHER direction is a parity bug.
    assert bash_succeeded == py_succeeded, (
        f"Fixture {fixture.name!r}: bash and python disagreed on outcome. "
        f"bash succeeded={bash_succeeded} (rc={bash_rc}, stdout={bash_stdout!r}, "
        f"stderr={bash_stderr!r}); python succeeded={py_succeeded} (result={py_result!r})."
    )

    if bash_succeeded:
        # Both picked SOME interpreter — must be the SAME interpreter.
        assert py_result is not None  # type-narrow
        bash_name = Path(bash_stdout).name
        py_name = py_result.name
        assert bash_name == py_name, (
            f"Fixture {fixture.name!r}: bash picked {bash_name!r} but "
            f"python picked {py_name!r}. Both should have agreed."
        )
        # Cross-check against the fixture's expected interpreter when given.
        if fixture.expected_interpreter_name is not None:
            assert bash_name == fixture.expected_interpreter_name, (
                f"Fixture {fixture.name!r}: expected {fixture.expected_interpreter_name!r}, "
                f"both helpers picked {bash_name!r} — fixture and helpers agree but the "
                f"fixture's expected value is wrong (or both helpers have the same bug)."
            )
    else:
        # Both failed — when the fixture expected failure, that's a pass.
        # When the fixture expected success but both failed, that's a
        # fixture bug (or both helpers have the same regression).
        if fixture.expected_outcome == "selected":
            pytest.fail(
                f"Fixture {fixture.name!r}: expected outcome 'selected' "
                f"({fixture.expected_interpreter_name!r}) but both helpers failed. "
                f"bash stderr: {bash_stderr!r}"
            )


# ---------------------------------------------------------------------------
# Task 6.1 — curated fixtures
# ---------------------------------------------------------------------------


_CURATED_FIXTURE_FILES = sorted(FIXTURES_DIR.glob("*.json"))


@pytest.mark.parametrize(
    "fixture_path",
    _CURATED_FIXTURE_FILES,
    ids=[p.stem for p in _CURATED_FIXTURE_FILES],
)
def test_curated_fixture_parity(
    fixture_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """For each curated fixture in tests/fixtures/python_discovery/, the
    bash and python implementations of find_latest_python MUST agree.
    """
    fixture = Fixture.from_json(fixture_path)
    bin_dir = tmp_path / "bin"
    _assert_parity(fixture, bin_dir, monkeypatch)


# ---------------------------------------------------------------------------
# Task 6.2 — 50 randomised fixtures (parity property test)
# ---------------------------------------------------------------------------


_PROPERTY_RUN_COUNT = 50
_RANDOM_SEED = 20260526  # deterministic — change to find new failures
# Pool of possible interpreter command names. The python3 (no .N) entry
# is intentionally NOT in the pool — it never participates in discovery,
# and including it would only test that both helpers ignore it (already
# covered by no_python_nn_at_all.json curated fixture).
_INTERPRETER_POOL = (
    "python3.9",
    "python3.10",
    "python3.11",
    "python3.12",
    "python3.13",
    "python3.14",
    "python3.15",
)
_VERSION_PATCH_RANGE = (0, 25)  # version "X.Y.Z" — random Z


def _generate_random_fixture(rng: random.Random, index: int) -> Fixture:
    """Build one randomised fixture. The interpreter set is a random
    non-empty subset of _INTERPRETER_POOL; each chosen interpreter
    reports its expected minor with a random patch level. Floor is a
    random (3, M) with M in [10, 16] so some fixtures fall entirely
    below the floor (testing the failure branch).
    """
    chosen_count = rng.randint(1, len(_INTERPRETER_POOL))
    chosen = rng.sample(_INTERPRETER_POOL, chosen_count)
    interpreters: list[tuple[str, str]] = []
    for name in chosen:
        # name is "python3.N"; parse the minor to build a matching version
        minor = int(name.split(".")[-1])
        patch = rng.randint(*_VERSION_PATCH_RANGE)
        version = f"3.{minor}.{patch}"
        interpreters.append((name, version))
    floor_minor = rng.randint(10, 16)
    # Derive expected outcome from the fixture so the test asserts
    # against ground truth, not the helper's behaviour.
    eligible = [
        (name, version) for name, version in interpreters if int(name.split(".")[-1]) >= floor_minor
    ]
    if eligible:
        # Highest minor wins (numeric sort, not string sort)
        winner = max(eligible, key=lambda nv: int(nv[0].split(".")[-1]))
        expected_outcome = "selected"
        expected_interpreter_name = winner[0]
    else:
        expected_outcome = "failed"
        expected_interpreter_name = None
    return Fixture(
        name=f"random-{index:02d}-{chosen_count}interps-floor3.{floor_minor}",
        interpreters=tuple(interpreters),
        floor=(3, floor_minor),
        expected_outcome=expected_outcome,
        expected_interpreter_name=expected_interpreter_name,
    )


def _generate_property_fixtures() -> list[Fixture]:
    rng = random.Random(_RANDOM_SEED)
    return [_generate_random_fixture(rng, i) for i in range(_PROPERTY_RUN_COUNT)]


_PROPERTY_FIXTURES = _generate_property_fixtures()


@pytest.mark.parametrize(
    "fixture",
    _PROPERTY_FIXTURES,
    ids=[f.name for f in _PROPERTY_FIXTURES],
)
def test_random_fixture_parity(
    fixture: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """50 randomised PATH layouts. Bash and python helpers MUST agree
    on outcome (both succeed → same interpreter; or both fail).
    """
    bin_dir = tmp_path / "bin"
    _assert_parity(fixture, bin_dir, monkeypatch)


# ---------------------------------------------------------------------------
# Sanity guards on the fixture corpus itself
# ---------------------------------------------------------------------------


def test_curated_fixtures_exist() -> None:
    """The fixtures directory must contain at least the curated set
    Plan 00110 Task 6.1 calls out. If a contributor accidentally deletes
    a fixture file the parity coverage silently shrinks — this guard
    surfaces that.
    """
    assert FIXTURES_DIR.is_dir(), f"Missing fixtures directory: {FIXTURES_DIR}"
    json_files = list(FIXTURES_DIR.glob("*.json"))
    assert len(json_files) >= 6, (
        f"Expected at least 6 curated fixtures in {FIXTURES_DIR}, "
        f"found {len(json_files)}. Plan 00110 Task 6.1 must regenerate "
        f"the curated set."
    )


def test_property_run_count_meets_plan_quota() -> None:
    """Plan 00110 Task 6.2 specifies 50 randomised fixtures. Guard
    against accidental lowering.
    """
    assert len(_PROPERTY_FIXTURES) == _PROPERTY_RUN_COUNT
    assert _PROPERTY_RUN_COUNT >= 50, (
        f"Plan 00110 Task 6.2 requires at least 50 random fixtures, "
        f"_PROPERTY_RUN_COUNT={_PROPERTY_RUN_COUNT}"
    )
