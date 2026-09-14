"""The package's public surface (Plan 00401 Task 1.1).

Three separate consumers import this package — a SessionStart sweep, a
PreToolUse handler and a CLI command — and the whole point of the package is
that they cannot drift in what they consider stale. That only holds if they
import the SAME entry points, so the re-export is a contract rather than a
convenience, and it is worth a test that fails when someone quietly moves one.
"""

from __future__ import annotations

import claude_code_hooks_daemon.reference_repos as reference_repos
from claude_code_hooks_daemon.reference_repos.discovery import discover_reference_repos


class TestPublicSurface:
    def test_discovery_is_re_exported_from_the_package(self) -> None:
        assert reference_repos.discover_reference_repos is discover_reference_repos

    def test_dunder_all_matches_what_is_actually_exported(self) -> None:
        """``__all__`` that names something absent breaks ``from ... import *``."""
        for name in reference_repos.__all__:
            assert hasattr(reference_repos, name), f"__all__ names missing {name!r}"

    def test_the_package_documents_itself(self) -> None:
        """A package whose purpose is a shared convention must say what it is."""
        assert reference_repos.__doc__
        assert reference_repos.__doc__.strip()
