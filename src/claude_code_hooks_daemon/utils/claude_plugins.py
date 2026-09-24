"""Which Claude Code plugins are enabled here, and what they bring (Plan 00468).

The plugin audit (Plan 00467) found the daemon barely knew Claude Code
plugins exist: plugin agents were invisible to the read-only dispatch logic,
the LSP advice ignored the plugins that actually provide LSP, and nothing
could say which plugins ship hooks. Every one of those needs the same
answer, so this module is the one place that gives it.

**Enablement** (settings-reference, ``enabledPlugins``): the key may be set in
user (``<config>/settings.json``), project (``.claude/settings.json``), local
(``.claude/settings.local.json``) and managed settings. A higher scope's
entry decides: managed, then local, then project, then user. A plugin with no
entry anywhere falls back to its ``defaultEnabled`` (marketplace entry, then
``plugin.json``, default true). Only file-based managed settings are read:
MDM profiles and server-managed settings are invisible from here.

**Installs** come from ``<config>/plugins/installed_plugins.json``. A project
or local install applies only when its ``projectPath`` is this project root,
compared after resolving symlinks. Plugins loaded without an install record
(``@skills-dir``, ``@synced``, ``--plugin-dir``) are reported as unresolved
rather than guessed at.

**Components** (plugins-reference): the default locations (``agents/``,
``skills/``, ``commands/``, ``hooks/hooks.json``, ``.lsp.json``, a root
``SKILL.md``) plus the manifest's component fields. A marketplace entry adds
to the manifest (``strict: true``, the default) or is the whole declaration
(``strict: false``), and a ``strict: false`` entry for a plugin whose
manifest also declares components fails to load, as in Claude Code.

A plugin agent's id is ``<plugin>[:<subdir>...]:<name>``: frontmatter
``name`` replaces only the file name, and a file listed in the manifest's
``agents`` field drops the subfolders. A plugin agent whose frontmatter is
missing loads with no fields, named after its file.

Nothing here raises for a missing or malformed file: each is logged, and a
problem inside one plugin is recorded on that plugin.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.utils.claude_config import claude_config_dir
from claude_code_hooks_daemon.utils.markdown_format import parse_frontmatter_lenient

logger = logging.getLogger(__name__)


class SettingsScope(StrEnum):
    """A Claude Code settings scope that can set ``enabledPlugins``."""

    USER = "user"
    PROJECT = "project"
    LOCAL = "local"
    MANAGED = "managed"


class SkillKind(StrEnum):
    """A ``SKILL.md`` skill, or a flat ``.md`` command."""

    SKILL = "skill"
    COMMAND = "command"


@dataclass(frozen=True)
class PluginAgent:
    """One plugin agent: its scoped id, file and parsed frontmatter."""

    scoped_id: str
    path: Path
    frontmatter: Mapping[str, Any]


@dataclass(frozen=True)
class PluginSkill:
    """One plugin skill or command, by the scoped name it is invoked with."""

    scoped_name: str
    kind: SkillKind
    path: Path
    frontmatter: Mapping[str, Any]


@dataclass(frozen=True)
class PluginHookSource:
    """One hooks declaration: a file (``path``) or inline in a manifest (None)."""

    path: Path | None
    events: Mapping[str, Any]

    @property
    def event_names(self) -> tuple[str, ...]:
        return tuple(self.events)


@dataclass(frozen=True)
class PluginLspServer:
    """One LSP server a plugin declares."""

    name: str
    command: str | None
    extension_to_language: Mapping[str, str]

    @property
    def extensions(self) -> tuple[str, ...]:
        return tuple(self.extension_to_language)


@dataclass(frozen=True)
class EnabledPlugin:
    """A plugin enabled for this project, and everything it contributes.

    ``enabled_by`` is the settings scope whose entry enabled it, or None when
    no scope had an entry and ``defaultEnabled`` did. ``install_scope`` is
    the scope recorded in ``installed_plugins.json``. ``problems`` lists what
    could not be read, so a caller can say so rather than silently trust a
    partial answer.
    """

    plugin_id: str
    name: str
    marketplace: str
    enabled_by: SettingsScope | None
    install_scope: str
    install_path: Path
    version: str | None
    agents: tuple[PluginAgent, ...] = ()
    skills: tuple[PluginSkill, ...] = ()
    hooks: tuple[PluginHookSource, ...] = ()
    lsp_servers: tuple[PluginLspServer, ...] = ()
    problems: tuple[str, ...] = ()

    @property
    def hook_events(self) -> tuple[str, ...]:
        """Every hook event this plugin registers for, sorted, once each."""
        return tuple(sorted({name for source in self.hooks for name in source.event_names}))


@dataclass(frozen=True)
class UnresolvedPlugin:
    """A plugin a settings file enables that could not be resolved here."""

    plugin_id: str
    enabled_by: SettingsScope | None
    reason: str


@dataclass(frozen=True)
class PluginInventory:
    """The enabled plugins for one project, plus the ones that did not resolve."""

    config_dir: Path
    enabled: tuple[EnabledPlugin, ...] = ()
    unresolved: tuple[UnresolvedPlugin, ...] = ()

    def find_agent(self, scoped_id: str) -> PluginAgent | None:
        """The enabled plugin agent with this scoped id, or None."""
        return next((agent for agent in self.agents() if agent.scoped_id == scoped_id), None)

    def agents(self) -> tuple[PluginAgent, ...]:
        return tuple(agent for plugin in self.enabled for agent in plugin.agents)

    def skills(self) -> tuple[PluginSkill, ...]:
        return tuple(skill for plugin in self.enabled for skill in plugin.skills)

    def lsp_servers(self) -> tuple[PluginLspServer, ...]:
        return tuple(server for plugin in self.enabled for server in plugin.lsp_servers)


# ── File locations ───────────────────────────────────────────────────

_PLUGINS_DIR: Final[str] = "plugins"
_INSTALLED_PLUGINS_FILE: Final[str] = "installed_plugins.json"
_KNOWN_MARKETPLACES_FILE: Final[str] = "known_marketplaces.json"
_MARKETPLACES_DIR: Final[str] = "marketplaces"
_PLUGIN_META_DIR: Final[str] = ".claude-plugin"
_MANIFEST_FILE: Final[str] = "plugin.json"
_MARKETPLACE_FILE: Final[str] = "marketplace.json"
_SETTINGS_FILE: Final[str] = "settings.json"
_LOCAL_SETTINGS_FILE: Final[str] = "settings.local.json"
_PROJECT_CLAUDE_DIR: Final[str] = ".claude"
_MANAGED_SETTINGS_FILE: Final[str] = "managed-settings.json"
_MANAGED_DROP_IN_DIR: Final[str] = "managed-settings.d"
_JSON_SUFFIX: Final[str] = ".json"
_MARKDOWN_GLOB: Final[str] = "*.md"
_SKILL_FILE: Final[str] = "SKILL.md"
_DEFAULT_AGENTS_DIR: Final[str] = "agents"
_DEFAULT_SKILLS_DIR: Final[str] = "skills"
_DEFAULT_COMMANDS_DIR: Final[str] = "commands"
_DEFAULT_HOOKS_FILE: Final[tuple[str, str]] = ("hooks", "hooks.json")
_DEFAULT_LSP_FILE: Final[str] = ".lsp.json"

#: File-based managed settings, per platform (managed-settings docs).
_MANAGED_DIRS: Final[Mapping[str, Path]] = {
    "darwin": Path("/Library/Application Support/ClaudeCode"),
    "win32": Path("C:/Program Files/ClaudeCode"),
}
_MANAGED_DIR_DEFAULT: Final[Path] = Path("/etc/claude-code")

# ── Settings and manifest keys ───────────────────────────────────────

_ENABLED_PLUGINS_KEY: Final[str] = "enabledPlugins"
_INSTALLED_PLUGINS_KEY: Final[str] = "plugins"
_INSTALL_LOCATION_KEY: Final[str] = "installLocation"
_SCOPE_KEY: Final[str] = "scope"
_INSTALL_PATH_KEY: Final[str] = "installPath"
_PROJECT_PATH_KEY: Final[str] = "projectPath"
_VERSION_KEY: Final[str] = "version"
_NAME_KEY: Final[str] = "name"
_STRICT_KEY: Final[str] = "strict"
_DEFAULT_ENABLED_KEY: Final[str] = "defaultEnabled"
_AGENTS_KEY: Final[str] = "agents"
_SKILLS_KEY: Final[str] = "skills"
_COMMANDS_KEY: Final[str] = "commands"
_HOOKS_KEY: Final[str] = "hooks"
_LSP_SERVERS_KEY: Final[str] = "lspServers"
_MCP_SERVERS_KEY: Final[str] = "mcpServers"
_COMMAND_KEY: Final[str] = "command"
_EXTENSION_TO_LANGUAGE_KEY: Final[str] = "extensionToLanguage"

#: Manifest fields that declare components; a ``strict: false`` marketplace
#: entry conflicts with a manifest carrying any of them.
_COMPONENT_FIELDS: Final[tuple[str, ...]] = (
    _AGENTS_KEY,
    _SKILLS_KEY,
    _COMMANDS_KEY,
    _HOOKS_KEY,
    _LSP_SERVERS_KEY,
    _MCP_SERVERS_KEY,
    "outputStyles",
    "workflows",
)

#: Install scopes that apply only to the project named by ``projectPath``.
_PROJECT_BOUND_INSTALL_SCOPES: Final[frozenset[str]] = frozenset({"project", "local"})

_GIT_ENTRY: Final[str] = ".git"
_GITDIR_PREFIX: Final[str] = "gitdir:"
_COMMONDIR_FILE: Final[str] = "commondir"
_GITDIR_FILE: Final[str] = "gitdir"
_WORKTREES_DIR: Final[str] = "worktrees"

_ID_SEPARATOR: Final[str] = "@"
_SCOPED_NAME_SEPARATOR: Final[str] = ":"


def default_managed_settings_dir() -> Path:
    """The file-based managed-settings directory for this platform."""
    return _MANAGED_DIRS.get(sys.platform, _MANAGED_DIR_DEFAULT)


def resolve_enabled_plugins(
    project_root: Path,
    *,
    config_dir: Path | None = None,
    managed_dir: Path | None = None,
) -> PluginInventory:
    """Every plugin enabled for ``project_root``, with its components.

    Args:
        project_root: The project whose ``.claude/`` settings and
            ``projectPath`` installs apply.
        config_dir: Claude Code's config dir; defaults to
            :func:`claude_config_dir`.
        managed_dir: The file-based managed-settings directory; defaults to
            :func:`default_managed_settings_dir`.

    Returns:
        A :class:`PluginInventory`, plugins ordered by id.
    """
    config = config_dir if config_dir is not None else claude_config_dir()
    managed = managed_dir if managed_dir is not None else default_managed_settings_dir()
    decisions = _effective_enablement(project_root, config, managed)
    installs = _install_records(config)

    enabled: list[EnabledPlugin] = []
    unresolved: list[UnresolvedPlugin] = []
    for plugin_id in sorted(set(decisions) | set(installs)):
        decision = decisions.get(plugin_id)
        if decision is not None and not decision[0]:
            continue
        scope = decision[1] if decision is not None else None
        outcome = _resolve_one(plugin_id, scope, installs.get(plugin_id, []), project_root, config)
        if isinstance(outcome, EnabledPlugin):
            enabled.append(outcome)
        elif outcome is not None:
            unresolved.append(UnresolvedPlugin(plugin_id, scope, outcome))
    return PluginInventory(config_dir=config, enabled=tuple(enabled), unresolved=tuple(unresolved))


# ── Enablement ───────────────────────────────────────────────────────


def _effective_enablement(
    project_root: Path, config_dir: Path, managed_dir: Path
) -> dict[str, tuple[bool, SettingsScope]]:
    """Each plugin id's deciding value and the scope it came from."""
    claude_dir = project_root / _PROJECT_CLAUDE_DIR
    sources: list[tuple[SettingsScope, Path]] = [
        (SettingsScope.USER, config_dir / _SETTINGS_FILE),
        (SettingsScope.PROJECT, claude_dir / _SETTINGS_FILE),
        (SettingsScope.LOCAL, claude_dir / _LOCAL_SETTINGS_FILE),
        (SettingsScope.MANAGED, managed_dir / _MANAGED_SETTINGS_FILE),
    ]
    sources.extend((SettingsScope.MANAGED, path) for path in _managed_drop_ins(managed_dir))

    decisions: dict[str, tuple[bool, SettingsScope]] = {}
    for scope, path in sources:
        settings = _read_json_object(path)
        entries = settings.get(_ENABLED_PLUGINS_KEY) if settings is not None else None
        if not isinstance(entries, dict):
            continue
        for plugin_id, value in entries.items():
            if isinstance(plugin_id, str) and isinstance(value, bool):
                decisions[plugin_id] = (value, scope)
    return decisions


def _managed_drop_ins(managed_dir: Path) -> list[Path]:
    """``managed-settings.d/*.json`` in merge order, hidden files skipped."""
    drop_in_dir = managed_dir / _MANAGED_DROP_IN_DIR
    if not drop_in_dir.is_dir():
        return []
    return sorted(
        path
        for path in drop_in_dir.iterdir()
        if path.suffix == _JSON_SUFFIX and not path.name.startswith(".")
    )


# ── Installs ─────────────────────────────────────────────────────────


def _install_records(config_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """``installed_plugins.json`` as plugin id -> install records."""
    loaded = _read_json_object(config_dir / _PLUGINS_DIR / _INSTALLED_PLUGINS_FILE)
    if loaded is None:
        return {}
    plugins = loaded.get(_INSTALLED_PLUGINS_KEY)
    table = plugins if isinstance(plugins, dict) else loaded
    records: dict[str, list[dict[str, Any]]] = {}
    for plugin_id, value in table.items():
        entries = value if isinstance(value, list) else [value]
        kept = [entry for entry in entries if isinstance(entry, dict)]
        if kept and isinstance(plugin_id, str):
            records[plugin_id] = kept
    return records


def _choose_install(
    records: list[dict[str, Any]], project_root: Path
) -> tuple[dict[str, Any] | None, str]:
    """The install that applies to this project, else why none does.

    Claude Code's rule: a project or local record applies when its
    ``projectPath`` is this project, or has the same canonical repository
    root, so a main checkout's install also applies in its linked worktrees
    (see :func:`canonical_repo_root`). A record for this exact path is
    preferred, then one for the same repository, then a user one.
    """
    resolved_root = project_root.resolve()
    same_repository: dict[str, Any] | None = None
    general: dict[str, Any] | None = None
    for record in records:
        if record.get(_SCOPE_KEY) in _PROJECT_BOUND_INSTALL_SCOPES:
            project_path = record.get(_PROJECT_PATH_KEY)
            if not isinstance(project_path, str):
                continue
            if Path(project_path).resolve() == resolved_root:
                return record, ""
            if same_repository is None and _same_repository(Path(project_path), project_root):
                same_repository = record
        elif general is None:
            general = record
    if same_repository is not None:
        return same_repository, ""
    if general is not None:
        return general, ""
    if records:
        return None, "installed only for another project (its projectPath is in another repository)"
    return None, "not installed (no installed_plugins.json record)"


def _resolve_one(
    plugin_id: str,
    enabled_by: SettingsScope | None,
    records: list[dict[str, Any]],
    project_root: Path,
    config_dir: Path,
) -> EnabledPlugin | str | None:
    """The resolved plugin, the reason it did not resolve, or None.

    None means the plugin is not active here at all: nothing enables it
    explicitly, and either no install applies to this project or its
    ``defaultEnabled`` is false. That is not a failure worth reporting.
    """
    id_name, separator, marketplace = plugin_id.rpartition(_ID_SEPARATOR)
    if not separator or not id_name:
        return "not a plugin@marketplace id; a plugin with no install record is not resolved"
    record, reason = _choose_install(records, project_root)
    if record is None:
        return reason if enabled_by is not None else None
    raw_path = record.get(_INSTALL_PATH_KEY)
    install_path = Path(raw_path) if isinstance(raw_path, str) and raw_path else None
    if install_path is None or not install_path.is_dir():
        return f"install path missing on disk: {raw_path!r}"

    manifest = _read_json_object(install_path / _PLUGIN_META_DIR / _MANIFEST_FILE) or {}
    entry = _marketplace_entry(config_dir, marketplace, id_name)
    if enabled_by is None and not _default_enabled(manifest, entry):
        return None
    declarations, conflict = _declarations(manifest, entry)
    if conflict:
        return conflict

    manifest_name = manifest.get(_NAME_KEY)
    name = manifest_name if isinstance(manifest_name, str) and manifest_name else id_name
    collector = _ComponentCollector(install_path, name, declarations)
    version = record.get(_VERSION_KEY) or manifest.get(_VERSION_KEY)
    return EnabledPlugin(
        plugin_id=plugin_id,
        name=name,
        marketplace=marketplace,
        enabled_by=enabled_by,
        install_scope=str(record.get(_SCOPE_KEY, "")),
        install_path=install_path,
        version=version if isinstance(version, str) else None,
        agents=collector.agents(),
        skills=collector.skills(),
        hooks=collector.hooks(),
        lsp_servers=collector.lsp_servers(),
        problems=tuple(collector.problems),
    )


def _marketplace_entry(config_dir: Path, marketplace: str, name: str) -> dict[str, Any] | None:
    """This plugin's entry in its marketplace's ``marketplace.json``, if any."""
    plugins_dir = config_dir / _PLUGINS_DIR
    known = _read_json_object(plugins_dir / _KNOWN_MARKETPLACES_FILE) or {}
    record = known.get(marketplace)
    location = record.get(_INSTALL_LOCATION_KEY) if isinstance(record, dict) else None
    base = (
        Path(location)
        if isinstance(location, str)
        else plugins_dir / _MARKETPLACES_DIR / marketplace
    )
    catalogue = _read_json_object(base / _PLUGIN_META_DIR / _MARKETPLACE_FILE)
    entries = catalogue.get(_INSTALLED_PLUGINS_KEY) if catalogue is not None else None
    if not isinstance(entries, list):
        return None
    return next(
        (e for e in entries if isinstance(e, dict) and e.get(_NAME_KEY) == name),
        None,
    )


def _default_enabled(manifest: Mapping[str, Any], entry: Mapping[str, Any] | None) -> bool:
    """``defaultEnabled``: the marketplace entry's, then the manifest's, else true."""
    for source in (entry or {}, manifest):
        value = source.get(_DEFAULT_ENABLED_KEY)
        if isinstance(value, bool):
            return value
    return True


def _declarations(
    manifest: Mapping[str, Any], entry: Mapping[str, Any] | None
) -> tuple[list[Mapping[str, Any]], str]:
    """The component declarations in force, or the ``strict`` conflict."""
    if entry is not None and entry.get(_STRICT_KEY) is False:
        if any(field_name in manifest for field_name in _COMPONENT_FIELDS):
            return [], (
                "marketplace entry is strict: false but plugin.json also declares "
                "components, which Claude Code refuses to load"
            )
        return [entry], ""
    return [source for source in (manifest, entry) if source], ""


# ── Components ───────────────────────────────────────────────────────


@dataclass
class _ComponentCollector:
    """Reads one plugin's components from its root and declarations."""

    root: Path
    name: str
    declarations: list[Mapping[str, Any]]
    problems: list[str] = field(default_factory=list)

    def _declared(self, key: str) -> list[Any]:
        """Every value declared for ``key``, lists flattened."""
        values: list[Any] = []
        for declaration in self.declarations:
            value = declaration.get(key)
            if isinstance(value, list):
                values.extend(value)
            elif value is not None:
                values.append(value)
        return values

    def _declared_paths(self, key: str) -> list[Path]:
        return [p for raw in self._declared(key) if (p := self._inside(raw, key)) is not None]

    def _inside(self, raw: Any, key: str) -> Path | None:
        """A declared path, if it is a string that stays inside the plugin root."""
        if not isinstance(raw, str) or not raw:
            self.problems.append(f"{key}: ignored a non-path value {raw!r}")
            return None
        candidate = (self.root / raw).resolve()
        if not candidate.is_relative_to(self.root.resolve()):
            self.problems.append(f"{key}: ignored {raw!r}, which leaves the plugin root")
            return None
        return candidate

    def _frontmatter(self, path: Path) -> dict[str, Any]:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.problems.append(f"cannot read {path}: {exc}")
            return {}
        return parse_frontmatter_lenient(text) or {}

    def _scoped(self, *parts: str) -> str:
        return _SCOPED_NAME_SEPARATOR.join((self.name, *parts))

    # agents

    def agents(self) -> tuple[PluginAgent, ...]:
        declared = self._declared_paths(_AGENTS_KEY)
        if self._declared(_AGENTS_KEY):
            files = [f for path in declared for f in _markdown_files(path)]
            return self._dedupe_agents(self._agent(f, ()) for f in files)
        agents_dir = self.root / _DEFAULT_AGENTS_DIR
        if not agents_dir.is_dir():
            return ()
        return self._dedupe_agents(
            self._agent(f, f.relative_to(agents_dir).parent.parts)
            for f in sorted(agents_dir.rglob(_MARKDOWN_GLOB))
        )

    def _agent(self, path: Path, subdirs: tuple[str, ...]) -> PluginAgent:
        frontmatter = self._frontmatter(path)
        declared_name = frontmatter.get(_NAME_KEY)
        leaf = declared_name if isinstance(declared_name, str) and declared_name else path.stem
        return PluginAgent(self._scoped(*subdirs, leaf), path, frontmatter)

    @staticmethod
    def _dedupe_agents(agents: Iterable[PluginAgent]) -> tuple[PluginAgent, ...]:
        seen: dict[str, PluginAgent] = {}
        for agent in agents:
            seen.setdefault(agent.scoped_id, agent)
        return tuple(seen.values())

    # skills and commands

    def skills(self) -> tuple[PluginSkill, ...]:
        found: dict[str, PluginSkill] = {}
        skill_dirs = self._skill_dirs()
        for skill_dir in skill_dirs:
            skill = self._skill(skill_dir / _SKILL_FILE, skill_dir.name)
            found.setdefault(skill.scoped_name, skill)
        if not skill_dirs and (self.root / _SKILL_FILE).is_file():
            skill = self._skill(self.root / _SKILL_FILE, self.root.name)
            found.setdefault(skill.scoped_name, skill)
        for command in self._commands():
            found.setdefault(command.scoped_name, command)
        return tuple(found.values())

    def _skill_dirs(self) -> list[Path]:
        """Directories holding a ``SKILL.md``: the default ``skills/`` plus
        every ``skills`` path, which adds to it."""
        dirs: list[Path] = []
        for base in [self.root / _DEFAULT_SKILLS_DIR, *self._declared_paths(_SKILLS_KEY)]:
            if (base / _SKILL_FILE).is_file() and base != self.root:
                dirs.append(base)
            elif base.is_dir():
                dirs.extend(
                    child for child in sorted(base.iterdir()) if (child / _SKILL_FILE).is_file()
                )
        return dirs

    def _skill(self, path: Path, fallback_name: str) -> PluginSkill:
        frontmatter = self._frontmatter(path)
        declared_name = frontmatter.get(_NAME_KEY)
        leaf = declared_name if isinstance(declared_name, str) and declared_name else fallback_name
        return PluginSkill(self._scoped(leaf), SkillKind.SKILL, path, frontmatter)

    def _commands(self) -> list[PluginSkill]:
        """Flat ``.md`` commands: the ``commands`` paths replace ``commands/``."""
        sources = (
            self._declared_paths(_COMMANDS_KEY)
            if self._declared(_COMMANDS_KEY)
            else [self.root / _DEFAULT_COMMANDS_DIR]
        )
        return [
            PluginSkill(self._scoped(f.stem), SkillKind.COMMAND, f, self._frontmatter(f))
            for source in sources
            for f in _markdown_files(source)
        ]

    # hooks

    def hooks(self) -> tuple[PluginHookSource, ...]:
        """Hook files (``hooks/hooks.json``, then declared paths), then inline hooks."""
        files: list[Path] = []
        inline: list[PluginHookSource] = []
        default = self.root.joinpath(*_DEFAULT_HOOKS_FILE)
        if default.is_file():
            files.append(default)
        for raw in self._declared(_HOOKS_KEY):
            if isinstance(raw, dict):
                inner = raw.get(_HOOKS_KEY)
                inline.append(PluginHookSource(None, inner if isinstance(inner, dict) else raw))
            elif (path := self._inside(raw, _HOOKS_KEY)) is not None:
                if all(path != known.resolve() for known in files):
                    files.append(path)
        from_files = [
            PluginHookSource(path, events)
            for path in files
            if (events := self._hook_file(path)) is not None
        ]
        return (*from_files, *inline)

    def _hook_file(self, path: Path) -> Mapping[str, Any] | None:
        loaded = _read_json_object(path)
        events = loaded.get(_HOOKS_KEY) if loaded is not None else None
        if not isinstance(events, dict):
            self.problems.append(f"{path}: not a hooks file with a 'hooks' object")
            return None
        return events

    # LSP servers

    def lsp_servers(self) -> tuple[PluginLspServer, ...]:
        tables: list[Mapping[str, Any]] = []
        default = self.root / _DEFAULT_LSP_FILE
        if default.is_file():
            tables.append(self._lsp_file(default))
        for raw in self._declared(_LSP_SERVERS_KEY):
            if isinstance(raw, dict):
                tables.append(raw)
            elif (path := self._inside(raw, _LSP_SERVERS_KEY)) is not None and path != default:
                tables.append(self._lsp_file(path))
        servers: dict[str, PluginLspServer] = {}
        for table in tables:
            for name, config in table.items():
                if isinstance(config, dict):
                    servers.setdefault(name, _lsp_server(name, config))
        return tuple(servers.values())

    def _lsp_file(self, path: Path) -> Mapping[str, Any]:
        loaded = _read_json_object(path)
        if loaded is None:
            self.problems.append(f"{path}: not a JSON object of LSP servers")
            return {}
        inner = loaded.get(_LSP_SERVERS_KEY)
        return inner if isinstance(inner, dict) else loaded


def _lsp_server(name: str, config: Mapping[str, Any]) -> PluginLspServer:
    command = config.get(_COMMAND_KEY)
    mapping = config.get(_EXTENSION_TO_LANGUAGE_KEY)
    extensions = (
        {k: v for k, v in mapping.items() if isinstance(k, str) and isinstance(v, str)}
        if isinstance(mapping, dict)
        else {}
    )
    return PluginLspServer(name, command if isinstance(command, str) else None, extensions)


def _markdown_files(path: Path) -> list[Path]:
    """``path`` itself when it is a ``.md`` file, else the ``.md`` files under it."""
    if path.is_file():
        return [path] if path.suffix == ".md" else []
    if path.is_dir():
        return sorted(path.rglob(_MARKDOWN_GLOB))
    return []


def _same_repository(first: Path, second: Path) -> bool:
    root = canonical_repo_root(second)
    return root is not None and canonical_repo_root(first) == root


def canonical_repo_root(path: Path) -> Path | None:
    """The repository root Claude Code keys project-bound installs on.

    Ported from Claude Code's own bundle, because an install record's
    ``projectPath`` applies wherever this answer matches. The git root is the
    nearest ancestor holding a ``.git`` entry; a linked worktree's root maps
    to its main checkout, but only when the chain is consistent: the ``.git``
    file names a ``gitdir`` under ``<common>/worktrees/``, and that entry's
    ``gitdir`` file points back at this checkout's ``.git``. Anything else
    leaves the git root as its own canonical root.

    Returns:
        The canonical root, resolved; None outside any repository.
    """
    git_root = _git_root(path.resolve())
    if git_root is None:
        return None
    return _main_checkout(git_root)


def _git_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / _GIT_ENTRY).exists():
            return candidate
    return None


def _main_checkout(git_root: Path) -> Path:
    dot_git = git_root / _GIT_ENTRY
    if not dot_git.is_file():
        return git_root
    pointer = _read_text(dot_git)
    if pointer is None or not pointer.startswith(_GITDIR_PREFIX):
        return git_root
    entry = (git_root / pointer[len(_GITDIR_PREFIX) :].strip()).resolve()
    common_text = _read_text(entry / _COMMONDIR_FILE)
    back_pointer = _read_text(entry / _GITDIR_FILE)
    if common_text is None or back_pointer is None:
        return git_root
    common = (entry / common_text).resolve()
    if entry.parent != common / _WORKTREES_DIR:
        return git_root
    if (entry / back_pointer).resolve() != dot_git.resolve():
        return git_root
    if common.name != _GIT_ENTRY:
        return git_root if (common / _GIT_ENTRY).exists() else common
    return common.parent


def _read_text(path: Path) -> str | None:
    """A small git bookkeeping file, stripped; None when it cannot be read."""
    text: str | None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        # Claude Code falls back to the checkout's own root on any failure
        # here; the caller does the same with None.
        logger.debug("claude_plugins: cannot read %s: %s", path, exc)
        text = None
    return text


def _read_json_object(path: Path) -> dict[str, Any] | None:
    """A JSON object from ``path``, or None when absent, unreadable or not an object."""
    if not path.is_file():
        return None
    loaded: Any
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # A missing or broken Claude Code file is a normal state for a
        # resolver that must answer anyway: logged, then treated as absent.
        logger.debug("claude_plugins: cannot read %s: %s", path, exc)
        loaded = None
    return loaded if isinstance(loaded, dict) else None
