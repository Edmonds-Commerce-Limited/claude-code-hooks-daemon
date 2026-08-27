"""ModelFallbackDetectorHandler - loud alert when a session runs a substituted model.

Plan 00278 Phase 3/3b. Some caller models carry an API-side content safety
classifier; when a request trips it, the platform silently substitutes a
different model for the REMAINDER of the session (``scope: "session"``). The
switch is announced once, in one transcript line, and never again — a measured
field incident ran ~5.5 hours degraded before a human noticed.

This SessionStart handler closes that observability gap the same way
``project_handler_load_checker`` closes the silently-skipped-handler gap: it
reads the record the platform ALREADY writes (the transcript JSONL's
``subtype: "model_refusal_fallback"`` record, corroborated by assistant-message
``content[].type == "fallback"`` blocks), and injects a loud
PROTECTION-DEGRADED-style advisory naming the original model, the fallback
model, and the refusal category. Model-agnostic: it keys on the record shape,
never on model names.

It ALSO writes a diagnostic snapshot — the fallback record(s) plus a bounded
window of the preceding transcript records, passed through the secret-word
redaction utility — so a project can diagnose WHY it was flagged and tune its
delegation config (``flaggable_work_advisor`` path globs / topic terms).
Snapshot failures degrade to a mention in the advisory, never an exception.

Advisory only; fail-silent per malformed transcript record. Dedupe state is
PERSISTED to one JSON state file per project (survives a daemon restart —
without this, every restart re-advised the full alert wall and re-wrote a
diagnostic snapshot for every historical record, including recovered ones):
an ACTIVE record re-advises once per (session, identity) across restarts; a
RECOVERED record is noted at most once EVER, across all sessions; and each
distinct record's diagnostic snapshot is written at most once EVER.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.utils import secret_redaction

# Module-level aliases so tests can monkeypatch this module's own names, and
# so the snapshot path has exactly one redaction entry point.
get_active_secret_terms = secret_redaction.get_active_secret_terms
redact_text = secret_redaction.redact_text

logger = logging.getLogger(__name__)

_SESSION_START_EVENT: Final[str] = "SessionStart"

# ── Transcript record shapes (see the Plan 00278 field report) ──────────────
_KEY_SUBTYPE: Final[str] = "subtype"
_FALLBACK_SUBTYPE: Final[str] = "model_refusal_fallback"
_KEY_MESSAGE: Final[str] = "message"
_KEY_CONTENT: Final[str] = "content"
_KEY_TYPE: Final[str] = "type"
_FALLBACK_BLOCK_TYPE: Final[str] = "fallback"
_KEY_ORIGINAL_MODEL: Final[str] = "originalModel"
_KEY_FALLBACK_MODEL: Final[str] = "fallbackModel"
_KEY_REFUSAL_CATEGORY: Final[str] = "apiRefusalCategory"
_KEY_SCOPE: Final[str] = "scope"
_KEY_TIMESTAMP: Final[str] = "timestamp"
_KEY_FROM: Final[str] = "from"
_KEY_TO: Final[str] = "to"
_KEY_MODEL: Final[str] = "model"

# Cheap substring pre-filter: only lines that can possibly hold a fallback
# record are json-parsed, so a large transcript stays a linear string scan.
_PREFILTER_TOKENS: Final[tuple[str, ...]] = (_FALLBACK_SUBTYPE, f'"{_FALLBACK_BLOCK_TYPE}"')

# Cheap substring pre-filter for assistant-message model tracking, used to
# decide whether a fallback has since RECOVERED (a later assistant message
# is back on the original model).
_ASSISTANT_TOKEN: Final[str] = '"assistant"'
_KEY_ROLE: Final[str] = "role"
_ROLE_ASSISTANT: Final[str] = "assistant"

_UNKNOWN_VALUE: Final[str] = "unknown"

# ── Snapshot defaults (options injected by the registry as _<option>) ───────
_DEFAULT_SNAPSHOT_ENABLED: Final[bool] = True
_DEFAULT_SNAPSHOT_DIR: Final[str] = "untracked/reports"
_DEFAULT_SNAPSHOT_WINDOW_RECORDS: Final[int] = 20
_SNAPSHOT_FILE_PREFIX: Final[str] = "model-fallback-snapshot"
_SNAPSHOT_TIMESTAMP_FORMAT: Final[str] = "%Y-%m-%d-%H%M%S"

# Bound the advised-record memory so a long-lived daemon cannot leak across
# many sessions (same FIFO-eviction shape as command_hints' fire-state map).
_MAX_ADVISED_KEYS: Final[int] = 512

# ── Persisted dedupe state (survives a daemon restart) ──────────────────────
_STATE_SUBDIR: Final[str] = "model-fallback-detector"
_STATE_FILENAME: Final[str] = "advised-state.json"
_STATE_KEY_ADVISED: Final[str] = "advised"
_STATE_KEY_RECOVERED_NOTED: Final[str] = "recovered_noted"
_STATE_KEY_SNAPSHOTTED: Final[str] = "snapshotted"


@dataclass(frozen=True)
class _FallbackRecord:
    """One detected fallback event, normalised from either record shape."""

    original_model: str
    fallback_model: str
    category: str
    scope: str
    timestamp: str
    identity: str
    raw_line: str
    preceding_lines: tuple[str, ...]
    line_index: int


def _record_identity(payload: dict[str, Any], raw_line: str) -> str:
    """A deterministic identity for one fallback record.

    Prefers the record's own distinguishing fields (timestamp + model pair);
    falls back to a digest of the raw line so two field-identical records on
    different lines still deduplicate deterministically.
    """
    timestamp = str(payload.get(_KEY_TIMESTAMP, "") or "")
    if timestamp:
        return "|".join(
            (
                timestamp,
                str(payload.get(_KEY_ORIGINAL_MODEL, "") or ""),
                str(payload.get(_KEY_FALLBACK_MODEL, "") or ""),
            )
        )
    # MD5 as a cheap content fingerprint, not a security control.
    return hashlib.md5(raw_line.encode("utf-8"), usedforsecurity=False).hexdigest()


def _extract_fallback_block(payload: dict[str, Any]) -> dict[str, Any] | None:
    """The first assistant-message ``fallback`` content block, if any."""
    message = payload.get(_KEY_MESSAGE)
    if not isinstance(message, dict):
        return None
    content = message.get(_KEY_CONTENT)
    if not isinstance(content, list):
        return None
    for block in content:
        if isinstance(block, dict) and block.get(_KEY_TYPE) == _FALLBACK_BLOCK_TYPE:
            return block
    return None


def _block_model(block: dict[str, Any], key: str) -> str:
    """The model name inside a fallback block's ``from``/``to`` object."""
    endpoint = block.get(key)
    if isinstance(endpoint, dict):
        return str(endpoint.get(_KEY_MODEL, _UNKNOWN_VALUE) or _UNKNOWN_VALUE)
    return _UNKNOWN_VALUE


class ModelFallbackDetectorHandler(SessionStartHandlerBase):
    """Detect a safety-triggered model fallback from the session transcript.

    Advisory only, opt-in (disabled by default), fail-silent on every
    per-record parse failure. Dedupe state is PERSISTED to disk (one JSON
    file per project) so it survives a daemon restart: an ACTIVE record
    re-advises once per (session, identity); a RECOVERED record is noted at
    most once EVER, across every session; and each distinct record's
    diagnostic snapshot is written at most once EVER.

    Ships DISABLED (Plan 00278): a SessionStart scan reports a fallback that
    already happened, so for a project that never does safeguard-flaggable work
    it essentially never fires, and when it does it is noisy (one snapshot file
    per distinct record). The continuous "am I downgraded?" signal is better
    served by the ``downgrade_indicator`` status-line handler, which self-detects
    a live downgrade on every render. This detector's unique value is the
    secret-redacted diagnostic snapshot for tuning delegation config, so it is
    left for a project (like this daemon's own dev estate) to opt into.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.MODEL_FALLBACK_DETECTOR,
            priority=Priority.MODEL_FALLBACK_DETECTOR,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ENVIRONMENT,
            ],
        )
        # Options — injected by the registry via setattr; typed and defaulted
        # here so mypy sees real attributes (command_hints convention).
        self._snapshot_enabled: bool = _DEFAULT_SNAPSHOT_ENABLED
        self._snapshot_dir: str = _DEFAULT_SNAPSHOT_DIR
        self._snapshot_window_records: int = _DEFAULT_SNAPSHOT_WINDOW_RECORDS

        # (session_id, record identity) keys already advised — bounded FIFO.
        # Persisted to disk; see _load_state/_save_state.
        self._advised: dict[tuple[str, str], None] = {}
        # Bare record identities already noted as RECOVERED — once ever.
        self._recovered_noted: dict[str, None] = {}
        # Bare record identities already snapshotted — once ever.
        self._snapshotted: dict[str, None] = {}

    def get_default_enabled(self) -> bool:
        """Opt-in: a SessionStart scan is a stale, noisy signal for most
        projects; the ``downgrade_indicator`` status line covers the live one
        (Plan 00278)."""
        return False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Fire on every SessionStart carrying a transcript path.

        Resumed sessions fire too — a degraded session that resumes is still
        degraded, and the once-per-record state keeps this from spamming.
        """
        if not isinstance(hook_input, dict):
            return False
        if hook_input.get(HookInputField.HOOK_EVENT_NAME) != _SESSION_START_EVENT:
            return False
        return bool(hook_input.get(HookInputField.TRANSCRIPT_PATH))

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Scan the transcript; advise loudly on any unreported fallback record."""
        try:
            transcript_path = str(hook_input.get(HookInputField.TRANSCRIPT_PATH, "") or "")
            session_id = str(hook_input.get(HookInputField.SESSION_ID, "") or _UNKNOWN_VALUE)

            self._load_state()

            records, assistant_models = self._scan_transcript(Path(transcript_path))
            new_records = [
                record for record in records if self._mark_advised(session_id, record.identity)
            ]
            if not new_records:
                return AdvisoryResult(decision=Decision.ALLOW, context=[])

            active_records = [
                record for record in new_records if not self._is_recovered(record, assistant_models)
            ]
            candidate_recovered = [record for record in new_records if record not in active_records]
            # A RECOVERED record is noted at most once EVER, across every
            # session — unlike an active record, it never needs re-surfacing.
            recovered_records = [
                record
                for record in candidate_recovered
                if self._mark_recovered_noted(record.identity)
            ]

            # Each distinct record's diagnostic snapshot is written at most
            # once EVER, even across daemon restarts and different sessions.
            snapshot_targets = [
                record
                for record in (*active_records, *recovered_records)
                if self._mark_snapshotted(record.identity)
            ]
            snapshot_notes: list[str] = []
            if self._snapshot_enabled and snapshot_targets:
                snapshot_notes = self._write_snapshots(snapshot_targets, transcript_path)

            context: list[str] = []
            if active_records:
                context.extend(self._build_alert(active_records, snapshot_notes))
            if recovered_records:
                if context:
                    context.append("")
                # The recovered notice covers the shared snapshot notes only
                # when nothing active already surfaced them.
                context.extend(
                    self._build_recovered_notice(
                        recovered_records, [] if active_records else snapshot_notes
                    )
                )

            self._save_state()
            return AdvisoryResult(decision=Decision.ALLOW, context=context)
        except Exception as exc:
            # Advisory handler: any failure degrades to silence, never blocks
            # a session start.
            logger.error("model_fallback_detector failed: %s", exc, exc_info=True)
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

    # ── Transcript scanning ─────────────────────────────────────────────────

    def _scan_transcript(self, path: Path) -> tuple[list[_FallbackRecord], list[tuple[int, str]]]:
        """Stream the transcript, collecting fallback records + assistant models.

        Missing/unreadable file → empty results. Malformed lines are skipped
        fail-silent per record. Every line feeds the bounded preceding-record
        window; only pre-filtered candidate lines are json-parsed.

        Also returns ``(line_index, model)`` for every assistant message that
        carries a ``message.model`` field, in transcript order — this is what
        lets a fallback record be classified as RECOVERED when a later
        assistant message is back on the original model.
        """
        window_size = max(0, int(self._snapshot_window_records))
        window: deque[str] = deque(maxlen=window_size or 1)
        found: list[_FallbackRecord] = []
        assistant_models: list[tuple[int, str]] = []
        try:
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                for line_index, raw_line in enumerate(stream):
                    line = raw_line.strip()
                    if not line:
                        continue
                    if any(token in line for token in _PREFILTER_TOKENS):
                        record = self._parse_candidate(
                            line, line_index, tuple(window) if window_size else ()
                        )
                        if record is not None:
                            found.append(record)
                    elif _ASSISTANT_TOKEN in line:
                        model = self._assistant_message_model(line)
                        if model is not None:
                            assistant_models.append((line_index, model))
                    window.append(line)
        except OSError as exc:
            logger.debug("model_fallback_detector: cannot read transcript %s: %s", path, exc)
        return found, assistant_models

    @staticmethod
    def _assistant_message_model(line: str) -> str | None:
        """The ``message.model`` of an assistant-role transcript line, if any."""
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        message = payload.get(_KEY_MESSAGE)
        if not isinstance(message, dict) or message.get(_KEY_ROLE) != _ROLE_ASSISTANT:
            return None
        model = message.get(_KEY_MODEL)
        return str(model) if model else None

    def _parse_candidate(
        self, line: str, line_index: int, preceding: tuple[str, ...]
    ) -> _FallbackRecord | None:
        """Parse one candidate line into a fallback record, or ``None``."""
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None

        if payload.get(_KEY_SUBTYPE) == _FALLBACK_SUBTYPE:
            return _FallbackRecord(
                original_model=str(payload.get(_KEY_ORIGINAL_MODEL, _UNKNOWN_VALUE) or ""),
                fallback_model=str(payload.get(_KEY_FALLBACK_MODEL, _UNKNOWN_VALUE) or ""),
                category=str(payload.get(_KEY_REFUSAL_CATEGORY, _UNKNOWN_VALUE) or ""),
                scope=str(payload.get(_KEY_SCOPE, _UNKNOWN_VALUE) or ""),
                timestamp=str(payload.get(_KEY_TIMESTAMP, "") or ""),
                identity=_record_identity(payload, line),
                raw_line=line,
                preceding_lines=preceding,
                line_index=line_index,
            )

        block = _extract_fallback_block(payload)
        if block is not None:
            return _FallbackRecord(
                original_model=_block_model(block, _KEY_FROM),
                fallback_model=_block_model(block, _KEY_TO),
                category=_UNKNOWN_VALUE,
                scope=_UNKNOWN_VALUE,
                timestamp=str(payload.get(_KEY_TIMESTAMP, "") or ""),
                identity=_record_identity(payload, line),
                raw_line=line,
                preceding_lines=preceding,
                line_index=line_index,
            )
        return None

    @staticmethod
    def _is_recovered(record: _FallbackRecord, assistant_models: list[tuple[int, str]]) -> bool:
        """Whether a LATER assistant message is back on the original model.

        A record with an unknown/empty original model can never be proven
        recovered — it stays ACTIVE, the conservative (louder) default.
        """
        if not record.original_model or record.original_model == _UNKNOWN_VALUE:
            return False
        return any(
            index > record.line_index and model == record.original_model
            for index, model in assistant_models
        )

    # ── Once-per-session-per-record state ───────────────────────────────────

    def _mark_advised(self, session_id: str, identity: str) -> bool:
        """True (and record it) the FIRST time this key is seen; False after."""
        key = (session_id, identity)
        if key in self._advised:
            return False
        if len(self._advised) >= _MAX_ADVISED_KEYS:
            del self._advised[next(iter(self._advised))]
        self._advised[key] = None
        return True

    def _mark_recovered_noted(self, identity: str) -> bool:
        """True (and record it) the first time a RECOVERED identity is seen.

        Unlike ``_mark_advised``, this is keyed on the bare identity alone —
        a recovered record is noted at most once EVER, across every session.
        """
        if identity in self._recovered_noted:
            return False
        if len(self._recovered_noted) >= _MAX_ADVISED_KEYS:
            del self._recovered_noted[next(iter(self._recovered_noted))]
        self._recovered_noted[identity] = None
        return True

    def _mark_snapshotted(self, identity: str) -> bool:
        """True (and record it) the first time a snapshot is attempted for
        this identity. Each distinct record's diagnostic snapshot is written
        at most once EVER, even across daemon restarts and sessions."""
        if identity in self._snapshotted:
            return False
        if len(self._snapshotted) >= _MAX_ADVISED_KEYS:
            del self._snapshotted[next(iter(self._snapshotted))]
        self._snapshotted[identity] = None
        return True

    # ── Persisted dedupe state (survives a daemon restart) ─────────────────

    def _resolve_state_file(self) -> Path | None:
        """The on-disk dedupe-state file path, or ``None`` if unresolvable.

        Best-effort: without a live ``ProjectContext`` (unit tests, CLI
        probes) dedupe falls back to in-memory-only for this process, never
        raising — persistence is an enhancement, not a hard requirement.
        """
        try:
            from claude_code_hooks_daemon.core.project_context import ProjectContext

            return ProjectContext.daemon_untracked_dir() / _STATE_SUBDIR / _STATE_FILENAME
        except (RuntimeError, OSError) as exc:
            logger.debug("model_fallback_detector: no project root for state file (%s)", exc)
            return None

    def _load_state(self) -> None:
        """Merge persisted dedupe state into the in-memory dicts.

        Fail-silent: a missing, unreadable, or malformed state file is
        treated as empty prior state — never raises, matching this
        handler's advisory fail-silent contract.
        """
        path = self._resolve_state_file()
        if path is None:
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.debug("model_fallback_detector: no persisted state yet (%s)", exc)
            return
        try:
            data: Any = json.loads(text)
        except ValueError as exc:
            logger.debug("model_fallback_detector: corrupt state file, ignoring (%s)", exc)
            return
        if not isinstance(data, dict):
            return

        advised = data.get(_STATE_KEY_ADVISED)
        if isinstance(advised, list):
            for pair in advised:
                if isinstance(pair, list) and len(pair) == 2:
                    self._advised.setdefault((str(pair[0]), str(pair[1])), None)
        recovered_noted = data.get(_STATE_KEY_RECOVERED_NOTED)
        if isinstance(recovered_noted, list):
            for identity in recovered_noted:
                if isinstance(identity, str):
                    self._recovered_noted.setdefault(identity, None)
        snapshotted = data.get(_STATE_KEY_SNAPSHOTTED)
        if isinstance(snapshotted, list):
            for identity in snapshotted:
                if isinstance(identity, str):
                    self._snapshotted.setdefault(identity, None)

    def _save_state(self) -> None:
        """Atomically persist the in-memory dedupe dicts to disk.

        Best-effort: a write failure (unwritable directory, disk full) is
        logged and swallowed — losing persistence for this call degrades to
        in-memory-only dedupe, never blocks a session start.
        """
        path = self._resolve_state_file()
        if path is None:
            return
        payload: dict[str, Any] = {
            _STATE_KEY_ADVISED: [[session, identity] for session, identity in self._advised],
            _STATE_KEY_RECOVERED_NOTED: list(self._recovered_noted),
            _STATE_KEY_SNAPSHOTTED: list(self._snapshotted),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.parent / f".{path.name}.{os.getpid()}.tmp"
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            tmp_path.replace(path)
        except OSError as exc:
            logger.warning("model_fallback_detector: could not persist dedupe state: %s", exc)

    # ── Advisory rendering ──────────────────────────────────────────────────

    @staticmethod
    def _build_alert(records: list[_FallbackRecord], snapshot_notes: list[str]) -> list[str]:
        lines: list[str] = [
            "🚨 MODEL FALLBACK DETECTED — SESSION IS RUNNING A SUBSTITUTED MODEL 🚨",
            "",
            "The platform's safety classifier flagged a turn and silently switched "
            "this session's model. The switch is scope: session — it will NOT "
            "recover on its own; every subsequent turn runs the fallback model "
            "until the session is restarted.",
            "",
        ]
        for record in records:
            detail = (
                f"  - {record.original_model or _UNKNOWN_VALUE} → "
                f"{record.fallback_model or _UNKNOWN_VALUE}"
                f" (category: {record.category or _UNKNOWN_VALUE}"
            )
            if record.timestamp:
                detail += f", at {record.timestamp}"
            detail += ")"
            lines.append(detail)
        lines.extend(
            [
                "",
                "ACTION: tell the human, and restart the session to clear the "
                "fallback. Prevention: delegate safeguard-flaggable work to the "
                "quarantine subagent BEFORE reading it (see flaggable_work_advisor).",
            ]
        )
        if snapshot_notes:
            lines.append("")
            lines.extend(snapshot_notes)
        return lines

    @staticmethod
    def _build_recovered_notice(
        records: list[_FallbackRecord], snapshot_notes: list[str]
    ) -> list[str]:
        """A soft, non-alarming notice for a fallback that has since recovered."""
        lines: list[str] = [
            "A past model fallback occurred and has since recovered — no " "action needed.",
            "",
        ]
        for record in records:
            detail = (
                f"  - {record.original_model or _UNKNOWN_VALUE} → "
                f"{record.fallback_model or _UNKNOWN_VALUE}"
                f" (category: {record.category or _UNKNOWN_VALUE}"
            )
            if record.timestamp:
                detail += f", at {record.timestamp}"
            detail += (
                f"); a later assistant turn returned to "
                f"{record.original_model or _UNKNOWN_VALUE}, so this session is "
                "no longer degraded"
            )
            lines.append(detail)
        if snapshot_notes:
            lines.append("")
            lines.extend(snapshot_notes)
        return lines

    # ── Snapshot writing ────────────────────────────────────────────────────

    def _resolve_snapshot_dir(self) -> Path:
        """The snapshot directory, resolved against the project root.

        Falls back to the current working directory when ``ProjectContext``
        is not initialised (unit tests, CLI probes) — snapshotting is
        best-effort diagnostics, never worth failing over.
        """
        configured = Path(self._snapshot_dir or _DEFAULT_SNAPSHOT_DIR).expanduser()
        if configured.is_absolute():
            return configured
        try:
            from claude_code_hooks_daemon.core.project_context import ProjectContext

            return ProjectContext.project_root() / configured
        except (RuntimeError, OSError) as exc:
            logger.debug("model_fallback_detector: no project root (%s); using cwd", exc)
            return Path.cwd() / configured

    def _write_snapshots(self, records: list[_FallbackRecord], transcript_path: str) -> list[str]:
        """Write one redacted diagnostic snapshot per record.

        Returns advisory note lines — the written paths on success, or a
        degradation notice on failure. Never raises.
        """
        notes: list[str] = []
        directory = self._resolve_snapshot_dir()
        terms = get_active_secret_terms()
        stamp = datetime.now().strftime(_SNAPSHOT_TIMESTAMP_FORMAT)
        for index, record in enumerate(records, start=1):
            target = directory / f"{_SNAPSHOT_FILE_PREFIX}-{stamp}-{index}.md"
            try:
                directory.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    self._render_snapshot(record, transcript_path, terms),
                    encoding="utf-8",
                )
                notes.append(f"Diagnostic snapshot written: {target}")
            except OSError as exc:
                logger.warning("model_fallback_detector: snapshot write failed: %s", exc)
                notes.append(
                    f"NOTE: the diagnostic snapshot could not be written ({exc}); "
                    "the advisory above is the only record of this detection."
                )
        return notes

    @staticmethod
    def _render_snapshot(
        record: _FallbackRecord, transcript_path: str, terms: tuple[str, ...]
    ) -> str:
        preceding = "\n".join(record.preceding_lines)
        body = (
            "# Model-fallback diagnostic snapshot\n\n"
            f"Transcript: `{transcript_path}`\n\n"
            "Purpose: show WHAT the safety classifier reacted to, so this "
            "project can tune its delegation config "
            "(`flaggable_work_advisor` path globs / topic terms) and keep "
            "flaggable material out of the main context.\n\n"
            "## Fallback record\n\n"
            "```json\n"
            f"{record.raw_line}\n"
            "```\n\n"
            f"## Preceding transcript records (up to {len(record.preceding_lines)})\n\n"
            "```json\n"
            f"{preceding}\n"
            "```\n"
        )
        return redact_text(body, terms)

    # ── Guidance surfaces ───────────────────────────────────────────────────

    def get_claude_md(self) -> str | None:
        return (
            "## model_fallback_detector — silent model substitution is surfaced\n\n"
            "At session start the transcript is scanned for the platform's own "
            "`model_refusal_fallback` record, AND for every subsequent assistant "
            "message's model — so the advisory can tell an ACTIVE fallback from "
            "one that has already RECOVERED.\n\n"
            "**`🚨 MODEL FALLBACK DETECTED 🚨` (ACTIVE — no later assistant turn "
            "returned to the original model)**:\n\n"
            "1. **Tell the human immediately** — the substitution is otherwise "
            "silent, and a session has run degraded for hours unnoticed.\n"
            "2. **A session restart is the only cure** — while active, the "
            "fallback is session-sticky; keep working only on the human's "
            "say-so.\n"
            "3. **Read the diagnostic snapshot** (path named in the advisory, "
            "default `untracked/reports/`): it holds the fallback record plus "
            "the preceding transcript window, secret-redacted, so the project "
            "can tune its `flaggable_work_advisor` delegation config to stop "
            "the recurrence.\n\n"
            "**A soft, non-alarming notice (no 🚨, no restart instruction) means "
            "RECOVERED** — a later assistant turn was already back on the "
            "original model before this advisory ever fired. No action is "
            "needed; the diagnostic snapshot is still written for tuning "
            "purposes.\n\n"
            "Dedupe state is PERSISTED to disk and survives a daemon "
            "restart: an ACTIVE record re-advises once per (session, "
            "identity); a RECOVERED record is noted at most once EVER, "
            "across every session; each distinct record's diagnostic "
            "snapshot is written at most once EVER.\n\n"
            "Options under `handlers.session_start.model_fallback_detector."
            "options`: `snapshot_enabled` (default true), `snapshot_dir` "
            "(default `untracked/reports`), `snapshot_window_records` (default "
            "20). Snapshots are never auto-committed."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="model fallback detector - alerts on a recorded fallback",
                command='echo "session start advisory"',
                description=(
                    "When the session transcript contains a model_refusal_fallback "
                    "record, a new session shows a MODEL FALLBACK DETECTED alert "
                    "naming the original and fallback models and the refusal "
                    "category, plus the diagnostic snapshot path."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"MODEL FALLBACK DETECTED"],
                safety_notes=(
                    "Advisory only. Requires a transcript carrying a real "
                    "fallback record, which cannot be synthesised safely in a "
                    "live session — verified by unit tests otherwise."
                ),
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event with a fallback record in the transcript",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
