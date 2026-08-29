"""Tests for the canonical vendored/build directory core constant.

Plan 00288 Task 3.2 — see
``CLAUDE/Plan/00288-project-layout-config-ssot/MEASUREMENT-vendored-dirs.md``
for the reviewed 11-name membership this constant pins.
"""

from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES


class TestCoreVendoredBuildDirNames:
    def test_is_frozenset(self) -> None:
        assert isinstance(CORE_VENDORED_BUILD_DIR_NAMES, frozenset)

    def test_exact_membership(self) -> None:
        # Pinned to the MEASUREMENT doc's reviewed 11-name core set.
        assert CORE_VENDORED_BUILD_DIR_NAMES == frozenset(
            {
                "node_modules",
                "vendor",
                "third_party",
                "dist",
                "build",
                ".build",
                "target",
                ".next",
                ".venv",
                "venv",
                "coverage",
            }
        )

    def test_no_domain_extras_present(self) -> None:
        # Names argued OUT of the core as domain extras (measurement §2) must
        # never leak into the shared constant.
        domain_extras = {
            "__pycache__",
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".tox",
            "untracked",
            "test-results",
        }
        assert CORE_VENDORED_BUILD_DIR_NAMES.isdisjoint(domain_extras)
