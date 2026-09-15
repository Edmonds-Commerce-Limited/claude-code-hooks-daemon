"""RuffFormatBlockerHandler — Black is the formatter here, Ruff is the linter.

Plan 00419 niggle N7. `CLAUDE/QA.md:48` states the split plainly: **Format
(Black) / Linter (Ruff)**, both auto-fixing via `./scripts/qa/run_autofix.sh`.
Running `ruff format` anyway put 163 files into a commit meant to carry 8
(`344ebf16`); the next QA run rewrote 82 of them back to Black's style, which
is how it surfaced — after the churn was already in pushed history and mixed
into an unrelated diff.

**Why a guard and not better documentation.** The documentation was already
correct and had already been read in the same session. Both formatters are
installed, both are a natural reach, and the wrong one SUCCEEDS: it reports
confidently and leaves a tree that passes `ruff format --check`. Nothing
objects until much later, and by then the cost has moved to whoever reviews
the diff. That is this repository's own thesis — a rule stated in prose and
enforced by nothing gets broken — demonstrated on its own author.

**Project-level, not shipped.** Another project may legitimately use Ruff as
its formatter, so this must never reach one as a library handler. The owner's
ruling for exactly this shape (Plan 00418) is to dogfood as a project handler
first; promotion would be a separate decision, and the answer there is
probably no.

**`--check` is blocked too, deliberately.** It writes nothing, so it looks
harmless — and it is the other half of the trap. It answers confidently about
a tree Black owns, so a green `ruff format --check` is a false reassurance.
Blocking only the writing form would leave the misleading half in place.

`ruff check` (with or without `--fix`) is NOT touched: that is Ruff being this
project's linter, which is exactly right. The deny message says so, because the
wrong lesson to take from this block is "Ruff is banned".
"""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.utils.shell_segmentation import (
    split_unquoted,
    strip_quoted_heredoc_bodies,
)

_AUTOFIX_SCRIPT = "./scripts/qa/run_autofix.sh"

# Commands that READ a path or record it as data rather than executing it. A
# `ruff format` inside a grep pattern, a commit message or a file being cat-ed
# is a mention: searching for this mistake and writing it down are both part of
# cleaning it up. The sibling `enforce_llm_qa` handler learned the commit-message
# case by hitting it while writing the very commit that described its own
# guarded script.
_MENTION_COMMANDS = (
    "cat",
    "less",
    "more",
    "head",
    "tail",
    "grep",
    "rg",
    "wc",
    "bat",
    "diff",
    "echo",
    "printf",
    "git",
    "gh",
)

# Top-level shell separators. A newline counts: `a\nb` runs two commands just as
# `a; b` does, and omitting it would let a real invocation on line 2 inherit
# line 1's harmless leading word.
_SEGMENT_SEPARATORS = (";", "|", "&", "\n")


def _is_format_invocation(segment: str) -> bool:
    """Whether one shell segment actually RUNS ruff's formatter.

    The distinguishing pair is ``ruff`` followed by the ``format`` subcommand.
    ``ruff check --fix`` shares the first word and is the linter doing its job,
    so the subcommand is what decides — not the presence of the word ``ruff``.
    """
    words = segment.split()
    if not words:
        return False

    # Find ruff wherever it sits: bare, `python -m ruff`, or an absolute venv
    # path. Taking the basename means `/workspace/untracked/venv-x/bin/ruff`
    # and `ruff` are the same word, which is the common spelling here because
    # the venv is resolved by a script rather than activated.
    for index, word in enumerate(words):
        if word.rsplit("/", 1)[-1] != "ruff":
            continue
        # The next non-flag word is the subcommand.
        for following in words[index + 1 :]:
            if following.startswith("-"):
                continue
            return following == "format"
        return False
    return False


class RuffFormatBlockerHandler(Handler):
    """Deny `ruff format`; point at the project's actual formatter."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="ruff-format-blocker",
            # 52 — a genuinely free slot, read off `hooks-daemon handlers`
            # rather than guessed. Copying the sibling `enforce_llm_qa`'s 41
            # collided with it, and 42 then collided with `advise-global-npm`:
            # a collision makes the daemon log a warning on every start and
            # leaves the two handlers' relative order arbitrary. Grepping the
            # source for `priority=` does NOT answer this, because library
            # handlers take their priority from config. Ordering against
            # `enforce_llm_qa` does not matter either way here — the two match
            # disjoint commands.
            priority=52,
            terminal=True,
            tags=["project", "blocking", "qa"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match a Bash command that runs ruff's FORMATTER, per segment."""
        if hook_input.get("tool_name") != "Bash":
            return False
        tool_input = hook_input.get("tool_input", {})
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        if "ruff" not in command:
            return False

        for segment in split_unquoted(strip_quoted_heredoc_bodies(command), _SEGMENT_SEPARATORS):
            stripped = segment.strip()
            if not stripped:
                continue
            words = stripped.split()
            leading_word = words[0].rsplit("/", 1)[-1]
            if leading_word in _MENTION_COMMANDS:
                # Reading or recording, not running. Judged per segment so
                # `grep ruff f; ruff format src` still matches on the second.
                continue
            if _is_format_invocation(stripped):
                return True
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Deny, naming the formatter of record and the entry point to use."""
        return HookResult(
            decision=Decision.DENY,
            reason=(
                "WRONG FORMATTER — Black is this project's formatter of record\n\n"
                "Ruff is the LINTER here; Black is the FORMATTER (CLAUDE/QA.md).\n"
                "Running `ruff format` restyles every file it touches, and the\n"
                "next QA run rewrites them back — so the churn lands in pushed\n"
                "history, mixed into an unrelated commit. That is niggle N7, and\n"
                "it cost one commit 155 files it should never have carried.\n\n"
                f"Use the project's auto-fix entry point instead:\n\n  {_AUTOFIX_SCRIPT}\n\n"
                "It runs Black and Ruff in the right roles.\n\n"
                "`ruff check` and `ruff check --fix` are NOT blocked — that is\n"
                "Ruff doing its actual job here. Only the formatter is wrong.\n\n"
                "`ruff format --check` is blocked too: it writes nothing, but it\n"
                "reports confidently about a tree Black owns, so passing it is a\n"
                "false reassurance rather than a clean bill of health."
            ),
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [
            AcceptanceTest(
                title="Block ruff format",
                command="echo 'ruff format src'",
                description="Blocks the wrong formatter, names Black and run_autofix.sh",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Black", r"run_autofix\.sh"],
                safety_notes="Uses echo - safe to execute",
                test_type=TestType.BLOCKING,
                dispatch_as_bash=True,
            ),
            AcceptanceTest(
                title="Allow ruff check (Ruff is the linter here)",
                command="echo 'ruff check src'",
                description=(
                    "Ruff IS this project's linter. Blocking its check command "
                    "would teach the wrong lesson and break the QA pipeline."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses echo - safe to execute",
                test_type=TestType.BLOCKING,
                dispatch_as_bash=True,
            ),
        ]
