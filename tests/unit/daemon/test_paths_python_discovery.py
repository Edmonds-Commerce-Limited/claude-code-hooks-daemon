"""Phase 3 RED-phase tests for the canonical Python interpreter discovery
helpers in ``daemon/paths.py``.

These mirror the bash helper tests under
``tests/acceptance/test_python_discovery_bash.py`` so behavioural parity is
enforceable in Phase 6. Each test synthesises a fake ``$PATH`` populated with
shell-script "python interpreters" that emit a hard-coded version string when
invoked with ``--version`` — the same fixture strategy as the bash suite.

API under test (Plan 00110 Task 1.2 / Task 3.2):

    find_latest_python(
        min_version: tuple[int, int],
        *,
        require_pyproject: Path | None = None,
    ) -> Path | None

    find_latest_python_or_explain(
        min_version: tuple[int, int],
        *,
        require_pyproject: Path | None = None,
    ) -> tuple[Path | None, list[ProbeResult]]

Both live in ``claude_code_hooks_daemon.daemon.paths``.

Precedence ladder (same as bash):

  1. ``HOOKS_DAEMON_PYTHON`` env var (validated against floor; fails fast
     if below floor — never silently falls back to PATH).
  2. Glob ``$PATH`` for ``python3.[0-9]`` and ``python3.[1-9][0-9]``,
     probe each, sort numerically by minor descending, pick the first
     that meets the floor.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.paths import (
    find_latest_python,
    find_latest_python_or_explain,
)

_FAKE_PYTHON_TEMPLATE = """#!/bin/sh
# Synthetic CPython stand-in. Emits the requested version string to stdout
# (CPython 3.4+ behaviour). Real CPython prints "Python X.Y.Z\\n".
echo "Python {version}"
"""


def _make_fake_python(bin_dir: Path, command_name: str, version: str) -> Path:
    """Create an executable shell-script stand-in for a CPython interpreter."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / command_name
    target.write_text(_FAKE_PYTHON_TEMPLATE.format(version=version))
    current = target.stat().st_mode
    target.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def _isolate_env(monkeypatch: pytest.MonkeyPatch, path_dir: Path) -> None:
    """Set PATH to ``path_dir`` only and clear HOOKS_DAEMON_PYTHON.

    Without isolating PATH the helper would discover the host's real
    pythons and the test would assert against an unpredictable set.
    """
    monkeypatch.setenv("PATH", str(path_dir))
    monkeypatch.delenv("HOOKS_DAEMON_PYTHON", raising=False)


# ----- discovery (rung 2: glob $PATH) -----


def test_empty_path_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No interpreters anywhere → returns None."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _isolate_env(monkeypatch, bin_dir)
    assert find_latest_python((3, 11)) is None


def test_picks_highest_minor_above_floor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """python3.9, python3.13, python3.14 on PATH, floor 3.11 → picks 3.14."""
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.9", "3.9.21")
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    expected = _make_fake_python(bin_dir, "python3.14", "3.14.0")
    _isolate_env(monkeypatch, bin_dir)

    result = find_latest_python((3, 11))

    assert result == expected, f"expected python3.14 (highest minor above floor), got {result!r}"


def test_below_floor_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only python3.9 present, floor 3.11 → None (no qualifying interpreter)."""
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.9", "3.9.21")
    _isolate_env(monkeypatch, bin_dir)
    assert find_latest_python((3, 11)) is None


def test_picks_double_digit_minor_correctly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """python3.9 vs python3.13 — numeric sort must yield 3.13 > 3.9, not the
    lexical sort that would yield "9" > "1" → 3.9 wrongly.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.9", "3.9.21")
    expected = _make_fake_python(bin_dir, "python3.13", "3.13.11")
    _isolate_env(monkeypatch, bin_dir)

    result = find_latest_python((3, 0))

    assert result == expected, f"numeric sort must rank 3.13 > 3.9, got {result!r}"


def test_non_executable_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A python3.13 file with no exec bit must be ignored (not crash)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    non_exec = bin_dir / "python3.13"
    non_exec.write_text(_FAKE_PYTHON_TEMPLATE.format(version="3.13.11"))
    non_exec.chmod(0o644)
    expected = _make_fake_python(bin_dir, "python3.14", "3.14.0")
    _isolate_env(monkeypatch, bin_dir)

    result = find_latest_python((3, 11))

    assert (
        result == expected
    ), f"non-exec python3.13 must be skipped; expected python3.14, got {result!r}"


def test_glob_does_not_match_python3_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``python3.13-config`` and ``python3.14-x86_64-config`` are not
    interpreters — the glob must reject them and keep only ``python3.<digits>``.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.13-config", "3.13.11")
    _make_fake_python(bin_dir, "python3.14-x86_64-config", "3.14.0")
    expected = _make_fake_python(bin_dir, "python3.13", "3.13.11")
    _isolate_env(monkeypatch, bin_dir)

    result = find_latest_python((3, 11))

    assert result == expected, f"glob must only match python3.<digits>, got {result!r}"


def test_bare_python3_excluded_by_glob(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bare ``python3`` (no minor in the name) is the 'diceroll' case the
    existing prerequisites.sh warns about — must NOT be matched by the glob.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3", "3.9.21")
    expected = _make_fake_python(bin_dir, "python3.13", "3.13.11")
    _isolate_env(monkeypatch, bin_dir)

    result = find_latest_python((3, 11))

    assert result == expected, f"bare 'python3' must not match; expected python3.13, got {result!r}"


def test_host_a_scenario_exactly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replay the exact host-a host layout:
    default python3 → 3.9.21, python3.13 → 3.13.11, python3.14 → 3.14.0,
    plus the python3.11-config and python3.14-x86_64-config noise.

    Expected: auto-selects python3.14, no HOOKS_DAEMON_PYTHON intervention.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3", "3.9.21")
    _make_fake_python(bin_dir, "python3.11-config", "3.11.5")
    _make_fake_python(bin_dir, "python3.11", "3.11.5")
    _make_fake_python(bin_dir, "python3.12", "3.12.7")
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    expected = _make_fake_python(bin_dir, "python3.14", "3.14.0")
    _make_fake_python(bin_dir, "python3.14-x86_64-config", "3.14.0")
    _isolate_env(monkeypatch, bin_dir)

    result = find_latest_python((3, 11))

    assert result == expected, f"host-a replay must auto-select python3.14, got {result!r}"


# ----- HOOKS_DAEMON_PYTHON precedence (rung 1) -----


def test_env_override_wins_when_satisfies_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HOOKS_DAEMON_PYTHON=python3.13 wins even when python3.14 is on PATH."""
    bin_dir = tmp_path / "bin"
    p13 = _make_fake_python(bin_dir, "python3.13", "3.13.11")
    _make_fake_python(bin_dir, "python3.14", "3.14.0")
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("HOOKS_DAEMON_PYTHON", str(p13))

    result = find_latest_python((3, 11))

    assert result == p13, f"HOOKS_DAEMON_PYTHON must outrank glob discovery, got {result!r}"


def test_env_override_violating_floor_fails_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HOOKS_DAEMON_PYTHON=python3.9 with floor 3.11 must FAIL FAST — never
    silently fall back to PATH discovery (would mask the broken operator
    configuration).
    """
    bin_dir = tmp_path / "bin"
    p9 = _make_fake_python(bin_dir, "python3.9", "3.9.21")
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("HOOKS_DAEMON_PYTHON", str(p9))

    result = find_latest_python((3, 11))

    assert result is None, (
        "env override below floor MUST fail (return None), not silently "
        f"fall back to python3.13. Got {result!r}"
    )


def test_env_override_unusable_fails_fast(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """HOOKS_DAEMON_PYTHON pointing at a nonexistent path must fail fast,
    not silently fall back to PATH discovery.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("HOOKS_DAEMON_PYTHON", str(tmp_path / "nowhere"))

    result = find_latest_python((3, 11))

    assert result is None, (
        "unresolvable HOOKS_DAEMON_PYTHON MUST fail (return None), not "
        f"silently fall back. Got {result!r}"
    )


# ----- pyproject.toml requires-python integration -----


def test_pyproject_requires_python_overrides_lower_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``requires-python = '>=3.13'`` in pyproject overrides a 3.11 floor arg
    upward (never downward).
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.11", "3.11.5")
    expected = _make_fake_python(bin_dir, "python3.13", "3.13.11")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nrequires-python = ">=3.13"\n')
    _isolate_env(monkeypatch, bin_dir)

    result = find_latest_python((3, 11), require_pyproject=pyproject)

    assert result == expected, f"pyproject must lift floor 3.11 → 3.13, got {result!r}"


def test_pyproject_requires_python_never_lowers_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``requires-python = '>=3.10'`` in pyproject must NOT lower a 3.13
    floor arg — the caller's floor is the minimum acceptable.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.11", "3.11.5")
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\nrequires-python = ">=3.10"\n')
    _isolate_env(monkeypatch, bin_dir)

    result = find_latest_python((3, 13), require_pyproject=pyproject)

    assert result is not None
    assert (
        result.name == "python3.13"
    ), f"caller floor 3.13 must hold even when pyproject says 3.10; got {result!r}"


# ----- find_latest_python_or_explain (diagnostics) -----


def test_explain_returns_probe_list_when_below_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``find_latest_python_or_explain`` returns (None, [ProbeResult,...])
    when no interpreter meets the floor — listing every interpreter
    OBSERVED during discovery so the caller can name them in error output.

    This is the host-a trap closer: never suggest a hardcoded version
    that may not exist on the host. Caller composes the diagnostic from
    real observations.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.9", "3.9.21")
    _isolate_env(monkeypatch, bin_dir)

    chosen, probes = find_latest_python_or_explain((3, 11))

    assert chosen is None
    assert any(
        "3.9" in p.version_full for p in probes
    ), f"probes must include observed python3.9, got {probes!r}"


def test_explain_returns_chosen_with_probes_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On success the diagnostic helper returns the chosen path AND the
    probe results (so callers can log the full discovery audit trail).
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.9", "3.9.21")
    expected = _make_fake_python(bin_dir, "python3.13", "3.13.11")
    _isolate_env(monkeypatch, bin_dir)

    chosen, probes = find_latest_python_or_explain((3, 11))

    assert chosen == expected
    versions_seen = sorted(p.version_full for p in probes)
    assert versions_seen == [
        "3.13.11",
        "3.9.21",
    ], f"probes must record every observed interpreter, got {versions_seen!r}"


def test_probe_result_carries_interpreter_path_and_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ProbeResult`` must expose the absolute path of the probed binary
    AND its reported version — both are needed for diagnostic output.
    """
    bin_dir = tmp_path / "bin"
    p13 = _make_fake_python(bin_dir, "python3.13", "3.13.11")
    _isolate_env(monkeypatch, bin_dir)

    _, probes = find_latest_python_or_explain((3, 11))

    assert len(probes) == 1
    probe = probes[0]
    assert probe.path == p13
    assert probe.version_full == "3.13.11"
    assert probe.major_minor == (3, 13)


# ----- PATHEXT / pathsep handling -----


def test_walks_multiple_path_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Helper must traverse every entry in PATH, not just the first."""
    bin_a = tmp_path / "a" / "bin"
    bin_b = tmp_path / "b" / "bin"
    _make_fake_python(bin_a, "python3.11", "3.11.5")
    expected = _make_fake_python(bin_b, "python3.14", "3.14.0")
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_a), str(bin_b)]))
    monkeypatch.delenv("HOOKS_DAEMON_PYTHON", raising=False)

    result = find_latest_python((3, 11))

    assert result == expected, f"helper must scan all PATH entries, got {result!r}"


def test_deduplicates_same_binary_on_multiple_path_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same bin dir appearing twice in PATH must not be probed twice
    (avoids spurious duplicates in the probe list).
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.13", "3.13.11")
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), str(bin_dir)]))
    monkeypatch.delenv("HOOKS_DAEMON_PYTHON", raising=False)

    _, probes = find_latest_python_or_explain((3, 11))

    assert len(probes) == 1, f"duplicate PATH entries must dedupe to one probe, got {probes!r}"
