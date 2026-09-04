"""End-to-end: a monorepo sub-project's vendor declaration reaches docs QA.

Plan 00332. Drives the PRODUCTION chain from a real on-disk YAML --
``Config.load_or_default`` -> ``ProjectRegistry.from_config`` ->
``vendor_scopes`` -> ``policy_from_config`` -> the consumers -- rather than
constructing a ``DocumentationPolicy`` by hand.

That matters here specifically. Plan 00331 shipped a ``layout.vendor_dirs``
that parsed correctly, merged correctly and answered correctly, and still
changed nothing, because no consumer sat on the path between the config and
the check. Only a test that starts at the YAML catches that class of defect;
one that builds a policy directly asserts the second half of the chain and
assumes the first.

SCOPE, stated plainly: these assert the two places a vendored path is
actually decided -- the corpus index and the module-doc walker's prune. They
do NOT assert that a specific check then emits a specific finding, which is
generic behaviour covered by each check's own unit tests. The vendor axis is
what this plan changed.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core.workspace import ProjectRegistry
from claude_code_hooks_daemon.docs_qa.checks.module_doc_budget import _iter_module_doc_paths
from claude_code_hooks_daemon.docs_qa.corpus import build_and_save_corpus
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy, policy_from_config

_YAML = """
projects:
  - name: api
    root: apps/api
    layout:
      vendor_dirs: [roles]
documentation:
  enabled: true
  trees:
    agent: CLAUDE
    human: docs
"""

_DOC = "# Third-party role\n\nSomething a dependency shipped.\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _policy_from_yaml(project_root: Path) -> DocumentationPolicy:
    """The policy the daemon itself would build for this tree."""
    config = Config.load_or_default(project_root / ".claude" / "hooks-daemon.yaml")
    registry = ProjectRegistry.from_config(config, project_root)
    return policy_from_config(config.documentation, vendor_scopes=registry.vendor_scopes())


def _monorepo(tmp_path: Path) -> Path:
    """Two identically-shaped vendored roles, one per sub-project.

    Only ``apps/api`` declares ``roles`` vendored. ``apps/web`` is the
    control: same directory name, no declaration.
    """
    _write(tmp_path / ".claude" / "hooks-daemon.yaml", _YAML)
    _write(tmp_path / "apps" / "api" / "roles" / "dep" / "CLAUDE.md", _DOC)
    _write(tmp_path / "apps" / "web" / "roles" / "dep" / "CLAUDE.md", _DOC)
    return tmp_path


class TestTheDeclarationReachesTheModuleDocWalker:
    """``module_doc_budget`` runs its OWN pruned walk rather than reading the
    corpus, so it is a separate consumer that has to be reached separately --
    the exact split that let Plan 00331's original defect hide in two places.
    """

    def test_the_declaring_sub_projects_role_is_pruned(self, tmp_path: Path) -> None:
        policy = _policy_from_yaml(_monorepo(tmp_path))

        found = _iter_module_doc_paths(tmp_path, "CLAUDE", vendor_scopes=policy.vendor_scopes)

        assert "apps/api/roles/dep/CLAUDE.md" not in found

    def test_a_sibling_that_declared_nothing_is_still_walked(self, tmp_path: Path) -> None:
        """The discriminating half.

        A repo-wide union of every project's ``vendor_dirs`` -- the design
        this plan rejects -- also passes the test above while silently
        hiding this file. Without this assertion the pair cannot tell the two
        implementations apart, and the union is the cheaper thing to build.
        """
        policy = _policy_from_yaml(_monorepo(tmp_path))

        found = _iter_module_doc_paths(tmp_path, "CLAUDE", vendor_scopes=policy.vendor_scopes)

        assert "apps/web/roles/dep/CLAUDE.md" in found


class TestTheDeclarationReachesTheCorpus:
    """The corpus is the other consumer: a path it excludes cannot be
    reported by any corpus-reading sweep check."""

    def test_a_declared_vendored_doc_tree_is_excluded(self, tmp_path: Path) -> None:
        _write(tmp_path / ".claude" / "hooks-daemon.yaml", _YAML)
        _write(tmp_path / "docs" / "roles" / "dep" / "guide.md", _DOC)
        _write(tmp_path / "docs" / "real" / "guide.md", _DOC)
        policy = _policy_from_yaml(tmp_path)

        corpus = build_and_save_corpus(tmp_path, policy, tmp_path / "untracked" / "index.json")
        indexed = set(corpus.document_paths())

        # `roles` is declared by apps/api ONLY, so a `roles` directory at the
        # repository root is NOT vendored -- the same discrimination as
        # above, from the corpus side.
        assert "docs/roles/dep/guide.md" in indexed
        assert "docs/real/guide.md" in indexed

    def test_a_root_declared_vendor_dir_is_excluded_from_the_corpus(self, tmp_path: Path) -> None:
        """The root scope still governs everything outside a declared
        project, so the Plan 00331 behaviour is intact."""
        _write(
            tmp_path / ".claude" / "hooks-daemon.yaml",
            "layout:\n  vendor_dirs: [roles]\ndocumentation:\n"
            "  enabled: true\n  trees:\n    agent: CLAUDE\n    human: docs\n",
        )
        _write(tmp_path / "docs" / "roles" / "dep" / "guide.md", _DOC)
        _write(tmp_path / "docs" / "real" / "guide.md", _DOC)
        policy = _policy_from_yaml(tmp_path)

        corpus = build_and_save_corpus(tmp_path, policy, tmp_path / "untracked" / "index.json")
        indexed = set(corpus.document_paths())

        assert "docs/roles/dep/guide.md" not in indexed
        assert "docs/real/guide.md" in indexed
