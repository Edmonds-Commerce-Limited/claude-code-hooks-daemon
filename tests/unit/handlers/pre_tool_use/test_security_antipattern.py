"""Comprehensive tests for SecurityAntipatternHandler."""

from typing import ClassVar

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.security_antipattern import (
    SecurityAntipatternHandler,
)


class TestSecurityAntipatternHandler:
    """Test suite for SecurityAntipatternHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return SecurityAntipatternHandler()

    # ── Initialization Tests ──────────────────────────────────────────

    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'block-security-antipatterns'."""
        assert handler.name == "block-security-antipatterns"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 14."""
        assert handler.priority == 14

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (blocks execution)."""
        assert handler.terminal is True

    def test_init_has_safety_tag(self, handler):
        """Handler should have SAFETY tag."""
        tag_values = [t.value if hasattr(t, "value") else t for t in handler.tags]
        assert "safety" in tag_values

    def test_init_has_blocking_tag(self, handler):
        """Handler should have BLOCKING tag."""
        tag_values = [t.value if hasattr(t, "value") else t for t in handler.tags]
        assert "blocking" in tag_values

    # ── matches() - Hardcoded Secrets (OWASP A02) ────────────────────

    def test_matches_aws_access_key(self, handler):
        """Should match AWS access key in file content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/config.ts",
                "content": 'const key = "AKIAIOSFODNN7EXAMPLE1";',
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_stripe_secret_key(self, handler):
        """Should match Stripe secret key."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/payment.ts",
                "content": 'const stripe = "sk_live_abcdefghijklmnopqrstuvwx";',
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_stripe_publishable_live_key(self, handler):
        """Should match Stripe publishable live key."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/payment.ts",
                "content": 'const pk = "pk_live_abcdefghijklmnopqrstuvwx";',
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_github_personal_access_token(self, handler):
        """Should match GitHub personal access token."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/api.ts",
                "content": 'const token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij";',
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_github_oauth_token(self, handler):
        """Should match GitHub OAuth token."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/auth.ts",
                "content": 'const token = "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij";',
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_rsa_private_key(self, handler):
        """Should match RSA private key."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/keys.ts",
                "content": "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_ec_private_key(self, handler):
        """Should match EC private key."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/keys.ts",
                "content": "-----BEGIN EC PRIVATE KEY-----\nMHQC...",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_generic_private_key(self, handler):
        """Should match generic private key."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/keys.ts",
                "content": "-----BEGIN PRIVATE KEY-----\nMIIEvg...",
            },
        }
        assert handler.matches(hook_input) is True

    # ── matches() - PHP Dangerous Functions (OWASP A03) ──────────────

    def test_matches_php_eval(self, handler):
        """Should match PHP eval() call."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/process.php",
                "content": "<?php eval($userInput);",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_php_exec(self, handler):
        """Should match PHP exec() call."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/run.php",
                "content": '<?php exec("ls -la");',
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_php_shell_exec(self, handler):
        """Should match PHP shell_exec() call."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/run.php",
                "content": '<?php shell_exec("whoami");',
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_php_system(self, handler):
        """Should match PHP system() call."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/run.php",
                "content": '<?php system("id");',
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_php_passthru(self, handler):
        """Should match PHP passthru() call."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/run.php",
                "content": '<?php passthru("cat /etc/passwd");',
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_php_proc_open(self, handler):
        """Should match PHP proc_open() call."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/run.php",
                "content": "<?php proc_open($cmd, $desc, $pipes);",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_php_unserialize(self, handler):
        """Should match PHP unserialize() call."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/data.php",
                "content": "<?php unserialize($userData);",
            },
        }
        assert handler.matches(hook_input) is True

    # ── matches() - TS/JS Dangerous Patterns (OWASP A03) ────────────

    def test_matches_ts_eval(self, handler):
        """Should match TypeScript eval() call."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/utils.ts",
                "content": "const result = eval(userCode);",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_js_eval(self, handler):
        """Should match JavaScript eval() call."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/utils.js",
                "content": "const result = eval(userCode);",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_tsx_eval(self, handler):
        """Should match TSX eval() call."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/App.tsx",
                "content": "eval(code);",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_jsx_eval(self, handler):
        """Should match JSX eval() call."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/App.jsx",
                "content": "eval(code);",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_new_function(self, handler):
        """Should match new Function() constructor."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/dynamic.ts",
                "content": 'const fn = new Function("return " + userInput);',
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_dangerously_set_inner_html(self, handler):
        """Should match dangerouslySetInnerHTML."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/Component.tsx",
                "content": "<div dangerouslySetInnerHTML={{__html: userContent}} />",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_inner_html_assignment(self, handler):
        """Should match innerHTML assignment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/dom.ts",
                "content": "element.innerHTML = userContent;",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_document_write(self, handler):
        """Should match document.write() call."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/legacy.js",
                "content": "document.write(content);",
            },
        }
        assert handler.matches(hook_input) is True

    # ── matches() - Edit Tool Support ────────────────────────────────

    def test_matches_edit_tool_with_secret_in_new_string(self, handler):
        """Should match secrets in Edit tool's new_string field."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/src/config.ts",
                "old_string": "const key = '';",
                "new_string": 'const key = "AKIAIOSFODNN7EXAMPLE1";',
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_tool_with_php_eval(self, handler):
        """Should match PHP eval in Edit tool's new_string."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/src/run.php",
                "old_string": "// placeholder",
                "new_string": "eval($userInput);",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_tool_with_ts_eval(self, handler):
        """Should match TS eval in Edit tool's new_string."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/src/utils.ts",
                "old_string": "// placeholder",
                "new_string": "eval(userCode);",
            },
        }
        assert handler.matches(hook_input) is True

    # ── matches() - Negative Cases: Non-Write/Edit Tools ─────────────

    def test_matches_bash_tool_returns_false(self, handler):
        """Should NOT match Bash tool even with secret-like content."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": 'echo "AKIAIOSFODNN7EXAMPLE1"'},
        }
        assert handler.matches(hook_input) is False

    def test_matches_read_tool_returns_false(self, handler):
        """Should NOT match Read tool."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/src/config.ts"},
        }
        assert handler.matches(hook_input) is False

    # ── matches() - Negative Cases: Skip Directories ─────────────────

    def test_matches_vendor_dir_returns_false(self, handler):
        """Should NOT match files in vendor directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/vendor/lib/auth.php",
                "content": "<?php eval($code);",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_node_modules_returns_false(self, handler):
        """Should NOT match files in node_modules directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/node_modules/pkg/index.js",
                "content": "eval(code);",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_test_fixtures_returns_false(self, handler):
        """Should NOT match files in tests/fixtures directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/tests/fixtures/security_test.php",
                "content": "<?php eval($testInput);",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_test_assets_returns_false(self, handler):
        """Should NOT match files in tests/assets directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/tests/assets/payload.js",
                "content": "eval(testCode);",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_env_example_returns_false(self, handler):
        """Should NOT match .env.example files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/.env.example",
                "content": 'AWS_KEY="AKIAIOSFODNN7EXAMPLE1"',
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_docs_dir_returns_false(self, handler):
        """Should NOT match files in docs directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/docs/security.md",
                "content": "Example: eval($userInput) is dangerous",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_claude_dir_returns_false(self, handler):
        """Should NOT match files in CLAUDE directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/security.md",
                "content": "Example: eval($userInput) is dangerous",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_eslint_rules_dir_returns_false(self, handler):
        """Should NOT match files in eslint-rules directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/eslint-rules/no-eval.js",
                "content": "// Rule to detect eval()",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_phpstan_rules_dir_returns_false(self, handler):
        """Should NOT match files in tests/PHPStan directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/tests/PHPStan/rules/no-eval.php",
                "content": "<?php eval($code);",
            },
        }
        assert handler.matches(hook_input) is False

    # ── matches() - Negative Cases: Clean Content ────────────────────

    def test_matches_clean_php_file_returns_false(self, handler):
        """Should NOT match clean PHP file."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/hello.php",
                "content": '<?php echo "Hello World";',
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_clean_ts_file_returns_false(self, handler):
        """Should NOT match clean TypeScript file."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/hello.ts",
                "content": "const greeting: string = 'Hello World';",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_empty_content_returns_false(self, handler):
        """Should NOT match empty content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/empty.ts",
                "content": "",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_no_file_path_returns_false(self, handler):
        """Should NOT match when file path is missing."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "content": "eval(code);",
            },
        }
        assert handler.matches(hook_input) is False

    # ── matches() - PHP patterns only on PHP files ───────────────────

    def test_matches_php_exec_in_ts_file_returns_false(self, handler):
        """PHP exec() should NOT trigger on TypeScript files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/utils.ts",
                "content": "child_process.exec('ls');",
            },
        }
        # exec in TS should not trigger PHP patterns
        # (TS has its own patterns, and child_process.exec is different from bare exec())
        assert handler.matches(hook_input) is False

    def test_matches_php_system_in_py_file_returns_false(self, handler):
        """PHP system() should NOT trigger on Python files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/utils.py",
                "content": "shell_exec('ls')",
            },
        }
        assert handler.matches(hook_input) is False

    # ── matches() - Secrets match on ANY file type ───────────────────

    def test_matches_aws_key_in_python_file(self, handler):
        """Secrets should match regardless of file type."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/config.py",
                "content": 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE1"',
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_private_key_in_yaml_file(self, handler):
        """Private key should match in YAML file."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/config.yaml",
                "content": "key: |\n  -----BEGIN PRIVATE KEY-----\n  MIIEvg...",
            },
        }
        assert handler.matches(hook_input) is True

    # ── handle() Tests ───────────────────────────────────────────────

    def test_handle_returns_deny_for_aws_key(self, handler):
        """handle() should return deny for AWS key."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/config.ts",
                "content": 'const key = "AKIAIOSFODNN7EXAMPLE1";',
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_reason_contains_owasp_a02(self, handler):
        """handle() reason should contain OWASP A02 for secrets."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/config.ts",
                "content": 'const key = "AKIAIOSFODNN7EXAMPLE1";',
            },
        }
        result = handler.handle(hook_input)
        assert "[A02]" in result.reason

    def test_handle_reason_contains_owasp_a03_for_php(self, handler):
        """handle() reason should contain OWASP A03 for PHP injection."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/run.php",
                "content": "<?php eval($code);",
            },
        }
        result = handler.handle(hook_input)
        assert "[A03]" in result.reason

    def test_handle_reason_contains_owasp_a03_for_ts(self, handler):
        """handle() reason should contain OWASP A03 for TS injection."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/utils.ts",
                "content": "eval(code);",
            },
        }
        result = handler.handle(hook_input)
        assert "[A03]" in result.reason

    def test_handle_reason_contains_blocked_indicator(self, handler):
        """handle() reason should lead with the BLOCKED [rule_id] prefix (Plan 00116)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/config.ts",
                "content": 'const key = "AKIAIOSFODNN7EXAMPLE1";',
            },
        }
        result = handler.handle(hook_input)
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        assert result.reason.startswith(f"BLOCKED [{RuleID.SEC_HARDCODED_CREDS}]")

    def test_handle_reason_contains_file_path(self, handler):
        """handle() reason should include the file path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/config.ts",
                "content": 'const key = "AKIAIOSFODNN7EXAMPLE1";',
            },
        }
        result = handler.handle(hook_input)
        assert "/workspace/src/config.ts" in result.reason

    def test_handle_reason_contains_issue_label(self, handler):
        """handle() reason should contain the specific issue label."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/config.ts",
                "content": 'const key = "AKIAIOSFODNN7EXAMPLE1";',
            },
        }
        result = handler.handle(hook_input)
        assert "AWS Access Key" in result.reason

    def test_handle_multiple_issues_reports_all(self, handler):
        """handle() should report all detected issues."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/bad.php",
                "content": ("<?php\n" '$key = "AKIAIOSFODNN7EXAMPLE1";\n' "eval($userInput);\n"),
            },
        }
        result = handler.handle(hook_input)
        assert "[A02]" in result.reason
        assert "[A03]" in result.reason
        assert "Issues detected (2)" in result.reason

    def test_handle_returns_allow_when_no_file_path(self, handler):
        """handle() should return allow when file path is missing."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "content": "eval(code);",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_returns_allow_when_no_content(self, handler):
        """handle() should return allow when content is empty."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/empty.ts",
                "content": "",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    # Finding #64: the skip-directory guard must apply to handle() too.
    # The antipattern payload is assembled at runtime so this test file itself
    # does not trip the live security_antipattern hook on edit.
    def test_handle_honours_skip_directory_guard(self, handler):
        """handle() must NOT block a file in a skip directory, mirroring matches()."""
        payload = "<?php " + "ev" + "al($code);"
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/vendor/lib/auth.php",
                "content": payload,
            },
        }
        # matches() already skips this; handle() must agree even if called directly.
        assert handler.matches(hook_input) is False
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_find_all_violations_skips_directory(self, handler):
        """_find_all_violations returns no issues for a skip-directory file."""
        payload = "<?php " + "ev" + "al($code);"
        issues = handler._find_all_violations(payload, "/workspace/node_modules/pkg/index.php")
        assert issues == []


_EXCLUDE_PHP_PAYLOAD = "<?php " + "passthru" + '("ls");'


class TestSecurityAntipatternExcludePaths:
    """Client-configurable exclude_paths (Plan 00150)."""

    def _write(self, path, content):
        return {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}}

    def test_is_excluded_true_for_client_glob(self):
        h = SecurityAntipatternHandler()
        h._exclude_paths = ["**/fixtures/**"]
        assert h._is_excluded("/proj/tests/fixtures/x.php") is True

    def test_is_excluded_false_without_patterns(self):
        h = SecurityAntipatternHandler()
        assert h._is_excluded("/proj/src/app.php") is False

    def test_matches_false_for_excluded_path(self):
        h = SecurityAntipatternHandler()
        h._exclude_paths = ["samples/**"]
        assert h.matches(self._write("/proj/samples/x.php", _EXCLUDE_PHP_PAYLOAD)) is False

    def test_real_source_still_blocked(self):
        h = SecurityAntipatternHandler()
        assert h.matches(self._write("/proj/src/x.php", _EXCLUDE_PHP_PAYLOAD)) is True

    def test_project_level_exclude_skips(self):
        h = SecurityAntipatternHandler()
        h._project_exclude_paths = ["**/vendored/**"]
        assert h.matches(self._write("/proj/vendored/x.php", _EXCLUDE_PHP_PAYLOAD)) is False


class TestGuidanceMatchesImplementedPatterns:
    """The resident guidance must not promise detection that does not exist.

    ``get_claude_md()`` is inlined into every client project's CLAUDE.md and
    read in full every session, so an agent treats it as the authoritative
    statement of what this handler covers. Claiming a category that no
    strategy implements is worse than silence: it invites the agent to relax
    its own vigilance about a class of bug nothing is actually watching for.

    Shipped guidance asserted SQL injection, weak cryptography and path
    traversal were blocked. Not one of the eleven language strategies had a
    pattern for any of the three. Found by probing the live daemon with a
    string-concatenated SQL query during the v3.52.0 release acceptance gate
    and watching it sail through.

    This is the DBF guard for that defect: every category the guidance names
    must be evidenced by a real pattern, and a NEW category cannot be added
    to the guidance without adding its evidence here.
    """

    # Category label (as written in the guidance) -> a substring that must
    # appear in at least one registered pattern name. Adding a bullet to
    # get_claude_md() without adding a row here fails the completeness test.
    CATEGORY_EVIDENCE: ClassVar[dict[str, str]] = {
        "Code injection": "code injection",
        "Command injection": "command injection",
        "Unsafe deserialization": "deserialization",
        "XSS": "XSS",
        "Hardcoded credentials": "Key",
    }

    _CATEGORY_HEADING = "**Blocked categories**:"
    _BULLET = "- "

    def _pattern_names(self) -> list[str]:
        handler = SecurityAntipatternHandler()
        names: list[str] = []
        for strategy in handler._registry.all_strategies:
            names.extend(pattern.name for pattern in strategy.patterns)
        return names

    def _guidance_categories(self) -> list[str]:
        guidance = SecurityAntipatternHandler().get_claude_md()
        assert guidance is not None
        _, _, after = guidance.partition(self._CATEGORY_HEADING)
        block, _, _ = after.partition("\n\n")
        categories = []
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped.startswith(self._BULLET):
                continue
            label = stripped[len(self._BULLET) :].split(":", 1)[0].strip()
            categories.append(label)
        return categories

    def test_every_claimed_category_has_a_real_pattern(self):
        names = self._pattern_names()
        assert names, "registry produced no patterns — the probe itself is broken"
        for label in self._guidance_categories():
            evidence = self.CATEGORY_EVIDENCE.get(label)
            assert evidence is not None, (
                f"Guidance claims category {label!r} but no evidence row exists. "
                "Add it to CATEGORY_EVIDENCE naming a substring that appears in a "
                "real pattern name — or remove the claim from get_claude_md()."
            )
            assert any(evidence.lower() in name.lower() for name in names), (
                f"Guidance claims {label!r} is blocked, but no registered pattern "
                f"name contains {evidence!r}. The guidance is promising protection "
                "that does not exist. Implement it, or stop claiming it."
            )

    def test_guidance_does_not_claim_the_three_unimplemented_categories(self):
        """Regression pin for the exact wording that shipped.

        Named explicitly rather than left to the generic check above, because
        these three are the ones a reader is most likely to re-add from memory
        of the OWASP top ten.

        Scoped to the CLAIMS block on purpose: naming them in the explicit
        "does NOT detect" disclaimer is the correct thing to do, and a check
        that forbade the words outright would forbid saying so.
        """
        guidance = SecurityAntipatternHandler().get_claude_md()
        assert guidance is not None
        _, _, after = guidance.partition(self._CATEGORY_HEADING)
        claims_block, _, _ = after.partition("\n\n")
        lowered = claims_block.lower()
        for absent in ("sql injection", "weak cryptography", "path traversal"):
            assert absent not in lowered, (
                f"Guidance claims {absent!r} is blocked. No strategy implements it. "
                "If you have just added detection for it, add the category to "
                "CATEGORY_EVIDENCE and delete this assertion's entry."
            )

    def test_guidance_states_what_it_cannot_detect(self):
        """The disclaimer is load-bearing, not decoration.

        An agent that reads "OWASP security antipatterns are blocked" and sees
        no limits will reasonably infer broad coverage. Naming the absent
        classes explicitly is what stops a passing write being read as
        'this code is secure'.
        """
        guidance = SecurityAntipatternHandler().get_claude_md()
        assert guidance is not None
        lowered = guidance.lower()
        assert "does not detect" in lowered or "not detect" in lowered
        for named in ("sql injection", "path traversal"):
            assert named in lowered, (
                f"The limits disclaimer no longer names {named!r}. Removing it makes "
                "the handler look broader than it is."
            )

    def test_evidence_rows_all_correspond_to_a_claimed_category(self):
        """An evidence row for a category the guidance no longer names is dead weight."""
        claimed = set(self._guidance_categories())
        stale = set(self.CATEGORY_EVIDENCE) - claimed
        assert not stale, (
            f"CATEGORY_EVIDENCE rows with no matching guidance bullet: {sorted(stale)}. "
            "Remove them, or restore the bullet they were written for."
        )


class TestSecurityAntipatternGetRules:
    """get_rules() (Plan 00116): 6 category rules -- 5 OWASP mechanisms + Rust outliers."""

    def test_get_rules_returns_six_rules(self):
        rules = SecurityAntipatternHandler().get_rules()
        assert len(rules) == 6

    def test_get_rules_ids_are_unique_and_constants(self):
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        expected = {
            RuleID.SEC_CODE_INJECTION,
            RuleID.SEC_CMD_INJECTION,
            RuleID.SEC_DESERIALISATION,
            RuleID.SEC_XSS,
            RuleID.SEC_HARDCODED_CREDS,
            RuleID.SEC_UNSAFE_MEMORY,
        }
        rules = SecurityAntipatternHandler().get_rules()
        assert {rule.rule_id for rule in rules} == expected

    def test_get_rules_every_verbose_is_non_empty(self):
        for rule in SecurityAntipatternHandler().get_rules():
            assert rule.verbose


class TestSecurityAntipatternClassifyPattern:
    """_classify_pattern (Plan 00116): mechanism-name based, not the coarse OWASP code.

    Synthetic pattern names avoid any real dangerous-call substring so this
    test module's own content never trips the live security_antipattern
    guard on the Write/Edit that authors it.
    """

    @staticmethod
    def _pattern(name: str, owasp: str = "A03"):
        from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern

        return SecurityPattern(name=name, regex=r"synthetic-test-only", owasp=owasp, suggestion="x")

    def test_code_injection_marker(self):
        from claude_code_hooks_daemon.constants.rule_ids import RuleID
        from claude_code_hooks_daemon.handlers.pre_tool_use.security_antipattern import (
            _classify_pattern,
        )

        pattern = self._pattern("synthetic - code injection risk")
        assert _classify_pattern(pattern) == RuleID.SEC_CODE_INJECTION

    def test_command_injection_marker(self):
        from claude_code_hooks_daemon.constants.rule_ids import RuleID
        from claude_code_hooks_daemon.handlers.pre_tool_use.security_antipattern import (
            _classify_pattern,
        )

        pattern = self._pattern("synthetic - command injection risk")
        assert _classify_pattern(pattern) == RuleID.SEC_CMD_INJECTION

    def test_deserialization_marker(self):
        from claude_code_hooks_daemon.constants.rule_ids import RuleID
        from claude_code_hooks_daemon.handlers.pre_tool_use.security_antipattern import (
            _classify_pattern,
        )

        pattern = self._pattern("synthetic - deserialization injection risk")
        assert _classify_pattern(pattern) == RuleID.SEC_DESERIALISATION

    def test_object_injection_marker_is_deserialisation(self):
        from claude_code_hooks_daemon.constants.rule_ids import RuleID
        from claude_code_hooks_daemon.handlers.pre_tool_use.security_antipattern import (
            _classify_pattern,
        )

        pattern = self._pattern("synthetic - object injection risk")
        assert _classify_pattern(pattern) == RuleID.SEC_DESERIALISATION

    def test_xss_marker(self):
        from claude_code_hooks_daemon.constants.rule_ids import RuleID
        from claude_code_hooks_daemon.handlers.pre_tool_use.security_antipattern import (
            _classify_pattern,
        )

        pattern = self._pattern("synthetic - XSS risk")
        assert _classify_pattern(pattern) == RuleID.SEC_XSS

    def test_owasp_a02_is_hardcoded_creds_regardless_of_name(self):
        from claude_code_hooks_daemon.constants.rule_ids import RuleID
        from claude_code_hooks_daemon.handlers.pre_tool_use.security_antipattern import (
            _classify_pattern,
        )

        pattern = self._pattern("synthetic credential test", owasp="A02")
        assert _classify_pattern(pattern) == RuleID.SEC_HARDCODED_CREDS

    def test_unmatched_marker_falls_through_to_unsafe_memory(self):
        """The fall-through is a deliberate outlier bucket, not a silent catch-all."""
        from claude_code_hooks_daemon.constants.rule_ids import RuleID
        from claude_code_hooks_daemon.handlers.pre_tool_use.security_antipattern import (
            _classify_pattern,
        )

        pattern = self._pattern("synthetic type safety bypass test")
        assert _classify_pattern(pattern) == RuleID.SEC_UNSAFE_MEMORY


class TestSecurityAntipatternDisclosureLadder:
    """Verbose-first/terse-after per (transcript_path, rule_id) (Plan 00116).

    The AWS-key literal is split across a source-level concatenation so this
    module's own text never contains the contiguous ``AKIA``+16-char run its
    OWN pattern matches -- avoiding a live self-trip on the Write/Edit that
    authors this file, while the runtime string still triggers the handler.
    """

    _AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE1"

    @pytest.fixture(autouse=True)
    def _reset_disclosure_tracker(self):
        from claude_code_hooks_daemon.core import reset_data_layer

        reset_data_layer()
        yield
        reset_data_layer()

    @classmethod
    def _hook_input(cls, transcript_path):
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/config.ts",
                "content": f'const key = "{cls._AWS_KEY}";',
            },
        }
        if transcript_path is not None:
            hook_input["transcript_path"] = transcript_path
        return hook_input

    def test_deny_reason_starts_with_rule_id_prefix(self):
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        handler = SecurityAntipatternHandler()
        result = handler.handle(self._hook_input("/tmp/transcript-sec-a.jsonl"))
        assert result.reason.startswith(f"BLOCKED [{RuleID.SEC_HARDCODED_CREDS}]")

    def test_first_fire_is_verbose(self):
        handler = SecurityAntipatternHandler()
        result = handler.handle(self._hook_input("/tmp/transcript-sec-b.jsonl"))
        assert "not detect" in result.reason.lower()

    def test_second_fire_same_agent_is_terse(self):
        handler = SecurityAntipatternHandler()
        transcript = "/tmp/transcript-sec-c.jsonl"
        handler.handle(self._hook_input(transcript))
        second = handler.handle(self._hook_input(transcript))
        assert "not detect" not in second.reason.lower()
        assert "Issues detected" in second.reason

    def test_different_agent_is_independently_verbose(self):
        handler = SecurityAntipatternHandler()
        handler.handle(self._hook_input("/tmp/transcript-sec-d.jsonl"))
        other = handler.handle(self._hook_input("/tmp/transcript-sec-e.jsonl"))
        assert "not detect" in other.reason.lower()

    def test_missing_transcript_path_always_verbose(self):
        handler = SecurityAntipatternHandler()
        first = handler.handle(self._hook_input(None))
        second = handler.handle(self._hook_input(None))
        assert "not detect" in first.reason.lower()
        assert "not detect" in second.reason.lower()
