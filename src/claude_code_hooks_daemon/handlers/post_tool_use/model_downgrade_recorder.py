"""ModelDowngradeRecorderHandler - publish the automatic model downgrade (Plan 00328).

The ccy supervisor restores the session model after Anthropic's safety
classifier substitutes it (`fable` -> `opus`). Getting that right needs one
fact: *was this family change the machine's doing, or the human's?* Every
earlier attempt inferred it NEGATIVELY — from typed keystrokes, from a model
high-water mark, from the user settings file — and a live dogfood showed what
that costs: the supervisor typed `/model fable` at a human who had just picked
Opus, drove effort to fable's floor, and queued a `/compact` that would have
destroyed the session context unattended.

Claude Code already writes the answer down. The automatic downgrade appears in
the session transcript as a structured record naming both models, the refusal
category and its scope. This handler reads that record on each PostToolUse and
publishes it as a per-session signal file, which turns the supervisor's
question around: it arms on a POSITIVELY attributed machine action, so a human
model change needs no recognition at all — it produces no such record.

Layering follows Plan 00317's thin-host audit. The supervisor does not read
transcripts; the daemon already receives ``transcript_path`` on every hook
event and already owns the record parser
(``utils/model_fallback_records.py``), so the producer belongs here and the
transport is the ``context-sidecar`` directory both sides already share --
the same shape ``goal_injection`` uses for ``<session>.goal-intent``.

Never blocks and never speaks. An advisory would fire on every tool call of a
long session to say something the human cannot act on; the value is entirely
in the file.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.status_line.downgrade_state import resolve_model_family
from claude_code_hooks_daemon.utils.model_downgrade_signal import (
    SIGNAL_SUBDIR,
    SIGNAL_SUFFIX,
    DowngradeSignal,
    write_downgrade_signal,
)
from claude_code_hooks_daemon.utils.model_fallback_records import (
    FallbackFacts,
    scan_transcript_tail,
)

logger = logging.getLogger(__name__)

# Re-exported so tests and readers can locate the published file without
# reaching past this handler into the shared signal module.
_SIGNAL_SUBDIR: Final[str] = SIGNAL_SUBDIR
_SIGNAL_SUFFIX: Final[str] = SIGNAL_SUFFIX

# Bounded tail window, matching ``TranscriptReader.load_tail``'s 1 MiB so the
# codebase has one answer to "how much tail is enough". A downgrade record
# sits in the assistant turn that issued the tool call being handled, so it is
# separated from the end by roughly one tool result -- comfortably inside this
# window unless a single result is enormous, and a miss is recoverable because
# the next tool call scans again.
_DEFAULT_TAIL_BYTES: Final[int] = 1_048_576


def _family_or_none(model_id: str) -> str | None:
    """The canonical family for ``model_id``, or ``None`` when unrecognised.

    ``None`` rather than a guess: the supervisor gates a real injection on
    this, and a mis-resolved family would aim the restore at the wrong model.
    """
    resolved = resolve_model_family(model_id)
    return resolved[0] if resolved is not None else None


def build_signal(facts: FallbackFacts, *, session_id: str) -> DowngradeSignal:
    """Render the per-session downgrade signal from a parsed transcript record.

    Model ids are resolved to families HERE so the supervisor stays thin. An
    unrecognised id becomes ``None`` rather than a guess: consumers gate a real
    injection and a status-line badge on it, and a mis-resolved family would
    aim both at the wrong model.
    """
    return DowngradeSignal(
        session_id=session_id,
        original_model=facts.original_model,
        fallback_model=facts.fallback_model,
        original_family=_family_or_none(facts.original_model),
        fallback_family=_family_or_none(facts.fallback_model),
        category=facts.category,
        scope=facts.scope,
        record_ts=facts.timestamp,
    )


def publish(signal: DowngradeSignal, *, now: float) -> Path | None:
    """Publish ``signal`` under the live project's untracked dir.

    Resolving that directory is the only thing this adds over
    ``write_downgrade_signal``; without a project context (a daemon started
    outside a project, or a unit test) there is nowhere to write and the record
    stays in the transcript for the next tool call to find.
    """
    try:
        daemon_untracked_dir = ProjectContext.daemon_untracked_dir()
    except RuntimeError as exc:
        logger.warning("model_downgrade_recorder: no project context: %s", exc)
        return None
    return write_downgrade_signal(daemon_untracked_dir, signal, now=now)


class ModelDowngradeRecorderHandler(PostToolUseHandlerBase):
    """Publish Claude Code's own automatic model-downgrade record, silently."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.MODEL_DOWNGRADE_RECORDER,
            priority=Priority.MODEL_DOWNGRADE_RECORDER,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ENVIRONMENT,
            ],
        )
        # Option — injected by the registry via setattr; typed and defaulted
        # here so mypy sees a real attribute (command_hints convention).
        self._tail_bytes: int = _DEFAULT_TAIL_BYTES

    def get_default_enabled(self) -> bool:
        """Ships ENABLED.

        Unlike the sibling ``model_fallback_detector`` (opt-in, because its
        SessionStart alert is noisy and writes snapshot files), this handler
        is silent and writes nothing at all for a session that never gets
        downgraded. The cost of it being off is worse than the cost of it
        being on: the supervisor's auto-restore then falls back to inferring
        human intent, which is the defect Plan 00328 exists to remove.
        """
        return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when the event carries both a transcript and a session to key on."""
        transcript_path = str(hook_input.get(HookInputField.TRANSCRIPT_PATH, "") or "")
        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "")
        return bool(transcript_path) and bool(session_id)

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Publish the downgrade record if the transcript tail holds one.

        Always ALLOW, always silent. Every failure path — missing transcript,
        unreadable file, no project context — degrades to "no signal", because
        a recorder that can take a hook dispatch down is worse than one that
        occasionally misses a record it will see again on the next tool call.
        """
        transcript_path = str(hook_input.get(HookInputField.TRANSCRIPT_PATH, "") or "")
        session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or "")
        if not transcript_path or not session_id:
            return BlockingResult(decision=Decision.ALLOW)

        facts = scan_transcript_tail(Path(transcript_path), max_bytes=int(self._tail_bytes))
        if facts is None:
            return BlockingResult(decision=Decision.ALLOW)

        publish(build_signal(facts, session_id=session_id), now=time.time())
        return BlockingResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return (
            "### model_downgrade_recorder — the automatic model downgrade is written down\n\n"
            "When Anthropic's safety classifier substitutes this session's model "
            "(typically `fable` → `opus`), Claude Code records it in the session "
            "transcript. This handler copies that record to "
            "`{daemon_untracked_dir}/context-sidecar/<session>.model-downgrade` so the "
            "ccy supervisor can tell a MACHINE downgrade from a model YOU chose.\n\n"
            "**Why it matters to you**: without it the supervisor has to guess, and a "
            "wrong guess types `/model` at you after you have just picked one. A model "
            "you select yourself writes no such record, so it is never overridden.\n\n"
            "It is silent — it never blocks, never advises, and writes nothing at all "
            "unless a downgrade actually happened. The file names both models, the "
            "refusal category and the scope; it carries no message content."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="an ordinary tool call publishes no downgrade signal",
                command=(
                    "Run any Bash command, then list "
                    "'<daemon untracked dir>/context-sidecar/' and verify no "
                    "'<session>.model-downgrade' file was created."
                ),
                description=(
                    "The recorder writes only when the transcript actually holds an "
                    "automatic model-downgrade record, so an undowngraded session "
                    "never accumulates a signal file."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Observe-only: reads a bounded transcript tail and writes nothing "
                    "unless a downgrade record is present."
                ),
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
