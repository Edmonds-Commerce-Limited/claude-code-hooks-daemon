"""The fake-values registry: one list of approved fakes, by kind (Plan 00492)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.fake_values import (
    REGISTRY_RELATIVE_PATH,
    FakeValuesError,
    FakeValuesRegistry,
    ValueSwap,
    load_fake_values,
    swap_unlisted_fakes,
)

_ALL_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_ALL_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_ALL_C = "cccccccc-cccc-cccc-cccc-cccccccccccc"
# Joined so this file does not itself carry a real-looking UUID literal.
_REAL_LOOKING = "-".join(("8e11bfb5", "7dc2", "432b", "9206", "928fa5c35731"))
_OTHER_REAL_LOOKING = "-".join(("0c9e6a2f", "7d41", "4f4e", "9a15", "3f4f7c2b8d10"))
_THIRD_REAL_LOOKING = "-".join(("5b2a9c8e", "1f63", "4d8a", "b7c4", "9e0d2a6f1c3b"))
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

_REGISTRY_YAML = f"""\
kinds:
  session-uuid:
    description: fake session ids
    fake_looking: '\\b([0-9a-f])\\1{{7}}-\\1{{4}}-\\1{{4}}-\\1{{4}}-\\1{{12}}\\b'
    values:
      - "{_ALL_A}"
      - "{_ALL_B}"
"""


def _write_registry(root: Path, text: str = _REGISTRY_YAML) -> Path:
    path = root / REGISTRY_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadFakeValues:
    def test_missing_file_is_an_empty_registry(self, tmp_path: Path) -> None:
        registry = load_fake_values(tmp_path)
        assert registry.allows("session-uuid", _ALL_A) is False
        assert registry.kind_names == ()

    def test_listed_value_is_allowed_exactly(self, tmp_path: Path) -> None:
        _write_registry(tmp_path)
        registry = load_fake_values(tmp_path)
        assert registry.allows("session-uuid", _ALL_A) is True
        assert registry.allows("session-uuid", _ALL_B) is True

    def test_unlisted_value_of_the_same_kind_is_not_allowed(self, tmp_path: Path) -> None:
        _write_registry(tmp_path)
        registry = load_fake_values(tmp_path)
        assert registry.allows("session-uuid", _REAL_LOOKING) is False
        assert registry.allows("session-uuid", _ALL_C) is False

    def test_match_is_exact_not_a_substring_or_case_fold(self, tmp_path: Path) -> None:
        _write_registry(tmp_path)
        registry = load_fake_values(tmp_path)
        assert registry.allows("session-uuid", _ALL_A.upper()) is False
        assert registry.allows("session-uuid", _ALL_A + "0") is False

    def test_a_value_is_only_allowed_under_its_own_kind(self, tmp_path: Path) -> None:
        _write_registry(tmp_path)
        registry = load_fake_values(tmp_path)
        assert registry.allows("some-other-kind", _ALL_A) is False

    def test_fake_looking_values_are_found_per_kind(self, tmp_path: Path) -> None:
        _write_registry(tmp_path)
        registry = load_fake_values(tmp_path)
        text = f"{_ALL_A} and {_ALL_C} and {_REAL_LOOKING}"
        assert registry.unlisted_fake_looking(text) == [("session-uuid", _ALL_C)]

    @pytest.mark.parametrize(
        "text",
        [
            "kinds: [not, a, mapping]",
            "nothing: here",
            "kinds:\n  session-uuid: not-a-mapping",
            "kinds:\n  session-uuid:\n    values: not-a-list",
            "kinds:\n  session-uuid:\n    values: [1]",
            "kinds:\n  session-uuid:\n    values: ['']",
            "kinds:\n  session-uuid:\n    values: ['a']\n    fake_looking: '('",
            "kinds:\n  session-uuid:\n    values: ['a']\n    surprise: 1",
            "- just\n- a list",
            "kinds: {\n",
        ],
    )
    def test_malformed_registry_fails_fast(self, tmp_path: Path, text: str) -> None:
        _write_registry(tmp_path, text)
        with pytest.raises(FakeValuesError):
            load_fake_values(tmp_path)

    def test_duplicate_value_in_a_kind_fails_fast(self, tmp_path: Path) -> None:
        _write_registry(
            tmp_path,
            f"kinds:\n  session-uuid:\n    values:\n      - '{_ALL_A}'\n      - '{_ALL_A}'\n",
        )
        with pytest.raises(FakeValuesError, match="more than once"):
            load_fake_values(tmp_path)


class TestSwapUnlistedFakes:
    @pytest.fixture
    def registry(self, tmp_path: Path) -> FakeValuesRegistry:
        _write_registry(tmp_path)
        return load_fake_values(tmp_path)

    def test_unlisted_value_is_replaced_by_a_listed_one(self, registry: FakeValuesRegistry) -> None:
        text, swaps = swap_unlisted_fakes(
            f'{{"session_id": "{_REAL_LOOKING}"}}', {"session-uuid": _UUID_RE}, registry
        )
        assert _REAL_LOOKING not in text
        assert _ALL_A in text
        assert swaps == (
            ValueSwap(
                kind="session-uuid",
                replacement=_ALL_A,
                occurrences=1,
                original_sha256=swaps[0].original_sha256,
            ),
        )
        assert len(swaps[0].original_sha256) == 64

    def test_every_occurrence_of_one_original_gets_the_same_replacement(
        self, registry: FakeValuesRegistry
    ) -> None:
        text, swaps = swap_unlisted_fakes(
            f"{_REAL_LOOKING} again {_REAL_LOOKING}", {"session-uuid": _UUID_RE}, registry
        )
        assert text == f"{_ALL_A} again {_ALL_A}"
        assert [swap.occurrences for swap in swaps] == [2]

    def test_distinct_originals_keep_distinct_replacements(
        self, registry: FakeValuesRegistry
    ) -> None:
        text, swaps = swap_unlisted_fakes(
            f"{_REAL_LOOKING} {_OTHER_REAL_LOOKING}", {"session-uuid": _UUID_RE}, registry
        )
        assert text == f"{_ALL_A} {_ALL_B}"
        assert [swap.replacement for swap in swaps] == [_ALL_A, _ALL_B]

    def test_listed_value_in_the_text_is_left_alone_and_not_reused(
        self, registry: FakeValuesRegistry
    ) -> None:
        text, swaps = swap_unlisted_fakes(
            f"{_ALL_A} {_REAL_LOOKING}", {"session-uuid": _UUID_RE}, registry
        )
        assert text == f"{_ALL_A} {_ALL_B}"
        assert [swap.replacement for swap in swaps] == [_ALL_B]

    def test_text_without_unlisted_values_is_returned_unchanged(
        self, registry: FakeValuesRegistry
    ) -> None:
        text, swaps = swap_unlisted_fakes(_ALL_A, {"session-uuid": _UUID_RE}, registry)
        assert text == _ALL_A
        assert swaps == ()

    def test_a_kind_the_registry_does_not_list_is_never_swapped(
        self, registry: FakeValuesRegistry
    ) -> None:
        text, swaps = swap_unlisted_fakes(_REAL_LOOKING, {"profanity": _UUID_RE}, registry)
        assert text == _REAL_LOOKING
        assert swaps == ()

    def test_running_out_of_listed_fakes_fails_fast(self, registry: FakeValuesRegistry) -> None:
        with pytest.raises(FakeValuesError, match="no unused listed fake"):
            swap_unlisted_fakes(
                f"{_REAL_LOOKING} {_OTHER_REAL_LOOKING} {_THIRD_REAL_LOOKING}",
                {"session-uuid": _UUID_RE},
                registry,
            )
