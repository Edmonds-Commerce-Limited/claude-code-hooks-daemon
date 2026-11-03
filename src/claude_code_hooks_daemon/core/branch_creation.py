"""The verdict on creating one more branch (Plan 00558 Task 4.2, DESIGN section 3).

ONE ``git for-each-ref`` call counts the open work branches; the slow
inventory (``build_inventory``) is never run here because this sits on the
PreToolUse path. Local and remote refs of one name, and refs at one tip, are
one piece of work (union-find over names and tips), so a pushed branch or a
copy never counts twice.

At the cap the creation is denied (``wip.mode: block``) or warned about
(``warn``), naming every open branch with the cheapest way to close it first.
A name that looks like an existing branch's work draws a duplicate warning,
never a deny. Any git failure allows with a "could not judge" line: a guard
that cannot read the repository must not stop work it cannot see.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from claude_code_hooks_daemon.config.models import BRANCH_DEFAULT_AUTO, BranchesConfig
from claude_code_hooks_daemon.constants.branch_guard import BRANCH_LIMIT_PRINCIPLE
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.branch_inventory import (
    DormancyStage,
    is_work_branch,
    worktrees_by_branch,
)
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import run_git

logger = logging.getLogger(__name__)

LABELS_RELATIVE_PATH: Final[Path] = Path("untracked/branch-inventory/labels.json")
DENY_LIST_LIMIT: Final[int] = 20
DUPLICATE_LIST_LIMIT: Final[int] = 5

_HEADS: Final[str] = "refs/heads/"
_REMOTES: Final[str] = "refs/remotes/"
_FIELD_SEP: Final[str] = "\x00"
_FORMAT: Final[str] = "%(refname)%00%(objectname)%00%(committerdate:unix)%00%(symref)"
_SECONDS_PER_DAY: Final[float] = 86400.0
_STEM_PREFIXES: Final[tuple[str, ...]] = ("worktree-", "agent-")
_STEM_SUFFIX: Final[re.Pattern[str]] = re.compile(
    r"[-_](\d{1,2}|r\d+|v\d+|orig|old|new|retry\d*|again|redo|copy|bak|backup|[0-9a-f]{8})$"
)
_TOKEN_SPLIT: Final[re.Pattern[str]] = re.compile(r"[-_/.]")
_NUMBER_TOKEN: Final[re.Pattern[str]] = re.compile(r"^\d{2,5}$")
_ISSUE_TOKEN: Final[re.Pattern[str]] = re.compile(r"(?:issue|gh)-(\d+)")
_GROUP_ORDER: Final[tuple[str, ...]] = (
    "merged",
    "patch-equivalent",
    "contained-nowhere",
    "dormant",
    "live",
)

Decision = Literal["allow", "warn", "deny"]
Labels = Mapping[str, Mapping[str, str | None]]


@dataclass(frozen=True)
class CreationVerdict:
    """What to do about one creation, and the lines that explain it."""

    decision: Decision
    lines: tuple[str, ...]
    rule_id: str | None = None


@dataclass(frozen=True)
class _Ref:
    name: str
    tip: str
    committed: float
    local: bool


@dataclass(frozen=True)
class _Work:
    """One connected piece of work: every name and tip that join it."""

    name: str
    names: frozenset[str]
    committed: float


# --- naming ---------------------------------------------------------------------------


def stem(name: str, remote: str) -> str:
    """``name`` with its tool prefixes and retry/copy suffixes stripped, lower-cased."""
    current = name.lower()
    prefixes = (f"{remote.lower()}/", *_STEM_PREFIXES)
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if current.startswith(prefix) and len(current) > len(prefix):
                current = current.removeprefix(prefix)
                changed = True
    stripped = _STEM_SUFFIX.sub("", current)
    while stripped != current and stripped:
        current = stripped
        stripped = _STEM_SUFFIX.sub("", current)
    return current


def number_tokens(name: str) -> frozenset[str]:
    """The 2-5 digit tokens of ``name`` plus every ``issue-N``/``gh-N`` number."""
    tokens = {token for token in _TOKEN_SPLIT.split(name) if _NUMBER_TOKEN.match(token)}
    tokens.update(_ISSUE_TOKEN.findall(name.lower()))
    return frozenset(tokens)


# --- labels snapshot ------------------------------------------------------------------


def write_labels(path: Path, branches: list[dict[str, object]]) -> None:
    """Write ``{name: {group, action}}`` from ``report_json(...)["branches"]``."""
    labels = {
        str(record["name"]): {
            "group": record.get("group"),
            "action": record.get("action"),
            "stage": record.get("dormancy_stage"),
        }
        for record in branches
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(labels, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        log_and_continue(
            logger,
            exc,
            reason="the labels snapshot only orders the creation guard's deny list; "
            "without it the list falls back to names and ages",
        )


def read_labels(path: Path) -> dict[str, dict[str, str | None]]:
    """The labels snapshot, or ``{}`` when it is absent or unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log_and_continue(
            logger, exc, reason="an unreadable labels snapshot means names-only ordering"
        )
        return {}
    if not isinstance(data, dict):
        logger.info("branch_creation: labels snapshot is not an object: %s", path)
        return {}
    return {
        str(name): {str(key): value for key, value in entry.items()}
        for name, entry in data.items()
        if isinstance(entry, dict)
    }


# --- reading refs ---------------------------------------------------------------------


def _read_refs(repo: Path, config: BranchesConfig) -> tuple[list[_Ref], str | None] | str:
    """Every local (and remote) ref plus the default name, or git's error text."""
    namespaces = [_HEADS.rstrip("/")]
    if config.wip.count_remote:
        namespaces.append(f"{_REMOTES}{config.remote}")
    result = run_git(
        repo, "for-each-ref", f"--format={_FORMAT}", *namespaces, timeout=Timeout.GIT_CONTEXT
    )
    if result.returncode != 0:
        return result.stderr.strip() or f"git exited {result.returncode}"
    remote_prefix = f"{_REMOTES}{config.remote}/"
    head_ref = f"{remote_prefix}HEAD"
    default = None if config.default == BRANCH_DEFAULT_AUTO else config.default
    refs: list[_Ref] = []
    for line in result.stdout.splitlines():
        fields = line.split(_FIELD_SEP)
        if len(fields) != 4:
            continue
        refname, tip, committed, symref = fields
        if refname == head_ref:
            if default is None and symref.startswith(remote_prefix):
                default = symref.removeprefix(remote_prefix)
            continue
        local = refname.startswith(_HEADS)
        name = refname.removeprefix(_HEADS) if local else refname.removeprefix(remote_prefix)
        refs.append(_Ref(name, tip, float(committed or 0), local))
    return refs, default


def _work_groups(refs: list[_Ref]) -> list[_Work]:
    """Union-find over names and tips: one entry per connected piece of work."""
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for ref in refs:
        parent[find(f"n:{ref.name}")] = find(f"t:{ref.tip}")
    members: dict[str, list[_Ref]] = {}
    for ref in refs:
        members.setdefault(find(f"n:{ref.name}"), []).append(ref)
    groups: list[_Work] = []
    for group in members.values():
        local = sorted(ref.name for ref in group if ref.local)
        name = local[0] if local else sorted(ref.name for ref in group)[0]
        groups.append(
            _Work(
                name=name,
                names=frozenset(ref.name for ref in group),
                committed=max(ref.committed for ref in group),
            )
        )
    return groups


# --- rendering ------------------------------------------------------------------------


def _detail(work: _Work, now: float, worktrees: Mapping[str, Path] | None) -> str:
    age = max(0, int((now - work.committed) // _SECONDS_PER_DAY))
    where = worktrees.get(work.name) if worktrees is not None else None
    place = f", worktree {where}" if where is not None else ""
    return f"{work.name} ({age}d old{place})"


def _rank(work: _Work, labels: Labels) -> int:
    group = labels.get(work.name, {}).get("group")
    return _GROUP_ORDER.index(group) if group in _GROUP_ORDER else len(_GROUP_ORDER)


def _cap_lines(
    groups: list[_Work],
    config: BranchesConfig,
    labels: Labels,
    now: float,
    worktrees: Mapping[str, Path] | None,
) -> list[str]:
    ordered = sorted(groups, key=lambda work: (_rank(work, labels), work.committed, work.name))
    lines = [
        f"Open work branches: {len(groups)} (cap {config.wip.cap}). "
        "Finish, park or delete one before starting another:"
    ]
    for work in ordered[:DENY_LIST_LIMIT]:
        label = labels.get(work.name, {})
        group, action = label.get("group"), label.get("action")
        suffix = f"  [{group}]" if group else ""
        if action:
            suffix += f"  -> {action}"
        lines.append(f"  - {_detail(work, now, worktrees)}{suffix}")
    if len(ordered) > DENY_LIST_LIMIT:
        lines.append(f"  ... and {len(ordered) - DENY_LIST_LIMIT} more")
    lines.append(BRANCH_LIMIT_PRINCIPLE)
    return lines


def _dormant_work(
    groups: list[_Work], config: BranchesConfig, labels: Labels
) -> tuple[list[_Work], list[_Work]]:
    """``(block-stage, noisy-stage)`` work from the labels snapshot's inventory stages.

    The inventory already aged and parked-checked each branch when the snapshot
    was written, so no age is computed here. ``dormancy.mode: warn`` folds the
    block stage into the noisy one; ``off`` reports nothing.
    """
    mode = config.dormancy.mode
    if mode == "off":
        return [], []
    blocking: list[_Work] = []
    noisy: list[_Work] = []
    for work in groups:
        stage = next(
            (
                labels[name].get("stage")
                for name in (work.name, *sorted(work.names))
                if labels.get(name, {}).get("stage")
            ),
            None,
        )
        if stage == DormancyStage.BLOCK and mode == "block":
            blocking.append(work)
        elif stage in (DormancyStage.NOISY, DormancyStage.BLOCK):
            noisy.append(work)
    return blocking, noisy


def _dormancy_deny_lines(
    blocking: list[_Work], now: float, worktrees: Mapping[str, Path] | None
) -> list[str]:
    lines = [
        "Dormant branches are blocking new work. Finish and merge each one, park it "
        "(`hooks-daemon branch-park <name> --reason ...`), or delete it (`delete-branch`):"
    ]
    ordered = sorted(blocking, key=lambda work: (work.committed, work.name))
    lines.extend(f"  - {_detail(work, now, worktrees)}" for work in ordered[:DENY_LIST_LIMIT])
    if len(ordered) > DENY_LIST_LIMIT:
        lines.append(f"  ... and {len(ordered) - DENY_LIST_LIMIT} more")
    lines.append(BRANCH_LIMIT_PRINCIPLE)
    return lines


def _dormancy_context_lines(
    noisy: list[_Work], now: float, worktrees: Mapping[str, Path] | None
) -> list[str]:
    ordered = sorted(noisy, key=lambda work: (work.committed, work.name))
    details = ", ".join(_detail(work, now, worktrees) for work in ordered[:DUPLICATE_LIST_LIMIT])
    return [
        f"Dormant branches need attention: {details}. Finish, park "
        "(`hooks-daemon branch-park <name> --reason ...`) or delete them."
    ]


def _duplicates(new_name: str, groups: list[_Work], remote: str) -> list[_Work]:
    new_stem = stem(new_name, remote)
    new_numbers = number_tokens(new_stem)
    found: list[_Work] = []
    for work in groups:
        if new_name in work.names:
            continue
        other = stem(work.name, remote)
        if other == new_stem or new_numbers & number_tokens(other):
            found.append(work)
    return sorted(found, key=lambda work: -work.committed)


# --- the verdict ----------------------------------------------------------------------


def creation_verdict(
    repo: Path,
    config: BranchesConfig,
    new_name: str | None,
    *,
    labels: Labels | None = None,
    now: float | None = None,
    name_is_branch: bool = True,
) -> CreationVerdict:
    """Judge creating one more branch in ``repo``.

    Args:
        repo: Any directory inside the repository.
        config: The ``branches:`` configuration.
        new_name: The name being created (or, for an Agent dispatch, the agent's
            name, used for the duplicate check only); None when unknown.
        labels: The SessionStart labels snapshot, ``{name: {group, action}}``.
        now: The clock, for ages; defaults to the current time.
        name_is_branch: When True a ``new_name`` already in ``refs/heads`` is a
            reset or a checkout, not a creation, and is allowed silently.

    Returns:
        The decision and its explanation lines.
    """
    read = _read_refs(repo, config)
    if isinstance(read, str):
        return CreationVerdict(
            "allow", (f"Branch limit: could not judge this creation (git: {read}).",)
        )
    refs, default = read
    if name_is_branch and new_name is not None:
        if any(ref.local and ref.name == new_name for ref in refs):
            return CreationVerdict("allow", ())
    work_refs = [ref for ref in refs if is_work_branch(ref.name, config, default)]
    groups = _work_groups(work_refs)
    moment = time.time() if now is None else now
    over_cap = config.wip.mode != "off" and len(groups) >= config.wip.cap
    duplicates = (
        _duplicates(new_name, groups, config.remote)
        if new_name and config.duplicates.mode == "warn"
        else []
    )
    blocking, noisy = _dormant_work(groups, config, labels or {})
    if not over_cap and not duplicates and not blocking and not noisy:
        return CreationVerdict("allow", ())
    worktrees = worktrees_by_branch(repo)
    lines: list[str] = []
    if duplicates:
        for work in duplicates[:DUPLICATE_LIST_LIMIT]:
            lines.append(
                f"A branch for this work may already exist: {_detail(work, moment, worktrees)}"
                " -- continue there instead of opening another."
            )
    if over_cap:
        lines.extend(_cap_lines(groups, config, labels or {}, moment, worktrees))
    if blocking:
        lines.extend(_dormancy_deny_lines(blocking, moment, worktrees))
    elif noisy:
        lines.extend(_dormancy_context_lines(noisy, moment, worktrees))
    cap_deny = over_cap and config.wip.mode == "block"
    if cap_deny:
        return CreationVerdict("deny", tuple(lines), RuleID.BRANCH_WIP_CAP)
    if blocking:
        return CreationVerdict("deny", tuple(lines), RuleID.BRANCH_DORMANT)
    if over_cap or duplicates:
        return CreationVerdict("warn", tuple(lines))
    return CreationVerdict("allow", tuple(lines))
