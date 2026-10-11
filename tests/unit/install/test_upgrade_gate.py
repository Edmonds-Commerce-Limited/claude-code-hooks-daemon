"""The pre-deploy upgrade gate (Plan 00376 Phase 3, review-00376 fixes).

The gate decides, once the daemon checkout sits on the target and before
anything is deployed, whether the upgrade may go on. It never asks whether a
terminal is attached:

- the FROM side is what is INSTALLED (the venv stamp, else the project's
  ``HOOKS-DAEMON.md`` marker), never the checkout, which may already be on the
  target (review MAJOR 1); with neither, the range is unknown;
- a caller with something to read stops until it passes
  ``--skip-reading-confirmation=<digest>``, the digest of the listing it was
  shown (review MINOR 6);
- a change that breaks the project (a MAJOR bump, a breaking manifest, a
  critical task, an unreadable installed version) is listed prominently in
  that same reading and stops nothing further: there is no owner approval and
  no second exit code (Plan 00503);
- a large jump prints advice to upgrade in phases, and never changes the exit.
"""

from __future__ import annotations

import errno
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.upgrade_gate import (
    GATED_INSTALL_SUBDIR,
    GateReport,
    GateVerdict,
    breaking_manifests,
    evaluate_gate,
    format_gate_report,
    gated_install_stamp,
    installed_version,
    main,
    phasing_advice,
    record_gated_install,
    record_install_main,
    release_key,
)

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
        assert acknowledged.verdict is GateVerdict.PROCEED

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
        path = untracked / GATED_INSTALL_SUBDIR / "gated-install.json"
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
        path = untracked / GATED_INSTALL_SUBDIR / "gated-install.json"
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
    """Review MINOR 2 / MAJOR 1: an unreadable range fails closed to the reading."""

    def test_an_unknown_previous_version_needs_the_reading_confirmed(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        stopped = _gate(daemon_dir, project, untracked, None, "3.65.0")
        assert stopped.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        assert "installed version is unknown" in format_gate_report(stopped)
        acknowledged = _acked(daemon_dir, project, untracked, None, "3.65.0")
        assert acknowledged.verdict is GateVerdict.PROCEED

    def test_an_unknown_previous_version_still_runs_every_detection_up_to_the_target(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _pre_task(upgrades, "v3.10.0-to-v3.11.0", "01-old.md", pattern="plan-qa[^\\n]*--json")
        text = format_gate_report(_gate(daemon_dir, project, untracked, None, "3.65.0"))
        assert "01-old.md" in text
        assert "tools/qa.sh:2" in text

    def test_a_target_that_is_not_a_release_lists_why_and_proceeds_once_confirmed(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        unconfirmed = _gate(daemon_dir, project, untracked, "3.64.0", "0123abc")
        assert unconfirmed.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        assert "is not a release version" in format_gate_report(unconfirmed)
        report = _acked(daemon_dir, project, untracked, "3.64.0", "0123abc")
        assert report.verdict is GateVerdict.PROCEED

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
    """What used to need the owner is read prominently and stops nothing more."""

    def test_a_major_bump_is_listed_and_proceeds_once_confirmed(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        stopped = _gate(daemon_dir, project, untracked, "3.66.0", "4.0.0")
        assert stopped.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        assert any("MAJOR" in reason for reason in stopped.escalations)
        assert "MAJOR version change" in format_gate_report(stopped)
        report = _acked(daemon_dir, project, untracked, "3.66.0", "4.0.0")
        assert report.verdict is GateVerdict.PROCEED
        assert report.verdict.exit_code == 0

    def test_the_breaking_reasons_come_before_the_guides_in_the_listing(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _guide(upgrades, "v3.66.0-to-v4.0.0")
        text = format_gate_report(_gate(daemon_dir, project, untracked, "3.66.0", "4.0.0"))
        assert "MAJOR version change" in text
        assert text.index("MAJOR version change") < text.index("v3.66.0-to-v4.0.0.md")

    def test_no_stop_names_an_owner_or_an_approval_command(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        report = _gate(daemon_dir, project, untracked, "3.66.0", "4.0.0")
        text = format_gate_report(report)
        assert "approve-upgrade" not in text
        assert "owner" not in text.lower()
        assert f"--skip-reading-confirmation={report.digest}" in text

    def test_a_crossed_breaking_manifest_is_listed_and_proceeds_once_confirmed(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _write(upgrades / "config-changes" / "v3.65.0.yaml", 'version: "3.65.0"\nbreaking: true\n')
        report = _acked(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.verdict is GateVerdict.PROCEED
        assert any("v3.65.0.yaml" in reason for reason in report.escalations)

    def test_a_critical_pre_task_with_hits_is_listed_and_proceeds_once_confirmed(
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
        assert report.verdict is GateVerdict.PROCEED
        assert any("01-rename.md" in reason for reason in report.escalations)

    def test_a_critical_pre_task_without_hits_does_not_escalate(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _pre_task(
            upgrades, "v3.64.0-to-v3.65.0", "01-rename.md", severity="critical", pattern="absent"
        )
        report = _gate(daemon_dir, project, untracked, "3.64.0", "3.65.0")
        assert report.escalations == []

    def test_a_stale_approval_marker_is_ignored(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        """A project that ran the old approval route leaves a marker behind."""
        marker = untracked / "upgrade-approvals" / "4.0.0.approved"
        marker.parent.mkdir(parents=True)
        marker.write_text("{}\n", encoding="utf-8")
        report = _acked(daemon_dir, project, untracked, "3.66.0", "4.0.0")
        assert report.verdict is GateVerdict.PROCEED
        assert marker.exists(), "the gate neither reads nor removes it"


class TestPhasingAdvice:
    """A large jump gets advice to go through an intermediate release; never a stop."""

    def _advice(self, upgrades: Path, frm: str, to: str) -> list[str]:
        return phasing_advice(upgrades, frm, to)

    def test_a_major_boundary_names_the_last_release_of_the_current_major(
        self, upgrades: Path
    ) -> None:
        _guide(upgrades, "v3.66.0-to-v3.67.0")
        _guide(upgrades, "v3.67.0-to-v3.68.0")
        _guide(upgrades, "v3.68.0-to-v4.0.0")
        advice = self._advice(upgrades, "3.66.0", "4.0.0")
        assert len(advice) == 1
        assert "in phases" in advice[0]
        assert "v3.68.0" in advice[0]
        assert "v4.0.0" in advice[0]

    def test_a_major_boundary_without_a_known_release_still_advises(self, upgrades: Path) -> None:
        advice = self._advice(upgrades, "3.66.0", "4.0.0")
        assert len(advice) == 1
        assert "last v3 release" in advice[0]

    def test_more_than_ten_minor_releases_names_an_intermediate_release(
        self, upgrades: Path
    ) -> None:
        _guide(upgrades, "v3.55.0-to-v3.58.0")
        _guide(upgrades, "v3.58.0-to-v3.60.0")
        _guide(upgrades, "v3.60.0-to-v3.62.0")
        advice = self._advice(upgrades, "3.50.0", "3.62.0")
        assert len(advice) == 1
        assert "in phases" in advice[0]
        assert "v3.60.0" in advice[0]

    def test_ten_minor_releases_is_not_a_large_jump(self, upgrades: Path) -> None:
        assert self._advice(upgrades, "3.50.0", "3.60.0") == []

    def test_a_patch_or_small_upgrade_has_no_advice(self, upgrades: Path) -> None:
        assert self._advice(upgrades, "3.66.0", "3.66.5") == []
        assert self._advice(upgrades, "3.66.0", "3.68.0") == []

    def test_a_downgrade_has_no_advice(self, upgrades: Path) -> None:
        assert self._advice(upgrades, "4.0.0", "3.50.0") == []

    def test_the_advice_is_printed_and_changes_neither_verdict_nor_exit_code(
        self, daemon_dir: Path, upgrades: Path, project: Path, untracked: Path
    ) -> None:
        _guide(upgrades, "v3.66.0-to-v3.67.0")
        stopped = _gate(daemon_dir, project, untracked, "3.66.0", "4.0.0")
        assert stopped.verdict is GateVerdict.NEEDS_ACKNOWLEDGEMENT
        assert stopped.advisories
        assert "in phases" in format_gate_report(stopped)
        assert _acked(daemon_dir, project, untracked, "3.66.0", "4.0.0").verdict is (
            GateVerdict.PROCEED
        )

    def test_the_advice_does_not_change_the_digest(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        large = _gate(daemon_dir, project, untracked, "3.66.0", "4.0.0")
        assert large.advisories
        again = _gate(daemon_dir, project, untracked, "3.66.0", "4.0.0")
        assert large.digest == again.digest

    def test_the_advice_is_printed_even_when_there_is_nothing_to_read(
        self, daemon_dir: Path, project: Path, untracked: Path
    ) -> None:
        report = _gate(daemon_dir, project, untracked, "3.40.0", "3.62.0")
        assert report.verdict is GateVerdict.PROCEED
        assert "in phases" in format_gate_report(report)


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


class TestReleaseKey:
    @pytest.mark.parametrize("raw", ["4.0.0", "v4.0.0", "4.0.0+main.abc1234", "v4.0"])
    def test_every_spelling_of_a_release_shares_one_key(self, raw: str) -> None:
        assert release_key(raw) == "4.0.0"


class TestVerdictExitCodes:
    def test_each_verdict_has_its_own_exit_code(self) -> None:
        codes = {verdict.exit_code for verdict in GateVerdict}
        assert len(codes) == len(GateVerdict)
        assert GateVerdict.PROCEED.exit_code == 0
        assert 1 not in codes
        assert 2 not in codes

    def test_there_is_no_owner_approval_verdict_or_exit_four(self) -> None:
        assert {verdict.name for verdict in GateVerdict} == {"PROCEED", "NEEDS_ACKNOWLEDGEMENT"}
        assert {verdict.exit_code for verdict in GateVerdict} == {0, 3}


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
        assert (
            gated_install_stamp(untracked, daemon_dir=daemon_dir, project_root=project) is None
        ), "a range the gate stopped on must record no install"
        assert main([*argv, "--acknowledgement", digest]) == 0
        assert (
            gated_install_stamp(untracked, daemon_dir=daemon_dir, project_root=project) == "v4.0.0"
        ), "a confirmed upgrade is recorded like any other the gate lets through"

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
        assert main([*argv, "--acknowledgement", digest]) == 0

    def test_a_major_upgrade_has_two_outcomes_only_stop_for_reading_or_proceed(
        self,
        tmp_path: Path,
        daemon_dir: Path,
        project: Path,
        untracked: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
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
        assert main(argv) == GateVerdict.NEEDS_ACKNOWLEDGEMENT.exit_code
        digest = capsys.readouterr().err.split("--skip-reading-confirmation=", 1)[1].split()[0]
        verdict_file.unlink()
        assert main([*argv, "--acknowledgement", digest]) == 0
        assert verdict_file.read_text().splitlines() == ["nonce=n0nce", "verdict=proceed"]

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
