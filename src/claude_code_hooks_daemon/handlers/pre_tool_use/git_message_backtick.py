"""GitMessageBacktickHandler - backticks in a double-quoted git message.

Bash performs command substitution inside DOUBLE quotes. A backticked span
in ``git commit -m "..."`` is therefore EXECUTED, and its stdout replaces the
text in the message. Inside SINGLE quotes nothing is substituted, so the same
backticks are literal and safe.

That fact is shared, not local to this handler: ``pipe_blocker`` independently
assumed the OPPOSITE -- that any message value is inert prose -- and so let a
real pipe through inside ``git commit -m "$(pytest ... | tail -1)"`` (Plan
00222). It now lives once, in
``utils.shell_segmentation.value_can_substitute``. A handler that needs to
know whether an argument can execute must ask there rather than re-deriving
it, which is how two handlers came to disagree about the shell.

This handler keeps its own narrower scan because it answers a different
question: not "can this execute?" but "is a BACKTICK the thing executing?",
since the remedy it offers is about corruption of the message text.

This is not theoretical (Plan 00219). Commit cc7dddc0 in this repository has
a body reading "pipe_blocker now allows , so the force-delete form" where a
backticked command used to be: bash ran it, it wrote to stderr and nothing to
stdout, and the phrase was deleted from the message. The commit SUCCEEDED, so
nothing signalled the loss -- and the stray `fatal:` on the terminal read as
git rejecting the commit rather than as bash running a command nobody asked
for.

Scope is deliberately the CORRUPTION half only. The EXECUTION half -- a
DANGEROUS command inside the backticks -- is already covered, because the
blocking handlers match the full Bash command string before bash ever sees
it. That was probed against the live daemon in both quoting forms before this
handler was written, rather than assumed; see the plan's Task 1.1.
"""

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.command_evasion import GIT_INVOCATION

# Subcommands that take a -m/--message value. `git tag -a vX -m "..."` carries
# the identical hazard, and CLAUDE/development/RELEASING.md instructs exactly
# that form for every release -- so the corruption path is live on the release
# route, not merely on ordinary commits.
_MESSAGE_BEARING_SUBCOMMANDS: tuple[str, ...] = ("commit", "tag")

# A git invocation, built on the SHARED GIT_INVOCATION fragment rather than a
# local regex. That fragment is the maintained answer to command-respelling
# evasion -- it tolerates any run of global options (`git -C /path commit`),
# and refuses to match across a sub-command separator, so `echo x; git commit`
# is parsed as two commands rather than one. A hand-rolled equivalent here
# would be a second thing to keep in step, and `git -C` silently bypassing
# four handlers is exactly what happened when that fragment did not exist.
_GIT_SUBCOMMAND_PATTERN = re.compile(
    GIT_INVOCATION + r"(?:" + "|".join(_MESSAGE_BEARING_SUBCOMMANDS) + r")\b"
)

# A -m/--message value in DOUBLE quotes. The body tolerates backslash escapes
# so an escaped quote does not terminate the match early. DOTALL because these
# messages routinely span lines.
_DOUBLE_QUOTED_MESSAGE_PATTERN = re.compile(
    r"(?:-m|--message)(?:\s+|=)\"((?:[^\"\\]|\\.)*)\"",
    re.DOTALL,
)

# A backtick that bash will act on. A backslash-escaped backtick is literal
# even inside double quotes, so it must not fire.
_UNESCAPED_BACKTICK_PATTERN = re.compile(r"(?<!\\)`")

_REMEDY_SINGLE_QUOTE = "git commit -m 'text with `backticks` stays literal'"
_REMEDY_MESSAGE_FILE = "git commit -F <file>"


class GitMessageBacktickHandler(Handler):
    """Block a double-quoted git message whose backticks would be executed.

    Single-quoted messages, escaped backticks, and the ``-F`` file form are
    all untouched -- none of them substitutes.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GIT_MESSAGE_BACKTICK,
            priority=Priority.GIT_MESSAGE_BACKTICK,
            tags=[HandlerTag.SAFETY, HandlerTag.GIT, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when a git commit/tag carries a double-quoted message whose
        backticks bash would substitute."""
        command = get_bash_command(hook_input)
        if not command:
            return False
        if not _GIT_SUBCOMMAND_PATTERN.search(command):
            return False
        return any(
            _UNESCAPED_BACKTICK_PATTERN.search(message)
            for message in _DOUBLE_QUOTED_MESSAGE_PATTERN.findall(command)
        )

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Deny, naming the substitution and both concrete remedies."""
        return HookResult(
            decision=Decision.DENY,
            reason=(
                "🚫 BLOCKED: backticks inside a double-quoted git message are "
                "EXECUTED, not quoted\n\n"
                "WHAT WOULD HAPPEN:\n"
                "  • Bash performs command substitution inside double quotes\n"
                "  • The backticked span runs, and its STDOUT replaces the text\n"
                "  • The commit still SUCCEEDS, so the loss is silent — this is "
                "how commit cc7dddc0 in this repo lost a phrase from its body\n\n"
                "USE INSTEAD (either is fine):\n"
                f"  {_REMEDY_SINGLE_QUOTE}\n"
                f"  {_REMEDY_MESSAGE_FILE}\n\n"
                "Single quotes suppress substitution entirely, so backticks stay "
                "literal. A backslash-escaped \\` inside double quotes is also "
                "safe and is not blocked.\n\n"
                "To disable: handlers.pre_tool_use.git_message_backtick"
            ),
        )

    def get_claude_md(self) -> str:
        """Guidance injected into the project's resident CLAUDE.md."""
        return (
            "## git_message_backtick — backticks in a double-quoted git message\n\n"
            "Bash runs command substitution inside DOUBLE quotes, so backticks in "
            '`git commit -m "..."` (and `git tag -m "..."`) are EXECUTED and the '
            "span is replaced by the command's stdout. The commit still succeeds, "
            "so the text is lost silently — this is not hypothetical, a commit in "
            "this repo lost a phrase exactly this way.\n\n"
            "**Blocked**: an unescaped backtick inside a double-quoted `-m`/"
            "`--message` value on `git commit` or `git tag`.\n\n"
            "**Always allowed** — none of these substitute:\n\n"
            f"- Single quotes: `{_REMEDY_SINGLE_QUOTE}`\n"
            f"- A message file: `{_REMEDY_MESSAGE_FILE}`\n"
            "- A backslash-escaped `` \\` `` inside double quotes\n\n"
            "**Prefer single quotes or `-F` for any message containing markdown.** "
            "If a message needs BOTH backticks and interpolation, put it in a file "
            "and use `-F` — do not try to escape your way through it.\n\n"
            "Note this handler covers the CORRUPTION case only. A *dangerous* "
            "command inside backticks is already denied by the full-command-string "
            "matching in `destructive_git` and friends, which run at a lower "
            "priority and give the better reason."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests exercised by the generated playbook.

        The DENY case cannot be wrapped in `echo` the way most blocking
        tests are: `echo "git commit -m \\"x `y`\\""` would itself perform
        the substitution being demonstrated. It is safe unwrapped instead,
        because the handler denies BEFORE bash runs anything.
        """
        from claude_code_hooks_daemon.core.acceptance_test import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        backtick = "`"
        return [
            AcceptanceTest(
                title="double-quoted backtick message blocked",
                command=f'git commit -m "now allows {backtick}git branch{backtick} so it holds"',
                description="Backticks in a double-quoted -m are executed by bash, not quoted",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"EXECUTED", r"-F"],
                safety_notes=(
                    "Denied before bash runs, so no substitution and no commit occurs. "
                    "Not echo-wrapped: echo would itself substitute the backticks."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="single-quoted backtick message allowed",
                command=f"echo 'git commit -m {backtick}safe{backtick} single-quoted'",
                description="Single quotes suppress substitution, so backticks stay literal",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
