"""A handler with a configurable advisory mode must not be terminal.

The PreToolUse chain breaks on ANY terminal match, whatever that handler
decided (``core/chain.py``). So a terminal handler that returns ALLOW does not
merely decline to act — it ends dispatch and silently disables every handler
with a higher priority number for that tool call. Nothing reports it: a
shadowed handler and one that never matched look identical from outside.

``Handler.__init__`` defaults ``terminal=True``, so this is the shape a
handler acquires by saying nothing.

WHY THIS RULE, AND NOT THE BROADER ONE
--------------------------------------
The obvious guard — "no terminal handler may return a non-restrictive
decision" — was tried first and discarded. It flagged 23 handlers, because
most blocking handlers carry a defensive ``allow`` in ``handle()`` that
``matches()`` makes unreachable; ``destructive_git`` and ``sudo_pip`` are
terminal quite legitimately. A guard that fails on 23 handlers on day one is
disabled within a day, which buys nothing.

A configurable warn/advisory MODE is the property that actually separates a
DESIGNED allow from a defensive one. A handler offering ``mode: warn`` will
return ALLOW as a normal outcome, so it must never be terminal. That rule
matched exactly the four handlers that had the defect and no others.

A non-terminal DENY is not a weaker deny: ``core/chain.py`` keeps the most
restrictive decision seen, so a later advisory ALLOW cannot wash it out (the
Plan 00144 regression). ``plan_qa_edit`` already ships blocking and
non-terminal.

Complements ``test_stop_chain_terminal_shadowing.py``, which pins ORDERING on
the Stop chain. This pins ENTITLEMENT on PreToolUse.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_HANDLER_DIR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "claude_code_hooks_daemon"
    / "handlers"
    / "pre_tool_use"
)

_MODE_ATTRIBUTE = "_mode"


def _assigns_mode(tree: ast.AST) -> bool:
    """True when the module assigns ``self._mode`` — a configurable mode."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and target.attr == _MODE_ATTRIBUTE
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                return True
    return False


def _declares_non_terminal(tree: ast.AST) -> bool:
    """True when a ``super().__init__`` call passes ``terminal=False``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "__init__"):
            continue
        for kw in node.keywords:
            if kw.arg == "terminal" and isinstance(kw.value, ast.Constant):
                return kw.value.value is False
    return False


def test_advisory_mode_handlers_are_not_terminal() -> None:
    """A handler offering `mode: warn` returns ALLOW by design, so it cannot be terminal."""
    offenders: list[str] = []
    inspected: list[str] = []

    for path in sorted(_HANDLER_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not _assigns_mode(tree):
            continue
        inspected.append(path.name)
        if not _declares_non_terminal(tree):
            offenders.append(path.name)

    assert inspected, (
        "No handler with a configurable mode was found. This guard has lost "
        "its grip on the codebase -- check whether the mode attribute was "
        f"renamed from self.{_MODE_ATTRIBUTE}."
    )
    assert not offenders, (
        "These PreToolUse handlers offer a configurable advisory mode but are "
        "TERMINAL, so whenever that mode returns ALLOW they end the chain and "
        "silently disable every higher-priority-number handler for that tool "
        "call:\n  " + "\n  ".join(offenders) + "\n\nPass terminal=False to "
        "super().__init__(). Denying is unaffected: core/chain.py keeps the "
        "most restrictive decision seen."
    )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
