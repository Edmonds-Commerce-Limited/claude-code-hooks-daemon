"""Docs QA check catalogue — one module per check, registered declaratively.

Mirrors :mod:`claude_code_hooks_daemon.plan_qa.checks`. :func:`all_checks`
assembles the registry consumed by :func:`docs_qa.runner.run_stage`.
"""

from claude_code_hooks_daemon.docs_qa.checks import pointer_resolves
from claude_code_hooks_daemon.docs_qa.types import CheckSpec


def all_checks() -> tuple[CheckSpec, ...]:
    """The full registered docs QA check catalogue (Plan 00284)."""
    return (*pointer_resolves.CHECKS,)
