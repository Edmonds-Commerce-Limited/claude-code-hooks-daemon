"""Plan 00621 Task 2.2: the SessionStart advisory that suggests the workflow linter.

It speaks once, at a new session, when a project has GitHub workflows and none of
them uses ``actions-qa-ci``. It is silent when there are no workflows, when a
workflow already uses the linter, and on a resumed session. A workflow file it
cannot read is named rather than skipped, and never counts as using the linter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start.workflow_linter_advisor import (
    RELEASES_URL,
    WorkflowLinterAdvisorHandler,
)

_STEP_USE = (
    "jobs:\n  qa:\n    runs-on: ubuntu-latest\n    steps:\n"
    "      - uses: LongTermSupport/actions-qa-ci@0123abcd\n"
)
_JOB_USE = "jobs:\n  qa:\n    uses: 'LongTermSupport/actions-qa-ci/.github/workflows/x.yml@v0'\n"
_PLAIN = "name: ci\non:\n  pull_request:\njobs:\n  b:\n    runs-on: ubuntu-latest\n"


def _handler(root: Path) -> WorkflowLinterAdvisorHandler:
    handler = WorkflowLinterAdvisorHandler()
    handler.workspace_root = root
    return handler


def _workflows(root: Path) -> Path:
    directory = root / ".github" / "workflows"
    directory.mkdir(parents=True)
    return directory


def _session(**overrides: Any) -> dict[str, Any]:
    return {"hook_event_name": "SessionStart", "source": "startup", **overrides}


def _context(handler: WorkflowLinterAdvisorHandler) -> str:
    result = handler.handle(_session())
    assert result.decision == Decision.ALLOW
    return "\n".join(result.context)


class TestMatches:
    def test_matches_a_new_session(self, tmp_path: Path) -> None:
        assert _handler(tmp_path).matches(_session()) is True

    def test_silent_on_a_resumed_session(self, tmp_path: Path) -> None:
        transcript = tmp_path / "t.jsonl"
        transcript.write_text("x" * 1000)

        assert _handler(tmp_path).matches(_session(transcript_path=str(transcript))) is False


class TestSilence:
    def test_no_workflows_directory(self, tmp_path: Path) -> None:
        assert _context(_handler(tmp_path)) == ""

    def test_empty_workflows_directory(self, tmp_path: Path) -> None:
        _workflows(tmp_path)

        assert _context(_handler(tmp_path)) == ""

    def test_only_non_yaml_files(self, tmp_path: Path) -> None:
        directory = _workflows(tmp_path)
        (directory / "README.md").write_text("uses: nothing\n")

        assert _context(_handler(tmp_path)) == ""

    def test_nested_workflow_is_not_a_workflow(self, tmp_path: Path) -> None:
        nested = _workflows(tmp_path) / "sub"
        nested.mkdir()
        (nested / "x.yml").write_text(_PLAIN)

        assert _context(_handler(tmp_path)) == ""

    def test_a_directory_named_like_a_workflow_is_not_one(self, tmp_path: Path) -> None:
        (_workflows(tmp_path) / "odd.yml").mkdir()

        assert _context(_handler(tmp_path)) == ""

    def test_step_level_use_silences(self, tmp_path: Path) -> None:
        (_workflows(tmp_path) / "qa.yml").write_text(_STEP_USE)

        assert _context(_handler(tmp_path)) == ""

    def test_reusable_workflow_use_silences(self, tmp_path: Path) -> None:
        (_workflows(tmp_path) / "qa.yaml").write_text(_JOB_USE)

        assert _context(_handler(tmp_path)) == ""

    def test_one_user_among_several_silences(self, tmp_path: Path) -> None:
        directory = _workflows(tmp_path)
        (directory / "a.yml").write_text(_PLAIN)
        (directory / "b.yml").write_text(_STEP_USE)

        assert _context(_handler(tmp_path)) == ""

    def test_no_project_root_is_silent(self) -> None:
        handler = WorkflowLinterAdvisorHandler()
        with patch(
            "claude_code_hooks_daemon.handlers.session_start.workflow_linter_advisor"
            ".ProjectContext.is_initialized",
            return_value=False,
        ):
            assert _context(handler) == ""


class TestFires:
    @pytest.mark.parametrize("name", ["ci.yml", "ci.yaml"])
    def test_fires_for_each_extension(self, tmp_path: Path, name: str) -> None:
        (_workflows(tmp_path) / name).write_text(_PLAIN)

        text = _context(_handler(tmp_path))

        assert "actions-qa-ci" in text
        assert RELEASES_URL in text

    def test_name_in_a_comment_or_run_line_does_not_count(self, tmp_path: Path) -> None:
        (_workflows(tmp_path) / "ci.yml").write_text(
            _PLAIN
            + "    steps:\n"
            + "      # uses: LongTermSupport/actions-qa-ci@v1\n"
            + "      - run: echo actions-qa-ci\n"
        )

        assert "actions-qa-ci" in _context(_handler(tmp_path))

    def test_text_names_the_tool_link_and_no_install_command(self, tmp_path: Path) -> None:
        (_workflows(tmp_path) / "ci.yml").write_text(_PLAIN)

        text = _context(_handler(tmp_path))

        assert RELEASES_URL == "https://github.com/LongTermSupport/actions-qa-ci/releases"
        assert "actions-qa" in text
        for install_word in ("install.sh", "curl", "wget", "go install", "| sh", "| bash"):
            assert install_word not in text

    def test_text_says_what_silences_it(self, tmp_path: Path) -> None:
        (_workflows(tmp_path) / "ci.yml").write_text(_PLAIN)

        text = _context(_handler(tmp_path))

        assert "workflow_linter_advisor" in text
        assert "enabled: false" in text

    def test_an_unreadable_workflow_is_named_and_not_counted_as_a_user(
        self, tmp_path: Path
    ) -> None:
        directory = _workflows(tmp_path)
        (directory / "bad.yml").write_bytes(b"\xff\xfe uses: LongTermSupport/actions-qa-ci@v1\n")

        text = _context(_handler(tmp_path))

        assert RELEASES_URL in text
        assert "bad.yml" in text
        assert "could not be read" in text

    def test_an_os_error_reading_a_workflow_is_named(self, tmp_path: Path) -> None:
        (_workflows(tmp_path) / "ci.yml").write_text(_STEP_USE)

        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            text = _context(_handler(tmp_path))

        assert "ci.yml" in text
        assert "could not be read" in text

    def test_an_unlistable_workflows_directory_is_reported(self, tmp_path: Path) -> None:
        (_workflows(tmp_path) / "ci.yml").write_text(_PLAIN)

        with patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
            text = _context(_handler(tmp_path))

        assert ".github/workflows" in text
        assert "could not be listed" in text


class TestMetadata:
    def test_non_terminal_and_no_resident_guidance(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path)

        assert handler.terminal is False
        assert handler.get_claude_md() is None

    def test_has_an_acceptance_test(self, tmp_path: Path) -> None:
        tests = _handler(tmp_path).get_acceptance_tests()

        assert len(tests) == 1
        assert tests[0].expected_decision == Decision.ALLOW
