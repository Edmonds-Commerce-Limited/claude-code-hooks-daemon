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

    def test_regex_character_class_is_not_matched(self) -> None:
        """Release v3.55.0 code-review blocker: a POSIX character class is a
        regex, not a path glob — ``fnmatch('vault_pass', '[A-Za-z]*')`` is
        True, so without a literal-residue gate every stem matched."""
        assert self._match("grep -o 'class [A-Za-z]*(x)' file.py") is None

    def test_regex_bracket_quantifier_is_not_matched(self) -> None:
        assert self._match("grep -E '[a-z]+_[0-9]*' src/mod.py") is None

    def test_numeric_class_glob_is_not_matched(self) -> None:
        assert self._match("ls report-[0-9]*.txt") is None

    def test_glob_with_protected_literal_residue_still_matched(self) -> None:
        """The residue gate must not weaken the real case: ``.vault-p*`` has
        literal residue ``.vault-p``, which is a prefix of the stem."""
        assert self._match("cat .vault-p*") is not None

    def test_trailing_wildcard_truncation_of_protected_basename_is_matched(self) -> None:
        """Plan 00272 live-probe gap (G2): a token whose fixed prefix is a
        real filename's stem plus part of the protected SUFFIX (the arbitrary
        prefix belongs to the pattern, e.g. ``*.vault-password``) must still
        be denied — the original stem-vs-token fnmatch missed this because
        the stem has no ``dummy`` prefix to match against."""
        assert self._match("cat dummy.vault-p*") is not None

    def test_shorter_trailing_wildcard_truncation_is_also_matched(self) -> None:
        """A shorter truncation of the same shape must not slip through —
        the fix must not be tuned to one specific truncation length."""
        assert self._match("cat dummy.vault-*") is not None

    def test_very_short_trailing_wildcard_truncation_is_matched(self) -> None:
        """Two-character literal overlap (``.v``) is still enough to deny —
        the minimum overlap threshold is set at 2, not at the full stem."""
        assert self._match("cat dummy.v*") is not None

    def test_single_char_generic_wildcard_is_not_matched(self) -> None:
        """``d*`` cannot overlap any stem by 2+ characters (max possible
        overlap is 1, since the token's literal residue is one character) —
        this is the accepted residual for arbitrarily short generic globs,
        not a special case: the threshold that catches ``dummy.v*`` cannot
        be lowered to 1 without flagging near-universal single-letter globs."""
        assert self._match("ls d*") is None

    def test_unrelated_trailing_wildcard_is_not_matched(self) -> None:
        """Negative control: a genuinely unrelated glob must stay allowed.
        ``dummy.txt`` shares no literal edge with any protected stem."""
        assert self._match("cat dummy.txt*") is None

    def test_leading_wildcard_reverse_overlap_is_matched(self) -> None:
        """A leading-wildcard TOKEN's residue can only overlap a stem in the
        REVERSE direction (stem's suffix vs residue's prefix) — exercises the
        second branch of ``_glob_token_overlaps_stem`` independently of the
        forward-direction case the trailing-wildcard tests already cover.
        Uses ``*vault_pass*`` (a leading-wildcard PATTERN — the overlap check
        is gated to those, see ``test_overlap_never_fires_for_anchored_or_exact_stems``),
        so this is not a synthetic corner case: ``*passXXX`` genuinely shares
        no substring with the stem, only a boundary overlap."""
        assert self._match("cat *passXXX") is not None

    def test_overlap_never_fires_for_anchored_or_exact_stems(self) -> None:
        """Coordinator-reported over-blocking regression: the overlap test
        must be GATED to patterns with a LEADING wildcard (``*.vault-password``,
        ``*.secret*``, ``*vault_pass*``). An exact-filename pattern
        (``id_rsa``/``id_ed25519``) or a pattern anchored at the START
        (``.vault-pass*``) has no arbitrary prefix for a token to hide
        behind, so ANY genuine truncation of those is already a literal
        PREFIX of the stem and is caught by the pre-existing substring+fnmatch
        check — the overlap test contributes nothing there but false
        positives from a coincidental short edge match. Every one of these
        tokens shares a 2+ char edge with the ``id_rsa`` stem purely by
        coincidence and must stay ALLOWED."""
        for token in ("sample*", "grid*", "valid*", "android*", "raid*", "hybrid*"):
            assert self._match(f"cat {token}") is None, token

    def test_prefix_truncation_of_exact_filename_pattern_still_denied(self) -> None:
        """``id_rs*`` is a REAL truncation of the exact-filename pattern
        ``id_rsa`` (residue ``id_rs`` is a literal substring/prefix of the
        stem) — this must keep denying via the untouched substring+fnmatch
        path, independent of the leading-wildcard gate on the overlap test."""
        assert self._match("cat id_rs*") is not None

    def test_short_prefix_of_exact_filename_pattern_still_denied(self) -> None:
        """``id*`` is also a literal prefix of ``id_rsa`` (and of
        ``id_ed25519``) — genuinely denied via the same substring+fnmatch
        path as ``id_rs*``, not the overlap heuristic. This is deliberately
        NOT in the allowed-FP list: unlike ``sample*``/``grid*``/etc. (which
        share only a coincidental short EDGE with the stem), ``id*`` shares
        the stem's own leading substring — exactly the shape the pre-existing
        check exists to catch, and exactly why ``id_rs*`` must also deny."""
        assert self._match("cat id*") is not None

    def test_dot_secret_leading_wildcard_negative_controls(self) -> None:
        """``*.secret*`` is both-ends-wildcard, so the overlap gate applies —
        confirm it does not manufacture new false positives on common tokens
        that merely start with ``.s`` or end with ``et``."""
        for token in ("start*", "reset*", ".ssh*", "market*"):
            assert self._match(f"cat {token}") is None, token

    def test_internal_wildcard_prefix_coincidence_is_not_matched(self) -> None:
        """Regression: a glob token with NO leading wildcard whose literal
        PREFIX coincidentally shares an edge with a stem's SUFFIX must not
        match. ``assert.*x`` shares ``ass`` with the ``vault_pass`` stem
        (``…p·ass``) yet is not a truncation of any vault file — the reverse
        overlap direction is only meaningful for a LEADING-wildcard token,
        where an arbitrary prefix could precede the residue. Observed live:
        ``grep 'assert.*→' file`` was denied as a ``*vault_pass*`` access."""
        assert self._match("grep -n 'assert.*x' file.py") is None

    def test_internal_wildcard_source_glob_is_not_matched(self) -> None:
        """``secret*.py`` starts with the literal ``secret`` (no leading
        wildcard) and is a source-file glob, not a secret — its ``secret``
        prefix coincides with the ``.secret`` stem's suffix but must not match
        ``*.secret*``. Observed live: ``grep secret*.py dir`` was denied."""
        assert self._match("ls src/secret*.py") is None

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

    def test_flag_position_check_uses_effective_patterns(self) -> None:
        """Review finding 1 regression: a project pattern (worst case:
        mode replace) must be visible to the flag-position re-test, or a
        BARE POSITIONAL consumer argument naming it is wrongly exempted."""
        patterns = ("*.mysecretfile",)
        cmd = "ansible-playbook /x/prod.mysecretfile"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS, patterns)

    def test_flag_position_with_effective_patterns_still_exempts_flag_form(self) -> None:
        patterns = ("*.mysecretfile",)
        cmd = "ansible-playbook --vault-password-file /x/prod.mysecretfile site.yml"
        assert sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS, patterns)

    def test_project_extends_consumers_via_config_shape(self) -> None:
        consumers = sfm.merge_allowed_consumers(
            [{"command": "my-deploy-tool", "path_flags": ["--secret-file"]}]
        )
        cmd = "my-deploy-tool --secret-file .vault-pass up"
        assert sfm.is_exempt_invocation(cmd, consumers)


class TestDirectoryContainsProtected:
    """Review finding 2: bounded partial enforcement for dir-rooted search."""

    def test_directory_holding_protected_file_is_flagged(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / ".vault-pass").write_text("x\n")
        matched = sfm.directory_contains_protected(str(tmp_path), sfm.DEFAULT_PROTECTED_PATTERNS)
        assert matched == ".vault-pass*"

    def test_clean_directory_is_not_flagged(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x\n")
        assert (
            sfm.directory_contains_protected(str(tmp_path), sfm.DEFAULT_PROTECTED_PATTERNS) is None
        )

    def test_non_directory_answers_none(self, tmp_path: Path) -> None:
        target = tmp_path / "file.txt"
        target.write_text("x\n")
        assert sfm.directory_contains_protected(str(target), sfm.DEFAULT_PROTECTED_PATTERNS) is None

    def test_cap_stops_the_walk(self, tmp_path: Path) -> None:
        """Over-cap trees are NOT fully checked — the documented residual."""
        for index in range(5):
            (tmp_path / f"file{index}.txt").write_text("x\n")
        (tmp_path / "zzz.vault-password").write_text("x\n")
        result = sfm.directory_contains_protected(
            str(tmp_path), sfm.DEFAULT_PROTECTED_PATTERNS, max_entries=2
        )
        assert result is None


class TestResolveConfiguredPatterns:
    """Plan 00272 Task 4-5: the shared cross-handler pattern resolver."""

    def setup_method(self) -> None:
        sfm.reset_configured_patterns_cache()

    def teardown_method(self) -> None:
        sfm.reset_configured_patterns_cache()

    def test_fails_open_to_defaults_when_uninitialised(self) -> None:
        """No ProjectContext (unit test process) never returns an empty tuple."""
        result = sfm.resolve_configured_patterns()
        assert result == sfm.DEFAULT_PROTECTED_PATTERNS

    def test_result_is_cached_across_calls(self) -> None:
        first = sfm.resolve_configured_patterns()
        second = sfm.resolve_configured_patterns()
        assert first == second

    def test_reset_clears_the_cache(self) -> None:
        sfm.resolve_configured_patterns()
        sfm.reset_configured_patterns_cache()
        # No exception, and still resolves (fail-open) after reset.
        assert sfm.resolve_configured_patterns() == sfm.DEFAULT_PROTECTED_PATTERNS

    def test_failure_before_yaml_is_touched_does_not_raise_nameerror(self) -> None:
        """``config_path()`` raising BEFORE the yaml import is ever reached
        must still be caught -- ``yaml`` is a module-level import, so the
        except tuple's ``yaml.YAMLError`` reference is always bound, even on
        a failure that never gets near yaml parsing."""
        from unittest.mock import patch

        from claude_code_hooks_daemon.core.project_context import ProjectContext

        with (
            patch.object(ProjectContext, "is_initialized", return_value=True),
            patch.object(
                ProjectContext, "config_path", side_effect=RuntimeError("not initialised")
            ),
        ):
            result = sfm.resolve_configured_patterns()
        assert result == sfm.DEFAULT_PROTECTED_PATTERNS

    def test_widened_except_catches_malformed_yaml(self, tmp_path: Path) -> None:
        """A malformed config file must fail OPEN to the shipped defaults.

        ``Config.load`` calls ``yaml.safe_load`` directly and does not catch
        its own parse errors -- the resolver's except clause must.
        """
        from unittest.mock import patch

        from claude_code_hooks_daemon.core.project_context import ProjectContext

        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text("handlers: [this is not: valid: yaml\n")

        with (
            patch.object(ProjectContext, "is_initialized", return_value=True),
            patch.object(ProjectContext, "config_path", return_value=config_path),
        ):
            result = sfm.resolve_configured_patterns()
        assert result == sfm.DEFAULT_PROTECTED_PATTERNS

    def test_widened_except_catches_schema_invalid_config(self, tmp_path: Path) -> None:
        """A schema-invalid config (pydantic ValidationError, a ValueError) fails open."""
        from unittest.mock import patch

        from claude_code_hooks_daemon.core.project_context import ProjectContext

        config_path = tmp_path / "hooks-daemon.yaml"
        # `version` must match `^\\d+\\.\\d+$` -- this value fails schema validation.
        config_path.write_text("version: not-a-version\n")

        with (
            patch.object(ProjectContext, "is_initialized", return_value=True),
            patch.object(ProjectContext, "config_path", return_value=config_path),
        ):
            result = sfm.resolve_configured_patterns()
        assert result == sfm.DEFAULT_PROTECTED_PATTERNS

    def test_reads_a_real_config_with_mode_replace_and_custom_patterns(
        self, tmp_path: Path
    ) -> None:
        """The resolver's try: block -- its only real job -- reads a live config."""
        from unittest.mock import patch

        from claude_code_hooks_daemon.core.project_context import ProjectContext

        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text(
            "version: '2.0'\n"
            "handlers:\n"
            "  pre_tool_use:\n"
            "    secret_file_guard:\n"
            "      options:\n"
            "        mode: replace\n"
            "        protected_paths:\n"
            "          - '*.my-custom-secret-shape'\n"
        )

        with (
            patch.object(ProjectContext, "is_initialized", return_value=True),
            patch.object(ProjectContext, "config_path", return_value=config_path),
        ):
            result = sfm.resolve_configured_patterns()
        assert result == ("*.my-custom-secret-shape",)

    def test_equivalent_to_the_registry_injected_handler(self, tmp_path: Path) -> None:
        """The resolver and the guard's own registry-injected options must agree.

        Two routes reach the SAME effective pattern set: the resolver reads
        the raw config dict directly; the handler receives its options via
        the registry's setattr injection (``registry.py``'s
        ``register_all``). This test proves they compute the identical
        answer for the SAME `mode`/`protected_paths` pair, rather than just
        asserting they can never disagree.
        """
        from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
            SecretFileGuardHandler,
        )

        mode = "replace"
        protected_paths = ["*.my-custom-secret-shape"]

        via_resolver = sfm.resolve_protected_patterns(mode, protected_paths)

        handler = SecretFileGuardHandler()
        handler._mode = mode
        handler._protected_paths = protected_paths
        via_handler = handler._patterns()

        assert via_resolver == via_handler == ("*.my-custom-secret-shape",)
