"""Each protected source seeded as a link is audited (Plan 00613 Task 2.2).

A link to a protected file is a read route to its content, so every one the
seeding executor creates appends one JSON line to a daemon-owned log under the
MAIN checkout's daemon ``untracked/`` directory (DESIGN section 7, reduced to
the seeding executor). The line records where and why, never the content, a
size or a digest.

Decisions pinned here (journalled with the plan):

- The protected set is read at PLACEMENT, only for links actually placed, so
  validation of a link-only config still never reads it (Task 2.1's pin).
- An unreadable protected set does not refuse a link (link mode behaves as
  before); every placed link is recorded as unclassified instead of none.
- A linked directory is judged on every path reachable through it; a walk that
  cannot complete records the link as unclassified.
- The line is written BEFORE the link; a log that cannot be appended to means
  the link is not created and seeding raises, so no unaudited protected link
  exists. Entries placed earlier stay placed.

Protected names are assembled from pieces so this file does not itself name a
protected path to the secret guard.
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.worktree_seed import (
    SEED_MODE_COPY,
    SEED_MODE_SYMLINK,
    SeedEntry,
)
from claude_code_hooks_daemon.daemon.install_layout import get_untracked_dir
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.worktree_seeding import (
    SEED_LINK_AUDIT_FILENAME,
    LinkAudit,
    WorktreeSeedError,
    seed_link_audit_path,
    seed_worktree,
)

VAULT = "." + "vault" + "-pass"
ED_KEY = "id_" + "ed25519"
_SECRET_CONTENT = "do-not-copy-me\n"

#: The exact key set of one audit line: DESIGN section 7, nothing more.
_AUDIT_KEYS = {
    "at",
    "verb",
    "outcome",
    "check",
    "worktree",
    "path",
    "pattern",
    "unclassified_reason",
    "session_id",
}


def _defaults() -> tuple[str, ...]:
    return sfm.DEFAULT_PROTECTED_PATTERNS


def _unreadable() -> tuple[str, ...]:
    raise sfm.ProtectedSetUnreadable("the test's protected set cannot be read")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A main checkout holding one protected file and one ordinary file."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / VAULT).write_text(_SECRET_CONTENT, encoding="utf-8")
    (project / ".env.local").write_text("PLAIN=1\n", encoding="utf-8")
    return project


@pytest.fixture
def worktree(root: Path) -> Path:
    path = root / ".claude" / "worktrees" / "alpha-1234abcd"
    path.mkdir(parents=True)
    return path


def _audit(root: Path, loader: Any = _defaults, session_id: str | None = "sess-1") -> LinkAudit:
    return LinkAudit(
        log_path=seed_link_audit_path(root), protected_patterns=loader, session_id=session_id
    )


def _lines(root: Path) -> list[dict[str, Any]]:
    path = seed_link_audit_path(root)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class TestTheLogLocation:
    def test_it_is_under_the_main_checkouts_daemon_untracked_dir(self, root: Path) -> None:
        assert seed_link_audit_path(root) == get_untracked_dir(root) / SEED_LINK_AUDIT_FILENAME

    def test_its_name_is_a_jsonl_file(self) -> None:
        assert SEED_LINK_AUDIT_FILENAME.endswith(".jsonl")


class TestAProtectedLinkIsAudited:
    def test_one_line_is_appended(self, root: Path, worktree: Path) -> None:
        seed_worktree(
            root, worktree, [SeedEntry(path=VAULT, mode=SEED_MODE_SYMLINK)], audit=_audit(root)
        )
        lines = _lines(root)
        assert len(lines) == 1
        line = lines[0]
        assert set(line) == _AUDIT_KEYS
        assert line["verb"] == "worktree-seed"
        assert line["outcome"] == "linked"
        assert line["check"] == "secret_file_guard"
        assert line["worktree"] == str(worktree)
        assert line["path"] == VAULT
        assert line["pattern"] in sfm.DEFAULT_PROTECTED_PATTERNS
        assert line["unclassified_reason"] is None
        assert line["session_id"] == "sess-1"
        assert line["at"].endswith("Z")

    def test_the_line_never_carries_content_size_or_digest(
        self, root: Path, worktree: Path
    ) -> None:
        seed_worktree(
            root, worktree, [SeedEntry(path=VAULT, mode=SEED_MODE_SYMLINK)], audit=_audit(root)
        )
        text = seed_link_audit_path(root).read_text(encoding="utf-8")
        assert _SECRET_CONTENT.strip() not in text
        # No numeric field exists at all, so no size can be carried.
        assert not any(
            isinstance(value, int | float) for value in _lines(root)[0].values()
        )

    def test_the_protected_file_is_never_opened(self, root: Path, worktree: Path) -> None:
        protected = str((root / VAULT).resolve())
        real_open = builtins.open

        def guarded_open(file: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(file, str | Path) and str(Path(file).resolve()) == protected:
                raise AssertionError("the protected file was opened")
            return real_open(file, *args, **kwargs)

        with patch.object(builtins, "open", guarded_open):
            seed_worktree(
                root,
                worktree,
                [SeedEntry(path=VAULT, mode=SEED_MODE_SYMLINK)],
                audit=_audit(root),
            )
        assert len(_lines(root)) == 1

    def test_a_missing_session_id_is_recorded_as_null(self, root: Path, worktree: Path) -> None:
        seed_worktree(
            root,
            worktree,
            [SeedEntry(path=VAULT, mode=SEED_MODE_SYMLINK)],
            audit=_audit(root, session_id=None),
        )
        assert _lines(root)[0]["session_id"] is None

    def test_each_protected_link_gets_its_own_line_and_lines_accumulate(
        self, root: Path, tmp_path: Path
    ) -> None:
        (root / ED_KEY).write_text(_SECRET_CONTENT, encoding="utf-8")
        entries = [
            SeedEntry(path=VAULT, mode=SEED_MODE_SYMLINK),
            SeedEntry(path=ED_KEY, mode=SEED_MODE_SYMLINK),
        ]
        first = tmp_path / "wt1"
        second = tmp_path / "wt2"
        first.mkdir()
        second.mkdir()
        seed_worktree(root, first, entries, audit=_audit(root))
        seed_worktree(root, second, entries, audit=_audit(root))
        assert [(line["worktree"], line["path"]) for line in _lines(root)] == [
            (str(first), VAULT),
            (str(first), ED_KEY),
            (str(second), VAULT),
            (str(second), ED_KEY),
        ]

    def test_an_unprotected_name_linking_to_a_protected_file_is_audited(
        self, root: Path, worktree: Path
    ) -> None:
        (root / "innocent.txt").symlink_to(VAULT)
        seed_worktree(
            root,
            worktree,
            [SeedEntry(path="innocent.txt", mode=SEED_MODE_SYMLINK)],
            audit=_audit(root),
        )
        assert [line["path"] for line in _lines(root)] == ["innocent.txt"]

    def test_a_linked_directory_holding_a_protected_file_is_audited(
        self, root: Path, worktree: Path
    ) -> None:
        (root / "local").mkdir()
        (root / "local" / ED_KEY).write_text(_SECRET_CONTENT, encoding="utf-8")
        seed_worktree(
            root, worktree, [SeedEntry(path="local", mode=SEED_MODE_SYMLINK)], audit=_audit(root)
        )
        lines = _lines(root)
        assert [line["path"] for line in lines] == ["local"]
        assert lines[0]["outcome"] == "linked"
        assert ED_KEY not in json.dumps(lines[0])

    def test_a_project_anchored_glob_is_judged_at_the_seeding_root(
        self, root: Path, worktree: Path
    ) -> None:
        (root / "config").mkdir()
        (root / "config" / "prod.creds").write_text(_SECRET_CONTENT, encoding="utf-8")
        seed_worktree(
            root,
            worktree,
            [SeedEntry(path="config/prod.creds", mode=SEED_MODE_SYMLINK)],
            audit=_audit(root, lambda: ("/config/prod.creds",)),
        )
        assert _lines(root)[0]["pattern"] == "/config/prod.creds"


class TestWhatIsNotAudited:
    def test_an_unprotected_link_writes_no_line(self, root: Path, worktree: Path) -> None:
        seed_worktree(
            root,
            worktree,
            [SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)],
            audit=_audit(root),
        )
        assert not seed_link_audit_path(root).exists()

    def test_a_copy_writes_no_line(self, root: Path, worktree: Path) -> None:
        seed_worktree(
            root, worktree, [SeedEntry(path=".env.local", mode=SEED_MODE_COPY)], audit=_audit(root)
        )
        assert not seed_link_audit_path(root).exists()

    def test_a_link_skipped_because_its_destination_exists_writes_no_line(
        self, root: Path, worktree: Path
    ) -> None:
        (worktree / VAULT).write_text("already here\n", encoding="utf-8")
        seed_worktree(
            root, worktree, [SeedEntry(path=VAULT, mode=SEED_MODE_SYMLINK)], audit=_audit(root)
        )
        assert _lines(root) == []

    def test_an_absent_optional_link_writes_no_line(self, root: Path, worktree: Path) -> None:
        seed_worktree(
            root,
            worktree,
            [SeedEntry(path=ED_KEY, mode=SEED_MODE_SYMLINK, optional=True)],
            audit=_audit(root),
        )
        assert _lines(root) == []

    def test_no_link_placed_means_the_protected_set_is_never_read(
        self, root: Path, worktree: Path
    ) -> None:
        def must_not_be_called() -> tuple[str, ...]:
            raise AssertionError("the protected set was read with no link to place")

        seed_worktree(
            root,
            worktree,
            [SeedEntry(path=".env.local", mode=SEED_MODE_COPY)],
            audit=_audit(root, must_not_be_called),
        )

    def test_the_protected_set_is_read_once_for_many_links(
        self, root: Path, worktree: Path
    ) -> None:
        calls: list[int] = []

        def counting() -> tuple[str, ...]:
            calls.append(1)
            return sfm.DEFAULT_PROTECTED_PATTERNS

        (root / ED_KEY).write_text(_SECRET_CONTENT, encoding="utf-8")
        seed_worktree(
            root,
            worktree,
            [
                SeedEntry(path=VAULT, mode=SEED_MODE_SYMLINK),
                SeedEntry(path=ED_KEY, mode=SEED_MODE_SYMLINK),
                SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK),
            ],
            audit=_audit(root, counting),
        )
        assert calls == [1]


class TestAnUnclassifiableLinkIsStillPlacedAndAudited:
    def test_an_unreadable_protected_set_audits_every_placed_link(
        self, root: Path, worktree: Path
    ) -> None:
        placed = seed_worktree(
            root,
            worktree,
            [
                SeedEntry(path=VAULT, mode=SEED_MODE_SYMLINK),
                SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK),
            ],
            audit=_audit(root, _unreadable),
        )
        assert placed == [worktree / VAULT, worktree / ".env.local"]
        lines = _lines(root)
        assert [line["path"] for line in lines] == [VAULT, ".env.local"]
        assert {line["outcome"] for line in lines} == {"linked-unclassified"}
        assert all(line["pattern"] is None for line in lines)
        assert all("could not be read" in line["unclassified_reason"] for line in lines)

    def test_a_linked_directory_that_cannot_be_walked_is_unclassified(
        self, root: Path, worktree: Path
    ) -> None:
        (root / "local").mkdir()
        (root / "local" / "loop").symlink_to(".")
        seed_worktree(
            root, worktree, [SeedEntry(path="local", mode=SEED_MODE_SYMLINK)], audit=_audit(root)
        )
        lines = _lines(root)
        assert [line["outcome"] for line in lines] == ["linked-unclassified"]
        assert "walked in full" in lines[0]["unclassified_reason"]


class TestAnAuditThatCannotBeWrittenRefusesTheLink:
    def test_the_link_is_not_created_and_seeding_raises(self, root: Path, worktree: Path) -> None:
        # A FILE where the log's directory should be: no append can succeed.
        untracked = get_untracked_dir(root)
        untracked.parent.mkdir(parents=True, exist_ok=True)
        untracked.write_text("not a directory\n", encoding="utf-8")
        with pytest.raises(WorktreeSeedError) as excinfo:
            seed_worktree(
                root,
                worktree,
                [
                    SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK),
                    SeedEntry(path=VAULT, mode=SEED_MODE_SYMLINK),
                ],
                audit=_audit(root),
            )
        assert not (worktree / VAULT).is_symlink()
        assert (worktree / ".env.local").is_symlink()
        message = str(excinfo.value)
        assert "seed entry #2" in message
        assert VAULT not in message

    def test_an_unprotected_link_does_not_need_the_log(self, root: Path, worktree: Path) -> None:
        untracked = get_untracked_dir(root)
        untracked.parent.mkdir(parents=True, exist_ok=True)
        untracked.write_text("not a directory\n", encoding="utf-8")
        placed = seed_worktree(
            root,
            worktree,
            [SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)],
            audit=_audit(root),
        )
        assert placed == [worktree / ".env.local"]
