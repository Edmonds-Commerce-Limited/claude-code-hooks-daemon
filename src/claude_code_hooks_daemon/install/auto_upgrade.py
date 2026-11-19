"""Eligibility pre-check for an automatic (unattended) daemon upgrade (Plan 00625).

The SessionStart ``version_check`` asks this module whether the project's
shipped-default authorisation (``daemon-auto-upgrade``) is in force and whether
the cheap, LOCAL facts allow an unattended upgrade at all. It starts nothing and
touches no network: the scripts (``upgrade.sh --unattended`` and the target's
Layer 2) enforce the same rules again, so this is only what lets the advisory
say "run it now" instead of "a human must".

``upgrade.sh`` records an attempt per target version when an unattended run
ends in a rollback, a failure or a needs-human stop, as
``<daemon untracked dir>/auto-upgrade/v<version>.state`` (``key=value`` lines:
``status`` = ``failed`` | ``needs-human``, ``target``, ``from``, ``detail``,
the shape ``background_sync`` records use). While one exists for the latest
release it is not tried again; a newer release has no record.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import yaml

from claude_code_hooks_daemon.handlers.user_prompt_submit.standing_authorisations import (
    auto_upgrade_authorised,
)
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

logger = logging.getLogger(__name__)

#: Under the daemon's untracked directory. Spelled in ``scripts/upgrade.sh`` as
#: well, which writes the records.
ATTEMPT_DIR_NAME: Final[str] = "auto-upgrade"

_STATE_SUFFIX: Final[str] = ".state"

#: Relative to the project root; exists only while a release is in flight.
_RELEASE_STATE_RELATIVE: Final[Path] = Path("untracked") / "release-state.json"

_HANDLERS_KEY: Final[str] = "handlers"
_EVENT_KEY: Final[str] = "user_prompt_submit"
_HANDLER_KEY: Final[str] = "standing_authorisations"

_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"\A(\d+)\.(\d+)\.(\d+)\Z")

#: Project-relative paths the upgrade rewrites and the skill's commit step
#: stages (skill step 7). A trailing slash is a directory prefix. Uncommitted
#: work under one of these refuses an unattended run; other uncommitted work in
#: the project is never staged by the upgrade, so it does not (relayed ruling,
#: Plan 00625 DESIGN 11a item 5). Mirrored in ``upgrade.sh``
#: ``_is_upgrade_owned_path``.
UPGRADE_OWNED_PATHS: Final[tuple[str, ...]] = (
    ".claude/hooks-daemon/",
    ".claude/hooks-daemon.yaml",
    ".claude/skills/hooks-daemon/",
    ".claude/hooks/",
    ".claude/settings.json",
)

_GIT_STATUS_TIMEOUT_SECONDS: Final[float] = 10.0


def _is_upgrade_owned(path: str) -> bool:
    return any(
        path.startswith(owned) if owned.endswith("/") else path == owned
        for owned in UPGRADE_OWNED_PATHS
    )


def _status_paths(root: Path) -> list[str] | None:
    """Paths ``git status`` reports dirty under ``root``; None when it cannot be read."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "-z", "--untracked-files=all"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_STATUS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log_and_continue(
            logger,
            exc,
            reason="an unreadable git status cannot be shown clean, so it refuses",
            level=logging.DEBUG,
        )
        return None
    if result.returncode != 0:
        return None
    paths: list[str] = []
    rename_source = False
    for entry in result.stdout.split("\0"):
        if not entry:
            continue
        if rename_source:
            rename_source = False
            paths.append(entry)
            continue
        if "R" in entry[:2] or "C" in entry[:2]:
            rename_source = True
        paths.append(entry[3:])
    return paths


def _uncommitted_work_reasons(project_root: Path, daemon_dir: Path) -> list[str]:
    reasons: list[str] = []
    if (project_root / ".git").exists():
        project_paths = _status_paths(project_root)
        if project_paths is None:
            reasons.append("the project's git status cannot be read")
        else:
            owned = [p for p in project_paths if _is_upgrade_owned(p)]
            if owned:
                reasons.append(
                    f"the project has uncommitted changes in a path the upgrade rewrites ({owned[0]})"
                )
    if (daemon_dir / ".git").exists():
        clone_paths = _status_paths(daemon_dir)
        if clone_paths is None:
            reasons.append("the daemon clone's git status cannot be read")
        elif clone_paths:
            reasons.append("the daemon clone has uncommitted changes")
    return reasons


class AttemptStatus(StrEnum):
    """How an unattended upgrade attempt to one target ended."""

    FAILED = "failed"
    NEEDS_HUMAN = "needs-human"


@dataclass(frozen=True)
class AttemptRecord:
    """What ``upgrade.sh`` recorded about an unattended attempt to one version."""

    status: AttemptStatus
    target: str
    from_version: str
    detail: str
    state_path: Path


@dataclass(frozen=True)
class Eligibility:
    """Whether an unattended upgrade may be invited, and why not when it may not."""

    eligible: bool
    reasons: list[str]


def attempt_state_path(untracked_dir: Path, version: str) -> Path:
    """The attempt record of the unattended upgrade to ``version``."""
    return untracked_dir / ATTEMPT_DIR_NAME / f"v{version}{_STATE_SUFFIX}"


def read_attempt_record(untracked_dir: Path, version: str) -> AttemptRecord | None:
    """Read the attempt record for ``version``; None when none was ever written.

    A record that cannot be read, or names no known status, is a FAILED record
    saying so: it exists only because an attempt happened, and treating it as
    absent would retry an upgrade nobody has looked at.
    """
    path = attempt_state_path(untracked_dir, version)
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except OSError as exc:
        return AttemptRecord(
            status=AttemptStatus.FAILED,
            target=version,
            from_version="",
            detail=f"the attempt record {path} cannot be read ({exc})",
            state_path=path,
        )
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key] = value
    try:
        status = AttemptStatus(fields.get("status", ""))
    except ValueError:
        return AttemptRecord(
            status=AttemptStatus.FAILED,
            target=fields.get("target", version),
            from_version=fields.get("from", ""),
            detail=f"the attempt record {path} names no known status",
            state_path=path,
        )
    return AttemptRecord(
        status=status,
        target=fields.get("target", version),
        from_version=fields.get("from", ""),
        detail=fields.get("detail", ""),
        state_path=path,
    )


def project_authorises_auto_upgrade(config_path: Path) -> bool:
    """Whether the project's config leaves ``daemon-auto-upgrade`` in force.

    An absent handler block or entry is the shipped default (authorised). A
    config that is missing, unreadable or not a mapping is NOT authorised: an
    opt-out may be written in it, and that cannot be ruled out.
    """
    try:
        document: Any = yaml.safe_load(config_path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        log_and_continue(
            logger,
            exc,
            reason=(
                "a config that cannot be read or parsed may hold the daemon-auto-upgrade "
                "opt-out, so the upgrade is not treated as authorised"
            ),
            level=logging.DEBUG,
        )
        return False
    if document is None:
        return True
    if not isinstance(document, dict):
        return False
    handlers = document.get(_HANDLERS_KEY)
    event = handlers.get(_EVENT_KEY) if isinstance(handlers, dict) else None
    block = event.get(_HANDLER_KEY) if isinstance(event, dict) else None
    return auto_upgrade_authorised(block if isinstance(block, dict) else None)


def _parse_version(version: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.match(version)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def check_eligibility(
    *,
    installed: str,
    latest: str,
    authorised: bool,
    self_install: bool,
    project_root: Path,
    untracked_dir: Path,
    daemon_dir: Path | None = None,
) -> Eligibility:
    """Judge whether an unattended upgrade from ``installed`` to ``latest`` may be invited.

    Every refusal that applies is listed, so the advisory can say all of them.
    Reads the release-in-flight marker and the attempt record and, when
    ``daemon_dir`` is given, runs ``git status`` in the project and the clone
    for uncommitted work the upgrade would collide with; no network.
    """
    reasons: list[str] = []
    if not authorised:
        reasons.append("automatic upgrades are not authorised in this project's config")
    if self_install:
        reasons.append("this is the daemon's own repository, where the source is the latest")
    if (project_root / _RELEASE_STATE_RELATIVE).exists():
        reasons.append("a release is in progress (untracked/release-state.json exists)")

    current = _parse_version(installed)
    target = _parse_version(latest)
    if current is None or target is None:
        reasons.append(f"versions v{installed} and v{latest} cannot be compared")
    else:
        if target <= current:
            reasons.append(f"v{latest} is not newer than the installed v{installed}")
        elif target[0] > current[0]:
            reasons.append(f"v{latest} is a MAJOR version bump from v{installed}")

    record = read_attempt_record(untracked_dir, latest)
    if record is not None:
        reasons.append(
            f"an unattended upgrade to v{latest} was already attempted "
            f"(status {record.status.value}: {record.detail or 'no detail recorded'})"
        )
    if daemon_dir is not None and not self_install:
        reasons.extend(_uncommitted_work_reasons(project_root, daemon_dir))
    return Eligibility(eligible=not reasons, reasons=reasons)
