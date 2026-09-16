"""Resolving which AST calls reach a ``subprocess`` spawner (Plan 00412).

Shared by every source-tree guard that reasons about spawns, and shared
DELIBERATELY. The knowledge here was won by execution, not by reading: the
first version of `test_git_spawns_are_bounded` hard-coded the name
``subprocess`` and so missed ``import subprocess as sp``, ``from subprocess
import run`` and ``from subprocess import run as launch`` — three ordinary
import idioms, none of them an evasion (Plan 00248 F5).

A second guard that re-derived this would start from the naive version and
inherit exactly those blind spots, while the first stayed correct. That is the
`asymmetric-sibling-protection` class this plan exists to close, and copying
these twenty lines is one of the cheapest ways to create a new member of it —
the register's own note that "deduplication is a way to CREATE a member of this
class" cuts both ways, and the guard against it is a single home, not a careful
copy.

What this module does NOT decide is what makes a spawn acceptable. Each guard
owns its own rule: `test_git_spawns_are_bounded` asks whether argv starts with
``git``, `test_subprocess_spawns_are_bounded` asks whether the call carries a
timeout. Only "is this a spawn at all, under this module's imports" lives here.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import Final, NamedTuple

#: `subprocess` entry points that start a process.
SPAWNING_CALLS: Final[frozenset[str]] = frozenset(
    {"run", "Popen", "call", "check_call", "check_output"}
)

#: The module whose spawners these guards are about.
SUBPROCESS: Final[str] = "subprocess"


class SubprocessBindings(NamedTuple):
    """The local names in one module that reach a `subprocess` spawner.

    Resolved per module rather than assumed from spelling, so a project-local
    ``run`` imported from elsewhere is not mistaken for a spawn.
    """

    #: Names bound to the `subprocess` MODULE — `subprocess`, `sp`, …
    modules: frozenset[str]
    #: LOCAL spawner name -> the `subprocess` name it refers to. A mapping
    #: rather than a set because an aliased import (`run as launch`) otherwise
    #: loses which spawner it is, and `Popen` has to be told from `run`.
    #: Membership tests (`name in bindings.spawners`) read the same either way.
    spawners: Mapping[str, str]


def subprocess_bindings(tree: ast.Module) -> SubprocessBindings:
    """Every local name in ``tree`` that leads to a `subprocess` spawner."""
    modules: set[str] = set()
    spawners: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == SUBPROCESS:
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == SUBPROCESS:
            for alias in node.names:
                if alias.name in SPAWNING_CALLS:
                    spawners[alias.asname or alias.name] = alias.name
    return SubprocessBindings(frozenset(modules), spawners)


def spawner_name(call: ast.Call, bindings: SubprocessBindings) -> str | None:
    """The `subprocess` spawner this call reaches, or None if it reaches none.

    Returns the SPAWNER's own name (``run``, ``Popen``, …) rather than a bool,
    because a guard about boundedness has to tell them apart: `Popen` takes no
    ``timeout`` at construction — its bound is set later at
    ``communicate(timeout=…)`` — so a rule that treated it like `run` would
    report every correctly-bounded `Popen` as a violation.
    """
    func = call.func
    if isinstance(func, ast.Attribute):
        if (
            func.attr in SPAWNING_CALLS
            and isinstance(func.value, ast.Name)
            and func.value.id in bindings.modules
        ):
            return func.attr
        return None
    if isinstance(func, ast.Name):
        return bindings.spawners.get(func.id)
    return None


def is_subprocess_spawn(call: ast.Call, bindings: SubprocessBindings) -> bool:
    """True for a call that reaches a `subprocess` spawner in this module."""
    return spawner_name(call, bindings) is not None
