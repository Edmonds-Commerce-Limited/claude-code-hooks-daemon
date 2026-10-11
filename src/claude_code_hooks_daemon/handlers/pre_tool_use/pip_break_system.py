"""Handler to block pip install --break-system-packages flag.

This handler prevents the use of pip's --break-system-packages flag, which
disables the system package manager conflict detection and can corrupt
Python installations managed by the OS package manager.
"""

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.command_evasion import strip_reserved_word_prefix
from claude_code_hooks_daemon.utils.command_position import (
    command_position_code_segments_with_separators,
)
from claude_code_hooks_daemon.utils.heredoc_operators import substitution_end

# Full first-fire teaching content (Plan 00116): reuses the pre-migration
# handler's rich prose verbatim, minus the invocation-specific `COMMAND:`
# interpolation a static Rule.verbose cannot carry (Migration Pattern).
_PIP_BREAK_SYSTEM_VERBOSE_CONTENT = (
    "The --break-system-packages flag disables pip's protection against\n"
    "conflicting with your system package manager (apt, dnf, pacman, etc.).\n\n"
    "Using this flag can:\n"
    "  • Corrupt your system Python installation\n"
    "  • Break OS tools that depend on Python\n"
    "  • Cause conflicts with system package manager\n"
    "  • Create difficult-to-debug environment issues\n\n"
    "SAFE alternatives:\n"
    "  1. Use a virtual environment (RECOMMENDED):\n"
    "     python -m venv myenv\n"
    "     source myenv/bin/activate\n"
    "     pip install <package>\n\n"
    "  2. Use --user flag for user-local install:\n"
    "     pip install --user <package>\n\n"
    "  3. If in a container/isolated environment, ask the human user\n"
    "     whether it's safe to proceed (they can override if truly needed)\n\n"
    "NEVER use --break-system-packages as default behavior."
)

# Any form of pip install with --break-system-packages in ONE command segment:
# pip/pip3/python -m pip/python3 -m pip (also behind a path or `uv`) + install
# + the flag.
#
# The flag may also sit BEFORE the subcommand (`pip --break-system-packages
# install x`), and the interpreter may be versioned (`pip3.11`,
# `python3.11 -m pip`), so both are asserted as lookaheads after the binary.
_PIP_BREAK_SYSTEM_FLAG_PATTERN = re.compile(
    r"\b(?:pip3?(?:\.\d+)?|python3?(?:\.\d+)?\s+-m\s+pip)\s+"
    r"(?=.*\binstall\b)(?=.*--break-system-packages)",
    re.IGNORECASE,
)

# The same switch set through pip's environment. Only a REAL assignment counts
# (a leading `VAR=value` prefix, after `env` and its options, or after
# `export` / `declare -x`), never the text `PIP_BREAK_SYSTEM_PACKAGES=1` as an
# argument of grep, find or docker. It is a finding only when it GOVERNS a pip
# install: a prefix on that same command, or an `export` earlier in the command
# line followed by one. A falsy value (0, false, no, off), quoted or not, or an
# empty one switches nothing on.
_ENV_VAR_NAME = "PIP_BREAK_SYSTEM_PACKAGES"
_FALSY_VALUES = frozenset({"", "0", "false", "no", "off"})
_ASSIGNMENT = re.compile(r"(\w+)=('[^']*'|\"[^\"]*\"|\S*)\s*")
_EXPORT_HEAD = re.compile(r"(?:export|(?:declare|typeset)\s+-\w*x\w*)\s+")
_ENV_HEAD = re.compile(r"env\s+(?:-\S+\s+)*")
# The path prefix is tried only where a whitespace-free run STARTS: the leftmost
# match of an unanchored `(?:\S*/)?` always begins at a run start anyway, and
# trying it from every offset inside one long run (`$($($(...`) is quadratic.
_SHELL_C_HEAD = re.compile(r"(?:(?<!\S)\S*/)?(?:ba|da|z)?sh\s+-\w*c\s+['\"]?\s*")
_PIPE_SEPARATORS = frozenset({"|", "|&"})
# A `&` backgrounds the command before it into a subshell, like a pipe stage.
_BACKGROUND_SEPARATOR = "&"
_TRAILING_REDIRECT = re.compile(r"\s*(?:\d*|&)(?:>>?|<)&?\s*[^\s()<>]+\s*$")
# `unset VAR` / `export -n VAR` take the variable out of the environment again.
_UNSET_HEAD = re.compile(rf"unset\s+(?:-\S+\s+)*(?:\S+\s+)*?{_ENV_VAR_NAME}\b")
_EXPORT_UNMARK_HEAD = re.compile(rf"export\s+-\w*n\w*\s+(?:\S+\s+)*?{_ENV_VAR_NAME}\b")
# `xargs` options that take a separate value (`-a FILE`, `-I X`, `-d D`, `-E S`,
# `-s N`, `-L N`, `-n N`, `-P N`); any other option is one word (`-r`, `-0`,
# `--arg-file=FILE`). `command` takes no option that matters.
_XARGS_VALUE_OPTION = r"-[aIdEsLnP]\s+\S+\s+"
_PIP_INSTALL_HEAD = re.compile(
    r"(?:(?:sudo|doas)\s+(?:-\S+\s+)*|uv\s+|nohup\s+|time\s+|command\s+(?:-\S+\s+)*"
    r"|xargs\s+(?:" + _XARGS_VALUE_OPTION + r"|-\S+\s+)*)*(?:\S*/)?"
    r"(?:pip3?(?:\.\d+)?|python3?(?:\.\d+)?\s+-m\s+pip)\s+(?:-\S+\s+)*install\b",
    re.IGNORECASE,
)


def _is_truthy(raw: str) -> bool:
    """Whether an env value (quotes allowed) switches the variable on."""
    return raw.strip("'\"").strip().lower() not in _FALSY_VALUES


def _leading_assignment(segment: str) -> tuple[bool, str | None, str]:
    """Read the assignments heading a command segment.

    Returns (is_export, raw value of the pip variable or None, the rest of the
    segment after the assignments).
    """
    rest = _SHELL_C_HEAD.sub("", strip_reserved_word_prefix(segment), count=1)
    is_export = False
    export_head = _EXPORT_HEAD.match(rest)
    env_head = _ENV_HEAD.match(rest)
    if export_head:
        is_export = True
        rest = rest[export_head.end() :]
    elif env_head:
        rest = rest[env_head.end() :]
    value: str | None = None
    while (assignment := _ASSIGNMENT.match(rest)) is not None and assignment.end() > 0:
        if assignment.group(1) == _ENV_VAR_NAME:
            value = assignment.group(2)
        rest = rest[assignment.end() :]
    return is_export, value, rest


def _is_pipe(separator: str) -> bool:
    """Whether ``separator`` joins two stages of one pipeline (`|` or `|&`)."""
    return separator.strip() in _PIPE_SEPARATORS


def _open_groups(text: str, stack: list[bool], exported: bool) -> str:
    """Strip the `(` heading ``text``, saving ``exported`` once per group opened."""
    while text.startswith("("):
        stack.append(exported)
        text = text[1:].lstrip()
    return text


def _without_trailing_redirects(text: str) -> str:
    """``text`` without the redirects ending it (`2>/dev/null`, `> log`, `&>f`, `2>&1`)."""
    while (match := _TRAILING_REDIRECT.search(text)) is not None:
        text = text[: match.start()]
    return text


def _strip_closes(text: str, open_groups: int) -> tuple[str, int]:
    """Strip up to ``open_groups`` trailing `)` from ``text``; return it and how many.

    Redirects after the paren (`(...) 2>/dev/null`) do not keep the group open,
    but are left on ``text`` when no group closes there.
    """
    closes = 0
    candidate = _without_trailing_redirects(text.rstrip()).rstrip()
    while closes < open_groups and candidate.endswith(")"):
        candidate = candidate[:-1].rstrip()
        closes += 1
    return (candidate, closes) if closes else (text.rstrip(), 0)


def _substitution_bodies(text: str) -> list[str]:
    """The bodies of the `$( ... )` and backtick substitutions that run in ``text``.

    Single-quoted text is literal and skipped; a double-quoted span still
    expands. A body keeps any substitution nested in it (read again by the caller).
    """
    bodies: list[str] = []
    in_single = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "'":
            in_single = not in_single
        elif not in_single and text.startswith("$(", index):
            # Bash's grammar finds the close: a quoted `)` does not end it.
            close = substitution_end(text, index + 1)
            bodies.append(text[index + 2 : len(text) if close is None else close - 1])
            index = len(text) if close is None else close
            continue
        elif not in_single and char == "`":
            end = text.find("`", index + 1)
            end = len(text) if end == -1 else end
            bodies.append(text[index + 1 : end])
            index = end
        index += 1
    return bodies


def _env_var_governs_pip_install(items: list[tuple[str, str]], exported: bool = False) -> bool:
    """Whether a truthy PIP_BREAK_SYSTEM_PACKAGES governs a pip install.

    ``items`` are ``(separator before, segment)`` pairs. An export is undone by
    ``unset`` / ``export -n``, is dropped when the `( ... )` group it was made
    in closes, and is neither made nor undone by a stage of a pipeline (each
    stage is a subshell) -- though a stage still inherits what was exported
    before the pipeline. A command substitution is a subshell that inherits the
    export too, so ``exported`` starts True for the body of one.
    """
    groups: list[bool] = []
    for index, (separator, segment) in enumerate(items):
        next_separator = items[index + 1][0] if index + 1 < len(items) else ""
        in_pipeline = (
            _is_pipe(separator)
            or _is_pipe(next_separator)
            or next_separator.strip() == _BACKGROUND_SEPARATOR
        )
        text = _open_groups(strip_reserved_word_prefix(segment).strip(), groups, exported)
        text, closes = _strip_closes(text, len(groups))
        is_export, value, rest = _leading_assignment(text)
        stripped = strip_reserved_word_prefix(text)
        if exported and any(
            _env_var_governs_pip_install(
                command_position_code_segments_with_separators(body), exported=True
            )
            for body in _substitution_bodies(text)
        ):
            return True
        if _UNSET_HEAD.match(stripped) or _EXPORT_UNMARK_HEAD.match(stripped):
            if not in_pipeline:
                exported = False
        elif is_export:
            if value is not None and not in_pipeline:
                exported = _is_truthy(value)
        else:
            effective = _is_truthy(value) if value is not None else exported
            if effective and _PIP_INSTALL_HEAD.match(rest):
                return True
        for _ in range(closes):
            exported = groups.pop()
    return False


class PipBreakSystemHandler(PreToolUseHandlerBase):
    """Block pip install --break-system-packages commands.

    This flag was introduced in pip 22.1 to bypass PEP 668 externally-managed
    environment protections. Using it can:
    - Conflict with system package manager (apt, dnf, etc.)
    - Break OS tools that depend on Python
    - Corrupt system Python installation
    - Cause difficult-to-debug issues

    Priority: 10 (safety-critical)
    Terminal: True (blocks execution)
    """

    def __init__(self) -> None:
        """Initialize handler with safety-critical priority."""
        super().__init__(
            handler_id=HandlerID.PIP_BREAK_SYSTEM,
            priority=Priority.PIP_BREAK_SYSTEM,
            terminal=True,
            # Plan 00466 n24 security review, M3: bypasses PEP 668 and can
            # corrupt the system Python installation -- structurally
            # fail-closed, not just BLOCKING.
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        self._rule = Rule(
            rule_id=RuleID.PIP_BREAK_SYSTEM_PACKAGES,
            blocked="`pip install --break-system-packages`",
            why="Bypasses PEP 668 protection and can corrupt the system Python installation",
            fix="Use a virtual environment or `pip install --user` instead",
            verbose=_PIP_BREAK_SYSTEM_VERBOSE_CONTENT,
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if command contains pip install --break-system-packages.

        Matches:
        - pip install --break-system-packages
        - pip3 install --break-system-packages
        - python -m pip install --break-system-packages
        - python3 -m pip install --break-system-packages

        Case-insensitive matching.

        Args:
            hook_input: Hook input containing tool_name and tool_input

        Returns:
            True if command uses --break-system-packages flag
        """
        # Canonical accessor: non-Bash returns None, and shell line
        # continuations are normalised so a command split across lines is
        # matched in the same form as a one-line one.
        command = get_bash_command(hook_input)
        if not command:
            return False

        # Judged per COMMAND-POSITION segment (ledger N407): the pattern's `.*`
        # used to cross `&&`, `;`, `#` and quotes, so an echo, a comment, a
        # grep pattern or a message that only NAMED the flag was denied.
        items = command_position_code_segments_with_separators(command)
        return any(
            _PIP_BREAK_SYSTEM_FLAG_PATTERN.search(segment) for _, segment in items
        ) or _env_var_governs_pip_install(items)

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's blocking behaviour."""
        return [self._rule]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Block command with a verbose-first/terse-after explanation.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G): the first fire for a
        given agent is verbose (full teaching content); subsequent fires for
        the SAME agent are terse. An event with no transcript_path fails
        toward verbose every time (unknown disclosure state -> more info)
        since there is no key to track against.

        Args:
            hook_input: Hook input containing the dangerous command

        Returns:
            GatingResult with deny decision and explanation
        """
        # Safety check: if command doesn't match, allow
        if not self.matches(hook_input):
            return GatingResult(decision=Decision.ALLOW)

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(
            transcript_path, RuleID.PIP_BREAK_SYSTEM_PACKAGES
        ):
            message = self._formatter.terse(self._rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.PIP_BREAK_SYSTEM_PACKAGES)
            message = self._formatter.verbose(self._rule)

        return GatingResult(
            decision=Decision.DENY,
            reason=message,
            context=[],
            guidance=None,
        )

    def get_claude_md(self) -> str | None:
        return (
            "## pip_break_system — --break-system-packages is blocked\n\n"
            "`pip install --break-system-packages` (and the `pip3` / `python -m pip` / "
            "`python3 -m pip` variants) is blocked. The flag bypasses PEP 668 system-package "
            "protection and corrupts the system Python environment in containers and on "
            "modern Linux distros.\n\n"
            "**Use a virtualenv or `--user` install instead**:\n\n"
            "```\n"
            f"python3 -m venv {ProjectPath.SCRATCH_DIR}/venv && "
            f"{ProjectPath.SCRATCH_DIR}/venv/bin/pip install <package>\n"
            "# or\n"
            "pip install --user <package>\n"
            "```\n\n"
            "If a tool's installer insists on `--break-system-packages` (some quick-start "
            "scripts do), download it first, inspect, and run it inside a venv — do not "
            "shortcut by adding the flag."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for pip break system handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="pip install --break-system-packages",
                command=(
                    "bash -n -c 'pip install --break-system-packages nonexistent-pkg-zz-safe-test'"
                ),
                dispatch_as_bash=True,
                description="Blocks pip --break-system-packages flag (system corruption risk)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"--break-system-packages",
                    r"system Python installation",
                    r"virtual environment",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="python3 -m pip install --break-system-packages",
                command=(
                    "bash -n -c 'python3 -m pip install --break-system-packages "
                    "nonexistent-pkg-zz-safe-test'"
                ),
                dispatch_as_bash=True,
                description="Blocks python3 -m pip with --break-system-packages",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"--break-system-packages",
                    r"Corrupt.*system Python",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
