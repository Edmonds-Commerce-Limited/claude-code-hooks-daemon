"""Shared workspace resolver for monorepo-aware handlers.

A single canonical answer to "which sub-tree is this file in", replacing the
several mutually incompatible partial notions scattered across handlers
(``ProjectContext.project_root()``, ``markdown_organization``'s
``monorepo_subproject_patterns``, ``tdd_enforcement``'s everything-before-
``src/`` inference, ``lint_on_edit``'s ``_MODULE_ROOT_MARKERS``, etc.).

Usage:
    from claude_code_hooks_daemon.core.workspace import Workspace

    workspace = Workspace.for_path(edited_file, ProjectContext.project_root())
    if workspace.kind == "node":
        ...
"""

from dataclasses import dataclass
from pathlib import Path

# Recognised manifest filenames, in precedence order. When a single directory
# contains more than one, the first entry in this list wins.
_MANIFEST_KINDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("package.json", "node", ("node_modules/.bin",)),
    ("composer.json", "php", ("vendor/bin",)),
    ("pyproject.toml", "python", (".venv/bin", "venv/bin")),
    ("go.mod", "go", ()),
    ("Cargo.toml", "rust", ()),
)


@dataclass(frozen=True)
class Workspace:
    """A resolved workspace: the nearest recognised manifest to a file.

    Attributes:
        root: Directory containing the resolved manifest, or the project
            root when no manifest was found (single-root fallback).
        kind: One of "node", "php", "python", "go", "rust", or "unknown"
            when no manifest was found.
        manifest: Absolute path to the manifest file that resolved this
            workspace, or None for the "unknown" fallback.
        bin_dirs: Absolute paths to this workspace's tool binary
            directories, in ecosystem-conventional order. Existence is the
            caller's concern -- these are not guaranteed to exist.
    """

    root: Path
    kind: str
    manifest: Path | None
    bin_dirs: tuple[Path, ...]

    @classmethod
    def for_path(cls, file_path: Path, project_root: Path) -> "Workspace":
        """Resolve the workspace containing ``file_path``.

        Walks up from ``file_path``'s directory looking for the nearest
        recognised manifest, stopping at (and including) ``project_root``.
        Falls back to ``project_root`` with kind "unknown" when no manifest
        is found -- this makes single-root repositories behave exactly as
        they do today, with no configuration required.

        If ``file_path`` is not under ``project_root``, the walk still never
        ascends above ``file_path``'s own filesystem root, and a manifest
        found there is honoured; if none is found the walk stops at
        ``file_path``'s own top-level directory and falls back to
        ``project_root``.

        Args:
            file_path: The file being acted on. May be relative; resolved
                to an absolute path before walking.
            project_root: The repository root -- resolution never looks
                above this directory when the file is under it.

        Returns:
            The resolved Workspace.
        """
        file_path = file_path.resolve()
        project_root = project_root.resolve()

        start_dir = file_path if file_path.is_dir() else file_path.parent
        under_project_root = start_dir == project_root or project_root in start_dir.parents

        current = start_dir
        while True:
            manifest, kind, bin_dir_names = cls._find_manifest_in(current)
            if manifest is not None:
                return cls(
                    root=current,
                    kind=kind,
                    manifest=manifest,
                    bin_dirs=tuple(current / name for name in bin_dir_names),
                )

            if under_project_root and current == project_root:
                break
            parent = current.parent
            # Filesystem root reached: only possible for a file outside
            # project_root, where the project_root stop above never fires.
            if parent == current:
                break
            current = parent

        return cls(root=project_root, kind="unknown", manifest=None, bin_dirs=())

    @staticmethod
    def _find_manifest_in(directory: Path) -> tuple[Path | None, str, tuple[str, ...]]:
        """Return the highest-precedence recognised manifest in ``directory``.

        Args:
            directory: Directory to check for manifest files.

        Returns:
            A (manifest_path, kind, bin_dir_names) tuple, or
            (None, "", ()) if no recognised manifest is present.
        """
        for filename, kind, bin_dir_names in _MANIFEST_KINDS:
            candidate = directory / filename
            if candidate.is_file():
                return candidate, kind, bin_dir_names
        return None, "", ()
