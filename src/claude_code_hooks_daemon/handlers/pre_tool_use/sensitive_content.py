"""SensitiveContentHandler - block Write/Edit content matching configured
sensitive patterns or a gitignored secret word list (Plan 00201).

Two independent sources:

- **Public patterns** (``options.public_patterns``): named regexes declared
  in ``.claude/hooks-daemon.yaml``, safe to name in the deny reason (paths,
  non-placeholder home dirs, session UUIDs, profanity, ...). The reason
  SHOULD say what matched — that is what makes it fixable.
- **Secret word list** (``options.secret_word_list_path``, default
  ``.claude/block-words.secret``): plain text, one gitignored term per line.
  A match here must NEVER reveal the term or its surrounding context — only
  a 1-based index into the (gitignored, hence meaningless-without-it) file.
  All loading/matching for this source is delegated to
  ``utils/secret_redaction.py``, the ONE place the raw terms are ever read.

Threat model: a deny ``reason`` is shown to the user, written to the session
transcript, and may be pasted into a bug report — so it is exactly as public
as this repo's own source code.

Surfaces, all judged by the same two sources (Plan 00362 Task 2.4 made the
last two part of this ONE guard rather than a sibling):

- ``Write``/``Edit`` — the path and the added text.
- ``git`` metadata commands — the command line (messages, refs, identity).
- ``git commit`` — the ADDED lines of what the commit would record (Plan
  00252 Phase 3). A file that arrived by ``mv``/``cp`` and was staged never
  passed a Write/Edit; the commit is the last moment it can be stopped
  without a history rewrite. Only the path and the entry index are ever
  reported, never a line.
- ``gh issue|pr comment|create|edit`` — the body, inline or from
  ``--body-file``/``-F`` (Plan 00264 Question 7). A GitHub comment is more
  public than a commit and nothing can retract it.
"""

import logging
import re
import shlex
from pathlib import Path
from typing import Any, ClassVar, Final, NamedTuple

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler import WorkspaceScope
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.utils import secret_redaction as sr
from claude_code_hooks_daemon.utils.command_evasion import git_subcommand_index
from claude_code_hooks_daemon.utils.git_repo import GitRepo, run_git
from claude_code_hooks_daemon.utils.path_exclusion import (
    handler_excludes_path,
    resolve_project_root,
)
from claude_code_hooks_daemon.utils.path_predicates import path_is_file
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LOGGER = logging.getLogger(__name__)

# Two independent rules (Plan 00116, Decision B): the two sources have
# genuinely different disclosure properties -- a public-pattern match is safe
# to name in full, a secret-word-list match must NEVER echo the term or its
# surrounding context. `Rule.verbose` for both is STATIC boilerplate only;
# the actual diagnostic (subject, pattern name/matched text, or entry index)
# is invocation-specific and is appended in `handle()`, never baked into a
# Rule -- for the secret-term rule that append path is the ONLY place the
# redaction contract is enforced, so it must never carry the raw term.
_RULE_PUBLIC_PATTERN = Rule(
    rule_id=RuleID.SENSITIVE_PUBLIC_PATTERN,
    blocked="content matching a configured public pattern",
    why="The pattern is a named, safe-to-disclose signal (a path, a placeholder, profanity, ...)",
    fix="Remove or replace the matched text before retrying",
    verbose=(
        "Public patterns are named regexes declared in `.claude/hooks-daemon.yaml`, "
        "safe to name in this reason -- the pattern name and the exact matched text "
        "are shown below so the write is fixable."
    ),
)

_RULE_SECRET_TERM = Rule(
    rule_id=RuleID.SENSITIVE_SECRET_TERM,
    blocked="content matching a configured blocked term",
    why="A gitignored secret word list term was found in what this call would record",
    fix="Ask the user what the cited entry covers, then remove the matching text",
    verbose=(
        "The term is deliberately not shown, and the word list file "
        f"(`{sr.DEFAULT_SECRET_WORD_LIST_PATH}`) is itself read-protected by "
        "secret_file_guard — do not try to open it. Only an entry INDEX is cited "
        "below, which is meaningless without the gitignored file itself."
    ),
)

_FIELD_FILE_PATH: Final[str] = "file_path"
_FIELD_CONTENT: Final[str] = "content"
_FIELD_NEW_STRING: Final[str] = "new_string"
_FIELD_COMMAND: Final[str] = "command"

# Neutral label for the offending thing named in a deny reason: a file path for
# Write/Edit, a command line for Bash. It was "File:" while only file writes
# were guarded, which now reads as a lie half the time.
_SUBJECT_LABEL: Final[str] = "Offending input"

# Git METADATA write surfaces. Contents and paths are only two of the seven
# places a term can enter a repository; the other five are metadata, and every
# one of them arrives as a Bash `git` invocation:
#
#   commit   -> commit messages          (filter-repo: --replace-message)
#   config   -> author/committer identity(filter-repo: --mailmap)
#   tag      -> tag names AND messages   (filter-repo: manual re-tag)
#   branch   -> branch names             (filter-repo: manual rename)
#   checkout -> `-b` creates a branch
#   switch   -> `-c` creates a branch
#   merge    -> `-m` writes a merge commit message
#
# Gated on a `git` invocation, never on the bare subcommand word: "commit",
# "tag" and "branch" are ordinary English, so matching them alone would deny
# any sentence mentioning a branch.
_GIT_EXECUTABLE: Final[str] = "git"
_GIT_METADATA_WRITE_SUBCOMMANDS: Final[tuple[str, ...]] = (
    "commit",
    "config",
    "tag",
    "branch",
    "checkout",
    "switch",
    "merge",
)

# Read-only git operations that TAKE a ref/pattern as an operand, so a term on
# the command line means the caller is INSPECTING one, not creating one. These
# must stay allowed: searching for a term and removing it are exactly the work
# of cleaning a repository, and a guard that blocks its own remedy gets
# switched off.
_GIT_READ_ONLY_FLAGS: Final[tuple[str, ...]] = ("--grep", "--list", "-l", "--get")

_GIT_COMMIT_SUBCOMMAND: Final[str] = "commit"

# `git commit -a`/`--all` stages every tracked modification AT commit time, so
# the index is not yet what the commit records -- the working tree is. `-am`
# and similar clusters carry the `a` inside a short-flag run.
_COMMIT_ALL_LONG_FLAG: Final[str] = "--all"
_COMMIT_ALL_SHORT_LETTER: Final[str] = "a"

# Everything after `--` is an operand, so a pathspec named `-a` is a file.
_END_OF_OPTIONS: Final[str] = "--"

# Short options of `git commit` that CONSUME a value: the letters after one of
# these inside a cluster belong to that value, not to another flag, so
# `-mall day` is a message and not `--all`. The first set's value is REQUIRED,
# so a cluster ending there takes the next token too (`-m msg`); `-S`/`-u`
# take an optional value, which git accepts only attached.
_COMMIT_SHORT_FLAGS_WITH_REQUIRED_VALUE: Final[str] = "mcCFt"
_COMMIT_SHORT_FLAGS_WITH_OPTIONAL_VALUE: Final[str] = "Su"

# Long options of `git commit` whose value is a SEPARATE token: the only
# places a leading dash can appear without being a flag of its own.
_COMMIT_LONG_FLAGS_WITH_VALUE: Final[frozenset[str]] = frozenset(
    {
        "--message",
        "--file",
        "--template",
        "--author",
        "--date",
        "--cleanup",
        "--reuse-message",
        "--reedit-message",
        "--fixup",
        "--squash",
        "--trailer",
        "--pathspec-from-file",
    }
)

# Staged-content bounds (Plan 00252 Task 3.2: decide the limit here rather
# than meet it as a timeout in the field). A single file whose ADDED lines
# exceed the per-file bound is stood down and logged by path; once the
# running total passes the whole-commit bound, the remaining files are stood
# down too. Neither is scanned partially: either a file was judged in full
# or the log says it was not. 512 KiB is far above any prose or source file
# and well inside what the term matcher handles in milliseconds; a generated
# artefact or vendored bundle past it is what the bound is for.
MAX_STAGED_FILE_BYTES: Final[int] = 512 * 1024
MAX_STAGED_TOTAL_BYTES: Final[int] = 4 * 1024 * 1024

# `git diff --diff-filter=ACM`: Added, Copied, Modified. A deleted or
# renamed-away path introduces no content. `--unified=0` drops context lines
# so only the ADDED lines (`+`) are ever read -- removing a term must never
# be blocked, and unchanged neighbours are not this commit's doing.
_DIFF_FILTER: Final[str] = "ACM"
_DIFF_HEADER_PREFIX: Final[str] = "diff --git "
_DIFF_ADDED_PREFIX: Final[str] = "+"
_DIFF_FILE_HEADER_PREFIX: Final[str] = "+++ "
_DIFF_PATH_PREFIX: Final[str] = "b/"

# The C escapes git writes when it quotes a path (`quote_c_style`), plus its
# three-digit octal form for any byte outside printable ASCII. Decoding is a
# byte operation: `\303\251` is ONE character in UTF-8, not two.
_C_QUOTE_ESCAPES: Final[dict[str, int]] = {
    "a": 0x07,
    "b": 0x08,
    "f": 0x0C,
    "n": 0x0A,
    "r": 0x0D,
    "t": 0x09,
    "v": 0x0B,
    "\\": 0x5C,
    '"': 0x22,
}
_OCTAL_ESCAPE_DIGITS: Final[int] = 3
_OCTAL_DIGITS: Final[str] = "01234567"

# `gh` subcommands that PUBLISH a body to GitHub. `view`/`list`/`checkout`
# read; `gh api` is deliberately outside this surface (its `-F` means a
# field, and a body there is one generic parameter among many), so it is
# documented as uncovered rather than half-covered.
_GH_EXECUTABLE: Final[str] = "gh"
_GH_BODY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[\s;&|(])gh\s+(?:issue|pr)\s+(?:comment|create|edit)\b"
)
# `--body-file <path>` / `--body-file=<path>` / `-F <path>`, bare or quoted.
_GH_BODY_FILE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:--body-file|-F)(?:\s+|=)(?:\"([^\"]+)\"|'([^']+)'|(\S+))"
)
_STDIN_BODY_FILE: Final[str] = "-"
# A body file larger than this is skipped rather than read (the same bound
# `github_auto_close_keywords` applies to its message files).
_MAX_BODY_FILE_BYTES: Final[int] = 65_536
_BODY_FILE_ENCODING: Final[str] = "utf-8"
_BODY_FILE_DECODE_ERRORS: Final[str] = "replace"

_PATTERN_KEY_NAME: Final[str] = "name"
_PATTERN_KEY_PATTERN: Final[str] = "pattern"
_PATTERN_KEY_DESCRIPTION: Final[str] = "description"


class _DispatchKey(NamedTuple):
    """What tells one tool call's haystacks apart from another's.

    Derived from the call's own CONTENT, never from the address of the dict
    carrying it. ``id()`` is unique only among LIVE objects, and the daemon
    frees each event's dict when its dispatch ends -- so a later dict
    allocated at that address compares equal to an address-derived key and
    the handler answers the new event from the previous event's text. The
    daemon also dispatches on a thread pool, so one handler instance is
    genuinely shared between concurrently allocating events.

    ``cwd`` is part of the key because the staged-diff surface belongs to a
    REPOSITORY: the same commit command in another worktree is a different
    call with different content.
    """

    session_id: str
    cwd: str
    tool_name: str
    subject: str
    body: str


class _Haystack(NamedTuple):
    """One piece of text a tool call would introduce, and what to call it.

    ``subject`` is what the deny reason names as the offending thing. It is
    itself redacted before it reaches a secret-term reason (a path or a
    command line can carry the term), and it is NEVER the text -- for a
    staged blob or a body file the text stays where it is and only the path
    is cited.
    """

    subject: str
    text: str


def _shell_tokens(command: str) -> list[str]:
    """Shell tokens of ``command``, falling back to whitespace splitting.

    An unbalanced quote is not something the shell would run either, so
    ``shlex`` raising means there is no correct tokenisation to be had. The
    naive split still locates the subcommand, and reading an extra flag out of
    it scans MORE than the commit records rather than less -- the safe
    direction for a guard.
    """
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _read_short_cluster(letters: str) -> tuple[bool, bool]:
    """``(cluster carries -a, cluster consumes the next token)``.

    A short cluster ends at the first letter that takes a value: everything
    after it is that value. Reading straight through instead is how a
    ``-m``-attached message was mined for flags.
    """
    for position, letter in enumerate(letters):
        if letter == _COMMIT_ALL_SHORT_LETTER:
            return True, False
        if letter in _COMMIT_SHORT_FLAGS_WITH_OPTIONAL_VALUE:
            return False, False
        if letter in _COMMIT_SHORT_FLAGS_WITH_REQUIRED_VALUE:
            return False, position == len(letters) - 1
    return False, False


def _commits_working_tree(options: list[str]) -> bool:
    """True when this ``git commit`` option run carries ``-a``/``--all``.

    Walks the options rather than testing each token independently, because
    whether a token IS an option depends on what came before it: an option's
    value, and anything after ``--``, are operands.
    """
    index = 0
    while index < len(options):
        option = options[index]
        index += 1
        if option == _END_OF_OPTIONS:
            return False
        if option == _COMMIT_ALL_LONG_FLAG:
            return True
        if option.startswith("--"):
            if option in _COMMIT_LONG_FLAGS_WITH_VALUE:
                index += 1
            continue
        if len(option) < 2 or not option.startswith("-"):
            continue
        carries_all, consumes_next = _read_short_cluster(option[1:])
        if carries_all:
            return True
        if consumes_next:
            index += 1
    return False


def _is_git_commit(command: str) -> tuple[bool, bool]:
    """``(is a git commit, commits the working tree via -a/--all)``.

    Locates the subcommand exactly as
    :meth:`SensitiveContentHandler._writes_git_metadata` does, but over SHELL
    tokens: this function also reads option VALUES, and a value is only
    distinguishable from a flag once quoting is applied. Splitting on
    whitespace made every dashed word of a quoted message an option, so
    ``git commit -m 'fix the -a flag handling'`` diffed the whole dirty
    working tree and let an UNSTAGED file deny a commit that never included
    it.
    """
    tokens = _shell_tokens(command)
    for position, token in enumerate(tokens[:-1]):
        if token != _GIT_EXECUTABLE and not token.endswith(f"/{_GIT_EXECUTABLE}"):
            continue
        subcommand_index = git_subcommand_index(tokens, position)
        if subcommand_index is None or tokens[subcommand_index] != _GIT_COMMIT_SUBCOMMAND:
            continue
        return True, _commits_working_tree(tokens[subcommand_index + 1 :])
    return False, False


def _is_octal_escape(text: str) -> bool:
    """True when ``text`` is a complete three-digit octal escape body."""
    return len(text) == _OCTAL_ESCAPE_DIGITS and all(digit in _OCTAL_DIGITS for digit in text)


def _unquote_diff_path(raw: str) -> str:
    """Decode git's C-quoted header path back to the real name.

    ``core.quotePath`` defaults to true, so a path carrying a non-ASCII byte,
    a quote, a backslash or a tab arrives as ``"b/caf\\303\\251.md"``: octal
    escapes, and the ``b/`` prefix INSIDE the quotes where ``removeprefix``
    cannot reach it. An undecoded key then matches no exclude glob and no
    secret-list path, so an allowlist stops working on a file-name property
    nobody would connect to it.

    An unquoted path is returned untouched: a backslash there is a literal
    character of the name, not an escape.
    """
    if len(raw) < 2 or not raw.startswith('"') or not raw.endswith('"'):
        return raw
    body = raw[1:-1]
    decoded = bytearray()
    index = 0
    while index < len(body):
        char = body[index]
        index += 1
        if char != "\\":
            decoded.extend(char.encode(_BODY_FILE_ENCODING))
            continue
        if index >= len(body):
            # A trailing lone backslash is not an escape git would emit.
            decoded.extend(b"\\")
            break
        escape = body[index]
        octal = body[index : index + _OCTAL_ESCAPE_DIGITS]
        if escape in _C_QUOTE_ESCAPES:
            decoded.append(_C_QUOTE_ESCAPES[escape])
            index += 1
        elif _is_octal_escape(octal):
            decoded.append(int(octal, 8))
            index += _OCTAL_ESCAPE_DIGITS
        else:
            decoded.extend(f"\\{escape}".encode(_BODY_FILE_ENCODING))
            index += 1
    return decoded.decode(_BODY_FILE_ENCODING, errors=_BODY_FILE_DECODE_ERRORS)


def _added_lines_by_path(diff_output: str) -> dict[str, str]:
    """Map each path in a ``--unified=0`` diff to its ADDED lines only.

    A binary blob prints no ``+`` lines (git says "Binary files differ"), so
    it maps to an empty string and is never scanned -- the skip is inherent,
    not a special case.
    """
    added: dict[str, str] = {}
    current: str | None = None
    for line in diff_output.splitlines():
        if line.startswith(_DIFF_HEADER_PREFIX):
            current = None
            continue
        if line.startswith(_DIFF_FILE_HEADER_PREFIX):
            target = line[len(_DIFF_FILE_HEADER_PREFIX) :].strip()
            current = _unquote_diff_path(target).removeprefix(_DIFF_PATH_PREFIX)
            added.setdefault(current, "")
            continue
        if current is not None and line.startswith(_DIFF_ADDED_PREFIX):
            added[current] += line[len(_DIFF_ADDED_PREFIX) :] + "\n"
    return added


# Compiled-pattern cache: the same handful of client public_patterns are
# matched on every Write/Edit, so translating + compiling once is worth it.
# An invalid regex is cached as None so it is never re-attempted per event.
_COMPILED_PATTERN_CACHE: dict[str, "re.Pattern[str] | None"] = {}


def _compiled_public_pattern(pattern: str) -> "re.Pattern[str] | None":
    """Compile ``pattern`` (case-insensitive), caching by source string.

    A pattern that fails to compile is a documented no-match (never crashes
    the handler) — cached as ``None`` so a broken client config is not
    re-attempted on every event.
    """
    if pattern in _COMPILED_PATTERN_CACHE:
        return _COMPILED_PATTERN_CACHE[pattern]
    try:
        compiled: re.Pattern[str] | None = re.compile(pattern, re.IGNORECASE)
    except re.error:
        compiled = None
    _COMPILED_PATTERN_CACHE[pattern] = compiled
    return compiled


class SensitiveContentHandler(PreToolUseHandlerBase):
    """Block Write/Edit content matching configured public patterns or a secret word list.

    Configuration options (``handlers.pre_tool_use.sensitive_content.options``):
        public_patterns: list of ``{name, pattern, description}`` dicts —
            safe-to-name regexes. Default empty (config is truth; no
            hardcoded patterns ship for client projects).
        secret_word_list_path: path to the gitignored secret word list,
            relative to the project root unless absolute. Default
            ``.claude/block-words.secret``. Missing file = feature inert.
        exclude_paths: glob patterns exempted from scanning, additive with
            the project-wide ``daemon.exclude_paths``.
    """

    # PROJECT-scoped: the exclusion check consults the OWNING project's
    # vendored set via `layout_for()` (Plan 00331 Task 1.3), and the REPO
    # contract forbids a repo-singular handler consuming per-project
    # resolution.
    workspace_scope: ClassVar[WorkspaceScope] = WorkspaceScope.PROJECT

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SENSITIVE_CONTENT,
            priority=Priority.SENSITIVE_CONTENT,
            tags=[
                HandlerTag.SAFETY,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
                HandlerTag.FILE_OPS,
                HandlerTag.CONTENT_QUALITY,
            ],
        )
        # Config options — injected by the registry via setattr; typed and
        # defaulted here so mypy sees real attributes, not dynamic ones.
        self._public_patterns: list[dict[str, str]] = []
        self._secret_word_list_path: str | None = None
        self._exclude_paths: list[str] | None = None
        # Per-dispatch bridge: matches() and handle() see the same call, so
        # the staged diff costs ONE subprocess and a body file ONE read. Key
        # and value live in a SINGLE attribute so a concurrent dispatch can
        # never pair one call's key with another call's haystacks -- one
        # assignment is atomic, two are not.
        self._cached_dispatch: tuple[_DispatchKey, list[_Haystack]] | None = None

    def _get_content(self, hook_input: dict[str, Any]) -> str:
        """Content to check: full content for Write, only the ADDED text for Edit.

        Edit's ``old_string`` is deliberately never checked — removing
        sensitive text must never itself be blocked.
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        if tool_name == ToolName.EDIT:
            return str(tool_input.get(_FIELD_NEW_STRING, ""))
        return str(tool_input.get(_FIELD_CONTENT, ""))

    def _is_excluded(self, file_path: str) -> bool:
        """Return True if file_path matches a client-configured exclude glob."""
        return handler_excludes_path(
            file_path,
            handler_patterns=self._exclude_paths,
            project_patterns=self._project_exclude_paths,
            layout=self.layout_for(file_path),
        )

    def _find_public_pattern_match(self, content: str) -> dict[str, str] | None:
        """First configured public pattern whose regex matches ``content``, else None.

        Returns the ORIGINAL pattern dict (with the actual matched substring
        attached under a synthetic ``_matched`` key) so the caller can build
        an exact, fixable deny reason.
        """
        for entry in self._public_patterns:
            pattern = entry.get(_PATTERN_KEY_PATTERN, "")
            if not pattern:
                continue
            compiled = _compiled_public_pattern(pattern)
            if compiled is None:
                continue
            match = compiled.search(content)
            if match:
                return {**entry, "_matched": match.group(0)}
        return None

    def scan_text(self, content: str) -> str | None:
        """Reason ``content`` must not be written, or None when it is clean.

        Public because content can enter the repository by routes this
        handler's own hook never sees. Plan 00326's ``remote-docs`` capture
        writes a fetched upstream page straight to disk from a CLI, so
        without this it could vendor an authenticated page's secrets with no
        check at all.

        The secret-word arm deliberately reports only an INDEX, never the
        term (the same disclosure rule the deny path follows).
        """
        public_match = self._find_public_pattern_match(content)
        if public_match is not None:
            name = public_match.get(_PATTERN_KEY_NAME, "unnamed pattern")
            return f"matches the sensitive-content pattern `{name}`"

        terms = self._secret_terms()
        for index, term in enumerate(terms, start=1):
            if sr.find_first_match_index(content, (term,)) is not None:
                return f"matches entry {index} of {len(terms)} in the secret word list"
        return None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        haystacks = self._compute_and_cache(hook_input)
        if not haystacks:
            return False

        if any(self._find_public_pattern_match(hay.text) is not None for hay in haystacks):
            return True

        terms = self._secret_terms()
        return any(sr.find_first_match_index(hay.text, terms) is not None for hay in haystacks)

    def _dispatch_key(self, hook_input: dict[str, Any]) -> _DispatchKey:
        """Identify this tool call by what it carries, never by where it lives."""
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        command = str(tool_input.get(_FIELD_COMMAND, ""))
        return _DispatchKey(
            session_id=str(hook_input.get(HookInputField.SESSION_ID, "")),
            cwd=str(hook_input.get(HookInputField.CWD, "")),
            tool_name=str(hook_input.get(HookInputField.TOOL_NAME, "")),
            subject=command or str(tool_input.get(_FIELD_FILE_PATH, "")),
            body=self._get_content(hook_input),
        )

    def _compute_and_cache(self, hook_input: dict[str, Any]) -> list[_Haystack]:
        """Compute this call's haystacks, leaving them for its own ``handle()``.

        Deliberately never READS the cache. The entry is a one-shot bridge
        across a single dispatch, not a memo across calls: the index can be
        restaged between two textually identical commit commands, so a second
        dispatch pays for its own diff rather than inheriting a stale one.
        """
        haystacks = self._compute_haystacks(hook_input)
        self._cached_dispatch = (self._dispatch_key(hook_input), haystacks)
        return haystacks

    def _take_cached_haystacks(self, hook_input: dict[str, Any]) -> list[_Haystack]:
        """The haystacks ``matches()`` computed for THIS call, else fresh ones.

        ``matches()`` and ``handle()`` must never disagree about what was
        inspected — a divergence there denies with a reason derived from text
        the match was not based on — but agreement is only worth having when
        the two are looking at the SAME call, which is what the key check
        establishes. Reading the entry consumes it: ``handle()`` is its last
        reader, and the text it holds (staged file content, a body file) is
        exactly what this handler exists to keep out of sight.
        """
        cached = self._cached_dispatch
        if cached is not None and cached[0] == self._dispatch_key(hook_input):
            self._cached_dispatch = None
            return cached[1]
        return self._compute_haystacks(hook_input)

    def commit_side_effects(self, hook_input: dict[str, Any], chain_decision: Decision) -> None:
        """Release the text this call introduced, whatever the chain decided.

        ``matches()`` can be the last method a dispatch calls here — another
        terminal handler denies first, so ``handle()`` never runs and never
        consumes the entry. The chain's post-decision hook is then the only
        place that retained content is dropped from an instance that lives
        for the whole daemon process.
        """
        self._cached_dispatch = None

    def _compute_haystacks(self, hook_input: dict[str, Any]) -> list[_Haystack]:
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name == ToolName.BASH:
            return self._bash_haystacks(hook_input)
        if tool_name not in (ToolName.WRITE, ToolName.EDIT):
            return []

        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        file_path = str(tool_input.get(_FIELD_FILE_PATH, ""))
        if not file_path or self._is_excluded(file_path):
            return []
        if self._is_secret_list_itself(file_path):
            return []
        return self._haystacks(hook_input, file_path)

    def _bash_haystacks(self, hook_input: dict[str, Any]) -> list[_Haystack]:
        """The Bash surfaces: git metadata, staged content, and ``gh`` bodies.

        Deliberately NOT every Bash command. A term legitimately appears on the
        command line when searching for it, reading a file containing it, or
        running the tooling that REMOVES it. Denying those blocks the remedy,
        and a guard that obstructs its own cleanup gets switched off — which
        costs more than the leak it prevents.
        """
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        command = str(tool_input.get(_FIELD_COMMAND, ""))
        if not command:
            return []
        haystacks: list[_Haystack] = []
        if self._writes_git_metadata(command) or _GH_BODY_PATTERN.search(command):
            # Git metadata: five of the seven surfaces that can carry a term
            # into a repository, none of them a file write -- one
            # `git commit -m "<term>"` re-contaminates a history that was
            # just rewritten clean. A `gh` body inline on the command line
            # is judged the same way, as the command itself.
            haystacks.append(_Haystack(subject=command, text=command))
        if _GH_BODY_PATTERN.search(command):
            haystacks.extend(self._gh_body_file_haystacks(command, hook_input))
        is_commit, commits_all = _is_git_commit(command)
        if is_commit:
            haystacks.extend(self._staged_content_haystacks(hook_input, commits_all))
        return haystacks

    def _gh_body_file_haystacks(self, command: str, hook_input: dict[str, Any]) -> list[_Haystack]:
        """Content of every readable ``--body-file``/``-F`` named in ``command``.

        A missing, unreadable, stdin (``-``) or oversized file cannot be
        judged and is skipped: ``gh`` fails on a missing file itself, and a
        body that big is not a comment a human wrote.
        """
        haystacks: list[_Haystack] = []
        for match in _GH_BODY_FILE_PATTERN.finditer(command):
            raw = next(group for group in match.groups() if group)
            if raw == _STDIN_BODY_FILE:
                continue
            path = Path(raw)
            if not path.is_absolute():
                cwd = hook_input.get(HookInputField.CWD)
                if isinstance(cwd, str) and cwd:
                    path = Path(cwd) / path
            if not path_is_file(path, unreadable_means=False):
                _LOGGER.debug("sensitive_content: skipping unreadable gh body file %s", path)
                continue
            body = self._read_body_file(path)
            if not body:
                continue
            haystacks.append(_Haystack(subject=f"gh body file {path}", text=body))
        return haystacks

    @staticmethod
    def _read_body_file(path: Path) -> str:
        """Text of ``path``, or ``""`` when there is nothing to judge.

        ``path_is_file(unreadable_means=False)`` answers False only when the
        STAT fails, and statting a file is not reading it: a file whose own
        mode denies read stats perfectly well, and so does one unlinked
        between that check and this read. Letting either raise takes the
        WHOLE guard down for the command -- ``_compute_haystacks`` never
        returns, so the inline ``--body`` goes unjudged too -- which is why
        this degrades per file, the way a non-zero ``git diff`` already does.

        An empty string is the same answer for an unreadable file, an
        oversized one and an empty one: no text this call would publish, so
        nothing for the caller to scan. The failure is logged with the path
        and the error, never swallowed.
        """
        try:
            if path.stat().st_size > _MAX_BODY_FILE_BYTES:
                _LOGGER.info("sensitive_content: gh body file %s exceeds the size bound", path)
                return ""
            raw = path.read_bytes()
        except OSError as error:
            _LOGGER.debug("sensitive_content: gh body file %s could not be read: %s", path, error)
            return ""
        return raw.decode(_BODY_FILE_ENCODING, errors=_BODY_FILE_DECODE_ERRORS)

    def _staged_content_haystacks(
        self, hook_input: dict[str, Any], commits_all: bool
    ) -> list[_Haystack]:
        """The ADDED lines of every file this commit would record.

        Run in the repository the command targets (the hook's ``cwd``, else
        the project root), so a worktree or nested repo judges its own index.
        No repository, or a git failure, means nothing to judge -- git owns
        that failure.
        """
        repo_root = self._commit_repo_root(hook_input)
        if repo_root is None:
            return []
        diff_args = ["diff", "--no-color", "--unified=0", f"--diff-filter={_DIFF_FILTER}"]
        diff_args.append("HEAD" if commits_all else "--cached")
        diff = run_git(repo_root, *diff_args)
        if diff.returncode != 0:
            _LOGGER.debug("sensitive_content: staged diff unavailable in %s", repo_root)
            return []

        haystacks: list[_Haystack] = []
        total = 0
        for relpath, added in _added_lines_by_path(diff.stdout).items():
            if not added:
                continue
            abs_path = str(repo_root / relpath)
            if self._is_excluded(abs_path) or self._is_secret_list_itself(abs_path):
                continue
            size = len(added.encode(_BODY_FILE_ENCODING, errors=_BODY_FILE_DECODE_ERRORS))
            if size > MAX_STAGED_FILE_BYTES:
                _LOGGER.info(
                    "sensitive_content: staged %s exceeds the per-file bound; not scanned",
                    relpath,
                )
                continue
            if total + size > MAX_STAGED_TOTAL_BYTES:
                _LOGGER.info(
                    "sensitive_content: staged content past %s exceeds the commit bound; "
                    "remaining files not scanned",
                    relpath,
                )
                break
            total += size
            haystacks.append(_Haystack(subject=f"staged content of {relpath}", text=added))
        return haystacks

    @staticmethod
    def _commit_repo_root(hook_input: dict[str, Any]) -> Path | None:
        cwd = hook_input.get(HookInputField.CWD)
        start = Path(cwd) if isinstance(cwd, str) and cwd else None
        if start is None:
            project_root = resolve_project_root()
            if project_root is None:
                return None
            start = Path(project_root)
        repo = GitRepo.resolve_for(start)
        return repo.root if repo is not None else None

    @staticmethod
    def _writes_git_metadata(command: str) -> bool:
        """True when ``command`` invokes git in a way that records metadata.

        Token-based, not substring: ``git`` must appear as its own token
        followed by a metadata subcommand, so neither a sentence about a branch
        nor a path like ``untracked/git-notes`` qualifies.

        The subcommand is located via ``git_subcommand_index`` rather than by
        reading the very next token, because git accepts GLOBAL OPTIONS first.
        Reading ``tokens[position + 1]`` blindly meant ``git -C /path commit``
        offered up ``-C`` as the subcommand, matched nothing, and let a blocked
        term through into a commit message — the one leak surface that cannot
        be undone without rewriting published history.
        """
        tokens = command.split()
        for position, token in enumerate(tokens[:-1]):
            if token != _GIT_EXECUTABLE and not token.endswith(f"/{_GIT_EXECUTABLE}"):
                continue
            subcommand_index = git_subcommand_index(tokens, position)
            if subcommand_index is None:
                continue
            subcommand = tokens[subcommand_index]
            if subcommand not in _GIT_METADATA_WRITE_SUBCOMMANDS:
                continue
            # `git tag -l <pattern>` / `git branch --list <pattern>` /
            # `git config --get <key>` take a ref pattern as an operand and
            # create nothing — inspecting what needs cleaning, not adding to it.
            if any(flag in tokens for flag in _GIT_READ_ONLY_FLAGS):
                continue
            return True
        return False

    def _haystacks(self, hook_input: dict[str, Any], file_path: str) -> list[_Haystack]:
        """Every piece of text this write would introduce: its PATH and its body.

        The path matters independently of the body. This repository's own
        history rewrite needed ``--path-rename`` for three files whose NAMES
        carried an identifier — ``--replace-text`` never touches a filename,
        and neither did this handler, so a file could be created with an
        identifier in its name and sail through on a clean body.
        """
        return [
            _Haystack(subject=file_path, text=text)
            for text in (self._relative_path_text(file_path), self._get_content(hook_input))
            if text
        ]

    @staticmethod
    def _relative_path_text(file_path: str) -> str:
        """``file_path`` relative to the project root, or ``""``.

        Deliberately NOT the absolute path. A project whose own root sits
        under a listed directory (a home directory on the secret list, say)
        would otherwise have EVERY write denied — a false positive so total
        it would force the handler to be switched off. Only the portion of
        the path the author actually chose is checked.
        """
        project_root = resolve_project_root()
        if project_root is None:
            return ""
        try:
            return str(Path(file_path).resolve().relative_to(Path(project_root).resolve()))
        except ValueError:
            # Outside the project root: not ours to judge.
            return ""

    def _secret_terms(self) -> tuple[str, ...]:
        """Terms from this handler's configured secret word list.

        A handler-level ``secret_word_list_path`` override always wins over
        the daemon-wide resolution in ``secret_redaction.get_active_secret_terms``
        (which has no handler-option visibility) so unit tests and per-handler
        overrides never depend on ``ProjectContext``/daemon config being
        initialised.
        """
        path = self._resolved_secret_list_path()
        if path is not None:
            return sr.get_cached_secret_terms(path)
        return sr.get_active_secret_terms()

    def _resolved_secret_list_path(self) -> Path | None:
        """Absolute path of this handler's configured secret word list, if any.

        The config value is repo-relative but every tool call carries an
        absolute ``file_path``, so both sides must be resolved before they can
        be compared (see ``_is_secret_list_itself``).
        """
        if not self._secret_word_list_path:
            return None
        path = Path(self._secret_word_list_path)
        if not path.is_absolute():
            project_root = resolve_project_root()
            if project_root is not None:
                path = Path(project_root) / path
        return path

    def _is_secret_list_itself(self, file_path: str) -> bool:
        """True when the write targets the word list that defines the terms.

        The list is the one file that MUST be allowed to contain its own
        terms. Without this the handler bricks its own configuration: the
        first write lands (nothing is configured yet, so nothing matches),
        and every later edit to add, remove or correct an entry is denied by
        the very terms the file exists to declare -- reported only as an
        opaque index, with no way to act on it. Found by dogfooding.

        Deliberately scoped to the resolved list path alone. The tracked
        ``.example`` seed is NOT exempt: it ships in the repo, so a real term
        pasted into it would be published -- exactly what this handler is for.
        """
        configured = self._resolved_secret_list_path()
        if configured is None:
            return False
        try:
            return Path(file_path).resolve() == configured.resolve()
        except (OSError, ValueError):
            # An unresolvable path is simply not the list; fall through to
            # normal scanning rather than failing open on the whole check.
            return False

    def get_rules(self) -> list[Rule]:
        """Return the 2 Rule objects backing this handler's blocking behaviour."""
        return [_RULE_PUBLIC_PATTERN, _RULE_SECRET_TERM]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        haystacks = self._take_cached_haystacks(hook_input)
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)

        for hay in haystacks:
            public_match = self._find_public_pattern_match(hay.text)
            if public_match is not None:
                return self._deny_public_pattern(transcript_path, hay.subject, public_match)

        terms = self._secret_terms()
        for hay in haystacks:
            index = sr.find_first_match_index(hay.text, terms)
            if index is not None:
                # The subject is echoed back in the deny reason, and the
                # subject is itself a thing that can MATCH — a file path, or
                # a whole git command line. Printing it raw would put the
                # term straight into the message the no-echo contract exists
                # to keep it out of: moving the leak, not closing it. The
                # TEXT is never echoed at all.
                return self._deny_secret_term(
                    transcript_path, sr.redact_text(hay.subject, terms), index, len(terms)
                )

        return GatingResult(decision=Decision.ALLOW)

    @staticmethod
    def _deny_public_pattern(
        transcript_path: str | None, subject: str, match: dict[str, str]
    ) -> GatingResult:
        """Deny a public-pattern match with a verbose-first/terse-after message.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G). The subject, pattern name
        and matched text are all SAFE to disclose (public patterns are
        declared safe-to-name), so they are appended on every fire — they
        change per invocation and are the whole point of a fixable message.
        """
        name = match.get(_PATTERN_KEY_NAME, "unnamed")
        description = match.get(_PATTERN_KEY_DESCRIPTION, "")
        matched_text = match.get("_matched", "")

        formatter = RuleFormatter()
        tracker = get_data_layer().disclosure
        if transcript_path and tracker.was_disclosed(
            transcript_path, RuleID.SENSITIVE_PUBLIC_PATTERN
        ):
            message = formatter.terse(_RULE_PUBLIC_PATTERN)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.SENSITIVE_PUBLIC_PATTERN)
            message = formatter.verbose(_RULE_PUBLIC_PATTERN)

        message += (
            f"\n\n{_SUBJECT_LABEL}: {subject}\n"
            f"Pattern: {name}" + (f" — {description}" if description else "") + "\n"
            f"Matched: {matched_text}"
        )

        return GatingResult(decision=Decision.DENY, reason=message)

    @staticmethod
    def _deny_secret_term(
        transcript_path: str | None, subject: str, index: int, total: int
    ) -> GatingResult:
        """Deny a secret-word-list match with a verbose-first/terse-after message.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G). ``subject`` is ALREADY
        redacted by the caller — this method never sees the raw term, so the
        no-echo security property holds regardless of verbosity. Only the
        entry index/total are appended, never the term itself.
        """
        formatter = RuleFormatter()
        tracker = get_data_layer().disclosure
        if transcript_path and tracker.was_disclosed(transcript_path, RuleID.SENSITIVE_SECRET_TERM):
            message = formatter.terse(_RULE_SECRET_TERM)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.SENSITIVE_SECRET_TERM)
            message = formatter.verbose(_RULE_SECRET_TERM)

        message += (
            f"\n\nMatched: entry {index} of {total} in the secret word list.\n"
            f"{_SUBJECT_LABEL}: {subject}"
        )

        return GatingResult(decision=Decision.DENY, reason=message)

    def get_claude_md(self) -> str | None:
        return (
            "## sensitive_content — blocked patterns and secret terms are never written\n\n"
            "A `Write`/`Edit` whose content matches a configured public pattern or a "
            "gitignored secret word list is blocked. Two sources, two different "
            "disclosure rules:\n\n"
            "**Public patterns** (`handlers.pre_tool_use.sensitive_content.options."
            "public_patterns`): named regexes safe to name — the deny reason shows the "
            "pattern name and the exact matched text so you can fix it.\n\n"
            "**Secret word list** (`options.secret_word_list_path`, default "
            "`.claude/block-words.secret`, gitignored): a term never appears anywhere — "
            "not in the deny reason, not in any log, not in payload capture, not in a "
            "transcript archive. The deny reason names only an index "
            "(`entry N of M in the secret word list`), which is meaningless without the "
            "gitignored file. **Do NOT try to guess or work around the block, and do NOT "
            "open the secret word list file** — it is itself read-protected by "
            "`secret_file_guard` (Plan 00272); ask the user what the entry covers. "
            "Only the ADDED text is checked on `Edit` (`new_string`) — removing "
            "sensitive content is never blocked.\n\n"
            "**Git metadata is checked too.** File contents and file PATHS are only "
            "two of the seven places a term can enter a repository — the other five are "
            "git metadata, and none of them is a file write. So a `Bash` command that "
            "records metadata is also checked: `git commit` (messages), `git tag` "
            "(names and messages), `git branch` / `checkout -b` / `switch -c` (branch "
            "names), `git config user.name|user.email` (author identity), `git merge -m`. "
            "A match denies the command.\n\n"
            "**A Bash command that writes a FILE is NOT checked at write time; the "
            "`git commit` that would RECORD it is.** A Bash "
            "command that writes a file (`cat > f <<EOF`, `>`, `>>`, `tee`, `mv`, `cp`) "
            "reaches disk unexamined — no block, no advisory, no record — so the commit "
            "is the gate: the ADDED lines of every staged file (the working tree for "
            "`git commit -a`) are scanned at commit time, and a match denies the "
            "commit naming only the file path and the pattern name or entry index, "
            "never the line. Removing a term is never blocked (only added lines "
            "count), binary blobs are skipped, and a file whose added lines exceed "
            "512 KiB — or a commit past 4 MiB in total — is stood down with a log "
            "line rather than scanned partially. `git push` is NOT a surface: it "
            "carries nothing a commit did not, and a denied commit is never pushed. "
            "Still prefer `Write`/`Edit` for file content so the block lands before "
            "the bytes do.\n\n"
            "**A `gh` body is checked like a commit message.** `gh issue comment`, "
            "`gh pr comment`, `gh issue|pr create` and `gh issue|pr edit` publish a "
            "body to GitHub, which no history rewrite can retract, so an inline "
            "`--body`/`-b` value and the content of a `--body-file`/`-F <file>` are "
            "both scanned. A body file is named by path only. `gh api` is not "
            "covered (its `-F` is a field), and a body piped on stdin (`-F -`) cannot "
            "be judged — write it to a file instead.\n\n"
            "**Reading is never blocked.** Only commands that WRITE metadata are "
            "candidates, so `grep`, `cat`, `git log --grep=`, `git show`, "
            "`git branch --list` and `git tag -l` stay allowed even when the term is "
            "right there on the command line — searching for a term and removing it "
            "are exactly the work of cleaning a repository.\n\n"
            "If a compound command is denied because an unrelated part of it carries "
            "a term (`grep <term> f && git commit -m 'clean'`), split it into two "
            "calls rather than trying to disguise the term.\n\n"
            "Missing/empty/comments-only secret file = this source is silently inert."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        # Plan 00243: only the PUBLIC-pattern probes can declare a payload.
        #
        # The secret-word-list probes below deliberately do NOT get one, and
        # that is a ruling rather than an omission. A declared payload has to
        # CONTAIN the content it sends, so giving one to a secret-list probe
        # would mean committing a live blocked term into tracked source -- the
        # one outcome the word list exists to prevent, and irreversible once
        # pushed. Their `command` therefore stays an instruction telling a
        # human tester to supply the term at test time, where it reaches no
        # file. Do not "finish the job" by inventing a payload for them.
        # `scratch_path` rather than a bare relative string: a relative
        # `file_path` never reaches this handler at all, because
        # `absolute_path` sits ahead of it and denies the write first. Both
        # probes then report on a guard neither of them is about -- and the
        # ALLOW one reports a DENY, which looks like a defect here.
        public_pattern_probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": scratch_path("sensitive-public-pattern-probe.txt"),
                "content": "deploy target: /var/www/vhosts/example",
            },
        )
        clean_probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": scratch_path("sensitive-clean-probe.txt"),
                "content": "The quick brown fox jumps over the lazy dog.\n",
            },
        )

        return [
            AcceptanceTest(
                title="sensitive_content - blocks a configured public pattern",
                command=(
                    f"{public_pattern_probe.as_instruction()} "
                    "-- with public_patterns configured to match `/var/www/vhosts`"
                ),
                tool_payload=public_pattern_probe,
                description=(
                    "Content matching a configured public pattern is denied with a "
                    "reason naming the pattern and the matched text."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    rf"BLOCKED \[{RuleID.SENSITIVE_PUBLIC_PATTERN}\]",
                    r"Pattern:",
                ],
                safety_notes="Deny path — no file is written",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="sensitive_content - blocks a secret-list term without revealing it",
                command=(
                    "Use the Write tool to write content containing a term from "
                    "`.claude/block-words.secret` to a scratch file"
                ),
                harness_cannot_produce=(
                    "A dispatchable payload would have to CONTAIN a term from the "
                    "project's gitignored secret word list, which would then live "
                    "in this handler's own tracked source — the disclosure the "
                    "feature exists to prevent. The list is read-protected, so "
                    "nothing automated can obtain a term to embed; the attempt to "
                    "write this very reason was itself refused, for naming the "
                    "list's path. A permanent boundary, and a correct one. Covered "
                    "by tests/unit/handlers/pre_tool_use/test_sensitive_content.py, "
                    "which points the handler at a temporary list holding a "
                    "throwaway term."
                ),
                description=(
                    "Content matching a secret-list term is denied with a reason "
                    "naming only an entry index — never the term itself."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"entry \d+ of \d+", r"deliberately not shown"],
                safety_notes=(
                    "Deny path — no file is written. Verify manually that the deny "
                    "reason does not contain the actual secret term.\n"
                    "NEVER write to the operational secret list to set this test up. "
                    "Point `secret_word_list_path` at a TEMP file with a throwaway "
                    "term, restart, test, then restore the path. Overwriting the real "
                    "list fails silently: the guard simply stops guarding and the QA "
                    "scanner starts reporting a cleaner tree than reality, which is "
                    "exactly how a redaction gets declared finished with identifiers "
                    "still in it."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="sensitive_content - blocks a secret-list term in a commit message",
                command=(
                    'Use the Bash tool to run `git commit -m "<term>"` where <term> '
                    "comes from `.claude/block-words.secret`"
                ),
                harness_cannot_produce=(
                    "Same boundary as the Write case above: the command a payload "
                    "would dispatch has to carry the term itself. Covered by "
                    "tests/unit/handlers/pre_tool_use/test_sensitive_content.py."
                ),
                description=(
                    "Git METADATA is a leak surface no file write can reach. A term in "
                    "a commit message is denied with an entry index only, never the term."
                ),
                expected_decision=Decision.DENY,
                # Plan 00319 Task 4.2: NOT "deliberately not shown" -- this test
                # and its Write-probe sibling above share ONE per-transcript
                # verbose-disclosure budget for RuleID.SENSITIVE_SECRET_TERM. A
                # tester runs the playbook top-to-bottom in one session, so the
                # sibling fires first and spends the budget; this test then
                # genuinely sees the TERSE form, which never carries the verbose
                # rationale sentence. The index-only pattern below still holds on
                # every fire, verbose or terse, and is the substantive contract
                # this test exists to check (see the safety_notes leak check).
                expected_message_patterns=[r"entry \d+ of \d+"],
                safety_notes=(
                    "Deny path — no commit is made. Verify the deny reason contains "
                    "neither the term nor the raw command line."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="sensitive_content - blocks a secret-list term in staged content",
                command=(
                    "Copy a scratch file containing a term from the project's secret "
                    "word list into the tree with `cp`, `git add` it, then use the Bash "
                    'tool to run `git commit -m "clean message"`'
                ),
                harness_cannot_produce=(
                    "The staged file would have to CONTAIN a term from the gitignored "
                    "list, the same boundary as every secret-list probe. Covered by "
                    "tests/unit/handlers/pre_tool_use/test_sensitive_content.py, which "
                    "stages a throwaway term in a temporary repository and asserts the "
                    "deny reason carries the path and index but never the line."
                ),
                description=(
                    "A file that arrived by `cp`/`mv` never passed a Write/Edit; the "
                    "commit is the last gate before a history rewrite is the only "
                    "remedy. The deny names the staged PATH and an entry index only."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"entry \d+ of \d+", r"staged content of"],
                safety_notes=(
                    "Deny path — no commit is made. Verify the deny reason contains "
                    "neither the term nor any line of the staged file. Unstage and "
                    "delete the probe file afterwards."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="sensitive_content - blocks a public pattern in a gh comment body",
                command=(
                    "gh issue comment 1 --body 'deploy target: /var/www/vhosts/example' "
                    "-- with public_patterns configured to match `/var/www/vhosts`"
                ),
                dispatch_as_bash=True,
                description=(
                    "A GitHub comment is more public than a commit and cannot be "
                    "retracted by a rewrite, so a `gh` body is judged like a message."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    rf"BLOCKED \[{RuleID.SENSITIVE_PUBLIC_PATTERN}\]",
                    r"Pattern:",
                ],
                safety_notes="Denied before bash runs, so nothing is posted to GitHub.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="sensitive_content - allows a read command naming a term",
                command=(
                    "Use the Bash tool to run `git log --grep=<term>` where <term> "
                    "comes from `.claude/block-words.secret`"
                ),
                harness_cannot_produce=(
                    "Same boundary as its two deny siblings — the command carries "
                    "the term — and worse as an automated probe: with no term in "
                    "it, an ALLOW would pass whether or not the handler ran, which "
                    "is the vacuous-pass shape this plan exists to remove. Covered "
                    "by tests/unit/handlers/pre_tool_use/test_sensitive_content.py."
                ),
                description=(
                    "Searching for a term must stay allowed — a guard that blocks its "
                    "own remedy gets switched off, which costs more than the leak."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Allow path — read-only git command, nothing is written",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="sensitive_content - allows clean content",
                command=clean_probe.as_instruction(),
                tool_payload=clean_probe,
                description="Content matching neither source passes silently.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Allow path",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
