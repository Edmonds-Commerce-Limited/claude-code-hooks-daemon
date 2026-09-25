"""Tests for the enabled Claude Code plugin resolver (Plan 00468 Task 2.1).

Every test builds a fake config dir, project and managed-settings dir under
``tmp_path`` and passes all three in: the real Claude home is never read.

The rules under test come from the Claude Code docs (plugins-reference,
settings-reference, managed-settings):

- ``enabledPlugins`` may be set in user, project, local and managed settings;
  managed beats local beats project beats user, and a plugin with no entry
  anywhere falls back to its ``defaultEnabled`` (default true).
- ``<config>/plugins/installed_plugins.json`` records each install's scope,
  ``installPath`` and, for project and local installs, ``projectPath``.
- Components come from default locations (``agents/``, ``skills/``,
  ``commands/``, ``hooks/hooks.json``, ``.lsp.json``) and the manifest's
  component fields, and a marketplace entry adds to them (``strict: true``,
  the default) or replaces them (``strict: false``).
- A plugin agent's id is ``<plugin>[:<subdir>...]:<name>``; frontmatter
  ``name`` replaces only the file name, and a manifest ``agents`` file drops
  the subfolders.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.utils.claude_plugins import (
    PluginInventory,
    SettingsScope,
    SkillKind,
    canonical_repo_root,
    default_managed_settings_dir,
    resolve_enabled_plugins,
)


class _Env:
    """A fake Claude config dir, project and managed-settings dir."""

    def __init__(self, tmp_path: Path) -> None:
        self.base = tmp_path
        self.config = tmp_path / "config"
        self.project = tmp_path / "project"
        self.managed = tmp_path / "managed"
        (self.config / "plugins").mkdir(parents=True)
        (self.project / ".claude").mkdir(parents=True)
        self._installs: dict[str, list[dict[str, Any]]] = {}

    def plugin_root(self, name: str, manifest: dict[str, Any] | None = None) -> Path:
        root = self.config / "plugins" / "cache" / "mkt" / name / "1.0.0"
        root.mkdir(parents=True, exist_ok=True)
        if manifest is not None:
            _write_json(root / ".claude-plugin" / "plugin.json", manifest)
        return root

    def install(
        self,
        plugin_id: str,
        root: Path,
        *,
        scope: str = "user",
        project_path: Path | None = None,
    ) -> None:
        entry: dict[str, Any] = {"scope": scope, "installPath": str(root), "version": "1.0.0"}
        if project_path is not None:
            entry["projectPath"] = str(project_path)
        self._installs.setdefault(plugin_id, []).append(entry)
        _write_json(
            self.config / "plugins" / "installed_plugins.json",
            {"version": 2, "plugins": self._installs},
        )

    def enable(self, scope: SettingsScope, plugin_id: str, value: bool = True) -> None:
        path = {
            SettingsScope.USER: self.config / "settings.json",
            SettingsScope.PROJECT: self.project / ".claude" / "settings.json",
            SettingsScope.LOCAL: self.project / ".claude" / "settings.local.json",
            SettingsScope.MANAGED: self.managed / "managed-settings.json",
        }[scope]
        settings = json.loads(path.read_text()) if path.exists() else {}
        settings.setdefault("enabledPlugins", {})[plugin_id] = value
        _write_json(path, settings)

    def marketplace(self, name: str, entries: list[dict[str, Any]]) -> Path:
        location = self.config / "plugins" / "marketplaces" / name
        _write_json(location / ".claude-plugin" / "marketplace.json", {"plugins": entries})
        known_path = self.config / "plugins" / "known_marketplaces.json"
        known = json.loads(known_path.read_text()) if known_path.exists() else {}
        known[name] = {"installLocation": str(location)}
        _write_json(known_path, known)
        return location

    def resolve(self) -> PluginInventory:
        return resolve_enabled_plugins(
            self.project, config_dir=self.config, managed_dir=self.managed
        )


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _agent(root: Path, relative: str, frontmatter: str | None) -> None:
    body = "Body.\n" if frontmatter is None else f"---\n{frontmatter}\n---\n\nBody.\n"
    _write(root / relative, body)


@pytest.fixture
def env(tmp_path: Path) -> _Env:
    return _Env(tmp_path)


def _ids(inventory: PluginInventory) -> list[str]:
    return [plugin.plugin_id for plugin in inventory.enabled]


# ── Which plugins are enabled ────────────────────────────────────────


class TestEnablement:
    def test_a_user_install_enabled_at_user_scope_resolves(self, env: _Env) -> None:
        env.install("p@mkt", env.plugin_root("p", {"name": "p"}))
        env.enable(SettingsScope.USER, "p@mkt")
        inventory = env.resolve()
        assert _ids(inventory) == ["p@mkt"]
        plugin = inventory.enabled[0]
        assert plugin.name == "p"
        assert plugin.marketplace == "mkt"
        assert plugin.enabled_by is SettingsScope.USER
        assert plugin.install_scope == "user"
        assert plugin.version == "1.0.0"

    def test_no_entry_anywhere_falls_back_to_default_enabled_true(self, env: _Env) -> None:
        env.install("p@mkt", env.plugin_root("p", {"name": "p"}))
        inventory = env.resolve()
        assert _ids(inventory) == ["p@mkt"]
        assert inventory.enabled[0].enabled_by is None

    def test_default_enabled_false_with_no_entry_is_not_enabled(self, env: _Env) -> None:
        env.install("p@mkt", env.plugin_root("p", {"name": "p", "defaultEnabled": False}))
        assert _ids(env.resolve()) == []

    def test_the_marketplace_default_enabled_beats_the_manifest(self, env: _Env) -> None:
        env.install("p@mkt", env.plugin_root("p", {"name": "p", "defaultEnabled": True}))
        env.marketplace("mkt", [{"name": "p", "source": "./p", "defaultEnabled": False}])
        assert _ids(env.resolve()) == []

    def test_project_true_beats_user_false(self, env: _Env) -> None:
        env.install("p@mkt", env.plugin_root("p", {"name": "p"}))
        env.enable(SettingsScope.USER, "p@mkt", False)
        env.enable(SettingsScope.PROJECT, "p@mkt", True)
        inventory = env.resolve()
        assert _ids(inventory) == ["p@mkt"]
        assert inventory.enabled[0].enabled_by is SettingsScope.PROJECT

    def test_local_false_beats_project_true(self, env: _Env) -> None:
        env.install("p@mkt", env.plugin_root("p", {"name": "p"}))
        env.enable(SettingsScope.PROJECT, "p@mkt", True)
        env.enable(SettingsScope.LOCAL, "p@mkt", False)
        inventory = env.resolve()
        assert _ids(inventory) == []
        assert inventory.unresolved == ()

    def test_managed_false_beats_local_true(self, env: _Env) -> None:
        env.install("p@mkt", env.plugin_root("p", {"name": "p"}))
        env.enable(SettingsScope.LOCAL, "p@mkt", True)
        env.enable(SettingsScope.MANAGED, "p@mkt", False)
        assert _ids(env.resolve()) == []

    def test_managed_drop_ins_merge_after_the_main_file(self, env: _Env) -> None:
        env.install("p@mkt", env.plugin_root("p", {"name": "p"}))
        env.enable(SettingsScope.MANAGED, "p@mkt", True)
        _write_json(
            env.managed / "managed-settings.d" / "20-off.json",
            {"enabledPlugins": {"p@mkt": False}},
        )
        assert _ids(env.resolve()) == []

    def test_a_non_boolean_value_is_ignored(self, env: _Env) -> None:
        env.install("p@mkt", env.plugin_root("p", {"name": "p"}))
        env.enable(SettingsScope.USER, "p@mkt", True)
        path = env.project / ".claude" / "settings.json"
        _write_json(path, {"enabledPlugins": {"p@mkt": "yes"}})
        inventory = env.resolve()
        assert inventory.enabled[0].enabled_by is SettingsScope.USER


class TestInstallScope:
    def test_a_project_install_for_this_project_resolves(self, env: _Env) -> None:
        """The dogfood shape: installed at project scope, enabled at local."""
        env.install(
            "p@mkt", env.plugin_root("p", {"name": "p"}), scope="project", project_path=env.project
        )
        env.enable(SettingsScope.LOCAL, "p@mkt")
        inventory = env.resolve()
        assert _ids(inventory) == ["p@mkt"]
        assert inventory.enabled[0].install_scope == "project"
        assert inventory.enabled[0].enabled_by is SettingsScope.LOCAL

    def test_a_project_install_for_another_project_is_unresolved(self, env: _Env) -> None:
        env.install(
            "p@mkt",
            env.plugin_root("p", {"name": "p"}),
            scope="project",
            project_path=env.base / "other",
        )
        env.enable(SettingsScope.PROJECT, "p@mkt")
        inventory = env.resolve()
        assert _ids(inventory) == []
        assert [u.plugin_id for u in inventory.unresolved] == ["p@mkt"]
        assert "another project" in inventory.unresolved[0].reason

    def test_a_local_install_needs_the_matching_project_path_too(self, env: _Env) -> None:
        env.install(
            "p@mkt", env.plugin_root("p", {"name": "p"}), scope="local", project_path=env.base / "x"
        )
        env.enable(SettingsScope.USER, "p@mkt")
        assert _ids(env.resolve()) == []

    def test_project_path_is_compared_after_resolving_symlinks(self, env: _Env) -> None:
        link = env.base / "project-link"
        link.symlink_to(env.project)
        env.install(
            "p@mkt", env.plugin_root("p", {"name": "p"}), scope="project", project_path=link
        )
        env.enable(SettingsScope.LOCAL, "p@mkt")
        assert _ids(env.resolve()) == ["p@mkt"]

    def test_the_project_install_is_preferred_over_a_user_install(self, env: _Env) -> None:
        user_root = env.plugin_root("p", {"name": "p"})
        project_root = env.config / "plugins" / "cache" / "mkt" / "p" / "2.0.0"
        _write_json(project_root / ".claude-plugin" / "plugin.json", {"name": "p"})
        env.install("p@mkt", user_root)
        env.install("p@mkt", project_root, scope="project", project_path=env.project)
        env.enable(SettingsScope.USER, "p@mkt")
        assert env.resolve().enabled[0].install_path == project_root

    def test_enabled_but_not_installed_is_unresolved(self, env: _Env) -> None:
        env.enable(SettingsScope.USER, "ghost@mkt")
        inventory = env.resolve()
        assert _ids(inventory) == []
        assert inventory.unresolved[0].plugin_id == "ghost@mkt"
        assert inventory.unresolved[0].enabled_by is SettingsScope.USER
        assert "not installed" in inventory.unresolved[0].reason

    def test_an_id_with_no_marketplace_is_unresolved(self, env: _Env) -> None:
        """This container's user settings enable a bare `phpantom-lsp`."""
        env.enable(SettingsScope.USER, "phpantom-lsp")
        inventory = env.resolve()
        assert inventory.unresolved[0].plugin_id == "phpantom-lsp"

    def test_an_install_path_that_is_gone_is_unresolved(self, env: _Env) -> None:
        env.install("p@mkt", env.base / "deleted")
        env.enable(SettingsScope.USER, "p@mkt")
        inventory = env.resolve()
        assert _ids(inventory) == []
        assert "install path" in inventory.unresolved[0].reason

    def test_no_installed_plugins_file_is_an_empty_inventory(self, env: _Env) -> None:
        inventory = env.resolve()
        assert inventory.enabled == ()
        assert inventory.config_dir == env.config

    def test_a_malformed_installed_plugins_file_is_an_empty_inventory(self, env: _Env) -> None:
        _write(env.config / "plugins" / "installed_plugins.json", "{not json")
        env.enable(SettingsScope.USER, "p@mkt")
        inventory = env.resolve()
        assert inventory.enabled == ()
        assert [u.plugin_id for u in inventory.unresolved] == ["p@mkt"]

    def test_a_malformed_settings_file_is_skipped(self, env: _Env) -> None:
        env.install("p@mkt", env.plugin_root("p", {"name": "p"}))
        env.enable(SettingsScope.USER, "p@mkt")
        _write(env.project / ".claude" / "settings.json", "{not json")
        assert _ids(env.resolve()) == ["p@mkt"]


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _repo_with_worktree(main: Path, worktree: Path) -> None:
    """``main`` as a git repo with one commit, and ``worktree`` linked to it."""
    main.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=main)
    _write(main / "README.md", "x\n")
    _git("add", "README.md", cwd=main)
    _git("commit", "-q", "--no-verify", "-m", "init", cwd=main)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "-q", "--detach", str(worktree), cwd=main)


class TestProjectInstallFromAWorktree:
    """Claude Code applies a project or local install record in any linked
    worktree of the same repository, not only at its ``projectPath``.

    Read from Claude Code's shipped bundle: a record applies when its scope is
    user or managed, when ``projectPath`` equals the session's project, or when
    both paths have the same canonical repository root, which for a linked
    worktree is the main checkout (``.git`` file -> ``gitdir`` -> ``commondir``,
    with the ``gitdir`` back-pointer checked).
    """

    def test_a_main_checkout_install_is_active_in_its_worktree(self, env: _Env) -> None:
        worktree = env.base / "untracked" / "worktrees" / "wt"
        _repo_with_worktree(env.project, worktree)
        env.install(
            "p@mkt", env.plugin_root("p", {"name": "p"}), scope="project", project_path=env.project
        )
        _write_json(
            worktree / ".claude" / "settings.local.json", {"enabledPlugins": {"p@mkt": True}}
        )
        inventory = resolve_enabled_plugins(
            worktree, config_dir=env.config, managed_dir=env.managed
        )
        assert _ids(inventory) == ["p@mkt"]
        assert inventory.enabled[0].enabled_by is SettingsScope.LOCAL

    def test_a_separate_clone_is_still_another_project(self, env: _Env) -> None:
        clone = env.base / "clone"
        _repo_with_worktree(env.project, env.base / "wt")
        clone.mkdir()
        _git("init", "-q", cwd=clone)
        env.install(
            "p@mkt", env.plugin_root("p", {"name": "p"}), scope="project", project_path=env.project
        )
        _write_json(clone / ".claude" / "settings.local.json", {"enabledPlugins": {"p@mkt": True}})
        inventory = resolve_enabled_plugins(clone, config_dir=env.config, managed_dir=env.managed)
        assert _ids(inventory) == []


class TestCanonicalRepoRoot:
    def test_a_main_checkout_is_its_own_root(self, tmp_path: Path) -> None:
        main = tmp_path / "main"
        _repo_with_worktree(main, tmp_path / "wt")
        assert canonical_repo_root(main / "sub" / "dir") == main.resolve()

    def test_a_linked_worktree_maps_to_the_main_checkout(self, tmp_path: Path) -> None:
        main = tmp_path / "main"
        worktree = tmp_path / "untracked" / "worktrees" / "wt"
        _repo_with_worktree(main, worktree)
        assert canonical_repo_root(worktree) == main.resolve()

    def test_outside_any_repository_there_is_none(self, tmp_path: Path) -> None:
        assert canonical_repo_root(tmp_path) is None

    def test_a_gitdir_that_does_not_point_back_is_not_followed(self, tmp_path: Path) -> None:
        """A `.git` file naming another repository's worktree entry, whose
        `gitdir` back-pointer is not this checkout, leaves this checkout its
        own root: a planted file cannot borrow another project's installs."""
        main = tmp_path / "main"
        _repo_with_worktree(main, tmp_path / "wt")
        impostor = tmp_path / "impostor"
        impostor.mkdir()
        entry = next((main / ".git" / "worktrees").iterdir())
        (impostor / ".git").write_text(f"gitdir: {entry}\n")
        assert canonical_repo_root(impostor) == impostor.resolve()


# ── Agents ──────────────────────────────────────────────────────────


class TestAgents:
    def _resolved(self, env: _Env, manifest: dict[str, Any] | None = None) -> Path:
        root = env.plugin_root("p", manifest if manifest is not None else {"name": "p"})
        env.install("p@mkt", root)
        env.enable(SettingsScope.USER, "p@mkt")
        return root

    def test_a_default_agent_is_scoped_by_its_name(self, env: _Env) -> None:
        root = self._resolved(env)
        _agent(root, "agents/reviewer.md", "name: reviewer\ntools: Read, Grep")
        agent = env.resolve().find_agent("p:reviewer")
        assert agent is not None
        assert agent.frontmatter["tools"] == "Read, Grep"
        assert agent.path == root / "agents" / "reviewer.md"

    def test_subfolders_join_the_scoped_id(self, env: _Env) -> None:
        root = self._resolved(env)
        _agent(root, "agents/review/security.md", "description: d")
        assert env.resolve().find_agent("p:review:security") is not None

    def test_frontmatter_name_replaces_only_the_file_name(self, env: _Env) -> None:
        root = self._resolved(env)
        _agent(root, "agents/review/security.md", "name: audit")
        inventory = env.resolve()
        assert inventory.find_agent("p:review:audit") is not None
        assert inventory.find_agent("p:review:security") is None

    def test_an_agent_with_no_frontmatter_is_named_after_its_file(self, env: _Env) -> None:
        """Claude Code loads a plugin agent whose frontmatter is missing or
        does not parse, names it after the file and ignores every field."""
        root = self._resolved(env)
        _agent(root, "agents/plain.md", None)
        agent = env.resolve().find_agent("p:plain")
        assert agent is not None
        assert agent.frontmatter == {}

    def test_a_colon_in_the_description_does_not_lose_the_fields(self, env: _Env) -> None:
        root = self._resolved(env)
        _agent(root, "agents/r.md", "name: r\ndescription: issues: many\ntools: Read")
        agent = env.resolve().find_agent("p:r")
        assert agent is not None
        assert agent.frontmatter["tools"] == "Read"

    def test_a_manifest_agents_field_replaces_the_default_and_drops_subfolders(
        self, env: _Env
    ) -> None:
        root = self._resolved(env, {"name": "p", "agents": ["./custom/review/security.md"]})
        _agent(root, "custom/review/security.md", "description: d")
        _agent(root, "agents/ignored.md", "description: d")
        inventory = env.resolve()
        assert inventory.find_agent("p:security") is not None
        assert inventory.find_agent("p:ignored") is None

    def test_a_manifest_path_escaping_the_plugin_root_is_refused(self, env: _Env) -> None:
        root = self._resolved(env, {"name": "p", "agents": "../outside.md"})
        _agent(root.parent, "outside.md", "description: d")
        inventory = env.resolve()
        assert inventory.enabled[0].agents == ()
        assert inventory.enabled[0].problems

    def test_the_manifest_name_namespaces_components(self, env: _Env) -> None:
        root = env.plugin_root("p", {"name": "renamed"})
        env.install("p@mkt", root)
        _agent(root, "agents/a.md", "description: d")
        assert env.resolve().find_agent("renamed:a") is not None

    def test_no_manifest_uses_the_id_name(self, env: _Env) -> None:
        root = env.plugin_root("p")
        env.install("p@mkt", root)
        _agent(root, "agents/a.md", "description: d")
        assert env.resolve().find_agent("p:a") is not None

    def test_an_unknown_id_is_none(self, env: _Env) -> None:
        self._resolved(env)
        assert env.resolve().find_agent("p:nothing") is None


# ── Skills and commands ─────────────────────────────────────────────


class TestSkills:
    def _root(self, env: _Env, manifest: dict[str, Any] | None = None) -> Path:
        root = env.plugin_root("p", manifest if manifest is not None else {"name": "p"})
        env.install("p@mkt", root)
        return root

    def _names(self, env: _Env) -> dict[str, SkillKind]:
        return {skill.scoped_name: skill.kind for skill in env.resolve().enabled[0].skills}

    def test_a_skills_directory_entry_uses_its_frontmatter_name(self, env: _Env) -> None:
        root = self._root(env)
        _write(root / "skills" / "dir-name" / "SKILL.md", "---\nname: dbf\ndescription: d\n---\n")
        assert self._names(env) == {"p:dbf": SkillKind.SKILL}

    def test_a_skill_without_a_name_uses_its_directory(self, env: _Env) -> None:
        root = self._root(env)
        _write(root / "skills" / "tidy" / "SKILL.md", "---\ndescription: d\n---\n")
        assert self._names(env) == {"p:tidy": SkillKind.SKILL}

    def test_a_manifest_skills_path_adds_to_the_default(self, env: _Env) -> None:
        root = self._root(env, {"name": "p", "skills": "./extra/"})
        _write(root / "skills" / "a" / "SKILL.md", "---\ndescription: d\n---\n")
        _write(root / "extra" / "b" / "SKILL.md", "---\ndescription: d\n---\n")
        assert set(self._names(env)) == {"p:a", "p:b"}

    def test_a_root_skill_md_is_a_single_skill_plugin(self, env: _Env) -> None:
        root = self._root(env)
        _write(root / "SKILL.md", "---\nname: solo\ndescription: d\n---\n")
        assert self._names(env) == {"p:solo": SkillKind.SKILL}

    def test_commands_are_flat_markdown_named_by_stem(self, env: _Env) -> None:
        root = self._root(env)
        _write(root / "commands" / "ship.md", "---\ndescription: d\n---\n")
        assert self._names(env) == {"p:ship": SkillKind.COMMAND}

    def test_a_manifest_commands_field_replaces_the_default(self, env: _Env) -> None:
        root = self._root(env, {"name": "p", "commands": ["./special/deploy.md"]})
        _write(root / "commands" / "ignored.md", "x")
        _write(root / "special" / "deploy.md", "x")
        assert self._names(env) == {"p:deploy": SkillKind.COMMAND}

    def test_the_skill_frontmatter_is_exposed(self, env: _Env) -> None:
        root = self._root(env)
        _write(root / "skills" / "a" / "SKILL.md", "---\ndescription: does a thing\n---\n")
        skill = env.resolve().enabled[0].skills[0]
        assert skill.frontmatter["description"] == "does a thing"


# ── Hooks ───────────────────────────────────────────────────────────


_EVENT_MAP: dict[str, Any] = {
    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "x"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "y"}]}],
}


class TestHooks:
    def _root(self, env: _Env, manifest: dict[str, Any] | None = None) -> Path:
        root = env.plugin_root("p", manifest if manifest is not None else {"name": "p"})
        env.install("p@mkt", root)
        return root

    def test_hooks_json_is_read(self, env: _Env) -> None:
        root = self._root(env)
        _write_json(root / "hooks" / "hooks.json", {"hooks": _EVENT_MAP})
        plugin = env.resolve().enabled[0]
        assert plugin.hook_events == ("PreToolUse", "Stop")
        assert plugin.hooks[0].path == root / "hooks" / "hooks.json"

    def test_inline_manifest_hooks_are_read(self, env: _Env) -> None:
        self._root(env, {"name": "p", "hooks": _EVENT_MAP})
        plugin = env.resolve().enabled[0]
        assert plugin.hook_events == ("PreToolUse", "Stop")
        assert plugin.hooks[0].path is None

    def test_a_manifest_hooks_path_is_read_alongside_the_default(self, env: _Env) -> None:
        root = self._root(env, {"name": "p", "hooks": "./more-hooks.json"})
        _write_json(root / "hooks" / "hooks.json", {"hooks": {"Stop": []}})
        _write_json(root / "more-hooks.json", {"hooks": {"SessionStart": []}})
        assert env.resolve().enabled[0].hook_events == ("SessionStart", "Stop")

    def test_the_default_file_named_again_in_the_manifest_is_read_once(self, env: _Env) -> None:
        root = self._root(env, {"name": "p", "hooks": "./hooks/hooks.json"})
        _write_json(root / "hooks" / "hooks.json", {"hooks": {"Stop": []}})
        assert len(env.resolve().enabled[0].hooks) == 1

    def test_malformed_hooks_json_is_a_problem_not_a_crash(self, env: _Env) -> None:
        root = self._root(env)
        _write(root / "hooks" / "hooks.json", "{nope")
        plugin = env.resolve().enabled[0]
        assert plugin.hooks == ()
        assert plugin.problems

    def test_no_hooks_is_empty(self, env: _Env) -> None:
        self._root(env)
        assert env.resolve().enabled[0].hook_events == ()


# ── LSP servers ─────────────────────────────────────────────────────


_GO_SERVER: dict[str, Any] = {"go": {"command": "gopls", "extensionToLanguage": {".go": "go"}}}


class TestLspServers:
    def test_dot_lsp_json_is_read(self, env: _Env) -> None:
        root = env.plugin_root("p", {"name": "p"})
        env.install("p@mkt", root)
        _write_json(root / ".lsp.json", _GO_SERVER)
        server = env.resolve().enabled[0].lsp_servers[0]
        assert server.name == "go"
        assert server.command == "gopls"
        assert dict(server.extension_to_language) == {".go": "go"}

    def test_inline_manifest_lsp_servers_are_read(self, env: _Env) -> None:
        env.install("p@mkt", env.plugin_root("p", {"name": "p", "lspServers": _GO_SERVER}))
        assert env.resolve().enabled[0].lsp_servers[0].name == "go"

    def test_a_strict_false_marketplace_entry_is_the_whole_definition(self, env: _Env) -> None:
        """The official LSP plugins' shape: the cache holds only a README and
        LICENSE, and the marketplace entry declares the server."""
        root = env.plugin_root("pyright-lsp")
        env.install("pyright-lsp@mkt", root)
        env.marketplace(
            "mkt",
            [
                {
                    "name": "pyright-lsp",
                    "source": "./plugins/pyright-lsp",
                    "strict": False,
                    "lspServers": {
                        "pyright": {
                            "command": "pyright-langserver",
                            "extensionToLanguage": {".py": "python", ".pyi": "python"},
                        }
                    },
                }
            ],
        )
        inventory = env.resolve()
        assert [s.name for s in inventory.lsp_servers()] == ["pyright"]
        assert inventory.lsp_servers()[0].extensions == (".py", ".pyi")

    def test_a_strict_true_marketplace_entry_adds_to_the_manifest(self, env: _Env) -> None:
        env.install("p@mkt", env.plugin_root("p", {"name": "p", "lspServers": _GO_SERVER}))
        rust = {"rs": {"command": "ra", "extensionToLanguage": {".rs": "rust"}}}
        env.marketplace("mkt", [{"name": "p", "lspServers": rust}])
        assert {s.name for s in env.resolve().enabled[0].lsp_servers} == {"go", "rs"}

    def test_strict_false_with_manifest_components_is_a_problem(self, env: _Env) -> None:
        """The docs: that combination is a conflict and the plugin fails to load."""
        env.install("p@mkt", env.plugin_root("p", {"name": "p", "lspServers": _GO_SERVER}))
        env.marketplace("mkt", [{"name": "p", "strict": False, "lspServers": _GO_SERVER}])
        inventory = env.resolve()
        assert _ids(inventory) == []
        assert "strict" in inventory.unresolved[0].reason

    def test_a_server_without_extension_mapping_has_no_extensions(self, env: _Env) -> None:
        env.install(
            "p@mkt", env.plugin_root("p", {"name": "p", "lspServers": {"x": {"command": "x"}}})
        )
        assert env.resolve().enabled[0].lsp_servers[0].extensions == ()


# ── Inventory helpers ───────────────────────────────────────────────


class TestInventory:
    def test_flattened_views_cover_every_enabled_plugin(self, env: _Env) -> None:
        for name in ("a", "b"):
            root = env.plugin_root(name, {"name": name})
            env.install(f"{name}@mkt", root)
            _agent(root, "agents/x.md", "description: d")
            _write(root / "skills" / "s" / "SKILL.md", "---\ndescription: d\n---\n")
        inventory = env.resolve()
        assert sorted(a.scoped_id for a in inventory.agents()) == ["a:x", "b:x"]
        assert sorted(s.scoped_name for s in inventory.skills()) == ["a:s", "b:s"]

    def test_the_plugins_are_ordered_by_id(self, env: _Env) -> None:
        for name in ("zeta", "alpha"):
            env.install(f"{name}@mkt", env.plugin_root(name, {"name": name}))
        assert _ids(env.resolve()) == ["alpha@mkt", "zeta@mkt"]


# ── Degraded input ──────────────────────────────────────────────────


class TestDegradedInput:
    """Nothing raises: a bad value is skipped and recorded on the plugin."""

    def test_a_non_string_path_value_is_a_problem(self, env: _Env) -> None:
        env.install("p@mkt", env.plugin_root("p", {"name": "p", "agents": [7]}))
        plugin = env.resolve().enabled[0]
        assert plugin.agents == ()
        assert any("non-path" in problem for problem in plugin.problems)

    def test_a_skills_path_naming_one_skill_directory_loads_it(self, env: _Env) -> None:
        root = env.plugin_root("p", {"name": "p", "skills": ["./extra/only"]})
        env.install("p@mkt", root)
        _write(root / "extra" / "only" / "SKILL.md", "---\ndescription: d\n---\n")
        assert [s.scoped_name for s in env.resolve().enabled[0].skills] == ["p:only"]

    def test_a_malformed_lsp_file_is_a_problem(self, env: _Env) -> None:
        root = env.plugin_root("p", {"name": "p"})
        env.install("p@mkt", root)
        _write(root / ".lsp.json", "[1, 2]")
        plugin = env.resolve().enabled[0]
        assert plugin.lsp_servers == ()
        assert plugin.problems

    def test_an_unreadable_agent_file_is_a_problem(self, env: _Env) -> None:
        root = env.plugin_root("p", {"name": "p"})
        env.install("p@mkt", root)
        _write(root / "agents" / "bad.md", "")
        (root / "agents" / "bad.md").write_bytes(b"\xff\xfe not utf-8")
        plugin = env.resolve().enabled[0]
        assert [a.scoped_id for a in plugin.agents] == ["p:bad"]
        assert plugin.agents[0].frontmatter == {}
        assert any("cannot read" in problem for problem in plugin.problems)

    def test_the_managed_dir_defaults_to_the_platform_location(self) -> None:
        assert default_managed_settings_dir().name in {"claude-code", "ClaudeCode"}
