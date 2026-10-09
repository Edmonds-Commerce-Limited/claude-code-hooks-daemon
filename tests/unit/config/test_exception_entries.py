"""Reasons on config exceptions (Plan 00484 G4, owner ruling B3).

``exclude_paths`` and ``extra_whitelist`` entries are either a plain string or a
``{pattern, reason}`` mapping. Handlers only ever see plain patterns. Under
``daemon.strict_mode`` a plain string loads and is reported as a warning.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.exception_entries import (
    entry_pattern,
    normalise_exception_entries,
)
from claude_code_hooks_daemon.config.models import Config, DaemonConfig, HandlerConfig


class TestNormaliseExceptionEntries:
    """The one shared normaliser."""

    def test_plain_strings_pass_through_as_unreasoned(self) -> None:
        result = normalise_exception_entries(["a/**", "b"], where="x")
        assert result.patterns == ["a/**", "b"]
        assert result.unreasoned == ["a/**", "b"]

    def test_mapping_form_yields_pattern_and_is_reasoned(self) -> None:
        result = normalise_exception_entries(
            [{"pattern": "a/**", "reason": "generated fixtures"}, "b"], where="x"
        )
        assert result.patterns == ["a/**", "b"]
        assert result.unreasoned == ["b"]

    @pytest.mark.parametrize("reason", ["", "tbd", "because", "-->", "n/a"])
    def test_placeholder_reason_is_rejected(self, reason: str) -> None:
        with pytest.raises(ValueError, match="reason"):
            normalise_exception_entries([{"pattern": "a", "reason": reason}], where="x")

    def test_missing_reason_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="reason"):
            normalise_exception_entries([{"pattern": "a"}], where="x")

    def test_missing_pattern_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="pattern"):
            normalise_exception_entries([{"reason": "because of things"}], where="x")

    def test_unknown_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown"):
            normalise_exception_entries(
                [{"pattern": "a", "reason": "a real reason", "why": "x"}], where="x"
            )

    def test_error_names_location(self) -> None:
        with pytest.raises(ValueError, match="daemon.exclude_paths"):
            normalise_exception_entries(
                [{"pattern": "a", "reason": "tbd"}], where="daemon.exclude_paths"
            )

    def test_non_string_non_mapping_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="entry"):
            normalise_exception_entries([5], where="x")

    def test_entry_pattern(self) -> None:
        assert entry_pattern("a") == "a"
        assert entry_pattern({"pattern": "b", "reason": "r"}) == "b"


class TestConfigModels:
    """Normalisation at config load."""

    def test_daemon_exclude_paths_mapping_becomes_plain(self) -> None:
        daemon = DaemonConfig.model_validate(
            {"exclude_paths": [{"pattern": "a/**", "reason": "vendored copy"}, "b"]}
        )
        assert daemon.exclude_paths == ["a/**", "b"]

    def test_handler_options_normalised(self) -> None:
        handler = HandlerConfig.model_validate(
            {
                "options": {
                    "exclude_paths": [{"pattern": "a", "reason": "generated output"}],
                    "extra_whitelist": [{"pattern": "^x\\b", "reason": "cheap filter"}, "^y"],
                }
            }
        )
        assert handler.options["exclude_paths"] == ["a"]
        assert handler.options["extra_whitelist"] == ["^x\\b", "^y"]

    def test_handler_options_bad_reason_is_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="reason"):
            HandlerConfig.model_validate(
                {"options": {"exclude_paths": [{"pattern": "a", "reason": "todo"}]}}
            )

    def test_handler_options_non_list_left_alone(self) -> None:
        handler = HandlerConfig.model_validate({"options": {"exclude_paths": "oops"}})
        assert handler.options["exclude_paths"] == "oops"

    def _config(self, strict: bool, **sections: Any) -> dict[str, Any]:
        return {
            "daemon": {"strict_mode": strict, **sections.get("daemon", {})},
            **{k: v for k, v in sections.items() if k != "daemon"},
        }

    def test_non_strict_accepts_plain_strings(self) -> None:
        Config.model_validate(self._config(False, daemon={"exclude_paths": ["a"]}))

    def test_strict_plain_daemon_exclude_loads_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A missing reason is not a dangerous config, so it must not stop the daemon."""
        with caplog.at_level("WARNING"):
            config = Config.model_validate(self._config(True, daemon={"exclude_paths": ["a"]}))

        assert config.daemon.exclude_paths == ["a"]
        assert len(config.config_problems) == 1
        assert "daemon.exclude_paths" in config.config_problems[0]
        assert "'a'" in config.config_problems[0]
        assert "reason" in config.config_problems[0]
        assert any("daemon.exclude_paths" in r.getMessage() for r in caplog.records)

    def test_non_strict_has_no_problems(self) -> None:
        config = Config.model_validate(self._config(False, daemon={"exclude_paths": ["a"]}))
        assert config.config_problems == []

    def test_reasoned_strict_has_no_problems(self) -> None:
        config = Config.model_validate(
            self._config(
                True, daemon={"exclude_paths": [{"pattern": "a", "reason": "vendored copy"}]}
            )
        )
        assert config.config_problems == []

    def test_strict_accepts_reasoned_entries(self) -> None:
        config = Config.model_validate(
            self._config(
                True,
                daemon={"exclude_paths": [{"pattern": "a", "reason": "vendored copy"}]},
            )
        )
        assert config.daemon.exclude_paths == ["a"]

    def test_strict_plain_handler_entry_loads_and_warns(self) -> None:
        raw = self._config(
            True,
            handlers={"pre_tool_use": {"pipe_blocker": {"options": {"extra_whitelist": ["^x"]}}}},
        )
        config = Config.model_validate(raw)

        assert config.handlers.pre_tool_use["pipe_blocker"].options["extra_whitelist"] == ["^x"]
        assert len(config.config_problems) == 1
        assert "pipe_blocker" in config.config_problems[0]
        assert "extra_whitelist" in config.config_problems[0]

    def test_placeholder_reason_stays_an_error_under_strict_mode(self) -> None:
        raw = self._config(True, daemon={"exclude_paths": [{"pattern": "a", "reason": "tbd"}]})
        with pytest.raises(ValidationError, match="reason"):
            Config.model_validate(raw)

    def test_strict_accepts_empty_lists(self) -> None:
        raw = self._config(
            True,
            handlers={"pre_tool_use": {"pipe_blocker": {"options": {"extra_whitelist": []}}}},
        )
        Config.model_validate(raw)


class TestThisRepositoryConfig:
    """The dogfood config runs under strict_mode, so every exception carries a reason."""

    def test_repo_config_validates_and_reaches_handlers_as_plain_patterns(self) -> None:
        from pathlib import Path

        from claude_code_hooks_daemon.config.loader import ConfigLoader

        path = Path(__file__).resolve().parents[3] / ".claude" / "hooks-daemon.yaml"
        config = Config.model_validate(ConfigLoader.load(path))

        assert config.daemon.strict_mode is True
        lint = config.handlers.post_tool_use["lint_on_edit"].options["exclude_paths"]
        assert "/untracked/scratch/**" in lint
        assert all(isinstance(p, str) for p in lint)
