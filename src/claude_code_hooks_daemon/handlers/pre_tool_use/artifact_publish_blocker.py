"""Handler that blocks artefact publishing by default (Plan 00259).

The ``Artifact`` tool renders a local file to a page hosted on claude.ai and
returns a URL. The page starts private, but it is hosted OUTSIDE the project and
the whole purpose of the URL is that a human can then share it. That makes it an
egress path the repository cannot see, cannot audit and cannot retract: once
content has left, deleting the artefact does not un-share a link somebody has
already opened.

This project consistently refuses to let an agent self-authorise disclosure --
the secret word list, ``delete-branch --allow-unproven`` demanding an
interactive human, and ``standing_authorisations`` shipping every entry disabled
are the same principle. Artefact publishing was the one disclosure path with no
guard at all.

Scope note: this handler blocks the ACT of publishing, not the content. Content
scanning belongs to ``sensitive_content``, which already ran when the file was
written; duplicating it here would create a second source of truth for "what is
sensitive" and the two would drift. The risk being managed is not "this page
contains a secret" but "a URL now exists outside the repository".
"""

from typing import Any

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult

# The tool's read-only mode. Enumerating existing artefacts discloses nothing
# new, so it is the one action deliberately left allowed.
_LIST_ACTION = "list"

# Config path a HUMAN edits to lift the block. Named in the deny reason so the
# person reading over the agent's shoulder knows exactly what to change.
_CONFIG_KEY_PATH = "handlers.pre_tool_use.artifact_publish_blocker.enabled"


class ArtifactPublishBlockerHandler(Handler):
    """Deny artefact publishing; allow read-only enumeration.

    Priority: 14 (grouped with ``sensitive_content`` and
    ``security_antipattern`` -- all three guard content leaving the project).
    Terminal: True.
    """

    def __init__(self) -> None:
        """Initialise with disclosure-band priority."""
        super().__init__(
            handler_id=HandlerID.ARTIFACT_PUBLISH_BLOCKER,
            priority=Priority.ARTIFACT_PUBLISH_BLOCKER,
            terminal=True,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Fire on any ``Artifact`` call that is not a read-only listing.

        The payload shape was captured from the live daemon rather than assumed
        (Plan 00259 Task 1.1): ``tool_input`` carries an optional ``action``,
        where an ABSENT action means publish. Defaulting to "this publishes"
        is the fail-safe reading -- a future action name this handler has never
        heard of is treated as publishing until proven otherwise, rather than
        being waved through.

        Args:
            hook_input: Hook input containing tool_name and tool_input.

        Returns:
            True if this call would create or update a hosted page.
        """
        if hook_input.get("tool_name") != ToolName.ARTIFACT:
            return False

        tool_input = hook_input.get("tool_input")
        if not isinstance(tool_input, dict):
            return False

        action = tool_input.get("action")
        if isinstance(action, str) and action.strip().lower() == _LIST_ACTION:
            return False

        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Deny the publish and explain who can lift the block.

        Args:
            hook_input: Hook input for the artefact call.

        Returns:
            HookResult denying the call, or allowing it when it does not match.
        """
        if not self.matches(hook_input):
            return HookResult(decision=Decision.ALLOW)

        reason = f"""🚫 BLOCKED: publishing an artefact

WHY BLOCKED:
Publishing renders this content to a page hosted on claude.ai and returns a
URL. The page starts private, but it lives OUTSIDE this project:
  • The repository cannot audit what left it
  • Deleting the artefact later does NOT un-share a link already opened
  • Whether that content should leave is the USER's decision, not yours

DO INSTEAD:
  • Write the file locally and tell the user its path — they lose nothing,
    since publishing is one step they can take themselves whenever they want
  • Report your findings directly in your reply

IF PUBLISHING IS GENUINELY WANTED:
Ask the user. Only a human may lift this block, by setting:

    {_CONFIG_KEY_PATH}: false

Do NOT edit that setting yourself and do NOT look for another route to publish.
An agent that authorises its own disclosure has defeated the entire point of
this guard — which is exactly why this handler has no MUST_..._BECAUSE escape
hatch, unlike guards whose consequences stay inside the repository.

STILL ALLOWED: listing existing artefacts (`action: "list"`) — enumerating
discloses nothing new."""

        return HookResult(
            decision=Decision.DENY,
            reason=reason,
            context=[],
            guidance=None,
        )

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## artifact_publish_blocker — publishing artefacts is blocked by default\n\n"
            "The `Artifact` tool renders a local file to a page hosted on claude.ai and "
            "returns a URL. The page starts private, but it lives OUTSIDE the project: "
            "the repository cannot audit what left it, and deleting the artefact later "
            "does not un-share a link someone has already opened. Whether content leaves "
            "is the USER's call.\n\n"
            "**Blocked**: any `Artifact` publish or update (an absent `action`, "
            '`action: "publish"`, or passing `url` to update an existing page).\n\n'
            '**Always allowed**: `action: "list"` — enumerating existing artefacts '
            "discloses nothing new.\n\n"
            "**Do instead**: write the file locally and give the user its path, or "
            "report your findings in your reply. The user loses nothing — publishing is "
            "a step they can take themselves at any time.\n\n"
            "**There is NO escape hatch.** Unlike `git_stash` or "
            "`ancestry_preserving_merge`, this handler accepts no "
            "`MUST_..._BECAUSE` declaration. Those hatches let an agent declare intent "
            "for an action whose consequences stay inside the repository; publishing "
            "leaves it. An agent that can type its own justification has self-authorised "
            "disclosure, which is the precise thing this guard exists to prevent — the "
            "same reason `delete-branch --allow-unproven` still demands an interactive "
            "human.\n\n"
            f"**To lift it**, a HUMAN sets `{_CONFIG_KEY_PATH}: false`. Ask them; do not "
            "apply it yourself, and do not hunt for another way to publish."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests: one DENY case and one ALLOW case."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Artifact publish is denied",
                command=(
                    "Use the Artifact tool to publish any local .html file "
                    "(no action parameter, which means publish)."
                ),
                description="Blocks artefact publishing (disclosure outside the project)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED: publishing an artefact",
                    r"artifact_publish_blocker",
                    r"Ask the user",
                ],
                safety_notes=("The call is denied before it runs, so nothing is ever published."),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Artifact list is allowed",
                command='Use the Artifact tool with action: "list" and limit: 1.',
                description=(
                    "Read-only enumeration is NOT blocked - proves the matcher is "
                    "not over-broad, which a deny-only suite cannot show"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read-only; publishes nothing.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
