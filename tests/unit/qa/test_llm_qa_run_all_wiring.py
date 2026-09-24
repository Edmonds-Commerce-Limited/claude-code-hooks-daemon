"""Every check `run_all.sh` runs must also be wired into `llm_qa.py` (N22).

`enforce_llm_qa` denies a direct `run_all.sh` invocation by an agent and
points at `./scripts/qa/llm_qa.py all` instead, so `llm_qa.py`'s
`TOOL_REGISTRY` is the suite every agent actually runs and reports as "full
QA N/N". `run_all.sh` remains the human-at-a-terminal entry point and is the
documented source of truth for which checks exist (`CLAUDE/QA.md`). When a
check is added to one but not the other, an agent's "full QA" silently stops
covering it — this is exactly what happened to shellcheck: `run_all.sh` step
8 ran `run_shell_check.sh`, `TOOL_REGISTRY` had no entry for it, and a shell
defect could reach `main` and be caught only by CI, after the merge.

This is a CLASS guard, not a fix for that one instance: it parses every
`"${SCRIPT_DIR}/<script>"` invocation out of `run_all.sh` and asserts each
has a `TOOL_REGISTRY` entry running that same script — or is named, with a
reason, in `_KNOWN_GAPS` below. The direction is one-way: a `TOOL_REGISTRY`
tool that `run_all.sh` does not invoke (e.g. `smoke_test`, which probes the
live daemon and is deliberately absent from the static `run_all.sh` suite) is
not this guard's concern.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUN_ALL_SH = PROJECT_ROOT / "scripts" / "qa" / "run_all.sh"

# Scripts run_all.sh invokes that carry NO matching TOOL_REGISTRY entry, each
# with a reason. Empty today: every script run_all.sh invokes is registered.
# A script landing here without huge scrutiny defeats the point of this test.
_KNOWN_GAPS: dict[str, str] = {}

# `"${SCRIPT_DIR}/check_magic_values.py"`, `"${SCRIPT_DIR}/run_format_check.sh"`
# — the two shapes every invocation in run_all.sh takes.
_SCRIPT_DIR_INVOCATION = re.compile(r"\$\{SCRIPT_DIR\}/([A-Za-z0-9_.]+\.(?:py|sh))")


def _load_llm_qa() -> Any:
    """Import `scripts/qa/llm_qa.py`, which is a script rather than a module."""
    module_path = PROJECT_ROOT / "scripts" / "qa" / "llm_qa.py"
    spec = importlib.util.spec_from_file_location("llm_qa_run_all_wiring_under_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


llm_qa = _load_llm_qa()


def _scripts_run_all_invokes() -> set[str]:
    """Every script basename `run_all.sh` runs, parsed from its own source."""
    text = RUN_ALL_SH.read_text(encoding="utf-8")
    return set(_SCRIPT_DIR_INVOCATION.findall(text))


def _scripts_registered_in_llm_qa() -> set[str]:
    """Every script basename a `TOOL_REGISTRY` entry runs.

    Bound to the SAME `SCRIPTS_DIR` the registry itself resolves commands
    against, rather than a re-derived path, so this cannot silently stop
    matching if that constant ever moves.
    """
    scripts_dir = str(llm_qa.SCRIPTS_DIR)
    names: set[str] = set()
    for config in llm_qa.TOOL_REGISTRY.values():
        for part in config.command:
            if part.startswith(scripts_dir):
                names.add(Path(part).name)
                break
    return names


class TestEveryRunAllScriptIsRegistered:
    """The class guard: run_all.sh's invocations are a subset of the registry."""

    def test_run_all_actually_invokes_scripts(self) -> None:
        """Sanity check on the parse itself — a regex that matched nothing
        would make the real assertion vacuously true."""
        assert len(_scripts_run_all_invokes()) >= 25

    def test_every_invoked_script_is_registered_or_a_known_gap(self) -> None:
        invoked = _scripts_run_all_invokes()
        registered = _scripts_registered_in_llm_qa()
        unaccounted = invoked - registered - set(_KNOWN_GAPS)
        assert not unaccounted, (
            f"run_all.sh invokes {sorted(unaccounted)} but llm_qa.py's "
            "TOOL_REGISTRY has no entry running them (and _KNOWN_GAPS does "
            "not name them with a reason) — an agent's 'full QA' silently "
            "skips these checks. Add a ToolConfig entry, or add a reasoned "
            "_KNOWN_GAPS entry if the omission is deliberate."
        )

    def test_known_gaps_are_still_actually_gaps(self) -> None:
        """A stale `_KNOWN_GAPS` entry (fixed but never removed) hides a
        script that IS registered from ever being checked again."""
        registered = _scripts_registered_in_llm_qa()
        stale = set(_KNOWN_GAPS) & registered
        assert not stale, f"{sorted(stale)} are now registered — remove from _KNOWN_GAPS"

    def test_shell_check_is_registered(self) -> None:
        """The concrete instance (N22): shellcheck must run under 'full QA'."""
        assert "run_shell_check.sh" in _scripts_registered_in_llm_qa()
        assert "shell_check" in llm_qa.TOOL_REGISTRY
        assert "shell_check" in llm_qa.SUMMARIZERS
