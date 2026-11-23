"""The ``team-seat`` command: print this session's resolved teamchat roles.

Plan 00631 Task 2.3. ``bin/hooks-daemon team-seat [--json]`` reads the
teamchat signals from its OWN environment (the session it is typed in), honours
the ``team_seat`` config block's ``detection`` setting, and runs the kit's
``whoami --json`` once, uncached. It prints the state, the reason category and
the validated per-team role, duty and handle. It never prints the raw command
output or the signal paths, and it opens nothing under teamchat's stores.

Exit codes::

    0  resolved, or absent (no team: nothing to report is a normal answer)
    3  unresolved (a team is signalled but the role could not be read)
    4  usage or configuration error (a malformed ``team_seat`` block)
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final, TextIO

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import TeamSeatConfig
from claude_code_hooks_daemon.daemon.validation import load_config_safe
from claude_code_hooks_daemon.utils.teamchat_seat import (
    UNKNOWN,
    CommandRunner,
    SeatContext,
    SeatState,
    SessionSignals,
    default_command_runner,
    probe_seat_context,
)

EXIT_OK: Final[int] = 0
EXIT_UNRESOLVED: Final[int] = 3
EXIT_USAGE: Final[int] = 4

CONFIG_KEY: Final[str] = "team_seat"


def load_team_seat_config(project_root: Path) -> TeamSeatConfig:
    """The project's ``team_seat`` block, or the defaults when absent.

    Raises:
        ValueError: The block is present but invalid.
    """
    config = load_config_safe(project_root) or {}
    block = config.get(CONFIG_KEY)
    if block is None:
        return TeamSeatConfig()
    try:
        return TeamSeatConfig.model_validate(block)
    except ValidationError as exc:
        raise ValueError(f"invalid {CONFIG_KEY} block: {exc.error_count()} error(s)") from exc


def _team_rows(context: SeatContext) -> list[dict[str, str]]:
    return [
        {
            "team": seat.team,
            "role": context.role_in(seat.team) or UNKNOWN,
            "duty": context.duty_in(seat.team) or UNKNOWN,
            "handle": seat.handle,
        }
        for seat in context.seats
    ]


def _write_text(context: SeatContext, stdout: TextIO) -> None:
    stdout.write(f"state: {context.state.value}\n")
    stdout.write(f"reason: {context.reason.value}\n")
    for row in _team_rows(context):
        handle = f"  handle {row['handle']}" if row["handle"] else ""
        stdout.write(f"team {row['team']}: role {row['role']}  duty {row['duty']}{handle}\n")
    for team in context.duplicate_teams:
        stdout.write(f"advisory: team {team} listed more than once\n")


def _write_json(context: SeatContext, stdout: TextIO) -> None:
    document = {
        "state": context.state.value,
        "reason": context.reason.value,
        "teams": _team_rows(context),
        "duplicate_teams": list(context.duplicate_teams),
    }
    stdout.write(json.dumps(document, indent=2) + "\n")


def run_team_seat(
    *,
    signals: SessionSignals,
    config: TeamSeatConfig,
    as_json: bool,
    stdout: TextIO,
    runner: CommandRunner = default_command_runner,
) -> int:
    """Probe once and print the answer. Never raises on a probe failure."""
    context = probe_seat_context(signals, detection_enabled=config.detection_enabled, runner=runner)
    if as_json:
        _write_json(context, stdout)
    else:
        _write_text(context, stdout)
    if context.state is SeatState.UNRESOLVED:
        return EXIT_UNRESOLVED
    return EXIT_OK


def main(
    *,
    project_root: Path,
    environ: Mapping[str, str],
    as_json: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """The command entry: load config, read ``environ``'s signals, probe, print."""
    try:
        config = load_team_seat_config(project_root)
    except ValueError as exc:
        stderr.write(f"error: {exc}\n")
        return EXIT_USAGE
    return run_team_seat(
        signals=SessionSignals.from_environ(environ),
        config=config,
        as_json=as_json,
        stdout=stdout,
    )
