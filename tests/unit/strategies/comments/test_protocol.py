"""Tests for the CommentStrategy Protocol."""

from typing import Any

from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.syntax import HASH_SYNTAX


class _FakeStrategy:
    """Minimal concrete implementation satisfying CommentStrategy structurally."""

    @property
    def language_name(self) -> str:
        return "FakeLang"

    @property
    def extensions(self) -> tuple[str, ...]:
        return (".fake",)

    @property
    def syntax(self) -> Any:
        return HASH_SYNTAX

    @property
    def skip_directories(self) -> tuple[str, ...]:
        return ("vendor/",)

    def get_acceptance_tests(self) -> list[Any]:
        return []


class TestCommentStrategyProtocol:
    """A structurally-conforming class satisfies the Protocol at runtime."""

    def test_fake_strategy_is_instance_of_protocol(self) -> None:
        strategy = _FakeStrategy()
        assert isinstance(strategy, CommentStrategy)

    def test_missing_member_is_not_instance_of_protocol(self) -> None:
        class Incomplete:
            @property
            def language_name(self) -> str:
                return "Incomplete"

        assert not isinstance(Incomplete(), CommentStrategy)

    def test_fake_strategy_exposes_expected_data(self) -> None:
        strategy = _FakeStrategy()
        assert strategy.language_name == "FakeLang"
        assert strategy.extensions == (".fake",)
        assert strategy.syntax is HASH_SYNTAX
        assert strategy.skip_directories == ("vendor/",)
        assert strategy.get_acceptance_tests() == []
