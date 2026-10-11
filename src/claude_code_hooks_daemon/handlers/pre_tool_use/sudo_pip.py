"""Handler to block sudo pip install commands.

This handler prevents the use of sudo with pip install, which creates
system-wide package installations that can conflict with OS package managers
and break system tools.
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
from claude_code_hooks_daemon.utils.command_evasion import (
    OPTIONAL_PATH,
    strip_reserved_word_prefix,
)
from claude_code_hooks_daemon.utils.command_position import (
    command_position_code_segments,
    is_shell_command_option,
    segment_spans,
)
from claude_code_hooks_daemon.utils.heredoc_operators import scan_heredocs

# Full first-fire teaching content (Plan 00116): reuses the pre-migration
# handler's rich prose verbatim, minus the invocation-specific `COMMAND:`
# interpolation a static Rule.verbose cannot carry (Migration Pattern).
_SUDO_PIP_VERBOSE_CONTENT = (
    "System-wide pip installs using sudo can cause serious problems:\n"
    "  • Conflicts with your OS package manager (apt, dnf, pacman, etc.)\n"
    "  • Breaks OS tools that depend on specific Python package versions\n"
    "  • Creates permission and ownership issues\n"
    "  • Bypasses PEP 668 externally-managed environment protections\n\n"
    "SAFE alternatives:\n"
    "  1. Use a virtual environment (RECOMMENDED):\n"
    "     python -m venv myenv\n"
    "     source myenv/bin/activate\n"
    "     pip install <package>\n\n"
    "  2. Use --user flag for user-local install:\n"
    "     pip install --user <package>\n\n"
    "  3. Use your OS package manager:\n"
    "     sudo apt install python3-<package>  # Debian/Ubuntu\n"
    "     sudo dnf install python3-<package>  # Fedora/RHEL\n\n"
    "NEVER use sudo pip install as default behavior."
)

# `sudo` + any form of pip install.
#
# Two respellings defeated the original `\bsudo\s+(pip3?|...)` anchor, and both
# are the FIRST thing a real user types:
#   sudo -H pip install ...        - sudo takes its own options
#   sudo /usr/bin/pip install ...  - the binary named by path
# OPTIONAL_SUDO covers the former (and is shared with curl_pipe_shell, which
# had already learned this lesson in isolation); OPTIONAL_PATH covers the
# latter for both `pip` and the `python -m pip` spelling.
#
# Further respellings (batch S, still careless rather than hostile):
#   sudo -u root pip install       - an option that TAKES a value (-u/-g/-C/...)
#   doas pip install               - sudo's OpenBSD-lineage twin
#   sudo env [VAR=x] pip install   - env between the elevator and pip
#   sudo bash -c 'pip install x'   - a shell run as root
#   pip3.11 / python3.11 -m pip    - a versioned interpreter
#   sudo --user root / -p 'pw: '   - a long or quoted-value sudo option
#   sudo pip -q install            - a pip option before the subcommand
#   sudo sh -c "a; pip install"    - pip after an earlier statement: the view heads
#                                    every later segment of a sudo/doas shell's
#                                    `-c` body with `sudo`, so any quoting works
_SUDO_OPTION_VALUE = r"(?:'[^']*'|\"[^\"]*\"|[\w.-]+)"
_ELEVATOR = (
    r"\b(?:sudo|doas)"
    r"(?:\s+-[A-Za-z]*[ugCDhpRTU]\s+" + _SUDO_OPTION_VALUE + r"|"
    r"\s+--(?:user|group|prompt|chdir|host|role|type|chroot|close-from|other-user)\s+"
    + _SUDO_OPTION_VALUE
    + r"|\s+-\S+)*\s+"
)
_ELEVATED_WRAPPER = (
    r"(?:"
    r"env\s+(?:-\S+\s+)*"
    r"|" + OPTIONAL_PATH + r"(?:ba|da|z)?sh\s+(?:-\w*c\s+)['\"]?\s*(?:[^'\"]*?(?:;|&&|\|\|)\s*)?"
    r")?"
    r"(?:\w+=\S*\s+)*"
)
_SUDO_PIP_PATTERN = (
    _ELEVATOR
    + _ELEVATED_WRAPPER
    + OPTIONAL_PATH
    + r"(?:pip3?(?:\.\d+)?|python3?(?:\.\d+)?\s+-m\s+pip)\s+(?:-\S+\s+)*install\b"
)


# A sudo option that takes the next word as its value (`-u root`, `-iu root`).
_VALUE_OPTION_CLUSTER = re.compile(r"-[A-Za-z]*[ugCDhpRTU]")
_LONG_VALUE_OPTIONS = frozenset(
    f"--{name}"
    for name in (
        "user",
        "group",
        "prompt",
        "chdir",
        "host",
        "role",
        "type",
        "chroot",
        "close-from",
        "other-user",
    )
)
_LOGIN_SHELL_LONG_OPTIONS = frozenset({"--login", "--shell"})
_SHELL_BINARIES = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
# A shell option that takes the next word as its value (`bash -o pipefail`).
_SHELL_VALUE_OPTIONS = frozenset({"-o", "+o", "-O", "+O"})
_REDIRECT_WORD = re.compile(r"\d*[<>]")


def _shell_reads_stdin(options: list[str]) -> bool:
    """Whether a shell with these words after its name reads its script from stdin.

    `-c` takes the program from a string, and a script operand names a file to
    run (the heredoc is then only that file's stdin) -- unless `-s` is given.
    """
    stdin_script = False
    index = 0
    while index < len(options):
        word = options[index]
        if not word.startswith(("-", "+")):
            return stdin_script
        if word in _SHELL_VALUE_OPTIONS:
            index += 1
        elif not word.startswith("--"):
            if is_shell_command_option(word):
                return False
            stdin_script = stdin_script or "s" in word[1:]
        index += 1
    return True


def _feeds_elevated_shell(head: str) -> bool:
    """Whether ``head`` (the command text before a `<<`) runs a shell as root on stdin.

    `sudo -i` / `sudo -s` / `--login` / `--shell` (no command after the
    options) and `sudo bash` (`sh -s`, a path) read their script from the
    heredoc. Any other command just consumes the text as data.
    """
    words = [
        word for word in strip_reserved_word_prefix(head).split() if not _REDIRECT_WORD.match(word)
    ]
    if not words or words[0].rsplit("/", 1)[-1] not in ("sudo", "doas"):
        return False
    login_shell = False
    index = 1
    while index < len(words) and words[index].startswith("-") and words[index] != "--":
        option = words[index]
        index += 1
        if option.startswith("--"):
            login_shell = login_shell or option in _LOGIN_SHELL_LONG_OPTIONS
            if option in _LONG_VALUE_OPTIONS:
                index += 1
        else:
            login_shell = login_shell or any(flag in option[1:] for flag in "is")
            if _VALUE_OPTION_CLUSTER.fullmatch(option):
                index += 1
    if index >= len(words):
        return login_shell
    if words[index].rsplit("/", 1)[-1] not in _SHELL_BINARIES:
        return False
    return _shell_reads_stdin(words[index + 1 :])


def _elevated_heredoc_bodies(command: str) -> list[str]:
    """The bodies of the heredocs ``command`` feeds to an elevated shell.

    Heredocs come from the repo's quote-aware scanner, so a `<<` inside a
    quoted string (a commit message, a `python3 -c` program) opens nothing.
    """
    bodies: list[str] = []
    for heredoc in scan_heredocs(command).heredocs:
        spans = segment_spans(command[: heredoc.operator.start])
        if not spans:
            continue
        start, end = spans[-1]
        if _feeds_elevated_shell(command[start:end]):
            bodies.append(heredoc.body(command))
    return bodies


def _elevated_body_runs_pip(command: str) -> bool:
    """Whether a heredoc body run by an elevated shell installs with pip."""
    return any(
        re.search(
            _SUDO_PIP_PATTERN,
            f"sudo {strip_reserved_word_prefix(segment).lstrip('( ')}",
            re.IGNORECASE,
        )
        for body in _elevated_heredoc_bodies(command)
        for segment in command_position_code_segments(body)
    )


class SudoPipHandler(PreToolUseHandlerBase):
    """Block sudo pip install commands.

    System-wide pip installs using sudo can:
    - Conflict with OS package manager (apt, dnf, etc.)
    - Break OS tools that depend on Python packages
    - Create permission and ownership issues
    - Bypass externally-managed environment protections

    Priority: 10 (safety-critical)
    Terminal: True (blocks execution)
    """

    def __init__(self) -> None:
        """Initialize handler with safety-critical priority."""
        super().__init__(
            handler_id=HandlerID.SUDO_PIP,
            priority=Priority.SUDO_PIP,
            terminal=True,
            # Plan 00466 n24 security review, M3: can corrupt the system
            # Python installation -- structurally fail-closed, not just
            # BLOCKING.
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        self._rule = Rule(
            rule_id=RuleID.SUDO_PIP_INSTALL,
            blocked="`sudo pip install`",
            why="Conflicts with the OS package manager and can corrupt system Python",
            fix="Use a virtual environment or `pip install --user` instead",
            verbose=_SUDO_PIP_VERBOSE_CONTENT,
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if command contains sudo pip install.

        Matches:
        - sudo pip install
        - sudo pip3 install
        - sudo python -m pip install
        - sudo python3 -m pip install

        Case-insensitive matching.

        Args:
            hook_input: Hook input containing tool_name and tool_input

        Returns:
            True if command uses sudo pip install
        """
        # get_bash_command is the CANONICAL accessor: it returns None for
        # non-Bash tools and normalises shell line continuations, so a command
        # split across lines is matched in the same form as a one-line one.
        # Reading tool_input directly skipped that and reopened the hole.
        command = get_bash_command(hook_input)
        if not command:
            return False

        # Judged per COMMAND-POSITION segment (ledger N407): text that only
        # names `sudo pip install` in an echo, grep pattern, comment or message
        # is not an invocation.
        return any(
            re.search(_SUDO_PIP_PATTERN, segment, re.IGNORECASE)
            for segment in command_position_code_segments(command)
        ) or _elevated_body_runs_pip(command)

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

        if transcript_path and tracker.was_disclosed(transcript_path, RuleID.SUDO_PIP_INSTALL):
            message = self._formatter.terse(self._rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.SUDO_PIP_INSTALL)
            message = self._formatter.verbose(self._rule)

        return GatingResult(
            decision=Decision.DENY,
            reason=message,
            context=[],
            guidance=None,
        )

    def get_claude_md(self) -> str | None:
        return (
            "## sudo_pip — sudo pip install is blocked\n\n"
            "`sudo pip install` (and the `sudo pip3` / `sudo python -m pip` / "
            "`sudo python3 -m pip` variants) is blocked. Installing as root corrupts the "
            "system Python managed by the OS package manager and creates "
            "permission/ownership issues that are painful to recover from.\n\n"
            "**Use a virtualenv or `--user` install instead**:\n\n"
            "```\n"
            f"python3 -m venv {ProjectPath.SCRATCH_DIR}/venv && "
            f"{ProjectPath.SCRATCH_DIR}/venv/bin/pip install <package>\n"
            "# or\n"
            "pip install --user <package>\n"
            "```\n\n"
            "Even in a container running as root, `sudo` adds nothing — drop it and use "
            "a venv."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for sudo pip handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="sudo pip install",
                command="bash -n -c 'sudo pip install nonexistent-pkg-zz-safe-test'",
                dispatch_as_bash=True,
                description="Blocks sudo pip install (system-wide corruption risk)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"sudo pip install",
                    r"OS package manager",
                    r"virtual environment",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="sudo python3 -m pip install",
                command="bash -n -c 'sudo python3 -m pip install nonexistent-pkg-zz-safe-test'",
                dispatch_as_bash=True,
                description="Blocks sudo python3 -m pip install",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"sudo pip",
                    r"Conflicts.*OS",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
