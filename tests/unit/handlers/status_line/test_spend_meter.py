"""Tests for SpendMeterHandler: the agents-only status-line segment (issue #133)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.handlers.status_line.spend_meter import SpendMeterHandler, compact
from claude_code_hooks_daemon.utils.session_load import live_snapshot_path

SESSION = "s1"

_RED = "\033[31m"
_RESET = "\033[0m"


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


def red(text: str) -> str:
    return f"{_RED}{text}{_RESET}"


def test_agents_segment_names_count_families_and_largest_context(handler, untracked) -> None:
    snapshot(untracked, count=2, largest_context=140_000, families={"opus": 1, "sonnet": 1})
    assert render(handler) == "| ⚙ 2 agents (opus, sonnet) · 140k"


def test_one_agent_is_singular(handler, untracked) -> None:
    snapshot(untracked, count=1, largest_context=127_400, families={"sonnet": 1})
    assert render(handler) == "| ⚙ 1 agent (sonnet) · 127k"


def test_families_are_listed_by_count_then_name_without_numbers(handler, untracked) -> None:
    snapshot(
        untracked,
        count=4,
        largest_context=412_000,
        families={"sonnet": 1, "opus": 2, "haiku": 1},
    )
    assert render(handler) == "| ⚙ 4 agents (opus, haiku, sonnet) · 412k"


def test_no_family_split_and_no_context_are_left_out(handler, untracked) -> None:
    snapshot(untracked, count=1, largest_context=0, families={})
    assert render(handler) == "| ⚙ 1 agent"


def test_the_cumulative_total_is_never_on_the_bar(handler, untracked) -> None:
    ledger_row(untracked, "a1", 1_200_000_000)
    snapshot(untracked, count=1, largest_context=127_000, families={"sonnet": 1})
    text = render(handler)
    assert "tok-eq" not in text
    assert "Σ" not in text
    assert "1.2G" not in text


def test_a_ledger_without_running_agents_renders_nothing(handler, untracked) -> None:
    ledger_row(untracked, "a1", 64_500)
    assert handler.handle({"session_id": SESSION}).context == []


def test_no_running_agent_renders_nothing(handler, untracked) -> None:
    snapshot(untracked, count=0, largest_context=0, families={}, unmeasured=0)
    assert handler.handle({"session_id": SESSION}).context == []


def test_stale_snapshot_renders_nothing(handler, untracked) -> None:
    snapshot(untracked, age=3600, count=5, largest_context=1, families={"opus": 5}, unmeasured=3)
    assert handler.handle({"session_id": SESSION}).context == []


def test_missing_snapshot_renders_nothing(handler) -> None:
    assert handler.handle({"session_id": SESSION}).context == []


def test_failures_are_red_and_appended_to_the_agents_segment(handler, untracked) -> None:
    snapshot(untracked, count=1, largest_context=127_000, families={"sonnet": 1}, unmeasured=2)
    expected = f"| ⚙ 1 agent (sonnet) · 127k · {red('2 unmeasured')}"
    assert render(handler) == expected


def test_zero_failures_show_nothing_extra(handler, untracked) -> None:
    snapshot(untracked, count=1, largest_context=127_000, families={"sonnet": 1}, unmeasured=0)
    assert "unmeasured" not in render(handler)


def test_failures_alone_are_shown_red_when_no_agent_is_running(handler, untracked) -> None:
    snapshot(untracked, count=0, largest_context=0, families={}, unmeasured=1)
    assert render(handler) == f"| {red('1 unmeasured')}"


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (0, "0"),
        (999, "999"),
        (999.6, "1k"),
        (1_500, "2k"),
        (2_500, "3k"),
        (277_500, "278k"),
        (412_000, "412k"),
        (999_499, "999k"),
        (999_500, "1M"),
        (2_500_000, "2.5M"),
        (3_000_000, "3M"),
        (61_249_999, "61.2M"),
        (999_960_000, "1G"),
        (1_600_000_000, "1.6G"),
        (1_664_000_000, "1.66G"),
        (2_000_000_000, "2G"),
    ],
)
def test_compact(value: float, text: str) -> None:
    """Whole k; one decimal for M and two for G, each dropped when it is zero."""
    assert compact(value) == text


def test_metadata(handler) -> None:
    assert handler.terminal is False
    assert handler.get_claude_md() is None
    assert handler.explain_segment().name == "Running Subagents"
    assert handler.get_acceptance_tests()
