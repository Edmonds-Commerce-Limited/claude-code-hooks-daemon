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
disk, and records it in the shared, bounded (never TTL'd -- RV5-M2 removed
the time bound entirely; see :mod:`utils.plan_status_snapshot`'s own
docstring) :mod:`utils.plan_status_snapshot` store, keyed by
``tool_use_id`` (unique per Claude Code tool invocation, carried by both
the PreToolUse and PostToolUse payloads for the SAME call). `goal_injection`
consumes the snapshot as ground truth when it is FRESH (RV5-M2: the
predicted post-image hash still matches what this write actually
produced); its old inference remains the fallback otherwise. RV6-m3: that
fallback is not a narrow window -- besides the two genuinely rare cases (a
daemon restart between this handler's Pre dispatch and `goal_injection`'s
Post dispatch of the same call, or a payload carrying no ``tool_use_id``
at all), it is also taken on a STALE snapshot (something rewrote the file
between Pre and Post -- a formatter running after `goal_injection` in the
same chain is one source, which is why `goal_injection`'s own docstring
requires it run first), on NO-PREDICT (this handler could not predict the
post-write text at all, e.g. a curly-quote/straight-quote mismatch in
``old_string``), and whenever the store evicts an orphaned entry under
sustained load. See `goal_injection.GoalInjectionHandler._resolve_transition`
for the full, single list.

Shares its trigger definition with ``goal_injection`` via
:mod:`utils.plan_trigger` (Plan 00466 RV3-n5) -- both handlers must agree
on exactly what counts as "the trigger", or a snapshot recorded under one
definition could be consumed under a different one.

RV4-m4: opt-OUT (``get_default_enabled() -> True``), unlike ``goal_injection``
itself. A static per-handler default cannot read another handler's resolved
config, so genuine "on wherever goal_injection is on" coupling is not
achievable through THAT mechanism -- the closest correct approximation
available to a static default is to make this handler's OWN default
effectively unconditional, so an operator who enables ONLY `goal_injection`
still gets ground-truth snapshots instead of silently falling back to
inference on every write.

RV5-m1/RV6-m1: `matches()` IS gated on `goal_injection`'s resolved config
state (:meth:`PlanStatusSnapshotHandler._goal_injection_enabled`), read via
`utils.config_cache.load_config_cached` -- the RV5-m1 review's claim that
no primitive in this codebase supports that was wrong (five other handlers
already read a resolved config this way) and is corrected here and in
NIGGLES.md. A project running this sensor (the shipped default) with
`goal_injection` off no longer pays the read/`PlanDoc.parse`/SHA-256 cost
on every active plan's `PLAN.md` write -- `get_relevance` (below) remains
NOT a runtime gate (it is consulted only by the config-optimisation REVIEW,
`daemon/cli.py`'s `optimise` command), but `matches()` itself now is. The
cost when `goal_injection` IS enabled is unchanged and modest (bounded by
plan-file size, no network, no lock contention beyond the shared store's
own), and an unconsumed snapshot is bounded by `max_entries` (RV5-M2),
never by time. Never blocks, never denies.
"""

import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.relevance import Relevance, RelevanceContext
from claude_code_hooks_daemon.handlers.utils.would_be_content import would_be_content
from claude_code_hooks_daemon.plan_qa.model import PlanDoc
from claude_code_hooks_daemon.utils.ccy_supervisor import supervisor_relevance
from claude_code_hooks_daemon.utils.config_cache import load_config_cached
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
        # RV8-m2: the last (Config identity, verdict) pair -- `_load_config`
        # returns the SAME object from `load_config_cached` while the file
        # is unchanged, so a matching identity means the mapping build and
        # tag lookup below are already known-good and can be skipped.
        self._goal_injection_verdict_cache: tuple[Config, bool] | None = None

    def get_default_enabled(self) -> bool:
        """RV4-m4: opt-OUT -- see the module docstring. Always-on is the
        closest this static default can get to "on wherever `goal_injection`
        is on", since this method has no access to another handler's
        resolved config."""
        return True

    def get_relevance(self, context: RelevanceContext) -> Relevance:
        """Relevant only under an armed ccy supervisor (mirrors `goal_injection`)."""
        return supervisor_relevance(context)

    def _load_config(self) -> Config:
        """The project's daemon config; bare defaults when it cannot be read.

        Mirrors ``recovery_cron_advisor._load_config``: defaults mean "not
        declared", which for THIS gate (:meth:`_goal_injection_enabled`)
        resolves the same way a config the registry itself cannot parse
        would -- falling back to defaults, under which the gate treats
        ``goal_injection`` as ENABLED. An absent block is registered exactly
        like an explicit ``enabled: true`` (RV7-m1), regardless of
        ``GoalInjectionHandler.get_default_enabled() -> False`` (its own
        opt-in default, which ``register_all`` never consults for a missing
        block) -- bare ``Config()`` defaults present as "no block at all"
        to the gate below, so this is the SAME outcome, not a special case.
        """
        try:
            config_path = ProjectContext.project_root() / ".claude" / "hooks-daemon.yaml"
            return load_config_cached(config_path)
        except (ValidationError, OSError, ValueError, RuntimeError) as exc:
            logger.debug("plan_status_snapshot: config unavailable: %s", exc)
            return Config()

    def _goal_injection_enabled(self) -> bool:
        """RV6-m1/RV7-m1: whether `goal_injection` (PostToolUse) is enabled
        in this project's resolved config -- decided by the SAME predicate
        `register_all` itself uses, so this gate reads the SAME state
        `register_all` did at the daemon's LAST startup (RV7-m1 measured two
        shapes where the earlier hand-rolled reading did not even do that:
        an ABSENT `goal_injection` block, and `disable_tags` covering it).
        It can still disagree with what the daemon is CURRENTLY running,
        because the registry is fixed at startup while this reads the
        config file live -- a config edit not yet followed by a restart is
        exactly that window, and is outside what a static per-event mapping
        can close (RV7-m1's own registry-injected-state option, not taken).

        Gates :meth:`matches` so a project running this sensor with
        `goal_injection` off -- the common case, since this sensor ships
        opt-out and `goal_injection` ships opt-in -- does not pay the
        read/`PlanDoc.parse`/SHA-256 cost on every active plan's `PLAN.md`
        write for a store nothing then consumes (measured ~290 microsec per
        write, `probe_gf6_gate_cost_out.txt`).

        RV8-m2: the verdict is memoised against the resolved `Config`
        object's IDENTITY (:attr:`_goal_injection_verdict_cache`) --
        `_load_config` returns the SAME object from `load_config_cached`
        while the file is unchanged, so rebuilding the mapping and
        re-deciding on every call was paying roughly half of what the
        snapshot this gates exists to save.

        `handlers.registry.handler_is_enabled` is the checklist's own
        predicate for "would `register_all` register this handler" -- it
        reads `config_skip_reason` (absent block means ENABLED, the
        registration default) and `tag_skip_reason` (`enable_tags`/
        `disable_tags`) together, over the same per-event mapping
        `handlers.registry.build_handler_config_mapping` builds for
        `register_all` itself (RV8-m2: moved out of `daemon.cli`, which a
        handler importing from ran the module layering backwards).
        `GoalInjectionHandler.TAGS` (RV8-m2: a class constant, so this no
        longer constructs a throwaway instance just to read its tags) is
        NOT `get_default_enabled() -> False` (opt-in) -- that default is NOT
        consulted here, deliberately: `register_all` never consults it
        either (RV7-m1) -- an absent block is registered exactly like an
        explicit `enabled: true` -- so a gate that honoured the opt-in
        default would disagree with the daemon it is meant to mirror.
        """
        config = self._load_config()
        cached = self._goal_injection_verdict_cache
        if cached is not None and cached[0] is config:
            return cached[1]

        from claude_code_hooks_daemon.handlers.post_tool_use.goal_injection import (
            GoalInjectionHandler,
        )
        from claude_code_hooks_daemon.handlers.registry import (
            build_handler_config_mapping,
            handler_is_enabled,
        )

        mapping = build_handler_config_mapping(config)
        event_config = mapping.get("post_tool_use", {})
        verdict = handler_is_enabled(
            event_config, HandlerID.GOAL_INJECTION.config_key, GoalInjectionHandler.TAGS
        )
        self._goal_injection_verdict_cache = (config, verdict)
        return verdict

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for a Write/Edit landing on an ACTIVE plan's PLAN.md, when
        `goal_injection` is enabled in this project's config (RV6-m1).

        RV7-M1: the cheap trigger match runs FIRST -- `matched_plan_write_or_edit`
        is a tuple membership test plus a path check, no file I/O -- so a
        non-plan event (the overwhelming majority: every Bash, Read, Grep,
        and every Write/Edit outside the active plan directory) never reaches
        the config-backed gate at all. Before this ordering, EVERY PreToolUse
        event paid the gate's `Path.resolve()`/`stat()`/lock, and a broken
        config cost a full re-parse (~80 ms) per event rather than per plan
        write.
        """
        if matched_plan_write_or_edit(hook_input, self._project_layout) is None:
            return False
        return self._goal_injection_enabled()

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
            "PreToolUse sensor (never blocks; ships enabled, opt-out — RV4-m4; "
            "`matches()` is gated on `goal_injection`'s resolved config state — "
            "RV6-m1 — so it only runs a matching write's read/parse/hash when "
            "`goal_injection` is actually enabled). Runs immediately before a "
            "`PLAN.md` Write/Edit "
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
            "fallback whenever no FRESH snapshot exists for a call (RV6-m3: not "
            "just a daemon restart or a payload with no `tool_use_id` — also a "
            "prediction that could not be made, a store eviction under load, or a "
            "snapshot rejected as stale because something rewrote the file before "
            "`goal_injection` read it; see "
            "`GoalInjectionHandler._resolve_transition`'s docstring for the full "
            "list), and that fallback use is logged.\n\n"
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
                    "Observe-only: records an in-memory (process-local, "
                    "bounded, no TTL) snapshot; writes nothing to disk."
                ),
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
