"""Probe: does `_DAEMON_WRAPPER_FRAGMENT` classify hook commands the way
MERGE-SPEC.md Q2 assumes? Evidence for Plan 00176 Task 1.3 audit.

Run: python3 untracked/scratch/00176-audit/probe_fragment.py
"""

import sys

sys.path.insert(0, "src")

from claude_code_hooks_daemon.utils.hook_command_migration import (
    legacy_command_bash_key,
)
from claude_code_hooks_daemon.utils.hook_registration import (
    _DAEMON_WRAPPER_FRAGMENT,
    HOOK_COMMAND_TEMPLATE,
)

CASES = [
    # (command, what it really is)
    ('bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-tool-use', "daemon forwarder (current)"),
    (
        ".claude/hooks/pre-tool-use",
        "daemon forwarder (relative legacy, install_version.sh fallback)",
    ),
    ('"$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-tool-use', "daemon forwarder (bare anchored legacy)"),
    (
        'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/my-secret-scan',
        "CLIENT script living in .claude/hooks/",
    ),
    (
        'python3 audit.py --wrappers "$CLAUDE_PROJECT_DIR"/.claude/hooks/',
        "CLIENT script that merely names the dir",
    ),
    (
        'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-tool-use && ./ci/extra-gate.sh',
        "daemon forwarder + CLIENT chained command",
    ),
    ('bash "$HOME"/dotfiles/.claude/hooks/lint', "CLIENT hook in their own dotfiles repo"),
]

print(f"fragment = {_DAEMON_WRAPPER_FRAGMENT!r}")
print(f"template = {HOOK_COMMAND_TEMPLATE!r}\n")
print(f"{'spec says OURS':<15} {'migrator sees legacy':<21} truth")
for cmd, truth in CASES:
    spec_owns = _DAEMON_WRAPPER_FRAGMENT in cmd
    legacy = legacy_command_bash_key(cmd)
    print(f"{spec_owns!s:<15} {legacy!s:<21} {truth}\n{'':36}{cmd!r}")
