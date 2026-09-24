"""Where Layer 2 runs its pre-deploy phase (Plan 00376 Tasks 1.1, 1.2 and 3.1).

The cheap, always-run half of ``test_upgrade_pre_deploy_phase_runs_on_layer1``
(which drives a real upgrade and is marked slow). Both routes into
``upgrade_version.sh`` must:

- call ``run_pre_deploy_phase`` -- the gate -- once the target is checked out
  and BEFORE ``ensure_venv`` rebuilds the venv for it, so that a stop leaves
  nothing to undo but the checkout;
- call the report-only config compatibility check once the target's venv is
  verified and before the first deploy.

The gate reads ``--skip-reading-confirmation=<digest>`` from the arguments, or
from ``UPGRADE_FLAGS`` when a genuine Layer 1 handed over, and never asks
whether a terminal is attached; its stop codes in bash are the ones the Python
gate returns; and no environment variable switches it off.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.install.upgrade_gate import SKIP_READING_FLAG, GateVerdict

_LAYER2: Final[Path] = Path(__file__).resolve().parents[2] / "scripts" / "upgrade_version.sh"
_GATE: Final[str] = "run_pre_deploy_phase"
_COMPAT: Final[str] = "run_config_compatibility_check"
_FAST_PATH_START: Final[str] = "Running idempotent deployment steps"
_ENSURE_VENV: Final[str] = "VENV_PATH=$(ensure_venv "
_VERIFY_VENV: Final[str] = 'verify_venv "$VENV_PYTHON"'
_FIRST_DEPLOY: Final[str] = 'deploy_all_hooks "$PROJECT_ROOT"'
_STEP_6: Final[str] = 'log_step "6"'
_STEP_8: Final[str] = 'log_step "8"'


def _script() -> str:
    return _LAYER2.read_text(encoding="utf-8")


def _call(text: str, name: str, start: int) -> int:
    match = re.compile(rf"^\s*{name}\s*$", re.MULTILINE).search(text, start)
    assert match is not None, f"{name} is not called after offset {start}"
    return match.start()


def _function_body(text: str, name: str) -> str:
    start = text.index(f"{name}() {{")
    return text[start : text.index("\n}\n", start)]


def test_the_idempotent_path_gates_before_the_venv_and_checks_compat_before_deploying() -> None:
    text = _script()
    fast_path = text.index(_FAST_PATH_START)
    gate = _call(text, _GATE, fast_path)
    compat = _call(text, _COMPAT, fast_path)
    assert gate < text.index(_ENSURE_VENV, fast_path)
    assert text.index(_VERIFY_VENV, fast_path) < compat < text.index(_FIRST_DEPLOY, fast_path)


def test_the_direct_path_gates_after_checkout_and_before_the_venv() -> None:
    text = _script()
    step_6 = text.index(_STEP_6)
    gate = _call(text, _GATE, step_6)
    compat = _call(text, _COMPAT, step_6)
    assert gate < text.index(_ENSURE_VENV, step_6)
    assert text.index(_VERIFY_VENV, step_6) < compat < text.index(_STEP_8)


def test_nothing_checks_compatibility_against_the_pre_checkout_tree() -> None:
    text = _script()
    body = _function_body(text, _COMPAT)
    assert "CompatibilityChecker" in body
    assert "CompatibilityChecker" not in text.replace(body, "")


def test_the_gate_honours_the_flag_and_never_infers_from_a_terminal() -> None:
    text = _script()
    assert SKIP_READING_FLAG in text
    assert "UPGRADE_FLAGS" in text
    body = _function_body(text, _GATE)
    assert "upgrade_gate_standalone.py" in body
    assert "-t 0" not in text, "a TTY test would disarm the gate for every agent"


def test_the_bash_stop_codes_are_the_gates_own() -> None:
    text = _script()
    for name, verdict in (
        ("GATE_NEEDS_ACKNOWLEDGEMENT", GateVerdict.NEEDS_ACKNOWLEDGEMENT),
        ("GATE_NEEDS_APPROVAL", GateVerdict.NEEDS_APPROVAL),
    ):
        assert re.search(rf"^{name}={verdict.exit_code}$", text, re.MULTILINE), name


def test_a_stop_restores_the_installed_version_not_a_handed_over_ref() -> None:
    """Review MAJOR 1/2: the restore target is what is installed, on every route."""
    text = _script()
    body = _function_body(text, "abort_before_deploy")
    assert "_restore_target" in body
    assert "reset --hard" in body
    restore = _function_body(text, "_restore_target")
    assert "INSTALLED_VERSION" in restore
    assert "_installed_release_from_docs" in restore
    assert "HOOKS_DAEMON_UPGRADE_PREVIOUS_REF" not in text


def test_the_gate_reads_the_installed_version_not_the_checkouts() -> None:
    body = _function_body(_script(), _GATE)
    assert '--installed-stamp "$INSTALLED_VERSION"' in body
    assert '--target-stamp "$INSTALL_STAMP"' in body
    assert "--from" not in body


def test_no_environment_variable_switches_the_gate_off() -> None:
    """Review MAJOR 4: the exported phase-done sentinel turned the whole gate off."""
    text = _script()
    assert "HOOKS_DAEMON_PRE_DEPLOY_PHASE_DONE" not in text
    body = _function_body(text, _GATE)
    assert not re.search(r"^\s*if \[ -n \"\$\{HOOKS_DAEMON_\w+", body, re.MULTILINE), body


def test_the_gate_runs_under_a_timeout_and_a_zero_exit_needs_its_verdict() -> None:
    body = _function_body(_script(), _GATE)
    assert 'timeout "$GATE_TIMEOUT_SECONDS"' in body
    assert "gate-verdict=proceed" in body


def test_the_used_approval_is_removed_only_on_success_on_both_paths() -> None:
    text = _script()
    calls = [m.start() for m in re.finditer(r"^\s*consume_used_approval\s*$", text, re.MULTILINE)]
    assert len(calls) == 2, calls
    fast_path_exit = text.index("exit 0\nfi", text.index(_FAST_PATH_START))
    assert calls[0] < fast_path_exit
    assert calls[1] > text.index('log_step "17"')


def test_the_layer1_handoff_is_a_file_bound_to_the_parent_process() -> None:
    body = _function_body(_script(), "_read_handoff")
    assert '"$PPID"' in body
    assert "-O" in body
    assert 'rm -f -- "$path"' in body
