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
        listed = {
            record["handler_class"]
            for record in json.loads(capsys.readouterr().out)
            if record["kind"] == "handler"
        }
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
        # A batch-check row's ID resolves with `llm_qa.py --explain`, not `explain-rule`.
        ids = {
            record["rule_id"]
            for record in records
            if record["rule_id"] and record["kind"] == "handler"
        }
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

    def test_batch_checks_are_listed_with_the_defect_class_of_their_handler(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_defences(_args()) == 0
        records = json.loads(capsys.readouterr().out)
        batch = [record for record in records if record["kind"] == "batch-check"]
        assert {record["handler_class"] for record in batch} == {
            "check_british_english.py",
            "audit_error_hiding.py",
            "check_sensitive_content.py",
            "check_inline_suppressions.py",
        }
        by_script = {record["handler_class"]: record["defect_class"] for record in batch}
        assert by_script["audit_error_hiding.py"] == "error-hiding"
        assert by_script["check_sensitive_content.py"] == "sensitive-content"
        assert by_script["check_inline_suppressions.py"] == "qa-suppression"
        assert by_script["check_british_english.py"] == "american-spelling"
        assert all(
            record["docs"].startswith("./scripts/qa/llm_qa.py --explain ") for record in batch
        )
        assert all(record["detector_entry_point"] for record in batch)

    def test_handler_rows_are_kind_handler(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cmd_defences(_args()) == 0
        records = json.loads(capsys.readouterr().out)
        by_id = {record["rule_id"]: record for record in records if record["rule_id"]}
        assert by_id["R-QA-SUPPRESSION"]["kind"] == "handler"

    def test_batch_defence_defect_classes_match_their_handlers(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The class of a batch row is the class its write-time handler declares."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.error_hiding_blocker import (
            ErrorHidingBlockerHandler,
        )
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )
        from claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content import (
            SensitiveContentHandler,
        )

        assert cmd_defences(_args()) == 0
        records = json.loads(capsys.readouterr().out)
        by_script = {
            record["handler_class"]: record["defect_class"]
            for record in records
            if record["kind"] == "batch-check"
        }
        assert by_script["audit_error_hiding.py"] == ErrorHidingBlockerHandler.defect_class
        assert by_script["check_inline_suppressions.py"] == QaSuppressionHandler.defect_class
        assert by_script["check_sensitive_content.py"] == SensitiveContentHandler.defect_class

    def test_text_mode_shows_batch_rows_with_their_kind(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_defences(_args(as_json=False)) == 0
        lines = capsys.readouterr().out.splitlines()
        assert any(line.startswith("american-spelling\tbritish_english\t") for line in lines)
        assert all(line.split("\t")[-1] in {"handler", "batch-check"} for line in lines)

    def test_project_without_a_qa_rules_file_lists_handler_rows_only(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from claude_code_hooks_daemon.rule_explain import defences

        monkeypatch.setattr(defences, "QA_RULES_RELATIVE_PATH", "no/such/qa-rules.json")
        assert cmd_defences(_args()) == 0
        records = json.loads(capsys.readouterr().out)
        assert {record["kind"] for record in records} == {"handler"}

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
