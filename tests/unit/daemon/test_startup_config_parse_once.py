"""The daemon start parses the config YAML once, not once per consumer.

Phase 1 of Plan 00495 measured four parses on the start path: the CLI load,
the controller's own validation, and the two config-driven asset syncs, each
of which reloaded the file (and re-ran the whole pydantic model) by itself.
"""

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from yaml.constructor import BaseConstructor

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.daemon.cli import _build_initialised_controller

VALID_CONFIG = (
    "version: '2.0'\ndaemon:\n  idle_timeout_seconds: 600\n  log_level: INFO\nhandlers: {}\n"
)

#: Loads as a Config, but ConfigValidator reports the missing log_level and handlers.
INCOMPLETE_CONFIG = "version: '2.0'\ndaemon:\n  idle_timeout_seconds: 600\n"


def _init_git_repo(root: Path) -> None:
    """ProjectContext fail-fasts unless the project is a git repo with an origin."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:example/example.git"],
        cwd=root,
        check=True,
    )


def _write_config(project: Path, text: str) -> Path:
    config_path = project / ".claude" / "hooks-daemon.yaml"
    config_path.parent.mkdir(exist_ok=True)
    config_path.write_text(text, encoding="utf-8")
    return config_path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A throwaway project with a minimal daemon config."""
    _write_config(tmp_path, VALID_CONFIG)
    _init_git_repo(tmp_path)
    return tmp_path


@pytest.fixture
def yaml_parse_count(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """Count every YAML document parsed, by either safe loader."""
    calls: list[int] = []
    real_get_single_data = BaseConstructor.get_single_data

    def counting_get_single_data(self: BaseConstructor) -> Any:
        calls.append(1)
        return real_get_single_data(self)

    monkeypatch.setattr(BaseConstructor, "get_single_data", counting_get_single_data)
    yield calls


def test_start_path_parses_the_config_once(project: Path, yaml_parse_count: list[int]) -> None:
    """Loading the config and building the controller costs one YAML parse."""
    config = Config.find_and_load(project)
    _build_initialised_controller(config, project)
    assert len(yaml_parse_count) == 1


def test_valid_reused_document_is_not_degraded(project: Path) -> None:
    """The reused document is still validated: a valid config is not degraded."""
    controller = _build_initialised_controller(Config.find_and_load(project), project)
    assert controller.is_degraded is False


def test_reused_document_reports_the_same_errors_as_a_fresh_parse(
    tmp_path: Path,
) -> None:
    """Reuse changes nothing about validation: same degraded flag, same errors."""
    config_path = _write_config(tmp_path, INCOMPLETE_CONFIG)
    _init_git_repo(tmp_path)
    config = Config.find_and_load(tmp_path)

    reused = _build_initialised_controller(config, tmp_path)

    fresh = _build_initialised_controller(config, tmp_path)
    fresh._validate_config(config_path)

    assert reused.is_degraded is True
    assert reused.is_degraded is fresh.is_degraded
    assert reused.config_errors == fresh.config_errors


def test_config_loaded_from_another_file_is_not_reused(project: Path, tmp_path: Path) -> None:
    """A config loaded from elsewhere is not mistaken for this project's file."""
    other = tmp_path / "other"
    other.mkdir()
    _write_config(other, "version: '2.0'\n")
    config_path = project / ".claude" / "hooks-daemon.yaml"
    assert Config.find_and_load(other).was_loaded_from(config_path) is False
    assert Config.find_and_load(project).was_loaded_from(config_path) is True


def test_default_config_matches_a_path_that_does_not_exist(tmp_path: Path) -> None:
    """With no file anywhere, the defaults stand in for the missing file."""
    isolated = tmp_path / "bare"
    isolated.mkdir()
    config_path = isolated / ".claude" / "hooks-daemon.yaml"
    assert Config().was_loaded_from(config_path) is True
    _write_config(isolated, "version: '2.0'\n")
    assert Config().was_loaded_from(config_path) is False


def test_empty_config_file_is_degraded_as_a_fresh_parse_would_report(tmp_path: Path) -> None:
    """An empty file parses to None; the reused document is refused like a fresh one."""
    config_path = _write_config(tmp_path, "")
    _init_git_repo(tmp_path)
    controller = _build_initialised_controller(Config.find_and_load(tmp_path), tmp_path)
    fresh = _build_initialised_controller(Config.find_and_load(tmp_path), tmp_path)
    fresh._validate_config(config_path)
    assert controller.is_degraded is True
    assert controller.config_errors == fresh.config_errors
    assert "must be a dictionary" in controller.config_errors[0]
