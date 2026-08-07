"""Plan 00200 Task 6.4 — every DENY-capable handler declares a near-miss ALLOW case.

Placed under tests/integration/ (not tests/unit/daemon/) because it needs a
FULLY instantiated production handler set — library handlers via
HandlerRegistry.discover() plus the project's own handlers via
ProjectHandlerLoader — which requires ProjectContext to be initialised
exactly like test_handler_instantiation.py already does via the
`project_context` fixture.

This is the ENFORCEMENT half of the requirement; the pure detection logic
(find_deny_capable_handlers_without_allow_case) has its own focused unit
tests in tests/unit/daemon/test_playbook_generator_negative_case.py.
"""

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.daemon.playbook_generator import (
    find_deny_capable_handlers_without_allow_case,
)
from claude_code_hooks_daemon.handlers.project_loader import ProjectHandlerLoader
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

# ---------------------------------------------------------------------------
# RATCHET, not permanent cover (Plan 00200 Task 6.4, dated 2026-08-07).
#
# These handlers are DENY-capable but do not yet declare a near-miss ALLOW
# acceptance test. The six false positives that motivated this requirement
# (EnforceLlmQaHandler, destructive_git, pipe_blocker, lsp_enforcement,
# plan_qa_commit_gate, plan_number_helper) are FIXED and are NOT in this set.
#
# The test below asserts EXACT equality against this frozenset in both
# directions: a handler added here without shrinking it elsewhere fails
# loudly (a regression), and a handler fixed without removing its entry ALSO
# fails loudly (so this set can never quietly become permanent cover — see
# CLAUDE.md "Scope discipline" in Plan 00200's originating instructions).
#
# To close one of these: add an AcceptanceTest with expected_decision=ALLOW
# expressing a realistic near-miss command the handler correctly does NOT
# block, then remove the corresponding line below.
# ---------------------------------------------------------------------------
_MISSING_NEGATIVE_CASE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "library:PreToolUse/AbsolutePathHandler",
        "library:PreToolUse/CurlPipeShellHandler",
        "library:PreToolUse/DaemonLocationGuardHandler",
        "library:PreToolUse/DangerousPermissionsHandler",
        "library:PreToolUse/GhIssueCommentsHandler",
        "library:PreToolUse/GhPrCommentsHandler",
        "library:PreToolUse/GitStashHandler",
        "library:PreToolUse/LockFileEditBlockerHandler",
        "library:PreToolUse/MarkdownOrganizationHandler",
        "library:PreToolUse/PipBreakSystemHandler",
        "library:PreToolUse/PlanTimeEstimatesHandler",
        "library:PreToolUse/QaSuppressionHandler",
        "library:PreToolUse/SedBlockerHandler",
        "library:PreToolUse/SudoPipHandler",
        "library:PreToolUse/TddEnforcementHandler",
        "library:PreToolUse/WorktreeFileCopyHandler",
    }
)


def _repo_root() -> Path:
    """Project root, derived from this file's location (not hardcoded)."""
    return Path(__file__).resolve().parents[2]


def _collect_all_acceptance_tests() -> list[dict[str, Any]]:
    """Every acceptance test declared by the REAL production handler set.

    Mirrors what `hooks-daemon generate-playbook` assembles: discovered
    library handlers plus the project's own `.claude/project-handlers/`
    handlers. `include_disabled=True` so a handler disabled by default in
    the shipped config template still has to satisfy the requirement.
    """
    from claude_code_hooks_daemon.daemon.playbook_generator import PlaybookGenerator

    registry = HandlerRegistry()
    registry.discover()

    project_handlers_path = _repo_root() / ".claude" / "project-handlers"
    project_handlers = [
        handler
        for _event_type, handler in ProjectHandlerLoader.discover_handlers(project_handlers_path)
    ]

    generator = PlaybookGenerator(
        config={},
        registry=registry,
        project_handlers=project_handlers,
    )
    return generator.generate_json(include_disabled=True)


def test_every_deny_capable_handler_has_a_near_miss_allow_case(project_context: Any) -> None:
    """No DENY-capable handler is missing a negative case beyond the tracked ratchet."""
    tests = _collect_all_acceptance_tests()
    missing = set(find_deny_capable_handlers_without_allow_case(tests))

    newly_missing = missing - _MISSING_NEGATIVE_CASE_ALLOWLIST
    assert not newly_missing, (
        "The following DENY-capable handler(s) are missing a near-miss ALLOW "
        "acceptance test and are NOT in the tracked allowlist — add "
        "AcceptanceTest(expected_decision=Decision.ALLOW, ...) for a realistic "
        "near-miss command, or add the handler to "
        "_MISSING_NEGATIVE_CASE_ALLOWLIST with a dated justification:\n"
        + "\n".join(sorted(newly_missing))
    )

    stale_allowlist_entries = _MISSING_NEGATIVE_CASE_ALLOWLIST - missing
    assert not stale_allowlist_entries, (
        "The following handler(s) are listed in _MISSING_NEGATIVE_CASE_ALLOWLIST "
        "but now declare a near-miss ALLOW case — remove them from the "
        "allowlist so it keeps shrinking instead of becoming permanent cover:\n"
        + "\n".join(sorted(stale_allowlist_entries))
    )


def test_six_regression_handlers_are_not_in_the_allowlist(project_context: Any) -> None:
    """The six false positives that motivated this requirement must stay fixed."""
    fixed_handlers = {
        "library:PreToolUse/DestructiveGitHandler",
        "library:PreToolUse/PipeBlockerHandler",
        "library:PreToolUse/LspEnforcementHandler",
        "library:PreToolUse/PlanNumberHelperHandler",
        "project:Project/EnforceLlmQaHandler",
    }
    assert fixed_handlers.isdisjoint(_MISSING_NEGATIVE_CASE_ALLOWLIST)

    tests = _collect_all_acceptance_tests()
    missing = set(find_deny_capable_handlers_without_allow_case(tests))
    assert fixed_handlers.isdisjoint(missing), (
        "A handler fixed for Plan 00200 Task 6.4 has regressed and no longer "
        f"declares a near-miss ALLOW case: {fixed_handlers & missing}"
    )
