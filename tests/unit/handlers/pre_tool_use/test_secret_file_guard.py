"""Tests for SecretFileGuardHandler (Plan 00272).

Deny-by-default read guard over configured protected files: Read/Write/Edit/
NotebookEdit/Grep on a protected path, and any Bash command mentioning one,
are DENIED — except the ``secret-meta`` helper and allowlisted consumers with
the path in flag position. No escape hatch (Decision 3).
"""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)


def _hook_input(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return {"tool_name": tool_name, "tool_input": tool_input}


def _handler() -> SecretFileGuardHandler:
    return SecretFileGuardHandler()


class TestInit:
    def test_identity(self) -> None:
        handler = _handler()
        assert handler.handler_id == HandlerID.SECRET_FILE_GUARD
        assert handler.priority == Priority.SECRET_FILE_GUARD
        assert handler.terminal is True

    def test_enabled_by_default(self) -> None:
        assert _handler().get_default_enabled() is True


class TestReadTools:
    def test_read_of_protected_path_matches(self) -> None:
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/.vault-pass"})
        assert handler.matches(hook_input)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_read_of_dot_secret_file_matches_default(self) -> None:
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/.claude/block-words.secret"})
        assert handler.matches(hook_input)

    def test_read_of_ordinary_file_does_not_match(self) -> None:
        handler = _handler()
        assert not handler.matches(_hook_input("Read", {"file_path": "/proj/src/main.py"}))

    def test_write_to_protected_path_matches(self) -> None:
        handler = _handler()
        hook_input = _hook_input("Write", {"file_path": "/proj/.vault-pass", "content": "x"})
        assert handler.matches(hook_input)

    def test_edit_of_protected_path_matches(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Edit", {"file_path": "/proj/foo.secret.env", "old_string": "a", "new_string": "b"}
        )
        assert handler.matches(hook_input)

    def test_notebook_edit_of_protected_path_matches(self) -> None:
        handler = _handler()
        hook_input = _hook_input("NotebookEdit", {"notebook_path": "/proj/creds.secret.ipynb"})
        assert handler.matches(hook_input)

    def test_grep_of_protected_path_matches(self) -> None:
        """Grep on a protected file is a content oracle in EVERY output mode."""
        handler = _handler()
        hook_input = _hook_input("Grep", {"pattern": "^a", "path": "/proj/.vault-pass"})
        assert handler.matches(hook_input)

    def test_grep_of_ordinary_dir_does_not_match(self) -> None:
        handler = _handler()
        assert not handler.matches(_hook_input("Grep", {"pattern": "x", "path": "/proj/src"}))

    def test_glob_tool_is_never_matched(self) -> None:
        """Names-only: presence is the feature, deliberately allowed."""
        handler = _handler()
        assert not handler.matches(_hook_input("Glob", {"pattern": "**/.vault-pass"}))


class TestBash:
    def test_cat_of_protected_path_is_denied(self) -> None:
        handler = _handler()
        hook_input = _hook_input("Bash", {"command": "cat .vault-pass"})
        assert handler.matches(hook_input)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_interpreter_one_liner_is_denied(self) -> None:
        handler = _handler()
        cmd = "python3 -c \"print(open('.claude/block-words.secret').read())\""
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_secret_meta_helper_is_allowed(self) -> None:
        handler = _handler()
        cmd = "bin/hooks-daemon secret-meta .vault-pass"
        assert not handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_ansible_playbook_consumer_is_allowed(self) -> None:
        handler = _handler()
        cmd = "ansible-playbook --vault-password-file .vault-pass site.yml"
        assert not handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_ansible_vault_view_is_denied(self) -> None:
        handler = _handler()
        cmd = "ansible-vault view --vault-password-file .vault-pass secrets.yml"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_clean_command_is_allowed(self) -> None:
        handler = _handler()
        assert not handler.matches(_hook_input("Bash", {"command": "git status"}))


class TestContentScan:
    """Task 4.3: authored SCRIPTS referencing a protected path are denied."""

    def test_script_content_referencing_protected_path_is_denied(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {"file_path": "/proj/steal.sh", "content": "#!/bin/bash\ncat .vault-pass\n"},
        )
        assert handler.matches(hook_input)

    def test_markdown_prose_mentioning_protected_name_is_allowed(self) -> None:
        """Docs (this plan's own!) legitimately NAME protected files."""
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {"file_path": "/proj/CLAUDE/Plan/x/PLAN.md", "content": "protect .vault-pass files"},
        )
        assert not handler.matches(hook_input)

    def test_excluded_path_content_scan_is_skipped(self) -> None:
        """The guard's own source/tests legitimately NAME protected paths —
        the dogfood config excludes them (sensitive_content precedent)."""
        handler = _handler()
        handler._exclude_paths = ["tests/unit/handlers/**"]
        hook_input = _hook_input(
            "Write",
            {
                "file_path": "/proj/tests/unit/handlers/test_x.py",
                "content": "assert guard('cat .vault-pass')",
            },
        )
        assert not handler.matches(hook_input)

    def test_exclusion_never_exempts_a_protected_path_itself(self) -> None:
        """exclude_paths scopes the CONTENT scan only — a protected file stays
        protected even if a glob would exclude it."""
        handler = _handler()
        handler._exclude_paths = ["**/*"]
        assert handler.matches(_hook_input("Read", {"file_path": "/proj/.vault-pass"}))

    def test_clean_script_is_allowed(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Write", {"file_path": "/proj/run.sh", "content": "#!/bin/bash\nls\n"}
        )
        assert not handler.matches(hook_input)


class TestDenyReason:
    def test_reason_names_glob_never_content(self) -> None:
        handler = _handler()
        result = handler.handle(_hook_input("Read", {"file_path": "/proj/.vault-pass"}))
        assert result.reason is not None
        assert ".vault-pass*" in result.reason
        assert "secret-meta" in result.reason

    def test_reason_states_no_escape_hatch(self) -> None:
        handler = _handler()
        result = handler.handle(_hook_input("Bash", {"command": "cat .vault-pass"}))
        assert result.reason is not None
        assert "MUST_" not in result.reason
        assert "human" in result.reason.lower()


class TestConfigModes:
    def test_project_patterns_are_additive_by_default(self) -> None:
        handler = _handler()
        handler._protected_paths = ["secrets/prod-token"]
        assert handler.matches(_hook_input("Read", {"file_path": "/proj/secrets/prod-token"}))
        assert handler.matches(_hook_input("Read", {"file_path": "/proj/.vault-pass"}))

    def test_replace_mode_uses_only_project_patterns(self) -> None:
        handler = _handler()
        handler._mode = "replace"
        handler._protected_paths = ["secrets/prod-token"]
        assert handler.matches(_hook_input("Read", {"file_path": "/proj/secrets/prod-token"}))
        assert not handler.matches(_hook_input("Read", {"file_path": "/proj/.vault-pass"}))

    def test_unknown_mode_fails_closed_as_additive(self) -> None:
        handler = _handler()
        handler._mode = "bogus"
        handler._protected_paths = ["extra.thing"]
        assert handler.matches(_hook_input("Read", {"file_path": "/proj/.vault-pass"}))
        assert handler.matches(_hook_input("Read", {"file_path": "/proj/extra.thing"}))


class TestGuidance:
    def test_claude_md_present_with_honest_limits(self) -> None:
        text = _handler().get_claude_md()
        assert text is not None
        assert "secret_file_guard" in text
        assert "no escape hatch" in text.lower() or "NO escape hatch" in text

    def test_acceptance_tests_use_dummy_paths(self) -> None:
        tests = _handler().get_acceptance_tests()
        assert tests
        for test in tests:
            assert "block-words" not in test.command
