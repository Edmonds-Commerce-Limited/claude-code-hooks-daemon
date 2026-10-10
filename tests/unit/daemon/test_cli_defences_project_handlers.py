"""``defences`` gives a project handler a ``--only`` entry point that ``probe`` accepts.

The docs generator files a project handler under the event ``project`` (or its
class name as the key), neither of which ``probe --only`` knows. The listing
must name the handler's real event and its config key, and the command it
prints must be one ``probe`` takes (Plan 00484 G11).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.cli import cmd_defences, cmd_init_config
from claude_code_hooks_daemon.daemon.hook_probe import build_probe_event, resolve_probe_event

_HANDLER_SOURCE = '''"""Project handler fixture that is a Defence."""

from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.constants.dbf import DefectClass
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.rule import Rule


class CanaryDefenceHandler(Handler):
    """Blocks nothing; declares a defect class and one rule."""

    defect_class: ClassVar[DefectClass | None] = DefectClass.QA_SUPPRESSION

    def __init__(self) -> None:
        super().__init__(
            handler_id="canary-defence-handler",
            priority=Priority.PLAN_WORKFLOW,
            terminal=False,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []

    def get_rules(self) -> list[Rule]:
        return [
            Rule(
                rule_id="R-PROJECT-CANARY",
                blocked="a canary",
                why="to be listed",
                fix="nothing",
                verbose="A canary rule for the defences listing.",
            )
        ]
'''


def _scaffold_project(tmp_path: Path) -> Path:
    """A git-backed project with one project handler under ``pre_tool_use``."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.com/acme/demo-project.git"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "hooks-daemon").mkdir()
    assert (
        cmd_init_config(argparse.Namespace(project_root=tmp_path, minimal=False, force=False)) == 0
    )
    handlers_dir = claude_dir / "project-handlers" / "pre_tool_use"
    handlers_dir.mkdir(parents=True)
    (handlers_dir / "__init__.py").write_text("")
    (handlers_dir / "canary_defence_handler.py").write_text(_HANDLER_SOURCE)
    config_path = claude_dir / "hooks-daemon.yaml"
    config_text = config_path.read_text()
    if "project_handlers:" not in config_text:
        config_path.write_text(
            config_text + "\nproject_handlers:\n  enabled: true\n  path: .claude/project-handlers\n"
        )
    return tmp_path


def _defences(project: Path, capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    args = argparse.Namespace(as_json=True, project_root=project)
    capsys.readouterr()  # drop what scaffolding printed
    assert cmd_defences(args) == 0
    records: list[dict[str, Any]] = json.loads(capsys.readouterr().out)
    return records


class TestProjectHandlerEntryPoint:
    def test_the_record_names_the_real_event_and_the_config_key(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _scaffold_project(tmp_path)
        by_id = {r["rule_id"]: r for r in _defences(project, capsys) if r["rule_id"]}
        record = by_id["R-PROJECT-CANARY"]
        assert record["event"] == "pre_tool_use"
        assert record["handler"] == "canary_defence_handler"
        assert record["detector_entry_point"] == (
            "hooks-daemon probe pre_tool_use --only canary_defence_handler --json <payload>"
        )

    def test_the_printed_only_value_is_accepted_by_probe(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _scaffold_project(tmp_path)
        by_id = {r["rule_id"]: r for r in _defences(project, capsys) if r["rule_id"]}
        entry_point = by_id["R-PROJECT-CANARY"]["detector_entry_point"]
        match = re.fullmatch(r"hooks-daemon probe (\S+) --only (\S+) --json <payload>", entry_point)
        assert match is not None
        event_name, only = match.groups()

        event = resolve_probe_event(event_name)
        probe_args = argparse.Namespace(project_root=project)
        hook_event = build_probe_event(
            {"tool_name": "Bash", "tool_input": {"command": "true"}},
            event=event,
            project_root=project,
            session_id="s",
            only=only,
            known_handlers=lambda: cli._loaded_handler_keys(
                probe_args, project, event.config_key
            ),
        )
        assert hook_event["probe_only"] == only
