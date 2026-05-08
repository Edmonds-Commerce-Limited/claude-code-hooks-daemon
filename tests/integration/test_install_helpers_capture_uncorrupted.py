"""Integration test: every ``VAR=$(fn ...)`` capture site in ``scripts/install/``
must yield a byte-exact, uncorrupted capture.

Plan 00105 Phase 2 Task 2.4.

The v3.10.0 SEV-1 was a single missing ``>&2`` on ``print_info`` that
corrupted ``VENV_PATH=$(ensure_venv ...)`` in ``scripts/install_version.sh``
and broke every existing user's upgrade in the field. Phase 2 added two
static checks (``audit_capture_corruption.py`` for the captured-function
rule + the log-helper rule). This dynamic test complements them: for every
function that returns a value via stdout AND is captured by some caller, we
invoke it with realistic args in a subshell, capture the output, and assert
it matches the documented contract byte-for-byte.

If any future regression introduces a ``print_info``/``echo``/``printf``
inside one of these functions without ``>&2``, the captured value will pick
up the leaking bytes and this test will fail with a clear diff before the
release ships.

The capture-site inventory was derived by grep-ing
``=\\$\\(([a-z_][a-z0-9_]*)`` across the install scripts, then keeping only
sites where the called name is a function defined in
``scripts/install/*.sh`` (i.e. not a system command like ``date`` or
``find``). The expensive cases (``ensure_venv`` triggering a real venv
creation, ``get_daemon_status`` starting a daemon) are exercised by
``tests/acceptance/test_install_sh_end_to_end.py`` instead — repeating
them here would just slow the test suite without adding coverage.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_DIR = REPO_ROOT / "scripts" / "install"
BASH = shutil.which("bash") or "/bin/bash"

# Sentinel used to delimit the capture inside the subshell's stdout. Anything
# between the two markers is the verbatim captured value; anything outside is
# noise that leaked past the redirect. Picking a sentinel that is not a
# valid path component nor a fingerprint character keeps the parse robust.
_OPEN = "<<<CAPTURE_BEGIN>>>"
_CLOSE = "<<<CAPTURE_END>>>"


def _run_capture(
    script_body: str, env: dict[str, str] | None = None, cwd: Path | None = None
) -> str:
    """Run a bash snippet that wraps ``VAR=$(fn ...)`` between sentinels.

    Returns the verbatim captured value (the bytes the caller would have
    received via ``$VAR``). If progress messages leak onto stdout, they
    appear in the captured value and the test fails.
    """
    full = textwrap.dedent(f"""
        set -uo pipefail
        cd "{cwd or REPO_ROOT}"
        {script_body}
        printf '%s' "{_OPEN}"
        printf '%s' "$CAPTURED"
        printf '%s' "{_CLOSE}"
        """)
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    result = subprocess.run(
        [BASH, "-c", full],
        capture_output=True,
        text=True,
        check=False,
        env=proc_env,
    )
    assert result.returncode == 0, (
        f"bash snippet exited {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    out = result.stdout
    assert _OPEN in out and _CLOSE in out, f"sentinels missing — full stdout: {out!r}"
    captured = out.split(_OPEN, 1)[1].split(_CLOSE, 1)[0]
    return captured


# ── pure path-shape captures ───────────────────────────────────────


class TestPurePathShapeCaptures:
    """Functions that return a path-shaped string. Every byte must match."""

    def test_get_snapshot_dir_returns_only_path(self, tmp_path: Path) -> None:
        daemon_dir = str(tmp_path / "daemon")
        body = (
            f'source "{INSTALL_DIR}/output.sh"\n'
            f'source "{INSTALL_DIR}/rollback.sh"\n'
            f'CAPTURED=$(get_snapshot_dir "{daemon_dir}")\n'
        )
        captured = _run_capture(body)
        # SNAPSHOT_BASE_DIR is "untracked/upgrade-snapshots" (rollback.sh:33).
        assert (
            captured == f"{daemon_dir}/untracked/upgrade-snapshots"
        ), f"get_snapshot_dir capture corrupted. Got: {captured!r}"

    def test_get_daemon_dir_self_install(self, tmp_path: Path) -> None:
        project_root = str(tmp_path / "project")
        body = (
            f'source "{INSTALL_DIR}/output.sh"\n'
            f'source "{INSTALL_DIR}/project_detection.sh"\n'
            f'CAPTURED=$(get_daemon_dir "{project_root}" "self-install")\n'
        )
        captured = _run_capture(body)
        assert (
            captured == project_root
        ), f"get_daemon_dir self-install capture corrupted. Got: {captured!r}"

    def test_get_daemon_dir_normal(self, tmp_path: Path) -> None:
        project_root = str(tmp_path / "project")
        body = (
            f'source "{INSTALL_DIR}/output.sh"\n'
            f'source "{INSTALL_DIR}/project_detection.sh"\n'
            f'CAPTURED=$(get_daemon_dir "{project_root}" "normal")\n'
        )
        captured = _run_capture(body)
        assert (
            captured == f"{project_root}/.claude/hooks-daemon"
        ), f"get_daemon_dir normal capture corrupted. Got: {captured!r}"


# ── mode-detection captures ────────────────────────────────────────


class TestDetectInstallModeCapture:
    """``detect_install_mode`` is captured by every install entry-point."""

    def test_no_config_returns_normal(self, tmp_path: Path) -> None:
        body = (
            f'source "{INSTALL_DIR}/output.sh"\n'
            f'source "{INSTALL_DIR}/project_detection.sh"\n'
            f'CAPTURED=$(detect_install_mode "{tmp_path}")\n'
        )
        captured = _run_capture(body)
        assert (
            captured == "normal"
        ), f"detect_install_mode (no config) capture corrupted. Got: {captured!r}"

    def test_self_install_yaml_returns_self_install(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(
            "daemon:\n  self_install_mode: true\n"
        )
        body = (
            f'source "{INSTALL_DIR}/output.sh"\n'
            f'source "{INSTALL_DIR}/project_detection.sh"\n'
            f'CAPTURED=$(detect_install_mode "{tmp_path}")\n'
        )
        captured = _run_capture(body)
        assert captured == "self-install", (
            f"detect_install_mode (self-install) capture corrupted. " f"Got: {captured!r}"
        )


# ── project-root walks ─────────────────────────────────────────────


class TestDetectProjectRootCaptures:
    """``detect_project_root`` and ``..._current_dir`` walk the FS."""

    def test_detect_project_root_walks_up_to_yaml(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "hooks-daemon.yaml").write_text("daemon: {}\n")
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        body = (
            f'source "{INSTALL_DIR}/output.sh"\n'
            f'source "{INSTALL_DIR}/project_detection.sh"\n'
            f"CAPTURED=$(detect_project_root)\n"
        )
        captured = _run_capture(body, cwd=deep)
        assert captured == str(
            tmp_path
        ), f"detect_project_root capture corrupted. Got: {captured!r}"

    def test_detect_project_root_current_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".git").mkdir()
        body = (
            f'source "{INSTALL_DIR}/output.sh"\n'
            f'source "{INSTALL_DIR}/project_detection.sh"\n'
            f"CAPTURED=$(detect_project_root_current_dir)\n"
        )
        captured = _run_capture(body, cwd=tmp_path)
        assert captured == str(tmp_path), (
            f"detect_project_root_current_dir capture corrupted. " f"Got: {captured!r}"
        )


# ── python-version + fingerprint captures ──────────────────────────


_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_MAJOR_MINOR_RE = re.compile(r"^\d+\.\d+$")
# Slug-prefixed fingerprint shape: ``{slug}-py{MM}-{8-hex}``. With no root
# (the test uses HOOKS_DAEMON_ROOT_DIR=""), it is the bare ``py{MM}-{8-hex}``.
_BARE_FINGERPRINT_RE = re.compile(r"^py\d{2,3}-[0-9a-f]{8}$")


class TestPythonVersionCaptures:
    """``get_python_version`` + ``get_python_major_minor`` from prerequisites.sh."""

    def test_get_python_version(self) -> None:
        body = (
            f'source "{INSTALL_DIR}/output.sh"\n'
            f'source "{INSTALL_DIR}/prerequisites.sh"\n'
            f"CAPTURED=$(get_python_version)\n"
        )
        captured = _run_capture(body)
        assert _VERSION_RE.match(captured), (
            f"get_python_version capture corrupted (expected M.m.p). " f"Got: {captured!r}"
        )

    def test_get_python_major_minor(self) -> None:
        body = (
            f'source "{INSTALL_DIR}/output.sh"\n'
            f'source "{INSTALL_DIR}/prerequisites.sh"\n'
            f"CAPTURED=$(get_python_major_minor)\n"
        )
        captured = _run_capture(body)
        assert _MAJOR_MINOR_RE.match(captured), (
            f"get_python_major_minor capture corrupted (expected M.m). " f"Got: {captured!r}"
        )


class TestPythonVenvFingerprintCapture:
    """``python_venv_fingerprint`` is captured by venv.sh and venv_resolver.sh."""

    def test_bare_fingerprint_no_root(self) -> None:
        python_bin = sys.executable
        body = (
            f'source "{INSTALL_DIR}/output.sh"\n'
            f'source "{INSTALL_DIR}/python_fingerprint.sh"\n'
            f'CAPTURED=$(HOOKS_DAEMON_ROOT_DIR="" '
            f'python_venv_fingerprint "{python_bin}")\n'
        )
        captured = _run_capture(body)
        assert _BARE_FINGERPRINT_RE.match(captured), (
            f"python_venv_fingerprint (no root) capture corrupted. " f"Got: {captured!r}"
        )


# ── config_diff_analyzer.sh (script-level capture) ─────────────────


class TestConfigDiffAnalyzerScriptIsUncorrupted:
    """``extract_handlers`` is captured INSIDE ``config_diff_analyzer.sh``
    itself (``OLD_HANDLERS=$(extract_handlers ...)``) — sourcing it standalone
    triggers the script's own ``set -euo pipefail`` + arg validation, so the
    cleanest dynamic check is to invoke the whole script with two real YAML
    configs and assert its stdout is parseable JSON with no leaked progress
    messages. Any future regression that adds an unredirected echo inside
    ``extract_handlers`` will corrupt ``OLD_HANDLERS``/``NEW_HANDLERS`` and
    in turn corrupt the JSON output.
    """

    def test_script_emits_clean_json(self, tmp_path: Path) -> None:
        old = tmp_path / "old.yaml"
        new = tmp_path / "new.yaml"
        old.write_text(textwrap.dedent("""
            handlers:
              pre_tool_use:
                handler_a:
                  enabled: true
                handler_b:
                  enabled: false
        """).lstrip())
        new.write_text(textwrap.dedent("""
            handlers:
              pre_tool_use:
                handler_a:
                  enabled: true
                handler_c:
                  enabled: true
        """).lstrip())
        result = subprocess.run(
            [BASH, str(INSTALL_DIR / "config_diff_analyzer.sh"), str(old), str(new)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"config_diff_analyzer.sh exited {result.returncode}\n" f"stderr: {result.stderr}"
        )
        # The very first non-whitespace stdout char MUST be ``{`` — anything
        # else means a progress message leaked before the JSON.
        first = result.stdout.lstrip()
        assert first.startswith("{"), (
            f"config_diff_analyzer.sh stdout has non-JSON prefix — a helper "
            f"is leaking to stdout. stdout starts with: {first[:80]!r}"
        )
        # And it must be parseable JSON — proof that the captured handler
        # lists weren't corrupted.
        json.loads(result.stdout)
