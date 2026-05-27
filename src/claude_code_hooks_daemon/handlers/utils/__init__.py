"""Utility functions for handlers."""

from claude_code_hooks_daemon.handlers.utils.plan_numbering import (
    get_next_plan_number,
    highest_plan_number,
    next_plan_number_for_target,
    read_plan_counter,
    record_plan_allocation,
    resolve_plan_repo_root,
    write_plan_counter,
)

__all__ = [
    "get_next_plan_number",
    "highest_plan_number",
    "next_plan_number_for_target",
    "read_plan_counter",
    "record_plan_allocation",
    "resolve_plan_repo_root",
    "write_plan_counter",
]
