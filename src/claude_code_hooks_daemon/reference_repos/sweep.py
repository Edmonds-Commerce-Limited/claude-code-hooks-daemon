"""The one pipeline that turns a project's config into recorded readings.

Discover the governed checkouts, refresh each, record the result. Three steps,
and two surfaces need all three: the SessionStart sweep handler and the
``reference-repos`` CLI command the other surfaces tell readers to run.

They each had their own copy, and the copies had already drifted. The CLI's JSON
payload learned about ``fetch_failed`` and ``verified`` while the handler's walk
did not, so the same repository — one whose fetch had failed outright — read as
a confident all-clear on one surface and an unverifiable one on the other. That
is the specific failure this package exists to prevent, reintroduced by
duplication rather than by any wrong idea about freshness.

Two details here are load-bearing rather than incidental:

``the cache is written on EVERY run, including a completely clean one``
    The cache is what records that a check HAPPENED. A clean sweep that wrote
    nothing would leave every later read as NOT VERIFIED, so the backstop would
    enforce hardest precisely when the repositories were perfect.

``the refresher is resolved at CALL time``
    :func:`~claude_code_hooks_daemon.reference_repos.refresh.refresh_repo` is
    the only function in this package that touches the network. Bound as a
    default argument it would be captured at import, and a test that replaced it
    would be silently bypassed — spending real fetches while reporting that it
    had not.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from claude_code_hooks_daemon.config.models import ReferenceReposConfig
from claude_code_hooks_daemon.reference_repos import refresh as refresh_module
from claude_code_hooks_daemon.reference_repos.cache import write_cache
from claude_code_hooks_daemon.reference_repos.discovery import discover_reference_repos
from claude_code_hooks_daemon.reference_repos.refresh import RefreshOutcome


def governed_roots(project_root: Path, roots: Sequence[str]) -> list[Path]:
    """Resolve the configured roots against a project.

    Trivial, and shared anyway: the expression had three copies, and a root
    resolved against the wrong base governs nothing, silently.

    Args:
        project_root: The project the roots are relative to.
        roots: Configured root paths, as written in ``reference_repos.roots``.

    Returns:
        One absolute path per configured root, in configured order.
    """
    return [project_root / relative for relative in roots]


def sweep_reference_repos(
    project_root: Path,
    settings: ReferenceReposConfig,
    *,
    refresher: Callable[..., RefreshOutcome] | None = None,
) -> list[RefreshOutcome]:
    """Refresh every governed checkout under ``project_root`` and record it.

    Args:
        project_root: The project whose reference repos to sweep.
        settings: The resolved ``reference_repos`` block — ``roots``, ``exclude``
            and ``auto_pull`` are read from it.
        refresher: Injected refresh function, for tests and for the SessionStart
            handler's own seam. ``None`` means the real one, looked up on the
            module at call time (see the module docstring).

    Returns:
        One outcome per governed checkout, in path order. Outcomes rather than
        bare states because ``detail`` carries the actionable half of a refusal:
        "dirty", "ahead" and "diverged" are one boolean to
        :attr:`RepoState.safe_to_pull` but three different remedies to a reader.
    """
    repos = discover_reference_repos(
        governed_roots(project_root, settings.roots),
        exclude_globs=settings.exclude,
        project_root=project_root,
    )

    refresh = refresh_module.refresh_repo if refresher is None else refresher
    outcomes = [refresh(repo, allow_pull=settings.auto_pull) for repo in sorted(repos)]

    write_cache(project_root, [outcome.state for outcome in outcomes])
    return outcomes
