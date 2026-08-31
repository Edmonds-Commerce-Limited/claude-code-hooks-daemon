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

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult, ProjectContext, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter

logger = logging.getLogger(__name__)

# The tool's read-only mode. Enumerating existing artefacts discloses nothing
# new, so it is the one action deliberately left allowed.
_LIST_ACTION = "list"

# Config path a HUMAN edits to lift the block. Named in the deny reason so the
# person reading over the agent's shoulder knows exactly what to change.
_CONFIG_KEY_PATH = "handlers.pre_tool_use.artifact_publish_blocker.enabled"

# The documented Claude Code settings switch that removes the Artifact tool at
# source: no schema in context, no publish surface at all. "No file can turn it
# back on" once any settings file sets it false (Claude Code >= 2.1.242 honours
# it in project/local settings too).
_ENABLE_ARTIFACT_KEY = "enableArtifact"

# One-shot backup + atomic-write staging suffixes, mirroring
# utils.settings_repair so the two settings rewriters stay equivalent.
_BACKUP_SUFFIX = ".bak.pre-artifact-source-disable"
_TMP_SUFFIX = ".tmp.artifact-source-disable"

_RULE = Rule(
    rule_id=RuleID.ARTIFACT_PUBLISH,
    blocked="publishing an artefact via the `Artifact` tool",
    why="The page lives OUTSIDE the project and the repository cannot audit or retract it",
    fix="Write the file locally and tell the user its path, or ask a human to publish",
    verbose=(
        "WHY BLOCKED:\n"
        "Publishing renders this content to a page hosted on claude.ai and returns a\n"
        "URL. The page starts private, but it lives OUTSIDE this project:\n"
        "  - The repository cannot audit what left it\n"
        "  - Deleting the artefact later does NOT un-share a link already opened\n"
        "  - Whether that content should leave is the USER's decision, not yours\n\n"
        "DO INSTEAD:\n"
        "  - Write the file locally and tell the user its path — they lose nothing,\n"
        "    since publishing is one step they can take themselves whenever they want\n"
        "  - Report your findings directly in your reply\n\n"
        f"IF PUBLISHING IS GENUINELY WANTED:\n"
        f"Ask the user. Only a human may lift this block, by setting:\n\n"
        f"    {_CONFIG_KEY_PATH}: false\n\n"
        "Do NOT edit that setting yourself and do NOT look for another route to publish.\n"
        "An agent that authorises its own disclosure has defeated the entire point of\n"
        "this guard — which is exactly why this handler has no MUST_..._BECAUSE escape\n"
        "hatch, unlike guards whose consequences stay inside the repository.\n\n"
        'STILL ALLOWED: listing existing artefacts (`action: "list"`) — enumerating\n'
        "discloses nothing new."
    ),
)


class ArtifactPublishBlockerHandler(PreToolUseHandlerBase):
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
        # Opt-in `source_disable` option (Plan 00293): when a project turns it
        # on, the handler ensures `.claude/settings.json` carries
        # `"enableArtifact": false` so future sessions never load the tool.
        # The registry overwrites this attribute from handler options.
        self._source_disable = False
        self._source_disable_checked = False

    def _ensure_source_disable(self) -> None:
        """Apply the settings-level Artifact disable, once per daemon process.

        Runs from ``matches`` on the FIRST PreToolUse event of any kind — it
        must not depend on an Artifact call ever happening, because once the
        settings disable holds, none ever will. The write is additive and
        idempotent: other settings keys are preserved, an existing
        ``enableArtifact: false`` means no write, a one-shot backup is taken
        before the first rewrite, and any failure is logged rather than
        raised — a PreToolUse chain must never crash on a broken client file.
        """
        if self._source_disable_checked or not getattr(self, "_source_disable", False):
            return
        self._source_disable_checked = True

        root = getattr(self, "_workspace_root", None)
        root_path = Path(root) if root is not None else ProjectContext.project_root()
        settings_path = root_path / ".claude" / "settings.json"

        settings: dict[str, Any] = {}
        exists = settings_path.exists()
        if exists:
            try:
                loaded = json.loads(settings_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning(
                    "artifact source-disable skipped — cannot read %s: %s", settings_path, exc
                )
                return
            if not isinstance(loaded, dict):
                logger.warning(
                    "artifact source-disable skipped — %s is not a JSON object", settings_path
                )
                return
            settings = loaded

        if settings.get(_ENABLE_ARTIFACT_KEY) is False:
            return

        settings[_ENABLE_ARTIFACT_KEY] = False
        tmp_path = settings_path.with_name(settings_path.name + _TMP_SUFFIX)
        try:
            if exists:
                backup_path = settings_path.with_name(settings_path.name + _BACKUP_SUFFIX)
                if not backup_path.exists():
                    shutil.copy2(settings_path, backup_path)
            else:
                settings_path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write: stage then rename, so a crash mid-write can never
            # leave settings.json truncated. copymode keeps the tracked file's
            # permissions instead of inheriting the temp file's umask mode.
            tmp_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
            if exists:
                shutil.copymode(settings_path, tmp_path)
            tmp_path.replace(settings_path)
        except OSError as exc:
            logger.warning("artifact source-disable aborted for %s: %s", settings_path, exc)
            return
        logger.info(
            "artifact source-disable applied: %s now sets enableArtifact=false", settings_path
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
        self._ensure_source_disable()

        if hook_input.get("tool_name") != ToolName.ARTIFACT:
            return False

        tool_input = hook_input.get("tool_input")
        if not isinstance(tool_input, dict):
            return False

        action = tool_input.get("action")
        if isinstance(action, str) and action.strip().lower() == _LIST_ACTION:
            return False

        return True

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's blocking behaviour."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny the publish and explain who can lift the block.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G). The `source_disable`
        note is appended on every fire when the option is active — it is
        per-project configuration, not per-invocation, but it still changes
        which settings key is relevant to name.

        Args:
            hook_input: Hook input for the artefact call.

        Returns:
            GatingResult denying the call, or allowing it when it does not match.
        """
        if not self.matches(hook_input):
            return GatingResult(decision=Decision.ALLOW)

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        formatter = RuleFormatter()

        if transcript_path and tracker.was_disclosed(transcript_path, RuleID.ARTIFACT_PUBLISH):
            reason = formatter.terse(_RULE)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.ARTIFACT_PUBLISH)
            reason = formatter.verbose(_RULE)

        if getattr(self, "_source_disable", False):
            reason += """

NOTE: this project declares the Artifact tool a NEVER-WANT (`source_disable`).
The daemon has ensured `.claude/settings.json` sets `"enableArtifact": false`,
which removes the tool entirely from every NEW session — this in-session deny
is the backstop until the current session ends."""

        return GatingResult(
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
            f"**To lift it**, a HUMAN changes `{_CONFIG_KEY_PATH}` to `false`. Ask them; "
            "do not apply it yourself, and do not hunt for another way to publish.\n\n"
            "**Optional full disable at source** (Plan 00293): a project that never "
            "wants the Artifact tool at all can opt in via "
            "`handlers.pre_tool_use.artifact_publish_blocker.options.source_disable: true`. "
            "The daemon then ensures `.claude/settings.json` carries "
            '`"enableArtifact": false` (additive, idempotent, one-shot backup), which '
            "removes the tool — and its schema's context cost — from every new "
            "session. The call-time deny above stays as the in-session backstop. "
            "Ships disabled; enabling it is a deliberate repository-owner act, and "
            "note it also removes the allowed `list` action once a new session starts."
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
