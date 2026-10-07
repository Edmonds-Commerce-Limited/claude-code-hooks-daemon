"""The test-suite shards (Plan 00500 Task 2.4): declared once, enforced to partition ``tests/``.

``scripts/qa/test_shards.yaml`` names every shard and the pytest paths it runs.
A sharded run that silently dropped or double-ran a test would make the gate
lie, so the real declaration is checked here against every test file on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.qa.suite_shards import (
    SCOPE_REST,
    SCOPE_UNIT,
    Shard,
    ShardError,
    collected_test_files,
    load_shards,
    owning_shards,
    shards_in_scope,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SHARDS_FILE = PROJECT_ROOT / "scripts" / "qa" / "test_shards.yaml"


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "shards.yaml"
    path.write_text(text, encoding="utf-8")
    return path


_VALID = """
shards:
  - name: unit-a
    scope: unit
    paths: [tests/unit/a]
  - name: unit-rest
    scope: unit
    remainder_of: tests/unit
  - name: other
    scope: rest
    remainder_of: tests
"""


class TestLoadShards:
    def test_a_remainder_shard_ignores_what_the_other_shards_claim(self, tmp_path: Path) -> None:
        shards = {s.name: s for s in load_shards(_write(tmp_path, _VALID))}

        assert shards["unit-a"].pytest_args == ["tests/unit/a"]
        assert shards["unit-rest"].pytest_args == ["tests/unit", "--ignore=tests/unit/a"]
        # tests/unit is already ignored whole, so its sub-paths are not repeated.
        assert shards["other"].pytest_args == ["tests", "--ignore=tests/unit"]

    def test_declaration_order_is_kept(self, tmp_path: Path) -> None:
        names = [s.name for s in load_shards(_write(tmp_path, _VALID))]

        assert names == ["unit-a", "unit-rest", "other"]

    def test_shards_in_scope_selects_by_scope_in_order(self, tmp_path: Path) -> None:
        shards = load_shards(_write(tmp_path, _VALID))

        assert [s.name for s in shards_in_scope(shards, SCOPE_UNIT)] == ["unit-a", "unit-rest"]
        assert [s.name for s in shards_in_scope(shards, SCOPE_REST)] == ["other"]

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("shards: []\n", "no shards"),
            ("not: shards\n", "shards"),
            ("shards:\n  - {name: A b, scope: unit, paths: [tests/x]}\n", "name"),
            (
                "shards:\n  - {name: a, scope: unit, paths: [tests/x]}\n"
                "  - {name: a, scope: rest, paths: [tests/y]}\n",
                "duplicate",
            ),
            ("shards:\n  - {name: a, scope: weird, paths: [tests/x]}\n", "scope"),
            ("shards:\n  - {name: a, scope: unit}\n", "exactly one"),
            (
                "shards:\n  - {name: a, scope: unit, paths: [tests/x], remainder_of: tests}\n",
                "exactly one",
            ),
            ("shards:\n  - {name: a, scope: unit, paths: []}\n", "paths"),
            ("shards:\n  - {name: a, scope: unit, paths: [/abs/tests]}\n", "relative"),
            ("shards:\n  - {name: a, scope: unit, paths: [tests/../x]}\n", "relative"),
            (
                "shards:\n  - {name: a, scope: unit, remainder_of: tests}\n"
                "  - {name: b, scope: rest, remainder_of: tests}\n",
                "remainder",
            ),
            ("shards:\n  - {name: a, scope: unit, paths: [tests/x], extra: 1}\n", "unknown"),
        ],
    )
    def test_a_malformed_declaration_fails_fast(
        self, tmp_path: Path, text: str, message: str
    ) -> None:
        with pytest.raises(ShardError, match=message):
            load_shards(_write(tmp_path, text))

    def test_a_missing_file_fails_fast(self, tmp_path: Path) -> None:
        with pytest.raises(ShardError, match="cannot read"):
            load_shards(tmp_path / "absent.yaml")

    def test_unparseable_yaml_fails_fast(self, tmp_path: Path) -> None:
        with pytest.raises(ShardError, match="cannot parse"):
            load_shards(_write(tmp_path, "shards: [unclosed\n"))


class TestOwningShards:
    def test_a_file_belongs_to_the_shard_whose_path_holds_it_and_does_not_ignore_it(
        self, tmp_path: Path
    ) -> None:
        shards = load_shards(_write(tmp_path, _VALID))

        assert [s.name for s in owning_shards(shards, "tests/unit/a/test_x.py")] == ["unit-a"]
        assert [s.name for s in owning_shards(shards, "tests/unit/b/test_x.py")] == ["unit-rest"]
        assert [s.name for s in owning_shards(shards, "tests/unit/test_top.py")] == ["unit-rest"]
        assert [s.name for s in owning_shards(shards, "tests/acceptance/test_y.py")] == ["other"]

    def test_a_path_prefix_that_is_not_a_directory_boundary_does_not_match(
        self, tmp_path: Path
    ) -> None:
        shards = load_shards(
            _write(
                tmp_path,
                "shards:\n  - {name: a, scope: unit, paths: [tests/unit/a]}\n",
            )
        )

        assert owning_shards(shards, "tests/unit/abc/test_x.py") == []

    def test_a_file_path_can_be_claimed_directly(self, tmp_path: Path) -> None:
        shards = load_shards(
            _write(tmp_path, "shards:\n  - {name: f, scope: rest, paths: [tests/test_one.py]}\n")
        )

        assert [s.name for s in owning_shards(shards, "tests/test_one.py")] == ["f"]


class TestCollectedTestFiles:
    def test_lists_test_files_relative_to_the_root_and_skips_hidden_and_cache_dirs(
        self, tmp_path: Path
    ) -> None:
        for relative in (
            "tests/unit/test_a.py",
            "tests/unit/helper.py",
            "tests/integration/sub/test_b.py",
            "tests/unit/__pycache__/test_c.py",
            "tests/.hidden/test_d.py",
        ):
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

        assert collected_test_files(tmp_path, "tests") == [
            "tests/integration/sub/test_b.py",
            "tests/unit/test_a.py",
        ]


class TestTheDeclaredShards:
    """The real ``scripts/qa/test_shards.yaml`` against the real ``tests/`` tree."""

    @pytest.fixture(scope="class")
    def shards(self) -> list[Shard]:
        return load_shards(SHARDS_FILE)

    def test_every_collected_test_file_belongs_to_exactly_one_shard(
        self, shards: list[Shard]
    ) -> None:
        files = collected_test_files(PROJECT_ROOT, "tests")
        assert files, "found no test files: the walk is broken"

        unowned = [f for f in files if not owning_shards(shards, f)]
        doubled = {
            f: [s.name for s in owning_shards(shards, f)]
            for f in files
            if len(owning_shards(shards, f)) > 1
        }

        assert unowned == [], f"in no shard (would never run): {unowned[:10]}"
        assert (
            doubled == {}
        ), f"in several shards (would run twice): {dict(list(doubled.items())[:10])}"

    def test_unit_scope_is_exactly_tests_unit_and_rest_scope_everything_else(
        self, shards: list[Shard]
    ) -> None:
        for file in collected_test_files(PROJECT_ROOT, "tests"):
            (owner,) = owning_shards(shards, file)
            expected = SCOPE_UNIT if file.startswith("tests/unit/") else SCOPE_REST
            assert owner.scope == expected, f"{file} is in {owner.name} ({owner.scope})"

    def test_every_declared_path_exists(self, shards: list[Shard]) -> None:
        for shard in shards:
            for path in (*shard.paths, *shard.ignore):
                assert (PROJECT_ROOT / path).exists(), f"{shard.name}: {path} does not exist"

    def test_there_are_a_handful_of_shards(self, shards: list[Shard]) -> None:
        assert 4 <= len(shards) <= 8
