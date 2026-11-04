"""The branch sweep report (Plan 00558 Tasks 2.2 and 2.3, DESIGN.md sections 2-4).

Turns a :class:`~claude_code_hooks_daemon.core.branch_inventory.BranchInventory`
into the three things people read: the ``hooks-daemon branch-sweep`` text, its
``--json`` document, and the short SessionStart summary. Nothing here runs git;
every verdict comes from the inventory, so the CLI and the SessionStart line
cannot disagree.

Fail-closed reading of the inventory: a dormant branch whose containment was
not measured is listed as dormant with "containment not measured", never as
contained (a cleanup candidate) and never silently dropped; an unclassified
branch is listed with its reason; a remote-only merged branch whose proof is an
unpushed local ref gets no delete command.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.branch_inventory import (
    BranchInventory,
    BranchRecord,
    BranchState,
    Containment,
)
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs

#: Entry lines the SessionStart summary prints before "and N more".
MAX_SUMMARY_LINES = 10


def sweep_command() -> str:
    """The ``branch-sweep`` invocation, spelled for this install's wrapper."""
    return daemon_cli_command_for_docs("branch-sweep")


def delete_command() -> str:
    """The ``delete-branch`` invocation, spelled for this install's wrapper."""
    return daemon_cli_command_for_docs("delete-branch")


#: The ``branch_count_advisor`` options read for one release as fallbacks, and
#: the ``branches.*`` key that replaces each (DESIGN.md section 1).
LEGACY_OPTION_KEYS: dict[str, str] = {
    "max_open_branches": "branches.wip.cap",
    "behind_main_threshold": "branches.sweep.behind_threshold",
}

#: Keys of every record in the ``--json`` document, in output order.
JSON_RECORD_KEYS: tuple[str, ...] = (
    "name",
    "state",
    "group",
    "local_tip",
    "remote_tip",
    "upstream",
    "worktree",
    "worktree_known",
    "ahead",
    "behind",
    "lines",
    "committed_at",
    "age_days",
    "parked_reason",
    "plan",
    "issue",
    "merged_into",
    "proven_by",
    "reason",
    "same_tip_as",
    "dormancy_stage",
    "containment",
    "contained_in",
    "action",
)

_NEVER_WORK = frozenset(
    {
        BranchState.EXEMPT,
        BranchState.DEFAULT,
        BranchState.INTEGRATION_LINE,
        BranchState.PROTECTED,
    }
)
_MERGED = frozenset({BranchState.MERGED_DEFAULT, BranchState.MERGED_LINE})


@dataclass(frozen=True)
class SweepGroups:
    """Records by report group, actionable groups first; each sorted by name."""

    contained_nowhere: tuple[BranchRecord, ...]
    merged: tuple[BranchRecord, ...]
    patch_equivalent: tuple[BranchRecord, ...]
    dormant: tuple[BranchRecord, ...]
    live: tuple[BranchRecord, ...]
    parked: tuple[BranchRecord, ...]
    unclassified: tuple[BranchRecord, ...]
    never_work: tuple[BranchRecord, ...]


def _group_name(record: BranchRecord) -> str:
    """The report group of one record (the ``group`` key of the JSON)."""
    state = record.state
    if state in _NEVER_WORK:
        return "not-work"
    if state in _MERGED:
        return "merged"
    if state == BranchState.PATCH_EQUIVALENT:
        return "patch-equivalent"
    if state == BranchState.DORMANT:
        if record.containment == Containment.NOWHERE:
            return "contained-nowhere"
        return "dormant"
    if state == BranchState.PARKED:
        return "parked"
    if state == BranchState.LIVE:
        return "live"
    return "unclassified"


def group_records(inventory: BranchInventory) -> SweepGroups:
    """Sort every record of ``inventory`` into its report group."""
    buckets: dict[str, list[BranchRecord]] = {}
    for name in sorted(inventory.records):
        record = inventory.records[name]
        buckets.setdefault(_group_name(record), []).append(record)

    def take(group: str) -> tuple[BranchRecord, ...]:
        return tuple(buckets.get(group, ()))

    return SweepGroups(
        contained_nowhere=take("contained-nowhere"),
        merged=take("merged"),
        patch_equivalent=take("patch-equivalent"),
        dormant=take("dormant"),
        live=take("live"),
        parked=take("parked"),
        unclassified=take("unclassified"),
        never_work=take("not-work"),
    )


def open_work_count(inventory: BranchInventory) -> int:
    """Open work branches, identical tips counted once (DESIGN.md section 3).

    Every branch that is not exempt, the default, an integration line or a
    protected name counts, merged and unclassified ones included: a branch
    still exists until it is deleted. Names linked by ``same_tip_as`` count as
    one.
    """
    work = {
        name: record
        for name, record in inventory.records.items()
        if record.state not in _NEVER_WORK
    }
    seen: set[str] = set()
    groups = 0
    for name in sorted(work):
        if name in seen:
            continue
        groups += 1
        pending = [name]
        while pending:
            current = pending.pop()
            if current in seen or current not in work:
                continue
            seen.add(current)
            pending.extend(work[current].same_tip_as)
    return groups


def effective_wip_cap(config: BranchesConfig, legacy_options: Mapping[str, Any]) -> int:
    """``branches.wip.cap`` if set, else the old ``max_open_branches``, else the default."""
    explicit = config.explicit_wip_cap()
    if explicit is not None:
        return explicit
    legacy = legacy_options.get("max_open_branches")
    if isinstance(legacy, int) and not isinstance(legacy, bool) and legacy >= 1:
        return legacy
    return config.wip.cap


def effective_behind_threshold(config: BranchesConfig, legacy_options: Mapping[str, Any]) -> int:
    """``sweep.behind_threshold`` if set, else ``behind_main_threshold``, else the default."""
    explicit = config.explicit_behind_threshold()
    if explicit is not None:
        return explicit
    legacy = legacy_options.get("behind_main_threshold")
    if isinstance(legacy, int) and not isinstance(legacy, bool) and legacy >= 1:
        return legacy
    return config.sweep.behind_threshold


def _far_behind(inventory: BranchInventory, threshold: int) -> list[BranchRecord]:
    """Unmerged work branches more than ``threshold`` commits behind the default."""
    done = _NEVER_WORK | _MERGED | {BranchState.PATCH_EQUIVALENT}
    return [
        inventory.records[name]
        for name in sorted(inventory.records)
        if inventory.records[name].state not in done
        and (inventory.records[name].behind or 0) > threshold
    ]


def deprecation_line(config: BranchesConfig, legacy_options: Mapping[str, Any]) -> str | None:
    """The one-release notice for old options still set while their new key is not."""
    explicit = {
        "max_open_branches": config.explicit_wip_cap(),
        "behind_main_threshold": config.explicit_behind_threshold(),
    }
    stale = [
        f"`options.{old}` -> `{new}`"
        for old, new in LEGACY_OPTION_KEYS.items()
        if old in legacy_options and explicit[old] is None
    ]
    if not stale:
        return None
    return (
        "Deprecated: handlers.session_start.branch_count_advisor options are read for one "
        f"more release only; move {', '.join(stale)} in .claude/hooks-daemon.yaml."
    )


# --- per-record text ---------------------------------------------------------------


def _age(record: BranchRecord) -> str:
    return "age unknown" if record.age_days is None else f"{int(record.age_days)}d old"


def _where(record: BranchRecord) -> str:
    if not record.worktree_known:
        return ", worktree unknown"
    return f", worktree {record.worktree}" if record.worktree is not None else ""


def push_command(record: BranchRecord, config: BranchesConfig) -> str:
    """The one command that secures a branch no remote holds."""
    return f"git push -u {config.remote} {record.name}"


def delete_action(record: BranchRecord, inventory: BranchInventory, config: BranchesConfig) -> str:
    """How to delete a done branch, never a raw force delete.

    A local copy is deleted through ``delete-branch``, which proves the claim
    again before it deletes; a target other than the default is passed as
    ``--protected-ref``. A remote-only branch proven only by an unpushed local
    ref gets no command: the push of that ref comes first.
    """
    remote_prefix = f"{config.remote}/"
    proven = record.proven_by
    if record.local_tip is None:
        if proven is not None and proven.startswith(remote_prefix):
            return f"remote only: git push {config.remote} --delete {record.name}"
        return f"remote only, proven by the unpushed {proven}: push {proven} first"
    command = f"{delete_command()} {record.name}"
    if record.merged_into is not None and record.merged_into != inventory.default_branch:
        command += f" --protected-ref {proven or record.merged_into}"
    return command


def _done_line(record: BranchRecord, inventory: BranchInventory, config: BranchesConfig) -> str:
    verb = "patch-equivalent to" if record.state == BranchState.PATCH_EQUIVALENT else "merged into"
    proof = f" (proven by {record.proven_by})" if record.proven_by else ""
    return (
        f"  {record.name}: {verb} {record.merged_into}{proof}, {_age(record)}{_where(record)}"
        f"\n      {delete_action(record, inventory, config)}"
    )


def _containment_text(record: BranchRecord) -> str:
    if record.containment is None:
        return "containment not measured"
    held = f" {record.contained_in}" if record.contained_in else ""
    if record.containment in {Containment.DEFAULT, Containment.REMOTE_REF}:
        return f"contained in{held}: cleanup candidate"
    return f"{record.containment.value}{held}"


def _nowhere_line(record: BranchRecord, config: BranchesConfig) -> str:
    return (
        f"CONTAINED NOWHERE: {record.name} ({_age(record)}{_where(record)}): no remote ref "
        f"holds its commits. Secure it: {push_command(record, config)}"
    )


def _dormant_line(record: BranchRecord) -> str:
    stage = record.dormancy_stage.value if record.dormancy_stage else "unstaged"
    return f"  {record.name}: {stage}, {_age(record)}, {_containment_text(record)}{_where(record)}"


def _work_line(record: BranchRecord) -> str:
    ahead = "" if record.ahead is None else f", {record.ahead} ahead"
    twins = f", same tip as {', '.join(record.same_tip_as)}" if record.same_tip_as else ""
    return f"  {record.name}: {_age(record)}{ahead}{twins}{_where(record)}"


# --- the CLI report --------------------------------------------------------------------


def _section(title: str, lines: list[str]) -> list[str]:
    return [title, *lines, ""] if lines else []


def render_report(
    inventory: BranchInventory, config: BranchesConfig, *, cap: int, show_all: bool = False
) -> list[str]:
    """The ``branch-sweep`` text: actionable groups first, then the count against the cap."""
    groups = group_records(inventory)
    out: list[str] = []
    if inventory.default_ref is None:
        out += [
            "WARNING: the default branch could not be resolved to a ref "
            f"(branches.default: {config.default!r}); nothing is judged merged into it.",
            "",
        ]
    if not inventory.worktrees_known:
        out += ["WARNING: `git worktree list` failed; worktree paths are unknown.", ""]
    out += _section(
        "CONTAINED NOWHERE (no remote ref holds these commits):",
        [f"  {_nowhere_line(r, config)}" for r in groups.contained_nowhere],
    )
    out += _section(
        "Merged, not deleted:",
        [_done_line(r, inventory, config) for r in groups.merged],
    )
    out += _section(
        "Patch-equivalent (every change already in the target):",
        [_done_line(r, inventory, config) for r in groups.patch_equivalent],
    )
    out += _section("Dormant:", [_dormant_line(r) for r in groups.dormant])
    out += _section("Live work:", [_work_line(r) for r in groups.live])
    out += _section(
        "Parked:",
        [f"{_work_line(r)}, reason: {r.parked_reason}" for r in groups.parked],
    )
    out += _section(
        "Not yet classified:",
        [f"  {r.name}: {r.reason}" for r in groups.unclassified],
    )
    if show_all:
        out += _section(
            "Not work (default, integration lines, protected, exempt):",
            [f"  {r.name}: {r.state.value}" for r in groups.never_work],
        )
    out.append(f"Open work: {open_work_count(inventory)} of {cap} (branches.wip.cap)")
    return out


def _record_json(
    record: BranchRecord, inventory: BranchInventory, config: BranchesConfig
) -> dict[str, Any]:
    group = _group_name(record)
    action: str | None = None
    if group in {"merged", "patch-equivalent"}:
        action = delete_action(record, inventory, config)
    elif group == "contained-nowhere":
        action = push_command(record, config)
    document: dict[str, Any] = {
        "name": record.name,
        "state": record.state.value,
        "group": group,
        "local_tip": record.local_tip,
        "remote_tip": record.remote_tip,
        "upstream": record.upstream,
        "worktree": str(record.worktree) if record.worktree is not None else None,
        "worktree_known": record.worktree_known,
        "ahead": record.ahead,
        "behind": record.behind,
        "lines": record.lines,
        "committed_at": record.committed_at,
        "age_days": record.age_days,
        "parked_reason": record.parked_reason,
        "plan": record.plan,
        "issue": record.issue,
        "merged_into": record.merged_into,
        "proven_by": record.proven_by,
        "reason": record.reason,
        "same_tip_as": list(record.same_tip_as),
        "dormancy_stage": record.dormancy_stage.value if record.dormancy_stage else None,
        "containment": record.containment.value if record.containment else None,
        "contained_in": record.contained_in,
        "action": action,
    }
    return {key: document[key] for key in JSON_RECORD_KEYS}


def report_json(
    inventory: BranchInventory, *, cap: int, config: BranchesConfig | None = None
) -> dict[str, Any]:
    """The ``--json`` document: every record, never-work ones included."""
    branches = config or BranchesConfig()
    return {
        "default_branch": inventory.default_branch,
        "default_ref": inventory.default_ref,
        "worktrees_known": inventory.worktrees_known,
        "open_work": open_work_count(inventory),
        "cap": cap,
        "branches": [
            _record_json(inventory.records[name], inventory, branches)
            for name in sorted(inventory.records)
        ],
    }


# --- the SessionStart summary ----------------------------------------------------------


def session_summary(
    inventory: BranchInventory,
    config: BranchesConfig,
    *,
    cap: int,
    new_session: bool,
    deprecation: str | None = None,
    behind_threshold: int | None = None,
) -> list[str]:
    """The SessionStart lines; empty when there is nothing to say.

    Contained-nowhere branches are named on every source; the merged count,
    the dormant branches, the work branches more than ``behind_threshold``
    (default ``branches.sweep.behind_threshold``) commits behind the default,
    the unresolved-default warning and the count against the cap only on a new
    session. At most :data:`MAX_SUMMARY_LINES` branch lines, then one "and N
    more" line.
    """
    groups = group_records(inventory)
    entries = [_nowhere_line(r, config) for r in groups.contained_nowhere]
    notes: list[str] = []
    if new_session:
        entries += [f"Dormant: {_dormant_line(r).strip()}" for r in groups.dormant]
        threshold = config.sweep.behind_threshold if behind_threshold is None else behind_threshold
        default = inventory.default_branch or "the default branch"
        entries += [
            f"Behind {default}: {r.name} is {r.behind} commits behind "
            f"(branches.sweep.behind_threshold: {threshold}); rebase or merge {default} "
            "into it, or delete it if it is done."
            for r in _far_behind(inventory, threshold)
        ]
        if inventory.default_ref is None:
            notes.append(
                "The default branch could not be resolved (branches.default: "
                f"{config.default!r}); nothing is judged merged."
            )
        if groups.merged:
            noun = "branch is" if len(groups.merged) == 1 else "branches are"
            notes.append(
                f"{len(groups.merged)} merged {noun} not deleted: run `{sweep_command()}` "
                "for the delete commands."
            )
        count = open_work_count(inventory)
        if count >= cap:
            notes.append(
                f"Open work: {count} of {cap} (branches.wip.cap). Finish, park or delete "
                f"branches; `{sweep_command()}` lists them."
            )
    shown = entries[:MAX_SUMMARY_LINES]
    hidden = len(entries) - len(shown)
    lines = [*shown]
    if hidden:
        lines.append(f"  and {hidden} more: run `{sweep_command()}`")
    lines += notes
    if deprecation is not None:
        lines.append(deprecation)
    return lines
