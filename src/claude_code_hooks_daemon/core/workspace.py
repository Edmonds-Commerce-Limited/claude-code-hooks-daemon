"""Project resolution: which declared project is this file in?

A project is **configured, never inferred**. :class:`ProjectRegistry` resolves
a file to the nearest DECLARED project containing it, falling back to the
repository root when nothing is declared -- which is exactly what every
single-project repository does today.

Deliberately absent: any walk-up that decides a boundary from what happens to
be on disk. Inferring boundaries would reintroduce the failure this exists to
fix, one level up -- a wrongly inferred boundary leaves enforcement looking
healthy while pointing at the wrong tree, and nothing says so. The manifest
table below is used only for convention INSIDE a declared root, and (by the
monorepo detector) to tell a human what is worth declaring.

Depth: ``CLAUDE/Code/WorkspaceResolution.md``.

Usage:
    from claude_code_hooks_daemon.core.workspace import ProjectRegistry

    workspace = registry.for_path(edited_file)
    if workspace.kind == "node":
        ...
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from claude_code_hooks_daemon.core.project_layout import ProjectLayout
from claude_code_hooks_daemon.utils.vendor_paths import VendorScope

if TYPE_CHECKING:
    from claude_code_hooks_daemon.config.models import Config, LayoutConfig

# Recognised manifest filenames, in precedence order, used only to break ties
# when one directory holds several. This table does NOT decide where a project
# is -- only what an ecosystem conventionally looks like inside a root someone
# declared, and what the detector reports as worth declaring.
_MANIFEST_KINDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("package.json", "node", ("node_modules/.bin",)),
    ("composer.json", "php", ("vendor/bin",)),
    ("pyproject.toml", "python", (".venv/bin", "venv/bin")),
    ("go.mod", "go", ()),
    ("Cargo.toml", "rust", ()),
)

_UNKNOWN_KIND = "unknown"


def _manifest_in(directory: Path) -> tuple[Path | None, str, tuple[str, ...]]:
    """Return the highest-precedence recognised manifest in ``directory``.

    Args:
        directory: Directory to check for manifest files. NOT walked -- this
            looks in exactly one directory.

    Returns:
        A ``(manifest_path, kind, bin_dir_names)`` tuple, or
        ``(None, "unknown", ())`` when no recognised manifest is present.
    """
    for filename, kind, bin_dir_names in _MANIFEST_KINDS:
        candidate = directory / filename
        if candidate.is_file():
            return candidate, kind, bin_dir_names
    return None, _UNKNOWN_KIND, ()


@dataclass(frozen=True)
class Workspace:
    """The resolved project a file belongs to.

    Attributes:
        root: The declared project's absolute root, or the repository root
            when the file is in no declared project.
        kind: ``node``, ``php``, ``python``, ``go``, ``rust``, a value the
            project declared, or ``unknown``.
        manifest: Absolute path to the manifest found AT ``root``, or None.
            A declared project need not have one.
        bin_dirs: Absolute tool binary directories, in ecosystem-conventional
            order. Existence is the caller's concern -- these are not probed.
    """

    root: Path
    kind: str
    manifest: Path | None
    bin_dirs: tuple[Path, ...]


@dataclass(frozen=True)
class DeclaredProject:
    """One project declared in the ``projects:`` config block.

    Attributes:
        name: Identifier, unique within the registry.
        root: Absolute project root.
        kind: Declared ecosystem, or None to infer from the manifest at root.
        bin_dirs: Declared root-relative bin dirs, or None to infer from the
            manifest. An EMPTY tuple is a project stating it has none -- a
            different statement from staying silent, so the two must not be
            conflated.
    """

    name: str
    root: Path
    kind: str | None = None
    bin_dirs: tuple[str, ...] | None = None
    layout: LayoutConfig | None = None

    def resolve(self) -> Workspace:
        """Build the :class:`Workspace` for this declaration.

        ``kind`` and ``bin_dirs`` fall back to the convention implied by the
        manifest at ``root``. That is convention inside a boundary the user
        drew, not a guess about where the boundary is.
        """
        manifest, detected_kind, detected_bin_dirs = _manifest_in(self.root)

        bin_dir_names = self.bin_dirs if self.bin_dirs is not None else detected_bin_dirs
        return Workspace(
            root=self.root,
            kind=self.kind or detected_kind,
            manifest=manifest,
            bin_dirs=tuple(self.root / name for name in bin_dir_names),
        )


@dataclass(frozen=True)
class ProjectRegistry:
    """The declared projects of one repository, resolved per file.

    Built once per config load via :meth:`from_config` and injected onto
    handlers, mirroring ``ProjectLayout`` (Plan 00288). Handlers never read
    raw config.

    Attributes:
        project_root: The repository root -- the fallback project.
        projects: Declared projects, in config order. Empty means
            single-project, which is the zero-config default.
        root_layout: The ROOT project's own `ProjectLayout` (from the
            top-level `layout:` block). This is the root project's layout
            ONLY -- never a global fallback leaked into a declared
            sub-project (Plan 00300); see :meth:`layout_for`.
    """

    project_root: Path
    projects: tuple[DeclaredProject, ...] = ()
    root_layout: ProjectLayout = field(default_factory=ProjectLayout.built_in_default)

    @classmethod
    def single_project(
        cls, project_root: Path, root_layout: ProjectLayout | None = None
    ) -> ProjectRegistry:
        """A registry with nothing declared: one project at the repo root."""
        return cls(
            project_root=project_root.resolve(),
            projects=(),
            root_layout=root_layout or ProjectLayout.built_in_default(),
        )

    @classmethod
    def from_config(cls, config: Config, project_root: Path) -> ProjectRegistry:
        """Build from a validated ``projects:`` block.

        Args:
            config: The loaded daemon configuration.
            project_root: Absolute repository root that declared roots are
                relative to.

        Returns:
            A registry; equivalent to :meth:`single_project` when the block
            is absent or empty.
        """
        resolved_root = project_root.resolve()
        declared = tuple(
            DeclaredProject(
                name=entry.name,
                root=(resolved_root / entry.root).resolve(),
                kind=entry.kind,
                bin_dirs=tuple(entry.bin_dirs) if entry.bin_dirs is not None else None,
                layout=entry.layout,
            )
            for entry in config.projects
        )
        return cls(
            project_root=resolved_root,
            projects=declared,
            root_layout=ProjectLayout.from_config(config),
        )

    def for_path(self, file_path: Path) -> Workspace:
        """Resolve the project containing ``file_path``.

        The NEAREST declared root containing the file wins, so nesting a
        package inside a workspace resolves unambiguously and config ORDER
        never decides the answer. A file in no declared project resolves to
        the repository root.

        Args:
            file_path: The file being acted on. May be relative; resolved to
                an absolute path first.

        Returns:
            The resolved Workspace. Never None -- the repository root is
            always a valid answer.
        """
        best = self._nearest_project(file_path.resolve())
        if best is not None:
            return best.resolve()
        return DeclaredProject(name="", root=self.project_root).resolve()

    def layout_for(self, file_path: Path) -> ProjectLayout:
        """Resolve the `ProjectLayout` OWNING ``file_path`` (Plan 00300).

        A declared project without its own `layout:` block uses BUILT-IN
        defaults for its four directory-role lists, never the root
        project's declared lists -- one project's layout must never leak
        into a sibling's, same declared-not-inferred philosophy as
        `for_path`. A file resolving to no declared project (including
        every file in a zero-config, single-project repository) gets
        `root_layout` -- byte-identical to pre-Plan-00300 behaviour.

        This is the DRY helper every per-file consumer of ProjectLayout
        should call instead of hand-rolling project resolution; use
        :meth:`iter_layouts`/:meth:`all_source_dirs` for whole-repo
        aggregation instead.

        Args:
            file_path: The file being acted on. May be relative; resolved to
                an absolute path first.
        """
        best = self._nearest_project(file_path.resolve())
        if best is None:
            return self.root_layout
        return ProjectLayout.for_project(best.layout, self.root_layout)

    def iter_layouts(self) -> Iterator[tuple[str, ProjectLayout]]:
        """Yield ``(label, ProjectLayout)`` for the root project + every declared project.

        The root project's label is ``""``. DRY aggregation helper for a
        handler that needs the union across EVERY project (e.g. "does any
        project in this repo call `test/` a test dir?") rather than "the
        owning project for one path" (:meth:`layout_for`). Handlers must
        never hand-roll this loop.
        """
        yield "", self.root_layout
        for project in self.projects:
            yield project.name, ProjectLayout.for_project(project.layout, self.root_layout)

    def vendor_scopes(self) -> tuple[VendorScope, ...]:
        """Every project's vendor truth, keyed by the repo-relative root it governs.

        The registry is the only place that knows BOTH a project's declared
        root and its resolved layout, which is why this cannot live where it
        is consumed. :meth:`iter_layouts` yields the project NAME, and a name
        cannot be matched against a path -- so it cannot serve here.

        Built for ``docs_qa``, which may not import ``ProjectLayout``
        (``core.project_layout`` already imports ``docs_qa.corpus``, so the
        reverse closes a cycle). Handing over plain
        :class:`~utils.vendor_paths.VendorScope` values keeps that boundary
        while still giving docs QA a per-path answer (Plan 00332).

        Returns:
            The root project's scope first, then one per declared project.
            Order carries no meaning -- resolution is longest-root-wins, so a
            reader must not infer precedence from position.
        """
        scopes = [
            VendorScope(
                root="",
                vendor_dirs=self.root_layout.vendor_dirs,
                vendor_exceptions=self.root_layout.vendor_exceptions,
            )
        ]
        for project in self.projects:
            layout = ProjectLayout.for_project(project.layout, self.root_layout)
            relative = os.path.relpath(project.root, self.project_root).replace("\\", "/")
            if relative == ".." or relative.startswith("../"):
                # A project declared OUTSIDE the repository root governs no
                # path the walkers will ever visit. Skipped rather than
                # keyed by a `..` root, which `_is_under` would read as a
                # literal segment and never match.
                continue
            scopes.append(
                VendorScope(
                    root="" if relative == "." else relative,
                    vendor_dirs=layout.vendor_dirs,
                    vendor_exceptions=layout.vendor_exceptions,
                )
            )
        return tuple(scopes)

    def all_source_dirs(self) -> tuple[str, ...]:
        """Union of `source_dirs` across the root project and every declared project.

        Order-preserving, de-duplicated (first occurrence wins), built on
        :meth:`iter_layouts` -- the DRY aggregation primitive every
        whole-repo-scoped consumer should share rather than re-deriving.
        """
        seen: dict[str, None] = {}
        for _, layout in self.iter_layouts():
            for name in layout.source_dirs:
                seen.setdefault(name, None)
        return tuple(seen)

    def _nearest_project(self, resolved: Path) -> DeclaredProject | None:
        """The nearest declared project containing ``resolved``, or None.

        Shared by :meth:`for_path` and :meth:`layout_for` so "nearest
        declared root wins" is decided in exactly one place.
        """
        best: DeclaredProject | None = None
        for project in self.projects:
            if not self._contains(project.root, resolved):
                continue
            # Nearest wins: a deeper root is more specific. Comparing part
            # COUNTS rather than string lengths keeps a long-named shallow
            # root from beating a short-named deeper one.
            if best is None or len(project.root.parts) > len(best.root.parts):
                best = project
        return best

    @staticmethod
    def _contains(root: Path, candidate: Path) -> bool:
        """Whether ``candidate`` is at or under ``root``.

        Compares path PARTS, not string prefixes: ``apps/web`` must not
        capture ``apps/web-admin``, which a ``startswith`` check would.
        """
        if candidate == root:
            return True
        return root in candidate.parents


def resolve_workspace(
    registry: ProjectRegistry | None, file_path: Path, project_root: Path
) -> Workspace:
    """Resolve ``file_path``'s project via an injected registry.

    The registry is injected onto handlers at construction and is None only
    where that injection has not happened -- a unit test exercising a handler
    directly, or a context with no loaded config. Falling back to a
    single-project registry there keeps the zero-config answer (the repository
    root) rather than raising, which is also the correct answer for every
    repository that declares nothing.

    Args:
        registry: The injected ``_project_registry``, or None.
        file_path: The file being acted on.
        project_root: Repository root, used only for the fallback.

    Returns:
        The resolved Workspace.
    """
    effective = registry if registry is not None else ProjectRegistry.single_project(project_root)
    return effective.for_path(file_path)


def resolve_layout(
    registry: ProjectRegistry | None,
    file_path: Path,
    project_root: Path,
    *,
    fallback_root_layout: ProjectLayout | None = None,
) -> ProjectLayout:
    """Resolve ``file_path``'s owning `ProjectLayout` via an injected registry (Plan 00300).

    Mirrors :func:`resolve_workspace`: the registry is injected onto
    handlers at construction and is None only where that injection has not
    happened (a unit test exercising a handler directly). Falling back to a
    single-project registry there keeps the zero-config answer -- the
    caller's own already-injected `_project_layout` facade, when one is
    passed as ``fallback_root_layout``, or the built-in defaults otherwise.

    Args:
        registry: The injected ``_project_registry``, or None.
        file_path: The file being acted on.
        project_root: Repository root, used only for the fallback.
        fallback_root_layout: The root layout to use when no registry is
            injected -- ordinarily the caller's own `_project_layout`
            (already injected by the registry, Plan 00288), so behaviour
            stays byte-identical to before this helper existed.

    Returns:
        The resolved `ProjectLayout`.
    """
    if registry is not None:
        return registry.layout_for(file_path)
    root_layout = fallback_root_layout or ProjectLayout.built_in_default()
    return ProjectRegistry.single_project(project_root, root_layout=root_layout).layout_for(
        file_path
    )
