"""Tests for ErrorHidingBlockerHandler."""

from typing import Any

import pytest
from tests.conftest import layout_declaring_vendor_dirs, registry_declaring_vendor_dirs

from claude_code_hooks_daemon.handlers.pre_tool_use.error_hiding_blocker import (
    ErrorHidingBlockerHandler,
)


@pytest.fixture
def handler() -> ErrorHidingBlockerHandler:
    """Create handler instance for testing."""
    return ErrorHidingBlockerHandler()


def make_write_input(file_path: str, content: str) -> dict[str, Any]:
    """Build a Write tool hook input."""
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }


def make_edit_input(file_path: str, new_string: str) -> dict[str, Any]:
    """Build an Edit tool hook input."""
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": file_path,
            "old_string": "# placeholder",
            "new_string": new_string,
        },
    }


def make_bash_input(command: str) -> dict[str, Any]:
    """Build a Bash tool hook input."""
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestErrorHidingBlockerHandlerInit:
    def test_name(self, handler: ErrorHidingBlockerHandler) -> None:
        assert handler.name == "error-hiding-blocker"

    def test_priority(self, handler: ErrorHidingBlockerHandler) -> None:
        assert handler.priority == 13

    def test_terminal(self, handler: ErrorHidingBlockerHandler) -> None:
        assert handler.terminal is True

    def test_tags_include_safety(self, handler: ErrorHidingBlockerHandler) -> None:
        assert "safety" in handler.tags

    def test_tags_include_blocking(self, handler: ErrorHidingBlockerHandler) -> None:
        assert "blocking" in handler.tags

    def test_tags_include_multi_language(self, handler: ErrorHidingBlockerHandler) -> None:
        assert "multi-language" in handler.tags


class TestErrorHidingBlockerMatchesNotApplicableTools:
    def test_bash_tool_does_not_match(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_bash_input("cmd || true")
        assert handler.matches(hook_input) is False

    def test_read_tool_does_not_match(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/test.sh"},
        }
        assert handler.matches(hook_input) is False

    def test_missing_tool_name_does_not_match(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input: dict[str, Any] = {}
        assert handler.matches(hook_input) is False

    def test_unknown_extension_does_not_match(self, handler: ErrorHidingBlockerHandler) -> None:
        # .xyz has no strategy
        hook_input = make_write_input("/tmp/test.xyz", "some_command || true")
        assert handler.matches(hook_input) is False

    def test_missing_file_path_does_not_match(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"content": "some_command || true"},
        }
        assert handler.matches(hook_input) is False

    def test_empty_content_does_not_match(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/test.sh", "")
        assert handler.matches(hook_input) is False


class TestErrorHidingBlockerMatchesShell:
    def test_write_sh_with_or_true_matches(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/test.sh", "#!/bin/bash\ncmd || true\n")
        assert handler.matches(hook_input) is True

    def test_write_sh_with_set_plus_e_matches(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/test.sh", "#!/bin/bash\nset +e\n")
        assert handler.matches(hook_input) is True

    def test_write_sh_with_dev_null_matches(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/test.sh", "cmd &>/dev/null\n")
        assert handler.matches(hook_input) is True

    def test_edit_sh_with_or_true_matches(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_edit_input("/tmp/script.sh", "cmd || true")
        assert handler.matches(hook_input) is True

    def test_edit_sh_with_or_colon_matches(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_edit_input("/tmp/script.sh", "cmd || :\n")
        assert handler.matches(hook_input) is True

    def test_write_bash_extension_matches(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/test.bash", "cmd || true\n")
        assert handler.matches(hook_input) is True

    def test_clean_shell_script_does_not_match(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input(
            "/tmp/test.sh",
            "#!/bin/bash\nset -euo pipefail\ncmd || { echo 'failed' >&2; exit 1; }\n",
        )
        assert handler.matches(hook_input) is False


class TestErrorHidingBlockerMatchesPython:
    def test_write_py_with_bare_except_pass_matches(
        self, handler: ErrorHidingBlockerHandler
    ) -> None:
        content = "try:\n    do_something()\nexcept:\n    pass\n"
        hook_input = make_write_input("/tmp/test.py", content)
        assert handler.matches(hook_input) is True

    def test_write_py_with_except_exception_pass_matches(
        self, handler: ErrorHidingBlockerHandler
    ) -> None:
        content = "try:\n    do_something()\nexcept Exception:\n    pass\n"
        hook_input = make_write_input("/tmp/test.py", content)
        assert handler.matches(hook_input) is True

    def test_edit_py_with_bare_except_ellipsis_matches(
        self, handler: ErrorHidingBlockerHandler
    ) -> None:
        content = "except:\n    ..."
        hook_input = make_edit_input("/tmp/module.py", content)
        assert handler.matches(hook_input) is True

    def test_clean_python_does_not_match(self, handler: ErrorHidingBlockerHandler) -> None:
        content = (
            "try:\n    do_something()\nexcept ValueError as e:\n    logger.error(e)\n    raise\n"
        )
        hook_input = make_write_input("/tmp/test.py", content)
        assert handler.matches(hook_input) is False


class TestErrorHidingBlockerMatchesJavaScript:
    def test_write_js_with_empty_catch_matches(self, handler: ErrorHidingBlockerHandler) -> None:
        content = "try { doSomething(); } catch (e) {}"
        hook_input = make_write_input("/tmp/test.js", content)
        assert handler.matches(hook_input) is True

    def test_write_ts_with_empty_catch_matches(self, handler: ErrorHidingBlockerHandler) -> None:
        content = "try { doSomething(); } catch (e) {}"
        hook_input = make_write_input("/tmp/test.ts", content)
        assert handler.matches(hook_input) is True

    def test_write_tsx_with_empty_catch_matches(self, handler: ErrorHidingBlockerHandler) -> None:
        content = "try { doSomething(); } catch (e) {}"
        hook_input = make_write_input("/tmp/test.tsx", content)
        assert handler.matches(hook_input) is True

    def test_write_jsx_with_empty_promise_catch_matches(
        self, handler: ErrorHidingBlockerHandler
    ) -> None:
        content = "promise.catch(() => {})"
        hook_input = make_write_input("/tmp/test.jsx", content)
        assert handler.matches(hook_input) is True

    def test_write_mjs_with_empty_catch_matches(self, handler: ErrorHidingBlockerHandler) -> None:
        content = "try { doSomething(); } catch (e) {}"
        hook_input = make_write_input("/tmp/test.mjs", content)
        assert handler.matches(hook_input) is True

    def test_clean_js_does_not_match(self, handler: ErrorHidingBlockerHandler) -> None:
        content = "try { doSomething(); } catch (e) { console.error(e); }"
        hook_input = make_write_input("/tmp/test.js", content)
        assert handler.matches(hook_input) is False


class TestErrorHidingBlockerMatchesGo:
    def test_write_go_with_empty_error_check_matches(
        self, handler: ErrorHidingBlockerHandler
    ) -> None:
        content = "if err != nil {}"
        hook_input = make_write_input("/tmp/main.go", content)
        assert handler.matches(hook_input) is True

    def test_write_go_with_blank_identifier_matches(
        self, handler: ErrorHidingBlockerHandler
    ) -> None:
        content = "result, _ := riskyCall()"
        hook_input = make_write_input("/tmp/main.go", content)
        assert handler.matches(hook_input) is True

    def test_clean_go_does_not_match(self, handler: ErrorHidingBlockerHandler) -> None:
        content = 'if err != nil { return fmt.Errorf("failed: %w", err) }'
        hook_input = make_write_input("/tmp/main.go", content)
        assert handler.matches(hook_input) is False


class TestErrorHidingBlockerMatchesJava:
    def test_write_java_with_empty_catch_matches(self, handler: ErrorHidingBlockerHandler) -> None:
        content = "try { doSomething(); } catch (Exception e) {}"
        hook_input = make_write_input("/tmp/Main.java", content)
        assert handler.matches(hook_input) is True

    def test_clean_java_does_not_match(self, handler: ErrorHidingBlockerHandler) -> None:
        content = "try { doSomething(); } catch (Exception e) { log.error(e.getMessage()); }"
        hook_input = make_write_input("/tmp/Main.java", content)
        assert handler.matches(hook_input) is False


class TestErrorHidingBlockerHandle:
    def test_returns_deny_for_shell_violation(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/test.sh", "cmd || true\n")
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_returns_deny_for_python_violation(self, handler: ErrorHidingBlockerHandler) -> None:
        content = "except:\n    pass\n"
        hook_input = make_write_input("/tmp/test.py", content)
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_reason_contains_blocked(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/test.sh", "cmd || true\n")
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_reason_contains_pattern_name(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/test.sh", "cmd || true\n")
        result = handler.handle(hook_input)
        assert "|| true" in result.reason

    def test_reason_contains_language(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/test.sh", "cmd || true\n")
        result = handler.handle(hook_input)
        assert "Shell" in result.reason

    def test_reason_contains_filename(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/test.sh", "cmd || true\n")
        result = handler.handle(hook_input)
        assert "test.sh" in result.reason

    def test_reason_contains_suggestion(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/test.sh", "cmd || true\n")
        result = handler.handle(hook_input)
        # Suggestion should appear in reason
        assert "Handle failure explicitly" in result.reason

    def test_reason_contains_disable_hint(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/test.sh", "cmd || true\n")
        result = handler.handle(hook_input)
        assert "error_hiding_blocker" in result.reason

    def test_returns_allow_for_clean_shell(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input(
            "/tmp/test.sh",
            "#!/bin/bash\nset -euo pipefail\ncmd || { echo 'failed' >&2; exit 1; }\n",
        )
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_returns_allow_for_unknown_extension(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/test.xyz", "cmd || true\n")
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_returns_allow_for_no_file_path(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"content": "cmd || true\n"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_edit_tool_content_from_new_string(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_edit_input("/tmp/test.sh", "cmd || true")
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_python_reason_contains_language(self, handler: ErrorHidingBlockerHandler) -> None:
        content = "except:\n    pass\n"
        hook_input = make_write_input("/tmp/test.py", content)
        result = handler.handle(hook_input)
        assert "Python" in result.reason

    def test_javascript_reason_contains_language(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/test.js", "catch (e) {}")
        result = handler.handle(hook_input)
        assert "JavaScript" in result.reason

    def test_go_reason_contains_language(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/main.go", "if err != nil {}")
        result = handler.handle(hook_input)
        assert "Go" in result.reason

    def test_java_reason_contains_language(self, handler: ErrorHidingBlockerHandler) -> None:
        hook_input = make_write_input("/tmp/Main.java", "catch (Exception e) {}")
        result = handler.handle(hook_input)
        assert "Java" in result.reason


class TestErrorHidingBlockerAcceptanceTests:
    def test_returns_list(self, handler: ErrorHidingBlockerHandler) -> None:
        assert isinstance(handler.get_acceptance_tests(), list)

    def test_returns_non_empty(self, handler: ErrorHidingBlockerHandler) -> None:
        assert len(handler.get_acceptance_tests()) > 0

    def test_all_languages_represented(self, handler: ErrorHidingBlockerHandler) -> None:
        tests = handler.get_acceptance_tests()
        # At minimum we expect tests for all 5 languages (Shell, Python, JS, Go, Java)
        assert len(tests) >= 10  # 2 tests each x 5 languages


_SHELL_HIDE = "#!/bin/bash\ncmd || true\n"


class TestErrorHidingBlockerExcludePaths:
    """Client-configurable exclude_paths + built-in default skips (Plan 00150)."""

    def test_default_skips_test_fixtures(self, handler: ErrorHidingBlockerHandler) -> None:
        assert handler.matches(make_write_input("/proj/tests/fixtures/x.sh", _SHELL_HIDE)) is False

    def test_default_skips_vendor(self, handler: ErrorHidingBlockerHandler) -> None:
        assert handler.matches(make_write_input("/proj/vendor/pkg/x.sh", _SHELL_HIDE)) is False

    @pytest.mark.parametrize(
        "vendored_dir",
        [
            "dist",
            "build",
            ".build",
            "target",
            ".venv",
            "venv",
            ".next",
            "third_party",
            "coverage",
        ],
    )
    def test_default_skips_core_vendored_build_dirs(
        self, handler: ErrorHidingBlockerHandler, vendored_dir: str
    ) -> None:
        """Plan 00288 Task 3.2: newly-accepted core deltas (measurement §3)."""
        assert handler.matches(make_write_input(f"/proj/{vendored_dir}/x.sh", _SHELL_HIDE)) is False

    def test_declared_vendor_dir_is_skipped(self, handler: ErrorHidingBlockerHandler) -> None:
        """Plan 00331: the defaults were frozen to the canonical set at
        module import, so a declared `layout.vendor_dirs` could not reach
        them. `roles` is not in the canonical set, so a test written against
        `vendor/` would pass without the fix."""
        handler._project_layout = layout_declaring_vendor_dirs("roles")
        assert handler.matches(make_write_input("/proj/infra/roles/x.sh", _SHELL_HIDE)) is False

    def test_undeclared_dir_of_that_name_is_still_blocked(
        self, handler: ErrorHidingBlockerHandler
    ) -> None:
        """The skip must come from the DECLARATION, not from the name."""
        assert handler.matches(make_write_input("/proj/infra/roles/x.sh", _SHELL_HIDE)) is True

    def test_canonical_set_survives_a_declaration(self, handler: ErrorHidingBlockerHandler) -> None:
        handler._project_layout = layout_declaring_vendor_dirs("roles")
        assert handler.matches(make_write_input("/proj/third_party/x.sh", _SHELL_HIDE)) is False

    def test_a_sub_projects_own_declaration_is_honoured(
        self, handler: ErrorHidingBlockerHandler
    ) -> None:
        """Plan 00331 Task 1.3: the vendor set comes from the file's OWNING
        project, resolved through the injected registry.

        Task 1.1 wired these defaults to `self._project_layout` -- the ROOT
        layout -- which `WorkspaceScope.PROJECT` forbids for a project-shaped
        question. In a single-project repo both answers agree, so only a
        monorepo shows the difference.
        """
        handler._project_registry = registry_declaring_vendor_dirs(
            "/proj", "/proj/apps/api", "roles"
        )
        assert handler.matches(make_write_input("/proj/apps/api/roles/x.sh", _SHELL_HIDE)) is False

    def test_a_sibling_sub_project_does_not_inherit_it(
        self, handler: ErrorHidingBlockerHandler
    ) -> None:
        """The discriminating half: reading the ROOT layout would skip this
        too, because a root-wide vendor set knows nothing about who declared
        it."""
        handler._project_registry = registry_declaring_vendor_dirs(
            "/proj", "/proj/apps/api", "roles"
        )
        assert handler.matches(make_write_input("/proj/apps/web/roles/x.sh", _SHELL_HIDE)) is True

    def test_real_source_still_blocked(self, handler: ErrorHidingBlockerHandler) -> None:
        assert handler.matches(make_write_input("/proj/src/deploy.sh", _SHELL_HIDE)) is True

    def test_client_exclude_path_skips(self, handler: ErrorHidingBlockerHandler) -> None:
        handler._exclude_paths = ["samples/**"]
        assert handler.matches(make_write_input("/proj/samples/x.sh", _SHELL_HIDE)) is False

    def test_project_level_exclude_skips(self, handler: ErrorHidingBlockerHandler) -> None:
        handler._project_exclude_paths = ["**/scratch/**"]
        assert handler.matches(make_write_input("/proj/scratch/x.sh", _SHELL_HIDE)) is False

    def test_is_excluded_false_for_normal_source(self, handler: ErrorHidingBlockerHandler) -> None:
        assert handler._is_excluded("/proj/src/deploy.sh") is False


class TestErrorHidingBlockerGetRules:
    """get_rules() (Plan 00116): one rule, language dimension lives in verbose."""

    def test_get_rules_returns_one_rule(self) -> None:
        rules = ErrorHidingBlockerHandler().get_rules()
        assert len(rules) == 1

    def test_get_rules_rule_id_is_constant(self) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        rule = ErrorHidingBlockerHandler().get_rules()[0]
        assert rule.rule_id == RuleID.ERROR_HIDING

    def test_get_rules_verbose_is_non_empty(self) -> None:
        rule = ErrorHidingBlockerHandler().get_rules()[0]
        assert rule.verbose


class TestErrorHidingBlockerDisclosureLadder:
    """Verbose-first/terse-after per (transcript_path, rule_id) (Plan 00116)."""

    @pytest.fixture(autouse=True)
    def _reset_disclosure_tracker(self):
        from claude_code_hooks_daemon.core import reset_data_layer

        reset_data_layer()
        yield
        reset_data_layer()

    @staticmethod
    def _hook_input(transcript_path: str | None) -> dict[str, Any]:
        hook_input = make_write_input("/proj/src/deploy.sh", _SHELL_HIDE)
        if transcript_path is not None:
            hook_input["transcript_path"] = transcript_path
        return hook_input

    def test_deny_reason_starts_with_rule_id_prefix(self) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        handler = ErrorHidingBlockerHandler()
        result = handler.handle(self._hook_input("/tmp/transcript-eh-a.jsonl"))
        assert result.reason.startswith(f"BLOCKED [{RuleID.ERROR_HIDING}]")

    def test_first_fire_is_verbose(self) -> None:
        handler = ErrorHidingBlockerHandler()
        result = handler.handle(self._hook_input("/tmp/transcript-eh-b.jsonl"))
        assert "cardinal sin" in result.reason

    def test_second_fire_same_agent_is_terse(self) -> None:
        handler = ErrorHidingBlockerHandler()
        transcript = "/tmp/transcript-eh-c.jsonl"
        handler.handle(self._hook_input(transcript))
        second = handler.handle(self._hook_input(transcript))
        assert "cardinal sin" not in second.reason
        assert "PATTERN:" in second.reason

    def test_different_agent_is_independently_verbose(self) -> None:
        handler = ErrorHidingBlockerHandler()
        handler.handle(self._hook_input("/tmp/transcript-eh-d.jsonl"))
        other = handler.handle(self._hook_input("/tmp/transcript-eh-e.jsonl"))
        assert "cardinal sin" in other.reason

    def test_missing_transcript_path_always_verbose(self) -> None:
        handler = ErrorHidingBlockerHandler()
        first = handler.handle(self._hook_input(None))
        second = handler.handle(self._hook_input(None))
        assert "cardinal sin" in first.reason
        assert "cardinal sin" in second.reason
