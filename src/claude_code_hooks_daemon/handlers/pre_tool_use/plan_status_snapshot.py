"""PlanStatusSnapshotHandler - PreToolUse sensor half of the RV3-n5 fix.

Plan 00466 RV3-n5. ``goal_injection`` (PostToolUse) previously had to
INFER a plan's pre-write status from an Edit's own
``old_string``/``new_string``, or a Write's git HEAD -- both genuinely
ambiguous in narrow but real cases: a bare status value colliding with a
table cell or a plan title (RV3-m1/m2/RV3-n5's C3b, m4d's C3), or HEAD
lagging an uncommitted flip (RV3-m6).

This handler removes the need to infer anything in the common case: it
runs immediately BEFORE the SAME Write/Edit `goal_injection` will see
AFTER it lands, reads the plan's CURRENT (pre-write) status straight off
disk, and records it in the shared, bounded, TTL'd
:mod:`utils.plan_status_snapshot` store, keyed by ``tool_use_id`` (unique
per Claude Code tool invocation, carried by both the PreToolUse and
PostToolUse payloads for the SAME call). ``goal_injection`` consumes the
snapshot as ground truth; its old inference remains as the fallback for
the narrow window where no snapshot exists (a daemon restart between this
handler's Pre dispatch and `goal_injection`'s Post dispatch of the same
call, or a payload carrying no ``tool_use_id`` at all).

Shares its trigger definition with ``goal_injection`` via
:mod:`utils.plan_trigger` (Plan 00466 RV3-n5) -- both handlers must agree
on exactly what counts as "the trigger", or a snapshot recorded under one
definition could be consumed under a different one.

RV4-m4: opt-OUT (``get_default_enabled() -> True``), unlike ``goal_injection``
itself. A static per-handler default cannot read another handler's resolved
config, so genuine "on wherever goal_injection is on" coupling is not
achievable through this mechanism -- the closest correct approximation is to
make this handler's OWN default effectively unconditional, so an operator
who enables ONLY `goal_injection` still gets ground-truth snapshots instead
of silently falling back to inference on every write.

RV5-m1: this genuinely runs -- a file read, a `PlanDoc.parse`, a SHA-256
hash -- on EVERY active plan's `PLAN.md` Write/Edit in EVERY client where
this handler is enabled (the shipped default), whether or not
`goal_injection` is enabled and whether or not a ccy supervisor is armed.
`get_relevance` (below) is NOT a runtime gate: it is consulted only by the
config-optimisation REVIEW (`daemon/cli.py`'s `optimise` command), never by
real dispatch, and `matches()` does not consult it either. The cost per
write is modest (bounded by plan-file size, no network, no lock contention
beyond the shared store's own), and an unconsumed snapshot is bounded by
`max_entries` (RV5-M2), never by time -- but "harmless" previously
overstated this as conditional on `goal_injection` or the supervisor being
armed, which it never was. Never blocks, never denies.
"""

import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.relevance import Relevance, RelevanceContext
from claude_code_hooks_daemon.handlers.utils.would_be_content import would_be_content
from claude_code_hooks_daemon.plan_qa.model import PlanDoc
from claude_code_hooks_daemon.utils.ccy_supervisor import supervisor_relevance
from claude_code_hooks_daemon.utils.path_predicates import path_is_file
from claude_code_hooks_daemon.utils.plan_status_snapshot import (
    hash_plan_text,
    plan_status_snapshots,
)
from claude_code_hooks_daemon.utils.plan_trigger import PlanUnreadable, matched_plan_write_or_edit

logger = logging.getLogger(__name__)


class PlanStatusSnapshotHandler(PreToolUseHandlerBase):
    """Record a PLAN.md's pre-write status for `goal_injection` to consume.

    Sensor only: never blocks, never denies, never surfaces any advisory
    text -- a silent PreToolUse counterpart to `goal_injection`'s
    PostToolUse consumption of what it records.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PLAN_STATUS_SNAPSHOT,
            priority=Priority.PLAN_STATUS_SNAPSHOT,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )

    def get_default_enabled(self) -> bool:
        """RV4-m4: opt-OUT -- see the module docstring. Always-on is the
        closest this static default can get to "on wherever `goal_injection`
        is on", since this method has no access to another handler's
        resolved config."""
        return True

    def get_relevance(self, context: RelevanceContext) -> Relevance:
        """Relevant only under an armed ccy supervisor (mirrors `goal_injection`)."""
        return supervisor_relevance(context)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for a Write/Edit landing on an ACTIVE plan's PLAN.md."""
        return matched_plan_write_or_edit(hook_input, self._project_layout) is not None

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Record the plan's pre-write status and PREDICTED post-image
        hash; always ALLOW.

        A missing file still parses status ``None`` -- itself a valid,
        meaningful ground-truth reading (no Status line: a brand-new plan
        file this Write is about to create for the first time), never
        skipped as though nothing had been recorded. A file that EXISTS
        but cannot be read or decoded is genuinely anomalous (``_read_plan``
        raises ``PlanUnreadable``): recording ``None`` for THAT case would
        confidently assert "no prior status" when the truth is simply
        unknown, so nothing is recorded at all -- `goal_injection` then
        falls back to its own inference for this ``tool_use_id``, exactly
        as it already does for the "no snapshot exists" case.

        RV5-M2: :func:`would_be_content` applies THIS call forward to the
        pre-write text just read -- a known, unambiguous starting point --
        predicting exactly what the file will read after the write lands.
        ``goal_injection`` later hashes the REAL post-edit text and
        compares: no reconstruction, no clock. When the prediction itself
        is not attemptable (an Edit whose ``old_string`` the pre-write text
        does not contain -- Claude Code would fail that call with its own
        error, so there is nothing to predict), nothing is recorded either,
        for the same reason as the unreadable-file case above.
        """
        matched = matched_plan_write_or_edit(hook_input, self._project_layout)
        if matched is None:
            return GatingResult(decision=Decision.ALLOW)
        file_path, _folder = matched
        tool_use_id = str(hook_input.get(HookInputField.TOOL_USE_ID, "") or "")
        if not tool_use_id:
            return GatingResult(decision=Decision.ALLOW)
        try:
            plan_text = self._read_plan(Path(file_path))
        except PlanUnreadable as e:
            logger.warning(
                "plan_status_snapshot: %s; recording no snapshot for tool_use_id=%r "
                "-- goal_injection falls back to its own inference",
                e,
                tool_use_id,
            )
            return GatingResult(decision=Decision.ALLOW)
        status = PlanDoc.parse(plan_text).status if plan_text is not None else None
        predicted = would_be_content(hook_input, current=plan_text)
        if predicted is None:
            logger.warning(
                "plan_status_snapshot: cannot predict the post-write text for "
                "tool_use_id=%r -- recording no snapshot; goal_injection falls "
                "back to its own inference",
                tool_use_id,
            )
            return GatingResult(decision=Decision.ALLOW)
        # RV5-M3: the shared store lives in `utils`, which must not import
        # `plan_qa` -- convert to the plain status VALUE at this boundary
        # instead. `goal_injection` (also outside `utils`) rehydrates it.
        plan_status_snapshots.record(
            tool_use_id, status.value if status is not None else None, hash_plan_text(predicted)
        )
        return GatingResult(decision=Decision.ALLOW)

    @staticmethod
    def _read_plan(path: Path) -> str | None:
        """Read the plan's CURRENT (pre-write) text; ``None`` when no file
        exists yet (the common brand-new-plan case, not an error).

        RV4-m3: the existence check runs INSIDE this try, not before it --
        the raw ``is_file`` stat predicate itself can raise (``EACCES`` on
        an unreadable parent directory, ``ENAMETOOLONG``), and a pre-check
        placed outside the try let exactly that escape as a raw, unwrapped
        ``OSError`` instead of the documented ``PlanUnreadable`` contract.
        ``return None`` here sits in the TRY body, not an except handler,
        so it is not the shape ``audit_error_hiding.py`` flags -- only a
        ``return None`` inside an except clause is. The predicate itself
        goes through :func:`path_is_file` with ``unreadable_means=True``
        (eacces_safe_predicates): a stat failure there is not swallowed --
        it falls through to the READ attempt below, which hits the SAME
        underlying error and is what this method's own ``except`` converts
        to ``PlanUnreadable``.

        Raises:
            PlanUnreadable: the file exists but could not be read
                (``OSError``, including a stat failure on the existence
                check itself) or decoded (``ValueError``, e.g. a non-UTF-8
                ``UnicodeDecodeError``).
        """
        try:
            if not path_is_file(path, unreadable_means=True):
                return None
            return path.read_text(encoding="utf-8")
        except (OSError, ValueError) as e:
            raise PlanUnreadable(f"could not read {path}: {e}") from e

    def get_claude_md(self) -> str | None:
        return (
            "## plan_status_snapshot — pre-write PLAN.md status snapshot\n\n"
            "PreToolUse sensor (never blocks; ships enabled, opt-out — RV4-m4; runs "
            "unconditionally on every matching write, whether or not `goal_injection` "
            "is enabled — RV5-m1). Runs immediately before a `PLAN.md` Write/Edit "
            "under the active plan directory (never `Completed/`), reads the plan's "
            "CURRENT status, and records it plus the SHA-256 of the PREDICTED "
            "post-write text (applying the same Write/Edit forward — RV5-M2), keyed "
            "by `tool_use_id`, in a store bounded by entry count alone (no TTL — a "
            "wall clock can step backward, and it cannot answer 'is this snapshot "
            "still correct' the way a hash comparison can). `goal_injection` "
            "(PostToolUse) consumes it as ground truth in place of inferring the "
            "pre-write status from `old_string`/`new_string` or git HEAD (Plan "
            "00466 RV3-n5) — removing collisions a bare status VALUE could have "
            "with a table cell or a plan title, and git HEAD's own lag behind an "
            "uncommitted flip. The old inference remains as `goal_injection`'s own "
            "fallback for the narrow window where no snapshot exists (a daemon "
            "restart between this handler's dispatch and `goal_injection`'s, or a "
            "payload with no `tool_use_id`), and that fallback use is logged.\n\n"
            "Shares its trigger definition with `goal_injection` via "
            "`utils.plan_trigger`, so the two handlers cannot silently disagree "
            "about what counts as a matching Write/Edit."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="plan_status_snapshot records nothing observable on its own",
                command=(
                    "Use the Edit tool to touch a scratch plan's PLAN.md, then "
                    "verify the tool call is ALLOWed with no advisory text."
                ),
                harness_cannot_produce=(
                    "The assertion is about an in-memory store this handler "
                    "writes to as a side effect, consumed by a DIFFERENT "
                    "PostToolUse handler on the SAME tool call -- the harness "
                    "compares decisions and message patterns only, and has no "
                    "way to inspect in-process state between the two dispatches. "
                    "Covered by "
                    "tests/unit/handlers/pre_tool_use/test_plan_status_snapshot.py."
                ),
                description=(
                    "With plan_status_snapshot enabled, any Write/Edit to an "
                    "active plan's PLAN.md is always ALLOWed and never adds "
                    "context — this handler is a silent sensor."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Observe-only: records an in-memory (session-local, "
                    "bounded, TTL'd) snapshot; writes nothing to disk."
                ),
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
