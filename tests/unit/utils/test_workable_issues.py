"""Tests for the workable-issues cache (Plan 00470 Phase 7).

The cache is written where a decision is made (``work-queue done``,
``issue-validity --list-eligible``) and read by the Stop hook, which must never
call GitHub itself.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.utils.github_issue_validity import (
    GhError,
    IssueValidityService,
)
from claude_code_hooks_daemon.utils.workable_issues import (
    NEEDS_HUMAN_LABEL,
    WORKABLE_ISSUES_FILENAME,
    read_workable,
    refresh_workable_cache,
    workable_numbers,
    write_workable,
)

APPROVED = ("lts-bob",)


def _issue(number: int, author: str = "lts-bob", labels: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "number": number,
        "assignees": [],
        "author": {"login": author},
        "state": "OPEN",
        "labels": [{"name": name} for name in labels],
    }


def _service(listing: list[dict[str, Any]] | Exception) -> IssueValidityService:
    def run(args: Sequence[str]) -> str:
        if isinstance(listing, Exception):
            raise listing
        return json.dumps(listing)

    return IssueValidityService(run)


class TestWorkableNumbers:
    def test_eligible_issues_without_the_needs_human_label_are_workable(self) -> None:
        service = _service(
            [
                _issue(1),
                _issue(2, labels=[NEEDS_HUMAN_LABEL]),
                _issue(3, author="stranger"),
                _issue(4, labels=["agent-triaged"]),
            ]
        )
        from claude_code_hooks_daemon.utils.github_issue_validity import AuthorWhitelistCheck

        reports = service.check_open_issues([AuthorWhitelistCheck(APPROVED)])
        assert workable_numbers(reports) == [1, 4]


class TestRoundTrip:
    def test_a_written_cache_reads_back(self, tmp_path: Path) -> None:
        path = tmp_path / WORKABLE_ISSUES_FILENAME
        write_workable(path, [7, 9], now=1000.0)
        cache = read_workable(path)
        assert cache is not None
        assert cache.numbers == (7, 9)
        assert cache.recorded_at == 1000.0

    def test_a_missing_file_reads_as_none(self, tmp_path: Path) -> None:
        assert read_workable(tmp_path / WORKABLE_ISSUES_FILENAME) is None

    @pytest.mark.parametrize(
        "body",
        [
            "not json",
            "[]",
            "\xff\xfe",
            '{"numbers": "x", "recorded_at": 1}',
            '{"numbers": [1, true], "recorded_at": 1}',
            '{"numbers": [1]}',
            '{"numbers": [1], "recorded_at": true}',
        ],
    )
    def test_a_corrupt_file_reads_as_nothing_known_to_be_workable(
        self, tmp_path: Path, body: str
    ) -> None:
        path = tmp_path / WORKABLE_ISSUES_FILENAME
        path.write_text(body, encoding="utf-8")
        cache = read_workable(path)
        assert cache is not None and cache.numbers == ()

    def test_a_missing_directory_is_created(self, tmp_path: Path) -> None:
        path = tmp_path / "missing-dir" / WORKABLE_ISSUES_FILENAME
        write_workable(path, [1], now=1.0)
        assert read_workable(path) is not None


class TestFreshness:
    def test_fresh_within_max_age(self, tmp_path: Path) -> None:
        path = tmp_path / WORKABLE_ISSUES_FILENAME
        write_workable(path, [1], now=1000.0)
        cache = read_workable(path)
        assert cache is not None
        assert cache.is_fresh(now=1000.0 + 60, max_age_seconds=120) is True
        assert cache.is_fresh(now=1000.0 + 121, max_age_seconds=120) is False

    def test_a_future_dated_cache_is_not_fresh(self, tmp_path: Path) -> None:
        path = tmp_path / WORKABLE_ISSUES_FILENAME
        write_workable(path, [1], now=5000.0)
        cache = read_workable(path)
        assert cache is not None
        assert cache.is_fresh(now=1000.0, max_age_seconds=120) is False


class TestRefresh:
    def test_it_writes_the_workable_numbers_and_returns_them(self, tmp_path: Path) -> None:
        path = tmp_path / WORKABLE_ISSUES_FILENAME
        service = _service([_issue(3), _issue(5, labels=[NEEDS_HUMAN_LABEL])])
        assert refresh_workable_cache(path, service, APPROVED, now=10.0) == [3]
        cache = read_workable(path)
        assert cache is not None and cache.numbers == (3,)

    def test_an_empty_result_is_written_so_a_stale_list_cannot_linger(self, tmp_path: Path) -> None:
        path = tmp_path / WORKABLE_ISSUES_FILENAME
        write_workable(path, [9], now=1.0)
        assert refresh_workable_cache(path, _service([]), APPROVED, now=2.0) == []
        cache = read_workable(path)
        assert cache is not None and cache.numbers == ()

    def test_a_gh_failure_raises_and_leaves_the_cache_alone(self, tmp_path: Path) -> None:
        path = tmp_path / WORKABLE_ISSUES_FILENAME
        write_workable(path, [9], now=1.0)
        with pytest.raises(GhError):
            refresh_workable_cache(path, _service(GhError("offline")), APPROVED, now=2.0)
        cache = read_workable(path)
        assert cache is not None and cache.numbers == (9,)
