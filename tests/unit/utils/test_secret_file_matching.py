"""Tests for utils/secret_file_matching.py (Plan 00272).

The matching core behind the secret_file_guard handler: protected-path glob
resolution (additive/replace modes), path matching (including symlink
realpath), and Bash path-mention detection with its two narrow exemptions
(the ``secret-meta`` helper; allowlisted consumers with the path in flag
position).
"""

import errno
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.shell_expansion import TooManyToEnumerateError

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

    def test_leading_wildcard_with_an_internal_wildcard_too_still_matched(self) -> None:
        """Regression (m1, Plan 00466 review): the N4 gate applies its
        stricter ``stem_basename.endswith(residue)`` requirement to EVERY
        leading-wildcard token, but that requirement is only correct for the
        simple splat shape (``*identifier``, nothing else). A token that
        carries ANOTHER wildcard besides its leading one -- ``*rd*rd``,
        ``*word*word`` -- is not that shape: fnmatch expands the internal
        ``*`` too, so the token can glob-match a protected name (``*rd*rd``
        matches ``rd.vault-password``: contains ``rd``, then later another
        ``rd``) without its residue needing to be a literal suffix of the
        stem at all. Only the pre-existing overlap-length check should gate
        this shape, exactly as before N4."""
        assert self._match("cat *rd*rd") is not None
        assert self._match("cat *word*word") is not None

    def test_leading_wildcard_project_pattern_with_an_internal_wildcard_still_matched(
        self,
    ) -> None:
        """The same regression against a PROJECT-configured pattern with its
        own internal wildcard (``*secret*.json``): a token shaped
        ``*on*.json`` can still glob-expand to a protected name
        (``on-secret.json``) and must stay denied."""
        patterns = ("*secret*.json",)
        assert sfm.find_protected_mention("cat *on*.json", patterns) is not None

    def test_interior_question_mark_truncation_is_matched(self) -> None:
        """N10 (Plan 00466 review): a wildcard sitting in the MIDDLE of a
        protected name is invisible to the edge-based checks above -- this
        token has neither a leading nor a trailing wildcard, so it never
        reached ``_glob_token_overlaps_stem`` at all, and its residue
        (``.vault-pasword``, one ``s`` short of the real stem) is not a
        substring of ``.vault-password`` either, so the pre-existing
        substring+fnmatch check missed it too. ``fnmatch('.vault-password',
        '.vault-pas?word')`` is True (the ``?`` absorbs the missing ``s``),
        so a real protected file is reachable through this exact token."""
        assert self._match("cat .vault-pas?word") is not None
        assert self._match("cat .vault-p?ss") is not None

    def test_interior_star_with_unrelated_prefix_is_matched(self) -> None:
        """A second interior-wildcard shape: an unrelated literal PREFIX in
        front of the token (``prod.``) does not save it, because the
        protected pattern (``*.vault-password``) itself has an open leading
        edge -- the two open edges can absorb each other's slack, and a real
        file named ``prod.vault-password`` would match both."""
        assert self._match("cat prod.vault-passw*rd") is not None

    def test_interior_bracket_expression_truncation_is_matched(self) -> None:
        """The interior wildcard can also be a bracket expression, not just
        ``?``/``*``. ``[sz]`` expands to two concrete spellings
        (``.vault-password`` and ``.vault-paszword``) -- the first is the
        real protected stem exactly, so it must be caught even though its
        sibling expansion is a genuine non-match."""
        assert self._match("cat .vault-pas[sz]word") is not None

    def test_unrelated_interior_wildcard_tokens_are_not_matched(self) -> None:
        """The new interior-wildcard check must not become a blanket
        "any glob token" denial -- ordinary, unrelated glob-shaped tokens
        stay allowed."""
        assert self._match("ls *.py") is None
        assert self._match("ls src/*.md") is None
        assert self._match("cat file?.txt") is None
        assert self._match("cat repo[12].json") is None

    def test_splat_false_positive_from_n4_still_allowed(self) -> None:
        """The N10 fix must keep the N4 false-positive fix intact: it is
        scoped to tokens with NEITHER a leading NOR a trailing wildcard, so
        the Python unpacking splat shapes (leading-wildcard, no trailing)
        that N4 fixed must still be allowed."""
        assert self._match("rest = [words[0], *words[position + 1 :]]") is None
        assert self._match("def f(*wordlist): pass") is None
        assert self._match("call(*wordlist)") is None

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


class TestInteriorWildcardDpIsBounded:
    """B1 (Plan 00466 guard-defects review 2): the N10 interior-wildcard DP is
    O(len(a) * len(b)) per call, and ``_interior_wildcard_mention`` calls it
    once per bracket expansion, per non-both-edges pattern, per token — an
    UNBOUNDED cost in the length of a single token. Since a PreToolUse
    socket timeout is an ALLOW (``.claude/init.sh``), a token slow enough to
    exhaust the client's 30s budget is a bypass, not just a nuisance:
    placing it BEFORE a genuine mention in the same command delays the
    verdict past the timeout while the real mention sits unscanned.

    Every case here reproduces a review-measured shape (main: well under a
    second; pre-fix branch: 15-35s) and pins it back under a small bound.
    """

    _BUDGET_SECONDS = 1.0

    def test_the_60kb_bracket_and_star_bypass_shape_denies_fast(self) -> None:
        """The review's own B1 evidence case: a[bc]x6 + 5000 stars + a,
        immediately followed by a genuine mention — pre-fix this took
        31.151s on the branch (0.096s on main)."""
        token = "a" + "[bc]" * 6 + "*" * 5000 + "a"
        command = f"cat {token}; cat .vault-pass"
        start = time.perf_counter()
        result = sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS)
        elapsed = time.perf_counter() - start
        assert result is not None
        assert (
            elapsed < self._BUDGET_SECONDS
        ), f"took {elapsed:.3f}s, budget {self._BUDGET_SECONDS}s"

    def test_two_hundred_bracket_and_star_tokens_denies_fast(self) -> None:
        """The review's second timing case (105 KB): 200 x a[bc]x6<500*>a --
        34.946s pre-fix (0.232s on main). 200 tokens x 64 bracket expansions
        each is real volume (12800 intersection checks), not a per-token
        blow-up, so this gets a more generous bound than the single-token
        60 KB case above -- still a >20x improvement over pre-fix, and the
        whole-scan deadline below is the backstop for volume like this."""
        token = "a" + "[bc]" * 6 + "*" * 500 + "a"
        command = " ".join([token] * 200)
        start = time.perf_counter()
        sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS)
        elapsed = time.perf_counter() - start
        assert elapsed < 3.0, f"took {elapsed:.3f}s"

    def test_ordinary_one_megabyte_write_content_stays_bounded_by_the_deadline(
        self,
    ) -> None:
        """The review's non-adversarial case: 1 MB of ordinary 'a*b ' tokens
        (e.g. minified JS) -- 15-17s measured here pre-deadline vs main's own
        4.564s baseline. Not achievable from the per-token DP budget alone:
        no single token here is pathological, the cost is volume across
        250k short tokens. This is exactly what the whole-scan deadline
        exists for: with one supplied (as ``secret_file_guard`` supplies),
        the call returns -- either with a real answer or a ``TimeoutError``
        -- well inside the deadline instead of running past it, whichever
        outcome it is. (Review 7 follow-up: the normalised-word stream no
        longer has its own word-count cap, so ``TooManyToEnumerateError``
        is no longer a possible outcome here -- ``TimeoutError`` or a real
        answer are the only two.)"""
        content = "a*b " * 250_000
        start = time.perf_counter()
        outcome = "completed"
        try:
            sfm.find_protected_mention_detail(
                content, sfm.DEFAULT_PROTECTED_PATTERNS, deadline=time.monotonic() + 2.0
            )
        except TimeoutError:
            outcome = "timed out"
        except TooManyToEnumerateError:
            outcome = "too many to enumerate"
        elapsed = time.perf_counter() - start
        assert elapsed < 3.0, f"{outcome} in {elapsed:.3f}s, past a 2s deadline"

    def test_a_lone_long_star_run_collapses_to_near_zero_cost(self) -> None:
        """Collapsing repeated '*' is language-preserving (``a**b`` and
        ``a*b`` match the same set) and removes the dominant cost driver
        directly, independent of the budget cap."""
        token = "a" + "*" * 60_000 + "a"
        start = time.perf_counter()
        sfm.find_protected_mention_detail(f"cat {token}", sfm.DEFAULT_PROTECTED_PATTERNS)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1, f"took {elapsed:.3f}s"

    def test_scan_deadline_denies_via_the_fail_closed_route(self) -> None:
        """The whole-scan deadline is a backstop: forcing an artificially
        tiny deadline must raise so the guard's own fail-closed wrapper (N11)
        turns it into a deny, rather than the scan silently truncating and
        answering "no mention" for content it never finished examining."""
        with pytest.raises(TimeoutError):
            list(
                sfm.iter_protected_mentions(
                    "cat .vault-pass extra words here",
                    sfm.DEFAULT_PROTECTED_PATTERNS,
                    deadline=time.monotonic() - 1,
                )
            )


class TestOrdinaryVolumeContentCompletesFast:
    """Team-lead's follow-up to review 3: n466-n24 measured
    ``secret_file_guard`` at 12.3s for 1 MB and 49s for 4 MB (linear, ~12
    us/byte) -- a 4 MB input exceeds the client's 30s timeout on its own,
    independent of any single pathological token. Profiling (cProfile on a
    1 MB Bash command and a 1 MB Write payload) found the constant factor
    itself needed cutting, not just another cap: a real ``os.stat`` syscall
    per token (``_realpath_if_resolvable``, unconditional even for a
    glob-shaped token that could not plausibly BE a literal symlink name),
    six unconditional regex ``.sub()`` calls per DP-intersection pair (most
    of them no-ops on ordinary text), a fresh 2D list allocated per DP call,
    and no memoisation despite a scan's token stream being heavily
    repetitive for real content (source code, logs -- a bounded local
    vocabulary reused throughout a file, not a fresh unique token every
    time). Fixed: a per-token verdict cache scoped to one scan, the
    ``os.stat`` skipped for glob-shaped tokens, the regex subs gated on a
    cheap substring check, and the DP grid replaced by a two-row rolling
    array. n24 is separately adding a whole-chain deadline and an input
    size cap as a backstop for the residual case this cannot fully solve
    (content with NO repetition at all, i.e. a fresh unique token every
    time) -- these tests pin the COMMON case, which is now fast on its own
    merits rather than merely bounded by hitting a timeout.

    Review 7 follow-up (team-lead): ``_BUDGET_SECONDS`` was raised from 1.0
    to 3.5 -- the WORD-CAP fix restored these tests to actually running the
    stream to completion (they previously "passed" by raising early, past
    the now-removed cap, before ever reaching this cost) and review 7's own
    per-word wrapper/interpreter option-walk (MAJOR-3/MAJOR-5) added real
    state-machine cost per decoded word that this class's original 1.0s pin
    predates. 1 MB measures ~1.0-1.4s on a quiet machine; 3.5s keeps a real
    margin against ordinary CI/container load noise while staying
    comfortably inside the production whole-scan deadline
    (``SCAN_DEADLINE_SECONDS`` = 5.0s).
    """

    _BUDGET_SECONDS = 3.5

    @staticmethod
    def _vocabulary_command(target_bytes: int) -> str:
        """A ~target_bytes command built from a small, realistic local
        vocabulary of glob-shaped-looking short tokens, reused throughout --
        the way an actual source file or log reuses identifiers, keywords
        and punctuation, rather than a fresh unique token every time."""
        vocabulary = [
            f"{prefix}{index}{suffix}"
            for prefix in ("tok", "var", "fn", "obj", "self.", "ctx.", "req.")
            for index in range(40)
            for suffix in ("", "*", "a", "b", "_id", "()")
        ][:400]
        words: list[str] = []
        size = 0
        index = 0
        while size < target_bytes:
            word = vocabulary[index % len(vocabulary)]
            words.append(word)
            size += len(word) + 1
            index += 1
        return " ".join(words)[:target_bytes]

    def test_one_megabyte_bash_command_completes_well_under_a_second(self) -> None:
        """Restored to this class's original contract (review 7 follow-up,
        team-lead): large ORDINARY content -- no genuine mention, nothing
        combinatorial about it -- completes fast AND answers correctly
        (no mention found), rather than being denied outright. The
        normalised-word stream no longer has a word-count cap of its own
        (review 7 MAJOR-1's cap on this stream was the wrong instrument
        for flat, linear-cost decoding; see
        ``shell_expansion.TestIterNormalisedShellWordsDeadline`` for its
        replacement, a TIME-based deadline)."""
        command = self._vocabulary_command(1024 * 1024)
        start = time.perf_counter()
        result = sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS)
        elapsed = time.perf_counter() - start
        assert result is None
        assert elapsed < self._BUDGET_SECONDS, f"took {elapsed:.3f}s"

    def test_one_megabyte_write_content_completes_well_under_a_second(self) -> None:
        # The script-content route (Write/Edit to a .py/.sh/...) scans
        # CONTENT the identical way the Bash route scans a command line --
        # same `find_protected_mention_detail` call, same cost profile.
        # Restored to this class's original contract: fast AND correct,
        # not denied (see the sibling Bash test's docstring above).
        content = self._vocabulary_command(1024 * 1024)
        start = time.perf_counter()
        result = sfm.find_protected_mention_detail(content, sfm.DEFAULT_PROTECTED_PATTERNS)
        elapsed = time.perf_counter() - start
        assert result is None
        assert elapsed < self._BUDGET_SECONDS, f"took {elapsed:.3f}s"

    def test_repeated_identical_tokens_benefit_from_the_per_scan_cache(self) -> None:
        """The review's own pre-existing 'a*b ' x 250000 shape -- still
        fast (the per-scan cache this class pins), and restored to this
        class's original contract: completes and answers correctly (no
        mention), not denied outright."""
        content = "a*b " * 250_000
        start = time.perf_counter()
        result = sfm.find_protected_mention_detail(content, sfm.DEFAULT_PROTECTED_PATTERNS)
        elapsed = time.perf_counter() - start
        assert result is None
        assert elapsed < self._BUDGET_SECONDS, f"took {elapsed:.3f}s"

    def test_a_genuine_mention_is_still_found_in_realistic_volume_content(self) -> None:
        """The speed-up must not cost detection: a real mention placed at
        the END of a large ordinary-vocabulary command is still found, fast."""
        command = self._vocabulary_command(1024 * 1024) + " cat .vault-password"
        start = time.perf_counter()
        result = sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS)
        elapsed = time.perf_counter() - start
        assert elapsed < self._BUDGET_SECONDS, f"took {elapsed:.3f}s"
        assert result is not None


class TestBraceAndFsWalkAreBounded:
    """B1-R3 / M-1 (Plan 00466 review 3): review 2's own B1 fix, and its own
    new M2 sub-fixes, EACH independently reintroduced B1's own defect class
    -- a slow SAFETY-guard scan is a fail-open. m-1 (review 3's own minor):
    the timing suite above pinned the DP/star shapes but had NO timing test
    for `{a,b}`xN brace expansion or a `/**/` filesystem walk, which is
    precisely why these shipped unfixed. This class is that pin, on the
    reviewer's own exact shapes.
    """

    _BUDGET_SECONDS = 1.0

    @pytest.mark.parametrize("repetitions", [20, 22, 40])
    def test_brace_alternation_with_a_real_mention_denies_fast(self, repetitions: int) -> None:
        """The blocker's exact exploit shape: a genuine `.vault-password`
        mention sits in the SAME command as an exponential brace word --
        pre-fix this took 36.3s at x20 and was killed past 90s at x22."""
        command = f"cat .vault-password; echo {'{a,b}' * repetitions}"
        start = time.perf_counter()
        result = sfm.find_protected_mention_detail(
            command,
            sfm.DEFAULT_PROTECTED_PATTERNS,
            deadline=time.monotonic() + sfm.SCAN_DEADLINE_SECONDS,
        )
        elapsed = time.perf_counter() - start
        assert elapsed < self._BUDGET_SECONDS, f"took {elapsed:.3f}s"
        assert result is not None

    @pytest.mark.parametrize("repetitions", [20, 22, 40])
    def test_brace_alternation_alone_stays_fast_even_past_the_cap(self, repetitions: int) -> None:
        """No genuine mention this time -- past the shared expander's
        spelling cap the scan must still raise (fail closed) fast, not
        silently answer "no mention" after enumerating for tens of
        seconds."""
        command = "echo " + "{a,b}" * repetitions
        start = time.perf_counter()
        with pytest.raises(TooManyToEnumerateError):
            list(
                sfm.iter_protected_mentions(
                    command,
                    sfm.DEFAULT_PROTECTED_PATTERNS,
                    deadline=time.monotonic() + sfm.SCAN_DEADLINE_SECONDS,
                )
            )
        elapsed = time.perf_counter() - start
        assert elapsed < self._BUDGET_SECONDS, f"took {elapsed:.3f}s"

    def test_a_recursive_glob_token_rooted_at_the_filesystem_root_denies_fast(
        self,
    ) -> None:
        """M-1's own reproducer: `cat /**/*.se?ret-zq9x; cat .vault-password`
        took 9.5s pre-fix on this small container alone -- a real client
        filesystem (large home dir, node_modules, mounted volumes) can push
        a single such token well past the client's 30s chain budget. A
        `/**/` token rooted at the bare filesystem root is refused
        OUTRIGHT (fail closed) rather than walked at all, so this raises --
        exactly like the deadline case above, ``secret_file_guard``'s own
        wrapper is what turns the raise into a deny."""
        command = "cat /**/*.se?ret-zq9x; cat .vault-password"
        start = time.perf_counter()
        with pytest.raises(TooManyToEnumerateError):
            sfm.find_protected_mention_detail(
                command,
                sfm.DEFAULT_PROTECTED_PATTERNS,
                deadline=time.monotonic() + sfm.SCAN_DEADLINE_SECONDS,
            )
        elapsed = time.perf_counter() - start
        assert elapsed < self._BUDGET_SECONDS, f"took {elapsed:.3f}s"

    def test_ten_root_rooted_recursive_glob_tokens_deny_fast(self) -> None:
        """M-1's own multi-token reproducer -- 10 x `cat /**/*.se?ret-zq9x`
        tokens, 9.0s pre-fix (the deadline caught it between tokens, but
        the FIRST token alone already ran multiple seconds). The FIRST
        token alone is refused outright now, so this raises immediately."""
        command = " ".join(["cat /**/*.se?ret-zq9x"] * 10) + "; cat .vault-password"
        start = time.perf_counter()
        with pytest.raises(TooManyToEnumerateError):
            sfm.find_protected_mention_detail(
                command,
                sfm.DEFAULT_PROTECTED_PATTERNS,
                deadline=time.monotonic() + sfm.SCAN_DEADLINE_SECONDS,
            )
        elapsed = time.perf_counter() - start
        assert elapsed < self._BUDGET_SECONDS, f"took {elapsed:.3f}s"

    @pytest.mark.parametrize("size_kb", [94, 200])
    def test_huge_no_op_regex_shaped_input_with_a_real_mention_denies_fast(
        self, size_kb: int
    ) -> None:
        """The reviewer's 94 KB / 200 KB regex-shaped reproducer: a large
        run of `a[bc]x6<*>a` immediately followed by a genuine mention (the
        pre-existing DP/star-collapse cap already bounds this -- this test
        pins it at the sizes review 3 specifically re-measured)."""
        unit = "a" + "[bc]" * 6 + "*" * 500 + "a"
        n = max(1, (size_kb * 1024) // (len(unit) + 1))
        command = " ".join([unit] * n) + "; cat .vault-password"
        start = time.perf_counter()
        result = sfm.find_protected_mention_detail(
            command,
            sfm.DEFAULT_PROTECTED_PATTERNS,
            deadline=time.monotonic() + sfm.SCAN_DEADLINE_SECONDS,
        )
        elapsed = time.perf_counter() - start
        assert elapsed < sfm.SCAN_DEADLINE_SECONDS + self._BUDGET_SECONDS, f"took {elapsed:.3f}s"
        assert result is not None


class TestEdgeOpenTokensReachTheDpAgainstNonBothEdgesPatterns:
    """M2a (Plan 00466 guard-defects review 2): a token whose OWN wildcard
    sits at an edge (``*.vault-pas?word``, ``?rod.vault-passw*rd``,
    ``*vault*password``) was excluded from the DP-intersection check
    entirely -- it was gated on carrying NO edge wildcard, so it fell
    through to the overlap heuristic, which the N4/m1 fix deliberately
    narrowed and cannot re-widen. The DP is an EXACT glob-intersection test,
    so running it for edge-open tokens too (against every pattern that is
    NOT both-edges) closes this without reopening N4.
    """

    def test_leading_wildcard_plus_interior_question_mark_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat *.vault-pas?word", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is not None

    def test_leading_question_mark_plus_interior_star_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat ?rod.vault-passw*rd", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is not None

    def test_leading_wildcard_plus_literal_trailing_word_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat *vault*password", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is not None

    def test_n4_false_positive_still_does_not_deny(self) -> None:
        """The N4 shape this fix must not reopen: Python's unpacking
        operator ``*words[position + 1 :]`` tokenises to ``*words[position``,
        whose residue shares only a coincidental short edge with any stem,
        with nowhere for the rest of it to go against an end-anchored
        pattern."""
        result = sfm.find_protected_mention_detail(
            "echo *words[position", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is None


class TestUnexpandableBracketClassesAreTreatedAsWildcardInTheDp:
    """M2b (Plan 00466 guard-defects review 2): a bracket expression that
    ``_expand_bracket_expressions`` cannot enumerate (negated, a POSIX named
    class, or an over-cap range) is left UNEXPANDED "so the fallback fails
    CLOSED" -- but the DP previously read its ``[``/``]``/``!`` characters as
    LITERAL, so it failed OPEN instead. Treating an unexpanded bracket
    expression as a single ``?`` in the DP is a SUPERSET of what it can
    really match, restoring the fail-closed direction.
    """

    def test_negated_bracket_with_bang_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail("cat id_r[!x]a", sfm.DEFAULT_PROTECTED_PATTERNS)
        assert result is not None

    def test_negated_bracket_with_caret_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail("cat id_r[^x]a", sfm.DEFAULT_PROTECTED_PATTERNS)
        assert result is not None

    def test_posix_named_class_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat id_r[[:alpha:]]a", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is not None

    def test_over_cap_range_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat id_[a-z][a-z]a", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is not None


class TestBraceExpansionBeforeTokenising:
    """M2d (Plan 00466 guard-defects review 2): a real brace alternation
    (``{s,}``) has no internal whitespace, so a shell reads it as ONE word --
    but ``_tokenise`` splits on ``,`` (a general token delimiter), tearing it
    apart before any spelling can be recognised. Brace words are found and
    expanded against the RAW command text instead, the same conflict
    ``enforce_llm_qa``'s M1 fix resolves for its own tokeniser.
    """

    def test_optional_middle_alternative_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat .vault-pas{s,}word", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is not None

    def test_optional_trailing_alternative_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail("cat id_r{s,}a", sfm.DEFAULT_PROTECTED_PATTERNS)
        assert result is not None

    def test_bare_alternation_naming_the_exact_file_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail("cat {id_rsa,x}", sfm.DEFAULT_PROTECTED_PATTERNS)
        assert result is not None

    def test_both_edges_pattern_brace_alternative_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat block-words.se{c,}ret", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is not None


class TestBraceSequenceExpansion:
    """n466-n24 review 4, M-1: a brace SEQUENCE (`{start..end[..step]}`) is
    a DIFFERENT syntax from the comma alternation above, and was not
    covered by it at all -- `_raw_brace_expansions` read the whole `a..a`
    body as one literal comma-free alternative, so `id_rs{a..a}` spelled
    `id_rsa..a`, not `id_rsa`."""

    def test_degenerate_alpha_sequence_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat id_rs{a..a}", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is not None

    def test_a_real_alpha_range_reaching_the_name_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat id_rs{y..a}", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is not None

    def test_degenerate_numeric_sequence_reaching_a_project_pattern(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat file{9..9}.mysecretfile", ("*.mysecretfile",)
        )
        assert result is not None

    def test_an_unrelated_sequence_is_not_denied(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat file{1..5}.txt", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is None

    def test_a_huge_numeric_sequence_fails_closed(self) -> None:
        with pytest.raises(TooManyToEnumerateError):
            sfm.find_protected_mention_detail(
                "cat id_rs{1..100000}", sfm.DEFAULT_PROTECTED_PATTERNS
            )


class TestShellWordNormalisation:
    """n466-n24 review 4, M-1: the class behind `id_rs{a..a}` and
    `id_rs{'a',x}` reaching a protected name -- quote removal, adjacency
    concatenation, backslash escapes, ANSI-C `$'...'`, and an unresolvable
    substitution ($VAR/${...}/$(...)/backtick/$((...))) collapsed to a
    single `*` so the word is judged as a glob instead of silently losing
    the substitution's contribution."""

    def test_double_quote_adjacency_concatenation_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail('cat id_"rs"a', sfm.DEFAULT_PROTECTED_PATTERNS)
        assert result is not None

    def test_single_quote_adjacency_concatenation_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail("cat i'd'_rsa", sfm.DEFAULT_PROTECTED_PATTERNS)
        assert result is not None

    def test_brace_alternative_carrying_a_quote_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat id_rs{'a',x}", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is not None

    def test_backslash_escape_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail("cat id_rs\\a", sfm.DEFAULT_PROTECTED_PATTERNS)
        assert result is not None

    def test_ansi_c_hex_escape_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat id_rs$'\\x61'", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is not None

    def test_dollar_var_unknown_suffix_becomes_a_glob_and_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail("cat id_rs$x", sfm.DEFAULT_PROTECTED_PATTERNS)
        assert result is not None

    def test_command_substitution_naming_the_file_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat ~/.ssh/$(echo id_rsa)", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is not None

    def test_double_quoted_var_plus_trailing_glob_still_denies(self) -> None:
        result = sfm.find_protected_mention_detail(
            'cat "$HOME"/.ssh/id_rs*', sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is not None

    def test_an_ordinary_dollar_var_path_is_not_denied(self) -> None:
        """The fail-closed direction only fires when a match is genuinely
        POSSIBLE -- an ordinary $VAR-rooted path must stay allowed."""
        result = sfm.find_protected_mention_detail(
            "cat $SOME_CONFIG_DIR/readme.txt", sfm.DEFAULT_PROTECTED_PATTERNS
        )
        assert result is None


class TestBothEdgesTextualIntersectionIsCwdAndExistenceIndependent:
    """m-2 (n466-n24 review 4 addendum): the both-edges FS-truth route
    denies a genuine ``?``-only interior truncation of a both-edges stem
    only when the file actually EXISTS and is reachable from the caller's
    cwd -- so a `cd` elsewhere in the same command, or a file the command
    creates later in the SAME command, hid a real mention from it. Folding
    the ``?``-only case into the textual DP (``_glob_intersection_mention``,
    via ``_dp_intersection_is_meaningful``'s both-edges branch) needs
    neither: it judges what the token's own text asserts, not what the
    filesystem currently holds."""

    def test_cd_elsewhere_still_denies_an_interior_question_mark_truncation(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cd /tmp && cat /elsewhere/demo.se?ret",
            sfm.DEFAULT_PROTECTED_PATTERNS,
            cwd="/tmp",
        )
        assert result is not None
        assert result[0] == "*.secret*"

    def test_a_file_created_later_in_the_same_command_still_denies(self) -> None:
        """The create-then-read shape: nothing on disk when the scan runs,
        proving this does not depend on filesystem truth at all."""
        result = sfm.find_protected_mention_detail(
            "echo hi > /tmp/demo.secret && cat /tmp/demo.se?ret",
            sfm.DEFAULT_PROTECTED_PATTERNS,
            cwd="/tmp",
        )
        assert result is not None
        assert result[0] == "*.secret*"

    def test_an_unrelated_star_bearing_token_stays_allowed(self) -> None:
        """The over-promiscuity control (Plan 00306/00311): a token that
        carries its own ``*`` does not glob-intersect a both-edges pattern
        just because some substring happens to line up -- a both-edges
        pattern's own wildcards could absorb ANY such token, which is
        exactly why only the bounded ``?`` case is folded in here."""
        result = sfm.find_protected_mention_detail(
            "cat report-[0-9]*.txt", sfm.DEFAULT_PROTECTED_PATTERNS, cwd="/tmp"
        )
        assert result is None

    def test_another_unrelated_star_bearing_token_stays_allowed(self) -> None:
        result = sfm.find_protected_mention_detail(
            "cat secret*.py", sfm.DEFAULT_PROTECTED_PATTERNS, cwd="/tmp"
        )
        assert result is None


class TestContentContextSkipsAggressiveGlobIntersection:
    """n466-n24 review 4 addendum, false-positive fold-in: a Python
    unpacking-plus-subscript token (``*words[subcommand_index``, from a real
    list literal ``[*words[:subcommand_index], ...]``) is glob-shaped by the
    crude tokeniser's own delimiter split, but names no real path and no
    shell will ever expand it -- it is not Bash text at all. The AGGRESSIVE
    glob-shaped heuristics (edge-overlap, DP intersection -- both-edges
    included, per m-2 -- and the both-edges FS-truth route) are Bash-only;
    ``context="content"`` restricts Write/Edit content scanning to the
    literal matcher, per team-lead's explicit remedy: "the aggressive glob
    intersection is for Bash command words, which the shell really
    expands."""

    def test_the_reported_python_unpacking_snippet_is_allowed_as_content(self) -> None:
        content = "combined = [*words[:subcommand_index], extra_word]\n"
        result = sfm.find_protected_mention_detail(
            content, sfm.DEFAULT_PROTECTED_PATTERNS, context="content"
        )
        assert result is None

    def test_the_same_snippet_denies_on_the_bash_route(self) -> None:
        """Control: this is a context-gated allowance, not a blanket one --
        confirms the default context is unaffected (though this specific
        shape happens not to trip the bash-route heuristics either, since
        the unclosed-bracket residue fix (a) also applies there)."""
        content = "combined = [*words[:subcommand_index], extra_word]\n"
        result = sfm.find_protected_mention_detail(content, sfm.DEFAULT_PROTECTED_PATTERNS)
        assert result is None

    def test_an_interior_wildcard_glob_denies_under_bash_context_regardless_of_source(
        self,
    ) -> None:
        """Review 5: pins that ``context="bash"`` is not a per-language
        exemption -- it is what the HANDLER now selects for anything a shell
        genuinely executes (a typed Bash command, but also authored `.sh`/
        `.bash`/Makefile/CI-YAML/shebang-shell content, per MAJOR-2's
        scoping in secret_file_guard.py). The SAME interior-wildcard text
        denies identically whether it arrived as a typed command or as
        script content scanned with ``context="bash"`` -- there is no
        content-shaped carve-out at the module level, only a caller-selected
        context. ``context="content"`` stays the narrow exemption it always
        was, for source that is genuinely NOT shell text (see the sibling
        test below)."""
        text = "cat prod.vault-passw*rd"
        assert sfm.find_protected_mention_detail(text, sfm.DEFAULT_PROTECTED_PATTERNS) is not None
        assert (
            sfm.find_protected_mention_detail(
                text, sfm.DEFAULT_PROTECTED_PATTERNS, context="bash"
            )
            is not None
        )

    def test_the_same_glob_as_a_python_string_literal_stays_allowed_under_content_context(
        self,
    ) -> None:
        """The genuinely context-dependent case: the identical text, quoted
        as a Python string literal, is source code in a non-shell language
        -- no shell will ever expand it -- so ``context="content"`` (what
        secret_file_guard.py now selects only for non-shell-executed
        content) must not run the aggressive glob-shaped heuristics on it."""
        source_line = "pattern = 'prod.vault-passw*rd'\n"
        assert (
            sfm.find_protected_mention_detail(
                source_line, sfm.DEFAULT_PROTECTED_PATTERNS, context="content"
            )
            is None
        )

    def test_a_quoted_literal_mention_still_denies_as_content(self) -> None:
        content = 'x = open(".vault-password")\n'
        result = sfm.find_protected_mention_detail(
            content, sfm.DEFAULT_PROTECTED_PATTERNS, context="content"
        )
        assert result is not None

    def test_a_script_brace_sequence_mention_still_denies_as_content(self) -> None:
        """The literal matcher still catches a script's own protected-name
        reference after brace-sequence expansion decodes it to the exact
        name -- content scanning is restricted, not disabled."""
        content = "cat id_rs{a..a}\n"
        result = sfm.find_protected_mention_detail(
            content, sfm.DEFAULT_PROTECTED_PATTERNS, context="content"
        )
        assert result is not None

    def test_a_both_edges_interior_question_mark_glob_stays_allowed_as_content(self) -> None:
        """The both-edges textual intersection (m-2) is itself Bash-only for
        the identical reason -- a code token is not a shell word, so a
        string literal that happens to look like a ``?``-only interior
        truncation must not deny under content scanning."""
        content = "pattern = 'demo.se?ret'\n"
        assert (
            sfm.find_protected_mention_detail("cat demo.se?ret", sfm.DEFAULT_PROTECTED_PATTERNS)
            is not None
        )
        result = sfm.find_protected_mention_detail(
            content, sfm.DEFAULT_PROTECTED_PATTERNS, context="content"
        )
        assert result is None


class TestUnclosedBracketResidueIsLiteral:
    """n466-n24 review 4 addendum, false-positive fold-in a: a ``[`` with no
    matching ``]`` INSIDE the token is not a bracket class -- bash, like
    ``fnmatch``, reads an unterminated bracket expression as a literal
    character. ``_token_literal_residue`` used to strip it anyway (it was
    listed in ``_GLOB_CHARS``, the same table used to compute a PATTERN's
    stem), silently shortening a token's residue for no linguistic reason."""

    def test_unmatched_bracket_survives_in_the_residue(self) -> None:
        assert sfm._token_literal_residue("*words[subcommand_index") == "words[subcommand_index"

    def test_a_complete_bracket_expression_is_still_removed_whole(self) -> None:
        assert sfm._token_literal_residue("id_r[sx]a") == "id_ra"


class TestBothEdgesFilesystemTruthRoute:
    """M2c (Plan 00466 guard-defects review 2): a both-edges pattern
    (``*.secret*``, ``*vault_pass*``) asserts only "contains this text
    anywhere", so an interior-wildcard spelling of it stays deliberately
    unreachable through the edge-overlap heuristic -- that check is gated on
    an open edge by construction, exactly so it does not re-litigate the
    N4/m1 false positives.

    m-2 (n466-n24 review 4 addendum) folded a ``?``-only interior spelling
    INTO the textual DP intersection (``_glob_intersection_mention``,
    gated by ``_dp_intersection_is_meaningful``'s both-edges branch): a
    ``?`` can only absorb one character, so a genuine intersection needs the
    token's literal text to closely resemble the stem already -- a real
    signal, denied whatever exists on disk or in which cwd. A token
    carrying its own ``*`` stays excluded from that textual test (a both-
    edges pattern's own wildcards can absorb an arbitrary run on either side
    of an inserted literal, so ANY ``*``-bearing token trivially
    "intersects" -- Plan 00306/00311's own false-positive class,
    ``report-[0-9]*.txt``/``secret*.py``), so THIS class is what the
    filesystem is still the one oracle for: expand the token's glob against
    the HOOK's cwd (passed explicitly here, never the daemon process's own)
    and deny only when a REAL protected-shaped file is what it names.
    """

    def test_interior_question_mark_spelling_denies_textually_with_no_real_file(self) -> None:
        """m-2: the ``?``-only case denies from the token's text alone,
        independent of whether the file exists."""
        result = sfm.find_protected_mention_detail(
            "cat demo.se?ret", sfm.DEFAULT_PROTECTED_PATTERNS, cwd="/tmp"
        )
        assert result is not None
        assert result[0] == "*.secret*"

    def test_interior_question_mark_spelling_denies_when_the_file_is_real(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "demo.secret").write_text("x")
        result = sfm.find_protected_mention_detail(
            "cat demo.se?ret", sfm.DEFAULT_PROTECTED_PATTERNS, cwd=str(tmp_path)
        )
        assert result is not None
        assert result[0] == "*.secret*"

    def test_interior_star_spelling_denies_when_the_file_is_real(self, tmp_path: Path) -> None:
        (tmp_path / "demo.secret").write_text("x")
        result = sfm.find_protected_mention_detail(
            "cat demo.s*t", sfm.DEFAULT_PROTECTED_PATTERNS, cwd=str(tmp_path)
        )
        assert result is not None
        assert result[0] == "*.secret*"

    def test_vault_pass_interior_spelling_denies_when_the_file_is_real(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "vault_passwords.yml").write_text("x")
        result = sfm.find_protected_mention_detail(
            "cat vault?passwords.yml", sfm.DEFAULT_PROTECTED_PATTERNS, cwd=str(tmp_path)
        )
        assert result is not None
        assert result[0] == "*vault_pass*"

    def test_a_star_glob_that_expands_to_nothing_does_not_deny(self, tmp_path: Path) -> None:
        """No real file named this way exists here -- a glob to nothing
        reads nothing, so there is genuinely no disclosure to stop. Uses the
        ``*`` spelling specifically (m-2): that shape is EXCLUDED from the
        textual DP by design, so this still tests the FS route's own
        allow-on-no-match behaviour, unlike the ``?`` spelling which now
        denies textually regardless of what this test's tmp_path holds."""
        result = sfm.find_protected_mention_detail(
            "cat demo.s*t", sfm.DEFAULT_PROTECTED_PATTERNS, cwd=str(tmp_path)
        )
        assert result is None


class TestExpandGlobTokenErrorHandling:
    """n466-n24 review 4: ``_expand_glob_token`` must fail CLOSED (propagate)
    on an expansion failure it cannot prove is a non-match -- except the one
    narrow case that genuinely proves a negative: ENOENT on a directory
    prefix that simply is not there."""

    def test_a_missing_directory_prefix_allows(self, tmp_path: Path) -> None:
        """A literal directory prefix that does not exist on disk proves,
        by itself, that nothing under it can be a mention -- no exception
        needed to reach that verdict, but it must still return ``None``
        rather than raise."""
        result = sfm._expand_glob_token(
            "nonexistent_prefix_xyz/secret.txt",
            sfm.DEFAULT_PROTECTED_PATTERNS,
            None,
            cwd=str(tmp_path),
        )
        assert result is None

    def test_enoent_raised_mid_expansion_allows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Forcing an ENOENT (rather than relying on it never firing) pins
        the actual except-branch: it must be swallowed, not propagated."""

        def _raise_enoent(self: Path, pattern: str) -> Iterator[Path]:
            raise OSError(errno.ENOENT, "No such file or directory")
            yield  # pragma: no cover -- makes this a generator function

        monkeypatch.setattr(Path, "glob", _raise_enoent)
        result = sfm._expand_glob_token(
            "somefile.secret", sfm.DEFAULT_PROTECTED_PATTERNS, None, cwd=str(tmp_path)
        )
        assert result is None

    def test_permission_denied_directory_in_the_glob_path_denies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A directory that could not be READ (permission denied) is NOT
        proof of a non-match -- it must propagate, not degrade to
        "no mention", so the caller's fail-closed wrapper denies."""

        def _raise_eacces(self: Path, pattern: str) -> Iterator[Path]:
            raise PermissionError(errno.EACCES, "Permission denied")
            yield  # pragma: no cover -- makes this a generator function

        monkeypatch.setattr(Path, "glob", _raise_eacces)
        with pytest.raises(PermissionError):
            sfm._expand_glob_token(
                "somefile.secret", sfm.DEFAULT_PROTECTED_PATTERNS, None, cwd=str(tmp_path)
            )

    def test_a_malformed_pattern_value_error_always_denies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``ValueError`` (a malformed glob pattern) is never a proof of
        absence -- always propagates, with no ENOENT-style exception."""

        def _raise_value_error(self: Path, pattern: str) -> Iterator[Path]:
            raise ValueError("malformed glob pattern")
            yield  # pragma: no cover -- makes this a generator function

        monkeypatch.setattr(Path, "glob", _raise_value_error)
        with pytest.raises(ValueError):
            sfm._expand_glob_token(
                "somefile.secret", sfm.DEFAULT_PROTECTED_PATTERNS, None, cwd=str(tmp_path)
            )


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


class TestNestedDashCAndEvalCommandsDeny:
    """n466-n24 review 5 minor-1: `bash -c '…'`/`sh -c '…'`/`eval '…'` whose
    ARGUMENT spells a protected name across a nested quote splice -- the
    argument only reveals the real filename on a SECOND decode pass, which
    :func:`shell_expansion.iter_normalised_shell_words` now performs
    recursively (bounded by depth and by bytes)."""

    def test_the_reported_bash_dash_c_nested_splice_denies(self) -> None:
        command = "bash -c 'cat id_'\\''rs'\\''a'"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_the_equivalent_eval_nested_splice_denies(self) -> None:
        command = "eval 'cat id_'\\''rs'\\''a'"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_two_levels_of_bash_dash_c_nesting_denies(self) -> None:
        """RED test requested by team-lead: two levels of nesting."""
        inner = "bash -c 'cat id_'\\''rs'\\''a'"
        escaped_inner = inner.replace("'", "'\\''")
        command = f"bash -c '{escaped_inner}'"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_mixed_double_and_single_quoting_denies(self) -> None:
        """RED test requested by team-lead: mixed quoting."""
        command = "bash -c \"cat id_'rs'a\""
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_an_unrelated_bash_dash_c_command_stays_allowed(self) -> None:
        command = "bash -c 'echo hello world'"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is None


class TestReview6ClosedShellFeedShapes:
    """n466-n24 review 6: closes the two "accepted simplifications" from
    minor-1 (a flag between the interpreter and `-c`; `eval` joining only
    its first argument word) as real, verified defects, plus three more
    literal-content-to-a-shell shapes team-lead named explicitly."""

    def test_a_flag_between_interpreter_and_dash_c_denies(self) -> None:
        command = "bash -x -c 'cat id_'\\''rs'\\''a'"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_bash_lc_clustered_denies(self) -> None:
        command = "bash -lc 'cat id_'\\''rs'\\''a'"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_an_arg_taking_option_before_dash_c_denies(self) -> None:
        command = "bash -O extglob -c 'cat id_'\\''rs'\\''a'"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_eval_with_several_words_denies(self) -> None:
        """Team-lead's own example: `eval cat id_\\'rs\\'a`."""
        command = "eval cat id_\\'rs\\'a"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_eval_with_two_double_quoted_words_denies(self) -> None:
        command = 'eval "cat" "id_\'rs\'a"'
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_eval_after_builtin_prefix_denies(self) -> None:
        command = "builtin eval cat id_\\'rs\\'a"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_eval_after_command_prefix_denies(self) -> None:
        command = "command eval cat id_\\'rs\\'a"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_source_process_substitution_of_a_literal_echo_denies(self) -> None:
        command = "source <(echo cat id_'\\''rs'\\''a')"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_source_process_substitution_of_a_non_literal_producer_with_no_mention_allows(
        self,
    ) -> None:
        """review 6 MAJOR-2: a non-literal producer's own command text is
        judged like any other nested command -- `cat somefile` mentions
        nothing protected, so this is no longer failed closed just for
        being an unrecognised producer."""
        assert (
            sfm.find_protected_mention_detail(
                "source <(cat somefile)", sfm.DEFAULT_PROTECTED_PATTERNS
            )
            is None
        )

    def test_source_process_substitution_of_a_non_literal_producer_with_a_protected_argument_denies(
        self,
    ) -> None:
        """The other half of MAJOR-2: a non-literal producer's OWN command
        text is still scanned, so a protected path IN that text is caught."""
        command = "source <(cat id_'\\''rs'\\''a')"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_source_process_substitution_of_a_completion_line_allows(self) -> None:
        """The false positive review 6 MAJOR-2 exists to fix: common
        shell-completion setup lines must not be denied wholesale."""
        for command in (
            "source <(kubectl completion bash)",
            "source <(gh completion -s bash)",
            "source <(helm completion bash)",
            "eval \"$(pip completion --bash)\"",
        ):
            assert (
                sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is None
            ), command

    def test_a_here_string_to_a_shell_denies(self) -> None:
        command = "bash <<<'cat id_'\\''rs'\\''a'"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_a_literal_echo_piped_to_a_shell_denies(self) -> None:
        command = "echo cat id_'\\''rs'\\''a' | bash"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None


class TestReview7CommandSubstitutionMentions:
    """Plan 00466 guard-defects review 7 MAJOR-2: `$(...)` and a backtick
    span are re-parsed as their own nested command, end to end through
    `find_protected_mention_detail`."""

    def test_dollar_paren_bash_dash_c_denies(self) -> None:
        command = "x=$(bash -c 'cat id_'\\''rs'\\''a')"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_backtick_bash_dash_c_denies(self) -> None:
        command = "echo `bash -c 'cat id_'\\''rs'\\''a'`"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_dollar_paren_with_no_mention_allows(self) -> None:
        assert (
            sfm.find_protected_mention_detail("x=$(date +%s)", sfm.DEFAULT_PROTECTED_PATTERNS)
            is None
        )


class TestReview7PipeWrapperMentions:
    """Plan 00466 guard-defects review 7 MAJOR-3: a pipe-to-shell wrapper's
    own options/positionals, `cat`-as-passthrough, and an output process
    substitution, end to end."""

    def test_sudo_dash_u_before_shell_denies(self) -> None:
        command = "echo cat id_'\\''rs'\\''a' | sudo -u root bash"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_timeout_with_duration_before_shell_denies(self) -> None:
        command = "echo cat id_'\\''rs'\\''a' | timeout 5 bash"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_cat_passthrough_with_no_argument_denies(self) -> None:
        command = "echo cat id_'\\''rs'\\''a' | cat | bash"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_output_process_substitution_denies(self) -> None:
        command = "echo cat id_'\\''rs'\\''a' > >(bash)"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_cat_here_string_piped_to_shell_denies(self) -> None:
        command = "cat <<< 'cat id_'\\''rs'\\''a' | bash"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_ordinary_sudo_command_allows(self) -> None:
        """Control: an ordinary sudo-wrapped, non-shell command allows."""
        assert (
            sfm.find_protected_mention_detail("sudo -u deploy ls -la", sfm.DEFAULT_PROTECTED_PATTERNS)
            is None
        )


class TestFileSchemeUrlMentions:
    """review 7: a `file:` URL is a real, literal local-file READ route
    (curl, wget, a Python urllib one-liner, `git clone file://...`, ...) in
    a DIFFERENT spelling than a plain bash token -- percent-decoded, with
    the scheme and an optional `localhost` host stripped, then judged
    exactly like any other path mention."""

    def test_curl_triple_slash_unencoded_denies(self) -> None:
        command = "curl -s file:///root/.ssh/id_rsa"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_curl_percent_encoded_basename_denies(self) -> None:
        command = "curl -s file:///root/.ssh/id_r%73a"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_wget_file_url_denies(self) -> None:
        command = "wget file:///root/.ssh/id_rsa"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_file_url_with_localhost_host_denies(self) -> None:
        command = "curl file://localhost/root/.ssh/id_rsa"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_git_clone_file_url_denies(self) -> None:
        command = "git clone file:///root/.ssh/id_rsa /tmp/x"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_python_urllib_one_liner_denies(self) -> None:
        command = "python3 -c \"import urllib.request; urllib.request.urlopen('file:///root/.ssh/id_rsa')\""
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_file_url_to_a_non_protected_path_allows(self) -> None:
        """Control: the route works, but a `file:` URL naming an ordinary
        path is not itself a protected-path mention."""
        command = "curl -s file:///etc/hostname"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is None

    def test_uppercase_scheme_denies(self) -> None:
        """Review 7 MAJOR-4: URL schemes are case-insensitive (RFC 3986),
        and curl accepts `FILE://` exactly like `file://`."""
        command = "curl FILE:///root/.ssh/id_rsa"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_mixed_case_scheme_denies(self) -> None:
        command = "curl File:///root/.ssh/id_rsa"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_url_split_by_single_quote_denies(self) -> None:
        """Review 7 MAJOR-4: a URL split by shell quoting never appears as
        one contiguous `file:...` span in the RAW text -- only the
        quote-decoded word reassembles it."""
        command = "curl 'file:///root/.ssh/id_r'sa"
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None

    def test_url_split_by_double_quote_denies(self) -> None:
        command = 'curl file:///root/.ssh/id_r"sa"'
        assert sfm.find_protected_mention_detail(command, sfm.DEFAULT_PROTECTED_PATTERNS) is not None
