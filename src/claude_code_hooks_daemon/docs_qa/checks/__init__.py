"""Docs QA check catalogue — one module per check, registered declaratively.

Mirrors :mod:`claude_code_hooks_daemon.plan_qa.checks`. :func:`all_checks`
assembles the registry consumed by :func:`docs_qa.runner.run_stage`.
"""

from claude_code_hooks_daemon.docs_qa.checks import (
    at_import_census,
    generated_doc_hand_edit,
    module_doc_budget,
    plan_promotion_disposition,
    pointer_resolves,
    quote_drift,
    quote_source_stale,
    rules_file_orphan_shrink,
    rules_file_shape,
)
from claude_code_hooks_daemon.docs_qa.types import CheckSpec


def all_checks() -> tuple[CheckSpec, ...]:
    """The full registered docs QA check catalogue (Plan 00284)."""
    return (
        *pointer_resolves.CHECKS,
        *generated_doc_hand_edit.CHECKS,
        *rules_file_shape.CHECKS,
        *quote_drift.CHECKS,
        *quote_source_stale.CHECKS,
        *rules_file_orphan_shrink.CHECKS,
        *plan_promotion_disposition.CHECKS,
        *at_import_census.CHECKS,
        *module_doc_budget.CHECKS,
    )
