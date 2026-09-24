"""Where Layer 2 runs its pre-deploy phase (Plan 00376 Task 1.1).

The cheap, always-run half of ``test_upgrade_pre_deploy_phase_runs_on_layer1``
(which drives a real upgrade and is marked slow). Both routes into
``upgrade_version.sh`` must call ``run_pre_deploy_phase`` after the target's
venv is verified and before the first deploy, and nothing may run the
compatibility check or the guide list against the pre-checkout tree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

_LAYER2: Final[Path] = Path(__file__).resolve().parents[2] / "scripts" / "upgrade_version.sh"
_CALL: Final[str] = "\n    run_pre_deploy_phase\n"
_SLOW_PATH_CALL: Final[str] = "\nrun_pre_deploy_phase\n"
_FAST_PATH_START: Final[str] = "Running idempotent deployment steps"
_FIRST_DEPLOY: Final[str] = 'deploy_all_hooks "$PROJECT_ROOT"'
_STEP_6: Final[str] = 'log_step "6"'
_STEP_8: Final[str] = 'log_step "8"'


def _script() -> str:
    return _LAYER2.read_text(encoding="utf-8")


def test_the_idempotent_path_runs_the_phase_before_its_first_deploy() -> None:
    text = _script()
    fast_path = text.index(_FAST_PATH_START)
    call = text.index(_CALL, fast_path)
    assert text.index("verify_venv", fast_path) < call < text.index(_FIRST_DEPLOY, fast_path)


def test_the_direct_path_runs_the_phase_after_checkout_and_before_deploying() -> None:
    text = _script()
    call = text.index(_SLOW_PATH_CALL, text.index(_STEP_6))
    assert call < text.index(_STEP_8)


def test_nothing_checks_compatibility_against_the_pre_checkout_tree() -> None:
    text = _script()
    definition_end = text.index("\n}\n", text.index("run_pre_deploy_phase() {"))
    outside = text[:definition_end].split("run_pre_deploy_phase() {")[0] + text[definition_end:]
    assert "CompatibilityChecker" not in outside
