"""The `skip-list-substring` Detector — Plan 00458 (Defence Before Fix, RED first).

The class: **a bare substring membership test between a directory/skip-list
entry and a path**, spelled ``any(X in path_var for X in LIST)`` (or the
equivalent explicit ``for`` loop). Because ``in`` on two strings is substring
containment, not segment containment, ``"venv/" in file_path`` is also true
for ``file_path == ".../worktree-issue-53-venv/untracked/scratch/x.py"`` — the
guard silently stands down for any path that merely ENDS in the skipped name
(00422 N20). Six sites had this shape; ``strategies/lint/common.py``'s
``matches_skip_path`` had already fixed it once and was never reached by the
other six.

The distinguishing property is that the comprehension's OWN loop variable is
compared directly, unmodified, against something that looks like a path. A
site that first NORMALISES the loop variable (adds slash boundaries, as
``strategies/tdd/common.py``'s ``matches_directory`` already does before its
own ``in`` test) no longer carries the hazard and must stay quiet, which is
what keeps this rule from re-litigating a shape that was already fixed by
another route.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_CHECKER = Path(__file__).resolve().parents[3] / "scripts" / "qa" / "check_skip_list_substring.py"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    """The Detector, imported from its script path."""
    spec = importlib.util.spec_from_file_location("check_skip_list_substring", _CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _scan(checker: ModuleType, tmp_path: Path, source: str) -> list[str]:
    """Scan ``source`` as a module; return the reported rule ids."""
    module_dir = tmp_path / "src" / "claude_code_hooks_daemon" / "handlers"
    module_dir.mkdir(parents=True)
    module = module_dir / "sample.py"
    module.write_text(source, encoding="utf-8")
    return [v.rule for v in checker.scan_tree(tmp_path / "src" / "claude_code_hooks_daemon")]


class TestTheRuleFires:
    """On the shape that carries the hazard."""

    def test_the_original_qa_suppression_shape_is_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """``qa_suppression.py:162``'s exact spelling."""
        source = (
            "def f(file_path, strategy):\n"
            "    return any(skip_dir in file_path for skip_dir in strategy.skip_directories)\n"
        )

        assert _scan(checker, tmp_path, source) == ["unbounded-skip-list-membership"]

    def test_a_module_level_tuple_constant_is_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """``security/common.py:23``'s exact spelling."""
        source = "def f(file_path):\n    return any(skip in file_path for skip in SKIP_PATTERNS)\n"

        assert _scan(checker, tmp_path, source) == ["unbounded-skip-list-membership"]

    def test_a_negated_all_form_is_reported(self, checker: ModuleType, tmp_path: Path) -> None:
        """``british_english.py:108``'s ``not any(...)`` spelling."""
        source = (
            "def f(file_path, directories):\n"
            "    if not any(d in file_path for d in directories):\n"
            "        return False\n"
        )

        assert _scan(checker, tmp_path, source) == ["unbounded-skip-list-membership"]

    def test_an_explicit_for_loop_is_reported(self, checker: ModuleType, tmp_path: Path) -> None:
        """The non-comprehension close variant named in the plan."""
        source = (
            "def f(file_path, patterns):\n"
            "    for pattern in patterns:\n"
            "        if pattern in file_path:\n"
            "            return True\n"
            "    return False\n"
        )

        assert _scan(checker, tmp_path, source) == ["unbounded-skip-list-membership"]

    def test_abs_path_is_recognised_as_a_path_variable(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """Not just the literal name ``file_path``."""
        source = "def f(abs_path):\n    return any(s in abs_path for s in SKIP)\n"

        assert _scan(checker, tmp_path, source) == ["unbounded-skip-list-membership"]

    def test_it_reports_the_line(self, checker: ModuleType, tmp_path: Path) -> None:
        module_dir = tmp_path / "src" / "claude_code_hooks_daemon" / "handlers"
        module_dir.mkdir(parents=True)
        (module_dir / "sample.py").write_text(
            "def f(file_path):\n    return any(s in file_path for s in SKIP)\n",
            encoding="utf-8",
        )

        violations = checker.scan_tree(tmp_path / "src" / "claude_code_hooks_daemon")

        assert violations[0].line == 2


class TestTheRuleStaysQuiet:
    """The false positives that would get it suppressed."""

    def test_a_normalised_loop_variable_is_not_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """``matches_directory``'s shape: the loop var is reassigned before the
        ``in`` test, so it no longer carries the un-bounded hazard."""
        source = (
            "def f(file_path, directories):\n"
            "    for directory in directories:\n"
            "        pattern = f'/{directory}/'\n"
            "        if pattern in file_path:\n"
            "            return True\n"
            "    return False\n"
        )

        assert _scan(checker, tmp_path, source) == []

    def test_an_fstring_wrapped_loop_variable_is_not_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """``validate_eslint_on_write.py``'s shape: an f-string, not a bare Name."""
        source = (
            "def f(file_path, prefixes):\n"
            "    return any(f'{prefix}/' in file_path for prefix in prefixes)\n"
        )

        assert _scan(checker, tmp_path, source) == []

    def test_an_unrelated_comparator_is_not_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """The right-hand side must look like a path, not just any string."""
        source = "def f(content):\n    return any(k in content for k in KEYWORDS)\n"

        assert _scan(checker, tmp_path, source) == []

    def test_membership_in_a_real_list_is_not_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """``x in some_list`` (list membership, not substring) is a different,
        unrelated idiom -- the comparator here is not a path."""
        source = "def f(name, allowed_names):\n    return name in allowed_names\n"

        assert _scan(checker, tmp_path, source) == []

    def test_a_bare_compare_with_no_loop_variable_is_not_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """A single fixed literal against a path is a different, narrower shape
        than a LIST being tested -- out of scope for this rule (Plan 00458
        Task 1.1's audit treats single-pattern sites separately)."""
        source = "def f(file_path):\n    return '/vendor/' in file_path\n"

        assert _scan(checker, tmp_path, source) == []


class TestTheReport:
    """What a violation says for itself."""

    def test_the_rule_id_is_stable(self, checker: ModuleType, tmp_path: Path) -> None:
        source = "def f(file_path):\n    return any(s in file_path for s in SKIP)\n"
        module_dir = tmp_path / "src" / "claude_code_hooks_daemon" / "handlers"
        module_dir.mkdir(parents=True)
        (module_dir / "sample.py").write_text(source, encoding="utf-8")

        violation = checker.scan_tree(tmp_path / "src" / "claude_code_hooks_daemon")[0]

        assert violation.to_dict()["rule"] == "unbounded-skip-list-membership"

    def test_the_message_names_the_hazard(self, checker: ModuleType, tmp_path: Path) -> None:
        source = "def f(file_path):\n    return any(s in file_path for s in SKIP)\n"
        module_dir = tmp_path / "src" / "claude_code_hooks_daemon" / "handlers"
        module_dir.mkdir(parents=True)
        (module_dir / "sample.py").write_text(source, encoding="utf-8")

        message = str(
            checker.scan_tree(tmp_path / "src" / "claude_code_hooks_daemon")[0].to_dict()["message"]
        )

        assert "segment" in message.lower()


class TestTheCurrentTree:
    """RED before the fix, GREEN after -- Defence Before Fix (Plan 00458)."""

    def test_the_real_tree_is_clean(self, checker: ModuleType) -> None:
        """Run against this repository's own source. Red until Task 1.3 lands;
        green afterwards -- this test IS the fix's acceptance criterion."""
        repo_root = Path(__file__).resolve().parents[3]
        scan_root = repo_root / "src" / "claude_code_hooks_daemon"

        violations = checker.scan_tree(scan_root)

        assert violations == []
