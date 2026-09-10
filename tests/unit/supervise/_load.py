"""Loader for the standalone `.claude/ccy/claude-supervise.py` script.

The script deliberately lives outside `src/` and has no `.py`-package
identity (its filename contains a hyphen), so it cannot be imported with a
normal `import` statement. It is loaded here via `importlib` so the test
suite can exercise it directly, in-process, exactly as `mypy`/`ruff`/pytest
coverage do.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from types import ModuleType

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / ".claude" / "ccy" / "claude-supervise.py"
_MODULE_NAME = "claude_supervise_standalone"


def load_supervisor_module() -> ModuleType:
    """Load (or return the already-loaded) standalone supervisor module."""
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]

    spec = importlib.util.spec_from_file_location(_MODULE_NAME, _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {_SCRIPT_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


SCRIPT_PATH = _SCRIPT_PATH


class SupervisorTickOutcome(Protocol):
    """Structural type for a `TickOutcome` instance from the loaded module.

    `load_supervisor_module` returns a `ModuleType`, so `_mod.decide_once(...)`
    is typed `Any` by pyright -- assignable to any Protocol. A test helper that
    hands a decision back to its caller annotates its return type with this
    Protocol instead of the too-wide `object`, so the fields tests assert on
    (``decision_value``, ``payload``, ...) stay checked rather than opaque.
    """

    decision_value: str
    reason: str
    payload: str | None
    submit: bool
    consume_signal_path: str | None
    deferred_log: str | None
    noop_reason_log: str | None
    confirm_enters: int
    model_switch_family: str | None
    model_switch_session: str | None
    audit_flush_log: str | None


class SupervisorStateMachine(Protocol):
    """Structural type for a `CompactStateMachine` instance from the loaded module.

    See `SupervisorTickOutcome` for why a Protocol is needed at all.
    """

    @property
    def coupled_effort_pending(self) -> str | None: ...

    @property
    def audit_pending(self) -> tuple[str, ...]: ...

    def export_state(self) -> dict[str, object]: ...

    def import_state(self, state: dict[str, object]) -> None: ...

    def note_manual_effort_command(self, level: str, *, now_wall: float) -> None: ...

    def arm_coupled_effort(self, *, session: str, family: str) -> None: ...

    def arm_audit(self, item: str) -> None: ...

    def mark_effort_injection(self, now_wall: float | None = None) -> None: ...

    def mark_audit_injection(self) -> None: ...

    def mark_model_restore(
        self,
        now_wall: float | None = None,
        *,
        family: str | None = None,
        session: str | None = None,
    ) -> None: ...
