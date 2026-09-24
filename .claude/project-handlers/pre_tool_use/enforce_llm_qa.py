"""EnforceLlmQaHandler - blocks run_all.sh, requires llm_qa.py.

This project uses LLM-optimised QA output (scripts/qa/llm_qa.py) which
produces ~16 lines instead of 200+. LLM agents should never run the
verbose run_all.sh directly.
"""

import fnmatch
import re
import shlex
from collections.abc import Iterator
from typing import Any, Final

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.utils import shell_expansion
from claude_code_hooks_daemon.utils.shell_segmentation import (
    split_unquoted,
    strip_quoted_heredoc_bodies,
)

_BLOCKED_SCRIPT = "run_all.sh"
_LLM_SCRIPT = "./scripts/qa/llm_qa.py all"

# Characters that end one command and begin the next AT THE TOP LEVEL of a
# shell line. A newline is one of them: `a\nb` runs two commands exactly as
# `a; b` does, and omitting it let a real invocation on line 2 inherit line 1's
# leading word. `&` covers both `&&` and backgrounding; splitting on the single
# character handles both without a second rule.
_SEGMENT_SEPARATORS = (";", "|", "&", "\n")

# Commands that read/inspect a file WITHOUT executing it, or record its path
# as DATA (a VCS message, a staged pathspec). This is the ONLY exemption from
# deny-by-default (Plan 00466 review, M1): a command whose head is not one of
# these, and does not itself name the script, is treated as a candidate
# invocation regardless of what verb it is -- `source`, `time`, `sudo`,
# `nohup`, `command`, `setsid`, `stdbuf`, a bare `CI=1 ./run_all.sh`, none of
# these was ever a "wrapper" in any enumerable sense, and an earlier
# allow-by-default redesign (which flipped the default to require an
# executing-wrapper allowlist instead) missed exactly those 16 shapes. See
# `_word_names_the_script` for how the N6 false positive (a prose mention
# inside a quoted argument to an unrelated command) stays fixed without an
# allow-by-default policy: it is fixed by TOKENISATION, not by widening what
# is allowed to execute.
_INSPECTION_COMMANDS = (
    "cat",
    "less",
    "more",
    "head",
    "tail",
    "grep",
    "rg",
    "wc",
    "bat",
    "shellcheck",
    "shfmt",
    "diff",
    "stat",
    "file",
)
_VCS_COMMANDS = ("git", "gh")
_DATA_CONSUMERS = _INSPECTION_COMMANDS + _VCS_COMMANDS


#: n3 (Plan 00466 guard-defects review 2): a `git`/`rg` HEAD is a trusted
#: data consumer in general, but these specific subcommand/flag shapes
#: EXECUTE an argument as a command rather than merely reading one --
#: `git bisect run <cmd>`, `git rebase -x/--exec <cmd>`, `git -c
#: alias.NAME=!<cmd>` (defines an alias that shells out when later
#: invoked), `rg --pre <cmd>` (a preprocessor command). The exemption is
#: VOIDED for these, falling through to the ordinary word-name/string-
#: executor checks below instead of returning early.
def _data_consumer_exemption_voided(head_name: str, command_tokens: list[str]) -> bool:
    """True when this ``head_name`` data consumer's own arguments execute."""
    rest = command_tokens[1:]
    if head_name == "git":
        if rest[:2] == ["bisect", "run"]:
            return True
        if rest[:1] == ["rebase"] and any(
            token in ("-x", "--exec") or token.startswith("--exec=") for token in rest[1:]
        ):
            return True
        if (
            rest[:1] == ["-c"]
            and len(rest) >= 2
            and rest[1].startswith("alias.")
            and "=" in rest[1]
        ):
            value = rest[1].split("=", 1)[1]
            # `!` is a `_PUNCTUATION_CHARS` entry, so an UNQUOTED
            # `alias.q=!cmd` tokenises as `alias.q=` then a SEPARATE `!`
            # token -- both spellings (the bang glued to the value, or
            # split off as its own next token) are checked.
            following = rest[2] if len(rest) >= 3 else ""
            if value.startswith("!") or following == "!":
                return True
        return False
    if head_name == "rg":
        return any(token == "--pre" or token.startswith("--pre=") for token in rest)
    return False


# `$(...)` and `` `...` `` both run their inner text as a command before the
# rest of the line runs (Plan 00466 N6, `test_still_matches_a_bare_command_substitution`
# and the pre-existing UNQUOTED-heredoc regression). Matched non-greedily and
# with one level of nested parens so `$(echo $(x))` still finds `echo $(x)`.
_SUBSTITUTION_PATTERN = re.compile(r"\$\(([^()]*(?:\([^()]*\)[^()]*)*)\)|`([^`]*)`")

# `(`, `{` and `!` introduce a subshell, a group, or negation and need to
# split off as their own token even when glued to the next word with no
# whitespace (`(./run_all.sh)`) -- plain whitespace-splitting would otherwise
# hand back one token `(./run_all.sh)` that names no real path (Plan 00466
# review M1). shlex's `punctuation_chars` support does exactly this, and
# also protects `~-./*?=` as wordchars so a path is never split mid-token.
# `<`/`>` join the set for the same reason (review 2, M1): a GLUED
# redirection (`run_all.sh>out.txt`, no whitespace) otherwise hands back one
# token whose suffix is `>out.txt`, not `/run_all.sh`.
_PUNCTUATION_CHARS = "(){}!<>"

# A leading `VAR=value` assignment before the real command (`CI=1 ./run_all.sh`)
# is not itself a command word, and must be skipped when resolving the
# segment's HEAD -- otherwise `VAR=value cat run_all.sh` would resolve to a
# head that matches no data-consumer and wrongly deny an inspection.
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _split_top_level(command: str) -> list[str]:
    """Split ``command`` into segments on UNQUOTED shell separators.

    A separator inside quotes is data, not syntax. The original regex split on
    a bare ``[;|]`` and so cut through a quoted grep alternation
    (``"a\\|b\\|CHECKS="``), stranding a fragment whose apparent leading word
    was the tail of the pattern — which matched no allowlist entry and denied
    an ordinary read of the script.

    Delegates to the shared scanner (Plan 00200 Task 3.7). This function used to
    carry its own, which applied backslash escaping INSIDE single quotes where
    bash treats it as literal — so a trailing ``\\`` in a single-quoted argument
    swallowed the closing quote, nothing split, and the guarded script rode
    through on an allowlisted leading word. The sibling scanner in
    ``pipe_blocker`` had the mirror-image bug. One implementation, one place to
    fix, no way for the two to disagree again.

    A QUOTED heredoc body is blanked BEFORE splitting, because a newline is a
    separator here: without it the body of ``git commit -F - <<'EOF'`` is cut
    into pseudo-commands and each line judged on its leading word, so a message
    merely MENTIONING the guarded script was denied (Plan 00234 finding H-3 —
    found by hitting it while writing that very commit). The VCS allowlist below
    was meant to prevent exactly that and could not reach this spelling. The
    stripper is shared with ``pipe_blocker`` for the same one-implementation
    reason as the splitter; an UNQUOTED ``<<EOF`` still expands and stays
    scanned.
    """
    return split_unquoted(strip_quoted_heredoc_bodies(command), _SEGMENT_SEPARATORS)


def _tokenise(segment: str) -> list[str] | None:
    """Quote- and punctuation-aware split of one shell segment, or ``None`` if
    it can't be split safely.

    Mirrors the established pattern in ``project_containment.py``
    (``shlex.split`` wrapped in try/except) rather than hand-rolling a new
    tokeniser — this project already has one way to do this — extended with
    ``punctuation_chars`` so ``(``/``{``/``!`` split off even glued to the
    next word (Plan 00466 review M1).
    """
    try:
        lexer = shlex.shlex(segment, posix=True, punctuation_chars=_PUNCTUATION_CHARS)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return None


def _segment_head_index(tokens: list[str]) -> int | None:
    """Index of the first real command word: skips punctuation tokens and
    ``VAR=value`` assignments (Plan 00466 review M1) so ``CI=1 cat run_all.sh``
    still resolves its head to ``cat``, not to the assignment. ``None`` when
    the segment is nothing but punctuation/assignments.
    """
    for index, token in enumerate(tokens):
        if token in _PUNCTUATION_CHARS or _ASSIGNMENT_RE.match(token):
            continue
        return index
    return None


def _segment_head(tokens: list[str]) -> str | None:
    """The first real command word — see ``_segment_head_index``."""
    index = _segment_head_index(tokens)
    return tokens[index] if index is not None else None


def _word_names_the_script(word: str) -> bool:
    """True when ``word`` — a single already-tokenised shell word — IS the script.

    Matches the bare name or any path ending in it (``./scripts/qa/run_all.sh``,
    ``/workspace/scripts/qa/run_all.sh``). Deliberately NOT a substring test:
    a whole shlex token that merely CONTAINS the name (e.g. an entire quoted
    ``--title "... run_all.sh ..."`` argument, which shlex hands back as one
    token) does not end in ``/run_all.sh`` or equal ``run_all.sh``, so prose
    naming the script in an otherwise-unrelated argument does not match here.
    """
    return word == _BLOCKED_SCRIPT or word.endswith("/" + _BLOCKED_SCRIPT)


#: M-3 (Plan 00466 review 3): brace-word discovery AND expansion both moved
#: to the shared bounded primitives in ``utils/shell_expansion`` -- this
#: module's own ``_BRACE_GROUP_RE``/``_expand_braces`` and, worse, a
#: ``\S*\{[^{}]*\}\S*`` word-finder regex (the EXACT catastrophically
#: backtracking shape the secret matcher's own M2d fix abandoned -- measured
#: here independently at 15s/94KB, >45s/200KB on adversarial no-brace input)
#: used to live here as a second, independent copy of both defects.


def _brace_words_in_segment(segment: str) -> Iterator[str]:
    """Every raw brace-expansion word in ``segment``'s own text (lazily)."""
    return shell_expansion.iter_brace_words(segment)


def _word_could_name_the_script(word: str) -> bool:
    """True when ``word`` IS the script (``_word_names_the_script``), or is a
    shell glob/brace expression the shell could expand TO it (review 2, M1):
    a token such as ``run_all.sh*`` or ``{run_all.sh,}`` is not literally
    equal to the script's own path, but names it just as directly as an
    exact word does the moment the shell expands it.

    M-3 (Plan 00466 review 3): a brace group past the shared expander's cap
    raises ``TooManyToEnumerateError`` rather than enumerating -- treated
    here as "could name it" (fail closed, DENY): this guard's whole
    redesign (M1, review 2) is already deny-by-default, over-blocking being
    the accepted safe direction (m-3, review 2's own minor), so an
    unenumerable brace word gets the same treatment as one that plainly
    does.
    """
    try:
        candidates = shell_expansion.expand_braces(word)
    except shell_expansion.TooManyToEnumerateError:
        return True
    for candidate in candidates:
        if _word_names_the_script(candidate):
            return True
        basename = candidate.rsplit("/", 1)[-1]
        if any(char in basename for char in "*?[") and fnmatch.fnmatch(_BLOCKED_SCRIPT, basename):
            return True
    return False


#: Shells whose ``-c``/``-lc`` argument is executed as a NEW shell command
#: line, not a filesystem path (review 2, M1) -- matched by basename so
#: ``/bin/bash``, ``bash`` and a version-suffixed ``zsh5`` all count.
_STRING_EXEC_SHELLS = ("bash", "sh", "zsh", "dash", "ksh", "ash")
_STRING_EXEC_C_FLAG_RE = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")


def _tokens_before_first_punctuation(tokens: list[str]) -> list[str]:
    """``tokens`` up to (not including) the first punctuation marker.

    Stops a trailing redirection glued onto a string-executor invocation
    (``ssh host 'cmd' > out.txt``) from being read as part of the remote
    command -- the punctuation marker is exactly where the OUTER command
    resumes.
    """
    result: list[str] = []
    for token in tokens:
        if token in _PUNCTUATION_CHARS:
            break
        result.append(token)
    return result


def _string_executor_argument(head_name: str, tokens: list[str]) -> str | None:
    """The nested SHELL TEXT argument of a string-executor invocation, or
    ``None`` (review 2, M1).

    ``_word_names_the_script`` only matches a ``-c`` argument when the
    invocation is the LAST thing in it -- a trailing flag, redirection or a
    second command after ``;``/``|`` inside the string defeated that. These
    heads get their string argument re-parsed as its own command line
    instead, through the caller's recursive ``_has_real_invocation`` call.
    """
    rest = _tokens_before_first_punctuation(tokens[1:])
    if head_name in _STRING_EXEC_SHELLS or head_name == "su":
        for index, token in enumerate(tokens[1:], start=1):
            if _STRING_EXEC_C_FLAG_RE.match(token) and index + 1 < len(tokens):
                return tokens[index + 1]
        return None
    if head_name == "eval":
        return " ".join(rest) if rest else None
    if head_name in ("ssh", "watch"):
        # `ssh [options] host command...` / `watch [options] command...` --
        # the LAST token before any redirection is the remote/watched
        # command, when there is more than just the host (ssh) or nothing
        # but flags (watch).
        return rest[-1] if len(rest) >= (2 if head_name == "ssh" else 1) else None
    return None


#: `python`/`python3`/a version-suffixed `python3.11` -- matched by
#: basename, mirroring `_STRING_EXEC_SHELLS`.
_PYTHON_HEAD_RE = re.compile(r"^python[23]?(\.\d+)?$")


def _python_dash_c_argument(head_name: str, tokens: list[str]) -> str | None:
    """The Python SOURCE argument of a ``python -c``/``python3 -c``
    invocation, or ``None`` (review 2, M1). Not shell text -- a substring
    test on it is enough, per the review's own judgement."""
    if not _PYTHON_HEAD_RE.match(head_name):
        return None
    for index, token in enumerate(tokens[1:], start=1):
        if token == "-c" and index + 1 < len(tokens):
            return tokens[index + 1]
    return None


def _strip_timeout_prefix(tokens: list[str]) -> list[str]:
    """``tokens`` with a leading ``timeout [OPTIONS] DURATION`` stripped, or
    ``tokens`` unchanged when it does not start with ``timeout`` (review 2,
    M1: ``timeout 900 bash -c '...'`` is an everyday agent shape). Flags are
    skipped by their leading ``-``; genuine flag VALUES (e.g. ``-s SIGNAL``)
    are not specially handled -- no test shape here needs it, and skipping
    one token too few only means the duration is mistaken for the command,
    which still tokenises safely and falls through to no match rather than
    a wrong one.
    """
    if not tokens or tokens[0] != "timeout":
        return tokens
    index = 1
    while index < len(tokens) and tokens[index].startswith("-"):
        index += 1
    if index < len(tokens):
        index += 1  # the duration argument itself
    return tokens[index:]


def _substitution_inner_segments(text: str) -> list[str]:
    """Every top-level segment inside every ``$(...)``/backtick substitution in ``text``."""
    inner_segments: list[str] = []
    for match in _SUBSTITUTION_PATTERN.finditer(text):
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        inner_segments.extend(_split_top_level(inner))
    return inner_segments


#: M-3 (Plan 00466 review 3): a string-executor argument (``eval``) and a
#: command substitution both feed BACK into ``_has_real_invocation``, which
#: re-tokenises and re-scans essentially the whole remaining text at every
#: level -- a legitimate command nests maybe two or three of these deep;
#: past this cap the recursion gives up and treats the segment as a
#: candidate invocation (fail closed, matching this guard's own
#: deny-by-default direction), rather than continuing to re-parse
#: attacker-controlled padding a fixed, small number of times more.
_MAX_INVOCATION_RECURSION_DEPTH: Final[int] = 20


def _segment_executes_script(segment: str, *, depth: int = 0) -> bool:
    """True when ``segment`` is a REAL invocation of the blocked script.

    Deny-by-default (Plan 00466 review M1): the script is a real invocation
    the moment it is named as its own shell WORD anywhere in the segment
    (``_word_names_the_script`` — exact name, or a path ending in it), UNLESS
    the segment's own HEAD is a data consumer (``_DATA_CONSUMERS`` — a reader
    or a VCS command), which only ever takes the path as data. There is no
    "known wrapper" allowlist: a leading ``VAR=value``, ``source``/``.``,
    ``time``, ``nohup``/``sudo``/``command``/``setsid``/``stdbuf``, and every
    other verb that is not a data consumer, is a candidate invocation by
    default. This also covers a quoted ``-c``/``-lc`` argument to a real
    shell without any special-casing: shlex hands the whole quoted string
    back as ONE word, and that word still ends in ``/run_all.sh`` whenever
    the invocation is the last thing on it (``bash -lc 'cd x && ./run_all.sh'``).

    A substitution's inner text is checked first, unconditionally, since bash
    runs it before running anything else on the line regardless of the
    surrounding command's head.

    A segment that can't be tokenised safely (unbalanced quoting) falls back
    to the old conservative substring check — deny rather than silently wave
    a real invocation through because it broke the parser.

    ``depth`` (M-3, Plan 00466 review 3) is threaded through every
    recursive call (a substitution's inner segment, a string-executor's
    nested command) -- see :data:`_MAX_INVOCATION_RECURSION_DEPTH`.
    """
    if depth > _MAX_INVOCATION_RECURSION_DEPTH:
        return True

    for inner_segment in _substitution_inner_segments(segment):
        if _segment_executes_script(inner_segment, depth=depth + 1):
            return True

    tokens = _tokenise(segment)
    if tokens is None:
        return _BLOCKED_SCRIPT in segment
    if not tokens:
        return False

    head_index = _segment_head_index(tokens)
    command_tokens = tokens[head_index:] if head_index is not None else tokens
    # `timeout N bash -c '...'` (review 2, M1): the ACTUAL command sits
    # after timeout's own duration argument, so it is stripped before any
    # of the checks below look at the head.
    command_tokens = _strip_timeout_prefix(command_tokens)
    if not command_tokens:
        return False

    head = command_tokens[0]
    head_name = head.rsplit("/", 1)[-1]
    # n3 (Plan 00466 review 2): the exemption is for the TRUSTED bare-word
    # reader, not whatever basename a path happens to end in -- `head ==
    # head_name` requires no `/` prefix at all, so a shadowed or
    # path-qualified `cat` gets no exemption and is judged like any other
    # unrecognised head.
    if (
        head == head_name
        and head_name in _DATA_CONSUMERS
        and not _data_consumer_exemption_voided(head_name, command_tokens)
    ):
        return False

    string_arg = _string_executor_argument(head_name, command_tokens)
    if string_arg is not None and _has_real_invocation(string_arg, depth=depth + 1):
        return True

    python_arg = _python_dash_c_argument(head_name, command_tokens)
    if python_arg is not None and _BLOCKED_SCRIPT in python_arg:
        return True

    if any(_word_could_name_the_script(token) for token in tokens):
        return True
    # A real brace expansion (`{run_all.sh,}`) has no internal whitespace, so
    # shlex would keep it as one word -- except `{`/`}` are themselves
    # punctuation chars (needed for `{ cmd; }` group syntax), which tears it
    # into three tokens before `_word_could_name_the_script` ever sees a
    # complete span. Recover it from the raw segment text instead.
    return any(_word_could_name_the_script(word) for word in _brace_words_in_segment(segment))


def _has_real_invocation(command: str, *, depth: int = 0) -> bool:
    """True when any top-level segment of ``command`` really runs the script."""
    for segment in _split_top_level(command):
        stripped = segment.strip()
        if stripped and _segment_executes_script(stripped, depth=depth):
            return True
    return False


class EnforceLlmQaHandler(Handler):
    """Block run_all.sh and direct LLM agents to llm_qa.py."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="enforce-llm-qa",
            priority=41,
            terminal=True,
            tags=["project", "blocking", "qa"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match Bash commands that actually run run_all.sh (not just mention it)."""
        if hook_input.get("tool_name") != "Bash":
            return False
        tool_input = hook_input.get("tool_input", {})
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        if _BLOCKED_SCRIPT not in command:
            return False
        # A path passed to cat/less/grep/shellcheck/git inspects or records the
        # script; none of them executes it, regardless of output volume. The
        # verdict is per segment, so `cat run_all.sh; bash run_all.sh` still
        # matches on the second half.
        return _has_real_invocation(command)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block with guidance to use llm_qa.py instead."""
        return HookResult(
            decision=Decision.DENY,
            reason=(
                "USE LLM-OPTIMISED QA SCRIPT\n\n"
                "run_all.sh produces 200+ lines of verbose output.\n"
                "Use the LLM-optimised wrapper instead:\n\n"
                f"  {_LLM_SCRIPT}\n\n"
                "This produces ~16 lines with structured JSON output.\n"
                "Individual scripts (run_tests.sh, run_lint.sh, etc.) are still allowed."
            ),
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Define acceptance tests."""
        return [
            AcceptanceTest(
                title="Block run_all.sh",
                command="bash -n scripts/qa/run_all.sh",
                description="Blocks verbose QA script, directs to llm_qa.py",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"llm_qa\.py", r"run_all\.sh"],
                safety_notes=(
                    "A genuine invocation shape (bash naming the script), so this "
                    "exercises the real detection path rather than a prose mention "
                    '(Plan 00466 N6: the old `echo "..."` fixture here was denied '
                    "only because echo wasn't on a since-removed allowlist, the "
                    "very false-positive class N6 fixes). `-n` makes bash parse "
                    "the script without running it, so it stays safe to actually "
                    "dispatch even if the block were to fail."
                ),
                test_type=TestType.BLOCKING,
                dispatch_as_bash=True,
            ),
            AcceptanceTest(
                title="Allow inspecting run_all.sh with cat (not an execution)",
                command="cat scripts/qa/run_all.sh",
                description=(
                    "cat reads the script's contents; it never executes it, so "
                    "this must NOT be blocked. Regression test for a real "
                    "dogfooding false positive (Plan 00200)."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read-only inspection of a tracked file",
                test_type=TestType.BLOCKING,
                dispatch_as_bash=True,
            ),
        ]
