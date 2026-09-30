"""The targeted test runner behind ``llm_qa.py changed`` (Plan 00463).

Sub-agents run targeted QA; the coordinator runs the full suite, once per
batch of ready branches. The allowed path has to be ONE command rather than a judgement call,
or each agent reinvents its own subset and some reinvent nothing. This runner
is that command's test half: pytest on the tests mapped from what changed
since the merge base.

The mapping is a heuristic, and the coordinator's full gate is the backstop
for what it cannot see. What the runner must never do is PASS having verified
nothing (review finding 1): every changed file maps to tests, to a declared
fallback, or is listed as unmapped and fails the run.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load(script: str, name: str) -> Any:
    """Import a file under ``scripts/qa/``, which is a script rather than a module."""
    module_path = PROJECT_ROOT / "scripts" / "qa" / script
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


changed_tests = _load("run_changed_tests.py", "run_changed_tests_under_test")
llm_qa = _load("llm_qa.py", "llm_qa_for_changed_tests_map")

_MERGE_BASE = "0" * 40


def _touch(root: Path, *relative: str, text: str = "") -> None:
    for path in relative:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def _git_answering(
    diff: str = "",
    untracked: str = "",
    merge_base_code: int = 0,
    branch: str = "worktree-x",
    origin_head: str | None = "origin/main",
    local_branches: tuple[str, ...] = ("main",),
) -> Any:
    """A ``run_git`` stand-in answering every call the runner makes."""

    def run(args: list[str], root: Path) -> tuple[int, str, str]:
        assert root.is_absolute()
        if args[0] == "merge-base":
            if merge_base_code:
                return merge_base_code, "", "fatal: Not a valid object name main"
            return 0, f"{_MERGE_BASE}\n", ""
        if args[0] == "diff":
            assert "--no-renames" in args, "a rename must list the old path too"
            assert args[-1] == _MERGE_BASE, "the diff must be taken against the merge base"
            return 0, diff, ""
        if args[0] == "ls-files" and "--cached" in args:
            return 0, "".join(f"{relative}\n" for relative in _tree(root)), ""
        if args[0] == "ls-files":
            return 0, untracked, ""
        if args[:2] == ["symbolic-ref", "--quiet"] and args[-1] == "HEAD":
            return (0, f"{branch}\n", "") if branch else (1, "", "")
        if args[:2] == ["symbolic-ref", "--quiet"]:
            return (0, f"{origin_head}\n", "") if origin_head else (1, "", "")
        if args[:3] == ["rev-parse", "--verify", "--quiet"]:
            name = args[3].removeprefix("refs/heads/")
            return (0, "abc\n", "") if name in local_branches else (1, "", "")
        raise AssertionError(f"unexpected git call: {args}")

    return run


def _rules(*entries: dict[str, Any]) -> list[Any]:
    rules, problems = changed_tests.parse_declared_rules({"rules": list(entries)})
    assert problems == [], problems
    return rules


def _tree(root: Path) -> list[str]:
    """Every file under ``root``, as ``git ls-files --cached --others`` would list it."""
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and "untracked" not in path.relative_to(root).parts
    )


def _select(root: Path, changed: list[str], rules: list[Any] | None = None) -> Any:
    return changed_tests.select_tests(
        changed, changed_tests.build_corpus(root, _tree(root)), root, rules or []
    )


class TestChangedFiles:
    def test_committed_working_tree_and_untracked_changes_are_all_seen(
        self, tmp_path: Path
    ) -> None:
        git = _git_answering(diff="src/pkg/a.py\nREADME.md\n", untracked="tests/unit/test_b.py\n")
        files, error = changed_tests.changed_files(tmp_path, "main", git=git)
        assert error is None
        assert files == ["README.md", "src/pkg/a.py", "tests/unit/test_b.py"]

    def test_no_merge_base_is_an_error_not_an_empty_change_set(self, tmp_path: Path) -> None:
        """An empty list would read as 'nothing changed' and select nothing."""
        files, error = changed_tests.changed_files(
            tmp_path, "main", git=_git_answering(merge_base_code=128)
        )
        assert files is None
        assert error is not None
        assert "main" in error


class TestTheBase:
    """Review finding 11: a clone with no local `main` must still work."""

    def test_origin_head_names_the_local_default_branch(self, tmp_path: Path) -> None:
        base, error = changed_tests.resolve_base(
            tmp_path,
            None,
            git=_git_answering(origin_head="origin/trunk", local_branches=("trunk",)),
        )
        assert (base, error) == ("trunk", None)

    def test_without_the_local_branch_the_remote_one_is_used(self, tmp_path: Path) -> None:
        base, _ = changed_tests.resolve_base(
            tmp_path, None, git=_git_answering(origin_head="origin/trunk", local_branches=())
        )
        assert base == "origin/trunk"

    def test_without_origin_head_a_local_main_is_used(self, tmp_path: Path) -> None:
        base, _ = changed_tests.resolve_base(tmp_path, None, git=_git_answering(origin_head=None))
        assert base == "main"

    def test_nothing_to_diff_against_is_an_error(self, tmp_path: Path) -> None:
        base, error = changed_tests.resolve_base(
            tmp_path, None, git=_git_answering(origin_head=None, local_branches=())
        )
        assert base is None
        assert error is not None
        assert "--base" in error

    def test_an_explicit_base_wins(self, tmp_path: Path) -> None:
        assert changed_tests.resolve_base(tmp_path, "release", git=_git_answering()) == (
            "release",
            None,
        )


class TestMirroredSelection:
    """Review finding 10: the mirrored location first, a global name search second."""

    def test_the_mirror_wins_over_same_named_tests_elsewhere(self, tmp_path: Path) -> None:
        _touch(
            tmp_path,
            "src/pkg/strategies/pipe_blocker/common.py",
            "tests/unit/strategies/pipe_blocker/test_common.py",
            "tests/unit/plan_qa/test_common.py",
            "tests/unit/lint/test_common.py",
        )
        selection = _select(tmp_path, ["src/pkg/strategies/pipe_blocker/common.py"])
        assert selection.selected == ["tests/unit/strategies/pipe_blocker/test_common.py"]
        assert selection.mapping[0]["rules"] == ["reference"]

    def test_variants_in_the_mirror_are_selected(self, tmp_path: Path) -> None:
        _touch(
            tmp_path,
            "src/pkg/utils/shell_segmentation.py",
            "tests/unit/utils/test_shell_segmentation.py",
            "tests/unit/utils/test_shell_segmentation_heredocs.py",
            "tests/unit/utils/test_shell.py",
        )
        selection = _select(tmp_path, ["src/pkg/utils/shell_segmentation.py"])
        assert selection.selected == [
            "tests/unit/utils/test_shell_segmentation.py",
            "tests/unit/utils/test_shell_segmentation_heredocs.py",
        ]

    def test_a_script_mirrors_under_tests_unit(self, tmp_path: Path) -> None:
        _touch(tmp_path, "scripts/qa/llm_qa.py", "tests/unit/qa/test_llm_qa_run_lock.py")
        selection = _select(tmp_path, ["scripts/qa/llm_qa.py"])
        assert selection.selected == ["tests/unit/qa/test_llm_qa_run_lock.py"]

    def test_a_test_elsewhere_is_selected_by_what_it_imports_not_its_name(
        self, tmp_path: Path
    ) -> None:
        """Delta review N3e: `test_<stem>_*` anywhere picked unrelated tests for short stems."""
        _touch(tmp_path, "src/claude_code_hooks_daemon/constants/handlers.py")
        _touch(tmp_path, "tests/integration/test_handlers_do_not_match_prose.py", text="x = 1\n")
        _touch(tmp_path, "tests/unit/skill_scan/test_handlers.py", text="x = 1\n")
        _touch(
            tmp_path,
            "tests/integration/test_ids.py",
            text="from claude_code_hooks_daemon.constants.handlers import HandlerID\n",
        )
        selection = _select(tmp_path, ["src/claude_code_hooks_daemon/constants/handlers.py"])
        assert selection.selected == ["tests/integration/test_ids.py"]

    def test_a_changed_test_file_selects_itself(self, tmp_path: Path) -> None:
        _touch(tmp_path, "tests/unit/test_thing.py")
        selection = _select(tmp_path, ["tests/unit/test_thing.py"])
        assert selection.selected == ["tests/unit/test_thing.py"]
        assert selection.unmapped == []


class TestImportReferences:
    def test_a_module_with_no_named_test_maps_to_the_tests_that_import_it(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path, "src/claude_code_hooks_daemon/core/orphan.py")
        _touch(
            tmp_path,
            "tests/unit/test_user.py",
            text="from claude_code_hooks_daemon.core.orphan import thing\n",
        )
        _touch(
            tmp_path,
            "tests/unit/test_other.py",
            text="from claude_code_hooks_daemon.core import (\n    orphan,\n)\n",
        )
        _touch(tmp_path, "tests/unit/test_unrelated.py", text="import os\n")
        selection = _select(tmp_path, ["src/claude_code_hooks_daemon/core/orphan.py"])
        assert selection.selected == ["tests/unit/test_other.py", "tests/unit/test_user.py"]
        assert selection.mapping[0]["rules"] == ["reference"]

    def test_a_reach_too_broad_to_target_is_unmapped_and_says_why(self, tmp_path: Path) -> None:
        """Every test importing a package is the full suite by another name (N3f)."""
        _touch(tmp_path, "src/claude_code_hooks_daemon/__init__.py")
        for number in range(changed_tests.MAX_IMPORT_SELECTION + 1):
            _touch(
                tmp_path,
                f"tests/unit/test_n{number}.py",
                text="from claude_code_hooks_daemon.core import x\n",
            )
        selection = _select(tmp_path, ["src/claude_code_hooks_daemon/__init__.py"])
        assert selection.selected == []
        assert selection.unmapped == ["src/claude_code_hooks_daemon/__init__.py"]
        reason = selection.reasons["src/claude_code_hooks_daemon/__init__.py"]
        assert reason["reason"] == "too-broad"

    def test_a_mention_in_a_comment_or_docstring_is_not_a_reference(self, tmp_path: Path) -> None:
        _touch(tmp_path, "src/claude_code_hooks_daemon/core/orphan.py")
        _touch(
            tmp_path,
            "tests/unit/test_prose.py",
            text=(
                '"""Unlike claude_code_hooks_daemon.core.orphan, this is prose."""\n'
                "# see src/claude_code_hooks_daemon/core/orphan.py\n"
            ),
        )
        selection = _select(tmp_path, ["src/claude_code_hooks_daemon/core/orphan.py"])
        assert selection.unmapped == ["src/claude_code_hooks_daemon/core/orphan.py"]


class TestTheUnionOfEveryRule:
    """Delta review N3: the first hit used to end the search, so "0 unmapped" overstated."""

    def test_a_declared_tools_rule_does_not_hide_a_test_that_reads_the_file(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path, "scripts/qa/run_tests.sh")
        _touch(
            tmp_path,
            "tests/unit/qa/test_runner_script.py",
            text='SCRIPT = ROOT / "scripts" / "qa" / "run_tests.sh"\n',
        )
        rules = _rules({"glob": "*.sh", "tools": ["shell_check"], "why": "shellcheck"})
        selection = _select(tmp_path, ["scripts/qa/run_tests.sh"], rules)
        assert selection.selected == ["tests/unit/qa/test_runner_script.py"]
        assert selection.mapping[0]["rules"] == ["declared", "reference"]

    def test_a_path_built_from_parts_is_a_reference(self, tmp_path: Path) -> None:
        """`CLAUDE/Plan/README.md` shares its basename, so the parts must both appear."""
        _touch(tmp_path, "CLAUDE/Plan/README.md", "docs/README.md")
        _touch(
            tmp_path,
            "tests/integration/test_plan_index.py",
            text='INDEX = ROOT / "CLAUDE" / "Plan" / "README.md"\n',
        )
        _touch(tmp_path, "tests/unit/test_docs.py", text='README = ROOT / "docs" / "README.md"\n')
        selection = _select(tmp_path, ["CLAUDE/Plan/README.md"])
        assert selection.selected == ["tests/integration/test_plan_index.py"]

    def test_a_mirror_hit_does_not_hide_a_dependents_tests(self, tmp_path: Path) -> None:
        """N3b: shell_segmentation's consumers' tests ran only when named after it."""
        _touch(
            tmp_path,
            "src/claude_code_hooks_daemon/utils/shell_segmentation.py",
            "tests/unit/utils/test_shell_segmentation.py",
        )
        _touch(
            tmp_path,
            "src/claude_code_hooks_daemon/utils/process_probe.py",
            text="from claude_code_hooks_daemon.utils.shell_segmentation import COMMAND_WRAPPERS\n",
        )
        _touch(tmp_path, "tests/unit/utils/test_process_probe.py")
        selection = _select(tmp_path, ["src/claude_code_hooks_daemon/utils/shell_segmentation.py"])
        assert selection.selected == [
            "tests/unit/utils/test_process_probe.py",
            "tests/unit/utils/test_shell_segmentation.py",
        ]
        assert selection.mapping[0]["rules"] == ["reference", "dependent"]

    def test_a_package_init_reaches_only_what_imports_the_package_itself(
        self, tmp_path: Path
    ) -> None:
        """Importing a submodule does not use what the `__init__` re-exports."""
        _touch(
            tmp_path,
            "src/claude_code_hooks_daemon/constants/__init__.py",
            text="from claude_code_hooks_daemon.constants.ids import HandlerID\n",
        )
        _touch(tmp_path, "src/claude_code_hooks_daemon/constants/ids.py")
        _touch(tmp_path, "src/claude_code_hooks_daemon/constants/paths.py")
        _touch(
            tmp_path,
            "tests/unit/test_reexport.py",
            text="from claude_code_hooks_daemon.constants import HandlerID\n",
        )
        _touch(
            tmp_path,
            "tests/unit/test_paths_only.py",
            text="from claude_code_hooks_daemon.constants import paths\n",
        )
        selection = _select(tmp_path, ["src/claude_code_hooks_daemon/constants/ids.py"])
        assert selection.selected == ["tests/unit/test_reexport.py"]

    def test_a_too_broad_reach_still_runs_the_files_own_tests(self, tmp_path: Path) -> None:
        _touch(
            tmp_path,
            "src/claude_code_hooks_daemon/core/scope.py",
            "tests/unit/core/test_scope.py",
        )
        _touch(
            tmp_path,
            "src/claude_code_hooks_daemon/core/hub.py",
            text="from claude_code_hooks_daemon.core.scope import SUB\n",
        )
        for number in range(changed_tests.MAX_IMPORT_SELECTION + 1):
            _touch(
                tmp_path,
                f"tests/unit/core/test_hub_{number}.py",
                text="from claude_code_hooks_daemon.core.hub import run\n",
            )
        selection = _select(tmp_path, ["src/claude_code_hooks_daemon/core/scope.py"])
        assert selection.unmapped == ["src/claude_code_hooks_daemon/core/scope.py"]
        reason = selection.reasons["src/claude_code_hooks_daemon/core/scope.py"]
        assert reason["reason"] == "too-broad"
        assert "core/hub.py" in reason["detail"]
        assert reason["tests_run"] == ["tests/unit/core/test_scope.py"]
        assert selection.selected == ["tests/unit/core/test_scope.py"]


class TestNothingPassesSilently:
    """Review finding 1: each case that used to pass having run nothing."""

    def test_a_source_module_with_no_test_is_unmapped(self, tmp_path: Path) -> None:
        _touch(tmp_path, "src/claude_code_hooks_daemon/orphan.py")
        selection = _select(tmp_path, ["src/claude_code_hooks_daemon/orphan.py"])
        assert selection.unmapped == ["src/claude_code_hooks_daemon/orphan.py"]

    def test_a_deleted_module_selects_the_tests_that_will_now_break(self, tmp_path: Path) -> None:
        _touch(
            tmp_path,
            "tests/unit/core/test_gone.py",
            text="from claude_code_hooks_daemon.core.gone import x\n",
        )
        selection = _select(tmp_path, ["src/claude_code_hooks_daemon/core/gone.py"])
        assert selection.selected == ["tests/unit/core/test_gone.py"]
        assert selection.deleted == ["src/claude_code_hooks_daemon/core/gone.py"]

    def test_a_deleted_module_nothing_references_is_verified_not_skipped(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path, "tests/unit/test_x.py", text="import os\n")
        selection = _select(tmp_path, ["src/claude_code_hooks_daemon/core/gone.py"])
        assert selection.unmapped == []
        assert selection.deleted == ["src/claude_code_hooks_daemon/core/gone.py"]
        assert selection.mapping[0]["rules"] == ["deleted-unreferenced"]

    def test_a_deleted_module_a_source_still_imports_is_unmapped(self, tmp_path: Path) -> None:
        """N3d: it was checked against tests only, so a dangling import passed."""
        _touch(
            tmp_path,
            "src/claude_code_hooks_daemon/core/user.py",
            text="from claude_code_hooks_daemon.core.gone import x\n",
        )
        selection = _select(tmp_path, ["src/claude_code_hooks_daemon/core/gone.py"])
        assert selection.unmapped == ["src/claude_code_hooks_daemon/core/gone.py"]
        reason = selection.reasons["src/claude_code_hooks_daemon/core/gone.py"]
        assert reason["reason"] == "deleted-but-referenced"
        assert "core/user.py" in reason["detail"]

    def test_a_non_python_file_with_no_declared_rule_is_unmapped_and_listed(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path, ".claude/hooks-daemon.yaml", "scripts/qa/run_x.sh")
        selection = _select(tmp_path, [".claude/hooks-daemon.yaml", "scripts/qa/run_x.sh"])
        assert selection.unmapped == [".claude/hooks-daemon.yaml", "scripts/qa/run_x.sh"]
        assert selection.non_python == [".claude/hooks-daemon.yaml", "scripts/qa/run_x.sh"]

    def test_a_declared_rule_maps_a_non_python_file_to_tests(self, tmp_path: Path) -> None:
        _touch(tmp_path, ".claude/hooks-daemon.yaml", "tests/integration/test_dogfood.py")
        rules = _rules(
            {
                "glob": ".claude/hooks-daemon.yaml",
                "tests": ["tests/integration/test_dogfood.py"],
                "why": "the dogfood config",
            }
        )
        selection = _select(tmp_path, [".claude/hooks-daemon.yaml"], rules)
        assert selection.selected == ["tests/integration/test_dogfood.py"]
        assert selection.unmapped == []
        assert selection.mapping[0]["rules"] == ["declared"]

    def test_a_declared_rule_can_name_the_tools_that_cover_a_file(self, tmp_path: Path) -> None:
        _touch(tmp_path, "CLAUDE/QA.md")
        rules = _rules({"glob": "*.md", "tools": ["docs_qa"], "why": "docs QA checks markdown"})
        selection = _select(tmp_path, ["CLAUDE/QA.md"], rules)
        assert selection.unmapped == []
        assert selection.mapping[0]["tools"] == ["docs_qa"]

    def test_the_root_conftest_is_too_broad(self, tmp_path: Path) -> None:
        """N3c: every test loads it, so its subtree is the suite."""
        _touch(tmp_path, "tests/conftest.py", "tests/unit/test_a.py")
        _touch(tmp_path, "tests/unit/test_b.py", text="from tests.conftest import fixture\n")
        selection = _select(tmp_path, ["tests/conftest.py"])
        assert selection.unmapped == ["tests/conftest.py"]
        assert selection.reasons["tests/conftest.py"]["reason"] == "too-broad"

    def test_a_nested_conftest_runs_its_whole_subtree(self, tmp_path: Path) -> None:
        """N3c: it was mapped to the few tests that import it by name."""
        _touch(
            tmp_path,
            "tests/unit/qa/conftest.py",
            "tests/unit/qa/test_a.py",
            "tests/unit/qa/deep/test_b.py",
            "tests/unit/other/test_c.py",
        )
        selection = _select(tmp_path, ["tests/unit/qa/conftest.py", "tests/unit/qa/test_a.py"])
        assert selection.selected == ["tests/unit/qa"]
        assert selection.mapping[0]["rules"] == ["conftest-subtree"]

    def test_a_nested_conftest_over_the_cap_is_too_broad(self, tmp_path: Path) -> None:
        """Review 3 R6: a subtree was ONE entry, so 180 test files passed the cap of 40."""
        tests = [
            f"tests/unit/big/test_{index}.py"
            for index in range(changed_tests.MAX_IMPORT_SELECTION + 1)
        ]
        _touch(tmp_path, "tests/unit/big/conftest.py", *tests)
        selection = _select(tmp_path, ["tests/unit/big/conftest.py"])
        assert selection.unmapped == ["tests/unit/big/conftest.py"]
        assert selection.reasons["tests/unit/big/conftest.py"]["reason"] == "too-broad"
        assert selection.selected == []

    def test_a_nested_conftest_at_the_cap_still_runs_its_subtree(self, tmp_path: Path) -> None:
        tests = [
            f"tests/unit/big/test_{index}.py" for index in range(changed_tests.MAX_IMPORT_SELECTION)
        ]
        _touch(tmp_path, "tests/unit/big/conftest.py", *tests)
        selection = _select(tmp_path, ["tests/unit/big/conftest.py"])
        assert selection.unmapped == []
        assert selection.selected == ["tests/unit/big"]

    def test_a_module_a_big_conftest_imports_is_too_broad_through_it(self, tmp_path: Path) -> None:
        """The dependent route reached the same subtree as one entry."""
        tests = [
            f"tests/integration/test_{index}.py"
            for index in range(changed_tests.MAX_IMPORT_SELECTION + 1)
        ]
        _touch(tmp_path, *tests)
        _touch(tmp_path, "src/claude_code_hooks_daemon/helper.py")
        _touch(
            tmp_path,
            "tests/integration/conftest.py",
            text="from claude_code_hooks_daemon.helper import thing\n",
        )
        selection = _select(tmp_path, ["src/claude_code_hooks_daemon/helper.py"])
        assert selection.unmapped == ["src/claude_code_hooks_daemon/helper.py"]
        assert selection.reasons["src/claude_code_hooks_daemon/helper.py"]["reason"] == "too-broad"

    def test_a_helper_modules_tests_are_its_importers(self, tmp_path: Path) -> None:
        _touch(tmp_path, "tests/unit/qa/helpers.py")
        _touch(
            tmp_path,
            "tests/unit/qa/test_user.py",
            text="from tests.unit.qa.helpers import build\n",
        )
        selection = _select(tmp_path, ["tests/unit/qa/helpers.py"])
        assert selection.selected == ["tests/unit/qa/test_user.py"]


class TestDeclaredRules:
    @pytest.mark.parametrize(
        "entry",
        [
            {"tests": ["x"], "why": "w"},
            {"glob": "*.md", "why": "w"},
            {"glob": "*.md", "tools": ["docs_qa"]},
            {"glob": "*.md", "tools": "docs_qa", "why": "w"},
            {"glob": "*.md", "tools": ["docs_qa"], "tests": ["x"], "why": "w"},
            {"glob": "*.md", "tools": ["docs_qa"], "why": "w", "surprise": 1},
            {"glob": "*.md", "path_glob": "docs/*.md", "tools": ["docs_qa"], "why": "w"},
            {"path_glob": "", "tools": ["docs_qa"], "why": "w"},
            {"path_glob": "CLAUDE/**/*.md", "tools": ["docs_qa"], "why": "w", "path_exclude": "x"},
            {
                "path_glob": "CLAUDE/**/*.md",
                "tools": ["docs_qa"],
                "why": "w",
                "path_exclude": [""],
            },
        ],
    )
    def test_a_malformed_rule_is_reported(self, entry: dict[str, Any]) -> None:
        _, problems = changed_tests.parse_declared_rules({"rules": [entry]})
        assert problems

    def test_path_exclude_stands_a_broad_glob_down_over_the_excluded_paths(self) -> None:
        """A ledger under an excluded subtree is NOT covered, an ordinary page still is.

        Plan 00463 gate fix 2: `test_documented_hook_probes_are_marked.py`
        globs `CLAUDE/**/*.md` but then drops `CLAUDE/Plan/` and
        `CLAUDE/UPGRADES/` itself (its own `_EXCLUDED_PREFIXES`); the declared
        rule must mirror that or a plan ledger reads as `tested`, not `docs`.
        """
        rules = _rules(
            {
                "path_glob": "CLAUDE/**/*.md",
                "path_exclude": ["CLAUDE/Plan/**", "CLAUDE/UPGRADES/**"],
                "tests": ["tests/integration/test_probes.py"],
                "why": "it checks every probe example in these documents",
            }
        )
        (rule,) = rules
        assert rule.matches("CLAUDE/Architecture/StatusLine.md") is True
        assert rule.matches("CLAUDE/Plan/00466-x/NIGGLES.md") is False
        assert rule.matches("CLAUDE/Plan/00466-x/JOURNAL/00466-Journal-26-01-01.md") is False
        assert rule.matches("CLAUDE/UPGRADES/UNRELEASED/release-notes/1-x.md") is False

    def test_a_second_rule_re_includes_a_path_the_first_excludes(self) -> None:
        """`_INCLUDED_DESPITE_PREFIX` re-includes the upgrade-template guide; two ORed rules do too."""
        rules = _rules(
            {
                "path_glob": "CLAUDE/**/*.md",
                "path_exclude": ["CLAUDE/UPGRADES/**"],
                "tests": ["tests/integration/test_probes.py"],
                "why": "it checks every probe example in these documents",
            },
            {
                "path_glob": "CLAUDE/UPGRADES/upgrade-template/**/*.md",
                "tests": ["tests/integration/test_probes.py"],
                "why": "re-included despite the exclusion above",
            },
        )
        path = "CLAUDE/UPGRADES/upgrade-template/PLAN.md"
        assert any(rule.matches(path) for rule in rules)

    @pytest.mark.parametrize(
        ("pattern", "path", "matches"),
        [
            ("CLAUDE/*.md", "CLAUDE/QA.md", True),
            ("CLAUDE/*.md", "CLAUDE/Plan/00466-x/NIGGLES.md", False),
            ("docs/**/*.md", "docs/a.md", True),
            ("docs/**/*.md", "docs/guides/deep/b.md", True),
            ("docs/**/*.md", "docs/guides/b.txt", False),
            ("docs/**/*.md", "other/docs/a.md", False),
            ("README.md", "README.md", True),
            ("README.md", "docs/README.md", False),
        ],
    )
    def test_a_path_glob_matches_like_pathlib_glob(
        self, pattern: str, path: str, matches: bool
    ) -> None:
        """Review 4 N1: the rule must read what the test's ``Path.glob`` reads, no more."""
        assert changed_tests.path_glob_matches(path, pattern) is matches

    def test_every_matching_rule_applies_not_only_the_first(self, tmp_path: Path) -> None:
        """A glob reader's tests AND the doc tools both cover a page it reads."""
        _touch(tmp_path, "docs/a.md", "tests/integration/test_pages.py")
        rules = _rules(
            {
                "path_glob": "docs/**/*.md",
                "tests": ["tests/integration/test_pages.py"],
                "why": "it reads every page by glob",
            },
            {"glob": "*.md", "tools": ["docs_qa"], "why": "docs QA checks markdown"},
        )
        selection = _select(tmp_path, ["docs/a.md"], rules)
        assert selection.selected == ["tests/integration/test_pages.py"]
        assert selection.mapping[0]["tools"] == ["docs_qa"]

    @pytest.mark.parametrize(
        "changed",
        [
            "src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py",
            "src/claude_code_hooks_daemon/handlers/stop/auto_continue_stop.py",
            "src/claude_code_hooks_daemon/handlers/nitpick/hedging_language.py",
        ],
    )
    def test_handler_code_selects_the_playbook_harness(self, changed: str) -> None:
        """Ledger 00466: a handler change broke acceptance probe #124 and nothing ran it."""
        rules, problems = changed_tests.load_declared_rules(changed_tests.DEFAULT_RULES_PATH)
        assert problems == []
        harness = "tests/acceptance/test_playbook_harness.py"
        matching = [rule for rule in rules if rule.matches(changed)]
        assert any(harness in rule.tests for rule in matching), changed

    def test_code_outside_the_handlers_does_not_select_the_playbook_harness(self) -> None:
        rules, _ = changed_tests.load_declared_rules(changed_tests.DEFAULT_RULES_PATH)
        harness = "tests/acceptance/test_playbook_harness.py"
        other = "src/claude_code_hooks_daemon/core/hook_result.py"
        assert not any(harness in rule.tests for rule in rules if rule.matches(other))

    def test_this_repositorys_map_is_valid_and_honest(self) -> None:
        """Every tool it names is one `changed` runs; every test it names exists."""
        rules, problems = changed_tests.load_declared_rules(changed_tests.DEFAULT_RULES_PATH)
        assert problems == []
        assert rules
        for rule in rules:
            for tool in rule.tools:
                assert tool in llm_qa.CHANGED_TOOL_NAMES, (rule.glob, tool)
            for test in rule.tests:
                assert (PROJECT_ROOT / test).is_file(), (rule.glob, test)


class TestTheReport:
    def test_a_green_run_passes_and_counts_its_inputs(self) -> None:
        report = changed_tests.build_report(
            base="main",
            changed=["src/pkg/a.py", "README.md"],
            selection=changed_tests.Selection(
                selected=["tests/unit/test_a.py"],
                mapping=[],
                unmapped=[],
                deleted=[],
                non_python=["README.md"],
            ),
            exit_code=0,
            output="3 passed in 0.10s\n",
            allow_unmapped=False,
        )
        summary = report["summary"]
        assert summary["passed_all"] is True
        assert summary["passed"] == 3
        assert summary["files_considered"] == 2
        assert summary["test_files_selected"] == 1
        assert report["non_python"] == ["README.md"]

    def test_a_failure_is_named(self) -> None:
        output = (
            "=========================== short test summary info ============================\n"
            "FAILED tests/unit/test_a.py::test_x - AssertionError\n"
            "1 failed, 2 passed in 0.10s\n"
        )
        report = changed_tests.build_report(
            base="main",
            changed=["src/pkg/a.py"],
            selection=changed_tests.Selection(selected=["tests/unit/test_a.py"]),
            exit_code=1,
            output=output,
            allow_unmapped=False,
        )
        assert report["summary"]["passed_all"] is False
        assert report["tests"] == [{"name": "tests/unit/test_a.py::test_x", "outcome": "failed"}]

    def test_selected_tests_that_collected_nothing_is_a_failure(self) -> None:
        report = changed_tests.build_report(
            base="main",
            changed=["src/pkg/a.py"],
            selection=changed_tests.Selection(selected=["tests/unit/test_a.py"]),
            exit_code=5,
            output="no tests ran in 0.01s\n",
            allow_unmapped=False,
        )
        assert report["summary"]["passed_all"] is False

    def test_an_unmapped_file_fails_the_run(self) -> None:
        report = changed_tests.build_report(
            base="main",
            changed=["src/pkg/orphan.py"],
            selection=changed_tests.Selection(unmapped=["src/pkg/orphan.py"]),
            exit_code=None,
            output="",
            allow_unmapped=False,
        )
        assert report["summary"]["passed_all"] is False
        assert report["unmapped"] == ["src/pkg/orphan.py"]

    def test_the_reason_for_each_unmapped_file_is_in_the_report(self) -> None:
        reasons = {"src/pkg/hub.py": {"reason": "too-broad", "detail": "d", "tests_run": []}}
        report = changed_tests.build_report(
            base="main",
            changed=["src/pkg/hub.py"],
            selection=changed_tests.Selection(unmapped=["src/pkg/hub.py"], reasons=reasons),
            exit_code=None,
            output="",
            allow_unmapped=False,
        )
        assert report["unmapped_reasons"] == reasons

    def test_an_explicit_allowance_passes_but_records_it(self) -> None:
        report = changed_tests.build_report(
            base="main",
            changed=["src/pkg/orphan.py"],
            selection=changed_tests.Selection(unmapped=["src/pkg/orphan.py"]),
            exit_code=None,
            output="",
            allow_unmapped=True,
        )
        assert report["summary"]["passed_all"] is True
        assert report["unmapped_allowed"] is True

    def test_a_failure_report_never_passes(self) -> None:
        report = changed_tests.failure_report("no merge base")
        assert report["summary"]["passed_all"] is False
        assert report["summary"]["error"] == "no merge base"


class TestMain:
    def _run(
        self,
        tmp_path: Path,
        *,
        git: Any,
        extra: list[str] | None = None,
        pytest_result: tuple[int, str] = (0, "1 passed in 0.01s\n"),
        rules: str = "rules: []\n",
    ) -> tuple[int, dict[str, Any], list[list[str]]]:
        calls: list[list[str]] = []

        def run_pytest(paths: list[str], root: Path) -> tuple[int, str]:
            calls.append(paths)
            return pytest_result

        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(rules, encoding="utf-8")
        code = changed_tests.main(
            ["--json", "--root", str(tmp_path), "--rules", str(rules_file), *(extra or [])],
            run_git=git,
            run_pytest=run_pytest,
        )
        report = json.loads((tmp_path / "untracked" / "qa" / "changed_tests.json").read_text())
        return code, report, calls

    def test_a_green_targeted_run(self, tmp_path: Path) -> None:
        _touch(tmp_path, "src/pkg/a.py", "tests/unit/test_a.py")
        code, report, calls = self._run(tmp_path, git=_git_answering(diff="src/pkg/a.py\n"))
        assert code == changed_tests.EXIT_SUCCESS
        assert calls == [["tests/unit/test_a.py"]]
        assert report["summary"]["passed_all"] is True

    def test_a_red_targeted_run(self, tmp_path: Path) -> None:
        _touch(tmp_path, "src/pkg/a.py", "tests/unit/test_a.py")
        code, _, _ = self._run(
            tmp_path,
            git=_git_answering(diff="src/pkg/a.py\n"),
            pytest_result=(1, "1 failed in 0.01s\n"),
        )
        assert code == changed_tests.EXIT_ISSUES

    def test_an_unmapped_change_fails_without_running_pytest(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _touch(tmp_path, ".claude/hooks-daemon.yaml")
        code, report, calls = self._run(
            tmp_path, git=_git_answering(diff=".claude/hooks-daemon.yaml\n")
        )
        assert code == changed_tests.EXIT_ISSUES
        assert calls == []
        assert report["unmapped"] == [".claude/hooks-daemon.yaml"]
        assert "no tests ran" in capsys.readouterr().out

    def test_allow_unmapped_passes_a_change_that_maps_to_nothing(self, tmp_path: Path) -> None:
        _touch(tmp_path, ".claude/hooks-daemon.yaml")
        code, report, _ = self._run(
            tmp_path,
            git=_git_answering(diff=".claude/hooks-daemon.yaml\n"),
            extra=["--allow-unmapped"],
        )
        assert code == changed_tests.EXIT_SUCCESS
        assert report["unmapped_allowed"] is True

    def test_a_change_covered_only_by_declared_tools_passes(self, tmp_path: Path) -> None:
        _touch(tmp_path, "CLAUDE/QA.md")
        code, _, calls = self._run(
            tmp_path,
            git=_git_answering(diff="CLAUDE/QA.md\n"),
            rules="rules:\n  - glob: '*.md'\n    tools: [docs_qa]\n    why: docs QA\n",
        )
        assert code == changed_tests.EXIT_SUCCESS
        assert calls == []

    def test_an_empty_change_set_verifies_nothing_and_fails(self, tmp_path: Path) -> None:
        code, report, calls = self._run(tmp_path, git=_git_answering())
        assert code == changed_tests.EXIT_ISSUES
        assert report["summary"]["passed_all"] is False
        assert calls == []

    def test_running_on_the_base_branch_itself_is_refused(self, tmp_path: Path) -> None:
        """On `main`, the merge base is HEAD, so committed work vanishes from the set."""
        _touch(tmp_path, "src/pkg/a.py", "tests/unit/test_a.py")
        code, report, calls = self._run(
            tmp_path, git=_git_answering(diff="src/pkg/a.py\n", branch="main")
        )
        assert code == changed_tests.EXIT_OPERATIONAL
        assert "--base" in report["summary"]["error"]
        assert calls == []

    def test_an_unresolvable_base_is_an_operational_failure(self, tmp_path: Path) -> None:
        code, report, calls = self._run(tmp_path, git=_git_answering(merge_base_code=128))
        assert code == changed_tests.EXIT_OPERATIONAL
        assert report["summary"]["passed_all"] is False
        assert calls == []


_RANGE_START = "a" * 40
_RANGE_END = "b" * 40
_RANGE = f"{_RANGE_START}..{_RANGE_END}"


def _range_git(diff: str) -> Any:
    """A ``run_git`` stand-in for ``--range``: one diff between the two ends, nothing else."""

    def run(args: list[str], root: Path) -> tuple[int, str, str]:
        if args[0] == "diff":
            assert "--no-renames" in args, "a rename must list the old path too"
            assert args[-2:] == [_RANGE_START, _RANGE_END], args
            return 0, diff, ""
        if args[0] == "ls-files" and "--cached" in args:
            return 0, "".join(f"{relative}\n" for relative in _tree(root)), ""
        raise AssertionError(f"a range run makes no other git call: {args}")

    return run


class TestAnExplicitRange:
    """``--range A..B``: what one span of history changed, judged in this tree.

    The batched gate's recheck after ``main`` moves needs exactly what the
    move brought in, not everything since the merge base (``llm_qa.py
    main-moved``, review 3 R1).
    """

    def _main(self, tmp_path: Path, argv: list[str], git: Any, calls: list[list[str]]) -> int:
        def run_pytest(paths: list[str], root: Path) -> tuple[int, str]:
            calls.append(paths)
            return 0, "1 passed in 0.01s\n"

        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text("rules: []\n", encoding="utf-8")
        return changed_tests.main(
            ["--root", str(tmp_path), "--rules", str(rules_file), *argv],
            run_git=git,
            run_pytest=run_pytest,
        )

    def test_the_range_is_the_change_set_and_is_recorded(self, tmp_path: Path) -> None:
        _touch(tmp_path, "src/pkg/a.py", "tests/unit/test_a.py")
        calls: list[list[str]] = []
        code = self._main(
            tmp_path, ["--json", "--range", _RANGE], _range_git("src/pkg/a.py\n"), calls
        )
        report = json.loads((tmp_path / "untracked" / "qa" / "changed_tests.json").read_text())
        assert code == changed_tests.EXIT_SUCCESS
        assert calls == [["tests/unit/test_a.py"]]
        assert report["range"] == _RANGE

    @pytest.mark.parametrize("spec", ["aaa", "..bbb", "aaa..", "aaa...bbb", "a..b..c"])
    def test_a_malformed_range_is_an_operational_failure(self, tmp_path: Path, spec: str) -> None:
        calls: list[list[str]] = []
        code = self._main(tmp_path, ["--range", spec], _range_git(""), calls)
        assert code == changed_tests.EXIT_OPERATIONAL
        assert calls == []

    def test_range_and_base_cannot_both_be_given(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            self._main(tmp_path, ["--range", _RANGE, "--base", "main"], _range_git(""), [])

    def test_select_only_prints_the_selection_and_runs_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _touch(tmp_path, "src/pkg/a.py", "tests/unit/test_a.py", "src/pkg/orphan.py")
        calls: list[list[str]] = []
        code = self._main(
            tmp_path,
            ["--json", "--range", _RANGE, "--select-only"],
            _range_git("src/pkg/a.py\nsrc/pkg/orphan.py\n"),
            calls,
        )
        payload = json.loads(capsys.readouterr().out)
        assert code == changed_tests.EXIT_SUCCESS
        assert calls == []
        assert not (tmp_path / "untracked" / "qa" / "changed_tests.json").exists()
        assert payload["range"] == _RANGE
        assert payload["selected"] == ["tests/unit/test_a.py"]
        assert [entry["file"] for entry in payload["mapping"]] == ["src/pkg/a.py"]
        assert payload["unmapped"] == ["src/pkg/orphan.py"]
        assert payload["unmapped_reasons"]["src/pkg/orphan.py"]["reason"] == "uncovered"

    def test_select_only_needs_a_range(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            self._main(tmp_path, ["--select-only"], _range_git(""), [])


@pytest.mark.parametrize(
    "flag", ["--base", "--root", "--allow-unmapped", "--rules", "--range", "--select-only"]
)
def test_the_cli_documents_its_options(flag: str) -> None:
    assert flag in (changed_tests.__doc__ or "")
