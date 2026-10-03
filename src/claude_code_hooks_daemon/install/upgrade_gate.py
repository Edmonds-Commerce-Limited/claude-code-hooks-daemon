"""The pre-deploy upgrade gate (Plan 00376 Phase 3).

Layer 2 (``scripts/upgrade_version.sh``) runs this once the daemon checkout
sits on the target and before anything is deployed into the project. It
assembles what the upgrade changes -- the crossed guides, and every
pre-upgrade task whose detection finds a call site in the project -- and
returns one verdict:

- ``PROCEED`` -- nothing to read, the exact target is already installed, or
  the caller confirmed the listing it was shown.
- ``NEEDS_ACKNOWLEDGEMENT`` -- there is something to read and the caller has
  not passed ``--skip-reading-confirmation=<digest>`` with the digest of THIS
  listing. There is no terminal inference: an agent and a human get the same
  stop.
- ``NEEDS_APPROVAL`` -- the upgrade breaks the project, so the owner must
  approve it: a MAJOR bump, a crossed config-changes manifest declaring
  ``breaking: true``, a ``critical`` pre-upgrade task detected in the project,
  or a range the gate cannot read. The approval is a marker only
  :func:`run_approval` writes -- it needs a terminal and a typed phrase naming
  both versions -- bound to this upgrade's from/to versions and install path.

The FROM side is what is INSTALLED (:func:`installed_version`): the venv's
stamp, else the project's committed ``HOOKS-DAEMON.md`` marker. The checkout is
never asked, because on a fresh clone, a manual checkout or a re-run it already
sits on the target and would make every range empty. Only the stamp is
verified, though: the marker is an ordinary tracked file an agent edits
routinely, so a marker-derived FROM that has caught up to or passed the target
(``evaluate_gate``'s ``from_untrusted``) is never read as "nothing to
install" -- it gets ``NEEDS_APPROVAL`` like any other range the gate cannot
vouch for, the same answer a venv stamp already at the target gets with no
matching :func:`gated_install_stamp` receipt.

The caller (bash) turns a stop into an abort that puts the daemon checkout
back on the installed version (Task 1.2), so a stopped upgrade deploys
nothing, and removes a used approval only once the upgrade has completed.

Standard library only, like everything it loads: it runs before the target's
venv exists (see ``upgrade_gate_standalone.py``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Final, TextIO

from claude_code_hooks_daemon.daemon.install_layout import get_untracked_dir
from claude_code_hooks_daemon.install.upgrade_guides import (
    UNRELEASED_DIRNAME,
    UPGRADES_SUBPATH,
    guide_documents,
    release_tuple,
)
from claude_code_hooks_daemon.install.upgrade_tasks import (
    SEVERITY_CRITICAL,
    TaskFinding,
    TaskKind,
    evaluate,
    format_findings_line,
    tasks_for_range,
)
from claude_code_hooks_daemon.install.version_parse import strip_tag_prefix
from claude_code_hooks_daemon.utils.one_shot_approval import OneShotApprovalStore
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to, path_relative_to

logger = logging.getLogger(__name__)

#: Sub-directory of the daemon's untracked dir holding upgrade approvals.
APPROVAL_SUBDIR: Final[str] = "upgrade-approvals"
#: The flag a caller passes to confirm it has read the listing; its value is
#: the listing's digest.
SKIP_READING_FLAG: Final[str] = "--skip-reading-confirmation"
#: The human's command; the version and ``--from`` are appended.
APPROVE_COMMAND: Final[str] = "hooks-daemon approve-upgrade"
#: What an unreadable installed version is recorded as in an approval.
UNKNOWN_VERSION: Final[str] = "unknown"
#: Where the project's generated daemon document records the installed release.
HOOKS_DAEMON_DOC: Final[Path] = Path(".claude") / "HOOKS-DAEMON.md"

SOURCE_VENV_STAMP: Final[str] = "venv stamp"
SOURCE_DOC_MARKER: Final[str] = HOOKS_DAEMON_DOC.as_posix()
SOURCE_NONE: Final[str] = "none"

_CONFIG_CHANGES_DIRNAME: Final[str] = "config-changes"
_MANIFEST_RE: Final[re.Pattern[str]] = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)\.yaml$")
#: Every YAML 1.1 spelling of true, any case, optionally followed by a comment.
_BREAKING_RE: Final[re.Pattern[str]] = re.compile(
    r"^breaking:\s*[\"']?(?:true|yes|on|y)[\"']?\s*(?:#.*)?$", re.MULTILINE | re.IGNORECASE
)
_RELEASE_RE: Final[re.Pattern[str]] = re.compile(r"^[vV]?\d+(?:\.\d+){0,2}(?:\+\S*)?$")
_DOC_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"Generated on [^(\n]*\(v(\d+\.\d+\.\d+)\)")
_DIGEST_LENGTH: Final[int] = 12
_RULE: Final[str] = "=" * 70
_APPROVAL_PHRASE: Final[str] = "approve upgrade from {frm} to v{to}"
_UNKNOWN_FROM_PHRASE: Final[str] = "an unknown version"
_STANDALONE_REL: Final[str] = "src/claude_code_hooks_daemon/install/upgrade_gate_standalone.py"
_APPROVAL_USED_PREFIX: Final[str] = "approval-marker="
_VERDICT_PREFIX: Final[str] = "verdict="
_NONCE_PREFIX: Final[str] = "nonce="
#: Only the gate's own user may read or write its verdict file.
_VERDICT_FILE_MODE: Final[int] = 0o600
_EARLIEST_RELEASE: Final[str] = "0.0.0"
#: What the gate last let through, in the approvals directory the upgrade
#: guard already keeps agents from writing.
GATED_INSTALL_FILENAME: Final[str] = "gated-install.json"
_FIELD_STAMP: Final[str] = "stamp"
_FIELD_RECORDED_AT: Final[str] = "recorded_at"

_FIELD_TO: Final[str] = "to"
_FIELD_FROM: Final[str] = "from"
_FIELD_DAEMON_DIR: Final[str] = "daemon_dir"
_FIELD_PROJECT_ROOT: Final[str] = "project_root"
_FIELD_APPROVED_AT: Final[str] = "approved_at"


class GateVerdict(Enum):
    """What the gate decided; ``exit_code`` is what the standalone entry returns."""

    PROCEED = "proceed"
    NEEDS_ACKNOWLEDGEMENT = "needs-acknowledgement"
    NEEDS_APPROVAL = "needs-approval"

    @property
    def exit_code(self) -> int:
        """0 to proceed; 3 and 4 to stop (1 is a crash and 2 an argparse error)."""
        return _EXIT_CODES[self]


_EXIT_CODES: Final[dict[GateVerdict, int]] = {
    GateVerdict.PROCEED: 0,
    GateVerdict.NEEDS_ACKNOWLEDGEMENT: 3,
    GateVerdict.NEEDS_APPROVAL: 4,
}


class ApprovalState(Enum):
    """What the approval store holds for one upgrade."""

    ABSENT = "absent"
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True)
class GateReport:
    """Everything the gate read, and its verdict."""

    daemon_dir: Path
    project_root: Path
    from_version: str | None
    to_version: str
    target_ref: str
    range_known: bool
    downgrade: bool
    already_installed: bool
    guides: list[Path]
    findings: list[TaskFinding]
    escalations: list[str]
    digest: str
    acknowledgement: str | None
    verdict: GateVerdict
    approval_marker: Path
    approval_state: ApprovalState
    approval_used: Path | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def applicable(self) -> list[TaskFinding]:
        """Pre-upgrade tasks detected in the project, or whose scan could not run."""
        return [finding for finding in self.findings if finding.applies is not False]

    @property
    def has_reading(self) -> bool:
        """Anything a caller must confirm it has read."""
        return bool(self.guides or self.applicable or self.escalations)


def _is_release(version: str | None) -> bool:
    return bool(version) and _RELEASE_RE.match(str(version)) is not None


def approval_key(version: str) -> str:
    """The release a marker approves, build metadata and ``v`` dropped (``4.0.0``)."""
    return ".".join(str(part) for part in release_tuple(version))


def _version_key(version: str | None) -> str:
    return approval_key(version) if version and _is_release(version) else UNKNOWN_VERSION


def installed_version(installed_stamp: str | None, project_root: Path) -> tuple[str | None, str]:
    """The release the project has INSTALLED, and where that answer came from.

    The venv's stamp is what the running daemon was built from; the committed
    ``HOOKS-DAEMON.md`` marker is what the project last generated docs for,
    and covers a fresh clone with no venv yet. Returns ``(None, "none")``
    when neither can be read.
    """
    if installed_stamp and _is_release(installed_stamp):
        return approval_key(installed_stamp), SOURCE_VENV_STAMP
    doc = project_root / HOOKS_DAEMON_DOC
    if doc.is_file():
        match = _DOC_MARKER_RE.search(doc.read_text(encoding="utf-8", errors="replace"))
        if match:
            return match.group(1), SOURCE_DOC_MARKER
    return None, SOURCE_NONE


def _manifest_version(path: Path) -> tuple[int, ...] | None:
    match = _MANIFEST_RE.match(path.name)
    return release_tuple(match.group("version")) if match else None


def _declares_breaking(path: Path) -> bool:
    return _BREAKING_RE.search(path.read_text(encoding="utf-8")) is not None


def breaking_manifests(
    upgrades_dir: Path, from_version: str, to_version: str, include_unreleased: bool
) -> list[Path]:
    """Config-changes manifests the upgrade crosses that declare ``breaking: true``.

    Released manifests count when ``from < version <= to``. Staged ones count
    on a branch install whatever version their file name carries: that name is
    the release it is aimed at, not one this upgrade can compare against.
    """
    from_v = release_tuple(from_version)
    to_v = release_tuple(to_version)
    found: list[Path] = []
    released_dir = upgrades_dir / _CONFIG_CHANGES_DIRNAME
    if released_dir.is_dir():
        for path in sorted(released_dir.iterdir(), key=lambda p: _manifest_version(p) or ()):
            version = _manifest_version(path)
            if version is not None and from_v < version <= to_v and _declares_breaking(path):
                found.append(path)
    staged_dir = upgrades_dir / UNRELEASED_DIRNAME / _CONFIG_CHANGES_DIRNAME
    if include_unreleased and staged_dir.is_dir():
        found.extend(
            path
            for path in sorted(staged_dir.iterdir(), key=lambda p: p.name)
            if _manifest_version(path) is not None and _declares_breaking(path)
        )
    return found


def _rel(path: Path, root: Path) -> str:
    if path_is_relative_to(path, root):
        return path_relative_to(path, root).as_posix()
    return str(path)


def _critical_escalations(findings: list[TaskFinding], daemon_dir: Path) -> list[str]:
    return [
        f"critical pre-upgrade task detected in this project: {_rel(finding.task.path, daemon_dir)}"
        for finding in findings
        if finding.task.severity == SEVERITY_CRITICAL and finding.applies is not False
    ]


def _escalations(
    daemon_dir: Path,
    from_version: str,
    to_version: str,
    include_unreleased: bool,
    findings: list[TaskFinding],
) -> list[str]:
    reasons: list[str] = []
    from_major = release_tuple(from_version)[0]
    to_major = release_tuple(to_version)[0]
    if to_major > from_major:
        reasons.append(f"MAJOR version change: v{from_major}.x -> v{to_major}.x")
    reasons.extend(
        f"config-changes manifest declares breaking: true: {_rel(path, daemon_dir)}"
        for path in breaking_manifests(
            daemon_dir / UPGRADES_SUBPATH, from_version, to_version, include_unreleased
        )
    )
    reasons.extend(_critical_escalations(findings, daemon_dir))
    return reasons


def _reading_list(
    upgrades_dir: Path, from_version: str, to_version: str, include_unreleased: bool
) -> list[Path]:
    """The guide documents, minus staged pre-upgrade tasks (shown by detection)."""
    return [
        document
        for document in guide_documents(
            upgrades_dir, from_version, to_version, include_unreleased=include_unreleased
        )
        if TaskKind.PRE.value not in path_relative_to(document, upgrades_dir).parts
    ]


def _digest(
    daemon_dir: Path,
    from_version: str | None,
    to_version: str,
    guides: list[Path],
    findings: list[TaskFinding],
    escalations: list[str],
) -> str:
    """A short fingerprint of what was listed, so an acknowledgement is bound to it."""
    lines = [f"from:{_version_key(from_version)}", f"to:{to_version}"]
    lines.extend(f"guide:{_rel(guide, daemon_dir)}" for guide in guides)
    lines.extend(
        f"task:{_rel(finding.task.path, daemon_dir)}"
        for finding in findings
        if finding.applies is not False
    )
    lines.extend(f"escalation:{reason}" for reason in escalations)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]


def _approval_payload(
    *, to_version: str, from_version: str | None, daemon_dir: Path, project_root: Path
) -> dict[str, str]:
    return {
        _FIELD_TO: approval_key(to_version),
        _FIELD_FROM: _version_key(from_version),
        _FIELD_DAEMON_DIR: str(daemon_dir.resolve()),
        _FIELD_PROJECT_ROOT: str(project_root.resolve()),
    }


def write_approval(
    untracked_dir: Path,
    *,
    to_version: str,
    from_version: str | None,
    daemon_dir: Path,
    project_root: Path,
) -> Path:
    """Record the owner's approval for exactly this upgrade; return the marker path.

    Called by :func:`run_approval` only, once the owner has typed the phrase.
    """
    payload = _approval_payload(
        to_version=to_version,
        from_version=from_version,
        daemon_dir=daemon_dir,
        project_root=project_root,
    )
    payload[_FIELD_APPROVED_AT] = datetime.now(UTC).isoformat(timespec="seconds")
    marker = OneShotApprovalStore(APPROVAL_SUBDIR).path(untracked_dir, payload[_FIELD_TO])
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return marker


def check_approval(
    untracked_dir: Path,
    *,
    to_version: str,
    from_version: str | None,
    daemon_dir: Path,
    project_root: Path,
) -> ApprovalState:
    """Whether a marker for ``to_version`` exists and approves THIS upgrade."""
    expected = _approval_payload(
        to_version=to_version,
        from_version=from_version,
        daemon_dir=daemon_dir,
        project_root=project_root,
    )
    marker = OneShotApprovalStore(APPROVAL_SUBDIR).path(untracked_dir, expected[_FIELD_TO])
    if not marker.is_file():
        return ApprovalState.ABSENT
    try:
        recorded = json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ApprovalState.INVALID
    if not isinstance(recorded, dict):
        return ApprovalState.INVALID
    matches = all(recorded.get(name) == value for name, value in expected.items())
    return ApprovalState.VALID if matches else ApprovalState.INVALID


def _gated_install_path(untracked_dir: Path) -> Path:
    return untracked_dir / APPROVAL_SUBDIR / GATED_INSTALL_FILENAME


def _install_binding(daemon_dir: Path, project_root: Path) -> dict[str, str]:
    return {
        _FIELD_DAEMON_DIR: str(daemon_dir.resolve()),
        _FIELD_PROJECT_ROOT: str(project_root.resolve()),
    }


def record_gated_install(
    untracked_dir: Path, *, stamp: str, daemon_dir: Path, project_root: Path
) -> Path:
    """Record that the gate let an upgrade to ``stamp`` through; return the record's path.

    Only an upgrade recorded here counts as installed when the venv stamp
    already equals the target (fresh review MAJOR 1): ``hooks-daemon repair``
    after a manual checkout writes the same stamp with no gate involved.

    review2 MINOR 3, stated plainly: this record is unsigned JSON, protected
    only by ``upgrade_approval_guard`` denying a write under
    ``upgrade-approvals/`` by any agent route. It carries no FROM version and
    nothing binds it to a git commit. A forged marker already grants an
    upgrade's approval (the same guard, the same predicate); this is not a
    stronger class of defence than that one, and should not be cited as one.
    """
    payload = _install_binding(daemon_dir, project_root)
    payload[_FIELD_STAMP] = stamp
    payload[_FIELD_RECORDED_AT] = datetime.now(UTC).isoformat(timespec="seconds")
    path = _gated_install_path(untracked_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def gated_install_stamp(untracked_dir: Path, *, daemon_dir: Path, project_root: Path) -> str | None:
    """The stamp the gate last let through for this install, or None."""
    path = _gated_install_path(untracked_dir)
    if not path.is_file():
        return None
    try:
        recorded: object = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        # A corrupt, undecodable or unreadable receipt is not distinguished
        # from "no receipt" below (both mean the gate cannot vouch for this
        # stamp), but the reason is worth a record: unlike a missing file,
        # one that exists but cannot be read usually points at something
        # worth investigating. `ValueError` also catches `UnicodeDecodeError`
        # (invalid bytes) and `json.JSONDecodeError` (its own subclass);
        # `OSError` catches a permission-denied or otherwise unreadable
        # file. Either way this must fail CLOSED (review3 item 1): a read
        # error on a security-relevant receipt is not license to crash.
        logger.debug("gated_install_stamp: %s is not readable/valid JSON (%s)", path, exc)
        recorded = None
    if not isinstance(recorded, dict):
        return None
    binding = _install_binding(daemon_dir, project_root)
    if any(recorded.get(name) != value for name, value in binding.items()):
        return None
    stamp = recorded.get(_FIELD_STAMP)
    return stamp if isinstance(stamp, str) else None


def _decide(
    *,
    daemon_dir: Path,
    project_root: Path,
    from_version: str | None,
    to_version: str,
    target_ref: str,
    range_known: bool,
    downgrade: bool,
    guides: list[Path],
    findings: list[TaskFinding],
    escalations: list[str],
    acknowledgement: str | None,
    marker: Path,
    state: ApprovalState,
    notes: list[str],
) -> GateReport:
    digest = _digest(daemon_dir, from_version, to_version, guides, findings, escalations)
    has_reading = bool(guides or escalations or [f for f in findings if f.applies is not False])
    used: Path | None = None
    if not has_reading:
        verdict = GateVerdict.PROCEED
    elif acknowledgement != digest:
        verdict = GateVerdict.NEEDS_ACKNOWLEDGEMENT
    elif not escalations:
        verdict = GateVerdict.PROCEED
    elif state is ApprovalState.VALID:
        verdict = GateVerdict.PROCEED
        used = marker
    else:
        verdict = GateVerdict.NEEDS_APPROVAL
    return GateReport(
        daemon_dir=daemon_dir,
        project_root=project_root,
        from_version=from_version,
        to_version=to_version,
        target_ref=target_ref,
        range_known=range_known,
        downgrade=downgrade,
        already_installed=False,
        guides=guides,
        findings=findings,
        escalations=escalations,
        digest=digest,
        acknowledgement=acknowledgement,
        verdict=verdict,
        approval_marker=marker,
        approval_state=state,
        approval_used=used,
        notes=notes,
    )


def _unknown_range_report(
    *,
    daemon_dir: Path,
    project_root: Path,
    from_version: str | None,
    to_version: str,
    target_ref: str,
    include_unreleased: bool,
    acknowledgement: str | None,
    untracked_dir: Path,
    unknown_reason: str | None = None,
) -> GateReport:
    """A range the gate cannot read: detect everything, and send it to the owner."""
    findings: list[TaskFinding] = []
    guides: list[Path] = []
    escalations: list[str] = []
    target_is_release = _is_release(to_version)
    if not target_is_release:
        escalations.append(f"the target {to_version!r} is not a release version")
    else:
        upgrades_dir = daemon_dir / UPGRADES_SUBPATH
        tasks = tasks_for_range(
            TaskKind.PRE,
            _EARLIEST_RELEASE,
            to_version,
            upgrades_dir=upgrades_dir,
            include_unreleased=include_unreleased,
        )
        findings = evaluate(tasks, project_root)
        # review4 follow-up: symmetric with the findings scan above -- an
        # unknown FROM means show every guide up to TO, not none. Dropping
        # this list left a guarded branch install (Plan 00291) informing the
        # owner of nothing, including a staged UNRELEASED document it exists
        # to surface, whenever the range could not be verified.
        guides = _reading_list(upgrades_dir, _EARLIEST_RELEASE, to_version, include_unreleased)
    if unknown_reason is not None:
        escalations.append(unknown_reason)
    elif not _is_release(from_version):
        escalations.append(
            "the installed version is unknown (no venv stamp and no version in "
            f"{HOOKS_DAEMON_DOC.as_posix()}), so no MAJOR bump or breaking change can be "
            "ruled out"
        )
    escalations.extend(_critical_escalations(findings, daemon_dir))
    key = approval_key(to_version) if target_is_release else strip_tag_prefix(to_version)
    state = (
        check_approval(
            untracked_dir,
            to_version=to_version,
            from_version=from_version,
            daemon_dir=daemon_dir,
            project_root=project_root,
        )
        if target_is_release
        else ApprovalState.ABSENT
    )
    return _decide(
        daemon_dir=daemon_dir,
        project_root=project_root,
        from_version=from_version,
        to_version=to_version,
        target_ref=target_ref,
        range_known=False,
        downgrade=False,
        guides=guides,
        findings=findings,
        escalations=escalations,
        acknowledgement=acknowledgement,
        marker=OneShotApprovalStore(APPROVAL_SUBDIR).path(untracked_dir, key),
        state=state,
        notes=[],
    )


def evaluate_gate(
    *,
    daemon_dir: Path,
    project_root: Path,
    from_version: str | None,
    to_version: str,
    include_unreleased: bool,
    acknowledgement: str | None,
    untracked_dir: Path,
    installed_stamp: str | None = None,
    target_stamp: str | None = None,
    target_ref: str | None = None,
    from_untrusted: bool = False,
) -> GateReport:
    """Read what the upgrade changes and decide whether it may go on.

    ``from_version`` is the INSTALLED release (None when unknown).
    ``from_untrusted`` is True when ``from_version`` did NOT come from a venv
    stamp that names a release (review2 BLOCKER 1): the committed
    ``HOOKS-DAEMON.md`` marker it falls back to is an ordinary tracked file an
    agent edits routinely, so it must never by itself certify that nothing new
    needs installing. Callers that already know their ``from_version`` is
    trustworthy (a real stamp, or a test fixing the installed release) leave
    this False.
    ``acknowledgement`` is the value the caller passed with
    ``--skip-reading-confirmation`` (None when it passed no flag); it counts
    only when it equals this listing's digest. A valid approval is reported in
    ``approval_used`` and left in place: the caller removes it once the
    upgrade has completed, so a failure after the gate does not spend it.
    """
    ref = target_ref or (f"v{approval_key(to_version)}" if _is_release(to_version) else to_version)
    store = OneShotApprovalStore(APPROVAL_SUBDIR)
    if installed_stamp and target_stamp and installed_stamp == target_stamp:
        gated = gated_install_stamp(untracked_dir, daemon_dir=daemon_dir, project_root=project_root)
        if gated != target_stamp:
            return _unknown_range_report(
                daemon_dir=daemon_dir,
                project_root=project_root,
                from_version=None,
                to_version=to_version,
                target_ref=ref,
                include_unreleased=include_unreleased,
                acknowledgement=acknowledgement,
                untracked_dir=untracked_dir,
                unknown_reason=(
                    f"the venv stamp says {target_stamp} is already installed, but no upgrade "
                    "through this gate installed it (a repair after a manual checkout writes "
                    "the same stamp), so the version installed before it cannot be told"
                ),
            )
        return GateReport(
            daemon_dir=daemon_dir,
            project_root=project_root,
            from_version=from_version,
            to_version=to_version,
            target_ref=ref,
            range_known=True,
            downgrade=False,
            already_installed=True,
            guides=[],
            findings=[],
            escalations=[],
            digest="",
            acknowledgement=acknowledgement,
            verdict=GateVerdict.PROCEED,
            approval_marker=store.path(untracked_dir, strip_tag_prefix(to_version)),
            approval_state=ApprovalState.ABSENT,
            notes=[f"{target_stamp} is already installed: nothing new to read or approve."],
        )
    # review2 BLOCKER 1: an untrusted FROM (the doc marker, not a venv stamp)
    # that has caught up to or passed the target is exactly as suspect as a
    # stamp with no matching receipt (checked above), and gets the same
    # answer: an unknown range, sent to the owner. A trusted FROM (a real
    # stamp, or a caller that already knows its own installed release) is
    # unaffected and keeps deciding on the normal range logic below --
    # including a deliberate downgrade, which this is not: it has no receipt
    # to lose, only a claim this project never verified.
    if (
        from_untrusted
        and from_version is not None
        and _is_release(from_version)
        and _is_release(to_version)
        and release_tuple(from_version) >= release_tuple(to_version)
    ):
        return _unknown_range_report(
            daemon_dir=daemon_dir,
            project_root=project_root,
            from_version=from_version,
            to_version=to_version,
            target_ref=ref,
            include_unreleased=include_unreleased,
            acknowledgement=acknowledgement,
            untracked_dir=untracked_dir,
            unknown_reason=(
                f"the installed version ({_from_label(from_version)}) is read only from "
                f"{HOOKS_DAEMON_DOC.as_posix()} (no venv stamp names it), an ordinary tracked "
                "file an agent edits routinely, and it is not behind the target, so it cannot "
                "be trusted to show there is nothing new to install"
            ),
        )
    if from_version is None or not (_is_release(from_version) and _is_release(to_version)):
        return _unknown_range_report(
            daemon_dir=daemon_dir,
            project_root=project_root,
            from_version=from_version,
            to_version=to_version,
            target_ref=ref,
            include_unreleased=include_unreleased,
            acknowledgement=acknowledgement,
            untracked_dir=untracked_dir,
        )
    upgrades_dir = daemon_dir / UPGRADES_SUBPATH
    notes: list[str] = []
    downgrade = release_tuple(from_version) > release_tuple(to_version)
    guides: list[Path] = []
    findings: list[TaskFinding] = []
    escalations: list[str] = []
    if downgrade:
        notes.append("This is a downgrade: no upgrade guide describes it.")
    else:
        guides = _reading_list(upgrades_dir, from_version, to_version, include_unreleased)
        tasks = tasks_for_range(
            TaskKind.PRE,
            from_version,
            to_version,
            upgrades_dir=upgrades_dir,
            include_unreleased=include_unreleased,
        )
        findings = evaluate(tasks, project_root)
        escalations = _escalations(
            daemon_dir, from_version, to_version, include_unreleased, findings
        )
    return _decide(
        daemon_dir=daemon_dir,
        project_root=project_root,
        from_version=from_version,
        to_version=to_version,
        target_ref=ref,
        range_known=True,
        downgrade=downgrade,
        guides=guides,
        findings=findings,
        escalations=escalations,
        acknowledgement=acknowledgement,
        marker=store.path(untracked_dir, approval_key(to_version)),
        state=check_approval(
            untracked_dir,
            to_version=to_version,
            from_version=from_version,
            daemon_dir=daemon_dir,
            project_root=project_root,
        ),
        notes=notes,
    )


def _from_label(from_version: str | None) -> str:
    """``v3.66.0``, or words a human can read (and type) for an unknown version."""
    key = _version_key(from_version)
    return _UNKNOWN_FROM_PHRASE if key == UNKNOWN_VERSION else f"v{key}"


def _reading_lines(report: GateReport) -> list[str]:
    to = strip_tag_prefix(report.to_version)
    lines = [
        "",
        "📚 REQUIRED READING: Upgrade Guides",
        _RULE,
        f"Upgrading from {_from_label(report.from_version)} to v{to}",
    ]
    if not report.range_known:
        lines.extend(
            [
                "The gate does not know which version this project last installed,",
                f"so every upgrade guide up to v{to} is listed. Read the ones newer",
                "than the version you last installed.",
            ]
        )
    if report.guides:
        lines.append(f"{len(report.guides)} document(s) describe what this upgrade changes:")
        lines.extend(f"  • {guide}" for guide in report.guides)
    applicable = report.applicable
    if applicable:
        lines.extend(
            [
                "",
                f"{len(applicable)} pre-upgrade task(s) apply to this project. Carry them out",
                "BEFORE the new version is deployed (each file says how):",
            ]
        )
        for finding in applicable:
            lines.extend(format_findings_line(finding))
    if report.escalations:
        lines.extend(["", "This upgrade needs the project owner, because:"])
        lines.extend(f"  ! {reason}" for reason in report.escalations)
    return lines


def _approval_lines(report: GateReport) -> list[str]:
    frm = _version_key(report.from_version)
    to = approval_key(report.to_version) if _is_release(report.to_version) else report.to_version
    daemon_dir = report.daemon_dir
    lines = [
        "",
        "UPGRADE STOPPED before anything was deployed: this upgrade needs the project",
        "owner's approval. An agent must not record it: report the reasons above to",
        "the user and stop.",
    ]
    if report.approval_state is ApprovalState.INVALID:
        lines.append(
            f"(The marker at {report.approval_marker} was not written by approve-upgrade "
            "for this upgrade, so it does not count.)"
        )
    lines.extend(
        [
            "The owner approves ONE run of exactly this upgrade, in their own terminal (it",
            "asks them to type a confirmation phrase naming both versions). With a daemon",
            "that has the command:",
            f"  .claude/hooks-daemon/bin/{APPROVE_COMMAND} {to} --from {frm}",
            "or, from ANY installed version, with this release's own code (the gate's own",
            "Python 3.11+ runs it):",
            f'  tmp="$(mktemp -d)" && git -C "{daemon_dir}" archive {report.target_ref} src '
            f'| tar -x -C "$tmp" && "{sys.executable}" "$tmp/{_STANDALONE_REL}" approve '
            f'--daemon-dir "{daemon_dir}" --project-root "{report.project_root}" '
            f"--from {frm} --to {to}",
            f"Then re-run the upgrade with {SKIP_READING_FLAG}={report.digest}",
        ]
    )
    return lines


def _verdict_lines(report: GateReport) -> list[str]:
    if report.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT:
        lines = [
            "",
            "UPGRADE STOPPED before anything was deployed: nothing confirmed the reading above.",
        ]
        if report.acknowledgement is not None:
            given = report.acknowledgement or "none"
            lines.append(
                f"The {SKIP_READING_FLAG} value given ({given}) does not match this listing."
            )
        lines.extend(
            [
                "Read every document listed and carry out the pre-upgrade tasks that apply.",
                "Then re-run the same upgrade command with:",
                f"  {SKIP_READING_FLAG}={report.digest}",
            ]
        )
        return lines
    if report.verdict is GateVerdict.NEEDS_APPROVAL:
        return _approval_lines(report)
    lines = [""]
    if report.approval_used is not None:
        lines.append(f"✓ Owner's approval accepted ({report.approval_used}).")
    lines.append(f"✓ Reading confirmed ({SKIP_READING_FLAG}); proceeding.")
    return lines


def format_gate_report(report: GateReport) -> str:
    """The text Layer 2 prints (to stderr) for the gate."""
    if report.already_installed or not report.has_reading:
        lines = [f"  {note}" for note in report.notes]
        if not report.already_installed:
            lines.append("✓ No upgrade guides or pre-upgrade tasks for this version range")
        return "\n".join(lines)
    return "\n".join(_reading_lines(report) + _verdict_lines(report))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upgrade-gate",
        description="Decide whether an upgrade may deploy (Plan 00376 Phase 3).",
    )
    parser.add_argument("--daemon-dir", type=Path, required=True, help="Target daemon checkout")
    parser.add_argument("--project-root", type=Path, required=True, help="Project being upgraded")
    parser.add_argument("--to", dest="to_version", required=True, help="Target release")
    parser.add_argument(
        "--installed-stamp",
        default="",
        help="The existing venv's .daemon-version stamp (empty when there is no venv)",
    )
    parser.add_argument(
        "--from",
        dest="from_version",
        default=None,
        help="Override the installed version (tests); normally derived from the install",
    )
    parser.add_argument("--target-stamp", default="", help="The stamp the target will install")
    parser.add_argument("--target-ref", default=None, help="Git ref of the target in the clone")
    parser.add_argument(
        "--include-unreleased",
        action="store_true",
        help="Also read CLAUDE/UPGRADES/UNRELEASED/ (a branch install)",
    )
    parser.add_argument(
        "--acknowledgement",
        default=None,
        help=f"The value the caller passed with {SKIP_READING_FLAG} (empty for the bare flag)",
    )
    parser.add_argument(
        "--untracked-dir",
        type=Path,
        default=None,
        help="Where approvals live (default: the project's daemon untracked dir)",
    )
    parser.add_argument(
        "--verdict-file",
        type=Path,
        default=None,
        help="Where to write the verdict, in a directory only the caller created",
    )
    parser.add_argument("--nonce", default="", help="The caller's nonce, echoed in the verdict")
    return parser


def _write_verdict(path: Path, nonce: str, report: GateReport) -> None:
    lines = [f"{_NONCE_PREFIX}{nonce}", f"{_VERDICT_PREFIX}{report.verdict.value}"]
    if report.approval_used is not None:
        lines.append(f"{_APPROVAL_USED_PREFIX}{report.approval_used}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _VERDICT_FILE_MODE)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Evaluate the gate, print its report to stderr, return the verdict's exit code.

    With ``--verdict-file`` the verdict is written there, first line the
    caller's ``--nonce``, then ``verdict=<verdict>`` and, when an owner's
    approval let the upgrade through, ``approval-marker=<path>`` for the
    caller to remove once the upgrade completes. The caller believes a zero
    exit only with that file (fresh review BLOCKER 1): a stdout line is what
    any wrapper process can print. A PROCEED for a target stamp is recorded
    (:func:`record_gated_install`) as what the gate let through.
    """
    args = _build_parser().parse_args(argv)
    project_root = Path(args.project_root).resolve()
    untracked_dir = (
        Path(args.untracked_dir) if args.untracked_dir else get_untracked_dir(project_root)
    )
    if args.from_version is not None:
        from_version: str | None = str(args.from_version)
        from_untrusted = False
    else:
        from_version, source = installed_version(args.installed_stamp or None, project_root)
        from_untrusted = source != SOURCE_VENV_STAMP
        # review2 N1: when the stamp claims the target itself, evaluate_gate
        # checks it against this install's own gated-install record next and
        # may reject it (no upgrade through this gate installed it) -- so
        # this line must not read as the settled answer in that one case.
        claims_target = (
            bool(args.installed_stamp)
            and bool(args.target_stamp)
            and args.installed_stamp == args.target_stamp
        )
        qualifier = ", checked against the gated-install record next" if claims_target else ""
        origin = (
            f"no venv stamp names it, and {SOURCE_DOC_MARKER} carries no release"
            if source == SOURCE_NONE
            else f"from the {source}{qualifier}"
        )
        print(
            f"Installed version: {from_version or UNKNOWN_VERSION} ({origin})",
            file=sys.stderr,
        )
    report = evaluate_gate(
        daemon_dir=Path(args.daemon_dir).resolve(),
        project_root=project_root,
        from_version=from_version,
        to_version=str(args.to_version),
        include_unreleased=bool(args.include_unreleased),
        acknowledgement=args.acknowledgement,
        untracked_dir=untracked_dir,
        installed_stamp=args.installed_stamp or None,
        target_stamp=args.target_stamp or None,
        target_ref=args.target_ref,
        from_untrusted=from_untrusted,
    )
    print(format_gate_report(report), file=sys.stderr)
    if report.verdict is GateVerdict.PROCEED and args.target_stamp and not report.already_installed:
        record_gated_install(
            untracked_dir,
            stamp=str(args.target_stamp),
            daemon_dir=Path(args.daemon_dir).resolve(),
            project_root=project_root,
        )
    if args.verdict_file is not None:
        _write_verdict(Path(args.verdict_file), str(args.nonce), report)
    return report.verdict.exit_code


def _build_record_install_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upgrade-gate record-install",
        description="Record a fresh install as what the gate would have let through (N327).",
    )
    parser.add_argument("--daemon-dir", type=Path, required=True, help="The daemon checkout")
    parser.add_argument("--project-root", type=Path, required=True, help="The installed project")
    parser.add_argument("--stamp", required=True, help="The stamp the fresh install wrote")
    parser.add_argument(
        "--untracked-dir",
        type=Path,
        default=None,
        help="Where approvals live (default: the project's daemon untracked dir)",
    )
    return parser


def record_install_main(argv: list[str] | None = None) -> int:
    """Record a FRESH install's stamp as a gated install; return 0.

    A fresh install runs no upgrade, so the gate never records it, and its
    first idempotent re-run then finds a venv stamp naming the target with no
    receipt (N327). The caller (``scripts/install_version.sh``) calls this only
    when no venv stamp existed before the install, which is what makes the
    stamp the install's own and not one a manual checkout plus ``repair`` wrote.
    An empty stamp is refused: a receipt for nothing vouches for nothing.
    """
    args = _build_record_install_parser().parse_args(argv)
    if not str(args.stamp).strip():
        _build_record_install_parser().error("--stamp must name the installed stamp")
    project_root = Path(args.project_root).resolve()
    untracked_dir = (
        Path(args.untracked_dir) if args.untracked_dir else get_untracked_dir(project_root)
    )
    path = record_gated_install(
        untracked_dir,
        stamp=str(args.stamp),
        daemon_dir=Path(args.daemon_dir).resolve(),
        project_root=project_root,
    )
    print(f"Recorded {args.stamp} as a gated install: {path}", file=sys.stderr)
    return 0


def run_approval(
    *,
    project_root: Path,
    daemon_dir: Path,
    from_version: str | None,
    to_version: str,
    untracked_dir: Path,
    stdin: TextIO,
    stdout: TextIO,
) -> int:
    """The owner's approval of one upgrade: a terminal and a typed phrase, or nothing.

    An agent's shell has no terminal on stdin, so this refuses it outright;
    the phrase names both versions, so a human confirms the exact upgrade the
    gate stopped. Returns 0 when the marker was written, 1 otherwise.
    """
    frm = _from_label(from_version)
    to = approval_key(to_version)
    if not stdin.isatty():
        print(
            "approve-upgrade must be run by the project owner in their own terminal: "
            "there is no terminal on stdin, so nothing was approved.",
            file=stdout,
        )
        return 1
    phrase = _APPROVAL_PHRASE.format(frm=frm, to=to)
    print(f"To approve ONE upgrade of {project_root} from {frm} to v{to}, type:", file=stdout)
    print(f"  {phrase}", file=stdout)
    stdout.flush()
    answer = stdin.readline().strip()
    if answer != phrase:
        print("That is not the phrase, so nothing was approved.", file=stdout)
        return 1
    marker = write_approval(
        untracked_dir,
        to_version=to,
        from_version=from_version,
        daemon_dir=daemon_dir,
        project_root=project_root,
    )
    print(f"Approved one upgrade from {frm} to v{to}; marker: {marker}", file=stdout)
    print(
        f"The upgrade re-run with {SKIP_READING_FLAG}=<digest> uses it, and removes it once "
        "that upgrade completes.",
        file=stdout,
    )
    return 0


def _build_approve_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upgrade-gate approve",
        description="The project owner's one-shot approval of one upgrade (needs a terminal).",
    )
    parser.add_argument("--daemon-dir", type=Path, required=True, help="The daemon checkout")
    parser.add_argument("--project-root", type=Path, required=True, help="The project")
    parser.add_argument(
        "--from",
        dest="from_version",
        required=True,
        help=f"The installed release the gate named (or {UNKNOWN_VERSION})",
    )
    parser.add_argument("--to", dest="to_version", required=True, help="The target release")
    parser.add_argument("--untracked-dir", type=Path, default=None, help="Override (tests)")
    return parser


def approve_main(argv: list[str] | None = None) -> int:
    """``upgrade_gate_standalone.py approve ...``: run :func:`run_approval` on the terminal."""
    args = _build_approve_parser().parse_args(argv)
    project_root = Path(args.project_root).resolve()
    frm = None if args.from_version == UNKNOWN_VERSION else str(args.from_version)
    return run_approval(
        project_root=project_root,
        daemon_dir=Path(args.daemon_dir).resolve(),
        from_version=frm,
        to_version=str(args.to_version),
        untracked_dir=(
            Path(args.untracked_dir) if args.untracked_dir else get_untracked_dir(project_root)
        ),
        stdin=sys.stdin,
        stdout=sys.stdout,
    )
