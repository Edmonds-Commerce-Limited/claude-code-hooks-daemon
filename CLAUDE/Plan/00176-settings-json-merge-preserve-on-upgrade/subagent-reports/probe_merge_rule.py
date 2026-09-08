"""Probe: implement MERGE-SPEC.md Q2's rule literally and run adversarial inputs.

Rule as specified (MERGE-SPEC.md:63-70, 130):
  copy the client doc; for each hooks[event] inner hook whose `command`
  contains `/.claude/hooks/`, rebuild it from HOOK_COMMAND_TEMPLATE; add any
  missing wired event. Siblings without the fragment are untouched.

Run: ./.venv/bin/python untracked/scratch/00176-audit/probe_merge_rule.py
"""

import copy
import json
import sys

sys.path.insert(0, "src")

from claude_code_hooks_daemon.utils.hook_registration import (
    _DAEMON_WRAPPER_FRAGMENT,
    HOOK_COMMAND_TEMPLATE,
    HOOK_EVENTS_IN_SETTINGS,
    detect_legacy_hook_commands,
    reconcile_settings_hooks,
    validate_hook_commands,
)


def spec_merge(client: dict) -> dict:
    out = copy.deepcopy(client)
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        # MERGE-SPEC.md:54 endorses the wholesale replace for this case.
        out, _ = reconcile_settings_hooks(out)
        return out
    for event, entries in hooks.items():
        bash_key = HOOK_EVENTS_IN_SETTINGS.get(event)
        if bash_key is None or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for inner in entry.get("hooks", []) or []:
                if not isinstance(inner, dict):
                    continue
                cmd = inner.get("command", "")
                if isinstance(cmd, str) and _DAEMON_WRAPPER_FRAGMENT in cmd:
                    inner["command"] = HOOK_COMMAND_TEMPLATE.format(bash_key=bash_key)
    out, _ = reconcile_settings_hooks(out)
    return out


def show(title, client):
    merged = spec_merge(client)
    print(f"\n=== {title} ===")
    print("BEFORE PreToolUse:", json.dumps(client["hooks"].get("PreToolUse"), indent=None))
    print("AFTER  PreToolUse:", json.dumps(merged["hooks"].get("PreToolUse"), indent=None))
    for issue in validate_hook_commands(merged):
        if "PreToolUse" in issue:
            print("  validator:", issue)
    for issue in detect_legacy_hook_commands(merged):
        if "PreToolUse" in issue:
            print("  legacy-detector:", issue)


# A: client's own script sits in .claude/hooks/ alongside the forwarder
show(
    "A - client script in .claude/hooks/, sibling of the forwarder",
    {
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": 'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-tool-use',
                            "timeout": 60,
                        },
                        {
                            "type": "command",
                            "command": 'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/my-secret-scan',
                        },
                    ]
                }
            ]
        },
    },
)

# B: client raised the forwarder timeout because their handlers are slow
show(
    "B - client raised timeout to 300",
    {
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": 'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-tool-use',
                            "timeout": 300,
                        },
                    ]
                }
            ]
        },
    },
)

# C: relative legacy forwarder (install_version.sh fallback shape)
show(
    "C - relative legacy forwarder",
    {
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {"type": "command", "command": ".claude/hooks/pre-tool-use"},
                    ]
                }
            ]
        },
    },
)

# D: client scoped OUR forwarder with a matcher
show(
    "D - client added matcher scoping the forwarder to Bash only",
    {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": 'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-tool-use',
                            "timeout": 60,
                        },
                    ],
                }
            ]
        },
    },
)

# E: forwarder chained with a client gate
show(
    "E - forwarder chained with a client gate",
    {
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": 'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-tool-use && bash ci/extra-gate.sh',
                            "timeout": 60,
                        },
                    ]
                }
            ]
        },
    },
)

# F: hooks is a list (hand-edited / future schema)
bad = {"permissions": {"deny": ["Edit(//tmp/**)"]}, "hooks": [{"PreToolUse": "..."}]}
merged = spec_merge(bad)
print("\n=== F - malformed hooks (list) ===")
print("BEFORE:", json.dumps(bad["hooks"]))
print(
    "AFTER kept client's hook data?:",
    any("PreToolUse" in str(v) and "..." in str(v) for v in [merged["hooks"]]),
)
print("permissions preserved:", merged.get("permissions"))
