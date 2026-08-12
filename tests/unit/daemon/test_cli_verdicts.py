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

    rc = cli.cmd_verdicts(
        _args(tmp_path, pid_file=str(tmp_path / "does-not-exist.pid"))
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Never-fired handlers: unavailable" in out
