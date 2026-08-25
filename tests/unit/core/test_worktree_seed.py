"""Tests for worktree seed-config parsing (Plan 00267 Phase 2).

The parser turns a project's raw ``options.seed`` YAML into validated
:class:`SeedEntry` objects. Two rules it exists to enforce:

**Shape errors degrade, they never raise.** One bad line in a project's YAML
must not take down worktree creation entirely — the same fail-open convention
``command_hints`` and ``sensitive_content`` use for their own option parsing.

**A bare string must never be iterated per character.** Handler options reach a
handler through an unvalidated ``setattr``, so a string written where a list
belongs arrives intact. The predecessor of this feature iterated
``".env.local"`` into ``'.'``, ``'e'``, ``'n'``… and silently seeded nothing —
a misconfiguration that produced no error and no seeded files. Several tests
below exist solely to pin that.
"""

from __future__ import annotations

import logging

import pytest

from claude_code_hooks_daemon.core.worktree_seed import (
    SEED_MODE_COPY,
    SEED_MODE_SYMLINK,
    SeedEntry,
    parse_seed_config,
)


class TestSeedEntry:
    """The TRUSTED construction path fails fast, per the house split."""

    def test_valid_entry_is_constructed(self) -> None:
        entry = SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)
        assert entry.path == ".env.local"
        assert entry.mode == SEED_MODE_SYMLINK

    def test_empty_path_raises(self) -> None:
        with pytest.raises(ValueError, match="path"):
            SeedEntry(path="", mode=SEED_MODE_SYMLINK)

    def test_whitespace_only_path_raises(self) -> None:
        with pytest.raises(ValueError, match="path"):
            SeedEntry(path="   ", mode=SEED_MODE_SYMLINK)

    def test_unknown_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="mode"):
            SeedEntry(path=".env.local", mode="hardlink")

    def test_entries_are_hashable_so_they_can_be_deduplicated(self) -> None:
        """Frozen, and therefore usable in the set arithmetic Phase 4's diff needs."""
        first = SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)
        second = SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)
        assert {first, second} == {first}


class TestParseUnconfigured:
    def test_none_is_empty(self) -> None:
        assert parse_seed_config(None) == []

    def test_empty_dict_is_empty(self) -> None:
        assert parse_seed_config({}) == []

    def test_absent_entries_is_empty(self) -> None:
        assert parse_seed_config({"default_mode": SEED_MODE_COPY}) == []

    def test_empty_entries_list_is_empty(self) -> None:
        assert parse_seed_config({"entries": []}) == []


class TestParseRejectsBareStrings:
    """The silent-no-op bug this parser exists to prevent."""

    def test_bare_string_seed_is_rejected_not_iterated(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            assert parse_seed_config(".env.local") == []
        assert "seed" in caplog.text.lower()

    def test_bare_string_entries_is_rejected_not_iterated(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            result = parse_seed_config({"entries": ".env.local"})
        assert result == []
        # Character iteration would have produced single-character paths.
        assert not any(len(entry.path) == 1 for entry in result)
        assert "entries" in caplog.text.lower()

    def test_entries_as_dict_is_rejected(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            assert parse_seed_config({"entries": {"path": ".env.local"}}) == []


class TestParseEntries:
    def test_string_entry_uses_default_mode(self) -> None:
        parsed = parse_seed_config({"default_mode": SEED_MODE_COPY, "entries": [".env.local"]})
        assert parsed == [SeedEntry(path=".env.local", mode=SEED_MODE_COPY)]

    def test_default_mode_defaults_to_symlink(self) -> None:
        parsed = parse_seed_config({"entries": [".env.local"]})
        assert parsed == [SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)]

    def test_dict_entry_mode_overrides_the_default(self) -> None:
        parsed = parse_seed_config(
            {
                "default_mode": SEED_MODE_SYMLINK,
                "entries": [{"path": ".secrets", "mode": SEED_MODE_COPY}],
            }
        )
        assert parsed == [SeedEntry(path=".secrets", mode=SEED_MODE_COPY)]

    def test_dict_entry_without_mode_uses_default(self) -> None:
        parsed = parse_seed_config(
            {"default_mode": SEED_MODE_COPY, "entries": [{"path": ".secrets"}]}
        )
        assert parsed == [SeedEntry(path=".secrets", mode=SEED_MODE_COPY)]

    def test_string_and_dict_entries_mix(self) -> None:
        parsed = parse_seed_config(
            {"entries": [".env.local", {"path": ".secrets", "mode": SEED_MODE_COPY}]}
        )
        assert parsed == [
            SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK),
            SeedEntry(path=".secrets", mode=SEED_MODE_COPY),
        ]

    def test_entry_path_is_stripped(self) -> None:
        parsed = parse_seed_config({"entries": ["  .env.local  "]})
        assert parsed == [SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)]


class TestParseDegradesOnBadShape:
    """Malformed input warns and skips; it never raises and never aborts."""

    def test_invalid_default_mode_falls_back_to_symlink(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            parsed = parse_seed_config({"default_mode": "hardlink", "entries": [".env.local"]})
        assert parsed == [SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)]
        assert "default_mode" in caplog.text

    def test_entry_with_unknown_mode_is_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            parsed = parse_seed_config({"entries": [{"path": ".env.local", "mode": "hardlink"}]})
        assert parsed == []
        assert "mode" in caplog.text

    def test_entry_missing_path_is_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            parsed = parse_seed_config({"entries": [{"mode": SEED_MODE_COPY}]})
        assert parsed == []
        assert "path" in caplog.text

    def test_entry_with_unknown_key_is_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            parsed = parse_seed_config({"entries": [{"path": ".env.local", "recursive": True}]})
        assert parsed == []
        assert "recursive" in caplog.text

    def test_non_string_non_dict_entry_is_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            parsed = parse_seed_config({"entries": [42]})
        assert parsed == []

    def test_blank_string_entry_is_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            parsed = parse_seed_config({"entries": ["   "]})
        assert parsed == []

    def test_one_bad_entry_does_not_discard_the_good_ones(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            parsed = parse_seed_config(
                {"entries": [".env.local", 42, {"path": ".secrets", "mode": SEED_MODE_COPY}]}
            )
        assert parsed == [
            SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK),
            SeedEntry(path=".secrets", mode=SEED_MODE_COPY),
        ]

    def test_unknown_top_level_key_is_warned_but_entries_still_parse(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            parsed = parse_seed_config({"entries": [".env.local"], "mode": SEED_MODE_COPY})
        assert parsed == [SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)]
        assert "mode" in caplog.text

    def test_a_list_at_the_top_level_is_rejected(self, caplog: pytest.LogCaptureFixture) -> None:
        """A project might reasonably guess ``seed:`` is itself the list."""
        with caplog.at_level(logging.WARNING):
            assert parse_seed_config([".env.local"]) == []
