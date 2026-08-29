"""Integration test: ``source-tree-markdown`` never double-reports with
``markdown_organization`` (Plan 00288, Task 5.2).

DESIGN §4b's division is: ``markdown_organization`` (PreToolUse, blocking)
owns "may a NEW `.md` be written here?" on the EDIT surface; the docs_qa
``source-tree-markdown`` check owns "does markdown ALREADY ON DISK in a
source/test dir violate the SSoT pattern?" on the SWEEP surface only. This
test pins both halves of that contract against a single scenario: a Write
of ``src/foo/NOTES.md``.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.docs_qa.checks import all_checks
from claude_code_hooks_daemon.docs_qa.checks.source_tree_markdown import CHECK_ID
from claude_code_hooks_daemon.docs_qa.context import edit_context
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.runner import run_stage
from claude_code_hooks_daemon.docs_qa.types import CheckStage
from claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization import (
    MarkdownOrganizationHandler,
)


@pytest.fixture(autouse=True)
def mock_project_context():
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = Path("/tmp/source-tree-markdown-test")
        yield mock


def test_markdown_organization_denies_the_write() -> None:
    """``markdown_organization`` is the ONLY handler that judges the write itself."""
    handler = MarkdownOrganizationHandler()
    hook_input: dict[str, Any] = {
        "tool_name": "Write",
        "tool_input": {"file_path": "src/foo/NOTES.md", "content": "# Notes"},
    }
    assert handler.matches(hook_input) is True
    result = handler.handle(hook_input)
    assert result.decision == Decision.DENY


def test_source_tree_markdown_has_no_edit_stage() -> None:
    """``source-tree-markdown`` is registered SWEEP-only -- structurally
    incapable of re-judging the same write, so it can never double-report
    with ``markdown_organization``'s EDIT-stage verdict above."""
    specs = [spec for spec in all_checks() if spec.check_id == CHECK_ID]
    assert specs, "source-tree-markdown must be registered"
    assert {spec.stage for spec in specs} == {CheckStage.SWEEP}


def test_source_tree_markdown_never_fires_at_edit_stage_in_practice(tmp_path: Path) -> None:
    """Belt-and-braces: running the EDIT stage against the same content
    never yields a ``source-tree-markdown`` finding, because no EDIT check
    is registered for it at all."""
    context = edit_context(
        project_root=tmp_path,
        policy=DocumentationPolicy(),
        file_path=tmp_path / "src" / "foo" / "NOTES.md",
        file_content="# Notes",
        file_exists_before=False,
    )
    findings = run_stage(CheckStage.EDIT, context)
    assert all(finding.check_id != CHECK_ID for finding in findings)
