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

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claude_code_hooks_daemon.config.models import Config

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
    """

    project_root: Path
    projects: tuple[DeclaredProject, ...] = ()

    @classmethod
    def single_project(cls, project_root: Path) -> ProjectRegistry:
        """A registry with nothing declared: one project at the repo root."""
        return cls(project_root=project_root.resolve(), projects=())

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
            )
            for entry in config.projects
        )
        return cls(project_root=resolved_root, projects=declared)

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
        resolved = file_path.resolve()

        best: DeclaredProject | None = None
        for project in self.projects:
            if not self._contains(project.root, resolved):
                continue
            # Nearest wins: a deeper root is more specific. Comparing part
            # COUNTS rather than string lengths keeps a long-named shallow
            # root from beating a short-named deeper one.
            if best is None or len(project.root.parts) > len(best.root.parts):
                best = project

        if best is not None:
            return best.resolve()

        return DeclaredProject(name="", root=self.project_root).resolve()

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
