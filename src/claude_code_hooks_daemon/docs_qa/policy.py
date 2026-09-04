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
from claude_code_hooks_daemon.utils.vendor_paths import VendorScope

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

    ``vendor_scopes`` is the one axis here with no ``documentation:`` config
    home: it mirrors ``layout.vendor_dirs``/``vendor_exceptions``, which are
    project-wide truths (Plan 00288) rather than docs-QA settings. They
    arrive as PLAIN VALUES from the caller for the same reason every other
    field does — importing ``ProjectLayout`` would couple this package to
    ``core``, and ``core.project_layout`` already imports ``docs_qa.corpus``,
    so the coupling would close a cycle.
    """

    enabled: bool = False
    trees: DocumentationTreesPolicy = field(default_factory=DocumentationTreesPolicy)
    qa: DocumentationQaPolicy = field(default_factory=DocumentationQaPolicy)
    #: One entry per declared project, each carrying the ROOT it governs
    #: alongside its vendored names and carve-outs. A flat pair of sets
    #: replaced this and could only express a repo-wide answer, so a
    #: monorepo sub-project's declaration was invisible here (Plan 00332).
    #: Resolution is per-path and never a union — see
    #: :func:`~utils.vendor_paths.is_vendored_path_in_scopes`.
    #:
    #: The default is the canonical set at the repository root, so a caller
    #: with no layout to hand loses nothing.
    vendor_scopes: tuple[VendorScope, ...] = (
        VendorScope(root="", vendor_dirs=CORE_VENDORED_BUILD_DIR_NAMES, vendor_exceptions=()),
    )


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
    vendor_scopes: Sequence[VendorScope] | None = None,
) -> DocumentationPolicy:
    """Build a plain-values :class:`DocumentationPolicy` from the typed config.

    Args:
        config: The ``documentation:`` block, structurally typed.
        vendor_scopes: One :class:`~utils.vendor_paths.VendorScope` per
            declared project, ordinarily built from
            ``ProjectRegistry.iter_layouts()``. Each scope's ``vendor_dirs``
            is the EFFECTIVE set already merged by ``ProjectLayout`` — the
            ``additive``/``replace`` semantics belong to the facade, so these
            are used verbatim and never re-unioned with the canonical set
            (re-unioning would silently defeat ``mode: replace``).

            ``None`` means "no layout available" and keeps the canonical set
            at the repository root, rather than emptying it. An explicitly
            EMPTY sequence is different and is honoured: it means nothing is
            vendored anywhere.
    """
    qa = config.qa
    return DocumentationPolicy(
        enabled=config.enabled,
        vendor_scopes=(
            DocumentationPolicy.vendor_scopes if vendor_scopes is None else tuple(vendor_scopes)
        ),
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
