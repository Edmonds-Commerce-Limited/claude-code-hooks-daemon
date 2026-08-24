"""A handler must not return a decision its event cannot deliver.

``to_json`` now enforces the response contract at runtime and logs a refusal an
event cannot carry, and
``tests/integration/test_every_handler_response_validates.py`` sweeps every
BUILT-IN handler. Neither reaches a **project handler**: it lives in a client's
own repository, is a supported extension point, and no test in this repository
can see it. For a client the defect is not unreachable — it is undetectable
until it silently misfires in production.

This module is the shared primitive that closes that gap. It answers one
question — *can this event actually deliver this decision?* — for the in-repo
sweep and for ``validate-project-handlers`` alike, so the two cannot drift.

**Why schema validation alone is not the answer.** Only 13 events have a
bespoke response schema; the other 18 wired events fall back to
``_permissive_response_schema()``, which accepts any object. A DENY on
``TaskCreated`` therefore VALIDATES and is still dropped on the wire. The check
must ask about delivery, not merely about schema conformance.

The probe classes below are ordinary module-level classes rather than generated
source, because that is exactly what the scan reads in production: a handler
class whose file is on disk.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.core.decision_capability import (
    decisions_referenced_by,
    undeliverable_decisions,
)
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.result_types import AdvisoryResult


class RefusingProbe:
    """Returns a refusal."""

    def handle(self, hook_input: dict[str, Any]) -> Decision:
        return Decision.DENY


class AskingProbe:
    """Returns an ASK."""

    def handle(self, hook_input: dict[str, Any]) -> Decision:
        return Decision.ASK


class AllowingProbe:
    """Returns the common, always-expressible decision."""

    def handle(self, hook_input: dict[str, Any]) -> Decision:
        return Decision.ALLOW


class BranchingProbe:
    """Returns more than one decision."""

    def handle(self, hook_input: dict[str, Any]) -> Decision:
        if hook_input:
            return Decision.DENY
        return Decision.ALLOW


class ContinuingProbe:
    """Returns the Stop-family continuation decision."""

    def handle(self, hook_input: dict[str, Any]) -> Decision:
        return Decision.CONTINUE


class ExpectationOnlyProbe:
    """Names a decision ONLY in an acceptance-test expectation."""

    def handle(self, hook_input: dict[str, Any]) -> Decision:
        return Decision.ALLOW

    def get_acceptance_tests(self) -> list[dict[str, Any]]:
        return [{"expected_decision": Decision.DENY}]


class FactoryRefusingProbe:
    """Refuses through the FACTORY, naming no ``Decision`` member at all.

    This is the shape most handlers actually use, and the scan was blind to it:
    ``HookResult.deny(...)`` reaches the same wire decision as
    ``Decision.DENY`` while mentioning neither the enum nor the member.
    """

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult.deny(reason="blocked")


class FactoryAskingProbe:
    """Asks through the factory."""

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult.ask(reason="confirm?")


class FactoryAllowingProbe:
    """Allows through the factory."""

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult.allow(context=["fyi"])


class NarrowedFactoryProbe:
    """Uses a narrowed tier's inherited factory.

    ``AdvisoryResult.deny(...)`` type-checks — ``deny`` is inherited — and only
    Pydantic stops it, at runtime, when that handler first executes. The scan
    is the surface that can say so beforehand.
    """

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        return AdvisoryResult.deny(reason="blocked")


class _NotAResult:
    """Something unrelated that happens to have a ``deny`` method."""

    def deny(self, reason: str) -> str:
        return reason


class FactoryLookalikeProbe:
    """A same-named method on something that is NOT a result type.

    The scan keys on the result classes by name, so an unrelated ``.deny(...)``
    must not be mistaken for a refusal — that would report a defect that is not
    there, in a diagnostic a client is asked to trust.
    """

    policy = _NotAResult()

    def handle(self, hook_input: dict[str, Any]) -> Decision:
        self.policy.deny(reason="not a HookResult")
        return Decision.ALLOW


#: One probe per Decision member, for the exhaustive cross-product below.
_PROBES: dict[Decision, type] = {
    Decision.ALLOW: AllowingProbe,
    Decision.DENY: RefusingProbe,
    Decision.ASK: AskingProbe,
    Decision.CONTINUE: ContinuingProbe,
}


class TestTheFactoryFormIsSeenToo:
    """``HookResult.deny(...)`` names no ``Decision`` member, and used to hide.

    Measured across this repository's own handlers when the gap was found: one
    built-in handler refuses this way and the scan saw nothing. It cost nothing
    here only because that handler is on ``PreToolUse``, which can deny. For a
    CLIENT it is the whole point — ``validate-project-handlers`` shares this
    primitive, so a project handler refusing on ``SessionStart`` through the
    factory passed the pre-flight check in silence.
    """

    def test_a_factory_deny_is_found(self) -> None:
        assert Decision.DENY in decisions_referenced_by(FactoryRefusingProbe)

    def test_a_factory_ask_is_found(self) -> None:
        assert Decision.ASK in decisions_referenced_by(FactoryAskingProbe)

    def test_a_factory_allow_is_found(self) -> None:
        assert Decision.ALLOW in decisions_referenced_by(FactoryAllowingProbe)

    def test_a_narrowed_tiers_inherited_factory_is_found(self) -> None:
        assert Decision.DENY in decisions_referenced_by(NarrowedFactoryProbe)

    def test_a_factory_refusal_is_reported_as_undeliverable(self) -> None:
        problems = undeliverable_decisions(FactoryRefusingProbe, "SessionStart")

        assert problems and "deny" in problems[0]

    def test_a_same_named_method_on_another_type_is_ignored(self) -> None:
        assert decisions_referenced_by(FactoryLookalikeProbe) == {Decision.ALLOW}


class TestDecisionsAreReadFromTheSource:
    """The scan must reflect what the handler DOES, not what it claims."""

    def test_a_returned_decision_is_found(self) -> None:
        assert Decision.DENY in decisions_referenced_by(RefusingProbe)

    def test_several_decisions_are_all_found(self) -> None:
        assert decisions_referenced_by(BranchingProbe) == {Decision.DENY, Decision.ALLOW}

    def test_acceptance_test_expectations_are_not_counted(self) -> None:
        """``expected_decision=`` asserts behaviour; it is not a return value.

        Both worktree handlers name ``Decision.ALLOW`` only there, so counting
        that reference would attribute a decision they never return.
        """
        assert decisions_referenced_by(ExpectationOnlyProbe) == {Decision.ALLOW}

    def test_a_class_with_no_readable_source_is_not_an_error(self) -> None:
        """A dynamically-built class must degrade quietly, not crash the CLI."""
        assert decisions_referenced_by(type("Ghost", (), {})) == set()


class TestAnEventThatCannotDeliverIsReported:
    """The property the client-side guard needs."""

    @pytest.mark.parametrize(
        "event_name",
        ["SessionStart", "SessionEnd", "PreCompact", "Notification"],
    )
    def test_a_deny_on_a_message_only_event_is_reported(self, event_name: str) -> None:
        assert undeliverable_decisions(
            RefusingProbe, event_name
        ), f"a DENY on {event_name} cannot block, and was not reported"

    def test_a_deny_on_a_permissive_schema_event_is_still_reported(self) -> None:
        """The case schema validation alone cannot catch.

        ``TaskCreated`` has no bespoke schema, so any response validates. The
        decision is dropped regardless.
        """
        assert undeliverable_decisions(RefusingProbe, "TaskCreated"), (
            "a DENY on a permissive-schema event validates but is still dropped, "
            "so schema conformance alone must not be the test"
        )

    def test_a_deny_on_status_is_reported(self) -> None:
        """A status line renders text and can refuse nothing."""
        assert undeliverable_decisions(RefusingProbe, "Status")

    def test_an_ask_is_reported_on_an_event_that_can_only_block(self) -> None:
        """``Stop`` expresses ``block`` but has no way to ASK."""
        assert undeliverable_decisions(AskingProbe, "Stop")

    def test_the_report_names_the_decision_and_the_event(self) -> None:
        """A report nobody can act on is barely better than none."""
        combined = " ".join(undeliverable_decisions(RefusingProbe, "SessionStart"))

        assert "deny" in combined
        assert "SessionStart" in combined


class TestDeliverableDecisionsAreLeftAlone:
    """A guard that cries wolf on correct handlers gets switched off."""

    @pytest.mark.parametrize(
        "event_name",
        ["PreToolUse", "PostToolUse", "Stop", "SubagentStop", "PermissionRequest"],
    )
    def test_a_deny_on_a_refusal_capable_event_is_not_reported(self, event_name: str) -> None:
        assert not undeliverable_decisions(RefusingProbe, event_name)

    @pytest.mark.parametrize("event_name", ["PreToolUse", "PermissionRequest"])
    def test_an_ask_on_an_ask_capable_event_is_not_reported(self, event_name: str) -> None:
        assert not undeliverable_decisions(AskingProbe, event_name)

    @pytest.mark.parametrize(
        "event_name",
        ["PreToolUse", "SessionStart", "Status", "TaskCreated", "Notification"],
    )
    def test_an_allow_is_never_reported(self, event_name: str) -> None:
        """Every event can allow; this is the overwhelmingly common case."""
        assert not undeliverable_decisions(AllowingProbe, event_name)

    def test_an_unknown_event_is_not_reported(self) -> None:
        """The CLI must not fail a handler because an event is unrecognised."""
        assert not undeliverable_decisions(RefusingProbe, "NoSuchEventXYZ")


class TestRefusalCapabilityCoversEverySchemaViolation:
    """The shortcut this module takes, asserted rather than assumed.

    ``undeliverable_decisions`` checks refusal capability ALONE — it never
    validates a response. That is only sound while refusal capability is a
    strict superset of schema validity: every combination the schema rejects
    must also be one the event cannot carry.

    Measured over the full cross-product, it currently is. But it is an
    empirical fact about the serialiser, not a law, so a new decision or a
    tightened schema could quietly break it and leave the client-side check
    waving through a response the runtime rejects. Sweeping every event against
    every decision is what makes that impossible to miss.
    """

    def test_every_probe_is_scanned_correctly(self) -> None:
        """Guard the guard's guard — a broken probe would sweep nothing."""
        for decision, probe in _PROBES.items():
            assert decisions_referenced_by(probe) == {decision}, (
                f"the {decision.value} probe does not scan to {decision.value}, so "
                "the cross-product below proves nothing"
            )

    def test_the_table_covers_every_decision(self) -> None:
        """A Decision member with no probe would go entirely unswept."""
        assert set(_PROBES) == set(Decision)

    def test_no_schema_violation_escapes_the_capability_check(self) -> None:
        from claude_code_hooks_daemon.core.hook_result import HookResult
        from claude_code_hooks_daemon.core.response_schemas import (
            RESPONSE_SCHEMAS,
            validate_response,
        )

        escaped: list[str] = []
        for event_name in sorted(RESPONSE_SCHEMAS):
            for decision, probe in _PROBES.items():
                # _build_wire_response, not to_json: to_json ENFORCES the
                # contract and substitutes a valid response, so asking it what
                # the serialiser would emit gets the answer after the repair.
                response = HookResult(decision=decision, reason="probe")._build_wire_response(
                    event_name
                )
                if not validate_response(event_name, response):
                    continue
                if not undeliverable_decisions(probe, event_name):
                    escaped.append(f"{decision.value} on {event_name} -> {response}")

        assert not escaped, (
            "these produce a schema-INVALID response that the capability check "
            "does not report, so a project handler would pass its pre-flight "
            "check and still be rejected at runtime:\n  " + "\n  ".join(escaped)
        )


class TestTheBuiltInHandlersAreClean:
    """Guard the guard — the primitive must agree with the shipped tree.

    If this fails, either a built-in handler really is broken or the capability
    logic has drifted into false positives. Both matter; neither is silent.
    """

    def test_no_shipped_handler_returns_an_undeliverable_decision(self) -> None:
        from tests.integration.test_every_handler_response_validates import (
            _handlers_with_event_names,
        )

        broken = [
            f"{name} [{event}]: {problems}"
            for name, cls, event in _handlers_with_event_names()
            for problems in [undeliverable_decisions(cls, event)]
            if problems
        ]

        assert not broken, "built-in handlers reported as undeliverable:\n" + "\n".join(broken)
