"""Tests for the shared workspace resolver."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.workspace import Workspace


class TestWorkspaceForPath:
    """Tests for Workspace.for_path()."""

    def test_node_workspace_resolves_via_package_json(self, tmp_path: Path) -> None:
        """A file under a directory with package.json resolves to a node workspace."""
        project_root = tmp_path
        workspace_dir = project_root / "web"
        workspace_dir.mkdir()
        (workspace_dir / "package.json").write_text("{}")
        src_file = workspace_dir / "src" / "index.ts"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("")

        workspace = Workspace.for_path(src_file, project_root)

        assert workspace.root == workspace_dir
        assert workspace.kind == "node"
        assert workspace.manifest == workspace_dir / "package.json"
        assert workspace.bin_dirs == (workspace_dir / "node_modules" / ".bin",)

    def test_php_workspace_resolves_via_composer_json(self, tmp_path: Path) -> None:
        """A file under a directory with composer.json resolves to a php workspace."""
        project_root = tmp_path
        workspace_dir = project_root / "service"
        workspace_dir.mkdir()
        (workspace_dir / "composer.json").write_text("{}")
        src_file = workspace_dir / "src" / "Foo.php"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("")

        workspace = Workspace.for_path(src_file, project_root)

        assert workspace.root == workspace_dir
        assert workspace.kind == "php"
        assert workspace.manifest == workspace_dir / "composer.json"
        assert workspace.bin_dirs == (workspace_dir / "vendor" / "bin",)

    def test_python_workspace_resolves_via_pyproject_toml(self, tmp_path: Path) -> None:
        """A file under a directory with pyproject.toml resolves to a python workspace."""
        project_root = tmp_path
        workspace_dir = project_root / "pylib"
        workspace_dir.mkdir()
        (workspace_dir / "pyproject.toml").write_text("")
        src_file = workspace_dir / "src" / "mod.py"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("")

        workspace = Workspace.for_path(src_file, project_root)

        assert workspace.root == workspace_dir
        assert workspace.kind == "python"
        assert workspace.manifest == workspace_dir / "pyproject.toml"
        assert workspace.bin_dirs == (
            workspace_dir / ".venv" / "bin",
            workspace_dir / "venv" / "bin",
        )

    def test_go_workspace_resolves_via_go_mod(self, tmp_path: Path) -> None:
        """A file under a directory with go.mod resolves to a go workspace with no bin dirs."""
        project_root = tmp_path
        workspace_dir = project_root / "svc"
        workspace_dir.mkdir()
        (workspace_dir / "go.mod").write_text("module svc\n")
        src_file = workspace_dir / "main.go"
        src_file.write_text("")

        workspace = Workspace.for_path(src_file, project_root)

        assert workspace.root == workspace_dir
        assert workspace.kind == "go"
        assert workspace.manifest == workspace_dir / "go.mod"
        assert workspace.bin_dirs == ()

    def test_rust_workspace_resolves_via_cargo_toml(self, tmp_path: Path) -> None:
        """A file under a directory with Cargo.toml resolves to a rust workspace."""
        project_root = tmp_path
        workspace_dir = project_root / "crate"
        workspace_dir.mkdir()
        (workspace_dir / "Cargo.toml").write_text("")
        src_file = workspace_dir / "src" / "main.rs"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("")

        workspace = Workspace.for_path(src_file, project_root)

        assert workspace.root == workspace_dir
        assert workspace.kind == "rust"
        assert workspace.manifest == workspace_dir / "Cargo.toml"
        assert workspace.bin_dirs == ()

    def test_nested_workspace_under_root_manifest_prefers_nearest(self, tmp_path: Path) -> None:
        """A root-level manifest does not shadow a nearer manifest in a subdirectory."""
        project_root = tmp_path
        (project_root / "package.json").write_text("{}")
        nested = project_root / "packages" / "app"
        nested.mkdir(parents=True)
        (nested / "package.json").write_text("{}")
        src_file = nested / "src" / "index.ts"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("")

        workspace = Workspace.for_path(src_file, project_root)

        assert workspace.root == nested
        assert workspace.manifest == nested / "package.json"

    def test_no_manifest_falls_back_to_project_root(self, tmp_path: Path) -> None:
        """With no manifest anywhere up to the project root, fall back to project root unknown."""
        project_root = tmp_path
        src_file = project_root / "docs" / "notes.txt"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("")

        workspace = Workspace.for_path(src_file, project_root)

        assert workspace == Workspace(
            root=project_root, kind="unknown", manifest=None, bin_dirs=()
        )

    def test_walk_stops_at_project_root_manifest_above_ignored(self, tmp_path: Path) -> None:
        """A manifest that lives ABOVE project_root is never considered."""
        outer_root = tmp_path
        (outer_root / "package.json").write_text("{}")
        project_root = outer_root / "project"
        project_root.mkdir()
        src_file = project_root / "docs" / "notes.txt"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("")

        workspace = Workspace.for_path(src_file, project_root)

        assert workspace == Workspace(
            root=project_root, kind="unknown", manifest=None, bin_dirs=()
        )

    def test_multiple_manifests_in_one_dir_use_precedence_order(self, tmp_path: Path) -> None:
        """When a directory holds several manifests, node > php > python > go > rust wins."""
        project_root = tmp_path
        workspace_dir = project_root / "mixed"
        workspace_dir.mkdir()
        (workspace_dir / "composer.json").write_text("{}")
        (workspace_dir / "pyproject.toml").write_text("")
        (workspace_dir / "package.json").write_text("{}")
        src_file = workspace_dir / "index.ts"
        src_file.write_text("")

        workspace = Workspace.for_path(src_file, project_root)

        assert workspace.kind == "node"
        assert workspace.manifest == workspace_dir / "package.json"

    def test_bin_dirs_are_absolute(self, tmp_path: Path) -> None:
        """bin_dirs are returned as absolute paths under the workspace root."""
        project_root = tmp_path
        workspace_dir = project_root / "web"
        workspace_dir.mkdir()
        (workspace_dir / "package.json").write_text("{}")
        src_file = workspace_dir / "index.ts"
        src_file.write_text("")

        workspace = Workspace.for_path(src_file, project_root)

        assert all(bin_dir.is_absolute() for bin_dir in workspace.bin_dirs)

    def test_file_directly_in_workspace_root(self, tmp_path: Path) -> None:
        """A file that lives directly beside the manifest resolves without descending further."""
        project_root = tmp_path
        (project_root / "package.json").write_text("{}")
        src_file = project_root / "index.ts"
        src_file.write_text("")

        workspace = Workspace.for_path(src_file, project_root)

        assert workspace.root == project_root
        assert workspace.manifest == project_root / "package.json"

    def test_workspace_is_frozen(self, tmp_path: Path) -> None:
        """Workspace instances are immutable."""
        workspace = Workspace(root=tmp_path, kind="unknown", manifest=None, bin_dirs=())

        attribute_name = "".join(["ki", "nd"])
        with pytest.raises(FrozenInstanceError):
            setattr(workspace, attribute_name, "node")
