"""Tests for the shared model-family table (Plan 00472 Task 3.1)."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.model_tiers import (
    EXPLORE_CAP_FAMILY,
    family_below,
    family_rank,
    predicted_explore_family,
    resolve_model_family,
)


class TestResolveModelFamily:
    @pytest.mark.parametrize(
        ("model_id", "expected"),
        [
            ("haiku", ("haiku", 0)),
            ("sonnet", ("sonnet", 1)),
            ("opus", ("opus", 2)),
            ("fable", ("fable", 3)),
            ("Opus", ("opus", 2)),
        ],
    )
    def test_alias(self, model_id: str, expected: tuple[str, int]) -> None:
        assert resolve_model_family(model_id) == expected

    @pytest.mark.parametrize(
        ("model_id", "expected"),
        [
            ("claude-haiku-4-5-20251001", ("haiku", 0)),
            ("claude-sonnet-5-5", ("sonnet", 1)),
            ("claude-opus-5-5", ("opus", 2)),
            ("claude-fable-5-1", ("fable", 3)),
            ("claude-mythos-1-0", ("fable", 3)),
            ("CLAUDE-OPUS-4-6", ("opus", 2)),
        ],
    )
    def test_full_id(self, model_id: str, expected: tuple[str, int]) -> None:
        assert resolve_model_family(model_id) == expected

    @pytest.mark.parametrize("model_id", ["", "inherit", "some-future-model-9-9", "<synthetic>"])
    def test_unknown(self, model_id: str) -> None:
        assert resolve_model_family(model_id) is None


class TestRanks:
    def test_family_rank(self) -> None:
        assert [family_rank(f) for f in ("haiku", "sonnet", "opus", "fable")] == [0, 1, 2, 3]

    def test_family_rank_unknown(self) -> None:
        assert family_rank("gpt") is None

    def test_family_below(self) -> None:
        assert family_below("fable") == "opus"
        assert family_below("opus") == "sonnet"
        assert family_below("sonnet") == "haiku"
        assert family_below("haiku") is None


class TestExploreCap:
    def test_explore_under_fable_main_is_capped_at_opus(self) -> None:
        assert EXPLORE_CAP_FAMILY == "opus"
        assert predicted_explore_family("fable") == "opus"

    def test_explore_under_opus_main_runs_opus(self) -> None:
        assert predicted_explore_family("opus") == "opus"

    def test_explore_under_sonnet_main_runs_sonnet(self) -> None:
        assert predicted_explore_family("sonnet") == "sonnet"


class TestStatusLineSharesTheTable:
    def test_downgrade_state_reexports_the_shared_resolver(self) -> None:
        from claude_code_hooks_daemon.handlers.status_line import downgrade_state

        assert downgrade_state.resolve_model_family is resolve_model_family
