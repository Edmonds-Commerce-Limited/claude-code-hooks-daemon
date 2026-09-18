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
    read_tracked_commands,
)

# The literal incident process: ugrep -rl … / at 1116% CPU for 6918s.
_INCIDENT_PS = """\
    PID    PPID    PGID  ELAPSED %CPU COMMAND
 295971  295967  295967     6918 1116 ugrep -G --ignore-files --hidden -I --exclude-dir=.git -rl class /
 295967      65  295967     6918  0.0 /bin/bash -c grep -rl class / 2>/dev/null
      1       0       1   100000  0.0 /sbin/init
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
        records = parse_ps_output("\n\nPID PPID PGID ELAPSED %CPU COMMAND\ngarbage line\n")
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
            tracked_commands=(),
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
            tracked_commands=(),
        )
        pids = {b.record.pid for b in breaches}
        # init (pid 1) runs forever but 0% CPU and is not tracked → no breach.
        assert 1 not in pids
        # the 0% bash parent is not a CPU breach and not tracked → no breach.
        assert 295967 not in pids

    def test_wall_ttl_only_applies_to_tracked_commands(self):
        text = (
            "PID PPID PGID ELAPSED %CPU COMMAND\n"
            "500 65 500 9999 0.1 node dev-server\n"  # long-lived, low CPU
        )
        records = parse_ps_output(text)
        # Not tracked → wall TTL must NOT flag a low-CPU long-lived process.
        assert (
            find_breaches(
                records,
                max_wall_seconds=600,
                max_cpu_percent=400,
                min_cpu_runtime_seconds=60,
                tracked_commands=(),
            )
            == []
        )
        # Tracked → wall TTL applies and surfaces it.
        breaches = find_breaches(
            records,
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_commands=("node dev-server",),
        )
        assert len(breaches) == 1
        assert any("TTL" in r or "ttl" in r.lower() for r in breaches[0].reasons)

    def test_blank_tracked_command_does_not_track_everything(self):
        """A blank entry must not make the whole process table "tracked".

        ``"" in args`` is True for every process, so a single empty ``command``
        field would turn the narrow wall TTL into a nag about ``init``.
        """
        records = parse_ps_output(
            "PID PPID PGID ELAPSED %CPU COMMAND\n1 0 1 999999 0.0 /sbin/init\n"
        )

        assert (
            find_breaches(
                records,
                max_wall_seconds=600,
                max_cpu_percent=400,
                min_cpu_runtime_seconds=60,
                tracked_commands=("", "   "),
            )
            == []
        )

    def test_tracked_command_matches_as_a_substring_of_args(self):
        """Correlation is by the command text surviving into ``ps`` args.

        A background Bash call reaches ``ps`` as a wrapper shell that ``eval``s
        the recorded command, so the match is a substring one — not equality.
        """
        text = (
            "PID PPID PGID ELAPSED %CPU COMMAND\n"
            "800 65 800 4000 0.1 /bin/bash -c eval 'npm run build' < /dev/null\n"
        )
        breaches = find_breaches(
            parse_ps_output(text),
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_commands=("npm run build",),
        )

        assert [b.record.pid for b in breaches] == [800]

    def test_cpu_breach_requires_min_runtime(self):
        text = "PID PPID PGID ELAPSED %CPU COMMAND\n700 65 700 5 900 some-burst\n"
        records = parse_ps_output(text)
        # 900% CPU but only 5s elapsed (< 60s window) → momentary spike, no breach.
        assert (
            find_breaches(
                records,
                max_wall_seconds=600,
                max_cpu_percent=400,
                min_cpu_runtime_seconds=60,
                tracked_commands=(),
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
            tracked_commands=(),
            exclude_pgids=(295967,),
        )
        assert breaches == []

    def test_breach_kill_command_targets_process_group(self, records):
        breaches = find_breaches(
            records,
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_commands=(),
        )
        breach = next(b for b in breaches if b.record.pid == 295971)
        assert isinstance(breach, Breach)
        assert breach.kill_command == "kill -- -295967"
        assert breach.reasons  # non-empty explanation


#: A tracked wrapper over the TTL, with one descendant sitting in a group the
#: caller excludes — the harvester's own. Every pid/pgid here is chosen to make
#: that shape unambiguous rather than to look realistic.
_TREE_SPANNING_EXCLUDED_PS = """\
    PID    PPID    PGID  ELAPSED %CPU COMMAND
   5000      65    5000     9000  0.0 /bin/bash -c ./scripts/qa/llm_qa.py all
   5001    5000    5001     9000 50.0 python -m pytest tests/
   5002    5000    7777     9000  0.0 bin/hooks-daemon harvest-background
      1       0       1   100000  0.0 /sbin/init
"""

_EXCLUDED_PGID = 7777


class TestAnExcludedGroupIsNeverNamedInTheKill:
    """Ledger 00422 N5 row (i), Plan 00438.

    ``exclude_pgids`` says "never flag these", and the flagging half honours
    it. ``tree_pgids`` was built from the descendant tree with no such filter,
    so the group the caller declared off-limits could still be rendered into
    ``kill_command`` — the one output of this tool that does damage when
    followed. The harvester never kills, which is exactly why the command it
    prints has to be right.
    """

    @staticmethod
    def _breach(text: str = _TREE_SPANNING_EXCLUDED_PS) -> Breach:
        breaches = find_breaches(
            parse_ps_output(text),
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_commands=("llm_qa.py all",),
            exclude_pgids=(_EXCLUDED_PGID,),
        )
        assert len(breaches) == 1, f"expected exactly one breach, got {breaches}"
        return breaches[0]

    def test_the_excluded_group_is_not_in_the_tree_pgids(self) -> None:
        assert _EXCLUDED_PGID not in self._breach().tree_pgids

    def test_the_excluded_group_is_not_in_the_kill_command(self) -> None:
        command = self._breach().kill_command
        assert f"-{_EXCLUDED_PGID}" not in command, (
            f"the suggested command names the group the caller excluded: {command}"
        )

    def test_the_groups_that_are_not_excluded_are_still_named(self) -> None:
        """Control: dropping every group would also pass the two tests above."""
        command = self._breach().kill_command
        assert "-5000" in command
        assert "-5001" in command

    def test_a_wholly_excluded_tree_falls_back_to_the_breaching_group(self) -> None:
        """A tree with nothing left to name must not produce a bare `kill --`.

        The breaching record's own group is always safe to fall back to: a
        record in an excluded group never becomes a breach at all.
        """
        text = """\
    PID    PPID    PGID  ELAPSED %CPU COMMAND
   5000      65    5000     9000  0.0 /bin/bash -c ./scripts/qa/llm_qa.py all
      1       0       1   100000  0.0 /sbin/init
"""
        breaches = find_breaches(
            parse_ps_output(text),
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_commands=("llm_qa.py all",),
            exclude_pgids=(5000,),
        )
        assert breaches == [], "a record in an excluded group must never breach"


class TestReadTrackedCommands:
    """The predecessor of this class read a ``pgid`` key (Plan 00236).

    It passed for as long as it existed, on records it invented itself — while
    the real writer emitted no ``pgid`` at all and the feature was dead. The
    fixtures below therefore mirror the PRODUCTION record shape, and the seam
    itself is pinned by
    ``tests/integration/test_background_tracker_harvester_roundtrip.py``, which
    runs the real writer against the real reader.
    """

    def test_missing_file_returns_empty(self, tmp_path):
        assert read_tracked_commands(tmp_path / "nope.jsonl") == []

    def test_reads_commands_skipping_malformed_lines(self, tmp_path):
        f = tmp_path / "bg.jsonl"
        f.write_text(
            json.dumps({"command": "sleep 600 &", "session_id": "s", "run_in_background": False})
            + "\n"
            + "not json\n"
            + json.dumps({"session_id": "s", "run_in_background": True})
            + "\n"
            + json.dumps({"command": "npm run dev", "session_id": "s", "run_in_background": True})
            + "\n"
        )
        assert read_tracked_commands(f) == ["sleep 600 &", "npm run dev"]

    def test_blank_commands_are_dropped(self, tmp_path):
        """A blank command would match every process in ``ps`` — never track it."""
        f = tmp_path / "bg.jsonl"
        f.write_text(
            json.dumps({"command": "", "session_id": "s"})
            + "\n"
            + json.dumps({"command": "   ", "session_id": "s"})
            + "\n"
            + json.dumps({"command": 42, "session_id": "s"})
            + "\n"
        )
        assert read_tracked_commands(f) == []


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
            tracked_commands=(),
        )
        assert report["has_breaches"] is True
        assert "kill -- -295967" in report["text"]
        assert "ugrep" in report["text"]

    def test_text_report_no_breaches_message(self):
        records = parse_ps_output("PID PPID PGID ELAPSED %CPU COMMAND\n1 0 1 999 0.0 /sbin/init\n")
        report = build_report(
            records,
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_commands=(),
        )
        assert report["has_breaches"] is False
        assert "NO RUNAWAY" in report["text"].upper()

    def test_json_report_is_serializable(self, records):
        report = build_report(
            records,
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_commands=(),
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
            tracked_commands=(),
        )
        assert "killed" not in report["text"].lower()


# A TTL breach on a HEALTHY long job, transcribed from a live `ps` during a QA
# run. Two things about it drive the tests below, and both are structural rather
# than incidental to this sample:
#
#   1. The TRACKED process is the wrapper shell background work is launched
#      through. It only ever waits on its child, so its own %CPU is 0.0 however
#      hard the job is working.
#   2. `python3` starts its OWN process group (3262451), so the wrapper is alone
#      in group 3262449 and every busy descendant is in a sibling group.
_WRAPPER_TTL_PS = """\
    PID    PPID    PGID  ELAPSED %CPU COMMAND
3262449      65 3262449      707  0.0 /bin/bash -c eval './scripts/qa/llm_qa.py all > qa15.txt'
3262451 3262449 3262451      707  0.0 python3 ./scripts/qa/llm_qa.py all
3264365 3262451 3262451      668  0.0 run_tests.sh
3264382 3264365 3262451      660 98.7 pytest tests/
      1       0       1   100000  0.0 /sbin/init
"""


class TestATtlBreachDescribesTheWholeJobNotTheWaiter:
    """A TTL breach line must describe the JOB, not the process that waits on it.

    An agent reads this report to answer one question — is this hung, or is it
    working? — and then runs or withholds the suggested `kill`. Both halves of
    the answer it was given were about the wrong process.

    **The %CPU.** The tracked process is the wrapper shell, blocked in `wait`, so
    for EVERY TTL breach of this shape the report says `0% CPU`. That reads as
    "hung, safe to reap" while the job is at full tilt. Not an unlucky sample —
    structural, and it points at the destructive answer.

    **The kill command.** Summing the process GROUP does not fix it either: an
    interpreter exec'd by the wrapper starts a NEW group, so the wrapper is
    alone in its own. That also made the suggested `kill -- -<pgid>` INCOMPLETE
    for this shape — it would have signalled the idle wrapper and left the real
    work running and orphaned, which is precisely the "killing one leaks the
    other" failure `kill_command` was introduced to prevent.

    Hit live: the report offered `kill -- -3262449` against a QA suite 79%
    through 24,412 tests, with a child at `STAT R` and 4:40 of accumulated CPU.
    Deciding correctly required going outside the tool entirely.

    A CPU breach is unaffected — there the breaching record IS the busy process.
    """

    @pytest.fixture
    def records(self):
        return parse_ps_output(_WRAPPER_TTL_PS)

    @staticmethod
    def _report(records):
        return build_report(
            records,
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_commands=("llm_qa.py all",),
        )

    def test_the_busy_descendant_is_visible_in_the_text(self, records):
        """The reader must be able to see the job is working, from the report alone."""
        report = self._report(records)

        assert report["has_breaches"] is True
        assert "99% CPU" in report["text"] or "98% CPU" in report["text"], (
            "the report shows only the wrapper's 0% CPU, so it reads as hung "
            f"while a descendant is at 98.7%:\n{report['text']}"
        )

    def test_the_tree_cpu_is_carried_in_the_json(self, records):
        """Whoever consumes the JSON decides on the same facts as the text reader."""
        report = self._report(records)

        breach = next(b for b in report["breaches"] if b["pid"] == 3262449)
        assert breach["tree_pcpu"] == pytest.approx(98.7)

    def test_the_kill_covers_every_group_the_job_spans(self, records):
        """Reaping only the wrapper's group orphans the work instead of stopping it."""
        report = self._report(records)

        breach = next(b for b in report["breaches"] if b["pid"] == 3262449)
        assert breach["tree_pgids"] == [3262449, 3262451]
        assert "-3262451" in breach["kill_command"], (
            "the suggested reap misses the group holding every busy process: "
            f"{breach['kill_command']}"
        )

    def test_a_genuinely_idle_job_still_reads_as_idle(self):
        """The fix must not make every stalled job look busy.

        Without this, 'report the tree's CPU' could be satisfied by printing a
        constant, and a truly hung job — the case where reaping is CORRECT —
        would be disguised exactly as badly in the other direction.
        """
        idle = parse_ps_output(
            "PID PPID PGID ELAPSED %CPU COMMAND\n"
            "555 65 555 700 0.0 /bin/bash -c eval 'llm_qa.py all'\n"
            "556 555 556 700 0.0 python3 llm_qa.py all\n"
        )

        report = self._report(idle)

        breach = next(b for b in report["breaches"] if b["pid"] == 555)
        assert breach["tree_pcpu"] == pytest.approx(0.0)

    def test_a_cpu_breach_still_reports_the_figure_that_tripped_it(self):
        """The runaway case must keep naming the number that breached the ceiling."""
        report = build_report(
            parse_ps_output(_INCIDENT_PS),
            max_wall_seconds=600,
            max_cpu_percent=400,
            min_cpu_runtime_seconds=60,
            tracked_commands=(),
        )

        assert "1116% CPU sustained" in report["text"]

    def test_a_self_parented_process_does_not_hang_the_walk(self):
        """`ps` reports pid 1 as its own parent on some systems; a cycle must terminate."""
        cyclic = parse_ps_output(
            "PID PPID PGID ELAPSED %CPU COMMAND\n1 1 1 100000 0.0 /sbin/init\n"
        )

        assert (
            find_breaches(
                cyclic, max_wall_seconds=600, max_cpu_percent=400, min_cpu_runtime_seconds=60
            )
            == []
        )
