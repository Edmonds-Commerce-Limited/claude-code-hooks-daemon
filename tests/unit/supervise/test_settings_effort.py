"""Plan 00466 N47 — settings.json is the single source of truth for effort.

Redesigned after adversarial review 1
(``subagent-reports/260925-n47-review1-opus-5-5.md``): the supervisor holds
almost no opinion of its own. Exactly two sanctioned interventions exist —
downgrade-episode xhigh compensation, and the Plan 00297 Fable anchor — and
every other family is corrected (in either direction) toward whatever
Claude Code's own settings.json resolves for the EXACT model id on screen,
across local/project/user files in Claude Code's own precedence. Nothing
configured means Claude Code's own per-model default already applies and is
never fought.

This file covers the resolver directly (multi-file precedence, per-model-id
matching, the user-file top-level cutoff, "max" rejection, the explicit env
override, and the cache's mtime reload / error reporting). The
episode/coupled-correction integration is covered in ``test_effort_restore.py``
and ``test_drop_anchor.py``, driven through ``decide_once``/``_poll_once``
with real sidecar sequences per the review's finding 6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.unit.supervise._load import load_supervisor_module
from tests.unit.supervise.conftest import write_settings_json

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()


# ── _claude_config_dir / _main_settings_path / project paths ───────────────


def test_claude_config_dir_env_var_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(_mod._CLAUDE_CONFIG_DIR_ENV_VAR, str(tmp_path / "custom"))
    assert _mod._claude_config_dir() == tmp_path / "custom"


def test_claude_config_dir_falls_back_to_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(_mod._CLAUDE_CONFIG_DIR_ENV_VAR, raising=False)
    monkeypatch.setattr(_mod.Path, "home", classmethod(lambda cls: tmp_path))
    assert _mod._claude_config_dir() == tmp_path / ".claude"


def test_main_settings_path_is_config_dir_slash_settings_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(_mod._CLAUDE_CONFIG_DIR_ENV_VAR, str(tmp_path))
    assert _mod._main_settings_path() == tmp_path / "settings.json"


def test_project_settings_path_uses_claude_project_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert _mod._project_settings_path() == tmp_path / ".claude" / "settings.json"
    assert _mod._local_settings_path() == tmp_path / ".claude" / "settings.local.json"


# ── _normalise_model_id ──────────────────────────────────────────────────────


def test_normalise_model_id_strips_1m_suffix() -> None:
    assert _mod._normalise_model_id("claude-opus-5-5[1m]") == "claude-opus-5-5"


def test_normalise_model_id_strips_date_suffix() -> None:
    assert _mod._normalise_model_id("claude-opus-5-5-20251101") == "claude-opus-5-5"


def test_normalise_model_id_strips_both() -> None:
    assert _mod._normalise_model_id("claude-opus-5-5-20251101[1m]") == "claude-opus-5-5"


def test_normalise_model_id_leaves_a_bare_id_alone() -> None:
    assert _mod._normalise_model_id("claude-opus-5-5") == "claude-opus-5-5"


# ── _model_settings_entry_effort: exact model id, never a sibling ──────────


def test_model_settings_entry_effort_exact_match() -> None:
    settings = {"modelSettings": {"claude-opus-5-5": {"effortLevel": "medium"}}}
    assert _mod._model_settings_entry_effort(settings, "claude-opus-5-5") == "medium"


def test_model_settings_entry_never_matches_a_sibling_model(tmp_path: Path) -> None:
    # Plan 00466 N47 finding 3: claude-opus-5 must never supply the value for
    # claude-opus-5-5, even though both belong to the "opus" family.
    settings = {
        "modelSettings": {
            "claude-opus-5": {"effortLevel": "xhigh"},
            "claude-opus-5-5": {"effortLevel": "medium"},
        }
    }
    assert _mod._model_settings_entry_effort(settings, "claude-opus-5-5") == "medium"
    assert _mod._model_settings_entry_effort(settings, "claude-opus-5") == "xhigh"


def test_model_settings_entry_matches_after_normalisation() -> None:
    settings = {"modelSettings": {"claude-opus-5-5": {"effortLevel": "medium"}}}
    assert _mod._model_settings_entry_effort(settings, "claude-opus-5-5-20251101[1m]") == "medium"


def test_model_settings_entry_with_no_matching_model_is_none() -> None:
    settings = {"modelSettings": {"claude-fable-5": {"effortLevel": "low"}}}
    assert _mod._model_settings_entry_effort(settings, "claude-opus-5-5") is None


def test_model_settings_entry_rejects_max() -> None:
    # Plan 00466 N47 finding 8: "max" is never a valid settings value.
    settings = {"modelSettings": {"claude-opus-5-5": {"effortLevel": "max"}}}
    assert _mod._model_settings_entry_effort(settings, "claude-opus-5-5") is None


def test_model_settings_entry_non_dict_entry_is_ignored() -> None:
    settings = {"modelSettings": {"claude-opus-5-5": "not-a-dict"}}
    assert _mod._model_settings_entry_effort(settings, "claude-opus-5-5") is None


def test_model_settings_entry_non_dict_model_settings_is_ignored() -> None:
    settings = {"modelSettings": "not-a-dict"}
    assert _mod._model_settings_entry_effort(settings, "claude-opus-5-5") is None


# ── _user_top_level_effort_applies: the Opus 5.5 cutoff ─────────────────────


def test_user_top_level_applies_to_pre_cutoff_opus() -> None:
    assert _mod._user_top_level_effort_applies("claude-opus-5") is True


def test_user_top_level_does_not_apply_to_opus_5_5() -> None:
    # Plan 00466 N47 finding 4.
    assert _mod._user_top_level_effort_applies("claude-opus-5-5") is False


def test_user_top_level_does_not_apply_to_a_later_opus() -> None:
    assert _mod._user_top_level_effort_applies("claude-opus-6") is False


def test_user_top_level_applies_to_non_opus_families() -> None:
    assert _mod._user_top_level_effort_applies("claude-fable-5-1") is True
    assert _mod._user_top_level_effort_applies("claude-sonnet-5") is True
    assert _mod._user_top_level_effort_applies("claude-haiku-4-5") is True


def test_user_top_level_does_not_apply_to_an_unparseable_opus_id() -> None:
    assert _mod._user_top_level_effort_applies("claude-opus-latest") is False


# ── _top_level_effort / _resolve_model_effort_from_settings ────────────────


def test_top_level_effort_applies_for_project_scope_even_to_opus_5_5() -> None:
    # Plan 00466 N47 finding 4: the cutoff is a USER-FILE-ONLY rule.
    settings = {"effortLevel": "medium"}
    assert _mod._top_level_effort(settings, scope="project", model_id="claude-opus-5-5") == "medium"
    assert _mod._top_level_effort(settings, scope="local", model_id="claude-opus-5-5") == "medium"


def test_top_level_effort_from_user_scope_is_withheld_for_opus_5_5() -> None:
    settings = {"effortLevel": "xhigh"}
    assert _mod._top_level_effort(settings, scope="user", model_id="claude-opus-5-5") is None


def test_top_level_effort_from_user_scope_still_applies_pre_cutoff() -> None:
    settings = {"effortLevel": "xhigh"}
    assert _mod._top_level_effort(settings, scope="user", model_id="claude-opus-5") == "xhigh"


def test_resolve_model_effort_from_settings_none_settings_is_none() -> None:
    assert (
        _mod._resolve_model_effort_from_settings(None, scope="user", model_id="claude-opus-5-5")
        is None
    )


def test_resolve_model_effort_from_settings_per_model_beats_top_level() -> None:
    settings = {
        "effortLevel": "high",
        "modelSettings": {"claude-opus-5-5": {"effortLevel": "medium"}},
    }
    assert (
        _mod._resolve_model_effort_from_settings(settings, scope="user", model_id="claude-opus-5-5")
        == "medium"
    )


def test_resolve_model_effort_from_settings_falls_through_to_top_level() -> None:
    settings = {"effortLevel": "medium"}
    assert (
        _mod._resolve_model_effort_from_settings(
            settings, scope="project", model_id="claude-opus-5-5"
        )
        == "medium"
    )


# ── SettingsEffortCache: missing / malformed / unreadable degrades cleanly ──


def test_cache_missing_file_resolves_to_none(tmp_path: Path) -> None:
    cache = _mod.SettingsEffortCache(tmp_path / "no-such-dir" / "settings.json")
    assert cache.settings() is None
    assert cache.last_error is not None
    assert "not found" in cache.last_error


def test_cache_malformed_json_resolves_to_none_with_a_logged_reason(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not valid json", encoding="utf-8")
    cache = _mod.SettingsEffortCache(path)
    assert cache.settings() is None
    assert cache.last_error is not None
    assert "settings.json" in cache.last_error


def test_cache_non_object_json_resolves_to_none_with_a_logged_reason(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    cache = _mod.SettingsEffortCache(path)
    assert cache.settings() is None
    assert cache.last_error is not None


def test_cache_unreadable_directory_resolves_to_none(tmp_path: Path) -> None:
    # A path whose PARENT is a file (not a directory) can never be stat()'d
    # successfully -- exercises the OSError branch without chmod tricks that
    # behave differently as root.
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    cache = _mod.SettingsEffortCache(blocker / "settings.json")
    assert cache.settings() is None


def test_cache_valid_settings_resolves(tmp_path: Path) -> None:
    write_settings_json(tmp_path, effort_level="medium")
    cache = _mod.SettingsEffortCache(tmp_path / "settings.json")
    settings = cache.settings()
    assert settings is not None
    assert settings["effortLevel"] == "medium"
    assert cache.last_error is None


# ── SettingsEffortCache: re-read on change (Task 5, no relaunch needed) ─────


def test_cache_picks_up_an_edit_without_reconstruction(tmp_path: Path) -> None:
    write_settings_json(tmp_path, effort_level="medium")
    cache = _mod.SettingsEffortCache(tmp_path / "settings.json")
    settings = cache.settings(now_wall=1000.0)
    assert settings is not None and settings["effortLevel"] == "medium"
    write_settings_json(tmp_path, effort_level="high")
    (tmp_path / "settings.json").touch()  # ensure a distinct mtime on fast filesystems
    later = 1000.0 + _mod._SETTINGS_RELOAD_CHECK_SECONDS + 1.0
    settings = cache.settings(now_wall=later)
    assert settings is not None and settings["effortLevel"] == "high"


def test_cache_throttles_the_stat_check_within_the_window(tmp_path: Path) -> None:
    write_settings_json(tmp_path, effort_level="medium")
    cache = _mod.SettingsEffortCache(tmp_path / "settings.json")
    cache.settings(now_wall=1000.0)
    write_settings_json(tmp_path, effort_level="high")
    soon = 1000.0 + (_mod._SETTINGS_RELOAD_CHECK_SECONDS / 2.0)
    settings = cache.settings(now_wall=soon)
    assert settings is not None and settings["effortLevel"] == "medium"


def test_cache_recovers_once_a_missing_file_appears(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    cache = _mod.SettingsEffortCache(path)
    assert cache.settings(now_wall=1000.0) is None
    write_settings_json(tmp_path, effort_level="medium")
    later = 1000.0 + _mod._SETTINGS_RELOAD_CHECK_SECONDS + 1.0
    settings = cache.settings(now_wall=later)
    assert settings is not None and settings["effortLevel"] == "medium"


# ── CompactStateMachine._resolve_configured_effort: precedence + fallback ──


def _machine_with_settings(
    *,
    local: dict[str, object] | None = None,
    project: dict[str, object] | None = None,
    user: dict[str, object] | None = None,
    tmp_path: Path,
):
    # No return annotation, matching this test suite's other dynamically-
    # loaded-module helpers (e.g. `test_effort_restore.py`'s `_machine`):
    # `CompactStateMachine` is a runtime attribute of an `Any`-typed module,
    # not a usable mypy --strict type, and `-> object` would make every
    # caller's attribute access an error instead.
    import json

    def _write(sub: str, data: dict[str, object] | None) -> Path:
        directory = tmp_path / sub
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "settings.json"
        if data is not None:
            path.write_text(json.dumps(data), encoding="utf-8")
        return path

    local_path = _write("local", local)
    project_path = _write("project", project)
    user_path = _write("user", user)
    policy = _mod.CompactPolicy(
        local_settings_path=local_path, project_settings_path=project_path, settings_path=user_path
    )
    return _mod.CompactStateMachine(policy)


def test_resolve_configured_effort_uses_user_settings_when_present(tmp_path: Path) -> None:
    machine = _machine_with_settings(user={"effortLevel": "medium"}, tmp_path=tmp_path)
    assert machine._resolve_configured_effort(model_id="claude-opus-5") == "medium"


def test_resolve_configured_effort_falls_back_to_none_when_nothing_configured(
    tmp_path: Path,
) -> None:
    machine = _machine_with_settings(tmp_path=tmp_path)
    assert machine._resolve_configured_effort(model_id="claude-opus-5-5") is None


def test_resolve_configured_effort_project_overrides_user(tmp_path: Path) -> None:
    # Plan 00466 N47 finding 2.
    machine = _machine_with_settings(
        user={"effortLevel": "high"}, project={"effortLevel": "low"}, tmp_path=tmp_path
    )
    assert machine._resolve_configured_effort(model_id="claude-fable-5") == "low"


def test_resolve_configured_effort_local_overrides_project_and_user(tmp_path: Path) -> None:
    machine = _machine_with_settings(
        user={"effortLevel": "high"},
        project={"effortLevel": "medium"},
        local={"effortLevel": "low"},
        tmp_path=tmp_path,
    )
    assert machine._resolve_configured_effort(model_id="claude-fable-5") == "low"


def test_resolve_configured_effort_per_model_id_never_uses_a_sibling(tmp_path: Path) -> None:
    machine = _machine_with_settings(
        user={
            "modelSettings": {
                "claude-opus-5": {"effortLevel": "xhigh"},
                "claude-opus-5-5": {"effortLevel": "medium"},
            }
        },
        tmp_path=tmp_path,
    )
    assert machine._resolve_configured_effort(model_id="claude-opus-5-5") == "medium"


# ── CCY_MIN_EFFORT_LEVELS is retired: it no longer has any effect ──────────


def test_ccy_min_effort_levels_env_var_no_longer_exists_as_a_symbol() -> None:
    assert not hasattr(_mod, "_MIN_EFFORT_ENV_VAR")
    assert not hasattr(_mod, "_parse_min_effort_levels")
    assert not hasattr(_mod, "_min_effort_levels_from_env")
    assert not hasattr(_mod, "_DEFAULT_MIN_EFFORT_LEVELS")


def test_ccy_min_effort_levels_env_var_is_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CCY_MIN_EFFORT_LEVELS", "opus=xhigh")
    machine = _machine_with_settings(tmp_path=tmp_path)
    assert machine._resolve_configured_effort(model_id="claude-opus-5") is None


def test_compact_policy_no_longer_accepts_min_effort_levels() -> None:
    with pytest.raises(TypeError):
        _mod.CompactPolicy(min_effort_levels={"opus": "xhigh"})


# ── CLAUDE_CODE_EFFORT_LEVEL: an explicit choice outranks every file ────────


def test_explicit_effort_override_wins_over_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "xhigh")
    machine = _machine_with_settings(user={"effortLevel": "medium"}, tmp_path=tmp_path)
    assert machine._resolve_configured_effort(model_id="claude-opus-5") == "xhigh"


def test_explicit_effort_override_ignores_junk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "bogus")
    assert _mod._explicit_effort_override() is None


def test_explicit_effort_override_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDE_CODE_EFFORT_LEVEL", raising=False)
    assert _mod._explicit_effort_override() is None


# ── CompactStateMachine.take_settings_error_note ────────────────────────────


def test_take_settings_error_note_reports_missing_files_once(tmp_path: Path) -> None:
    machine = _machine_with_settings(tmp_path=tmp_path)
    machine._resolve_configured_effort(model_id="claude-opus-5", now_wall=1000.0)
    note = machine.take_settings_error_note()
    assert note is not None
    assert "not found" in note
    # Consumed -- the same still-missing files do not re-report every tick.
    machine._resolve_configured_effort(model_id="claude-opus-5", now_wall=1001.0)
    assert machine.take_settings_error_note() is None


def test_take_settings_error_note_reports_a_malformed_file(tmp_path: Path) -> None:
    (tmp_path / "user").mkdir()
    (tmp_path / "user" / "settings.json").write_text("{not valid json", encoding="utf-8")
    machine = _machine_with_settings(tmp_path=tmp_path)
    machine._resolve_configured_effort(model_id="claude-opus-5", now_wall=1000.0)
    note = machine.take_settings_error_note()
    assert note is not None
    assert "user=" in note


def test_take_settings_error_note_is_none_once_every_file_is_present_and_valid(
    tmp_path: Path,
) -> None:
    machine = _machine_with_settings(
        local={"effortLevel": "low"},
        project={"effortLevel": "medium"},
        user={"effortLevel": "high"},
        tmp_path=tmp_path,
    )
    machine._resolve_configured_effort(model_id="claude-opus-5", now_wall=1000.0)
    assert machine.take_settings_error_note() is None


# ── Finding 7: the note reaches decision.log, not just the resolver ────────


def test_missing_settings_is_logged_once_via_decide_once(tmp_path: Path) -> None:
    """A missing settings.json is said out loud in decision.log at startup.

    Plan 00466 N47 finding 7: silence here used to be indistinguishable from
    "nothing is wrong". Driven through the real `decide_once` entry point
    (not `take_settings_error_note` directly), with the log write wired the
    same way `_apply_decision` wires it in production.
    """
    machine = _mod.CompactStateMachine(_mod.CompactPolicy())
    facts = _mod.TickFacts(
        now_wall=1000.0,
        idle=True,
        input_line_empty=True,
        human_compact_submitted=False,
        work_idle=True,
    )
    outcome = _mod.decide_once(
        machine,
        sidecar_dir=tmp_path / "cs",
        facts=facts,
        dry_run=True,
        freshness_seconds=30.0,
    )
    assert outcome.settings_status_log is not None
    assert "settings.json status:" in outcome.settings_status_log
    assert "not found" in outcome.settings_status_log

    log_path = tmp_path / "decision.log"
    log = _mod.DecisionLog(log_path)
    if log is not None and outcome.settings_status_log is not None:
        log.write_noop(outcome.settings_status_log)
    contents = log_path.read_text(encoding="utf-8")
    assert "settings.json status:" in contents

    # The next tick observes the SAME still-missing files -- said once, not
    # on every tick.
    second = _mod.decide_once(
        machine,
        sidecar_dir=tmp_path / "cs",
        facts=facts,
        dry_run=True,
        freshness_seconds=30.0,
    )
    assert second.settings_status_log is None
