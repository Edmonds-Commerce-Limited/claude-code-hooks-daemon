"""The Claude Code deny layer stays in sync with the daemon (Plan 00333).

`project_containment` is the real control: deny-by-default, whitelist-shaped,
enforced in a PreToolUse hook. The `permissions.deny` block in
`.claude/settings.json` is a backstop for when that hook is not running — a
stopped daemon, a failed restart, a project where hooks are not yet registered.

Two layers guarding one rule drift apart unless something asserts otherwise,
and a backstop that has silently stopped matching the thing it backs up is
worse than none: it still reads like policy.

**The two layers are NOT equivalent, and that asymmetry is the point.** Claude
Code's permission rules cannot express a whitelist. Rules evaluate deny → ask →
allow with the first match winning, so a broad `Edit(//**)` deny cannot carry an
allow exception for the project; there is no negation syntax; and there is no
writes counterpart to `blockReadsOutsideWorkingDirectories`. So the settings
layer can only enumerate roots. This test pins that enumeration to the daemon's
own constant — it does not pretend the two layers are the same shape.
"""

from __future__ import annotations

import json
from pathlib import Path

from claude_code_hooks_daemon.constants.paths import ProjectPath

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SETTINGS = _REPO_ROOT / ".claude" / "settings.json"


def _deny_rules() -> list[str]:
    settings = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    permissions = settings.get("permissions", {})
    return list(permissions.get("deny", []))


class TestTheBackstopMatchesTheDaemon:
    def test_every_ephemeral_root_is_denied(self) -> None:
        """A root the daemon names but settings omits is an unguarded hole
        exactly when the daemon is the thing that is down."""
        missing = [
            ProjectPath.claude_code_deny_rule(root)
            for root in ProjectPath.EPHEMERAL_ROOTS
            if ProjectPath.claude_code_deny_rule(root) not in _deny_rules()
        ]

        assert not missing, (
            f"{_SETTINGS} is missing deny rules for {missing}. The daemon names "
            "these roots as ephemeral; the Claude Code layer must too, or the "
            "backstop does not cover what it claims to."
        )

    def test_no_stale_rule_survives_in_settings(self) -> None:
        """The other direction: a rule for a root the daemon no longer names."""
        expected = {ProjectPath.claude_code_deny_rule(r) for r in ProjectPath.EPHEMERAL_ROOTS}
        stale = [rule for rule in _deny_rules() if rule not in expected]

        assert not stale, (
            f"{_SETTINGS} carries deny rules {stale} that the daemon's "
            "EPHEMERAL_ROOTS no longer names. Either add the root to the "
            "constant or drop the rule — a rule with no owner is not policy."
        )


class TestTheRuleSyntaxIsTheSupportedOne:
    """Every part of this syntax is counter-intuitive and was verified against
    the official documentation rather than inferred."""

    def test_rules_use_the_edit_tool_not_write(self) -> None:
        """`Write` is not a permission-rule tool name. A `Write(...)` rule
        matches nothing and fails silently — the worst possible outcome for a
        backstop."""
        for rule in _deny_rules():
            assert rule.startswith("Edit("), f"{rule} does not use the Edit tool"

    def test_rules_are_anchored_to_the_filesystem_root(self) -> None:
        """The leading `//` means an ABSOLUTE path. A single slash anchors to
        the settings file's own location and a bare pattern to the working
        directory, so dropping one slash silently re-points the rule."""
        for rule in _deny_rules():
            assert rule.startswith("Edit(//"), f"{rule} is not absolute-anchored"

    def test_rules_match_recursively(self) -> None:
        for rule in _deny_rules():
            assert rule.endswith("/**)"), f"{rule} does not match recursively"


class TestTheConstantIsMeaningful:
    def test_the_temp_directory_is_named(self) -> None:
        """Control: an empty or accidentally-cleared constant would make every
        assertion above vacuously true."""
        assert "/tmp" in ProjectPath.EPHEMERAL_ROOTS

    def test_every_root_is_absolute(self) -> None:
        for root in ProjectPath.EPHEMERAL_ROOTS:
            assert root.startswith("/"), f"{root} is not an absolute path"
