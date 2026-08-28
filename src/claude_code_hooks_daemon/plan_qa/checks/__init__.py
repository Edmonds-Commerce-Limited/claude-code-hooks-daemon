"""Plan QA check catalogue — one module per check, registered declaratively.

Each check module exposes a ``CHECK: CheckSpec`` constant, or ``CHECKS`` (a
COMMIT + SWEEP pair sharing one run function) for the cross-file tree checks
— that dual registration is how the plan's ``full-tree-consistency`` is
realised: the sweep evaluates the same invariants the commit gate enforces.
``index_row_length`` extends the same idea to three surfaces, adding an EDIT
registration so the rule also has a fast loop (Plan 00218).
:func:`all_checks` assembles the registry consumed by
:func:`plan_qa.runner.run_stage`; the catalogue is therefore greppable and
documentation can be generated from it.
"""

from claude_code_hooks_daemon.plan_qa.checks import (
    archive_immutability,
    archived_status_coherence,
    claim_spotcheck_queue,
    counter_sanity,
    dormant_honesty,
    header_body_coherence,
    index_at_birth,
    index_no_log,
    index_row_length,
    journal_append_only,
    journal_completion_entry,
    journal_dayfile_is_today,
    journal_dayfile_naming,
    journal_entry_with_progress,
    journal_folder_present,
    journal_freshness,
    location_status_coherence,
    no_new_collisions,
    path_existence,
    plan_doc_size,
    plan_ref_format,
    plan_shrink_without_journal,
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
        # Document-level rules — dual EDIT + SWEEP registration (Plan 00230).
        # The sweep half is what examines plans already on disk; without it a
        # violation predating the rule is never looked at again.
        *status_line_present.CHECKS,
        *status_enum_and_date.CHECKS,
        *header_body_coherence.CHECKS,
        *task_grammar.CHECKS,
        *path_existence.CHECKS,
        *journal_dayfile_naming.CHECKS,
        # Stage 1 — checks about the ACT OF WRITING, with no batch equivalent
        # by design (see common.WRITE_ACT_ONLY_RULES for the reason each).
        template_metadata.CHECK,
        terminal_placement_hint.CHECK,
        archive_immutability.CHECK,
        plan_doc_size.CHECK,
        journal_dayfile_is_today.CHECK,
        journal_append_only.CHECK,
        # Cross-file tree checks — dual COMMIT + SWEEP registration
        *no_new_collisions.CHECKS,
        *row_folder_bijection.CHECKS,
        *stats_recount.CHECKS,
        *structure_archive_dirs.CHECKS,
        *location_status_coherence.CHECKS,
        # Plan-index shape — EDIT + COMMIT + SWEEP (Plan 00218)
        *index_row_length.CHECKS,
        *index_no_log.CHECKS,
        # Stage 2 — commit-gate-only checks
        index_at_birth.CHECK,
        counter_sanity.CHECK,
        terminal_state_atomic.CHECK,
        archived_status_coherence.CHECK,
        same_commit_plan_doc.CHECK,
        plan_ref_format.CHECK,
        journal_entry_with_progress.CHECK,
        journal_completion_entry.CHECK,
        plan_shrink_without_journal.CHECK,
        # Stage 3 — sweep-only checks
        staleness_nag.CHECK,
        dormant_honesty.CHECK,
        claim_spotcheck_queue.CHECK,
        journal_folder_present.CHECK,
        journal_freshness.CHECK,
    )
