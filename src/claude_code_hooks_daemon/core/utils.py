"""Utility functions for hook handlers."""

import logging
import os
import re
from pathlib import Path
from typing import Any, Final, NamedTuple, cast

from claude_code_hooks_daemon.constants import HookInputField, ToolName
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils import linear_shlex
from claude_code_hooks_daemon.utils.ansi_c import ansi_c_string
from claude_code_hooks_daemon.utils.command_evasion import normalise_line_continuations
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.heredoc_operators import (
    COMMENT_PRECEDERS,
    HeredocScan,
    find_heredoc_operators,
    remove_line_continuations,
    scan_heredocs,
)
from claude_code_hooks_daemon.utils.shell_segmentation import (
    DATA_SINKS,
    body_may_run,
    heredoc_consumers,
    known_variables,
    substitute_known_variables,
)

logger = logging.getLogger(__name__)

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
#: written is `dest/<basename of each source>`; see `resolve_bash_write_destination`.
_COPY_VERBS: Final[frozenset[str]] = frozenset({"cp", "mv", "install"})

#: `mv` is a copy verb that ALSO removes its sources.
_MOVE: Final[str] = "mv"

#: `ln` writes its LAST operand (or `-t DEST`) like a copy verb, but only when a
#: caller asks for mutations: it puts a link there, not content.
_LINK: Final[str] = "ln"

_SED: Final[str] = "sed"
_TRUNCATE: Final[str] = "truncate"
_TOUCH: Final[str] = "touch"

#: Verbs that change or remove a file they do not author, reported only to a
#: caller that asks for them (``include_mutations``). Every operand of `rm` and
#: `truncate` is a file; `sed` names its files only with `-i`/`--in-place`.
_MUTATION_VERBS: Final[frozenset[str]] = frozenset({"rm", "unlink", "touch", _TRUNCATE, _SED})

#: `dd`'s destination is an `of=` operand rather than a redirect.
_DD_OUTPUT_PREFIX: Final[str] = "of="

#: Stop consuming operands here, so a later command is never absorbed into an
#: earlier one's target list.
_OPERAND_TERMINATORS: Final[frozenset[str]] = frozenset({"|", "&&", "||", ";", "&"})

#: Redirects that read: their word is no operand of the command.
_INPUT_REDIRECT_OPERATORS: Final[frozenset[str]] = frozenset({"<", "<<", "<<-", "<<<"})

_FLAG_PREFIX: Final[str] = "-"

#: `cp a b` needs a source AND a destination before the last operand is a write.
_MIN_COPY_OPERANDS: Final[int] = 2

#: `-t DEST` / `--target-directory=DEST` move the destination to the FRONT, so
#: "the last operand is the destination" becomes false and would name a SOURCE
#: -- a file the command READS. Differential-testing against a real shell caught
#: exactly that. The flag also declares the destination to be a directory, which
#: is what `BashWriteDestination.directory_only` records: the written files are
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

#: Device nodes are not files a handler should judge. Only real nodes: `/dev/shm`
#: and `/dev/mqueue` are tmpfs directories, so a write there is an ordinary
#: write outside the project.
_DEVICE_NODES: Final[frozenset[str]] = frozenset(
    {
        "/dev/null",
        "/dev/zero",
        "/dev/full",
        "/dev/random",
        "/dev/urandom",
        "/dev/stdin",
        "/dev/stdout",
        "/dev/stderr",
        "/dev/tty",
        "/dev/console",
    }
)
_DEVICE_NODE_RE: Final[re.Pattern[str]] = re.compile(r"/dev/(?:tty[A-Za-z0-9]+|(?:pts|fd)/[0-9]+)")

#: Cheap "could this text name a write target at all?" test, run over a heredoc
#: body before deciding to tokenise it. Every operator and verb recognised by
#: `_write_target_tokens` appears here, so a body this misses provably has no
#: target to find -- it is an optimisation, never a coverage decision.
_WRITE_INDICATOR_RE: Final[re.Pattern[str]] = re.compile(r">|of=|\b(?:tee|cp|mv|install|dd)\b")

#: Shell bodies nested in shell bodies followed before the rest is unreadable.
_MAX_SHELL_BODY_DEPTH: Final[int] = 4


class BashWriteDestination(NamedTuple):
    """One destination, before resolution, with what it needs to be judged.

    PUBLIC so a DENY guard can see a destination the resolver declines
    (``> "$OUT"``, a glob) and fail closed on it; see
    :func:`bash_write_destinations`. ``destination`` is the raw token as the
    shell lexer produced it.

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
    #: The command changes or removes this path (``rm``, ``sed -i``, the source
    #: of ``mv``). A directory is then a real target, not a place files land.
    mutation: bool = False


class BashWriteScan(NamedTuple):
    """Every destination a command names, and the text that could not be read.

    ``unreadable`` is the command text from the first complete command the
    tokeniser could not read to the end of the command, or ``None`` when every
    command was read. Bash runs each complete command before an unreadable
    one, so ``destinations`` still holds theirs. What the unreadable text
    writes is UNKNOWN, not nothing: a guard that denies on a write location
    must fail closed on it (Plan 00466 N120).
    """

    destinations: list[BashWriteDestination]
    unreadable: str | None


class BashWriteTargets(NamedTuple):
    """The resolved counterpart of :class:`BashWriteScan`.

    ``unresolved`` holds each destination that still needs an expansion
    after the variables :func:`known_variables` pins are substituted: where
    it writes is unknown, so a guard that denies on a write location must
    fail closed on it (Plan 00466 N101 round 12, N215).
    """

    paths: list[str]
    unreadable: str | None
    unresolved: tuple[str, ...] = ()


def get_bash_command(hook_input: dict[str, Any]) -> str | None:
    """Extract bash command from hook input, or None if not Bash tool.

    Args:
        hook_input: Hook input dictionary

    Returns:
        Bash command string, or None if not a Bash tool call
    """
    if hook_input.get(HookInputField.TOOL_NAME) != "Bash":
        return None
    tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
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
    if hook_input.get(HookInputField.TOOL_NAME) not in ["Write", "Edit"]:
        return None
    tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
    return cast("str", tool_input.get("file_path", ""))


#: The tool-input fields a Grep call may name its target in (``file_path`` is
#: accepted in place of ``path`` from Claude Code 2.1.292).
GREP_TARGET_FIELDS: Final[tuple[str, ...]] = ("path", "file_path")


def grep_targets(tool_input: Any) -> list[str]:
    """Every distinct, non-empty target a Grep call names, ``path`` first.

    The single reader of a Grep call's target: a handler that reads only
    ``path`` misses a call that names its file in ``file_path``. When both are
    present, both are returned so each can be judged.
    """
    if not isinstance(tool_input, dict):
        return []
    found: list[str] = []
    for field in GREP_TARGET_FIELDS:
        value = tool_input.get(field)
        if isinstance(value, str) and value and value not in found:
            found.append(value)
    return found


def grep_input_for(hook_input: dict[str, Any], target: str) -> dict[str, Any]:
    """A copy of a Grep ``hook_input`` that names only ``target``, in ``path``."""
    tool_input = hook_input.get(HookInputField.TOOL_INPUT)
    kept = {
        key: value
        for key, value in (tool_input if isinstance(tool_input, dict) else {}).items()
        if key not in GREP_TARGET_FIELDS
    }
    return {**hook_input, HookInputField.TOOL_INPUT: {**kept, "path": target}}


def get_file_content(hook_input: dict[str, Any]) -> str | None:
    """Extract file content from hook input, or None if not Write/Edit.

    Args:
        hook_input: Hook input dictionary

    Returns:
        File content string, or None if not a Write/Edit tool call
    """
    if hook_input.get(HookInputField.TOOL_NAME) not in ["Write", "Edit"]:
        return None
    tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
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

    That existence check bounds the residual but does NOT remove it, and the
    difference was measured against the live daemon rather than reasoned about.
    When the conditionally-named file is ABSENT the denying linters cannot fire
    at all (``lint_on_edit`` and ``validate_eslint_on_write`` both gate on
    ``Path(...).exists()``), so the common shape is harmless. When it is PRESENT
    and already failing lint, the command IS denied for a file it never touched.
    Reaching that needs all three of: a conditional write, to a pre-existing
    file, that already fails its linter.

    Two candidate fixes were considered and both are worse:

    - **An mtime window** (lint only a target modified since the command began)
      fails DANGEROUS. A long command that wrote early looks stale by the time
      PostToolUse runs, so a real write is missed — and a miss is the direction
      a guard must never fail in.
    - **The command's exit code**, which PostToolUse does receive, cannot
      disambiguate either operator. For ``A || B`` an overall 0 means A
      succeeded *or* B ran and succeeded; for ``A && B`` a non-zero means A
      failed *or* B ran and failed. The compound status simply does not carry
      which branch executed.

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

    **A command the tokeniser cannot read to the end yields only the targets of
    the commands before that point.** That is right for a content or advisory
    caller, and WRONG for one that denies on a write location: the unread text
    may write anywhere. Such a caller must use :func:`scan_bash_write_targets`
    and fail closed on its ``unreadable`` text (Plan 00466 N120).

    Returns:
        Absolute paths, in command order, de-duplicated. Empty when the command
        writes nothing this function can name with confidence.
    """
    return scan_bash_write_targets(
        hook_input, include_heredoc_bodies=include_heredoc_bodies, authored_only=authored_only
    ).paths


def scan_bash_write_targets(
    hook_input: dict[str, Any],
    *,
    include_heredoc_bodies: bool = False,
    authored_only: bool = False,
    include_mutations: bool = False,
) -> BashWriteTargets:
    """:func:`get_bash_write_targets`, plus the command text it could not read.

    The accessor for a guard that DENIES on a write location. The options mean
    what they mean on :func:`get_bash_write_targets`.

    ``include_mutations`` also reports the files a command changes or removes
    without authoring them: ``sed -i``, ``ln``, ``rm``, ``truncate`` and the
    source of ``mv``. A guard that keeps a path read-only wants them; a caller
    judging what a command writes does not, which is why they are off by
    default (Plan 00499).
    """
    command = get_bash_command(hook_input)
    if not command:
        return BashWriteTargets([], None)

    cwd = hook_input.get(HookInputField.CWD)
    scan = scan_bash_write_destinations(
        command,
        include_heredoc_bodies=include_heredoc_bodies,
        include_mutations=include_mutations,
    )
    known = known_variables(command)
    found: list[str] = []
    unresolved: list[str] = []
    for candidate in scan.destinations:
        if authored_only and not candidate.authored:
            continue
        destination = substitute_known_variables(
            substitute_cwd_expansions(candidate.destination, command, cwd), known
        )
        if destination is None or needs_expansion(destination):
            unresolved.append(candidate.destination)
            continue
        substituted = candidate._replace(destination=destination)
        for resolved in resolve_bash_write_destination(substituted, cwd):
            if resolved not in found:
                found.append(resolved)
    return BashWriteTargets(found, scan.unreadable, tuple(unresolved))


#: The working-directory expansions read as the hook cwd, spelled exactly:
#: ``$PWD`` and ``${PWD}`` (not ``$PWDX``) and ``$(pwd)``.
_PWD_EXPANSION_RE: Final[re.Pattern[str]] = re.compile(
    r"\$\{PWD\}|\$PWD(?![A-Za-z0-9_])|\$\(\s*pwd\s*\)"
)

#: The repository root, spelled exactly as ``git rev-parse --show-toplevel``.
_TOPLEVEL_EXPANSION_RE: Final[re.Pattern[str]] = re.compile(
    r"\$\(\s*git\s+rev-parse\s+--show-toplevel\s*\)"
)

#: A command that may change its own directory or assign ``PWD``, after which
#: the hook cwd is no longer what ``$PWD`` means. A mention inside a string
#: matches too, which only leaves the expansion unresolved (and so denied).
_CHANGES_DIRECTORY_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:cd|pushd|popd)\b|\bPWD=")


def repository_root(cwd: str) -> str | None:
    """The nearest directory at or above ``cwd`` holding a ``.git`` entry (a
    directory, or the file a worktree has), which is where
    ``git rev-parse --show-toplevel`` answers; ``None`` when there is none."""
    for directory in (Path(cwd), *Path(cwd).parents):
        if (directory / ".git").exists():
            return str(directory)
    return None


def substitute_cwd_expansions(token: str, command: str, cwd: Any) -> str:
    """``token`` with ``$PWD``, ``${PWD}``, ``$(pwd)`` read as the hook cwd and
    ``$(git rev-parse --show-toplevel)`` as that cwd's repository root.

    Only these literal spellings, one level deep. Returned unchanged when
    ``cwd`` is not an absolute path, when ``command`` changes directory or
    assigns ``PWD`` (the cwd is then not what the shell sees), or, for the
    repository root, when no repository encloses ``cwd``: what remains is
    still an expansion, and the caller declines it as it always did.
    """
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        return token
    if _CHANGES_DIRECTORY_RE.search(command):
        return token
    token = _PWD_EXPANSION_RE.sub(lambda _match: cwd, token)
    if _TOPLEVEL_EXPANSION_RE.search(token):
        root = repository_root(cwd)
        if root is not None:
            token = _TOPLEVEL_EXPANSION_RE.sub(lambda _match: root, token)
    return token


def is_device_path(target: str) -> bool:
    """Is ``target`` a device node (``/dev/null``), which no handler judges
    as a file written?

    The path is normalised first, so ``/dev/../tmp/x`` is judged as ``/tmp/x``.
    """
    normalised = os.path.normpath(target)
    return normalised in _DEVICE_NODES or _DEVICE_NODE_RE.fullmatch(normalised) is not None


def needs_expansion(token: str) -> bool:
    """Does ``token`` still need an expansion the daemon cannot perform?"""
    return any(character in token for character in _UNEXPANDABLE_CHARACTERS)


def bash_write_destinations(
    command: str, *, include_heredoc_bodies: bool = False
) -> list[BashWriteDestination]:
    """The destinations of :func:`scan_bash_write_destinations`, without the rest.

    Every destination ``command`` names as written, UNRESOLVED. A caller that
    DENIES must use the scan instead, which also reports text it could not
    read.
    """
    return scan_bash_write_destinations(
        command, include_heredoc_bodies=include_heredoc_bodies
    ).destinations


def scan_bash_write_destinations(
    command: str, *, include_heredoc_bodies: bool = False, include_mutations: bool = False
) -> BashWriteScan:
    """Every destination ``command`` names as written, UNRESOLVED.

    The raw half of :func:`get_bash_write_targets`, from the same parser. That
    accessor drops a destination it cannot resolve, which is right for a guard
    that acts on a path; a DENY guard also needs the ones it could NOT place
    (``> "$OUT"``, ``> dir/*.md``, ``> name-$(date).md``) so it can fail closed
    when such a token visibly names what it protects. A token needing
    expansion is kept exactly as the lexer produced it, cut at the first shell
    punctuation character.

    ``include_heredoc_bodies`` has the meaning, and the caveats, documented on
    :func:`get_bash_write_targets`.

    The text outside heredoc bodies is read one complete command at a time --
    split at the newlines that end a command, never at one inside a quoted
    argument or a substitution. The first command the tokeniser cannot read
    stops the reading, and it and everything after it are ``unreadable``.
    A body is data, so a body shlex cannot read costs that body only and is
    never reported as unreadable. A body whose closing line never comes is
    not known to be data -- a delimiter read differently from bash looks
    exactly like that, and bash then ran every line after its own closer --
    so its text is ``unreadable`` too (Plan 00466 N120). So is every command
    from the one where the scan STOPPED: past that point the scanner cannot
    tell a body from a command (Plan 00466 N101 round 10).

    A body fed to a SHELL (:data:`SHELL_BODY_RUNNERS`, named directly or by a
    variable the command shows names one) is commands, not data: its writes
    are read like the command's own, and text in it the tokeniser cannot read
    is ``unreadable`` (Plan 00466 N101 round 10, S3). So is a body fed to a
    receiver nothing names (``$PY -`` with no literal ``PY=`` earlier), which
    is unknown rather than data (round 12, N212). With
    ``include_heredoc_bodies``, so is an unreadable body fed to anything but
    a data sink.
    """
    return _scan_destinations(command, include_heredoc_bodies, depth=0, mutations=include_mutations)


def _scan_destinations(
    command: str, include_heredoc_bodies: bool, depth: int, mutations: bool = False
) -> BashWriteScan:
    """:func:`scan_bash_write_destinations`, ``depth`` shell bodies deep."""
    if depth > _MAX_SHELL_BODY_DEPTH:
        return BashWriteScan([], command)
    scan = scan_heredocs(command)
    destinations: list[BashWriteDestination] = []
    unreadable: str | None = None
    readable_end = len(command)
    if scan.stopped_at is not None:
        readable_end = max((b for b in scan.breaks if b < scan.stopped_at), default=-1) + 1
    commands = _complete_commands(command, scan, readable_end)
    unscanned = [command[readable_end:]] if readable_end < len(command) else []
    for position, text in enumerate(commands):
        tokens = _tokenise(text)
        if tokens is None:
            unreadable = "\n".join([*commands[position:], *unscanned])
            break
        destinations.extend(_write_target_tokens(tokens, mutations))
    if unreadable is None and unscanned:
        unreadable = unscanned[0]
    if unreadable is None:
        unclosed = [h.body(command) for h in scan.heredocs if not h.terminated]
        unreadable = next((body for body in unclosed if body.strip()), None)
    consumers = heredoc_consumers(command, scan.heredocs)
    for heredoc, words in zip(scan.heredocs, consumers, strict=True):
        body = heredoc.body(command)
        if body_may_run(words):
            # The shell reads each body line with its newline, and joins its
            # continuations as it reads.
            script = remove_line_continuations(body + "\n")
            nested = _scan_destinations(script, include_heredoc_bodies, depth + 1, mutations)
            destinations.extend(nested.destinations)
            unreadable = unreadable if unreadable is not None else nested.unreadable
        # A body with no redirect and no write verb cannot name a target, so
        # it is never tokenised. Purely an optimisation, and a load-bearing
        # one: tokenising is per-character Python, a 40 KB prose body
        # measured ~25 ms, and a dispatched event pays it twice.
        elif include_heredoc_bodies and _WRITE_INDICATOR_RE.search(body):
            tokens = _tokenise(body)
            if tokens is None and not all(word in DATA_SINKS for word in words):
                unreadable = unreadable if unreadable is not None else body
            destinations.extend(_write_target_tokens(tokens or [], mutations))
    return BashWriteScan(destinations, unreadable)


def _complete_commands(command: str, scan: HeredocScan, readable_end: int) -> list[str]:
    """The text before ``readable_end`` outside heredoc bodies, one complete
    command per entry."""
    removed = _body_spans(command, scan)
    commands: list[str] = []
    start = 0
    for end in [*(b for b in scan.breaks if b < readable_end), readable_end]:
        text = _without_spans(command, start, end, removed)
        if text.strip():
            commands.append(text)
        start = end + 1
    return commands


def _body_spans(command: str, scan: HeredocScan) -> list[tuple[int, int]]:
    """Each body and its closing line, with the newline that introduces it."""
    return [
        (heredoc.body_start - 1, heredoc.closer_end)
        for heredoc in scan.heredocs
        if heredoc.body_start < len(command)
    ]


def _without_spans(command: str, start: int, end: int, removed: list[tuple[int, int]]) -> str:
    """``command[start:end]`` with every removed span that falls inside it cut out."""
    parts: list[str] = []
    cursor = start
    for span_start, span_end in removed:
        if span_end <= cursor or span_start >= end:
            continue
        parts.append(command[cursor : max(cursor, span_start)])
        cursor = max(cursor, span_end)
    parts.append(command[cursor:end] if cursor < end else "")
    return "".join(parts)


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

    Command text the tokeniser cannot read names no path here, deliberately:
    a content guard judges a file it can name, and one it cannot name has
    nothing to lint. Its silence claims nothing. A LOCATION guard is the
    opposite case and must use :func:`scan_bash_write_targets` (Plan 00466
    N120).

    Returns:
        Absolute paths, in command order, de-duplicated. Empty when this event
        authored nothing the daemon can name with confidence.
    """
    tool_name = hook_input.get(HookInputField.TOOL_NAME)
    if tool_name in (ToolName.WRITE, ToolName.EDIT):
        file_path = get_file_path(hook_input)
        return [file_path] if file_path else []
    return get_bash_write_targets(hook_input, authored_only=True)


def resolve_bash_write_destination(candidate: BashWriteDestination, cwd: Any) -> list[str]:
    """Every file this one candidate actually writes. Usually zero or one.

    The resolved half of :func:`bash_write_destinations`; empty when the token
    needs an expansion the daemon cannot perform.

    A destination that is an existing DIRECTORY is not itself written -- but
    for a copy verb the written files are still nameable exactly, as
    ``dest/<basename of each source>``. That was measured against a real shell:
    `cp a.py somedir` writes `somedir/a.py`, and returning nothing there left a
    live gap, since copying a file INTO a guarded directory is the obvious way
    to reach one without ever naming the file.

    With no sources there is nothing to expand and the directory is dropped:
    ``echo x > somedir`` is a shell error that writes nothing, so inventing a
    path would be fabrication. A destination declared to be a directory that
    turns out not to be a real one is dropped for the same reason -- the shell
    refuses it. Two spellings make that declaration: the ``-t``/
    ``--target-directory`` flag (``candidate.directory_only``), and a trailing
    slash on the RAW destination token (``cp a.py dest/``) -- checked here,
    against ``candidate.destination`` rather than the resolved path, because
    ``_resolve_write_target`` strips the slash to produce the path to test.
    """
    destination = _resolve_write_target(candidate.destination, cwd)
    if destination is None:
        return []
    if candidate.mutation:
        return [destination]
    directory_only = candidate.directory_only or candidate.destination.endswith("/")
    try:
        destination_is_dir = Path(destination).is_dir()
    except OSError as exc:
        # Logged, not swallowed. This is the only thing that separates the
        # branch from the silent-fallback antipattern the repo's own
        # error-hiding auditor exists to catch: without a record, "the guard
        # decided this is not a directory" and "the guard could not look" are
        # indistinguishable to whoever is asking why a policy did not fire.
        log_and_continue(
            logger,
            exc,
            reason="an unstattable write destination is treated as a non-directory (the answer pathlib gives for expected stat failures); the copy-verb expansion stays suppressed, so a path-keyed guard loses only the directory-target inference and nothing is fabricated",
        )
        # An unstattable destination is not KNOWN to be a directory, so it is
        # treated as not one -- the same answer pathlib already gives for every
        # stat failure it considers expected (ENOENT, ENOTDIR, ELOOP, EBADF).
        # EACCES is absent from that set, so `is_dir()` RAISES on a path whose
        # parent chain lacks `+x` for the daemon's user, and these paths come
        # from a command a user typed: the daemon has no say in whether it can
        # stat them.
        #
        # Reporting nothing here would be the worse failure. It would turn an
        # unreadable parent directory into a blanket exemption from every
        # path-keyed guard, which is the direction a guard must never fail in.
        # The copy-verb expansion below stays suppressed, so nothing is
        # fabricated inside a directory this cannot see.
        destination_is_dir = False
    if destination_is_dir:
        return [str(Path(destination) / Path(source).name) for source in candidate.sources]
    return [] if directory_only else [destination]


def _tokenise(text: str) -> list[str] | None:
    """Shell tokens, or ``None`` when the text cannot be parsed.

    ``None`` is not "no tokens": the caller decides what an unreadable span
    costs. For a heredoc body it costs that body only. For command text it
    marks the scan ``unreadable`` (Plan 00466 N120), because bash runs every
    complete command before the one it cannot parse -- and an unreadable
    command may write anywhere.

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

    The text is first put through :func:`bash_text_for_shlex`, because shlex
    and bash disagree in two places where shlex does NOT raise, and silently
    reads the rest of the line wrong (Plan 00466 N120): shlex starts a comment
    at a ``#`` inside a word, and does not know ANSI-C ``$'...'``. On main,
    ``echo a#b > /opt/o.md`` and ``echo $'it\\'s' > /opt/x \\'`` both named no
    target while bash wrote one. That function also returns ``None`` for the
    only two texts POSIX shlex raises on -- a quote that never closes and a
    trailing lone backslash -- so shlex is never handed one.
    """
    normalised = bash_text_for_shlex(text)
    if normalised is None:
        return None
    lexer = linear_shlex.LinearShlex(normalised, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def bash_text_for_shlex(text: str) -> str | None:
    """``text`` rewritten so shlex splits it where bash does; None if a quote
    never closes or the text ends in a lone backslash, the two things POSIX
    shlex raises on.

    Bash's comments are removed (a ``#`` starting a word, outside quotes, up to
    the newline), so shlex can run with no comment character of its own: shlex
    would also start one INSIDE a word, where bash does not. Each ANSI-C
    ``$'...'`` string is decoded and re-quoted as a plain single-quoted word;
    shlex reads ``$'it\\'s'`` as a quote closed at the escaped one. ``$$`` is
    the shell's pid, so the quote after it is a plain one.
    Everything else is kept byte for byte.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\" and index + 1 == length:
            return None
        if char == "\\" or text.startswith("$$", index):
            out.append(text[index : index + 2])
            index += 2
        elif char == "'":
            end = text.find("'", index + 1)
            if end < 0:
                return None
            out.append(text[index : end + 1])
            index = end + 1
        elif char == '"':
            end = _double_quote_end(text, index + 1)
            if end < 0:
                return None
            out.append(text[index : end + 1])
            index = end + 1
        elif text.startswith("$'", index):
            decoded = ansi_c_string(text, index + 2)
            if decoded is None:
                return None
            value, index = decoded
            out.append("'" + value.replace("'", "'\"'\"'") + "'")
        elif char == "#" and (index == 0 or text[index - 1] in COMMENT_PRECEDERS):
            line_end = text.find("\n", index)
            index = length if line_end < 0 else line_end
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _double_quote_end(text: str, index: int) -> int:
    """Index of the ``"`` closing a double-quoted span begun before ``index``, or -1."""
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == '"':
            return index
        else:
            index += 1
    return -1


class HeredocBody(NamedTuple):
    """One heredoc body, with the line that introduced it.

    ``opener_line`` is where the RECEIVER is named (``python3 - <<'PY'``), so a
    caller can tell a body that is data (fed to ``cat``) from one that is a
    program (fed to an interpreter).

    ``ordinal`` counts the operators on ``opener_line`` naming the same
    delimiter before this one, so ``cat <<'EOF'; bash <<'EOF'`` tells the
    second body's receiver from the first's.
    """

    opener_line: str
    body: str
    delimiter: str
    ordinal: int = 0


def split_heredocs(command: str) -> tuple[str, list[HeredocBody]]:
    """Separate the shell being RUN from the heredoc bodies being WRITTEN.

    Returns ``(command_without_bodies, heredocs)``. The introducing line stays
    with the command because the real target lives on it
    (``cat > out.md <<'EOF'``); the body is data to that line's receiver.

    They are returned apart rather than as one string so each can be tokenised
    on its own — see :func:`_tokenise` for why that matters, and
    :func:`get_bash_write_targets` for the cost it avoids.

    Where a heredoc starts and what closes it is bash's grammar, shared with
    every other heredoc site through
    :func:`~claude_code_hooks_daemon.utils.heredoc_operators.scan_heredocs`
    (Plan 00466 N120): any delimiter word, quoted or not.
    """
    scan = scan_heredocs(command)
    heredocs: list[HeredocBody] = []
    for heredoc in scan.heredocs:
        line_start = command.rfind("\n", 0, heredoc.operator.start) + 1
        line_end = command.find("\n", heredoc.operator.start)
        opener_line = command[line_start : len(command) if line_end < 0 else line_end]
        delimiter = heredoc.operator.delimiter
        column = heredoc.operator.start - line_start
        ordinal = sum(
            1
            for operator in find_heredoc_operators(opener_line)
            if operator.delimiter == delimiter and operator.start < column
        )
        heredocs.append(HeredocBody(opener_line, heredoc.body(command), delimiter, ordinal))
    return _without_spans(command, 0, len(command), _body_spans(command, scan)), heredocs


def _write_target_tokens(
    tokens: list[str], include_mutations: bool = False
) -> list[BashWriteDestination]:
    """Candidate targets, in command order, before quoting or path resolution.

    Each candidate carries the SOURCE operands that would supply a basename if
    the destination turns out to be a directory. Only copy verbs have any --
    ``cp a.py somedir`` writes ``somedir/a.py``, a path nothing else can name.

    ``include_mutations`` adds the verbs that change or remove a file without
    authoring its content (:data:`_MUTATION_VERBS`, ``sed -i``, ``ln`` and the
    source of ``mv``). Off by default, so every caller that did not ask for
    them keeps the answers it had.
    """
    targets: list[BashWriteDestination] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]

        if token in _REDIRECT_OPERATORS and index + 1 < len(tokens):
            targets.append(BashWriteDestination(tokens[index + 1]))
            index += 2
            continue

        # A caller that asked for mutations judges COMMANDS, so a verb named as
        # an argument (`grep rm f`) is no write. The default scan keeps reading
        # every word, as its callers have always relied on.
        if (
            include_mutations
            and token in _JUDGED_AS_COMMANDS
            and not _is_command_word(tokens, index, token)
        ):
            index += 1
            continue

        if token == _TEE:
            index = _collect_trailing_operands(tokens, index + 1, targets, keep_all=True)
            continue

        if token in _COPY_VERBS or (include_mutations and token == _LINK):
            before = len(targets)
            index = _collect_trailing_operands(
                tokens, index + 1, targets, keep_all=False, authored=False
            )
            if include_mutations and token == _MOVE and len(targets) > before:
                # The file moved AWAY is gone from where it was.
                targets.extend(
                    BashWriteDestination(source, authored=False, mutation=True)
                    for source in targets[-1].sources
                )
            continue

        if include_mutations and token in _MUTATION_VERBS:
            index = _collect_mutated_operands(tokens, index + 1, targets, token)
            continue

        if token.startswith(_DD_OUTPUT_PREFIX):
            targets.append(BashWriteDestination(token[len(_DD_OUTPUT_PREFIX) :], authored=False))
            index += 1
            continue

        index += 1
    return targets


#: Tokens that end one simple command and start the next.
_COMMAND_BOUNDARIES: Final[frozenset[str]] = _OPERAND_TERMINATORS | frozenset({"(", ")", "{", "}"})

#: The lexer fuses adjacent punctuation (`);`, `)&&`) into one token.
_BOUNDARY_CHARACTERS: Final[frozenset[str]] = frozenset("();&|{}")


def _is_command_boundary(token: str) -> bool:
    """Does ``token`` end one simple command and start the next?"""
    return token in _COMMAND_BOUNDARIES or (
        bool(token) and all(char in _BOUNDARY_CHARACTERS for char in token)
    )


#: Shell keywords and modifiers that may stand before a command word.
_COMMAND_PREFIXES: Final[frozenset[str]] = frozenset(
    {"then", "do", "else", "elif", "if", "while", "until", "!", "time", "coproc"}
)

#: Commands that run the command named after their own options, so a verb
#: following one is a command. `git` runs only `rm` and `mv` that way, and
#: `find` only through `-exec`.
_WRAPPER_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "sudo",
        "doas",
        "env",
        "xargs",
        "command",
        "nice",
        "ionice",
        "nohup",
        "timeout",
        "exec",
        "setsid",
        "stdbuf",
        "watch",
        "busybox",
        "git",
        "find",
    }
)
_GIT_RUNS: Final[frozenset[str]] = frozenset({"rm", "mv"})
_GIT_VALUE_OPTIONS: Final[frozenset[str]] = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
)

#: Words that are judged only where a command stands, under ``include_mutations``.
_JUDGED_AS_COMMANDS: Final[frozenset[str]] = (
    _COPY_VERBS | frozenset({_TEE, _LINK}) | _MUTATION_VERBS
)

#: `NAME=value` before a command.
_ASSIGNMENT_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


def _is_command_word(tokens: list[str], index: int, verb: str) -> bool:
    """Is ``tokens[index]`` run as a command, rather than named as an argument?

    True when it is the first word of its simple command (after any
    assignments and shell keywords), or follows a command that runs another
    one (:data:`_WRAPPER_COMMANDS`). After ``git`` only its own global options
    may intervene, and only ``rm`` and ``mv`` are git subcommands that count.
    """
    start = index
    while start > 0 and not _is_command_boundary(tokens[start - 1]):
        start -= 1
    words = [
        word
        for word in tokens[start:index]
        if word not in _COMMAND_PREFIXES and not _ASSIGNMENT_RE.match(word)
    ]
    if not words:
        return True
    first = words[0]
    if first not in _WRAPPER_COMMANDS:
        return False
    if first != "git":
        return True
    if verb not in _GIT_RUNS:
        return False
    skip_value = False
    for word in words[1:]:
        if skip_value:
            skip_value = False
        elif word in _GIT_VALUE_OPTIONS:
            skip_value = True
        elif not word.startswith(_FLAG_PREFIX):
            return False
    return True


class _ParsedWords(NamedTuple):
    """One command's words, split into operands and the options it was given."""

    operands: list[str]
    short: set[str]
    long: set[str]
    end: int


def _parse_command_words(
    tokens: list[str],
    start: int,
    targets: list[BashWriteDestination],
    *,
    short_value: str = "",
    short_optional: str = "",
    long_value: frozenset[str] = frozenset(),
) -> _ParsedWords:
    """Split one command's words into operands and options.

    Stops at a shell separator. A redirect's word is no operand, and a
    redirect that writes is appended to ``targets`` as it is anywhere else.
    ``short_value`` letters take a value (attached, or the next word);
    ``short_optional`` letters take the rest of their cluster as an optional
    suffix and never the next word (``sed -i.bak``); ``long_value`` names take
    ``=value`` or the next word. ``--`` ends the options.
    """
    operands: list[str] = []
    short: set[str] = set()
    long: set[str] = set()
    index = start
    skip_next = False
    options_ended = False
    while index < len(tokens) and not _is_command_boundary(tokens[index]):
        token = tokens[index]
        if token in _REDIRECT_OPERATORS or token in _INPUT_REDIRECT_OPERATORS:
            if token in _REDIRECT_OPERATORS and index + 1 < len(tokens):
                targets.append(BashWriteDestination(tokens[index + 1]))
            index += 2
            continue
        index += 1
        if skip_next:
            skip_next = False
        elif options_ended or not token.startswith(_FLAG_PREFIX) or token == _FLAG_PREFIX:
            operands.append(token)
        elif token == "--":
            options_ended = True
        elif token.startswith("--"):
            name, equals, _value = token.partition("=")
            long.add(name)
            skip_next = name in long_value and not equals
        else:
            for position, letter in enumerate(token[1:], start=1):
                short.add(letter)
                if letter in short_optional:
                    break
                if letter in short_value:
                    skip_next = position == len(token) - 1
                    break
    return _ParsedWords(operands, short, long, index)


def _collect_mutated_operands(
    tokens: list[str], start: int, targets: list[BashWriteDestination], verb: str
) -> int:
    """Append the files ``verb`` changes or removes; return the next token index.

    These put no new content on disk, so every candidate is not ``authored``.
    ``sed`` counts only with ``-i``/``--in-place``; without it the file is read.
    """
    if verb == _SED:
        parsed = _parse_command_words(
            tokens,
            start,
            targets,
            short_value="efl",
            short_optional="i",
            long_value=frozenset({"--expression", "--file", "--line-length"}),
        )
        in_place = "i" in parsed.short or "--in-place" in parsed.long
        script_given = bool({"e", "f"} & parsed.short) or bool(
            {"--expression", "--file"} & parsed.long
        )
        files = parsed.operands if script_given else parsed.operands[1:]
        if in_place:
            targets.extend(
                BashWriteDestination(file, authored=False, mutation=True) for file in files
            )
        return parsed.end
    if verb == _TRUNCATE:
        parsed = _parse_command_words(
            tokens,
            start,
            targets,
            short_value="sr",
            long_value=frozenset({"--size", "--reference"}),
        )
    elif verb == _TOUCH:
        parsed = _parse_command_words(
            tokens,
            start,
            targets,
            short_value="drt",
            long_value=frozenset({"--date", "--reference", "--time"}),
        )
    else:
        parsed = _parse_command_words(tokens, start, targets)
    targets.extend(
        BashWriteDestination(file, authored=False, mutation=True) for file in parsed.operands
    )
    return parsed.end


def _collect_trailing_operands(
    tokens: list[str],
    start: int,
    targets: list[BashWriteDestination],
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
        if token in _REDIRECT_OPERATORS or token in _INPUT_REDIRECT_OPERATORS:
            # A redirect's word is no operand, and the operands after it are
            # still the command's (Plan 00466 N101 round 12).
            if token in _REDIRECT_OPERATORS and index + 1 < len(tokens):
                targets.append(BashWriteDestination(tokens[index + 1]))
            index += 2
            continue
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
        targets.extend(BashWriteDestination(operand, authored=authored) for operand in operands)
    elif target_directory is not None:
        # Destination first: every remaining operand is a SOURCE.
        targets.append(
            BashWriteDestination(
                target_directory, tuple(operands), directory_only=True, authored=authored
            )
        )
    elif len(operands) >= _MIN_COPY_OPERANDS:
        targets.append(BashWriteDestination(operands[-1], tuple(operands[:-1]), authored=authored))
    return index


def expand_home(target: str) -> str | None:
    """A `~`-leading token as an absolute path, or None when it cannot be.

    PUBLIC so that every route resolving a write destination expands `~` the
    same way. A second resolver that declines `~` instead disagrees with this
    one about where the same token lands, and the two verdicts are then decided
    by which spelling the command happened to use rather than by where the
    write goes (Plan 00412).

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
    of dangerously (the wrong file judged). ``resolve_bash_write_destination`` is where that
    decline actually happens (via ``is_dir()`` and ``candidate.directory_only``)
    -- this function's job is only to produce the path to test, which is why a
    trailing slash is stripped here rather than declined outright.

    **A trailing slash is shell's own directory marker** (``cp a.py dest/``,
    ``-t dest/``), not part of the path. Declining every trailing-slash token
    used to make ``cp a.py somedir/`` and ``cp a.py somedir`` disagree for no
    reason a real shell would recognise -- the first was always dropped before
    ``is_dir()`` ever ran, even when ``somedir`` genuinely existed. Stripping
    it here lets the same real-directory test that already handles the
    slash-less spelling, and ``-t``'s value, decide both consistently.

    **No quote-stripping happens here.** :func:`_tokenise` runs in POSIX mode,
    so quotes are already removed by the lexer, which knows which ones were
    syntax. Stripping again would corrupt the rare path whose name genuinely
    begins or ends with a quote character -- turning a correct target into a
    wrong one, the exact failure this function exists to avoid.
    """
    if not target or needs_expansion(target):
        return None
    if is_device_path(target):
        return None

    target = target.rstrip("/") or "/"

    if target.startswith(_HOME_PREFIX):
        return expand_home(target)

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

    **WARNING -- this is anchored to THIS MODULE's ``__file__``, not to any
    caller's project.** The upward search starts from where
    ``claude_code_hooks_daemon`` is installed on disk, so it always resolves
    to the source tree the daemon package physically lives in (the real repo
    in self-install mode; the vendored ``.claude/hooks-daemon/`` copy in a
    normal client install) -- regardless of which project a particular
    caller, test, or daemon instance is actually operating on. A daemon
    constructed for a DIFFERENT project root (e.g. a test daemon rooted at a
    tmp directory) still gets the source tree's root here, silently. Callers
    that know their own project root (most already do, via
    :class:`ProjectContext` or an explicit constructor argument) should pass
    it through rather than rely on this function to infer it.

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
