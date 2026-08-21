"""The ``generate-playbook`` CLI must surface project-handler acceptance tests.

``PlaybookGenerator`` has accepted a ``project_handlers=`` argument since Plan
00040, and ``test_playbook_generator_project_handlers.py`` proves that branch
works when it is given one. Nothing asserted that the CLI ever passes it — so
``cmd_generate_playbook`` never did, and the branch was dead on the only path a
release actually runs.

The failure mode is silent in the worst way. A project handler declares
acceptance tests, the release playbook is generated, the gate is executed, and
the handler is simply absent from it. Nothing errors and no count looks wrong,
because nobody knows what the count should have been. In this repository that
hid the two most repo-specific guardrails there are — the one that blocks Stop
mid-release and the one that redirects a direct QA-runner invocation.

The DBF point is that a unit test on the generator could never catch this: it
supplies the argument itself, which is precisely the thing that was missing.
The check has to run the command.
"""

import argparse
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import (
    cmd_generate_docs,
    cmd_generate_playbook,
    cmd_init_config,
)

_HANDLER_SOURCE = '''"""Project handler fixture that declares an acceptance test."""

from typing import Any

from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision


class CanaryProjectHandler(Handler):
    """Declares one acceptance test with an unmistakable title."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="canary-project-handler",
            priority=Priority.PLAN_WORKFLOW,
            terminal=False,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [
            AcceptanceTest(
                title="CANARY-PROJECT-ACCEPTANCE-TEST",
                command='echo "canary probe"',
                description="Proves project handler tests reach the playbook",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                test_type=TestType.ADVISORY,
            ),
        ]
'''

_CANARY_TITLE = "CANARY-PROJECT-ACCEPTANCE-TEST"


def _init_git_repo(path: Path) -> None:
    """ProjectContext FAIL-FASTs without an origin remote."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.com/acme/demo-project.git"],
        cwd=path,
        capture_output=True,
        check=True,
    )


def _scaffold_project_with_canary_handler(tmp_path: Path) -> Path:
    """A git-backed project whose project-handlers dir holds the canary."""
    _init_git_repo(tmp_path)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "hooks-daemon").mkdir()

    assert (
        cmd_init_config(argparse.Namespace(project_root=tmp_path, minimal=False, force=False)) == 0
    )

    handlers_dir = claude_dir / "project-handlers" / "pre_tool_use"
    handlers_dir.mkdir(parents=True)
    (handlers_dir / "__init__.py").write_text("")
    (handlers_dir / "canary_handler.py").write_text(_HANDLER_SOURCE)

    config_path = claude_dir / "hooks-daemon.yaml"
    config_text = config_path.read_text()
    if "project_handlers:" not in config_text:
        config_text += "\nproject_handlers:\n  enabled: true\n  path: .claude/project-handlers\n"
        config_path.write_text(config_text)

    return tmp_path


def _playbook_args(project_root: Path) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=project_root,
        include_disabled=False,
        format="markdown",
        filter_type=None,
        filter_handler=None,
    )


class TestGeneratePlaybookIncludesProjectHandlers:
    """The CLI path, not the generator in isolation."""

    def test_markdown_playbook_contains_the_project_handler_test(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The declared test must appear in the playbook a release generates."""
        project = _scaffold_project_with_canary_handler(tmp_path)

        assert cmd_generate_playbook(_playbook_args(project)) == 0

        assert _CANARY_TITLE in capsys.readouterr().out, (
            "a project handler declared an acceptance test and the generated "
            "playbook does not contain it, so the release gate silently skips it"
        )

    def test_json_playbook_contains_the_project_handler_test(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Both output formats share the collection step, so both must show it."""
        project = _scaffold_project_with_canary_handler(tmp_path)
        args = _playbook_args(project)
        args.format = "json"

        assert cmd_generate_playbook(args) == 0

        assert _CANARY_TITLE in capsys.readouterr().out

    def test_playbook_and_docs_agree_on_project_handlers(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The property, not the instance — these two siblings must not diverge.

        ``generate-docs`` loads project handlers and ``generate-playbook`` did
        not, which is the whole defect: one command was updated and its
        neighbour was not. Asserting the canary by name would pass again the
        moment some future third command repeats the omission. Asserting that
        the two agree is what actually holds.
        """
        project = _scaffold_project_with_canary_handler(tmp_path)

        assert cmd_generate_playbook(_playbook_args(project)) == 0
        playbook_out = capsys.readouterr().out

        docs_path = project / ".claude" / "generated-docs.md"
        docs_args = argparse.Namespace(
            project_root=project, include_disabled=False, output=str(docs_path)
        )
        assert cmd_generate_docs(docs_args) == 0
        docs_out = docs_path.read_text()

        handler_id = "canary-project-handler"
        assert (handler_id in docs_out or "CanaryProjectHandler" in docs_out) == (
            _CANARY_TITLE in playbook_out
        ), (
            "generate-docs and generate-playbook disagree about whether project "
            "handlers exist; one of them is not loading them"
        )
