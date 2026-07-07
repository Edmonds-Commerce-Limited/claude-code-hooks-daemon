"""Plan QA check catalogue — one module per check, registered declaratively.

Each check module exposes a ``CHECK: CheckSpec`` constant, or ``CHECKS`` (a
COMMIT + SWEEP pair sharing one run function) for the cross-file tree checks
— that dual registration is how the plan's ``full-tree-consistency`` is
realised: the sweep evaluates the same invariants the commit gate enforces.
:func:`all_checks` assembles the registry consumed by
:func:`plan_qa.runner.run_stage`; the catalogue is therefore greppable and
documentation can be generated from it.
"""

from claude_code_hooks_daemon.plan_qa.checks import (
    archive_immutability,
    claim_spotcheck_queue,
    counter_sanity,
    dormant_honesty,
    header_body_coherence,
    index_at_birth,
    location_status_coherence,
    no_new_collisions,
    path_existence,
    plan_ref_format,
    row_folder_bijection,
    same_commit_plan_doc,
    staleness_nag,
    stats_recount,
    status_enum_and_date,
    status_line_present,
    structure_archive_dirs,
    task_grammar,
    template_metadata,
    terminal_placement_hint,
    terminal_state_atomic,
)
from claude_code_hooks_daemon.plan_qa.types import CheckSpec


def all_checks() -> tuple[CheckSpec, ...]:
    """The full registered check catalogue (Plan 00144)."""
    return (
        # Stage 1 — edit-time single-file checks
        status_line_present.CHECK,
        status_enum_and_date.CHECK,
        header_body_coherence.CHECK,
        template_metadata.CHECK,
        task_grammar.CHECK,
        terminal_placement_hint.CHECK,
        archive_immutability.CHECK,
        path_existence.CHECK,
        # Cross-file tree checks — dual COMMIT + SWEEP registration
        *no_new_collisions.CHECKS,
        *row_folder_bijection.CHECKS,
        *stats_recount.CHECKS,
        *structure_archive_dirs.CHECKS,
        *location_status_coherence.CHECKS,
        # Stage 2 — commit-gate-only checks
        index_at_birth.CHECK,
        counter_sanity.CHECK,
        terminal_state_atomic.CHECK,
        same_commit_plan_doc.CHECK,
        plan_ref_format.CHECK,
        # Stage 3 — sweep-only checks
        staleness_nag.CHECK,
        dormant_honesty.CHECK,
        claim_spotcheck_queue.CHECK,
    )
