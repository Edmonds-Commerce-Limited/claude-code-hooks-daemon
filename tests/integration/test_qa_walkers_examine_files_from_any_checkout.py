"""Every tree-walking QA check examines files wherever the checkout lives (00466 N26).

``check_skill_references.py`` passed after scanning 0 files when run from an
agent worktree: it excluded any file whose ABSOLUTE path had a component named
``untracked`` or ``worktrees``, and every worktree lives under
``untracked/worktrees/``. Two more checks had the same shape, and a fourth
matched ``constants``, ``fixtures`` and ``test`` the same way.

This runs each walker from a copy of the tracked tree placed under a directory
path made of every name a walker is known to exclude, and requires a non-zero
examined count. ``test_every_check_is_classified`` makes a new check declare
which kind it is, so the class stays pinned.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
QA_DIR = REPO_ROOT / "scripts" / "qa"

#: A checkout location made of directory names QA walkers exclude.
HOSTILE_LOCATION = (
    "test",
    "fixtures",
    "constants",
    "build",
    "examples",
    "Completed",
    "venv",
    "ccy",
    "untracked",
    "worktrees",
    "wt",
)

#: Walkers: script -> (artefact under untracked/qa/, examined-count key).
WALKERS: dict[str, tuple[str, str]] = {
    "audit_shell.py": ("shell_audit.json", "files_scanned"),
    "check_authored_path_stat.py": ("authored_path_stat.json", "files_scanned"),
    "check_british_english.py": ("british_english.json", "files_scanned"),
    "check_doc_snippets.py": ("doc_snippets.json", "documents_scanned"),
    "check_doc_truth.py": ("doc_truth.json", "docs_scanned"),
    "check_eacces_safe_predicates.py": ("eacces_safe.json", "files_scanned"),
    "check_git_history.py": ("git_history.json", "commits_scanned"),
    "check_github_urls.py": ("github_urls.json", "files_scanned"),
    "check_magic_values.py": ("magic_values.json", "files_scanned"),
    "check_python_var_guidance.py": ("python_var_guidance.json", "files_scanned"),
    "check_repo_hygiene.py": ("repo_hygiene.json", "paths_checked"),
    "check_security_downgrade_flags.py": ("security_downgrade_flags.json", "files_checked"),
    "check_sensitive_content.py": ("sensitive_content.json", "files_scanned"),
    "check_skill_references.py": ("skill_references.json", "files_scanned"),
    "check_skip_list_substring.py": ("skip_list_substring.json", "files_scanned"),
    "check_unreachable_handle_branch.py": ("unreachable_handle_branch.json", "files_scanned"),
}

#: Checks that read a fixed input (and fail when it is missing), or report no
#: examined count, so a walker's examined-nothing failure cannot occur.
FIXED_INPUT_CHECKS: frozenset[str] = frozenset(
    {
        "check_dangerous_invocation_corpus.py",
        "check_declared_invariant_pairs.py",
        "check_fail_open_inventory.py",
        "check_generated_doc_drift.py",
        "check_handler_reference.py",
        "check_hook_contract.py",
        "check_input_contract.py",
        "check_project_handler_tests.py",
    }
)

#: Walkers that report no examined count but exit non-zero, writing no
#: artefact, when they collect no file (Plan 00364 Task 5.4).
SELF_GUARDED_WALKERS: frozenset[str] = frozenset(
    {
        "audit_capture_corruption.py",
        "audit_error_hiding.py",
    }
)

#: The QA scripts that judge the tree: every one must be classified above.
_QA_CHECK_GLOBS = ("check_*.py", "audit_*.py")

_RUN_TIMEOUT_SECONDS = 600


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture(scope="module")
def hostile_checkout(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The tracked tree, copied under a path of excluded names, as a git repo."""
    root = tmp_path_factory.mktemp("n26").joinpath(*HOSTILE_LOCATION)
    tracked = _git("ls-files", "-z", cwd=REPO_ROOT).split("\0")
    for relative in filter(None, tracked):
        source = REPO_ROOT / relative
        if not source.is_file() or source.is_symlink():
            continue
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    _git("init", "-q", cwd=root)
    _git("add", "-A", cwd=root)
    _git(
        "-c",
        "user.name=n26",
        "-c",
        "user.email=n26@example.invalid",
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "-q",
        "--no-verify",
        "-m",
        "fixture",
        cwd=root,
    )
    return root


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("script", sorted(WALKERS))
def test_a_walker_examines_files_from_a_hostile_location(
    script: str, hostile_checkout: Path, tmp_path: Path
) -> None:
    artefact, key = WALKERS[script]
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path / "claude-config")}
    subprocess.run(
        [sys.executable, str(hostile_checkout / "scripts" / "qa" / script), "--json"],
        cwd=hostile_checkout,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=_RUN_TIMEOUT_SECONDS,
    )
    summary = json.loads((hostile_checkout / "untracked" / "qa" / artefact).read_text())["summary"]
    assert summary[key] > 0, f"{script} examined nothing from {hostile_checkout}: {summary}"


_SELF_GUARDED_ARTEFACTS: dict[str, str] = {
    "audit_capture_corruption.py": "capture_corruption.json",
    "audit_error_hiding.py": "error_hiding.json",
}


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("script", sorted(SELF_GUARDED_WALKERS))
def test_a_self_guarded_walker_collects_files_from_a_hostile_location(
    script: str, hostile_checkout: Path
) -> None:
    """It writes its artefact only after collecting at least one file."""
    artefact = hostile_checkout / "untracked" / "qa" / _SELF_GUARDED_ARTEFACTS[script]
    artefact.unlink(missing_ok=True)
    result = subprocess.run(
        [sys.executable, str(hostile_checkout / "scripts" / "qa" / script), "--json"],
        cwd=hostile_checkout,
        check=False,
        capture_output=True,
        text=True,
        timeout=_RUN_TIMEOUT_SECONDS,
    )
    assert (
        artefact.is_file()
    ), f"{script} collected nothing from {hostile_checkout}: {result.stderr}"


def test_every_check_is_classified() -> None:
    """A new check must say whether it walks the tree, so the pin above covers it."""
    present = {path.name for pattern in _QA_CHECK_GLOBS for path in QA_DIR.glob(pattern)}
    classified = set(WALKERS) | FIXED_INPUT_CHECKS | SELF_GUARDED_WALKERS
    assert (
        present == classified
    ), f"unclassified: {sorted(present - classified)}; gone: {sorted(classified - present)}"
