"""Handler relevance: when a handler is a fit for a project (Plan 00330).

The config-optimisation review scores EVERY registered handler. There is no
exemption list — "default off" and "not worth enabling" are different
things, and a subtraction list in the skill would rot exactly like the
hardcoded checklist it replaced. What a handler declares instead is when it
is RELEVANT: most are always relevant; ``lsp_enforcement`` needs an LSP, the
npm handlers a ``package.json``, the ccy handlers an armed supervisor. The
optimal state of a relevant handler is enabled; an irrelevant one is
reported as "not applicable here", never as a shortfall.

This module is pure stdlib so the base ``Handler`` can import it without
pulling in config or registry code.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: Root-level marker files that identify a language toolchain. A cheap,
#: deterministic probe — no directory walk — so relevance can be decided by
#: a CLI verb in milliseconds. The keys are the ``HandlerTag`` language
#: spellings.
_LANGUAGE_MARKERS: Final[dict[str, tuple[str, ...]]] = {
    "python": ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"),
    "javascript": ("package.json",),
    "typescript": ("tsconfig.json",),
    "php": ("composer.json",),
    "go": ("go.mod",),
    "rust": ("Cargo.toml",),
    "java": ("pom.xml", "build.gradle", "build.gradle.kts"),
}


def detect_languages(project_root: Path) -> frozenset[str]:
    """Languages a project uses, from its root-level toolchain markers.

    A project with ``package.json`` and ``tsconfig.json`` reports both
    ``javascript`` and ``typescript``. A missing or unreadable root reports
    nothing rather than raising: relevance is advisory input to a report,
    and a probe failure must degrade to "unknown", not abort the review.
    """
    if not project_root.is_dir():
        return frozenset()
    found = {
        language
        for language, markers in _LANGUAGE_MARKERS.items()
        if any((project_root / marker).is_file() for marker in markers)
    }
    return frozenset(found)


@dataclass(frozen=True, slots=True)
class RelevanceContext:
    """The view of a project a relevance verdict is decided against.

    Built once per review and handed to every handler, so a hundred
    predicates share one filesystem probe. Handlers needing something not
    carried here read it through :meth:`has_file` (cheap existence checks)
    rather than growing this class per handler.
    """

    project_root: Path
    languages: frozenset[str]

    @classmethod
    def probe(
        cls,
        project_root: Path,
        *,
        declared_languages: Iterable[str] | None = None,
    ) -> RelevanceContext:
        """Build a context for ``project_root``.

        Args:
            project_root: The repository root the review runs against.
            declared_languages: The project's ``daemon.languages`` config,
                when set. A declaration is authoritative over detection —
                that is what the setting exists for.
        """
        if declared_languages is not None:
            languages = frozenset(language.lower() for language in declared_languages)
        else:
            languages = detect_languages(project_root)
        return cls(project_root=project_root, languages=languages)

    def has_file(self, *parts: str) -> bool:
        """Whether ``project_root / parts...`` exists as a regular file."""
        return self.project_root.joinpath(*parts).is_file()

    def uses_any_language(self, *languages: str) -> bool:
        """Whether the project uses at least one of ``languages``."""
        return any(language.lower() in self.languages for language in languages)


@dataclass(frozen=True, slots=True)
class Relevance:
    """A handler's verdict on whether it applies to a project.

    ``reason`` is shown to the human in the optimise report: for an
    applicable handler it explains why enabling it is recommended, for an
    inapplicable one it explains why the handler is "not applicable here"
    rather than a shortfall.
    """

    applicable: bool
    reason: str

    @classmethod
    def always(cls) -> Relevance:
        """The default: the handler applies to every project."""
        return cls(applicable=True, reason="applies to every project")

    @classmethod
    def when(cls, condition: bool, *, present: str, absent: str) -> Relevance:
        """Applicable iff ``condition``; the reason names what was (not) found."""
        return cls(applicable=condition, reason=present if condition else absent)
