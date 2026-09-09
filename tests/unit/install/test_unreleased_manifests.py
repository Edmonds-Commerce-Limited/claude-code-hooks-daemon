"""Plan 00291 Task 2.3 — a branch install sees UNRELEASED manifests as pending.

A branch install is ahead of the last release, so the migrations it is ahead
on live in ``CLAUDE/UPGRADES/UNRELEASED/``. Both manifest loaders take
``include_unreleased``; when it is left unset they ask the install stamp and
include the staging directory exactly when the running install is a branch
install. A release install never sees them.

The staging directory is resolved as ``<manifests_dir>/../UNRELEASED/<name>``
so a test override of the released directory carries its own staging twin.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install import config_migrations, truth_changes
from claude_code_hooks_daemon.install.config_cli import run_check_config_migrations
from claude_code_hooks_daemon.install.config_migrations import (
    list_known_versions,
    load_manifests_between,
    unreleased_manifests_dir,
)
from claude_code_hooks_daemon.install.truth_changes import (
    list_known_truth_change_versions,
    load_truth_changes_between,
    run_check_truth_changes,
)

_CONFIG_MANIFEST = """\
version: "{version}"
date: "{date}"
breaking: false
config_changes:
  added:
    - key: "handlers.pre_tool_use.{handler}.enabled"
      description: "Added in {version}"
      example_yaml: "handlers:\\n  pre_tool_use:\\n    {handler}:\\n      enabled: true\\n"
  renamed: []
  removed: []
  changed: []
"""

_TRUTH_MANIFEST = """\
version: '{version}'
truth_changes:
  - was: Truth before {version}.
    now: Truth as of {version}.
"""


@pytest.fixture
def upgrades_tree(tmp_path: Path) -> Path:
    """``UPGRADES/`` with one released and one UNRELEASED manifest of each kind."""
    upgrades = tmp_path / "UPGRADES"
    released_cfg = upgrades / "config-changes"
    staged_cfg = upgrades / "UNRELEASED" / "config-changes"
    released_truth = upgrades / "truth-changes"
    staged_truth = upgrades / "UNRELEASED" / "truth-changes"
    for d in (released_cfg, staged_cfg, released_truth, staged_truth):
        d.mkdir(parents=True)
    (released_cfg / "v3.62.0.yaml").write_text(
        _CONFIG_MANIFEST.format(version="3.62.0", date="2026-08-01", handler="released_handler")
    )
    (staged_cfg / "v3.63.0.yaml").write_text(
        _CONFIG_MANIFEST.format(version="3.63.0", date="UNRELEASED", handler="staged_handler")
    )
    (staged_cfg / "README.md").write_text("# staging")
    (released_truth / "v3.62.0.yaml").write_text(_TRUTH_MANIFEST.format(version="3.62.0"))
    (staged_truth / "v3.63.0.yaml").write_text(_TRUTH_MANIFEST.format(version="3.63.0"))
    (staged_truth / "README.md").write_text("# staging")
    return upgrades


@pytest.fixture
def release_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_migrations, "is_branch_install", lambda: False)
    monkeypatch.setattr(truth_changes, "is_branch_install", lambda: False)


@pytest.fixture
def branch_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_migrations, "is_branch_install", lambda: True)
    monkeypatch.setattr(truth_changes, "is_branch_install", lambda: True)


class TestUnreleasedDirResolution:
    def test_staging_dir_is_the_released_dirs_twin_under_unreleased(self, tmp_path: Path) -> None:
        released = tmp_path / "UPGRADES" / "config-changes"
        assert unreleased_manifests_dir(released) == tmp_path / "UPGRADES" / "UNRELEASED" / (
            "config-changes"
        )


class TestConfigMigrationsIncludeUnreleased:
    def test_explicit_true_includes_the_staged_manifest(self, upgrades_tree: Path) -> None:
        manifests = load_manifests_between(
            "3.61.0",
            "3.63.0",
            manifests_dir=upgrades_tree / "config-changes",
            include_unreleased=True,
        )
        assert [m.version for m in manifests] == ["3.62.0", "3.63.0"]

    def test_explicit_false_excludes_it(self, upgrades_tree: Path) -> None:
        manifests = load_manifests_between(
            "3.61.0",
            "3.63.0",
            manifests_dir=upgrades_tree / "config-changes",
            include_unreleased=False,
        )
        assert [m.version for m in manifests] == ["3.62.0"]

    def test_range_still_applies_to_staged_manifests(self, upgrades_tree: Path) -> None:
        manifests = load_manifests_between(
            "3.61.0",
            "3.62.0",
            manifests_dir=upgrades_tree / "config-changes",
            include_unreleased=True,
        )
        assert [m.version for m in manifests] == ["3.62.0"]

    @pytest.mark.usefixtures("release_install")
    def test_unset_on_a_release_install_excludes_it(self, upgrades_tree: Path) -> None:
        manifests = load_manifests_between(
            "3.61.0", "3.63.0", manifests_dir=upgrades_tree / "config-changes"
        )
        assert [m.version for m in manifests] == ["3.62.0"]

    @pytest.mark.usefixtures("branch_install")
    def test_unset_on_a_branch_install_includes_it(self, upgrades_tree: Path) -> None:
        manifests = load_manifests_between(
            "3.61.0", "3.63.0", manifests_dir=upgrades_tree / "config-changes"
        )
        assert [m.version for m in manifests] == ["3.62.0", "3.63.0"]

    @pytest.mark.usefixtures("release_install")
    def test_known_versions_follow_the_same_switch(self, upgrades_tree: Path) -> None:
        released = upgrades_tree / "config-changes"
        assert list_known_versions(manifests_dir=released) == ["3.62.0"]
        assert list_known_versions(manifests_dir=released, include_unreleased=True) == [
            "3.62.0",
            "3.63.0",
        ]

    def test_missing_staging_dir_is_not_an_error(self, tmp_path: Path) -> None:
        released = tmp_path / "config-changes"
        released.mkdir()
        assert (
            load_manifests_between(
                "1.0.0", "2.0.0", manifests_dir=released, include_unreleased=True
            )
            == []
        )

    @pytest.mark.usefixtures("branch_install")
    def test_advisory_on_a_branch_install_surfaces_the_staged_option(
        self, upgrades_tree: Path, tmp_path: Path
    ) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text("version: '1.0'\nhandlers:\n  pre_tool_use: {}\n")
        result = run_check_config_migrations(
            from_version="3.61.0",
            to_version="3.63.0",
            user_config_path=config,
            manifests_dir=upgrades_tree / "config-changes",
        )
        keys = {s["key"] for s in result["suggestions"]}
        assert "handlers.pre_tool_use.staged_handler.enabled" in keys

    @pytest.mark.usefixtures("release_install")
    def test_advisory_on_a_release_install_does_not(
        self, upgrades_tree: Path, tmp_path: Path
    ) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text("version: '1.0'\nhandlers:\n  pre_tool_use: {}\n")
        result = run_check_config_migrations(
            from_version="3.61.0",
            to_version="3.63.0",
            user_config_path=config,
            manifests_dir=upgrades_tree / "config-changes",
        )
        keys = {s["key"] for s in result["suggestions"]}
        assert "handlers.pre_tool_use.staged_handler.enabled" not in keys
        assert "handlers.pre_tool_use.released_handler.enabled" in keys


class TestTruthChangesIncludeUnreleased:
    def test_explicit_true_includes_the_staged_manifest(self, upgrades_tree: Path) -> None:
        manifests = load_truth_changes_between(
            "3.61.0",
            "3.63.0",
            truth_changes_dir=upgrades_tree / "truth-changes",
            include_unreleased=True,
        )
        assert [m.version for m in manifests] == ["3.62.0", "3.63.0"]

    @pytest.mark.usefixtures("release_install")
    def test_unset_on_a_release_install_excludes_it(self, upgrades_tree: Path) -> None:
        manifests = load_truth_changes_between(
            "3.61.0", "3.63.0", truth_changes_dir=upgrades_tree / "truth-changes"
        )
        assert [m.version for m in manifests] == ["3.62.0"]

    @pytest.mark.usefixtures("branch_install")
    def test_unset_on_a_branch_install_includes_it(self, upgrades_tree: Path) -> None:
        manifests = load_truth_changes_between(
            "3.61.0", "3.63.0", truth_changes_dir=upgrades_tree / "truth-changes"
        )
        assert [m.version for m in manifests] == ["3.62.0", "3.63.0"]

    @pytest.mark.usefixtures("release_install")
    def test_known_versions_follow_the_same_switch(self, upgrades_tree: Path) -> None:
        released = upgrades_tree / "truth-changes"
        assert list_known_truth_change_versions(truth_changes_dir=released) == ["3.62.0"]
        assert list_known_truth_change_versions(
            truth_changes_dir=released, include_unreleased=True
        ) == ["3.62.0", "3.63.0"]

    @pytest.mark.usefixtures("release_install")
    def test_run_check_passes_the_switch_through(self, upgrades_tree: Path) -> None:
        result = run_check_truth_changes(
            "3.61.0",
            "3.63.0",
            truth_changes_dir=upgrades_tree / "truth-changes",
            include_unreleased=True,
        )
        assert [c["version"] for c in result["changes"]] == ["3.62.0", "3.63.0"]
