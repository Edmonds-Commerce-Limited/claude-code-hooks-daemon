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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.branch_guard import BRANCH_LIMIT_PRINCIPLE
from claude_code_hooks_daemon.core.branch_cleanup import sweep_clean_command, sweep_clean_line
from claude_code_hooks_daemon.core.branch_inventory import (
    BranchInventory,
    BranchRecord,
    BranchState,
    Containment,
    Pool,
    pool_of,
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
    "pool",
    "stale",
    "park_count",
    "kept_reason",
    "kept_by",
    "kept_at",
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
    bot_owned: tuple[BranchRecord, ...] = ()


def _group_name(record: BranchRecord) -> str:
    """The report group of one record (the ``group`` key of the JSON)."""
    state = record.state
    if state == BranchState.BOT_OWNED:
        return "bot-owned"
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
        bot_owned=take("bot-owned"),
    )


def pool_count(inventory: BranchInventory, pool: Pool) -> int:
    """Branches in ``pool``, identical tips counted once (Plan 00571 DESIGN.md section 1).

    Membership is the record's state (:func:`pool_of`); an unclassified
    branch is open work. Names of one pool linked by ``same_tip_as`` count as
    one.
    """
    work = {
        name: record for name, record in inventory.records.items() if pool_of(record.state) == pool
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


def open_work_count(inventory: BranchInventory) -> int:
    """Open work branches (``branches.wip.cap``'s pool), identical tips counted once."""
    return pool_count(inventory, Pool.OPEN)


def effective_wip_cap(config: BranchesConfig, legacy_options: Mapping[str, Any]) -> int:
    """``branches.wip.cap`` if set, else the old ``max_open_branches``, else the default."""
    explicit = config.explicit_wip_cap()
    if explicit is not None:
        return explicit
    legacy = legacy_options.get("max_open_branches")
    if isinstance(legacy, int) and not isinstance(legacy, bool) and legacy >= 1:
        return legacy
    return config.effective_wip_cap()


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


def delete_action(
    record: BranchRecord,
    inventory: BranchInventory,
    config: BranchesConfig,
    remote_proven: frozenset[str] = frozenset(),
) -> str:
    """How to delete a done branch, never a raw force delete.

    A local copy is deleted through ``delete-branch``, which proves the claim
    again before it deletes; a target other than the default is passed as
    ``--protected-ref``. A remote-only branch proven only by an unpushed local
    ref gets no command: the push of that ref comes first.

    A remote delete is printed as a runnable line only for a name in
    ``remote_proven``, the names the remote-delete guard's own proof
    (``remote_branch_proof.prove_remote_merged``) accepted; any other remote-only
    branch gets owner-only wording, because the guard would refuse the line. The
    default is no proof, so no runnable line.
    """
    remote_prefix = f"{config.remote}/"
    proven = record.proven_by
    if record.local_tip is None:
        if proven is not None and proven.startswith(remote_prefix):
            if record.name in remote_proven:
                return f"remote only: git push {config.remote} --delete {record.name}"
            return (
                f"remote only: deleting {config.remote}/{record.name} is for the owner "
                "(the remote-delete guard cannot prove it merged)"
            )
        return f"remote only, proven by the unpushed {proven}: push {proven} first"
    command = f"{delete_command()} {record.name}"
    if record.merged_into is not None and record.merged_into != inventory.default_branch:
        command += f" --protected-ref {proven or record.merged_into}"
    return command


def _done_line(
    record: BranchRecord,
    inventory: BranchInventory,
    config: BranchesConfig,
    remote_proven: frozenset[str],
) -> str:
    verb = "patch-equivalent to" if record.state == BranchState.PATCH_EQUIVALENT else "merged into"
    proof = f" (proven by {record.proven_by})" if record.proven_by else ""
    return (
        f"  {record.name}: {verb} {record.merged_into}{proof}, {_age(record)}{_where(record)}"
        f"{_keep_text(record, config)}"
        f"\n      {delete_action(record, inventory, config, remote_proven)}"
        f"\n      keep it instead: {daemon_cli_command_for_docs('branch-keep')} "
        f"{record.name} --reason ..."
    )


def _keep_text(record: BranchRecord, config: BranchesConfig) -> str:
    """The keep and stale suffix of a merged line."""
    max_age = f"branches.merged.max_age_days {config.effective_pool_max_age(Pool.MERGED)}"
    text = ""
    if record.kept_reason is not None:
        text += f", kept: {record.kept_reason} (by {record.kept_by})"
    if record.stale:
        lapsed = "keep lapsed, " if record.kept_reason is not None else "unkept, "
        text += f", STALE ({lapsed}past {max_age})"
    return text


def _containment_text(record: BranchRecord) -> str:
    if record.containment is None:
        return "containment not measured"
    held = f" {record.contained_in}" if record.contained_in else ""
    if record.containment in {
        Containment.DEFAULT,
        Containment.REMOTE_REF,
        Containment.REMOTE_UNFETCHED,
    }:
        return f"contained in{held}: cleanup candidate"
    return f"{record.containment.value}{held}"


def _nowhere_scope(inventory: BranchInventory, config: BranchesConfig) -> str:
    """What was actually checked, said plainly, for the CONTAINED NOWHERE text."""
    listing = inventory.remote_refs
    if listing is None:
        return (
            f"no fetched remote-tracking ref of {config.remote} holds its commits (a remote "
            "may hold it outside refs/heads, which the CLI `hooks-daemon branch-sweep` and "
            "`delete-branch` can verify)"
        )
    if listing.failure is not None:
        return (
            f"no fetched remote-tracking ref of {config.remote} holds its commits, and the "
            f"remote could not be checked (`git ls-remote {config.remote}` failed: "
            f"{listing.failure})"
        )
    return (
        f"no fetched remote-tracking ref of {config.remote} holds its commits and the remote "
        "was checked: none of its refs is at or above the tip"
    )


def _nowhere_line(record: BranchRecord, inventory: BranchInventory, config: BranchesConfig) -> str:
    return (
        f"CONTAINED NOWHERE: {record.name} ({_age(record)}{_where(record)}): "
        f"{_nowhere_scope(inventory, config)}. Secure it: {push_command(record, config)}"
    )


def _dormant_line(record: BranchRecord) -> str:
    stage = record.dormancy_stage.value if record.dormancy_stage else "unstaged"
    return f"  {record.name}: {stage}, {_age(record)}, {_containment_text(record)}{_where(record)}"


def dormant_action(name: str) -> str:
    """The next step for an idle branch: finish it, park it, or delete it when nothing is lost."""
    cli = daemon_cli_command_for_docs
    return (
        f"finish and merge it; or {cli('branch-park')} {name} --reason ...; "
        f"or {cli('delete-branch')} {name} (only when the guard proves nothing is lost)"
    )


def _dormant_section(records: Sequence[BranchRecord]) -> list[str]:
    """The Dormant lines, each with its next action, and the principle once."""
    if not records:
        return []
    lines = [BRANCH_LIMIT_PRINCIPLE]
    for record in records:
        lines += [_dormant_line(record), f"      {dormant_action(record.name)}"]
    return lines


def _work_line(record: BranchRecord) -> str:
    ahead = "" if record.ahead is None else f", {record.ahead} ahead"
    twins = f", same tip as {', '.join(record.same_tip_as)}" if record.same_tip_as else ""
    return f"  {record.name}: {_age(record)}{ahead}{twins}{_where(record)}"


def _parked_line(record: BranchRecord, config: BranchesConfig) -> str:
    line = f"{_work_line(record)}, reason: {record.parked_reason}"
    if record.stale:
        max_age = config.effective_pool_max_age(Pool.PARKED)
        line += f", STALE (past branches.parked.max_age_days {max_age})"
    if record.park_count is not None and record.park_count > 1:
        line += f", re-parked {record.park_count} times"
    return line


# --- the CLI report --------------------------------------------------------------------


def _section(title: str, lines: list[str]) -> list[str]:
    return [title, *lines, ""] if lines else []


def _with_clean_line(lines: list[str], *, remote: bool) -> list[str]:
    """``lines`` plus the one-step ``branch-sweep --clean`` fix, when there are any."""
    return [*lines, f"  {sweep_clean_line(remote=remote)}"] if lines else []


def render_report(
    inventory: BranchInventory,
    config: BranchesConfig,
    *,
    cap: int,
    show_all: bool = False,
    remote_proven: frozenset[str] = frozenset(),
) -> list[str]:
    """The ``branch-sweep`` text: actionable groups first, then the count against the cap.

    ``remote_proven`` names the remote-only branches the remote-delete guard's proof
    accepted (see :func:`delete_action`).
    """
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
    listing = inventory.remote_refs
    if listing is not None and listing.failure is not None:
        out += [
            f"WARNING: the remote could not be checked (`git ls-remote {config.remote}` failed: "
            f"{listing.failure}); containment below covers fetched remote-tracking refs only.",
            "",
        ]
    out += _section(
        f"CONTAINED NOWHERE (no fetched remote-tracking ref of {config.remote} holds these "
        "commits):",
        [f"  {_nowhere_line(r, inventory, config)}" for r in groups.contained_nowhere],
    )
    out += _section(
        "Merged, not deleted:",
        _with_clean_line(
            [_done_line(r, inventory, config, remote_proven) for r in groups.merged],
            remote=any(r.remote_tip is not None for r in groups.merged),
        ),
    )
    # A patch-equivalent REMOTE branch fails the remote-delete proof, so --remote
    # would not clear it; the local clean is the one step that applies.
    out += _section(
        "Patch-equivalent (every change already in the target):",
        _with_clean_line(
            [_done_line(r, inventory, config, remote_proven) for r in groups.patch_equivalent],
            remote=False,
        ),
    )
    out += _section("Dormant:", _dormant_section(groups.dormant))
    out += _section("Live work:", [_work_line(r) for r in groups.live])
    out += _section(
        "Parked:",
        [_parked_line(r, config) for r in groups.parked],
    )
    out += _section(
        "Not yet classified:",
        [f"  {r.name}: {r.reason}" for r in groups.unclassified],
    )
    out += _section(
        "Bot-owned (branches.bot_owned: in no pool, never cleaned; the bot removes them):",
        [f"  {r.name}: {_age(r)}" for r in groups.bot_owned],
    )
    if show_all:
        out += _section(
            "Not work (default, integration lines, protected, exempt):",
            [f"  {r.name}: {r.state.value}" for r in groups.never_work],
        )
    out += pool_count_lines(inventory, config, cap=cap)
    return out


#: The footer label of each pool, with the config key that caps it.
_POOL_LABELS: dict[Pool, tuple[str, str]] = {
    Pool.OPEN: ("Open work", "branches.wip.cap"),
    Pool.PARKED: ("Parked", "branches.parked.cap"),
    Pool.MERGED: ("Merged, not deleted", "branches.merged.cap"),
}


def pool_caps(config: BranchesConfig, *, cap: int) -> dict[Pool, int]:
    """Each pool's cap; ``cap`` is the WIP cap the caller resolved (legacy option included).

    A pool whose own cap is unset follows ``cap``, so the report and the
    creation guard agree even when only the retired option is set.
    """
    caps = {Pool.OPEN: cap}
    for pool in (Pool.PARKED, Pool.MERGED):
        own = config.parked.cap if pool == Pool.PARKED else config.merged.cap
        caps[pool] = cap if own is None else own
    return caps


def pool_count_lines(inventory: BranchInventory, config: BranchesConfig, *, cap: int) -> list[str]:
    """One ``<pool>: N of CAP (<key>)`` line per pool."""
    caps = pool_caps(config, cap=cap)
    return [
        f"{label}: {pool_count(inventory, pool)} of {caps[pool]} ({key})"
        for pool, (label, key) in _POOL_LABELS.items()
    ]


def _record_json(
    record: BranchRecord,
    inventory: BranchInventory,
    config: BranchesConfig,
    remote_proven: frozenset[str],
) -> dict[str, Any]:
    group = _group_name(record)
    action: str | None = None
    if group in {"merged", "patch-equivalent"}:
        action = delete_action(record, inventory, config, remote_proven)
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
        "pool": pool.value if (pool := pool_of(record.state)) is not None else None,
        "stale": record.stale,
        "park_count": record.park_count,
        "kept_reason": record.kept_reason,
        "kept_by": record.kept_by,
        "kept_at": record.kept_at,
        "action": action,
    }
    return {key: document[key] for key in JSON_RECORD_KEYS}


def report_json(
    inventory: BranchInventory,
    *,
    cap: int,
    config: BranchesConfig | None = None,
    remote_proven: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """The ``--json`` document: every record, never-work ones included."""
    branches = config or BranchesConfig()
    return {
        "default_branch": inventory.default_branch,
        "default_ref": inventory.default_ref,
        "worktrees_known": inventory.worktrees_known,
        "open_work": open_work_count(inventory),
        "cap": cap,
        "pools": {
            pool.value: {"count": pool_count(inventory, pool), "cap": pool_cap}
            for pool, pool_cap in pool_caps(branches, cap=cap).items()
        },
        "branches": [
            _record_json(inventory.records[name], inventory, branches, remote_proven)
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
    entries = [_nowhere_line(r, inventory, config) for r in groups.contained_nowhere]
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
            remote = any(r.remote_tip is not None for r in groups.merged)
            notes.append(
                f"{len(groups.merged)} merged {noun} not deleted: "
                f"`{sweep_clean_command(remote=remote)}` deletes them in one step "
                f"(`{sweep_command()}` lists them)."
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
