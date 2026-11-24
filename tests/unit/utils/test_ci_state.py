"""Tests for the ci-state reader (Plan 00636 Task 2.3, s5).

The reader takes the output a ``gh`` CI command already printed and tells a
GitHub run that is QUEUED (waiting for a runner, normal) from one queued past
the threshold (STUCK). Anything it cannot read stays UNKNOWN: it never says
"queued, fine" or "stuck" without a status and an age it parsed. Fixtures are
the non-TTY shapes ``gh`` 2.105 prints.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from claude_code_hooks_daemon.utils.ci_state import (
    CiCommandKind,
    CiState,
    ci_commands,
    read_ci_output,
    render_ci_readings,
)

NOW = datetime(2026, 11, 24, 6, 0, 0, tzinfo=UTC)
THRESHOLD = 30 * 60


def _row(status: str, created: str, conclusion: str = "", run_id: str = "45334494394") -> str:
    """One non-TTY ``gh run list`` row (nine tab-separated columns)."""
    return "\t".join(
        [
            status,
            conclusion,
            "Merge pull request #237",
            "QA",
            "main",
            "push",
            run_id,
            "2m16s",
            created,
        ]
    )


def _read(output: str) -> list[tuple[CiState, str]]:
    return [
        (r.state, r.label) for r in read_ci_output(output, now=NOW, stuck_after_seconds=THRESHOLD)
    ]


class TestCommands:
    @pytest.mark.parametrize(
        ("command", "kind"),
        [
            ("gh run list --limit 5", CiCommandKind.RUN_LIST),
            ("gh run view 123 --json status,createdAt", CiCommandKind.RUN_VIEW_JSON),
            ("gh pr checks 237", CiCommandKind.PR_CHECKS),
            ("cd repo && gh run list", CiCommandKind.RUN_LIST),
            ("gh run list --json status,createdAt --jq '.[].status'", CiCommandKind.RESHAPED),
            ("gh pr checks 237 --json bucket -t '{{.}}'", CiCommandKind.RESHAPED),
        ],
    )
    def test_a_ci_reading_command_is_recognised(self, command: str, kind: CiCommandKind) -> None:
        assert ci_commands(command) == [kind]

    @pytest.mark.parametrize(
        "command",
        [
            'echo "gh run list shows queued"',
            "gh run view 123",  # text form: no status column to read
            "gh pr view 237 --json body,comments",
            "gh run rerun 123",
            "git log --oneline",
        ],
    )
    def test_anything_else_is_not_a_ci_reading(self, command: str) -> None:
        assert ci_commands(command) == []


class TestRunListRows:
    def test_a_recently_queued_run_is_queued_not_stuck(self) -> None:
        assert _read(_row("queued", "2026-11-24T05:56:00Z")) == [
            (CiState.QUEUED, "QA #45334494394")
        ]

    def test_a_run_queued_past_the_threshold_is_stuck(self) -> None:
        assert _read(_row("queued", "2026-11-24T05:00:00Z")) == [(CiState.STUCK, "QA #45334494394")]

    def test_exactly_at_the_threshold_is_stuck(self) -> None:
        assert _read(_row("queued", "2026-11-24T05:30:00Z"))[0][0] is CiState.STUCK

    def test_running_and_completed_runs_say_nothing(self) -> None:
        output = "\n".join(
            [
                _row("in_progress", "2026-11-24T05:00:00Z"),
                _row("completed", "2026-11-24T04:00:00Z", conclusion="success"),
            ]
        )
        assert _read(output) == []

    def test_an_unparseable_created_time_is_unknown(self) -> None:
        assert _read(_row("queued", "about 2 hours ago"))[0][0] is CiState.UNKNOWN

    def test_a_created_time_in_the_future_is_unknown(self) -> None:
        assert _read(_row("queued", "2026-11-24T07:00:00Z"))[0][0] is CiState.UNKNOWN

    def test_a_created_time_without_a_zone_is_unknown(self) -> None:
        assert _read(_row("queued", "2026-11-24T05:56:00"))[0][0] is CiState.UNKNOWN

    @pytest.mark.parametrize("status", ["pending", "requested", "waiting"])
    def test_other_not_started_statuses_are_unknown(self, status: str) -> None:
        assert _read(_row(status, "2026-11-24T05:00:00Z"))[0][0] is CiState.UNKNOWN

    def test_a_row_with_the_wrong_column_count_is_not_read(self) -> None:
        assert _read("queued\tQA\t2026-11-24T05:00:00Z") == []


class TestJson:
    def test_run_list_json_queued_recent(self) -> None:
        output = json.dumps(
            [
                {
                    "databaseId": 7,
                    "workflowName": "QA",
                    "status": "queued",
                    "createdAt": "2026-11-24T05:50:00Z",
                },
                {"databaseId": 8, "workflowName": "QA", "status": "in_progress", "createdAt": ""},
            ]
        )
        assert _read(output) == [(CiState.QUEUED, "QA #7")]

    def test_run_view_json_object_queued_old_is_stuck(self) -> None:
        output = json.dumps(
            {
                "databaseId": 9,
                "name": "CodeQL",
                "status": "queued",
                "createdAt": "2026-11-23T05:00:00Z",
            }
        )
        assert _read(output) == [(CiState.STUCK, "CodeQL #9")]

    def test_a_rerun_is_aged_from_its_attempt_start_not_the_first_creation(self) -> None:
        """gh keeps createdAt across re-run attempts; startedAt is this attempt's (gh 2.105)."""
        output = json.dumps(
            {
                "databaseId": 9,
                "workflowName": "QA",
                "status": "queued",
                "attempt": 2,
                "createdAt": "2026-11-23T05:00:00Z",
                "startedAt": "2026-11-24T05:58:00Z",
            }
        )
        assert _read(output) == [(CiState.QUEUED, "QA #9")]

    def test_an_unreadable_started_at_falls_back_to_created_at(self) -> None:
        output = json.dumps(
            {"status": "queued", "createdAt": "2026-11-24T05:58:00Z", "startedAt": ""}
        )
        assert _read(output)[0][0] is CiState.QUEUED

    def test_queued_json_without_created_at_is_unknown(self) -> None:
        assert _read(json.dumps([{"status": "queued", "databaseId": 3}]))[0][0] is CiState.UNKNOWN

    def test_pr_checks_json_pending_bucket_cannot_split_queued_from_running(self) -> None:
        output = json.dumps([{"name": "tests", "bucket": "pending", "state": "IN_PROGRESS"}])
        assert _read(output) == [(CiState.PENDING_UNSPLIT, "tests")]

    def test_a_non_string_status_is_not_read(self) -> None:
        assert _read(json.dumps([{"status": 3, "createdAt": "2026-11-24T05:50:00Z"}])) == []


class TestPrChecksRows:
    def test_a_pending_check_cannot_split_queued_from_running(self) -> None:
        output = "\t".join(
            ["tests", "pending", "0", "https://github.com/o/r/actions/runs/1/job/2", ""]
        )
        assert _read(output) == [(CiState.PENDING_UNSPLIT, "tests")]

    def test_passing_checks_say_nothing(self) -> None:
        output = "\t".join(
            ["tests", "pass", "41s", "https://github.com/o/r/actions/runs/1/job/2", ""]
        )
        assert _read(output) == []


class TestRender:
    def _render(self, output: str) -> str:
        readings = read_ci_output(output, now=NOW, stuck_after_seconds=THRESHOLD)
        return render_ci_readings(readings, stuck_after_seconds=THRESHOLD)

    def test_queued_says_normal_waiting_with_age_and_threshold(self) -> None:
        text = self._render(_row("queued", "2026-11-24T05:56:00Z"))
        assert "QUEUED" in text
        assert "4 min" in text
        assert "30 min" in text
        assert "not stuck" in text

    def test_stuck_names_the_run_and_the_check_to_make(self) -> None:
        text = self._render(_row("queued", "2026-11-24T05:00:00Z"))
        assert "STUCK" in text
        assert "60 min" in text
        assert "gh run view 45334494394" in text
        assert "startedAt" in text

    def test_stuck_without_a_run_id_names_a_placeholder_not_a_blank(self) -> None:
        output = json.dumps({"status": "queued", "createdAt": "2026-11-23T05:00:00Z"})
        text = self._render(output)
        assert "gh run view <run-id>" in text
        assert "gh run view  " not in text

    def test_the_split_command_asks_for_the_attempt_start(self) -> None:
        text = self._render("\t".join(["tests", "pending", "0", "u", ""]))
        assert "startedAt" in text

    def test_unknown_never_claims_either_state(self) -> None:
        text = self._render(_row("queued", "garbage"))
        assert "UNKNOWN" in text
        assert "QUEUED (" not in text
        assert "STUCK" not in text

    def test_pending_points_at_the_command_that_can_tell(self) -> None:
        text = self._render("\t".join(["tests", "pending", "0", "u", ""]))
        assert "gh run list" in text
        assert "--json" in text

    def test_the_reading_is_not_citable_and_carries_the_ask_the_seat_rule(self) -> None:
        text = self._render(_row("queued", "2026-11-24T05:56:00Z"))
        assert "not a verification" in text
        assert "without asking that seat" in text

    def test_reshaped_output_reading(self) -> None:
        text = render_ci_readings(
            read_ci_output("queued\n", now=NOW, stuck_after_seconds=THRESHOLD, reshaped=True),
            stuck_after_seconds=THRESHOLD,
        )
        assert "UNKNOWN" in text
        assert "--jq" in text

    def test_reshaped_output_without_a_not_started_word_says_nothing(self) -> None:
        assert (
            read_ci_output("success\n", now=NOW, stuck_after_seconds=THRESHOLD, reshaped=True) == []
        )
