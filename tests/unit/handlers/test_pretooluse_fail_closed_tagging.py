"""Plan 00466 n24 security review, M3: fail-closed must be structural.

`HandlerChain.execute` only fails a call CLOSED on a crash/timeout/saturation
when the handler carries BOTH `HandlerTag.SAFETY` and `HandlerTag.BLOCKING`
(see `chain.py`'s `_record_unjudged`). A PreToolUse handler that CAN deny a
call but was never given both tags silently fails OPEN under exactly the
pressure this project's own N24/N25/N34 work exists to guard against.

Scope (deliberately narrower than "every handler lacking SAFETY+BLOCKING"):
the class below covers handlers with NEITHER tag -- ones nobody had ever
made a fail-closed decision about at all. The review separately found 22
handlers tagged BLOCKING but not SAFETY (`enforce-tdd`,
`qa-suppression-blocker`, `plan-*`, ...): mostly plan/QA/workflow governance
gates where BLOCKING was plausibly a deliberate choice already, not an
oversight -- auditing that bucket one-by-one was deferred as a follow-up
(Plan 00466 N40) rather than rushed alongside this niggle. This test's job
stayed narrower and mechanical: close the "nobody ever decided" gap, and
stop it reopening. `test_every_blocking_without_safety_handler_is_audited`
below is that follow-up, done: every handler in the (live-rescanned, 24-wide
-- see its own comment) bucket is either promoted to SAFETY or recorded with
a reason in `_AUDITED_BLOCKING_ONLY_REASONS`.

This is the OPT-OUT-NOT-OPT-IN registry test the review's M3 direction asks
for: a completely untagged PreToolUse handler whose source can produce a
deny/block decision must be SAFETY+BLOCKING, unless it explicitly declares
`HandlerTag.ADVISORY` -- a deliberate statement that failing open here is an
accepted trade-off (six of the 14 this niggle found, each conditional on a
non-default config value: `bash-safe-mode`, `docs-qa-commit-gate`,
`docs-qa-edit`, `plan-qa-commit-gate`, `staged-lint-gate`,
`verification-result-gate`), not an oversight. The other two of the 14 --
`ask-user-question-blocker` (strict mode, the default, denies
unconditionally) and `validate-instruction-content` (denies unconditionally
whenever a blocked pattern matches, no config gate at all) -- turned out to
deny under a DEFAULT install rather than an opt-in mode, so they were tagged
`HandlerTag.BLOCKING` instead: `test_declared_behaviour_matches_source.py`
(same test tree) independently requires this for any handler whose default
behaviour denies, and ADVISORY there would have understated them in the
generated doc. Both stay out of SAFETY, since neither is a dangerous-action
guard. A new handler that denies and carries neither marker fails this
test, which is the whole point: the reviewer for THAT handler is forced to
make the same call this niggle made for the existing 14, rather than the
gap growing silently.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.registry import (
    BuiltinHandlerRef,
    iter_builtin_handler_classes,
)

_DENY_SIGNALS = ("HookResult.deny", "Decision.DENY", "Decision.BLOCK")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _ensure_project_context() -> None:
    if not ProjectContext.is_initialized():
        ProjectContext.initialize(_project_root() / ".claude" / "hooks-daemon.yaml")


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Some handler constructors resolve project-scoped defaults directly.

    Mirrors ``test_safety_handlers_hostile_input_performance.py``: a handler
    that raises on construction without this would silently drop out of the
    parametrized sweep below rather than fail loudly.
    """
    _ensure_project_context()


def _can_deny(ref: BuiltinHandlerRef) -> bool:
    source = inspect.getsource(ref.handler_cls)
    return any(signal in source for signal in _DENY_SIGNALS)


def _pretooluse_refs() -> list[BuiltinHandlerRef]:
    # Collection-time (parametrize evaluates this at import), same as
    # `_project_context` at test-run-time -- construction below needs it too.
    _ensure_project_context()
    return [ref for ref in iter_builtin_handler_classes() if ref.event_dir == "pre_tool_use"]


def _tags_of(ref: BuiltinHandlerRef) -> set[str]:
    return set(ref.handler_cls().tags)


@pytest.mark.parametrize(
    "ref",
    _pretooluse_refs(),
    ids=lambda ref: ref.config_key,
)
def test_a_denying_untagged_pretooluse_handler_declares_fail_open_or_closed(
    ref: BuiltinHandlerRef,
) -> None:
    if not _can_deny(ref):
        return
    tags = _tags_of(ref)
    if HandlerTag.BLOCKING in tags or HandlerTag.SAFETY in tags:
        # Already has SOME fail-closed-relevant tag: a deliberate past
        # decision, however incomplete -- out of THIS test's narrower scope
        # (see module docstring). Not silently ignored: it is exactly the
        # 22-handler bucket recorded as a follow-up in NIGGLES.md N35.
        return
    is_declared_advisory = HandlerTag.ADVISORY in tags
    assert is_declared_advisory, (
        f"pre_tool_use/{ref.config_key} can deny (matched one of {_DENY_SIGNALS}) but "
        f"carries neither HandlerTag.SAFETY/BLOCKING nor HandlerTag.ADVISORY (tags="
        f"{sorted(tags)!r}). A handler in this state fails OPEN on a "
        "crash/timeout/dispatch-pool-saturation with no one having decided that on "
        "purpose. Either tag it HandlerTag.SAFETY + HandlerTag.BLOCKING, or add "
        "HandlerTag.ADVISORY with a comment explaining why failing open here is "
        "acceptable (Plan 00466 n24 security review, M3)."
    )


def test_the_scope_still_finds_pretooluse_handlers() -> None:
    """A collection-time filtering bug would make every case above vacuous."""
    assert len(_pretooluse_refs()) > 50


# ---------------------------------------------------------------------------
# Plan 00466 N40: the BLOCKING-without-SAFETY bucket, audited (the review's
# own follow-up note above named it "22-handler"; a live scan of the full
# registry -- every event, not only pre_tool_use, since HandlerChain.execute's
# fail-closed logic is generic across events -- found 24 at audit time: the
# 21 pre_tool_use handlers the review named or implied plus 3 more from other
# events (`lint_on_edit`, `subagent_report_path_verifier`,
# `failsafe_cron_blockage_suppressor`) that carry the same tag shape).
#
# Every one of the 24 is a WORKFLOW/QA/GOVERNANCE gate: its consequence on a
# crash/timeout/saturation fail-open is "a step the project asks for did not
# happen" (an unreviewed plan close, an unlinted edit, a missing citation) --
# reversible, visible in the diff/PR, and never itself a destructive,
# security-critical or irreversible ACTION. That is the same bar the
# existing SAFETY roster is drawn at (destructive git, secret disclosure,
# RCE-shaped constructs, write-clobbering, curl-pipe-shell, ...): SAFETY is
# reserved for a handler that is the ONLY thing standing between a tool call
# and a dangerous action, not for "the agent skipped a process step". None of
# the 24 below guards a dangerous action, so none is promoted; each entry
# records the specific reason a reviewer would want, not a copy-pasted one.
_AUDITED_BLOCKING_ONLY_REASONS: dict[str, str] = {
    "lint_on_edit": (
        "PostToolUse: runs AFTER the write already landed on disk. There is no "
        "action left to fail closed on before the fact -- it reports a QA "
        "failure for the agent to fix, the same shape as R-LINT-FAILURE."
    ),
    "ask_user_question_blocker": (
        "Denies unconditionally in strict mode (the shipped default) -- audited "
        "in the 14-handler bucket above; not a dangerous-action guard, so "
        "HandlerTag.BLOCKING alone (not ADVISORY) per "
        "test_declared_behaviour_matches_source.py's requirement for a "
        "default-denying handler."
    ),
    "comment_changelog": "Comment-content style gate (changelog narrative does not belong in code).",
    "comment_size": "Comment-length style gate, with its own MUST_EXCEED escape hatch.",
    "dispatch_declaration": "Workflow gate: a subagent must declare where its report goes.",
    "gh_issue_comments": "Workflow completeness gate: forces --comments on gh issue view.",
    "gh_pr_comments": "Workflow completeness gate: forces --comments on gh pr view.",
    "lsp_enforcement": "Steers Grep/Bash-grep toward LSP tools; opt-in, off by default; a speed/precision nudge, not a guard.",
    "markdown_organization": "Documentation-placement gate (which directory a new .md belongs in).",
    "merge_to_main_approval": (
        "Approval workflow gate on a merge -- the merge ACTION itself is git, "
        "already covered by the SAFETY-tagged destructive_git/ancestry_"
        "preserving_merge; this handler adds a review step, not a backstop "
        "against data loss."
    ),
    "plan_close_approval": "Approval workflow gate on closing a plan.",
    "plan_journal_guard": "Workflow integrity gate: only mkplan.bash --journal stamps a real timestamp.",
    "plan_number_helper": "Workflow integrity gate: prevents a plan-number collision, not a dangerous action.",
    "plan_qa_edit": "Plan-document QA gate (PLAN.md/README.md content quality).",
    "plan_time_estimates": "Plan-content policy gate (no time estimates).",
    "qa_suppression": (
        "Blocks noqa/type:ignore/etc. Considered for SAFETY by analogy with "
        "sibling error_hiding_blocker (which IS SAFETY), but the two differ: "
        "error_hiding_blocker guards a RUNTIME error being silently swallowed "
        "(invisible at the call site, the exact shape N24 found in this "
        "project's own chain.py); a suppression COMMENT is static, always "
        "visible in the diff/review, and disables a check rather than hiding "
        "an outcome. Stays BLOCKING-only."
    ),
    "reference_repo_freshness": "Accuracy gate (a stale governed clone), not a dangerous action.",
    "remote_docs_commit_gate": "Provenance workflow gate on a remote-docs commit.",
    "remote_docs_provenance": "Provenance workflow gate on a remote-docs write.",
    "remote_docs_routing": "Workflow gate: use remote-docs add instead of hand-authoring.",
    "tdd_enforcement": "Workflow gate: test file must exist before source file.",
    "validate_instruction_content": (
        "Denies unconditionally on a pattern match, no config gate -- audited "
        "in the 14-handler bucket above; not a dangerous-action guard, "
        "HandlerTag.BLOCKING per the same default-denying-handler requirement "
        "as ask_user_question_blocker."
    ),
    "subagent_report_path_verifier": (
        "SubagentStop: catches a claimed report path that does not exist. "
        "Workflow integrity (false-report detection), not a dangerous action."
    ),
    "failsafe_cron_blockage_suppressor": (
        "UserPromptSubmit: drops a guaranteed-no-op cron tick for a session "
        "already known to be blocked only on human input. A cost/cadence "
        "optimisation, not a guard against anything dangerous."
    ),
}


def _all_builtin_refs() -> list[BuiltinHandlerRef]:
    _ensure_project_context()
    return list(iter_builtin_handler_classes())


@pytest.mark.parametrize(
    "ref",
    _all_builtin_refs(),
    ids=lambda ref: f"{ref.event_dir}/{ref.config_key}",
)
def test_every_blocking_without_safety_handler_is_audited(ref: BuiltinHandlerRef) -> None:
    """Plan 00466 N40: opt-out-not-opt-in for the WHOLE BLOCKING-without-SAFETY
    bucket, across every event -- the follow-up the module docstring's
    14-handler audit deferred. A handler tagged BLOCKING but not SAFETY must
    either be a documented, deliberate decision (a row in
    ``_AUDITED_BLOCKING_ONLY_REASONS`` above) or be promoted to SAFETY. A NEW
    handler that lands here with neither fails this test, which is the point:
    the reviewer for THAT handler is forced to make the same call this audit
    made for the existing 24, rather than the gap growing silently again.
    """
    tags = _tags_of(ref)
    if HandlerTag.SAFETY in tags or HandlerTag.BLOCKING not in tags:
        return
    assert ref.config_key in _AUDITED_BLOCKING_ONLY_REASONS, (
        f"{ref.event_dir}/{ref.config_key} carries HandlerTag.BLOCKING but not "
        "HandlerTag.SAFETY, and is not in _AUDITED_BLOCKING_ONLY_REASONS above. "
        "Decide: is this a dangerous-action guard (add HandlerTag.SAFETY) or a "
        "workflow/QA governance gate (add a row here explaining why, Plan 00466 "
        "N40)?"
    )


def test_the_audit_table_names_only_handlers_that_still_exist_and_still_need_it() -> None:
    """Registry rot in the other direction: a stale row must not read as
    coverage of a handler that was renamed, removed, or promoted to SAFETY.
    """
    live_blocking_only = {
        ref.config_key
        for ref in _all_builtin_refs()
        if HandlerTag.BLOCKING in _tags_of(ref) and HandlerTag.SAFETY not in _tags_of(ref)
    }
    stale = set(_AUDITED_BLOCKING_ONLY_REASONS) - live_blocking_only
    assert stale == set(), (
        f"_AUDITED_BLOCKING_ONLY_REASONS names handler(s) no longer in the "
        f"BLOCKING-without-SAFETY bucket: {sorted(stale)}. Remove the stale "
        "row(s) -- a row for a handler that moved on reads as coverage of "
        "nothing."
    )
