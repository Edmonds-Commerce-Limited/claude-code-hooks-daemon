"""SubagentReportSizeBlockerHandler - block an oversized subagent final message.

Plan 00307 Task 3.1. Task 1.1's live reproduction dispatched a subagent
instructed to return a deliberately huge (~24k-token) final message inline:
the coordinator received a report with the requested start/end sentinels
intact, but an explicit truncation marker had been spliced into the MIDDLE by
the harness — roughly seven sections silently lost. A coordinator cannot
detect that failure by inspecting what it received (it looks complete), so
enforcement must live on the SUBAGENT side, at the moment it tries to stop.

The vendored SubagentStop contract (v2.1.252) delivers
``last_assistant_message`` directly on ``hook_input`` — no transcript parse
needed. This handler compares its length against a configured character
threshold and blocks the stop, instructing the agent to write the full report
to a file and reply with a short summary + path instead.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SubagentStopHandlerBase
from claude_code_hooks_daemon.utils.option_coercion import coerce_int_option
from claude_code_hooks_daemon.utils.subagent_report_paths import (
    DEFAULT_REPORT_DIR as _DEFAULT_PERSISTED_REPORT_DIR,
)
from claude_code_hooks_daemon.utils.subagent_report_paths import (
    find_persisted_report,
)
from claude_code_hooks_daemon.utils.subagent_tool_resolution import (
    resolve_agent_can_write,
    resolve_lookup_root,
)

# Task 1.1's reproduction measured harmful truncation at a ~24k-token
# (roughly 96k-character) final message. A subagent's final message should be
# a short completion summary, not the report itself — a few hundred to low
# thousands of characters covers that comfortably, so the default threshold
# sits an order of magnitude below the observed harmful shape.
_DEFAULT_THRESHOLD_CHARS = 4000

# Fallback directory for a report with no declared plan folder. MUST match
# dispatch_declaration's default (Plan 00307 Task 2.2/4.2) so the two
# handlers tell one consistent story, and MUST resolve under
# markdown_organization's built-in `untracked/` allow-rule so this handler's
# own prescription is never itself rejected by that handler (Task 4.2 tuning
# finding 2: the GREEN re-run's probe hit exactly that clash on its first,
# self-chosen write location). Configurable via
# subagent_report_size_blocker.options.fallback_report_dir.
_DEFAULT_FALLBACK_REPORT_DIR = "untracked/agent-reports/"

# Placeholder tokens used when the render inputs are unavailable at this
# surface — documented inline in the deny message so an agent copying the
# path literally sees they are placeholders, not real values.
_AGENT_NAME_PLACEHOLDER = "{agent-name}"
_MODEL_PLACEHOLDER = "{model}"


class SubagentReportSizeBlockerHandler(SubagentStopHandlerBase):
    """Block a SubagentStop whose ``last_assistant_message`` is oversized.

    Fails open on any missing/malformed input (no report, no verdict) and
    never re-fires on re-entry (``stop_hook_active``), so a subagent that
    complies after one block cannot be looped.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SUBAGENT_REPORT_SIZE_BLOCKER,
            priority=Priority.SUBAGENT_REPORT_SIZE_BLOCKER,
            terminal=True,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.TERMINAL,
            ],
        )
        # Config flags, declared here so mypy can verify them and a typo in a
        # config setter surfaces as a normal attribute (fail-fast).
        # `Any`, not `int`: options arrive by blind setattr from YAML, so a
        # string value is a real runtime possibility `_threshold()` must
        # guard against -- an `int` annotation here would make mypy treat
        # that guard's `isinstance(value, int)` check as always-true and
        # flag it `redundant-expr` (peer precedent: bash_safe_mode's
        # `_min_statements: Any` for the identical reason).
        self._threshold_chars: Any = _DEFAULT_THRESHOLD_CHARS
        self._fallback_report_dir: str = _DEFAULT_FALLBACK_REPORT_DIR
        # Plan 00460 Task 1.6: where subagent_report_persistence saves every
        # reply. Separately configurable from `_fallback_report_dir` above
        # (still used for the never-persisted fallback message), but shares
        # the same default -- change both together if you reconfigure either.
        self._persisted_report_dir: str = _DEFAULT_PERSISTED_REPORT_DIR
        # Test-only override (mirrors subagent_report_path_verifier's
        # `_project_root`): production resolves lazily via `_root()` so the
        # handler is never pinned to whatever directory the daemon happened
        # to start in.
        self._project_root: Path | None = None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for every SubagentStop except a re-entry (loop guard)."""
        return not bool(hook_input.get("stop_hook_active", False))

    def _prescribed_fallback_path(self, hook_input: dict[str, Any]) -> str:
        """Render a concrete, always-writable target path for the deny reason.

        The dispatch's plan folder (if any) is not visible at this SubagentStop
        surface, so this always renders the FALLBACK directory (not a plan
        folder's ``subagent-reports/``) — a real path an agent can write to
        immediately, not vague "write to a file" guidance. ``{yymmdd}`` is
        rendered from today's date (always known); the agent name comes from
        ``agent_type`` when the hook input carries it, else the literal
        placeholder token (documented in the deny message); the model is
        always the placeholder token — it is not part of the SubagentStop
        contract at all.
        """
        yymmdd = datetime.now(tz=UTC).strftime("%y%m%d")
        agent_type = hook_input.get("agent_type")
        agent_name = (
            agent_type if isinstance(agent_type, str) and agent_type else (_AGENT_NAME_PLACEHOLDER)
        )
        return f"{self._fallback_report_dir}{yymmdd}-{agent_name}-{_MODEL_PLACEHOLDER}.md"

    def _agent_can_write(self, hook_input: dict[str, Any]) -> bool | None:
        """Plan 00460 Task 1.1: whether the stopping agent has a `Write` tool.

        True/False when resolvable (a documented built-in, or a project/user
        `.claude/agents/*.md` file), else None (unknown — callers must keep
        today's behaviour, never guess).
        """
        agent_type = hook_input.get("agent_type")
        root = resolve_lookup_root(self._project_root, getattr(self, "_workspace_root", None))
        return resolve_agent_can_write(agent_type if isinstance(agent_type, str) else None, root)

    def _find_persisted_report(self, hook_input: dict[str, Any]) -> Path | None:
        """Plan 00460 Task 1.6: what `subagent_report_persistence` already saved.

        Globs by agent type/id (:func:`find_persisted_report`) rather than
        reconstructing an exact filename -- this handler and the persister
        each compute their own timestamp within the same dispatch, which can
        straddle a second boundary, and a collision-suffixed filename would
        not match an exact reconstruction either. No in-memory hand-off
        between the two handlers: only this lookup, run after the persister
        by priority ordering (10 before 15).
        """
        agent_id = hook_input.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            return None
        agent_type = hook_input.get("agent_type")
        root = resolve_lookup_root(self._project_root, getattr(self, "_workspace_root", None))
        target_dir = root / self._persisted_report_dir
        return find_persisted_report(
            target_dir, agent_type if isinstance(agent_type, str) else "", agent_id
        )

    @staticmethod
    def _deny_saved(
        path: Path, length: int, threshold: int, *, warn_against_bash_write: bool
    ) -> BlockingResult:
        """Plan 00460 Task 1.6: the reply is already saved -- point at it.

        Applies to EVERY agent, read-only or writable: neither needs to
        write anything itself any more. ``warn_against_bash_write`` adds the
        Bash-workaround warning for a read-only agent (Task 1.3's own
        concern is unrelated to WHO saved the file, only to what a
        Write-less agent might try instead).
        """
        bash_warning = (
            "\n\nDo NOT write your own copy via a Bash heredoc/redirect/`tee` "
            "— the file above is already saved through the content-safe "
            "daemon path; writing your own bypasses the guards a real "
            "`Write` call would get."
            if warn_against_bash_write
            else ""
        )
        return BlockingResult(
            decision=Decision.DENY,
            reason=(
                "📦 REPORT TOO LARGE (Plan 00307/00460): your final message is "
                f"{length} characters, over the {threshold}-character "
                "threshold. The full text is already saved at:\n\n"
                f"  {path}\n\n"
                "Reply now with that path and a short completion summary, "
                f"together under {threshold} characters — do not repeat the "
                f"full report inline.{bash_warning}"
            ),
        )

    @staticmethod
    def _deny_read_only(agent_type: str, length: int, threshold: int) -> BlockingResult:
        """Plan 00460 Task 1.2 decision (b): condense, never write-around.

        Never instructs a Write-less agent to write a file — that CLAUDE.md
        itself warns steers a read-only agent with Bash toward a heredoc/
        redirect, which reaches disk unexamined by the content guards a real
        `Write` call would get (see the plan journal's T1.2 decision for why
        the daemon cannot safely replicate those guards itself).
        """
        return BlockingResult(
            decision=Decision.DENY,
            reason=(
                "📦 REPORT TOO LARGE (Plan 00307/00460): your final message is "
                f"{length} characters, over the {threshold}-character "
                f"threshold. `{agent_type}` has no `Write` tool, so it cannot "
                "do what this block would otherwise ask: write the report to "
                "a file.\n\n"
                "Condense your reply to a short summary under the threshold: "
                "state what you found, cite file:line locations, and drop "
                "anything that does not fit. The coordinator can always ask a "
                "follow-up question for depth it still needs — a shorter "
                "report is not a lesser one.\n\n"
                "Do NOT write the file another way. A `cat <<'EOF'` heredoc, "
                "a shell redirect, or `tee` all reach disk WITHOUT the "
                "content guards (sensitive-content, secret-file, "
                "markdown-location) a `Write` tool call would get — this "
                "project's CLAUDE.md says so explicitly. Working around the "
                "missing tool defeats guards this project relies on."
            ),
        )

    def _threshold(self) -> int:
        """Coerced ``threshold_chars`` option, via the shared
        :func:`coerce_int_option` (Plan 00311 Task 1.5).

        Options arrive by blind ``setattr`` from YAML, so the type is not
        trusted: a YAML author writing ``threshold_chars: "4000"`` (a string)
        would otherwise raise ``TypeError`` on the ``len(message) <= ...``
        comparison inside a TERMINAL SubagentStop handler -- fail-fast
        elsewhere, but not here, where an unhandled exception in the
        dispatch hot path is worse than falling back to the shipped default.
        """
        return coerce_int_option(self._threshold_chars, default=_DEFAULT_THRESHOLD_CHARS)

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """DENY when ``last_assistant_message`` exceeds the threshold, else ALLOW."""
        message = hook_input.get("last_assistant_message")
        if not isinstance(message, str):
            # Fail open: no verdict without a readable report string.
            return BlockingResult(decision=Decision.ALLOW)

        threshold = self._threshold()
        if len(message) <= threshold:
            return BlockingResult(decision=Decision.ALLOW)

        can_write = self._agent_can_write(hook_input)

        persisted = self._find_persisted_report(hook_input)
        if persisted is not None:
            return self._deny_saved(
                persisted, len(message), threshold, warn_against_bash_write=can_write is False
            )

        if can_write is False:
            agent_type = hook_input.get("agent_type")
            return self._deny_read_only(
                agent_type if isinstance(agent_type, str) else _AGENT_NAME_PLACEHOLDER,
                len(message),
                threshold,
            )

        fallback_path = self._prescribed_fallback_path(hook_input)

        return BlockingResult(
            decision=Decision.DENY,
            reason=(
                "📦 REPORT TOO LARGE (Plan 00307): your final message is "
                f"{len(message)} characters, over the {threshold}-"
                "character threshold. A subagent's final message travels over "
                "a bounded-size wire channel that silently elides an oversized "
                "inline report in the MIDDLE — the coordinator can receive "
                "something that LOOKS complete while content is missing.\n\n"
                "Write the full report to a file now, at this exact path:\n\n"
                f"  {fallback_path}\n\n"
                f"(`{_MODEL_PLACEHOLDER}` is a literal placeholder — this "
                "handler has no model field to render; replace it and "
                f"`{_AGENT_NAME_PLACEHOLDER}` if shown above with real values. "
                "This fallback directory is always writable under this "
                "project's markdown-location rules.)\n\n"
                "If this dispatch declared a plan folder, prefer that folder's "
                "`subagent-reports/{yymmdd}-{agent-name}-{model}.md` instead "
                "of the fallback above.\n\n"
                "Then reply with a short completion summary plus the file "
                "path — not the report content itself."
            ),
        )

    def get_claude_md(self) -> str | None:
        return (
            "## subagent_report_size_blocker — write large reports to a file\n\n"
            "A subagent whose final message exceeds a configured character "
            "threshold is blocked from stopping. A subagent's return travels "
            "over a bounded-size wire channel that silently elides an "
            "oversized inline report in the MIDDLE — the coordinator can "
            "receive what looks like a complete report while content is "
            "missing.\n\n"
            "**Fix (usual case, Plan 00460 Task 1.6)**: `subagent_report_"
            "persistence` already saved this stop's full reply to a "
            f"gitignored file (default `{_DEFAULT_PERSISTED_REPORT_DIR}`) "
            "before this handler runs — the deny message names that exact "
            "path. Reply with the path plus a short completion summary; "
            "nothing needs to be written by the agent itself, whether or "
            "not it has a `Write` tool.\n\n"
            "**Fix (fallback — persistence unavailable or failed, agent has "
            "a `Write` tool)**: write the full report to a "
            "file under the declared plan folder's "
            "`subagent-reports/{yymmdd}-{agent-name}-{model}.md` — or, for "
            "non-plan work, the configured fallback directory (default "
            f"`{_DEFAULT_FALLBACK_REPORT_DIR}`) using the same filename "
            "convention. The deny message renders this fallback path "
            "concretely (today's date, `agent_type` when the hook input "
            "carries it, `{model}` as a literal placeholder — no model field "
            "exists at this surface), then reply with a short completion "
            "summary plus the file path.\n\n"
            "**Fix (fallback — persistence unavailable or failed, agent has "
            "no `Write` tool, e.g. `Explore`/`Plan`, or a project agent "
            "whose frontmatter omits `Write`)**: condense the "
            "reply to a short summary under the threshold instead — never "
            "write the file another way. A Bash heredoc/redirect/`tee` "
            "reaches disk WITHOUT the content guards (sensitive-content, "
            "secret-file, markdown-location) a real `Write` call would get, "
            "so the deny message explicitly forbids it (Plan 00460)."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the subagent report size blocker."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Subagent attempts to stop with an oversized final message",
                command=(
                    "Dispatch a subagent instructed to return a final message "
                    "well over the configured threshold, writing nothing to disk"
                ),
                description=(
                    "Blocks the SubagentStop and instructs the agent to write "
                    "the report to a file and reply with a summary + path"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"REPORT TOO LARGE", r"subagent-reports"],
                safety_notes=(
                    "Fails open on any missing/malformed last_assistant_message "
                    "and never re-fires on stop_hook_active re-entry."
                ),
                test_type=TestType.BLOCKING,
                requires_event="SubagentStop",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
                # SubagentStop carries no tool call, so a ToolPayload cannot
                # describe it (Plan 00319 Task 4.6) -- hook_input drives the
                # CI-time contract test directly. One character over the
                # SHIPPED default threshold, not `self._threshold()`: a
                # payload built from the handler's OWN (possibly
                # option-overridden) threshold would still pass after a
                # regression that silently stopped reading the option.
                hook_input={
                    "hook_event_name": "SubagentStop",
                    "last_assistant_message": "x" * (_DEFAULT_THRESHOLD_CHARS + 1),
                    "stop_hook_active": False,
                },
            ),
            AcceptanceTest(
                title="Subagent stops with a short summary + path (near-miss allow)",
                command="Dispatch a subagent that writes its report to a file and replies with a short summary",
                description="Stays silent when the final message is within the threshold",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Negative case: a compliant subagent must never be blocked.",
                test_type=TestType.BLOCKING,
                requires_event="SubagentStop",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
                hook_input={
                    "hook_event_name": "SubagentStop",
                    "last_assistant_message": "Done -- wrote the full report to disk; see path above.",
                    "stop_hook_active": False,
                },
            ),
            AcceptanceTest(
                title="Explore (read-only) attempts to stop with an oversized final message",
                command=(
                    "Dispatch an Explore subagent instructed to return a final "
                    "message well over the configured threshold"
                ),
                description=(
                    "Plan 00460: Explore has no Write tool, so the block never "
                    "instructs it to write a report file -- it is told to "
                    "condense its reply instead, with an explicit warning "
                    "against writing around the missing tool via Bash"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"REPORT TOO LARGE", r"no `Write` tool", r"Condense"],
                safety_notes=(
                    "Fails open on any missing/malformed last_assistant_message "
                    "and never re-fires on stop_hook_active re-entry."
                ),
                test_type=TestType.BLOCKING,
                requires_event="SubagentStop",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
                hook_input={
                    "hook_event_name": "SubagentStop",
                    "agent_type": "Explore",
                    "last_assistant_message": "x" * (_DEFAULT_THRESHOLD_CHARS + 1),
                    "stop_hook_active": False,
                },
            ),
        ]
