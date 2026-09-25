"""Plan 00466 N47 — settings.json is the single source of truth for effort.

The ccy supervisor used to keep its own opinion of per-model effort (a
built-in floor table + the ``CCY_MIN_EFFORT_LEVELS`` env var), which fought
Claude Code's own ``settings.json``: the owner set medium there and the
supervisor still typed ``/effort high`` (the default floor) or ``/effort
xhigh`` (every restore to a non-top family). This file covers the resolver
(``_resolve_family_effort``, ``SettingsEffortCache``) directly; the
integration-level behaviour (floor injections, coupled-effort restores) is
covered in ``test_effort_restore.py`` and ``test_drop_anchor.py``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module
from tests.unit.supervise.conftest import write_settings_json

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()


# ── _claude_config_dir / _main_settings_path ────────────────────────────────


def test_claude_config_dir_env_var_wins(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(_mod._CLAUDE_CONFIG_DIR_ENV_VAR, str(tmp_path / "custom"))
    assert _mod._claude_config_dir() == tmp_path / "custom"


def test_claude_config_dir_falls_back_to_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(_mod._CLAUDE_CONFIG_DIR_ENV_VAR, raising=False)
    monkeypatch.setattr(_mod.Path, "home", classmethod(lambda cls: tmp_path))
    assert _mod._claude_config_dir() == tmp_path / ".claude"


def test_blank_claude_config_dir_env_var_falls_back_to_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(_mod._CLAUDE_CONFIG_DIR_ENV_VAR, "   ")
    monkeypatch.setattr(_mod.Path, "home", classmethod(lambda cls: tmp_path))
    assert _mod._claude_config_dir() == tmp_path / ".claude"


def test_main_settings_path_is_config_dir_slash_settings_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(_mod._CLAUDE_CONFIG_DIR_ENV_VAR, str(tmp_path))
    assert _mod._main_settings_path() == tmp_path / "settings.json"


# ── _resolve_family_effort ───────────────────────────────────────────────────


def test_resolve_family_effort_none_settings_is_none() -> None:
    assert _mod._resolve_family_effort(None, "opus") is None


def test_resolve_family_effort_empty_settings_is_none() -> None:
    assert _mod._resolve_family_effort({}, "opus") is None


def test_resolve_family_effort_top_level_effort_level() -> None:
    assert _mod._resolve_family_effort({"effortLevel": "medium"}, "opus") == "medium"


def test_resolve_family_effort_per_model_beats_top_level() -> None:
    settings = {
        "effortLevel": "medium",
        "modelSettings": {"claude-opus-5-5": {"effortLevel": "high"}},
    }
    assert _mod._resolve_family_effort(settings, "opus") == "high"


def test_resolve_family_effort_per_model_for_a_different_family_is_ignored() -> None:
    settings = {
        "effortLevel": "medium",
        "modelSettings": {"claude-fable-5": {"effortLevel": "xhigh"}},
    }
    assert _mod._resolve_family_effort(settings, "opus") == "medium"


def test_resolve_family_effort_invalid_level_is_ignored() -> None:
    settings = {"effortLevel": "not-a-real-level"}
    assert _mod._resolve_family_effort(settings, "opus") is None


def test_resolve_family_effort_invalid_per_model_level_falls_through_to_top_level() -> None:
    settings = {
        "effortLevel": "medium",
        "modelSettings": {"claude-opus-5-5": {"effortLevel": "bogus"}},
    }
    assert _mod._resolve_family_effort(settings, "opus") == "medium"


def test_resolve_family_effort_non_dict_model_settings_entry_is_ignored() -> None:
    settings = {"effortLevel": "medium", "modelSettings": {"claude-opus-5-5": "not-a-dict"}}
    assert _mod._resolve_family_effort(settings, "opus") == "medium"


# ── SettingsEffortCache: missing / malformed / unreadable degrades cleanly ──


def test_cache_missing_file_resolves_to_none_with_a_logged_reason(tmp_path: Path) -> None:
    cache = _mod.SettingsEffortCache(tmp_path / "no-such-dir" / "settings.json")
    assert cache.effort_for_family("opus") is None
    assert cache.last_error is None  # a missing file is silent, not an error


def test_cache_malformed_json_resolves_to_none_with_a_logged_reason(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not valid json", encoding="utf-8")
    cache = _mod.SettingsEffortCache(path)
    assert cache.effort_for_family("opus") is None
    assert cache.last_error is not None
    assert "settings.json" in cache.last_error


def test_cache_non_object_json_resolves_to_none_with_a_logged_reason(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    cache = _mod.SettingsEffortCache(path)
    assert cache.effort_for_family("opus") is None
    assert cache.last_error is not None


def test_cache_unreadable_directory_resolves_to_none_with_a_logged_reason(tmp_path: Path) -> None:
    # A path whose PARENT is a file (not a directory) can never be stat()'d
    # successfully -- exercises the OSError branch without needing chmod
    # tricks that behave differently as root.
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    cache = _mod.SettingsEffortCache(blocker / "settings.json")
    assert cache.effort_for_family("opus") is None


def test_cache_valid_settings_resolves_the_configured_family(tmp_path: Path) -> None:
    write_settings_json(tmp_path, effort_level="medium")
    cache = _mod.SettingsEffortCache(tmp_path / "settings.json")
    assert cache.effort_for_family("opus") == "medium"


# ── SettingsEffortCache: re-read on change (Task 5, no relaunch needed) ─────


def test_cache_picks_up_an_edit_without_reconstruction(tmp_path: Path) -> None:
    write_settings_json(tmp_path, effort_level="medium")
    cache = _mod.SettingsEffortCache(tmp_path / "settings.json")
    assert cache.effort_for_family("opus", now_wall=1000.0) == "medium"
    write_settings_json(tmp_path, effort_level="high")
    (tmp_path / "settings.json").touch()  # ensure a distinct mtime on fast filesystems
    # Past the reload-check throttle window, on the SAME cache instance.
    later = 1000.0 + _mod._SETTINGS_RELOAD_CHECK_SECONDS + 1.0
    assert cache.effort_for_family("opus", now_wall=later) == "high"


def test_cache_throttles_the_stat_check_within_the_window(tmp_path: Path) -> None:
    write_settings_json(tmp_path, effort_level="medium")
    cache = _mod.SettingsEffortCache(tmp_path / "settings.json")
    assert cache.effort_for_family("opus", now_wall=1000.0) == "medium"
    write_settings_json(tmp_path, effort_level="high")
    # Still inside the throttle window -- the edit is not observed yet.
    soon = 1000.0 + (_mod._SETTINGS_RELOAD_CHECK_SECONDS / 2.0)
    assert cache.effort_for_family("opus", now_wall=soon) == "medium"


def test_cache_recovers_once_a_missing_file_appears(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    cache = _mod.SettingsEffortCache(path)
    assert cache.effort_for_family("opus", now_wall=1000.0) is None
    write_settings_json(tmp_path, effort_level="medium")
    later = 1000.0 + _mod._SETTINGS_RELOAD_CHECK_SECONDS + 1.0
    assert cache.effort_for_family("opus", now_wall=later) == "medium"


# ── CompactStateMachine.take_settings_error_note ────────────────────────────


def test_take_settings_error_note_reports_a_new_error_once(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not valid json", encoding="utf-8")
    machine = _mod.CompactStateMachine(_mod.CompactPolicy(settings_path=path))
    machine._resolve_effort_for_family("opus", now_wall=1000.0)
    note = machine.take_settings_error_note()
    assert note is not None
    assert "settings.json" in note
    # Consumed -- the same still-broken file does not re-report every tick.
    machine._resolve_effort_for_family("opus", now_wall=1001.0)
    assert machine.take_settings_error_note() is None


def test_take_settings_error_note_is_none_while_settings_is_fine(tmp_path: Path) -> None:
    write_settings_json(tmp_path, effort_level="medium")
    machine = _mod.CompactStateMachine(_mod.CompactPolicy(settings_path=tmp_path / "settings.json"))
    machine._resolve_effort_for_family("opus", now_wall=1000.0)
    assert machine.take_settings_error_note() is None


def test_take_settings_error_note_is_none_for_a_simply_missing_file(tmp_path: Path) -> None:
    machine = _mod.CompactStateMachine(
        _mod.CompactPolicy(settings_path=tmp_path / "no-such-dir" / "settings.json")
    )
    machine._resolve_effort_for_family("opus", now_wall=1000.0)
    assert machine.take_settings_error_note() is None


# ── _resolve_effort_for_family: settings first, defaults second ────────────


def test_resolve_effort_for_family_uses_settings_when_present(tmp_path: Path) -> None:
    write_settings_json(tmp_path, effort_level="medium")
    machine = _mod.CompactStateMachine(_mod.CompactPolicy(settings_path=tmp_path / "settings.json"))
    assert machine._resolve_effort_for_family("opus") == "medium"


def test_resolve_effort_for_family_falls_back_to_defaults(tmp_path: Path) -> None:
    machine = _mod.CompactStateMachine(
        _mod.CompactPolicy(settings_path=tmp_path / "no-such-dir" / "settings.json")
    )
    assert machine._resolve_effort_for_family("opus") == _mod._DEFAULT_MIN_EFFORT_LEVELS["opus"]
    assert machine._resolve_effort_for_family("fable") == _mod._DEFAULT_MIN_EFFORT_LEVELS["fable"]


# ── CCY_MIN_EFFORT_LEVELS is retired: it no longer has any effect ──────────


def test_ccy_min_effort_levels_env_var_no_longer_exists_as_a_symbol() -> None:
    assert not hasattr(_mod, "_MIN_EFFORT_ENV_VAR")
    assert not hasattr(_mod, "_parse_min_effort_levels")
    assert not hasattr(_mod, "_min_effort_levels_from_env")


def test_ccy_min_effort_levels_env_var_is_ignored(monkeypatch, tmp_path: Path) -> None:
    # A retired override channel must not silently keep working: setting the
    # old env var must have NO effect on the resolved floor, whether or not
    # settings.json configures the family.
    monkeypatch.setenv("CCY_MIN_EFFORT_LEVELS", "opus=xhigh")
    machine = _mod.CompactStateMachine(
        _mod.CompactPolicy(settings_path=tmp_path / "no-such-dir" / "settings.json")
    )
    assert machine._resolve_effort_for_family("opus") == _mod._DEFAULT_MIN_EFFORT_LEVELS["opus"]

    write_settings_json(tmp_path, effort_level="medium")
    machine_with_settings = _mod.CompactStateMachine(
        _mod.CompactPolicy(settings_path=tmp_path / "settings.json")
    )
    assert machine_with_settings._resolve_effort_for_family("opus") == "medium"


def test_compact_policy_no_longer_accepts_min_effort_levels() -> None:
    import pytest

    with pytest.raises(TypeError):
        _mod.CompactPolicy(min_effort_levels={"opus": "xhigh"})


# ── Live settings.json fixture verification (Plan 00466 N47 grounding) ──────


def test_a_real_settings_json_with_per_model_and_top_level_parses_as_expected(
    tmp_path: Path,
) -> None:
    """Mirrors this repo's own live settings.json shape (both entries agree)."""
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "model": "opus",
                "effortLevel": "medium",
                "modelSettings": {
                    "claude-opus-5": {"effortLevel": "medium"},
                    "claude-opus-5-5": {"effortLevel": "medium"},
                },
            }
        ),
        encoding="utf-8",
    )
    settings = json.loads(path.read_text(encoding="utf-8"))
    assert _mod._resolve_family_effort(settings, "opus") == "medium"
    # No modelSettings entry names a fable model id, so fable falls through
    # to the top-level effortLevel -- still "medium", not None: settings.json
    # configures SOMETHING for every family via its top-level default.
    assert _mod._resolve_family_effort(settings, "fable") == "medium"
