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
from dataclasses import dataclass
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils import linear_shlex
from claude_code_hooks_daemon.utils.escape_hatch import command_declares_hatch
from claude_code_hooks_daemon.utils.path_predicates import path_is_file

# Full first-fire teaching content (Plan 00116), preserving the pre-migration
# handler's rich prose verbatim.
_ROOT_RECURSION_VERBOSE_CONTENT = (
    "A recursive scanner (grep -r/-rl, ugrep, find, fd, rg) was pointed "
    "at /, /proc, /sys, /home, /root, ~ or $HOME. This walks the ENTIRE "
    "filesystem (including /proc, network mounts, container overlays) and, "
    "where grep is aliased to multi-threaded ugrep, saturates every core. "
    "An incident like this ran for ~115 minutes at >1000% CPU.\n\n"
    "`... | head` does NOT bound the work: head closes the pipe, but a -l/-rl "
    "scan that matches nothing never writes, so it never gets SIGPIPE and runs "
    "to completion across the whole disk.\n\n"
    "DO THIS INSTEAD — scope the search to the project:\n"
    '  rg -l "pattern" .\n'
    '  grep -rl "pattern" "$CLAUDE_PROJECT_DIR"\n'
    "Prefer rg (respects .gitignore, far cheaper) over grep -r.\n\n"
    "ESCAPE HATCH (if you truly must scan from a root):\n"
    '  MUST_SCAN_ROOT_BECAUSE="explain why"; grep -rl x /'
)

# Escape hatch: MUST_SCAN_ROOT_BECAUSE="non-empty reason" bypasses the block.
_ESCAPE_HATCH: Final = "MUST_SCAN_ROOT_BECAUSE"

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

# Home-relative tokens that denote the user's entire home tree.
_HOME_EXACT: Final[frozenset[str]] = frozenset({"~", "$HOME", "${HOME}"})

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
    """Return True if ``token`` is a scan root that walks a whole catastrophic tree.

    ``/``, ``/home``, ``/root``, ``/proc``, ``/sys``, ``~`` and ``$HOME`` are
    the trees themselves (a trailing slash is the same root). A subdirectory of
    the home tree (``~/projects``) is a project root, and an existing FILE under
    ``/proc`` or ``/sys`` is a single read: neither walks the tree.
    """
    root = token.rstrip("/") or token
    if root in _HOME_EXACT or root in _DEFAULT_EXACT_ROOTS:
        return True
    if any(root.startswith(prefix + "/") for prefix in _DEFAULT_PREFIX_ROOTS):
        # An unreadable path counts as not-a-file, so it is judged as a tree.
        return not path_is_file(root, unreadable_means=False)
    return root in _DEFAULT_PREFIX_ROOTS


@dataclass(frozen=True)
class _ScanSyntax:
    """The option syntax that tells a scanner's operands apart."""

    short_values: str  # short options whose value is the next word (or attached)
    long_values: frozenset[str]  # long options whose value is the next word
    pattern_options: str = ""  # short options that SUPPLY the pattern
    pattern_long: frozenset[str] = frozenset()  # long options that supply the pattern
    depth_short: str = ""  # short option bounding the depth
    depth_long: frozenset[str] = frozenset()  # long options bounding the depth
    path_long: frozenset[str] = frozenset()  # long options whose value IS a scan root
    pattern_operand: bool = True  # the first operand is a pattern, not a path


_GREP_SYNTAX: Final = _ScanSyntax(
    short_values="efmABCdD",
    long_values=frozenset(
        {"regexp", "file", "max-count", "after-context", "before-context", "context"}
        | {"include", "exclude", "exclude-from", "exclude-dir", "include-dir", "directories"}
        | {"devices", "label", "binary-files"}
    ),
    pattern_options="ef",
    pattern_long=frozenset({"regexp", "file"}),
)
_RG_SYNTAX: Final = _ScanSyntax(
    short_values="efmABCgtTjMrEd",
    long_values=frozenset(
        {"regexp", "file", "max-count", "after-context", "before-context", "context", "glob"}
        | {"iglob", "type", "type-not", "type-add", "max-depth", "threads", "max-filesize"}
        | {"replace", "engine", "encoding", "pre", "pre-glob", "sort", "sortr", "colors"}
        | {"ignore-file", "max-columns", "path-separator"}
    ),
    pattern_options="ef",
    pattern_long=frozenset({"regexp", "file", "files"}),
    depth_short="d",
    depth_long=frozenset({"max-depth"}),
)
_FD_SYNTAX: Final = _ScanSyntax(
    short_values="deEtSjc",
    long_values=frozenset(
        {"max-depth", "extension", "exclude", "type", "size", "threads", "color", "min-depth"}
        | {"exact-depth", "changed-within", "changed-before", "owner", "format", "ignore-file"}
        | {"max-results", "search-path", "base-directory"}
    ),
    depth_short="d",
    depth_long=frozenset({"max-depth"}),
    path_long=frozenset({"search-path", "base-directory"}),
)
_SYNTAX_BY_COMMAND: Final[dict[str, _ScanSyntax]] = {
    **dict.fromkeys(_GREP_FAMILY_SCANNERS | {"rgrep"}, _GREP_SYNTAX),
    "rg": _RG_SYNTAX,
    "fd": _FD_SYNTAX,
    "fdfind": _FD_SYNTAX,
}

# A scan bounded to this many levels below its root does not walk the tree.
_BOUNDED_DEPTH: Final = 1


def _depth_within_bound(value: str | None) -> bool:
    return value is not None and value.isdigit() and int(value) <= _BOUNDED_DEPTH


_FIND_ACTIONS: Final = frozenset({"-exec", "-execdir", "-ok", "-okdir"})


def _find_roots(args: list[str]) -> tuple[list[str], bool]:
    """The start paths of a ``find`` and whether ``-maxdepth`` bounds it."""
    index = 0
    while index < len(args):
        if args[index] in ("-H", "-L", "-P") or args[index].startswith("-O"):
            index += 1
        elif args[index] == "-D":
            index += 2
        else:
            break
    roots: list[str] = []
    while index < len(args) and not args[index].startswith(("-", "(", "!", ",")):
        roots.append(args[index])
        index += 1
    # `-exec`/`-ok` hand every entry to another command, which may recurse.
    runs_a_command = any(arg in _FIND_ACTIONS for arg in args)
    bounded = not runs_a_command and any(
        arg == "-maxdepth" and _depth_within_bound(following)
        for arg, following in zip(args, [*args[1:], ""], strict=True)
    )
    return roots, bounded


def _search_roots(syntax: _ScanSyntax, args: list[str]) -> tuple[list[str], bool]:
    """The paths a grep/rg/fd-style scan walks and whether a depth option bounds it.

    The first operand is the PATTERN (unless an option supplies it), so
    ``rg "/home" src/`` scans ``src/`` only. An option's value is not an operand.
    """
    operands: list[str] = []
    roots: list[str] = []
    pattern_given = False
    bounded = False
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg == "--":
            operands.extend(args[index:])
            break
        value: str | None = None
        if arg.startswith("--"):
            name, equals, attached = arg[2:].partition("=")
            pattern_given = pattern_given or name in syntax.pattern_long
            takes_next = not equals and name in syntax.long_values
            value = attached if equals else (args[index] if takes_next else None)
            index += takes_next
            if name in syntax.path_long and value is not None:
                roots.append(value)
            if name in syntax.depth_long:
                bounded = bounded or _depth_within_bound(value)
        elif arg.startswith("-") and len(arg) > 1:
            for position, letter in enumerate(arg[1:], 1):
                if letter in syntax.short_values:
                    pattern_given = pattern_given or letter in syntax.pattern_options
                    attached = arg[position + 1 :]
                    takes_next = not attached
                    value = attached or (args[index] if index < len(args) else None)
                    index += takes_next
                    if letter in syntax.depth_short:
                        bounded = bounded or _depth_within_bound(value)
                    break
        else:
            operands.append(arg)
    skipped = 0 if pattern_given or not syntax.pattern_operand else 1
    return roots + operands[skipped:], bounded


def _tokenize(segment: str) -> list[str]:
    """Tokenize a command segment, tolerating shell syntax shlex cannot parse."""
    try:
        return linear_shlex.split(segment)
    except ValueError:
        # Unbalanced quotes etc. — fall back to whitespace splitting so detection
        # still runs (fail-safe toward catching the dangerous case).
        return segment.split()


def _is_xargs(segment: str) -> bool:
    """Whether a pipeline stage is ``xargs`` (after any ``VAR=value`` prefix)."""
    tokens = [token for token in _tokenize(segment) if not re.match(r"^\w+=", token)]
    return bool(tokens) and _command_token_basename(tokens[0]) == "xargs"


def _segment_is_dangerous(segment: str, feeds_xargs: bool = False) -> bool:
    """Return True if a single command segment is a root-rooted recursive scan.

    ``feeds_xargs``: its output is piped to ``xargs``, which runs a command on
    every entry, so a depth bound no longer limits the work.
    """
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

    if command == "find":
        roots, bounded = _find_roots(args)
    else:
        roots, bounded = _search_roots(_SYNTAX_BY_COMMAND[command], args)
    return not (bounded and not feeds_xargs) and any(_is_dangerous_root(root) for root in roots)


class RootRecursionGuardHandler(PreToolUseHandlerBase):
    """Block recursive scanners (grep -r, find, fd, rg, ...) rooted at ``/``/home/etc."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.ROOT_RECURSION_GUARD,
            priority=Priority.ROOT_RECURSION_GUARD,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        self._rule = Rule(
            rule_id=RuleID.ROOT_RECURSION_CATASTROPHIC,
            blocked="`grep -r`/`find`/`rg`/... rooted at `/`, `/proc`, `/sys`, `/home`, `/root`, `~`, `$HOME`",
            why="Walks the entire filesystem and can pin every CPU core for hours",
            fix='Scope the search to the project (e.g. `rg -l "pattern" .`)',
            verbose=_ROOT_RECURSION_VERBOSE_CONTENT,
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        command = get_bash_command(hook_input)
        if not command:
            return False
        # Escape hatch: explicit justification bypasses the block.
        if command_declares_hatch(command, _ESCAPE_HATCH):
            return False
        parts = _SEGMENT_SPLIT_RE.split(command)
        separators = _SEGMENT_SPLIT_RE.findall(command)
        return any(
            _segment_is_dangerous(
                segment,
                feeds_xargs=index < len(separators)
                and separators[index] == "|"
                and _is_xargs(parts[index + 1]),
            )
            for index, segment in enumerate(parts)
        )

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's blocking behaviour."""
        return [self._rule]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Block with a verbose-first/terse-after explanation.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G): the first fire for a
        given agent is verbose (full teaching content); subsequent fires for
        the SAME agent are terse. An event with no transcript_path fails
        toward verbose every time (unknown disclosure state -> more info)
        since there is no key to track against.
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(
            transcript_path, RuleID.ROOT_RECURSION_CATASTROPHIC
        ):
            message = self._formatter.terse(self._rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.ROOT_RECURSION_CATASTROPHIC)
            message = self._formatter.verbose(self._rule)

        return GatingResult(decision=Decision.DENY, reason=message)

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
            '`rg -l "x" .`, `grep -rl "x" "$CLAUDE_PROJECT_DIR"`, '
            "`grep -rl x src/`, `find . -name y`. Non-recursive `grep x /etc/hosts` "
            "is not affected. The guard judges the scan ROOT: a pattern operand "
            '(`rg "/home" src/`), a single file (`grep -r foo /proc/self/status`), '
            "a subdirectory of home (`~/projects`, `$HOME/proj`) and a scan bounded to "
            "one level (`find / -maxdepth 1`, `rg --max-depth 1 x /`) are allowed. "
            "`grep -r x /`, `find / -name x` and `rg x ~` stay blocked.\n\n"
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
                command='false && grep -rl "class X" /',
                dispatch_as_bash=True,
                description="Blocks grep -rl rooted at / — steer to a scoped search",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED",
                    # The deny text scopes via "$CLAUDE_PROJECT_DIR", not an
                    # expanded project path (v3.55.0 Test 64).
                    r"CLAUDE_PROJECT_DIR",
                    r"MUST_SCAN_ROOT_BECAUSE",
                ],
                safety_notes=(
                    "'false &&' short-circuits so grep never executes. Detection happens "
                    "at the PreToolUse hook stage before the shell runs anything, so a "
                    "correct deny never lets the command run; the short-circuit is a second "
                    "layer of safety, not the mechanism relied on. NOTE: this command must "
                    "NOT be wrapped in echo — the handler tokenizes the command with shlex "
                    "and inspects the first real word of each shell segment, so "
                    'echo "grep -rl ... /" makes echo the detected command and silently '
                    "defeats detection."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="find rooted at / blocked",
                command="false && find / -type d -name phparkitect",
                dispatch_as_bash=True,
                description="Blocks find rooted at / (always recursive)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"head"],
                safety_notes=(
                    "'false &&' short-circuits so find never executes. See the previous "
                    "test's safety_notes for why this must not be wrapped in echo instead."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="scoped recursive grep allowed",
                command='false && grep -rl "needle" src',
                dispatch_as_bash=True,
                description="Allows a recursive scan scoped to a project subdirectory",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "The root is a literal project-relative path, not a shell expansion: "
                    "flaggable_content_channel_guard fails closed on an expanded root such "
                    "as the project-dir variable, so that shape would be denied by it in a "
                    "full-daemon run. The variable root stays covered by this handler's "
                    "unit tests. "
                    "'false &&' short-circuits so grep never executes even though this "
                    "case is allowed by this handler. Pattern is 'needle' (not a "
                    "class-name-shaped string) so this does not incidentally trip "
                    "lsp_enforcement's symbol-lookup heuristic in a live end-to-end run."
                ),
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
