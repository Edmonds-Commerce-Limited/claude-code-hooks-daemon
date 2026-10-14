"""Shared module-root and effective-path resolution for lint runs."""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.strategies.lint.module_context import (
    MODULE_ROOT_MARKERS,
    find_module_root,
    resolve_module_context,
)


class TestFindModuleRoot:
    def test_walks_up_to_the_marker(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module m\n")
        source = tmp_path / "a" / "b" / "x.go"
        source.parent.mkdir(parents=True)
        source.write_text("package b\n")

        assert find_module_root(str(source), "go.mod") == str(tmp_path)

    def test_returns_none_without_a_marker(self, tmp_path: Path) -> None:
        source = tmp_path / "x.go"
        source.write_text("package main\n")

        assert find_module_root(str(source), "go.mod") is None


class TestResolveModuleContext:
    def test_go_with_a_module_vets_the_package_directory(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module m\n")
        source = tmp_path / "app" / "app.go"
        source.parent.mkdir()
        source.write_text("package app\n")

        context = resolve_module_context(str(source), "Go")

        assert context.module_root == str(tmp_path)
        assert context.effective_path == "./app/"

    def test_go_at_the_module_root_vets_the_root_package(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module m\n")
        source = tmp_path / "main.go"
        source.write_text("package main\n")

        assert resolve_module_context(str(source), "Go").effective_path == "./" + "/"

    def test_go_without_a_module_keeps_the_single_file(self, tmp_path: Path) -> None:
        source = tmp_path / "main.go"
        source.write_text("package main\n")

        context = resolve_module_context(str(source), "Go")

        assert context.module_root is None
        assert context.effective_path == str(source)

    def test_other_languages_keep_the_file_but_report_their_root(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("[package]\n")
        source = tmp_path / "src" / "lib.rs"
        source.parent.mkdir()
        source.write_text("")

        context = resolve_module_context(str(source), "Rust")

        assert context.module_root == str(tmp_path)
        assert context.effective_path == str(source)

    def test_a_language_without_a_marker_has_no_root(self, tmp_path: Path) -> None:
        source = tmp_path / "a.py"
        source.write_text("")

        context = resolve_module_context(str(source), "Python")

        assert context.module_root is None
        assert context.effective_path == str(source)

    def test_markers_cover_go_ansible_and_rust(self) -> None:
        assert MODULE_ROOT_MARKERS == {
            "Go": "go.mod",
            "Ansible": "ansible.cfg",
            "Rust": "Cargo.toml",
        }
