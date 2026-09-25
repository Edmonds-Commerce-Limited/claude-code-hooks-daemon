"""A fake installed Claude Code plugin for tests (Plan 00468).

Builds just enough of a Claude config dir for
``claude_code_hooks_daemon.utils.claude_plugins.resolve_enabled_plugins`` to
find a plugin: the plugin root under ``<config>/plugins/cache/``, its
``installed_plugins.json`` record, and an ``enabledPlugins`` entry. Every
caller passes a ``tmp_path`` config dir, so the real Claude home is never
touched.

The default shape is the Defence Before Fix plugin as this repository first
installed it: project scope, ``projectPath`` set, enabled at local scope.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

#: The two DBF agents' real frontmatter shape: no Write in ``tools``.
READ_ONLY_TOOLS: Final[str] = "Read, Grep, Glob, Bash"


def install_fake_plugin(
    config_dir: Path,
    project_root: Path,
    *,
    plugin: str = "defence-before-fix",
    marketplace: str = "defence-before-fix",
    agents: dict[str, str | None] | None = None,
    skills: dict[str, str] | None = None,
    manifest: dict[str, Any] | None = None,
    install_scope: str = "project",
    enable_in: str | None = "local",
) -> Path:
    """Install and enable one fake plugin; return its root.

    Args:
        config_dir: The fake Claude config dir.
        project_root: The project the install is bound to.
        plugin: The plugin name (``<plugin>@<marketplace>`` is its id).
        marketplace: The marketplace name.
        agents: Relative path under ``agents/`` -> frontmatter text, or None
            for a file with no frontmatter.
        skills: Skill directory name -> ``SKILL.md`` frontmatter text.
        manifest: ``plugin.json``; defaults to ``{"name": plugin}``.
        install_scope: ``user``, ``project`` or ``local``.
        enable_in: ``user``, ``project`` or ``local`` settings to enable it in,
            or None to rely on ``defaultEnabled``.
    """
    root = config_dir / "plugins" / "cache" / marketplace / plugin / "1.0.0"
    _write_json(root / ".claude-plugin" / "plugin.json", manifest or {"name": plugin})
    for relative, frontmatter in (agents or {}).items():
        body = "Body.\n" if frontmatter is None else f"---\n{frontmatter}\n---\n\nBody.\n"
        _write(root / "agents" / relative, body)
    for name, frontmatter in (skills or {}).items():
        _write(root / "skills" / name / "SKILL.md", f"---\n{frontmatter}\n---\n\nBody.\n")

    plugin_id = f"{plugin}@{marketplace}"
    record: dict[str, Any] = {"scope": install_scope, "installPath": str(root)}
    if install_scope != "user":
        record["projectPath"] = str(project_root)
    installed_path = config_dir / "plugins" / "installed_plugins.json"
    installed = _read_json(installed_path) or {"version": 2, "plugins": {}}
    installed["plugins"].setdefault(plugin_id, []).append(record)
    _write_json(installed_path, installed)

    if enable_in is not None:
        settings_path = {
            "user": config_dir / "settings.json",
            "project": project_root / ".claude" / "settings.json",
            "local": project_root / ".claude" / "settings.local.json",
        }[enable_in]
        settings = _read_json(settings_path) or {}
        settings.setdefault("enabledPlugins", {})[plugin_id] = True
        _write_json(settings_path, settings)
    return root


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _write_json(path: Path, data: Any) -> None:
    _write(path, json.dumps(data))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
