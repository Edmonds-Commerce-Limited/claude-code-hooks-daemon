"""Three-way merge for a client's ``settings.json`` (Plan 00176).

Both upgrade routes used to copy the daemon's ``settings.json`` over the
client's verbatim, so an extra hook, a custom status line or a hand-written
``permissions`` block was silently discarded. This module replaces that copy.

**The direction of the copy is the safety property.** The merge starts from the
CLIENT's document and edits the daemon-owned parts of it; it never builds a
daemon document and grafts client keys on. A merge cannot lose what it does not
look at, so every key this module has never heard of survives by construction
rather than by enumeration.

Three ownership classes, three different rules — which is why this is a
dedicated merge rather than a second mode inside the YAML one
(``preserve_config_for_upgrade``), whose whole contract is "preserve what the
user changed". The ``hooks`` block is force-refreshed AGAINST the user's copy,
the exact inverse of that contract.

============================ ===============================================
Class                        Rule
============================ ===============================================
Daemon-owned (``hooks``)     rebuilt from the SSoT template; missing wired
                             events added; every unmatched sibling untouched
Recommended default          three-way: a value still at the OLD default is
(``statusLine.*``)           upgraded; a value differing from it is a
                             deliberate override and is preserved
Client-owned (everything     preserved verbatim, always — including the
else)                        ABSENCE of a key the client removed
============================ ===============================================

Decided in ``CLAUDE/Plan/00176-settings-json-merge-preserve-on-upgrade/MERGE-SPEC.md``,
which records why each rule is what it is.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.utils.hook_command_migration import (
    canonical_hook_command,
    legacy_command_bash_key,
)
from claude_code_hooks_daemon.utils.hook_registration import (
    HOOK_EVENTS_IN_SETTINGS,
    build_hook_registration,
    canonical_hook_entry,
    validate_settings_hooks,
)

_HOOKS_KEY: Final = "hooks"
_STATUS_LINE_KEY: Final = "statusLine"

#: Sub-keys the daemon RECOMMENDS but does not own. A client value equal to the
#: old default was an accepted recommendation and moves with us; anything else
#: is a choice and stays.
_RECOMMENDED_DEFAULTS: Final[tuple[tuple[str, str], ...]] = (
    (_STATUS_LINE_KEY, "command"),
    (_STATUS_LINE_KEY, "refreshInterval"),
)

#: Top-level keys whose absence costs a SECURITY guarantee rather than a
#: preference. With no baseline there is no way to tell an accepted default from
#: a deliberate removal (see ``MergeReport`` and MERGE-SPEC Q2b), and the
#: preference class degrades to "change nothing". These do the opposite: they
#: are delivered and reported, because declining to deliver a deny rule destroys
#: nothing but silently withholds a guard the verbatim copy used to provide.
_SECURITY_RELEVANT_KEYS: Final = frozenset({"permissions", "enableArtifact"})

#: Suffix of the same-directory scratch file every whole-file write lands in
#: before it is renamed over the target. See :func:`_write_atomically`.
_TMP_SUFFIX: Final = ".tmp"

#: The wired forwarders, keyed by the command each renders to. Membership of
#: this set — not a substring of the command — is what separates our forwarder
#: from a client script that happens to live under ``.claude/hooks/``.
_WIRED_BASH_KEYS: Final = frozenset(HOOK_EVENTS_IN_SETTINGS.values())
_CANONICAL_COMMANDS: Final[dict[str, str]] = {
    canonical_hook_command(bash_key): bash_key for bash_key in _WIRED_BASH_KEYS
}


@dataclass(frozen=True)
class MergeReport:
    """What the merge did, in terms a human can act on.

    ``absences_preserved`` is deliberately NOT part of ``changed``: honouring a
    key the client removed alters nothing, and reporting it as a change would
    make every upgrade of a customised project look eventful.
    """

    hooks_added: tuple[str, ...] = ()
    hooks_refreshed: tuple[str, ...] = ()
    defaults_upgraded: tuple[str, ...] = ()
    keys_delivered: tuple[str, ...] = ()
    absences_preserved: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        """Whether the merged document differs from what the client had."""
        return bool(
            self.hooks_added
            or self.hooks_refreshed
            or self.defaults_upgraded
            or self.keys_delivered
        )


def merge_settings(
    client: Mapping[str, Any],
    new_default: Mapping[str, Any],
    old_default: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], MergeReport]:
    """Merge the daemon's shipped settings into a client's, preserving theirs.

    Pure function — no argument is mutated.

    Args:
        client: The project's current ``settings.json``, parsed.
        new_default: The settings this daemon version ships.
        old_default: The settings the PREVIOUS version shipped, when it can be
            resolved. ``None`` on a fresh install or a directly-invoked upgrade
            layer, in which case nothing is guessed: an accepted default is
            indistinguishable from a deliberate override, so the recommended
            class preserves every client value and upgrades none. There is
            deliberately no fallback that infers a baseline — a
            plausible-but-wrong one misclassifies silently.

    Returns:
        ``(merged, report)``. ``merged`` is a deep copy of ``client`` with the
        daemon-owned parts brought up to date.
    """
    merged = copy.deepcopy(dict(client))

    hooks, hooks_added, hooks_refreshed = _merge_hooks(merged.get(_HOOKS_KEY))
    merged[_HOOKS_KEY] = hooks

    delivered, absences = _merge_presence(merged, new_default, old_default)
    upgraded = _merge_recommended_defaults(merged, new_default, old_default)

    return merged, MergeReport(
        hooks_added=hooks_added,
        hooks_refreshed=hooks_refreshed,
        defaults_upgraded=upgraded,
        keys_delivered=delivered,
        absences_preserved=absences,
    )


def _daemon_bash_key(inner: Any) -> str | None:
    """The wired forwarder this inner hook IS, or None if it is the client's.

    Anchored to the WHOLE command, never a substring of it. A substring test was
    wrong in both directions: it missed the relative legacy shape
    (``.claude/hooks/pre-tool-use``) that is precisely the stale entry needing
    repair, and it claimed a client's ``.claude/hooks/my-secret-scan`` and any
    chained command as ours — rebuilding which would drop the client's half.
    """
    if not isinstance(inner, dict):
        return None
    command = inner.get("command")
    if not isinstance(command, str):
        return None
    legacy = legacy_command_bash_key(command)
    if legacy is not None and legacy in _WIRED_BASH_KEYS:
        return legacy
    return _CANONICAL_COMMANDS.get(command)


def _validate_daemon_forwarders(settings: Mapping[str, Any]) -> list[str]:
    """Exactly one canonical daemon forwarder per wired event, and no more.

    Deliberately NOT ``validate_hook_commands``, which counts every ``type:
    command`` hook in a wired event's array and calls more than one a duplicate
    registration. That is incompatible with this merge's own ownership rule — a
    client hook may legitimately share an event array with our forwarder, and
    preserving it is the headline behaviour — so using that validator as the
    write gate escalated the upgrade for precisely the clients whose
    customisations this exists to protect, on every run. A file that is
    preserved but never merged is worse than the overwrite it replaced: the
    wired set silently rots instead.

    The discriminator is what makes the narrower check possible: it can tell OUR
    forwarder from a client's hook, which a count cannot.
    """
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return ["`hooks` is not an object"]

    issues: list[str] = []
    for json_key, bash_key in sorted(HOOK_EVENTS_IN_SETTINGS.items()):
        entries = hooks.get(json_key)
        if not isinstance(entries, list):
            issues.append(f"{json_key} has no daemon forwarder")
            continue
        found = 0
        for group in entries:
            inner_list = group.get(_HOOKS_KEY) if isinstance(group, dict) else None
            if not isinstance(inner_list, list):
                continue
            found += sum(1 for inner in inner_list if _daemon_bash_key(inner) == bash_key)
        if found != 1:
            issues.append(f"{json_key} has {found} daemon forwarders, expected exactly 1")
    return issues


def _merge_hooks(existing: Any) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]:
    """Complete and repair the wired forwarders, leaving client hooks alone."""
    hooks: dict[str, Any] = copy.deepcopy(existing) if isinstance(existing, dict) else {}

    added: list[str] = []
    refreshed: list[str] = []
    for json_key in sorted(HOOK_EVENTS_IN_SETTINGS):
        bash_key = HOOK_EVENTS_IN_SETTINGS[json_key]
        entries = hooks.get(json_key)
        if not isinstance(entries, list):
            hooks[json_key] = build_hook_registration(bash_key)
            added.append(json_key)
            continue
        hooks[json_key], changed = _refresh_event(entries, bash_key)
        if changed:
            refreshed.append(json_key)
    return hooks, tuple(added), tuple(refreshed)


def _refresh_event(entries: list[Any], bash_key: str) -> tuple[list[Any], bool]:
    """Rebuild this event's forwarder in place; append it if it is missing.

    A forwarder is identified by its COMMAND, not by its position: an array
    index is not identity, so reordering a client's hooks must not change which
    entry is treated as ours.
    """
    canonical = canonical_hook_entry(bash_key)
    new_entries: list[Any] = []
    found = False
    changed = False

    for group in entries:
        inner_list = group.get(_HOOKS_KEY) if isinstance(group, dict) else None
        if not isinstance(inner_list, list):
            new_entries.append(group)
            continue
        new_inner: list[Any] = []
        for inner in inner_list:
            if _daemon_bash_key(inner) != bash_key:
                new_inner.append(inner)
                continue
            found = True
            if inner != canonical:
                changed = True
            new_inner.append(copy.deepcopy(canonical))
        new_group = dict(group)
        new_group[_HOOKS_KEY] = new_inner
        new_entries.append(new_group)

    if not found:
        # The event key existing is not the same as our forwarder existing: a
        # client array holding only their own hook would otherwise leave the
        # event unwired while looking present.
        new_entries.extend(build_hook_registration(bash_key))
        changed = True
    return new_entries, changed


def _merge_presence(
    merged: dict[str, Any],
    new_default: Mapping[str, Any],
    old_default: Mapping[str, Any] | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Decide, per absent top-level key, whether it is new or was removed.

    Presence is merged three-way exactly as value is, because preserving a
    client key otherwise includes preserving its absence — and a client whose
    file predates a key would then never receive it, which for a security
    control is worse than the preference regression it resembles.
    """
    delivered: list[str] = []
    absences: list[str] = []

    for key in sorted(new_default):
        if key == _HOOKS_KEY or key in merged:
            continue
        if old_default is None:
            if key in _SECURITY_RELEVANT_KEYS:
                merged[key] = copy.deepcopy(new_default[key])
                delivered.append(key)
            continue
        if key in old_default:
            absences.append(key)
            continue
        merged[key] = copy.deepcopy(new_default[key])
        delivered.append(key)
    return tuple(delivered), tuple(absences)


def _merge_recommended_defaults(
    merged: dict[str, Any],
    new_default: Mapping[str, Any],
    old_default: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """Upgrade only the recommendations the client never expressed a view on."""
    if old_default is None:
        return ()

    upgraded: list[str] = []
    for parent, key in _RECOMMENDED_DEFAULTS:
        block = merged.get(parent)
        if not isinstance(block, dict) or key not in block:
            continue
        old_block = old_default.get(parent)
        new_block = new_default.get(parent)
        if not isinstance(old_block, dict) or not isinstance(new_block, dict):
            continue
        if key not in old_block or key not in new_block:
            continue
        if block[key] != old_block[key] or new_block[key] == old_block[key]:
            continue
        block[key] = copy.deepcopy(new_block[key])
        upgraded.append(f"{parent}.{key}")
    return tuple(upgraded)


class MergeStatus(Enum):
    """What ``run_settings_merge`` did to the file on disk."""

    #: No client file existed; the shipped settings were written as-is.
    INSTALLED = "installed"
    #: Nothing was owed. The file is NOT rewritten — churning its mtime would
    #: invite a pointless backup from the deploy helper on the next run.
    UNCHANGED = "unchanged"
    #: The merged document replaced the client's.
    MERGED = "merged"
    #: Nothing was written. See ``MergeOutcome.messages``.
    ESCALATED = "escalated"


#: Appended to the client path for the merge we WOULD have written. It sits
#: beside the original so a human comparing the two needs no daemon command.
PROPOSAL_SUFFIX: Final = ".merge-proposal"

#: Deliberately not 1. To `install_version.sh` and `upgrade_version.sh` a 1 from
#: this step means abort, and aborting the idempotent fast path leaves new
#: forwarders over old settings with no snapshot to roll back to — strictly
#: worse than carrying on with the client's file intact and a warning on screen.
ESCALATION_EXIT_CODE: Final = 3


@dataclass(frozen=True)
class MergeOutcome:
    """The result of merging one file, including the refusal case.

    An escalation is deliberately not an exception: on the idempotent upgrade
    fast path `deploy_all_hooks` runs BEFORE the settings deploy and the
    rollback snapshot is not taken until a later step, so aborting there would
    leave new forwarders, old settings and nothing to roll back with. The caller
    is meant to warn, carry the status, and let the run FINISH.
    """

    status: MergeStatus
    report: MergeReport | None = None
    proposal_path: Path | None = None
    messages: tuple[str, ...] = ()

    @property
    def escalated(self) -> bool:
        return self.status is MergeStatus.ESCALATED


def _load_json_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Parse a settings document, returning ``(document, problem)``.

    The problem string is carried rather than discarded so no caller can turn a
    corrupt file into a silent default. It matters most for the OLD-DEFAULT
    baseline: absent and unreadable both degrade to "no baseline", but only one
    of them is expected, and a client whose handover is corrupt would otherwise
    stop receiving recommended defaults with nothing said.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{path} could not be read: {exc}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"{path} is not valid JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, f"{path} is not a JSON object"
    return parsed, None


def _serialise(settings: Mapping[str, Any]) -> str:
    return json.dumps(settings, indent=2) + "\n"


def _write_atomically(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a temp file in the same directory.

    The lost-update reasoning below (four unlocked writers, worst case a lost
    update rather than corruption) only holds while every writer is atomic.
    ``write_text`` truncates before it writes, so an interruption left a
    half-written ``settings.json`` -- a file Claude Code cannot parse, taking
    every hook down with it (Plan 00364 Task 2.7). Same directory, so the
    replace is a rename within one filesystem.
    """
    tmp_path = path.with_suffix(path.suffix + _TMP_SUFFIX)
    tmp_path.write_text(text, encoding="utf-8")
    try:
        tmp_path.replace(path)
    except OSError:
        # The rename is the only step that can fail with the destination
        # still intact. Clear the temp file so a retry is not confused by a
        # stale sibling, then let the caller see the failure.
        tmp_path.unlink(missing_ok=True)
        raise


def run_settings_merge(
    client_path: Path,
    new_default_path: Path,
    old_default_path: Path | None = None,
) -> MergeOutcome:
    """Merge the shipped settings into the client's file on disk.

    Args:
        client_path: The project's ``settings.json``. Written only on success.
        new_default_path: The settings this daemon version ships.
        old_default_path: The previous version's shipped settings, when a
            handover captured one. A path that cannot be read is treated as NO
            baseline rather than as an empty one — an empty baseline would call
            every client value a deliberate override and freeze the project's
            settings permanently.

    Returns:
        A ``MergeOutcome``. On ``ESCALATED`` nothing was written to
        ``client_path`` and the proposed merge is at ``proposal_path``.
    """
    new_default, problem = _load_json_object(new_default_path)
    if new_default is None:
        return MergeOutcome(
            status=MergeStatus.ESCALATED,
            messages=(f"Could not read the daemon's own settings: {problem}",),
        )

    if not client_path.exists():
        _write_atomically(client_path, _serialise(new_default))
        return MergeOutcome(status=MergeStatus.INSTALLED)

    notes: list[str] = []
    old_default = None
    if old_default_path is not None:
        old_default, baseline_problem = _load_json_object(old_default_path)
        if baseline_problem is not None:
            # Degrade, but say so. Treating this as an empty baseline would call
            # every client value a deliberate override and freeze their settings.
            notes.append(
                f"No usable settings baseline ({baseline_problem}), so your values "
                "are all preserved and no new default is applied."
            )

    client, client_problem = _load_json_object(client_path)
    if client is None:
        return _escalate(
            client_path,
            new_default,
            (
                f"{client_problem}, so it cannot be merged.",
                "It has been left exactly as it is.",
            ),
        )

    merged, report = merge_settings(client, new_default, old_default)

    problems = validate_settings_hooks(merged) + _validate_daemon_forwarders(merged)
    if problems:
        return _escalate(
            client_path,
            merged,
            (f"The merged settings did not validate: {'; '.join(problems)}.",),
            client,
        )

    if not report.changed:
        return MergeOutcome(status=MergeStatus.UNCHANGED, report=report, messages=tuple(notes))

    # Re-read immediately before writing. Four things write this file with no
    # lock between them; every whole-file writer here is atomic
    # (`_write_atomically`), so the failure mode is a LOST UPDATE rather than
    # corruption, and re-reading is the cheap mitigation. A lock is worth
    # adding when one is actually observed, not in anticipation.
    latest, _ = _load_json_object(client_path)
    if latest is not None and latest != client:
        merged, report = merge_settings(latest, new_default, old_default)

    _write_atomically(client_path, _serialise(merged))
    return MergeOutcome(status=MergeStatus.MERGED, report=report, messages=tuple(notes))


def _top_level_diff(client: Mapping[str, Any], proposal: Mapping[str, Any]) -> tuple[str, ...]:
    """Which top-level keys the proposal would have changed, added or removed.

    Bounded on purpose: the full text of both documents is already on disk at
    the two paths the escalation names, and a warning nobody finishes reading
    is the thing this whole escalation path exists to avoid.
    """
    lines: list[str] = []
    for key in sorted(set(client) | set(proposal)):
        if key not in proposal:
            lines.append(f"  - {key} (would be removed)")
        elif key not in client:
            lines.append(f"  + {key} (would be added)")
        elif client[key] != proposal[key]:
            lines.append(f"  ~ {key} (would change)")
    return tuple(lines)


def _escalate(
    client_path: Path,
    proposal: Mapping[str, Any],
    reasons: tuple[str, ...],
    client: Mapping[str, Any] | None = None,
) -> MergeOutcome:
    """Write the merge we would have made, change nothing, and say both paths."""
    proposal_path = client_path.with_name(client_path.name + PROPOSAL_SUFFIX)
    _write_atomically(proposal_path, _serialise(proposal))

    diff = _top_level_diff(client, proposal) if client is not None else ()
    return MergeOutcome(
        status=MergeStatus.ESCALATED,
        proposal_path=proposal_path,
        messages=(
            *reasons,
            f"Your settings are unchanged at {client_path}.",
            f"The merge we would have applied is at {proposal_path}.",
            *(("It would have differed at these top-level keys:",) if diff else ()),
            *diff,
            "Compare the two files and apply what you want by hand.",
        ),
    )
