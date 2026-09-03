"""``ProjectLayout`` — the single handler-facing facade over directory-role
truths (Plan 00288).

Directory truths (which dir is source, test, human docs, agent docs, plans,
vendor/build) previously had no single home: some had a config home that
consumers bypassed (Shape A, see ``DESIGN-layout-ssot.md`` §1a), others had
none at all (Shape B, §1b). ``ProjectLayout`` is a small frozen object built
ONCE from :class:`~claude_code_hooks_daemon.config.models.Config` that
composes the new ``layout:`` block (Shape B truths) WITH the existing config
homes (``documentation.trees``, ``plan_workflow.directory``,
``plan_workflow.qa.completed_dir``/``cancelled_dir`` — Shape A truths, left
where they are per decision D2) into ONE API. Handlers never read raw config
keys and never re-declare a truth.

Zero-config behaviour is byte-identical to today (pinned by tests in
``tests/unit/core/test_project_layout.py``):

- ``config_dirs`` and ``vendor_dirs`` fall back to built-in constants that
  already exist project-wide (``config``; the canonical vendored/build set
  in ``docs_qa.corpus``).
- ``test_dirs`` falls back to :data:`COMMON_TEST_DIRECTORIES`
  (``strategies/tdd/common.py``) — the one cross-language test-dir
  convention that already exists.
- ``source_dirs`` has NO cross-language built-in to fall back on: today's
  source-dir knowledge lives only in 11 per-language ``_SOURCE_DIRECTORIES``
  tuples (see DESIGN §1b). ``is_source_path()`` therefore reports nothing
  when ``source_dirs`` is undeclared — that per-language inference stays the
  real answer in the TDD strategies until Task 4.4 (C6) wires the facade in
  as a first-checked layer ahead of it.

``mode: additive`` (default) merges a project's declared list onto the
built-in; ``mode: replace`` makes a list the project actually SET stand
alone, but a list the project left UNSET still falls back to the built-in
(DESIGN §2c; mirrors how ``secret_file_guard`` scopes its own ``mode`` to
the option it governs).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from claude_code_hooks_daemon.docs_qa.corpus import COMMON_VENDORED_BUILD_DIR_NAMES
from claude_code_hooks_daemon.strategies.tdd.common import COMMON_TEST_DIRECTORIES

if TYPE_CHECKING:
    from claude_code_hooks_daemon.config.models import Config, LayoutConfig

_MODE_REPLACE: Final[str] = "replace"

# No config home existed for "config" directories before this plan (DESIGN
# §2b) -- this IS the built-in, defined here for the first time.
_BUILTIN_CONFIG_DIRS: Final[tuple[str, ...]] = ("config",)

# COMMON_TEST_DIRECTORIES entries are slash-delimited path-fragment markers
# (e.g. "/tests/"); ProjectLayout works in plain directory-NAME terms, so the
# delimiters are stripped once here.
_BUILTIN_TEST_DIRS: Final[tuple[str, ...]] = tuple(
    name.strip("/") for name in COMMON_TEST_DIRECTORIES
)

# See the module docstring: no cross-language source-dir convention exists
# today, so there is nothing to fall back on here.
_BUILTIN_SOURCE_DIRS: Final[tuple[str, ...]] = ()

_BUILTIN_VENDOR_DIRS: Final[tuple[str, ...]] = tuple(COMMON_VENDORED_BUILD_DIR_NAMES)

# Doc/plan axes fallbacks (Plan 00300), matching Config's own field defaults
# (DocumentationTreesConfig.agent/human, PlanWorkflowConfig.directory,
# PlanWorkflowQaConfig.completed_dir) -- used only when NO Config is
# available at all (e.g. ProjectLayout.built_in_default() for a registry
# built with no config, mirroring ProjectRegistry.single_project()).
_DEFAULT_AGENT_DOCS_DIR: Final[str] = "CLAUDE"
_DEFAULT_HUMAN_DOCS_DIR: Final[str] = "docs"
#: Top level by design (Plan 00326 D12): nested under ``docs/`` it would
#: inherit the human-docs role rule's "keep it terse, summarise" instruction,
#: which is the opposite of verbatim capture, and rule globs cannot be negated.
_DEFAULT_REMOTE_DOCS_DIR: Final[str] = "remote-docs"
_DEFAULT_PLAN_DIR: Final[str] = "CLAUDE/Plan"
_DEFAULT_PLAN_ARCHIVE_DIRS: Final[tuple[str, ...]] = ("Completed",)


def _merge(mode: str, declared: tuple[str, ...], builtin: tuple[str, ...]) -> tuple[str, ...]:
    """Effective directory-name list under the additive/replace convention.

    An UNSET (empty) ``declared`` list always keeps the built-in, whatever
    ``mode`` is -- ``replace`` only ever stands alone for a list the project
    actually populated. ``additive`` (default) merges ``declared`` onto
    ``builtin``, skipping names already present.
    """
    if not declared:
        return builtin
    if mode == _MODE_REPLACE:
        return declared
    merged = list(builtin)
    for name in declared:
        if name not in merged:
            merged.append(name)
    return tuple(merged)


def _path_parts(rel_path: str) -> tuple[str, ...]:
    """Non-empty path segments of a project-root-relative path."""
    return tuple(part for part in rel_path.split("/") if part and part != ".")


def _has_dir_component(rel_path: str, dirs: tuple[str, ...]) -> bool:
    """True when any segment of ``rel_path`` names one of ``dirs``."""
    return any(part in dirs for part in _path_parts(rel_path))


def _dirs_from_layout_config(
    layout_config: LayoutConfig | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], frozenset[str]]:
    """Effective (source_dirs, test_dirs, config_dirs, vendor_dirs) for one `layout:` block.

    Shared by the root project (`from_config`) and every declared project
    (`for_project`) so the additive/replace merge rule (see `_merge`) is
    computed in exactly one place. `layout_config=None` means "declares
    nothing" -- additive mode over the built-ins, i.e. the built-ins
    unchanged.
    """
    if layout_config is None:
        return (
            _BUILTIN_SOURCE_DIRS,
            _BUILTIN_TEST_DIRS,
            _BUILTIN_CONFIG_DIRS,
            frozenset(_BUILTIN_VENDOR_DIRS),
        )
    mode = layout_config.mode
    return (
        _merge(mode, tuple(layout_config.source_dirs), _BUILTIN_SOURCE_DIRS),
        _merge(mode, tuple(layout_config.test_dirs), _BUILTIN_TEST_DIRS),
        _merge(mode, tuple(layout_config.config_dirs), _BUILTIN_CONFIG_DIRS),
        frozenset(_merge(mode, tuple(layout_config.vendor_dirs), _BUILTIN_VENDOR_DIRS)),
    )


def _is_under(rel_path: str, root: str) -> bool:
    """True when ``rel_path`` is ``root`` itself or lives beneath it."""
    root_norm = root.strip("/")
    if not root_norm:
        return False
    path_norm = rel_path.strip("/")
    return path_norm == root_norm or path_norm.startswith(root_norm + "/")


@dataclass(frozen=True)
class ProjectLayout:
    """Frozen, handler-facing facade over the project's directory-role truths.

    Built once per config load via :meth:`from_config` and injected onto
    every handler instance by the registry (mirroring the
    ``_project_exclude_paths`` precedent). Consumers read this facade
    instead of hardcoding directory names or re-declaring a truth already
    stated elsewhere.

    Attributes:
        source_dirs: Effective source directory names (declared + built-in
            per ``mode``; see the module docstring for why the built-in is
            empty today)
        test_dirs: Effective test directory names (declared + built-in)
        config_dirs: Effective config directory names (declared + built-in)
        vendor_dirs: Effective vendored/build directory names (declared +
            the canonical constant)
        agent_docs_dir: Root of the agent-facing doc tree
            (``documentation.trees.agent``)
        human_docs_dir: Root of the human-facing doc tree
            (``documentation.trees.human``)
        remote_docs_dir: Root of the vendored remote-docs tree
            (``documentation.trees.remote``). Deliberately NOT part of
            :meth:`is_docs_path`: it holds upstream prose this project did
            not author and cannot fix, so consumers keyed on "is this our
            documentation?" must not claim it (Plan 00326 D1/D12)
        plan_dir: The configured plan directory (``plan_workflow.directory``)
        plan_archive_dirs: Configured plan archive directory names
            (``plan_workflow.qa.completed_dir``/``cancelled_dir``, deduped)
    """

    source_dirs: tuple[str, ...]
    test_dirs: tuple[str, ...]
    config_dirs: tuple[str, ...]
    vendor_dirs: frozenset[str]
    agent_docs_dir: str
    human_docs_dir: str
    plan_dir: str
    plan_archive_dirs: tuple[str, ...]
    # Defaulted, and last, so adding this axis stays ADDITIVE for the many
    # existing call sites that construct a layout positionally or without it.
    # Mirrors how `_DEFAULT_HUMAN_DOCS_DIR` and the pydantic model each state
    # the "docs" default in their own layer.
    remote_docs_dir: str = _DEFAULT_REMOTE_DOCS_DIR

    def is_source_path(self, rel_path: str) -> bool:
        """True when ``rel_path`` has a declared/built-in source dir component."""
        return _has_dir_component(rel_path, self.source_dirs)

    def is_test_path(self, rel_path: str) -> bool:
        """True when ``rel_path`` has a declared/built-in test dir component."""
        return _has_dir_component(rel_path, self.test_dirs)

    def is_vendored_path(self, rel_path: str) -> bool:
        """True when ``rel_path`` has a declared/canonical vendor dir component."""
        return any(part in self.vendor_dirs for part in _path_parts(rel_path))

    def is_docs_path(self, rel_path: str) -> bool:
        """True when ``rel_path`` is under the agent or human doc tree."""
        return _is_under(rel_path, self.agent_docs_dir) or _is_under(rel_path, self.human_docs_dir)

    def is_remote_docs_path(self, rel_path: str) -> bool:
        """True when ``rel_path`` is under the vendored remote-docs tree.

        Kept separate from :meth:`is_docs_path` on purpose — see the
        ``remote_docs_dir`` attribute note.
        """
        return _is_under(rel_path, self.remote_docs_dir)

    def is_plan_path(self, rel_path: str) -> bool:
        """True when ``rel_path`` is under the configured plan directory."""
        return _is_under(rel_path, self.plan_dir)

    @classmethod
    def built_in_default(cls) -> ProjectLayout:
        """A `ProjectLayout` with every axis at its built-in default.

        Used where no `Config` is available at all (mirrors
        `ProjectRegistry.single_project()`), and as the base every DECLARED
        project without its own `layout:` block resolves to (Plan 00300) --
        never the root project's own declared lists, so one project's layout
        can never leak into another's.
        """
        return cls(
            source_dirs=_BUILTIN_SOURCE_DIRS,
            test_dirs=_BUILTIN_TEST_DIRS,
            config_dirs=_BUILTIN_CONFIG_DIRS,
            vendor_dirs=frozenset(_BUILTIN_VENDOR_DIRS),
            agent_docs_dir=_DEFAULT_AGENT_DOCS_DIR,
            human_docs_dir=_DEFAULT_HUMAN_DOCS_DIR,
            remote_docs_dir=_DEFAULT_REMOTE_DOCS_DIR,
            plan_dir=_DEFAULT_PLAN_DIR,
            plan_archive_dirs=_DEFAULT_PLAN_ARCHIVE_DIRS,
        )

    @classmethod
    def for_project(
        cls, layout_config: LayoutConfig | None, doc_axes: ProjectLayout
    ) -> ProjectLayout:
        """Build a per-DECLARED-project `ProjectLayout` (Plan 00300).

        `source_dirs`/`test_dirs`/`config_dirs`/`vendor_dirs` come from this
        project's OWN `layout:` block (or the built-in defaults when it
        declares none) -- deliberately never from `doc_axes`' own declared
        lists, so one project's layout can never leak into a sibling's. The
        doc/plan axes (`agent_docs_dir`, `human_docs_dir`, `plan_dir`,
        `plan_archive_dirs`) are not yet a per-project concept and are reused
        from `doc_axes` (ordinarily the registry's `root_layout`).

        Args:
            layout_config: This project's own `layout:` block, or None.
            doc_axes: Supplies the doc/plan axes only.
        """
        source_dirs, test_dirs, config_dirs, vendor_dirs = _dirs_from_layout_config(layout_config)
        return cls(
            source_dirs=source_dirs,
            test_dirs=test_dirs,
            config_dirs=config_dirs,
            vendor_dirs=vendor_dirs,
            agent_docs_dir=doc_axes.agent_docs_dir,
            human_docs_dir=doc_axes.human_docs_dir,
            remote_docs_dir=doc_axes.remote_docs_dir,
            plan_dir=doc_axes.plan_dir,
            plan_archive_dirs=doc_axes.plan_archive_dirs,
        )

    @classmethod
    def from_config(cls, config: Config) -> ProjectLayout:
        """Compose a :class:`ProjectLayout` from the daemon's typed ``Config``.

        Reads the new ``layout:`` block (Shape B truths) plus
        ``documentation.trees`` and ``plan_workflow`` (Shape A truths, left
        canonical where they are per decision D2) — the single place these
        homes are combined into one API.
        """
        qa = config.plan_workflow.qa
        archive_dirs = tuple(
            dict.fromkeys(name for name in (qa.completed_dir, qa.cancelled_dir) if name)
        )
        source_dirs, test_dirs, config_dirs, vendor_dirs = _dirs_from_layout_config(config.layout)
        return cls(
            source_dirs=source_dirs,
            test_dirs=test_dirs,
            config_dirs=config_dirs,
            vendor_dirs=vendor_dirs,
            agent_docs_dir=config.documentation.trees.agent,
            human_docs_dir=config.documentation.trees.human,
            remote_docs_dir=config.documentation.trees.remote,
            plan_dir=config.plan_workflow.directory,
            plan_archive_dirs=archive_dirs,
        )


# "Main repo code dirs" (DESIGN §1b, C5): the top-level dirs several
# consumers (worktree_file_copy, same-commit-plan-doc, path-existence) treat
# as "this is real project code", independently of ``source_dirs``' role as
# a per-language TDD inference input. ``source_dirs`` has no cross-language
# built-in (see the module docstring), so it is empty by default -- this
# fallback restores "src" for that case specifically, matching every
# consumer's pre-facade hardcoded literal.
_MAIN_REPO_SOURCE_FALLBACK: Final[tuple[str, ...]] = ("src",)


def main_repo_code_dirs(layout: ProjectLayout | None) -> tuple[str, ...]:
    """Effective "main repo code dirs" truth shared by C5's three consumers.

    Composes ``source_dirs`` (falling back to ``("src",)`` when undeclared —
    see :data:`_MAIN_REPO_SOURCE_FALLBACK`), ``test_dirs``, and
    ``config_dirs``. Zero-config behaviour is a SAFE SUPERSET of the
    pre-facade literal ``("src", "tests", "config")``, never a subset: the
    facade's ``test_dirs`` built-in additionally recognises ``test/``,
    ``__tests__/`` and ``spec/`` (the same cross-language convention
    :class:`ProjectLayout` already uses for TDD), so a project using one of
    those names now gets it also recognised as a main-repo code dir where it
    previously was not. ``config_dirs`` matches the old default exactly
    (``("config",)``).

    ``layout=None`` (a consumer constructed outside the registry, as unit
    tests do) returns the pre-facade literal directly.
    """
    if layout is None:
        return (*_MAIN_REPO_SOURCE_FALLBACK, "tests", "config")
    source_dirs = layout.source_dirs or _MAIN_REPO_SOURCE_FALLBACK
    return tuple(dict.fromkeys((*source_dirs, *layout.test_dirs, *layout.config_dirs)))
