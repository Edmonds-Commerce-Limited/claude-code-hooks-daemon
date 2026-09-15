"""Plan 00416 Task 1.2 — the SessionStart action-tier mechanism.

``ACTION_REQUIRED`` is computed, never declared: a handler earns it only by
implementing a verifier (``verify_still_needed``) that is CURRENTLY failing.
Everything else — no verifier at all, a verifier that passes, a verifier that
raises — falls through to the handler's own declared tier (``ACTION_SUGGESTED``
or ``INFO``), which stays author-chosen because neither carries enforcement.

See CLAUDE/Plan/00416-session-start-action-tiers-and-teeth/PLAN.md, "The
design", for the rationale: a tier any handler can declare for itself
inflates, so ``ACTION_REQUIRED`` must be the one tier nothing can claim by
configuration alone.
"""

from __future__ import annotations

import logging

import pytest

from claude_code_hooks_daemon.core.session_start_tiers import (
    SessionStartVerifiable,
    SessionTier,
    compute_tier,
    has_verifier,
    prefix_context_with_tier,
)


class _PlainHandler:
    """A handler with no verifier at all — the overwhelming common case."""

    name = "plain-handler"
    #: Nothing in this class ever sets this — only a test tampers with it
    #: directly, to prove `compute_tier` clamps rather than trusts it.
    declared_tier: SessionTier | None = None


class _MixinNoOverride(SessionStartVerifiable):
    """Mixed in, but never overrode the verifier — still "no verifier"."""

    name = "mixin-no-override"


class _FailingVerifierHandler(SessionStartVerifiable):
    """A verifier that reports the advised-about condition still holds."""

    name = "failing-verifier"

    def verify_still_needed(self) -> bool:
        return True


class _PassingVerifierHandler(SessionStartVerifiable):
    """A verifier that reports the condition is already resolved."""

    name = "passing-verifier"

    def verify_still_needed(self) -> bool:
        return False


class _RaisingVerifierHandler(SessionStartVerifiable):
    """A verifier that blows up instead of answering."""

    name = "raising-verifier"

    def verify_still_needed(self) -> bool:
        raise RuntimeError("synthetic failure for test")


class _DuckTypedVerifierHandler:
    """A handler that never inherits the mixin, but still quacks like one.

    ``compute_tier`` must recognise this too — the interface is duck-typed,
    not gated on inheritance, so a real handler class can be monkeypatched
    (as tests already do for ``explain_segment``) without also being
    reparented onto a new base.
    """

    name = "duck-typed-verifier"

    def verify_still_needed(self) -> bool:
        return True


class TestAntiInflationGuarantee:
    """A handler with NO verifier can never produce ACTION_REQUIRED."""

    def test_a_handler_with_no_verifier_method_is_never_action_required(self) -> None:
        handler = _PlainHandler()
        assert compute_tier(handler) != SessionTier.ACTION_REQUIRED

    def test_mixing_in_without_overriding_is_still_no_verifier(self) -> None:
        handler = _MixinNoOverride()
        assert not has_verifier(handler)
        assert compute_tier(handler) != SessionTier.ACTION_REQUIRED

    def test_tampering_with_declared_tier_directly_cannot_reach_action_required(
        self,
    ) -> None:
        """However it is configured: even bypassing the constructor guard."""
        handler = _PlainHandler()
        handler.declared_tier = SessionTier.ACTION_REQUIRED
        assert compute_tier(handler) != SessionTier.ACTION_REQUIRED

    def test_this_holds_regardless_of_declared_tier_value(self) -> None:
        for tier in SessionTier:
            handler = _PlainHandler()
            handler.declared_tier = tier
            assert compute_tier(handler) != SessionTier.ACTION_REQUIRED


class TestVerifierDrivesTheTier:
    def test_a_passing_verifier_is_not_action_required(self) -> None:
        assert compute_tier(_PassingVerifierHandler()) != SessionTier.ACTION_REQUIRED

    def test_a_failing_verifier_is_action_required(self) -> None:
        assert compute_tier(_FailingVerifierHandler()) == SessionTier.ACTION_REQUIRED

    def test_duck_typed_verifier_is_recognised_without_the_mixin(self) -> None:
        handler = _DuckTypedVerifierHandler()
        assert has_verifier(handler)
        assert compute_tier(handler) == SessionTier.ACTION_REQUIRED


class TestVerifierDegradesSafely:
    def test_a_raising_verifier_does_not_propagate(self) -> None:
        # Must not raise.
        compute_tier(_RaisingVerifierHandler())

    def test_a_raising_verifier_falls_back_to_the_declared_tier(self) -> None:
        handler = _RaisingVerifierHandler(declared_tier=SessionTier.ACTION_SUGGESTED)
        assert compute_tier(handler) == SessionTier.ACTION_SUGGESTED

    def test_a_raising_verifier_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.ERROR):
            compute_tier(_RaisingVerifierHandler())
        assert "raising-verifier" in caplog.text


class TestDeclaredTierFallback:
    def test_no_verifier_falls_back_to_info_by_default(self) -> None:
        assert compute_tier(_PlainHandler()) == SessionTier.INFO

    def test_no_verifier_uses_the_mixins_declared_tier(self) -> None:
        handler = _MixinNoOverride(declared_tier=SessionTier.ACTION_SUGGESTED)
        assert compute_tier(handler) == SessionTier.ACTION_SUGGESTED

    def test_a_passing_verifier_falls_back_to_declared_tier_too(self) -> None:
        handler = _PassingVerifierHandler(declared_tier=SessionTier.ACTION_SUGGESTED)
        assert compute_tier(handler) == SessionTier.ACTION_SUGGESTED


class TestSessionStartVerifiableConstruction:
    def test_default_declared_tier_is_info(self) -> None:
        assert SessionStartVerifiable().declared_tier == SessionTier.INFO

    def test_action_suggested_is_declarable(self) -> None:
        mixin = SessionStartVerifiable(declared_tier=SessionTier.ACTION_SUGGESTED)
        assert mixin.declared_tier == SessionTier.ACTION_SUGGESTED

    def test_action_required_is_rejected_at_construction(self) -> None:
        """FAIL FAST: computed-only, so declaring it is a bug worth surfacing
        immediately rather than silently downgrading it."""
        with pytest.raises(ValueError, match="ACTION_REQUIRED"):
            SessionStartVerifiable(declared_tier=SessionTier.ACTION_REQUIRED)

    def test_the_default_verifier_is_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            SessionStartVerifiable().verify_still_needed()


class TestHasVerifier:
    def test_plain_object_has_no_verifier(self) -> None:
        assert not has_verifier(_PlainHandler())

    def test_mixin_without_override_has_no_verifier(self) -> None:
        assert not has_verifier(_MixinNoOverride())

    def test_mixin_with_override_has_a_verifier(self) -> None:
        assert has_verifier(_FailingVerifierHandler())


class TestPrefixContextWithTier:
    def test_empty_context_stays_empty(self) -> None:
        assert prefix_context_with_tier(_PlainHandler(), []) == []

    def test_tags_the_first_line_with_the_computed_tier(self) -> None:
        result = prefix_context_with_tier(_FailingVerifierHandler(), ["do the thing"])
        assert result[0].startswith("[ACTION_REQUIRED]")
        assert "do the thing" in result[0]

    def test_leaves_later_entries_untouched(self) -> None:
        result = prefix_context_with_tier(_PlainHandler(), ["first", "second"])
        assert result[1] == "second"

    def test_info_tier_is_tagged_too(self) -> None:
        """Every message is tagged, including INFO — that's what makes the
        must-do set stand out by CONTRAST rather than by being the only
        tagged item."""
        result = prefix_context_with_tier(_PlainHandler(), ["hello"])
        assert result[0].startswith("[INFO]")
