"""Unit tests for QuarantineArtefactReadGuardHandler (Plan 00278 Phase 3d.2).

Enforces the ``*-opus-security-DETAIL*`` read-boundary by PATTERN, not trust:
the DETAIL artefact holds raw flaggable substance the coordinator must NEVER
read. Read/Edit/Grep/NotebookEdit and content-revealing Bash over a matching
path are DENIED; the paired SUMMARY artefact and authoring (Write) the DETAIL
file itself stay allowed. Ships DISABLED but pre-seeded, so enabling it works
out of the box with no config.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from tests.bash_sandbox import run_sandboxed_bash
from tests.indexed_project import index_project

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use import quarantine_artefact_read_guard as guard
from claude_code_hooks_daemon.handlers.pre_tool_use.quarantine_artefact_read_guard import (
    QuarantineArtefactReadGuardHandler,
)
from claude_code_hooks_daemon.utils import protected_file_index


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test in this module."""
    reset_data_layer()
    yield
    reset_data_layer()


def _hook_input(
    tool_name: str, tool_input: dict[str, Any], cwd: Path | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "tool_name": tool_name,
        "tool_input": tool_input,
    }
    if cwd is not None:
        payload["cwd"] = str(cwd)
    return payload


@pytest.fixture(autouse=True)
def _fresh_index_cache():
    """No protected-file index survives from one test to the next."""
    protected_file_index.reset_index_cache()
    yield
    protected_file_index.reset_index_cache()


@pytest.fixture
def handler() -> QuarantineArtefactReadGuardHandler:
    return QuarantineArtefactReadGuardHandler()


def _indexed(
    handler: QuarantineArtefactReadGuardHandler, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Make ``root`` the project and serve the handler its index of quarantined artefacts."""
    monkeypatch.setattr(guard, "resolve_project_root", lambda: root)
    index_project(root, handler._effective_globs())


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
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "topic-opus-security-DETAIL.md").write_text("raw")
        _indexed(handler, tmp_path, monkeypatch)
        payload = _hook_input("Grep", {"pattern": "x", "path": str(tmp_path)})
        assert handler.matches(payload) is True

    def test_grep_rooted_at_directory_without_detail_artefact_does_not_match(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "ordinary.md").write_text("fine")
        _indexed(handler, tmp_path, monkeypatch)
        payload = _hook_input("Grep", {"pattern": "x", "path": str(tmp_path)})
        assert handler.matches(payload) is False


class TestBashRecursiveSearch:
    """Plan 00483 D1 (ledger 00474 N144): a recursive search reads a DETAIL artefact."""

    @pytest.fixture
    def holding_dir(
        self,
        tmp_path: Path,
        handler: QuarantineArtefactReadGuardHandler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Path:
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "topic-opus-security-DETAIL.md").write_text("raw")
        (tmp_path / "other").mkdir()
        (tmp_path / "other" / "ordinary.md").write_text("fine")
        _indexed(handler, tmp_path, monkeypatch)
        return tmp_path

    @pytest.mark.parametrize(
        "command",
        [
            "grep -r x .",
            "grep -rl x reports",
            "rg x",
            "find . | xargs rg x",
            "find . -name '*.md' -exec grep x {} +",
            "bash -c 'grep -r x .'",
        ],
    )
    def test_search_over_a_tree_holding_an_artefact_matches(
        self, handler: QuarantineArtefactReadGuardHandler, holding_dir: Path, command: str
    ) -> None:
        payload = _hook_input("Bash", {"command": command}, cwd=holding_dir)
        assert handler.matches(payload) is True
        assert handler.handle(payload).decision == Decision.DENY

    @pytest.mark.parametrize("command", ["grep -r x other", "rg x other", "grep x ."])
    def test_search_over_a_clean_tree_does_not_match(
        self, handler: QuarantineArtefactReadGuardHandler, holding_dir: Path, command: str
    ) -> None:
        payload = _hook_input("Bash", {"command": command}, cwd=holding_dir)
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
        _indexed(handler, tmp_path, monkeypatch)
        payload = _hook_input("Bash", {"command": "grep -c pattern docs/*.md"}, cwd=tmp_path)
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
        _indexed(handler, tmp_path, monkeypatch)
        payload = _hook_input("Bash", {"command": "grep -c pattern docs/*.md"}, cwd=tmp_path)
        assert handler.matches(payload) is True

    def test_glob_token_in_a_directory_with_no_files_at_all_is_allowed(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _indexed(handler, tmp_path, monkeypatch)
        payload = _hook_input("Bash", {"command": "grep -c pattern *.md"}, cwd=tmp_path)
        assert handler.matches(payload) is False

    def test_a_malformed_recursive_wildcard_is_judged_rather_than_raising(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Plan 00357: `Path.glob` is lazy, so a pattern it rejects raises on
        the FIRST ITERATION, not at the call. A guard around the call alone
        lets the ValueError escape `matches()`, and the daemon's fail-open
        policy then skips this guard for the whole tool call. The malformed
        token must be judged like any other glob that expands to nothing."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "topic-opus-security-DETAIL.md").write_text("raw")
        _indexed(handler, tmp_path, monkeypatch)
        payload = _hook_input("Bash", {"command": "grep -c pattern docs/a**b.md"}, cwd=tmp_path)
        assert handler.matches(payload) is False

    def test_a_malformed_wildcard_does_not_hide_a_literal_detail_token(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The escape's real cost: a malformed glob EARLIER in the command
        aborted matching before a literal protected token was ever reached."""
        monkeypatch.chdir(tmp_path)
        payload = _hook_input("Bash", {"command": "cat docs/a**b.md topic-opus-security-DETAIL.md"})
        assert handler.matches(payload) is True

    def test_a_single_name_past_the_name_limit_stays_allowed(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        chain = HandlerChain()
        chain.add(handler)
        command = "grep -c pattern " + "n" * 300 + "/*.md"
        result = chain.execute(_hook_input("Bash", {"command": command}), strict_mode=False)
        assert result.result.decision != Decision.DENY, result.result.reason

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
        assert result.reason is not None
        assert "opus-security-DETAIL" in result.reason

    def test_deny_reason_explains_summary_contract(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Read", {"file_path": "/p/topic-opus-security-DETAIL.md"})
        result = handler.handle(payload)
        assert result.reason is not None
        assert "SUMMARY" in result.reason
        assert "NO escape hatch" in result.reason

    def test_allow_when_no_match(self, handler: QuarantineArtefactReadGuardHandler) -> None:
        payload = _hook_input("Read", {"file_path": "/p/src/app.py"})
        result = handler.handle(payload)
        assert result.decision == Decision.ALLOW


class TestEvaluationErrorIsAllowedWithAdvisory:
    """Plan 00483 A1: a call the guard could not finish judging is allowed with
    an advisory, never denied -- unless the command itself names an artefact."""

    @pytest.mark.parametrize("error", [OSError, PermissionError, ValueError, TimeoutError])
    def test_an_error_is_an_advisory_not_a_deny(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        monkeypatch: pytest.MonkeyPatch,
        error: type[Exception],
    ) -> None:
        def _raise(self: Any, hook_input: dict[str, Any]) -> str | None:
            raise error("simulated failure")

        monkeypatch.setattr(QuarantineArtefactReadGuardHandler, "_evaluate_matched_pattern", _raise)
        payload = _hook_input("Bash", {"command": "cat some-ordinary-file"})
        assert handler.matches(payload) is True
        result = handler.handle(payload)
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "could NOT fully judge" in result.context[0]

    def test_a_literal_artefact_in_the_command_still_denies(
        self, handler: QuarantineArtefactReadGuardHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(self: Any, hook_input: dict[str, Any]) -> str | None:
            raise TimeoutError("deadline")

        monkeypatch.setattr(QuarantineArtefactReadGuardHandler, "_evaluate_matched_pattern", _raise)
        payload = _hook_input("Bash", {"command": "cat topic-opus-security-DETAIL.md"})
        result = handler.handle(payload)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert RuleID.QUARANTINE_ARTEFACT_READ in result.reason

    def test_a_raise_on_the_read_tool_is_an_advisory(
        self, handler: QuarantineArtefactReadGuardHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(self: Any, hook_input: dict[str, Any]) -> str | None:
            raise ValueError("simulated malformed-pattern failure")

        monkeypatch.setattr(QuarantineArtefactReadGuardHandler, "_evaluate_matched_pattern", _raise)
        result = handler.handle(_hook_input("Read", {"file_path": "/p/src/app.py"}))
        assert result.decision == Decision.ALLOW


class TestMalformedToolInputNeverRaises:
    """n466-n24 review 4 (mirroring secret_file_guard's own M-2, Plan 00466
    review 3): a malformed `tool_input` (`None`, a list, a bare string
    instead of the expected dict) must never let an exception escape
    `matches()`/`handle()` uncaught -- an uncaught exception is an ALLOW in
    a non-strict chain.

    Unlike `secret_file_guard`/`project_containment`, this handler has no
    separate `_dispatch_key`/caching layer at all (`matches()`/`handle()`
    each call `_matched_pattern` fresh) -- so the specific M-2 defect class
    (a caching key computed OUTSIDE the fail-closed wrapper) cannot occur
    here structurally; there is nothing outside the wrapper to leave
    unguarded. `_evaluate_matched_pattern` itself already isinstance-guards
    both `hook_input` and `tool_input` and returns `None` -- a genuine,
    correct ALLOW, since there is no command or path to search -- rather
    than raising, for all three malformed shapes. These tests pin that
    directly; `TestFailClosedOnEvaluationError` above separately pins that
    IF evaluation ever did raise, the wrapper denies.
    """

    @staticmethod
    def _payload(bad_tool_input: Any) -> dict[str, Any]:
        return {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "Bash",
            "tool_input": bad_tool_input,
        }

    @pytest.mark.parametrize("bad_tool_input", [None, [], "not-a-dict"])
    def test_matches_does_not_raise(
        self, handler: QuarantineArtefactReadGuardHandler, bad_tool_input: Any
    ) -> None:
        assert handler.matches(self._payload(bad_tool_input)) is False

    @pytest.mark.parametrize("bad_tool_input", [None, [], "not-a-dict"])
    def test_handle_does_not_raise_and_allows(
        self, handler: QuarantineArtefactReadGuardHandler, bad_tool_input: Any
    ) -> None:
        result = handler.handle(self._payload(bad_tool_input))
        assert result.decision == Decision.ALLOW

    @pytest.mark.parametrize("bad_tool_input", [None, [], "not-a-dict"])
    def test_handle_alone_also_does_not_raise(
        self, handler: QuarantineArtefactReadGuardHandler, bad_tool_input: Any
    ) -> None:
        """`handle()` called with no preceding `matches()` for the SAME
        input must independently survive too."""
        result = handler.handle(self._payload(bad_tool_input))
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


class TestDeclaredAcceptancePatternsAreProducible:
    """Every declared acceptance pattern must match the reason really produced.

    The release acceptance gate passes a test only when the handler's own
    ``expected_message_patterns`` match the live deny reason. A pattern left
    behind by a header change therefore makes the gate unpassable while the
    handler is behaving perfectly -- reporting a correct handler as a release
    blocker, and costing a FAIL-FAST cycle to work out that nothing is wrong.
    """

    def _patterns_for(
        self, handler: QuarantineArtefactReadGuardHandler, title_fragment: str
    ) -> list[str]:
        for test in handler.get_acceptance_tests():
            if title_fragment in test.title:
                return list(test.expected_message_patterns)
        raise AssertionError(f"no acceptance test titled like {title_fragment!r}")

    def test_read_deny_reason_matches_its_declared_patterns(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Read", {"file_path": "/tmp/topic-opus-security-DETAIL.md"})
        reason = handler.handle(payload).reason or ""
        for pattern in self._patterns_for(handler, "blocks Read of a DETAIL artefact"):
            assert re.search(pattern, reason), f"{pattern!r} no longer appears in: {reason}"

    def test_bash_deny_reason_matches_its_declared_patterns(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        payload = _hook_input("Bash", {"command": "cat /tmp/topic-opus-security-DETAIL.md"})
        reason = handler.handle(payload).reason or ""
        for pattern in self._patterns_for(handler, "blocks Bash cat of a DETAIL artefact"):
            assert re.search(pattern, reason), f"{pattern!r} no longer appears in: {reason}"


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
    """get_rules() declares the one Rule backing this handler's deny (Plan 00116)."""

    def test_returns_one_rule(self, handler: QuarantineArtefactReadGuardHandler) -> None:
        rules = handler.get_rules()
        assert len(rules) == 1
        assert all(isinstance(rule, Rule) for rule in rules)

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
        assert result.reason is not None
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
        assert result.reason is not None
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

        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.QUARANTINE_ARTEFACT_READ}]")

    def test_missing_transcript_path_is_always_verbose(
        self, handler: QuarantineArtefactReadGuardHandler
    ) -> None:
        hook_input = _hook_input("Read", {"file_path": "/p/topic-opus-security-DETAIL.md"})
        handler.handle(hook_input)
        result = handler.handle(hook_input)

        assert result.reason is not None
        assert "SUMMARY" in result.reason


def _bash_words(command: str, cwd: Path) -> list[str]:
    """The words bash passes to a program for ``command``'s arguments."""
    return run_sandboxed_bash(f"printf '%s\\n' {command}", cwd, "/usr/bin:/bin").splitlines()


class TestAQuotedGlobIsNeverEnumerated:
    """Ledger 00466 N238: a quoted word is a literal, which bash hands on as
    written, so it must not reach the enumerator; one bash does expand and
    that cannot be listed within the budget is a named deny, never a guard
    bug. Each shape is run through bash first."""

    @pytest.mark.parametrize(
        ("command", "argument"),
        [
            ("rg -g '**/*.md' x", "'**/*.md'"),
            ("grep -rn x --include='**/*.md' .", "--include='**/*.md'"),
            ("jq '.files[\"d1/*.md\"]' r.json", "'.files[\"d1/*.md\"]'"),
            ('echo "**/*.md"', '"**/*.md"'),
            ("ls \\*\\*/\\*.md", "\\*\\*/\\*.md"),
        ],
    )
    def test_a_quoted_glob_is_not_enumerated(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        command: str,
        argument: str,
    ) -> None:
        (tmp_path / "d1").mkdir()
        (tmp_path / "d1" / "ordinary.md").touch()
        assert len(_bash_words(argument, tmp_path)) == 1
        _indexed(handler, tmp_path, monkeypatch)
        assert handler.matches(_hook_input("Bash", {"command": command}, cwd=tmp_path)) is False

    def test_a_quoted_artefact_name_is_still_a_mention(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        payload = _hook_input("Bash", {"command": "cat 'docs/topic-opus-security-DETAIL.md'"})
        assert handler.matches(payload) is True

    @pytest.mark.parametrize(
        "command",
        [
            # (v) a quoted regex holding `**`, with a two-wildcard path.
            "awk '/**Round**/,0' d*/*f1*",
            "awk '/x/,0' d*/*f1*",
            # (vi) a plain grep with a regex.
            "grep -n '/**Status**/' d1/f1.md",
            "grep -rn 'x.*y' .",
            'grep -n "^#.*d1" d1/f1.md',
            "grep -nE '^d[0-9]+/.*:.*#' d1/f1.md",
            # (vii) a grep with several -e patterns.
            "grep -n -e '/**a**/' -e '/b/**' -e 'c.*' d1/f1.md",
            "grep -rn -e 'a.*b' -e 'c.*d' -e '^x' -e 'y$' -e '[0-9]*' .",
            # (ix) a quote-heavy heredoc.
            "cat > q.md <<'EOF'\n"
            + "\n".join(f"- it's \"{i}\" and '{{a,b}}' or \"*.md\" 'd*/f*'" for i in range(600))
            + "\nEOF",
        ],
    )
    def test_a_regex_or_quoted_prose_is_allowed(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        command: str,
    ) -> None:
        _indexed(handler, tmp_path, monkeypatch)
        hook_input = _hook_input("Bash", {"command": command}, cwd=tmp_path)
        assert handler.matches(hook_input) is False

    def test_a_two_wildcard_glob_within_the_budget_is_allowed(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        for directory in range(3):
            (tmp_path / f"d{directory}").mkdir()
            (tmp_path / f"d{directory}" / "f-p421.md").touch()
        _indexed(handler, tmp_path, monkeypatch)
        hook_input = _hook_input("Bash", {"command": "awk '/x/,0' d*/*p421*"}, cwd=tmp_path)
        assert handler.matches(hook_input) is False


class TestUnjudgedCallsAreAllowedWithAdvisory:
    """Plan 00483 A1: with no index to judge a recursive search by, the call is
    allowed and the advisory says what was not checked."""

    @pytest.fixture
    def no_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            QuarantineArtefactReadGuardHandler, "_index", lambda self, patterns: None
        )

    @pytest.mark.parametrize(
        ("tool_name", "tool_input"),
        [
            (ToolName.GREP, {"pattern": "x"}),
            (ToolName.BASH, {"command": "grep -r x ."}),
        ],
    )
    def test_a_search_with_no_index_is_allowed_with_an_advisory(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        no_index: None,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> None:
        if tool_name == ToolName.GREP:
            tool_input = {**tool_input, "path": str(tmp_path)}
        result = handler.handle(_hook_input(tool_name, tool_input, cwd=tmp_path))
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "index of quarantined artefacts is not available" in result.context[0]

    def test_a_finding_keeps_its_own_rule(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "topic-opus-security-DETAIL.md").touch()
        _indexed(handler, tmp_path, monkeypatch)
        result = handler.handle(_hook_input("Bash", {"command": "grep -r x ."}, cwd=tmp_path))
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.QUARANTINE_ARTEFACT_READ}]")

    def test_a_passed_deadline_is_an_advisory(
        self,
        handler: QuarantineArtefactReadGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _expired(*_args: object, **_kwargs: object) -> None:
            raise TimeoutError

        monkeypatch.setattr(
            QuarantineArtefactReadGuardHandler, "_evaluate_matched_pattern", _expired
        )
        result = handler.handle(_hook_input("Bash", {"command": "ls"}, cwd=tmp_path))
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "deadline" in result.context[0]
