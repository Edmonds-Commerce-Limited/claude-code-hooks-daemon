"""The ownership statement and hint drops (Plan 00599)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from claude_code_hooks_daemon.config.models import ClaudeMdConfig, ClaudeMdOwnership
from claude_code_hooks_daemon.core import ownership
from claude_code_hooks_daemon.core.ownership import OwnershipHint


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    ownership.reset()
    yield
    ownership.reset()


class TestStatement:
    def test_own_returns_the_default_sentence(self) -> None:
        text = ownership.ownership_statement(ClaudeMdConfig())
        assert text == ownership.OWNERSHIP_SENTENCE
        assert text is not None
        assert text.startswith("This codebase is yours")

    def test_off_returns_none(self) -> None:
        assert (
            ownership.ownership_statement(ClaudeMdConfig(ownership=ClaudeMdOwnership.OFF)) is None
        )

    def test_custom_returns_the_project_text_stripped(self) -> None:
        config = ClaudeMdConfig(
            ownership=ClaudeMdOwnership.CUSTOM, ownership_text="  Mine except vendor/.  "
        )
        assert ownership.ownership_statement(config) == "Mine except vendor/."

    def test_none_config_returns_none(self) -> None:
        assert ownership.ownership_statement(None) is None


class TestHintsEnabled:
    def test_unconfigured_is_inactive(self) -> None:
        assert ownership.hints_enabled() is False

    def test_own_and_custom_are_active_off_is_not(self) -> None:
        ownership.configure(ClaudeMdConfig())
        assert ownership.hints_enabled() is True
        ownership.configure(ClaudeMdConfig(ownership=ClaudeMdOwnership.CUSTOM, ownership_text="x"))
        assert ownership.hints_enabled() is True
        ownership.configure(ClaudeMdConfig(ownership=ClaudeMdOwnership.OFF))
        assert ownership.hints_enabled() is False

    def test_config_helper_matches(self) -> None:
        assert ownership.config_hints_enabled(ClaudeMdConfig()) is True
        assert (
            ownership.config_hints_enabled(ClaudeMdConfig(ownership=ClaudeMdOwnership.OFF)) is False
        )


class TestHintOnce:
    def test_fires_once_per_session_and_hint(self) -> None:
        ownership.configure(ClaudeMdConfig())
        first = ownership.hint_once(OwnershipHint.QA_FAILURE, "s1")
        assert first == ownership.HINT_TEXT[OwnershipHint.QA_FAILURE]
        assert ownership.hint_once(OwnershipHint.QA_FAILURE, "s1") is None
        assert ownership.hint_once(OwnershipHint.QA_FAILURE, "s2") is not None
        assert ownership.hint_once(OwnershipHint.PLAN_TIDY, "s1") is not None

    def test_silent_when_off_and_does_not_consume(self) -> None:
        ownership.configure(ClaudeMdConfig(ownership=ClaudeMdOwnership.OFF))
        assert ownership.hint_once(OwnershipHint.PLAN_TIDY, "s1") is None
        ownership.configure(ClaudeMdConfig())
        assert ownership.hint_once(OwnershipHint.PLAN_TIDY, "s1") is not None

    def test_missing_session_id_still_fires_once(self) -> None:
        ownership.configure(ClaudeMdConfig())
        assert ownership.hint_once(OwnershipHint.DISPATCH, None) is not None
        assert ownership.hint_once(OwnershipHint.DISPATCH, None) is None

    def test_peek_does_not_consume(self) -> None:
        ownership.configure(ClaudeMdConfig())
        assert ownership.hint_pending(OwnershipHint.DISPATCH, "s1") is True
        assert ownership.hint_pending(OwnershipHint.DISPATCH, "s1") is True
        ownership.hint_once(OwnershipHint.DISPATCH, "s1")
        assert ownership.hint_pending(OwnershipHint.DISPATCH, "s1") is False


class TestTexts:
    def test_every_hint_has_text(self) -> None:
        for hint in OwnershipHint:
            assert ownership.HINT_TEXT[hint]

    def test_foreign_counter_hint_says_not_yours(self) -> None:
        text = ownership.HINT_TEXT[OwnershipHint.BRANCH_FOREIGN].lower()
        assert "not yours" in text
