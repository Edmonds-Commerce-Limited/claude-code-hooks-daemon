"""Tests for utils/secret_file_matching.py (Plan 00272).

The matching core behind the secret_file_guard handler: protected-path glob
resolution (additive/replace modes), path matching (including symlink
realpath), and Bash path-mention detection with its two narrow exemptions
(the ``secret-meta`` helper; allowlisted consumers with the path in flag
position).
"""

from pathlib import Path

from claude_code_hooks_daemon.utils import secret_file_matching as sfm


class TestResolveProtectedPatterns:
    def test_defaults_include_dot_secret_pattern(self) -> None:
        """User directive: any filename containing '.secret' is protected by default."""
        assert "*.secret*" in sfm.DEFAULT_PROTECTED_PATTERNS

    def test_defaults_include_vault_password_shapes(self) -> None:
        assert ".vault-pass*" in sfm.DEFAULT_PROTECTED_PATTERNS
        assert "*vault_pass*" in sfm.DEFAULT_PROTECTED_PATTERNS

    def test_additive_mode_merges_project_patterns_onto_defaults(self) -> None:
        patterns = sfm.resolve_protected_patterns(
            mode=sfm.MODE_ADDITIVE, project_patterns=["secrets/prod-token"]
        )
        assert "secrets/prod-token" in patterns
        assert "*.secret*" in patterns

    def test_additive_is_the_default_mode(self) -> None:
        patterns = sfm.resolve_protected_patterns(mode=None, project_patterns=None)
        assert list(patterns) == list(sfm.DEFAULT_PROTECTED_PATTERNS)

    def test_replace_mode_discards_defaults(self) -> None:
        patterns = sfm.resolve_protected_patterns(
            mode=sfm.MODE_REPLACE, project_patterns=["only/this"]
        )
        assert list(patterns) == ["only/this"]

    def test_unknown_mode_behaves_as_additive(self) -> None:
        """Fail closed toward MORE protection (command_hints precedent)."""
        patterns = sfm.resolve_protected_patterns(mode="bogus", project_patterns=["x"])
        assert "*.secret*" in patterns
        assert "x" in patterns

    def test_duplicates_are_removed(self) -> None:
        patterns = sfm.resolve_protected_patterns(
            mode=sfm.MODE_ADDITIVE, project_patterns=["*.secret*"]
        )
        assert list(patterns).count("*.secret*") == 1


class TestPathIsProtected:
    def test_block_words_secret_matches_default(self) -> None:
        assert sfm.path_is_protected(
            "/proj/.claude/block-words.secret", sfm.DEFAULT_PROTECTED_PATTERNS
        )

    def test_dot_secret_anywhere_in_name_matches(self) -> None:
        assert sfm.path_is_protected("/proj/foo.secret.yaml", sfm.DEFAULT_PROTECTED_PATTERNS)

    def test_vault_pass_file_matches(self) -> None:
        assert sfm.path_is_protected("/proj/.vault-pass", sfm.DEFAULT_PROTECTED_PATTERNS)

    def test_ordinary_file_does_not_match(self) -> None:
        assert not sfm.path_is_protected("/proj/src/main.py", sfm.DEFAULT_PROTECTED_PATTERNS)

    def test_symlink_to_protected_target_matches(self, tmp_path: Path) -> None:
        """worktree_create seeds block-words.secret as a symlink — the LINK
        path may be innocuous, so the realpath must be checked too."""
        target = tmp_path / "real.vault-password"
        target.write_text("x\n")
        link = tmp_path / "innocuous-name"
        link.symlink_to(target)
        assert sfm.path_is_protected(str(link), sfm.DEFAULT_PROTECTED_PATTERNS)


class TestBashMentionsProtectedPath:
    PATTERNS = sfm.DEFAULT_PROTECTED_PATTERNS

    def _match(self, command: str) -> str | None:
        return sfm.find_protected_mention(command, self.PATTERNS)

    def test_cat_of_protected_path_is_matched(self) -> None:
        assert self._match("cat .vault-pass") is not None

    def test_absolute_spelling_is_matched(self) -> None:
        assert self._match("head -c 100 /proj/.claude/block-words.secret") is not None

    def test_interpreter_one_liner_is_matched(self) -> None:
        cmd = "python3 -c \"print(open('.vault-pass').read())\""
        assert self._match(cmd) is not None

    def test_redirection_source_is_matched(self) -> None:
        assert self._match("tr -d '\\n' < .vault-pass") is not None

    def test_command_substitution_is_matched(self) -> None:
        assert self._match('echo "$(cat .vault-pass)"') is not None

    def test_variable_assignment_in_same_invocation_is_matched(self) -> None:
        assert self._match('P=.vault-pass; cat "$P"') is not None

    def test_copy_relocation_is_matched(self) -> None:
        assert self._match("cp .claude/block-words.secret /tmp/out") is not None

    def test_tilde_prefix_is_matched(self) -> None:
        assert self._match("cat ~/.vault-pass") is not None

    def test_home_variable_prefix_is_matched(self) -> None:
        assert self._match('cat "$HOME/.vault-pass"') is not None

    def test_glob_shaped_mention_is_matched(self) -> None:
        """A glob token that could expand to a protected name is matched."""
        assert self._match("cat .vault-p*") is not None

    def test_no_echo_exemption(self) -> None:
        """Decision 9(c): unlike sed_blocker, echo buys no exemption."""
        assert self._match('echo ".vault-pass"') is not None

    def test_clean_command_is_not_matched(self) -> None:
        assert self._match("git status && ls -la src/") is None

    def test_prose_word_secret_alone_is_not_matched(self) -> None:
        assert self._match("echo keep secrets out of context") is None

    def test_match_names_the_pattern(self) -> None:
        matched = self._match("cat .vault-pass")
        assert matched in self.PATTERNS


class TestExemptions:
    PATTERNS = sfm.DEFAULT_PROTECTED_PATTERNS

    def test_secret_meta_helper_is_exempt(self) -> None:
        cmd = "bin/hooks-daemon secret-meta .vault-pass"
        assert sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_absolute_wrapper_secret_meta_is_exempt(self) -> None:
        cmd = "/proj/bin/hooks-daemon secret-meta .claude/block-words.secret"
        assert sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_ansible_playbook_with_vault_password_flag_is_exempt(self) -> None:
        cmd = "ansible-playbook --vault-password-file .vault-pass site.yml"
        assert sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_ansible_vault_encrypt_is_exempt(self) -> None:
        cmd = "ansible-vault encrypt --vault-password-file .vault-pass secrets.yml"
        assert sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_ansible_vault_view_is_never_exempt(self) -> None:
        """Draft-review finding 3: view/decrypt exist to PRINT secret material."""
        cmd = "ansible-vault view --vault-password-file .vault-pass secrets.yml"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_ansible_vault_decrypt_is_never_exempt(self) -> None:
        cmd = "ansible-vault decrypt --vault-password-file .vault-pass secrets.yml"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_process_substitution_defeats_consumer_exemption(self) -> None:
        """`<(cat f)` hands content to the outer command — never flag position."""
        cmd = "ansible-playbook --vault-password-file <(cat .vault-pass) site.yml"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_cat_is_not_an_allowed_consumer(self) -> None:
        assert not sfm.is_exempt_invocation("cat .vault-pass", sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_compound_command_with_reader_is_not_exempt(self) -> None:
        cmd = "ansible-playbook --vault-password-file .vault-pass s.yml; cat .vault-pass"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_project_extends_consumers_via_config_shape(self) -> None:
        consumers = sfm.merge_allowed_consumers(
            [{"command": "my-deploy-tool", "path_flags": ["--secret-file"]}]
        )
        cmd = "my-deploy-tool --secret-file .vault-pass up"
        assert sfm.is_exempt_invocation(cmd, consumers)
