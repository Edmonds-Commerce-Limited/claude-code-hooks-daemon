"""Tests for SecretFileGuardHandler (Plan 00272).

Deny-by-default read guard over configured protected files: Read/Write/Edit/
NotebookEdit/Grep on a protected path, and any Bash command mentioning one,
are DENIED — except the ``secret-meta`` helper and allowlisted consumers with
the path in flag position. No escape hatch (Decision 3).
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.vault_payloads import vault_file_bytes

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import encrypted_at_rest


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test in this module."""
    reset_data_layer()
    yield
    reset_data_layer()


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

    def test_grep_rooted_at_dir_containing_protected_file_matches(self, tmp_path: Any) -> None:
        """Review finding 2: directory-rooted Grep gets a bounded walk."""
        (tmp_path / ".vault-pass").write_text("x\n")
        handler = _handler()
        assert handler.matches(_hook_input("Grep", {"pattern": "x", "path": str(tmp_path)}))

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

    def test_replace_mode_pattern_denies_bare_positional_consumer_arg(self) -> None:
        """Review finding 1 regression (verified bypass): under mode replace
        the project pattern must reach the flag-position check, so a bare
        positional argument to an allowlisted consumer is DENIED."""
        handler = _handler()
        handler._mode = "replace"
        handler._protected_paths = ["*.mysecretfile"]
        cmd = "ansible-playbook /x/prod.mysecretfile"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_replace_mode_pattern_still_exempts_flag_position(self) -> None:
        handler = _handler()
        handler._mode = "replace"
        handler._protected_paths = ["*.mysecretfile"]
        cmd = "ansible-playbook --vault-password-file /x/prod.mysecretfile site.yml"
        assert not handler.matches(_hook_input("Bash", {"command": cmd}))


class TestBashRouteInterpreterOneLiners:
    """review 6 minor-2: an interpreter one-liner on the BASH route
    (`python3 -c "..."`) gets the SAME item-3 treatment a `.py` FILE's
    content already gets -- a protected path hidden inside a known
    shell-exec call's string literal, not just a bare top-level mention.

    Fixture bodies split the shell-exec CALL SYNTAX itself across separate
    string pieces, matching ``TestShellExecCallLiteralsInOtherLanguages``'s
    own convention -- `security_antipattern` pattern-matches on the exact
    contiguous text on ANY Write/Edit."""

    def test_python_dash_c_os_system_denies(self) -> None:
        handler = _handler()
        cmd = 'python3 -c "import os; os.' + "system('cat .vault-password')\""
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_python_dash_c_ordinary_code_stays_allowed(self) -> None:
        handler = _handler()
        cmd = "python3 -c \"print('hello world, nothing secret here')\""
        assert not handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_ruby_dash_e_backtick_denies(self) -> None:
        handler = _handler()
        cmd = "ruby -e '`cat .vault-password`'"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_perl_dash_e_system_denies(self) -> None:
        handler = _handler()
        cmd = "perl -e '" + "system" + '(\'cat .vault-password\')\''
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_node_dash_e_exec_sync_denies(self) -> None:
        handler = _handler()
        cmd = "node -e \"require('child_process')." + "exec" + "Sync('cat .vault-password')\""
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_php_dash_r_shell_exec_denies(self) -> None:
        handler = _handler()
        cmd = 'php -r "shell_' + "exe" + "c('cat .vault-password');\""
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_python_dash_c_split_string_literal_denies(self) -> None:
        """Proves the NEW mechanism specifically, not the pre-existing
        raw-text mention scan: the protected name is split across two
        ADJACENT Python string literals (`'a' 'b'`), which Python's own
        parser folds into ONE constant at parse time -- the raw bash
        command text never carries the name contiguously, only the
        extracted call's AST-folded literal does."""
        handler = _handler()
        cmd = "python3 -c \"import os; os." + "system('cat .vault-pas' 'sword')\""
        assert handler.matches(_hook_input("Bash", {"command": cmd}))


class TestBashRouteInterpreterOneLinersReview7:
    """Plan 00466 guard-defects review 7 MAJOR-5: the one-liner route is an
    OPTION WALK, not exact-basename/exact-adjacency matching -- versioned
    and absolute interpreters, an interpreter option before the code flag,
    a clustered short flag, `perl -E`, and `node -p`/`--eval`."""

    def test_versioned_python_dash_c_denies(self) -> None:
        handler = _handler()
        cmd = 'python3.12 -c "import os; os.' + "system('cat .vault-password')\""
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_absolute_versioned_python_dash_c_denies(self) -> None:
        handler = _handler()
        cmd = '/usr/bin/python3.11 -c "import os; os.' + "system('cat .vault-password')\""
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_pypy_dash_c_denies(self) -> None:
        handler = _handler()
        cmd = 'pypy3 -c "import os; os.' + "system('cat .vault-password')\""
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_python_option_before_dash_c_denies(self) -> None:
        handler = _handler()
        cmd = 'python3 -I -c "import os; os.' + "system('cat .vault-password')\""
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_python_clustered_dash_capital_s_c_denies(self) -> None:
        handler = _handler()
        cmd = 'python3 -Sc "import os; os.' + "system('cat .vault-password')\""
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_perl_capital_e_backtick_denies(self) -> None:
        handler = _handler()
        cmd = "perl -E 'say `cat .vault-password`'"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_perl_clustered_dash_le_backtick_denies(self) -> None:
        handler = _handler()
        cmd = "perl -le 'print `cat .vault-password`'"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_ruby_clustered_dash_we_backtick_denies(self) -> None:
        handler = _handler()
        cmd = "ruby -we '`cat .vault-password`'"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_node_dash_p_exec_sync_denies(self) -> None:
        handler = _handler()
        cmd = "node -p \"require('child_process')." + "exec" + "Sync('cat .vault-password')\""
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_node_dash_dash_eval_exec_sync_denies(self) -> None:
        handler = _handler()
        cmd = (
            "node --eval \"require('child_process')." + "exec" + "Sync('cat .vault-password')\""
        )
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_unrelated_short_cluster_stays_allowed(self) -> None:
        """Control: a Python flag cluster with no `c` in it must not be
        mistaken for the code flag."""
        handler = _handler()
        cmd = "python3 -Im \"print('hello world')\""
        assert not handler.matches(_hook_input("Bash", {"command": cmd}))


class TestPythonOneLinerMinorFixesReview7:
    """Plan 00466 guard-defects review 7 MINOR-1: `subprocess.getoutput`/
    `getstatusoutput` always run a shell (gated on `shell=True`, which they
    do not take, so they never matched before); an f-string's constant
    parts are collected as a literal even with no placeholder."""

    def test_subprocess_getoutput_denies(self) -> None:
        handler = _handler()
        cmd = (
            'python3 -c "import subprocess; subprocess.getoutput'
            "('cat .vault-password')\""
        )
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_subprocess_getstatusoutput_denies(self) -> None:
        handler = _handler()
        cmd = (
            'python3 -c "import subprocess; subprocess.getstatusoutput'
            "('cat .vault-password')\""
        )
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_fstring_with_no_placeholder_denies(self) -> None:
        handler = _handler()
        cmd = 'python3 -c "import os; os.' + "system(f'cat .vault-password')\""
        assert handler.matches(_hook_input("Bash", {"command": cmd}))


class TestRubyBareSystemReview7:
    """Plan 00466 guard-defects review 7 MINOR-2: Ruby's idiomatic
    paren-free `system 'x'` form."""

    def test_ruby_bare_system_no_paren_denies(self) -> None:
        handler = _handler()
        cmd = "ruby -e \"system 'cat .vault-password'\""
        assert handler.matches(_hook_input("Bash", {"command": cmd}))


class TestShellWordNormalisationThroughTheHandler:
    """n466-n24 review 4, M-1: every listed spelling, end-to-end through the
    real handler, both against shipped defaults (id_rsa) and a
    project-configured EXACT ``protected_paths`` entry (``.env``)."""

    def test_degenerate_brace_sequence_is_denied(self) -> None:
        handler = _handler()
        cmd = "cat id_rs{a..a}"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_double_quote_adjacency_concatenation_is_denied(self) -> None:
        handler = _handler()
        cmd = 'cat id_"rs"a'
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_single_quote_adjacency_concatenation_is_denied(self) -> None:
        handler = _handler()
        cmd = "cat i'd'_rsa"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_brace_alternative_carrying_a_quote_is_denied(self) -> None:
        handler = _handler()
        cmd = "cat id_rs{'a',x}"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_backslash_escape_is_denied(self) -> None:
        handler = _handler()
        cmd = "cat id_rs\\a"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_ansi_c_hex_escape_is_denied(self) -> None:
        handler = _handler()
        cmd = "cat id_rs$'\\x61'"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_dollar_var_unknown_suffix_becomes_a_glob_and_is_denied(self) -> None:
        handler = _handler()
        cmd = "cat id_rs$x"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_command_substitution_naming_the_file_is_denied(self) -> None:
        handler = _handler()
        cmd = "cat ~/.ssh/$(echo id_rsa)"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_double_quoted_var_plus_trailing_glob_is_denied(self) -> None:
        handler = _handler()
        cmd = 'cat "$HOME"/.ssh/id_rs*'
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_an_ordinary_dollar_var_path_is_allowed(self) -> None:
        handler = _handler()
        cmd = "cat $SOME_CONFIG_DIR/readme.txt"
        assert not handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_project_configured_exact_pattern_degenerate_sequence_is_denied(self) -> None:
        handler = _handler()
        handler._mode = "replace"
        handler._protected_paths = [".env"]
        cmd = "cat .en{v..v}"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_project_configured_exact_pattern_quote_removal_is_denied(self) -> None:
        handler = _handler()
        handler._mode = "replace"
        handler._protected_paths = [".env"]
        cmd = 'cat .e"n"v'
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_project_configured_exact_pattern_unresolved_substitution_is_denied(self) -> None:
        handler = _handler()
        handler._mode = "replace"
        handler._protected_paths = [".env"]
        cmd = "cat .en$x"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_project_configured_exact_pattern_unrelated_command_is_allowed(self) -> None:
        handler = _handler()
        handler._mode = "replace"
        handler._protected_paths = [".env"]
        cmd = "cat readme.txt"
        assert not handler.matches(_hook_input("Bash", {"command": cmd}))


class TestBothEdgesTextualIntersectionThroughTheHandler:
    """m-2 (n466-n24 review 4 addendum), end-to-end through the real
    handler: a ``?``-only interior truncation of a both-edges stem denies
    textually, whatever the caller's cwd or the filesystem's current
    contents -- folded into the DP intersection, not the FS-truth route."""

    def test_cd_elsewhere_still_denies_an_interior_question_mark_truncation(self) -> None:
        handler = _handler()
        cmd = "cd /tmp && cat /elsewhere/demo.se?ret"
        hook_input = _hook_input("Bash", {"command": cmd})
        hook_input["cwd"] = "/tmp"
        assert handler.matches(hook_input)

    def test_a_file_created_later_in_the_same_command_still_denies(self) -> None:
        handler = _handler()
        cmd = "echo hi > /tmp/demo.secret && cat /tmp/demo.se?ret"
        hook_input = _hook_input("Bash", {"command": cmd})
        hook_input["cwd"] = "/tmp"
        assert handler.matches(hook_input)

    def test_an_unrelated_star_bearing_token_stays_allowed(self) -> None:
        handler = _handler()
        hook_input = _hook_input("Bash", {"command": "cat report-[0-9]*.txt"})
        hook_input["cwd"] = "/tmp"
        assert not handler.matches(hook_input)


class TestContentContextThroughTheHandler:
    """n466-n24 review 4 addendum, false-positive fold-in, end-to-end: a
    Write/Edit of ordinary Python source that merely LOOKS glob-shaped to
    the crude tokeniser must stay allowed, while a real protected-path
    reference in the same kind of file still denies."""

    def test_python_unpacking_subscript_snippet_is_allowed(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Edit",
            {
                "file_path": "/proj/helper.py",
                "new_string": "combined = [*words[:subcommand_index], extra_word]\n",
            },
        )
        assert not handler.matches(hook_input)
        assert handler.handle(hook_input).decision == Decision.ALLOW

    def test_a_quoted_literal_mention_in_python_still_denies(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {"file_path": "/proj/helper.py", "content": 'x = open(".vault-password")\n'},
        )
        assert handler.matches(hook_input)

    def test_a_shell_script_brace_sequence_mention_still_denies(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Write", {"file_path": "/proj/helper.sh", "content": "cat id_rs{a..a}\n"}
        )
        assert handler.matches(hook_input)

    def test_a_shell_script_interior_wildcard_glob_still_denies(self) -> None:
        """Review 5 MAJOR-2: a `.sh`/`.bash` file's content IS shell text a
        shell will expand when the script runs (`bash deploy.sh`) -- an
        interior-wildcard glob-shaped reference must still deny under the
        AGGRESSIVE (bash-route) heuristics, not fall through to the weaker
        literal-only content matcher a `.py`/`.js` file gets."""
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {"file_path": "/proj/deploy.sh", "content": "#!/bin/bash\ncat prod.vault-pass*\n"},
        )
        assert handler.matches(hook_input)

    def test_a_bash_extension_interior_wildcard_glob_still_denies(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Write", {"file_path": "/proj/deploy.bash", "content": "cat id_rs?\n"}
        )
        assert handler.matches(hook_input)

    def test_a_python_interior_wildcard_string_literal_stays_allowed(self) -> None:
        """Control: the SAME interior-wildcard text stays allowed in a
        non-shell extension, where it is genuinely just source code."""
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {"file_path": "/proj/helper.py", "content": "pattern = 'prod.vault-pass*'\n"},
        )
        assert not handler.matches(hook_input)

    def test_a_makefile_recipe_glob_shaped_mention_denies(self) -> None:
        """Review 5 MAJOR-2 (further scoping): a Makefile recipe line IS
        shell text `make` will expand -- and `_SCRIPT_EXTENSIONS` alone would
        never even scan an extensionless `Makefile` at all."""
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {"file_path": "/proj/Makefile", "content": "deploy:\n\tcat prod.vault-pass*\n"},
        )
        assert handler.matches(hook_input)

    def test_a_dotmk_file_glob_shaped_mention_denies(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Write", {"file_path": "/proj/rules.mk", "content": "cat id_rs?\n"}
        )
        assert handler.matches(hook_input)

    def test_a_github_workflow_run_step_glob_shaped_mention_denies(self) -> None:
        """A CI workflow's `run:` step is shell text the CI runner expands --
        `.yml`/`.yaml` alone is not in `_SCRIPT_EXTENSIONS`, so this also
        widens the initial scan gate, not just the context choice."""
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {
                "file_path": "/proj/.github/workflows/ci.yml",
                "content": "jobs:\n  build:\n    steps:\n      - run: cat id_rs?\n",
            },
        )
        assert handler.matches(hook_input)

    def test_a_gitlab_ci_yaml_glob_shaped_mention_denies(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {"file_path": "/proj/.gitlab-ci.yml", "content": "script:\n  - cat id_rs?\n"},
        )
        assert handler.matches(hook_input)

    def test_an_ordinary_yaml_file_stays_unaffected_by_ci_scanning(self) -> None:
        """Control: a plain YAML config (not a CI workflow path) is not in
        `_SCRIPT_EXTENSIONS` and matches none of the CI markers, so it is not
        scanned at all -- same as before this fix."""
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {"file_path": "/proj/config.yml", "content": "pattern: 'prod.vault-pass*'\n"},
        )
        assert not handler.matches(hook_input)

    def test_an_extensionless_shell_shebang_script_glob_shaped_mention_denies(self) -> None:
        """A shebang alone identifies an extensionless shell script
        (`install`, `configure`) that `_SCRIPT_EXTENSIONS` would otherwise
        never even scan."""
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {"file_path": "/proj/install", "content": "#!/usr/bin/env bash\ncat id_rs?\n"},
        )
        assert handler.matches(hook_input)

    def test_an_extensionless_python_shebang_script_stays_unaffected(self) -> None:
        """Control: a non-shell shebang (`python3`) does not trip shell
        classification, and an extensionless file with no script marker at
        all is not scanned -- same as before this fix."""
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {
                "file_path": "/proj/generate",
                "content": "#!/usr/bin/env python3\npattern = 'prod.vault-pass*'\n",
            },
        )
        assert not handler.matches(hook_input)


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

    def test_reason_names_the_offending_token_in_a_bash_command(self) -> None:
        """Plan 00356: the glob alone does not say WHICH word tripped it, so
        diagnosing a long command meant bisecting it across repeated denials.
        The token is the caller's own input, never file content."""
        handler = _handler()
        result = handler.handle(
            _hook_input("Bash", {"command": "tar -cf out.tar README.md .vault-pass extra.txt"})
        )
        assert result.reason is not None
        assert ".vault-pass" in result.reason
        assert "README.md" not in result.reason

    def test_reason_names_the_offending_token_in_authored_script_content(self) -> None:
        """The case that actually needed it: a whole FILE was scanned, and
        nothing said which of its lines was the problem."""
        handler = _handler()
        result = handler.handle(
            _hook_input(
                "Write",
                {
                    "file_path": "/proj/deploy.sh",
                    "content": "#!/usr/bin/env bash\nset -e\ncat .vault-pass\necho done\n",
                },
            )
        )
        assert result.reason is not None
        assert "token" in result.reason.lower()
        assert ".vault-pass" in result.reason

    def test_read_route_still_does_not_echo_the_path(self) -> None:
        """The token echo is deliberately NOT extended to the read route: a
        directory-rooted Grep reaches it carrying a protected filename the
        bounded walk DISCOVERED, which the caller never typed."""
        handler = _handler()
        result = handler.handle(_hook_input("Read", {"file_path": "/proj/other.vault-password"}))
        assert result.reason is not None
        assert "other.vault-password" not in result.reason

    def test_grep_of_directory_does_not_echo_the_discovered_filename(self, tmp_path: Any) -> None:
        """The disclosure case the scoping exists for: the walk finds a
        protected file the caller did not name, and must not reveal it."""
        (tmp_path / "found-by-the-walk.vault-password").write_text("x\n")
        handler = _handler()
        result = handler.handle(_hook_input("Grep", {"pattern": "x", "path": str(tmp_path)}))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "found-by-the-walk" not in result.reason

    def test_remediation_points_at_explain_handler_not_the_config_file(self) -> None:
        """Plan 00356: a project on shipped defaults has no `protected_paths`
        key, so the config file cannot answer which globs are in force —
        `explain-handler` prints the effective list."""
        handler = _handler()
        result = handler.handle(_hook_input("Read", {"file_path": "/proj/.vault-pass"}))
        assert result.reason is not None
        assert "explain-handler secret_file_guard" in result.reason

    def test_jq_subscript_in_authored_script_is_no_longer_denied(self) -> None:
        """End-to-end regression for the reported defect: an array subscript
        after a one-letter field is an ordinary jq path, not a protected-path
        reference."""
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {
                "file_path": "/proj/bin/collect.sh",
                "content": "#!/usr/bin/env bash\nx=$(jq -r '.foo.v[0]' data.json)\n",
            },
        )
        assert handler.matches(hook_input) is False
        assert handler.handle(hook_input).decision == Decision.ALLOW


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


class TestGetRules:
    """get_rules() declares the 4 Rule objects backing this handler (Plan 00116,
    plus the evaluation-error rule added by Plan 00466 N11)."""

    def test_returns_four_rules(self) -> None:
        rules = _handler().get_rules()
        assert len(rules) == 4
        assert all(isinstance(rule, Rule) for rule in rules)

    def test_rule_ids_match_constants(self) -> None:
        expected = {
            RuleID.SECRET_READ,
            RuleID.SECRET_BASH_MENTION,
            RuleID.SECRET_SCRIPT_AUTHOR,
            RuleID.SECRET_EVALUATION_ERROR,
        }
        actual = {rule.rule_id for rule in _handler().get_rules()}
        assert actual == expected

    def test_every_rule_has_non_empty_verbose(self) -> None:
        for rule in _handler().get_rules():
            assert rule.verbose, f"{rule.rule_id} has empty verbose content"


class TestFailsClosedOnEvaluationError:
    """Plan 00466 N11 (major M4): any exception during evaluation is a DENY,
    structurally -- independent of the daemon's global `strict_mode`.

    N5 fixed the one raise path the coordinator found; this pins the CLASS.
    `matches()`/`handle()` must never propagate an exception at all, since a
    propagated exception is exactly what `core/chain.py`'s non-strict
    default (every client install unless `strict_mode: true`) treats as "no
    match" -- silently disabling this guard for that call, including any
    genuine protected-path mention elsewhere in the same input.
    """

    def test_bash_route_exception_still_denies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic failure injected by the test")

        monkeypatch.setattr(guard_module.sfm, "find_protected_mention_detail", _raise)
        handler = _handler()
        hook_input = _hook_input("Bash", {"command": "echo hello"})

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "RuntimeError" in result.reason
        # n1 (Plan 00466 guard-defects review 2): the exception MESSAGE goes
        # to the log only, never the deny reason -- see
        # TestErrorRouteEchoesOnlyTheExceptionType below.
        assert "synthetic failure injected by the test" not in result.reason

    def test_read_route_exception_still_denies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_args: object, **_kwargs: object) -> bool:
            raise ValueError("synthetic path_is_protected failure")

        monkeypatch.setattr(guard_module.sfm, "path_is_protected", _raise)
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/ordinary.py"})

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "ValueError" in result.reason

    def test_bash_scan_deadline_timeout_still_denies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """B1 (Plan 00466 guard-defects review 2): the mention scan raises
        ``TimeoutError`` when it exceeds the deadline this handler supplies
        (``sfm.SCAN_DEADLINE_SECONDS``) -- a real ``iter_protected_mentions``
        run out of time reaches exactly this same route, since a raise from
        ``find_protected_mention_detail`` is indistinguishable from any
        other evaluation exception to ``_evaluate``'s wrapper."""

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise TimeoutError("secret_file_guard mention scan exceeded its deadline")

        monkeypatch.setattr(guard_module.sfm, "find_protected_mention_detail", _raise)
        handler = _handler()
        hook_input = _hook_input("Bash", {"command": "echo hello"})

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "TimeoutError" in result.reason

    def test_grep_directory_route_exception_still_denies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(guard_module.sfm, "path_is_protected", lambda *_a, **_k: False)

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise OSError("synthetic directory-walk failure")

        monkeypatch.setattr(guard_module.sfm, "directory_contains_protected", _raise)
        handler = _handler()
        hook_input = _hook_input("Grep", {"path": "/proj/some-dir", "pattern": "x"})

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "OSError" in result.reason

    def test_script_content_route_exception_still_denies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic script-content-scan failure")

        monkeypatch.setattr(guard_module.sfm, "find_protected_mention_detail", _raise)
        handler = _handler()
        hook_input = _hook_input(
            "Write", {"file_path": "scripts/x.py", "content": "print('hello')"}
        )

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "RuntimeError" in result.reason

    def test_the_live_nul_byte_path_still_denies(self) -> None:
        """The one raise path the review found still live after N5: a file
        path containing a NUL byte raises `ValueError: embedded null byte`
        out of `os.path.realpath`/`os.path.relpath`. Not exploitable for
        disclosure (no tool can open a NUL path), but the class fix must
        cover it without a dedicated patch."""
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/a\x00b"})

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_an_evaluation_error_denial_uses_its_own_rule_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic")

        monkeypatch.setattr(guard_module.sfm, "find_protected_mention_detail", _raise)
        handler = _handler()
        result = handler.handle(_hook_input("Bash", {"command": "echo hello"}))

        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.SECRET_EVALUATION_ERROR}]")


class TestDispatchKeyMalformedToolInput:
    """M-2 (Plan 00466 review 3): `_dispatch_key` itself was called OUTSIDE
    the fail-closed wrapper -- a malformed `tool_input` (None, a list, a bare
    string, instead of the expected dict) made its `.get()` calls raise
    `AttributeError`, which escaped `matches()`/`handle()` entirely and was
    treated as "no match" by a non-strict chain. This is a regression the m2
    caching fix (Plan 00466 review 2) itself introduced: `_evaluate`'s own
    fail-closed wrapper correctly denies for the SAME malformed payload, but
    `_dispatch_key` sat one line below it, unwrapped.
    """

    @pytest.mark.parametrize("bad_tool_input", [None, [], "not-a-dict"])
    def test_matches_does_not_raise_and_reports_a_match(self, bad_tool_input: object) -> None:
        handler = _handler()
        hook_input = {"tool_name": "Bash", "tool_input": bad_tool_input}

        assert handler.matches(hook_input) is True

    @pytest.mark.parametrize("bad_tool_input", [None, [], "not-a-dict"])
    def test_handle_denies_for_safety(self, bad_tool_input: object) -> None:
        handler = _handler()
        hook_input = {"tool_name": "Bash", "tool_input": bad_tool_input}

        handler.matches(hook_input)
        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY

    @pytest.mark.parametrize("bad_tool_input", [None, [], "not-a-dict"])
    def test_handle_alone_also_denies(self, bad_tool_input: object) -> None:
        """`handle()` called with no preceding `matches()` for the SAME
        input must independently deny too -- the cache miss path
        (`_take_cached_matched`) calls `_dispatch_key` unwrapped as well."""
        handler = _handler()
        hook_input = {"tool_name": "Bash", "tool_input": bad_tool_input}

        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY


class TestChainLevelFailClosedBehaviour:
    """n4 (Plan 00466 guard-defects review 2): every prior N11/m1/m2 test in
    this file calls ``matches()``/``handle()`` directly -- not through
    ``HandlerChain.execute(..., strict_mode=False)``, which is the property
    actually claimed ("this guard fails closed independent of the daemon's
    strict_mode"). That gap is exactly why m1 (an exception in `handle()`'s
    own tail) was not caught by the existing direct-call tests.
    """

    def test_a_handle_tail_exception_still_denies_through_the_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(self: object, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic chain-level failure")

        monkeypatch.setattr(guard_module.RuleFormatter, "verbose", _raise)
        chain = HandlerChain()
        chain.add(_handler())
        hook_input = _hook_input("Read", {"file_path": "/proj/.vault-pass"})

        result = chain.execute(hook_input, strict_mode=False)
        assert result.result.decision == Decision.DENY

    def test_an_evaluation_exception_still_denies_through_the_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic chain-level evaluation failure")

        monkeypatch.setattr(guard_module.sfm, "find_protected_mention_detail", _raise)
        chain = HandlerChain()
        chain.add(_handler())
        hook_input = _hook_input("Bash", {"command": "echo hello"})

        result = chain.execute(hook_input, strict_mode=False)
        assert result.result.decision == Decision.DENY


class TestErrorRouteEchoesOnlyTheExceptionType:
    """n1 (Plan 00466 guard-defects review 2): the deny reason on an
    evaluation-error route must show only the exception TYPE -- the message
    itself goes to the log only (``logger.exception``). Today no raise path
    carries a filename, but Plan 00356's rule is that a name DISCOVERED by
    a directory walk must never be echoed, and an ``OSError`` message from a
    future ``stat`` call could easily carry one.
    """

    def test_the_evaluation_error_route_omits_the_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("a message that must never reach the deny reason")

        monkeypatch.setattr(guard_module.sfm, "find_protected_mention_detail", _raise)
        handler = _handler()
        result = handler.handle(_hook_input("Bash", {"command": "echo hello"}))

        assert result.reason is not None
        assert "RuntimeError" in result.reason
        assert "a message that must never reach the deny reason" not in result.reason

    def test_the_handle_tail_error_route_omits_the_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(self: object, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("a different message that must never reach the deny reason")

        monkeypatch.setattr(guard_module.RuleFormatter, "verbose", _raise)
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/.vault-pass"})
        result = handler.handle(hook_input)

        assert result.reason is not None
        assert "RuntimeError" in result.reason
        assert "a different message that must never reach the deny reason" not in result.reason


class TestMatchesAndHandleShareOneEvaluation:
    """m2 (Plan 00466 guard-defects review 2): ``matches()`` and ``handle()``
    each independently called ``_matched_pattern_and_route`` -- so a
    TRANSIENT raise seen by ``matches()`` (denied, correctly, via the error
    route) could be silently overwritten by a clean re-evaluation inside
    ``handle()``, turning a correct DENY into an ALLOW for a call ``matches()``
    itself already flagged. The two calls must share ONE evaluation per
    dispatch.
    """

    def test_a_transient_raise_seen_by_matches_is_not_erased_by_handle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"count": 0}

        def _flaky(*_args: object, **_kwargs: object) -> tuple[str, str] | None:
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("transient failure, first call only")
            return None  # a clean re-evaluation finds nothing

        monkeypatch.setattr(guard_module.sfm, "find_protected_mention_detail", _flaky)
        handler = _handler()
        hook_input = _hook_input("Bash", {"command": "echo hello"})

        assert handler.matches(hook_input) is True  # error route: matches() saw the raise
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "RuntimeError" in result.reason


class TestHandleTailFailsClosed:
    """m1 (Plan 00466 guard-defects review 2): ``_evaluate``'s fail-closed
    wrapper only covers reaching a VERDICT. Once ``handle()`` has a real
    match it does further work UNWRAPPED -- resolving the disclosure
    tracker, formatting the rule, string-building the message -- and an
    exception there used to propagate straight out of ``handle()``, which a
    non-strict chain (every install unless ``strict_mode: true``, and M3
    found that inert here too) treats as "no match": ALLOW, for a call that
    had a GENUINE protected mention. ``matches()`` already returned True
    for every case below; the only question is whether ``handle()`` denies
    or raises.
    """

    def test_data_layer_lookup_exception_still_denies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise() -> None:
            raise RuntimeError("synthetic get_data_layer failure")

        monkeypatch.setattr(guard_module, "get_data_layer", _raise)
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/.vault-pass"})

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "RuntimeError" in result.reason

    def test_rule_formatter_exception_still_denies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(self: object, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic RuleFormatter.verbose failure")

        monkeypatch.setattr(guard_module.RuleFormatter, "verbose", _raise)
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/.vault-pass"})

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "RuntimeError" in result.reason

    def test_unhashable_transcript_path_still_denies(self) -> None:
        """The review's own concrete case: a list where a string is
        expected (harness-supplied, not agent-controllable, but the fail
        path must hold regardless of how the bad value got there)."""
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/.vault-pass"})
        hook_input["transcript_path"] = ["not", "a", "string"]

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY


class TestDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Decision G)."""

    def _read_with_transcript(self, path: str, transcript_path: str) -> dict[str, Any]:
        hook_input = _hook_input("Read", {"file_path": path})
        hook_input["transcript_path"] = transcript_path
        return hook_input

    def test_first_fire_for_agent_is_verbose(self) -> None:
        handler = _handler()
        hook_input = self._read_with_transcript(
            "/proj/.vault-pass", "/tmp/agent-a/transcript.jsonl"
        )
        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "secret-meta" in result.reason

    def test_second_fire_for_same_agent_same_rule_is_terse(self) -> None:
        handler = _handler()
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._read_with_transcript("/proj/.vault-pass", transcript_path))
        result = handler.handle(
            self._read_with_transcript("/proj/other.vault-password", transcript_path)
        )

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "NO escape hatch" not in result.reason
        assert "other.vault-password" not in result.reason  # only the glob is echoed

    def test_terse_message_leads_with_rule_id(self) -> None:
        handler = _handler()
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._read_with_transcript("/proj/.vault-pass", transcript_path))
        result = handler.handle(self._read_with_transcript("/proj/.vault-pass", transcript_path))

        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.SECRET_READ}]")

    def test_different_route_same_agent_is_independently_verbose(self) -> None:
        handler = _handler()
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._read_with_transcript("/proj/.vault-pass", transcript_path))
        hook_input = _hook_input("Bash", {"command": "cat .vault-pass"})
        hook_input["transcript_path"] = transcript_path
        result = handler.handle(hook_input)

        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.SECRET_BASH_MENTION}]")
        assert "secret-meta" in result.reason

    def test_missing_transcript_path_is_always_verbose(self) -> None:
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/.vault-pass"})
        handler.handle(hook_input)
        result = handler.handle(hook_input)

        assert result.reason is not None
        assert "secret-meta" in result.reason


# ── Plan 00459: a protected file whose content is encrypted at rest ──────────

_VAULT_REL = "group_vars/all/vault_passwords.yml"
_TEMPLATE_REL = "templates/app.secrets"


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Path]:
    """A project root the guard resolves as its own, with an encrypted vars file."""
    root = tmp_path / "project"
    root.mkdir()
    _put(root, _VAULT_REL, vault_file_bytes())
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        yield root


def _put(root: Path, relpath: str, data: bytes) -> Path:
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _decrypt_in_place(root: Path, relpath: str) -> None:
    """What `ansible-vault decrypt` leaves behind: the same path, plaintext."""
    (root / relpath).write_bytes(b"db_password: not-a-real-secret\n")


def _in(root: Path, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return {"tool_name": tool_name, "tool_input": tool_input, "cwd": str(root)}


def _verdict(hook_input: dict[str, Any]) -> Decision:
    handler = _handler()
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


class TestEncryptedFileOnPathTools:
    def test_read_of_encrypted_file_is_allowed(self, project: Path) -> None:
        hook_input = _in(project, "Read", {"file_path": str(project / _VAULT_REL)})
        assert not _handler().matches(hook_input)
        assert _handler().handle(hook_input).decision == Decision.ALLOW

    def test_read_of_the_same_path_decrypted_in_place_is_denied(self, project: Path) -> None:
        hook_input = _in(project, "Read", {"file_path": str(project / _VAULT_REL)})
        assert _verdict(hook_input) == Decision.ALLOW
        _decrypt_in_place(project, _VAULT_REL)
        assert _verdict(hook_input) == Decision.DENY

    def test_encrypted_dot_secrets_template_is_allowed(self, project: Path) -> None:
        _put(project, _TEMPLATE_REL, vault_file_bytes(version="1.2", label="prod"))
        hook_input = _in(project, "Read", {"file_path": str(project / _TEMPLATE_REL)})
        assert _verdict(hook_input) == Decision.ALLOW

    def test_relative_path_resolves_against_cwd(self, project: Path) -> None:
        assert _verdict(_in(project, "Read", {"file_path": _VAULT_REL})) == Decision.ALLOW

    def test_relative_path_without_cwd_is_denied(self, project: Path) -> None:
        assert _verdict(_hook_input("Read", {"file_path": _VAULT_REL})) == Decision.DENY

    def test_edit_and_write_of_encrypted_file_are_allowed(self, project: Path) -> None:
        path = str(project / _VAULT_REL)
        edit = _in(project, "Edit", {"file_path": path, "old_string": "a", "new_string": "b"})
        write = _in(project, "Write", {"file_path": path, "content": "x"})
        assert _verdict(edit) == Decision.ALLOW
        assert _verdict(write) == Decision.ALLOW

    def test_grep_of_encrypted_file_is_allowed(self, project: Path) -> None:
        hook_input = _in(project, "Grep", {"pattern": "x", "path": str(project / _VAULT_REL)})
        assert _verdict(hook_input) == Decision.ALLOW

    def test_grep_rooted_at_a_tree_of_only_encrypted_files_is_allowed(self, project: Path) -> None:
        hook_input = _in(project, "Grep", {"pattern": "x", "path": str(project / "group_vars")})
        assert _verdict(hook_input) == Decision.ALLOW

    def test_grep_rooted_at_a_tree_with_a_plaintext_sibling_is_denied(self, project: Path) -> None:
        _put(project, "group_vars/all/.vault-pass", b"not-a-real-secret\n")
        hook_input = _in(project, "Grep", {"pattern": "x", "path": str(project / "group_vars")})
        assert _verdict(hook_input) == Decision.DENY

    def test_symlink_named_like_a_vault_file_to_a_plaintext_secret_is_denied(
        self, project: Path
    ) -> None:
        plaintext = _put(project, "notes/plain.txt", b"db_password: not-a-real-secret\n")
        link = project / "group_vars/web/vault_passwords.yml"
        link.parent.mkdir(parents=True)
        link.symlink_to(plaintext)
        assert _verdict(_in(project, "Read", {"file_path": str(link)})) == Decision.DENY
        assert _verdict(_in(project, "Bash", {"command": f"cat {link}"})) == Decision.DENY

    def test_file_too_large_to_verify_is_denied(self, project: Path) -> None:
        hook_input = _in(project, "Read", {"file_path": str(project / _VAULT_REL)})
        with patch.object(encrypted_at_rest, "MAX_INSPECTED_BYTES", 16):
            assert _verdict(hook_input) == Decision.DENY

    def test_empty_file_is_denied(self, project: Path) -> None:
        _put(project, _VAULT_REL, b"")
        assert _verdict(_in(project, "Read", {"file_path": _VAULT_REL})) == Decision.DENY
        assert _verdict(_in(project, "Bash", {"command": f"git add {_VAULT_REL}"})) == Decision.DENY

    def test_encrypted_file_outside_the_project_root_is_denied(
        self, tmp_path: Path, project: Path
    ) -> None:
        outside = _put(tmp_path, "elsewhere/vault_passwords.yml", vault_file_bytes())
        assert _verdict(_in(project, "Read", {"file_path": str(outside)})) == Decision.DENY

    def test_plaintext_vault_password_file_is_protected_as_before(self, project: Path) -> None:
        for name in (".vault_pass", ".vault-pass", "vault_pass.txt"):
            _put(project, name, b"not-a-real-secret\n")
            for hook_input in (
                _in(project, "Read", {"file_path": name}),
                _in(project, "Grep", {"pattern": "x", "path": str(project / name)}),
                _in(project, "Bash", {"command": f"cat {name}"}),
                _in(project, "Bash", {"command": f"git add {name}"}),
            ):
                assert _verdict(hook_input) == Decision.DENY, (name, hook_input)


class TestEncryptedFileOnBash:
    def test_git_add_naming_it_is_allowed(self, project: Path) -> None:
        assert _verdict(_in(project, "Bash", {"command": f"git add {_VAULT_REL}"})) == (
            Decision.ALLOW
        )

    def test_git_commit_naming_it_is_allowed(self, project: Path) -> None:
        command = f"git commit -m 'Rotate the database password' -- {_VAULT_REL}"
        assert _verdict(_in(project, "Bash", {"command": command})) == Decision.ALLOW

    def test_git_add_after_decrypting_in_place_is_denied(self, project: Path) -> None:
        hook_input = _in(project, "Bash", {"command": f"git add {_VAULT_REL}"})
        _decrypt_in_place(project, _VAULT_REL)
        handler = _handler()
        assert handler.matches(hook_input)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.SECRET_BASH_MENTION}]")

    def test_glob_covering_the_encrypted_file_and_a_plaintext_sibling_is_denied(
        self, project: Path
    ) -> None:
        _put(project, f"{_VAULT_REL}.bak", b"db_password: not-a-real-secret\n")
        command = "cat group_vars/all/vault_pass*"
        assert _verdict(_in(project, "Bash", {"command": command})) == Decision.DENY

    def test_encrypted_and_plaintext_protected_files_together_are_denied(
        self, project: Path
    ) -> None:
        _put(project, ".vault-pass", b"not-a-real-secret\n")
        command = f"git add {_VAULT_REL} .vault-pass"
        assert _verdict(_in(project, "Bash", {"command": command})) == Decision.DENY

    def test_ansible_vault_view_and_decrypt_stay_denied(self, project: Path) -> None:
        for command in (
            f"ansible-vault view {_VAULT_REL}",
            f"ansible-vault decrypt {_VAULT_REL}",
            f"ansible-vault edit {_VAULT_REL}",
        ):
            assert _verdict(_in(project, "Bash", {"command": command})) == Decision.DENY, command

    def test_commands_that_could_decrypt_via_configured_password_stay_denied(
        self, project: Path
    ) -> None:
        for command in (
            f"ansible localhost -m debug -a var=db_password -e @{_VAULT_REL}",
            f"git diff {_VAULT_REL}",
            f"python3 decrypt.py {_VAULT_REL}",
        ):
            assert _verdict(_in(project, "Bash", {"command": command})) == Decision.DENY, command

    def test_directory_change_before_the_read_is_denied(self, project: Path) -> None:
        command = f"cd inventories/staging && cat {_VAULT_REL}"
        assert _verdict(_in(project, "Bash", {"command": command})) == Decision.DENY

    def test_bash_without_cwd_cannot_resolve_a_relative_mention(self, project: Path) -> None:
        hook_input = _hook_input("Bash", {"command": f"git add {_VAULT_REL}"})
        assert _verdict(hook_input) == Decision.DENY

    def test_existing_consumer_exemption_is_unchanged(self, project: Path) -> None:
        command = "ansible-playbook --vault-password-file .vault-pass site.yml"
        assert _verdict(_in(project, "Bash", {"command": command})) == Decision.ALLOW


class TestEncryptedFileOnScriptAuthoring:
    def test_script_naming_an_encrypted_file_is_still_denied(self, project: Path) -> None:
        """A script runs LATER, by a command that does not name the file, so
        no check can happen at the time of use -- and the file may have been
        decrypted in place by then."""
        hook_input = _in(
            project,
            "Write",
            {"file_path": str(project / "deploy.sh"), "content": f"cat {_VAULT_REL}\n"},
        )
        handler = _handler()
        assert handler.matches(hook_input)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.SECRET_SCRIPT_AUTHOR}]")


class TestEncryptedFileGuidance:
    def test_claude_md_explains_the_encrypted_exemption(self) -> None:
        text = _handler().get_claude_md()
        assert text is not None
        assert "encrypted at rest" in text.lower()
        assert "ansible-vault view|decrypt" in text

    def test_deny_text_explains_the_encrypted_exemption(self) -> None:
        """The three content-policy rules (read/bash/script) all teach the
        encrypted-at-rest exemption. The evaluation-error rule (Plan 00466
        N11) is a different failure mode entirely -- the guard crashed, it
        never reached a content verdict -- so mentioning an exemption that
        was never evaluated would mislead, not help."""
        for rule in _handler().get_rules():
            if rule.rule_id == RuleID.SECRET_EVALUATION_ERROR:
                continue
            assert "encrypted" in rule.verbose.lower(), rule.rule_id


class TestEncryptedFileAcceptanceProbes:
    def _probe(self, title_fragment: str) -> Any:
        matches = [t for t in _handler().get_acceptance_tests() if title_fragment in t.title]
        assert len(matches) == 1, title_fragment
        return matches[0]

    def test_allow_probe_for_an_encrypted_file(self) -> None:
        probe = self._probe("allows naming an encrypted")
        assert probe.expected_decision == Decision.ALLOW
        assert probe.setup_commands
        assert probe.cleanup_commands

    def test_deny_probe_for_the_decrypted_twin(self) -> None:
        probe = self._probe("decrypted in place")
        assert probe.expected_decision == Decision.DENY
        assert probe.setup_commands

    def test_allow_probe_fixture_is_a_confirmed_vault_payload(self, tmp_path: Path) -> None:
        """The printf fixture must decode to what the detector confirms, or the
        ALLOW probe would pass or fail for the wrong reason."""
        probe = self._probe("allows naming an encrypted")
        writes = [cmd for cmd in probe.setup_commands if cmd.startswith("printf '")]
        assert len(writes) == 1
        payload = writes[0].split("'")[1].replace("\\n", "\n")
        target = tmp_path / "fixture.yml"
        target.write_text(payload)
        assert encrypted_at_rest.is_encrypted_at_rest(target, tmp_path)


class TestShellExecCallLiteralsInOtherLanguages:
    """Review 6 item 3: a `.py`/`.rb`/`.php`/`.pl`/`.js`/`.ts` file's OWN
    extension keeps it on the weaker literal-only "content" scan (an
    ordinary string literal must stay allowed) -- but a string handed to a
    KNOWN shell-executing call in that same file is executed by a shell just
    as surely as a `.sh` file's body, so it gets `context="bash"` treatment
    end-to-end through the handler. Each language pairs a deny case with an
    ordinary-literal control that must stay allowed.

    Fixture bodies below assemble the shell-executing CALL SYNTAX itself
    from separate string pieces -- not to hide anything, but because that
    exact contiguous text (e.g. the four characters "exec" immediately
    followed by "(") is what `security_antipattern` pattern-matches on ANY
    Write/Edit, including this test file's own fixture content; the split
    keeps these as ordinary Write payloads the handler that owns this
    behaviour (secret_file_guard) can still see whole once assembled."""

    def test_python_os_system_string_denies(self) -> None:
        handler = _handler()
        call = "os." + "system" + "('cat .vault-password')\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_python_subprocess_shell_true_string_denies(self) -> None:
        handler = _handler()
        call = "subprocess.run('cat .vault-password', shell" + "=True)\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_python_subprocess_shell_list_shape_denies(self) -> None:
        handler = _handler()
        call = 'subprocess.run(["bash", "-c", "cat .vault-password"])\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_python_subprocess_without_shell_true_ordinary_argv_stays_allowed(self) -> None:
        """Control: an ordinary argv list naming no shell interpreter and
        with no shell=True never reaches a shell -- the literal is left to
        the (allowed) literal-only content scan."""
        handler = _handler()
        call = 'subprocess.run(["cat", "prod.vault-pass*"])\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert not handler.matches(hook_input)

    def test_python_ordinary_string_literal_control_stays_allowed(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {"file_path": "/proj/helper.py", "content": "pattern = 'prod.vault-passw*rd'\n"},
        )
        assert not handler.matches(hook_input)

    def test_ruby_backtick_shellout_denies(self) -> None:
        handler = _handler()
        call = "result = `cat .vault-password`\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.rb", "content": call})
        assert handler.matches(hook_input)

    def test_ruby_percent_x_shellout_denies(self) -> None:
        handler = _handler()
        call = "result = %" + "x{cat .vault-password}\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.rb", "content": call})
        assert handler.matches(hook_input)

    def test_ruby_system_call_denies(self) -> None:
        handler = _handler()
        call = "system" + "('cat .vault-password')\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.rb", "content": call})
        assert handler.matches(hook_input)

    def test_ruby_ordinary_string_literal_control_stays_allowed(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {"file_path": "/proj/helper.rb", "content": "pattern = 'prod.vault-passw*rd'\n"},
        )
        assert not handler.matches(hook_input)

    def test_php_shell_exec_denies(self) -> None:
        handler = _handler()
        call = "<?php\n$x = shell_" + "exe" + "c('cat .vault-password');\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.php", "content": call})
        assert handler.matches(hook_input)

    def test_php_backtick_shellout_denies(self) -> None:
        handler = _handler()
        call = "<?php\n$x = `cat .vault-password`;\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.php", "content": call})
        assert handler.matches(hook_input)

    def test_php_ordinary_string_literal_control_stays_allowed(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {
                "file_path": "/proj/helper.php",
                "content": "<?php\n$pattern = 'prod.vault-passw*rd';\n",
            },
        )
        assert not handler.matches(hook_input)

    def test_perl_backtick_shellout_denies(self) -> None:
        handler = _handler()
        call = "my $x = `cat .vault-password`;\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.pl", "content": call})
        assert handler.matches(hook_input)

    def test_perl_qx_shellout_denies(self) -> None:
        handler = _handler()
        call = "my $x = q" + "x{cat .vault-password};\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.pl", "content": call})
        assert handler.matches(hook_input)

    def test_perl_system_call_denies(self) -> None:
        handler = _handler()
        call = "system" + "('cat .vault-password');\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.pl", "content": call})
        assert handler.matches(hook_input)

    def test_perl_ordinary_string_literal_control_stays_allowed(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {"file_path": "/proj/helper.pl", "content": "my $pattern = 'prod.vault-passw*rd';\n"},
        )
        assert not handler.matches(hook_input)

    def test_node_exec_sync_denies(self) -> None:
        handler = _handler()
        call = "exec" + "Sync('cat .vault-password');\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.js", "content": call})
        assert handler.matches(hook_input)

    def test_node_child_process_exec_denies(self) -> None:
        handler = _handler()
        call = "child_process." + "exe" + "c('cat .vault-password');\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.ts", "content": call})
        assert handler.matches(hook_input)

    def test_node_ordinary_string_literal_control_stays_allowed(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {
                "file_path": "/proj/helper.js",
                "content": "const pattern = 'prod.vault-passw*rd';\n",
            },
        )
        assert not handler.matches(hook_input)


class TestPythonAstShellExecLiterals:
    """review 6 minor-2: the Python route uses the `ast` module -- from
    imports and aliases, `shell=True` with any spacing, absolute
    interpreter paths, `asyncio.create_subprocess_shell`,
    `os.exec*`/`os.spawn*`, and `pty.spawn`. Fixture bodies split
    shell-exec CALL SYNTAX across pieces per this file's own convention."""

    def test_from_import_alias_denies(self) -> None:
        handler = _handler()
        call = "from os import " + "system" + " as s\ns('cat .vault-password')\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_module_import_alias_denies(self) -> None:
        handler = _handler()
        call = (
            "import subprocess as sp\nsp.run('cat .vault-password', shell"
            + "=True)\n"
        )
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_shell_true_with_unusual_spacing_denies(self) -> None:
        handler = _handler()
        call = "subprocess.run('cat .vault-password',    shell   " + "=   True)\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_absolute_interpreter_path_in_argv_list_denies(self) -> None:
        handler = _handler()
        call = 'subprocess.run(["/bin/bash", "-c", "cat .vault-password"])\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_asyncio_create_subprocess_shell_denies(self) -> None:
        handler = _handler()
        call = "await asyncio.create_subprocess_shell('cat .vault-password')\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_os_execv_denies(self) -> None:
        handler = _handler()
        call = 'os.execv("/bin/sh", ["/bin/sh", "-c", "cat .vault-password"])\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_os_spawnl_denies(self) -> None:
        handler = _handler()
        call = 'os.spawnl(os.P_WAIT, "/bin/sh", "sh", "-c", "cat .vault-password")\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_pty_spawn_denies(self) -> None:
        handler = _handler()
        call = "import pty\npty.spawn(['sh', '-c', 'cat .vault-password'])\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_unparseable_fragment_falls_back_to_the_regex_heuristic(self) -> None:
        """A fragment neither the dedent nor the function-wrap recovery
        can parse (an unterminated string) genuinely falls all the way
        through to the regex heuristic -- the floor, not a silent miss."""
        handler = _handler()
        call = "    os." + "system('cat .vault-password\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_uniformly_indented_fragment_is_recovered_by_dedent(self) -> None:
        """Review 7 (read-only finding): the Edit route scans `new_string`,
        which is routinely indented relative to its real surrounding file
        -- `ast.parse` rejects that outright (`IndentationError`). Proven
        with a shape the WEAKER regex fallback cannot catch (an adjacent
        string-literal split Python folds at parse time), so this can only
        pass via the AST path."""
        handler = _handler()
        call = "    os." + "system('cat .vault-pas' 'sword')\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_non_uniformly_indented_fragment_is_recovered_by_function_wrap(self) -> None:
        """A fragment with its OWN internal indentation (a nested `if`)
        cannot be fixed by `dedent` alone -- it still needs a syntactically
        valid indented block to sit inside, which wrapping in a synthetic
        function body provides. Proven the same way, via the AST-only
        split-literal shape."""
        handler = _handler()
        call = (
            "    if True:\n"
            "        os." + "system('cat .vault-pas' 'sword')\n"
        )
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)


class TestPythonRegexFallbackEquivalence:
    """Plan 00466 guard-defects review 7 follow-up (team-lead): the regex
    fallback (reached only when ast.parse genuinely cannot handle the
    content, even after dedent/function-wrap recovery -- e.g. a real
    UNTERMINATED string elsewhere in the fragment) must recognise the SAME
    shapes the AST path does: an import alias, `shell=True` regardless of
    spacing, and the always-shell subprocess functions
    (getoutput/getstatusoutput).

    Every fixture below pairs a genuinely unparseable fragment (a real
    unterminated string on a LATER line) with a complete, well-formed call
    earlier in the same content -- proving the regex path specifically,
    since the AST path can never reach it here. The call's argument is a
    GLOB-shaped literal (`prod.vault-pass*`), never a bare exact pattern
    name -- an exact name like `.vault-password` denies on its OWN as a
    plain string literal via the ordinary content scan, regardless of
    whether shell-exec-call detection (alias/`shell=True`) ever fires, so
    it cannot isolate what these tests are for. A glob-shaped literal only
    denies once it reaches ``context="bash"`` treatment, which happens
    ONLY through the shell-exec-call route -- the SAME discriminator
    ``TestShellExecCallLiteralsInOtherLanguages``'s own control tests use."""

    def test_import_alias_is_resolved_by_the_regex_fallback(self) -> None:
        call = (
            "from os import " + "system" + " as s\n"
            "s('cat prod.vault-pass*')\n"
            "broken = 'unterminated\n"
        )
        handler = _handler()
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_module_alias_is_resolved_by_the_regex_fallback(self) -> None:
        call = (
            "import subprocess as sp\n"
            "sp.run('cat prod.vault-pass*', shell" + "=True)\n"
            "broken = 'unterminated\n"
        )
        handler = _handler()
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_unusually_spaced_shell_true_is_recognised_by_the_regex_fallback(self) -> None:
        call = (
            "subprocess.run('cat prod.vault-pass*',    shell   " + "=   True)\n"
            "broken = 'unterminated\n"
        )
        handler = _handler()
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_getoutput_with_no_shell_true_is_recognised_by_the_regex_fallback(self) -> None:
        call = (
            "subprocess.getoutput('cat prod.vault-pass*')\n"
            "broken = 'unterminated\n"
        )
        handler = _handler()
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_getstatusoutput_with_no_shell_true_is_recognised_by_the_regex_fallback(
        self,
    ) -> None:
        call = (
            "subprocess.getstatusoutput('cat prod.vault-pass*')\n"
            "broken = 'unterminated\n"
        )
        handler = _handler()
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert handler.matches(hook_input)

    def test_ordinary_argv_with_no_shell_true_stays_allowed_via_the_regex_fallback(
        self,
    ) -> None:
        """Control: an ordinary argv-list call naming no shell interpreter
        and with no shell=True must still be left to the (allowed)
        literal-only content scan, via the regex fallback too."""
        call = (
            'subprocess.run(["cat", "prod.vault-pass*"])\n'
            "broken = 'unterminated\n"
        )
        handler = _handler()
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.py", "content": call})
        assert not handler.matches(hook_input)

    def test_this_fixture_genuinely_reaches_the_regex_fallback(self) -> None:
        """Proves the premise every test above relies on: the fixture
        shape really is unparseable even after dedent/function-wrap
        recovery, so the AST path is never the one answering."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
            _python_shell_exec_literals_ast,
        )

        call = "subprocess.getoutput('cat .vault-password')\nbroken = 'unterminated\n"
        assert _python_shell_exec_literals_ast(call) is None


class TestBroadenedRubyPhpNodeShellExecLiterals:
    """review 6 minor-2: Open3 and IO.popen for Ruby, proc_open for PHP,
    and Node's `spawn` with a shell option."""

    def test_ruby_open3_capture2e_denies(self) -> None:
        handler = _handler()
        call = "require 'open3'\nOpen3.capture2e('cat .vault-password')\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.rb", "content": call})
        assert handler.matches(hook_input)

    def test_ruby_io_popen_denies(self) -> None:
        handler = _handler()
        call = "IO." + "popen('cat .vault-password')\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.rb", "content": call})
        assert handler.matches(hook_input)

    def test_php_proc_open_denies(self) -> None:
        handler = _handler()
        call = "<?php\nproc_" + "open('cat .vault-password', [], $p);\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.php", "content": call})
        assert handler.matches(hook_input)

    def test_node_spawn_with_shell_option_denies(self) -> None:
        handler = _handler()
        call = "spawn('cat .vault-password', [], {shel" + "l: true});\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.js", "content": call})
        assert handler.matches(hook_input)

    def test_node_spawn_without_shell_option_stays_allowed(self) -> None:
        """Control: `spawn` with an ordinary argv list and no shell option
        never reaches a shell -- left to the (allowed) literal-only scan."""
        handler = _handler()
        call = "spawn('cat', ['prod.vault-pass*']);\n"
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.js", "content": call})
        assert not handler.matches(hook_input)


class TestGoRustJavaShellExecLiterals:
    """review 6 minor-2: `exec.Command(sh, -c, ...)` (Go),
    `Command::new("sh").arg("-c")` (Rust), and `Runtime.exec`/
    `ProcessBuilder` with `sh -c` (Java)."""

    def test_go_exec_command_sh_dash_c_denies(self) -> None:
        handler = _handler()
        call = "exe" + 'c.Command("sh", "-c", "cat .vault-password")\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.go", "content": call})
        assert handler.matches(hook_input)

    def test_go_exec_command_ordinary_argv_stays_allowed(self) -> None:
        handler = _handler()
        call = "exe" + 'c.Command("cat", "prod.vault-pass*")\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.go", "content": call})
        assert not handler.matches(hook_input)

    def test_rust_command_new_sh_dash_c_denies(self) -> None:
        handler = _handler()
        call = 'Command::new("sh").arg("-c").arg("cat .vault-password");\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.rs", "content": call})
        assert handler.matches(hook_input)

    def test_rust_command_new_ordinary_argv_stays_allowed(self) -> None:
        handler = _handler()
        call = 'Command::new("cat").arg("prod.vault-pass*");\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.rs", "content": call})
        assert not handler.matches(hook_input)

    def test_java_runtime_exec_denies(self) -> None:
        handler = _handler()
        call = "Runtime.getRuntime()." + "exe" + 'c("cat .vault-password");\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.java", "content": call})
        assert handler.matches(hook_input)

    def test_java_process_builder_sh_dash_c_denies(self) -> None:
        handler = _handler()
        call = 'new ProcessBuilder("sh", "-c", "cat .vault-password");\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.java", "content": call})
        assert handler.matches(hook_input)

    def test_java_process_builder_ordinary_argv_stays_allowed(self) -> None:
        handler = _handler()
        call = 'new ProcessBuilder("cat", "prod.vault-pass*");\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.java", "content": call})
        assert not handler.matches(hook_input)


class TestGoRustJavaAbsolutePathInterpretersReview7:
    """Plan 00466 guard-defects review 7 (read-only finding): the
    Go/Rust/Java first-literal shell-exec check compared the raw string
    to a bare shell name with no basename strip, unlike the Python path,
    so an ABSOLUTE interpreter path (`/usr/bin/bash`) was invisible.
    Every deny case here uses a GLOB-shaped literal (`prod.vault-pass*`),
    never the bare exact pattern name -- an exact name denies on its own
    via the plain content scan regardless of call-context recognition, so
    it cannot isolate the fix these tests are for (the same discriminator
    the other controls in this class already use)."""

    def test_go_exec_command_absolute_bash_path_denies(self) -> None:
        handler = _handler()
        call = "exe" + 'c.Command("/usr/bin/bash", "-c", "cat prod.vault-pass*")\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.go", "content": call})
        assert handler.matches(hook_input)

    def test_rust_command_new_absolute_bash_path_denies(self) -> None:
        handler = _handler()
        call = 'Command::new("/usr/bin/bash").arg("-c").arg("cat prod.vault-pass*");\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.rs", "content": call})
        assert handler.matches(hook_input)

    def test_java_process_builder_absolute_bash_path_denies(self) -> None:
        handler = _handler()
        call = 'new ProcessBuilder("/usr/bin/bash", "-c", "cat prod.vault-pass*");\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.java", "content": call})
        assert handler.matches(hook_input)

    def test_go_exec_command_absolute_non_shell_path_stays_allowed(self) -> None:
        """Control: an absolute path to an ORDINARY (non-shell) binary
        must not be mistaken for an interpreter."""
        handler = _handler()
        call = "exe" + 'c.Command("/usr/bin/cat", "prod.vault-pass*")\n'
        hook_input = _hook_input("Write", {"file_path": "/proj/helper.go", "content": call})
        assert not handler.matches(hook_input)


class TestFileSchemeUrlOnBashRoute:
    """review 7: a `file:` URL is a real, literal local-file read route --
    curl, wget, and anything else accepting a URL argument."""

    def test_curl_percent_encoded_denies(self) -> None:
        handler = _handler()
        cmd = "curl -s file:///root/.ssh/id_r%73a"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_wget_denies(self) -> None:
        handler = _handler()
        cmd = "wget file:///root/.ssh/id_rsa"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_file_url_localhost_denies(self) -> None:
        handler = _handler()
        cmd = "curl file://localhost/root/.ssh/id_rsa"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_file_url_to_non_protected_path_stays_allowed(self) -> None:
        handler = _handler()
        cmd = "curl -s file:///etc/hostname"
        assert not handler.matches(_hook_input("Bash", {"command": cmd}))
