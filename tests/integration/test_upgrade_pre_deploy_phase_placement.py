"""Where Layer 2 runs its pre-deploy phase (Plan 00376 Tasks 1.1, 1.2 and 3.1).

The cheap, always-run half of ``test_upgrade_pre_deploy_phase_runs_on_layer1``
(which drives a real upgrade and is marked slow). Both routes into
``upgrade_version.sh`` must:

- call ``run_pre_deploy_phase`` -- the gate -- once the target is checked out
  and BEFORE ``ensure_venv`` rebuilds the venv for it, so that a stop leaves
  nothing to undo but the checkout;
- call the report-only config compatibility check once the target's venv is
  verified and before the first deploy.

The gate reads ``--skip-reading-confirmation`` from the arguments or
``UPGRADE_FLAGS`` and never asks whether a terminal is attached, and its
stop codes in bash are the ones the Python gate returns.
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


def test_a_stop_on_the_idempotent_path_restores_the_previous_ref() -> None:
    body = _function_body(_script(), "abort_before_deploy")
    assert "HOOKS_DAEMON_UPGRADE_PREVIOUS_REF" in body
    assert "reset --hard" in body
