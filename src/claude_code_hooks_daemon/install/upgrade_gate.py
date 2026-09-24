"""The pre-deploy upgrade gate (Plan 00376 Phase 3).

Layer 2 (``scripts/upgrade_version.sh``) runs this once the daemon checkout
sits on the target and before anything is deployed into the project. It
assembles what the upgrade changes -- the crossed guides, and every
pre-upgrade task whose detection finds a call site in the project -- and
returns one verdict:

- ``PROCEED`` -- nothing to read, or the caller confirmed it has read it.
- ``NEEDS_ACKNOWLEDGEMENT`` -- there is something to read and the caller has
  not passed ``--skip-reading-confirmation``. There is no terminal inference:
  an agent and a human get the same stop.
- ``NEEDS_APPROVAL`` -- the upgrade breaks the project, so the owner must
  approve it (``hooks-daemon approve-upgrade <version>``, a one-shot marker
  from :mod:`claude_code_hooks_daemon.utils.one_shot_approval`). The triggers
  are a MAJOR bump, a crossed config-changes manifest declaring
  ``breaking: true``, and a ``critical`` pre-upgrade task detected in the
  project. The approval is consumed only by the run it lets through.

The caller (bash) turns a stop into an abort that puts the daemon checkout
back on the previous ref (Task 1.2), so a stopped upgrade deploys nothing.

Standard library only, like everything it loads: it runs before the target's
venv exists (see ``upgrade_gate_standalone.py``).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final

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

#: Sub-directory of the daemon's untracked dir holding upgrade approvals.
APPROVAL_SUBDIR: Final[str] = "upgrade-approvals"
#: The flag a caller passes to confirm it has read the reading list.
SKIP_READING_FLAG: Final[str] = "--skip-reading-confirmation"
#: The human's command; the version is appended.
APPROVE_COMMAND: Final[str] = "hooks-daemon approve-upgrade"

_CONFIG_CHANGES_DIRNAME: Final[str] = "config-changes"
_MANIFEST_RE: Final[re.Pattern[str]] = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)\.yaml$")
_BREAKING_RE: Final[re.Pattern[str]] = re.compile(r"^breaking:\s*true\s*(?:#.*)?$", re.MULTILINE)
_BUILD_METADATA_SEPARATOR: Final[str] = "+"
_RULE: Final[str] = "=" * 70


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


@dataclass(frozen=True)
class GateReport:
    """Everything the gate read, and its verdict."""

    from_version: str
    to_version: str
    range_known: bool
    downgrade: bool
    guides: list[Path]
    findings: list[TaskFinding]
    escalations: list[str]
    acknowledged: bool
    verdict: GateVerdict
    approval_marker: Path
    approval_consumed: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def applicable(self) -> list[TaskFinding]:
        """Pre-upgrade tasks detected in the project, or whose scan could not run."""
        return [finding for finding in self.findings if finding.applies is not False]


def approval_key(version: str) -> str:
    """The release a marker approves: ``v4.0+main.abc`` -> ``4.0.0``."""
    return ".".join(str(part) for part in release_tuple(version))


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


def _escalations(
    upgrades_dir: Path,
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
        f"config-changes manifest declares breaking: true: {path}"
        for path in breaking_manifests(upgrades_dir, from_version, to_version, include_unreleased)
    )
    reasons.extend(
        f"critical pre-upgrade task detected in this project: {finding.task.path}"
        for finding in findings
        if finding.task.severity == SEVERITY_CRITICAL and finding.applies is not False
    )
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
        if TaskKind.PRE.value not in document.relative_to(upgrades_dir).parts
    ]


def evaluate_gate(
    *,
    daemon_dir: Path,
    project_root: Path,
    from_version: str,
    to_version: str,
    include_unreleased: bool,
    acknowledged: bool,
    untracked_dir: Path,
) -> GateReport:
    """Read what the upgrade changes and decide whether it may go on.

    An approval marker is consumed only when the verdict is ``PROCEED``
    because of it, so an approval recorded ahead of an unacknowledged run is
    still there for the acknowledged re-run.
    """
    upgrades_dir = daemon_dir / UPGRADES_SUBPATH
    store = OneShotApprovalStore(APPROVAL_SUBDIR)
    notes: list[str] = []
    try:
        from_v = release_tuple(from_version)
        to_v = release_tuple(to_version)
    except ValueError:
        verdict = GateVerdict.PROCEED if acknowledged else GateVerdict.NEEDS_ACKNOWLEDGEMENT
        return GateReport(
            from_version=from_version,
            to_version=to_version,
            range_known=False,
            downgrade=False,
            guides=[],
            findings=[],
            escalations=[],
            acknowledged=acknowledged,
            verdict=verdict,
            approval_marker=store.path(untracked_dir, strip_tag_prefix(to_version)),
        )

    marker = store.path(untracked_dir, approval_key(to_version))
    downgrade = from_v > to_v
    if downgrade:
        notes.append("This is a downgrade: no upgrade guide describes it.")
        guides: list[Path] = []
        findings: list[TaskFinding] = []
        escalations: list[str] = []
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
            upgrades_dir, from_version, to_version, include_unreleased, findings
        )

    applicable = [finding for finding in findings if finding.applies is not False]
    has_reading = bool(guides or applicable or escalations)
    consumed = False
    if not has_reading:
        verdict = GateVerdict.PROCEED
    elif not acknowledged:
        verdict = GateVerdict.NEEDS_ACKNOWLEDGEMENT
    elif not escalations:
        verdict = GateVerdict.PROCEED
    elif store.consume(untracked_dir, approval_key(to_version)):
        consumed = True
        verdict = GateVerdict.PROCEED
    else:
        verdict = GateVerdict.NEEDS_APPROVAL
    return GateReport(
        from_version=from_version,
        to_version=to_version,
        range_known=True,
        downgrade=downgrade,
        guides=guides,
        findings=findings,
        escalations=escalations,
        acknowledged=acknowledged,
        verdict=verdict,
        approval_marker=marker,
        approval_consumed=consumed,
        notes=notes,
    )


def _reading_lines(report: GateReport) -> list[str]:
    frm, to = strip_tag_prefix(report.from_version), strip_tag_prefix(report.to_version)
    lines = ["", "📚 REQUIRED READING: Upgrade Guides", _RULE, f"Upgrading from v{frm} to v{to}"]
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
        lines.extend(["", "This upgrade breaks something this project relies on:"])
        lines.extend(f"  ! {reason}" for reason in report.escalations)
    return lines


def _verdict_lines(report: GateReport) -> list[str]:
    if report.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT:
        return [
            "",
            "UPGRADE STOPPED before anything was deployed: nothing confirmed the reading above.",
            "Read every document listed, carry out the pre-upgrade tasks that apply, then",
            f"re-run the same upgrade command with {SKIP_READING_FLAG}.",
        ]
    if report.verdict is GateVerdict.NEEDS_APPROVAL:
        key = approval_key(report.to_version)
        return [
            "",
            "UPGRADE STOPPED before anything was deployed: this upgrade needs the project",
            "owner's approval. An agent must not record it. Report the reasons above and",
            "stop. The owner approves ONE run by executing:",
            f"  .claude/hooks-daemon/bin/{APPROVE_COMMAND} {key}",
            "(on a daemon older than that command, by creating the file",
            f"  {report.approval_marker}",
            f"by hand), after which the upgrade is re-run with {SKIP_READING_FLAG}.",
        ]
    lines = [""]
    if report.approval_consumed:
        lines.append(f"✓ Owner's approval consumed ({report.approval_marker}).")
    lines.append(f"✓ Reading confirmed ({SKIP_READING_FLAG}); proceeding.")
    return lines


def format_gate_report(report: GateReport) -> str:
    """The text Layer 2 prints (to stderr) for the gate."""
    if not report.range_known:
        lines = [
            "",
            f"From {report.from_version!r} to {report.to_version!r} is not a range of release",
            "versions, so the gate cannot tell which upgrade guides this upgrade crosses.",
            "Read the guides in CLAUDE/UPGRADES/ newer than the version this project last",
            "installed, up to the one being installed.",
        ]
        return "\n".join(lines + _verdict_lines(report))
    has_reading = bool(report.guides or report.applicable or report.escalations)
    if not has_reading:
        lines = [f"  {note}" for note in report.notes]
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
    parser.add_argument("--from", dest="from_version", required=True, help="Previous version")
    parser.add_argument("--to", dest="to_version", required=True, help="Target version")
    parser.add_argument(
        "--include-unreleased",
        action="store_true",
        help="Also read CLAUDE/UPGRADES/UNRELEASED/ (a branch install)",
    )
    parser.add_argument(
        "--acknowledged",
        action="store_true",
        help=f"The caller passed {SKIP_READING_FLAG}",
    )
    parser.add_argument(
        "--untracked-dir",
        type=Path,
        default=None,
        help="Where approvals live (default: the project's daemon untracked dir)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Evaluate the gate, print its report to stderr, return the verdict's exit code."""
    args = _build_parser().parse_args(argv)
    project_root = Path(args.project_root).resolve()
    untracked_dir = (
        Path(args.untracked_dir) if args.untracked_dir else get_untracked_dir(project_root)
    )
    report = evaluate_gate(
        daemon_dir=Path(args.daemon_dir).resolve(),
        project_root=project_root,
        from_version=str(args.from_version),
        to_version=str(args.to_version),
        include_unreleased=bool(args.include_unreleased),
        acknowledged=bool(args.acknowledged),
        untracked_dir=untracked_dir,
    )
    print(format_gate_report(report), file=sys.stderr)
    return report.verdict.exit_code
