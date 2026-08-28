"""Tests for DocsQaEditHandler (Plan 00284, Task 3.1c).

EDIT-stage docs QA lint: Write/Edit of a documentation-scoped file is
checked against the docs QA EDIT-stage catalogue on the WOULD-BE content.
Denies only a BLOCK-severity finding whose resolved check mode is
"block"; everything else surfaces as advisory context.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.docs_qa.policy import (
    DocumentationPolicy,
    DocumentationQaPolicy,
    GeneratedDocEntry,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.docs_qa_edit import DocsQaEditHandler


def _handler(policy: DocumentationPolicy | None = None) -> DocsQaEditHandler:
    handler = DocsQaEditHandler()
    handler._documentation = policy if policy is not None else DocumentationPolicy(enabled=True)
    return handler


def _write_input(file_path: Path, content: str) -> dict[str, Any]:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": str(file_path), "content": content},
    }


def _edit_input(
    file_path: Path, old_string: str, new_string: str, replace_all: bool = False
) -> dict[str, Any]:
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(file_path),
            "old_string": old_string,
            "new_string": new_string,
            "replace_all": replace_all,
        },
    }


def _patched_root(root: Path) -> Any:
    target = (
        "claude_code_hooks_daemon.handlers.pre_tool_use.docs_qa_edit.ProjectContext.project_root"
    )
    return patch(target, return_value=root)


class TestInit:
    def test_identity(self) -> None:
        handler = DocsQaEditHandler()
        assert handler.name == "docs-qa-edit"
        assert handler.terminal is False
        assert "documentation" in handler.tags


class TestMatches:
    def test_matches_write_to_agent_tree_markdown(self, tmp_path: Path) -> None:
        target = tmp_path / "CLAUDE" / "X.md"
        with _patched_root(tmp_path):
            assert _handler().matches(_write_input(target, "x")) is True

    def test_matches_edit_to_human_tree_markdown(self, tmp_path: Path) -> None:
        target = tmp_path / "docs" / "X.md"
        with _patched_root(tmp_path):
            assert _handler().matches(_edit_input(target, "a", "b")) is True

    def test_matches_generated_docs_manifest_path_outside_corpus_scope(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / ".claude" / "HOOKS-DAEMON.md"
        policy = DocumentationPolicy(
            enabled=True,
            qa=DocumentationQaPolicy(
                generated_docs=(
                    GeneratedDocEntry(
                        glob=".claude/HOOKS-DAEMON.md",
                        generator="bin/hooks-daemon generate-docs",
                    ),
                )
            ),
        )
        with _patched_root(tmp_path):
            assert _handler(policy).matches(_write_input(target, "x")) is True

    def test_ignores_files_outside_docs_scope(self, tmp_path: Path) -> None:
        target = tmp_path / "src" / "module.py"
        with _patched_root(tmp_path):
            assert _handler().matches(_write_input(target, "x")) is False

    def test_ignores_other_tools(self, tmp_path: Path) -> None:
        target = tmp_path / "CLAUDE" / "X.md"
        hook_input = {"tool_name": "Bash", "tool_input": {"command": f"cat {target}"}}
        with _patched_root(tmp_path):
            assert _handler().matches(hook_input) is False

    def test_skips_without_policy(self, tmp_path: Path) -> None:
        handler = DocsQaEditHandler()
        target = tmp_path / "CLAUDE" / "X.md"
        with _patched_root(tmp_path):
            assert handler.matches(_write_input(target, "x")) is False

    def test_skips_when_documentation_disabled(self, tmp_path: Path) -> None:
        handler = _handler(policy=DocumentationPolicy(enabled=False))
        target = tmp_path / "CLAUDE" / "X.md"
        with _patched_root(tmp_path):
            assert handler.matches(_write_input(target, "x")) is False

    def test_skips_empty_file_path(self, tmp_path: Path) -> None:
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "", "content": "x"}}
        with _patched_root(tmp_path):
            assert _handler().matches(hook_input) is False

    def test_skips_path_outside_project_root(self, tmp_path: Path) -> None:
        other_root = tmp_path / "elsewhere"
        target = other_root / "CLAUDE" / "X.md"
        project_root = tmp_path / "project"
        project_root.mkdir()
        with _patched_root(project_root):
            assert _handler().matches(_write_input(target, "x")) is False


class TestHandleBlocking:
    def test_new_rules_file_with_fence_denies_in_block_mode(self, tmp_path: Path) -> None:
        (tmp_path / ".claude" / "rules").mkdir(parents=True)
        target = tmp_path / ".claude" / "rules" / "one.md"
        policy = DocumentationPolicy(enabled=True, qa=DocumentationQaPolicy(edit_mode="block"))
        handler = _handler(policy)
        content = "---\npaths: ['*']\ndescription: x\n---\n# T\n\n```bash\necho hi\n```\n"
        with _patched_root(tmp_path):
            result = handler.handle(_write_input(target, content))
        assert result.decision == Decision.DENY
        assert "rules-file-shape" in (result.reason or "")

    def test_new_rules_file_with_fence_advises_in_warn_mode(self, tmp_path: Path) -> None:
        (tmp_path / ".claude" / "rules").mkdir(parents=True)
        target = tmp_path / ".claude" / "rules" / "one.md"
        policy = DocumentationPolicy(enabled=True, qa=DocumentationQaPolicy(edit_mode="warn"))
        handler = _handler(policy)
        content = "---\npaths: ['*']\ndescription: x\n---\n# T\n\n```bash\necho hi\n```\n"
        with _patched_root(tmp_path):
            result = handler.handle(_write_input(target, content))
        assert result.decision == Decision.ALLOW
        assert any("rules-file-shape" in item for item in result.context)

    def test_check_modes_override_wins_over_default_edit_mode(self, tmp_path: Path) -> None:
        (tmp_path / ".claude" / "rules").mkdir(parents=True)
        target = tmp_path / ".claude" / "rules" / "one.md"
        # Default warn, but this specific check is ratcheted to block.
        policy = DocumentationPolicy(
            enabled=True,
            qa=DocumentationQaPolicy(edit_mode="warn", check_modes={"rules-file-shape": "block"}),
        )
        handler = _handler(policy)
        content = "---\npaths: ['*']\ndescription: x\n---\n# T\n\n```bash\necho hi\n```\n"
        with _patched_root(tmp_path):
            result = handler.handle(_write_input(target, content))
        assert result.decision == Decision.DENY

    def test_advise_severity_finding_never_blocks_even_in_block_mode(self, tmp_path: Path) -> None:
        target = tmp_path / "CLAUDE" / "X.md"
        (tmp_path / "CLAUDE").mkdir()
        policy = DocumentationPolicy(enabled=True, qa=DocumentationQaPolicy(edit_mode="block"))
        handler = _handler(policy)
        # pointer-resolves ADVISEs (never blocks) on a pre-existing broken
        # link that this edit does not add.
        old_content = "See [missing](Nope.md).\n"
        with _patched_root(tmp_path):
            target.write_text(old_content)
            result = handler.handle(_edit_input(target, "See", "Intro. See"))
        assert result.decision == Decision.ALLOW
        assert any("pointer-resolves" in item for item in result.context)

    def test_clean_content_produces_no_context(self, tmp_path: Path) -> None:
        target = tmp_path / "CLAUDE" / "X.md"
        (tmp_path / "CLAUDE").mkdir()
        with _patched_root(tmp_path):
            result = _handler().handle(_write_input(target, "# clean\n"))
        assert result.decision == Decision.ALLOW
        assert result.context == []


class TestHandleContentResolution:
    def test_write_uses_content_payload(self, tmp_path: Path) -> None:
        target = tmp_path / "CLAUDE" / "X.md"
        (tmp_path / "CLAUDE").mkdir()
        with _patched_root(tmp_path):
            result = _handler().handle(_write_input(target, "See [x](Nope.md).\n"))
        assert result.decision == Decision.ALLOW
        assert any("Nope.md" in item for item in result.context)

    def test_edit_on_missing_old_string_produces_no_findings(self, tmp_path: Path) -> None:
        target = tmp_path / "CLAUDE" / "X.md"
        (tmp_path / "CLAUDE").mkdir()
        target.write_text("# hello\n")
        with _patched_root(tmp_path):
            result = _handler().handle(_edit_input(target, "not-present", "y"))
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_edit_on_nonexistent_file_produces_no_findings(self, tmp_path: Path) -> None:
        target = tmp_path / "CLAUDE" / "ghost.md"
        (tmp_path / "CLAUDE").mkdir()
        with _patched_root(tmp_path):
            result = _handler().handle(_edit_input(target, "a", "b"))
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_edit_replace_all_applies_every_occurrence(self, tmp_path: Path) -> None:
        target = tmp_path / "CLAUDE" / "X.md"
        (tmp_path / "CLAUDE").mkdir()
        target.write_text("a a a\n")
        with _patched_root(tmp_path):
            result = _handler().handle(_edit_input(target, "a", "b", replace_all=True))
        assert result.decision == Decision.ALLOW


class TestClaudeMdAndAcceptanceTests:
    def test_get_claude_md_returns_content(self) -> None:
        content = DocsQaEditHandler().get_claude_md()
        assert content is not None
        assert "docs_qa_edit" in content

    def test_get_acceptance_tests_returns_list(self) -> None:
        tests = DocsQaEditHandler().get_acceptance_tests()
        assert len(tests) >= 1
