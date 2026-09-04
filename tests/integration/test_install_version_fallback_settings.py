"""The fallback settings.json the upgrade script writes must not be a trap.

Plan 00102 Phase 6. ``scripts/install_version.sh`` normally generates
settings.json by calling ``reconcile-settings``, which renders through the
SSoT template. When no venv python is available it falls back to a heredoc
literal — and that literal had no test of any kind, which is how it kept a
shape every other source had migrated away from years earlier.

Two properties are asserted, and the second is the one that bites:

- every command is ``bash``-invoked, so a dropped exec bit is irrelevant
  (Tier 1's whole purpose);
- every command is anchored to ``$CLAUDE_PROJECT_DIR`` rather than being
  relative.

The relative form is not merely untidy. A relative command resolves against
the process cwd, so it breaks the moment a Bash tool call changes directory —
and NOTHING repairs it afterwards: ``_LEGACY_PATH_PATTERN`` in the Tier 2
migrator requires a ``$CLAUDE_PROJECT_DIR`` prefix before it will rewrite a
command, and ``reconcile_settings_hooks`` only fills in MISSING events, never
rewriting ones already present. A fallback install therefore stays broken
permanently, which is exactly the failure mode Plan 00102 exists to remove.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "install_version.sh"


def _fallback_settings() -> dict:
    """Parse the heredoc literal the script writes when it has no python.

    Extracted by locating the quoted-delimiter heredoc body rather than by
    running the installer: the fallback only triggers when no venv python
    exists, which is not a state a test can reach without dismantling the
    environment it runs in.
    """
    text = _SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"<<'SETTINGS_EOF'\n(.*?)\nSETTINGS_EOF", text, re.DOTALL)
    assert match is not None, "could not locate the fallback settings heredoc"
    return json.loads(match.group(1))


def _all_commands(settings: dict) -> dict[str, str]:
    commands: dict[str, str] = {}
    status_line = settings.get("statusLine", {})
    if "command" in status_line:
        commands["statusLine"] = status_line["command"]
    for event_name, hook_configs in settings.get("hooks", {}).items():
        for hook_config in hook_configs:
            for hook in hook_config.get("hooks", []):
                if hook.get("type") == "command" and "command" in hook:
                    commands[event_name] = hook["command"]
    return commands


def test_the_fallback_heredoc_is_valid_json() -> None:
    assert _all_commands(_fallback_settings()), "fallback registers no commands at all"


def test_every_fallback_command_is_bash_invoked() -> None:
    commands = _all_commands(_fallback_settings())

    bare = {name: cmd for name, cmd in commands.items() if not cmd.startswith("bash ")}

    assert not bare, f"fallback commands must be `bash`-invoked — bare: {bare!r}"


def test_every_fallback_command_is_anchored_to_the_project_dir() -> None:
    """The self-heal cannot reach a relative command, so it must never ship one."""
    commands = _all_commands(_fallback_settings())

    relative = {name: cmd for name, cmd in commands.items() if "$CLAUDE_PROJECT_DIR" not in cmd}

    assert not relative, (
        "fallback commands must be anchored to $CLAUDE_PROJECT_DIR — a relative "
        "command resolves against the process cwd and no migrator will ever "
        f"rewrite it: {relative!r}"
    )
