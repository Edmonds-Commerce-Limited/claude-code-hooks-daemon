"""Plan 00399 — a compaction is recognised from the daemon's PreCompact record.

A `/compact` reached by typing `/comp` and pressing Tab is expanded INSIDE
Claude Code's input box, so the forwarded keystrokes never spell `/compact`
and the keystroke recogniser cannot see it. Owner ruling (option 2, the Plan
00328 precedent): the supervisor does not widen the keystroke match. It takes
the fact -- a compaction started, and whose it was -- from the daemon's own
`<session>.compacting` record, which is written only when a compaction really
starts and so cannot produce a false recognition.
"""

from __future__ import annotations

import base64
import io
import json
from typing import TYPE_CHECKING, Any

import pytest

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_SESSION = "fg"
_NOW = 1000.0
_LEGACY_REASON = "compaction detected -> would inject continue"


def _write_compaction_record(sidecar_dir: Path, **fields: object) -> Path:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"{_SESSION}.compacting"
    path.write_text(json.dumps({"ts": _NOW, "session_id": _SESSION, **fields}), encoding="utf-8")
    return path


def _write_urgent_sidecar(sidecar_dir: Path) -> None:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    (sidecar_dir / f"{_SESSION}.json").write_text(
        json.dumps(
            {
                "red": True,
                "critical": False,
                "compact_urgent": True,
                "tier": "urgent",
                "pct": 50.0,
                "session_id": _SESSION,
                "ts": _NOW,
                "seq": 1,
                "writer_pid": 1,
                "compacting": False,
            }
        ),
        encoding="utf-8",
    )


def _facts(*, idle: bool = True, raw: bytes = b"", now: float = _NOW) -> object:
    return _mod.TickFacts(
        now_wall=now,
        idle=idle,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
        human_raw_input=base64.b64encode(raw).decode("ascii"),
    )


def _decide(sidecar_dir: Path) -> Any:
    policy = _mod.CompactPolicy()
    return _mod.decide_once(
        _mod.CompactStateMachine(policy),
        sidecar_dir=sidecar_dir,
        facts=_facts(),
        dry_run=True,
        freshness_seconds=policy.freshness_seconds,
    )


# ── The keystroke recogniser stays exact (success criterion 3) ──────────────


@pytest.mark.parametrize(
    "typed",
    [
        pytest.param(b"/comp\t\r", id="tab-then-enter"),
        pytest.param(b"/comp\tok lets continue pruning these plans\r", id="tab-then-args"),
        pytest.param(b"/comp\r", id="unknown-command-no-tab"),
    ],
)
def test_keystrokes_without_the_whole_word_are_not_a_compact(typed: bytes) -> None:
    """A prefix is NOT a `/compact`: widening the match would let a mistyped
    command park the supervisor in AWAIT for the whole await timeout, which
    silences every band including critical. The record below is the channel."""
    line = _mod.HumanInputLine()
    line.feed(typed)
    assert line.take_compact_submitted() is False


# ── Reading the record ──────────────────────────────────────────────────────


def test_origin_is_read_from_the_record(tmp_path: Path) -> None:
    path = _write_compaction_record(tmp_path, trigger="manual", origin="human")
    assert _mod.load_compaction_origin(path) == "human"


def test_record_without_origin_reads_as_unattributed(tmp_path: Path) -> None:
    # A daemon older than Plan 00399 writes only ts + session_id.
    path = _write_compaction_record(tmp_path)
    assert _mod.load_compaction_origin(path) == ""


def test_non_string_origin_reads_as_unattributed(tmp_path: Path) -> None:
    path = _write_compaction_record(tmp_path, origin=7)
    assert _mod.load_compaction_origin(path) == ""


def test_unreadable_record_reads_as_unattributed(tmp_path: Path) -> None:
    path = tmp_path / f"{_SESSION}.compacting"
    path.write_text("not json", encoding="utf-8")
    assert _mod.load_compaction_origin(path) == ""


def test_missing_record_reads_as_unattributed(tmp_path: Path) -> None:
    assert _mod.load_compaction_origin(tmp_path / "gone.compacting") == ""


def test_non_object_record_reads_as_unattributed(tmp_path: Path) -> None:
    path = tmp_path / f"{_SESSION}.compacting"
    path.write_text(json.dumps(["human"]), encoding="utf-8")
    assert _mod.load_compaction_origin(path) == ""


# ── The decision names whose compaction it was ──────────────────────────────


@pytest.mark.parametrize(
    ("origin", "label"),
    [
        ("human", "human /compact"),
        ("supervisor", "supervisor /compact"),
        ("auto", "auto-compact"),
    ],
)
def test_resume_names_the_recorded_origin(tmp_path: Path, origin: str, label: str) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_compaction_record(sidecar_dir, trigger="manual", origin=origin)

    outcome = _decide(sidecar_dir)

    assert outcome.decision_value == _mod.Decision.WOULD_CONTINUE.value
    assert outcome.reason == f"compaction detected ({label}) -> would inject continue"


@pytest.mark.parametrize("fields", [{}, {"origin": "unknown"}], ids=["legacy", "unknown"])
def test_unattributed_record_keeps_the_plain_reason(
    tmp_path: Path, fields: dict[str, object]
) -> None:
    sidecar_dir = tmp_path / "context-sidecar"
    _write_compaction_record(sidecar_dir, **fields)

    outcome = _decide(sidecar_dir)

    assert outcome.decision_value == _mod.Decision.WOULD_CONTINUE.value
    assert outcome.reason == _LEGACY_REASON


# ── End to end: a Tab-completed `/compact` through the worker ────────────────


def test_tab_completed_compact_is_recognised_from_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The human submits `/comp` + Tab at an idle prompt; Claude Code starts the
    compaction at once and the daemon records it. The worker must never type a
    second `/compact` over it, and must name the human as the origin when it
    resumes -- with the keystroke recogniser having seen nothing."""
    monkeypatch.setattr(_mod, "cached_own_session_ids", lambda: frozenset({_SESSION}))
    sidecar_dir = tmp_path / "context-sidecar"
    _write_urgent_sidecar(sidecar_dir)
    _write_compaction_record(sidecar_dir, trigger="manual", origin="human")
    ticks = [
        # The Enter has just been pressed, so the session is not idle yet.
        _mod._facts_to_json(_facts(idle=False, raw=b"/comp\t\r", now=_NOW)),
        _mod._facts_to_json(_facts(idle=True, now=_NOW + 2.0)),
    ]
    out_stream = io.StringIO()

    _mod.run_worker(
        io.StringIO("\n".join(ticks) + "\n"),
        out_stream,
        dry_run=True,
        sidecar_dir=sidecar_dir,
        policy=_mod.CompactPolicy(),
    )

    outcomes = [
        _mod._outcome_from_json(ln) for ln in out_stream.getvalue().splitlines() if ln.strip()
    ]
    assert [o.decision_value for o in outcomes] == [
        _mod.Decision.NOOP.value,
        _mod.Decision.WOULD_CONTINUE.value,
    ]
    assert outcomes[1].reason == "compaction detected (human /compact) -> would inject continue"
    # The keystrokes were never read as a `/compact`: AWAIT was not entered as
    # a human-originated wait on either tick.
    assert all(o.machine_state is not None for o in outcomes)
    assert all(o.machine_state["await_is_human"] is False for o in outcomes)
