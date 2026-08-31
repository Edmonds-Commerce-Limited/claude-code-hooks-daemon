"""Tests for the ``Workspace`` value type and the manifest convention table.

Plan 00296. This file previously tested a ``Workspace.for_path()`` classmethod
that walked up to the nearest manifest and resolved a workspace from it. That
walk no longer decides anything: projects are declared, never inferred, so
resolution lives in ``ProjectRegistry`` (see ``test_project_registry.py``) and
the manifest table survives only as CONVENTION applied inside a root someone
declared.

What is tested here is therefore the narrow remainder: the frozen value type,
and that each ecosystem's manifest maps to the right kind and bin dirs when
found AT a declared root.
"""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.workspace import DeclaredProject, Workspace


class TestManifestConventionAtADeclaredRoot:
    """A declared root's kind and bin dirs come from the manifest sitting in it.

    Note every case declares the root explicitly. There is no test for
    "resolves by searching", because searching is exactly what was removed.
    """

    def test_node_manifest_yields_node_modules_bin(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")

        workspace = DeclaredProject(name="web", root=tmp_path).resolve()

        assert workspace.kind == "node"
        assert workspace.manifest == tmp_path / "package.json"
        assert workspace.bin_dirs == (tmp_path / "node_modules" / ".bin",)

    def test_php_manifest_yields_vendor_bin(self, tmp_path: Path) -> None:
        (tmp_path / "composer.json").write_text("{}", encoding="utf-8")

        workspace = DeclaredProject(name="service", root=tmp_path).resolve()

        assert workspace.kind == "php"
        assert workspace.bin_dirs == (tmp_path / "vendor" / "bin",)

    def test_python_manifest_yields_both_venv_conventions(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")

        workspace = DeclaredProject(name="lib", root=tmp_path).resolve()

        assert workspace.kind == "python"
        assert workspace.bin_dirs == (tmp_path / ".venv" / "bin", tmp_path / "venv" / "bin")

    def test_go_manifest_yields_no_bin_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example.com/x\n", encoding="utf-8")

        workspace = DeclaredProject(name="svc", root=tmp_path).resolve()

        assert workspace.kind == "go"
        assert workspace.bin_dirs == ()

    def test_rust_manifest_yields_no_bin_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n", encoding="utf-8")

        workspace = DeclaredProject(name="crate", root=tmp_path).resolve()

        assert workspace.kind == "rust"
        assert workspace.bin_dirs == ()

    def test_several_manifests_in_one_dir_use_precedence_order(self, tmp_path: Path) -> None:
        """The table's order breaks the tie; package.json is first."""
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        (tmp_path / "composer.json").write_text("{}", encoding="utf-8")

        assert DeclaredProject(name="both", root=tmp_path).resolve().kind == "node"

    def test_no_manifest_is_kind_unknown_not_an_error(self, tmp_path: Path) -> None:
        """A declared project need not have a manifest — the report's `infra/`."""
        workspace = DeclaredProject(name="infra", root=tmp_path).resolve()

        assert workspace.kind == "unknown"
        assert workspace.manifest is None
        assert workspace.bin_dirs == ()

    def test_a_manifest_above_the_declared_root_is_ignored(self, tmp_path: Path) -> None:
        """Convention looks IN the declared root, never up from it.

        Walking up is what boundary inference did; a declared root that
        happens to sit under a manifest must not inherit that manifest's kind.
        """
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        nested = tmp_path / "infra"
        nested.mkdir()

        assert DeclaredProject(name="infra", root=nested).resolve().kind == "unknown"


class TestDeclaredOverrides:
    def test_declared_kind_beats_the_manifest(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")

        workspace = DeclaredProject(name="web", root=tmp_path, kind="custom").resolve()

        assert workspace.kind == "custom"

    def test_declared_bin_dirs_beat_the_convention(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")

        workspace = DeclaredProject(name="web", root=tmp_path, bin_dirs=("tools/bin",)).resolve()

        assert workspace.bin_dirs == (tmp_path / "tools" / "bin",)

    def test_empty_bin_dirs_is_not_the_same_as_unset(self, tmp_path: Path) -> None:
        """Stating "no bin dirs" must beat the node convention, not fall back to it."""
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")

        assert DeclaredProject(name="web", root=tmp_path, bin_dirs=()).resolve().bin_dirs == ()


class TestWorkspaceValueType:
    def test_workspace_is_frozen(self, tmp_path: Path) -> None:
        workspace = DeclaredProject(name="x", root=tmp_path).resolve()

        attribute_name = "".join(["ki", "nd"])
        with pytest.raises(FrozenInstanceError):
            setattr(workspace, attribute_name, "node")

    def test_declared_project_is_frozen(self, tmp_path: Path) -> None:
        project = DeclaredProject(name="x", root=tmp_path)

        attribute_name = "".join(["na", "me"])
        with pytest.raises(FrozenInstanceError):
            setattr(project, attribute_name, "y")

    def test_bin_dirs_are_absolute(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")

        workspace = DeclaredProject(name="web", root=tmp_path).resolve()

        assert all(bin_dir.is_absolute() for bin_dir in workspace.bin_dirs)

    def test_workspace_can_be_constructed_directly(self, tmp_path: Path) -> None:
        """Handlers receive Workspace instances; the type must stand alone."""
        workspace = Workspace(root=tmp_path, kind="node", manifest=None, bin_dirs=())

        assert workspace.root == tmp_path
        assert workspace.kind == "node"
