"""Tests for :mod:`claude_code_hooks_daemon.daemon.permission_audit` (Plan 00239).

This is the BATCH half of the umask fix. Changing the daemon's umask governs
what it creates from now on and retro-fixes nothing, so every daemon already
deployed keeps its world-writable files until something looks at them. A
write-time guard structurally cannot see what is already on disk — hence a check
that runs against an existing install.

The rule is deliberately narrow: group-or-other **writable**, symlinks skipped,
venv trees skipped. Each exclusion is here because it was measured as a false
positive on a real install, not anticipated:

* symlinks are always ``lrwxrwxrwx`` — the mode belongs to the target, and a
  venv's ``bin/python`` and ``lib64`` are symlinks;
* a venv is a package manager's business, and uv leaves a ``0666`` ``.lock``
  inside one;
* the daemon socket is deliberately ``0660`` (explicit post-bind chmod).

Flagging other-READABLE too was considered and rejected: nothing the fixed daemon
creates is other-readable, while a venv tree is full of legitimate ``0644``, so
the rule would be mostly noise. Writable is the unambiguous bug shape.
"""

from __future__ import annotations

import stat
from pathlib import Path

from claude_code_hooks_daemon.daemon.permission_audit import (
    audit_untracked_permissions,
    tighten_permissions,
)


def _make(path: Path, mode: int) -> Path:
    """Create a file with an explicit mode, defeating the ambient umask."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    path.chmod(mode)
    return path


class TestAuditUntrackedPermissions:
    """What the audit flags, and what it deliberately does not."""

    def test_group_writable_file_is_flagged(self, tmp_path: Path) -> None:
        target = _make(tmp_path / "verdicts.jsonl", 0o660)

        findings = audit_untracked_permissions(tmp_path)

        assert [f.path for f in findings] == [target]

    def test_world_writable_file_is_flagged(self, tmp_path: Path) -> None:
        target = _make(tmp_path / "stop-events.jsonl", 0o666)

        findings = audit_untracked_permissions(tmp_path)

        assert [f.path for f in findings] == [target]
        assert findings[0].mode == 0o666

    def test_world_writable_directory_is_flagged(self, tmp_path: Path) -> None:
        target = tmp_path / "payload-capture"
        target.mkdir()
        target.chmod(0o777)

        findings = audit_untracked_permissions(tmp_path)

        assert [f.path for f in findings] == [target]

    def test_owner_only_artefacts_are_clean(self, tmp_path: Path) -> None:
        _make(tmp_path / "verdicts.jsonl", 0o600)
        (tmp_path / "thread-registry").mkdir()
        (tmp_path / "thread-registry").chmod(0o700)

        assert audit_untracked_permissions(tmp_path) == []

    def test_other_readable_but_not_writable_is_not_flagged(self, tmp_path: Path) -> None:
        """0644 is not the bug shape — see the module docstring."""
        _make(tmp_path / "notes.txt", 0o644)

        assert audit_untracked_permissions(tmp_path) == []

    def test_symlinks_are_skipped(self, tmp_path: Path) -> None:
        """A symlink is always lrwxrwxrwx; its mode says nothing about the target."""
        target = _make(tmp_path / "real.json", 0o600)
        (tmp_path / "link.json").symlink_to(target)

        assert audit_untracked_permissions(tmp_path) == []

    def test_venv_trees_are_skipped(self, tmp_path: Path) -> None:
        """uv leaves a 0666 .lock inside a venv; that is not the daemon's file."""
        _make(tmp_path / "venv-workspace-py311-abc12345" / ".lock", 0o666)

        assert audit_untracked_permissions(tmp_path) == []

    def test_exempt_paths_are_skipped(self, tmp_path: Path) -> None:
        """The socket is deliberately 0660 and must not be reported."""
        socket_path = _make(tmp_path / "daemon-host.sock", 0o660)

        assert audit_untracked_permissions(tmp_path, exempt=[socket_path]) == []

    def test_missing_directory_is_not_an_error(self, tmp_path: Path) -> None:
        """A daemon that has never run has no untracked tree yet."""
        assert audit_untracked_permissions(tmp_path / "absent") == []

    def test_findings_are_sorted_for_stable_output(self, tmp_path: Path) -> None:
        _make(tmp_path / "b.jsonl", 0o666)
        _make(tmp_path / "a.jsonl", 0o666)

        findings = audit_untracked_permissions(tmp_path)

        assert [f.path.name for f in findings] == ["a.jsonl", "b.jsonl"]


class TestTightenPermissions:
    """The opt-in remediation half."""

    def test_tighten_strips_group_and_other_bits(self, tmp_path: Path) -> None:
        target = _make(tmp_path / "verdicts.jsonl", 0o666)

        tighten_permissions(audit_untracked_permissions(tmp_path))

        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_tighten_preserves_owner_execute_on_directories(self, tmp_path: Path) -> None:
        """A directory must stay traversable by its owner, or it is bricked."""
        target = tmp_path / "payload-capture"
        target.mkdir()
        target.chmod(0o777)

        tighten_permissions(audit_untracked_permissions(tmp_path))

        assert stat.S_IMODE(target.stat().st_mode) == 0o700

    def test_tighten_reports_what_it_changed(self, tmp_path: Path) -> None:
        _make(tmp_path / "verdicts.jsonl", 0o666)

        changed = tighten_permissions(audit_untracked_permissions(tmp_path))

        assert [p.name for p in changed] == ["verdicts.jsonl"]

    def test_tighten_leaves_a_clean_tree_alone(self, tmp_path: Path) -> None:
        _make(tmp_path / "verdicts.jsonl", 0o600)

        assert tighten_permissions(audit_untracked_permissions(tmp_path)) == []

    def test_audit_is_clean_after_tightening(self, tmp_path: Path) -> None:
        """The remediation must actually satisfy the check that prompted it."""
        _make(tmp_path / "verdicts.jsonl", 0o666)
        (tmp_path / "payload-capture").mkdir()
        (tmp_path / "payload-capture").chmod(0o777)

        tighten_permissions(audit_untracked_permissions(tmp_path))

        assert audit_untracked_permissions(tmp_path) == []
