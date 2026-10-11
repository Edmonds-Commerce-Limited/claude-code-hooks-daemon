"""A malformed ``public_patterns`` entry never crashes the sensitive-content guard (N374 review).

The options come from client YAML, so an entry can be a bare string. The guard
skips it with a logged warning and still applies the entries around it.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content import (
    SensitiveContentHandler,
)


def _handler(entries: list[Any]) -> SensitiveContentHandler:
    handler = SensitiveContentHandler()
    handler._public_patterns = cast("list[dict[str, str]]", entries)
    return handler


def test_a_non_mapping_entry_is_skipped_and_the_rest_still_apply(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler = _handler(["just-a-string", {"name": "token", "pattern": r"secret-\d+"}])

    with caplog.at_level(logging.WARNING):
        match = handler._find_public_pattern_match("value secret-42 here")

    assert match is not None
    assert match["name"] == "token"
    assert any("not a mapping" in record.getMessage() for record in caplog.records)


def test_a_non_mapping_entry_alone_matches_nothing() -> None:
    assert _handler([42])._find_public_pattern_match("anything") is None
