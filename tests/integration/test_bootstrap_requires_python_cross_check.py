"""Plan 00104 Phase 7 Task 7.2 — bootstrap requires-python cross-check (closed Phase 3 Task 3.6).

PLAN.md Task 7.2: bootstrap probe rejects an interpreter that satisfies
the hardcoded ``>=3.11`` floor but violates the daemon's actual
``pyproject.toml::requires-python`` constraint.

Without this cross-check, ``scripts/upgrade.sh::find_compatible_python``
checked only the hardcoded floor via ``_is_python_at_least_311``. If the
daemon's ``pyproject.toml`` said ``requires-python = ">=3.13"`` and the
operator had only Python 3.11 on PATH, the probe happily selected 3.11
and the daemon exploded deep in the call stack with a confusing
``SyntaxError`` from a 3.13-only language feature. The contract Phase 7
Task 7.2 landed:

    find_compatible_python <daemon_dir>

When ``<daemon_dir>/pyproject.toml`` exists and parses, the probe parses
the ``requires-python`` lower bound and rejects any candidate whose
``--version`` falls below it — even if it satisfies the hardcoded 3.11
floor. The error is actionable: stderr names the
``requires-python`` constraint and the lower bound version so the
operator can install the right interpreter.

The test plants a fake ``python3.11`` on PATH and a fixture
``pyproject.toml`` with ``requires-python = ">=3.99"`` (an impossible
ceiling that no real interpreter can satisfy). The probe fails
non-zero AND the stderr directive mentions ``requires-python`` AND
``3.99``.

The smoke test pins the inverse — ``requires-python = ">=3.11"`` plus a
3.11 fake on PATH — to ensure the cross-check is constraint-aware (only
fires when the candidate is below the bound) rather than always
rejecting.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UPGRADE_SCRIPT = REPO_ROOT / "scripts" / "upgrade.sh"
BASH = shutil.which("bash") or "/bin/bash"

IMPOSSIBLE_REQUIRES_PYTHON = ">=3.99"
IMPOSSIBLE_MIN_TOKEN = "3.99"
SATISFIABLE_REQUIRES_PYTHON = ">=3.11"

_HELPER_STUBS = textwrap.dedent("""\
    #!/usr/bin/env bash
    set -uo pipefail
    _ok()   { echo "OK $1"; }
    _err()  { echo "ERR $1" >&2; }
    _fail() { _err "$1"; exit 1; }

    """)


def _extract_probe_function(tmp_path: Path) -> Path:
    """Extract ``find_compatible_python`` + ``_is_python_at_least_311`` to a sourceable file.

    Mirrors the extraction logic in
    ``tests/integration/test_bootstrap_explicit_probe.py`` so the two
    tests stay in lock-step on probe-extraction conventions. Phase 4
    will move both into the canonical library; until then, sourcing the
    function bodies in isolation is the only way to exercise the probe
    without triggering upgrade.sh's main-body git operations.
    """
    text = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    lines = text.splitlines()

    def _slice_function(name: str) -> str:
        start: int | None = None
        end: int | None = None
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{name}()"):
                start = index
                continue
            if start is not None and stripped == "}":
                end = index
                break
        assert start is not None and end is not None, (
            f"could not locate {name}() in scripts/upgrade.sh — if the function "
            f"was renamed or moved, update the extraction logic"
        )
        return "\n".join(lines[start : end + 1])

    helper_body = _slice_function("_is_python_at_least_311")
    func_body = _slice_function("find_compatible_python")

    sourceable = tmp_path / "probe_func.sh"
    sourceable.write_text(
        _HELPER_STUBS + helper_body + "\n\n" + func_body + "\n",
        encoding="utf-8",
    )
    sourceable.chmod(0o755)
    return sourceable


def _make_fake_python(bin_dir: Path, name: str, major: int, minor: int) -> Path:
    """Create a fake ``python3.N`` that responds to ``--version`` and ``-c``.

    Identical contract to the helper in ``test_bootstrap_explicit_probe.py``
    — duplicated rather than imported so the two test modules can evolve
    independently if either probe's contract changes.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / name
    is_compatible = major > 3 or (major == 3 and minor >= 11)
    version_check_exit = 0 if is_compatible else 1
    script.write_text(
        textwrap.dedent(f"""\
            #!{BASH}
            case "$1" in
                --version)
                    echo "Python {major}.{minor}.0"
                    exit 0
                    ;;
                -c)
                    exit {version_check_exit}
                    ;;
                *)
                    exit 0
                    ;;
            esac
            """),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _write_pyproject(daemon_dir: Path, requires_python: str) -> Path:
    """Plant a minimal ``pyproject.toml`` carrying just ``requires-python``.

    The probe only needs to parse the ``[project]`` table's
    ``requires-python`` key — everything else (name, version,
    dependencies) is irrelevant to the cross-check. Keeping the fixture
    minimal pins the test to the contract and not to incidental TOML
    structure.
    """
    daemon_dir.mkdir(parents=True, exist_ok=True)
    pyproject = daemon_dir / "pyproject.toml"
    pyproject.write_text(
        textwrap.dedent(f"""\
            [project]
            name = "test-fixture"
            version = "0.0.0"
            requires-python = "{requires_python}"
            """),
        encoding="utf-8",
    )
    return pyproject


def _run_probe_with_daemon_dir(
    sourceable: Path,
    path_dir: Path,
    daemon_dir: Path,
) -> subprocess.CompletedProcess[str]:
    """Invoke ``find_compatible_python <daemon_dir>`` under a controlled PATH.

    The positional-arg form pins the contract Phase 7 Task 7.2 ships:
    the probe accepts ``<daemon_dir>`` as ``$1`` and, when that
    directory contains a parseable ``pyproject.toml``, cross-checks
    every candidate's ``--version`` against the parsed
    ``requires-python`` lower bound.
    """
    env: dict[str, str] = {
        "PATH": str(path_dir),
        "HOME": str(path_dir.parent),
    }
    cmd = [
        BASH,
        "-c",
        (
            f'source "{sourceable}" && '
            f'find_compatible_python "{daemon_dir}" && '
            f'echo "RESULT=$HOOKS_DAEMON_PYTHON"'
        ),
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_smoke_probe_succeeds_when_pyproject_satisfiable(tmp_path: Path) -> None:
    """Sanity check: ``requires-python = ">=3.11"`` + 3.11 fake on PATH → succeeds.

    Pins the baseline so the xfail below isn't masked by an unrelated
    probe regression. If THIS test fails, the extraction or fake-python
    helper is broken — fix that first, then re-evaluate the xfail.
    """
    sourceable = _extract_probe_function(tmp_path)
    path_dir = tmp_path / "bin"
    _make_fake_python(path_dir, "python3.11", 3, 11)
    daemon_dir = tmp_path / "daemon"
    _write_pyproject(daemon_dir, SATISFIABLE_REQUIRES_PYTHON)

    result = _run_probe_with_daemon_dir(sourceable, path_dir, daemon_dir)

    assert result.returncode == 0, (
        f"baseline probe must succeed with satisfiable requires-python.\n"
        f"returncode={result.returncode}\nstdout={result.stdout!r}\n"
        f"stderr={result.stderr!r}"
    )
    assert "RESULT=" in result.stdout, (
        "probe must export HOOKS_DAEMON_PYTHON on success.\n" f"stdout={result.stdout!r}"
    )


def test_probe_rejects_candidate_below_pyproject_requires_python(tmp_path: Path) -> None:
    """3.11 fake on PATH + pyproject says ``>=3.99`` → probe must reject.

    The fake interpreter satisfies the hardcoded ``>=3.11`` floor but
    violates ``pyproject.toml::requires-python = ">=3.99"`` (an
    impossible ceiling). Phase 7 Task 7.2 contract: stderr must mention
    ``requires-python`` AND the impossible token (``3.99``) so the
    operator immediately sees both halves of the mismatch.
    """
    sourceable = _extract_probe_function(tmp_path)
    path_dir = tmp_path / "bin"
    _make_fake_python(path_dir, "python3.11", 3, 11)
    daemon_dir = tmp_path / "daemon"
    _write_pyproject(daemon_dir, IMPOSSIBLE_REQUIRES_PYTHON)

    result = _run_probe_with_daemon_dir(sourceable, path_dir, daemon_dir)

    assert result.returncode != 0, (
        "probe must fail when no candidate satisfies pyproject's "
        "requires-python — even if every candidate clears the hardcoded "
        "3.11 floor.\n"
        f"returncode={result.returncode}\nstdout={result.stdout!r}\n"
        f"stderr={result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "requires-python" in combined, (
        "stderr must cite the requires-python constraint so the operator "
        "knows which contract is being violated.\n"
        f"output=\n{combined}"
    )
    assert IMPOSSIBLE_MIN_TOKEN in combined, (
        f"stderr must cite the constraint's lower bound ({IMPOSSIBLE_MIN_TOKEN}) "
        "so the operator can compare it against their installed interpreters.\n"
        f"output=\n{combined}"
    )
