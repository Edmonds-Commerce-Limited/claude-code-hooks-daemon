"""Generic agent-asset install subsystem (Plan 00279).

The daemon ships agent definitions into a client project's flat
``.claude/agents/`` namespace. This module is the single registry and
lifecycle engine for those assets: per-agent metadata (namespaced name,
semantic version, the config key that gates deployment), a version/md5 ledger
covering EVERY shipped revision, a classification helper
(absent | current | outdated | customised), and the deploy/remove engine.

Ownership contract (Plan 00279 Decisions 1 and 2):

- A deployed file whose content md5 matches ANY shipped revision is PRISTINE:
  the current revision is kept, an older one is overwritten on upgrade.
- A file matching NO shipped revision is CUSTOMISED and is NEVER touched — a
  loud warning names the file instead. Hacking on daemon-owned agents is
  strongly discouraged: copy the file to a new name of your own and edit that.
- The daemon never silently deletes from ``.claude/agents/``. When an agent's
  gating config is disabled while the file is present, the sync produces a
  removal ADVISORY naming ``hooks-daemon agents remove <name>``; only that
  explicit CLI command removes, and only a pristine file.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.config.models import Config

logger = logging.getLogger(__name__)

#: Directory (relative to this package's ``install/`` module) holding the
#: bundled agent definitions — the single source of truth for shipped content.
_AGENTS_TEMPLATE_DIR_PARTS: Final[tuple[str, str]] = ("templates", "agents")

#: Client-project-relative location Claude Code resolves agent definitions
#: from. A FLAT namespace the client owns — daemon-deployed agents are
#: ``hooks-daemon-`` prefixed so they cannot collide with a client's own.
AGENTS_DIR_PARTS: Final[tuple[str, str]] = (".claude", "agents")

#: Marker line embedded in every shipped agent so the deployed file itself
#: names the revision it came from.
AGENT_VERSION_MARKER_PREFIX: Final[str] = "<!-- hooks-daemon-agent-version:"

#: Owner rw, group/other r — a definition that is read, never executed.
_AGENT_FILE_MODE: Final[int] = 0o644

DEDUPE_AGENT_NAME: Final[str] = "hooks-daemon-plan-dedupe-scout"
OPUS_SECURITY_AGENT_NAME: Final[str] = "hooks-daemon-opus-security"

_MD_SUFFIX: Final[str] = ".md"

#: How a project removes a deployed agent — quoted in every removal advisory
#: so the reader gets the exact command, never a hunt.
_REMOVE_COMMAND_TEMPLATE: Final[str] = "hooks-daemon agents remove {name}"


class AgentAssetState(Enum):
    """Classification of the deployed copy of one shipped agent."""

    ABSENT = "absent"
    CURRENT = "current"
    OUTDATED = "outdated"
    CUSTOMISED = "customised"


class AgentAction(Enum):
    """What the engine did (or advises) for one agent."""

    DEPLOYED = "deployed"
    UPDATED = "updated"
    KEPT_CURRENT = "kept-current"
    CUSTOMISED_WARNING = "customised-warning"
    REMOVAL_ADVISED = "removal-advised"
    SKIPPED_DISABLED = "skipped-disabled"
    REMOVED = "removed"
    REFUSED_CUSTOMISED = "refused-customised"
    ALREADY_ABSENT = "already-absent"


@dataclass(frozen=True)
class AgentAssetSpec:
    """Metadata for one daemon-shipped agent definition.

    Attributes:
        name: Namespaced (``hooks-daemon-*``) agent name; the bundled and
            deployed filename is ``<name>.md``.
        version: Semantic version of the CURRENT bundled content. A ledger
            unit test pins the bundled file's md5 to this version, so editing
            the file without bumping the version fails QA loudly.
        gating_config_key: Dotted config key (for messages) that gates
            deployment of this agent.
        is_enabled: Reads the gating key from a loaded :class:`Config`.
        historic_versions: ``(label, md5)`` pairs for every PREVIOUSLY shipped
            revision. Membership makes an on-disk file provably pristine, so
            an upgrade may overwrite it; anything outside the set is
            customised and never touched.
    """

    name: str
    version: str
    gating_config_key: str
    is_enabled: Callable[[Config], bool]
    historic_versions: tuple[tuple[str, str], ...] = ()

    @property
    def historic_md5s(self) -> tuple[str, ...]:
        """The md5 digests of every previously shipped revision."""
        return tuple(md5 for _label, md5 in self.historic_versions)


@dataclass(frozen=True)
class AgentActionResult:
    """Outcome for one agent from a deploy/remove/sync operation."""

    name: str
    action: AgentAction
    message: str


@dataclass
class AgentSyncReport:
    """Aggregate outcome of a config-driven sync across every shipped agent."""

    results: list[AgentActionResult] = field(default_factory=list)

    @property
    def messages(self) -> list[str]:
        """Every per-agent message, in registry order."""
        return [result.message for result in self.results]


def _plan_workflow_enabled(config: Config) -> bool:
    return config.plan_workflow.enabled


def _opus_security_enabled(config: Config) -> bool:
    return config.agents.opus_security.enabled


# Historic dedupe-scout revisions, harvested from this repository's git
# history (every blob the template ever shipped as, including the pre-marker
# content current at the time this subsystem was introduced). Without these,
# a pristine existing install would be classified customised and never
# upgraded again.
_DEDUPE_HISTORIC_VERSIONS: Final[tuple[tuple[str, str], ...]] = (
    ("pre-1.1.0", "550b1e034bc8b7d0a3ae1ea8cf12dfa6"),
    ("legacy-4", "8b5f66621c986cb926720ccddabb8fc8"),
    ("legacy-3", "892b875cafe304bb4fd52dd1ab1e6cd3"),
    ("legacy-2", "b65355647e0783576a33c1518307c2f1"),
    ("legacy-1", "a590da6b9f2d03e877856e6b9b56a0bd"),
)

SHIPPED_AGENTS: Final[tuple[AgentAssetSpec, ...]] = (
    AgentAssetSpec(
        name=DEDUPE_AGENT_NAME,
        version="1.1.0",
        gating_config_key="plan_workflow.enabled",
        is_enabled=_plan_workflow_enabled,
        historic_versions=_DEDUPE_HISTORIC_VERSIONS,
    ),
    AgentAssetSpec(
        name=OPUS_SECURITY_AGENT_NAME,
        version="1.0.0",
        gating_config_key="agents.opus_security.enabled",
        is_enabled=_opus_security_enabled,
    ),
)


def spec_by_name(name: str) -> AgentAssetSpec:
    """Return the shipped spec for ``name``.

    Raises:
        KeyError: If no shipped agent carries that name.
    """
    for spec in SHIPPED_AGENTS:
        if spec.name == name:
            return spec
    raise KeyError(f"No daemon-shipped agent named {name!r}")


def agents_source_dir() -> Path:
    """Absolute path to the bundled agent-definitions directory."""
    return Path(__file__).resolve().parent.joinpath(*_AGENTS_TEMPLATE_DIR_PARTS)


def spec_source_path(spec: AgentAssetSpec) -> Path:
    """Absolute path to the bundled definition file for ``spec``."""
    return agents_source_dir() / f"{spec.name}{_MD_SUFFIX}"


def deployed_agent_path(spec: AgentAssetSpec, project_root: Path) -> Path:
    """Where ``spec`` deploys inside a client project."""
    return project_root.joinpath(*AGENTS_DIR_PARTS) / f"{spec.name}{_MD_SUFFIX}"


def content_md5(text: str) -> str:
    """MD5 of agent content — identity fingerprint only, not cryptographic."""
    # SECURITY: md5 used as a content-identity fingerprint for pristine-vs-
    # customised classification, never for security (usedforsecurity=False).
    return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()


def ledger() -> dict[str, dict[str, str]]:
    """Agent → version → content md5, covering EVERY shipped revision.

    The current revision's md5 is computed from the bundled file (the single
    source of truth for shipped content); historic revisions are recorded on
    each spec.
    """
    book: dict[str, dict[str, str]] = {}
    for spec in SHIPPED_AGENTS:
        entries = {spec.version: content_md5(spec_source_path(spec).read_text())}
        entries.update(dict(spec.historic_versions))
        book[spec.name] = entries
    return book


def classify_agent(spec: AgentAssetSpec, project_root: Path) -> AgentAssetState:
    """Classify the deployed copy of ``spec`` in ``project_root``."""
    target = deployed_agent_path(spec, project_root)
    if not target.is_file():
        return AgentAssetState.ABSENT
    deployed_md5 = content_md5(target.read_text())
    if deployed_md5 == content_md5(spec_source_path(spec).read_text()):
        return AgentAssetState.CURRENT
    if deployed_md5 in spec.historic_md5s:
        return AgentAssetState.OUTDATED
    return AgentAssetState.CUSTOMISED


def _customised_warning(spec: AgentAssetSpec, target: Path) -> str:
    return (
        f"WARNING: {target} does not match any revision the daemon ever shipped "
        f"— it has been CUSTOMISED locally, so the daemon will NOT touch it "
        f"(the current shipped revision is v{spec.version}). Hacking on "
        f"daemon-owned agents is strongly discouraged: your edits are invisible "
        f"to upgrades and prompt fixes will never reach this file. Copy it to a "
        f"name of your own (dropping the 'hooks-daemon-' prefix), edit that "
        f"copy, and restore this file with 'hooks-daemon agents install "
        f"{spec.name}' after removing your customised version."
    )


def deploy_agent(spec: AgentAssetSpec, project_root: Path) -> AgentActionResult:
    """Deploy/refresh one agent, honouring the never-clobber-customised rule."""
    state = classify_agent(spec, project_root)
    target = deployed_agent_path(spec, project_root)
    if state is AgentAssetState.CURRENT:
        return AgentActionResult(
            name=spec.name,
            action=AgentAction.KEPT_CURRENT,
            message=f"{spec.name} already at v{spec.version} (kept)",
        )
    if state is AgentAssetState.CUSTOMISED:
        message = _customised_warning(spec, target)
        logger.warning(message)
        return AgentActionResult(
            name=spec.name, action=AgentAction.CUSTOMISED_WARNING, message=message
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(spec_source_path(spec).read_text())
    target.chmod(_AGENT_FILE_MODE)
    if state is AgentAssetState.OUTDATED:
        action = AgentAction.UPDATED
        message = f"Updated {spec.name} to v{spec.version} (previous shipped revision replaced)"
    else:
        action = AgentAction.DEPLOYED
        message = f"Deployed {spec.name} v{spec.version} to {target}"
    logger.info(message)
    return AgentActionResult(name=spec.name, action=action, message=message)


def remove_agent(spec: AgentAssetSpec, project_root: Path) -> AgentActionResult:
    """Remove a deployed agent — refuses a customised file, never guesses."""
    state = classify_agent(spec, project_root)
    target = deployed_agent_path(spec, project_root)
    if state is AgentAssetState.ABSENT:
        return AgentActionResult(
            name=spec.name,
            action=AgentAction.ALREADY_ABSENT,
            message=f"{spec.name} is not deployed (nothing to remove)",
        )
    if state is AgentAssetState.CUSTOMISED:
        message = (
            f"REFUSED to remove {target}: its content matches no revision the "
            f"daemon ever shipped, so it holds local customisation the daemon "
            f"must not destroy. Remove the file manually if you are certain."
        )
        logger.warning(message)
        return AgentActionResult(
            name=spec.name, action=AgentAction.REFUSED_CUSTOMISED, message=message
        )
    target.unlink()
    message = f"Removed {target} (pristine shipped revision)"
    logger.info(message)
    return AgentActionResult(name=spec.name, action=AgentAction.REMOVED, message=message)


def sync_agents(project_root: Path, config: Config) -> AgentSyncReport:
    """Config-driven lifecycle pass over every shipped agent.

    Enabled + absent/outdated ⇒ deploy/update; enabled + current ⇒ keep;
    enabled + customised ⇒ loud warning, never clobbered. Disabled + present ⇒
    removal ADVISORY naming the CLI command (never a silent delete); disabled +
    absent ⇒ skipped.
    """
    report = AgentSyncReport()
    for spec in SHIPPED_AGENTS:
        if spec.is_enabled(config):
            report.results.append(deploy_agent(spec, project_root))
            continue
        state = classify_agent(spec, project_root)
        if state is AgentAssetState.ABSENT:
            report.results.append(
                AgentActionResult(
                    name=spec.name,
                    action=AgentAction.SKIPPED_DISABLED,
                    message=(
                        f"{spec.name} not deployed ({spec.gating_config_key} is disabled)"
                    ),
                )
            )
            continue
        remove_command = _REMOVE_COMMAND_TEMPLATE.format(name=spec.name)
        message = (
            f"{spec.name} is deployed but its gating config "
            f"({spec.gating_config_key}) is disabled. The daemon never deletes "
            f"agents itself — run '{remove_command}' to remove it, or re-enable "
            f"the config key to keep it maintained."
        )
        logger.warning(message)
        report.results.append(
            AgentActionResult(name=spec.name, action=AgentAction.REMOVAL_ADVISED, message=message)
        )
    return report


def deploy_agents_if_enabled(project_root: Path, config_path: Path) -> AgentSyncReport:
    """Load config (defaults when absent) and run the lifecycle sync.

    The single decision site for daemon-start and CLI-driven agent deployment,
    mirroring ``deploy_plan_workflow_if_enabled``.
    """
    config = Config.load_or_default(config_path)
    return sync_agents(project_root, config)
