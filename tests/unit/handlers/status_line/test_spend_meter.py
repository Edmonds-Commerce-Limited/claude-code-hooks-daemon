"""Tests for SpendMeterHandler (Plan 00471 Task 2.5, lever L7): render from fixture sidecars."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.handlers.status_line.spend_meter import SpendMeterHandler, compact
from claude_code_hooks_daemon.utils.session_load import live_snapshot_path

SESSION = "s1"


@pytest.fixture
def untracked(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def handler(untracked: Path) -> SpendMeterHandler:
    instance = SpendMeterHandler()
    instance._untracked_override = untracked
    return instance


def ledger_row(untracked: Path, agent: str, ite: int) -> None:
    directory = untracked / "cache-sidecar" / SESSION
    directory.mkdir(parents=True, exist_ok=True)
    row = {
        "requests": 1,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "ttl_5m_write_tokens": 0,
        "ttl_1h_write_tokens": 0,
        "ite": ite,
    }
    (directory / f"{agent}.json").write_text(json.dumps(row), encoding="utf-8")


def snapshot(untracked: Path, *, age: float = 5, **fields: object) -> None:
    path = live_snapshot_path(untracked, SESSION)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ts": time.time() - age, **fields}), encoding="utf-8")


def render(handler: SpendMeterHandler) -> str:
    return "".join(handler.handle({"session_id": SESSION}).context)


def test_full_segment(handler, untracked) -> None:
    ledger_row(untracked, "a1", 1_200_000_000)
    ledger_row(untracked, "a2", 460_000_000)
    snapshot(
        untracked,
        count=3,
        largest_context=412_000,
        families={"opus": 2, "sonnet": 1},
        unmeasured=2,
    )
    assert render(handler) == "| Σ⚙ 1.66G ite · 3 live (2 opus, 1 sonnet) · max 412k · 2 unmeasured"


def test_spend_only(handler, untracked) -> None:
    ledger_row(untracked, "a1", 64_500)
    assert render(handler) == "| Σ⚙ 64.5k ite"


def test_stale_snapshot_drops_the_live_part(handler, untracked) -> None:
    ledger_row(untracked, "a1", 3_000_000)
    snapshot(untracked, age=3600, count=5, largest_context=1, families={"opus": 5}, unmeasured=0)
    assert render(handler) == "| Σ⚙ 3M ite"


def test_zero_live_shows_no_max(handler, untracked) -> None:
    ledger_row(untracked, "a1", 500)
    snapshot(untracked, count=0, largest_context=0, families={}, unmeasured=0)
    assert render(handler) == "| Σ⚙ 500 ite · 0 live"


def test_nothing_to_show_renders_nothing(handler) -> None:
    assert handler.handle({"session_id": SESSION}).context == []


def test_unmeasured_alone_is_shown(handler, untracked) -> None:
    snapshot(untracked, count=0, largest_context=0, families={}, unmeasured=1)
    assert render(handler) == "| Σ⚙ 0 ite · 0 live · 1 unmeasured"


@pytest.mark.parametrize(
    ("value", "text"),
    [(0, "0"), (999, "999"), (1_500, "1.5k"), (2_500_000, "2.5M"), (1_664_000_000, "1.66G")],
)
def test_compact(value: int, text: str) -> None:
    assert compact(value) == text


def test_metadata(handler) -> None:
    assert handler.terminal is False
    assert handler.get_claude_md() is None
    assert handler.explain_segment().name == "Subagent Spend"
    assert handler.get_acceptance_tests()
