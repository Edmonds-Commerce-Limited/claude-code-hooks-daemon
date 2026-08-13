"""Tests for the ``harvest-background`` CLI command (Plan 00142, Layer B).

Verifies exit-code contract (0 = clean, 1 = breaches surfaced) and that the
command NEVER kills — it only reports. ``run_ps`` is monkeypatched so the test
is deterministic and process-free; a real ``--state-file`` is supplied so the
command does not touch ProjectContext.
"""

import argparse
import json

from claude_code_hooks_daemon.daemon import background_harvester, cli

_CLEAN_PS = "PID PGID ELAPSED %CPU COMMAND\n1 1 99999 0.0 /sbin/init\n"
_RUNAWAY_PS = (
    "PID PGID ELAPSED %CPU COMMAND\n"
    "295971 295967 6918 1116 ugrep -rl class /\n"
    "1 1 99999 0.0 /sbin/init\n"
)


def _args(tmp_path, **overrides):
    ns = argparse.Namespace(
        max_wall_seconds=600,
        max_cpu_percent=400.0,
        min_cpu_runtime_seconds=60,
        state_file=str(tmp_path / "bg.jsonl"),
        format="text",
        project_root=None,
    )
    for key, value in overrides.items():
        setattr(ns, key, value)
    return ns


def test_clean_system_returns_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(background_harvester, "run_ps", lambda: _CLEAN_PS)
    rc = cli.cmd_harvest_background(_args(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert "NO RUNAWAYS" in out.upper()


def test_runaway_returns_one_and_suggests_group_kill(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(background_harvester, "run_ps", lambda: _RUNAWAY_PS)
    rc = cli.cmd_harvest_background(_args(tmp_path))
    out = capsys.readouterr().out
    assert rc == 1
    assert "kill -- -295967" in out
    # NEVER reports an actual kill — only suggests one.
    assert "killed" not in out.lower()


def test_json_format(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(background_harvester, "run_ps", lambda: _RUNAWAY_PS)
    rc = cli.cmd_harvest_background(_args(tmp_path, format="json"))
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["has_breaches"] is True
    assert any("ugrep" in b["args"] for b in payload["breaches"])


def test_ps_failure_returns_two(tmp_path, monkeypatch, capsys):
    def _boom():
        raise OSError("ps not found")

    monkeypatch.setattr(background_harvester, "run_ps", _boom)
    rc = cli.cmd_harvest_background(_args(tmp_path))
    err = capsys.readouterr().err
    assert rc == 2
    assert "ps" in err.lower()


def test_tracked_command_over_ttl_is_surfaced(tmp_path, monkeypatch, capsys):
    # A low-CPU but long-lived process is only flagged when it was tracked.
    # The state record is the PRODUCTION shape the tracker writes (Plan 00236):
    # no pgid — the daemon never learns one — so correlation is by command text.
    state = tmp_path / "bg.jsonl"
    state.write_text(
        json.dumps({"command": "node server", "session_id": "s", "run_in_background": True}) + "\n"
    )
    monkeypatch.setattr(
        background_harvester,
        "run_ps",
        lambda: "PID PGID ELAPSED %CPU COMMAND\n500 500 9999 0.2 node server\n",
    )
    rc = cli.cmd_harvest_background(_args(tmp_path, state_file=str(state)))
    out = capsys.readouterr().out
    assert rc == 1
    assert "kill -- -500" in out


def test_untracked_long_lived_process_is_not_surfaced(tmp_path, monkeypatch, capsys):
    """The scoping that keeps the wall TTL bearable, asserted through the CLI.

    Without it the harvester would nag about every dev server and system
    daemon on the box, which is why the TTL was scoped to tracked work in the
    first place.
    """
    state = tmp_path / "bg.jsonl"
    state.write_text(
        json.dumps({"command": "npm run dev", "session_id": "s", "run_in_background": True}) + "\n"
    )
    monkeypatch.setattr(
        background_harvester,
        "run_ps",
        lambda: "PID PGID ELAPSED %CPU COMMAND\n500 500 9999 0.2 node server\n",
    )

    rc = cli.cmd_harvest_background(_args(tmp_path, state_file=str(state)))

    assert rc == 0
    assert "NO RUNAWAYS" in capsys.readouterr().out
