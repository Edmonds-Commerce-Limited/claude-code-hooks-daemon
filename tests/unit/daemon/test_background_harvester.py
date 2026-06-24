"""Tests for the background-process harvester core (Plan 00142, Layer B).

Pure, process-free logic: parse ``ps`` output into ProcessRecords and evaluate
them against resource budgets to surface RUNAWAYS. The harvester NEVER kills —
it only reports breaches with a ready-to-run ``kill -- -<pgid>`` command for the
agent to act on.
"""

import json

import pytest

from claude_code_hooks_daemon.daemon.background_harvester import (
    Breach,
    ProcessRecord,
    build_report,
    find_breaches,
    parse_ps_output,
    read_tracked_pgids,
)

# The literal incident process: ugrep -rl … / at 1116% CPU for 6918s.
_INCIDENT_PS = """\
    PID    PGID  ELAPSED %CPU COMMAND
 295971  295967     6918 1116 ugrep -G --ignore-files --hidden -I --exclude-dir=.git -rl class /
 295967  295967     6918  0.0 /bin/bash -c grep -rl class / 2>/dev/null
      1       1   100000  0.0 /sbin/init
"""


class TestParsePsOutput:
    def test_parses_records_skipping_header(self):
        records = parse_ps_output(_INCIDENT_PS)
        assert len(records) == 3
        assert all(isinstance(r, ProcessRecord) for r in records)

    def test_parses_fields(self):
        records = parse_ps_output(_INCIDENT_PS)
        top = records[0]
        assert top.pid == 295971
        assert top.pgid == 295967
        assert top.etimes == 6918
        assert top.pcpu == pytest.approx(1116.0)
        assert "ugrep" in top.args
        assert top.args.endswith("/")

    def test_ignores_blank_and_malformed_lines(self):
        records = parse_ps_output("\n\nPID PGID ELAPSED %CPU COMMAND\ngarbage line\n")
        assert records == []


class TestFindBreaches:
    @pytest.fixture
    def records(self):
        return parse_ps_output(_INCIDENT_PS)

    def test_incident_cpu_runaway_is_a_breach(self, records):
        breaches = find_breaches(
            records,
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_pgids=(),
        )
        pids = {b.record.pid for b in breaches}
        # The 1116% CPU ugrep is caught even with NO tracked pgids (orphan case).
        assert 295971 in pids

    def test_init_and_idle_bash_not_breached(self, records):
        breaches = find_breaches(
            records,
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_pgids=(),
        )
        pids = {b.record.pid for b in breaches}
        # init (pid 1) runs forever but 0% CPU and is not tracked → no breach.
        assert 1 not in pids
        # the 0% bash parent is not a CPU breach and not tracked → no breach.
        assert 295967 not in pids

    def test_wall_ttl_only_applies_to_tracked_pgids(self):
        text = (
            "PID PGID ELAPSED %CPU COMMAND\n"
            "500 500 9999 0.1 node dev-server\n"  # long-lived, low CPU
        )
        records = parse_ps_output(text)
        # Not tracked → wall TTL must NOT flag a low-CPU long-lived process.
        assert (
            find_breaches(
                records,
                max_wall_seconds=600,
                max_cpu_percent=400,
                min_cpu_runtime_seconds=60,
                tracked_pgids=(),
            )
            == []
        )
        # Tracked → wall TTL applies and surfaces it.
        breaches = find_breaches(
            records,
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_pgids=(500,),
        )
        assert len(breaches) == 1
        assert any("TTL" in r or "ttl" in r.lower() for r in breaches[0].reasons)

    def test_cpu_breach_requires_min_runtime(self):
        text = "PID PGID ELAPSED %CPU COMMAND\n700 700 5 900 some-burst\n"
        records = parse_ps_output(text)
        # 900% CPU but only 5s elapsed (< 60s window) → momentary spike, no breach.
        assert (
            find_breaches(
                records,
                max_wall_seconds=600,
                max_cpu_percent=400,
                min_cpu_runtime_seconds=60,
                tracked_pgids=(),
            )
            == []
        )

    def test_exclude_pgids_skips_self(self, records):
        # Excluding the offender's pgid (e.g. the harvester's own group) skips it.
        breaches = find_breaches(
            records,
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_pgids=(),
            exclude_pgids=(295967,),
        )
        assert breaches == []

    def test_breach_kill_command_targets_process_group(self, records):
        breaches = find_breaches(
            records,
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_pgids=(),
        )
        breach = next(b for b in breaches if b.record.pid == 295971)
        assert isinstance(breach, Breach)
        assert breach.kill_command == "kill -- -295967"
        assert breach.reasons  # non-empty explanation


class TestReadTrackedPgids:
    def test_missing_file_returns_empty(self, tmp_path):
        assert read_tracked_pgids(tmp_path / "nope.jsonl") == []

    def test_reads_pgids_skipping_malformed_lines(self, tmp_path):
        f = tmp_path / "bg.jsonl"
        f.write_text(
            json.dumps({"pgid": 100, "command": "a &"})
            + "\n"
            + "not json\n"
            + json.dumps({"command": "no pgid here"})
            + "\n"
            + json.dumps({"pgid": 200, "command": "b &"})
            + "\n"
        )
        assert read_tracked_pgids(f) == [100, 200]


class TestBuildReport:
    @pytest.fixture
    def records(self):
        return parse_ps_output(_INCIDENT_PS)

    def test_text_report_lists_breach_and_kill_command(self, records):
        report = build_report(
            records,
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_pgids=(),
        )
        assert report["has_breaches"] is True
        assert "kill -- -295967" in report["text"]
        assert "ugrep" in report["text"]

    def test_text_report_no_breaches_message(self):
        records = parse_ps_output("PID PGID ELAPSED %CPU COMMAND\n1 1 999 0.0 /sbin/init\n")
        report = build_report(
            records,
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_pgids=(),
        )
        assert report["has_breaches"] is False
        assert "NO RUNAWAY" in report["text"].upper()

    def test_json_report_is_serializable(self, records):
        report = build_report(
            records,
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_pgids=(),
        )
        assert report["has_breaches"] is True
        # breaches must round-trip through JSON
        round_tripped = json.loads(json.dumps(report["breaches"]))
        assert any(b["kill_command"] == "kill -- -295967" for b in round_tripped)

    def test_report_never_contains_a_performed_kill(self, records):
        # Defensive: the report only SUGGESTS kill commands, never reports a kill done.
        report = build_report(
            records,
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_pgids=(),
        )
        assert "killed" not in report["text"].lower()
