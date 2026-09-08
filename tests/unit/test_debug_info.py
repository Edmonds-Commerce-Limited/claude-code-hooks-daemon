"""Plan 00122 BUG 4 — debug_info.py honest, client-aware diagnostics.

The official diagnostic ``scripts/debug_info.py`` (the tool ``src/CLAUDE.md``
tells bug reporters to run) was nearly useless on macOS:

  * It derived the project root from ``Path(__file__).parent.parent`` — which in
    a client install is ``{client}/.claude/hooks-daemon`` (the daemon's own
    clone), NOT the client project.
  * When ``.claude/init.sh`` path-detection failed it printed a single
    ``ERROR: Could not detect daemon paths`` line and returned, dumping none of
    the very things needed to diagnose the macOS socket bug (runtime files,
    venv state, daemon processes).

These tests pin the fix: client-aware root detection (locate the dir holding
``.claude/hooks-daemon.yaml``) and graceful degradation that still emits
process / runtime-file / venv diagnostics when init.sh detection fails.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEBUG_INFO_PATH = REPO_ROOT / "scripts" / "debug_info.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("debug_info_under_test", DEBUG_INFO_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def debug_info_module():
    return _load_module()


def _make_client_project(tmp_path: Path) -> Path:
    """A client project: ``.claude/hooks-daemon.yaml`` at the root, with the
    daemon cloned under ``.claude/hooks-daemon/``."""
    project = tmp_path / "client"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "hooks-daemon.yaml").write_text("self_install_mode: false\n")
    (project / ".claude" / "hooks-daemon" / "scripts").mkdir(parents=True)
    return project


def test_detects_client_project_root_not_daemon_clone(
    debug_info_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root resolves to the dir holding hooks-daemon.yaml, not the clone dir."""
    project = _make_client_project(tmp_path)
    monkeypatch.chdir(project)

    gen = debug_info_module.DebugInfoGenerator(output_file=str(tmp_path / "out.md"))

    assert gen.project_root == project, (
        f"project root must be the client project ({project}), not {gen.project_root}"
    )


def test_explicit_project_root_override(debug_info_module, tmp_path: Path) -> None:
    """An explicit project_root argument is honoured (testability seam)."""
    project = _make_client_project(tmp_path)
    gen = debug_info_module.DebugInfoGenerator(
        output_file=str(tmp_path / "out.md"), project_root=project
    )
    assert gen.project_root == project


def test_degrades_gracefully_when_init_sh_missing(debug_info_module, tmp_path: Path) -> None:
    """When init.sh path-detection fails, still emit runtime/venv/process state.

    Pre-fix: a single 'Could not detect daemon paths' line then return.
    Post-fix: the report still includes the degraded diagnostics that are
    exactly what's needed to diagnose the macOS socket bug.
    """
    project = _make_client_project(tmp_path)
    # No .claude/init.sh → get_daemon_paths() returns None.
    untracked = project / ".claude" / "hooks-daemon" / "untracked"
    untracked.mkdir(parents=True)
    (untracked / "daemon-somehost.sock").write_text("")
    (untracked / "venv-py311-abc").mkdir()

    gen = debug_info_module.DebugInfoGenerator(
        output_file=str(tmp_path / "out.md"), project_root=project
    )
    gen.generate()
    report = "\n".join(gen.output_lines)

    # It must NOT stop at the error line.
    assert "Could not detect daemon paths" in report  # the note is still shown
    # Degraded diagnostics must be present:
    assert "Runtime Files" in report, "degraded report must list runtime files"
    assert "daemon-somehost.sock" in report, "runtime file names must be dumped"
    assert "venv-py311-abc" in report, "venv directory names must be dumped"
    assert "Process State" in report, "degraded report must include process state"


def test_blank_python_cmd_is_reported_not_executed(debug_info_module, tmp_path: Path) -> None:
    """Plan 00353: a blank PYTHON_CMD must be rejected, not handed to subprocess.

    The interpreter guard asked ``Path(python_cmd).exists()``, but ``Path("")``
    is ``PosixPath('.')`` — the current directory, which always exists. So a
    blank ``PYTHON_CMD`` sailed past the guard and every section that shells out
    to the interpreter reported ``[Errno 13] Permission denied: ''`` instead of
    the real problem.
    """
    project = _make_client_project(tmp_path)
    # An init.sh that resolves no interpreter: the five echoed keys are all
    # present (so path detection "succeeds") but PYTHON_CMD is empty.
    (project / ".claude" / "init.sh").write_text('#!/usr/bin/env bash\nPYTHON_CMD=""\n')

    gen = debug_info_module.DebugInfoGenerator(
        output_file=str(tmp_path / "out.md"), project_root=project
    )
    gen.generate()
    report = "\n".join(gen.output_lines)

    assert "Permission denied" not in report, "a blank interpreter must never be executed"
    assert "Python venv not found" in report, "the report must name the real problem"


def test_daemon_status_and_installed_handlers_sections_run_without_an_error_line(
    debug_info_module, tmp_path: Path
) -> None:
    """Plan 00362 D21: the two sections that shell out to the interpreter appear
    in the report and carry no ``[Errno ...]`` line.

    The client field report showed ``[Errno 13] Permission denied: ''`` under
    BOTH "Daemon Status" and "Installed Handlers" in every generated report.
    The blank-interpreter test above pins the guard; this one pins the happy
    path the reporter never saw: a resolvable interpreter yields both sections
    with real content.
    """
    project = _make_client_project(tmp_path)
    untracked = project / ".claude" / "hooks-daemon" / "untracked"
    untracked.mkdir(parents=True)
    (project / ".claude" / "init.sh").write_text(
        "#!/usr/bin/env bash\n"
        f'PROJECT_PATH="{project}"\n'
        f'HOOKS_DAEMON_ROOT_DIR="{REPO_ROOT}"\n'
        f'PYTHON_CMD="{sys.executable}"\n'
        f'SOCKET_PATH="{untracked / "daemon-test.sock"}"\n'
        f'PID_PATH="{untracked / "daemon-test.pid"}"\n'
    )

    gen = debug_info_module.DebugInfoGenerator(
        output_file=str(tmp_path / "out.md"), project_root=project
    )
    gen.generate()
    report = "\n".join(gen.output_lines)

    assert "## Daemon Status" in report
    assert "## Installed Handlers" in report
    assert "Errno" not in report, "no section may report a failed command launch"
    assert "Permission denied" not in report
    assert "Discovered" in report, "the handlers section must list what it found"
