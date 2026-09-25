"""Plan 00466 n24 security review, M3: fail-closed must be structural.

`HandlerChain.execute` only fails a call CLOSED on a crash/timeout/saturation
when the handler carries BOTH `HandlerTag.SAFETY` and `HandlerTag.BLOCKING`
(see `chain.py`'s `_record_unjudged`). A PreToolUse handler that CAN deny a
call but was never given both tags silently fails OPEN under exactly the
pressure this project's own N24/N25/N34 work exists to guard against.

Scope (deliberately narrower than "every handler lacking SAFETY+BLOCKING"):
this covers handlers with NEITHER tag -- ones nobody has ever made a
fail-closed decision about at all. The review separately found 22 handlers
tagged BLOCKING but not SAFETY (`enforce-tdd`, `qa-suppression-blocker`,
`plan-*`, ...): mostly plan/QA/workflow governance gates where BLOCKING was
plausibly a deliberate choice already, not an oversight — auditing that much
larger bucket one-by-one is out of scope here and recorded as a follow-up in
NIGGLES.md rather than rushed. This test's job is narrower and mechanical:
close the "nobody ever decided" gap, and stop it reopening.

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
