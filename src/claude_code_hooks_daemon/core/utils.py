"""Utility functions for hook handlers."""

import os
import re
import shlex
from pathlib import Path
from typing import Any, Final, NamedTuple, cast

from claude_code_hooks_daemon.constants import HookInputField, ToolName
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.command_evasion import normalise_line_continuations

# --- Bash write-target detection (Plan 00260) --------------------------------
# Shell operators and verbs that put bytes into a named file. Each is here
# because a real bypass was measured against it, not for completeness: the
# raw-string regexes in `markdown_organization` missed `>|`, `&>`, `dd of=`,
# `cp`/`mv`/`install` and every `tee` target after the first.
#
# This SUPPLEMENTS those regexes rather than replacing them, and that handler
# unions the two on purpose: this module declines any target needing an
# expansion it cannot perform (`$HOME/...`), which the regexes do catch by
# substring. Deleting them would reopen a spelling the policy already blocked.

#: Redirections that WRITE. `>|` overrides noclobber and was missed entirely;
#: `&>`/`&>>` are bash's both-streams forms and were missed too.
#:
#: `>&` is deliberately EXCLUDED. It looks like a sibling but `2>&1` tokenises
#: as `2`, `>&`, `1`, so accepting it would report the file `1` -- a path the
#: command never wrote. The rule is not "operators containing `>`"; it is
#: "operators whose operand is always a filename".
_REDIRECT_OPERATORS: Final[frozenset[str]] = frozenset({">", ">>", ">|", "&>", "&>>"})

#: Writes every operand it is given, not just one.
_TEE: Final[str] = "tee"

#: Write their LAST operand -- UNLESS `-t`/`--target-directory` is present,
#: which moves the destination to the FRONT and makes that rule name a SOURCE.
#: Either way the destination may be a directory, in which case the file really
#: written is `dest/<basename of each source>`; see `_written_paths`.
_COPY_VERBS: Final[frozenset[str]] = frozenset({"cp", "mv", "install"})

#: `dd`'s destination is an `of=` operand rather than a redirect.
_DD_OUTPUT_PREFIX: Final[str] = "of="

#: Stop consuming operands here, so a later command is never absorbed into an
#: earlier one's target list.
_OPERAND_TERMINATORS: Final[frozenset[str]] = frozenset(
    {"|", "&&", "||", ";", "&", "<", ">", ">>", ">|", "&>", "&>>"}
)

_FLAG_PREFIX: Final[str] = "-"

#: `cp a b` needs a source AND a destination before the last operand is a write.
_MIN_COPY_OPERANDS: Final[int] = 2

#: `-t DEST` / `--target-directory=DEST` move the destination to the FRONT, so
#: "the last operand is the destination" becomes false and would name a SOURCE
#: -- a file the command READS. Differential-testing against a real shell caught
#: exactly that. The flag also declares the destination to be a directory, which
#: is what `_TargetCandidate.directory_only` records: the written files are
#: `DEST/<basename>` per source, and if DEST is not a real directory the shell
#: refuses the command, so nothing is reported.
_TARGET_DIRECTORY_FLAGS: Final[tuple[str, ...]] = ("-t", "--target-directory")

#: Characters meaning the token needs an expansion the daemon cannot perform.
#: Naming the wrong file is worse than naming none, so these are declined.
#:
#: `~` is deliberately ABSENT: unlike `$VAR` or a glob, a leading tilde is a
#: deterministic expansion of HOME that this process can perform exactly. It
#: also must not be declined -- Claude's own memory files live at
#: `~/.claude/projects/*/memory/`, and `markdown_organization` blocks writes to
#: them today, so treating `~` as unresolvable would silently un-enforce that
#: policy for its most natural spelling.
_UNEXPANDABLE_CHARACTERS: Final[tuple[str, ...]] = ("$", "*", "?", "`")

_HOME_PREFIX: Final[str] = "~"
_HOME_RELATIVE_PREFIX: Final[str] = "~/"
_HOME_VARIABLE: Final[str] = "HOME"

#: Device nodes are not files a handler should judge.
_DEV_PREFIX: Final[str] = "/dev/"

#: `<<EOF` / `<<-'EOF'` / `<<"EOF"`. Group 2 is the delimiter word.
_HEREDOC_RE: Final[re.Pattern[str]] = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")
_HEREDOC_DELIMITER_GROUP: Final[int] = 2

#: Cheap "could this text name a write target at all?" test, run over a heredoc
#: body before deciding to tokenise it. Every operator and verb recognised by
#: `_write_target_tokens` appears here, so a body this misses provably has no
#: target to find -- it is an optimisation, never a coverage decision.
_WRITE_INDICATOR_RE: Final[re.Pattern[str]] = re.compile(r">|of=|\b(?:tee|cp|mv|install|dd)\b")


class _TargetCandidate(NamedTuple):
    """One destination, before resolution, with what it needs to be judged.

    ``sources`` supply the basename when ``destination`` turns out to be a
    directory (`cp a.py somedir` writes `somedir/a.py`). They are empty for
    everything except copy verbs, because only those write INTO a directory --
    `echo x > somedir` is a shell error, not a write.

    ``directory_only`` marks a destination that is a directory BY DEFINITION,
    which `-t`/`--target-directory` is. Without it, a `-t` naming a directory
    that does not exist would be reported as a written FILE -- an overclaim,
    and one a real shell refuses outright.

    ``authored`` separates putting NEW content on disk (a redirect, ``tee``, a
    heredoc) from RELOCATING content that already exists (``cp``/``mv``/
    ``install``/``dd``). Both are writes, so a LOCATION guard must see both --
    copying into a guarded directory is a real bypass. A CONTENT guard must see
    only the first: denying `cp broken.py copy.py` reports a defect the command
    did not introduce, and the agent's only remedy would be to repair a file it
    never chose to write.
    """

    destination: str
    sources: tuple[str, ...] = ()
    directory_only: bool = False
    authored: bool = True


def get_bash_command(hook_input: dict[str, Any]) -> str | None:
    """Extract bash command from hook input, or None if not Bash tool.

    Args:
        hook_input: Hook input dictionary

    Returns:
        Bash command string, or None if not a Bash tool call
    """
    if hook_input.get("tool_name") != "Bash":
        return None
    tool_input: dict[str, Any] = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")
    # A Bash call can carry command=None (or an empty string). Both must pass
    # straight through: callers test falsiness, and normalising None would
    # raise inside the regex. Only real text is normalised.
    if not command or not isinstance(command, str):
        return cast("str | None", command)
    # Line continuations are normalised HERE, at the single point where commands
    # enter the daemon, so no handler pattern has to know about them. A command
    # split across lines with `\<newline>` reached guards in a form none of their
    # patterns matched — `\s+` does not match a backslash — so `git \<newline>
    # reset --hard` was allowed while the one-line form was denied.
    return normalise_line_continuations(command)


def get_file_path(hook_input: dict[str, Any]) -> str | None:
    """Extract file path from hook input, or None if not Write/Edit.

    Args:
        hook_input: Hook input dictionary

    Returns:
        File path string, or None if not a Write/Edit tool call
    """
    if hook_input.get("tool_name") not in ["Write", "Edit"]:
        return None
    tool_input: dict[str, Any] = hook_input.get("tool_input", {})
    return cast("str", tool_input.get("file_path", ""))


def get_file_content(hook_input: dict[str, Any]) -> str | None:
    """Extract file content from hook input, or None if not Write/Edit.

    Args:
        hook_input: Hook input dictionary

    Returns:
        File content string, or None if not a Write/Edit tool call
    """
    if hook_input.get("tool_name") not in ["Write", "Edit"]:
        return None
    tool_input: dict[str, Any] = hook_input.get("tool_input", {})
    return cast("str", tool_input.get("content", ""))


def get_bash_write_targets(
    hook_input: dict[str, Any],
    *,
    include_heredoc_bodies: bool = False,
    authored_only: bool = False,
) -> list[str]:
    """Absolute paths a Bash command plainly writes. Conservative by contract.

    The sibling of :func:`get_file_path` for the OTHER route a file reaches
    disk. Those two accessors return ``None`` for any tool that is not
    Write/Edit, which is where the Bash blind spot actually lives — twenty-two
    handlers inherit it without deciding to (Plan 00260). This lifts it in one
    place rather than twenty-two.

    Returns ``[]`` for a non-Bash event, so a caller can ask unconditionally.

    **Conservative means a target appears only when the command plainly says
    so.** A variable (``> "$OUT"``), a glob, or anything else needing an
    expansion the daemon cannot perform yields nothing. A WRONG path is worse
    than no path: it attributes a write to a file that was never touched, and a
    path-keyed guard then judges the wrong file.

    **One overclaim survives that rule deliberately: conditional execution.**
    ``cp a b || echo x > f`` names ``f`` even when ``cp`` succeeds and the branch
    never runs, and ``false && echo x > f`` is the mirror. Resolving it would mean
    learning the command's exit code, which requires EXECUTING it -- something a
    PreToolUse accessor must never do. Dropping conditional branches instead
    would trade this for a MISS on every legitimate ``&& >`` write, a common and
    deliberate shape. So the limit is documented rather than fixed, and callers
    that DENY must keep checking the path exists before acting on it.

    **Why ``shlex`` and not regexes.** The existing detector in
    ``markdown_organization`` scans the raw string, so
    ``echo 'the arrow > file thing'`` yields the target ``file`` — a false
    positive that denied a sub-agent gathering evidence for this plan. It is
    tolerable there only because a narrow memory-path substring test filters it
    out. Tokenising with ``punctuation_chars=True`` makes that case
    structurally impossible instead of filtered: a quoted string is ONE token,
    so a ``>`` inside it is never an operator.

    Args:
        hook_input: Hook input dictionary.
        include_heredoc_bodies: Scan heredoc BODIES too. Off by default,
            because authoring a script that would write later is not writing
            now. A deny-by-default POLICY wants it on, where over-blocking is
            cheap -- and ``markdown_organization`` already behaves that way, so
            stripping bodies unconditionally would silently regress it.

            **This flag WEAKENS the conservative guarantee, deliberately.** A
            body is data, and nothing distinguishes a script being authored
            from prose that happens to contain a redirect: the body
            ``route out > somewhere`` yields the target ``somewhere``, which
            the command never writes. Differential-testing against a real shell
            confirmed it. So with bodies on the result is a SUPERSET -- writes
            this command performs, PLUS writes a nested command would perform,
            PLUS the occasional phantom from prose. That is safe only for a
            caller that filters the result by path, which is what the one
            caller does. Leave it off for anything that acts on a target
            directly.
        authored_only: Return only destinations the command puts NEW content
            into -- a redirect, ``tee``, a heredoc -- and drop the ones it
            merely relocates (``cp``/``mv``/``install``/``dd``). Off by
            default, because the original caller is a LOCATION guard and a copy
            into a guarded directory is a genuine bypass it must see.

            **A CONTENT guard wants it on**, and should reach for
            :func:`get_written_file_paths` rather than setting it by hand.
            Denying `cp broken.py copy.py` would report a defect the command
            did not introduce: the bytes were already on disk and already
            broken, so the write is the messenger. That matters here precisely
            because the handlers this serves DENY.

    Returns:
        Absolute paths, in command order, de-duplicated. Empty when the command
        writes nothing this function can name with confidence.
    """
    command = get_bash_command(hook_input)
    if not command:
        return []

    outside_bodies, bodies = _split_heredoc_bodies(command)
    segments = [outside_bodies]
    if include_heredoc_bodies:
        # A body with no redirect and no write verb cannot name a target, so it
        # is never tokenised. Purely an optimisation, and a load-bearing one:
        # tokenising is per-character Python, a 40 KB prose body measured ~25 ms,
        # and a dispatched event pays it twice.
        segments.extend(body for body in bodies if _WRITE_INDICATOR_RE.search(body))

    cwd = hook_input.get(HookInputField.CWD)
    found: list[str] = []
    for segment in segments:
        for candidate in _write_target_tokens(_tokenise(segment)):
            if authored_only and not candidate.authored:
                continue
            for resolved in _written_paths(candidate, cwd):
                if resolved not in found:
                    found.append(resolved)
    return found


def get_written_file_paths(hook_input: dict[str, Any]) -> list[str]:
    """Every file this event put NEW content into, whichever tool did it.

    The accessor a CONTENT guard should use -- a linter, a syntax check,
    anything that judges what a file now CONTAINS. It unifies the two routes so
    a handler does not re-derive the tool-name switch (Plan 00260 Task 3.5):

    - ``Write``/``Edit`` -> the single ``file_path``, exactly as
      :func:`get_file_path` reports it.
    - ``Bash`` -> the paths the command AUTHORS, via
      :func:`get_bash_write_targets` with ``authored_only=True``.
    - anything else -> ``[]``, so a caller can ask unconditionally.

    **Relocation routes are deliberately absent.** ``cp``/``mv``/``install``/
    ``dd`` all write a file, and a LOCATION guard must see them -- copying into
    a guarded directory is a real bypass, which is why
    :func:`get_bash_write_targets` reports them by default. A content guard must
    not: denying `cp broken.py copy.py` blames a command for a defect that was
    already on disk, and leaves the agent repairing a file it never chose to
    write.

    Heredoc BODIES are excluded for the same reason. That flag yields a
    superset containing occasional phantoms from prose, and a handler that
    DENIES must never act on a path the command did not write.

    Returns:
        Absolute paths, in command order, de-duplicated. Empty when this event
        authored nothing the daemon can name with confidence.
    """
    tool_name = hook_input.get(HookInputField.TOOL_NAME)
    if tool_name in (ToolName.WRITE, ToolName.EDIT):
        file_path = get_file_path(hook_input)
        return [file_path] if file_path else []
    return get_bash_write_targets(hook_input, authored_only=True)


def _written_paths(candidate: _TargetCandidate, cwd: Any) -> list[str]:
    """Every file this one candidate actually writes. Usually zero or one.

    A destination that is an existing DIRECTORY is not itself written -- but
    for a copy verb the written files are still nameable exactly, as
    ``dest/<basename of each source>``. That was measured against a real shell:
    `cp a.py somedir` writes `somedir/a.py`, and returning nothing there left a
    live gap, since copying a file INTO a guarded directory is the obvious way
    to reach one without ever naming the file.

    With no sources there is nothing to expand and the directory is dropped:
    ``echo x > somedir`` is a shell error that writes nothing, so inventing a
    path would be fabrication. A ``directory_only`` destination that is not a
    real directory is dropped for the same reason -- the shell refuses it.
    """
    destination = _resolve_write_target(candidate.destination, cwd)
    if destination is None:
        return []
    if Path(destination).is_dir():
        return [str(Path(destination) / Path(source).name) for source in candidate.sources]
    return [] if candidate.directory_only else [destination]


def _tokenise(text: str) -> list[str]:
    """Shell tokens, or an empty list when the text cannot be parsed.

    Returning empty rather than raising is what makes the per-segment split
    matter: an unbalanced quote in one heredoc body costs that body only. When
    the whole command was parsed as a single string, a stray `"` in ordinary
    prose discarded the genuine target on the introducing line too — silently
    un-enforcing any policy keyed on that path.

    **``posix=True`` is load-bearing, not a default (Plan 00263).** Non-POSIX
    mode does not process backslash escapes, so a ``\\"`` inside a double-quoted
    argument TERMINATES the quote and everything after it is read as live shell.
    That falsifies the one guarantee this module rests on — "a quoted string is
    a single token, so a ``>`` inside it is never an operator" — and it produced
    PHANTOM targets: paths reported as written by a command that only mentioned
    them. It was found by a live false denial, not by inspection.

    The reach went past redirects. Once the quote broke, ``tee`` and the copy
    verbs consumed the trailing operands, so a run of prose words became a list
    of written files (``... \\" loudly"`` yielded the target ``loudly``). A
    phantom that is a bare plausible word is worse than a malformed one, because
    a malformed path fails the ``exists()`` check and a plausible one need not.

    POSIX mode also fixes the mirror-image defect: ``> sp\\ ace.txt`` is one path
    to bash, and unprocessed escapes split it into ``sp\\`` and ``ace.txt`` —
    naming a file nothing writes while missing the file that was written.

    Tokens arrive UNQUOTED as a result, which is why callers must not re-strip
    quote characters; see :func:`_resolve_write_target`.

    The one behaviour traded away is that POSIX mode also rejects a trailing
    lone backslash ("No escaped character") where non-POSIX tolerated it. That
    is the fail-safe direction — a segment yields no targets rather than a wrong
    one — and such a command is unterminated to bash as well.
    """
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return []


def _split_heredoc_bodies(command: str) -> tuple[str, list[str]]:
    """Separate the shell being RUN from the heredoc bodies being WRITTEN.

    Returns ``(command_without_bodies, bodies)``. The introducing line stays
    with the command because the real target lives on it
    (``cat > out.md <<'EOF'``); the body is data.

    They are returned apart rather than as one string so each can be tokenised
    on its own — see :func:`_tokenise` for why that matters, and
    :func:`get_bash_write_targets` for the cost it avoids.
    """
    lines = command.split("\n")
    kept: list[str] = []
    bodies: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        delimiters = [match.group(_HEREDOC_DELIMITER_GROUP) for match in _HEREDOC_RE.finditer(line)]
        index += 1
        for delimiter in delimiters:
            start = index
            while index < len(lines) and lines[index].strip() != delimiter:
                index += 1
            bodies.append("\n".join(lines[start:index]))
            index += 1  # step past the closing delimiter itself
    return "\n".join(kept), bodies


def _write_target_tokens(tokens: list[str]) -> list[_TargetCandidate]:
    """Candidate targets, in command order, before quoting or path resolution.

    Each candidate carries the SOURCE operands that would supply a basename if
    the destination turns out to be a directory. Only copy verbs have any --
    ``cp a.py somedir`` writes ``somedir/a.py``, a path nothing else can name.
    """
    targets: list[_TargetCandidate] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]

        if token in _REDIRECT_OPERATORS and index + 1 < len(tokens):
            targets.append(_TargetCandidate(tokens[index + 1]))
            index += 2
            continue

        if token == _TEE:
            index = _collect_trailing_operands(tokens, index + 1, targets, keep_all=True)
            continue

        if token in _COPY_VERBS:
            index = _collect_trailing_operands(
                tokens, index + 1, targets, keep_all=False, authored=False
            )
            continue

        if token.startswith(_DD_OUTPUT_PREFIX):
            targets.append(_TargetCandidate(token[len(_DD_OUTPUT_PREFIX) :], authored=False))
            index += 1
            continue

        index += 1
    return targets


def _collect_trailing_operands(
    tokens: list[str],
    start: int,
    targets: list[_TargetCandidate],
    *,
    keep_all: bool,
    authored: bool = True,
) -> int:
    """Consume one command's operands, appending the written ones.

    ``tee`` writes EVERY operand; ``cp``/``mv``/``install`` write ONE
    destination, which is the last operand -- or the value of
    ``-t``/``--target-directory``, which moves it to the front. Both stop at a
    shell separator so a later command is never absorbed.

    ``authored`` is stamped onto every candidate this call produces: ``tee``
    writes content it is handed, a copy verb relocates content that exists.
    """
    index = start
    operands: list[str] = []
    target_directory: str | None = None
    expects_directory_value = False
    while index < len(tokens) and tokens[index] not in _OPERAND_TERMINATORS:
        token = tokens[index]
        if expects_directory_value:
            target_directory = token
            expects_directory_value = False
        elif token.startswith(_FLAG_PREFIX):
            flag, _, inline_value = token.partition("=")
            if flag in _TARGET_DIRECTORY_FLAGS:
                if inline_value:
                    target_directory = inline_value
                else:
                    expects_directory_value = True
        else:
            operands.append(token)
        index += 1

    if keep_all:
        targets.extend(_TargetCandidate(operand, authored=authored) for operand in operands)
    elif target_directory is not None:
        # Destination first: every remaining operand is a SOURCE.
        targets.append(
            _TargetCandidate(
                target_directory, tuple(operands), directory_only=True, authored=authored
            )
        )
    elif len(operands) >= _MIN_COPY_OPERANDS:
        targets.append(_TargetCandidate(operands[-1], tuple(operands[:-1]), authored=authored))
    return index


def _expand_home(target: str) -> str | None:
    """A `~`-leading token as an absolute path, or None when it cannot be.

    Only the HOME-relative form (`~` alone, or `~/...`) is expanded. `~otheruser`
    is declined deliberately: resolving another account's home would name a file
    outside the session's reach, and the policy this serves -- Claude's own
    memory files under `~/.claude/projects/*/memory/` -- is always the CURRENT
    user's.

    ``HOME`` is read directly rather than through ``Path.expanduser()`` because
    that raises ``RuntimeError`` when no home can be determined, and an accessor
    returning a list must not throw out of one malformed token. Reading the
    variable makes "no home" an ordinary declined verdict.
    """
    if target != _HOME_PREFIX and not target.startswith(_HOME_RELATIVE_PREFIX):
        return None
    home = os.environ.get(_HOME_VARIABLE)
    if not home:
        return None
    if target == _HOME_PREFIX:
        return str(Path(home))
    return str(Path(home) / target[len(_HOME_RELATIVE_PREFIX) :])


def _resolve_write_target(target: str, cwd: Any) -> str | None:
    """One raw token as an absolute path, or None when it cannot be named.

    Declines rather than guesses. A directory destination is declined too: the
    written file is ``dest/<basename>``, so reporting ``dest`` would name a
    path no path-keyed guard matches -- failing safe (a missed write) instead
    of dangerously (the wrong file judged).

    **No quote-stripping happens here.** :func:`_tokenise` runs in POSIX mode,
    so quotes are already removed by the lexer, which knows which ones were
    syntax. Stripping again would corrupt the rare path whose name genuinely
    begins or ends with a quote character -- turning a correct target into a
    wrong one, the exact failure this function exists to avoid.
    """
    if not target or target.endswith("/"):
        return None
    if any(character in target for character in _UNEXPANDABLE_CHARACTERS):
        return None
    if target.startswith(_DEV_PREFIX):
        return None

    if target.startswith(_HOME_PREFIX):
        return _expand_home(target)

    path = Path(target)
    if path.is_absolute():
        return str(path)
    if not isinstance(cwd, str) or not cwd:
        return None
    return str(Path(cwd) / path)


def get_workspace_root() -> Path:
    """Find project root by searching upward for directory with BOTH .git AND CLAUDE.

    This allows handlers to work in any directory structure, not just hardcoded paths.
    Prevents bugs from hardcoded absolute paths that only work in specific environments.

    Requires BOTH markers to ensure we find the actual project root, not a subdirectory
    that happens to have one marker.

    Returns:
        Path to project root directory
    """
    # Start from this file's location
    current = Path(__file__).resolve()

    # Search upward through parent directories
    for parent in [current, *current.parents]:
        # Require BOTH .git AND CLAUDE to exist
        if (parent / ".git").exists() and (parent / "CLAUDE").exists():
            return parent

    # Fallback: use ProjectContext (single source of truth)
    return ProjectContext.project_root()
