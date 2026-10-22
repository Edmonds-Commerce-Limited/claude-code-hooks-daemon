"""The goal-loop detector's pure logic (Plan 00501 Tasks 6.1 and 6.2).

A goal loop is a session that keeps stopping with ``STOPPING BECAUSE:`` while
Claude Code's goal evaluator keeps answering "not met", so the goal re-arms the
turn and the agent stops again, with nothing a human said in between. This
module reads that pattern out of the transcript; the ``goal_loop_detector``
Stop handler owns the per-session state and the logging.

* :func:`read_new_lines` reads a transcript from a byte checkpoint. The first
  sight of a session reads only a bounded tail, so a daemon restart never
  rescans a large transcript; the checkpoint only ever advances to the last
  complete line.
* :func:`extract_events` turns transcript records into :class:`LoopEvent` s:
  a ``STOPPING BECAUSE:`` stop, an unmet goal evaluation (``goal_status``
  ``met:false`` with no ``sentinel``), a goal met or cleared, and a genuine
  human prompt (the ``is_genuine_human_prompt`` classifier; ``isMeta`` records
  and tool results are never prompts).
* :class:`CycleRing` counts cycles -- a stop followed by an unmet evaluation
  with no human prompt between -- inside a time window. A human prompt, a goal
  met or cleared, or a repository change empties it, with the cause.
* :func:`assess` compares the ring with the thresholds. Stop-text similarity
  goes into the evidence only; it is never a fire condition (ruling 08).
* :func:`repo_fingerprint` hashes ``HEAD`` plus ``git status --porcelain -uno``,
  without journal files and untracked scratch.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import Any, Final, Protocol

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.session_modes import is_genuine_human_prompt

logger = logging.getLogger(__name__)

_SECONDS_PER_MINUTE: Final[int] = 60
_SECONDS_PER_HOUR: Final[int] = 3600

#: Similarity is measured on at most this many characters of each stop text,
#: which bounds its cost on a long stop message.
_SIMILARITY_CHARS: Final[int] = 2000

#: Fingerprint hex digits kept; enough to tell trees apart in a log line.
_FINGERPRINT_CHARS: Final[int] = 12

#: Porcelain paths the fingerprint ignores: plan journals and untracked scratch
#: change while an agent is looping without being progress (Plan 00501 Goals).
_JOURNAL_SEGMENT: Final[str] = "/JOURNAL/"
_UNTRACKED_PREFIX: Final[str] = "untracked/"
_PORCELAIN_PATH_START: Final[int] = 3
_RENAME_ARROW: Final[str] = " -> "

_RECORD_TYPE: Final[str] = "type"
_RECORD_TIMESTAMP: Final[str] = "timestamp"
_RECORD_MESSAGE: Final[str] = "message"
_RECORD_CONTENT: Final[str] = "content"
_RECORD_IS_META: Final[str] = "isMeta"
_RECORD_ATTACHMENT: Final[str] = "attachment"
_TYPE_USER: Final[str] = "user"
_TYPE_ASSISTANT: Final[str] = "assistant"
_TYPE_ATTACHMENT: Final[str] = "attachment"
_TYPE_TEXT: Final[str] = "text"
_TYPE_GOAL_STATUS: Final[str] = "goal_status"
_FIELD_TEXT: Final[str] = "text"
_FIELD_MET: Final[str] = "met"
_FIELD_SENTINEL: Final[str] = "sentinel"

_OPTION_MODE: Final[str] = "mode"
_OPTION_CYCLE_THRESHOLD: Final[str] = "cycle_threshold"
_OPTION_DECLARED_THRESHOLD: Final[str] = "declared_cycle_threshold"
_OPTION_WINDOW_MINUTES: Final[str] = "window_minutes"
_OPTION_BLOCKED_HOURS: Final[str] = "blocked_hours"
_INT_OPTIONS: Final[tuple[str, ...]] = (
    _OPTION_CYCLE_THRESHOLD,
    _OPTION_DECLARED_THRESHOLD,
    _OPTION_WINDOW_MINUTES,
)


class EventKind(StrEnum):
    """What one transcript record means to the detector."""

    STOP = "stop"
    UNMET = "unmet"
    GOAL_MET = "goal-met"
    GOAL_CLEARED = "goal-cleared"
    HUMAN = "human"


@dataclass(frozen=True, slots=True)
class LoopEvent:
    """One detector-relevant transcript record.

    Attributes:
        kind: What the record is.
        at: Its timestamp, epoch seconds.
        text: A stop's text from the ``STOPPING BECAUSE:`` prefix on, else empty.
        declared: Whether a stop declares it is blocked only on the human.
    """

    kind: EventKind
    at: float
    text: str = ""
    declared: bool = False


@dataclass(frozen=True, slots=True)
class Extraction:
    """The events read from a batch of lines, and how many lines were unusable."""

    events: tuple[LoopEvent, ...]
    skipped: int


def _timestamp(record: Mapping[str, Any]) -> float:
    """The record's timestamp in epoch seconds.

    Raises:
        ValueError: The record has no timestamp string, or it is not ISO 8601.
    """
    raw = record.get(_RECORD_TIMESTAMP)
    if not isinstance(raw, str):
        raise ValueError(f"record has no timestamp string: {raw!r}")
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()


def _text_blocks(content: object) -> str | None:
    """The joined text of a content list holding only text blocks, else None."""
    if not isinstance(content, list) or not content:
        return None
    texts: list[str] = []
    for block in content:
        if not isinstance(block, dict) or block.get(_RECORD_TYPE) != _TYPE_TEXT:
            return None
        text = block.get(_FIELD_TEXT)
        if not isinstance(text, str):
            return None
        texts.append(text)
    return "\n".join(texts)


def _assistant_text(content: object) -> str:
    """Every text block of an assistant message, joined; other blocks skipped."""
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block[_FIELD_TEXT])
        for block in content
        if isinstance(block, dict)
        and block.get(_RECORD_TYPE) == _TYPE_TEXT
        and isinstance(block.get(_FIELD_TEXT), str)
    )


def _classify(
    record: Mapping[str, Any],
    *,
    stop_prefix: str,
    declares_blocked: Callable[[str], bool],
) -> tuple[EventKind, str, bool] | None:
    """The event a record carries (kind, stop text, declared), or None."""
    record_type = record.get(_RECORD_TYPE)
    if record_type == _TYPE_ATTACHMENT:
        attachment = record.get(_RECORD_ATTACHMENT)
        if not isinstance(attachment, dict) or attachment.get(_RECORD_TYPE) != _TYPE_GOAL_STATUS:
            return None
        met = attachment.get(_FIELD_MET)
        if attachment.get(_FIELD_SENTINEL) is True:
            # Snapshots (goal set, compaction, skill load) are not verdicts; a met
            # snapshot is what ``/goal clear`` writes.
            return (EventKind.GOAL_CLEARED, "", False) if met is True else None
        if met is False:
            return (EventKind.UNMET, "", False)
        if met is True:
            return (EventKind.GOAL_MET, "", False)
        return None
    message = record.get(_RECORD_MESSAGE)
    if not isinstance(message, dict):
        return None
    content = message.get(_RECORD_CONTENT)
    if record_type == _TYPE_USER:
        if record.get(_RECORD_IS_META) is True:
            return None
        prompt = content if isinstance(content, str) else _text_blocks(content)
        if prompt is not None and is_genuine_human_prompt(prompt):
            return (EventKind.HUMAN, "", False)
        return None
    if record_type == _TYPE_ASSISTANT:
        text = _assistant_text(content)
        start = text.find(stop_prefix)
        if start < 0:
            return None
        stop_text = text[start:]
        return (EventKind.STOP, stop_text, declares_blocked(stop_text))
    return None


def extract_events(
    lines: Iterable[str],
    *,
    stop_prefix: str,
    declares_blocked: Callable[[str], bool],
) -> Extraction:
    """Read the detector's events out of transcript JSON lines.

    Args:
        lines: Transcript lines, each one JSON record; blank lines are ignored.
        stop_prefix: The explained-stop prefix (``STOPPING BECAUSE:``).
        declares_blocked: Whether a stop's text declares it is blocked only on
            the human (``auto_continue_stop``'s matcher, so there is one).

    Returns:
        The events in transcript order, plus the count of lines that were not
        JSON objects, or that carried an event but no usable timestamp.
    """
    events: list[LoopEvent] = []
    skipped = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        if not isinstance(record, dict):
            skipped += 1
            continue
        found = _classify(record, stop_prefix=stop_prefix, declares_blocked=declares_blocked)
        if found is None:
            continue
        try:
            at = _timestamp(record)
        except ValueError:
            skipped += 1
            continue
        kind, text, declared = found
        events.append(LoopEvent(kind=kind, at=at, text=text, declared=declared))
    return Extraction(events=tuple(events), skipped=skipped)


# --- checkpointed reads ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Where a session's transcript was read up to: always a line boundary."""

    path: str
    inode: int
    offset: int


class CheckpointInvalidError(Exception):
    """A checkpoint no longer describes the file; ``anchor`` is a fresh one at EOF."""

    def __init__(self, reason: str, anchor: Checkpoint) -> None:
        super().__init__(reason)
        self.anchor = anchor


def read_new_lines(
    path: Path, checkpoint: Checkpoint | None, *, tail_bytes: int
) -> tuple[list[str], Checkpoint]:
    """The complete lines appended since ``checkpoint``, and the next checkpoint.

    With no checkpoint (first sight) only the last ``tail_bytes`` are read,
    starting at the first line boundary inside them. A backlog larger than
    ``tail_bytes`` is skipped to its tail the same way, so one read is bounded.

    Raises:
        OSError: The transcript cannot be opened or read.
        CheckpointInvalidError: The checkpoint names another path, another
            inode, or an offset past the end (the file shrank).
    """
    with path.open("rb") as handle:
        status = os.fstat(handle.fileno())
        size = status.st_size
        if checkpoint is not None:
            anchor = Checkpoint(path=str(path), inode=status.st_ino, offset=size)
            if checkpoint.path != str(path):
                raise CheckpointInvalidError(
                    f"transcript path changed from {checkpoint.path}", anchor
                )
            if checkpoint.inode != status.st_ino:
                raise CheckpointInvalidError("transcript inode changed", anchor)
            if checkpoint.offset > size:
                raise CheckpointInvalidError(
                    f"transcript shrank below offset {checkpoint.offset} to {size}", anchor
                )
        start = checkpoint.offset if checkpoint is not None else 0
        mid_line = False
        if size - start > tail_bytes:
            if checkpoint is not None:
                logger.info(
                    "goal-loop detector: %d unread bytes in %s, reading the last %d",
                    size - start,
                    path,
                    tail_bytes,
                )
            start = size - tail_bytes
            mid_line = True
        if mid_line:
            # One byte back tells whether ``start`` already sits on a line boundary.
            handle.seek(start - 1)
            mid_line = handle.read(1) != b"\n"
        handle.seek(start)
        data = handle.read(size - start)
    if mid_line:
        handle_start = data.find(b"\n")
        if handle_start < 0:
            return [], Checkpoint(path=str(path), inode=status.st_ino, offset=start)
        start += handle_start + 1
        data = data[handle_start + 1 :]
    end = data.rfind(b"\n") + 1
    complete = data[:end].decode("utf-8", errors="replace")
    return complete.splitlines(), Checkpoint(
        path=str(path), inode=status.st_ino, offset=start + end
    )


# --- config --------------------------------------------------------------------------


class DetectorMode(StrEnum):
    """What the detector does at the threshold: ``observe`` only logs, ``act`` enters."""

    OBSERVE = "observe"
    ACT = "act"


def _positive_int_problem(key: str, value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return f"{key} must be a positive integer, got {value!r}"
    return None


def option_problems(options: Mapping[str, Any]) -> dict[str, str]:
    """The detector options that are invalid, keyed by option name."""
    problems: dict[str, str] = {}
    if _OPTION_MODE in options:
        mode = options[_OPTION_MODE]
        valid = [str(m) for m in DetectorMode]
        if mode not in valid:
            problems[_OPTION_MODE] = f"{_OPTION_MODE} must be one of {valid}, got {mode!r}"
    for key in _INT_OPTIONS:
        if key in options:
            problem = _positive_int_problem(key, options[key])
            if problem is not None:
                problems[key] = problem
    if _OPTION_BLOCKED_HOURS in options:
        hours = options[_OPTION_BLOCKED_HOURS]
        if (
            isinstance(hours, bool)
            or not isinstance(hours, (int, float))
            or not math.isfinite(hours)
            or hours <= 0
        ):
            problems[_OPTION_BLOCKED_HOURS] = (
                f"{_OPTION_BLOCKED_HOURS} must be a positive number, got {hours!r}"
            )
    return problems


@dataclass(frozen=True, slots=True)
class GoalLoopConfig:
    """The detector's thresholds (Plan 00501 Goals: 3 cycles, 2 declared, 30 min, 4 h)."""

    mode: DetectorMode = DetectorMode.OBSERVE
    cycle_threshold: int = 3
    declared_cycle_threshold: int = 2
    window_minutes: int = 30
    blocked_hours: float = 4

    def __post_init__(self) -> None:
        """Refuse an invalid value. Raises ``ValueError`` naming the option."""
        problems = option_problems(
            {
                _OPTION_MODE: str(self.mode),
                _OPTION_CYCLE_THRESHOLD: self.cycle_threshold,
                _OPTION_DECLARED_THRESHOLD: self.declared_cycle_threshold,
                _OPTION_WINDOW_MINUTES: self.window_minutes,
                _OPTION_BLOCKED_HOURS: self.blocked_hours,
            }
        )
        if problems:
            raise ValueError("; ".join(problems.values()))

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> GoalLoopConfig:
        """Build from handler options; an absent option keeps its default.

        Raises:
            ValueError: An option is invalid; the message names it.
        """
        problems = option_problems(options)
        if problems:
            raise ValueError("; ".join(problems.values()))
        defaults = cls()
        return cls(
            mode=DetectorMode(options.get(_OPTION_MODE, defaults.mode)),
            cycle_threshold=options.get(_OPTION_CYCLE_THRESHOLD, defaults.cycle_threshold),
            declared_cycle_threshold=options.get(
                _OPTION_DECLARED_THRESHOLD, defaults.declared_cycle_threshold
            ),
            window_minutes=options.get(_OPTION_WINDOW_MINUTES, defaults.window_minutes),
            blocked_hours=options.get(_OPTION_BLOCKED_HOURS, defaults.blocked_hours),
        )

    @property
    def window_seconds(self) -> int:
        """The cycle window in seconds."""
        return self.window_minutes * _SECONDS_PER_MINUTE

    @property
    def blocked_seconds(self) -> float:
        """How long a goal-loop entry lasts, in seconds."""
        return self.blocked_hours * _SECONDS_PER_HOUR

    def threshold_for(self, cycles: Iterable[Cycle]) -> int:
        """The declared threshold when every cycle is declared, else the plain one."""
        items = list(cycles)
        if items and all(cycle.declared for cycle in items):
            return self.declared_cycle_threshold
        return self.cycle_threshold


# --- the ring ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Cycle:
    """A stop answered by an unmet evaluation; ``at`` is the evaluation's time."""

    at: float
    stop_text: str
    declared: bool


class ResetCause(StrEnum):
    """Why the ring was emptied (the exit cause in the transition log)."""

    HUMAN_PROMPT = "human-prompt"
    GOAL_CLEARED = "goal-cleared"
    GOAL_MET = "goal-met"
    REPO_CHANGE = "repo-change"


_RESET_FOR: Final[dict[EventKind, ResetCause]] = {
    EventKind.HUMAN: ResetCause.HUMAN_PROMPT,
    EventKind.GOAL_CLEARED: ResetCause.GOAL_CLEARED,
    EventKind.GOAL_MET: ResetCause.GOAL_MET,
}


@dataclass(frozen=True, slots=True)
class RingReset:
    """The ring was emptied: why, how many cycles it held, and when."""

    cause: ResetCause
    dropped: int
    at: float


@dataclass(frozen=True, slots=True)
class FeedResult:
    """What one batch of events did: cycles added and non-empty resets."""

    new_cycles: int
    resets: tuple[RingReset, ...]


class CycleRing:
    """The cycles one session has run inside the window.

    Args:
        window_seconds: Cycles older than this, measured back from the newest
            cycle, drop out.
    """

    def __init__(self, *, window_seconds: int) -> None:
        self._window = window_seconds
        self._cycles: deque[Cycle] = deque()
        self._pending: LoopEvent | None = None
        self._fingerprint: str | None = None

    @property
    def cycles(self) -> tuple[Cycle, ...]:
        """The cycles in the window, oldest first."""
        return tuple(self._cycles)

    @property
    def fingerprint(self) -> str | None:
        """The repository fingerprint the current cycles were run against."""
        return self._fingerprint

    def _reset(self, cause: ResetCause, at: float) -> RingReset | None:
        dropped = len(self._cycles)
        self._cycles.clear()
        self._pending = None
        self._fingerprint = None
        return RingReset(cause=cause, dropped=dropped, at=at) if dropped else None

    def restart_count(self) -> None:
        """Start counting afresh after an entry or a would-enter.

        Empties the cycles and the pending stop but keeps the fingerprint, so a
        later repository change is still seen. Logs nothing: the enter or
        would-enter line is the record.
        """
        self._cycles.clear()
        self._pending = None

    def feed(self, events: Iterable[LoopEvent]) -> FeedResult:
        """Apply events in order; return the cycles added and any resets."""
        new_cycles = 0
        resets: list[RingReset] = []
        for event in events:
            cause = _RESET_FOR.get(event.kind)
            if cause is not None:
                reset = self._reset(cause, event.at)
                if reset is not None:
                    resets.append(reset)
            elif event.kind is EventKind.STOP:
                self._pending = event
            elif event.kind is EventKind.UNMET and self._pending is not None:
                self._cycles.append(
                    Cycle(
                        at=event.at, stop_text=self._pending.text, declared=self._pending.declared
                    )
                )
                self._pending = None
                new_cycles += 1
                self._prune()
        return FeedResult(new_cycles=new_cycles, resets=tuple(resets))

    def _prune(self) -> None:
        newest = self._cycles[-1].at
        while self._cycles and self._cycles[0].at < newest - self._window:
            self._cycles.popleft()

    def note_fingerprint(self, fingerprint: str, *, new_cycles: int) -> RingReset | None:
        """Record the tree the newest ``new_cycles`` cycles ran against.

        A fingerprint different from the ring's means the repository changed
        since the older cycles, so they are dropped (cause ``repo-change``) and
        only the newest ``new_cycles`` stay.
        """
        previous = self._fingerprint
        self._fingerprint = fingerprint
        if previous is None or previous == fingerprint:
            return None
        keep = min(new_cycles, len(self._cycles))
        dropped = len(self._cycles) - keep
        kept = list(self._cycles)[len(self._cycles) - keep :]
        self._cycles = deque(kept)
        if not dropped:
            return None
        at = kept[0].at if kept else 0.0
        return RingReset(cause=ResetCause.REPO_CHANGE, dropped=dropped, at=at)


# --- the verdict ---------------------------------------------------------------------


class Verdict(StrEnum):
    """Where the ring stands against its threshold."""

    QUIET = "quiet"
    NEAR_MISS = "near-miss"
    WOULD_ENTER = "would-enter"


@dataclass(frozen=True, slots=True)
class Assessment:
    """The ring measured against the thresholds, with its evidence."""

    verdict: Verdict
    count: int
    threshold: int
    declared: int
    similarities: tuple[float, ...]
    span_seconds: float

    def evidence(self, config: GoalLoopConfig, fingerprint: str | None) -> str:
        """Compact ``k=v`` evidence for the transition log."""
        similarity = ",".join(f"{s:.2f}" for s in self.similarities) or "-"
        return (
            f"cycles={self.count} threshold={self.threshold} "
            f"declared={self.declared}/{self.count} window={config.window_minutes}m "
            f"span={self.span_seconds:.0f}s similarity={similarity} "
            f"fingerprint={fingerprint or '-'} mode={config.mode}"
        )


def _similarity(first: str, second: str) -> float:
    return SequenceMatcher(None, first[:_SIMILARITY_CHARS], second[:_SIMILARITY_CHARS]).ratio()


def assess(ring: CycleRing, config: GoalLoopConfig) -> Assessment:
    """Measure the ring against the threshold that applies to its cycles."""
    cycles = ring.cycles
    threshold = config.threshold_for(cycles)
    count = len(cycles)
    if count >= threshold:
        verdict = Verdict.WOULD_ENTER
    elif count and count == threshold - 1:
        verdict = Verdict.NEAR_MISS
    else:
        verdict = Verdict.QUIET
    similarities = tuple(_similarity(a.stop_text, b.stop_text) for a, b in pairwise(cycles))
    span = cycles[-1].at - cycles[0].at if cycles else 0.0
    return Assessment(
        verdict=verdict,
        count=count,
        threshold=threshold,
        declared=sum(1 for c in cycles if c.declared),
        similarities=similarities,
        span_seconds=span,
    )


# --- the repository fingerprint ------------------------------------------------------


class FingerprintError(Exception):
    """The repository state could not be read."""


class GitRunner(Protocol):
    """``run_git``'s shape, so a test can substitute a failing run."""

    def __call__(self, cwd: Path, *args: str, timeout: float) -> Any:
        """Run git in ``cwd``; return a CompletedProcess-like result."""


def _porcelain_path(line: str) -> str:
    path = line[_PORCELAIN_PATH_START:]
    return path.split(_RENAME_ARROW)[-1]


def _counts(path: str) -> bool:
    return _JOURNAL_SEGMENT not in f"/{path}" and not path.startswith(_UNTRACKED_PREFIX)


def repo_fingerprint(
    root: Path, *, run: GitRunner = run_git, timeout: float = Timeout.GIT_CONTEXT
) -> str:
    """A short hash of ``HEAD`` plus the tracked changes, journals and scratch excluded.

    Raises:
        FingerprintError: Either git run failed or timed out.
    """
    head = run(root, "rev-parse", "HEAD", timeout=timeout)
    if head.returncode != 0:
        raise FingerprintError(f"git rev-parse HEAD failed: {str(head.stderr).strip()}")
    status = run(root, "status", "--porcelain", "-uno", timeout=timeout)
    if status.returncode != 0:
        raise FingerprintError(f"git status failed: {str(status.stderr).strip()}")
    kept = sorted(
        line for line in str(status.stdout).splitlines() if line and _counts(_porcelain_path(line))
    )
    digest = hashlib.sha256("\n".join([str(head.stdout).strip(), *kept]).encode("utf-8"))
    return digest.hexdigest()[:_FINGERPRINT_CHARS]
