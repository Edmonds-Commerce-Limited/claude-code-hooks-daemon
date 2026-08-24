"""What mypy must say — and must NOT say — about the result factories.

Handlers build results with ``allow``/``deny``/``ask``, not by calling
``__init__``. So the factories decide whether a narrowed handler is writable at
all, and they have to cut two ways at once:

- ``BlockingResult.deny(...)`` must satisfy a ``-> BlockingResult`` return, or
  every reparented handler would have to construct its results by hand;
- ``AdvisoryResult.deny(...)`` must NOT, because that event cannot refuse.

Both directions are pinned here. The marked lines must be reported;
``test_nothing_unexpected_is_reported`` polices every unmarked line, so the
correct usages below fail the suite the moment they stop type-checking. That
second half is the part a violations-only fixture cannot express, and it is the
half that would otherwise be discovered by 84 handlers failing at once.

The runtime behaviour is already correct without any of this — the factories
call ``cls(...)``, so ``AdvisoryResult.allow()`` has always RETURNED an
``AdvisoryResult``. Only the annotation was wide. That is exactly why a runtime
test cannot stand in for this file: every assertion in
``test_result_types.py`` passed before the fix and after it.

**Keep every violation on ONE line** — see ``undeliverable_decisions.py`` for
why, and for the black/ruff/mypy exclusions that keep it that way.
"""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest
from claude_code_hooks_daemon.core.handler_bases import (
    PostToolUseHandlerBase,
    PreToolUseHandlerBase,
    SessionStartHandlerBase,
)
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.core.result_types import (
    AdvisoryResult,
    BlockingResult,
    GatingResult,
)

# ── The factories must return the tier they were called on ──────────────────


def advisory_allow_is_usable() -> AdvisoryResult:
    """Must be clean: otherwise no advisory handler can use ``allow``."""
    return AdvisoryResult.allow(context=["fyi"])


def blocking_deny_is_usable() -> BlockingResult:
    """Must be clean: ``PostToolUse``/``Stop`` genuinely block."""
    return BlockingResult.deny(reason="blocked")


def gating_ask_is_usable() -> GatingResult:
    """Must be clean: ``PreToolUse``/``PermissionRequest`` genuinely ask."""
    return GatingResult.ask(reason="confirm?")


def gating_deny_is_usable() -> GatingResult:
    return GatingResult.deny(reason="blocked")


# ── ...and must NOT hand a narrowed tier a decision it cannot carry ─────────


def advisory_deny_through_the_factory() -> AdvisoryResult:
    """``deny`` is INHERITED, so this is the remaining way in.

    It resolves to the base ``deny``, which is deliberately left returning the
    wide ``HookResult`` — so the narrowed return type rejects it here.
    """
    return AdvisoryResult.deny(reason="blocked")  # VIOLATION: return-value


def advisory_ask_through_the_factory() -> AdvisoryResult:
    return AdvisoryResult.ask(reason="confirm?")  # VIOLATION: return-value


def blocking_ask_through_the_factory() -> BlockingResult:
    return BlockingResult.ask(reason="confirm?")  # VIOLATION: return-value


def the_wide_factory_does_not_satisfy_a_narrow_return() -> AdvisoryResult:
    """``HookResult.allow()`` is the wide type, whatever it holds."""
    return HookResult.allow()  # VIOLATION: return-value


# ── The same, reached the way a handler actually reaches it ─────────────────


class CorrectAdvisoryHandler(SessionStartHandlerBase):
    """Must be clean, with nothing declared beyond the return annotation."""

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        return AdvisoryResult.allow(context=["session context"])

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return []


class CorrectBlockingHandler(PostToolUseHandlerBase):
    """Must be clean: this tier really can refuse."""

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        return BlockingResult.deny(reason="lint failed")

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return []


class CorrectGatingHandler(PreToolUseHandlerBase):
    """Must be clean: this tier can deny AND ask."""

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        if hook_input:
            return GatingResult.deny(reason="blocked")
        return GatingResult.ask(reason="confirm?")

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return []


class RefusingAdvisoryHandler(SessionStartHandlerBase):
    """The defect, written the way a handler would really write it."""

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        return AdvisoryResult.deny(reason="blocked")  # VIOLATION: return-value

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return []
