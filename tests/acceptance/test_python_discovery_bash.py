"""Plan 00110 Phase 2 Task 2.1 — acceptance tests for the canonical bash
``find_latest_python`` helper.

The bash helper MUST work when no compatible python is yet installed (skill
bootstrap case), so it is a self-contained POSIX shell implementation with no
Python dependency. These tests build fake ``python3.N`` interpreters in a
temp directory, point ``$PATH`` at it, source ``scripts/lib/python_discovery.sh``,
and assert the helper's behaviour.

A fake interpreter is a tiny shell script that prints ``Python X.Y.Z`` to
stdout when invoked with ``--version`` — that is the exact contract the helper
parses, no real CPython needed.

The host-a field report (``untracked/hooks-daemon-upgrade-python-version.md``)
exposed the failure mode these tests pin: when default ``python3`` is too old
but a newer ``python3.N`` is on PATH, the daemon's discovery must auto-find it
without operator intervention. The helper's contract:

    find_latest_python <min_major.min_minor> [pyproject_path]

Echoes the absolute path of the chosen interpreter on stdout (exit 0), or a
remediation hint to stderr (exit 1). Precedence:

  1. ``$HOOKS_DAEMON_PYTHON`` — explicit override, validated, no fallback on failure
  2. Glob ``$PATH`` for ``python3.[1-9][0-9]``, sort by minor descending, pick
     highest that meets the floor (and ``requires-python`` if a pyproject path
     is given)

Failure messages MUST name interpreters observed during the glob — never a
hardcoded version that may not exist on the host (the host-a trap).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "lib" / "python_discovery.sh"
BASH = shutil.which("bash") or "/bin/bash"

_FAKE_PYTHON_TEMPLATE = """\
#!/bin/sh
case "$1" in
    --version) echo "Python {version}" ;;
    -c) shift; eval "echo 'Python {version}'" ;;
    *) echo "Python {version}" ;;
esac
"""


def _make_fake_python(bin_dir: Path, command_name: str, version: str) -> Path:
    """Create a fake interpreter at ``bin_dir/command_name`` that reports
    ``version`` when called with ``--version``.

    The fake is a tiny POSIX shell script — no CPython dependency. Returns
    the absolute path of the created script.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / command_name
    path.write_text(_FAKE_PYTHON_TEMPLATE.format(version=version))
    path.chmod(0o755)
    return path


def _invoke_helper(
    *args: str,
    path_dir: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Source the helper in a clean subshell and invoke
    ``find_latest_python`` with ``args``. PATH is replaced with only
    ``path_dir`` so the test controls every interpreter the helper sees.
    """
    env = {
        "PATH": str(path_dir),
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    if extra_env:
        env.update(extra_env)
    quoted_args = " ".join(f'"{a}"' for a in args)
    script = f'set -u; . "{HELPER}"; find_latest_python {quoted_args}'
    return subprocess.run(
        [BASH, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_helper_file_exists() -> None:
    """The canonical helper file MUST exist at the expected path."""
    assert HELPER.is_file(), (
        f"Canonical bash helper missing: {HELPER}. "
        "Plan 00110 Phase 2 Task 2.2 has not yet been implemented."
    )


def test_empty_path_fails_with_clear_message(tmp_path: Path) -> None:
    """Empty PATH (no python3.N anywhere) → exit 1, stderr mentions absence."""
    empty_bin = tmp_path / "empty_bin"
    empty_bin.mkdir()
    result = _invoke_helper("3.11", path_dir=empty_bin)
    assert (
        result.returncode == 1
    ), f"Expected exit 1, got {result.returncode}. Stdout: {result.stdout!r} Stderr: {result.stderr!r}"
    assert result.stdout.strip() == "", "stdout must be empty on failure"
    combined = result.stderr.lower()
    assert "no" in combined and (
        "python" in combined or "interpreter" in combined
    ), f"stderr must explain no interpreters found, got: {result.stderr!r}"


def test_only_below_floor_fails_naming_observed(tmp_path: Path) -> None:
    """Only python3.9 present, floor 3.11 → fail naming python3.9 explicitly
    (not a hardcoded suggestion like python3.11 which may not exist).
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.9", "3.9.21")
    result = _invoke_helper("3.11", path_dir=bin_dir)
    assert result.returncode == 1
    assert (
        "3.9" in result.stderr
    ), f"stderr must name the observed python3.9 interpreter, got: {result.stderr!r}"


def test_picks_highest_minor_above_floor(tmp_path: Path) -> None:
    """python3.9, python3.13, python3.14 all on PATH, floor 3.11 → picks 3.14."""
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.9", "3.9.21")
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    _make_fake_python(bin_dir, "python3.14", "3.14.0")
    result = _invoke_helper("3.11", path_dir=bin_dir)
    assert (
        result.returncode == 0
    ), f"Expected exit 0, got {result.returncode}. Stderr: {result.stderr!r}"
    chosen = result.stdout.strip()
    assert chosen.endswith(
        "/python3.14"
    ), f"Expected python3.14 (highest minor above floor), got: {chosen!r}"


def test_env_override_wins_when_satisfies_floor(tmp_path: Path) -> None:
    """HOOKS_DAEMON_PYTHON=python3.13 wins even if python3.14 is also present."""
    bin_dir = tmp_path / "bin"
    p13 = _make_fake_python(bin_dir, "python3.13", "3.13.11")
    _make_fake_python(bin_dir, "python3.14", "3.14.0")
    result = _invoke_helper(
        "3.11",
        path_dir=bin_dir,
        extra_env={"HOOKS_DAEMON_PYTHON": str(p13)},
    )
    assert result.returncode == 0, f"Stderr: {result.stderr!r}"
    chosen = result.stdout.strip()
    assert chosen == str(p13), f"Expected env override to win with {p13}, got: {chosen!r}"


def test_env_override_violating_floor_fails_fast(tmp_path: Path) -> None:
    """HOOKS_DAEMON_PYTHON=python3.9, floor 3.11 → fail explicitly, no fallback."""
    bin_dir = tmp_path / "bin"
    p9 = _make_fake_python(bin_dir, "python3.9", "3.9.21")
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    result = _invoke_helper(
        "3.11",
        path_dir=bin_dir,
        extra_env={"HOOKS_DAEMON_PYTHON": str(p9)},
    )
    assert (
        result.returncode == 1
    ), "env override below floor MUST fail fast, not silently fall back to PATH"
    assert (
        "HOOKS_DAEMON_PYTHON" in result.stderr
    ), f"stderr must reference the broken env var, got: {result.stderr!r}"


def test_pyproject_requires_python_overrides_lower_floor(tmp_path: Path) -> None:
    """A pyproject with requires-python = '>=3.13' overrides a 3.11 floor arg.

    python3.11 and python3.13 on PATH, floor arg 3.11, pyproject requires 3.13
    → must pick python3.13 (not python3.11).
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.11", "3.11.5")
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nrequires-python = ">=3.13"\n')
    result = _invoke_helper("3.11", str(pyproject), path_dir=bin_dir)
    assert result.returncode == 0, f"Stderr: {result.stderr!r}"
    chosen = result.stdout.strip()
    assert chosen.endswith(
        "/python3.13"
    ), f"pyproject requires-python = '>=3.13' must override 3.11 arg, got: {chosen!r}"


def test_non_executable_skipped(tmp_path: Path) -> None:
    """A python3.13 file that isn't executable must be ignored, not crash."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    non_exec = bin_dir / "python3.13"
    non_exec.write_text(_FAKE_PYTHON_TEMPLATE.format(version="3.13.11"))
    non_exec.chmod(0o644)
    _make_fake_python(bin_dir, "python3.14", "3.14.0")
    result = _invoke_helper("3.11", path_dir=bin_dir)
    assert result.returncode == 0, f"Stderr: {result.stderr!r}"
    chosen = result.stdout.strip()
    assert chosen.endswith(
        "/python3.14"
    ), f"non-exec python3.13 must be skipped; expected python3.14, got: {chosen!r}"


def test_glob_does_not_match_python3_config(tmp_path: Path) -> None:
    """Glob ``python3.[1-9][0-9]`` must NOT match ``python3.13-config`` or
    ``python3.13-gdb.py`` — those are not interpreters.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.13-config", "3.13.11")
    _make_fake_python(bin_dir, "python3.13-gdb.py", "3.13.11")
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    result = _invoke_helper("3.11", path_dir=bin_dir)
    assert result.returncode == 0, f"Stderr: {result.stderr!r}"
    chosen = result.stdout.strip()
    assert chosen.endswith("/python3.13"), f"glob must only match interpreters, got: {chosen!r}"


def test_single_digit_python_excluded_by_glob(tmp_path: Path) -> None:
    """``python3.9`` MUST be matched (operator confirmed 9 acceptable when in
    PATH); but bare ``python3`` (no minor) MUST NOT be matched — it's the
    'diceroll' case the existing prerequisites.sh comments warn about.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3", "3.9.21")
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    result = _invoke_helper("3.11", path_dir=bin_dir)
    assert result.returncode == 0
    chosen = result.stdout.strip()
    assert chosen.endswith("/python3.13"), (
        "glob must skip bare 'python3' (no minor); expected python3.13, " f"got: {chosen!r}"
    )


def test_picks_double_digit_minor_correctly(tmp_path: Path) -> None:
    """python3.9 < python3.13 in semver. A naïve lexical sort would put 3.9
    AFTER 3.13 (because '9' > '1'). Numeric sort must yield 3.13 > 3.9.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.9", "3.9.21")
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    result = _invoke_helper("3.0", path_dir=bin_dir)
    assert result.returncode == 0
    chosen = result.stdout.strip()
    assert chosen.endswith("/python3.13"), (
        "numeric sort must yield 3.13 > 3.9, not lexical sort which would "
        f"yield 3.9 > 3.13. got: {chosen!r}"
    )


def test_helper_safe_to_source_with_set_u(tmp_path: Path) -> None:
    """The helper must be safe to source under ``set -u`` (callers like
    ``upgrade.sh`` and ``prerequisites.sh`` both run with strict mode).
    No unset-variable references anywhere.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    script = f'set -eu; . "{HELPER}"; find_latest_python 3.11'
    result = subprocess.run(
        [BASH, "-c", script],
        env={"PATH": str(bin_dir), "HOME": os.environ.get("HOME", "/tmp")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        result.returncode == 0
    ), f"helper must run cleanly under set -eu. stderr: {result.stderr!r}"


def test_host_a_scenario_exactly(tmp_path: Path) -> None:
    """Replay the exact host-a layout from the field report:
    default python3 → 3.9.21, python3.13 → 3.13.11, python3.14 → 3.14.0.
    Floor 3.11. No env override.

    Expected behaviour: pick python3.14 cleanly, no operator intervention.
    This is the regression test the host-a operator would have benefited from.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3", "3.9.21")
    _make_fake_python(bin_dir, "python3.11-config", "3.11.5")
    _make_fake_python(bin_dir, "python3.11", "3.11.5")
    _make_fake_python(bin_dir, "python3.12", "3.12.7")
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    _make_fake_python(bin_dir, "python3.14", "3.14.0")
    _make_fake_python(bin_dir, "python3.14-x86_64-config", "3.14.0")
    result = _invoke_helper("3.11", path_dir=bin_dir)
    assert result.returncode == 0, (
        f"host-a replay must succeed without HOOKS_DAEMON_PYTHON. " f"stderr: {result.stderr!r}"
    )
    chosen = result.stdout.strip()
    assert chosen.endswith(
        "/python3.14"
    ), f"host-a replay must auto-select python3.14 (highest), got: {chosen!r}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
