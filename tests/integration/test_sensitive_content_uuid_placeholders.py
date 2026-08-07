"""The session-uuid rule must not block the placeholder it recommends.

Regression test for a self-defeating guard found while using this repo's own
``sensitive_content`` handler to redact real session UUIDs from tracked docs.

The rule matched ANY UUID shape. Its deny message said "use an all-zeros
placeholder instead" -- and then denied that placeholder too, because it is
also a UUID shape. The only remediation the handler advertised was one the
handler refused to accept, so a redaction could not be completed at all. The
fix was worse than blocked: the explanatory comment in the config tripped the
live rule, so the pattern had to be relaxed before its own justification could
be typed into the file.

This test reads the pattern out of the REAL project config rather than
restating it, so deleting the lookahead fails here instead of silently
restoring the deadlock.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / ".claude" / "hooks-daemon.yaml"
_RULE_NAME = "session-uuid"

# All-same-hex-digit UUIDs. These are the sanctioned placeholders: obviously
# synthetic, and distinguishable from each other when a document has to keep
# two sessions apart (which is exactly why a single all-zeros value is not
# sufficient on its own).
_PLACEHOLDERS = (
    "00000000-0000-0000-0000-000000000000",
    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    "ffffffff-ffff-ffff-ffff-ffffffffffff",
    "11111111-1111-1111-1111-111111111111",
)


def _load_session_uuid_pattern() -> str:
    """The live ``session-uuid`` regex from the project config.

    Deliberately not a copy: a test that restates the pattern passes happily
    while the deployed rule regresses.
    """
    with _CONFIG_PATH.open(encoding="utf-8") as handle:
        config: dict[str, Any] = yaml.safe_load(handle)

    options = config["handlers"]["pre_tool_use"]["sensitive_content"]["options"]
    for entry in options["public_patterns"]:
        if entry.get("name") == _RULE_NAME:
            return str(entry["pattern"])
    pytest.fail(f"No {_RULE_NAME!r} entry in public_patterns -- did the rule get renamed?")


@pytest.fixture(scope="module")
def rule() -> re.Pattern[str]:
    return re.compile(_load_session_uuid_pattern())


@pytest.mark.parametrize("placeholder", _PLACEHOLDERS)
def test_placeholder_uuids_are_not_flagged(rule: re.Pattern[str], placeholder: str) -> None:
    """A redaction must be able to land its own replacement text."""
    assert rule.search(placeholder) is None, (
        f"{placeholder} is an all-same-digit placeholder, but the rule flags it. "
        "That makes redaction impossible: the replacement is rejected too."
    )


def test_a_real_shaped_uuid_is_still_flagged(rule: re.Pattern[str]) -> None:
    """The control. Without this, deleting the whole rule would pass the test above.

    Generated rather than hard-coded: a real-shaped UUID literal in this file
    would itself be denied by the very handler under test.
    """
    assert rule.search(str(uuid.uuid4())) is not None, (
        "The rule no longer matches real UUIDs at all -- the exemption has "
        "swallowed the rule it was meant to narrow."
    )


def test_near_placeholder_uuids_are_still_flagged(rule: re.Pattern[str]) -> None:
    """Uniformity is the test, not 'looks a bit like zeros'.

    A value that is all zeros except one digit is still a plausible real
    identifier, so the exemption must not extend to it. This is the boundary
    the fix was written against.
    """
    almost = "0" * 8 + "-" + "0" * 4 + "-" + "0" * 4 + "-" + "0" * 4 + "-" + "0" * 11 + "b"
    assert (
        rule.search(almost) is not None
    ), "A near-uniform UUID slipped through; the exemption is too loose."
