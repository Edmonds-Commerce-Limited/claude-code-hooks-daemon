"""`scope` is refused on an event that cannot carry `agent_id` (Plan 00423).

The key discriminates on `agent_id`. On an event whose contract never delivers
that field, `MAIN` would admit every event and `SUB` none — so configuring
either states a protection that cannot exist. Accepting it silently is the
worse failure: the author reads their own config and believes a handler is
scoped out of subagent sessions when nothing of the sort is happening.

This is the shape 00422 N2 taught, in a different costume. A setting that
quietly does nothing looks identical to one that works, and only something
that ASKS finds out. The author is present at config-validation time and can
be told; at dispatch time nobody is.

The eligible set IS restated in code, because `contracts/` is a
repository-side reference and is not shipped with the package — parsing it at
import would work here and fail in every client. Restating is how a list goes
stale, so the first class below reads the real contracts and fails when the
copy stops matching them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import HandlersConfig, scope_from_raw_block
from claude_code_hooks_daemon.core.handler_scope import (
    AGENT_ID_EVENTS,
    HandlerScope,
    event_supports_scope,
    validate_scope_for_event,
)

_CONTRACTS = Path(__file__).resolve().parents[3] / "contracts" / "claude-code-hooks"


def _declares_agent_id(contract: Path) -> bool:
    """Whether this contract DELIVERS agent_id, by its declared field lists.

    Read from `conditional_input_fields` and `input_example` rather than by
    searching the file's text. A text search says six events, because
    `Elicitation.json` discusses `agent_id` in a prose note ABOUT `PreToolUse`
    without ever delivering it — the looser method overcounts, and this set is
    the basis for refusing a config key, so it has to be exact.
    """
    data = json.loads(contract.read_text(encoding="utf-8"))
    declared = set(data.get("conditional_input_fields") or {})
    declared |= set(data.get("input_example") or {})
    return "agent_id" in declared


class TestTheConstantMatchesTheShippedContracts:
    """The set is copied into code, so something must read the originals.

    `contracts/` is a repository-side reference and is not shipped with the
    package, so `handler_scope` cannot parse it at import — it would work here
    and fail in every client. The cost of copying is drift; this is what pays
    it.
    """

    def test_every_contract_declaring_agent_id_is_in_the_set(self) -> None:
        from_disk = {c.stem for c in sorted(_CONTRACTS.glob("*.json")) if _declares_agent_id(c)}
        assert from_disk == set(AGENT_ID_EVENTS)

    def test_the_extractor_actually_finds_something(self) -> None:
        """Guard the guard: a finder matching nothing would pass vacuously."""
        assert sum(1 for c in _CONTRACTS.glob("*.json") if _declares_agent_id(c)) >= 3

    def test_it_reads_real_contracts_not_an_empty_directory(self) -> None:
        assert len(list(_CONTRACTS.glob("*.json"))) > 20


class TestTheEligibleSetIsDerivedFromTheContracts:
    """Guard the guard: an empty or universal set would make every test vacuous."""

    def test_it_is_neither_empty_nor_everything(self) -> None:
        assert 2 <= len(AGENT_ID_EVENTS) <= 8

    @pytest.mark.parametrize("event", ["PreToolUse", "PostToolUse", "Stop", "SubagentStop"])
    def test_it_contains_every_event_with_a_handler_package(self, event: str) -> None:
        """These four are where the 85 scopeable handlers actually live."""
        assert event in AGENT_ID_EVENTS

    @pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit", "PreCompact"])
    def test_it_excludes_the_session_level_events(self, event: str) -> None:
        assert event not in AGENT_ID_EVENTS


class TestEventSupportsScope:
    def test_true_for_an_event_that_can_carry_agent_id(self) -> None:
        assert event_supports_scope("PreToolUse")

    def test_false_for_one_that_cannot(self) -> None:
        assert not event_supports_scope("SessionStart")

    def test_an_unknown_event_is_not_assumed_to_support_it(self) -> None:
        """Assuming support would accept a scope that silently does nothing."""
        assert not event_supports_scope("NoSuchEvent")


class TestValidateScopeForEvent:
    def test_all_is_accepted_everywhere(self) -> None:
        """ALL is the default and means "no restriction" — never a false promise."""
        for event in ("SessionStart", "PreToolUse", "NoSuchEvent"):
            validate_scope_for_event(event, "some_handler", HandlerScope.ALL)

    def test_none_is_accepted_everywhere(self) -> None:
        """An unset key is not a claim about anything."""
        validate_scope_for_event("SessionStart", "some_handler", None)

    @pytest.mark.parametrize("scope", [HandlerScope.MAIN, HandlerScope.SUB])
    def test_a_restricting_scope_is_accepted_on_an_eligible_event(
        self, scope: HandlerScope
    ) -> None:
        validate_scope_for_event("PreToolUse", "some_handler", scope)

    @pytest.mark.parametrize("scope", [HandlerScope.MAIN, HandlerScope.SUB])
    def test_a_restricting_scope_is_refused_on_an_ineligible_event(
        self, scope: HandlerScope
    ) -> None:
        with pytest.raises(ValueError) as excinfo:
            validate_scope_for_event("SessionStart", "some_handler", scope)
        message = str(excinfo.value)
        assert "SessionStart" in message
        assert "some_handler" in message
        assert "agent_id" in message

    def test_the_refusal_names_the_scopes_that_would_work(self) -> None:
        """A refusal that does not say what to do instead just blocks the author."""
        with pytest.raises(ValueError, match="ALL"):
            validate_scope_for_event("SessionStart", "some_handler", HandlerScope.MAIN)


class TestTheRefusalFiresThroughTheRealLoader:
    """Every case above calls the predicate directly, and that was not enough.

    The first version of the config validator guarded with
    `isinstance(handler_block, dict)`. By the time an `after` validator runs,
    pydantic has already coerced each block into a `HandlerConfig`, so the
    guard matched NOTHING and the refusal never fired — with all the direct
    tests green. It was found by putting real YAML through
    `HandlersConfig.model_validate`, which is what these do.

    A guard that silently matches nothing passes vacuously. That is issue #44's
    lesson and 00422 N2's, and it applies to a config validator exactly as it
    applies to a handler.
    """

    @staticmethod
    def _validate(text: str) -> None:
        HandlersConfig.model_validate(yaml.safe_load(text))

    def test_main_on_a_session_level_event_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="SessionStart"):
            self._validate("session_start:\n  docs_qa_sweep:\n    scope: MAIN\n")

    def test_sub_on_a_session_level_event_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="user_prompt_submit|UserPromptSubmit"):
            self._validate("user_prompt_submit:\n  standing_authorisations:\n    scope: SUB\n")

    def test_main_on_an_eligible_event_is_accepted(self) -> None:
        self._validate("pre_tool_use:\n  sed_blocker:\n    scope: MAIN\n")

    def test_a_lowercase_value_on_an_eligible_event_is_accepted(self) -> None:
        self._validate("stop:\n  auto_continue_stop:\n    scope: main\n")

    def test_a_padded_value_through_model_validate_is_accepted(self) -> None:
        """Via the public loader, `coerce_handler_configs` (a `field_validator("*",
        mode="before")`) always coerces each handler block to `HandlerConfig`
        before `validate_handler_scopes` (an `after` validator) ever runs, so a
        padded value is normalised by `HandlerConfig.normalise_scope` before it
        reaches this handler's own branch. This case was already accepted before
        the fix below; it is here to pin that it stays accepted.
        """
        self._validate('pre_tool_use:\n  sed_blocker:\n    scope: " MAIN "\n')

    def test_a_padded_value_reaching_the_raw_dict_branch_is_accepted(self) -> None:
        """The raw-dict path must strip whitespace like its two siblings
        (`HandlerConfig.normalise_scope` and `resolve_scope` in
        `handler_scope.py`, both of which strip).

        Exercised through `scope_from_raw_block` directly. That branch is
        unreachable through the public `model_validate` loader — a block is
        always already a `HandlerConfig` by the time any `mode="after"`
        validator runs — so the function is where the behaviour lives and is
        the honest thing to pin. Before the fix a padded value raised a bare
        `ValueError: ' MAIN ' is not a valid HandlerScope`, naming neither the
        handler nor the config key.
        """
        assert scope_from_raw_block(" MAIN ") is HandlerScope.MAIN
        assert scope_from_raw_block("sub") is HandlerScope.SUB
        assert scope_from_raw_block(None) is None

    def test_all_on_an_ineligible_event_is_accepted(self) -> None:
        """ALL claims nothing, so it can never be a false promise."""
        self._validate("session_start:\n  docs_qa_sweep:\n    scope: ALL\n")

    def test_an_unset_scope_is_accepted_everywhere(self) -> None:
        self._validate("session_start:\n  docs_qa_sweep:\n    enabled: true\n")

    def test_this_projects_own_config_still_loads(self) -> None:
        """The check must not reject the config this repository actually ships."""
        config = yaml.safe_load(
            (Path(__file__).resolve().parents[3] / ".claude" / "hooks-daemon.yaml").read_text(
                encoding="utf-8"
            )
        )
        HandlersConfig.model_validate(config.get("handlers") or {})
