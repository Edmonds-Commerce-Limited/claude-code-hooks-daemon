"""Tests for ``ProjectRegistry`` — declared projects resolve, nothing is inferred.

Plan 00296 Task 3.2. The registry is the ONLY source of project boundaries.
An undeclared repository resolves one project at its root, which is exactly
what every single-project repository does today.

The property these tests exist to defend is a negative one: a repository that
LOOKS like a monorepo but declares nothing must NOT be silently split up. A
wrongly guessed boundary leaves enforcement looking healthy while pointing at
the wrong tree, and nothing says so — the same silent failure this whole
mechanism exists to remove.
"""

from pathlib import Path

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core.workspace import ProjectRegistry


def _monorepo(tmp_path: Path) -> Path:
    """Two manifest-bearing workspaces plus one with no manifest at all."""
    web = tmp_path / "apps" / "web"
    (web / "src").mkdir(parents=True)
    (web / "package.json").write_text("{}", encoding="utf-8")

    service = tmp_path / "apps" / "service"
    (service / "src").mkdir(parents=True)
    (service / "composer.json").write_text("{}", encoding="utf-8")

    infra = tmp_path / "infra" / "roles"
    infra.mkdir(parents=True)
    (tmp_path / "infra" / "ansible.cfg").write_text("[defaults]\n", encoding="utf-8")

    return tmp_path


class TestUndeclaredRepositoryIsNotSplitUp:
    """No declarations means one project at the root. No guessing."""

    def test_manifest_bearing_subdir_still_resolves_to_the_repo_root(self, tmp_path: Path) -> None:
        """THE anti-inference test.

        `apps/web` has a package.json and looks exactly like a workspace. With
        nothing declared it must still resolve to the repository root: the
        daemon reports the shape, it does not act on it.
        """
        root = _monorepo(tmp_path)
        registry = ProjectRegistry.single_project(root)

        workspace = registry.for_path(root / "apps" / "web" / "src" / "index.ts")

        assert workspace.root == root

    def test_root_workspace_still_reports_a_root_manifest(self, tmp_path: Path) -> None:
        """Convention inside the ONE declared boundary still applies."""
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        registry = ProjectRegistry.single_project(tmp_path)

        workspace = registry.for_path(tmp_path / "src" / "index.ts")

        assert workspace.root == tmp_path
        assert workspace.kind == "node"
        assert workspace.bin_dirs == (tmp_path / "node_modules" / ".bin",)

    def test_no_manifest_anywhere_is_kind_unknown(self, tmp_path: Path) -> None:
        registry = ProjectRegistry.single_project(tmp_path)

        workspace = registry.for_path(tmp_path / "notes.txt")

        assert workspace.kind == "unknown"
        assert workspace.manifest is None
        assert workspace.bin_dirs == ()


class TestDeclaredProjectsResolve:
    @staticmethod
    def _registry(root: Path, projects: list[dict[str, object]]) -> ProjectRegistry:
        config = Config.model_validate({"projects": projects})
        return ProjectRegistry.from_config(config, root)

    def test_file_resolves_to_its_declared_project(self, tmp_path: Path) -> None:
        root = _monorepo(tmp_path)
        registry = self._registry(
            root,
            [
                {"name": "web", "root": "apps/web"},
                {"name": "service", "root": "apps/service"},
            ],
        )

        workspace = registry.for_path(root / "apps" / "web" / "src" / "index.ts")

        assert workspace.root == root / "apps" / "web"

    def test_sibling_project_is_not_confused_with_it(self, tmp_path: Path) -> None:
        root = _monorepo(tmp_path)
        registry = self._registry(
            root,
            [
                {"name": "web", "root": "apps/web"},
                {"name": "service", "root": "apps/service"},
            ],
        )

        workspace = registry.for_path(root / "apps" / "service" / "src" / "Foo.php")

        assert workspace.root == root / "apps" / "service"
        assert workspace.kind == "php"
        assert workspace.bin_dirs == (root / "apps" / "service" / "vendor" / "bin",)

    def test_a_declared_project_with_no_manifest_resolves(self, tmp_path: Path) -> None:
        """The report's `infra/`: config-driven, nothing to detect.

        This is the case that cannot be reached any other way, and the reason
        declaration exists at all.
        """
        root = _monorepo(tmp_path)
        registry = self._registry(
            root, [{"name": "infra", "root": "infra", "kind": "ansible", "bin_dirs": [".venv/bin"]}]
        )

        workspace = registry.for_path(root / "infra" / "roles" / "web.yml")

        assert workspace.root == root / "infra"
        assert workspace.kind == "ansible"
        assert workspace.bin_dirs == (root / "infra" / ".venv" / "bin",)
        assert workspace.manifest is None

    def test_file_outside_every_declared_project_falls_back_to_the_root(
        self, tmp_path: Path
    ) -> None:
        """Declaring some projects does not orphan the rest of the repository."""
        root = _monorepo(tmp_path)
        registry = self._registry(root, [{"name": "web", "root": "apps/web"}])

        workspace = registry.for_path(root / "docs" / "readme.md")

        assert workspace.root == root

    def test_nearest_declared_root_wins_when_projects_nest(self, tmp_path: Path) -> None:
        root = _monorepo(tmp_path)
        registry = self._registry(
            root,
            [
                {"name": "apps", "root": "apps"},
                {"name": "web", "root": "apps/web"},
            ],
        )

        workspace = registry.for_path(root / "apps" / "web" / "src" / "index.ts")

        assert workspace.root == root / "apps" / "web", "the nearer declaration must win"

    def test_declaration_order_does_not_decide_nesting(self, tmp_path: Path) -> None:
        """Same as above with the entries reversed — ordering must not matter."""
        root = _monorepo(tmp_path)
        registry = self._registry(
            root,
            [
                {"name": "web", "root": "apps/web"},
                {"name": "apps", "root": "apps"},
            ],
        )

        workspace = registry.for_path(root / "apps" / "web" / "src" / "index.ts")

        assert workspace.root == root / "apps" / "web"

    def test_dot_root_declares_the_repository_itself(self, tmp_path: Path) -> None:
        root = _monorepo(tmp_path)
        registry = self._registry(
            root, [{"name": "repo", "root": "."}, {"name": "web", "root": "apps/web"}]
        )

        assert registry.for_path(root / "docs" / "x.md").root == root
        assert (
            registry.for_path(root / "apps" / "web" / "src" / "i.ts").root == root / "apps" / "web"
        )

    def test_kind_is_inferred_from_the_manifest_at_a_declared_root(self, tmp_path: Path) -> None:
        """Convention inside a boundary the user drew — not boundary inference."""
        root = _monorepo(tmp_path)
        registry = self._registry(root, [{"name": "web", "root": "apps/web"}])

        workspace = registry.for_path(root / "apps" / "web" / "src" / "index.ts")

        assert workspace.kind == "node"
        assert workspace.manifest == root / "apps" / "web" / "package.json"

    def test_declared_kind_overrides_the_manifest(self, tmp_path: Path) -> None:
        root = _monorepo(tmp_path)
        registry = self._registry(root, [{"name": "web", "root": "apps/web", "kind": "custom"}])

        assert registry.for_path(root / "apps" / "web" / "src" / "i.ts").kind == "custom"

    def test_explicitly_empty_bin_dirs_yields_no_bin_dirs(self, tmp_path: Path) -> None:
        """Stating "this project has none" must beat the node convention."""
        root = _monorepo(tmp_path)
        registry = self._registry(root, [{"name": "web", "root": "apps/web", "bin_dirs": []}])

        assert registry.for_path(root / "apps" / "web" / "src" / "i.ts").bin_dirs == ()

    def test_a_declared_root_is_never_confused_with_a_sibling_prefix(self, tmp_path: Path) -> None:
        """`apps/web` must not capture `apps/web-admin` on a string prefix."""
        root = tmp_path
        (root / "apps" / "web").mkdir(parents=True)
        (root / "apps" / "web-admin" / "src").mkdir(parents=True)
        registry = self._registry(root, [{"name": "web", "root": "apps/web"}])

        workspace = registry.for_path(root / "apps" / "web-admin" / "src" / "i.ts")

        assert workspace.root == root, "web-admin is not inside web"


class TestFromConfig:
    def test_empty_config_yields_a_single_root_project(self, tmp_path: Path) -> None:
        registry = ProjectRegistry.from_config(Config(), tmp_path)

        assert registry.for_path(tmp_path / "apps" / "web" / "x.ts").root == tmp_path


class TestPerProjectLayout:
    """Plan 00300 owner ruling: `layout.source_dirs` is per-project config.

    A declared project without its own `layout:` block uses BUILT-IN
    defaults for ITS root -- never the top-level `layout:` block, which is
    the ROOT project's layout only, never a global fallback. Same
    declared-not-inferred philosophy as `root`/`kind`.
    """

    def test_single_project_config_with_top_level_layout_needs_zero_edits(
        self, tmp_path: Path
    ) -> None:
        """Owner acceptance check: a top-level `layout:` with no `projects:`
        parses and resolves EXACTLY as before Plan 00300 -- the dogfood
        config shape (`layout: {source_dirs: [...]}`, no `projects:` key).
        """
        config = Config.model_validate({"layout": {"source_dirs": ["src"]}})
        registry = ProjectRegistry.from_config(config, tmp_path)

        layout = registry.layout_for(tmp_path / "src" / "main.py")

        assert layout.source_dirs == ("src",)
        assert layout is registry.root_layout, "no projects: means every path is the root project"

    def test_declared_project_without_own_layout_uses_built_in_defaults(
        self, tmp_path: Path
    ) -> None:
        """No leaking: the root's declared `layout.source_dirs` must NOT
        apply inside a sub-project that declares no `layout:` of its own."""
        (tmp_path / "apps" / "web").mkdir(parents=True)
        config = Config.model_validate(
            {
                "layout": {"source_dirs": ["root-only-src"]},
                "projects": [{"name": "web", "root": "apps/web"}],
            }
        )
        registry = ProjectRegistry.from_config(config, tmp_path)

        layout = registry.layout_for(tmp_path / "apps" / "web" / "main.py")

        assert "root-only-src" not in layout.source_dirs
        # Falls back to the cross-project built-in (currently empty for
        # source_dirs — see project_layout.py's module docstring), NOT the
        # root project's own declared list.
        assert layout.source_dirs == ()

    def test_declared_project_with_own_layout_uses_it(self, tmp_path: Path) -> None:
        (tmp_path / "apps" / "web").mkdir(parents=True)
        config = Config.model_validate(
            {
                "projects": [
                    {
                        "name": "web",
                        "root": "apps/web",
                        "layout": {"source_dirs": ["web-src"]},
                    }
                ]
            }
        )
        registry = ProjectRegistry.from_config(config, tmp_path)

        layout = registry.layout_for(tmp_path / "apps" / "web" / "main.py")

        assert layout.source_dirs == ("web-src",)

    def test_a_path_outside_every_declared_project_gets_the_root_layout(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "apps" / "web").mkdir(parents=True)
        config = Config.model_validate(
            {
                "layout": {"source_dirs": ["root-src"]},
                "projects": [
                    {
                        "name": "web",
                        "root": "apps/web",
                        "layout": {"source_dirs": ["web-src"]},
                    }
                ],
            }
        )
        registry = ProjectRegistry.from_config(config, tmp_path)

        layout = registry.layout_for(tmp_path / "other" / "main.py")

        assert layout.source_dirs == ("root-src",)

    def test_iter_layouts_yields_root_then_every_declared_project(self, tmp_path: Path) -> None:
        (tmp_path / "apps" / "web").mkdir(parents=True)
        (tmp_path / "apps" / "service").mkdir(parents=True)
        config = Config.model_validate(
            {
                "layout": {"source_dirs": ["root-src"]},
                "projects": [
                    {"name": "web", "root": "apps/web", "layout": {"source_dirs": ["web-src"]}},
                    {"name": "service", "root": "apps/service"},
                ],
            }
        )
        registry = ProjectRegistry.from_config(config, tmp_path)

        labelled = dict(registry.iter_layouts())

        assert set(labelled) == {"", "web", "service"}
        assert labelled[""].source_dirs == ("root-src",)
        assert labelled["web"].source_dirs == ("web-src",)
        assert labelled["service"].source_dirs == ()

    def test_all_source_dirs_is_the_deduped_union_across_every_project(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "apps" / "web").mkdir(parents=True)
        (tmp_path / "apps" / "service").mkdir(parents=True)
        config = Config.model_validate(
            {
                "layout": {"source_dirs": ["shared-src"]},
                "projects": [
                    {
                        "name": "web",
                        "root": "apps/web",
                        "layout": {"source_dirs": ["shared-src", "web-src"]},
                    },
                    {
                        "name": "service",
                        "root": "apps/service",
                        "layout": {"source_dirs": ["service-src"]},
                    },
                ],
            }
        )
        registry = ProjectRegistry.from_config(config, tmp_path)

        assert registry.all_source_dirs() == ("shared-src", "web-src", "service-src")

    def test_single_project_registry_has_built_in_default_root_layout(self, tmp_path: Path) -> None:
        """`ProjectRegistry.single_project` (no Config at all) still works."""
        registry = ProjectRegistry.single_project(tmp_path)

        assert registry.layout_for(tmp_path / "anything.py").source_dirs == ()
        assert registry.all_source_dirs() == ()
