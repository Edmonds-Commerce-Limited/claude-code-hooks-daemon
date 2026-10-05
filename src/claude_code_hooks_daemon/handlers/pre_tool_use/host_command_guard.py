"""HostCommandGuardHandler - four commands whose reach goes past the project.

Plan 00483 Task 2.2, owner ruling A6 (``OWNER-RULINGS-261005.md``). Each row was a
`UNCOVERED-open` entry in ``scripts/qa/dangerous-invocation-corpus.yaml``:

=========================================  ============================================
Command                                    Verdict
=========================================  ============================================
``docker run -v /:/host`` (host root)      Block, with the alternative named
``gh auth token``                          Block: prints the token into the transcript
``pip install --index-url <non-PyPI>``     Human only: stop and ask the human
``crontab -r``                             Human only: stop and ask the human
=========================================  ============================================

``git push --delete`` is the fifth human-only row of the ruling; it lives in
``destructive_git`` beside the other ``git push`` rules. ``git tag -d``,
``git reset --keep``, ``truncate -s 0`` and ``rm -rf`` are ALLOWED by the ruling
and are deliberately not touched here.

**Judged on a positive finding (owner ruling A1).** A command is read with the
shared simple-command reader, so only a program that IS the command is judged:
``echo 'crontab -r'``, a ``git commit -m`` message and a ``grep`` pattern are
data. A value the reading cannot resolve (``--index-url $INDEX``) is allowed,
not denied: deliberate evasion is out of scope under the threat model.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Final
from urllib.parse import urlsplit

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.command_position import DATA_HEADS
from claude_code_hooks_daemon.utils.git_commit_parsing import SimpleCommand, simple_commands
from claude_code_hooks_daemon.utils.shell_segmentation import command_word, peel_command_wrappers

_ASSIGNMENT_WORD: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")

#: What a pip index must be to count as PyPI: HTTPS and one of these hosts exactly.
#: ``test.pypi.org`` is a different index (a sandbox anyone can upload to), so it is
#: not PyPI; ``pypi.org.example`` is a different host, so a prefix never counts.
PYPI_HOSTS: Final[frozenset[str]] = frozenset({"pypi.org", "files.pythonhosted.org"})
_PYPI_SCHEME: Final[str] = "https"

#: Characters that mean the shell computes the value, so this reading cannot say what it is.
_UNRESOLVED_VALUE: Final[tuple[str, ...]] = ("$", "`")

_DOCKER: Final[str] = "docker"
_DOCKER_CONTAINER: Final[str] = "container"
_DOCKER_CREATES: Final[frozenset[str]] = frozenset({"run", "create"})
#: `docker` global options that take a value word, so the value is not the subcommand.
_DOCKER_VALUE_OPTIONS: Final[frozenset[str]] = frozenset(
    {"--context", "-c", "-H", "--host", "--config", "-l", "--log-level"}
)
_VOLUME_OPTIONS: Final[frozenset[str]] = frozenset({"-v", "--volume"})
_MOUNT_OPTION: Final[str] = "--mount"
_MOUNT_SOURCE_KEYS: Final[frozenset[str]] = frozenset({"source", "src"})

_GH: Final[str] = "gh"
_GH_AUTH_TOKEN: Final[tuple[str, str]] = ("auth", "token")

_PIP_PROGRAMS: Final[frozenset[str]] = frozenset({"pip", "pip3"})
_PYTHON_PREFIX: Final[str] = "python"
_PIP_INSTALL: Final[str] = "install"
_PIP_INDEX_OPTIONS: Final[frozenset[str]] = frozenset({"--index-url", "--extra-index-url", "-i"})
_PIP_SHORT_INDEX: Final[str] = "-i"

_CRONTAB: Final[str] = "crontab"
_CRONTAB_REMOVE_LETTER: Final[str] = "r"

_LONG_PREFIX: Final[str] = "--"
_SHORT_PREFIX: Final[str] = "-"
_PIPE: Final[str] = "|"
_ENDS_IN_SUBSTITUTION: Final[str] = "$"

_ASK_THE_HUMAN: Final[str] = (
    "Do not run it, and do not look for another spelling of it. Stop and ask the human to "
    "run it themselves: tell them exactly what you want run and why. There is no escape hatch."
)

_RULES: Final[dict[str, Rule]] = {
    RuleID.DOCKER_ROOT_MOUNT: Rule(
        rule_id=RuleID.DOCKER_ROOT_MOUNT,
        blocked="`docker run -v /:/host …` (the host root mounted into a container)",
        why="The container then reads and writes the whole host, past every path-scoped guard",
        fix='Mount the specific directory the container needs, e.g. `-v "$PWD":/app`',
        verbose=(
            "Mounting the host root (`-v /:/host`, `--volume /:…`, `--mount "
            "type=bind,source=/,…`) gives the container the whole host filesystem. Every "
            "path-scoped guard in this daemon stops at the project root, so none of them "
            "sees what happens through that mount.\n\n"
            'Mount only the specific directory the container needs: `-v "$PWD":/app` '
            "for the project, or `-v /tmp/x:/x` for a scratch directory. If a container "
            "genuinely needs the host root, the human has to run that command themselves."
        ),
    ),
    RuleID.GH_AUTH_TOKEN: Rule(
        rule_id=RuleID.GH_AUTH_TOKEN,
        blocked="`gh auth token`",
        why="Prints the GitHub OAuth token into the transcript, where it is stored and replayed",
        fix="Use `gh auth status` to check the login; let `gh` itself authenticate its calls",
        verbose=(
            "`gh auth token` prints the stored OAuth token. Run as a tool call, the token "
            "lands in the session transcript, which is saved and can be replayed, and the "
            "token grants whatever the account can do.\n\n"
            "You never need the value: `gh` authenticates its own commands from the "
            "credential store. To check the login, run `gh auth status`. A tool that "
            "genuinely needs the token takes it from `gh auth token` inside a pipe or a "
            "`$(...)` the human sets up; do not print it yourself."
        ),
    ),
    RuleID.PIP_NON_PYPI_INDEX: Rule(
        rule_id=RuleID.PIP_NON_PYPI_INDEX,
        blocked="`pip install --index-url <url>` / `-i <url>` / `--extra-index-url <url>` "
        "naming a non-PyPI index",
        why="The index decides which code gets installed and run, and this one is not PyPI",
        fix="Install from PyPI, or stop and ask the human to run it themselves",
        verbose=(
            "`pip install` runs code from whatever index it is pointed at: a package's "
            "build script executes at install time. `--index-url` and `-i` replace PyPI "
            "with another server and `--extra-index-url` adds one, so the host named there "
            "chooses what runs on this machine.\n\n"
            "An index counts as PyPI only when it is `https://pypi.org/...` or "
            "`https://files.pythonhosted.org/...`; `test.pypi.org`, plain `http://`, a "
            "`file://` path and every other host do not. A value held in a variable "
            "(`$INDEX`) is not judged.\n\n" + _ASK_THE_HUMAN
        ),
    ),
    RuleID.CRONTAB_REMOVE: Rule(
        rule_id=RuleID.CRONTAB_REMOVE,
        blocked="`crontab -r`",
        why="Deletes every scheduled job with no confirmation and no undo",
        fix="`crontab -l` to inspect, `crontab -e` to edit; stop and ask the human to run `-r`",
        verbose=(
            "`crontab -r` removes the whole crontab at once, with no confirmation and no "
            "backup. This project can depend on declared crons, and a missing one is "
            "discovered only when the work it ran stops.\n\n"
            "`crontab -l` lists and `crontab -e` edits, and neither is blocked. "
            "Removing one job means installing the edited list, not wiping it.\n\n" + _ASK_THE_HUMAN
        ),
    ),
}


def _program(words: Sequence[str]) -> tuple[str, list[str]] | None:
    """The program a simple command runs and its arguments, past assignments and wrappers.

    ``FOO=1 sudo -H pip install x`` runs ``pip`` with ``["install", "x"]``. None when
    nothing is left to run (a bare assignment).
    """
    rest = list(words)
    while rest and _ASSIGNMENT_WORD.match(rest[0]):
        rest = rest[1:]
    _wrappers, start = peel_command_wrappers(rest)
    rest = rest[start:]
    if not rest:
        return None
    return command_word(rest[0]), rest[1:]


def _option_values(arguments: Sequence[str], names: frozenset[str]) -> list[str]:
    """Every value given to an option in ``names``, in any of its spellings.

    ``--name value``, ``--name=value`` and, for a one-letter option, ``-Nvalue``.
    """
    values: list[str] = []
    for index, argument in enumerate(arguments):
        if argument in names:
            if index + 1 < len(arguments):
                values.append(arguments[index + 1])
            continue
        if argument.startswith(_LONG_PREFIX):
            name, equals, value = argument.partition("=")
            if equals and name in names:
                values.append(value)
        elif argument.startswith(_SHORT_PREFIX):
            letter = argument[:2]
            if len(argument) > 2 and letter in names:
                values.append(argument[2:])
    return values


def _docker_creation_arguments(arguments: Sequence[str]) -> list[str] | None:
    """The arguments after ``docker [container] run|create``, or None for any other command."""
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument.startswith(_SHORT_PREFIX):
            index += 2 if argument in _DOCKER_VALUE_OPTIONS else 1
            continue
        if argument == _DOCKER_CONTAINER:
            index += 1
            continue
        if argument in _DOCKER_CREATES:
            return list(arguments[index + 1 :])
        return None
    return None


def _is_host_root(source: str) -> bool:
    """True for the filesystem root itself: ``/`` or ``//``, never ``/tmp`` or ``/x/``."""
    return bool(source) and set(source) == {"/"}


def _volume_mounts_root(spec: str) -> bool:
    """``-v`` spec ``<source>:<target>[:opts]`` whose host source is the root."""
    source, colon, _target = spec.partition(":")
    return bool(colon) and _is_host_root(source)


def _mount_mounts_root(spec: str) -> bool:
    """``--mount`` spec ``type=bind,source=/,target=…`` whose source is the root."""
    for field in spec.split(","):
        key, equals, value = field.partition("=")
        if equals and key in _MOUNT_SOURCE_KEYS and _is_host_root(value):
            return True
    return False


def _docker_root_mount(arguments: Sequence[str]) -> bool:
    options = _docker_creation_arguments(arguments)
    if options is None:
        return False
    volumes = _option_values(options, _VOLUME_OPTIONS)
    mounts = _option_values(options, frozenset({_MOUNT_OPTION}))
    return any(_volume_mounts_root(spec) for spec in volumes) or any(
        _mount_mounts_root(spec) for spec in mounts
    )


def _is_pypi(url: str) -> bool:
    """Whether ``url`` is PyPI, or a value this reading cannot judge (treated as PyPI)."""
    if not url or any(char in url for char in _UNRESOLVED_VALUE):
        return True
    parts = urlsplit(url)
    return parts.scheme == _PYPI_SCHEME and parts.hostname in PYPI_HOSTS


def _pip_arguments(program: str, arguments: Sequence[str]) -> list[str] | None:
    """The arguments to ``pip`` for ``pip``, ``pip3`` or ``python -m pip``, else None."""
    if program in _PIP_PROGRAMS:
        return list(arguments)
    if program.startswith(_PYTHON_PREFIX) and list(arguments[:2]) == ["-m", "pip"]:
        return list(arguments[2:])
    return None


def _pip_non_pypi_index(program: str, arguments: Sequence[str]) -> bool:
    pip_arguments = _pip_arguments(program, arguments)
    if pip_arguments is None:
        return False
    subcommand = next((a for a in pip_arguments if not a.startswith(_SHORT_PREFIX)), None)
    if subcommand != _PIP_INSTALL:
        return False
    return any(not _is_pypi(url) for url in _option_values(pip_arguments, _PIP_INDEX_OPTIONS))


def _crontab_remove(arguments: Sequence[str]) -> bool:
    """``crontab -r``, alone or in a cluster (``-ri``)."""
    return any(
        argument.startswith(_SHORT_PREFIX)
        and not argument.startswith(_LONG_PREFIX)
        and _CRONTAB_REMOVE_LETTER in argument[1:]
        for argument in arguments
    )


def _token_is_consumed(steps: Sequence[SimpleCommand], index: int) -> bool:
    """Whether the ``gh auth token`` at ``steps[index]`` feeds another command.

    Piped on (``gh auth token | docker login --password-stdin``) or substituted into
    one (``TOKEN=$(gh auth token)``) the value reaches a consumer, not the transcript.
    A substitution inside ``echo``/``printf`` prints it, so that is still a finding.
    """
    if index + 1 < len(steps) and steps[index + 1].operator == _PIPE:
        return True
    if index == 0 or steps[index].operator:
        return False
    before = steps[index - 1].words
    if not before or not before[-1].endswith(_ENDS_IN_SUBSTITUTION):
        return False
    owner = _program(before)
    return owner is None or owner[0] not in DATA_HEADS


def _check_step(program: str, arguments: list[str]) -> str | None:
    """The rule one program with its arguments breaks, ignoring the gh pipeline context."""
    if program == _DOCKER and _docker_root_mount(arguments):
        return RuleID.DOCKER_ROOT_MOUNT
    if _pip_non_pypi_index(program, arguments):
        return RuleID.PIP_NON_PYPI_INDEX
    if program == _CRONTAB and _crontab_remove(arguments):
        return RuleID.CRONTAB_REMOVE
    return None


def _findings(command: str) -> list[str]:
    """Every rule id ``command`` breaks, in command order."""
    steps = simple_commands(command)
    found: list[str] = []
    for index, step in enumerate(steps):
        reading = _program(step.words)
        if reading is None:
            continue
        program, arguments = reading
        rule_id = _check_step(program, arguments)
        if (
            rule_id is None
            and program == _GH
            and tuple(arguments[:2]) == _GH_AUTH_TOKEN
            and not _token_is_consumed(steps, index)
        ):
            rule_id = RuleID.GH_AUTH_TOKEN
        if rule_id is not None:
            found.append(rule_id)
    return found


class HostCommandGuardHandler(PreToolUseHandlerBase):
    """Deny the four commands of owner ruling A6 that reach past the project."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.HOST_COMMAND_GUARD,
            priority=Priority.HOST_COMMAND_GUARD,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when a command in command position breaks one of the four rules."""
        command = get_bash_command(hook_input)
        if not command:
            return False
        return bool(_findings(command))

    def get_rules(self) -> list[Rule]:
        """The four rules backing this handler's denials."""
        return list(_RULES.values())

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny with the verbose text on first fire and the terse reminder after.

        Disclosure is per (transcript_path, rule_id) through the shared tracker, like
        every other rule-backed handler (Plan 00116, Decision G).
        """
        command = get_bash_command(hook_input)
        findings = _findings(command) if command else []
        if not findings:
            return GatingResult(decision=Decision.ALLOW)
        rule = _RULES[findings[0]]
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        if transcript_path and tracker.was_disclosed(transcript_path, rule.rule_id):
            message = self._formatter.terse(rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, rule.rule_id)
            message = self._formatter.verbose(rule)
        return GatingResult(decision=Decision.DENY, reason=message)

    def get_claude_md(self) -> str | None:
        return (
            "## host_command_guard — commands whose reach goes past the project\n\n"
            "Four commands are denied when they are the command itself (a prose mention, "
            "a `git commit -m` message or an `echo`/`grep` argument is not):\n\n"
            "| Rule | Command | What to do |\n"
            "|------|---------|------------|\n"
            f"| {RuleID.DOCKER_ROOT_MOUNT} | `docker run -v /:/host …` (also `--volume`, "
            "`--mount type=bind,source=/,…`, `docker create`) | Mount only the directory "
            'needed: `-v "$PWD":/app` |\n'
            f"| {RuleID.GH_AUTH_TOKEN} | `gh auth token` | Prints the token into the "
            "transcript. Use `gh auth status`; a pipe or `$(...)` that hands it to another "
            "command is allowed |\n"
            f"| {RuleID.PIP_NON_PYPI_INDEX} | `pip install --index-url <url>` / `-i` / "
            "`--extra-index-url` naming a non-PyPI index | HUMAN ONLY: stop and ask the "
            "human to run it |\n"
            f"| {RuleID.CRONTAB_REMOVE} | `crontab -r` | HUMAN ONLY: stop and ask the "
            "human to run it. `crontab -l` and `-e` are allowed |\n\n"
            "**What counts as PyPI**: `https://pypi.org/...` and "
            "`https://files.pythonhosted.org/...` only. `test.pypi.org`, plain `http://`, "
            "`file://` and any other host are not, and a value held in a variable is not "
            "judged. `pip install -r requirements.txt` is unaffected.\n\n"
            "The human-only rows have no escape hatch: do not look for another spelling, "
            "tell the human what you want run and why.\n\n"
            "Not blocked, by owner ruling: `git tag -d`, `git reset --keep`, "
            "`truncate -s 0`, `rm -rf`. Deleting a ref on the REMOTE (`git push --delete`) "
            "is human-only under `destructive_git`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests: one deny per rule, and the near-miss allows."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        def case(
            title: str,
            command: str,
            description: str,
            decision: Decision,
            patterns: list[str],
        ) -> AcceptanceTest:
            return AcceptanceTest(
                title=title,
                command=f"bash -n -c '{command}'",
                dispatch_as_bash=True,
                description=description,
                expected_decision=decision,
                expected_message_patterns=patterns,
                safety_notes="bash -n -c only parses the command, never executes it",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            )

        return [
            case(
                "docker run with the host root mounted",
                "docker run -v /:/host NONEXISTENT_SAFE_TEST_IMAGE",
                "Blocks a container with the host root mounted; names the alternative",
                Decision.DENY,
                [r"host root", r"specific directory"],
            ),
            case(
                "docker run with a project directory mounted is allowed",
                "docker run -v /tmp/x:/x NONEXISTENT_SAFE_TEST_IMAGE",
                "An ordinary bind mount is not the host root",
                Decision.ALLOW,
                [],
            ),
            case(
                "gh auth token",
                "gh auth token",
                "Blocks printing the GitHub token into the transcript",
                Decision.DENY,
                [r"transcript", r"gh auth status"],
            ),
            case(
                "gh auth status is allowed",
                "gh auth status",
                "Checking the login prints no token",
                Decision.ALLOW,
                [],
            ),
            case(
                "pip install from a non-PyPI index (human only)",
                "pip install --index-url http://example.invalid/simple NONEXISTENT_SAFE_PKG",
                "Blocks a non-PyPI index; the denial says to ask the human",
                Decision.DENY,
                [r"PyPI", r"ask the human"],
            ),
            case(
                "pip install from PyPI by URL is allowed",
                "pip install --index-url https://pypi.org/simple NONEXISTENT_SAFE_PKG",
                "PyPI itself is the default index and stays allowed when named",
                Decision.ALLOW,
                [],
            ),
            case(
                "crontab -r (human only)",
                "crontab -r",
                "Blocks wiping the crontab; the denial says to ask the human",
                Decision.DENY,
                [r"no confirmation", r"ask the human"],
            ),
            case(
                "crontab -l is allowed",
                "crontab -l",
                "Listing the crontab changes nothing",
                Decision.ALLOW,
                [],
            ),
        ]
