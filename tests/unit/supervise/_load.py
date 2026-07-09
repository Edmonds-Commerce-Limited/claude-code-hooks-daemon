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
from typing import TYPE_CHECKING

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
