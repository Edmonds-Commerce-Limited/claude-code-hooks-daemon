"""The pre-deploy upgrade gate (Plan 00376 Phase 3, review-00376 fixes).

The gate decides, once the daemon checkout sits on the target and before
anything is deployed, whether the upgrade may go on. It never asks whether a
terminal is attached:

- the FROM side is what is INSTALLED (the venv stamp, else the project's
  ``HOOKS-DAEMON.md`` marker), never the checkout, which may already be on the
  target (review MAJOR 1); with neither, the owner must approve;
- a caller with something to read stops until it passes
  ``--skip-reading-confirmation=<digest>``, the digest of the listing it was
  shown (review MINOR 6);
- a change that breaks the project also needs the owner's one-shot approval,
  a marker bound to this upgrade's from/to versions and install path, which a
  bare ``touch`` cannot forge (review MAJOR 4).
"""

from __future__ import annotations

import errno
import io
import json
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install import upgrade_gate as upgrade_gate_module
from claude_code_hooks_daemon.install.upgrade_gate import (
    APPROVAL_SUBDIR,
    ApprovalState,
    GateReport,
    GateVerdict,
    approval_key,
    approve_main,
    breaking_manifests,
    check_approval,
    evaluate_gate,
    format_gate_report,
    gated_install_stamp,
    installed_version,
    main,
    record_gated_install,
    record_install_main,
    run_approval,
    write_approval,
)
from claude_code_hooks_daemon.utils.one_shot_approval import OneShotApprovalStore
from claude_code_hooks_daemon.utils.path_predicates import TextOrReason

_REPO_UPGRADES_ROOT = Path(__file__).resolve().parents[3]

_TASK = """# Task: {title}

**Type**: workflow-change
**Severity**: {severity}
**Applies to**: all
**Idempotent**: yes
**Detect**: `{pattern}`
**Detect in**: `*.sh`

## Why

Because.

## How to detect if this applies to you

Look.

## How to handle

Do it.

## How to confirm

Check it.
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def daemon_dir(tmp_path: Path) -> Path:
    root = tmp_path / "daemon"
    (root / "CLAUDE" / "UPGRADES" / "config-changes").mkdir(parents=True)
    return root


@pytest.fixture
def upgrades(daemon_dir: Path) -> Path:
    return daemon_dir / "CLAUDE" / "UPGRADES"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    _write(root / "tools" / "qa.sh", "set -e\nhooks-daemon plan-qa --json | jq .level\n")
    return root


@pytest.fixture
def untracked(tmp_path: Path) -> Path:
    return tmp_path / "untracked"


def _guide(upgrades: Path, name: str) -> Path:
    major = name.split(".")[0]
    return _write(upgrades / major / name / f"{name}.md", f"# {name}\n")


def _pre_task(
    upgrades: Path, guide: str, name: str, *, severity: str = "recommended", pattern: str
) -> Path:
    major = guide.split(".")[0]
    return _write(
        upgrades / major / guide / "pre-upgrade-tasks" / name,
        _TASK.format(title=name, severity=severity, pattern=pattern),
    )


def _gate(
    daemon_dir: Path,
    project: Path,
    untracked: Path,
    frm: str | None,
    to: str,
    *,
    acknowledgement: str | None = None,
    include_unreleased: bool = False,
    installed_stamp: str | None = None,
    target_stamp: str | None = None,
) -> GateReport:
    return evaluate_gate(
        daemon_dir=daemon_dir,
        project_root=project,
        from_version=frm,
        to_version=to,
        include_unreleased=include_unreleased,
        acknowledgement=acknowledgement,
        untracked_dir=untracked,
        installed_stamp=installed_stamp,
        target_stamp=target_stamp,
    )


def _acked(
    daemon_dir: Path,
    project: Path,
    untracked: Path,
    frm: str | None,
    to: str,
    *,
    include_unreleased: bool = False,
) -> GateReport:
    """Run once to learn the listing's digest, then again acknowledging it."""
    first = _gate(daemon_dir, project, untracked, frm, to, include_unreleased=include_unreleased)
    return _gate(
        daemon_dir,
        project,
        untracked,
        frm,
        to,
        acknowledgement=first.digest,
        include_unreleased=include_unreleased,
    )


def _approve(untracked: Path, daemon_dir: Path, project: Path, frm: str, to: str) -> Path:
    return write_approval(
        untracked, to_version=to, from_version=frm, daemon_dir=daemon_dir, project_root=project
    )


class TestNothingToRead:
    def test_proceeds_silently(self, daemon_dir: Path, project: Path, untracked: Path) -> None:
        report = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.verdict is GateVerdict.PROCEED
        assert report.guides == []
        assert "No upgrade guides" in format_gate_report(report)

    def test_a_pre_task_that_detects_nothing_stays_silent(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _pre_task(upgrades, "v3.64.0-to-v3.65.0", "01-quiet.md", pattern="absent-token")
        report = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.verdict is GateVerdict.PROCEED
        assert "01-quiet.md" not in format_gate_report(report)


class TestReadingNeedsAcknowledgement:
    def test_a_crossed_guide_stops_an_unacknowledged_caller(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        guide = _guide(upgrades, "v3.64.0-to-v3.65.0")
        report = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        text = format_gate_report(report)
        assert str(guide) in text
        assert f"--skip-reading-confirmation={report.digest}" in text

    def test_the_digest_of_what_was_listed_lets_it_through(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _guide(upgrades, "v3.64.0-to-v3.65.0")
        assert _acked(daemon_dir, project, untracked, "3.64.0", "3.65.0").verdict is (
            GateVerdict.PROCEED
        )

    @pytest.mark.parametrize("acknowledgement", ["", "0123456789ab"])
    def test_a_bare_or_stale_acknowledgement_is_not_one(
        self,
        daemon_dir: Path,
        upgrades: Path,
        project: Path,
        untracked: Path,
        acknowledgement: str,
    ) -> None:
        _guide(upgrades, "v3.64.0-to-v3.65.0")
        report = _gate(
            daemon_dir, project, untracked, "3.64.0", "3.65.0", acknowledgement=acknowledgement
        )
        assert report.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        assert "does not match" in format_gate_report(report)

    def test_the_digest_changes_when_the_listing_does(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _guide(upgrades, "v3.64.0-to-v3.65.0")
        before = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0").digest
        _guide(upgrades, "v3.64.0-to-v3.64.1")
        after = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0").digest
        assert before != after

    def test_a_detected_pre_task_is_named_at_file_and_line(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _pre_task(upgrades, "v3.64.0-to-v3.65.0", "01-rename.md", pattern="plan-qa[^\\n]*--json")
        report = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        text = format_gate_report(report)
        assert "01-rename.md" in text
        assert "tools/qa.sh:2" in text

    def test_a_task_whose_scan_could_not_run_says_so(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _pre_task(upgrades, "v3.64.0-to-v3.65.0", "01-broken.md", pattern="(unclosed")
        text = format_gate_report(_gate(daemon_dir, project, untracked, "3.64.0", "3.65.0"))
        assert "01-broken.md" in text
        assert "could not run" in text

    def test_staged_documents_count_on_a_branch_install(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _write(upgrades / "UNRELEASED" / "release-notes" / "01-note.md", "# note\n")
        release = _gate(daemon_dir, project, untracked, "3.66.0", "3.66.0")
        branch = _gate(daemon_dir, project, untracked, "3.66.0", "3.66.0", include_unreleased=True)
        assert release.verdict is GateVerdict.PROCEED
        assert branch.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT

    def test_a_downgrade_crosses_no_guide(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        """A downgrade FROM a real venv stamp is trusted and proceeds silently.

        ``installed_stamp`` stands in for the venv's own ``.daemon-version``
        (review2 BLOCKER 1: an unstamped FROM at or past the target is never
        trusted, so this scenario must be backed by a stamp to mean what it
        says).
        """
        _guide(upgrades, "v3.64.0-to-v3.65.0")
        report = _gate(
            daemon_dir, project, untracked, "3.65.0", "3.64.0", installed_stamp="v3.65.0"
        )
        assert report.verdict is GateVerdict.PROCEED
        assert "downgrade" in format_gate_report(report)


class TestAlreadyInstalled:
    """The exact target already installed: a re-run, or a direct call's second pass.

    Only an upgrade this gate let through counts as installed (fresh review
    MAJOR 1): ``hooks-daemon repair`` after a manual checkout writes the same
    venv stamp, and would otherwise have the gate wave a MAJOR through.
    """

    def test_the_same_stamp_proceeds_even_on_a_branch_install(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _write(upgrades / "UNRELEASED" / "release-notes" / "01-note.md", "# note\n")
        stamp = "v3.66.0+main.abc1234"
        record_gated_install(untracked, stamp=stamp, daemon_dir=daemon_dir, project_root=project)
        report = _gate(
            daemon_dir,
            project,
            untracked,
            "3.66.0",
            "3.66.0",
            include_unreleased=True,
            installed_stamp=stamp,
            target_stamp=stamp,
        )
        assert report.verdict is GateVerdict.PROCEED
        assert "already installed" in format_gate_report(report)

    def test_a_different_commit_of_the_same_release_is_not_installed(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _write(upgrades / "UNRELEASED" / "release-notes" / "01-note.md", "# note\n")
        report = _gate(
            daemon_dir,
            project,
            untracked,
            "3.66.0",
            "3.66.0",
            include_unreleased=True,
            installed_stamp="v3.66.0+main.abc1234",
            target_stamp="v3.66.0+main.def5678",
        )
        assert report.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT

    @pytest.mark.parametrize("recorded", [None, "v3.66.0", "v4.0.0"])
    def test_a_stamp_no_gated_upgrade_wrote_is_not_installed(
        self, daemon_dir: Path, project: Path, untracked: Path, recorded: str | None
    ) -> None:
        """A checkout of v4 plus `repair` stamps the venv v4 with no gate involved."""
        if recorded is not None:
            other = daemon_dir if recorded != "v4.0.0" else daemon_dir / "elsewhere"
            record_gated_install(untracked, stamp=recorded, daemon_dir=other, project_root=project)
        report = _gate(
            daemon_dir,
            project,
            untracked,
            "4.0.0",
            "4.0.0",
            installed_stamp="v4.0.0",
            target_stamp="v4.0.0",
        )
        assert not report.already_installed
        assert report.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        assert "no upgrade through this gate installed it" in format_gate_report(report)
        acknowledged = _gate(
            daemon_dir,
            project,
            untracked,
            "4.0.0",
            "4.0.0",
            acknowledgement=report.digest,
            installed_stamp="v4.0.0",
            target_stamp="v4.0.0",
        )
        assert acknowledged.verdict is GateVerdict.NEEDS_APPROVAL

    def test_the_gate_records_what_it_let_through(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        argv = [
            "--daemon-dir",
            str(daemon_dir),
            "--project-root",
            str(project),
            "--untracked-dir",
            str(untracked),
            "--installed-stamp",
            "v3.64.0",
            "--to",
            "3.65.0",
            "--target-stamp",
            "v3.65.0",
        ]
        assert main(argv) == 0
        assert gated_install_stamp(untracked, daemon_dir=daemon_dir, project_root=project) == (
            "v3.65.0"
        )
        rerun = [*argv[:-6], "--installed-stamp", "v3.65.0", *argv[-4:]]
        assert main(rerun) == 0

    def test_a_stop_records_nothing(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _guide(upgrades, "v3.64.0-to-v3.65.0")
        argv = [
            "--daemon-dir",
            str(daemon_dir),
            "--project-root",
            str(project),
            "--untracked-dir",
            str(untracked),
            "--installed-stamp",
            "v3.64.0",
            "--to",
            "3.65.0",
            "--target-stamp",
            "v3.65.0",
        ]
        assert main(argv) == GateVerdict.NEEDS_ACKNOWLEDGEMENT.exit_code
        assert gated_install_stamp(untracked, daemon_dir=daemon_dir, project_root=project) is None


class TestGatedInstallStampFailsClosedOnAnUnreadableReceipt:
    """Plan 00376 review3 item 1: check the OTHER error-hiding fixes the same
    way as MAJOR 1 -- with a probe proving which way each falls.

    ``gated_install_stamp`` used to catch only ``json.JSONDecodeError``
    around ``path.read_text(...)`` + ``json.loads(...)``. A receipt file
    that cannot be READ at all -- invalid UTF-8 bytes (``UnicodeDecodeError``,
    a ``ValueError`` subclass) or a permission-denied open (``OSError``) --
    was never caught, so the gate crashed instead of falling back to
    "unknown", the fail-closed answer every other read failure here takes.
    """

    def test_invalid_utf8_bytes_fail_closed_instead_of_crashing(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        path = untracked / APPROVAL_SUBDIR / "gated-install.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe\x00not valid utf-8")

        assert gated_install_stamp(untracked, daemon_dir=daemon_dir, project_root=project) is None

    def test_a_permission_denied_receipt_fails_closed_instead_of_crashing(
        self,
        daemon_dir: Path,
        project: Path,
        untracked: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Plan 00466 N56: every test runs as root, so a `chmod 0o000` proves
        nothing here -- root reads through any permission bits. Fault the
        specific ``Path.read_text`` call `gated_install_stamp` makes instead,
        which fails the same way for root and non-root alike.
        """
        path = untracked / APPROVAL_SUBDIR / "gated-install.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"stamp": "v3.65.0"}', encoding="utf-8")

        real_read_text = Path.read_text

        def _faulty_read_text(
            self: Path, encoding: str | None = None, errors: str | None = None
        ) -> str:
            if self == path:
                raise PermissionError(errno.EACCES, "Permission denied", str(self))
            return real_read_text(self, encoding=encoding, errors=errors)

        monkeypatch.setattr(Path, "read_text", _faulty_read_text)

        assert gated_install_stamp(untracked, daemon_dir=daemon_dir, project_root=project) is None


class TestUnknownRange:
    """Review MINOR 2 / MAJOR 1: an unreadable range fails closed to the owner."""

    def test_an_unknown_previous_version_needs_the_owner(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        stopped = _gate(daemon_dir, project, untracked, None, "3.65.0")
        assert stopped.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        assert "installed version is unknown" in format_gate_report(stopped)
        acknowledged = _acked(daemon_dir, project, untracked, None, "3.65.0")
        assert acknowledged.verdict is GateVerdict.NEEDS_APPROVAL

    def test_an_unknown_previous_version_still_runs_every_detection_up_to_the_target(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _pre_task(upgrades, "v3.10.0-to-v3.11.0", "01-old.md", pattern="plan-qa[^\\n]*--json")
        text = format_gate_report(_gate(daemon_dir, project, untracked, None, "3.65.0"))
        assert "01-old.md" in text
        assert "tools/qa.sh:2" in text

    def test_the_owner_can_approve_an_unknown_previous_version(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        write_approval(
            untracked,
            to_version="3.65.0",
            from_version=None,
            daemon_dir=daemon_dir,
            project_root=project,
        )
        assert _acked(daemon_dir, project, untracked, None, "3.65.0").verdict is (
            GateVerdict.PROCEED
        )

    def test_a_target_that_is_not_a_release_needs_the_owner(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        report = _acked(daemon_dir, project, untracked, "3.64.0", "0123abc")
        assert report.verdict is GateVerdict.NEEDS_APPROVAL

    def test_an_unknown_previous_version_still_lists_every_guide_up_to_the_target(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        """review4 follow-up: `_unknown_range_report` scans PRE tasks from
        earliest to target (proven above), but hardcoded ``guides=[]`` --
        dropping every informational guide document (including a staged,
        UNRELEASED one a guarded branch install exists to surface) whenever
        the range is unknown, with no way for the owner to see what they are
        approving. Symmetric with the findings scan: unknown FROM means show
        everything up to TO, not nothing.
        """
        _guide(upgrades, "v3.10.0-to-v3.11.0")
        report = _gate(daemon_dir, project, untracked, None, "3.65.0")
        assert any("v3.10.0-to-v3.11.0.md" in str(guide) for guide in report.guides), report.guides

    def test_the_header_says_why_every_guide_is_listed(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        """review4 n1: "cannot tell which guides" followed by a list of every
        guide read as a contradiction; the header says the list is complete
        because the starting version is unknown."""
        _guide(upgrades, "v3.10.0-to-v3.11.0")
        text = format_gate_report(_gate(daemon_dir, project, untracked, None, "3.65.0"))
        assert "so every upgrade guide up to v3.65.0 is listed" in text
        assert "cannot tell which upgrade guides" not in text


class TestUntrustedFrom:
    """Review2 BLOCKER 1: an untrusted FROM at or past the target is unknown.

    ``from_untrusted`` is what :func:`main` sets whenever ``from_version``
    did not come from a venv stamp naming a release -- in production, the
    ``HOOKS-DAEMON.md`` fallback. It must never by itself certify "nothing to
    install": that marker is an ordinary tracked file an agent edits
    routinely, unlike a venv stamp bound to a ``gated-install.json`` receipt.
    """

    def _untrusted(
        self, daemon_dir: Path, project: Path, untracked: Path, frm: str, to: str
    ) -> GateReport:
        return evaluate_gate(
            daemon_dir=daemon_dir,
            project_root=project,
            from_version=frm,
            to_version=to,
            include_unreleased=False,
            acknowledgement=None,
            untracked_dir=untracked,
            from_untrusted=True,
        )

    def test_equal_to_the_target_needs_the_owner(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        report = self._untrusted(daemon_dir, project, untracked, "4.0.0", "4.0.0")
        assert report.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        assert not report.already_installed
        assert report.escalations, "an unknown range must not sail through silently"

    def test_ahead_of_the_target_needs_the_owner_not_a_downgrade(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        report = self._untrusted(daemon_dir, project, untracked, "5.0.0", "4.0.0")
        assert report.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        assert not report.downgrade
        assert "downgrade" not in format_gate_report(report)

    def test_behind_the_target_is_unaffected(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        report = self._untrusted(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.verdict is GateVerdict.PROCEED

    def test_trusted_from_at_the_target_is_not_escalated_by_this_rule(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        """``from_untrusted`` defaults to False: a caller vouching for its own
        FROM (a real stamp, or a fixed test scenario) keeps deciding on the
        normal range logic, same as before this fix."""
        report = _gate(daemon_dir, project, untracked, "4.0.0", "4.0.0")
        assert report.verdict is GateVerdict.PROCEED


class TestInstalledVersion:
    """Review MAJOR 1: FROM is what is installed, never what is checked out."""

    def test_the_venv_stamp_wins(self, project: Path) -> None:
        _write(project / ".claude" / "HOOKS-DAEMON.md", "> Generated on 2026-09-01 (v3.60.0)\n")
        assert installed_version("v3.66.0+main.abc1234", project) == ("3.66.0", "venv stamp")

    def test_the_committed_marker_is_the_fallback(self, project: Path) -> None:
        _write(
            project / ".claude" / "HOOKS-DAEMON.md",
            "# x\n\n> Generated on 2026-09-01 (v3.60.0) by `generate-docs`.\n",
        )
        assert installed_version(None, project) == ("3.60.0", ".claude/HOOKS-DAEMON.md")
        assert installed_version("garbage", project) == ("3.60.0", ".claude/HOOKS-DAEMON.md")

    def test_neither_is_unknown(self, project: Path) -> None:
        assert installed_version("", project) == (None, "none")


class TestEscalation:
    def test_a_major_bump_needs_the_owner(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        report = _acked(daemon_dir, project, untracked, "3.66.0", "4.0.0")
        assert report.verdict is GateVerdict.NEEDS_APPROVAL
        assert any("MAJOR" in reason for reason in report.escalations)

    def test_the_stop_prints_an_approval_command_the_new_code_can_run(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        first = _gate(daemon_dir, project, untracked, "3.66.0", "4.0.0")
        report = evaluate_gate(
            daemon_dir=daemon_dir,
            project_root=project,
            from_version="3.66.0",
            to_version="4.0.0",
            include_unreleased=False,
            acknowledgement=first.digest,
            untracked_dir=untracked,
            target_ref="v4.0.0",
        )
        text = format_gate_report(report)
        assert "approve-upgrade 4.0.0 --from 3.66.0" in text
        assert f'git -C "{daemon_dir}" archive v4.0.0 src' in text
        assert 'upgrade_gate_standalone.py" approve' in text
        assert "terminal" in text
        # Fresh review D7: a bare `python3` is 3.9 on the hosts that need an override.
        assert f'"{sys.executable}" "$tmp/' in text
        assert 'python3 "$tmp/' not in text

    def test_a_crossed_breaking_manifest_needs_the_owner(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _write(upgrades / "config-changes" / "v3.65.0.yaml", 'version: "3.65.0"\nbreaking: true\n')
        report = _acked(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.verdict is GateVerdict.NEEDS_APPROVAL
        assert any("v3.65.0.yaml" in reason for reason in report.escalations)

    def test_a_critical_pre_task_with_hits_needs_the_owner(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _pre_task(
            upgrades,
            "v3.64.0-to-v3.65.0",
            "01-rename.md",
            severity="critical",
            pattern="plan-qa[^\\n]*--json",
        )
        report = _acked(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.verdict is GateVerdict.NEEDS_APPROVAL
        assert any("01-rename.md" in reason for reason in report.escalations)

    def test_a_critical_pre_task_without_hits_does_not_escalate(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _pre_task(
            upgrades, "v3.64.0-to-v3.65.0", "01-rename.md", severity="critical", pattern="absent"
        )
        report = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.escalations == []

    def test_a_bound_approval_lets_it_through_and_is_named_not_consumed(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        marker = _approve(untracked, daemon_dir, project, "3.66.0", "4.0.0")
        report = _acked(daemon_dir, project, untracked, "3.66.0", "v4.0.0")
        assert report.verdict is GateVerdict.PROCEED
        assert report.approval_used == marker
        assert marker.exists(), "consumed by the caller only once the upgrade completes"

    def test_an_approval_is_not_used_while_reading_is_unacknowledged(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        _approve(untracked, daemon_dir, project, "3.66.0", "4.0.0")
        report = _gate(daemon_dir, project, untracked, "3.66.0", "4.0.0")
        assert report.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        assert report.approval_used is None

    def test_a_touched_marker_is_not_an_approval(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        marker = OneShotApprovalStore(APPROVAL_SUBDIR).path(untracked, "4.0.0")
        marker.parent.mkdir(parents=True)
        marker.touch()
        report = _acked(daemon_dir, project, untracked, "3.66.0", "4.0.0")
        assert report.verdict is GateVerdict.NEEDS_APPROVAL
        assert "not written by approve-upgrade for this upgrade" in format_gate_report(report)

    @pytest.mark.parametrize(
        ("frm", "other_daemon"),
        [("3.65.0", False), ("3.66.0", True)],
        ids=["another-from", "another-install"],
    )
    def test_an_approval_for_another_upgrade_does_not_count(
        self,
        tmp_path: Path,
        daemon_dir: Path,
        project: Path,
        untracked: Path,
        frm: str,
        other_daemon: bool,
    ) -> None:
        write_approval(
            untracked,
            to_version="4.0.0",
            from_version=frm,
            daemon_dir=tmp_path / "elsewhere" if other_daemon else daemon_dir,
            project_root=project,
        )
        assert _acked(daemon_dir, project, untracked, "3.66.0", "4.0.0").verdict is (
            GateVerdict.NEEDS_APPROVAL
        )


class TestApprovalMarker:
    def test_the_marker_records_what_it_approves(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        marker = _approve(untracked, daemon_dir, project, "v3.66.0", "4.0")
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["to"] == "4.0.0"
        assert payload["from"] == "3.66.0"
        assert payload["daemon_dir"] == str(daemon_dir.resolve())
        assert payload["project_root"] == str(project.resolve())

    def test_check_distinguishes_absent_valid_and_invalid(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        kwargs = {
            "to_version": "4.0.0",
            "from_version": "3.66.0",
            "daemon_dir": daemon_dir,
            "project_root": project,
        }
        assert check_approval(untracked, **kwargs) is ApprovalState.ABSENT
        marker = _approve(untracked, daemon_dir, project, "3.66.0", "4.0.0")
        assert check_approval(untracked, **kwargs) is ApprovalState.VALID
        marker.write_text("4.0.0 approved\n", encoding="utf-8")
        assert check_approval(untracked, **kwargs) is ApprovalState.INVALID


class TestUnreadableApprovalMarker:
    """N323: a marker that exists but cannot be read is not a missing one."""

    @staticmethod
    def _state(daemon_dir: Path, project: Path, untracked: Path) -> ApprovalState:
        return check_approval(
            untracked,
            to_version="4.0.0",
            from_version="3.66.0",
            daemon_dir=daemon_dir,
            project_root=project,
        )

    @staticmethod
    def _refuse_reads(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            upgrade_gate_module,
            "read_text_or_reason",
            lambda path, **_: TextOrReason(reason="[Errno 13] Permission denied"),
        )

    def test_a_marker_the_read_refuses_is_unreadable_not_absent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        daemon_dir: Path,
        project: Path,
        untracked: Path,
    ) -> None:
        _approve(untracked, daemon_dir, project, "3.66.0", "4.0.0")
        self._refuse_reads(monkeypatch)
        assert self._state(daemon_dir, project, untracked) is ApprovalState.UNREADABLE

    def test_an_unreadable_marker_fails_closed_and_the_message_names_permissions(
        self,
        monkeypatch: pytest.MonkeyPatch,
        daemon_dir: Path,
        project: Path,
        untracked: Path,
    ) -> None:
        _approve(untracked, daemon_dir, project, "3.66.0", "4.0.0")
        self._refuse_reads(monkeypatch)
        report = _acked(daemon_dir, project, untracked, "3.66.0", "4.0.0")
        assert report.verdict is GateVerdict.NEEDS_APPROVAL
        assert report.approval_state is ApprovalState.UNREADABLE
        text = format_gate_report(report)
        assert "unreadable" in text
        assert "permissions" in text


class _FakeTty(io.StringIO):
    def __init__(self, text: str, *, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class TestRunApproval:
    """Review MAJOR 4: only a human at a terminal who types the phrase approves."""

    def _run(
        self, daemon_dir: Path, project: Path, untracked: Path, answer: str, *, tty: bool
    ) -> tuple[int, str]:
        out = io.StringIO()
        code = run_approval(
            project_root=project,
            daemon_dir=daemon_dir,
            from_version="3.66.0",
            to_version="4.0.0",
            untracked_dir=untracked,
            stdin=_FakeTty(answer, tty=tty),
            stdout=out,
        )
        return code, out.getvalue()

    def test_no_terminal_no_approval(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        code, out = self._run(
            daemon_dir, project, untracked, "approve upgrade from v3.66.0 to v4.0.0\n", tty=False
        )
        assert code != 0
        assert "terminal" in out
        assert not (untracked / APPROVAL_SUBDIR).exists()

    def test_the_wrong_phrase_is_refused(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        code, _out = self._run(daemon_dir, project, untracked, "yes\n", tty=True)
        assert code != 0
        assert not (untracked / APPROVAL_SUBDIR).exists()

    def test_the_phrase_naming_the_versions_records_a_bound_marker(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        code, out = self._run(
            daemon_dir, project, untracked, "approve upgrade from v3.66.0 to v4.0.0\n", tty=True
        )
        assert code == 0
        assert "approve upgrade from v3.66.0 to v4.0.0" in out
        assert (
            check_approval(
                untracked,
                to_version="4.0.0",
                from_version="3.66.0",
                daemon_dir=daemon_dir,
                project_root=project,
            )
            is ApprovalState.VALID
        )

    def test_an_unknown_installed_version_is_not_typed_as_vunknown(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        """Fresh review N4: the phrase asked a human to type `vunknown`."""
        phrase = "approve upgrade from an unknown version to v4.0.0"
        out = io.StringIO()
        code = run_approval(
            project_root=project,
            daemon_dir=daemon_dir,
            from_version=None,
            to_version="4.0.0",
            untracked_dir=untracked,
            stdin=_FakeTty(f"{phrase}\n", tty=True),
            stdout=out,
        )
        assert code == 0, out.getvalue()
        assert phrase in out.getvalue()
        assert "vunknown" not in out.getvalue()

    def test_approve_main_refuses_without_a_terminal(
        self,
        daemon_dir: Path,
        project: Path,
        untracked: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sys.stdin", _FakeTty("approve upgrade from v3.66.0 to v4.0.0\n", tty=False)
        )
        code = approve_main(
            [
                "--daemon-dir",
                str(daemon_dir),
                "--project-root",
                str(project),
                "--from",
                "3.66.0",
                "--to",
                "4.0.0",
                "--untracked-dir",
                str(untracked),
            ]
        )
        assert code != 0
        assert not (untracked / APPROVAL_SUBDIR).exists()


class TestBreakingManifests:
    def test_only_the_crossed_range_counts(self, upgrades: Path) -> None:
        for version in ("3.64.0", "3.65.0", "3.66.0"):
            _write(upgrades / "config-changes" / f"v{version}.yaml", "breaking: true\n")
        _write(upgrades / "config-changes" / "v3.65.1.yaml", "breaking: false\n")
        found = breaking_manifests(upgrades, "3.64.0", "3.65.1", include_unreleased=False)
        assert [path.name for path in found] == ["v3.65.0.yaml"]

    @pytest.mark.parametrize("spelling", ["True", "yes", "TRUE", "on", "true  # comment"])
    def test_every_yaml_spelling_of_true_counts(self, upgrades: Path, spelling: str) -> None:
        _write(upgrades / "config-changes" / "v3.65.0.yaml", f"breaking: {spelling}\n")
        assert breaking_manifests(upgrades, "3.64.0", "3.65.0", include_unreleased=False)

    def test_staged_manifests_count_on_a_branch_install_whatever_their_name(
        self, upgrades: Path
    ) -> None:
        _write(upgrades / "UNRELEASED" / "config-changes" / "v3.67.0.yaml", "breaking: true\n")
        assert breaking_manifests(upgrades, "3.66.0", "3.66.0", include_unreleased=False) == []
        found = breaking_manifests(upgrades, "3.66.0", "3.66.0", include_unreleased=True)
        assert [path.name for path in found] == ["v3.67.0.yaml"]


class TestTheRealTree:
    """Review MAJOR 3: the published manifests must not stop every v3.64 client."""

    def test_a_v3_64_client_upgrading_to_the_current_release_is_not_escalated(
        self, project: Path, untracked: Path
    ) -> None:
        from claude_code_hooks_daemon.version import __version__

        report = _acked(_REPO_UPGRADES_ROOT, project, untracked, "3.64.1", __version__)
        assert report.escalations == [], report.escalations
        assert report.verdict is GateVerdict.PROCEED


class TestApprovalKey:
    @pytest.mark.parametrize("raw", ["4.0.0", "v4.0.0", "4.0.0+main.abc1234", "v4.0"])
    def test_every_spelling_of_a_release_shares_one_key(self, raw: str) -> None:
        assert approval_key(raw) == "4.0.0"


class TestVerdictExitCodes:
    def test_each_verdict_has_its_own_exit_code(self) -> None:
        codes = {verdict.exit_code for verdict in GateVerdict}
        assert len(codes) == len(GateVerdict)
        assert GateVerdict.PROCEED.exit_code == 0
        assert 1 not in codes
        assert 2 not in codes


class TestMain:
    def _argv(self, daemon_dir: Path, project: Path, untracked: Path, *extra: str) -> list[str]:
        return [
            "--daemon-dir",
            str(daemon_dir),
            "--project-root",
            str(project),
            "--untracked-dir",
            str(untracked),
            *extra,
        ]

    def test_the_exit_code_is_the_verdict(
        self,
        daemon_dir: Path,
        upgrades: Path,
        project: Path,
        untracked: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _guide(upgrades, "v3.64.0-to-v3.65.0")
        argv = self._argv(
            daemon_dir, project, untracked, "--installed-stamp", "v3.64.0", "--to", "3.65.0"
        )
        assert main(argv) == GateVerdict.NEEDS_ACKNOWLEDGEMENT.exit_code
        err = capsys.readouterr().err
        assert "REQUIRED READING" in err
        digest = err.split("--skip-reading-confirmation=", 1)[1].split()[0]
        assert main([*argv, "--acknowledgement", digest]) == 0

    def test_a_repair_route_stamp_claiming_the_target_is_not_stated_as_settled(
        self,
        daemon_dir: Path,
        project: Path,
        untracked: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """review2 N1: the stamp line must not read as fact when it is about
        to be checked against (and can be rejected by) the gated-install
        record -- the repair-route case printed 'Installed version: 4.0.0
        (from the venv stamp)' immediately followed by 'an unknown version'.
        """
        argv = self._argv(
            daemon_dir,
            project,
            untracked,
            "--installed-stamp",
            "v4.0.0",
            "--to",
            "4.0.0",
            "--target-stamp",
            "v4.0.0",
        )
        main(argv)
        err = capsys.readouterr().err
        assert "checked against the gated-install record next" in err

    def test_no_source_is_said_in_words(
        self,
        daemon_dir: Path,
        project: Path,
        untracked: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """review4 n2: with neither a venv stamp nor HOOKS-DAEMON.md the line
        read 'Installed version: unknown (from the none)'."""
        main(self._argv(daemon_dir, project, untracked, "--to", "3.65.0"))
        err = capsys.readouterr().err
        assert "from the none" not in err
        assert (
            "Installed version: unknown (no venv stamp names it, and "
            ".claude/HOOKS-DAEMON.md carries no release)" in err
        )

    def test_from_comes_from_the_install_not_the_checkout(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _guide(upgrades, "v3.64.0-to-v3.65.0")
        _write(project / ".claude" / "HOOKS-DAEMON.md", "> Generated on 2026-09-01 (v3.64.0)\n")
        argv = self._argv(daemon_dir, project, untracked, "--to", "3.65.0")
        assert main(argv) == GateVerdict.NEEDS_ACKNOWLEDGEMENT.exit_code

    def test_a_doc_marker_equal_to_the_target_does_not_manufacture_already_installed(
        self,
        daemon_dir: Path,
        project: Path,
        untracked: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """review2 BLOCKER 1: no venv stamp, doc marker says the target itself.

        A missing stamp plus an edited ``HOOKS-DAEMON.md`` must not read as
        "already installed": that marker is an ordinary tracked file an agent
        edits routinely, and it names no receipt a real gated install would
        have left. The range must be treated as unknown and sent to the
        owner, never PROCEED.
        """
        _write(project / ".claude" / "HOOKS-DAEMON.md", "> Generated on 2026-09-01 (v4.0.0)\n")
        argv = self._argv(
            daemon_dir, project, untracked, "--to", "4.0.0", "--target-stamp", "v4.0.0"
        )
        first = main(argv)
        assert first == GateVerdict.NEEDS_ACKNOWLEDGEMENT.exit_code
        err = capsys.readouterr().err
        assert "already installed" not in err
        digest = err.split("--skip-reading-confirmation=", 1)[1].split()[0]
        assert main([*argv, "--acknowledgement", digest]) == GateVerdict.NEEDS_APPROVAL.exit_code
        assert (
            gated_install_stamp(untracked, daemon_dir=daemon_dir, project_root=project) is None
        ), "a range the gate refused to read must record no install"

    def test_a_doc_marker_ahead_of_the_target_is_not_a_silent_downgrade(
        self,
        daemon_dir: Path,
        project: Path,
        untracked: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A tampered marker naming a version PAST the target must also escalate."""
        _write(project / ".claude" / "HOOKS-DAEMON.md", "> Generated on 2026-09-01 (v5.0.0)\n")
        argv = self._argv(
            daemon_dir, project, untracked, "--to", "4.0.0", "--target-stamp", "v4.0.0"
        )
        first = main(argv)
        assert first == GateVerdict.NEEDS_ACKNOWLEDGEMENT.exit_code
        err = capsys.readouterr().err
        assert "downgrade" not in err
        digest = err.split("--skip-reading-confirmation=", 1)[1].split()[0]
        assert main([*argv, "--acknowledgement", digest]) == GateVerdict.NEEDS_APPROVAL.exit_code

    def test_an_approval_used_is_written_to_the_verdict_file_for_the_caller_to_consume(
        self,
        tmp_path: Path,
        daemon_dir: Path,
        project: Path,
        untracked: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        marker = _approve(untracked, daemon_dir, project, "3.66.0", "4.0.0")
        verdict_file = tmp_path / "verdict"
        argv = self._argv(
            daemon_dir,
            project,
            untracked,
            "--installed-stamp",
            "v3.66.0",
            "--to",
            "4.0.0",
            "--verdict-file",
            str(verdict_file),
            "--nonce",
            "n0nce",
        )
        main(argv)
        digest = capsys.readouterr().err.split("--skip-reading-confirmation=", 1)[1].split()[0]
        verdict_file.unlink()
        assert main([*argv, "--acknowledgement", digest]) == 0
        assert f"approval-marker={marker}" in verdict_file.read_text().splitlines()

    def test_a_verdict_file_already_there_is_never_reused(
        self, tmp_path: Path, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        planted = tmp_path / "verdict"
        planted.write_text("nonce=n0nce\nverdict=proceed\n")
        argv = self._argv(
            daemon_dir,
            project,
            untracked,
            "--installed-stamp",
            "v3.66.0",
            "--to",
            "4.0.0",
            "--verdict-file",
            str(planted),
            "--nonce",
            "n0nce",
        )
        with pytest.raises(FileExistsError):
            main(argv)

    @pytest.mark.parametrize(
        ("stamp", "expected"),
        [("v3.66.0", "verdict=proceed"), ("v3.64.0", "verdict=needs-acknowledgement")],
    )
    def test_the_verdict_goes_to_the_callers_file_bound_to_its_nonce(
        self,
        tmp_path: Path,
        daemon_dir: Path,
        upgrades: Path,
        project: Path,
        untracked: Path,
        capsys: pytest.CaptureFixture[str],
        stamp: str,
        expected: str,
    ) -> None:
        """Fresh review BLOCKER 1: a stdout line is what any wrapper can print."""
        _guide(upgrades, "v3.64.0-to-v3.65.0")
        verdict_file = tmp_path / "verdict"
        main(
            self._argv(
                daemon_dir,
                project,
                untracked,
                "--installed-stamp",
                stamp,
                "--to",
                "3.66.0",
                "--verdict-file",
                str(verdict_file),
                "--nonce",
                "n0nce",
            )
        )
        lines = verdict_file.read_text().splitlines()
        assert lines[0] == "nonce=n0nce"
        assert expected in lines
        assert "verdict=" not in capsys.readouterr().out
        assert verdict_file.stat().st_mode & 0o077 == 0, "only the gate's user may read it"

    def test_include_unreleased_is_an_explicit_flag(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _write(upgrades / "UNRELEASED" / "release-notes" / "01-note.md", "# note\n")
        argv = self._argv(
            daemon_dir, project, untracked, "--installed-stamp", "v3.66.0", "--to", "3.66.0"
        )
        assert main(argv) == 0
        assert main([*argv, "--include-unreleased"]) == GateVerdict.NEEDS_ACKNOWLEDGEMENT.exit_code


class TestRecordInstall:
    """N327: a fresh install must leave the same receipt a gated upgrade leaves.

    Without it the first idempotent re-run of the version a project was freshly
    installed at finds a venv stamp naming the target and no receipt, and the
    gate sends the project to its owner with every guide since v2.0.
    """

    def _argv(self, daemon_dir: Path, project: Path, untracked: Path, stamp: str) -> list[str]:
        return [
            "--daemon-dir",
            str(daemon_dir),
            "--project-root",
            str(project),
            "--untracked-dir",
            str(untracked),
            "--stamp",
            stamp,
        ]

    def test_it_writes_the_receipt_a_gated_upgrade_would_write(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        assert record_install_main(self._argv(daemon_dir, project, untracked, "v3.68.0")) == 0
        assert (
            gated_install_stamp(untracked, daemon_dir=daemon_dir, project_root=project) == "v3.68.0"
        )

    def test_a_rerun_at_the_installed_version_then_proceeds_without_the_owner(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        record_install_main(self._argv(daemon_dir, project, untracked, "v3.68.0"))
        report = _gate(
            daemon_dir,
            project,
            untracked,
            "3.68.0",
            "3.68.0",
            installed_stamp="v3.68.0",
            target_stamp="v3.68.0",
        )
        assert report.verdict is GateVerdict.PROCEED
        assert report.already_installed

    def test_an_install_with_no_receipt_still_goes_to_the_owner(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        report = _gate(
            daemon_dir,
            project,
            untracked,
            "3.68.0",
            "3.68.0",
            installed_stamp="v3.68.0",
            target_stamp="v3.68.0",
        )
        assert report.verdict is not GateVerdict.PROCEED
        assert not report.already_installed

    def test_an_empty_stamp_is_refused_and_writes_nothing(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        with pytest.raises(SystemExit):
            record_install_main(self._argv(daemon_dir, project, untracked, ""))
        assert gated_install_stamp(untracked, daemon_dir=daemon_dir, project_root=project) is None
