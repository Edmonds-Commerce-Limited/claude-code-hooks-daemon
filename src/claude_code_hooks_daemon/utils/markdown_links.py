"""Markdown link-target extraction, shared by both QA subsystems.

Docs QA has always needed it (``pointer-resolves``). Plan QA needs the same
primitive now that ``plan-link-resolves`` exists, and copying the regex into a
second caller is how two answers to one question start disagreeing — the shape
this project keeps meeting (``Priority`` vs the shipped template, the
vendored-dir sets before ``constants.layout``).

It lives in ``utils`` rather than in either subsystem so the dependency runs
one way: both QA packages import it, and it imports neither of them. That
sentence was false for as long as it stood — the fence splitter it builds on
was still in ``plan_qa.model``, six lines below this paragraph — so
``tests/integration/test_qa_package_dependency_direction.py`` now checks it
instead of taking the docstring's word for it.
"""

import re
from typing import Final

from claude_code_hooks_daemon.utils.markdown_fences import lines_outside_fences

MARKDOWN_LINK_RE: Final[re.Pattern[str]] = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def extract_link_targets(text: str) -> list[str]:
    """Every plain markdown link target in ``text``, outside fenced code blocks.

    Backticked prose paths (``\\`src/foo.py\\```) are not markdown link
    syntax and are never matched — no special-casing needed.
    """
    targets: list[str] = []
    for line in lines_outside_fences(text):
        targets.extend(match.group(1) for match in MARKDOWN_LINK_RE.finditer(line))
    return targets
