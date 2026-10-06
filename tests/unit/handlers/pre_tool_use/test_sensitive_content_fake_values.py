"""sensitive_content lets a registered fake through and still blocks an unlisted one (Plan 00492)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content import (
    SensitiveContentHandler,
)
from claude_code_hooks_daemon.utils.fake_values import REGISTRY_RELATIVE_PATH

_LISTED = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
# Built at runtime so this file never carries a real-looking UUID literal.
_UNLISTED_REAL_LOOKING = "-".join(("8e11bfb5", "7dc2", "432b", "9206", "928fa5c35731"))
# The dogfood rule: any UUID except one whose hex digits are all the same.
_UUID_PATTERN = {
    "name": "session-uuid",
    "pattern": (
        r"\b(?!([0-9a-fA-F])\1{7}-\1{4}-\1{4}-\1{4}-\1{12}\b)"
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    ),
    "description": "a real session UUID",
}
# A pattern that DOES match a uniform UUID, so the registry is what allows it.
_ANY_UUID_PATTERN = {
    "name": "session-uuid",
    "pattern": r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    "description": "any UUID",
}
_ANOTHER_PATTERN = {"name": "marker-path", "pattern": "zzqx-marker", "description": "d"}


def _write(path: str, content: str) -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}}


def _handler(
    root: Path, *patterns: dict[str, str], registry: str | None
) -> SensitiveContentHandler:
    if registry is not None:
        target = root / REGISTRY_RELATIVE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(registry, encoding="utf-8")
    handler = SensitiveContentHandler()
    handler._public_patterns = list(patterns)
    handler._project_root_override = root
    return handler


def _registry(*values: str, kind: str = "session-uuid") -> str:
    listed = "".join(f"      - '{value}'\n" for value in values)
    return f"kinds:\n  {kind}:\n    values:\n{listed}"


class TestRegisteredFakesAreAllowed:
    def test_a_listed_value_matched_by_the_pattern_is_allowed(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, _ANY_UUID_PATTERN, registry=_registry(_LISTED))
        hook = _write(str(tmp_path / "docs.md"), f"session {_LISTED}")
        assert handler.matches(hook) is False

    def test_without_the_registry_the_same_value_is_blocked(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, _ANY_UUID_PATTERN, registry=None)
        hook = _write(str(tmp_path / "docs.md"), f"session {_LISTED}")
        assert handler.matches(hook) is True

    def test_an_unlisted_real_looking_value_is_still_blocked(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, _UUID_PATTERN, registry=_registry(_LISTED))
        hook = _write(str(tmp_path / "docs.md"), f"session {_UNLISTED_REAL_LOOKING}")
        assert handler.matches(hook) is True
        result = handler.handle(hook)
        assert result.decision == Decision.DENY
        assert _UNLISTED_REAL_LOOKING in (result.reason or "")

    def test_a_listed_value_does_not_shelter_an_unlisted_one_beside_it(
        self, tmp_path: Path
    ) -> None:
        handler = _handler(tmp_path, _UUID_PATTERN, registry=_registry(_LISTED))
        hook = _write(str(tmp_path / "docs.md"), f"a {_LISTED} b {_UNLISTED_REAL_LOOKING}")
        assert handler.matches(hook) is True

    def test_the_same_text_under_another_kind_is_not_allowed(self, tmp_path: Path) -> None:
        handler = _handler(
            tmp_path,
            _ANY_UUID_PATTERN,
            registry=_registry(_LISTED, kind="some-other-kind"),
        )
        hook = _write(str(tmp_path / "docs.md"), f"session {_LISTED}")
        assert handler.matches(hook) is True

    def test_a_pattern_the_registry_does_not_list_is_unaffected(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, _ANOTHER_PATTERN, registry=_registry(_LISTED))
        hook = _write(str(tmp_path / "docs.md"), "see zzqx-marker here")
        assert handler.matches(hook) is True

    def test_a_malformed_registry_allows_nothing(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, _ANY_UUID_PATTERN, registry="kinds: [oops")
        hook = _write(str(tmp_path / "docs.md"), f"session {_LISTED}")
        assert handler.matches(hook) is True

    def test_scan_text_applies_the_same_rule_to_a_capture(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path, _UUID_PATTERN, registry=_registry(_LISTED))
        assert handler.scan_text(f"id {_LISTED}") is None
        reason = handler.scan_text(f"id {_UNLISTED_REAL_LOOKING}")
        assert reason is not None
        assert "session-uuid" in reason


@pytest.mark.parametrize("content", ["no uuid here", ""])
def test_content_without_a_match_is_untouched(tmp_path: Path, content: str) -> None:
    handler = _handler(tmp_path, _UUID_PATTERN, registry=_registry(_LISTED))
    assert handler.matches(_write(str(tmp_path / "docs.md"), content)) is False
