"""Plain-values mirror of the typed ``documentation`` config (Plan 00284).

Mirrors the ``plan_qa.context`` precedent: the daemon's pydantic
``DocumentationConfig`` (``config/models.py``) is the single source of
truth for parsing/validating YAML, and this package never parses YAML
itself. :func:`policy_from_config` copies the validated config into the
plain dataclasses below via structural typing (:class:`typing.Protocol`),
so this package stays daemon/pydantic-decoupled — the real config model, a
test stand-in, or plain values loaded elsewhere all satisfy the Protocol.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES

DEFAULT_AGENT_TREE = "CLAUDE"
DEFAULT_HUMAN_TREE = "docs"
DEFAULT_RESIDENT_AT_IMPORTS: tuple[str, ...] = ("CLAUDE.md",)


@dataclass(frozen=True)
class GeneratedDocEntry:
    """One entry in the generated-docs manifest (R10)."""

    glob: str
    generator: str


@dataclass(frozen=True)
class DocumentationTreesPolicy:
    """Names of the two audience-split documentation trees."""

    agent: str = DEFAULT_AGENT_TREE
    human: str = DEFAULT_HUMAN_TREE


@dataclass(frozen=True)
class DocumentationQaPolicy:
    """Documentation QA subsystem policy (mirrors ``DocumentationQaConfig``)."""

    edit_mode: str = "warn"
    commit_gate_mode: str = "warn"
    sweep_mode: str = "advise"
    check_modes: Mapping[str, str] = field(default_factory=dict)
    grandfather_allowlist: tuple[str, ...] = ()
    generated_docs: tuple[GeneratedDocEntry, ...] = ()
    registered_module_docs: tuple[str, ...] = ()
    resident_at_imports: tuple[str, ...] = DEFAULT_RESIDENT_AT_IMPORTS
    scope_exclude_globs: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentationPolicy:
    """Top-level documentation QA policy (mirrors ``DocumentationConfig``).

    ``vendor_dirs`` is the one axis here with no ``documentation:`` config
    home: it mirrors ``layout.vendor_dirs``, which is a project-wide truth
    (Plan 00288) rather than a docs-QA setting. It arrives as PLAIN VALUES
    from the caller for the same reason every other field does — importing
    ``ProjectLayout`` would couple this package to ``core``, and
    ``core.project_layout`` already imports ``docs_qa.corpus``, so the
    coupling would close a cycle.
    """

    enabled: bool = False
    trees: DocumentationTreesPolicy = field(default_factory=DocumentationTreesPolicy)
    qa: DocumentationQaPolicy = field(default_factory=DocumentationQaPolicy)
    #: Effective vendored/build directory NAMES. Defaults to the canonical
    #: constant so a caller with no layout to hand loses nothing.
    vendor_dirs: frozenset[str] = CORE_VENDORED_BUILD_DIR_NAMES
    #: Repo-relative path globs carved OUT of ``vendor_dirs`` — a first-party
    #: library the project maintains inside an otherwise third-party tree.
    #: A different dialect from ``vendor_dirs`` on purpose; see
    #: :mod:`~claude_code_hooks_daemon.utils.vendor_paths`.
    vendor_exceptions: tuple[str, ...] = ()


class TreesConfigProtocol(Protocol):
    """Structural view of ``DocumentationTreesConfig``."""

    @property
    def agent(self) -> str: ...

    @property
    def human(self) -> str: ...


class GeneratedDocEntryProtocol(Protocol):
    """Structural view of ``DocumentationGeneratedDocEntry``."""

    @property
    def glob(self) -> str: ...

    @property
    def generator(self) -> str: ...


class QaConfigProtocol(Protocol):
    """Structural view of ``DocumentationQaConfig``."""

    @property
    def edit_mode(self) -> str: ...

    @property
    def commit_gate_mode(self) -> str: ...

    @property
    def sweep_mode(self) -> str: ...

    @property
    def check_modes(self) -> Mapping[str, str]: ...

    @property
    def grandfather_allowlist(self) -> Sequence[str]: ...

    @property
    def generated_docs(self) -> Sequence[GeneratedDocEntryProtocol]: ...

    @property
    def registered_module_docs(self) -> Sequence[str]: ...

    @property
    def resident_at_imports(self) -> Sequence[str]: ...

    @property
    def scope_exclude_globs(self) -> Sequence[str]: ...


class DocumentationConfigProtocol(Protocol):
    """Structural view of ``DocumentationConfig``."""

    @property
    def enabled(self) -> bool: ...

    @property
    def trees(self) -> TreesConfigProtocol: ...

    @property
    def qa(self) -> QaConfigProtocol: ...


def policy_from_config(
    config: DocumentationConfigProtocol,
    *,
    vendor_dirs: Sequence[str] | None = None,
    vendor_exceptions: Sequence[str] = (),
) -> DocumentationPolicy:
    """Build a plain-values :class:`DocumentationPolicy` from the typed config.

    Args:
        config: The ``documentation:`` block, structurally typed.
        vendor_dirs: The project's EFFECTIVE vendored/build directory names,
            ordinarily ``ProjectLayout.vendor_dirs``. Already merged by the
            caller — the ``additive``/``replace`` semantics belong to
            ``ProjectLayout``, so this is used verbatim and never re-unioned
            with the canonical set (re-unioning would silently defeat
            ``mode: replace``). ``None`` means "no layout available", which
            keeps the canonical default rather than emptying the set.
        vendor_exceptions: ``ProjectLayout.vendor_exceptions`` — repo-relative
            path globs carved OUT of ``vendor_dirs``. Empty is the correct
            default here, unlike ``vendor_dirs``: there is no built-in set of
            first-party carve-outs for a caller to lose.
    """
    qa = config.qa
    return DocumentationPolicy(
        enabled=config.enabled,
        vendor_dirs=(
            CORE_VENDORED_BUILD_DIR_NAMES if vendor_dirs is None else frozenset(vendor_dirs)
        ),
        vendor_exceptions=tuple(vendor_exceptions),
        trees=DocumentationTreesPolicy(agent=config.trees.agent, human=config.trees.human),
        qa=DocumentationQaPolicy(
            edit_mode=qa.edit_mode,
            commit_gate_mode=qa.commit_gate_mode,
            sweep_mode=qa.sweep_mode,
            check_modes=dict(qa.check_modes),
            grandfather_allowlist=tuple(qa.grandfather_allowlist),
            generated_docs=tuple(
                GeneratedDocEntry(glob=entry.glob, generator=entry.generator)
                for entry in qa.generated_docs
            ),
            registered_module_docs=tuple(qa.registered_module_docs),
            resident_at_imports=tuple(qa.resident_at_imports),
            scope_exclude_globs=tuple(qa.scope_exclude_globs),
        ),
    )
