"""The record listing: every exception, with the reason it carries (Plan 00484 G12).

``hooks-daemon exceptions`` lists what exempts something from a guard: the
config exceptions (``exclude_paths``, ``extra_whitelist``), a handler switched
off or downgraded, the in-file ``MUST_EXCEED_*_BECAUSE`` hatches (closing G3's
"list them" half), and the fixed set of exception files the QA scripts read.
One test per source.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from claude_code_hooks_daemon.config.exceptions_listing import (
    QA_EXCEPTION_FILES,
    SOURCE_CONFIG_EXCEPTION,
    SOURCE_DISABLED_HANDLER,
    SOURCE_DOWNGRADED_HANDLER,
    SOURCE_IN_FILE_HATCH,
    SOURCE_QA_EXCEPTION_FILE,
    ExceptionRecord,
    collect_config_exceptions,
    collect_in_file_hatches,
    collect_qa_exception_files,
)
from claude_code_hooks_daemon.daemon.cli import cmd_exceptions

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _by_source(records: list[ExceptionRecord], source: str) -> list[ExceptionRecord]:
    return [r for r in records if r.source == source]


class TestConfigExceptions:
    def test_a_reasoned_entry_carries_its_reason(self) -> None:
        config: dict[str, Any] = {
            "handlers": {
                "pre_tool_use": {
                    "sensitive_content": {
                        "options": {
                            "exclude_paths": [
                                {"pattern": "vendor/**", "reason": "third-party code"}
                            ]
                        }
                    }
                }
            }
        }
        (record,) = _by_source(collect_config_exceptions(config), SOURCE_CONFIG_EXCEPTION)
        assert record.value == "vendor/**"
        assert record.reason == "third-party code"
        assert record.location == "handlers.pre_tool_use.sensitive_content.options.exclude_paths"

    def test_a_plain_entry_has_no_reason(self) -> None:
        config: dict[str, Any] = {"daemon": {"exclude_paths": ["legacy/**"]}}
        (record,) = _by_source(collect_config_exceptions(config), SOURCE_CONFIG_EXCEPTION)
        assert (record.value, record.reason) == ("legacy/**", None)
        assert record.location == "daemon.exclude_paths"

    def test_extra_whitelist_is_listed_too(self) -> None:
        config: dict[str, Any] = {
            "handlers": {
                "pre_tool_use": {"pipe_blocker": {"options": {"extra_whitelist": ["^mytool\\b"]}}}
            }
        }
        (record,) = collect_config_exceptions(config)
        assert record.value == "^mytool\\b"
        assert record.location.endswith("pipe_blocker.options.extra_whitelist")

    def test_a_disabled_handler_is_listed_with_no_reason(self) -> None:
        config: dict[str, Any] = {"handlers": {"stop": {"auto_continue_stop": {"enabled": False}}}}
        (record,) = _by_source(collect_config_exceptions(config), SOURCE_DISABLED_HANDLER)
        assert record.location == "handlers.stop.auto_continue_stop"
        assert record.reason is None

    def test_an_enabled_handler_is_not_listed(self) -> None:
        config: dict[str, Any] = {"handlers": {"stop": {"auto_continue_stop": {"enabled": True}}}}
        assert collect_config_exceptions(config) == []

    def test_a_handler_set_to_warn_is_listed_as_downgraded(self) -> None:
        config: dict[str, Any] = {
            "handlers": {"pre_tool_use": {"bash_safe_mode": {"options": {"mode": "warn"}}}}
        }
        (record,) = _by_source(collect_config_exceptions(config), SOURCE_DOWNGRADED_HANDLER)
        assert record.location == "handlers.pre_tool_use.bash_safe_mode"
        assert record.value == "mode: warn"

    def test_a_handler_in_another_mode_is_not_listed(self) -> None:
        config: dict[str, Any] = {
            "handlers": {"pre_tool_use": {"bash_safe_mode": {"options": {"mode": "block"}}}}
        }
        assert collect_config_exceptions(config) == []

    def test_a_config_with_no_handlers_lists_nothing(self) -> None:
        assert collect_config_exceptions({}) == []


class TestInFileHatches:
    def test_a_comment_size_hatch_is_listed_with_file_line_and_reason(self, tmp_path: Path) -> None:
        source = tmp_path / "a.py"
        source.write_text(
            "x = 1\n# MUST_EXCEED_COMMENT_SIZE_BECAUSE: verbatim upstream licence text\n",
            encoding="utf-8",
        )
        (record,) = collect_in_file_hatches(tmp_path, [Path("a.py")])
        assert record.source == SOURCE_IN_FILE_HATCH
        assert record.location == "a.py:2"
        assert record.value == "MUST_EXCEED_COMMENT_SIZE_BECAUSE"
        assert record.reason == "verbatim upstream licence text"

    def test_a_plan_size_hatch_inside_an_html_comment_loses_the_closer(
        self, tmp_path: Path
    ) -> None:
        doc = tmp_path / "PLAN.md"
        doc.write_text("<!-- MUST_EXCEED_PLAN_SIZE_BECAUSE: one long audit table -->\n")
        (record,) = collect_in_file_hatches(tmp_path, [Path("PLAN.md")])
        assert record.value == "MUST_EXCEED_PLAN_SIZE_BECAUSE"
        assert record.reason == "one long audit table"

    def test_documentation_naming_the_placeholder_is_not_a_hatch(self, tmp_path: Path) -> None:
        doc = tmp_path / "doc.md"
        doc.write_text("Write `<!-- MUST_EXCEED_PLAN_SIZE_BECAUSE: <reason> -->` to opt out.\n")
        assert collect_in_file_hatches(tmp_path, [Path("doc.md")]) == []

    @pytest.mark.parametrize(
        "line",
        [
            'text = "# MUST_EXCEED_COMMENT_SIZE_BECAUSE: licence text\\n"',
            "Use `# MUST_EXCEED_COMMENT_SIZE_BECAUSE: licence text` to opt out.",
            "The MUST_EXCEED_COMMENT_SIZE_BECAUSE: licence text hatch exists.",
        ],
    )
    def test_a_mention_of_the_hatch_in_code_or_prose_is_not_a_declaration(
        self, line: str, tmp_path: Path
    ) -> None:
        (tmp_path / "m.py").write_text(line + "\n", encoding="utf-8")
        assert collect_in_file_hatches(tmp_path, [Path("m.py")]) == []

    def test_a_file_without_a_hatch_lists_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "b.py").write_text("print('hi')\n", encoding="utf-8")
        assert collect_in_file_hatches(tmp_path, [Path("b.py")]) == []

    def test_a_binary_file_is_skipped_not_an_error(self, tmp_path: Path) -> None:
        (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00MUST_EXCEED_COMMENT_SIZE_BECAUSE: x")
        assert collect_in_file_hatches(tmp_path, [Path("blob.bin")]) == []


class TestQaExceptionFiles:
    def test_only_files_present_in_the_project_are_listed(self, tmp_path: Path) -> None:
        present = QA_EXCEPTION_FILES[0]
        (tmp_path / present).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / present).write_text("{}", encoding="utf-8")
        records = collect_qa_exception_files(tmp_path)
        assert [r.location for r in records] == [present]
        assert records[0].source == SOURCE_QA_EXCEPTION_FILE

    def test_every_declared_file_exists_in_this_repository(self) -> None:
        """A renamed or deleted exception file must be re-declared, not silently dropped."""
        missing = [path for path in QA_EXCEPTION_FILES if not (_REPO_ROOT / path).is_file()]
        assert missing == []


class TestCmdExceptions:
    def _project(self, root: Path, *, git: bool = True) -> None:
        if git:
            subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / ".claude").mkdir()
        (root / ".claude" / "hooks-daemon.yaml").write_text(
            yaml.safe_dump({"daemon": {"exclude_paths": ["legacy/**"]}}), encoding="utf-8"
        )

    def _args(self, root: Path, as_json: bool) -> argparse.Namespace:
        return argparse.Namespace(project_root=root, json=as_json)

    def test_json_lists_every_record(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._project(tmp_path)
        assert cmd_exceptions(self._args(tmp_path, True)) == 0
        records = json.loads(capsys.readouterr().out)
        assert {"source", "location", "value", "reason"} <= set(records[0])
        assert any(r["value"] == "legacy/**" and r["reason"] is None for r in records)

    def test_text_marks_an_exception_that_has_no_reason(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._project(tmp_path)
        assert cmd_exceptions(self._args(tmp_path, False)) == 0
        assert "(no reason)" in capsys.readouterr().out

    def test_untracked_hatches_are_not_listed_but_tracked_ones_are(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._project(tmp_path)
        (tmp_path / "t.py").write_text("# MUST_EXCEED_COMMENT_SIZE_BECAUSE: licence text\n")
        (tmp_path / "u.py").write_text("# MUST_EXCEED_COMMENT_SIZE_BECAUSE: scratch\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "t.py"], check=True)
        assert cmd_exceptions(self._args(tmp_path, True)) == 0
        hatches = [r for r in json.loads(capsys.readouterr().out) if r["source"] == "in-file-hatch"]
        assert [r["location"] for r in hatches] == ["t.py:1"]

    def test_a_project_that_is_not_a_git_repository_is_an_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._project(tmp_path, git=False)
        assert cmd_exceptions(self._args(tmp_path, False)) == 1
        assert "tracked files" in capsys.readouterr().err

    def test_a_missing_config_is_an_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_exceptions(self._args(tmp_path, False)) == 1
        assert "hooks-daemon.yaml" in capsys.readouterr().err
