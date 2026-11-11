"""The ownership statement and the hint drops that follow from it (Plan 00599).

``claude_md.ownership`` decides two things from one setting: whether the
injected ``CLAUDE.md`` block leads with a sentence telling the model the
codebase is its own, and whether the daemon's handlers drop short hints that
say the same thing at the moment it matters (plan files to keep tidy, a QA
failure in code just touched, branches to clean, a sub-agent brief).

Process-wide state is deliberate: the daemon is one process, the setting is
one value read at start-up, and threading it through every handler's
constructor would touch each one for a flag only these hints read. Unconfigured
means inactive, so code that never configures it (the CLI, unit tests) gets
no hints unless it opts in explicitly.
"""

from __future__ import annotations

from enum import StrEnum

from claude_code_hooks_daemon.config.models import ClaudeMdConfig, ClaudeMdOwnership

#: The sentence ``ownership: own`` leads the injected block with.
OWNERSHIP_SENTENCE = (
    "This codebase is yours: what it's for and how it's built are your call, "
    "and you'll keep building on it."
)


class OwnershipHint(StrEnum):
    """Each place the daemon drops an ownership hint."""

    PLAN_TIDY = "plan-tidy"
    QA_FAILURE = "qa-failure"
    BRANCH_OWNED = "branch-owned"
    BRANCH_FOREIGN = "branch-foreign"
    DISPATCH = "dispatch"


#: One line each. The foreign one is the counter-hint: foreign branches are listed
#: so they are visible, never so they can be changed.
HINT_TEXT: dict[OwnershipHint, str] = {
    OwnershipHint.PLAN_TIDY: (
        "Plan and ledger files are yours to keep tidy: merge duplicates and fix stale "
        "links you meet, do not only report them."
    ),
    OwnershipHint.QA_FAILURE: (
        "You own this code: fix the cause of the failure, do not only report it."
    ),
    OwnershipHint.BRANCH_OWNED: (
        "These branches are yours: clean or keep each one deliberately, do not only report them."
    ),
    OwnershipHint.BRANCH_FOREIGN: (
        "Foreign branches are not yours to change: they are listed so they are visible, "
        "never to be cleaned, merged or edited."
    ),
    OwnershipHint.DISPATCH: (
        "This codebase is yours, and so is the brief you write: tell the agent to fix "
        "what it finds in the code it touches, not only to report it."
    ),
}

_mode: ClaudeMdOwnership | None = None
_fired: set[tuple[OwnershipHint, str | None]] = set()


def ownership_statement(config: ClaudeMdConfig | None) -> str | None:
    """The sentence to lead the block with, or ``None`` when there is none."""
    if config is None or config.ownership == ClaudeMdOwnership.OFF:
        return None
    if config.ownership == ClaudeMdOwnership.CUSTOM:
        # The config's validator guarantees non-blank text for custom.
        return (config.ownership_text or "").strip()
    return OWNERSHIP_SENTENCE


def config_hints_enabled(config: ClaudeMdConfig) -> bool:
    """Whether ``config`` asks for hint drops (everything but ``off``)."""
    return config.ownership != ClaudeMdOwnership.OFF


def configure(config: ClaudeMdConfig | None) -> None:
    """Set the process-wide mode from the daemon's ``claude_md`` block."""
    global _mode
    _mode = None if config is None else config.ownership


def reset() -> None:
    """Return to the unconfigured state and forget every fired hint."""
    global _mode
    _mode = None
    _fired.clear()


def hints_enabled() -> bool:
    """True once configured with a mode other than ``off``."""
    return _mode is not None and _mode != ClaudeMdOwnership.OFF


def hint_pending(hint: OwnershipHint, session_id: str | None) -> bool:
    """Would :func:`hint_once` speak now? Does not consume the hint."""
    return hints_enabled() and (hint, session_id) not in _fired


def hint_once(hint: OwnershipHint, session_id: str | None) -> str | None:
    """The hint text the first time per session, else ``None`` (always ``None`` when off)."""
    if not hint_pending(hint, session_id):
        return None
    _fired.add((hint, session_id))
    return HINT_TEXT[hint]
