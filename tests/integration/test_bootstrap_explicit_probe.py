r"""Plan 00103 Phase 1 Task 1.5 — bootstrap probe must be explicit and open-ended.

Decision 3 (split, part B — probe-list ban): the bootstrap probe in
``scripts/upgrade.sh::find_compatible_python`` must

 1. **Remove bare ``python3`` from the candidate list.** Bare ``python3`` on the
    user's PATH is a "diceroll" (the user's words) — RHEL/CentOS-default
    ``python3`` is 3.9, container-default is whatever the image picked, etc.
    The probe must only use versioned commands.
 2. **Add open-ended ``compgen -c python3.`` discovery.** So that future
    versions like ``python3.14`` / ``python3.15`` are picked up automatically
    without a code change.
 3. **Honour ``HOOKS_DAEMON_PYTHON`` as an explicit override**, validated
    against the 3.11+ minimum. An invalid override (pointing at <3.11) must
    fail fast — never silently fall back to PATH probing because that would
    mask the user's broken configuration.

Pre-fix structure:

    candidates=("python3" "python3.13" "python3.12" "python3.11")

Bare ``python3`` is probed first; ``HOOKS_DAEMON_PYTHON`` is treated as an
*output* (set after probing succeeds) rather than an *input* (no override
honoured); future versions are not discovered.

Post-fix structure (expected):

    # Honour explicit override, validated.
    if [ -n "${HOOKS_DAEMON_PYTHON:-}" ]; then ...

    # Versioned-only candidates + open-ended discovery via compgen.
    candidates=("python3.13" "python3.12" "python3.11")
    while IFS= read -r cmd; do
        [[ "$cmd" =~ ^python3\.[0-9]+$ ]] && candidates+=("$cmd")
    done < <(compgen -c "python3.")

These tests source the production ``find_compatible_python`` function (after
extracting it from upgrade.sh in isolation, so the main script body does not
run) and exercise it under a controlled PATH containing only fake versioned
interpreters.
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UPGRADE_SCRIPT = REPO_ROOT / "scripts" / "upgrade.sh"
BASH = shutil.which("bash") or "/bin/bash"

_PHASE4_REASON = (
    "Plan 00103 Phase 4 not yet landed — find_compatible_python in "
    "scripts/upgrade.sh still uses bare ``python3`` candidate and ignores "
    "``HOOKS_DAEMON_PYTHON`` as input. Marker is removed as part of the "
    "Phase 4 bootstrap-probe rewrite; strict=True forces the marker to be "
    "removed the moment the fix lands."
)

_HELPER_STUBS = textwrap.dedent("""\
    #!/usr/bin/env bash
    set -uo pipefail
    _ok()   { echo "OK $1"; }
    _err()  { echo "ERR $1" >&2; }
    _fail() { _err "$1"; exit 1; }

    """)


def _extract_probe_function(tmp_path: Path) -> Path:
    """Extract ``find_compatible_python`` to a self-contained sourceable file.

    Reads ``scripts/upgrade.sh``, locates the function definition, writes a
    file with stubbed ``_ok`` / ``_err`` / ``_fail`` helpers and the function
    body. This lets the test source the function in isolation without
    triggering upgrade.sh's main body (which would attempt git operations
    against a non-existent project root).
    """
    text = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = None
    end = None
    for index, line in enumerate(lines):
        if line.strip().startswith("find_compatible_python()"):
            start = index
            continue
        if start is not None and line.strip() == "}":
            end = index
            break
    assert start is not None and end is not None, (
        "could not locate find_compatible_python() in scripts/upgrade.sh — "
        "if the function was renamed or moved, update the extraction logic"
    )
    func_body = "\n".join(lines[start : end + 1])

    sourceable = tmp_path / "probe_func.sh"
    sourceable.write_text(_HELPER_STUBS + func_body + "\n", encoding="utf-8")
    sourceable.chmod(0o755)
    return sourceable


def _make_fake_python(bin_dir: Path, name: str, major: int, minor: int) -> Path:
    """Create a fake ``python3.N`` executable that responds to version probes.

    The probe function calls:

        $candidate -c 'import sys; v=sys.version_info; exit(0 if v >= (3,11) else 1)'
        $candidate --version

    The fake interpreter satisfies both calls without needing a real Python
    installation, so we can simulate "PATH contains python3.14" or "PATH
    contains python3 → 3.9" in CI.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / name
    is_compatible = major > 3 or (major == 3 and minor >= 11)
    version_check_exit = 0 if is_compatible else 1
    # Use absolute shebang so the fake interpreter runs even when the test
    # has set a controlled PATH that does not include /bin or /usr/bin.
    script.write_text(
        textwrap.dedent(f"""\
            #!{BASH}
            case "$1" in
                --version)
                    echo "Python {major}.{minor}.0"
                    exit 0
                    ;;
                -c)
                    # Probe is `import sys; v=...; exit(0 if v >= (3,11) else 1)`
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


def _run_probe(
    sourceable: Path,
    path_dir: Path,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Source the extracted probe function and capture HOOKS_DAEMON_PYTHON.

    The bash subshell echoes ``RESULT=$HOOKS_DAEMON_PYTHON`` after the probe
    returns successfully. Tests parse that line to learn which interpreter
    was selected.
    """
    env: dict[str, str] = {
        "PATH": str(path_dir),
        "HOME": str(path_dir.parent),
    }
    if env_overrides:
        env.update(env_overrides)

    cmd = [
        BASH,
        "-c",
        f'source "{sourceable}" && find_compatible_python && '
        f'echo "RESULT=$HOOKS_DAEMON_PYTHON"',
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _selected_python(stdout: str) -> str:
    """Return the value emitted by ``echo RESULT=$HOOKS_DAEMON_PYTHON`` (or '')."""
    for line in stdout.splitlines():
        if line.startswith("RESULT="):
            return line.split("=", 1)[1]
    return ""


@pytest.mark.xfail(strict=True, reason=_PHASE4_REASON)
def test_bootstrap_probes_versioned_commands_first(tmp_path: Path) -> None:
    """When both ``python3`` and ``python3.13`` exist & both work, prefer versioned.

    Setup: PATH contains ``python3`` (faking 3.13) AND ``python3.13`` (also 3.13).

    Pre-fix: candidate list starts with bare ``python3`` and matches it first.
    HOOKS_DAEMON_PYTHON ends up resolving to ``$path_dir/python3``.

    Post-fix: bare ``python3`` is not in the candidate list. The probe selects
    ``python3.13`` even though ``python3`` is also a valid 3.11+ interpreter.

    The assertion: ``HOOKS_DAEMON_PYTHON`` must end with ``/python3.13``,
    never ``/python3``.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3", 3, 13)
    _make_fake_python(bin_dir, "python3.13", 3, 13)

    sourceable = _extract_probe_function(tmp_path)
    result = _run_probe(sourceable, bin_dir)

    assert result.returncode == 0, (
        f"probe must succeed when versioned interpreter exists. "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
    selected = _selected_python(result.stdout)
    assert selected, f"probe did not export HOOKS_DAEMON_PYTHON. stdout={result.stdout!r}"
    assert selected.endswith("/python3.13"), (
        f"probe must prefer versioned ``python3.13`` over bare ``python3``. "
        f"Selected: {selected!r}"
    )
    # The bare-python3 ban is the load-bearing assertion: even if both work,
    # the probe must NEVER lock onto the unversioned alias.
    assert not selected.endswith("/python3"), (
        f"probe must NEVER select bare ``python3`` (Decision 3 ban). " f"Selected: {selected!r}"
    )


@pytest.mark.xfail(strict=True, reason=_PHASE4_REASON)
def test_bootstrap_probes_open_ended_for_future_versions(tmp_path: Path) -> None:
    """Probe must discover future versions like ``python3.14`` via compgen.

    Setup: PATH contains only ``python3.14`` (a hypothetical future version
    that is NOT in the static candidate list of any current code).

    Pre-fix: hardcoded candidates list only includes 3.11/3.12/3.13. python3.14
    is invisible to the probe; the function fails despite a perfectly valid
    interpreter being present.

    Post-fix: ``compgen -c python3.`` enumerates PATH and discovers
    python3.14, adding it to the candidate set, and the probe succeeds.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.14", 3, 14)

    sourceable = _extract_probe_function(tmp_path)
    result = _run_probe(sourceable, bin_dir)

    assert result.returncode == 0, (
        f"probe must discover future python3.14 via compgen. "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
    selected = _selected_python(result.stdout)
    assert selected.endswith(
        "/python3.14"
    ), f"probe must select discovered python3.14. Selected: {selected!r}"


def test_bootstrap_fails_fast_when_no_compatible_python(tmp_path: Path) -> None:
    """No compatible interpreter on PATH → exit non-zero with clear directive.

    Setup: PATH contains only ``python3`` faking 3.9.

    Required failure message contents:
    - Names the 3.11 minimum requirement
    - Names what was tried (candidate list and/or compgen discovery result)
    - Does NOT export ``HOOKS_DAEMON_PYTHON``

    The function calls ``_fail`` which exits non-zero. The test asserts the
    user-facing diagnostic is informative — not a silent failure.
    """
    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3", 3, 9)

    sourceable = _extract_probe_function(tmp_path)
    result = _run_probe(sourceable, bin_dir)

    assert result.returncode != 0, (
        f"probe must exit non-zero when no compatible Python is available. "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
    combined = result.stdout + "\n" + result.stderr
    assert "3.11" in combined, (
        f"failure message must name the 3.11 minimum requirement. "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
    assert _selected_python(result.stdout) == "", (
        f"probe must not export HOOKS_DAEMON_PYTHON when no compatible "
        f"interpreter is found. stdout={result.stdout!r}"
    )


@pytest.mark.xfail(strict=True, reason=_PHASE4_REASON)
def test_bootstrap_honours_explicit_override(tmp_path: Path) -> None:
    """``HOOKS_DAEMON_PYTHON`` explicit override short-circuits the probe.

    Setup: ``HOOKS_DAEMON_PYTHON`` points at a fake python3.12 outside PATH.
    PATH contains a *different* versioned interpreter (python3.13) so the
    test can detect when the probe ran instead of honouring the override.

    Pre-fix: the function ignores the env var entirely and runs the candidate
    probe regardless. ``HOOKS_DAEMON_PYTHON`` ends up overwritten with the
    PATH-discovered ``python3.13`` — silently corrupting the user's intent.

    Post-fix: when ``HOOKS_DAEMON_PYTHON`` is set to a valid 3.11+
    interpreter, the function uses it verbatim and skips probing entirely.
    """
    override_dir = tmp_path / "override"
    override_dir.mkdir()
    override_python = _make_fake_python(override_dir, "python3.12", 3, 12)

    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.13", 3, 13)

    sourceable = _extract_probe_function(tmp_path)
    result = _run_probe(
        sourceable,
        bin_dir,
        env_overrides={"HOOKS_DAEMON_PYTHON": str(override_python)},
    )

    assert result.returncode == 0, (
        f"probe must accept valid HOOKS_DAEMON_PYTHON override. "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
    selected = _selected_python(result.stdout)
    assert selected == str(override_python), (
        f"probe must use HOOKS_DAEMON_PYTHON override verbatim. "
        f"Expected={str(override_python)!r}, got={selected!r}"
    )


@pytest.mark.xfail(strict=True, reason=_PHASE4_REASON)
def test_bootstrap_rejects_invalid_override(tmp_path: Path) -> None:
    """``HOOKS_DAEMON_PYTHON`` pointing at <3.11 must fail fast.

    Setup: ``HOOKS_DAEMON_PYTHON`` points at a fake python3.9. PATH has a
    valid python3.13 — pre-fix code would silently use it, masking the
    broken override.

    Pre-fix: function ignores env var → silently picks the 3.13 from PATH,
    user never learns their override is broken.

    Post-fix: explicit override is validated against the 3.11+ requirement
    and the function fails with a clear error message naming the override.
    Crucially, the function MUST NOT fall back to PATH probing — that would
    silently mask the user's misconfiguration.
    """
    override_dir = tmp_path / "override"
    override_dir.mkdir()
    override_python = _make_fake_python(override_dir, "python3.9", 3, 9)

    bin_dir = tmp_path / "bin"
    _make_fake_python(bin_dir, "python3.13", 3, 13)

    sourceable = _extract_probe_function(tmp_path)
    result = _run_probe(
        sourceable,
        bin_dir,
        env_overrides={"HOOKS_DAEMON_PYTHON": str(override_python)},
    )

    assert result.returncode != 0, (
        f"probe must reject HOOKS_DAEMON_PYTHON pointing at <3.11. "
        f"Falling back to PATH probing would silently mask the user's broken "
        f"configuration. stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
    combined = result.stdout + "\n" + result.stderr
    assert str(override_python) in combined or "HOOKS_DAEMON_PYTHON" in combined, (
        f"failure message must reference the rejected override so the user "
        f"can diagnose and fix it. "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
    assert _selected_python(result.stdout) == "", (
        f"probe must not export HOOKS_DAEMON_PYTHON when override is invalid. "
        f"stdout={result.stdout!r}"
    )
