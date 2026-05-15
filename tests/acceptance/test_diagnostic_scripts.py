r"""Plan 00104 Phase 9 Task 9.6 — H-1 acceptance gate for diagnostic scripts.

The 2026-05-01 field report (``CLAUDE/Plan/00104-.../context/2026-05-01-field-
report-upgrade-issues.md``) surfaced six issues. v3.10.0 closes Issues #1, #2,
#3, #4, and (as a phantom of #4) #6. This file is the acceptance gate that
exercises the production scripts end-to-end so the v3.9.x regression style
cannot recur — the v3.9.0 escape happened because acceptance focused on hook
dispatch, never on diagnostic-script invocation paths.

Test cases (per PLAN.md Phase 9 Task 9.6):

  1. Fresh-install metadata is correct: ``write-venv-metadata`` writes
     ``python_path`` pointing at the venv's own ``bin/python``, NOT at the
     system ``/usr/bin/python3.11`` that invoked the CLI. (Issue #4.)
  2. ``daemon-cli.sh status`` from a freshly-bootstrapped layout runs without
     ``ModuleNotFoundError``. (Issue #4 phantom.)
  3. ``health-check.sh`` from the same layout runs without
     ``ModuleNotFoundError``. (Issue #6.)
  4. Skill ``upgrade.sh`` self-bootstrap produces the latest version when the
     local copy is stale. (Issue #1, Decision 3.C.)
  5. Skill ``upgrade.sh`` aborts loudly on network failure — never silently
     falls back to the stale local copy. (Issue #1, Decision 3.C.)
  6. Stale ``daemon-cli.sh`` self-bootstraps on first invocation per session
     (Decision 3.B). DEFERRED — Task 5.1.B is not landing in v3.10.0; this
     case is recorded here as a placeholder so the test file matches Task 9.6
     verbatim and a future plan can wire it up.

Each case builds its own minimal fixture from the live source tree
(``src/.../skills/hooks-daemon/scripts/...``, ``scripts/lib/resolve_venv.sh``,
``src/.../daemon/paths.py``) so the acceptance contract evolves in lock-step
with the production scripts.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "claude_code_hooks_daemon"
SKILL_SCRIPTS = SRC_ROOT / "skills" / "hooks-daemon" / "scripts"
DAEMON_CLI_SH = SKILL_SCRIPTS / "daemon-cli.sh"
HEALTH_CHECK_SH = SKILL_SCRIPTS / "health-check.sh"
RESOLVE_VENV_SH = SKILL_SCRIPTS / "_resolve-venv.sh"
SKILL_UPGRADE_SH = SKILL_SCRIPTS / "upgrade.sh"
PATHS_PY = SRC_ROOT / "daemon" / "paths.py"
CANONICAL_LIB = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
BASH = shutil.which("bash") or "/bin/bash"

_DOGFOOD_VENV_PYTHON = Path(sys.executable)
_DOGFOOD_VENV_DIR = _DOGFOOD_VENV_PYTHON.parent.parent


def _build_diagnostic_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Build a fixture project with the layout daemon-cli.sh and health-check.sh expect.

    Layout::

        $tmp/project/
            .claude/
                hooks-daemon.yaml                # marker for PROJECT_ROOT walk
                hooks-daemon/
                    scripts/
                        lib/resolve_venv.sh      -> repo
                    src/claude_code_hooks_daemon/daemon/paths.py  -> repo
                    untracked/
                        venv-py311-acceptance/
                            bin/python           -> the pytest interpreter

    The pytest interpreter has the daemon package installed editable, so
    invoking ``$PYTHON -m claude_code_hooks_daemon.daemon.cli`` succeeds —
    proving the absence of the v3.9.0 ``ModuleNotFoundError`` regression.

    Returns (project_root, daemon_dir).
    """
    project_root = tmp_path / "project"
    daemon_dir = project_root / ".claude" / "hooks-daemon"
    (project_root / ".claude").mkdir(parents=True)
    (project_root / ".claude" / "hooks-daemon.yaml").write_text("handlers: {}\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=project_root, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/acceptance.git"],
        cwd=project_root,
        check=True,
    )

    lib_target = daemon_dir / "scripts" / "lib" / "resolve_venv.sh"
    lib_target.parent.mkdir(parents=True)
    os.symlink(CANONICAL_LIB, lib_target)

    paths_target = daemon_dir / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"
    paths_target.parent.mkdir(parents=True)
    os.symlink(PATHS_PY, paths_target)

    untracked_dir = daemon_dir / "untracked"
    untracked_dir.mkdir(parents=True)
    venv_target = untracked_dir / "venv-py311-acceptance"
    os.symlink(_DOGFOOD_VENV_DIR, venv_target)

    return project_root, daemon_dir


def test_write_venv_metadata_records_venv_resident_python_path(tmp_path: Path) -> None:
    """Case 1: ``write-venv-metadata`` MUST record the venv's own bin/python.

    The v3.9.0 field bug (Issue #4 in the 2026-05-01 report) was that
    ``write-venv-metadata`` stored ``/usr/bin/python3.11`` — the calling
    system interpreter — as ``python_path``. Downstream skill scripts then
    used the system Python and crashed with
    ``ModuleNotFoundError: No module named 'claude_code_hooks_daemon'``.

    v3.10.0 (Plan 00104 Task 2.1, commit 5674a3e) fixes ``cli.py:1415``
    to use ``str(venv_path / "bin" / "python")``. This test asserts the
    fixed behaviour by invoking the live CLI command against a fixture
    venv and reading the produced metadata file.
    """
    venv_path = tmp_path / "venv-py311-acceptance"
    venv_bin = venv_path / "bin"
    venv_bin.mkdir(parents=True)
    venv_python = venv_bin / "python"
    os.symlink(_DOGFOOD_VENV_PYTHON, venv_python)

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text(
        '[project]\nname = "acceptance-fixture"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            str(_DOGFOOD_VENV_PYTHON),
            "-m",
            "claude_code_hooks_daemon.daemon.cli",
            "write-venv-metadata",
            "--venv-path",
            str(venv_path),
            "--fingerprint",
            "py311-acceptance",
            "--daemon-version",
            "v3.10.0",
            "--project-root",
            str(project_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"write-venv-metadata must succeed against a real fixture venv. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    metadata_path = venv_path / ".daemon-metadata.json"
    assert metadata_path.is_file(), (
        f"write-venv-metadata must produce {metadata_path}. "
        f"Found dir contents: {list(venv_path.iterdir())}"
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    expected_python_path = str(venv_python)
    assert metadata["python_path"] == expected_python_path, (
        f"python_path must point at the venv's own bin/python (not the "
        f"system interpreter that invoked the CLI). expected="
        f"{expected_python_path!r}, got={metadata['python_path']!r}. "
        f"This is the regression that caused the 2026-05-01 field report "
        f"Issue #4."
    )
    assert "/usr/bin/" not in metadata["python_path"], (
        f"python_path must NEVER be a system /usr/bin/ path — that's exactly "
        f"the v3.9.0 bug. Got: {metadata['python_path']!r}"
    )


def _run_daemon_cli_status(project_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(project_root.parent)
    # Plan 00105 Phase 4: daemon-cli.sh now carries the same self-bootstrap
    # stanza as upgrade.sh. This test exercises the daemon-CLI dispatch path,
    # not the bootstrap path — disable bootstrap so the test does not depend
    # on a published release manifest. The bootstrap path itself is covered
    # by test_skill_*_self_bootstrap_* below.
    env["HOOKS_DAEMON_SKIP_BOOTSTRAP"] = "1"
    return subprocess.run(
        [BASH, str(DAEMON_CLI_SH), "status"],
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
        check=False,
    )


def test_daemon_cli_status_runs_without_module_not_found_error(tmp_path: Path) -> None:
    """Case 2: ``daemon-cli.sh status`` must import the package cleanly.

    The v3.9.0 field bug surfaced as ``ModuleNotFoundError: No module
    named 'claude_code_hooks_daemon'`` because ``daemon-cli.sh``
    ultimately invoked ``/usr/bin/python3.11`` (read out of the broken
    metadata, see Case 1). v3.10.0 with the corrected metadata writer
    plus the canonical-library resolver routes the script to the venv's
    own interpreter — so the import succeeds.

    The status CLI exits 1 when no daemon is running (which is the
    expected state in our fixture — we did not start one). What matters
    for the acceptance contract is the absence of ``ModuleNotFoundError``
    and the presence of the recognisable ``Daemon: NOT RUNNING`` /
    ``Daemon: RUNNING`` line, which proves the Python import + CLI
    dispatch reached the status code path.
    """
    project_root, _ = _build_diagnostic_fixture(tmp_path)
    result = _run_daemon_cli_status(project_root)

    combined = result.stdout + "\n" + result.stderr
    assert "ModuleNotFoundError" not in combined, (
        f"daemon-cli.sh must NOT crash with ModuleNotFoundError — that's "
        f"the v3.9.0 field-bug signature. stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    assert "Daemon:" in result.stdout, (
        f"daemon-cli.sh status output must include the 'Daemon:' status "
        f"line, proving the Python import + CLI dispatch succeeded. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_health_check_runs_without_module_not_found_error(tmp_path: Path) -> None:
    """Case 3: ``health-check.sh`` must import the package cleanly.

    Same root cause as Case 2 (Issue #6 in the field report — the field
    report initially classified it separately, but v3.10.0's metadata
    fix closes both at once because both scripts share the same
    ``_resolve-venv.sh`` shim). The health-check exits non-zero when no
    daemon is running, which is fine for the acceptance contract — we
    pin the absence of the import-time crash.
    """
    project_root, _ = _build_diagnostic_fixture(tmp_path)
    env = os.environ.copy()
    env["HOME"] = str(project_root.parent)
    # Plan 00105 Phase 4: health-check.sh now carries the same self-bootstrap
    # stanza as upgrade.sh. This test exercises the daemon-CLI dispatch path,
    # not the bootstrap path — disable bootstrap so the test does not depend
    # on a published release manifest. The bootstrap path itself is covered
    # by test_skill_*_self_bootstrap_* below.
    env["HOOKS_DAEMON_SKIP_BOOTSTRAP"] = "1"
    result = subprocess.run(
        [BASH, str(HEALTH_CHECK_SH)],
        capture_output=True,
        text=True,
        cwd=project_root,
        env=env,
        check=False,
    )

    combined = result.stdout + "\n" + result.stderr
    assert "ModuleNotFoundError" not in combined, (
        f"health-check.sh must NOT crash with ModuleNotFoundError. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "Health Check" in result.stdout or "DAEMON STATUS" in result.stdout, (
        f"health-check.sh output must include its banner sections, proving "
        f"the script reached the daemon-CLI dispatch step. "
        f"stdout={result.stdout!r}"
    )


_BEGIN_MARKER = "# === SELF-BOOTSTRAP BEGIN"
_END_MARKER = "# === SELF-BOOTSTRAP END ==="


def _extract_bootstrap_stanza() -> str:
    # Plan 00109 Phase 2.2 collapsed the skill upgrade.sh to a thin
    # curl-and-exec shim — it no longer carries the bootstrap stanza. The
    # three sibling diagnostic scripts (daemon-cli.sh, health-check.sh,
    # init-handlers.sh) still embed the parameterised stanza verbatim per
    # Plan 00105 Phase 4 Decision 3.B, so daemon-cli.sh is the canonical
    # source for these acceptance fixtures going forward.
    text = DAEMON_CLI_SH.read_text(encoding="utf-8")
    start = text.find(_BEGIN_MARKER)
    end = text.find(_END_MARKER)
    assert start != -1, f"could not find {_BEGIN_MARKER!r} in {DAEMON_CLI_SH}"
    assert end != -1, f"could not find {_END_MARKER!r} in {DAEMON_CLI_SH}"
    return text[start : end + len(_END_MARKER)]


def _wrap_stanza(body_marker: str) -> str:
    stanza = _extract_bootstrap_stanza()
    template = textwrap.dedent(f"""\
        #!{BASH}
        set -euo pipefail
        {{stanza}}
        echo "{body_marker}"
        """)
    return template.replace("{stanza}", stanza)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Plan 00109 Phase 2.2: the former upgrade.sh-specific bootstrap acceptance
# tests (test_skill_upgrade_self_bootstrap_produces_latest and
# test_skill_upgrade_aborts_on_network_failure_with_directive) were retired
# here. The skill upgrade.sh is now a thin curl+exec shim that delegates to
# the canonical scripts/upgrade.sh on a configurable git ref; the equivalent
# end-to-end coverage now lives in tests/acceptance/test_skill_upgrade_shim.py.
# The sibling-script parametrised cases below continue to exercise the
# self-bootstrap contract for daemon-cli.sh / health-check.sh / init-handlers.sh
# which retain the stanza per Plan 00109 Non-Goals.


# Plan 00105 Phase 4 — Decision 3.B activated. The bootstrap stanza is now
# parameterised by ``$(basename "$0")`` and shared verbatim by upgrade.sh,
# daemon-cli.sh, health-check.sh, and init-handlers.sh. The cases below pin
# the contract that EVERY diagnostic script self-bootstraps on first
# invocation per session and short-circuits via a per-(basename, own-sha)
# cache marker on subsequent invocations.

_BOOTSTRAPPED_BASENAMES = ["daemon-cli.sh", "health-check.sh", "init-handlers.sh"]


@pytest.mark.parametrize("basename", _BOOTSTRAPPED_BASENAMES)
def test_stale_diagnostic_script_self_bootstraps_on_first_invocation(
    tmp_path: Path, basename: str
) -> None:
    """Case 6: stale diagnostic scripts self-bootstrap to the fresh release.

    Plan 00105 Phase 4 lands the parameterised bootstrap stanza in
    daemon-cli.sh, health-check.sh, and init-handlers.sh. This test pins the
    same contract as case 4 (skill upgrade.sh) but per-script: a stale local
    body detects its sha256 mismatch, downloads the fresh body, re-execs
    with ``--already-bootstrapped``, and the fresh body runs.
    """
    # Use a unique TMPDIR so an earlier test run's cache marker doesn't
    # short-circuit this fixture.
    bootstrap_tmp = tmp_path / "bootstrap-tmp"
    bootstrap_tmp.mkdir()

    fresh_dir = tmp_path / "release-mock"
    fresh_dir.mkdir()
    fresh_script_path = fresh_dir / basename
    fresh_script_path.write_text(_wrap_stanza("FRESH_BODY_RAN"), encoding="utf-8")
    fresh_script_path.chmod(fresh_script_path.stat().st_mode | stat.S_IEXEC)

    fresh_sha = _sha256_hex(fresh_script_path.read_bytes())
    checksums_path = fresh_dir / "bootstrap-checksums.txt"
    checksums_path.write_text(f"{fresh_sha}  {basename}\n", encoding="utf-8")

    install_dir = tmp_path / "stale-install"
    install_dir.mkdir()
    stale_script_path = install_dir / basename
    stale_script_path.write_text(_wrap_stanza("STALE_BODY_RAN"), encoding="utf-8")
    stale_script_path.chmod(stale_script_path.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env["HOOKS_DAEMON_BOOTSTRAP_BASE_URL"] = f"file://{fresh_dir}"
    env["TMPDIR"] = str(bootstrap_tmp)

    result = subprocess.run(
        [str(stale_script_path)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, (
        f"{basename} self-bootstrap must succeed end-to-end. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "FRESH_BODY_RAN" in result.stdout, (
        f"{basename}: the fresh script body MUST execute after self-bootstrap. "
        f"stdout={result.stdout!r}"
    )
    assert "STALE_BODY_RAN" not in result.stdout, (
        f"{basename}: the stale script body MUST NOT execute — it was bypassed "
        f"by the re-exec. stdout={result.stdout!r}"
    )


@pytest.mark.parametrize("basename", _BOOTSTRAPPED_BASENAMES)
def test_diagnostic_script_aborts_on_network_failure(tmp_path: Path, basename: str) -> None:
    """Case 7: network unreachable MUST abort loudly for every diagnostic script.

    Mirrors case 5 (skill upgrade.sh) for the three diagnostic scripts. The
    bootstrap stanza MUST exit non-zero with a clear operator-facing
    directive when the manifest URL cannot be reached, rather than silently
    continuing on with the stale local body — that would be the
    silent-fallback antipattern that caused the v3.9.0 field bug.
    """
    bootstrap_tmp = tmp_path / "bootstrap-tmp"
    bootstrap_tmp.mkdir()

    install_dir = tmp_path / "stale-install"
    install_dir.mkdir()
    stale_script_path = install_dir / basename
    stale_script_path.write_text(_wrap_stanza("STALE_BODY_RAN"), encoding="utf-8")
    stale_script_path.chmod(stale_script_path.stat().st_mode | stat.S_IEXEC)

    unreachable_dir = tmp_path / "does-not-exist"
    env = os.environ.copy()
    env["HOOKS_DAEMON_BOOTSTRAP_BASE_URL"] = f"file://{unreachable_dir}"
    env["TMPDIR"] = str(bootstrap_tmp)

    result = subprocess.run(
        [str(stale_script_path)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode != 0, (
        f"{basename} self-bootstrap MUST exit non-zero when the bootstrap "
        f"source is unreachable. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "STALE_BODY_RAN" not in result.stdout, (
        f"{basename}: the stale body MUST NOT run after a failed bootstrap — "
        f"that would be the silent-fallback antipattern. stdout={result.stdout!r}"
    )
    assert "failed to download" in result.stderr.lower(), (
        f"{basename}: failure message MUST direct the operator at the network "
        f"problem. stderr={result.stderr!r}"
    )


@pytest.mark.parametrize("basename", _BOOTSTRAPPED_BASENAMES)
def test_bootstrap_cache_marker_short_circuits_network_round_trip(
    tmp_path: Path, basename: str
) -> None:
    """Case 8: a pre-existing per-(basename, own-sha) marker skips the network.

    The stanza writes a marker at
    ``${TMPDIR:-/tmp}/hooks-daemon-bootstrap/<basename>-<own-sha>.ok`` after
    a successful verify. On the next invocation with the same body, the
    stanza must short-circuit — no curl call, no manifest fetch — so
    repeated invocations within a session do not hammer the network. We
    pin this by pointing ``HOOKS_DAEMON_BOOTSTRAP_BASE_URL`` at an
    unreachable URL: with the marker present, the script must still run
    successfully because the bootstrap stanza never tries to fetch.
    """
    bootstrap_tmp = tmp_path / "bootstrap-tmp"
    marker_dir = bootstrap_tmp / "hooks-daemon-bootstrap"
    marker_dir.mkdir(parents=True)

    install_dir = tmp_path / "install"
    install_dir.mkdir()
    script_path = install_dir / basename
    script_path.write_text(_wrap_stanza("BODY_RAN"), encoding="utf-8")
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

    own_sha = _sha256_hex(script_path.read_bytes())
    marker_path = marker_dir / f"{basename}-{own_sha}.ok"
    marker_path.write_text("", encoding="utf-8")

    unreachable_dir = tmp_path / "does-not-exist"
    env = os.environ.copy()
    env["HOOKS_DAEMON_BOOTSTRAP_BASE_URL"] = f"file://{unreachable_dir}"
    env["TMPDIR"] = str(bootstrap_tmp)

    result = subprocess.run(
        [str(script_path)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, (
        f"{basename}: a pre-existing cache marker MUST short-circuit the "
        f"bootstrap stanza so the script runs without a network call. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "BODY_RAN" in result.stdout, (
        f"{basename}: the script body MUST run when the cache marker is "
        f"present. stdout={result.stdout!r}"
    )
    assert "failed to download" not in result.stderr.lower(), (
        f"{basename}: with the marker present, the stanza MUST NOT attempt "
        f"to fetch the manifest. stderr={result.stderr!r}"
    )
