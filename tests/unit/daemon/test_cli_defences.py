"""Tests for `hooks-daemon defences` (Plan 00484 Task 3.2).

Run against the repository's own config and real handlers, so the listing is
checked against the same sources `generate-docs` and `explain-rule` read.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_defences

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {"as_json": True, "project_root": _REPO_ROOT}
    values.update(overrides)
    return argparse.Namespace(**values)


class TestCmdDefences:
    def test_json_is_a_list_of_records(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cmd_defences(_args()) == 0
        records = json.loads(capsys.readouterr().out)
        assert isinstance(records, list)
        assert records
        assert {"rule_id", "handler", "defect_class", "docs", "detector_entry_point"} <= set(
            records[0]
        )

    def test_known_active_rule_is_listed_with_its_docs_route(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_defences(_args()) == 0
        records = json.loads(capsys.readouterr().out)
        by_id = {record["rule_id"]: record for record in records if record["rule_id"]}
        record = by_id["R-QA-SUPPRESSION"]
        assert record["handler"] == "qa_suppression"
        assert record["docs"] == "hooks-daemon explain-rule R-QA-SUPPRESSION"
        assert record["event"] == "pre_tool_use"

    def test_every_record_names_a_defect_class(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cmd_defences(_args()) == 0
        records = json.loads(capsys.readouterr().out)
        assert all(record["defect_class"] for record in records)
        by_id = {record["rule_id"]: record for record in records if record["rule_id"]}
        assert by_id["R-QA-SUPPRESSION"]["defect_class"] == "qa-suppression"

    def test_action_guards_are_not_listed(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Owner ruling C1: the action guards are outside the Defence set."""
        assert cmd_defences(_args()) == 0
        listed = {record["handler"] for record in json.loads(capsys.readouterr().out)}
        assert not listed & {"destructive_git", "sed_blocker", "pipe_blocker", "git_stash"}

    def test_listing_is_exactly_the_handlers_that_declare_a_defect_class(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from claude_code_hooks_daemon.rule_explain.lookup import discover_handler_rules

        assert cmd_defences(_args()) == 0
        listed = {record["handler_class"] for record in json.loads(capsys.readouterr().out)}
        declared = {
            entry.class_name
            for entry in discover_handler_rules(include_project_handlers=True)
            if entry.defect_class is not None
        }
        assert listed <= declared
        assert len(listed) > 10

    def test_every_listed_rule_id_resolves_with_explain_rule(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from claude_code_hooks_daemon.daemon.cli import cmd_explain_rule

        assert cmd_defences(_args()) == 0
        records = json.loads(capsys.readouterr().out)
        ids = {record["rule_id"] for record in records if record["rule_id"]}
        capsys.readouterr()
        assert (
            cmd_explain_rule(
                argparse.Namespace(rule_id=None, list_rules=True, project_root=str(_REPO_ROOT))
            )
            == 0
        )
        known = {line.split("\t")[0] for line in capsys.readouterr().out.splitlines()}
        assert ids <= known

    def test_text_mode_prints_one_tab_separated_line_per_record(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_defences(_args(as_json=False)) == 0
        lines = capsys.readouterr().out.splitlines()
        assert any(line.startswith("R-QA-SUPPRESSION\tqa_suppression\t") for line in lines)

    def test_uninstalled_project_fails_fast(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / ".claude").mkdir()
        assert cmd_defences(_args(project_root=tmp_path)) == 1
        assert "not installed" in capsys.readouterr().err

    def test_missing_config_file_fails_fast(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(cli, "get_project_path", lambda _override: tmp_path)
        assert cmd_defences(_args(project_root=tmp_path)) == 1
        assert "hooks-daemon.yaml" in capsys.readouterr().err


class TestDefencesParser:
    def test_subcommand_is_registered_with_json_flag(self) -> None:
        parsed = build_parser().parse_args(["defences", "--json"])
        assert parsed.as_json is True
        assert parsed.func is cmd_defences
