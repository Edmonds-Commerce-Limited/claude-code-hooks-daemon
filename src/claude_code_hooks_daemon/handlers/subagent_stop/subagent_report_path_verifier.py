"""SubagentReportPathVerifierHandler - a claimed report path must exist.

Plan 00446, from ledger 00422 N15. A dedupe scout's final message ended
``Report written to:`` and a path that was well-formed, matched the project's
filename convention exactly, and named a file nobody ever created. The verdict
had arrived inline and was re-derivable by hand, so that time it cost nothing;
what it costs otherwise is a PLAN.md citing evidence at a path that resolves to
nothing.

**No caller-stated value can catch this.** Plan 00434's remedy for N13 moved
the plan COUNT outside the agent so the report could be checked against
something the agent did not produce, and that works. But an EXISTENCE claim has
nothing to compare against except the filesystem, and a coordinator that simply
believes the message records a dead path.

So this is the sibling of ``subagent_report_size_blocker``, whose reasoning
transfers unchanged: the coordinator cannot detect the failure by inspecting
what it received, because what it received looks right. The one moment at which
the claim and the filesystem are both in reach is the subagent's own stop.

**The risk is false positives, and the design is shaped around it.** This
handler blocks a stop, and honest reports cite the files they examined. So a
claim is only recognised when a WRITE verb governs the path, fenced blocks are
stripped first, and a path outside the project root is never judged. Everything
else -- no message, a non-string message, no claim, a re-entry -- allows.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import SubagentStopHandlerBase

# Fenced spans are stripped before matching: a fence is something the agent is
# SHOWING the coordinator (a command to run, a snippet to read), not a claim
# about what it did. `cat untracked/report.md` inside a fence names a path
# under a verb, and without this would read as a write claim.
_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)

# The write verbs, in the shapes agents actually use. Deliberately PAST tense
# or passive: "write X next" and "you should write X" are recommendations, and
# blocking on those would fire on advice rather than on a claim.
_CLAIM_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:written|wrote|saved|created)\b"  # the verb
    r"(?:\s+\w+){0,3}?"  # "written to", "saved to", "wrote the full"
    r"\s*:?\s*"
    r"[`'\"]?(?P<path>[\w./@-]+\.md)[`'\"]?",
    re.IGNORECASE,
)

#: Only `.md` is judged. Every report convention in this project writes
#: markdown, and widening it would start judging incidental filenames.
_MAX_CLAIMS_REPORTED: Final[int] = 5


def written_path_claims(message: str) -> list[str]:
    """Paths the message claims to have WRITTEN, in order, de-duplicated.

    A mention is not a claim. "I read X", "you should write X", and anything
    inside a fenced block all return nothing -- see this module's docstring
    for why that asymmetry is deliberate rather than conservative.
    """
    if not message:
        return []
    prose = _FENCE_RE.sub(" ", message)
    claims: list[str] = []
    for match in _CLAIM_RE.finditer(prose):
        path = match.group("path")
        if path not in claims:
            claims.append(path)
    return claims


class SubagentReportPathVerifierHandler(SubagentStopHandlerBase):
    """Block a SubagentStop whose claimed report file does not exist.

    Non-terminal by design: a report can be both unwritten and oversized, and
    the agent should hear about both in one stop rather than one per round
    trip. See ``Priority.SUBAGENT_REPORT_PATH_VERIFIER`` for why it runs ahead
    of the terminal size blocker.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SUBAGENT_REPORT_PATH_VERIFIER,
            priority=Priority.SUBAGENT_REPORT_PATH_VERIFIER,
            terminal=False,
            tags=[HandlerTag.WORKFLOW],
        )
        # Overridable by a test; resolved lazily in production so the handler
        # is not pinned to whatever directory the daemon happened to start in.
        self._project_root: Path | None = None

    def _root(self) -> Path:
        """The checkout a claimed relative path is resolved against.

        Mirrors ``cron_subagent_stop_enforcer._project_root``: an injected
        ``_workspace_root`` wins, then :class:`ProjectContext`. ``Path.cwd()``
        is deliberately NOT the fallback — a worktree dispatch resolves a
        relative claim against the wrong checkout and reports a written file
        as missing.
        """
        if self._project_root is not None:
            return self._project_root
        root = getattr(self, "_workspace_root", None)
        return Path(root) if root is not None else ProjectContext.project_root()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for every SubagentStop except a re-entry (loop guard)."""
        return not bool(hook_input.get("stop_hook_active", False))

    def _missing(self, claim: str) -> str | None:
        """The claim, if it names a project path that is not on disk.

        A path outside the project root is never judged: it is not this
        repository's business, and an absolute path into someone else's tree
        cannot be checked meaningfully from here.
        """
        project_root = self._root()
        candidate = Path(claim)
        resolved = candidate if candidate.is_absolute() else project_root / candidate
        try:
            resolved = resolved.resolve()
            root = project_root.resolve()
        except OSError:
            # Fail open: an unresolvable path is not evidence of a false claim.
            return None
        if not resolved.is_relative_to(root):
            return None
        return None if resolved.exists() else claim

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """DENY when the message claims a project file it did not write."""
        message = hook_input.get("last_assistant_message")
        if not isinstance(message, str):
            # Fail open: no verdict without a readable report string.
            return BlockingResult(decision=Decision.ALLOW)

        missing = [
            claim for claim in written_path_claims(message) if self._missing(claim) is not None
        ]
        if not missing:
            return BlockingResult(decision=Decision.ALLOW)

        named = "\n".join(f"  {claim}" for claim in missing[:_MAX_CLAIMS_REPORTED])
        return BlockingResult(
            decision=Decision.DENY,
            reason=(
                "📄 REPORT PATH DOES NOT EXIST (Plan 00446): your final message "
                "says you wrote a file, and it is not there:\n\n"
                f"{named}\n\n"
                "A coordinator cannot check this by reading your message — the "
                "path looks right, which is exactly why a false one is "
                "expensive: it gets recorded as evidence and resolves to "
                "nothing.\n\n"
                "Two ways forward, and the second is not a lesser one:\n\n"
                "  1. Write the file now, at that exact path, then stop.\n"
                "  2. Stop WITHOUT claiming a path. If your report was short "
                "enough to deliver inline, that was the right call — say so and "
                "drop the sentence naming a file. Do NOT create an empty or "
                "padded file just to satisfy this check; an invented report is "
                "worse than the claim it replaces, because it looks like "
                "evidence."
            ),
        )

    def get_claude_md(self) -> str | None:
        return (
            "## subagent_report_path_verifier — a claimed report path must exist\n\n"
            "A subagent whose final message says it WROTE a file is blocked "
            "from stopping when that file is not on disk. The coordinator "
            "cannot catch this itself: a fabricated path is well-formed and "
            "looks correct, so it gets recorded as evidence and later resolves "
            "to nothing.\n\n"
            "**Only a write CLAIM counts.** A path you read, a path you "
            "recommend the coordinator create, and anything inside a fenced "
            "block are all ignored — cite files freely. Paths outside the "
            "project root are never judged.\n\n"
            "**Fix**: either write the file at the path you named, or stop "
            "without naming one. Delivering a short report inline is "
            "legitimate; what is not legitimate is claiming a file that does "
            "not exist, and creating an empty file to get past this check is "
            "worse than either."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the subagent report path verifier."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Subagent stops claiming a report file it never wrote",
                command=(
                    "Dispatch a subagent that replies 'Report written to "
                    "`untracked/agent-reports/no-such-report-00446.md`' "
                    "without creating that file"
                ),
                description=(
                    "Blocks the SubagentStop, names the missing path, and "
                    "offers both writing the file and stopping without the claim"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"REPORT PATH DOES NOT EXIST",
                    r"no-such-report-00446\.md",
                ],
                safety_notes=(
                    "Fails open on any missing/malformed last_assistant_message, "
                    "on a path outside the project root, and never re-fires on "
                    "stop_hook_active re-entry."
                ),
                test_type=TestType.BLOCKING,
                requires_event="SubagentStop",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
                # SubagentStop carries no tool call, so a ToolPayload cannot
                # describe it -- hook_input drives the CI-time contract test
                # directly, matching the size blocker's own note. The path is
                # deliberately one no convention would ever produce, so the
                # probe cannot be satisfied by a real report left behind.
                hook_input={
                    "hook_event_name": "SubagentStop",
                    "last_assistant_message": (
                        "Report written to `untracked/agent-reports/no-such-report-00446.md`"
                    ),
                    "stop_hook_active": False,
                },
            ),
            AcceptanceTest(
                title="Subagent stops citing files it READ (control)",
                command="Dispatch a subagent that summarises inline, naming the files it consulted",
                description=(
                    "Stays silent: a mention is not a claim, so honest reports "
                    "that cite their sources are never blocked"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Negative case, and the one that matters: the positive probe "
                    "above is satisfied just as well by a guard that blocks "
                    "everything, so this is what distinguishes them."
                ),
                test_type=TestType.BLOCKING,
                requires_event="SubagentStop",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
                hook_input={
                    "hook_event_name": "SubagentStop",
                    "last_assistant_message": (
                        "Checked 29 live plans. I read `CLAUDE/Plan/README.md` "
                        "and `CLAUDE/Plan/00422-niggles-ledger-fifteen/PLAN.md`; "
                        "no duplicates found."
                    ),
                    "stop_hook_active": False,
                },
            ),
        ]
