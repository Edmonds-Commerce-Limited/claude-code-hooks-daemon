"""SessionStart action tiers — ACTION_REQUIRED is computed, never declared.

Plan 00416 Task 1.2. Twenty-five SessionStart handlers emit into one flat
block with no priority signal, so an agent reads it as background rather than
as a turn. The fix is not louder wording (the plan's Non-Goals rule that out)
— it is a tier the model can trust, because nothing can inflate it.

A SessionStart handler never sets its own ``ACTION_REQUIRED`` directly. It may
optionally implement a **verifier** — ``verify_still_needed()``, answering "is
the thing I am advising about still not done?" — and :func:`compute_tier`
grants ``ACTION_REQUIRED`` exactly when a verifier exists AND is currently
failing. Every other case (no verifier, a passing verifier, a verifier that
raises) falls through to the handler's own declared tier, which is
``ACTION_SUGGESTED`` or ``INFO`` — author-chosen, because neither carries
enforcement and therefore neither can be gamed into teeth.

The verifier check is DUCK-TYPED (a plain ``hasattr`` probe), not an
``isinstance`` check against :class:`SessionStartVerifiable`. That mixin is
the convenient, type-safe way for a new or reclassified handler to opt in —
and the only way to acquire a validated ``declared_tier`` — but a caller that
already has a handler instance with a ``verify_still_needed`` method
(monkeypatched in a test, say) gets picked up too, exactly the way an existing
shipped handler will need to when Task 2.1/2.2 wire real verifiers in without
reparenting them onto a new base.

Why this lives apart from ``core.handler_bases``: ``SessionStartHandlerBase``
there is asserted (``test_handler_bases.py``) to be the literal
``AdvisoryHandler`` object, shared with SessionEnd, Notification, Status and
more — none of which render a tiered block or are covered by
``session-actions``. Keeping the tier concept in its own module means it never
has to touch that identity.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Final

logger = logging.getLogger(__name__)

#: The method name a handler implements to opt into ACTION_REQUIRED. Named
#: once so `has_verifier` and the mixin's own default cannot drift apart.
_VERIFY_METHOD_NAME: Final[str] = "verify_still_needed"


class SessionTier(StrEnum):
    """The three SessionStart message tiers.

    ``ACTION_REQUIRED`` is never constructed by handler code directly — see
    the module docstring and :func:`compute_tier`.
    """

    ACTION_REQUIRED = "ACTION_REQUIRED"
    ACTION_SUGGESTED = "ACTION_SUGGESTED"
    INFO = "INFO"


#: The only tiers a handler may declare for itself. `ACTION_REQUIRED` is
#: excluded here and enforced at construction by `SessionStartVerifiable`.
_DECLARABLE_TIERS: Final[frozenset[SessionTier]] = frozenset(
    {SessionTier.ACTION_SUGGESTED, SessionTier.INFO}
)


class SessionStartVerifiable:
    """Opt-in mixin: gives a SessionStart handler a verifier and a declared tier.

    Mix in alongside a handler's normal base (``SessionStartHandlerBase``)
    only when the handler can answer "is the thing I'm advising about still
    not done?" from disk or from persisted state — the plan's "verifiable"
    admission test. Most SessionStart handlers never mix this in, and keep
    behaving exactly as before: no verifier, `compute_tier` returns
    ``SessionTier.INFO``.
    """

    #: Author-chosen tier used whenever no verifier fires. Restricted to
    #: `_DECLARABLE_TIERS` by the constructor below — never ACTION_REQUIRED.
    declared_tier: SessionTier

    def __init__(self, *, declared_tier: SessionTier = SessionTier.INFO) -> None:
        """Record the author-chosen fallback tier.

        Args:
            declared_tier: ACTION_SUGGESTED or INFO — the tier used whenever
                `verify_still_needed` is absent, raises, or returns False.

        Raises:
            ValueError: If given ACTION_REQUIRED. That tier is computed from
                a verifier, never declared — FAIL FAST here rather than
                silently downgrading a mistaken attempt.
        """
        if declared_tier not in _DECLARABLE_TIERS:
            raise ValueError(
                f"declared_tier={declared_tier!r} is not declarable — "
                "ACTION_REQUIRED is computed from a verifier, never declared. "
                "Use SessionTier.ACTION_SUGGESTED or SessionTier.INFO."
            )
        self.declared_tier = declared_tier

    def verify_still_needed(self) -> bool:
        """Optional verifier: True iff this handler's advisory condition still holds.

        Override this to make the handler eligible for ACTION_REQUIRED. The
        default is unimplemented rather than a fixed False, so
        :func:`has_verifier` can tell "mixed in but never overridden" apart
        from "implemented and currently passing" — both must behave as "no
        verifier", so ACTION_REQUIRED stays impossible to reach by mixing in
        without implementing.

        Returns:
            True when the situation being advised about is still un-fixed.

        Raises:
            NotImplementedError: Always, unless overridden.
        """
        raise NotImplementedError(
            f"{type(self).__name__} mixes in SessionStartVerifiable but never "
            f"overrode {_VERIFY_METHOD_NAME}()"
        )


def has_verifier(handler: object) -> bool:
    """Whether ``handler`` implements a real verifier (not just the default).

    Duck-typed on purpose — see the module docstring. Checked on the CLASS,
    not the instance, so a bound-method identity comparison against the
    mixin's own unbound default works whether or not `handler` actually
    inherits :class:`SessionStartVerifiable`.

    Args:
        handler: Any handler instance.

    Returns:
        True iff ``handler`` has a `verify_still_needed` method that is not
        `SessionStartVerifiable`'s own unimplemented default.
    """
    method = getattr(type(handler), _VERIFY_METHOD_NAME, None)
    if method is None:
        return False
    default = SessionStartVerifiable.__dict__[_VERIFY_METHOD_NAME]
    return method is not default


def compute_tier(handler: object) -> SessionTier:
    """The tier ``handler`` earns right now — computed, never trusted as-is.

    ``ACTION_REQUIRED`` iff `handler` implements a verifier AND it is
    currently failing (`verify_still_needed()` returns True). This is the
    ONLY path to ``ACTION_REQUIRED`` in the whole mechanism: a handler with no
    verifier cannot reach it however it is configured — `has_verifier` gates
    entry, and the fallback below clamps even a directly-tampered
    ``declared_tier`` attribute back to INFO rather than trusting it.

    A verifier that raises degrades safely to the declared tier rather than
    failing the whole SessionStart chain — a defect in one handler's check
    must not hide every other handler's output (Plan 00416 boundary).

    Args:
        handler: The SessionStart handler instance that just matched.

    Returns:
        ACTION_REQUIRED, or the handler's declared tier (INFO if it never
        opted into `SessionStartVerifiable` or set nothing on its own).
    """
    if has_verifier(handler):
        verify = getattr(handler, _VERIFY_METHOD_NAME)
        try:
            still_needed = verify()
        except Exception:
            logger.exception(
                "SessionStart verifier for %s raised; degrading to declared tier",
                getattr(handler, "name", type(handler).__name__),
            )
        else:
            if still_needed:
                return SessionTier.ACTION_REQUIRED

    declared = getattr(handler, "declared_tier", SessionTier.INFO)
    if declared == SessionTier.ACTION_REQUIRED:
        # Defence in depth: `SessionStartVerifiable.__init__` already refuses
        # this, but a caller could set the attribute directly, bypassing it.
        # However it got here, ACTION_REQUIRED is not a value this fallback
        # may return — only the verifier path above may.
        logger.error(
            "%s declared_tier=ACTION_REQUIRED directly; clamping to INFO — "
            "ACTION_REQUIRED is computed from a verifier, never declared",
            getattr(handler, "name", type(handler).__name__),
        )
        return SessionTier.INFO
    try:
        return SessionTier(declared)
    except ValueError:
        return SessionTier.INFO


def prefix_context_with_tier(handler: object, context: list[str]) -> list[str]:
    """Tag ``context``'s first entry with ``handler``'s computed tier.

    Every SessionStart message is tagged, including INFO — the must-do set
    stands out by CONTRAST against the tagged majority, not by being the only
    tagged item (which would just be a louder version of the same flat
    block). Only the first entry is tagged: a handler's later context entries
    are continuation of the same advisory, not a second one.

    Args:
        handler: The SessionStart handler instance that produced ``context``.
        context: That handler's own context lines (unmerged with any other
            handler's — this runs per handler, before the chain flattens
            everything into one list).

    Returns:
        A new list, tag prepended to the first entry; empty input unchanged.
    """
    if not context:
        return context
    tier = compute_tier(handler)
    tagged = list(context)
    tagged[0] = f"[{tier.value}] {tagged[0]}"
    return tagged
