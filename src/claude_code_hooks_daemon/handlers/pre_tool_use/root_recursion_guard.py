"""RootRecursionGuardHandler - block recursive scanners rooted at catastrophic paths.

Plan 00142, Layer A. Written after an orphaned ``ugrep -rl "class X" /`` ran
unreaped for ~115 minutes at >1000% CPU (see
``untracked/hooks-daemon-runaway-background-shell-harvester.md``).

The handler blocks a recursive scanner — ``grep -r/-R/-rl``, ``ugrep -r``,
``rgrep``, ``find``, ``fd``/``fdfind``, ``rg`` — whose path argument resolves to
a catastrophic root location (``/``, ``/proc``, ``/sys``, ``/home``, ``/root``,
``~``, ``$HOME``). Recursing from such a root walks the entire filesystem
(including ``/proc``, network mounts, container overlays) and, where ``grep`` is
aliased to multi-threaded ``ugrep``, saturates every core.

Why ``pipe_blocker`` does not catch this: it allowlists ``grep``/``find`` as
"cheap" filters and guards against output truncation, not resource blow-up. And
``... | head`` does NOT bound a ``-l``/``-rl`` scan — ``head`` closes the pipe,
but a producer that matches nothing never writes, so it never receives SIGPIPE
and runs to completion across the whole disk.

Escape hatch (mirrors git_stash's ``MUST_STASH_BECAUSE=``):
    MUST_SCAN_ROOT_BECAUSE="reason"; grep -rl x /
"""

import re
import shlex
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command

# Escape hatch: MUST_SCAN_ROOT_BECAUSE="non-empty reason" bypasses the block.
_ESCAPE_HATCH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""MUST_SCAN_ROOT_BECAUSE=["']([^"']+)["']""",
    re.IGNORECASE,
)

# Scanners that ALWAYS recurse from their path argument (no flag required).
_ALWAYS_RECURSIVE_SCANNERS: Final[frozenset[str]] = frozenset(
    {"find", "fd", "fdfind", "rg", "rgrep"}
)

# Grep-family scanners that recurse ONLY when given an -r/-R style flag.
_GREP_FAMILY_SCANNERS: Final[frozenset[str]] = frozenset({"grep", "egrep", "fgrep", "ugrep"})

# Explicit long/short recursion flags for the grep family.
_GREP_RECURSIVE_FLAGS: Final[frozenset[str]] = frozenset(
    {"-r", "-R", "--recursive", "--dereference-recursive"}
)

# A short-flag cluster like -rl, -Rn, -rIl (recursion bundled with other flags).
_SHORT_FLAG_CLUSTER_RE: Final[re.Pattern[str]] = re.compile(r"-[A-Za-z]+$")

# Shell separators that delimit independent command segments. ``||`` and ``&&``
# are matched before single ``|`` via ordered alternation. ``&`` is deliberately
# NOT split on (it appears inside redirections like ``2>&1``).
_SEGMENT_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"\|\||&&|;|\||\n")

# Home-relative tokens (and prefixes) that denote the user's entire home tree.
_HOME_EXACT: Final[frozenset[str]] = frozenset({"~", "$HOME", "${HOME}"})
_HOME_PREFIXES: Final[tuple[str, ...]] = ("~/", "$HOME/", "${HOME}/")

# Default catastrophic roots. ``/`` is matched EXACTLY (never as a prefix, or it
# would block every absolute path). ``/home`` and ``/root`` are matched exactly
# (so a project living under them is not blocked); ``/proc``/``/sys`` match the
# dir or any descendant. ``~``/``$HOME`` are handled separately.
_DEFAULT_PREFIX_ROOTS: Final[tuple[str, ...]] = ("/proc", "/sys")
_DEFAULT_EXACT_ROOTS: Final[frozenset[str]] = frozenset({"/", "/home", "/root"})


def _command_token_basename(token: str) -> str:
    """Return the bare command name from a (possibly path-qualified) token."""
    return token.rsplit("/", 1)[-1]


def _is_dangerous_root(token: str) -> bool:
    """Return True if ``token`` is a path argument rooted at a catastrophic location."""
    if token in _HOME_EXACT:
        return True
    if any(token.startswith(prefix) for prefix in _HOME_PREFIXES):
        return True
    if token in _DEFAULT_EXACT_ROOTS:
        return True
    for root in _DEFAULT_PREFIX_ROOTS:
        if token == root or token.startswith(root + "/"):
            return True
    return False


def _tokenize(segment: str) -> list[str]:
    """Tokenize a command segment, tolerating shell syntax shlex cannot parse."""
    try:
        return shlex.split(segment)
    except ValueError:
        # Unbalanced quotes etc. — fall back to whitespace splitting so detection
        # still runs (fail-safe toward catching the dangerous case).
        return segment.split()


def _segment_is_dangerous(segment: str) -> bool:
    """Return True if a single command segment is a root-rooted recursive scan."""
    tokens = _tokenize(segment)
    # Skip leading ``VAR=value`` environment assignments to find the real command.
    index = 0
    while index < len(tokens) and re.match(r"^\w+=", tokens[index]):
        index += 1
    if index >= len(tokens):
        return False

    command = _command_token_basename(tokens[index])
    args = tokens[index + 1 :]

    if command in _ALWAYS_RECURSIVE_SCANNERS:
        recursive = True
    elif command in _GREP_FAMILY_SCANNERS:
        recursive = any(
            arg in _GREP_RECURSIVE_FLAGS
            or (_SHORT_FLAG_CLUSTER_RE.fullmatch(arg) is not None and ("r" in arg or "R" in arg))
            for arg in args
        )
    else:
        return False

    if not recursive:
        return False

    return any(_is_dangerous_root(arg) for arg in args)


class RootRecursionGuardHandler(Handler):
    """Block recursive scanners (grep -r, find, fd, rg, ...) rooted at ``/``/home/etc."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.ROOT_RECURSION_GUARD,
            priority=Priority.ROOT_RECURSION_GUARD,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        command = get_bash_command(hook_input)
        if not command:
            return False
        # Escape hatch: explicit justification bypasses the block.
        if _ESCAPE_HATCH_PATTERN.search(command):
            return False
        return any(_segment_is_dangerous(seg) for seg in _SEGMENT_SPLIT_RE.split(command))

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(
            decision=Decision.DENY,
            reason=(
                "BLOCKED: recursive scan rooted at a catastrophic location\n\n"
                "A recursive scanner (grep -r/-rl, ugrep, find, fd, rg) was pointed "
                "at /, /proc, /sys, /home, /root, ~ or $HOME. This walks the ENTIRE "
                "filesystem (including /proc, network mounts, container overlays) and, "
                "where grep is aliased to multi-threaded ugrep, saturates every core. "
                "An incident like this ran for ~115 minutes at >1000% CPU.\n\n"
                "`... | head` does NOT bound the work: head closes the pipe, but a -l/-rl "
                "scan that matches nothing never writes, so it never gets SIGPIPE and runs "
                "to completion across the whole disk.\n\n"
                "DO THIS INSTEAD — scope the search to the project:\n"
                '  rg -l "pattern" /workspace\n'
                '  grep -rl "pattern" "$CLAUDE_PROJECT_DIR"\n'
                "Prefer rg (respects .gitignore, far cheaper) over grep -r.\n\n"
                "ESCAPE HATCH (if you truly must scan from a root):\n"
                '  MUST_SCAN_ROOT_BECAUSE="explain why"; grep -rl x /'
            ),
        )

    def get_claude_md(self) -> str | None:
        return (
            "## root_recursion_guard — recursive scans rooted at / are blocked\n\n"
            "A recursive scanner whose path argument resolves to a catastrophic root "
            "location is blocked, because it walks the entire filesystem and can pin "
            "every CPU core for hours.\n\n"
            "**Blocked** (recursive scanner + dangerous root path):\n\n"
            "- `grep -r`/`-R`/`-rl`, `ugrep -r`, `rgrep`, `find`, `fd`/`fdfind`, `rg`\n"
            "- pointed at `/`, `/proc`, `/sys`, `/home`, `/root`, `~`, `$HOME`\n\n"
            "**Allowed**: the same scanners scoped to the project — "
            '`rg -l "x" /workspace`, `grep -rl "x" "$CLAUDE_PROJECT_DIR"`, '
            "`grep -rl x src/`, `find . -name y`. Non-recursive `grep x /etc/hosts` "
            "is not affected.\n\n"
            "**Note**: `... | head` does NOT bound a `-l`/`-rl` scan — a producer that "
            "matches nothing never writes, so it never receives SIGPIPE and runs to "
            "completion across the whole disk.\n\n"
            "**Escape hatch** (rare legitimate whole-disk scan):\n"
            "```\n"
            'MUST_SCAN_ROOT_BECAUSE="explain why"; grep -rl x /\n'
            "```"
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="recursive grep rooted at / blocked",
                command='echo "grep -rl \\"class X\\" /"',
                description="Blocks grep -rl rooted at / — steer to a scoped search",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"workspace", r"MUST_SCAN_ROOT_BECAUSE"],
                safety_notes="Uses echo - the dangerous command is only a string, never run",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="find rooted at / blocked",
                command='echo "find / -type d -name phparkitect"',
                description="Blocks find rooted at / (always recursive)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"head"],
                safety_notes="Uses echo - the dangerous command is only a string, never run",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="scoped recursive grep allowed",
                command='echo "grep -rl \\"class X\\" /workspace"',
                description="Allows a recursive scan scoped to the project root",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses echo - safe; scoped search must not be blocked",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
