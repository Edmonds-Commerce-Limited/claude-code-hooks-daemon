"""Plan 00318 — the supervisor's audit trail is a banner, not a chat injection.

Announcing the actions the supervisor took on the user's behalf used to cost a
whole model turn and a permanent transcript entry, for a notice whose only
audience is the human watching the terminal. It now goes out on the same
transient status-line channel as the Ctrl+C hint, with a longer TTL and a
visible countdown so it plainly announces its own transience.

`decision.log` stays the durable, complete audit record — the banner is the
glance-able surface, not the archive.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

_NOW = 50_000.0
_SESSION = "banner-sess-1"


def _write_sidecar(sidecar_dir: Path, *, model_id: str = "claude-fable-5") -> None:
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    (sidecar_dir / f"{_SESSION}.json").write_text(
        json.dumps(
            {
                "red": False,
                "critical": False,
                "compact_urgent": False,
                "tier": "ok",
                "pct": 20.0,
                "session_id": _SESSION,
                "ts": _NOW - 1.0,
                "seq": 1,
                "writer_pid": 42,
                "compacting": False,
                "model_id": model_id,
                "effort": "low",
            }
        ),
        encoding="utf-8",
    )


def _facts(*, input_line_empty: bool = True) -> object:
    return _mod.TickFacts(
        now_wall=_NOW,
        idle=True,
        input_line_empty=input_line_empty,
        human_compact_submitted=False,
        work_idle=True,
    )


def _flush(tmp_path: Path, *, items: tuple[str, ...], input_line_empty: bool = True) -> object:
    """Arm ``items`` and run the tick that flushes them."""
    sidecar_dir = tmp_path / "cs"
    _write_sidecar(sidecar_dir)
    machine = _mod.CompactStateMachine(_mod.CompactPolicy())
    for item in items:
        machine.arm_audit(item)
    return _mod.decide_once(
        machine,
        sidecar_dir=sidecar_dir,
        facts=_facts(input_line_empty=input_line_empty),
        dry_run=False,
        freshness_seconds=_mod.CompactPolicy().freshness_seconds,
    )


def _banner_payload(tmp_path: Path) -> dict[str, object]:
    path = tmp_path / _mod._LOG_SUBDIRECTORY / _mod._STATUS_MESSAGE_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


class TestAuditBannerText:
    def test_banner_is_the_actions_only_no_chat_preamble(self) -> None:
        banner = _mod._format_audit_banner(
            ("/effort low (coupled to model switch)", "/model fable (auto-restore after downgrade)")
        )
        assert banner.startswith(_mod._AUDIT_BANNER_GLYPH)
        assert f"{_mod._AUDIT_ACTION_EFFORT_GLYPH} /effort low" in banner
        assert f"{_mod._AUDIT_ACTION_MODEL_GLYPH} /model fable" in banner
        # The status line is width-constrained: the per-item reason, the
        # provenance preamble and the log path all belong to decision.log.
        assert "coupled to model switch" not in banner
        assert "decision.log" not in banner
        assert "NOT a human" not in banner

    def test_long_backlog_is_truncated_with_a_remainder_count(self) -> None:
        banner = _mod._format_audit_banner(tuple(f"/effort low (attempt {n})" for n in range(6)))
        assert "+3 more" in banner
        assert banner.count("/effort low") == _mod._AUDIT_BANNER_MAX_ITEMS


class TestAuditFlushPostsBanner:
    def test_flush_posts_a_countdown_banner_and_injects_nothing(self, tmp_path: Path) -> None:
        outcome = _flush(tmp_path, items=("/effort low (coupled to model switch)",))
        assert outcome.decision_value == _mod.Decision.WOULD_AUDIT.value
        # The whole point: no chat line, so no model turn and no context cost.
        assert outcome.payload is None
        payload = _banner_payload(tmp_path)
        assert payload["countdown"] is True
        assert payload["expires_at"] == _NOW + _mod._AUDIT_BANNER_TTL_SECONDS
        assert "/effort low" in str(payload["text"])

    def test_flush_records_the_audit_in_the_decision_log_line(self, tmp_path: Path) -> None:
        outcome = _flush(tmp_path, items=("/model fable (auto-restore after downgrade)",))
        assert outcome.noop_reason_log is not None
        assert "audit" in outcome.noop_reason_log
        assert "/model fable" in outcome.noop_reason_log

    def test_flush_clears_the_pending_items(self, tmp_path: Path) -> None:
        sidecar_dir = tmp_path / "cs"
        _write_sidecar(sidecar_dir)
        machine = _mod.CompactStateMachine(_mod.CompactPolicy())
        machine.arm_audit("/effort low (coupled to model switch)")
        _mod.decide_once(
            machine,
            sidecar_dir=sidecar_dir,
            facts=_facts(),
            dry_run=False,
            freshness_seconds=_mod.CompactPolicy().freshness_seconds,
        )
        assert machine.audit_pending == ()

    def test_banner_posts_even_while_the_user_is_typing(self, tmp_path: Path) -> None:
        """A banner writes a file, not the PTY — it needs no empty input box."""
        outcome = _flush(
            tmp_path,
            items=("/effort low (coupled to model switch)",),
            input_line_empty=False,
        )
        assert outcome.decision_value == _mod.Decision.WOULD_AUDIT.value
        assert "/effort low" in str(_banner_payload(tmp_path)["text"])

    def test_no_pending_items_posts_nothing(self, tmp_path: Path) -> None:
        outcome = _flush(tmp_path, items=())
        assert outcome.decision_value != _mod.Decision.WOULD_AUDIT.value
        assert not (tmp_path / _mod._LOG_SUBDIRECTORY / _mod._STATUS_MESSAGE_FILENAME).exists()
