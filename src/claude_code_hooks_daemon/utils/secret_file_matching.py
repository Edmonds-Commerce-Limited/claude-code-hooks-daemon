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
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.utils.path_exclusion import (
    path_matches_globs,
    resolve_project_root,
)

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

# The metadata helper: the ONE universally-exempt way to mention a protected
# path in Bash. Recognised as `<anything>/hooks-daemon secret-meta ...` (or a
# bare `hooks-daemon`), so both the project wrapper and a PATH install work.
_HELPER_EXECUTABLE: Final[str] = "hooks-daemon"
SECRET_META_SUBCOMMAND: Final[str] = "secret-meta"

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
    for token in _tokenise(command):
        for form in _normalised_token_forms(token):
            for pattern in patterns:
                if path_matches_globs(form, (pattern,), project_root=project_root):
                    return pattern
            if any(char in form for char in _GLOB_CHARS):
                for stem, pattern in stem_pairs:
                    basename = form.rsplit("/", maxsplit=1)[-1]
                    stem_basename = stem.rsplit("/", maxsplit=1)[-1]
                    if fnmatch.fnmatch(stem_basename, basename):
                        return pattern
        real = _realpath_if_resolvable(token)
        if real is not None:
            for pattern in patterns:
                if path_matches_globs(real, (pattern,), project_root=project_root):
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
    the compound as a whole is judged by the deny rule instead.
    """
    stripped = command.strip()
    if not stripped:
        return False
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

    for consumer in consumers:
        if head_base != consumer.command:
            continue
        if _denied_subcommand_used(words, consumer):
            return False
        return _paths_only_in_flag_position(words, consumer, patterns)
    return False


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
