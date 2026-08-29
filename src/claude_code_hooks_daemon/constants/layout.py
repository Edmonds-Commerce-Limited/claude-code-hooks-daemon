"""Canonical vendored/build directory core constant (Plan 00288 Task 3.2).

Before this module existed, four independent consumers each hardcoded their
own vendored/build-dir name set, and the sets had silently drifted apart
(``docs_qa/corpus.py``, ``strategies/lint/common.py``,
``utils/worktree_seed_suggestions.py``,
``handlers/post_tool_use/validate_eslint_on_write.py``, plus two entries in
``handlers/pre_tool_use/error_hiding_blocker.py``'s default excludes). This
module is the single reviewed core every one of those consumers now derives
from, unioned with whatever consumer-specific "domain extras" that consumer
still needs (a tool cache, a fixture dir, this daemon's own ``untracked/``
convention).

The exact 11-name membership and the per-consumer before/after diff that
justifies it are measured in
``CLAUDE/Plan/00288-project-layout-config-ssot/MEASUREMENT-vendored-dirs.md``
— do not add or remove a name here without updating that measurement.
"""

from typing import Final

# Directory names that hold ONLY third-party or generated content in ANY
# ecosystem, so no consumer that skips vendored/build content could ever be
# wrong to skip it. See MEASUREMENT-vendored-dirs.md §2 for the criterion and
# the per-name justification table.
CORE_VENDORED_BUILD_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        "node_modules",  # JS dependency tree
        "vendor",  # Go/PHP/Ruby vendoring convention
        "third_party",  # Vendored code by definition (Chromium/Bazel)
        "dist",  # JS/Python distribution output
        "build",  # Generic build output
        ".build",  # SwiftPM build output
        "target",  # Cargo/Maven build output
        ".next",  # Next.js build output
        ".venv",  # Python virtualenv
        "venv",  # Python virtualenv, unhidden spelling
        "coverage",  # Coverage-report output
    }
)
