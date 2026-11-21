"""The read-only archive-store view types live outside the archive modules (Plan 00627).

``scratch_inventory`` (imported by handlers) needs the shape of a store's
status but must never import an archive module, so the two frozen dataclasses
live in ``scratch_store_view`` and the status reader re-exports them.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import scratch_store_view
from claude_code_hooks_daemon.core.scratch_store_view import ArchiveStatus, StoreStatus


def test_the_types_are_frozen_values() -> None:
    row = ArchiveStatus(
        archive_id="a1",
        original_paths=("untracked/scratch/x",),
        verdict="SAFE",
        expires=None,
        note="held",
        keeps=0,
        restore_command="restore a1",
    )
    status = StoreStatus(archives=(row,), torn=False)
    assert status.archives[0] is row
    assert dataclasses.fields(StoreStatus)
    for instance, field_name in ((status, "torn"), (row, "note")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(instance, field_name, None)


def test_the_status_reader_reuses_the_same_types() -> None:
    from claude_code_hooks_daemon.core import scratch_archive_status

    assert scratch_archive_status.StoreStatus is StoreStatus
    assert scratch_archive_status.ArchiveStatus is ArchiveStatus


def test_the_view_module_imports_nothing_from_the_daemon() -> None:
    tree = ast.parse(Path(scratch_store_view.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("claude_code_hooks_daemon")
