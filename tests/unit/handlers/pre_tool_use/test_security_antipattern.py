"""Comprehensive tests for SecurityAntipatternHandler."""

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
                "content": "os.system('ls')",
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
        """handle() reason should say SECURITY ANTIPATTERN BLOCKED."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/config.ts",
                "content": 'const key = "AKIAIOSFODNN7EXAMPLE1";',
            },
        }
        result = handler.handle(hook_input)
        assert "SECURITY ANTIPATTERN BLOCKED" in result.reason

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
