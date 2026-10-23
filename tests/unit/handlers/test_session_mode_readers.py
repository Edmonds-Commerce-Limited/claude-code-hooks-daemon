"""No handler reads session-mode state unless it is declared here (Plan 00501).

A session mode halts work-DRIVING machinery and never a guard. The chain's
autonomy gate enforces that for the declared drivers without any handler
reading a mode. This file holds the static half: every handler module that
reaches the mode state directly (the session-modes registry, the composed
policy, the autonomy verdict that carries it, the mode modules, or the
usage-pause record) must be in :data:`MODE_READERS` with the reason it reads
it. A guard that starts depending on a mode therefore fails here first, and
must be argued into the inventory in review.

The tool-call guards are held tighter still: the only PreToolUse handler that
reads any mode state is the usage-pause tool gate, and it reads the usage-pause
record alone, never the registry or the policy.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import claude_code_hooks_daemon.handlers as handlers_package

HANDLERS_ROOT: Final[Path] = Path(handlers_package.__file__).resolve().parent

_PACKAGE: Final[str] = "claude_code_hooks_daemon."

#: Modules that ARE the registry/policy state or decide from it.
REGISTRY_MODULES: Final[frozenset[str]] = frozenset(
    _PACKAGE + name
    for name in (
        "utils.session_modes",
        "utils.autonomy",
        "core.session_mode_registry",
        "core.focus_mode",
        "core.manual_goals",
        "core.goal_loop_block",
        "core.session_mode_statement",
    )
)

#: Accessors that read the registry or the policy built from it.
REGISTRY_NAMES: Final[frozenset[str]] = frozenset(
    {
        "session_modes",
        "session_policy",
        "autonomy_verdict",
        "autonomy_allowed",
        "SessionPolicy",
        "SessionModeRegistry",
        "displayed_policy",
    }
)

#: The usage-pause record: its own store, not the registry (``SessionMode.registry_owned``).
USAGE_PAUSE_MODULES: Final[frozenset[str]] = frozenset(
    {_PACKAGE + "utils.usage_pause", _PACKAGE + "utils.usage_pause_gate"}
)
USAGE_PAUSE_NAMES: Final[frozenset[str]] = frozenset(
    {"is_usage_paused", "hook_is_usage_paused", "active_usage_pause"}
)

#: Every handler module that reads mode state, relative to the handlers package.
MODE_READERS: Final[dict[str, str]] = {
    "post_tool_use/background_process_tracker.py": (
        "advisory: picks the protective wording where autonomy is off"
    ),
    "post_tool_use/goal_injection.py": "driver: writes no goal intent under manual-goals",
    "post_tool_use/recovery_cron_advisor.py": "driver: no cron advice while usage-paused",
    "pre_tool_use/usage_pause_tool_gate.py": "the usage-paused mode's own tool gate",
    "session_start/autonomy_notice.py": "states the autonomy verdict at session start",
    "session_start/failsafe_cron_session_advisor.py": "driver: no cron while usage-paused",
    "session_start/persistent_cron_assertor.py": "driver: no cron while usage-paused",
    "status_line/environment_indicator.py": "displays the autonomy verdict",
    "status_line/session_mode_indicator.py": "displays the session's modes",
    "status_line/usage_indicator.py": "displays the usage pause",
    "stop/auto_continue_stop.py": "drives continuation; enters awaiting-human",
    "stop/cron_stop_enforcer.py": "driver: no cron demand while usage-paused",
    "stop/goal_loop_detector.py": "enters goal-blocked",
    "stop/idle_workable_issue_stop_gate.py": (
        "work-driving stop gate: stands aside for a blocked or paused session"
    ),
    "stop/usage_pause_stop_gate.py": "the usage-paused mode's own stop gate",
    "subagent_stop/cron_subagent_stop_enforcer.py": "driver: no cron demand while usage-paused",
    "user_prompt_submit/failsafe_cron_blockage_suppressor.py": "drops ticks per the mode policy",
    "user_prompt_submit/focus_mode_trigger.py": "enters and ends focus and manual-goals",
    "user_prompt_submit/usage_pause_gate.py": "enters usage-paused",
}

_PRE_TOOL_USE_READERS: Final[frozenset[str]] = frozenset({"pre_tool_use/usage_pause_tool_gate.py"})


def _reads(path: Path, modules: frozenset[str], names: frozenset[str]) -> set[str]:
    """The accessors of ``modules``/``names`` that ``path`` imports or references."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module in modules:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name in modules)
        elif isinstance(node, ast.Attribute) and node.attr in names:
            found.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in names:
            found.add(node.id)
    return found


def _modules() -> list[Path]:
    return sorted(HANDLERS_ROOT.rglob("*.py"))


def _relative(path: Path) -> str:
    return path.relative_to(HANDLERS_ROOT).as_posix()


def _readers() -> dict[str, set[str]]:
    modules = REGISTRY_MODULES | USAGE_PAUSE_MODULES
    names = REGISTRY_NAMES | USAGE_PAUSE_NAMES
    readers: dict[str, set[str]] = {}
    for path in _modules():
        found = _reads(path, modules, names)
        if found:
            readers[_relative(path)] = found
    return readers


def test_the_scan_sees_the_handler_tree() -> None:
    """Vacuity guard: the scan walks real handler modules."""
    assert len(_modules()) > 100


def test_the_scan_finds_a_known_reader() -> None:
    """Vacuity guard: a module known to read the registry is found by the scan."""
    found = _reads(
        HANDLERS_ROOT / "stop" / "goal_loop_detector.py", REGISTRY_MODULES, REGISTRY_NAMES
    )
    assert "SessionModeRegistry" in found


def test_every_mode_reader_is_declared() -> None:
    """A handler that starts reading a mode must be argued into the inventory."""
    assert set(_readers()) == set(MODE_READERS)


def test_every_declared_reader_names_its_reason() -> None:
    assert all(reason.strip() for reason in MODE_READERS.values())


def test_no_tool_call_guard_reads_a_mode() -> None:
    """Only the usage-pause tool gate, among PreToolUse handlers, reads mode state."""
    pre_tool_use = {name for name in _readers() if name.startswith("pre_tool_use/")}
    assert pre_tool_use == _PRE_TOOL_USE_READERS


def test_the_usage_pause_tool_gate_reads_no_registry_or_policy() -> None:
    """The one PreToolUse reader sees the usage-pause record only."""
    for name in _PRE_TOOL_USE_READERS:
        assert _reads(HANDLERS_ROOT / name, REGISTRY_MODULES, REGISTRY_NAMES) == set()
