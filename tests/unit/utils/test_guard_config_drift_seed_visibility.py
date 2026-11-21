"""An uncommitted seed entry is visible as config drift (Plan 00613, config-edit route).

The seed list is the project config's grant of what is linked into a worktree.
An agent can Edit the config like any other file: a PreToolUse deny on config
writes is circular (guard_config_drift's module docstring), so the project's
answer is visibility, not prevention. This pins that a seed entry added in the
working tree is counted as drift, an unnamed difference the session-start report
counts. It is NOT a named weakening, so the commit gate (weakenings only) says
nothing about it. A pin: it passes on the comparison as shipped.
"""

from __future__ import annotations

from claude_code_hooks_daemon.utils.guard_config_drift import compare_guard_config

_COMMITTED = """\
version: '2.0'
handlers:
  worktree_create:
    worktree_create:
      enabled: true
      options:
        seed:
          entries:
            - path: local.env
"""

_WITH_ADDED_ENTRY = _COMMITTED + "            - path: added-entry\n              mode: symlink\n"


def test_an_added_seed_entry_is_counted_as_drift() -> None:
    report = compare_guard_config(_COMMITTED, _WITH_ADDED_ENTRY)
    assert report.other_changes >= 1
    assert report.guard_changes == ()


def test_an_unchanged_seed_list_is_not_drift() -> None:
    report = compare_guard_config(_COMMITTED, _COMMITTED)
    assert report.other_changes == 0
    assert report.guard_changes == ()
