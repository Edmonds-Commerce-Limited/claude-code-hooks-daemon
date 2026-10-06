"""The whole-tree scanner honours the fake-values registry (Plan 00492)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.utils.fake_values import REGISTRY_RELATIVE_PATH
from tests.unit.qa.test_check_sensitive_content import _run_checker, _write_config

_UUID_REGEX = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_LISTED = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
# Built at runtime so this file never carries a real-looking UUID literal.
_UNLISTED = "-".join(("8e11bfb5", "7dc2", "432b", "9206", "928fa5c35731"))
_REGISTRY = f"kinds:\n  session-uuid:\n    values:\n      - '{_LISTED}'\n"


def _scan(tmp_path: Path, content: str, *, registry: str | None) -> dict[str, Any]:
    config = tmp_path / "hooks-daemon.yaml"
    _write_config(config, public_patterns=[{"name": "session-uuid", "pattern": _UUID_REGEX}])
    (tmp_path / "docs.md").write_text(content, encoding="utf-8")
    if registry is not None:
        target = tmp_path / REGISTRY_RELATIVE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(registry, encoding="utf-8")
    return _run_checker(tmp_path, config)


class TestRegistryInTheTreeScan:
    def test_a_listed_fake_is_not_flagged(self, tmp_path: Path) -> None:
        data = _scan(tmp_path, f"session {_LISTED}\n", registry=_REGISTRY)
        assert data["summary"]["passed"] is True, data["violations"]

    def test_the_same_value_is_flagged_without_the_registry(self, tmp_path: Path) -> None:
        data = _scan(tmp_path, f"session {_LISTED}\n", registry=None)
        assert [v["rule"] for v in data["violations"]] == ["public-pattern:session-uuid"]

    def test_an_unlisted_real_looking_value_is_still_flagged(self, tmp_path: Path) -> None:
        data = _scan(tmp_path, f"session {_UNLISTED}\n", registry=_REGISTRY)
        assert [v["rule"] for v in data["violations"]] == ["public-pattern:session-uuid"]
        assert _UNLISTED in data["violations"][0]["message"]

    def test_a_listed_fake_does_not_shelter_an_unlisted_one_on_the_same_line(
        self, tmp_path: Path
    ) -> None:
        data = _scan(tmp_path, f"{_LISTED} {_UNLISTED}\n", registry=_REGISTRY)
        assert [v["rule"] for v in data["violations"]] == ["public-pattern:session-uuid"]
        assert _UNLISTED in data["violations"][0]["message"]

    def test_a_malformed_registry_fails_the_scan(self, tmp_path: Path) -> None:
        data = _scan(tmp_path, f"session {_LISTED}\n", registry="kinds: [oops")
        assert data["summary"]["passed"] is False
        assert "config" in {v["rule"] for v in data["violations"]}
