"""Shipped ``.claude/rules/`` directory-role pointer files (Plan 00288, D5).

One rule file per directory role (source dirs, test dirs, the two doc
trees, ``.claude/skills/``, ``.claude/agents/``, the plan directory), each
scoped by a ``paths:`` glob DERIVED from the project's configured layout at
deploy time (:class:`~claude_code_hooks_daemon.core.project_layout.ProjectLayout`)
and routing to the canonical ``CLAUDE/DirectoryRoles.md`` doc — the R7a
pointer-only contract enforced by ``docs_qa``'s ``rules-file-shape`` check.

Client-visibility decision (recorded here, not re-derived): ``DirectoryRoles.md``
is NOT re-shipped as a seeded copy into the client's own doc tree. It does not
need to be — a normal (non-self-install) client install clones the WHOLE
daemon repository into ``.claude/hooks-daemon/`` (see ``CLAUDE/LLM-INSTALL.md``),
so the daemon's own ``CLAUDE/DirectoryRoles.md`` already exists on disk at a
fixed, predictable path the moment the daemon itself is installed — before
these rules are ever deployed. Seeding a second copy into the client's
configurable agent tree would (a) duplicate a fact this project's own R1
forbids, (b) require also seeding DirectoryRoles.md's own dependencies
(``DocumentationStrategy.md`` et al., which are NOT shipped client assets
today) to avoid dead links, and (c) go stale independently of the vendored
original. :func:`directory_roles_link` instead computes the correct relative
link depending on install mode — ``CLAUDE/DirectoryRoles.md`` in self-install
(daemon IS the project) or ``.claude/hooks-daemon/CLAUDE/DirectoryRoles.md``
in a normal client install (the vendored daemon's own doc tree, a fixed name
independent of the CLIENT's configured ``documentation.trees.agent``).

Ownership contract, adapted from the agent-asset subsystem
(``install/agent_assets.py``, Plan 00279) for content that is PARTLY
config-derived rather than fully static:

- The rule BODY (trigger + rule + link, no frontmatter) is the daemon-owned,
  versioned unit subject to pristine-vs-customised classification — mirrors
  an agent's content md5 ledger, except rendered against the project's
  CURRENT config rather than read from a static bundled file (the link
  target varies by install mode; a future body-text revision would still be
  compared this way).
- The frontmatter (``paths:`` glob list) is ALWAYS regenerated when the body
  is pristine, refreshing stale globs after a ``layout``/``documentation``/
  ``plan_workflow`` config change without that counting as an upgrade.
- A body that matches NEITHER the current template render NOR (once one
  exists) a historic one is CUSTOMISED and is never touched, mirroring
  ``agent_assets``' contract exactly.

Deployment gating: six of the seven roles apply to directories every project
has regardless of feature flags (source, test, the two doc trees,
``.claude/skills/``, ``.claude/agents/`` — the last two the daemon deploys
into itself), so they deploy unconditionally, matching ``deploy_skills``.
The plan-dir role is the one exception: the plan directory only exists when
``plan_workflow.enabled`` is true (mirrors the ``PlanJournalling.md``/
plan-dedupe-scout gating precedent in ``install/plan_workflow.py``) — a rule
pointing at a directory that was never created would be pure noise.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.core.project_layout import ProjectLayout

#: Client-project-relative location Claude Code resolves rule files from.
RULES_DIR_PARTS: Final[tuple[str, str]] = (".claude", "rules")

#: Marker line embedded in every shipped rule so the deployed file itself
#: names the body-template revision it came from (mirrors
#: ``AGENT_VERSION_MARKER_PREFIX``).
RULE_VERSION_MARKER_PREFIX: Final[str] = "<!-- hooks-daemon-rule-version:"

_MD_SUFFIX: Final[str] = ".md"

# Owner rw, group/other r — a rule file is read, never executed (matches
# agent_assets' _AGENT_FILE_MODE).
_RULE_FILE_MODE: Final[int] = 0o644

# "src/**/*.md" is the conventional fallback when a project has declared no
# ``layout.source_dirs`` — ProjectLayout has no cross-language source-dir
# built-in (see core/project_layout.py's module docstring), so without this
# fallback the source-dirs rule would ship with an EMPTY paths: list and
# never fire for the single most common source-dir name. This is advisory
# routing, not enforcement, so a convention default is an acceptable choice
# here even though ``is_source_path()`` itself deliberately has none.
_SOURCE_DIRS_FALLBACK: Final[tuple[str, ...]] = ("src",)

# ProjectLayout.test_dirs always has a built-in (COMMON_TEST_DIRECTORIES), so
# this fallback is a pure defensive backstop, never expected to fire.
_TEST_DIRS_FALLBACK: Final[tuple[str, ...]] = ("tests",)

_CLAUDE_SKILLS_GLOB: Final[str] = ".claude/skills/**/*.md"
_CLAUDE_AGENTS_GLOB: Final[str] = ".claude/agents/**/*.md"

_DAEMON_OWN_AGENT_TREE_NAME: Final[str] = "CLAUDE"
_DIRECTORY_ROLES_DOC_NAME: Final[str] = "DirectoryRoles.md"

_FRONTMATTER_RE: Final[re.Pattern[str]] = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n?", re.DOTALL)


def _plan_workflow_enabled(config: Config) -> bool:
    return config.plan_workflow.enabled


def _always_enabled(_config: Config) -> bool:
    return True


@dataclass(frozen=True)
class RuleAssetSpec:
    """Metadata for one daemon-shipped directory-role rule file.

    Attributes:
        key: Filename stem; the deployed file is ``.claude/rules/<key>.md``.
        version: Version of the CURRENT body template.
        description: Frontmatter ``description:`` value (the trigger, in
            R7a's terms — what makes Claude Code load this rule).
        body_template: The rule's pointer body (heading, trigger sentence,
            the rule in <=2 imperative lines, a link) with a single
            ``{directory_roles_link}`` placeholder. No frontmatter, no
            version marker — those are rendered separately.
        glob_resolver: Computes this role's ``paths:`` globs from the
            project's current :class:`ProjectLayout`.
        is_enabled: Whether this rule should be deployed for a given
            :class:`Config`. Defaults to always-on.
        gating_config_key: Dotted config key shown in the skip message when
            ``is_enabled`` is false. ``None`` for the always-on roles.
    """

    key: str
    version: str
    description: str
    body_template: str
    glob_resolver: Callable[[ProjectLayout], tuple[str, ...]]
    is_enabled: Callable[[Config], bool] = _always_enabled
    gating_config_key: str | None = None


class RuleAssetState(Enum):
    """Classification of the deployed copy of one shipped rule."""

    ABSENT = "absent"
    CURRENT = "current"
    OUTDATED = "outdated"
    CUSTOMISED = "customised"


class RuleAction(Enum):
    """What the engine did (or advises) for one rule."""

    DEPLOYED = "deployed"
    REFRESHED = "refreshed"
    KEPT_CURRENT = "kept-current"
    CUSTOMISED_WARNING = "customised-warning"
    SKIPPED_DISABLED = "skipped-disabled"


@dataclass(frozen=True)
class RuleActionResult:
    """Outcome for one rule from a deploy/sync operation."""

    key: str
    action: RuleAction
    message: str


@dataclass
class RuleSyncReport:
    """Aggregate outcome of a config-driven sync across every shipped rule."""

    results: list[RuleActionResult] = field(default_factory=list)

    @property
    def messages(self) -> list[str]:
        """Every per-rule message, in registry order."""
        return [result.message for result in self.results]


def _source_dirs_globs(layout: ProjectLayout) -> tuple[str, ...]:
    dirs = layout.source_dirs or _SOURCE_DIRS_FALLBACK
    return tuple(f"{name}/**/*.md" for name in dirs)


def _test_dirs_globs(layout: ProjectLayout) -> tuple[str, ...]:
    dirs = layout.test_dirs or _TEST_DIRS_FALLBACK
    return tuple(f"{name}/**/*.md" for name in dirs)


def _human_docs_globs(layout: ProjectLayout) -> tuple[str, ...]:
    return (f"{layout.human_docs_dir}/**/*.md",)


def _remote_docs_globs(layout: ProjectLayout) -> tuple[str, ...]:
    return (f"{layout.remote_docs_dir}/**/*.md",)


def _agent_docs_globs(layout: ProjectLayout) -> tuple[str, ...]:
    return (f"{layout.agent_docs_dir}/**/*.md",)


def _claude_skills_globs(_layout: ProjectLayout) -> tuple[str, ...]:
    return (_CLAUDE_SKILLS_GLOB,)


def _claude_agents_globs(_layout: ProjectLayout) -> tuple[str, ...]:
    return (_CLAUDE_AGENTS_GLOB,)


def _plan_dir_globs(layout: ProjectLayout) -> tuple[str, ...]:
    return (f"{layout.plan_dir}/**/*.md",)


_SOURCE_DIRS_BODY: Final[str] = """\
# Source directory markdown

You are about to add or edit markdown under a source directory.

Keep it to a collocated `CLAUDE.md` (module doc) or `README.md` -- anything else is promoted into a doc tree, with a pointer left behind.

See [DirectoryRoles.md]({directory_roles_link}) for the full rule.
"""

_TEST_DIRS_BODY: Final[str] = """\
# Test directory markdown

You are about to add or edit markdown under a test directory.

Same rule as source directories -- a collocated `CLAUDE.md` or `README.md` only. Fixture-directory markdown is test data, not documentation, and is exempt.

See [DirectoryRoles.md]({directory_roles_link}) for the full rule.
"""

_HUMAN_DOCS_BODY: Final[str] = """\
# Human-facing documentation

You are about to add or edit markdown in the human-facing doc tree.

Keep it terse and human-register -- summarise and point into the agent tree for depth, never restate its content at length here.

See [DirectoryRoles.md]({directory_roles_link}) for the full rule.
"""

_AGENT_DOCS_BODY: Final[str] = """\
# Agent-facing documentation

You are about to add or edit markdown in the agent-facing doc tree.

This tree owns the depth for every fact -- every satellite surface should point here, never duplicate it.

See [DirectoryRoles.md]({directory_roles_link}) for the full rule.
"""

_CLAUDE_SKILLS_BODY: Final[str] = """\
# Skill definitions

You are about to add or edit a skill under `.claude/skills/`.

A skill is a thin, intent-matched shim: invocation mechanics only. Point at a canonical doc for the procedure body -- do not inline it.

See [DirectoryRoles.md]({directory_roles_link}) for the full rule.
"""

_CLAUDE_AGENTS_BODY: Final[str] = """\
# Sub-agent definitions

You are about to add or edit a sub-agent under `.claude/agents/`.

Keep it to role framing and pointers -- no engineering-principle restatements or remediation cookbooks.

See [DirectoryRoles.md]({directory_roles_link}) for the full rule.
"""

_REMOTE_DOCS_BODY: Final[str] = """\
# Vendored remote documentation

You are about to add or edit markdown in the vendored remote-docs tree.

This tree is NOT authored here: every file is captured from upstream by `hooks-daemon remote-docs`, carries mandatory provenance frontmatter, and must not be reworded -- editing it silently falsifies its recorded `fidelity`.

See [DirectoryRoles.md]({directory_roles_link}) for the full rule.
"""

_PLAN_DIR_BODY: Final[str] = """\
# Plan directory markdown

You are about to add or edit markdown under the plan directory.

Keep `PLAN.md` lean and current; put narrative in this plan's `JOURNAL/` and durable detail in a named supporting document.

See [DirectoryRoles.md]({directory_roles_link}) for the full rule.
"""

SOURCE_DIRS_RULE_KEY: Final[str] = "source-dirs"
TEST_DIRS_RULE_KEY: Final[str] = "test-dirs"
HUMAN_DOCS_RULE_KEY: Final[str] = "human-docs"
REMOTE_DOCS_RULE_KEY: Final[str] = "remote-docs"
AGENT_DOCS_RULE_KEY: Final[str] = "agent-docs"
CLAUDE_SKILLS_RULE_KEY: Final[str] = "claude-skills"
CLAUDE_AGENTS_RULE_KEY: Final[str] = "claude-agents"
PLAN_DIR_RULE_KEY: Final[str] = "plan-dir"

SHIPPED_RULES: Final[tuple[RuleAssetSpec, ...]] = (
    RuleAssetSpec(
        key=SOURCE_DIRS_RULE_KEY,
        version="1.0.0",
        description="Markdown under a source directory is routing-only (R7d)",
        body_template=_SOURCE_DIRS_BODY,
        glob_resolver=_source_dirs_globs,
    ),
    RuleAssetSpec(
        key=TEST_DIRS_RULE_KEY,
        version="1.0.0",
        description="Markdown under a test directory follows the same rule as source (R7d)",
        body_template=_TEST_DIRS_BODY,
        glob_resolver=_test_dirs_globs,
    ),
    RuleAssetSpec(
        key=HUMAN_DOCS_RULE_KEY,
        version="1.0.0",
        description="The human-facing doc tree is terse and points at the agent tree (R3)",
        body_template=_HUMAN_DOCS_BODY,
        glob_resolver=_human_docs_globs,
    ),
    RuleAssetSpec(
        key=REMOTE_DOCS_RULE_KEY,
        version="1.0.0",
        description="Vendored upstream docs are captured, never authored or reworded",
        body_template=_REMOTE_DOCS_BODY,
        glob_resolver=_remote_docs_globs,
    ),
    RuleAssetSpec(
        key=AGENT_DOCS_RULE_KEY,
        version="1.0.0",
        description="The agent-facing doc tree owns the depth for every fact (R2)",
        body_template=_AGENT_DOCS_BODY,
        glob_resolver=_agent_docs_globs,
    ),
    RuleAssetSpec(
        key=CLAUDE_SKILLS_RULE_KEY,
        version="1.0.0",
        description="Skills are thin intent-matched shims that point (R7b)",
        body_template=_CLAUDE_SKILLS_BODY,
        glob_resolver=_claude_skills_globs,
    ),
    RuleAssetSpec(
        key=CLAUDE_AGENTS_RULE_KEY,
        version="1.0.0",
        description="Sub-agent files are role framing plus pointers (R7c)",
        body_template=_CLAUDE_AGENTS_BODY,
        glob_resolver=_claude_agents_globs,
    ),
    RuleAssetSpec(
        key=PLAN_DIR_RULE_KEY,
        version="1.0.0",
        description="A plan folder is a drafting ground, not a documentation home (R8)",
        body_template=_PLAN_DIR_BODY,
        glob_resolver=_plan_dir_globs,
        is_enabled=_plan_workflow_enabled,
        gating_config_key="plan_workflow.enabled",
    ),
)


def spec_by_key(key: str) -> RuleAssetSpec:
    """Return the shipped spec for ``key``.

    Raises:
        KeyError: If no shipped rule carries that key.
    """
    for spec in SHIPPED_RULES:
        if spec.key == key:
            return spec
    raise KeyError(f"No daemon-shipped directory-role rule keyed {key!r}")


def rules_dir(project_root: Path) -> Path:
    """Absolute path to ``.claude/rules/`` inside ``project_root``."""
    return project_root.joinpath(*RULES_DIR_PARTS)


def deployed_rule_path(spec: RuleAssetSpec, project_root: Path) -> Path:
    """Where ``spec`` deploys inside a client project."""
    return rules_dir(project_root) / f"{spec.key}{_MD_SUFFIX}"


def directory_roles_link(config: Config) -> str:
    """Relative link from a deployed rule file to the canonical DirectoryRoles.md.

    See the module docstring's "Client-visibility decision" for why this
    resolves to a different path per install mode instead of seeding a
    second copy of the doc into the client's own tree. Purely a function of
    config (agent-tree name, self-install mode) — no project_root needed,
    since the link is always project-root-RELATIVE.
    """
    if config.daemon.self_install_mode:
        target = Path(config.documentation.trees.agent) / _DIRECTORY_ROLES_DOC_NAME
    else:
        target = (
            Path(ProjectPath.HOOKS_DAEMON_INSTALL_DIR)
            / _DAEMON_OWN_AGENT_TREE_NAME
            / _DIRECTORY_ROLES_DOC_NAME
        )
    rules_rel = Path(*RULES_DIR_PARTS)
    return posixpath.relpath(target.as_posix(), start=rules_rel.as_posix())


def _render_frontmatter(spec: RuleAssetSpec, globs: tuple[str, ...]) -> str:
    glob_lines = "\n".join(f'  - "{glob}"' for glob in globs)
    return f"---\npaths:\n{glob_lines}\ndescription: {spec.description}\n---\n"


def _render_body(spec: RuleAssetSpec, link: str) -> str:
    return spec.body_template.format(directory_roles_link=link)


def render_rule_content(spec: RuleAssetSpec, globs: tuple[str, ...], link: str) -> str:
    """Full deployed file content for ``spec`` given resolved globs and link."""
    frontmatter = _render_frontmatter(spec, globs)
    marker = f"{RULE_VERSION_MARKER_PREFIX} {spec.version} -->"
    body = _render_body(spec, link)
    return f"{frontmatter}\n{marker}\n\n{body}"


def _strip_frontmatter_and_marker(text: str) -> str:
    """The pointer BODY of a deployed rule file — frontmatter and the
    version-marker line removed, so a version bump or a glob refresh never
    counts as customisation."""
    body = _FRONTMATTER_RE.sub("", text, count=1).lstrip("\n")
    marker_line_end = body.find("-->")
    if body.startswith(RULE_VERSION_MARKER_PREFIX) and marker_line_end != -1:
        body = body[marker_line_end + len("-->") :]
    return body.lstrip("\n")


def classify_rule(spec: RuleAssetSpec, project_root: Path, config: Config) -> RuleAssetState:
    """Classify the deployed copy of ``spec`` in ``project_root``."""
    target = deployed_rule_path(spec, project_root)
    if not target.is_file():
        return RuleAssetState.ABSENT

    layout = ProjectLayout.from_config(config)
    globs = spec.glob_resolver(layout)
    link = directory_roles_link(config)
    deployed_text = target.read_text()

    if deployed_text == render_rule_content(spec, globs, link):
        return RuleAssetState.CURRENT

    deployed_body = _strip_frontmatter_and_marker(deployed_text).strip()
    if deployed_body == _render_body(spec, link).strip():
        return RuleAssetState.OUTDATED
    return RuleAssetState.CUSTOMISED


def _customised_warning(spec: RuleAssetSpec, target: Path) -> str:
    return (
        f"WARNING: {target} does not match the daemon-shipped body for this rule "
        f"— it has been CUSTOMISED locally, so the daemon will NOT touch it "
        f"(the current shipped revision is v{spec.version}). Its `paths:` "
        f"globs will not be refreshed after a layout/documentation config "
        f"change until you either restore the shipped body or maintain the "
        f"globs by hand."
    )


def deploy_rule(spec: RuleAssetSpec, project_root: Path, config: Config) -> RuleActionResult:
    """Deploy/refresh one rule, honouring the never-clobber-customised rule."""
    state = classify_rule(spec, project_root, config)
    target = deployed_rule_path(spec, project_root)
    if state is RuleAssetState.CURRENT:
        return RuleActionResult(
            key=spec.key,
            action=RuleAction.KEPT_CURRENT,
            message=f"{spec.key} already current (kept)",
        )
    if state is RuleAssetState.CUSTOMISED:
        message = _customised_warning(spec, target)
        return RuleActionResult(key=spec.key, action=RuleAction.CUSTOMISED_WARNING, message=message)

    layout = ProjectLayout.from_config(config)
    globs = spec.glob_resolver(layout)
    link = directory_roles_link(config)
    content = render_rule_content(spec, globs, link)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    target.chmod(_RULE_FILE_MODE)

    if state is RuleAssetState.OUTDATED:
        action = RuleAction.REFRESHED
        message = f"Refreshed {spec.key} (paths: globs recomputed from current layout)"
    else:
        action = RuleAction.DEPLOYED
        message = f"Deployed {spec.key} to {target}"
    return RuleActionResult(key=spec.key, action=action, message=message)


def sync_directory_role_rules(project_root: Path, config: Config) -> RuleSyncReport:
    """Config-driven lifecycle pass over every shipped directory-role rule.

    Enabled + absent/outdated => deploy/refresh; enabled + current => keep;
    enabled + customised => loud warning, never clobbered. Disabled (the
    plan-dir role only, when ``plan_workflow.enabled`` is false) => skipped,
    any already-deployed copy left untouched (no destructive removal — the
    plan-dedupe-scout agent precedent removes only via an explicit CLI
    command, never a sync pass; this rule has no such command yet, so it
    simply stops refreshing).
    """
    report = RuleSyncReport()
    for spec in SHIPPED_RULES:
        if not spec.is_enabled(config):
            report.results.append(
                RuleActionResult(
                    key=spec.key,
                    action=RuleAction.SKIPPED_DISABLED,
                    message=f"{spec.key} not deployed ({spec.gating_config_key} is disabled)",
                )
            )
            continue
        report.results.append(deploy_rule(spec, project_root, config))
    return report


def sync_directory_role_rules_if_enabled(project_root: Path, config_path: Path) -> RuleSyncReport:
    """Load config (defaults when absent) and run the lifecycle sync.

    The single decision site for daemon-start and CLI/installer-driven rule
    deployment, mirroring ``deploy_agents_if_enabled``.
    """
    config = Config.load_or_default(config_path)
    return sync_directory_role_rules(project_root, config)
