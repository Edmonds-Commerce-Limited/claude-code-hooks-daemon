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

import contextlib
import contextvars
import fnmatch
import functools
import itertools
import logging
import os
import re
import time
import urllib.parse
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

import yaml

from claude_code_hooks_daemon.utils import linear_shlex, shell_expansion
from claude_code_hooks_daemon.utils.command_evasion import (
    REGEX_PATTERN_ATTACHED_PREFIXES,
    REGEXP_LONG_OPTION,
    GitGrepRole,
    git_grep_word_roles,
    git_subcommand_index,
    strip_transparent_reserved_words,
)
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.path_exclusion import (
    first_matching_glob,
    literal_screen,
    resolve_project_root,
)
from claude_code_hooks_daemon.utils.realpath import resolve_checking_loop
from claude_code_hooks_daemon.utils.shell_segmentation import (
    UnplaceableSubstitutionError,
    mask_quoted,
    segment_command_word,
    shell_word_spans,
    split_unquoted_spans,
    strip_inert_spans,
    substitution_inner_spans,
)

if TYPE_CHECKING:
    # Typing only: the index imports git_repo, which imports this module.
    from claude_code_hooks_daemon.utils.protected_file_index import ProtectedFileIndex

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

# Plan 00311 Task 1.3 (N5) second-look finding: `--pathspec-from-file=<file>`
# makes `git rm` READ `<file>` and treat each line as a pathspec -- breaking
# the "reads no content" invariant the whole exemption above rests on.
# Empirically verified: a pathspec that matches nothing is echoed back
# VERBATIM in git's own error text (`fatal: pathspec '<line content>' did
# not match any files`), so `git rm --cached --pathspec-from-file=<protected>`
# discloses the protected file's content through stderr even though the
# command still "only" untracks -- exactly the shape this guard exists to
# stop. The flag is not in `_GIT_RM_GRAMMAR`, so it (and every
# abbreviation git would accept) voids the exemption, whatever it names.

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

    from claude_code_hooks_daemon.core.project_context import ProjectContext

    # Not latched before init: a call that precedes init returns the defaults
    # without caching them, so the configured extra paths are picked up later.
    if not ProjectContext.is_initialized():
        return _CONFIGURED_PATTERNS

    _CONFIGURED_PATTERNS_RESOLVED = True

    try:
        from claude_code_hooks_daemon.config.models import Config, handler_options

        config = Config.load_or_default(ProjectContext.config_path())
        options = handler_options(config.handlers.pre_tool_use.get("secret_file_guard"))
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
        log_and_continue(
            logger,
            exc,
            reason="an unresolvable secret_file_guard config keeps the already-set SHIPPED DEFAULT patterns, which still protect; config errors are reported by the config loader itself",
            level=logging.DEBUG,
        )
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
    return protecting_pattern(file_path, patterns) is not None


def protecting_pattern(file_path: str, patterns: tuple[str, ...]) -> str | None:
    """The first of ``patterns``, in order, protecting ``file_path`` or its realpath.

    :func:`path_is_protected` for a caller that must also name the glob. It
    resolves the realpath ONCE for the whole list: asked one pattern at a
    time, each call walked every component of the path again, which for a
    90 KB-deep ``file_path`` cost seconds (Plan 00466 N40 review 2 nit 4).
    """
    if not file_path or not patterns:
        return None
    try:
        real, looped = resolve_checking_loop(file_path)
    except (OSError, ValueError) as exc:
        # Plan 00466 N24 follow-up: a NUL-bearing path raises ValueError,
        # not OSError -- the OS itself cannot realpath it, so it cannot BE
        # a symlink to anything (nor a loop); nothing for this check to
        # discover. The spelled path is still matched, below. Logged without
        # the path, which may itself be a protected name.
        logger.debug("protecting_pattern: no realpath (%s); matched as spelled", type(exc).__name__)
        real, looped = file_path, False
    if looped:
        # Plan 00466 N24 review 4 (team-lead follow-up on R4-B1): once a
        # loop is hit, os.path.realpath's own answer for the rest of the
        # path is version-dependent, so the realpath comparison below cannot
        # be trusted to catch a protected file reached through one. Treat a
        # loop as protected by every pattern rather than let a version
        # difference decide whether a secret is guarded.
        return patterns[0]
    return _pattern_for_spellings(file_path, real, patterns, resolve_project_root())


def _pattern_for_spellings(
    file_path: str, real: str, patterns: tuple[str, ...], project_root: str | None
) -> str | None:
    """The first pattern protecting ``file_path`` as spelled or as resolved to ``real``."""
    matches = [first_matching_glob(file_path, patterns, project_root=project_root)]
    if real != file_path:
        matches.append(first_matching_glob(real, patterns, project_root=project_root))
    found = [pattern for pattern in matches if pattern is not None]
    return min(found, key=patterns.index) if found else None


def protected_among(paths: Iterable[str], patterns: tuple[str, ...]) -> list[str]:
    """The members of ``paths`` for which :func:`path_is_protected` is true, in order.

    A repository-wide sweep asks this of every file git knows, and walking each
    file's whole path through ``realpath`` was the dominant cost of the
    SessionStart sweeps (N289b). Here each DIRECTORY is resolved and listed
    once: a file that the listing shows is not a symlink has, as its real path,
    its resolved parent plus its name, which is what ``realpath`` would
    return. A path whose spelling and real path both lack every literal run of
    every pattern (:func:`literal_screen`) cannot be protected, so the glob
    matcher is not entered for it. Anything these shapes do not cover (a
    symlink, a missing file or parent, a relative path, a NUL byte) is
    answered by :func:`protecting_pattern` itself, so the result equals the
    per-path call on every input.
    """
    if not patterns:
        return []
    project_root = resolve_project_root()
    screen = literal_screen(patterns)
    parents: dict[str, _ListedDirectory | None] = {}
    protected: list[str] = []
    for path in paths:
        real = _resolve_through_parent(path, parents)
        if real is None:
            hit = protecting_pattern(path, patterns) is not None
        elif screen is not None and not screen(path) and (real == path or not screen(real)):
            hit = False
        else:
            hit = _pattern_for_spellings(path, real, patterns, project_root) is not None
        if hit:
            protected.append(path)
    return protected


@dataclass(frozen=True, slots=True)
class _ListedDirectory:
    """A directory resolved once: its real path and which entries are symlinks."""

    real: str
    is_symlink: dict[str, bool]


#: How many ancestors deep a directory is resolved through its parent's
#: listing before ``realpath`` is asked instead (bounds the recursion).
_MAX_LISTING_DEPTH: Final[int] = 64


def _list_directory(
    directory: str, listed: dict[str, _ListedDirectory | None], depth: int = 0
) -> _ListedDirectory | None:
    """``directory`` strictly resolved and listed, or ``None`` when it cannot be.

    A directory that its parent's listing shows is not a symlink resolves to
    the parent's real path plus its name, with no walk of its own; only a
    root, a symlink, or something deeper than ``_MAX_LISTING_DEPTH`` costs a
    ``realpath``. ``listed`` memoises every directory seen.
    """
    if directory in listed:
        return listed[directory]
    real: str | None = None
    parent, separator, name = directory.rpartition("/")
    if separator and name and name not in (".", "..") and "//" not in directory:
        if depth < _MAX_LISTING_DEPTH:
            above = _list_directory(parent, listed, depth + 1)
            if above is not None and above.is_symlink.get(name) is False:
                real = f"{above.real.rstrip('/')}/{name}"
    result: _ListedDirectory | None = None
    if real is not None or Path(directory or "/").is_dir():
        # `is_dir` is true only for a directory that resolves, so the strict
        # and non-strict `realpath` agree here.
        result = _scan_directory(real or os.path.realpath(directory or "/"))
    listed[directory] = result
    return result


def _scan_directory(real: str) -> _ListedDirectory | None:
    """``real`` listed with each entry's symlink status.

    An unreadable directory comes back with an EMPTY listing, which names no
    file as plain, so every file in it is judged one by one by the per-path
    check.
    """
    try:
        with os.scandir(real) as entries:
            return _ListedDirectory(real, {e.name: e.is_symlink() for e in entries})
    except OSError as exc:
        logger.warning(
            "protected_among: a directory could not be listed (%s); its files are "
            "judged one by one",
            type(exc).__name__,
        )
        return _ListedDirectory(real, {})


def _resolve_through_parent(path: str, parents: dict[str, _ListedDirectory | None]) -> str | None:
    """``realpath(path)`` for a plain existing file under a listable parent, else ``None``.

    ``parents`` memoises each directory's listing (``None`` records one that
    cannot be listed). ``None`` is "this shape is not covered here", never an
    answer about the path.
    """
    head, separator, name = path.rpartition("/")
    if not separator or not name or name in (".", "..") or "//" in path or "\0" in path:
        return None
    listed = _list_directory(head, parents)
    if listed is None or listed.is_symlink.get(name, True):
        return None
    return f"{listed.real.rstrip('/')}/{name}"


def _tokenise(command: str) -> list[str]:
    """Split a command string into candidate path WORDS.

    Deliberately crude: this is mention detection, not shell parsing. Every
    run of non-delimiter characters is a candidate token, so paths inside
    quotes, substitutions, assignments and interpreter one-liners all
    surface. False positives are acceptable (deny-by-default); false
    negatives are the enumerated class-(c)/(d) limits.
    """
    return [token for token, _start in _tokenise_with_offsets(command)]


def _tokenise_with_offsets(command: str) -> list[tuple[str, int]]:
    """:func:`_tokenise`'s tokens, each with its offset in ``command``."""
    return [(match.group(), match.start()) for match in _TOKEN_PATTERN.finditer(command)]


_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(
    "[^" + re.escape(_TOKEN_DELIMITERS.replace("\n", "")) + "\\n]+"
)
#: The characters bash expands a word's pathname by.
_GLOB_CHARACTERS: Final[frozenset[str]] = frozenset("*?[")


#: A Python import statement's dotted MODULE path. Anchored per line, and the
#: grammar admits only identifier characters and dots -- notably no ``/``,
#: which is what makes the exemption below unable to hide a filesystem path.
_IMPORT_MODULE_RE: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*(?:from|import)[ \t]+([A-Za-z_][A-Za-z0-9_.]*)", re.MULTILINE
)

#: The same import-statement shape, anchored at the START of a `python -c`
#: (or `python3 -c`) inline script instead of a physical line (Plan 00311
#: Task 1.2 residual). `python -c "import <module>"` puts the statement on
#: the SAME line as the interpreter invocation, so `_IMPORT_MODULE_RE`'s
#: line-start anchor never reaches it -- the dotted module path was denied
#: on the Bash surface even after the Write/Edit surface (the ``from``/
#: ``import`` statement case above) was fixed for the identical name.
#: Requiring the literal `-c` flag immediately before the opening quote (not
#: a bare quote-lookbehind) keeps this exemption scoped to genuine inline
#: Python source rather than any quoted prose that happens to start with the
#: word "import".
_IMPORT_MODULE_INLINE_RE: Final[re.Pattern[str]] = re.compile(
    r"-c[ \t]+[\"'][ \t]*(?:from|import)[ \t]+([A-Za-z_][A-Za-z0-9_.]*)"
)


#: The quoted script argument of a ``-c`` flag. Imports after the first
#: statement of that script (``import sys; import a.b``) are found inside it.
_DASH_C_SCRIPT_RE: Final[re.Pattern[str]] = re.compile(
    r"(-c[ \t]+)([\"'])(.*?)(?<!\\)\2", re.DOTALL
)

#: An import statement at the start of a ``-c`` script body, or after a ``;``
#: or newline inside it. Applied to the script body only, never the whole command.
_IMPORT_STATEMENT_IN_SCRIPT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:(?<=;)|^)[ \t]*(?:from|import)[ \t]+([A-Za-z_][A-Za-z0-9_.]*)", re.MULTILINE
)

#: ``python -m <module>``: the interpreter word, plain option clusters
#: (``-I``, ``-u``), then ``-m`` and the dotted module. An option that takes a
#: value (``-W ignore``) is not recognised, so that shape stays denied.
_PYTHON_DASH_M_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|(?<=[\s/]))(?:python|pypy)\d*(?:\.\d+)*(?:[ \t]+-[A-Za-z]+)*[ \t]+-m[ \t]+"
    r"([A-Za-z_][A-Za-z0-9_.]*)"
)


def _drop_dash_c_script_imports(match: re.Match[str]) -> str:
    """Drop the module path of each import statement inside one ``-c`` script."""
    body = _IMPORT_STATEMENT_IN_SCRIPT_RE.sub(_drop_module_path, match.group(3))
    return f"{match.group(1)}{match.group(2)}{body}{match.group(2)}"


def _drop_module_path(match: re.Match[str]) -> str:
    """Shared substitution callback for both import-statement regexes above.

    Keeps everything up to the start of the captured module-path group
    (the `import `/`from ` lead-in, and -- for the inline variant -- the
    `-c "` prefix before it), dropping only the module path itself, so
    `from a.b import X` still contributes its `X` token.
    """
    return match.group(0)[: match.start(1) - match.start(0)]


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
    harmlessly while the real command after it runs. The inline
    (``python -c``) variant carries the same positional guarantee: it only
    ever deletes the module-path span sitting directly inside that one
    ``-c "..."`` argument, never a later, independent occurrence of the same
    text elsewhere in the command.

    A slash path still cannot be spelled as a module (the grammar admits no
    ``/``), so a genuine path is untouched by this either way. Nor can the
    inline variant be used to smuggle a real path past a real reader: the
    only way to make it match is to write the literal text ``import
    <name>`` immediately inside a ``-c "..."``/``-c '...'`` argument, and a
    shell argument carrying that literal prefix is no longer spelled
    identically to the bare protected name, so no command that actually
    reads ``<name>`` can be built this way.

    Applied only by :func:`find_protected_mention`, not the ``_strict``
    variant: strict serves the quarantine-artefact globs, whose hyphenated
    markers cannot collide with a Python module name in the first place, so
    changing it would be a fix for a problem it does not have.
    """
    without_line_anchored = _IMPORT_MODULE_RE.sub(_drop_module_path, command)
    without_inline = _IMPORT_MODULE_INLINE_RE.sub(_drop_module_path, without_line_anchored)
    without_script_imports = _DASH_C_SCRIPT_RE.sub(_drop_dash_c_script_imports, without_inline)
    return _PYTHON_DASH_M_RE.sub(_drop_module_path, without_script_imports)


def _normalised_token_forms(token: str) -> list[str]:
    """Spellings of a token to match against protected globs.

    A token that IS a home prefix and nothing else (``~/`` with no name
    after it) strips to the empty string. That candidate is dropped rather
    than appended (Ledger 00466 N44): every consumer of this list feeds each
    form to :func:`~utils.path_exclusion.path_matches_globs`, which computes
    ``os.path.relpath`` against a project root -- and ``os.path.relpath("",
    root)`` raises ``ValueError: no path specified``, a live daemon crash on
    a Bash command as ordinary as ``cp ~/ /tmp/x``. An empty string also
    never usefully matches a protected glob, so dropping it costs nothing.
    """
    forms: list[str] = []
    for candidate in (token, *_colon_path_parts(token)):
        for form in _home_and_dot_forms(candidate):
            if form not in forms:
                forms.append(form)
    return forms


#: How many leading colons a token is split at (the last colon is always
#: split too). Bounds the work a colon-stuffed token costs: each split yields
#: one more form to judge, and the real shapes (``:0:p``, ``HEAD:p``,
#: ``host:p``) carry at most two.
_MAX_COLON_SPLITS: Final[int] = 8


def _colon_path_parts(token: str) -> list[str]:
    """The path a ``prefix:path`` token names, one entry per split point.

    git's object syntax (``HEAD:p``, ``<sha>:p``, ``HEAD~2:p``, ``:p``,
    ``:0:p``, ``HEAD:./p``) and a remote path (``host:p``) both put the path
    after a ``:``. The whole token keeps its prefix, so an anchored pattern
    such as ``.vault-pass*`` never matches its basename at the repository
    root (ledger 00474 N283); judging the part after each ``:`` as well
    closes that. The whole token is still judged by the caller, so nothing it
    matched before stops matching.
    """
    positions = [i for i, char in enumerate(token) if char == ":"]
    if len(positions) > _MAX_COLON_SPLITS + 1:
        positions = [*positions[:_MAX_COLON_SPLITS], positions[-1]]
    return [token[i + 1 :] for i in positions if token[i + 1 :]]


def _home_and_dot_forms(token: str) -> list[str]:
    """``token`` with a leading home prefix or ``./`` stripped, token first."""
    forms = [token]
    for prefix in _HOME_PREFIXES:
        if token.startswith(prefix):
            stripped_home = token[len(prefix) :]
            if stripped_home:
                forms.append(stripped_home)
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

# A finite bracket expression denotes a CHARACTER SET, not an open run
# (Plan 00356). The edge predicates below answer "could an arbitrary run
# follow/precede this?" and a complete bracket expression at an edge made
# them answer yes -- so an array subscript like `.foo.v[0]` was read as
# ".foo.v then anything", whose 2-char `.v` edge overlaps the
# `.vault-password` stem, and an ordinary jq path was denied. Expanding the
# set to its concrete members instead fixes the INPUT the existing gates see,
# rather than adding another gate to them.
#
# The cap bounds the combinatorial product across a token's expressions, and
# equally the width of any ONE range within them -- ``_bracket_expression_
# members`` applies it before materialising, so the guarantee is on the WORK
# done rather than only on the result kept. Beyond it -- and for every class
# that is not a finite list -- the token is left UNEXPANDED and judged exactly
# as it was before, so the fallback fails CLOSED.
_MAX_BRACKET_EXPANSIONS: Final[int] = 64

# `[[:alpha:]]`-style named classes are not character LISTS; expanding the raw
# body would build a wrong and too-NARROW set, which is the one error
# direction this guard cannot take.
_POSIX_NAMED_CLASS_MARKER: Final[str] = "[:"

# Bash reads BOTH spellings as negation. Python's `fnmatch` honours only `!`
# (it treats `^` as a literal member), but these tokens are SHELL words, so
# the shell's reading decides what the token can name. A negated class is the
# complement of a set -- not finitely enumerable in any useful sense -- so
# neither spelling is expanded.
_BRACKET_NEGATION_CHARS: Final[tuple[str, ...]] = ("!", "^")


def _bracket_expression_members(expression: str) -> tuple[str, ...] | None:
    """Characters ``expression`` can match, or ``None`` when not enumerable.

    ``expression`` is a COMPLETE bracket expression including its delimiters
    (``[0]``, ``[a-f]``, ``[]]``). ``None`` means "leave this token alone",
    i.e. keep the pre-Plan-00356 conservative treatment.

    A range WIDER than ``_MAX_BRACKET_EXPANSIONS`` is rejected here rather
    than built and handed to the product cap in
    :func:`_expand_bracket_expressions`. The verdict is the same either way --
    a range that wide already blows the product, so the token comes back
    unexpanded -- but the cost is not: this function is reached from
    ``find_protected_mention`` on Write/Edit CONTENT, and materialising a
    literal range spanning the code-point space cost 650 ms and 145 MB per
    token on a PreToolUse hot path.
    """
    body = expression[1:-1]
    if body[:1] in _BRACKET_NEGATION_CHARS:
        return None
    if _POSIX_NAMED_CLASS_MARKER in body:
        return None
    members: list[str] = []
    if body[:1] == "]":
        # POSIX: a `]` immediately after `[` is a MEMBER, not the closer.
        members.append("]")
        body = body[1:]
    index = 0
    while index < len(body):
        if index + 2 < len(body) and body[index + 1] == "-":
            start, end = body[index], body[index + 2]
            span = ord(end) - ord(start)
            # An inverted range names nothing; an over-wide one cannot survive
            # the product cap anyway. Both leave the token unexpanded, so
            # deciding here costs one subtraction instead of a full range.
            if span < 0 or span >= _MAX_BRACKET_EXPANSIONS:
                return None
            members.extend(chr(point) for point in range(ord(start), ord(end) + 1))
            index += 3
            continue
        members.append(body[index])
        index += 1
    return tuple(dict.fromkeys(members)) or None


def _expand_bracket_expressions(token: str) -> list[str]:
    """Concrete spellings of ``token``, one per member of each finite class.

    ``.foo.v[0]`` -> ``['.foo.v0']``; ``dummy.vault-[pq]*`` ->
    ``['dummy.vault-p*', 'dummy.vault-q*']`` (a real ``*`` survives expansion
    and each spelling is still analysed as a glob).

    A token with no complete bracket expression, one carrying a class that is
    not a finite list, or one whose expansion would exceed
    ``_MAX_BRACKET_EXPANSIONS`` is returned UNCHANGED as a single-element
    list — the caller can compare against ``[token]`` to detect that.
    """
    matches = list(_BRACKET_EXPRESSION_RE.finditer(token))
    if not matches:
        return [token]

    member_sets: list[tuple[str, ...]] = []
    combinations = 1
    for match in matches:
        members = _bracket_expression_members(match.group(0))
        if members is None:
            return [token]
        combinations *= len(members)
        if combinations > _MAX_BRACKET_EXPANSIONS:
            return [token]
        member_sets.append(members)

    spellings = [""]
    cursor = 0
    for match, members in zip(matches, member_sets, strict=True):
        literal = token[cursor : match.start()]
        spellings = [prefix + literal + member for prefix in spellings for member in members]
        cursor = match.end()
    tail = token[cursor:]
    return [spelling + tail for spelling in spellings]


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


def _has_wildcard_after_leading(basename: str) -> bool:
    """True when ``basename`` carries a genuine wildcard SOMEWHERE AFTER its
    own leading one (Plan 00466 review, minor m1).

    The N4 fix's stricter ``stem_basename.endswith(residue)`` requirement in
    ``_glob_token_overlaps_stem`` is only correct for the simple splat shape
    it was built for -- a token that is a leading wildcard followed by pure
    literal text (``*words[position``, ``*wordlist``), where fnmatch has
    nothing left to expand once the leading ``*`` is consumed. A token that
    carries ANOTHER wildcard too (``*rd*rd``, project-configured
    ``*on*.json``) is a different shape entirely: fnmatch expands the
    INTERNAL wildcard as well, so the token can glob-match a protected name
    without its residue being anywhere near a literal suffix of the stem
    (``*rd*rd`` matches ``rd.vault-password`` -- contains ``rd``, then later
    another ``rd``, with an arbitrary run in between). Applying the splat
    fix's stricter requirement to this shape silently dropped that
    detection; this predicate lets the caller skip the requirement instead
    for any token where it does not apply, restoring the pre-N4 overlap-only
    behaviour for genuinely multi-wildcard tokens.

    Only ``*``/``?`` after the leading marker count, matching
    ``_is_glob_shaped``'s own rule that a lone unmatched ``[`` is literal to
    fnmatch, not a wildcard.
    """
    if basename[:1] in ("*", "?"):
        rest = basename[1:]
    else:
        leading_bracket = _BRACKET_EXPRESSION_RE.match(basename)
        rest = basename[leading_bracket.end() :] if leading_bracket else basename
    return _is_glob_shaped(rest)


def _token_literal_residue(token: str) -> str:
    """The literal text left after removing glob syntax from ``token``.

    Bracket expressions are removed WHOLE (``[A-Za-z]`` contributes nothing),
    then ``*`` and ``?`` are stripped: ``.vault-p*`` -> ``.vault-p``;
    ``[A-Za-z]*`` -> ``''``. The residue is what the token literally asserts
    about a filename, so it is what must overlap a protected stem.

    Only ``*``/``?`` are stripped here, NOT a bare ``[`` (n466-n24 review 4
    addendum, M-1 fold-in a): a ``[`` that survives the bracket-expression
    removal above has no matching ``]`` in this token, and bash -- like
    ``fnmatch`` -- reads an UNTERMINATED bracket expression as a literal
    character, never a wildcard. A Python list/slice token such as
    ``*words[subcommand_index`` genuinely carries that shape (the review's
    own live finding): dropping its lone ``[`` shortens the residue by one
    character for no linguistic reason and can accidentally manufacture a
    longer coincidental overlap with a protected stem than the token's own
    text actually supports.
    """
    residue = _BRACKET_EXPRESSION_RE.sub("", token)
    for char in ("*", "?"):
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
    pattern_has_trailing_wildcard: bool,
    token_has_wildcard_after_leading: bool,
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
      The TOKEN's own trailing wildcard supplies the flexibility needed to
      absorb whatever the pattern demands after the overlap, so this holds
      regardless of the pattern's own trailing shape.
    - A LEADING-wildcard token (``*passXXX``) can be preceded on the LEFT, so
      the stem's SUFFIX must overlap the residue's PREFIX (reverse) — but
      here the token supplies NO trailing flexibility of its own (a leading
      wildcard AND a trailing wildcard both being open is the BOTH-edges
      case above, handled first). Whatever follows the overlap in the
      residue (``position`` in ``*words[position``) can only be absorbed by
      the PATTERN's own trailing wildcard, if it has one. A pattern anchored
      at the end (``*.vault-password``, no trailing ``*``) admits no such
      leftover, so a genuine truncation needs the residue's FULL length to
      be a literal suffix of the stem — a partial boundary overlap is then
      coincidence, not truncation (observed live (N4, Plan 00466): the
      Python unpacking operator ``*words[position + 1 :]`` tokenises to
      ``*words[position``, whose residue ``wordsposition`` shares only its
      first 4 characters, ``word``, with the stem's tail ``...pass-word``,
      leaving ``sposition`` with nowhere to go). The pre-existing
      substring+fnmatch check above already denies every FULL-suffix case,
      so this branch is never the sole route to a genuine positive here —
      only to this false one. This stricter requirement is scoped to a token
      shaped ``*literal`` with NO further wildcard (m1, Plan 00466 review):
      a token that ALSO carries an internal wildcard (``*rd*rd``) is not the
      splat shape at all — fnmatch expands that wildcard too, so the token
      can still glob-match the stem without a literal-suffix residue — and
      for that shape the requirement is skipped, restoring the pre-N4
      overlap-only behaviour (see ``_has_wildcard_after_leading``).

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
        and (
            pattern_has_trailing_wildcard
            or token_has_wildcard_after_leading
            or stem_basename.endswith(residue)
        )
    ):
        return True
    return False


#: B1 (Plan 00466 guard-defects review 2): a run of consecutive ``*`` matches
#: exactly what a single ``*`` matches (zero or more of anything), so
#: collapsing one is language-preserving -- and it removes the dominant cost
#: driver the review measured directly: a 5000-``*`` token turned the DP's
#: O(len(a) * len(b)) grid into tens of millions of cells for no semantic
#: gain. Applied to BOTH operands, since either side can carry the run (a
#: project-configured pattern is just as capable of a long ``*`` run as a
#: token is).
_STAR_RUN_RE: Final[re.Pattern[str]] = re.compile(r"\*{2,}")

#: The DP is O(len(a) * len(b)); past this many cells the token is treated
#: as intersecting WITHOUT running it (fail closed), per the review's fix
#: direction: "no legitimate path glob is 500 characters of wildcards". A
#: few 10**4 keeps the worst case comfortably sub-millisecond in pure Python
#: while leaving every realistic glob (a few dozen characters at most, even
#: after bracket expansion) untouched -- the star-collapse above already
#: defeats the specific 5000-``*`` shape long before this cap would matter;
#: this is the backstop for any OTHER way to build a long operand.
_DP_MAX_CELLS: Final[int] = 20_000

#: M2b (Plan 00466 guard-defects review 2): the outer `[...]` of a POSIX
#: named class (`[[:alpha:]]`) matched WHOLE, ahead of the general
#: `_BRACKET_EXPRESSION_RE` below -- that regex's `[^\]]*\]` stops at the
#: class's OWN closing `]` (the one in `[:alpha:]`), one character short of
#: the real outer close, and substituting only that inner span would leave
#: the final `]` behind as a stray literal character.
_POSIX_NAMED_CLASS_RE: Final[re.Pattern[str]] = re.compile(r"\[\[:[a-z]+:\]\]")

#: Test seam (N123): counts DP grid cells ``_globs_can_intersect`` actually
#: visits, so a test can assert on WORK DONE instead of wall-clock time --
#: a fixed-second budget flakes under host contention (concurrent worktree
#: gates), independent of whether the cost bound itself holds. A
#: ``ContextVar`` rather than a module-level counter: no per-request state
#: leaks across concurrent calls, and production pays nothing beyond a
#: ``None`` check when no test has opened :func:`dp_cell_counter`.
_dp_cell_counter: contextvars.ContextVar[list[int] | None] = contextvars.ContextVar(
    "_dp_cell_counter", default=None
)


@contextlib.contextmanager
def dp_cell_counter() -> Iterator[list[int]]:
    """Count DP grid cells ``_globs_can_intersect`` visits during the block.

    Returns a one-element list holding the running total, so it stays
    visible without a second read of the ``ContextVar``. Test-only seam
    (N123); production code never calls this.
    """
    counts = [0]
    token = _dp_cell_counter.set(counts)
    try:
        yield counts
    finally:
        _dp_cell_counter.reset(token)


@functools.lru_cache(maxsize=256)
def _wildcard_regex(glob: str) -> re.Pattern[str]:
    """``glob`` as a regex in which only ``*`` (any run) and ``?`` (any one
    character) are special -- the two wildcards ``_globs_can_intersect``
    understands. The cache is keyed on the pattern text alone (shipped
    patterns repeat for every token), so no per-request state is held."""
    return re.compile(
        "".join(".*" if ch == "*" else "." if ch == "?" else re.escape(ch) for ch in glob),
        re.DOTALL,
    )


def _globs_can_intersect(a: str, b: str) -> bool:
    """True when some single string could be matched by BOTH ``a`` and ``b``,
    each read as a ``*``/``?`` glob (N10, Plan 00466 review).

    A genuine two-glob language-intersection test, not another edge
    heuristic: the leading/trailing overlap checks above answer "is the
    wildcard at an EDGE", so a token whose wildcard sits in the MIDDLE
    (``.vault-pas?word``, ``prod.vault-passw*rd``) has neither edge open and
    is invisible to every check above it, even though it can glob-expand to
    a real protected filename. Standard sequence-alignment DP, O(len(a) *
    len(b)): ``dp[i][j]`` is True when the length-``i`` prefix of ``a`` and
    the length-``j`` prefix of ``b`` can produce an identical output prefix.
    A ``*`` matches zero or more characters, so it can either contribute
    nothing new (fall back to the shorter prefix on its own side) or absorb
    one more character the OTHER side is currently offering; a ``?`` or a
    literal must line up one-for-one with the other side's ``?``/matching
    literal. ``dp[len(a)][len(b)]`` is the answer for the full patterns.

    Callers are responsible for expanding any bracket expression first (see
    ``_expand_bracket_expressions``) -- this function only understands the
    two characters above, matching the scope ``fnmatch`` needs once a finite
    class has already been reduced to its concrete members.

    B1 (Plan 00466 guard-defects review 2): a crafted long operand made this
    an unbounded-cost call on a PreToolUse hot path, and a slow verdict is a
    BYPASS here, not just a nuisance -- the client's socket timeout on the
    30s budget is an ALLOW for the whole chain. ``*`` runs are collapsed
    first (language-preserving), and the DP itself is never run past
    ``_DP_MAX_CELLS`` -- past that, the pair is treated as intersecting
    (fail closed) without paying for the grid.
    """
    # M2b (Plan 00466 guard-defects review 2): an unexpanded bracket
    # expression (negated, a POSIX named class, or an over-cap range) was
    # read as LITERAL characters below -- so `id_r[!x]a` compared as the
    # literal text `id_r[!x]a`, never as a match for `id_rsa`, even though
    # `[!x]` really can expand to any character but `x`. A single `?` is the
    # narrowest wildcard that is still a SUPERSET of every finite class this
    # could denote, so substituting it stays fail-closed rather than
    # fail-open, the same direction `_expand_bracket_expressions` already
    # commits to for the cases it cannot enumerate. The POSIX form is
    # substituted FIRST and with its own regex: `_BRACKET_EXPRESSION_RE`'s
    # `[^\]]*\]` stops at the class's OWN closing `]` (`[:alpha:]`), one
    # character short of the outer bracket expression's real close, and
    # would otherwise leave that outer `]` behind as a stray literal.
    # Cut the constant factor (team-lead's 1 MB timing follow-up to review
    # 3): a regex `.sub()` call costs real overhead even on a NO-OP match --
    # for the common case of a short ordinary token, calling all three
    # substitutions unconditionally was paying that cost six times (three
    # per operand) for patterns that never contain a POSIX class, a bracket
    # expression, or a star run at all. A cheap substring/character check
    # first skips the regex engine entirely when there is nothing for it to
    # do -- semantically identical, since each `.sub()` is a no-op exactly
    # when its trigger character(s) are absent.
    if "[:" in a:
        a = _POSIX_NAMED_CLASS_RE.sub("?", a)
    if "[:" in b:
        b = _POSIX_NAMED_CLASS_RE.sub("?", b)
    if "[" in a:
        a = _BRACKET_EXPRESSION_RE.sub("?", a)
    if "[" in b:
        b = _BRACKET_EXPRESSION_RE.sub("?", b)
    if "**" in a:
        a = _STAR_RUN_RE.sub("*", a)
    if "**" in b:
        b = _STAR_RUN_RE.sub("*", b)
    len_a, len_b = len(a), len(b)
    if len_a * len_b > _DP_MAX_CELLS:
        return True
    # N265: a token with no wildcard of its own (the usual case once its
    # brackets are expanded) intersects a glob exactly when that glob matches
    # it, which one compiled-regex match answers without the grid.
    if "*" not in a and "?" not in a:
        return _wildcard_regex(b).fullmatch(a) is not None
    # Rolling two-row DP instead of a full (len_a+1) x (len_b+1) grid: the
    # transition for row `i` only ever reads row `i-1` and the CURRENT
    # row's own previous cell, so one full grid's worth of list-of-lists
    # allocation per call (the dominant constant-factor cost at these
    # problem sizes -- most tokens and patterns here are a few dozen
    # characters at most) is unnecessary. Semantically identical to the
    # grid version; `prev`/`curr` alternate which physical list plays which
    # role instead of copying.
    prev = [False] * (len_b + 1)
    curr = [False] * (len_b + 1)
    prev[0] = True
    for j in range(1, len_b + 1):
        prev[j] = b[j - 1] == "*" and prev[j - 1]
    cell_counter = _dp_cell_counter.get()
    for i in range(1, len_a + 1):
        char_a = a[i - 1]
        curr[0] = char_a == "*" and prev[0]
        if cell_counter is not None:
            cell_counter[0] += len_b
        for j in range(1, len_b + 1):
            char_b = b[j - 1]
            if char_a == "*":
                curr[j] = prev[j] or curr[j - 1]
            elif char_b == "*":
                curr[j] = curr[j - 1] or prev[j]
            elif char_a == "?" or char_b == "?" or char_a == char_b:
                curr[j] = prev[j - 1]
            else:
                curr[j] = False
        prev, curr = curr, prev
    return prev[len_b]


def _glob_intersection_mention(
    expansions: list[str], stem_pairs: list[tuple[str, str]]
) -> str | None:
    """First protected pattern a glob-shaped token could glob-expand to,
    else ``None`` (N10, Plan 00466 review; M2a extends it past interior-only).

    A wildcard sitting in the MIDDLE of a token (``.vault-pas?word``,
    ``prod.vault-passw*rd``) has neither edge open, so the leading/trailing
    overlap check never sees it (that check is gated on an open edge by
    construction, exactly so it does not re-litigate the N4/m1 false
    positives) and the substring+fnmatch check needs the residue to already
    be a literal substring of the stem, which a truncation that drops an
    INTERIOR character never is. A token whose OWN wildcard sits at an edge
    (``*.vault-pas?word``) used to be excluded from here too, on the theory
    that the overlap heuristic already covered edge shapes -- but that
    heuristic was deliberately NARROWED by the N4/m1 fix and does not, in
    fact, cover every edge-open shape (M2a review 2 finding). The DP is an
    EXACT intersection test, so running it here for edge-open tokens as well
    closes that gap without reopening N4: ``*words[position`` (N4's own
    false-positive shape) still does not glob-intersect an end-anchored
    stem, because nothing in either glob can absorb the leftover residue.

    Run over ``expansions``, not gated on the individual form still being
    glob-shaped: a finite bracket expression (``.vault-pa[sz]word``) resolves
    to plain literals that no longer carry a wildcard of their own, yet one
    of those literals can still be exactly this shape of truncation. The
    caller gates the call itself on ``_is_glob_shaped(raw_form)`` so an
    ordinary non-glob word never reaches this at all -- once here, a fully
    literal expansion is simply the degenerate case of the same intersection
    test (no ``*``/``?`` on either side reduces it to plain equality).

    A pattern with wildcards on BOTH edges (``*.secret*``, ``*vault_pass*``)
    is INCLUDED here too (m-2, n466-n24 review 4 addendum) -- but only ever
    reaches a real DP call for a token carrying no ``*`` of its own (a
    ``?``-only or fully-literal-after-bracket-expansion token); see
    :func:`_dp_intersection_is_meaningful`'s both-edges branch for why a
    token WITH its own ``*`` must stay excluded (``report-[0-9]*.txt`` and
    ``secret*.py`` genuinely do glob-intersect ``*.secret*``, but neither is
    evidence of a protected file -- Plan 00306/00311's own false-positive
    class, still avoided). A genuine both-edges truncation/extension that
    DOES carry the token's own ``*`` is left to the filesystem-truth route
    (M2c, ``_both_edges_glob_mention``) instead, which can safely accept the
    wider class because it verifies against a real file rather than judging
    text alone.

    Each (token, pattern) pair is also gated by
    :func:`_dp_intersection_is_meaningful` before the DP runs at all -- see
    its docstring for the degenerate cases that gate exists to skip.

    A form's own residue must also clear ``_MIN_GLOB_OVERLAP_CHARS`` first
    (own live finding, own RED test): a single-character residue (a bare
    ``.`` from an HTML-regex-shaped ``.*?`` quantifier token, or one letter
    out of a ``[A-Za-z]*`` character-class expansion) trivially fnmatches
    almost anything -- ``i*`` glob-matches the literal ``id_rsa`` outright,
    with no truncation of any real filename involved at all. This is the
    identical floor the overlap heuristic above already enforces for the
    identical reason (see ``_MIN_GLOB_OVERLAP_CHARS``'s own docstring).
    """
    # m-2 (n466-n24 review 4 addendum): every pattern is now eligible --
    # `_dp_intersection_is_meaningful` is what keeps a both-edges pattern
    # from over-firing, not exclusion from this list.
    eligible_patterns = [pattern for _stem, pattern in stem_pairs]
    for form in expansions:
        basename = form.rsplit("/", maxsplit=1)[-1]
        if len(_token_literal_residue(basename)) < _MIN_GLOB_OVERLAP_CHARS:
            continue
        for pattern in eligible_patterns:
            if _dp_intersection_is_meaningful(basename, pattern) and _globs_can_intersect(
                basename, pattern
            ):
                return pattern
    return None


def _dp_intersection_is_meaningful(token_basename: str, pattern: str) -> bool:
    """False when a DP call for this pair is a DEGENERATE always-true case
    rather than a genuine constraint (M2a follow-up, own live finding: not
    in the review report, caught by this branch's own RED test for the N4
    shape reopening against a DIFFERENT shipped pattern).

    A both-edges PATTERN (``*.secret*``, ``*vault_pass*``) is handled FIRST
    and separately (m-2, n466-n24 review 4 addendum): it is meaningful only
    when ``token_basename`` carries no ``*`` of its own. A both-edges
    pattern's own two wildcards can absorb an arbitrary run on EITHER side
    of its fixed literal, so any token that also has a ``*`` can always
    satisfy it by inserting the pattern's own literal directly into that
    token's wildcard gap, wherever it sits -- ``report-[0-9]*.txt`` and
    ``secret*.py`` genuinely do glob-intersect ``*.secret*`` this way (a
    real ``report-0.secret.txt``/``secret.secret.py`` would satisfy both),
    but neither is evidence of a protected file (Plan 00306/00311's own
    false-positive class). A token using ONLY ``?`` (or nothing) has no such
    unbounded gap -- it can absorb at most one character per ``?`` -- so a
    genuine intersection there requires its fixed literal text to actually,
    closely resemble the stem (``demo.se?ret`` intersecting ``*.secret*``
    only because it is one character removed from spelling ``demo.secret``
    outright), which is a real signal worth running the DP for.

    A single-star glob with its open end on ONE side is, in effect, "any
    prefix, then this literal" (a leading wildcard) or "this literal, then
    any suffix" (a trailing wildcard). Two such globs intersect
    UNCONDITIONALLY -- for ANY pair of literals whatsoever -- whenever their
    open ends face OPPOSITE directions: concatenating the pattern's literal
    with the token's literal (or vice versa) always satisfies both at once
    (``"*words[position"`` needs a string ENDING in ``"words[position"``;
    ``".vault-pass*"`` needs one STARTING with ``".vault-pass"``; simply
    concatenate them). Since this holds regardless of what the literals
    actually say, running the DP there would deny essentially every
    leading-wildcard token in existence against every shipped
    trailing-wildcard pattern -- for example an ordinary ``*.py`` -- not
    just a genuine truncation of a protected name. The DP stays a real,
    literal-dependent test only when both open ends face the SAME
    direction (requiring the literals to actually share a compatible
    prefix/suffix), when the token is a BOTH-edges glob compared against a
    fully literal pattern (a "contains" test against one fixed string,
    which is meaningful), or whenever either side carries no wildcard at
    its edges at all (then the DP reduces to an ordinary single-glob
    match, always well-defined). A both-edges TOKEN against an
    edge-wildcard pattern is degenerate the same way (``"*L*"`` against
    ``"*S"``/``"P*"`` is always satisfiable by ``L + S``/``P + L``).
    """
    pattern_leading = _has_leading_wildcard(pattern)
    pattern_trailing = _has_trailing_wildcard(pattern)
    if pattern_leading and pattern_trailing:
        return "*" not in token_basename
    if not (pattern_leading or pattern_trailing):
        return True  # a fully literal pattern is never degenerate.
    token_leading = _has_leading_wildcard(token_basename)
    token_trailing = _has_trailing_wildcard(token_basename)
    if not (token_leading or token_trailing):
        return True  # a fully literal token is never degenerate.
    if token_leading and token_trailing:
        return False  # both-edges token vs any edge-open pattern: always intersects.
    return token_leading == pattern_leading


#: Which surface a mention scan is judging (n466-n24 review 4 addendum,
#: false-positive fold-in b). ``"bash"`` (the default, and every pre-existing
#: caller) is a real shell command: the AGGRESSIVE glob-shaped heuristics
#: (edge-overlap, full DP intersection, the both-edges residue/FS-truth
#: routes) all apply, because a real shell really does expand a glob-shaped
#: word. ``"content"`` is Write/Edit CONTENT -- arbitrary source code, not
#: shell text a shell will ever run -- where an ordinary code token that
#: merely LOOKS glob-shaped (Python unpacking-plus-subscript:
#: ``*words[subcommand_index``, from a real list-literal
#: ``[*words[:subcommand_index], ...]``) is not evidence of anything. Content
#: is judged on the LITERAL matcher only (an exact/glob-pattern comparison
#: against the raw token and its bracket-expansions, already unconditional
#: below): a quoted path string (``open(".vault-password")``) or a script's
#: own protected-name reference (``cat id_rsa`` in a ``.sh`` file, brace
#: sequences and quote/escape decoding still applied by the token streams
#: upstream) still denies through it -- only the HEURISTIC "could this
#: glob-shaped code token coincidentally expand to a protected name"
#: reasoning is switched off, because content is never expanded by a shell.
MentionContext = Literal["bash", "content"]


def find_protected_mention(
    command: str,
    patterns: tuple[str, ...],
    *,
    deadline: float | None = None,
    context: MentionContext = "bash",
    bash_tool_command: bool = False,
) -> str | None:
    """First protected glob a token of ``command`` mentions, else ``None``.

    A mention is a shell WORD that matches a protected glob (after `~`/`$HOME`
    normalisation and realpath resolution), or a glob-shaped word whose
    expansion could include a protected name. Prose containing the bare word
    ``secret`` never matches — only path-shaped tokens do.

    Thin wrapper over :func:`find_protected_mention_detail`, which also
    reports WHICH token matched. Kept as the primary entry point so the
    callers that only need the glob are unaffected. ``deadline`` (Plan 00466
    review 8 L1) is forwarded straight through -- see
    :func:`find_protected_mention_detail`'s own docstring. ``context`` -- see
    :data:`MentionContext` -- defaults to ``"bash"``, so every pre-existing
    caller keeps its exact prior behaviour unchanged. ``bash_tool_command``
    -- see :func:`_brace_expansion_tokens`.
    """
    detail = find_protected_mention_detail(
        command,
        patterns,
        deadline=deadline,
        context=context,
        bash_tool_command=bash_tool_command,
    )
    return None if detail is None else detail[0]


#: B1 (Plan 00466 guard-defects review 2): the per-call DP budget bounds a
#: single token's cost, but not the TOTAL cost of a scan over many ordinary
#: tokens (the review's 1 MB-of-"a*b"-tokens case: no single token is
#: pathological, the cost is volume). Comfortably under the client's 30s
#: PreToolUse budget, with headroom for every other handler sharing it.
#: Public (no leading underscore): ``secret_file_guard`` supplies this as
#: its scan deadline, so the value is shared rather than duplicated.
SCAN_DEADLINE_SECONDS: Final[float] = 5.0


def bash_route_word_stream(command: str, *, deadline: float | None = None) -> list[str] | None:
    """The single decoded word list safe to share between BOTH consumers on
    the Bash route: the ordinary mention scan (:func:`iter_protected_
    mentions`) and ``secret_file_guard``'s interpreter one-liner fallback
    (review 7 follow-up, team-lead's double-scan finding).

    The ordinary scan reads ``command`` with import-module-path stripping
    applied (:func:`_without_import_module_paths`); the one-liner fallback
    MUST read raw ``command`` (stripping a `-c "import ...` argument's own
    module name corrupts that argument's syntax before the one-liner
    scan's AST-based literal extraction ever runs -- proven RED by a real
    inline-import one-liner that stopped matching once fed stripped words).
    Decoding twice is only ACTUALLY necessary when stripping changes the
    text at all -- true for the overwhelming majority of commands, which
    contain no `import <module>` positioned where the stripper looks, so
    the two decodes would be identical anyway.

    Returns the ONE decode (safe for both consumers) when stripping made no
    difference, or ``None`` when it did -- signalling that each consumer
    must decode separately for correctness, exactly the pre-existing
    two-pass behaviour, kept only for this rare case.
    """
    if _without_import_module_paths(command) != command:
        return None
    return list(shell_expansion.iter_normalised_shell_words(command, deadline=deadline))


def find_protected_mention_detail(
    command: str,
    patterns: tuple[str, ...],
    *,
    deadline: float | None = None,
    cwd: str | None = None,
    context: MentionContext = "bash",
    normalised_words: list[str] | None = None,
    bash_tool_command: bool = False,
    cwds: tuple[str, ...] | None = None,
    index: "ProtectedFileIndex | None" = None,
) -> tuple[str, str] | None:
    """``(pattern, token)`` for the first protected mention, else ``None``.

    The TOKEN is reported so a deny message can name the span it objected to
    (Plan 00356). Without it the only route to a diagnosis is bisecting the
    input across repeated denied writes — the glob alone does not say which
    of a file's many words tripped it. Echoing it discloses nothing: it is
    text the caller just supplied, never content read from a protected file.

    ``deadline`` (a ``time.monotonic()`` cutoff) is forwarded to
    :func:`iter_protected_mentions` -- see its docstring for why exceeding it
    raises rather than silently truncating the scan. ``cwd`` (M2c, Plan
    00466 review 2) is the HOOK's working directory, forwarded to the
    both-edges filesystem-truth route -- a caller with no hook cwd to hand
    simply omits it. ``context`` -- see :data:`MentionContext` -- defaults to
    ``"bash"``, unchanged from every pre-existing caller. ``normalised_words``
    (review 7 follow-up) is forwarded straight through -- see
    :func:`bash_route_word_stream`. ``bash_tool_command`` -- see
    :func:`_brace_expansion_tokens`.
    """
    return next(
        iter_protected_mentions(
            command,
            patterns,
            deadline=deadline,
            cwd=cwd,
            context=context,
            normalised_words=normalised_words,
            bash_tool_command=bash_tool_command,
            cwds=cwds,
            index=index,
        ),
        None,
    )


#: Command heads whose quoted arguments are text they only READ or PRINT, by
#: how the text is used. An ALLOWLIST: a missing head costs a false positive, a
#: wrong one costs the guard. Deliberately absent, because each globs or runs
#: text of its own: ``find``, ``ls``, ``python``, ``bash``/``sh -c``, ``xargs``.
_ECHO_HEADS: Final[frozenset[str]] = frozenset({"echo", "printf"})
_GREP_HEADS: Final[frozenset[str]] = frozenset({"grep", "egrep", "fgrep"})
_RG_HEAD: Final[str] = "rg"
_AWK_HEADS: Final[frozenset[str]] = frozenset({"awk", "gawk", "mawk"})
_GH_HEAD: Final[str] = "gh"
_TEXT_CONSUMER_HEADS: Final[frozenset[str]] = (
    _ECHO_HEADS | _GREP_HEADS | _AWK_HEADS | frozenset({_RG_HEAD, _GH_HEAD})
)
#: Text consumers whose quoted operand never reaches their output (it is the
#: matched content of the files read), the only ones relaxed inside a
#: substitution. Not ``rg`` (``-r`` prints its replacement text) and not ``awk``
#: (a program prints its string literals).
_SEARCH_HEADS: Final[frozenset[str]] = _GREP_HEADS
#: ``gh`` flags whose value is prose published as written.
_GH_TEXT_FLAGS: Final[frozenset[str]] = frozenset(
    {"--body", "-b", "--title", "-t", "--notes", "-n"}
)
#: An awk program containing one of these can hand its text to a shell or read
#: a file it names, so it is not merely a pattern.
_AWK_RUNNING_MARKERS: Final[tuple[str, ...]] = ("system", "getline", "|")
#: Heads whose pattern operand is a regular expression, never a path.
_REGEX_PATTERN_HEADS: Final[frozenset[str]] = _GREP_HEADS | frozenset({_RG_HEAD})
_GIT_HEAD: Final[str] = "git"
_GIT_GREP_SUBCOMMAND: Final[str] = "grep"
#: The roles ``git_grep_word_roles`` gives a regex pattern word.
_GIT_GREP_PATTERN_ROLES: Final[frozenset[GitGrepRole]] = frozenset(
    {GitGrepRole.PATTERN, GitGrepRole.PATTERN_ATTACHED}
)
_TEXT_OPERAND_PLACEHOLDER: Final[str] = "TEXT_OPERAND"
#: Shells whose ``-c`` program string is read as shell commands (not ``python -c``).
_SHELL_PROGRAM_HEADS: Final[frozenset[str]] = frozenset({"bash", "sh", "dash", "zsh", "ksh"})
#: How many ``bash -c '...'`` layers deep text operands are looked for.
_MAX_SHELL_PROGRAM_DEPTH: Final[int] = 3
_SEGMENT_SEPARATORS: Final[tuple[str, ...]] = ("&&", "||", ";", "|", "&", "\n")
#: Unquoted, any of these makes bash compute the word: a glob, a variable or
#: substitution, a brace list, a tilde.
_WORD_EXPANDING_CHARACTERS: Final[frozenset[str]] = frozenset("*?[$`{~")


def _is_literal_quoted_word(word: str) -> bool:
    """True for a word carrying quotes whose every glob character bash reads
    literally: nothing unquoted expands and no command substitution runs in
    it. ``mask_quoted`` blanks single quotes, ANSI-C strings and escapes, and
    with ``keep_double`` False the inside of double quotes too."""
    if "'" not in word and '"' not in word:
        return False
    unquoted = mask_quoted(word, keep_double=False).replace("$'", "'")
    if any(char in _WORD_EXPANDING_CHARACTERS for char in unquoted):
        return False
    substitutable = mask_quoted(word, keep_double=True)
    return "`" not in substitutable and "$(" not in substitutable


def _is_text_operand(word: str, previous: str, head: str) -> bool:
    """Whether ``word`` is a quoted argument ``head`` uses purely as text."""
    if not _is_literal_quoted_word(word):
        return False
    if head == _GH_HEAD:
        return previous in _GH_TEXT_FLAGS or word.partition("=")[0] in _GH_TEXT_FLAGS
    if head in _REGEX_PATTERN_HEADS:
        # The pattern given as an option's value is a regex like the positional
        # one: `--regexp=PAT`, `-ePAT`, and `--regexp PAT`.
        if word.startswith(REGEX_PATTERN_ATTACHED_PREFIXES):
            return True
        if previous == REGEXP_LONG_OPTION:
            return True
    if word.startswith("-"):
        return False
    if head in _ECHO_HEADS:
        return True
    # A long option's separate value may be a glob the tool applies itself
    # (`grep --include GLOB`), and `rg -g GLOB` does the same.
    if previous.startswith("--") and "=" not in previous:
        return False
    if head == _RG_HEAD:
        return not (previous.startswith("-") and previous.endswith("g"))
    if head in _AWK_HEADS:
        return not any(marker in word for marker in _AWK_RUNNING_MARKERS)
    return head in _GREP_HEADS


def _without_text_operands(command: str) -> str:
    """``command`` with every quoted operand of a pure text consumer replaced
    by a placeholder: a ``grep``/``rg``/``awk`` pattern, ``echo``/``printf``
    arguments, a ``gh`` body or title, a ``-m`` message and the body of a
    quoted-delimiter heredoc fed to a data sink. Bash hands each of those on
    literally, so a glob character in one is not a glob.

    What is left is what bash or a program can still expand. Unquoted words,
    tool glob options, and any quoted text given to a program that globs or
    runs it (``python -c``, ``bash -c``, ``find -name``) are untouched.

    The command text of each substitution (command, backtick, process) is a
    command of its own, so it is segmented and judged the same way as the top
    level (ledger 00474 N291), with one difference: a substitution's OUTPUT
    becomes words of the outer command, and an unquoted result is glob-expanded.
    ``echo``/``printf``/``gh`` operands ARE their output, so inside a
    substitution only the operands of ``grep`` (:data:`_SEARCH_HEADS`), whose
    output is matched content rather than the pattern, are relaxed. A
    text the scanner cannot place with certainty is judged at top level only.
    """
    if "'" not in command and '"' not in command and "<<" not in command:
        return command
    text = strip_inert_spans(command)
    operands = _text_operand_spans(text, 0, 0)
    pieces: list[str] = []
    copied_to = 0
    for operand_start, operand_end in sorted(operands):
        if operand_start < copied_to:
            continue
        pieces.append(text[copied_to:operand_start])
        pieces.append(_TEXT_OPERAND_PLACEHOLDER)
        copied_to = operand_end
    pieces.append(text[copied_to:])
    return "".join(pieces)


def _text_operand_spans(text: str, offset: int, depth: int) -> set[tuple[int, int]]:
    """Absolute ``(start, end)`` of every text operand in ``text``, which begins
    at ``offset`` in the whole command.

    Covers the top level, each substitution (only :data:`_SEARCH_HEADS` operands
    there) and, up to :data:`_MAX_SHELL_PROGRAM_DEPTH` levels deep, the program
    string of a shell's single-quoted ``-c`` (ledger 00474 N356): that string is
    a command of its own, handed to a shell that reads its quotes as bash does.
    """
    try:
        inner_regions = substitution_inner_spans(text)
    except UnplaceableSubstitutionError as exc:
        # Nothing inside a substitution can be placed, so only the top level is relaxed.
        log_and_continue(
            logger,
            exc,
            reason="a substitution whose inner spans cannot be placed leaves no inner regions, so only the top level is relaxed; everything inside the substitution stays judged as a mention",
            level=logging.DEBUG,
        )
        inner_regions = []
    operands: dict[tuple[int, int], str] = {}
    programs: list[tuple[int, int]] = []
    for region_start, region_end in [(0, len(text)), *inner_regions]:
        region = text[region_start:region_end]
        for start, end in split_unquoted_spans(region, _SEGMENT_SEPARATORS):
            segment = region[start:end]
            head, spans = _segment_text_operands(segment, offset + region_start + start)
            operands.update(dict.fromkeys(spans, head))
            program = _shell_dash_c_program_span(segment, head)
            if program is not None:
                programs.append(
                    (region_start + start + program[0], region_start + start + program[1])
                )
    found: set[tuple[int, int]] = set()
    for (operand_start, operand_end), head in operands.items():
        # By start offset: an outer-pass word can run on past the closing delimiter.
        inside_substitution = any(
            start <= operand_start - offset < end for start, end in inner_regions
        )
        if inside_substitution and head not in _SEARCH_HEADS:
            continue
        found.add((operand_start, operand_end))
    if depth < _MAX_SHELL_PROGRAM_DEPTH:
        for program_start, program_end in programs:
            found |= _text_operand_spans(
                text[program_start:program_end], offset + program_start, depth + 1
            )
    return found


def _shell_dash_c_program_span(segment: str, head: str) -> tuple[int, int] | None:
    """``(start, end)`` within ``segment`` of the CONTENT of a single-quoted
    program given to a shell's ``-c`` (``bash -c '...'``, ``sh -lc '...'``), or
    ``None``. Single quotes pass their content on verbatim, so the span maps
    exactly onto the text the shell runs; a double-quoted program, whose
    escapes and expansions change it, is left to the ordinary scan."""
    if head not in _SHELL_PROGRAM_HEADS:
        return None
    spans = shell_word_spans(segment)
    words = [segment[start:end] for start, end in spans]
    shell_index = next((i for i, word in enumerate(words) if word.rsplit("/", 1)[-1] == head), None)
    if shell_index is None:
        return None
    index = shell_index + 1
    while index < len(words) and words[index].startswith("-") and not words[index].startswith("--"):
        if "c" in words[index][1:]:
            if index + 1 >= len(words):
                return None
            program_start, program_end = spans[index + 1]
            word = words[index + 1]
            if len(word) >= 2 and word[0] == word[-1] == "'" and "'" not in word[1:-1]:
                return program_start + 1, program_end - 1
            return None
        index += 1
    return None


def _git_grep_pattern_spans(segment: str) -> list[tuple[int, int]]:
    """``(start, end)`` within ``segment`` of each regex pattern word of a
    ``git grep``, or none when the segment is another git command.

    The pattern is the first positional, or the value of ``-e``/``--regexp``
    (then every positional is a revision or pathspec, which is judged as a
    path). Everything after ``--`` is a pathspec."""
    spans = shell_word_spans(segment)
    words = [segment[start:end] for start, end in spans]
    git_index = next(
        (index for index, word in enumerate(words) if word.rsplit("/", 1)[-1] == _GIT_HEAD), None
    )
    if git_index is None:
        return []
    subcommand = git_subcommand_index(words, git_index)
    if subcommand is None or words[subcommand] != _GIT_GREP_SUBCOMMAND:
        return []
    roles = git_grep_word_roles(words, subcommand)
    return [
        spans[index]
        for index, role in sorted(roles.items())
        if role in _GIT_GREP_PATTERN_ROLES and _is_literal_quoted_word(words[index])
    ]


def _segment_text_operands(segment: str, offset: int) -> tuple[str, list[tuple[int, int]]]:
    """The segment's command word and the absolute ``(start, end)`` of each
    text operand in it; ``segment`` begins at ``offset`` in the command. No
    operands unless the command word is a pure text consumer."""
    head = segment_command_word(segment) or ""
    if head == _GIT_HEAD:
        git_grep_spans = _git_grep_pattern_spans(segment)
        # git grep prints matched content, like grep, so it is judged as grep.
        return (_GIT_GREP_SUBCOMMAND, [(offset + s, offset + e) for s, e in git_grep_spans])
    if head not in _TEXT_CONSUMER_HEADS:
        return head, []
    spans = shell_word_spans(segment)
    return head, [
        (offset + word_start, offset + word_end)
        for index, (word_start, word_end) in enumerate(spans)
        if _is_text_operand(
            segment[word_start:word_end],
            segment[spans[index - 1][0] : spans[index - 1][1]] if index else "",
            head,
        )
    ]


class _GlobExpansionGate:
    """Whether a token's text is something bash can glob-expand.

    Built once per scan and queried only for a glob-shaped token. A command
    with nothing to mask answers True for every token without another pass. Any
    other command is re-tokenised once with its text operands blanked
    (:func:`_without_text_operands`); a token is then expandable only if it
    still occurs there, so text that also appears unquoted elsewhere stays
    judged.
    """

    def __init__(self, command: str, tokenise: Callable[[str], Iterable[str]]) -> None:
        self._command = command
        self._tokenise = tokenise
        self._expandable: set[str] | None = None
        self._resolved = False

    def expands(self, token: str) -> bool:
        """False only when ``token`` occurs solely inside text operands."""
        if not self._resolved:
            view = _without_text_operands(self._command)
            if view != self._command:
                self._expandable = set(self._tokenise(view))
            self._resolved = True
        return self._expandable is None or token in self._expandable

    def is_quoted_literal(self, token: str) -> bool:
        """True when ``token`` occurs only as a whole quoted word, which bash
        passes on as written (``cat 'dir/*'``), never glob-expanded."""
        if f"'{token}'" not in self._command and f'"{token}"' not in self._command:
            return False
        return token not in set(self._tokenise(mask_quoted(self._command, keep_double=False)))


def iter_protected_mentions(
    command: str,
    patterns: tuple[str, ...],
    *,
    deadline: float | None = None,
    cwd: str | None = None,
    context: MentionContext = "bash",
    normalised_words: list[str] | None = None,
    bash_tool_command: bool = False,
    cwds: tuple[str, ...] | None = None,
    index: "ProtectedFileIndex | None" = None,
) -> Iterator[tuple[str, str]]:
    """``(pattern, token)`` for EVERY protected mention in ``command``, in order.

    ``index`` is the protected-file index (:mod:`protected_file_index`): a
    glob-shaped word is also a mention when it matches a protected file that
    exists, read from each of the ``cwds``. With no index only the literal and
    stem checks judge a glob.

    ``cwds`` are the directories a relative word may be read from (see
    :func:`effective_cwds`); ``None`` derives them from ``command`` and ``cwd``.
    A caller judging a fragment of a longer command passes the whole
    command's.

    One entry per mentioning token, carrying the first glob it trips. The
    encrypted-target exemption (Plan 00459) needs them all: a command is let
    through only when each one is confirmed, and stopping at the first would
    confirm an encrypted file while a plaintext one sat later in the line.

    ``deadline`` (B1, Plan 00466 guard-defects review 2) is an optional
    ``time.monotonic()`` cutoff, checked once per token -- a whole-scan
    backstop for the per-token DP budget in :func:`_globs_can_intersect`,
    which bounds one token's cost but not the total across many ordinary
    ones. Past the deadline this RAISES ``TimeoutError`` rather than
    stopping and answering "no mention": a socket timeout on the client's
    30s budget is an ALLOW for the whole PreToolUse chain, so silently
    truncating here would silently skip whatever mention sat past the cutoff
    -- the same bypass shape B1 found, moved one layer up. Raising lets
    ``secret_file_guard``'s fail-closed wrapper (N11) turn it into a deny;
    callers that do not pass a deadline are unaffected (default ``None``
    never checks the clock).

    ``cwd`` (M2c, Plan 00466 review 2) is the HOOK's working directory,
    forwarded to :func:`_token_mention`'s both-edges filesystem-truth route.

    The token stream is the ordinary tokenisation PLUS every raw brace word
    (M2d) -- ``_tokenise`` splits on ``,``, which tears a real brace
    alternation like ``{s,}`` apart before it can be recognised as one word,
    so brace words are found and expanded straight from the untokenised text
    instead (see :func:`_brace_expansion_tokens`).

    B1-R3 (Plan 00466 review 3): the brace half of the token stream is now a
    LAZY generator chained onto the ordinary tokens, not an eagerly-built
    list -- review 2's own B1 fix passed a ``deadline``, but only checked it
    once per token in THIS loop, after ``tokens`` had already been fully
    materialised (including every brace spelling). An exponential
    ``{a,b}``x22 word built its full expansion before the loop -- and
    therefore the deadline check -- ever ran once. Chaining lazily means
    pulling the NEXT token (which may be where an over-cap brace word raises
    ``TooManyToEnumerateError``, itself fail-closed the same way a deadline
    breach is) only happens after THIS token has already passed the check
    below, so construction is now bounded by the very same per-token gate
    that bounds consumption.

    M-1 (n466-n24 review 4): a THIRD stream, :func:`_normalised_word_tokens`,
    adds every shell WORD with quotes/escapes/ANSI-C decoded and any
    statically-unresolvable substitution (``$VAR``, ``$(...)``, a backtick,
    ``$((...))``) collapsed to a single ``*`` -- ``_tokenise``'s crude
    delimiter split treats a quote character, `` ` ``, and ``$`` as plain
    separators, so ``cat id_rs$x`` never produces a token resembling a
    protected name at all, not even a mangled one, and ``cat id_"rs"a``
    produces three USELESS fragments instead of the one real word a shell
    would read. Lazily chained for the identical reason the brace stream is.
    An ordinary word with nothing to decode normalises back to the exact
    same text ``_tokenise`` already produced for it, so the per-token dedup
    below (keyed on token TEXT, not stream) is what keeps that overlap from
    doubling every ordinary mention.

    ``context`` (n466-n24 review 4 addendum, false-positive fold-in b) is
    forwarded to :func:`_token_mention` -- see :data:`MentionContext` for
    why a ``"content"`` scan skips the aggressive glob-shaped heuristics
    that a ``"bash"`` scan still runs.

    Review 7 follow-up (team-lead's double-scan finding): the normalised-
    word and ``file:`` URL streams below BOTH need the decoded word list
    (the second one scans each word's own text for a `file:` URL), and used
    to call :func:`shell_expansion.iter_normalised_shell_words` separately
    -- a full second decode pass over the same text. They now share ONE
    underlying generator via :func:`itertools.tee` when ``normalised_words``
    is not supplied: still lazy relative to ``_tokenise``/
    ``_brace_expansion_tokens`` above (the shared generator is never even
    created if one of those two already answers the call), but each word is
    decoded once and read by both consumers, not decoded twice.

    ``normalised_words`` (review 7 follow-up): the Bash route in
    ``secret_file_guard`` can go further still, in the common case where a
    single decode is provably safe to share with its OWN interpreter
    one-liner fallback too -- see :func:`bash_route_word_stream` for the
    safety condition. When given, both streams below read this list
    directly instead of tee-ing a fresh decode.
    """
    if not command or not patterns:
        return
    project_root = resolve_project_root()
    effective = effective_cwds(command, cwd) if cwds is None else cwds
    stem_pairs = _pattern_literal_stems(patterns)
    tokens = _mention_token_stream(
        command,
        deadline=deadline,
        bash_tool_command=bash_tool_command,
        source_code=context == "content",
        normalised_words=normalised_words,
    )
    glob_gate = _GlobExpansionGate(
        command,
        lambda view: _mention_token_stream(
            view,
            deadline=deadline,
            bash_tool_command=bash_tool_command,
            source_code=False,
            normalised_words=None,
        ),
    )
    # Own live finding (team-lead's 1 MB timing follow-up to review 3): real
    # content is full of REPEATED short tokens (log lines, minified code,
    # boilerplate) -- every one of `patterns`/`stem_pairs`/`project_root`/
    # `cwd`/`index` is fixed for the WHOLE
    # call, so the verdict for a given token text can never differ between
    # two occurrences of it in the same command. Caching by token text turns
    # a scan that redid the full DP/bracket/filesystem work for every
    # occurrence into one that pays for each DISTINCT token once.
    #
    # M-1 (n466-n24 review 4): the SAME cache doubles as the yield-dedup --
    # an ordinary word with nothing for `_normalised_word_tokens` to decode
    # is the identical string `_tokenise` already produced, so without this
    # every plain mention would be reported twice, once per stream that
    # happened to find it. `_mention_is_encrypted` (the one caller that
    # consumes every yielded mention) is a pure function of token text, so
    # collapsing repeats -- whether from stream overlap or the command
    # genuinely repeating a word -- changes no verdict it computes.
    mention_cache: dict[str, str | None] = {}
    yielded_tokens: set[str] = set()
    for token in tokens:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("secret_file_guard mention scan exceeded its deadline")
        if token in mention_cache:
            pattern = mention_cache[token]
        else:
            pattern = _token_mention(
                token,
                patterns,
                stem_pairs,
                project_root,
                context=context,
                expands_globs=functools.partial(glob_gate.expands, token),
                is_quoted_literal=functools.partial(glob_gate.is_quoted_literal, token),
                effective_cwds=effective,
                index=index,
            )
            mention_cache[token] = pattern
        if pattern is not None and token not in yielded_tokens:
            yielded_tokens.add(token)
            yield (pattern, token)


def _with_option_value_forms(tokens: Iterable[str]) -> Iterator[str]:
    """Each token, then the path it may carry after a leading ``@`` (``curl -d
    @FILE``) or a short option's attached value (``-fFILE``, ``-e@FILE``).

    Plan 00483 owner ruling A4 (N229): only these two prefixes, no parser.
    A form is yielded only when stripping changed the token.
    """
    for token in tokens:
        yield token
        value = token
        if len(value) > 2 and value[0] == "-" and value[1] != "-":
            value = value[2:]
            yield value
        if value.startswith("@") and len(value) > 1:
            yield value[1:]


def _mention_token_stream(
    command: str,
    *,
    deadline: float | None,
    bash_tool_command: bool,
    source_code: bool,
    normalised_words: list[str] | None,
) -> Iterator[str]:
    """The four lazily chained token streams :func:`iter_protected_mentions`
    judges: the crude tokenisation, every raw brace word, every decoded shell
    word, and every ``file:`` URL path. See that function for why each exists
    and why none is built ahead of the loop that consumes it."""
    # The import-module-path exemption is applied ONCE, up front, and every
    # stream reads the same stripped text -- an import statement's dotted
    # module path is not a filesystem path regardless of which stream would
    # otherwise re-discover it (M-1, n466-n24 review 4: the brace and
    # normalised-word streams read raw `command` before this fix, so an
    # `import <name>` line naming a protected stem in its own module path
    # was exempted for `_tokenise` only, and still flagged by the other two).
    import_stripped = _without_import_module_paths(command)
    words_for_normalised_stream: Iterable[str]
    words_for_file_url_stream: Iterable[str]
    if normalised_words is not None:
        words_for_normalised_stream = normalised_words
        words_for_file_url_stream = normalised_words
    else:
        words_for_normalised_stream, words_for_file_url_stream = itertools.tee(
            shell_expansion.iter_normalised_shell_words(import_stripped, deadline=deadline)
        )
    return itertools.chain(
        _with_option_value_forms(_tokenise(import_stripped)),
        _brace_expansion_tokens(
            command, bash_tool_command=bash_tool_command, source_code=source_code
        ),
        _normalised_word_tokens(
            import_stripped, deadline=deadline, words=words_for_normalised_stream
        ),
        _file_url_path_tokens(import_stripped, deadline=deadline, words=words_for_file_url_stream),
    )


def _brace_expansion_tokens(
    command: str, *, bash_tool_command: bool = False, source_code: bool = False
) -> Iterator[str]:
    """Lazily yield every concrete spelling of every raw brace-expansion word
    in ``command`` (B1-R3, Plan 00466 review 3).

    One word at a time, via the shared bounded primitives in
    ``utils/shell_expansion`` -- word discovery (:func:`shell_expansion.
    iter_brace_words`) is itself bounded and non-backtracking, and each
    word's own expansion (:func:`shell_expansion.expand_braces`) is capped
    on total spellings AND recursion depth, raising ``TooManyToEnumerateError``
    (a plain ``Exception``, caught the same way ``TimeoutError`` already is
    by ``secret_file_guard``'s fail-closed wrapper) rather than ever
    materialising an exponential blow-up. Superseded this module's own prior
    ``_expand_braces``/``_brace_expanded_tokens`` -- see
    ``iter_protected_mentions``'s docstring for why this must also be LAZY,
    not just capped.

    Each concrete spelling is then quote/escape-normalised (n466-n24 review
    4, M-1): a brace ALTERNATIVE can itself carry a quote (``{'a',x}``), so
    a shell reads ``id_rs{'a',x}`` as EITHER ``id_rsa`` or ``id_rsx`` -- the
    quote strips only once the alternative is chosen, not from the group
    template beforehand. Run over the EXPANDED spelling, matching that
    order.

    Plan 00466 N101: when ``bash_tool_command`` is set, the brace words come
    from :func:`shell_expansion.brace_expansion_view`, which neutralises the
    CODE braces (dict and set displays, comprehensions, f-string fields) of
    a standalone `python3` program no shell reads the output of -- text no
    shell expands, whose enumeration modelled nothing and failed the guard
    closed on ordinary Python programs. Every string literal and comment of
    that program is enumerated on its own, with the same caps, and so is
    every brace word not wholly inside one. Everything else is enumerated
    exactly as before, caps and fail-closed included.

    Plan 00466 N107: each source's words are also found by
    :func:`shell_expansion.iter_shell_brace_words`, which splits them as
    bash does, so a group holding quoted whitespace reaches the expander
    whole; and :func:`shell_expansion.expand_braces` reads a quoted or
    escaped brace or comma as text, as bash does.

    Only a caller judging the Bash tool's own, whole command line sets it
    (the guard's Bash route, payload capture): the view's safety argument
    is that the line's top-level stdout reaches the model, not a shell. An
    authored script, Makefile recipe or CI step (``context="bash"`` on the
    Write/Edit route), a segment of a command, and ``"content"`` are all
    enumerated whole, as on main (round 3, D-RULE B2): a script's output
    goes to whoever runs it later.

    ``command`` is the RAW command: the view parses the Python program
    itself, which deleting import module paths would break (`import `
    alone does not parse). The deletion is applied to the view's text
    instead, which neutralising braces never touches.

    ``source_code`` marks authored source in a non-shell language (the
    ``"content"`` scan, ledger 00466 N238). No shell reads that text, so
    where it parses as Python only its string literals and comments are
    enumerated (:func:`shell_expansion.python_string_literals`), which is
    all a shell can be handed from it: a dict or set display in code is not
    a brace group, however many commas it holds. Text that does not parse
    as Python is enumerated whole.
    """
    literals = shell_expansion.python_string_literals(command) if source_code else None
    if bash_tool_command:
        view = shell_expansion.brace_expansion_view(command)
        sources: tuple[str, ...] = (_without_import_module_paths(view.text), *view.literals)
        code_words = view.code_words
        code_shell_words = view.shell_words
    elif literals is not None:
        sources = literals
        code_words = ()
        code_shell_words = ()
    else:
        sources = (_without_import_module_paths(command),)
        code_words = ()
        code_shell_words = ()
    for word in itertools.chain(
        *(shell_expansion.iter_brace_words(source) for source in sources), code_words
    ):
        for spelling in shell_expansion.expand_braces(word):
            yield shell_expansion.normalise_word(spelling)
    for word in itertools.chain(
        *(shell_expansion.iter_shell_brace_words(source) for source in sources), code_shell_words
    ):
        yield from shell_expansion.shell_word_spellings(word)


def _normalised_word_tokens(
    command: str, *, deadline: float | None = None, words: Iterable[str] | None = None
) -> Iterator[str]:
    """Lazily yield every shell WORD in ``command``, quote/escape/ANSI-C
    decoded, with any statically-unresolvable substitution collapsed to a
    single ``*`` (n466-n24 review 4, M-1).

    A thin pass-through to :func:`shell_expansion.iter_normalised_shell_words`
    -- the bounded, non-backtracking word scanner lives there so it stays
    the one place shared with any other caller that needs the same class of
    normalisation, the same reason brace expansion and the recursive glob
    walk live there. A resulting word that now carries a ``*`` (from an
    unresolved ``$VAR``/``$(...)``/backtick/``$((...))``) is not treated
    specially here -- it reaches :func:`_token_mention` exactly like any
    other glob-shaped token, where the EXISTING interior-wildcard DP
    intersection (:func:`_globs_can_intersect`) decides whether it could
    reach a protected path, denying only when a match is genuinely
    possible.

    ``deadline`` (review 7 follow-up) is forwarded straight through -- flat
    word decoding is no longer bounded by a word COUNT (that capped
    ordinary large content, not just adversarial input), so THIS deadline,
    the same one ``iter_protected_mentions`` already checks per token, is
    now the only volume backstop for this stream too.

    ``words`` (review 7 follow-up, team-lead's double-scan finding): when
    given, yields THIS pre-decoded stream instead of calling
    :func:`shell_expansion.iter_normalised_shell_words` again --
    ``iter_protected_mentions`` passes one branch of an
    :func:`itertools.tee` split shared with :func:`_file_url_path_tokens`,
    so the underlying decode runs once for both streams.
    """
    if words is not None:
        yield from words
        return
    yield from shell_expansion.iter_normalised_shell_words(command, deadline=deadline)


#: `file:///path`, `file://localhost/path`, or the rarer single-slash
#: `file:/path` -- the scheme and an optional empty/`localhost` host are
#: consumed, leaving the absolute filesystem path as the capture group.
#: `\b` anchors the scheme so an unrelated word ending in "...file:" (rare,
#: but cheap to exclude) does not false-trigger. Case-INSENSITIVE (review 7
#: MAJOR-4): URL schemes are case-insensitive per RFC 3986, and curl itself
#: accepts `FILE://`/`File://` exactly like `file://` -- the review-6 fix
#: only matched the lowercase spelling.
_FILE_URL_RE: Final[re.Pattern[str]] = re.compile(
    r"\bfile:(?:/{2})?(?:localhost)?(/[^\s'\"<>|;&)]*)", re.IGNORECASE
)


def _file_url_path_tokens(
    command: str, *, deadline: float | None = None, words: Iterable[str] | None = None
) -> Iterator[str]:
    """Lazily yield the percent-decoded filesystem PATH named by every
    ``file:`` URL in ``command`` (review 7: guard-defects review 6's own
    probe found `curl -s file:///root/.ssh/id_r%73a` invisible to every
    other stream -- a real, literal local-file READ route, in a DIFFERENT
    spelling than a plain bash token, reachable from `curl`, `wget`, a
    Python ``urllib`` one-liner, ``git clone file://...``, or anything else
    that accepts a URL argument).

    Percent-decoding (``urllib.parse.unquote``) happens BEFORE the result is
    handed to :func:`_token_mention`, so ``id_r%73a`` is judged as the
    literal path ``id_rsa`` it names, exactly like any other path mention --
    no separate matching logic, just a different way to PRODUCE a candidate
    token.

    Run over TWO sources (review 7 MAJOR-4): ``command``'s raw text, and
    every word :func:`shell_expansion.iter_normalised_shell_words` produces
    after quote removal -- a URL split by shell quoting
    (``curl 'file:///root/.ssh/id_r'%73a``, ``curl file:///root/.ssh/id_r
    "%73"a``) never appears as one contiguous ``file:...`` span in the raw
    text at all; only the DECODED word (quotes stripped, adjacent pieces
    concatenated into one shell word) reassembles it. The raw-text pass
    stays first so an ordinary, unquoted URL costs nothing beyond the
    existing regex scan.

    ``words`` (review 7 follow-up, team-lead's double-scan finding): when
    given, the second pass reads THIS pre-decoded stream instead of calling
    :func:`shell_expansion.iter_normalised_shell_words` again --
    ``iter_protected_mentions`` passes the other branch of the same
    :func:`itertools.tee` split fed to :func:`_normalised_word_tokens`.
    """
    for match in _FILE_URL_RE.finditer(command):
        yield urllib.parse.unquote(match.group(1))
    word_stream = (
        words
        if words is not None
        else shell_expansion.iter_normalised_shell_words(command, deadline=deadline)
    )
    for word in word_stream:
        for match in _FILE_URL_RE.finditer(word):
            yield urllib.parse.unquote(match.group(1))


def _token_mention(
    token: str,
    patterns: tuple[str, ...],
    stem_pairs: list[tuple[str, str]],
    project_root: str | None,
    *,
    context: MentionContext = "bash",
    realpath_cache: dict[str, str | None] | None = None,
    expands_globs: Callable[[], bool] = lambda: True,
    effective_cwds: tuple[str, ...] = (),
    is_quoted_literal: Callable[[], bool] = lambda: False,
    index: "ProtectedFileIndex | None" = None,
) -> str | None:
    """The first protected glob ``token`` names (or could glob-expand to), else None.

    ``effective_cwds`` (:func:`effective_cwds`) are the directories a relative
    ``token`` may be read from: a directory or absolute-path pattern is matched
    against the path the word reaches there too, not only as spelled, and a
    glob-shaped token is matched against ``index`` (the protected files that
    exist) from each of them.

    ``expands_globs`` answers, only when ``token`` is glob-shaped, whether the
    word can be glob-expanded at all (:class:`_GlobExpansionGate`). ``False``
    leaves the literal check as the only judge of the token.

    ``context`` (n466-n24 review 4 addendum, false-positive fold-in b) --
    see :data:`MentionContext`. The LITERAL check just below (an exact/glob-
    pattern comparison of the raw token and its bracket-expansions against
    every configured pattern) runs unconditionally in both contexts; only
    the AGGRESSIVE glob-shaped heuristics further down -- edge-overlap
    fnmatch, the full DP intersection, and the both-edges residue/FS-truth
    routes -- are skipped for ``"content"``. A live example that must stay
    ALLOWED for content: the Python unpacking-plus-subscript shape
    ``*words[subcommand_index`` (from a real list literal
    ``[*words[:subcommand_index], ...]``) is glob-shaped by the crude
    tokeniser's own delimiter split, but it names no real path and a shell
    will never expand it -- it is not a Bash word at all.

    ``realpath_cache`` (review 7 follow-up, team-lead's memoisation cut):
    an optional dict, LOCAL to one caller's scan (never module-level --
    per-request state on a shared object is exactly what N23 forbids),
    memoising the ``os.path.realpath`` syscall the symlink-alias check
    below makes. ``iter_protected_mentions`` already dedups repeated
    TOKENS before ever reaching this function (its own ``mention_cache``),
    so this only helps a caller that invokes ``_token_mention`` directly,
    outside that loop, for a genuinely repeated token (e.g.
    ``is_grep_pattern_only_mention`` checking several file-target words).
    ``None`` (the default) skips the cache entirely -- identical behaviour
    to before this parameter existed.
    """
    for raw_form in _normalised_token_forms(token):
        # A token whose bracket expressions are all finite denotes exactly
        # the set of its expansions, so that set -- not the bracketed
        # spelling -- is what the glob heuristics must judge (Plan 00356).
        expansions = _expand_bracket_expressions(raw_form)
        # The UNEXPANDED spelling still faces the LITERAL check: a shell
        # passes an unmatched glob through verbatim, so a file literally
        # named `x[0].secret` is reachable under that exact name. This is
        # the "literal matcher" content scanning relies on exclusively.
        literal_forms = [raw_form] if expansions == [raw_form] else [raw_form, *expansions]
        for form in literal_forms:
            matched = first_matching_glob(form, patterns, project_root=project_root)
            if matched is not None:
                return matched
            for anchored in _anchored_spellings(form, effective_cwds if context == "bash" else ()):
                matched = first_matching_glob(anchored, patterns, project_root=project_root)
                if matched is not None:
                    return matched
        if context != "bash":
            continue
        # Everything below judges a word bash would glob-expand. Text that a
        # pure text consumer takes quoted is literal to bash, so it is only
        # ever matched by the literal check above (ledger 00474 N269).
        if any(_is_glob_shaped(form) for form in (raw_form, *expansions)) and not expands_globs():
            continue
        for form in expansions:
            if not _is_glob_shaped(form):
                continue
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
                    pattern_has_trailing_wildcard=_has_trailing_wildcard(pattern),
                    token_has_wildcard_after_leading=_has_wildcard_after_leading(basename),
                ):
                    return pattern
        if _is_glob_shaped(raw_form):
            match = _glob_intersection_mention(expansions, stem_pairs)
            if match is not None:
                return match
            if index is not None and not is_quoted_literal():
                for form in expansions:
                    if _is_glob_shaped(form):
                        match = index.glob_matches(form, effective_cwds)
                        if match is not None:
                            return match
    # Own live finding (team-lead's 1 MB timing follow-up to review 3): the
    # symlink-alias check exists for the `worktree_create` seeding case --
    # an innocuous LINK name pointing at a protected TARGET -- which is
    # only a plausible shape for a token that could itself BE a literal
    # filename. A glob-shaped token (`a*b`, `id[0-9]`) would need a real
    # on-disk symlink literally named with an unescaped `*`/`?`/bracket
    # expression to matter here -- legal on most filesystems but not a
    # shape any genuine alias uses, and skipping the `os.stat` syscall for
    # it is the single biggest per-token cost this scan pays at volume (a
    # 1 MB command built of ordinary glob-shaped tokens did one real
    # syscall per token for no security benefit).
    if not _is_glob_shaped(token):
        if realpath_cache is not None and token in realpath_cache:
            real = realpath_cache[token]
        else:
            real = _realpath_if_resolvable(token)
            if realpath_cache is not None:
                realpath_cache[token] = real
        if real is not None:
            return first_matching_glob(real, patterns, project_root=project_root)
    return None


def has_name_agnostic_glob(command: str) -> bool:
    """Does ``command`` carry an unquoted glob whose file name says almost nothing?

    ``*``, ``.*``, ``?`` and ``[a-z]*`` name no file family of their own: the
    text checks have nothing to compare against a protected name (a residue
    under ``_MIN_GLOB_OVERLAP_CHARS``), so only the index of protected files
    can say whether one is reached. A caller with no index uses this to tell
    the agent the glob went unjudged. A glob that asserts real name text
    (``report-*.txt``) was judged by the text checks and is not reported.
    Only a glob bash would expand counts: one quoted or escaped is a literal.
    """
    unquoted = mask_quoted(command, keep_double=False)
    for token, start in _tokenise_with_offsets(command):
        if not any(char in _GLOB_CHARACTERS for char in unquoted[start : start + len(token)]):
            continue
        for form in _normalised_token_forms(token):
            for expansion in _expand_bracket_expressions(form):
                basename = expansion.rsplit("/", maxsplit=1)[-1]
                if (
                    _is_glob_shaped(expansion)
                    and len(_token_literal_residue(basename)) < _MIN_GLOB_OVERLAP_CHARS
                ):
                    return True
    return False


def find_protected_mention_strict(
    command: str,
    patterns: tuple[str, ...],
    cwd: str | None = None,
    index: "ProtectedFileIndex | None" = None,
) -> str | None:
    """First protected glob a token of ``command`` mentions, requiring a REAL
    match in ``index`` (the protected files that exist) for any glob-shaped
    token, else ``None``. Without an ``index`` a glob-shaped token never counts.

    The rest of this docstring describes the on-disk-truth rationale.

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
    the glob against the filesystem (project root, then the hook's ``cwd``)
    and only counts it as a mention when at least one resulting path is
    itself protected.

    Only a token with a glob character bash would expand is expanded (ledger
    00466 N238): one inside quotes or escaped is a literal, which bash
    hands on as written (``jq '.files["a"]'``, ``rg -g '**/*.md'``).
    """
    if not command or not patterns:
        return None
    project_root = resolve_project_root()
    unquoted = mask_quoted(command, keep_double=False)
    bases = effective_cwds(command, cwd) if index is not None else ()
    for token, start in _tokenise_with_offsets(command):
        globbed = any(char in _GLOB_CHARACTERS for char in unquoted[start : start + len(token)])
        for form in _normalised_token_forms(token):
            matched = first_matching_glob(form, patterns, project_root=project_root)
            if matched is not None:
                return matched
            if index is not None and globbed and _is_glob_shaped(form):
                match = index.glob_matches(form, bases)
                if match is not None:
                    return match
        real = _realpath_if_resolvable(token)
        if real is not None:
            matched = first_matching_glob(real, patterns, project_root=project_root)
            if matched is not None:
                return matched
    return None


_DIRECTORY_CHANGE_COMMANDS: Final[frozenset[str]] = frozenset({"cd", "pushd"})
_COMMAND_SEGMENT_SEPARATORS: Final[re.Pattern[str]] = re.compile(r"&&|\|\||[;|&\n]")


def effective_cwds(command: str, cwd: str | None) -> tuple[str, ...]:
    """The directories ``command`` may run in: the hook's ``cwd``, then each literal ``cd`` target.

    Ledger 00474 N221. A relative path in a command is read from where the
    command is, so ``cd vault && cat r.md`` reaches ``vault/r.md``. Every
    ``cd``/``pushd`` is tracked cumulatively and ALL the resulting directories
    are returned, because a word is judged against each: the over-approximation
    errs towards denying and needs no per-word ordering. A target bash computes
    (a variable, substitution, glob, brace list, tilde) or that cannot be
    placed (``cd -``, a relative step with no absolute directory to start
    from) is not tracked -- out of scope, as before.
    """
    directories: list[str] = [cwd] if cwd is not None and Path(cwd).is_absolute() else []
    for segment in _COMMAND_SEGMENT_SEPARATORS.split(command):
        words = _shell_words(segment)
        if words is None or len(words) < 2 or words[0] not in _DIRECTORY_CHANGE_COMMANDS:
            continue
        operands = [word for word in words[1:] if not word.startswith("-") or word == "-"]
        if not operands:
            continue
        target = operands[0]
        if target == "-" or any(char in _WORD_EXPANDING_CHARACTERS for char in target):
            continue
        if not Path(target).is_absolute():
            if not directories:
                continue
            target = str(Path(directories[-1]) / target)
        directories.append(os.path.normpath(target))
    return tuple(dict.fromkeys(directories))


def _anchored_spellings(form: str, cwds: tuple[str, ...]) -> list[str]:
    """The lexically collapsed paths ``form`` reaches, when they differ from its spelling.

    Ledger 00474 N184: an absolute ``form`` has its ``..`` collapsed
    (``os.path.normpath``, symlinks untouched). N221: a relative ``form`` is
    joined to each of ``cwds`` and collapsed. A home-relative or NUL-bearing
    word is left alone.
    """
    if not form or "\0" in form or form.startswith("~"):
        return []
    if form.startswith("/"):
        bases: tuple[str, ...] = ("",)
    else:
        bases = cwds
    spellings: list[str] = []
    for base in bases:
        collapsed = os.path.normpath(str(Path(base) / form) if base else form)
        if collapsed != form and collapsed not in spellings:
            spellings.append(collapsed)
    return spellings


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


_CD_EXECUTABLE: Final[str] = "cd"
_AND_SEPARATOR: Final[str] = "&&"
# A substitution in the cd TARGET runs a command and puts its output on the
# argument, so `cd $(cat <protected>)` really does disclose. A bare `cd` does
# not, and that difference is the whole basis for stripping the prefix.
_COMPOUND_MARKERS: Final[tuple[str, ...]] = ("&", "$(", "`")
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
    *,
    deadline: float | None = None,
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

    A leading ``time`` or ``!`` is looked past (Plan 00422 N25): neither
    changes which command runs or what it reads. ``then``, ``do`` and the
    other compound-only reserved words are NOT, so a fragment of a compound
    command is never judged as the single command this exemption requires.

    ``deadline`` (Plan 00466 review 8 L1) is forwarded to
    :func:`_paths_only_in_flag_position`'s per-word mention checks.
    """
    stripped = command.strip()
    if not stripped:
        return False
    stripped = _strip_leading_cd(stripped, patterns) or stripped
    stripped = strip_transparent_reserved_words(stripped)
    if _PROCESS_SUBSTITUTION in stripped:
        return False
    if any(separator in stripped for separator in _COMMAND_SEPARATORS):
        return False
    if any(marker in stripped for marker in _COMPOUND_MARKERS):
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
        return _paths_only_in_flag_position(words, consumer, patterns, deadline=deadline)
    return False


def _is_git_rm_cached(words: list[str]) -> bool:
    """True when ``words`` is ``git <global options> rm ... --cached ...`` --
    untrack only, with no content-reading flag present.

    Both option lists are CLOSED (N253). Before the subcommand only
    ``_GIT_SAFE_GLOBAL_FLAGS`` and ``-C <dir>`` are looked past; ``-c``,
    ``--config-env`` and every other global option voids the exemption,
    because a config key such as ``core.fsmonitor`` runs a command. After
    ``rm`` only ``_GIT_RM_GRAMMAR`` is accepted, so ``--pathspec-from-file`` (which makes ``rm``
    READ a file and echo its lines in an error -- Plan 00311 Task 1.3) and
    every abbreviation git would accept of it or of any other option are
    refused, not skipped. ``--cached`` must be present: without it the
    command can delete the working-tree file too, so it is not exempt.
    """
    subcommand_index = _git_closed_global_options_end(words)
    if subcommand_index is None or len(words) < subcommand_index + 2:
        return False
    if words[subcommand_index] != _GIT_RM_SUBCOMMAND:
        return False
    rm_options = _GIT_RM_GRAMMAR.option_names(words[subcommand_index + 1 :])
    return rm_options is not None and _GIT_RM_CACHED_FLAG in rm_options


#: The ONLY git global options the ``rm --cached`` exemption looks past (N253).
#: ``-c``/``--config-env`` are absent on purpose: they set ``core.fsmonitor``
#: and friends, which EXECUTE a command; ``--git-dir``/``--work-tree``/
#: ``--exec-path`` redirect which repository, config or helper git runs.
_GIT_SAFE_GLOBAL_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "--no-pager",
        "--no-optional-locks",
        "--literal-pathspecs",
        "--glob-pathspecs",
        "--noglob-pathspecs",
        "--icase-pathspecs",
        "--no-replace-objects",
    }
)
_GIT_CHDIR_FLAG: Final[str] = "-C"

_END_OF_OPTIONS: Final[str] = "--"


@dataclass(frozen=True)
class _OptionGrammar:
    """The CLOSED set of options one git subcommand may carry (N253).

    Every option is matched by its FULL name. git's parse-options accepts an
    unambiguous prefix of a long option, so an abbreviation (``--verb`` for
    ``--verbose``, ``--pathspec-from`` for ``--pathspec-from-file``) is
    refused here rather than skipped as unknown: a denylist cannot know every
    prefix, an allowlist needs no list of them.
    """

    short_flags: frozenset[str]
    long_flags: frozenset[str]
    short_valued: frozenset[str] = frozenset()
    long_valued: frozenset[str] = frozenset()
    long_optional_value: frozenset[str] = frozenset()

    def option_names(self, words: Sequence[str]) -> frozenset[str] | None:
        """The long option names in ``words``, or ``None`` if any option is outside
        the grammar. A flag takes no value (``--cached=x`` is not ``--cached``);
        a value-taking option consumes its attached value, or the next word; an
        optional-value option takes only an attached one. Words after ``--``
        and non-option words are not examined."""
        seen: set[str] = set()
        index = 0
        while index < len(words):
            word = words[index].strip("\"'")
            index += 1
            if word == _END_OF_OPTIONS:
                break
            if not word.startswith("-") or word == "-":
                continue
            if word.startswith("--"):
                name, has_value, _value = word.partition("=")
                if name in self.long_valued:
                    index += 0 if has_value else 1
                elif name in self.long_optional_value:
                    pass
                elif name not in self.long_flags or has_value:
                    return None
                seen.add(name)
                continue
            for position, letter in enumerate(word[1:], start=1):
                if letter in self.short_valued:
                    index += 0 if word[position + 1 :] else 1
                    break
                if letter not in self.short_flags:
                    return None
        return frozenset(seen)


_GIT_RM_GRAMMAR: Final[_OptionGrammar] = _OptionGrammar(
    short_flags=frozenset("rfnq"),
    long_flags=frozenset(
        {"--cached", "--force", "--dry-run", "--quiet", "--ignore-unmatch", "--sparse"}
    ),
)


def _git_closed_global_options_end(words: list[str]) -> int | None:
    """Index of the subcommand after ``git``, or ``None`` if any global option
    before it is not on the closed safe list (``-C <dir>`` is the one
    value-taking member). A leading environment assignment never gets here:
    the head word is then not ``git``."""
    index = 1
    while index < len(words):
        word = words[index].strip("\"'")
        if not word.startswith("-"):
            return index
        if word in _GIT_SAFE_GLOBAL_FLAGS:
            index += 1
        elif word == _GIT_CHDIR_FLAG and index + 1 < len(words):
            if words[index + 1].startswith("-"):
                return None
            index += 2
        else:
            return None
    return None


def _denied_subcommand_used(words: list[str], consumer: ConsumerSpec) -> bool:
    """True when ANY argument is a disclosure subcommand.

    Not just the first non-flag word: an option this module does not know may
    take a separate value (``ansible-vault --output x view``), which would
    otherwise be mistaken for the subcommand.
    """
    return any(word.strip("\"'") in consumer.denied_subcommands for word in words[1:])


def _paths_only_in_flag_position(
    words: list[str],
    consumer: ConsumerSpec,
    patterns: tuple[str, ...],
    *,
    deadline: float | None = None,
) -> bool:
    """True when no bare word other than a flag VALUE looks path-mention-risky.

    Conservative: every word is fine unless it follows nothing recognisable.
    The caller has already established the command mentions a protected path;
    this checks the mention sits directly after a recognised path flag (or in
    a ``--flag=value`` form). Any other placement voids the exemption — the
    deny rule then applies. ``patterns`` are the caller's EFFECTIVE globs —
    see ``is_exempt_invocation`` for why the defaults must not be used here.
    ``deadline`` (Plan 00466 review 8 L1) is forwarded to
    :func:`find_protected_mention` per word -- this loop's own total cost
    across many words is otherwise unbounded the same way B1 found for
    :func:`iter_protected_mentions`.
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
        # An option word is judged too (N253): `--inventory=<key>` or
        # `-i<key>` carries a path in a position no recognised path flag owns,
        # so the value after `=` and the tail of a short option are judged
        # as words of their own.
        candidates = [bare]
        if bare.startswith("-"):
            candidates.append(bare.partition("=")[2])
            if not bare.startswith("--"):
                candidates.append(bare[2:])
        if any(
            candidate and find_protected_mention(candidate, patterns, deadline=deadline) is not None
            for candidate in candidates
        ):
            return False
    return True


# ── Encrypted-target exemption (Plan 00459) ──────────────────────────────────
#
# Ciphertext is harmless to read only while the reader cannot decrypt it, and
# Ansible finds a vault password WITHOUT the command naming it (the
# `DEFAULT_VAULT_PASSWORD_FILE` config key, `ANSIBLE_VAULT_PASSWORD_FILE`), as
# does `git diff` under the common `diff=ansible-vault` textconv setup. A list
# of commands that decrypt could never be complete, so the heads below are
# the ones that CANNOT, and every other head keeps the existing verdict.

#: Plain file commands that print, count, list or relocate bytes as they are.
#: `grep` is absent on purpose: `grep -r` reads a whole tree, and the named
#: encrypted file must not vouch for the plaintext beside it (the Grep TOOL
#: covers searching an encrypted file).
_ENCRYPTED_TARGET_COMMANDS: Final[frozenset[str]] = frozenset(
    {"cat", "head", "tail", "wc", "ls", "stat", "file", "cp", "mv"}
)

#: git subcommands that never run a textconv filter (`diff`, `log`, `show`,
#: `blame` and `grep` all can), each with the CLOSED option set it may carry
#: (N253). Anything outside it -- including an abbreviation git would accept
#: of a diff-rendering or editor-opening option (`--verb`, `--patc`, `--ed`)
#: -- is not exempt. The omissions are deliberate: `-v`/`--verbose`,
#: `-p`/`--patch`, `-i`/`--interactive`, `-e`/`--edit`, `-F`, `-c`/`-C`.
_ENCRYPTED_TARGET_GIT_GRAMMARS: Final[dict[str, _OptionGrammar]] = {
    "add": _OptionGrammar(
        short_flags=frozenset("fnuAN"),
        long_flags=frozenset(
            {
                "--force",
                "--dry-run",
                "--update",
                "--all",
                "--no-all",
                "--intent-to-add",
                "--ignore-errors",
                "--renormalize",
                "--sparse",
                "--ignore-removal",
                "--no-ignore-removal",
            }
        ),
    ),
    "commit": _OptionGrammar(
        short_flags=frozenset("aqsn"),
        long_flags=frozenset({"--all", "--quiet", "--signoff", "--no-verify", "--allow-empty"}),
        short_valued=frozenset("m"),
        long_valued=frozenset({"--message"}),
    ),
    "status": _OptionGrammar(
        short_flags=frozenset("sbz"),
        long_flags=frozenset(
            {
                "--short",
                "--branch",
                "--no-renames",
                "--renames",
                "--null",
                "--long",
                "--show-stash",
                "--no-column",
                "--ahead-behind",
                "--no-ahead-behind",
            }
        ),
        long_optional_value=frozenset(
            {"--porcelain", "--ignored", "--untracked-files", "--column"}
        ),
    ),
    "mv": _OptionGrammar(
        short_flags=frozenset("fnkv"),
        long_flags=frozenset({"--force", "--dry-run", "--verbose", "--sparse"}),
    ),
    "rm": _GIT_RM_GRAMMAR,
    "ls-files": _OptionGrammar(
        short_flags=frozenset("cdmoiskztvf"),
        long_flags=frozenset(
            {
                "--cached",
                "--deleted",
                "--modified",
                "--others",
                "--ignored",
                "--stage",
                "--killed",
                "--unmerged",
                "--exclude-standard",
                "--full-name",
                "--error-unmatch",
                "--directory",
                "--no-empty-directory",
                "--eol",
                "--deduplicate",
                "--recurse-submodules",
                "--resolve-undo",
                "--sparse",
            }
        ),
    ),
    "check-ignore": _OptionGrammar(
        short_flags=frozenset("qnz"),
        long_flags=frozenset({"--quiet", "--non-matching", "--no-index"}),
    ),
}

#: Any of these makes the word the shell opens differ from the text written:
#: parameter/command substitution, escapes, line continuation, globs, braces
#: and tilde. Refused anywhere in the command, not just in the mention, since
#: an expansion in another word can change where the mention resolves.
_EXPANSION_CHARS: Final[frozenset[str]] = frozenset("$`\\\n\r*?[]{}~")

#: Operator characters shlex splits out as their own tokens.
_SHELL_OPERATOR_CHARS: Final[frozenset[str]] = frozenset("();<>|&")

#: The only operator tokens allowed: redirections. Everything else joins,
#: backgrounds, pipes or wraps commands, and a second command could change
#: directory before the first reads (`cd other && cat <file>`).
_REDIRECTION_OPERATORS: Final[frozenset[str]] = frozenset(
    {"<", ">", ">>", ">&", "<&", "&>", "&>>", "<>"}
)


def is_encrypted_target_invocation(
    command: str,
    patterns: tuple[str, ...],
    *,
    cwd: str | None,
    is_encrypted: Callable[[str], bool],
    deadline: float | None = None,
) -> bool:
    """True when ``command`` names only protected files confirmed encrypted,
    in a command that cannot decrypt them (Plan 00459).

    ALL of these must hold, and anything unrecognised fails closed:

    - one simple command: no expansion characters anywhere, quoting that
      parses, and no operator but a redirection;
    - its head is an allowlisted reader (``_ENCRYPTED_TARGET_COMMANDS``, or
      ``git`` with an allowlisted subcommand directly after it, so no global
      option such as ``-C`` can move the read, and no diff-rendering flag);
    - at least one protected mention, and EVERY one is a complete literal
      shell word that resolves -- absolute, or joined to the absolute
      ``cwd`` -- to a file ``is_encrypted`` confirms. A glob that could also
      reach a plaintext sibling is never a complete literal word.

    ``is_encrypted`` receives an absolute path and must read the file at the
    time of the call: the answer is not cached here.

    A leading ``time`` or ``!`` is looked past before the head is read, as in
    ``is_exempt_invocation``; no other reserved word is.

    ``deadline`` (Plan 00466 review 8 L1) is forwarded to
    :func:`iter_protected_mentions`.
    """
    if any(char in _EXPANSION_CHARS for char in command):
        return False
    words = _shell_words(strip_transparent_reserved_words(command))
    if not words or not _is_single_simple_command(words):
        return False
    if not _is_encrypted_target_reader(words):
        return False
    mentions = list(iter_protected_mentions(command, patterns, deadline=deadline))
    if not mentions:
        return False
    literal_words = frozenset(words)
    return all(
        _mention_is_encrypted(token, literal_words, cwd, is_encrypted)
        for _pattern, token in mentions
    )


def _shell_words(command: str) -> list[str] | None:
    """POSIX shell words with operators split out, or ``None`` if unparseable."""
    lexer = linear_shlex.LinearShlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    # `#` starts a comment only at the start of a word in bash; left as a word
    # character, nothing that bash would read is ever dropped from the view.
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError as exc:
        # Unbalanced quoting: the shell's own reading is unknown, so the
        # command is not confirmed. Registered in error_hiding_exclusions.json.
        log_and_continue(
            logger,
            exc,
            reason="a command with unbalanced quoting is not confirmed (None), so the encrypted-target exemption does not apply and the ordinary deny-by-default mention rule decides",
            level=logging.DEBUG,
        )
        return None


def _is_single_simple_command(words: list[str]) -> bool:
    for word in words:
        if word and all(char in _SHELL_OPERATOR_CHARS for char in word):
            if word not in _REDIRECTION_OPERATORS:
                return False
    return True


def _is_encrypted_target_reader(words: list[str]) -> bool:
    head = words[0]
    if head in _ENCRYPTED_TARGET_COMMANDS:
        return True
    if head != _GIT_EXECUTABLE or len(words) < 2:
        return False
    grammar = _ENCRYPTED_TARGET_GIT_GRAMMARS.get(words[1])
    return grammar is not None and grammar.option_names(words[2:]) is not None


#: grep-family binaries: their FIRST positional argument (or an `-e`
#: flag's value) is a search PATTERN, not a filesystem path.
_GREP_FAMILY_COMMANDS: Final[frozenset[str]] = frozenset({"grep", "egrep", "fgrep", _RG_HEAD})

#: Long flag whose VALUE is pattern content, never a file target.
_GREP_PATTERN_VALUE_LONG_FLAG: Final[str] = "--regexp"

#: Long flags whose VALUE is a FILE that grep itself opens and reads (taken
#: from GNU grep 3.8's `--help`, not from memory): `--file` reads patterns
#: from it, `--exclude-from` reads exclusion globs from it. Unlike a search
#: PATTERN, grep performs a real read of this path, so its value is a
#: file-target word and must be judged like any other one -- exempting it
#: would let `grep -f ~/.ssh/id_rsa docs/a.md` print the key.
_GREP_FILE_VALUE_LONG_FLAGS: Final[frozenset[str]] = frozenset({"--file", "--exclude-from"})

#: Short options that consume the rest of their token (or the next word) as
#: a value, keyed by what that value IS. GNU grep's getopt clustering means
#: the first such letter reached inside a `-xyz` cluster claims everything
#: after it in the token (attached value); letters before it in the same
#: cluster are plain flags. `e` supplies a PATTERN; `f` supplies a FILE
#: grep reads; the rest (`m`, `A`, `B`, `C`, `d`, `D`) take a value that is
#: neither, so it is consumed and dropped rather than left to be
#: misclassified as a positional file-target word.
_GREP_SHORT_PATTERN_VALUE_OPT: Final[str] = "e"
_GREP_SHORT_FILE_VALUE_OPT: Final[str] = "f"
_GREP_SHORT_OTHER_VALUE_OPTS: Final[frozenset[str]] = frozenset({"m", "A", "B", "C", "d", "D"})
_GREP_SHORT_VALUE_OPTS: Final[frozenset[str]] = (
    frozenset({_GREP_SHORT_PATTERN_VALUE_OPT, _GREP_SHORT_FILE_VALUE_OPT})
    | _GREP_SHORT_OTHER_VALUE_OPTS
)

#: The CLOSED option list (N253). An option outside it voids the exemption,
#: because GNU getopt_long accepts any unambiguous PREFIX of a long option
#: (`--rege=.` is `--regexp=.`) and ugrep has pattern-supplying options of its
#: own (`--and`); a parser that skips what it does not know would then treat
#: the real pattern slot as a file target's neighbour and exempt a command
#: that prints the file. Long options are matched by their FULL name only.
#: `--group-separator` is absent: ugrep reads its arity differently.
_GREP_FLAG_LONG_OPTIONS: Final[frozenset[str]] = frozenset(
    {
        "--basic-regexp",
        "--extended-regexp",
        "--fixed-strings",
        "--perl-regexp",
        "--byte-offset",
        "--count",
        "--dereference-recursive",
        "--files-with-matches",
        "--files-without-match",
        "--help",
        "--ignore-case",
        "--no-ignore-case",
        "--initial-tab",
        "--line-buffered",
        "--line-number",
        "--line-regexp",
        "--no-filename",
        "--no-group-separator",
        "--no-messages",
        "--null",
        "--null-data",
        "--only-matching",
        "--quiet",
        "--recursive",
        "--invert-match",
        "--silent",
        "--text",
        "--binary",
        "--version",
        "--with-filename",
        "--word-regexp",
        "--color",
        "--colour",
    }
)

#: Long options that take a value; the value must be ATTACHED (`--max-count=3`)
#: because GNU grep and ugrep disagree on whether a separate word is the value.
#: `--regexp`, `--file` and `--exclude-from` are handled separately.
_GREP_ATTACHED_VALUE_LONG_OPTIONS: Final[frozenset[str]] = frozenset(
    {
        "--after-context",
        "--before-context",
        "--binary-files",
        "--context",
        "--color",
        "--colour",
        "--devices",
        "--directories",
        "--label",
        "--max-count",
    }
)

#: Long options whose attached value is a glob matched against file names:
#: it selects which files print, so it is judged like a file target.
_GREP_FILE_SELECTOR_LONG_OPTIONS: Final[frozenset[str]] = frozenset(
    {"--include", "--exclude", "--exclude-dir"}
)

#: Short options that take no value. Digits (`-2`, context) are also allowed.
_GREP_SHORT_FLAG_OPTS: Final[frozenset[str]] = frozenset("EFGPiwxzsvVbnHhoqaIrRLlcTZU0123456789")


def _without_single_quoted_content(command: str) -> str:
    """``command`` with the inside of each plain ``'...'`` span blanked.

    Bash reads everything between single quotes literally, so a regex
    metacharacter there (``'foo\\.bar'``, ``'a|b'``) expands nothing and does
    not move any word. An ANSI-C ``$'...'`` span is left alone (its escapes
    DO decode), as is everything inside double quotes and any escaped quote.
    """
    out = list(command)
    index = 0
    in_double = False
    while index < len(command):
        char = command[index]
        if char == "\\":
            index += 2
            continue
        if char == '"':
            in_double = not in_double
        elif char == "'" and not in_double:
            if index > 0 and command[index - 1] == "$":
                return command
            close = command.find("'", index + 1)
            if close < 0:
                return command
            out[index + 1 : close] = " " * (close - index - 1)
            index = close
        index += 1
    return "".join(out)


def is_grep_pattern_only_mention(
    command: str,
    patterns: tuple[str, ...] = DEFAULT_PROTECTED_PATTERNS,
    *,
    deadline: float | None = None,
) -> bool:
    """True when EVERY protected mention in ``command`` sits only in a
    grep-family command's PATTERN argument, never in a FILE-TARGET argument
    (Plan 00466 niggle, gd5_fp review probe).

    Searching FOR a protected name's literal text is not reading the file:
    ``grep 'id_rsa' docs/ssh-setup.md`` was denied outright, blocking an
    ordinary documentation search that never opens the real key. The
    protected mention here is the search PATTERN, not a path.

    Scoped the same way :func:`is_encrypted_target_invocation` is (and
    reusing its exact primitives): no expansion character anywhere in
    ``command`` (glob, substitution, tilde -- keeping this to the simple,
    fully-literal case), one parseable simple command (no separator, pipe,
    or redirection-that-isn't-a-redirect), head is a bare grep/egrep/fgrep.

    Only ``-e``/``--regexp`` supplies a PATTERN. ``-f``/``--file`` and
    ``--exclude-from`` name a FILE that grep itself opens and reads (GNU
    grep 3.8's own ``--help`` lists no other file-reading pattern/exclusion
    flags), so their value is checked exactly like a file-target word, not
    exempted as a pattern -- this is what stops ``grep -f ~/.ssh/id_rsa
    docs/a.md`` (main denies it; an earlier version of this exemption
    wrongly allowed it, Plan 00466 review 8 MAJOR-A) and an attached
    ``-f<key>``/``--file=<key>``/``--exclude-from=<key>`` value from
    slipping through, whether the flag stands alone or is clustered with
    other short options (``-rhf <key>``).

    Every OTHER bare positional word (after the pattern slot -- an
    ``-e``/``--regexp`` flag's value when present, otherwise the first bare
    word) is a file-target argument and is checked with the SAME per-token
    judge (:func:`_token_mention`) the rest of the scan trusts; if ANY of
    them, or any ``-f``/``--file``/``--exclude-from`` value, is itself a
    protected mention, the exemption does not apply and the deny rule
    stands -- this is what stops ``grep foo ~/.ssh/id_rsa``-shaped commands
    (though the tilde alone already fails closed above) or ``grep id_rsa
    id_rsa`` (the second, file-target occurrence) from slipping through.

    ``deadline`` (Plan 00466 review 8 L1) is forwarded to
    :func:`iter_protected_mentions`.
    """
    if any(char in _EXPANSION_CHARS for char in _without_single_quoted_content(command)):
        return False
    words = _shell_words(strip_transparent_reserved_words(command))
    if not words or not _is_single_simple_command(words):
        return False
    head = words[0]
    if head not in _GREP_FAMILY_COMMANDS:
        return False

    saw_explicit_pattern_source = False
    file_target_values: list[str] = []
    positional_indices: list[int] = []
    cursor = 1
    end_of_options = False
    while cursor < len(words):
        word = words[cursor]
        if not end_of_options and word == "--":
            end_of_options = True
            cursor += 1
            continue
        if end_of_options or word == "-" or not word.startswith("-"):
            positional_indices.append(cursor)
            cursor += 1
            continue
        if word.startswith("--"):
            long_flag, has_eq, attached_value = word.partition("=")
            if long_flag == _GREP_PATTERN_VALUE_LONG_FLAG:
                saw_explicit_pattern_source = True
                # The value is pattern content either way; nothing to check.
                if not has_eq and cursor + 1 < len(words):
                    cursor += 1
                cursor += 1
                continue
            if long_flag in _GREP_FILE_VALUE_LONG_FLAGS:
                if long_flag == "--file":
                    saw_explicit_pattern_source = True
                if has_eq:
                    file_target_values.append(attached_value)
                elif cursor + 1 < len(words):
                    file_target_values.append(words[cursor + 1])
                    cursor += 1
                cursor += 1
                continue
            if long_flag in _GREP_FILE_SELECTOR_LONG_OPTIONS and has_eq:
                file_target_values.append(attached_value)
            elif not (
                (long_flag in _GREP_ATTACHED_VALUE_LONG_OPTIONS and has_eq)
                or (long_flag in _GREP_FLAG_LONG_OPTIONS and not has_eq)
            ):
                return False
            cursor += 1
            continue
        # Short-option cluster: GNU grep's getopt claims the rest of the
        # token for the FIRST value-taking letter it reaches, attached if
        # anything follows in the token, otherwise the next word.
        consumed_next = False
        for position, letter in enumerate(word[1:], start=1):
            if letter not in _GREP_SHORT_VALUE_OPTS:
                if letter not in _GREP_SHORT_FLAG_OPTS:
                    return False
                continue
            attached_value = word[position + 1 :]
            value: str | None
            if attached_value:
                value = attached_value
            elif cursor + 1 < len(words):
                value = words[cursor + 1]
                consumed_next = True
            else:
                value = None
            if letter == _GREP_SHORT_PATTERN_VALUE_OPT:
                saw_explicit_pattern_source = True
                # Pattern content either way; nothing to check.
            elif letter == _GREP_SHORT_FILE_VALUE_OPT:
                saw_explicit_pattern_source = True
                if value is not None:
                    file_target_values.append(value)
            break
        cursor += 2 if consumed_next else 1

    if not saw_explicit_pattern_source and positional_indices:
        positional_indices = positional_indices[1:]

    mentions = list(iter_protected_mentions(command, patterns, deadline=deadline))
    if not mentions:
        return False

    project_root = resolve_project_root()
    stem_pairs = _pattern_literal_stems(patterns)
    # Team-lead's memoisation cut: this loop calls `_token_mention` directly,
    # outside `iter_protected_mentions`'s own per-scan `mention_cache`, so a
    # file-target word repeated across several positional arguments would
    # otherwise pay for a fresh `os.path.realpath` syscall every occurrence.
    # LOCAL to this one call, never module-level (N23).
    realpath_cache: dict[str, str | None] = {}
    file_target_words = [words[index] for index in positional_indices] + file_target_values
    for target_word in file_target_words:
        if (
            _token_mention(
                target_word,
                patterns,
                stem_pairs,
                project_root,
                realpath_cache=realpath_cache,
            )
            is not None
        ):
            return False
    return True


def _mention_is_encrypted(
    token: str,
    literal_words: frozenset[str],
    cwd: str | None,
    is_encrypted: Callable[[str], bool],
) -> bool:
    # A token that is only PART of a shell word (`x<file>`, `--flag=<file>`,
    # a commit message naming it) does not name the file the command opens.
    if token not in literal_words or token.startswith("-"):
        return False
    path = resolve_against_cwd(token, cwd)
    return path is not None and is_encrypted(path)


def resolve_against_cwd(path: str, cwd: str | None) -> str | None:
    """``path`` as a normalised absolute path, or ``None`` if that is unknowable.

    A relative path means nothing without the caller's working directory,
    and resolving it against the DAEMON's would judge a different file, so
    a missing or relative ``cwd`` answers ``None`` rather than a guess.
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        if cwd is None or not Path(cwd).is_absolute():
            return None
        candidate = Path(cwd) / candidate
    return os.path.normpath(candidate)
