"""Matching core for the secret_file_guard handler (Plan 00272).

Three concerns, all pure functions so the handler stays orchestration-only:

- **Protected-pattern resolution** — shipped defaults merged with project
  config under the daemon's ``mode: additive | replace`` convention
  (``command_hints`` precedent; an unknown mode fails CLOSED toward more
  protection, i.e. behaves as ``additive``).
- **Path matching** — gitignore-style globs via the shared
  ``utils/path_exclusion`` dialect, plus realpath resolution so a symlink to a
  protected target (the ``worktree_create`` seeding case) is matched on BOTH
  spellings.
- **Bash path-mention detection** — deny-by-default in the ``sed_blocker``
  style: any shell token that names (or could glob-expand to) a protected
  path counts as a mention, whatever the surrounding command. The only
  exemptions are the ``secret-meta`` metadata helper and allowlisted
  consumers with the path strictly in flag position.

Honest limits (documented, not hand-waved): string-assembled paths
(``cat .vault-"pass"``), cross-invocation shell state, and pre-existing
scripts that open the file internally are NOT detectable at command-text
level — see the plan's RESEARCH-read-routes.md class-(d) rows.
"""

import fnmatch
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml

from claude_code_hooks_daemon.utils.path_exclusion import (
    path_matches_globs,
    resolve_project_root,
)

logger = logging.getLogger(__name__)

# ── Config modes (additive/replace paradigm, mirrors command_hints) ──────────
MODE_ADDITIVE: Final[str] = "additive"
MODE_REPLACE: Final[str] = "replace"

# Shipped default protected globs (Plan 00272 Decision 7). Deliberately a
# SHORT conservative list: vault-password shapes, any name containing
# ``.secret`` (user directive — covers the daemon's own
# ``.claude/block-words.secret``), and the classic SSH private-key names.
# ``*.pem``/``*.key`` are deliberately absent: public certs share those
# extensions and blanket-protecting them would break real workflows — a human
# adds them per-project via ``protected_paths``.
DEFAULT_PROTECTED_PATTERNS: Final[tuple[str, ...]] = (
    "*.secret*",
    ".vault-pass*",
    "*.vault-password",
    "*vault_pass*",
    "id_rsa",
    "id_ed25519",
)

# Delimiters that end a shell WORD for mention-detection purposes. Quotes are
# included so `open('.vault-pass')` and `"$HOME/.vault-pass"` both yield a
# clean path token; `=` so `P=.vault-pass` yields the assigned value.
_TOKEN_DELIMITERS: Final[str] = " \t\n\"'`;|&<>()=$,"

# Known home-style prefixes stripped from a token before glob matching, so
# `~/.vault-pass` and `$HOME/.vault-pass` reduce to the protected name.
_HOME_PREFIXES: Final[tuple[str, ...]] = ("~/", "$HOME/", "${HOME}/", "$PWD/", "${PWD}/")

# Shell command separators: an exempt invocation must be a SINGLE command —
# a compound command gets no exemption even when one segment would qualify.
_COMMAND_SEPARATORS: Final[tuple[str, ...]] = (";", "&&", "||", "|", "\n")

# Process substitution hands the file's CONTENT to the outer command, so a
# path inside `<(...)` is never "flag position" (draft-review finding 3).
_PROCESS_SUBSTITUTION: Final[str] = "<("

_GLOB_CHARS: Final[tuple[str, ...]] = ("*", "?", "[")
# Wildcard-position detection (leading edge opens an arbitrary prefix,
# trailing edge an arbitrary suffix) lives in `_has_leading_wildcard` /
# `_has_trailing_wildcard` — a bracket only counts as a wildcard when it
# forms a COMPLETE expression (Plan 00305 Task 2.5), which a fixed char
# tuple cannot express.

# The metadata helper: the ONE universally-exempt way to mention a protected
# path in Bash. Recognised as `<anything>/hooks-daemon secret-meta ...` (or a
# bare `hooks-daemon`), so both the project wrapper and a PATH install work.
_HELPER_EXECUTABLE: Final[str] = "hooks-daemon"
SECRET_META_SUBCOMMAND: Final[str] = "secret-meta"

# `git rm --cached <path>` reads no content -- it only stops tracking a file
# (the exact hygiene `secret_file_hygiene_checker` recommends for a
# git-tracked protected path), so it is exempt the same way the secret-meta
# helper is (Plan 00306 Task 1.3). Plain `git rm` (no `--cached`) also
# deletes the working-tree file and stays denied -- it is a different,
# more destructive operation this exemption must not cover.
_GIT_EXECUTABLE: Final[str] = "git"
_GIT_RM_SUBCOMMAND: Final[str] = "rm"
_GIT_RM_CACHED_FLAG: Final[str] = "--cached"

_CONSUMER_KEY_COMMAND: Final[str] = "command"
_CONSUMER_KEY_PATH_FLAGS: Final[str] = "path_flags"
_CONSUMER_KEY_DENIED_SUBCOMMANDS: Final[str] = "denied_subcommands"

_ANSIBLE_VAULT_PASSWORD_FLAGS: Final[tuple[str, ...]] = (
    "--vault-password-file",
    "--vault-pass-file",
    "--vault-id",
)

# ``ansible-vault view|decrypt`` exist to PRINT decrypted secret material to
# stdout — allowlisting them would sanction the most direct disclosure path
# while denying `cat` (draft-review finding 3), so they are denied by name.
_ANSIBLE_VAULT_DENIED_SUBCOMMANDS: Final[tuple[str, ...]] = ("view", "decrypt")


@dataclass(frozen=True)
class ConsumerSpec:
    """An allowlisted consumer: may receive a protected path in flag position."""

    command: str
    path_flags: tuple[str, ...]
    denied_subcommands: tuple[str, ...] = field(default=())


DEFAULT_ALLOWED_CONSUMERS: Final[tuple[ConsumerSpec, ...]] = (
    ConsumerSpec(
        command="ansible-vault",
        path_flags=_ANSIBLE_VAULT_PASSWORD_FLAGS,
        denied_subcommands=_ANSIBLE_VAULT_DENIED_SUBCOMMANDS,
    ),
    ConsumerSpec(command="ansible-playbook", path_flags=_ANSIBLE_VAULT_PASSWORD_FLAGS),
    ConsumerSpec(command="ansible", path_flags=_ANSIBLE_VAULT_PASSWORD_FLAGS),
)


# Process-lifetime cache for the live secret_file_guard config (Plan 00272
# Task 4.5), mirroring ``secret_redaction._resolve_active_path``'s contract:
# other daemon-owned outputs (payload capture, lint diagnostics) need the
# SAME effective protected-path set without importing the handler directly,
# and config changes in this daemon are only ever picked up on restart, so
# re-deriving this on every hot-path call would be a real cost for no gain.
_CONFIGURED_PATTERNS_RESOLVED: bool = False
_CONFIGURED_PATTERNS: tuple[str, ...] = DEFAULT_PROTECTED_PATTERNS


def resolve_configured_patterns() -> tuple[str, ...]:
    """Effective protected globs from the live ``secret_file_guard`` config.

    Fails open to the SHIPPED DEFAULTS (never an empty tuple) when
    ``ProjectContext`` is not initialised or config cannot be loaded — this
    is a residual-route seam-closer (payload capture, lint diagnostics), not
    the guard itself, so a resolution failure must still protect the
    defaults rather than silently disabling protection.
    """
    global _CONFIGURED_PATTERNS_RESOLVED, _CONFIGURED_PATTERNS
    if _CONFIGURED_PATTERNS_RESOLVED:
        return _CONFIGURED_PATTERNS

    _CONFIGURED_PATTERNS_RESOLVED = True
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    if not ProjectContext.is_initialized():
        return _CONFIGURED_PATTERNS

    try:
        from claude_code_hooks_daemon.config.models import Config, HandlerConfig

        config = Config.load_or_default(ProjectContext.config_path())
        handler_cfg = config.handlers.pre_tool_use.get("secret_file_guard")
        # ``Config``'s own ``coerce_handler_configs`` validator turns every
        # entry into a ``HandlerConfig`` instance (not a plain dict) once the
        # config has been loaded through the model -- ``.options`` is the
        # correct access, and a stray ``isinstance(..., dict)`` guard here
        # silently found nothing and fell through to the shipped defaults on
        # every real config, never actually reading a project's settings.
        options = handler_cfg.options if isinstance(handler_cfg, HandlerConfig) else {}
        mode = options.get("mode")
        project_patterns = options.get("protected_paths")
        _CONFIGURED_PATTERNS = resolve_protected_patterns(mode, project_patterns)
    except (OSError, RuntimeError, ValueError, yaml.YAMLError) as exc:
        # OSError: unreadable config file. RuntimeError: ProjectContext-adjacent
        # failures. ValueError: Config.load's own "unsupported format" AND
        # pydantic's ValidationError (a ValueError subclass) for a
        # schema-invalid config. yaml.YAMLError: malformed YAML -- Config.load
        # calls yaml.safe_load directly and does not catch this itself. All
        # four leave the SHIPPED DEFAULTS already set above in place.
        logger.debug("Could not resolve secret_file_guard config, using defaults: %s", exc)
    return _CONFIGURED_PATTERNS


def reset_configured_patterns_cache() -> None:
    """Clear the process-lifetime resolved-patterns cache. Test-only escape hatch."""
    global _CONFIGURED_PATTERNS_RESOLVED, _CONFIGURED_PATTERNS
    _CONFIGURED_PATTERNS_RESOLVED = False
    _CONFIGURED_PATTERNS = DEFAULT_PROTECTED_PATTERNS


def resolve_protected_patterns(
    mode: str | None, project_patterns: list[str] | None
) -> tuple[str, ...]:
    """Effective protected globs under the additive/replace convention.

    ``additive`` (default, and any unrecognised mode — fail closed toward
    MORE protection) merges project patterns onto the shipped defaults;
    ``replace`` uses ONLY the project list.
    """
    project = tuple(p for p in (project_patterns or []) if p)
    if mode == MODE_REPLACE:
        return project
    merged: list[str] = list(DEFAULT_PROTECTED_PATTERNS)
    for pattern in project:
        if pattern not in merged:
            merged.append(pattern)
    return tuple(merged)


def merge_allowed_consumers(
    project_consumers: list[dict[str, Any]] | None,
) -> tuple[ConsumerSpec, ...]:
    """Shipped consumer allowlist plus project-configured entries (additive)."""
    merged: list[ConsumerSpec] = list(DEFAULT_ALLOWED_CONSUMERS)
    for entry in project_consumers or []:
        command = str(entry.get(_CONSUMER_KEY_COMMAND, "")).strip()
        if not command:
            continue
        merged.append(
            ConsumerSpec(
                command=command,
                path_flags=tuple(str(f) for f in entry.get(_CONSUMER_KEY_PATH_FLAGS, [])),
                denied_subcommands=tuple(
                    str(s) for s in entry.get(_CONSUMER_KEY_DENIED_SUBCOMMANDS, [])
                ),
            )
        )
    return tuple(merged)


def path_is_protected(file_path: str, patterns: tuple[str, ...]) -> bool:
    """True when ``file_path`` (or its realpath) matches a protected glob.

    The realpath check covers the symlink seeding case: the link path can be
    innocuous while the target is protected, and vice versa — both spellings
    must be guarded or the symlink is a one-call bypass.
    """
    if not file_path or not patterns:
        return False
    project_root = resolve_project_root()
    if path_matches_globs(file_path, patterns, project_root=project_root):
        return True
    try:
        real = os.path.realpath(file_path)
    except OSError:
        return False
    if real != file_path:
        return path_matches_globs(real, patterns, project_root=project_root)
    return False


def _tokenise(command: str) -> list[str]:
    """Split a command string into candidate path WORDS.

    Deliberately crude: this is mention detection, not shell parsing. Every
    run of non-delimiter characters is a candidate token, so paths inside
    quotes, substitutions, assignments and interpreter one-liners all
    surface. False positives are acceptable (deny-by-default); false
    negatives are the enumerated class-(c)/(d) limits.
    """
    pattern = "[" + re.escape(_TOKEN_DELIMITERS.replace("\n", "")) + "\\n]+"
    return [token for token in re.split(pattern, command) if token]


#: A Python import statement's dotted MODULE path. Anchored per line, and the
#: grammar admits only identifier characters and dots -- notably no ``/``,
#: which is what makes the exemption below unable to hide a filesystem path.
_IMPORT_MODULE_RE: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*(?:from|import)[ \t]+([A-Za-z_][A-Za-z0-9_.]*)", re.MULTILINE
)


def _without_import_module_paths(command: str) -> str:
    """``command`` with the dotted module path of each import statement removed.

    A module path is not a filesystem path, and importing a module cannot
    read a file -- so a module whose dotted name happens to contain a
    protected stem is not a mention. The shipped ``*.secret*`` default
    substring-matches ``...pre_tool_use.secret_file_guard``, which made it
    impossible to add an import of this package's own guard module to any
    file that was not already on the handler's ``exclude_paths``. A client
    with a ``.secret``-containing module path hits the same wall and cannot
    be expected to enumerate its files.

    The exemption is POSITIONAL: it deletes the span the import statement
    occupies, so the token vanishes only where it was imported. Keying it on
    the token's STRING instead would exempt every later occurrence too, and
    a line of ``import <name>`` prepended to any command would delete that
    name from the matcher's view -- an escape hatch in a guard whose deny
    text states it has none, gating four DENY/suppress surfaces including
    payload capture. ``import`` is not a shell builtin, so such a line fails
    harmlessly while the real command after it runs.

    A slash path still cannot be spelled as a module (the grammar admits no
    ``/``), so a genuine path is untouched by this either way.

    Applied only by :func:`find_protected_mention`, not the ``_strict``
    variant: strict serves the quarantine-artefact globs, whose hyphenated
    markers cannot collide with a Python module name in the first place, so
    changing it would be a fix for a problem it does not have.
    """

    def _drop_module_path(match: re.Match[str]) -> str:
        # Keep the `import `/`from ` lead-in, drop only the module path, so
        # `from a.b import X` still contributes its `X` token.
        return match.group(0)[: match.start(1) - match.start(0)]

    return _IMPORT_MODULE_RE.sub(_drop_module_path, command)


def _normalised_token_forms(token: str) -> list[str]:
    """Spellings of a token to match against protected globs."""
    forms = [token]
    for prefix in _HOME_PREFIXES:
        if token.startswith(prefix):
            forms.append(token[len(prefix) :])
    stripped = token.lstrip("./")
    if stripped and stripped != token and token.startswith("./"):
        forms.append(stripped)
    return forms


def _pattern_literal_stems(patterns: tuple[str, ...]) -> list[tuple[str, str]]:
    """Best-effort ``(stem, pattern)`` pairs, for glob-token checks.

    ``*.secret*`` -> ``.secret``; ``.vault-pass*`` -> ``.vault-pass``. Used to
    catch a GLOB-shaped command token (``cat .vault-p*``) that could expand to
    a protected name — the token-as-glob is matched against these stems.

    Built as PAIRS in one pass (review finding 5): a pattern whose stem is
    empty is dropped WITH its pattern, so the stem checked and the glob
    reported in the deny reason can never desynchronise.
    """
    pairs: list[tuple[str, str]] = []
    for pattern in patterns:
        stem = pattern
        for char in _GLOB_CHARS:
            stem = stem.replace(char, "")
        if stem:
            pairs.append((stem, pattern))
    return pairs


# `!?\]?` (Plan 00306 Task 2.3): the POSIX "literal `]` first" character
# class shape (`x[]]`, matching a literal `]`, optionally negated `x[!]]`) —
# a `]` immediately after `[` (or after `[!]`) is a MEMBER of the class, not
# its closer, so without this the regex closed on that first `]` and treated
# the expression as ending one character early.
_BRACKET_EXPRESSION_RE: Final[re.Pattern[str]] = re.compile(r"\[!?\]?[^\]]*\]")

# Plan 00272 live-probe gap (class-(c) glob truncation, G2): the minimum
# character overlap required at the boundary between a glob token's literal
# residue and a LEADING-WILDCARD protected pattern's literal stem before the
# token is treated as a possible truncation of a real protected basename.
# This overlap test is used ONLY for patterns starting with "*" — see the
# gate at its call site in ``find_protected_mention`` and Decision 12 in
# CLAUDE/Plan/00272-secret-file-read-blocker/PLAN.md for why an exact-filename
# or start-anchored pattern must never reach it (it would only add
# coincidental false positives there; the pre-existing substring+fnmatch
# check already catches every genuine truncation of those).
#
# Even restricted to leading-wildcard patterns, a single-character overlap
# is still coincidental far too often in ordinary project vocabulary — this
# project's own coordinator review caught a first cut of this fix flagging
# common tokens like "sample*"/"grid*"/"id*" purely from a 2-char edge match
# against the EXACT-filename "id_rsa" stem (fixed by the gate above, not by
# raising this threshold — those stems must not use overlap matching at
# all). Two characters is the smallest overlap a LEADING-wildcard shipped
# stem ever needs (".vault-password" truncated to "dummy.v*" needs exactly
# the 2-char ".v" overlap) — see TestBashMentionsProtectedPath in
# tests/unit/utils/test_secret_file_matching.py for the worked cases this
# threshold is tuned against, including the false-positive allowlist the
# coordinator's review added. A single-character generic glob like "d*" is
# accepted residual: it cannot reach this threshold against any shipped
# leading-wildcard stem, by construction, not by a special case.
_MIN_GLOB_OVERLAP_CHARS: Final[int] = 2


def _is_glob_shaped(token: str) -> bool:
    """True when ``token`` carries a genuine fnmatch metacharacter.

    ``*`` and ``?`` are always wildcards. ``[``/``]`` are wildcards only as a
    COMPLETE bracket expression (``_BRACKET_EXPRESSION_RE``) -- fnmatch itself
    treats a lone, unterminated ``[`` as a literal character, and Plan 00305
    Task 2.5 found this handler disagreeing: a Python list literal like
    ``[pass_result, fail_result]`` tokenises (on the comma) into
    ``[pass_result`` and ``fail_result]``, each carrying an unmatched
    bracket. Treating that as glob-shaped let the leading-wildcard overlap
    check compare ``pass_result``'s ``pass`` edge against the
    ``*vault_pass*`` stem and false-fire. Requiring a matched pair closes
    that gap while leaving real bracket expressions (``[Vv]ault_pass``)
    unaffected.
    """
    if "*" in token or "?" in token:
        return True
    return bool(_BRACKET_EXPRESSION_RE.search(token))


def _has_leading_wildcard(basename: str) -> bool:
    """True when ``basename``'s LEFT edge is open to an arbitrary prefix."""
    if basename[:1] in ("*", "?"):
        return True
    # `.match()` is already anchored at position 0 -- `match.start() == 0`
    # can never be False when `match` is not None, so it was dead code
    # (Plan 00306 Task 2.2).
    return _BRACKET_EXPRESSION_RE.match(basename) is not None


def _has_trailing_wildcard(basename: str) -> bool:
    """True when ``basename``'s RIGHT edge is open to an arbitrary suffix."""
    if basename[-1:] in ("*", "?"):
        return True
    return any(match.end() == len(basename) for match in _BRACKET_EXPRESSION_RE.finditer(basename))


def _token_literal_residue(token: str) -> str:
    """The literal text left after removing glob syntax from ``token``.

    Bracket expressions are removed WHOLE (``[A-Za-z]`` contributes nothing),
    then ``*`` and ``?`` are stripped: ``.vault-p*`` -> ``.vault-p``;
    ``[A-Za-z]*`` -> ``''``. The residue is what the token literally asserts
    about a filename, so it is what must overlap a protected stem.
    """
    residue = _BRACKET_EXPRESSION_RE.sub("", token)
    for char in _GLOB_CHARS:
        residue = residue.replace(char, "")
    return residue


def _suffix_prefix_overlap_length(a: str, b: str) -> int:
    """Longest ``k`` such that ``a``'s last ``k`` characters equal ``b``'s
    first ``k`` characters (0 when no such ``k`` exists).

    This models exactly ONE wildcard site joining two literal edges directly
    — the shape of a real truncation (``dummy.vault-p*`` is a real filename
    ``dummy.vault-password`` with everything past ``p`` replaced by ``*``).
    It deliberately does NOT allow an arbitrary filler splice between two
    otherwise-unrelated literal fragments the way a full two-glob language
    intersection would — that weaker test is what a genuinely unrelated
    truncation like ``dummy.txt*`` would need to false-positive on
    ``*.vault-password`` (a hypothetical file ``dummy.txt.vault-password``
    satisfies both globs, but nothing about the token's own characters
    suggests that filename — the ``.txt`` and ``.vault-p...`` never touch).
    """
    max_k = min(len(a), len(b))
    for k in range(max_k, 0, -1):
        if a[-k:] == b[:k]:
            return k
    return 0


def _both_edges_residue_is_near_total_stem_match(residue: str, stem_basename: str) -> bool:
    """True when a both-edges-wildcard token's residue could plausibly
    glob-expand to the whole protected stem, rather than merely sharing a
    coincidental substring with it (Plan 00311 follow-up to Plan 00306; R1
    of the incremental re-review tightened this further).

    A both-edges token (``*word*``) asserts only "contains this text" — most
    of the time that is a plain-English "contains" search, not a truncation
    of one specific protected filename, and Plan 00306 correctly stopped
    treating every such token as a match (``*secret_file*matching*`` sharing
    ``secret`` with the ``.secret`` stem; ``*word*`` sharing ``word`` with the
    tail of ``.vault-password``). But an unconditional exclusion goes too
    far: a residue that genuinely spells out the stem, or an initial/final
    run of it, still glob-expands to the real protected file and must stay
    denied.

    **The discriminator, chosen after a length-difference rule (``<= 1``
    char) proved too narrow** (it restored the deny direction only for a
    residue exactly one character short of the stem, leaving every other
    genuine truncation/extension open — five distinct probe shapes against
    a synthetic pattern, live-verified): both ``residue`` and ``stem_basename``
    are reduced to their "core" by stripping a single leading boundary
    character (``.``, the common case for this project's dot-leading
    stems), then judged by which side is the anchor:

    - **Truncation** (``residue`` no longer than the stem core): denied when
      the residue is a literal PREFIX of the stem core (``ZQZ`` is a prefix
      of ``ZQZ-fshape``) — an arbitrary-length leading run of the real
      filename, however short, since the token's own trailing wildcard can
      absorb the rest. Deliberately NOT a suffix check in this direction —
      that is exactly the Plan 00306 false-positive shape (``word`` is a
      suffix of ``vault-password`` purely by English-word coincidence, not
      because anyone is truncating the real filename from the front).
    - **Extension** (``residue`` longer than the stem core): denied when the
      stem core is a literal SUFFIX of the residue (``dummy.ZQZ-fshape``
      ends with ``ZQZ-fshape``) — the token already contains a real matching
      filename verbatim, with arbitrary junk glued in front. Deliberately
      NOT a prefix check in this direction — that is the mirror-image false
      positive (``secret_filematching`` starts with ``secret`` purely
      because a source filename happens to start with that word, not
      because it truncates any protected name).

    Below ``_MIN_GLOB_OVERLAP_CHARS`` neither side is trusted, for the same
    reason the single-edge overlap check requires it (see that constant's
    docstring) — a one-character coincidental anchor is too generic. This
    swaps false-negative risk for false-positive risk on the rare ambiguous
    case (e.g. a token whose residue happens to be a genuine short prefix of
    ``secret``) — deliberately, since a rare over-block on a secret-adjacent
    guard is far cheaper than a silent leak.
    """
    if not residue or not stem_basename:
        return False
    stem_core = stem_basename.lstrip(".")
    residue_core = residue.lstrip(".")
    if len(residue_core) < _MIN_GLOB_OVERLAP_CHARS or not stem_core:
        return False
    if len(residue_core) <= len(stem_core):
        return stem_core.startswith(residue_core)
    return residue_core.endswith(stem_core)


def _glob_token_overlaps_stem(
    residue: str,
    stem_basename: str,
    *,
    leading_wildcard: bool,
    trailing_wildcard: bool,
) -> bool:
    """True when ``residue``'s literal edge could directly join ``stem_basename``.

    Each direction models exactly one wildcard SITE and is gated on the token
    actually carrying a wildcard THERE — without that gate a token whose
    residue merely shares a coincidental edge with the stem is flagged even
    though it is no truncation of any protected name (observed live: ``assert.*``
    shares ``ass`` with the ``vault_pass`` stem, ``secret*.py`` shares
    ``secret`` with the ``.secret`` stem — neither has the wildcard at the
    edge that would make the overlap a real truncation):

    - A TRAILING-wildcard token (``dummy.vault-p*``) can be extended on the
      RIGHT, so its residue's SUFFIX must overlap the stem's PREFIX (forward).
    - A LEADING-wildcard token (``*passXXX``) can be preceded on the LEFT, so
      the stem's SUFFIX must overlap the residue's PREFIX (reverse).

    A token whose wildcard sits INTERNALLY (``assert.*x``, ``secret*.py``) has
    neither edge open, so neither direction applies. Gated at
    ``_MIN_GLOB_OVERLAP_CHARS`` — see its docstring.

    A token with a wildcard at BOTH edges (``*secret_file*matching*``) only
    counts as a match when the residue is a NEAR-TOTAL match of the stem
    (``_both_edges_residue_is_near_total_stem_match``, Plan 00311) rather than
    a coincidental short-edge overlap — see that helper's docstring for the
    false positive (Plan 00306) and the false negative (Plan 00311) this
    balances. A truncation with only ONE open edge still has a genuinely
    anchored other edge, so those keep using the overlap test as before.
    """
    if leading_wildcard and trailing_wildcard:
        return _both_edges_residue_is_near_total_stem_match(residue, stem_basename)
    if (
        trailing_wildcard
        and _suffix_prefix_overlap_length(residue, stem_basename) >= _MIN_GLOB_OVERLAP_CHARS
    ):
        return True
    if (
        leading_wildcard
        and _suffix_prefix_overlap_length(stem_basename, residue) >= _MIN_GLOB_OVERLAP_CHARS
    ):
        return True
    return False


def find_protected_mention(command: str, patterns: tuple[str, ...]) -> str | None:
    """First protected glob a token of ``command`` mentions, else ``None``.

    A mention is a shell WORD that matches a protected glob (after `~`/`$HOME`
    normalisation and realpath resolution), or a glob-shaped word whose
    expansion could include a protected name. Prose containing the bare word
    ``secret`` never matches — only path-shaped tokens do.
    """
    if not command or not patterns:
        return None
    project_root = resolve_project_root()
    stem_pairs = _pattern_literal_stems(patterns)
    for token in _tokenise(_without_import_module_paths(command)):
        for form in _normalised_token_forms(token):
            for pattern in patterns:
                if path_matches_globs(form, (pattern,), project_root=project_root):
                    return pattern
            if _is_glob_shaped(form):
                basename = form.rsplit("/", maxsplit=1)[-1]
                residue = _token_literal_residue(basename)
                if not residue:
                    continue
                # Where the token's wildcard sits decides which overlap
                # direction is a plausible truncation (see the helper).
                has_leading_wildcard = _has_leading_wildcard(basename)
                has_trailing_wildcard = _has_trailing_wildcard(basename)
                for stem, pattern in stem_pairs:
                    stem_basename = stem.rsplit("/", maxsplit=1)[-1]
                    # Original fnmatch check (v3.55.0 release code review): a
                    # POSIX character class is a regex, not a path glob —
                    # fnmatch('vault_pass', '[A-Za-z]*') is True, so without
                    # the residue gate every stem matched any bracketed
                    # token. The token must share literal text with the stem
                    # (residue is a substring of the stem) before its fnmatch
                    # result counts. This only catches a token whose residue
                    # is a PREFIX-compatible spelling of an anchored-start
                    # stem (e.g. ".vault-p*" vs stem ".vault-pass").
                    #
                    # Plan 00284 live dogfooding find: a residue below
                    # ``_MIN_GLOB_OVERLAP_CHARS`` is too generic to trust —
                    # a bare ``.`` (the residue of a ``.*?`` regex
                    # quantifier token, isolated whenever it sits between
                    # ``<``/``>`` delimiters) is a substring of every
                    # dot-leading stem, and used raw as the fnmatch pattern
                    # it absorbs the rest via its own ``*``/``?``. Reusing
                    # the overlap check's threshold here (not a separate
                    # constant) because both gates encode the identical
                    # concept: how many literal characters are needed
                    # before a partial glob match is trusted as a genuine
                    # truncation rather than coincidence.
                    # Gated on both-edges-wildcard via the NEAR-TOTAL-MATCH
                    # test, not a flat exclusion (Plan 00311 follow-up to
                    # Plan 00306): with a wildcard on BOTH sides,
                    # `fnmatch(stem, basename)` succeeds whenever the residue
                    # occurs ANYWHERE inside the stem, not just as a real
                    # prefix/suffix truncation -- an ordinary "*word*"
                    # contains-glob (or prose emphasis) coincidentally
                    # matching a stem that merely contains that substring
                    # elsewhere (e.g. ``*word*`` against ``.vault-password``,
                    # which ends "...s-s-w-o-r-d") is not evidence of a real
                    # protected filename. But a both-edges token whose residue
                    # effectively SPELLS the stem (``*zzz-passwd*`` against a
                    # ``*.zzz-passwd`` stem) really does glob-expand to the
                    # protected file and must still deny -- see
                    # ``_both_edges_residue_is_near_total_stem_match``.
                    if (
                        len(residue) >= _MIN_GLOB_OVERLAP_CHARS
                        and residue in stem_basename
                        and (
                            not (has_leading_wildcard and has_trailing_wildcard)
                            or _both_edges_residue_is_near_total_stem_match(residue, stem_basename)
                        )
                        and fnmatch.fnmatch(stem_basename, basename)
                    ):
                        return pattern
                    # Plan 00272 gap fix (G2), GATED to leading-wildcard
                    # patterns only (over-blocking regression fix, same
                    # plan): a trailing-wildcard TRUNCATION of a real
                    # protected basename can carry an arbitrary prefix
                    # belonging to the pattern's own LEADING wildcard (e.g.
                    # "dummy.vault-p*" truncates the real file
                    # "dummy.vault-password", matched by "*.vault-password"
                    # whose fixed stem ".vault-password" has no "dummy"
                    # prefix to compare against). The overlap check exists
                    # ONLY for that shape: an exact-filename pattern
                    # ("id_rsa") or a pattern anchored at the START
                    # (".vault-pass*") has NO arbitrary-prefix wildcard for
                    # a token to hide behind, so a genuine truncation of
                    # THOSE patterns is already a literal PREFIX of the stem
                    # and is caught by the fnmatch check above — the overlap
                    # test adds nothing there but false positives (a token
                    # like "sample*" or "id*" sharing a coincidental 2-char
                    # edge with "id_rsa" was denied before this gate).
                    if pattern.startswith("*") and _glob_token_overlaps_stem(
                        residue,
                        stem_basename,
                        leading_wildcard=has_leading_wildcard,
                        trailing_wildcard=has_trailing_wildcard,
                    ):
                        return pattern
        real = _realpath_if_resolvable(token)
        if real is not None:
            for pattern in patterns:
                if path_matches_globs(real, (pattern,), project_root=project_root):
                    return pattern
    return None


def find_protected_mention_strict(command: str, patterns: tuple[str, ...]) -> str | None:
    """First protected glob a token of ``command`` mentions, requiring a REAL
    on-disk match for any glob-shaped token, else ``None``.

    ``find_protected_mention`` treats a glob-shaped token (``.vault-p*``) as a
    possible mention purely from its literal SPELLING, on purpose: for a
    secret, a false positive is cheap and a false negative is not, so
    ``secret_file_guard`` accepts over-blocking (see that function's
    docstring). That trade-off does not hold for every consumer — a quarantine
    artefact glob defaulting to ``*-opus-security-DETAIL*``/``*-opus-security-
    DETAIL.md`` caused an ordinary ``grep -c pattern docs/*.md`` to be denied
    with no DETAIL file anywhere on disk, because the token ``*.md`` fnmatches
    the second seed pattern's literal stem regardless of what actually exists
    (canary-php-qa-ci-upgrade-26-08-30.md, Finding 6). This variant keeps
    literal-token matching identical, but for a GLOB-shaped token it expands
    the glob against the filesystem (project root, then cwd) and only counts
    it as a mention when at least one resulting path is itself protected.
    """
    if not command or not patterns:
        return None
    project_root = resolve_project_root()
    for token in _tokenise(command):
        for form in _normalised_token_forms(token):
            for pattern in patterns:
                if path_matches_globs(form, (pattern,), project_root=project_root):
                    return pattern
            if _is_glob_shaped(form):
                match = _expand_glob_token(form, patterns, project_root)
                if match is not None:
                    return match
        real = _realpath_if_resolvable(token)
        if real is not None:
            for pattern in patterns:
                if path_matches_globs(real, (pattern,), project_root=project_root):
                    return pattern
    return None


def _expand_glob_token(
    token: str, patterns: tuple[str, ...], project_root: str | None
) -> str | None:
    """First protected pattern matched by a file ``token`` actually expands to.

    Tried against each plausible base (the project root, then the process
    cwd — a Bash tool call runs relative to one of these) so a relative glob
    like ``docs/*.md`` is resolved the way the shell would resolve it. An
    absolute token is tried as-is, split into its anchor plus the remaining
    pattern so ``Path.glob`` (which only accepts a RELATIVE pattern) can
    still expand it. A token that expands to nothing, or only to unrelated
    files, returns ``None`` — this is the filesystem-truth check the
    heuristic stem-overlap match in ``find_protected_mention`` does not have.
    """
    token_path = Path(token)
    if token_path.is_absolute():
        search_specs = [(Path(token_path.anchor), str(token_path.relative_to(token_path.anchor)))]
    else:
        bases: list[Path] = []
        if project_root:
            bases.append(Path(project_root))
        cwd = Path.cwd()
        if cwd not in bases:
            bases.append(cwd)
        search_specs = [(base, token) for base in bases]

    seen: set[str] = set()
    for base, pattern_str in search_specs:
        key = f"{base}:{pattern_str}"
        if key in seen:
            continue
        seen.add(key)
        try:
            matches = base.glob(pattern_str)
        except (OSError, ValueError):
            continue
        for match in matches:
            match_str = str(match)
            for pattern in patterns:
                if path_matches_globs(match_str, (pattern,), project_root=project_root):
                    return pattern
    return None


def _realpath_if_resolvable(token: str) -> str | None:
    """Realpath of ``token`` when it names an existing symlink, else None."""
    try:
        is_symlink = Path(token).is_symlink()
    except OSError:
        # A token that cannot be stat-ed (over-long path from prose text) is
        # not a symlink to resolve; matching proceeds on the raw token, so
        # nothing is hidden. Registered in error_hiding_exclusions.json.
        is_symlink = False
    if is_symlink:
        return os.path.realpath(token)
    return None


# Bounded-walk cap for directory-rooted content-search checks. A PreToolUse
# handler runs in the dispatch hot path, so the walk must have a hard ceiling;
# a tree larger than this is NOT fully checked (documented residual — the
# guidance names directory-rooted search as a limit for exactly this reason).
DIRECTORY_SCAN_MAX_ENTRIES: Final[int] = 5000


def directory_contains_protected(
    directory: str, patterns: tuple[str, ...], max_entries: int = DIRECTORY_SCAN_MAX_ENTRIES
) -> str | None:
    """First protected glob matched by any file under ``directory``, else None.

    Best-effort partial enforcement for directory-rooted content search
    (review finding 2): a Grep rooted at an ancestor of a protected file
    reads its content without ever naming it. The walk is BOUNDED by
    ``max_entries`` — once the cap is hit the scan stops and answers None,
    so a huge tree cannot stall dispatch; that residue is a documented
    limit, not a guarantee.
    """
    if not patterns:
        return None
    root = Path(directory)
    if not root.is_dir():
        return None
    project_root = resolve_project_root()
    seen = 0
    for current_dir, _subdirs, files in os.walk(root):
        for name in files:
            seen += 1
            if seen > max_entries:
                return None
            full_path = str(Path(current_dir) / name)
            for pattern in patterns:
                if path_matches_globs(full_path, (pattern,), project_root=project_root):
                    return pattern
    return None


_CD_EXECUTABLE: Final[str] = "cd"
_AND_SEPARATOR: Final[str] = "&&"
# A substitution in the cd TARGET runs a command and puts its output on the
# argument, so `cd $(cat <protected>)` really does disclose. A bare `cd` does
# not, and that difference is the whole basis for stripping the prefix.
_SUBSTITUTION_MARKERS: Final[tuple[str, ...]] = ("$(", "`", "${", _PROCESS_SUBSTITUTION)


def _strip_leading_cd(command: str, patterns: tuple[str, ...]) -> str | None:
    """Remove ONE leading ``cd <dir> &&``, or return ``None`` to leave the
    command untouched.

    A trusted consumer stopped being exempt the moment it was reached via
    ``cd <dir> && ...``, because the compound rule voids the exemption before
    the consumer is ever examined. That shape is not incidental: a tool whose
    project root is resolved by walking up from cwd can only be invoked from
    its own directory. It is the same failing-closed case ``git -C <path>``
    already carries an exemption for.

    The prefix is safe to remove because ``cd`` names a directory and sets
    cwd — it neither reads nor transmits the protected file. Nothing else is
    relaxed: the REMAINDER goes through the unchanged separator and
    process-substitution rules, so a disclosure chained after the consumer is
    still caught by the rule that caught it before.

    Deliberately narrow, because each restriction removes a way to launder a
    command through the prefix:

    * ``&&`` only, not ``;`` — ``&&`` proves the ``cd`` succeeded, so the
      consumer runs where the caller intended.
    * Exactly ``cd`` plus ONE argument. A redirection or extra word is not
      this shape.
    * No substitution in the target (above).
    * The target must not itself be a protected path — not a disclosure, but
      a mistake or a probe, and refusing costs a legitimate caller nothing.
    * Stripped ONCE. Recursion would peel an arbitrary chain one command at a
      time; after one strip a second ``cd`` leaves a separator behind and the
      compound is judged whole.
    """
    head, separator, remainder = command.partition(_AND_SEPARATOR)
    if not separator:
        return None
    words = head.split()
    if len(words) != 2 or words[0] != _CD_EXECUTABLE:
        return None
    target = words[1]
    if any(marker in head for marker in _SUBSTITUTION_MARKERS):
        return None
    if path_is_protected(target.strip("\"'"), patterns):
        return None
    return remainder.strip() or None


def is_exempt_invocation(
    command: str,
    consumers: tuple[ConsumerSpec, ...],
    patterns: tuple[str, ...] = DEFAULT_PROTECTED_PATTERNS,
) -> bool:
    """True when ``command`` is one of the two sanctioned path-mention shapes.

    1. The metadata helper: ``.../hooks-daemon secret-meta <path> ...``.
    2. An allowlisted consumer whose subcommand is not disclosure-purposed,
       with every protected-looking argument in FLAG POSITION (immediately
       following a recognised path flag, or as ``--flag=path``).

    ``patterns`` MUST be the caller's EFFECTIVE protected globs (review
    finding 1): the flag-position check re-tests each bare argument against
    them, and testing the shipped defaults instead would make every
    project-configured pattern — all of them, under ``mode: replace`` —
    invisible here, exempting ``ansible-playbook <protected-file>`` with the
    path in POSITIONAL position. The default exists for callers that really
    do run with the shipped defaults, not as a shortcut.

    An exemption applies only to a SINGLE command: any separator (``;``,
    ``&&``, ``||``, a pipe, a newline) or process substitution voids it —
    the compound as a whole is judged by the deny rule instead. A single
    leading ``cd <dir> &&`` is removed before that judgement (see
    ``_strip_leading_cd``); everything after it faces the unchanged rule.
    """
    stripped = command.strip()
    if not stripped:
        return False
    stripped = _strip_leading_cd(stripped, patterns) or stripped
    if _PROCESS_SUBSTITUTION in stripped:
        return False
    if any(separator in stripped for separator in _COMMAND_SEPARATORS):
        return False

    words = stripped.split()
    if not words:
        return False
    head = words[0].strip("\"'")
    head_base = head.rsplit("/", maxsplit=1)[-1]

    if head_base == _HELPER_EXECUTABLE:
        return len(words) > 1 and words[1] == SECRET_META_SUBCOMMAND

    if head_base == _GIT_EXECUTABLE and _is_git_rm_cached(words):
        return True

    for consumer in consumers:
        if head_base != consumer.command:
            continue
        if _denied_subcommand_used(words, consumer):
            return False
        return _paths_only_in_flag_position(words, consumer, patterns)
    return False


_GIT_C_FLAG: Final[str] = "-C"


def _is_git_rm_cached(words: list[str]) -> bool:
    """True when ``words`` is ``git [-C <path>] rm ... --cached ...`` --
    untrack only.

    Requires the ``rm`` subcommand (immediately after ``git``, or after a
    leading ``-C <path>`` -- Plan 00311 follow-up: an agent working from
    another cwd via ``git -C /repo rm --cached <path>`` is exactly the shape
    ``secret_file_hygiene_checker``'s own recommended remedy takes, and was
    failing CLOSED before this) and ``--cached`` present anywhere after the
    subcommand. No ``--cached`` (or no ``rm``) means the command can delete
    the working-tree file too, so it is not exempt.
    """
    subcommand_index = 1
    if len(words) > 2 and words[1] == _GIT_C_FLAG:
        subcommand_index = 3
    if len(words) < subcommand_index + 2:
        return False
    if words[subcommand_index] != _GIT_RM_SUBCOMMAND:
        return False
    return any(word.strip("\"'") == _GIT_RM_CACHED_FLAG for word in words[subcommand_index + 1 :])


def _denied_subcommand_used(words: list[str], consumer: ConsumerSpec) -> bool:
    """True when the first non-flag argument is a disclosure subcommand."""
    for word in words[1:]:
        if word.startswith("-"):
            continue
        return word in consumer.denied_subcommands
    return False


def _paths_only_in_flag_position(
    words: list[str], consumer: ConsumerSpec, patterns: tuple[str, ...]
) -> bool:
    """True when no bare word other than a flag VALUE looks path-mention-risky.

    Conservative: every word is fine unless it follows nothing recognisable.
    The caller has already established the command mentions a protected path;
    this checks the mention sits directly after a recognised path flag (or in
    a ``--flag=value`` form). Any other placement voids the exemption — the
    deny rule then applies. ``patterns`` are the caller's EFFECTIVE globs —
    see ``is_exempt_invocation`` for why the defaults must not be used here.
    """
    flag_value_positions: set[int] = set()
    for index, word in enumerate(words):
        bare = word.strip("\"'")
        if bare in consumer.path_flags and index + 1 < len(words):
            flag_value_positions.add(index + 1)
        for flag in consumer.path_flags:
            if bare.startswith(flag + "="):
                flag_value_positions.add(index)
    # Every word that would count as a protected mention must be a flag value.
    for index, word in enumerate(words[1:], start=1):
        if index in flag_value_positions:
            continue
        bare = word.strip("\"'")
        if bare.startswith("-"):
            continue
        if find_protected_mention(bare, patterns) is not None:
            return False
    return True
