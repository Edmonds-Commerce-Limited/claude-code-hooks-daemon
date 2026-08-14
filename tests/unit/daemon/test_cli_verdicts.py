"""Tests for the ``verdicts`` CLI command (Plan 00209 Task 2.5).

A real ``--log-file`` override is supplied so the command does not touch
ProjectContext (mirrors ``test_cli_harvest_background.py``'s ``--state-file``
pattern) and stays deterministic/process-free. The daemon-query path for
``never_fired`` is exercised separately since it degrades gracefully when no
daemon is running (``read_pid_file`` returns ``None``).
"""

import argparse
import json

from claude_code_hooks_daemon.daemon import cli


def _args(tmp_path, **overrides):
    # pid_file defaults to a path that can never exist, so every test is
    # hermetic and never accidentally queries this REAL project's own
    # daemon (get_project_path(None) would otherwise resolve from cwd,
    # which — running inside the daemon's own repo — has a real .claude/).
    ns = argparse.Namespace(
        log_file=str(tmp_path / "verdicts.jsonl"),
        json=False,
        project_root=None,
        pid_file=str(tmp_path / "no-daemon-here.pid"),
        socket=None,
    )
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


def _write_verdicts(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


class TestBehaviouralHandlerNames:
    """Status renderers must not become false "never-fired" entries.

    Plan 00234/00236: Status events are no longer recorded to verdicts.jsonl
    (they were 99.43% of the volume and always ``allow``). Left unhandled, that
    would put all 14 status handlers into the report's "never-fired" list —
    replacing one misleading signal with another, which is the failure mode
    this whole audit exists to stop.

    Fired-ness is a question about handlers that DECIDE. A renderer has no
    verdict to record, so it does not belong in that roster at all.
    """

    def test_status_handlers_are_excluded(self):
        handlers = {
            "Status": [{"name": "status-git-branch"}, {"name": "status-model-context"}],
            "PreToolUse": [{"name": "pipe-blocker"}],
        }
        assert cli._behavioural_handler_names(handlers) == ["pipe-blocker"]

    def test_pseudo_event_handlers_are_excluded(self):
        """Their verdicts are never recorded, so counting them guarantees never-fired.

        `_record_verdicts` runs BEFORE the pseudo dispatch, and pseudo results
        merge as HookResult, which carries no per-handler verdict — so no
        pseudo verdict can reach the log. Keeping them on the registered side
        of `registered - fired` therefore reported live handlers as dead
        forever. Verified against the running daemon: both nitpick handlers
        appeared in never_fired while firing normally.
        """
        handlers = {
            "pseudo-events": [
                {"name": "nitpick-dismissive-language"},
                {"name": "nitpick-hedging-language"},
            ],
            "PreToolUse": [{"name": "pipe-blocker"}],
        }
        assert cli._behavioural_handler_names(handlers) == ["pipe-blocker"]

    def test_non_status_events_are_all_kept(self):
        handlers = {
            "PreToolUse": [{"name": "a"}, {"name": "b"}],
            "Stop": [{"name": "c"}],
        }
        assert sorted(cli._behavioural_handler_names(handlers)) == ["a", "b", "c"]

    def test_entries_without_a_name_are_skipped(self):
        handlers = {"PreToolUse": [{"name": "a"}, {}, {"name": ""}]}
        assert cli._behavioural_handler_names(handlers) == ["a"]

    def test_empty_listing_is_empty(self):
        assert cli._behavioural_handler_names({}) == []


def test_no_log_file_reports_zero_records(tmp_path, capsys):
    rc = cli.cmd_verdicts(_args(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Total recorded decisions: 0" in out


def test_reports_handler_counts_from_log(tmp_path, capsys):
    log_file = tmp_path / "verdicts.jsonl"
    _write_verdicts(
        log_file,
        [
            {"handler": "pipe_blocker", "verdict": "deny", "overridden": False},
            {"handler": "pipe_blocker", "verdict": "deny", "overridden": False},
            {"handler": "absolute_path", "verdict": "allow", "overridden": False},
        ],
    )

    rc = cli.cmd_verdicts(_args(tmp_path))
    out = capsys.readouterr().out

    assert rc == 0
    assert "pipe_blocker: 2" in out
    assert "absolute_path: 1" in out


def test_json_output_is_parseable(tmp_path, capsys):
    log_file = tmp_path / "verdicts.jsonl"
    _write_verdicts(
        log_file,
        [{"handler": "pipe_blocker", "verdict": "deny", "overridden": False}],
    )

    rc = cli.cmd_verdicts(_args(tmp_path, json=True))
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["handler_counts"] == {"pipe_blocker": 1}


def test_reports_override_rate(tmp_path, capsys):
    log_file = tmp_path / "verdicts.jsonl"
    _write_verdicts(
        log_file,
        [
            {"handler": "absolute_path", "verdict": "allow", "overridden": False},
            {"handler": None, "verdict": "override", "overridden": True},
        ],
    )

    rc = cli.cmd_verdicts(_args(tmp_path))
    out = capsys.readouterr().out

    assert rc == 0
    assert "Overrides" in out
    assert "50.0%" in out


def test_no_daemon_running_reports_never_fired_as_unavailable(tmp_path, capsys):
    """No pid file resolvable at the (nonexistent) default paths -> the
    report degrades gracefully rather than crashing."""
    log_file = tmp_path / "verdicts.jsonl"
    _write_verdicts(
        log_file,
        [{"handler": "pipe_blocker", "verdict": "deny", "overridden": False}],
    )

    rc = cli.cmd_verdicts(_args(tmp_path, pid_file=str(tmp_path / "does-not-exist.pid")))
    out = capsys.readouterr().out

    assert rc == 0
    assert "Never-fired handlers: unavailable" in out
