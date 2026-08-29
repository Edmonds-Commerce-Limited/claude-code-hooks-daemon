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
    from claude_code_hooks_daemon.config.models import Config

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

    def is_plan_path(self, rel_path: str) -> bool:
        """True when ``rel_path`` is under the configured plan directory."""
        return _is_under(rel_path, self.plan_dir)

    @classmethod
    def from_config(cls, config: Config) -> ProjectLayout:
        """Compose a :class:`ProjectLayout` from the daemon's typed ``Config``.

        Reads the new ``layout:`` block (Shape B truths) plus
        ``documentation.trees`` and ``plan_workflow`` (Shape A truths, left
        canonical where they are per decision D2) — the single place these
        homes are combined into one API.
        """
        layout_config = config.layout
        mode = layout_config.mode
        qa = config.plan_workflow.qa
        archive_dirs = tuple(
            dict.fromkeys(name for name in (qa.completed_dir, qa.cancelled_dir) if name)
        )
        return cls(
            source_dirs=_merge(mode, tuple(layout_config.source_dirs), _BUILTIN_SOURCE_DIRS),
            test_dirs=_merge(mode, tuple(layout_config.test_dirs), _BUILTIN_TEST_DIRS),
            config_dirs=_merge(mode, tuple(layout_config.config_dirs), _BUILTIN_CONFIG_DIRS),
            vendor_dirs=frozenset(
                _merge(mode, tuple(layout_config.vendor_dirs), _BUILTIN_VENDOR_DIRS)
            ),
            agent_docs_dir=config.documentation.trees.agent,
            human_docs_dir=config.documentation.trees.human,
            plan_dir=config.plan_workflow.directory,
            plan_archive_dirs=archive_dirs,
        )
