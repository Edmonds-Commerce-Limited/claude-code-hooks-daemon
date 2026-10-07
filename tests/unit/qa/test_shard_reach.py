"""Which shards a change can reach: the declared floors and whole-suite triggers.

``changed`` used to give up on a file it could not map to named tests. The
shard reach narrows that give-up to the shards the file can touch, and keeps
the whole suite where nothing sound can be said.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from claude_code_hooks_daemon.qa.shard_reach import (
    ShardReach,
    floor_shards,
    load_shard_reach,
    path_glob_matches,
    shard_targets,
    whole_suite_reason,
)
from claude_code_hooks_daemon.qa.suite_shards import Shard, ShardError, load_shards

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REACH_FILE = PROJECT_ROOT / "scripts" / "qa" / "changed_shard_reach.yaml"
SHARDS_FILE = PROJECT_ROOT / "scripts" / "qa" / "test_shards.yaml"

SHARDS = [
    Shard("unit-a", "unit", ("tests/unit/a",)),
    Shard("unit-rest", "unit", ("tests/unit",), ("tests/unit/a",)),
    Shard("integration", "rest", ("tests/integration",)),
]


def _write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "reach.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def _document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "whole_suite": [{"path_glob": "pyproject.toml", "why": "the build config"}],
        "floors": [
            {"path_glob": "src/**/*.py", "shards": ["integration"], "why": "end to end"},
        ],
    }
    document.update(overrides)
    return document


class TestPathGlob:
    def test_star_stays_in_one_directory(self) -> None:
        assert path_glob_matches("a/b.py", "a/*.py")
        assert not path_glob_matches("a/c/b.py", "a/*.py")

    def test_double_star_is_any_depth_including_none(self) -> None:
        assert path_glob_matches("a/b.py", "a/**/*.py")
        assert path_glob_matches("a/c/d/b.py", "a/**/*.py")


class TestLoading:
    def test_a_valid_file_loads(self, tmp_path: Path) -> None:
        reach = load_shard_reach(_write(tmp_path, _document()), SHARDS)
        assert isinstance(reach, ShardReach)
        assert reach.floors[0].shards == ("integration",)

    def test_a_floor_naming_an_unknown_shard_is_refused(self, tmp_path: Path) -> None:
        document = _document(floors=[{"path_glob": "src/**", "shards": ["nope"], "why": "x"}])
        with pytest.raises(ShardError, match="nope"):
            load_shard_reach(_write(tmp_path, document), SHARDS)

    def test_a_rule_without_a_why_is_refused(self, tmp_path: Path) -> None:
        document = _document(whole_suite=[{"path_glob": "pyproject.toml"}])
        with pytest.raises(ShardError, match="why"):
            load_shard_reach(_write(tmp_path, document), SHARDS)

    def test_an_unknown_key_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ShardError, match="unknown"):
            load_shard_reach(_write(tmp_path, _document(extra=[])), SHARDS)

    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ShardError, match="cannot read"):
            load_shard_reach(tmp_path / "absent.yaml", SHARDS)

    def test_a_floor_with_no_shards_is_refused(self, tmp_path: Path) -> None:
        document = _document(floors=[{"path_glob": "src/**", "shards": [], "why": "x"}])
        with pytest.raises(ShardError, match="shards"):
            load_shard_reach(_write(tmp_path, document), SHARDS)


class TestJudging:
    def test_a_whole_suite_trigger_gives_its_reason(self, tmp_path: Path) -> None:
        reach = load_shard_reach(_write(tmp_path, _document()), SHARDS)
        assert whole_suite_reason(reach, "pyproject.toml") == "the build config"
        assert whole_suite_reason(reach, "src/pkg/a.py") is None

    def test_floor_shards_are_the_union_of_every_matching_floor(self, tmp_path: Path) -> None:
        document = _document(
            floors=[
                {"path_glob": "src/**/*.py", "shards": ["integration"], "why": "end to end"},
                {"path_glob": "src/pkg/*.py", "shards": ["unit-a"], "why": "its own unit tests"},
            ]
        )
        reach = load_shard_reach(_write(tmp_path, document), SHARDS)
        names, whys = floor_shards(reach, "src/pkg/a.py")
        assert names == {"integration", "unit-a"}
        assert whys == ["end to end", "its own unit tests"]
        assert floor_shards(reach, "docs/a.py") == (set(), [])


class TestTargets:
    def test_a_path_shard_runs_its_directories(self, tmp_path: Path) -> None:
        assert shard_targets(SHARDS[0], tmp_path) == ["tests/unit/a"]

    def test_a_remainder_shard_runs_explicit_files_so_nothing_is_double_run(
        self, tmp_path: Path
    ) -> None:
        for relative in (
            "tests/unit/a/test_x.py",
            "tests/unit/b/test_y.py",
            "tests/unit/test_z.py",
        ):
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
        assert shard_targets(SHARDS[1], tmp_path) == [
            "tests/unit/b/test_y.py",
            "tests/unit/test_z.py",
        ]


class TestTheRealDeclaration:
    """The shipped file must load against the shipped shards."""

    def test_it_loads(self) -> None:
        reach = load_shard_reach(REACH_FILE, load_shards(SHARDS_FILE))
        assert reach.floors
        assert reach.whole_suite

    @pytest.mark.parametrize(
        "relative",
        [
            "pyproject.toml",
            "uv.lock",
            "tests/conftest.py",
            "tests/support/helper.py",
            "scripts/qa/llm_qa.py",
        ],
    )
    def test_what_nothing_sound_can_be_said_about_is_the_whole_suite(self, relative: str) -> None:
        reach = load_shard_reach(REACH_FILE, load_shards(SHARDS_FILE))
        assert whole_suite_reason(reach, relative)

    def test_a_handler_floor_includes_the_end_to_end_shards(self) -> None:
        reach = load_shard_reach(REACH_FILE, load_shards(SHARDS_FILE))
        names, _ = floor_shards(reach, "src/claude_code_hooks_daemon/handlers/pre_tool_use/x.py")
        assert {"unit-handlers", "integration", "acceptance-and-other"} <= names
