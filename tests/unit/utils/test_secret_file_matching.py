"""Tests for utils/secret_file_matching.py (Plan 00272).

The matching core behind the secret_file_guard handler: protected-path glob
resolution (additive/replace modes), path matching (including symlink
realpath), and Bash path-mention detection with its two narrow exemptions
(the ``secret-meta`` helper; allowlisted consumers with the path in flag
position).
"""

import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import secret_file_matching as sfm

#: Wall-clock ceiling for the wide-range tests below. The rejected path does
#: no allocation at all, so it costs microseconds; a range materialised before
#: the cap saw it cost 650 ms for ONE token and 13.5 s for twenty. Two orders
#: of magnitude of headroom keeps this from turning into a timing flake while
#: still failing loudly on a re-materialising regression.
_WIDE_RANGE_BUDGET_SECONDS = 0.05

#: The whole code-point space as a LITERAL range, the shape the probe in
#: Plan 00364's review measured. A Python escape sequence would not do: it
#: tokenises as ordinary backslash text and never reaches the range branch.
_WIDEST_POSSIBLE_RANGE = f"[{chr(0)}-{chr(0x10FFFF)}]"


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

    def test_posix_literal_bracket_first_class_is_glob_shaped(self) -> None:
        """Plan 00306 Task 2.3: the POSIX "literal ``]`` first" character
        class shape (``x[]]``, matching a literal ``]``) must be recognised
        as a COMPLETE bracket expression, same as an ordinary
        ``[A-Za-z]`` class -- the leading ``]`` right after ``[`` (optionally
        after a ``!`` negation) is a member of the class, not its closer."""
        assert sfm._is_glob_shaped("x[]]") is True
        assert sfm._has_trailing_wildcard("x[]]") is True
        assert sfm._is_glob_shaped("x[!]]") is True

    def test_bracket_subscript_adjacent_code_is_not_matched(self) -> None:
        """Regression (peer-reported): a code token like ``words[0].rsplit``
        strips its ``[0]`` bracket expression to residue ``words.rsplit``,
        which shares the 4-char ``word`` edge with the ``.vault-password``
        stem. The subscript is a Python index, not a leading/trailing glob
        wildcard, so the overlap gate must not fire — the wildcard-position
        gate rejects it because neither token edge carries a wildcard."""
        assert self._match("x = words[0].rsplit(y)") is None
        assert self._match("a = parts[0].split(z)") is None

    def test_leading_wildcard_python_splat_operator_is_not_matched(self) -> None:
        """Regression (N4, Plan 00466): a Python unpacking/splat ``*`` glued
        to an identifier is not a shell glob wildcard, but the leading-
        wildcard reverse-overlap branch of ``_glob_token_overlaps_stem``
        cannot tell the difference. The reported Edit added ``rest =
        [words[0], *words[position + 1 :]]`` -- the space before the
        colon splits the slice into its own token, leaving ``*words[position``
        to stand alone. Stripped of its ``*``/``[`` glob chars the residue is
        ``wordsposition``, whose ``word`` PREFIX coincidentally overlaps the
        ``.vault-password`` stem's ``word`` SUFFIX (``pass-word``) by 4
        characters -- past the 2-char minimum. The pattern ``*.vault-password``
        has NO trailing wildcard, so nothing on the pattern side can absorb
        the residue's leftover ``sposition`` -- a genuine truncation would
        need the token's ENTIRE residue to be a literal suffix of the stem,
        not a boundary coincidence. The plain (bracket-free) unpacking shape
        reproduces the same false match."""
        assert self._match("rest = [words[0], *words[position + 1 :]]") is None
        assert self._match("def f(*wordlist): pass") is None
        assert self._match("call(*wordlist)") is None

    def test_leading_wildcard_full_suffix_of_anchored_stem_still_matched(self) -> None:
        """The fix above must not blunt a REAL truncation of an anchored
        (no-trailing-wildcard) pattern: a token whose ENTIRE residue is a
        literal suffix of the stem still glob-expands to the protected file
        and must stay denied -- these already pass via the pre-existing
        substring+fnmatch check, so this pins that the gate change leaves it
        alone."""
        assert self._match("cat *password") is not None
        assert self._match("cat *ult-password") is not None

    def test_python_list_literal_is_not_matched(self) -> None:
        """Regression (Plan 00305 Task 2.5, clippy-shim-fix agent report): an
        Edit whose added content was the literal Python list
        ``[pass_result, fail_result]`` was denied as matching the
        ``*vault_pass*`` protected glob. The comma splits it into tokens
        ``[pass_result`` and ``fail_result]`` — the unmatched ``[``/``]`` are
        Python list syntax, not a real fnmatch bracket expression, so the
        token must never be treated as glob-shaped, and ``pass_result``'s
        ``pass`` edge must never be compared against the ``vault_pass``
        stem."""
        assert self._match("result = [pass_result, fail_result]") is None

    def test_regex_non_greedy_quantifier_is_not_matched(self) -> None:
        """Plan 00284 live dogfooding find: ``<`` and ``>`` are token
        delimiters, so an HTML/XML-shaped regex like ``<a>.*?</a>`` isolates
        a bare ``.*?`` token — an ordinary non-greedy quantifier. Its
        literal residue after stripping glob chars is a single ``.``,
        trivially found inside every dot-leading stem (``.secret``,
        ``.vault-pass``, ``.vault-password``). Used AS the fnmatch pattern,
        ``.*?`` then matches any of them (``.`` literal, ``*`` absorbs the
        middle, ``?`` absorbs one trailing char), even though nothing here
        names a protected file. The residue must clear the same
        minimum-length floor the overlap check already uses before a
        stem-fnmatch counts as a genuine truncation."""
        assert self._match('_RE = re.compile(r"<a>.*?</a>")') is None
        assert self._match(r'grep -oP "(?<=x).*?(?=y)" file.py') is None

    def test_both_edges_wildcard_plain_word_is_not_matched(self) -> None:
        """Plan 00306 false positive: a ``*word*`` "contains" glob token
        (both edges wildcard) is not a truncation of any specific real
        filename — the leading-wildcard reverse-overlap direction is only a
        plausible truncation model for a token with an arbitrary prefix but
        an ANCHORED, fixed suffix (``*passXXX``). When the trailing edge is
        ALSO a wildcard the token asserts nothing about what follows its
        residue either, so a residue that merely starts with a plain English
        word sharing a short edge with a stem (``secret_file`` vs the
        ``.secret`` stem's ``secret`` suffix) must not be treated as
        evidence of a real protected name. Observed live: ``find . -iname
        "*secret_file*matching*"`` (a plain source-file name search) was
        denied as a ``*.secret*`` mention."""
        assert self._match('find . -iname "*secret_file*matching*"') is None

    def test_both_edges_wildcard_generic_word_search_is_not_matched(self) -> None:
        """A both-edges glob token (``*.txt``) unrelated to any protected
        stem, alongside a plain (non-glob-shaped) word that merely starts
        with 'secret', is not a mention -- neither the fixed-extension token
        nor the bare English word approximates a protected filename."""
        assert self._match("grep -l secretary_report *.txt") is None

    def test_both_edges_wildcard_naming_the_stem_is_still_matched(self) -> None:
        """Plan 00311 regression (opposite direction from the Plan 00306
        tests above): a both-edges-wildcard token whose residue effectively
        SPELLS the protected stem still glob-expands to the real file and
        must stay denied -- unconditionally excluding both-edges tokens
        opened a real read path (verified live with a synthetic pattern:
        ``cat *zzz-passwd*`` was allowed while ``cat *zzz-passwd`` stayed
        denied). Here the residue ``vault-pass`` differs from the
        ``.vault-pass`` stem by only the leading dot, so it is a near-total
        match, not a coincidental substring share."""
        assert self._match("cat *vault-pass*") is not None

    def test_both_edges_wildcard_naming_the_longer_stem_is_still_matched(self) -> None:
        """Companion to the test above, against the longer ``.vault-password``
        stem rather than the shorter ``.vault-pass`` one -- both near-total
        residues must stay denied."""
        assert self._match("grep x *vault-password*") is not None

    def test_both_edges_wildcard_prefix_truncation_multi_char_short_is_matched(
        self,
    ) -> None:
        """Plan 00311 follow-up (R1, incremental re-review): a both-edges
        residue that is a PREFIX of the stem but MORE than one character
        short of it must still deny -- the prior ``<= 1`` length-diff rule
        only restored the single-character-short case, leaving every longer
        truncation open. Verified live with a synthetic ``*.ZQZ-fshape``
        pattern: a 1-char-short and a 3-char-short residue were BOTH denied
        by v3.58.1."""
        synthetic_patterns = ("*.ZQZ-fshape",)
        assert sfm.find_protected_mention("ls *ZQZ-fshap*", synthetic_patterns) is not None
        assert sfm.find_protected_mention("ls *ZQZ-fsh*", synthetic_patterns) is not None

    def test_both_edges_wildcard_short_prefix_of_stem_is_matched(self) -> None:
        """The extreme truncation case: a residue that is only a small
        PREFIX of the stem's fixed literal (``*ZQZ*`` against a
        ``*.ZQZ-fshape`` stem) still glob-expands to the real file and must
        deny -- v3.58.1 denied the equivalent shape."""
        synthetic_patterns = ("*.ZQZ-fshape",)
        assert sfm.find_protected_mention("ls *ZQZ*", synthetic_patterns) is not None

    def test_both_edges_wildcard_short_prefix_of_short_stem_is_matched(self) -> None:
        """Same shape against a short 4-character stem (``.qqq``-style):
        a 2-character prefix residue still denies. v3.58.1 denied the
        equivalent shape against a short synthetic stem."""
        synthetic_patterns = (".QQQ",)
        assert sfm.find_protected_mention("ls *QQ*", synthetic_patterns) is not None

    def test_both_edges_wildcard_extension_containing_full_stem_is_matched(
        self,
    ) -> None:
        """A residue that CONTAINS the whole stem as its suffix (an
        arbitrary prefix glued onto the real filename, e.g. ``*dummy.ZQZ-
        fshape*``) names the real file exactly and must deny -- the most
        natural spelling of a truncation-avoidance probe, and denied by
        v3.58.1."""
        synthetic_patterns = ("*.ZQZ-fshape",)
        assert sfm.find_protected_mention("cat *dummy.ZQZ-fshape*", synthetic_patterns) is not None

    def test_both_edges_wildcard_prose_asterisk_word_is_not_matched(self) -> None:
        """Plan 00306 follow-up: the PRE-EXISTING (untouched-by-the-overlap-
        fix) substring+fnmatch branch has the identical both-edges-wildcard
        flaw -- ``fnmatch(stem, "*word*")`` succeeds whenever the residue
        occurs ANYWHERE inside the stem, not just as a real prefix/suffix
        truncation, so an ordinary emphasised prose word like ``*word*``
        coincidentally matches ``*.vault-password`` purely because
        ``.vault-password`` happens to end in ``...s-s-w-o-r-d``. Observed
        live: a commit message describing this very fix, containing the
        literal text ``a "*word*" contains-search``, was denied as a
        ``*.vault-password`` mention."""
        assert self._match('echo a "*word*" contains-search') is None

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


class TestFiniteBracketExpressionsAreNotWildcards:
    """Plan 00356: a bracket expression denotes a FINITE character set.

    A complete bracket expression sitting at a token's edge made
    ``_has_trailing_wildcard``/``_has_leading_wildcard`` report that edge as
    open to an arbitrary run, and ``_token_literal_residue`` dropped the
    bracket's own character entirely. Together those turned the jq path
    ``.foo.v[0]`` into the assertion "starts with ``.foo.v``, then anything",
    whose 2-character ``.v`` edge overlaps the ``.vault-password`` stem — so
    an ordinary array subscript was denied as a protected-path reference.

    ``[0]`` matches exactly one character. It opens nothing.
    """

    PATTERNS = sfm.DEFAULT_PROTECTED_PATTERNS

    def _match(self, command: str) -> str | None:
        return sfm.find_protected_mention(command, self.PATTERNS)

    def test_jq_subscript_after_a_v_field_is_not_matched(self) -> None:
        """The reported shape: field ``v``, element ``0``. Denied as
        ``*.vault-password`` because ``.foo.v`` + "anything" was thought to
        reach ``.foo.vault-password``."""
        assert self._match("x=$(jq -r '.foo.v[0]' data.json)") is None

    def test_decisive_single_letter_class_is_not_matched(self) -> None:
        """The decisive case from the report. Under POSIX ``[z]`` matches
        exactly ``z``, so this token can only ever denote the literal
        ``.foo.vz`` — which cannot be a ``*.vault-password`` file under any
        expansion. It was denied anyway."""
        assert self._match("x=$(jq -r '.foo.v[z]' data.json)") is None

    def test_realistic_repeated_field_read_is_not_matched(self) -> None:
        assert self._match("p=$(jq -r '.records[] | .values.v[0]' data.json)") is None

    def test_bracket_quoted_workaround_spelling_stays_allowed(self) -> None:
        """The workaround the reporter had to adopt must keep working — this
        is the control showing the two spellings now agree."""
        assert self._match("x=$(jq -r '.values[\"v\"][0]' data.json)") is None

    def test_sibling_subscripts_that_already_passed_still_pass(self) -> None:
        """Negative controls from the report's table that were already
        allowed — the fix must not disturb them."""
        assert self._match("x=$(jq -r '.foo.v' data.json)") is None
        assert self._match("x=$(jq -r '.foo[0]' data.json)") is None
        assert self._match("x=$(jq -r '.foo.x[0]' data.json)") is None

    def test_character_range_subscript_is_not_matched(self) -> None:
        """``[a-f]`` is a finite set too, not a wildcard."""
        assert self._match("cat .foo.v[a-f]") is None

    def test_python_dict_index_at_token_end_is_not_matched(self) -> None:
        """The same defect in any language that subscripts with brackets."""
        assert self._match("value = record['v'][0]") is None

    # ── Security direction: the fix must not over-correct into a fail-open ──

    def test_bracket_expression_naming_a_protected_file_is_still_matched(self) -> None:
        """A bracket expression whose expansion IS a protected name must stay
        denied — expanding the set is what makes this provable rather than
        heuristic."""
        assert self._match("cat [Vv]ault_pass") is not None

    def test_bracket_expression_expanding_onto_a_protected_name_is_matched(self) -> None:
        """Every concrete spelling is checked, so a protected name reachable
        through ANY member of the set denies."""
        assert self._match("cat dummy.vault-passwor[cde]") is not None

    def test_negated_bracket_stays_conservative(self) -> None:
        """``[!...]``/``[^...]`` is the complement of a set, not a finite one.
        Bash reads both as negation, so neither is expanded and both keep the
        pre-fix conservative treatment."""
        assert self._match("cat dummy.v[!x]") is not None
        assert self._match("cat dummy.v[^x]") is not None

    def test_real_wildcards_are_untouched_by_the_bracket_fix(self) -> None:
        """The generous glob-intersection behaviour this guard depends on is
        unchanged for genuine wildcards — these are the cases the shipped
        guidance promises are caught."""
        assert self._match("cat .vault-p*") is not None
        assert self._match('find .claude -name "*secret*"') is not None
        assert self._match("cat dummy.vault-p*") is not None
        assert self._match("cat dummy.v*") is not None

    def test_bracket_combined_with_a_real_wildcard_still_matched(self) -> None:
        """A token carrying BOTH a finite bracket and a real ``*`` keeps its
        wildcard: each expansion is still analysed as a glob."""
        assert self._match("cat dummy.vault-[pq]*") is not None

    def test_oversized_expansion_falls_back_to_conservative_treatment(self) -> None:
        """Beyond the expansion cap the token is left unexpanded, so it is
        judged exactly as it was before this fix — failing closed."""
        token = "dummy.v" + "[a-z]" * 4
        assert self._match(f"cat {token}") is not None


class TestBracketExpansionPrimitives:
    """Unit coverage for the expansion helpers themselves."""

    def test_single_member_class_expands_to_one_spelling(self) -> None:
        assert sfm._expand_bracket_expressions(".foo.v[0]") == [".foo.v0"]

    def test_range_expands_to_every_member(self) -> None:
        assert sfm._expand_bracket_expressions("x[a-c]") == ["xa", "xb", "xc"]

    def test_multiple_classes_expand_combinatorially(self) -> None:
        assert sfm._expand_bracket_expressions("[ab]-[cd]") == ["a-c", "a-d", "b-c", "b-d"]

    def test_literal_leading_bracket_member_is_honoured(self) -> None:
        """POSIX: a ``]`` immediately after ``[`` is a MEMBER of the class."""
        assert sfm._expand_bracket_expressions("x[]]") == ["x]"]

    def test_negated_class_is_not_expanded(self) -> None:
        assert sfm._expand_bracket_expressions("x[!a]") == ["x[!a]"]
        assert sfm._expand_bracket_expressions("x[^a]") == ["x[^a]"]

    def test_posix_named_class_is_not_expanded(self) -> None:
        """``[[:alpha:]]`` is not a character list — expanding its raw body
        would produce a WRONG, too-narrow set, so it stays conservative."""
        assert sfm._expand_bracket_expressions("x[[:alpha:]]") == ["x[[:alpha:]]"]

    def test_token_without_a_complete_bracket_is_returned_unchanged(self) -> None:
        assert sfm._expand_bracket_expressions("[pass_result") == ["[pass_result"]
        assert sfm._expand_bracket_expressions("plain.txt") == ["plain.txt"]

    def test_expansion_is_capped(self) -> None:
        token = "x" + "[a-z]" * 4
        assert sfm._expand_bracket_expressions(token) == [token]

    def test_a_range_at_the_cap_still_expands(self) -> None:
        """The rejection must start exactly where the product cap already did.

        A range of ``_MAX_BRACKET_EXPANSIONS`` members passed the product cap
        before and still has to, or the cheap check has quietly narrowed what
        the guard expands.
        """
        end = chr(ord("a") + sfm._MAX_BRACKET_EXPANSIONS - 1)
        expansions = sfm._expand_bracket_expressions(f"x[a-{end}]")
        assert len(expansions) == sfm._MAX_BRACKET_EXPANSIONS
        assert expansions[0] == "xa"

    def test_a_range_one_past_the_cap_is_left_unexpanded(self) -> None:
        end = chr(ord("a") + sfm._MAX_BRACKET_EXPANSIONS)
        token = f"x[a-{end}]"
        assert sfm._expand_bracket_expressions(token) == [token]


class TestAWideRangeIsRejectedBeforeItIsBuilt:
    """The cap must bound the WORK, not just the result (Plan 00364 Task 3.1).

    ``_MAX_BRACKET_EXPANSIONS`` was checked against a member list
    ``_bracket_expression_members`` had ALREADY built, so a token carrying a
    wide literal range materialised every code point in it — and deduplicated
    them — purely to discover the product was over the cap.

    The verdict is identical either way: over the cap, the token is returned
    unexpanded and judged exactly as it was before, which fails CLOSED. Only
    the cost differs, and it matters because ``find_protected_mention`` runs on
    Write/Edit CONTENT from ``secret_file_guard``, a PreToolUse handler on the
    dispatch hot path.
    """

    def test_the_widest_possible_range_is_left_unexpanded(self) -> None:
        token = f"f{_WIDEST_POSSIBLE_RANGE}.txt"
        assert sfm._expand_bracket_expressions(token) == [token]

    def test_the_widest_possible_range_costs_no_time(self) -> None:
        token = f"f{_WIDEST_POSSIBLE_RANGE}.txt"
        start = time.perf_counter()
        sfm._expand_bracket_expressions(token)
        elapsed = time.perf_counter() - start
        assert elapsed < _WIDE_RANGE_BUDGET_SECONDS, (
            f"expanding {len(_WIDEST_POSSIBLE_RANGE)} characters of literal "
            f"range took {elapsed:.3f}s — the range is being materialised "
            f"before the cap rejects it"
        )

    def test_the_members_helper_rejects_the_range_itself(self) -> None:
        """The check belongs INSIDE the helper, not at its call site.

        Asserting on ``_expand_bracket_expressions`` alone would still pass
        with the rejection left where it was, since that function's return
        value never changed.
        """
        assert sfm._bracket_expression_members(_WIDEST_POSSIBLE_RANGE) is None

    def test_many_wide_ranges_in_one_payload_stay_cheap(self) -> None:
        """The measured 13.5 s case: cost is linear in the token count.

        Driven through the public entry point ``secret_file_guard`` calls, so
        this covers the real hot path rather than the primitive alone.
        """
        content = " ".join(f"f{index}{_WIDEST_POSSIBLE_RANGE}.txt" for index in range(20))
        start = time.perf_counter()
        assert sfm.find_protected_mention(content, ("*.secret*",)) is None
        elapsed = time.perf_counter() - start
        assert (
            elapsed < _WIDE_RANGE_BUDGET_SECONDS
        ), f"twenty wide-range tokens took {elapsed:.3f}s on the PreToolUse hot path"

    def test_edge_predicates_are_left_untouched(self) -> None:
        """The fix deliberately does NOT redefine the edge predicates — the
        Plan 00306 contract that a complete bracket expression IS glob syntax
        still holds; expansion changes the INPUT they are applied to."""
        assert sfm._is_glob_shaped("x[]]") is True
        assert sfm._has_trailing_wildcard("x[]]") is True
        assert sfm._is_glob_shaped("x[!]]") is True


class TestPythonImportStatements:
    """A dotted Python MODULE path is not a filesystem path.

    Found dogfooding: the shipped default glob ``*.secret*`` substring-matches
    the module path ``...handlers.pre_tool_use.secret_file_guard``, so NO file
    could add an import of the guard's own module — the existing test files
    survive only because they predate the guard and are on its
    ``exclude_paths``. Any client with a ``.secret``-containing module path
    hits the same wall, and cannot be expected to enumerate them.

    Narrowed to import STATEMENTS rather than to dotted tokens generally, so
    it cannot produce a false negative: importing a module name cannot read a
    file, and the module-path grammar admits no ``/``, so no filesystem path
    can be spelled as one. That matters because this module's stated
    trade-off is that over-blocking is cheap and under-blocking is not.
    """

    PROTECTED = ("*.secret*",)

    def test_a_from_import_of_such_a_module_is_not_a_mention(self) -> None:
        command = (
            "from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard "
            "import SecretFileGuardHandler"
        )
        assert sfm.find_protected_mention(command, self.PROTECTED) is None

    def test_a_plain_import_of_such_a_module_is_not_a_mention(self) -> None:
        command = "import claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard"
        assert sfm.find_protected_mention(command, self.PROTECTED) is None

    def test_a_real_protected_path_alongside_an_import_is_still_caught(self) -> None:
        """The exemption must not become a carrier: a genuine path in the same
        content is still a mention."""
        command = (
            "from a.b.secret_file_guard import X\n"
            "data = open('.claude/block-words.secret').read()\n"
        )
        assert sfm.find_protected_mention(command, self.PROTECTED) == "*.secret*"

    def test_a_path_shaped_token_outside_an_import_is_still_a_mention(self) -> None:
        """Scoped to import statements, not to dotted tokens: a bare filename
        carrying the stem is still judged normally."""
        assert sfm.find_protected_mention("cat foo.secret", self.PROTECTED) == "*.secret*"

    def test_a_slash_path_can_never_be_spelled_as_a_module(self) -> None:
        """The module grammar admits no `/`, which is what makes the exemption
        unable to hide a filesystem path."""
        command = "import .claude/block-words.secret"
        assert sfm.find_protected_mention(command, self.PROTECTED) == "*.secret*"


class TestPythonDashCImportStatements:
    """Plan 00311 Task 1.2 (N2) residual: `python -c "import <module>"` puts
    the import statement on the SAME line as the interpreter invocation, so
    ``_IMPORT_MODULE_RE``'s line-start anchor never reaches it even though
    the equivalent multi-line `from`/`import` STATEMENT case
    (``TestPythonImportStatements`` above) is exempt. Diagnosed live while
    investigating Plan 00356 -- naming the dotted module path this way was
    denied on the Bash surface (this module's own dotted path,
    ``...utils.secret_file_matching``, substring-matches the shipped
    ``*.secret*`` default) even after the Write/Edit surface was fixed for
    the identical name.
    """

    PROTECTED = ("*.secret*",)

    def test_python_dash_c_import_of_this_modules_own_path_is_not_a_mention(self) -> None:
        command = 'python -c "import claude_code_hooks_daemon.utils.secret_file_matching"'
        assert sfm.find_protected_mention(command, self.PROTECTED) is None

    def test_python3_dash_c_single_quoted_import_is_not_a_mention(self) -> None:
        command = "python3 -c 'import claude_code_hooks_daemon.utils.secret_file_matching'"
        assert sfm.find_protected_mention(command, self.PROTECTED) is None

    def test_dash_c_from_import_form_is_not_a_mention(self) -> None:
        command = (
            'python -c "from claude_code_hooks_daemon.utils.secret_file_matching '
            'import find_protected_mention"'
        )
        assert sfm.find_protected_mention(command, self.PROTECTED) is None

    def test_a_real_protected_path_alongside_a_dash_c_import_is_still_caught(self) -> None:
        """The exemption must not become a carrier on the inline surface
        either: a genuine path elsewhere in the same command is still a
        mention."""
        command = (
            'python -c "import claude_code_hooks_daemon.utils.secret_file_matching" '
            "&& cat .claude/block-words.secret"
        )
        assert sfm.find_protected_mention(command, self.PROTECTED) == "*.secret*"

    def test_a_quoted_import_without_the_dash_c_flag_is_still_a_mention(self) -> None:
        """Scoped to the ``-c`` shape specifically, not to any quoted text
        starting with the word "import" -- proves the exemption did not
        widen into a general quote-anchored amnesty."""
        command = 'echo "import mykeys.secret"'
        assert sfm.find_protected_mention(command, self.PROTECTED) == "*.secret*"

    def test_a_dash_c_import_does_not_hide_a_separate_real_argument(self) -> None:
        """The same laundering check as ``TestTheImportExemptionCannotLaunderAMention``,
        for the inline surface: an EXACT-filename pattern's own bare mention
        elsewhere in the command is still caught."""
        command = 'python -c "import id_rsa" && cat id_rsa'
        assert sfm.find_protected_mention(command, ("id_rsa",)) == "id_rsa"


class TestBareHomePrefixTokenDoesNotCrash:
    """N5 (Plan 00466), security fail-open: a token that is EXACTLY one of
    ``_HOME_PREFIXES`` (the prefix with nothing following it, e.g. a quoted
    Python string literal ``"~/"``) strips down to an EMPTY residual in
    ``_normalised_token_forms`` -- ``token[len(prefix):]`` on a token equal to
    the prefix is ``""``. That empty form then reached
    ``path_matches_globs("", ...)`` with a real ``project_root``, which calls
    ``os.path.relpath("", root)`` and raises ``ValueError: no path specified``
    -- os.path.relpath rejects an empty PATH argument outright, regardless of
    ``start``.

    Reproduced live (00463's agent's transcript, replayed through the real
    daemon by the coordinator): editing
    ``subagent_full_qa_blocker.py`` to add
    ``_HOME_PREFIXES: Final[tuple[str, ...]] = ("~/", "$HOME/", "${HOME}/",
    "$PWD/", "${PWD}/")`` raised inside ``secret_file_guard``'s ``matches()``.
    Because the exception happens in ``matches()``, not ``handle()``, the
    daemon's non-strict per-handler catch (``core/chain.py``) logs it as
    context and moves on -- which means THIS HANDLER, `secret_file_guard`,
    is skipped for that write. That is a fail-OPEN on a security guard, not
    mere noise: a write whose content also names a real protected path
    would slip through unexamined. See
    ``test_a_genuine_mention_alongside_the_crashing_token_is_still_denied``
    below, which pins the fail-SAFE behaviour the fix must restore.

    All tests here initialise ``ProjectContext`` (via ``monkeypatch``) so
    ``resolve_project_root()`` returns a real root -- the crash needs a
    non-``None`` ``project_root`` to reach ``os.path.relpath`` at all, which
    an un-initialised unit-test process never supplies on its own.
    """

    PATTERNS = sfm.DEFAULT_PROTECTED_PATTERNS

    @pytest.fixture(autouse=True)
    def _project_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from claude_code_hooks_daemon.core import project_context as pc

        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext, "project_root", classmethod(lambda cls: Path("/proj")), raising=False
        )

    def test_normalised_token_forms_never_yields_an_empty_string(self) -> None:
        for prefix in sfm._HOME_PREFIXES:
            assert "" not in sfm._normalised_token_forms(prefix), prefix

    def test_each_bare_prefix_token_alone_does_not_raise(self) -> None:
        for prefix in sfm._HOME_PREFIXES:
            assert sfm.find_protected_mention_detail(prefix, self.PATTERNS) is None

    def test_the_reported_tuple_literal_does_not_raise(self) -> None:
        """The exact shape from the live transcript: a quoted string literal
        equal to a home/pwd prefix, inside a Python tuple, as Write/Edit
        CONTENT (the ``_script_content_mention`` route)."""
        content = (
            "_HOME_PREFIXES: Final[tuple[str, ...]] = "
            '("~/", "$HOME/", "${HOME}/", "$PWD/", "${PWD}/")\n'
        )
        assert sfm.find_protected_mention_detail(content, self.PATTERNS) is None

    def test_the_bare_expansion_marker_tuple_does_not_raise(self) -> None:
        """The third live payload: single-character expansion markers,
        individually quoted."""
        content = '_UNSEEN_CD_PREFIXES: Final[tuple[str, ...]] = ("$", "~", "`")\n'
        assert sfm.find_protected_mention_detail(content, self.PATTERNS) is None

    def test_a_genuine_mention_alongside_the_crashing_token_is_still_denied(self) -> None:
        """Fail-SAFE pin (team-lead item (c)): a content blob carrying BOTH a
        home-prefix token AND a genuine protected-path mention must still
        DENY. Before the fix, the crash on the home-prefix token happened
        mid-scan and the real mention later in the same content was never
        reached -- an exception is not a decision, and this handler's
        contract has no silent-skip case."""
        content = 'home = "~/"\nkey_path = "id_rsa"\n'
        assert sfm.find_protected_mention_detail(content, self.PATTERNS) == ("id_rsa", "id_rsa")

    def test_mention_scan_never_raises_over_a_corpus_of_path_operands(self) -> None:
        """Class test (team-lead ask): the mention scan must be TOTAL over
        every shell/Python path-expansion operand observed in the payloads
        that triggered N5, alone and paired with ordinary code around them."""
        operands = (
            "~/",
            "$HOME/",
            "${HOME}/",
            "$PWD/",
            "${PWD}/",
            "$PWD",
            "${PWD}",
            "$",
            "~",
            "`",
            "./",
            ".",
            "..",
        )
        for operand in operands:
            sfm.find_protected_mention_detail(operand, self.PATTERNS)
            sfm.find_protected_mention_detail(f'x = "{operand}"\n', self.PATTERNS)
            sfm.find_protected_mention_detail(f"path.startswith({operand!r})\n", self.PATTERNS)


class TestTheImportExemptionCannotLaunderAMention:
    """A fake import must not blind the matcher to the SAME token elsewhere.

    The exemption has to be positional, not a string-identity amnesty. Keyed on
    identity, prefixing any command with ``import <token>`` deletes that token
    from consideration everywhere in the text — an escape hatch in a guard
    whose own deny text states there is none, and one that gates four DENY /
    suppress surfaces including payload capture.

    The original tests missed this because they demonstrated the exemption with
    a SLASH path, which the module grammar genuinely cannot spell. A protected
    file named without a directory — which the shipped ``*.secret*`` default
    matches — is spellable as a module, and that is the whole hole.
    """

    PROTECTED = ("*.secret*",)

    def test_a_fake_import_line_does_not_hide_a_later_read(self) -> None:
        command = "import mykeys.secret\ncat mykeys.secret"
        assert sfm.find_protected_mention(command, self.PROTECTED) == "*.secret*"

    def test_a_fake_from_line_does_not_hide_a_later_read(self) -> None:
        command = "from mykeys.secret import x\ncat mykeys.secret"
        assert sfm.find_protected_mention(command, self.PROTECTED) == "*.secret*"

    def test_a_semicolon_import_on_one_line_does_not_hide_the_read(self) -> None:
        """`import` is not a shell builtin, so the laundering statement fails
        harmlessly and the real command after the `;` still runs."""
        command = "import mykeys.secret; cat mykeys.secret"
        assert sfm.find_protected_mention(command, self.PROTECTED) == "*.secret*"

    def test_leading_whitespace_does_not_enable_the_laundering(self) -> None:
        command = "  import mykeys.secret\ncat mykeys.secret"
        assert sfm.find_protected_mention(command, self.PROTECTED) == "*.secret*"

    def test_the_legitimate_import_only_case_is_still_exempt(self) -> None:
        """The fix must not re-break what the exemption exists for: an import
        of a module whose dotted name merely contains the stem, with no other
        occurrence of that token, is still not a mention."""
        command = "import claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard"
        assert sfm.find_protected_mention(command, self.PROTECTED) is None

    def test_a_multiline_module_with_a_separate_legitimate_body_is_exempt(self) -> None:
        command = "from a.b.secret_file_guard import X\nresult = X().handle(event)\n"
        assert sfm.find_protected_mention(command, self.PROTECTED) is None


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

    def test_git_rm_cached_protected_path_is_exempt(self) -> None:
        """Plan 00306 Task 1.3: ``secret_file_hygiene_checker`` recommends
        ``git rm --cached <protected-path>`` to untrack a protected file —
        that command reads no content, it only stops tracking the file, so
        it must be runnable verbatim rather than denied by the very guard
        whose hygiene it improves."""
        cmd = "git rm --cached .claude/block-words.secret"
        assert sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_git_rm_cached_glob_pathspec_is_exempt(self) -> None:
        cmd = "git rm --cached '.claude/block-words.*'"
        assert sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_git_rm_without_cached_is_never_exempt(self) -> None:
        """``git rm`` (no ``--cached``) deletes the working-tree file too —
        that is a different, more destructive operation and stays denied."""
        cmd = "git rm .claude/block-words.secret"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_git_rm_cached_compound_command_is_not_exempt(self) -> None:
        cmd = "git rm --cached .claude/block-words.secret && cat .claude/block-words.secret"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_git_rm_dry_run_cached_is_exempt(self) -> None:
        """Plan 00311 Task 1.3 (N5) second look: ``--cached`` matching
        ANYWHERE after the subcommand means an interleaved ``--dry-run`` is
        also exempt. Verified correct -- ``--dry-run`` reports what WOULD be
        removed without touching the index or reading any content, so this
        stays exempt on purpose."""
        cmd = "git rm --dry-run --cached .claude/block-words.secret"
        assert sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_git_rm_recursive_cached_is_exempt(self) -> None:
        """Same second look, for ``-r``: recursive untracking still reads no
        file content, only index entries -- verified correct, stays exempt."""
        cmd = "git rm -r --cached .claude/block-words.secret"
        assert sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_git_rm_cached_pathspec_from_file_is_never_exempt(self) -> None:
        """Plan 00311 Task 1.3 (N5) second-look FINDING (not a false alarm):
        ``--pathspec-from-file=<file>`` makes ``git rm`` READ ``<file>`` and
        treat each line as a pathspec. Empirically verified (untracked scratch
        repo, this session): a non-matching pathspec is echoed VERBATIM into
        git's own stderr (``fatal: pathspec '<line content>' did not match any
        files``) -- so this shape discloses the named file's content even
        though the command still "only" untracks. Must stay denied."""
        cmd = "git rm --cached --pathspec-from-file=.claude/block-words.secret"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_git_rm_cached_pathspec_from_file_space_form_is_never_exempt(self) -> None:
        """Same finding, ``--flag value`` form (git accepts both)."""
        cmd = "git rm --cached --pathspec-from-file .claude/block-words.secret"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_git_rm_cached_pathspec_from_file_naming_something_else_is_never_exempt(
        self,
    ) -> None:
        """The flag voids the exemption outright, regardless of what it
        names -- the broken invariant is "rm reads a file", not "rm reads
        THIS file"."""
        cmd = "git rm --cached --pathspec-from-file=list.txt .claude/block-words.secret"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_git_dash_c_rm_cached_is_exempt(self) -> None:
        """N4 code-review fix (Plan 00311 follow-up): ``git -C <path> rm
        --cached <protected-path>`` is exactly the shape an agent working
        from another cwd types, and is exactly what
        ``secret_file_hygiene_checker``'s own recommended remedy can produce
        -- it must not be denied by the guard whose hygiene it improves."""
        cmd = "git -C /repo rm --cached .claude/block-words.secret"
        assert sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_git_dash_c_rm_without_cached_is_never_exempt(self) -> None:
        cmd = "git -C /repo rm .claude/block-words.secret"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_git_dash_c_rm_recursive_cached_is_exempt(self) -> None:
        """Plan 00311 Task 1.4 regression pin: an intervening ``-r`` between
        the subcommand and ``--cached`` must not upset the generic skipper
        that replaced the ``-C``-only special case."""
        cmd = "git -C /repo rm -r --cached .claude/block-words.secret"
        assert sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_git_dash_c_rm_cached_equals_form_is_never_exempt(self) -> None:
        """``--cached=x`` is not the real ``--cached`` flag -- the exact-match
        check must not be loosened by the generic global-option skipper."""
        cmd = "git -C /repo rm --cached=x .claude/block-words.secret"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_git_dash_lowercase_c_config_rm_cached_is_exempt(self) -> None:
        """Plan 00311 Task 1.4 (R5): the generic leading-global-flag skipper
        must see past ANY value-taking global option, not just ``-C`` -- a
        real hygiene-recommended invocation carrying an unrelated ``-c
        <key>=<value>`` global was failing CLOSED (the same usability gap N4
        described, one layer out)."""
        cmd = "git -c core.pager=cat rm --cached .claude/block-words.secret"
        assert sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_git_dash_c_no_pager_rm_cached_is_exempt(self) -> None:
        """Same as above, for a run of TWO leading global options -- one
        value-taking (``-C``), one valueless (``--no-pager``)."""
        cmd = "git -C /repo --no-pager rm --cached .claude/block-words.secret"
        assert sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_cat_of_protected_path_stays_denied_alongside_git_rm_exemption(self) -> None:
        assert not sfm.is_exempt_invocation(
            "cat .claude/block-words.secret", sfm.DEFAULT_ALLOWED_CONSUMERS
        )


class TestLeadingCdPrefix:
    """Client report: a trusted consumer stopped being exempt the moment it
    was reached via ``cd <dir> && ...``.

    The reported command was
    ``cd /workspace/infra/ansible && ansible-playbook ... --vault-password-file <path>``.
    ``ansible-playbook`` is a shipped consumer and ``--vault-password-file``
    a recognised path flag, but the separator check voided the exemption
    before either was consulted, so the compound fell through to the generic
    deny. The shape is forced rather than incidental: those vault scripts
    resolve their project root by walking up from cwd, so they have to be
    invoked from the project directory.

    This is the same failing-closed shape ``git -C <path> rm --cached``
    already has an exemption for -- an agent working from another cwd.

    A bare ``cd`` cannot disclose anything: it names a directory and sets
    cwd. What must NOT follow is any weakening of the compound rule itself,
    so the prefix is stripped and the REMAINDER is re-judged by the same
    function -- which still voids on every separator. The attack cases below
    pin that.
    """

    _VAULT = "ansible-playbook site.yml --vault-password-file vault-pass-dev.secret"

    def test_the_reported_command_is_exempt(self) -> None:
        cmd = f"cd /workspace/infra/ansible && {self._VAULT}"
        assert sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_a_relative_cd_is_exempt_too(self) -> None:
        assert sfm.is_exempt_invocation(
            f"cd infra/ansible && {self._VAULT}", sfm.DEFAULT_ALLOWED_CONSUMERS
        )

    def test_a_trailing_disclosure_after_the_consumer_is_still_denied(self) -> None:
        """The attack the separator rule exists to stop. Stripping the cd
        must not smuggle it through: the remainder still holds a separator,
        so the same rule that caught it before still catches it."""
        cmd = f"cd /infra && {self._VAULT} && cat vault-pass-dev.secret"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_a_disclosure_chained_with_a_pipe_is_still_denied(self) -> None:
        cmd = f"cd /infra && {self._VAULT} | tee leaked.txt"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_cd_does_not_launder_an_untrusted_command(self) -> None:
        """The prefix buys the REMAINDER nothing it would not have had on
        its own -- `cat <protected>` is denied either way."""
        cmd = "cd /infra && cat vault-pass-dev.secret"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_a_command_substitution_in_the_cd_target_is_denied(self) -> None:
        """`cd $(cat <protected>)` DOES disclose -- the substitution runs and
        its output reaches the process table and any error message. A bare
        `cd` is safe; this is not a bare `cd`."""
        cmd = f"cd $(cat vault-pass-dev.secret) && {self._VAULT}"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_a_backtick_substitution_in_the_cd_target_is_denied(self) -> None:
        cmd = f"cd `cat vault-pass-dev.secret` && {self._VAULT}"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_only_one_cd_prefix_is_stripped(self) -> None:
        """Recursion would let an arbitrary chain be peeled one command at a
        time. Exactly one prefix is removed; a second leaves a separator in
        the remainder and the compound is judged as a whole."""
        cmd = f"cd /a && cd /b && {self._VAULT}"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_a_semicolon_prefix_is_not_covered(self) -> None:
        """Deliberately narrow: `&&` proves the cd SUCCEEDED, so the consumer
        runs where it was meant to. With `;` it runs regardless of where it
        lands, which is a different shape and was not the one reported."""
        cmd = f"cd /infra ; {self._VAULT}"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_cd_with_no_argument_is_not_a_prefix(self) -> None:
        assert not sfm.is_exempt_invocation(f"cd && {self._VAULT}", sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_a_protected_path_as_the_cd_target_is_denied(self) -> None:
        """Not a disclosure, but not a shape worth exempting either: a
        directory argument that is itself a protected path is a mistake or
        a probe, and refusing it costs a legitimate caller nothing."""
        cmd = f"cd .claude/block-words.secret && {self._VAULT}"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

    def test_the_prefix_does_not_rescue_a_denied_subcommand(self) -> None:
        """A consumer's disclosure-purposed subcommand stays denied through
        the prefix, exactly as it would without one."""
        cmd = "cd /infra && ansible-vault view --vault-password-file vault-pass-dev.secret"
        assert not sfm.is_exempt_invocation(cmd, sfm.DEFAULT_ALLOWED_CONSUMERS)

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

    def test_exempt_file_is_skipped(self, tmp_path: Path) -> None:
        """Plan 00459: a protected file confirmed encrypted does not flag its tree."""
        (tmp_path / "vault_passwords.yml").write_text("x\n")
        exempt = str(tmp_path / "vault_passwords.yml")
        result = sfm.directory_contains_protected(
            str(tmp_path), sfm.DEFAULT_PROTECTED_PATTERNS, is_exempt=lambda p: p == exempt
        )
        assert result is None

    def test_exempt_file_beside_a_plaintext_one_still_flags(self, tmp_path: Path) -> None:
        (tmp_path / "vault_passwords.yml").write_text("x\n")
        (tmp_path / ".vault-pass").write_text("x\n")
        exempt = str(tmp_path / "vault_passwords.yml")
        result = sfm.directory_contains_protected(
            str(tmp_path), sfm.DEFAULT_PROTECTED_PATTERNS, is_exempt=lambda p: p == exempt
        )
        assert result == ".vault-pass*"


class TestIterProtectedMentions:
    """Plan 00459: every mention, not just the first, so each can be confirmed."""

    def test_yields_every_mentioned_token_in_order(self) -> None:
        command = "git add group_vars/all/vault_passwords.yml .vault-pass README.md"
        mentions = list(sfm.iter_protected_mentions(command, sfm.DEFAULT_PROTECTED_PATTERNS))
        assert [token for _pattern, token in mentions] == [
            "group_vars/all/vault_passwords.yml",
            ".vault-pass",
        ]

    def test_one_mention_per_token(self) -> None:
        """A token matching two globs is still ONE mention to confirm."""
        mentions = list(
            sfm.iter_protected_mentions("cat x.secret.vault_pass", sfm.DEFAULT_PROTECTED_PATTERNS)
        )
        assert len(mentions) == 1

    def test_detail_is_the_first_mention(self) -> None:
        command = "cat .vault-pass group_vars/all/vault_passwords.yml"
        first = next(sfm.iter_protected_mentions(command, sfm.DEFAULT_PROTECTED_PATTERNS))
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) == first

    def test_no_mentions(self) -> None:
        assert not list(sfm.iter_protected_mentions("git status", sfm.DEFAULT_PROTECTED_PATTERNS))


_CWD = "/proj"
_ENC = "group_vars/all/vault_passwords.yml"
_ENC_TEMPLATE = "templates/app.secrets"
_ENCRYPTED = frozenset({f"{_CWD}/{_ENC}", f"{_CWD}/{_ENC_TEMPLATE}"})


def _encrypted_ok(command: str, *, cwd: str | None = _CWD) -> bool:
    return sfm.is_encrypted_target_invocation(
        command,
        sfm.DEFAULT_PROTECTED_PATTERNS,
        cwd=cwd,
        is_encrypted=lambda path: path in _ENCRYPTED,
    )


class TestEncryptedTargetInvocationAllows:
    """Plan 00459: naming a confirmed-encrypted file in a command that cannot decrypt it."""

    def test_git_add(self) -> None:
        assert _encrypted_ok(f"git add {_ENC}")

    def test_git_add_two_encrypted_files(self) -> None:
        assert _encrypted_ok(f"git add {_ENC} {_ENC_TEMPLATE}")

    def test_git_commit_naming_it(self) -> None:
        assert _encrypted_ok(f"git commit -m 'Rotate the database password' -- {_ENC}")

    def test_git_status_mv_rm(self) -> None:
        assert _encrypted_ok(f"git status --short {_ENC}")
        assert _encrypted_ok(f"git mv {_ENC} group_vars/all/renamed.yml")
        assert _encrypted_ok(f"git rm {_ENC}")

    def test_git_add_force_flag(self) -> None:
        assert _encrypted_ok(f"git add -f {_ENC}")

    def test_git_commit_all_with_message(self) -> None:
        assert _encrypted_ok(f"git commit -am 'x' {_ENC}")

    def test_plain_readers(self) -> None:
        for head in ("cat", "head -n 3", "tail -n 3", "wc -c", "ls -l", "stat", "file"):
            assert _encrypted_ok(f"{head} {_ENC}"), head
        assert _encrypted_ok(f"cp {_ENC} backup.yml")
        assert _encrypted_ok(f"mv {_ENC} group_vars/all/renamed.yml")

    def test_quoted_whole_word(self) -> None:
        assert _encrypted_ok(f"cat '{_ENC}'")
        assert _encrypted_ok(f'cat "{_ENC}"')

    def test_plain_redirections(self) -> None:
        assert _encrypted_ok(f"cat {_ENC} 2>&1")
        assert _encrypted_ok(f"cat {_ENC} > copy.txt")

    def test_absolute_path_needs_no_cwd(self) -> None:
        assert _encrypted_ok(f"cat {_CWD}/{_ENC}", cwd=None)

    def test_dot_slash_spelling(self) -> None:
        assert _encrypted_ok(f"git add ./{_ENC}")


class TestEncryptedTargetInvocationDenies:
    """Every shape the exemption must NOT unlock."""

    def test_no_mention_is_not_an_exemption(self) -> None:
        assert not _encrypted_ok("git status")

    def test_plaintext_protected_file_beside_the_encrypted_one(self) -> None:
        assert not _encrypted_ok(f"git add {_ENC} .vault-pass")

    def test_decrypted_or_missing_file(self) -> None:
        assert not _encrypted_ok("cat group_vars/prod/vault_passwords.yml")

    def test_relative_token_without_a_cwd(self) -> None:
        assert not _encrypted_ok(f"cat {_ENC}", cwd=None)
        assert not _encrypted_ok(f"cat {_ENC}", cwd="proj")

    def test_commands_that_can_decrypt(self) -> None:
        """Ansible finds the vault password from config without the command naming it."""
        for command in (
            f"ansible-vault view {_ENC}",
            f"ansible-vault decrypt {_ENC}",
            f"ansible-vault decrypt --output - {_ENC}",
            f"ansible-vault edit {_ENC}",
            f"EDITOR=cat ansible-vault edit {_ENC}",
            f"ansible localhost -m debug -a var=db_password -e @{_ENC}",
            f"ansible-playbook site.yml -e @{_ENC}",
            f"ansible-inventory --list -e @{_ENC}",
            f"python3 decrypt.py {_ENC}",
            f"git diff {_ENC}",
            f"git log -p {_ENC}",
            f"git show HEAD:{_ENC}",
            f"git blame {_ENC}",
            f"git grep -e x -- {_ENC}",
            f"git cat-file --textconv HEAD:{_ENC}",
        ):
            assert not _encrypted_ok(command), command

    def test_wrappers_and_path_spelled_heads(self) -> None:
        for command in (
            f"sh -c 'cat {_ENC}'",
            f"env cat {_ENC}",
            f"command cat {_ENC}",
            f"sudo cat {_ENC}",
            f"xargs cat {_ENC}",
            f"/bin/cat {_ENC}",
            f"./cat {_ENC}",
            f"LESSOPEN=x cat {_ENC}",
        ):
            assert not _encrypted_ok(command), command

    def test_grep_is_not_covered(self) -> None:
        """`grep -r` reads a whole tree; the named encrypted file must not vouch for it."""
        assert not _encrypted_ok(f"grep -c ANSIBLE {_ENC}")
        assert not _encrypted_ok(f"grep -r password {_ENC} .")

    def test_git_global_options(self) -> None:
        for command in (
            f"git -C sub add {_ENC}",
            f"git -c core.hooksPath=h add {_ENC}",
            f"git --no-pager add {_ENC}",
            f"git --git-dir=other/.git add {_ENC}",
        ):
            assert not _encrypted_ok(command), command

    def test_git_flags_that_render_a_diff(self) -> None:
        for command in (
            f"git add -p {_ENC}",
            f"git add --patch {_ENC}",
            f"git add -i {_ENC}",
            f"git add --interactive {_ENC}",
            f"git add -e {_ENC}",
            f"git commit -v -m x {_ENC}",
            f"git commit --verbose -m x {_ENC}",
            f"git commit -e -m x {_ENC}",
            f"git status -v {_ENC}",
            f"git commit -vm x {_ENC}",
        ):
            assert not _encrypted_ok(command), command

    def test_compound_commands(self) -> None:
        for command in (
            f"git add {_ENC} && git commit -m x",
            f"git add {_ENC}; cat .vault-pass",
            f"cat {_ENC} | grep x",
            f"cat {_ENC} || true",
            f"cat {_ENC} & cat other",
            f"(cat {_ENC})",
            f"cat {_ENC}\ncat .vault-pass",
            f"cat {_ENC} |& cat",
        ):
            assert not _encrypted_ok(command), command

    def test_a_directory_change_before_the_read(self) -> None:
        """The token resolves under cwd; the shell would open it somewhere else."""
        assert not _encrypted_ok(f"cd inventories/staging && cat {_ENC}")
        assert not _encrypted_ok(f"cd inventories/staging; cat {_ENC}")

    def test_expansions_anywhere_in_the_command(self) -> None:
        for command in (
            f"cat $HOME/{_ENC}",
            f'cat "$D"{_ENC}',
            f"cat ${{D}}/{_ENC}",
            f"cat `pwd`/{_ENC}",
            f"cat $(pwd)/{_ENC}",
            f"cat ~/{_ENC}",
            f"cat \\\n {_ENC}",
            f"cat {_ENC} other\\ file",
            f"cat {{{_ENC},.vault-pass}}",
            f"cat {_ENC} x*",
            "cat group_vars/all/vault_pass*",
            "cat group_vars/all/vault_passwords.y?l",
            "cat group_vars/all/vault_passwords.[y]ml",
        ):
            assert not _encrypted_ok(command), command

    def test_token_not_a_whole_shell_word(self) -> None:
        for command in (
            'cat "group_vars/"all/vault_passwords.yml',
            f"cat x{_ENC}",
            f"git commit -m 'update {_ENC}'",
            f"git add --pathspec-from-file={_ENC}",
            f"cat -{_ENC}",
        ):
            assert not _encrypted_ok(command), command

    def test_process_substitution_and_here_strings(self) -> None:
        assert not _encrypted_ok(f"cat <(cat {_ENC})")
        assert not _encrypted_ok(f"cat {_ENC} >(cat)")
        assert not _encrypted_ok(f"cat {_ENC} <<< x")

    def test_redirect_into_a_plaintext_protected_name(self) -> None:
        assert not _encrypted_ok(f"cat {_ENC} > copy.secret")

    def test_unparseable_quoting(self) -> None:
        assert not _encrypted_ok(f"cat '{_ENC}")


class TestResolveAgainstCwd:
    def test_absolute_path_is_normalised(self) -> None:
        assert sfm.resolve_against_cwd("/proj/a/../b.yml", None) == "/proj/b.yml"

    def test_relative_path_joins_the_cwd(self) -> None:
        assert sfm.resolve_against_cwd("./a/b.yml", "/proj") == "/proj/a/b.yml"

    def test_relative_path_without_a_usable_cwd_is_unknowable(self) -> None:
        assert sfm.resolve_against_cwd("a/b.yml", None) is None
        assert sfm.resolve_against_cwd("a/b.yml", "proj") is None


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
