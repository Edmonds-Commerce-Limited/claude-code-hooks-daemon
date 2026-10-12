"""The opt-in handler restore runs before the upgrade restarts the daemon (N445).

``check-effective-handlers --apply`` (N360) writes ``enabled: true`` for every
opt-in handler an upgrade would switch off. Layer 1 used to run it after
Layer 2 had deployed and restarted the daemon, so the restarted daemon ran
without the restored handlers until a manual restart.

Layer 2 now runs it (``run_effective_handler_restore``) on both routes, after
the target's venv is verified and before the first deploy. It hands the report
to Layer 1 through the handoff directory (``restored-handlers``), and Layer 1
no longer asks for a restart for a restore that already preceded the restart.
An older Layer 2 (no step, no file) keeps Layer 1's own ``--apply`` call and
its restart request.

Ordering is asserted structurally on the script text, like the sibling
``test_upgrade_pre_deploy_phase_placement``; the Layer 2 function and the
Layer 1 block are also executed, extracted from the scripts, against a stub
interpreter.
"""

from __future__ import annotations

import re
import stat
import subprocess
from pathlib import Path
from typing import Final

_SCRIPTS: Final[Path] = Path(__file__).resolve().parents[2] / "scripts"
_LAYER1: Final[Path] = _SCRIPTS / "upgrade.sh"
_LAYER2: Final[Path] = _SCRIPTS / "upgrade_version.sh"
_RESTORE: Final[str] = "run_effective_handler_restore"
_COMPAT: Final[str] = "run_config_compatibility_check"
_FAST_PATH_START: Final[str] = "Running idempotent deployment steps"
_FIRST_DEPLOY: Final[str] = 'deploy_all_hooks "$PROJECT_ROOT"'
_RESTART: Final[str] = 'restart_daemon_verified "$VENV_PYTHON"'
_STEP_6: Final[str] = 'log_step "6"'
_STEP_8: Final[str] = 'log_step "8"'
_STEP_15: Final[str] = 'log_step "15"'
_L1_START: Final[str] = "# Version change and effective handler set"
_L1_END: Final[str] = "# Post-upgrade tasks"
_RESTORED_TEXT: Final[str] = (
    "1 opt-in handler(s) RESTORED (enabled: true written to the config):\n"
    "  - handlers.pre_tool_use.some_handler\n"
)
_STOPS_TEXT: Final[str] = (
    "1 handler(s) STOP running with this upgrade:\n  - handlers.pre_tool_use.other_handler\n"
)


def _layer2() -> str:
    return _LAYER2.read_text(encoding="utf-8")


def _call(text: str, name: str, start: int) -> int:
    match = re.compile(rf"^\s*{name}\s*$", re.MULTILINE).search(text, start)
    assert match is not None, f"{name} is not called after offset {start}"
    return match.start()


def _function(text: str, name: str) -> str:
    start = text.index(f"{name}() {{")
    match = re.compile(r"\n\}\n").search(text, start)
    assert match is not None, f"no closing brace found for {name}"
    return text[start : match.start() + 2]


def test_the_idempotent_path_restores_after_the_venv_and_before_deploy_and_restart() -> None:
    text = _layer2()
    fast_path = text.index(_FAST_PATH_START)
    restore = _call(text, _RESTORE, fast_path)
    assert text.index('verify_venv "$VENV_PYTHON"', fast_path) < restore
    assert restore < text.index(_FIRST_DEPLOY, fast_path)
    assert restore < text.index(_RESTART, fast_path)


def test_the_direct_path_restores_after_the_venv_and_before_deploy_and_restart() -> None:
    text = _layer2()
    step_6 = text.index(_STEP_6)
    restore = _call(text, _RESTORE, step_6)
    assert text.index('verify_venv "$VENV_PYTHON"', step_6) < restore < text.index(_STEP_8)
    assert restore < text.index(_STEP_15) < text.index(_RESTART, step_6)


def test_both_routes_call_the_one_function_so_the_logic_is_not_duplicated() -> None:
    text = _layer2()
    assert len(re.findall(r"^\s*run_effective_handler_restore\s*$", text, re.MULTILINE)) == 2
    assert len(re.findall(r"^\s*check-effective-handlers \\$", text, re.MULTILINE)) == 1


def test_the_restore_follows_the_compatibility_check() -> None:
    text = _layer2()
    for start in (text.index(_FAST_PATH_START), text.index(_STEP_6)):
        assert _call(text, _COMPAT, start) < _call(text, _RESTORE, start)


def _layer2_harness(tmp_path: Path, python_body: str, caller: str) -> tuple[Path, Path, Path]:
    """A script that sources only the restore function, with a stub interpreter."""
    stub = tmp_path / "python"
    stub.write_text(f"#!/bin/bash\necho \"$@\" >> '{tmp_path}/calls'\n{python_body}\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    config = tmp_path / "hooks-daemon.yaml"
    config.write_text("version: 1\n")
    handoff_dir = tmp_path / "handoff"
    handoff_dir.mkdir()
    harness = tmp_path / "harness.sh"
    harness.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        'print_info() { echo "INFO: $*"; }\n'
        'print_warning() { echo "WARN: $*"; }\n'
        '_target_release() { echo "v3.0.0"; }\n'
        f'VENV_PYTHON="{stub}"\n'
        f'TARGET_CONFIG="{config}"\n'
        'CURRENT_VERSION="2.9.0"\n'
        f'UPGRADE_CALLER="{caller}"\n'
        f'HANDOFF_DIR="{handoff_dir}"\n'
        f"{_function(_layer2(), _RESTORE)}\n"
        f"{_RESTORE}\n"
        "echo FINISHED\n"
    )
    return harness, handoff_dir, tmp_path / "calls"


def test_the_function_applies_the_restore_and_hands_the_report_to_layer1(tmp_path: Path) -> None:
    harness, handoff_dir, calls = _layer2_harness(
        tmp_path, f"printf '%s' '{_RESTORED_TEXT}'\nexit 1", "layer1"
    )
    result = subprocess.run(["bash", str(harness)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "handler(s) RESTORED" in result.stdout
    assert "FINISHED" in result.stdout
    argv = calls.read_text()
    assert "check-effective-handlers" in argv
    assert "--apply" in argv
    assert "--from 2.9.0" in argv
    assert "--to 3.0.0" in argv
    assert (handoff_dir / "restored-handlers").read_text() == _RESTORED_TEXT


def test_a_direct_call_has_no_layer1_to_hand_a_report_to(tmp_path: Path) -> None:
    harness, handoff_dir, _ = _layer2_harness(
        tmp_path, f"printf '%s' '{_RESTORED_TEXT}'\nexit 1", "direct"
    )
    result = subprocess.run(["bash", str(harness)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "handler(s) RESTORED" in result.stdout
    assert not (handoff_dir / "restored-handlers").exists()


def test_stops_that_were_not_restored_leave_the_report_to_layer1(tmp_path: Path) -> None:
    harness, handoff_dir, _ = _layer2_harness(
        tmp_path, f"printf '%s' '{_STOPS_TEXT}'\nexit 1", "layer1"
    )
    result = subprocess.run(["bash", str(harness)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert not (handoff_dir / "restored-handlers").exists()


def test_an_older_target_without_apply_does_not_stop_the_upgrade(tmp_path: Path) -> None:
    harness, handoff_dir, _ = _layer2_harness(
        tmp_path, "echo 'unrecognized arguments'\nexit 2", "layer1"
    )
    result = subprocess.run(["bash", str(harness)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "FINISHED" in result.stdout
    assert not (handoff_dir / "restored-handlers").exists()


def test_a_crashed_restore_is_reported_and_the_upgrade_continues(tmp_path: Path) -> None:
    harness, _, _ = _layer2_harness(tmp_path, "echo 'Traceback'\nexit 7", "layer1")
    result = subprocess.run(["bash", str(harness)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "WARN:" in result.stdout
    assert "exit 7" in result.stdout
    assert "FINISHED" in result.stdout


def test_an_unknown_previous_version_skips_the_restore(tmp_path: Path) -> None:
    harness, _, calls = _layer2_harness(tmp_path, "exit 0", "layer1")
    harness.write_text(
        harness.read_text().replace('CURRENT_VERSION="2.9.0"', 'CURRENT_VERSION="unknown"')
    )
    result = subprocess.run(["bash", str(harness)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert not calls.exists()


def _layer1_block() -> str:
    text = _LAYER1.read_text(encoding="utf-8")
    return text[text.index(_L1_START) : text.index(_L1_END)]


def _run_layer1_block(
    tmp_path: Path, python_body: str, handed_over: str | None
) -> subprocess.CompletedProcess[str]:
    stub = tmp_path / "python"
    stub.write_text(f"#!/bin/bash\necho \"$@\" >> '{tmp_path}/calls'\n{python_body}\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    handoff_dir = tmp_path / "handoff"
    handoff_dir.mkdir()
    if handed_over is not None:
        (handoff_dir / "restored-handlers").write_text(handed_over)
    harness = tmp_path / "layer1.sh"
    harness.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        '_info() { echo "INFO: $*"; }\n'
        '_warn() { echo "WARN: $*"; }\n'
        '_ok() { echo "OK: $*"; }\n'
        '_BOLD=""\n_NC=""\n'
        'FROM_VERSION="v2.9.0"\nTARGET_SEMVER="v3.0.0"\nTARGET_DISPLAY="v3.0.0"\n'
        f'_metadata_venv_python="{stub}"\n'
        f'_metadata_config_file="{tmp_path}/hooks-daemon.yaml"\n'
        '_metadata_config_summary="no config changes"\n'
        f'_HANDOFF_DIR="{handoff_dir}"\n'
        f"{_layer1_block()}\n"
        'echo "SUMMARY: $_metadata_config_summary"\n'
        'echo "CHANGES: $_metadata_handler_changes"\n'
    )
    return subprocess.run(["bash", str(harness)], capture_output=True, text=True, check=False)


def test_layer1_does_not_ask_for_a_restart_after_a_restore_that_preceded_it(tmp_path: Path) -> None:
    # After the Layer 2 restore the config already has the handlers on, so
    # Layer 1's own check finds nothing left to restore.
    result = _run_layer1_block(tmp_path, "exit 0", handed_over=_RESTORED_TEXT)
    assert result.returncode == 0, result.stderr
    assert "RESTART THE DAEMON" not in result.stdout
    assert "handler(s) RESTORED" in result.stdout
    assert "some_handler" in result.stdout
    assert "restored:handlers.pre_tool_use.some_handler" in result.stdout
    assert "before the daemon was restarted" in result.stdout


def test_layer1_keeps_the_stops_it_finds_besides_the_early_restore(tmp_path: Path) -> None:
    result = _run_layer1_block(tmp_path, f"printf '%s' '{_STOPS_TEXT}'\nexit 1", _RESTORED_TEXT)
    assert "RESTART THE DAEMON" not in result.stdout
    assert (
        "restored:handlers.pre_tool_use.some_handler,stops:handlers.pre_tool_use.other_handler"
        in (result.stdout)
    )


def test_an_older_layer2_keeps_layer1_applying_and_asking_for_a_restart(tmp_path: Path) -> None:
    result = _run_layer1_block(
        tmp_path, f"printf '%s' '{_RESTORED_TEXT}'\nexit 1", handed_over=None
    )
    assert result.returncode == 0, result.stderr
    assert "--apply" in (tmp_path / "calls").read_text()
    assert "RESTART THE DAEMON" in result.stdout


def test_a_target_without_apply_keeps_the_report_only_fallback(tmp_path: Path) -> None:
    body = (
        'case "$*" in *--apply*) echo "unrecognized arguments"; exit 2;; esac\n'
        f"printf '%s' '{_STOPS_TEXT}'\nexit 1"
    )
    result = _run_layer1_block(tmp_path, body, handed_over=None)
    assert "other_handler" in result.stdout
    assert "RESTART THE DAEMON" not in result.stdout
