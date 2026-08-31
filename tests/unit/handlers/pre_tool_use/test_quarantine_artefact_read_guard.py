"""Unit tests for QuarantineArtefactReadGuardHandler (Plan 00278 Phase 3d.2).

Enforces the ``*-opus-security-DETAIL*`` read-boundary by PATTERN, not trust:
the DETAIL artefact holds raw flaggable substance the coordinator must NEVER
read. Read/Edit/Grep/NotebookEdit and content-revealing Bash over a matching
path are DENIED; the paired SUMMARY artefact and authoring (Write) the DETAIL
file itself stay allowed. Ships DISABLED but pre-seeded, so enabling it works
out of the box with no config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.quarantine_artefact_read_guard import (
    QuarantineArtefactReadGuardHandler,
)


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test in this module."""
    reset_data_layer()
    yield
    reset_data_layer()


def _hook_input(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


@pytest.fixture
def handler() -> QuarantineArtefactReadGuardHandler:
    return QuarantineArtefactReadGuardHandler()


class TestInitialisation:
    def test_identity(self, handler: QuarantineArtefactReadGuardHandler) -> None:
        assert handler.handler_id == HandlerID.QUARANTINE_ARTEFACT_READ_GUARD
        assert handler.priority == Priority.QUARANTINE_ARTEFACT_READ_GUARD
        assert handler.terminal is True

    def test_ships_disabled(self, handler: QuarantineArtefactReadGuardHandler) -> None:
        assert handler.get_default_enabled() is False

    def test_seeded_out_of_the_box_with_no_config(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        """Enabling the handler works with zero configuration (Decision text)."""
        payload = _hook_input("Read", {"file_path": "/p/topic-opus-security-DETAIL.md"})
        assert handler.matches(payload) is True


class TestToolLevelPathChecks:
    def test_read_of_detail_artefact_matches(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Read", {"file_path": "/p/topic-opus-security-DETAIL.md"})
        assert handler.matches(payload) is True

    def test_edit_of_detail_artefact_matches(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input(
            "Edit",
            {
                "file_path": "/p/topic-opus-security-DETAIL.md",
                "old_string": "a",
                "new_string": "b",
            },
        )
        assert handler.matches(payload) is True

    def test_notebook_edit_of_detail_artefact_matches(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input(
            "NotebookEdit", {"notebook_path": "/p/topic-opus-security-DETAIL.ipynb"}
        )
        assert handler.matches(payload) is True

    def test_grep_path_of_detail_artefact_matches(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Grep", {"pattern": "x", "path": "/p/topic-opus-security-DETAIL.md"})
        assert handler.matches(payload) is True

    def test_write_of_detail_artefact_is_allowed(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        """The subagent AUTHORS the DETAIL file — Write must stay unblocked."""
        payload = _hook_input(
            "Write", {"file_path": "/p/topic-opus-security-DETAIL.md", "content": "raw stuff"}
        )
        assert handler.matches(payload) is False

    def test_read_of_summary_artefact_is_always_allowed(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Read", {"file_path": "/p/topic-opus-security-SUMMARY.md"})
        assert handler.matches(payload) is False

    def test_read_of_unrelated_path_does_not_match(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Read", {"file_path": "/p/src/app.py"})
        assert handler.matches(payload) is False

    def test_read_with_missing_path_field_does_not_match(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Read", {})
        assert handler.matches(payload) is False

    def test_grep_rooted_at_directory_containing_detail_artefact_matches(
        self, handler: QuarantineArtefactReadGuardHandler, tmp_path: Path
    ) -> None:
        (tmp_path / "topic-opus-security-DETAIL.md").write_text("raw")
        payload = _hook_input("Grep", {"pattern": "x", "path": str(tmp_path)})
        assert handler.matches(payload) is True

    def test_grep_rooted_at_directory_without_detail_artefact_does_not_match(
        self, handler: QuarantineArtefactReadGuardHandler, tmp_path: Path
    ) -> None:
        (tmp_path / "ordinary.md").write_text("fine")
        payload = _hook_input("Grep", {"pattern": "x", "path": str(tmp_path)})
        assert handler.matches(payload) is False


class TestBashRevealingVerbs:
    def test_cat_of_detail_artefact_matches(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Bash", {"command": "cat topic-opus-security-DETAIL.md"})
        assert handler.matches(payload) is True

    def test_head_of_detail_artefact_matches(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Bash", {"command": "head -20 topic-opus-security-DETAIL.md"})
        assert handler.matches(payload) is True

    def test_less_of_detail_artefact_matches(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Bash", {"command": "less topic-opus-security-DETAIL.md"})
        assert handler.matches(payload) is True

    def test_grep_of_detail_artefact_matches(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Bash", {"command": "grep mechanics topic-opus-security-DETAIL.md"})
        assert handler.matches(payload) is True

    def test_python_one_liner_reveal_matches(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input(
            "Bash",
            {"command": "python3 -c \"print(open('topic-opus-security-DETAIL.md').read())\""},
        )
        assert handler.matches(payload) is True

    def test_cat_redirect_authoring_the_artefact_is_allowed(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        """``cat > file <<EOF`` AUTHORS the file — this is the subagent's job."""
        payload = _hook_input(
            "Bash",
            {"command": "cat > topic-opus-security-DETAIL.md <<'EOF'\nraw\nEOF"},
        )
        assert handler.matches(payload) is False

    def test_git_add_and_commit_of_the_artefact_is_allowed(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        """The subagent owns the entire git cycle for its own artefacts."""
        payload = _hook_input(
            "Bash",
            {
                "command": (
                    "git add topic-opus-security-DETAIL.md && "
                    "git commit -m 'Plan 00278: add detail'"
                )
            },
        )
        assert handler.matches(payload) is False

    def test_ls_of_detail_artefact_is_allowed(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Bash", {"command": "ls topic-opus-security-DETAIL.md"})
        assert handler.matches(payload) is False

    def test_path_qualified_cat_still_matches(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Bash", {"command": "/bin/cat topic-opus-security-DETAIL.md"})
        assert handler.matches(payload) is True

    def test_env_prefixed_cat_still_matches(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Bash", {"command": "env cat topic-opus-security-DETAIL.md"})
        assert handler.matches(payload) is True

    def test_env_assignment_prefixed_grep_still_matches(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input(
            "Bash", {"command": "LANG=C grep mechanics topic-opus-security-DETAIL.md"}
        )
        assert handler.matches(payload) is True

    def test_path_qualified_cat_with_redirect_still_authors(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input(
            "Bash",
            {"command": "/bin/cat > topic-opus-security-DETAIL.md <<'EOF'\nraw\nEOF"},
        )
        assert handler.matches(payload) is False

    def test_bash_mentioning_unrelated_file_does_not_match(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Bash", {"command": "cat src/app.py"})
        assert handler.matches(payload) is False

    def test_missing_command_does_not_match(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Bash", {"command": ""})
        assert handler.matches(payload) is False


class TestBashGlobTokenExpansion:
    """canary-php-qa-ci-upgrade-26-08-30.md Finding 6: an unexpanded shell
    glob token (`docs/*.md`) must not be treated as a mention of a protected
    quarantine artefact unless it actually expands to one on disk."""

    def test_glob_token_with_no_matching_artefact_on_disk_is_allowed(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "ordinary.md").write_text("fine")
        monkeypatch.chdir(tmp_path)
        payload = _hook_input("Bash", {"command": "grep -c pattern docs/*.md"})
        assert handler.matches(payload) is False

    def test_glob_token_that_expands_to_a_real_detail_artefact_still_matches(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "topic-opus-security-DETAIL.md").write_text("raw")
        monkeypatch.chdir(tmp_path)
        payload = _hook_input("Bash", {"command": "grep -c pattern docs/*.md"})
        assert handler.matches(payload) is True

    def test_glob_token_in_a_directory_with_no_files_at_all_is_allowed(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        payload = _hook_input("Bash", {"command": "grep -c pattern *.md"})
        assert handler.matches(payload) is False

    def test_literal_detail_artefact_token_still_matches_without_filesystem(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        """A LITERAL (non-glob) token keeps today's behaviour: no filesystem
        check needed, matching purely on the path itself."""
        payload = _hook_input("Bash", {"command": "cat topic-opus-security-DETAIL.md"})
        assert handler.matches(payload) is True


class TestModeMerging:
    def test_additive_mode_extends_seed_globs(self) -> None:
        instance = QuarantineArtefactReadGuardHandler()
        instance._quarantine_artefact_globs = ["*-project-quarantine-RAW*"]
        payload = _hook_input("Read", {"file_path": "/p/topic-project-quarantine-RAW.md"})
        assert instance.matches(payload) is True
        # Built-in seed still active under additive mode.
        seeded = _hook_input("Read", {"file_path": "/p/topic-opus-security-DETAIL.md"})
        assert instance.matches(seeded) is True

    def test_replace_mode_discards_seed_globs(self) -> None:
        instance = QuarantineArtefactReadGuardHandler()
        instance._mode = "replace"
        instance._quarantine_artefact_globs = ["*-project-quarantine-RAW*"]
        seeded = _hook_input("Read", {"file_path": "/p/topic-opus-security-DETAIL.md"})
        assert instance.matches(seeded) is False
        replaced = _hook_input("Read", {"file_path": "/p/topic-project-quarantine-RAW.md"})
        assert instance.matches(replaced) is True

    def test_replace_mode_with_no_configured_globs_is_fully_inert(self) -> None:
        instance = QuarantineArtefactReadGuardHandler()
        instance._mode = "replace"
        payload = _hook_input("Read", {"file_path": "/p/topic-opus-security-DETAIL.md"})
        assert instance.matches(payload) is False


class TestHandle:
    def test_denies_with_glob_in_reason(self, handler: QuarantineArtefactReadGuardHandler) -> None:
        payload = _hook_input("Read", {"file_path": "/p/topic-opus-security-DETAIL.md"})
        result = handler.handle(payload)
        assert result.decision == Decision.DENY
        assert "opus-security-DETAIL" in result.reason

    def test_deny_reason_explains_summary_contract(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Read", {"file_path": "/p/topic-opus-security-DETAIL.md"})
        result = handler.handle(payload)
        assert "SUMMARY" in result.reason
        assert "NO escape hatch" in result.reason

    def test_allow_when_no_match(self, handler: QuarantineArtefactReadGuardHandler) -> None:
        payload = _hook_input("Read", {"file_path": "/p/src/app.py"})
        result = handler.handle(payload)
        assert result.decision == Decision.ALLOW


class TestGuidanceSurfaces:
    def test_get_claude_md(self, handler: QuarantineArtefactReadGuardHandler) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "quarantine_artefact_read_guard" in guidance

    def test_get_acceptance_tests(self, handler: QuarantineArtefactReadGuardHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert tests
        for test in tests:
            assert test.title
        assert any(test.expected_decision == Decision.DENY for test in tests)


class TestEdgeBranches:
    def test_non_dict_hook_input_does_not_match(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload: Any = None
        assert handler.matches(payload) is False

    def test_non_dict_tool_input_does_not_match(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload: dict[str, Any] = {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": "not-a-dict",
        }
        assert handler.matches(payload) is False


class TestQuarantineArtefactReadGuardGetRules:
    """get_rules() declares the single Rule backing this handler (Plan 00116)."""

    def test_returns_one_rule(self, handler: QuarantineArtefactReadGuardHandler) -> None:
        rules = handler.get_rules()
        assert len(rules) == 1
        assert isinstance(rules[0], Rule)

    def test_rule_id_matches_constant(self, handler: QuarantineArtefactReadGuardHandler) -> None:
        assert handler.get_rules()[0].rule_id == RuleID.QUARANTINE_ARTEFACT_READ

    def test_rule_has_non_empty_verbose(self, handler: QuarantineArtefactReadGuardHandler) -> None:
        assert handler.get_rules()[0].verbose


class TestQuarantineArtefactReadGuardDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Decision G)."""

    def _hook_input(self, path: str, transcript_path: str) -> dict[str, Any]:
        payload = _hook_input("Read", {"file_path": path})
        payload["transcript_path"] = transcript_path
        return payload

    def test_first_fire_for_agent_is_verbose(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        hook_input = self._hook_input(
            "/p/topic-opus-security-DETAIL.md", "/tmp/agent-a/transcript.jsonl"
        )
        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert "NO escape hatch" in result.reason

    def test_second_fire_for_same_agent_is_terse(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input("/p/topic-opus-security-DETAIL.md", transcript_path))
        result = handler.handle(
            self._hook_input("/p/other-opus-security-DETAIL.md", transcript_path)
        )

        assert result.decision == Decision.DENY
        assert "NO escape hatch" not in result.reason
        assert "opus-security-DETAIL" in result.reason

    def test_terse_message_leads_with_rule_id(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input("/p/topic-opus-security-DETAIL.md", transcript_path))
        result = handler.handle(
            self._hook_input("/p/topic-opus-security-DETAIL.md", transcript_path)
        )

        assert result.reason.startswith(f"BLOCKED [{RuleID.QUARANTINE_ARTEFACT_READ}]")

    def test_missing_transcript_path_is_always_verbose(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        hook_input = _hook_input("Read", {"file_path": "/p/topic-opus-security-DETAIL.md"})
        handler.handle(hook_input)
        result = handler.handle(hook_input)

        assert "SUMMARY" in result.reason
