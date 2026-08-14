"""Tests for the documented-snippet API check.

The motivating defect (Plan 00243): ``CLAUDE/CodeLifecycle/Features.md`` taught
``AcceptanceTest(test_id=..., hook_input={...})``. Neither keyword argument
exists on the dataclass, so an agent copying the documented example got a
``TypeError`` on construction. It survived because nothing validates the
Python snippets in documentation against the symbols they construct.

A follow-up audit found seven more, of which the first version of this check
caught exactly one. The rules below are the subset that is MECHANICALLY
DECIDABLE — no guessing, no type inference. What is deliberately out of scope
is recorded in the module docstring of the check itself.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "qa" / "check_doc_snippets.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("check_doc_snippets", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_doc_snippets"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod() -> Any:
    return _load_module()


def _rules(violations: list[Any]) -> list[str]:
    return [v.rule for v in violations]


class TestExtractPythonBlocks:
    """Fenced python blocks are located with their true line numbers."""

    def test_extracts_a_single_block(self, mod: Any) -> None:
        blocks = mod.extract_python_blocks("intro\n\n```python\nx = 1\n```\n")
        assert len(blocks) == 1
        assert blocks[0].source == "x = 1"

    def test_line_number_points_at_the_first_code_line(self, mod: Any) -> None:
        blocks = mod.extract_python_blocks("a\nb\n```python\nx = 1\n```\n")
        assert blocks[0].start_line == 4

    def test_ignores_non_python_fences(self, mod: Any) -> None:
        assert mod.extract_python_blocks("```bash\nls -la\n```\n") == []

    def test_extracts_multiple_blocks(self, mod: Any) -> None:
        text = "```python\na = 1\n```\ntext\n```python\nb = 2\n```\n"
        assert len(mod.extract_python_blocks(text)) == 2


class TestUnknownKeyword:
    """A keyword the real symbol does not accept. The motivating defect."""

    def test_flags_unknown_kwarg_on_a_core_symbol(self, mod: Any) -> None:
        found = mod.check_snippet("doc.md", 1, "AcceptanceTest(test_id='x', title='t')")
        assert _rules(found) == [mod.RULE_UNKNOWN_KEYWORD]
        assert "test_id" in found[0].message

    def test_flags_every_unknown_kwarg(self, mod: Any) -> None:
        found = mod.check_snippet("doc.md", 1, "AcceptanceTest(test_id='x', hook_input={})")
        assert len(found) == 2

    def test_accepts_real_kwargs(self, mod: Any) -> None:
        snippet = "AcceptanceTest(title='t', command='c', description='d')"
        assert mod.check_snippet("doc.md", 1, snippet) == []

    def test_missing_required_args_are_not_flagged(self, mod: Any) -> None:
        """Docs abbreviate; only a WRONG name is decidable."""
        assert mod.check_snippet("doc.md", 1, "AcceptanceTest(title='t')") == []

    def test_ignores_symbols_that_are_not_daemon_api(self, mod: Any) -> None:
        assert mod.check_snippet("doc.md", 1, "SomeThirdPartyThing(whatever=1)") == []

    def test_flags_hookresult_unknown_kwarg(self, mod: Any) -> None:
        """Pydantic DISCARDS this silently, so it never crashes — worse, not better."""
        found = mod.check_snippet("doc.md", 1, "HookResult(decision='deny', message='x')")
        assert _rules(found) == [mod.RULE_UNKNOWN_KEYWORD]


class TestPositionalArgument:
    """A keyword-only symbol given a positional argument raises TypeError."""

    def test_flags_positional_arg_to_hookresult(self, mod: Any) -> None:
        found = mod.check_snippet("doc.md", 1, "HookResult('allow', context=[])")
        assert _rules(found) == [mod.RULE_POSITIONAL_ARG]

    def test_allows_positional_where_the_signature_permits_it(self, mod: Any) -> None:
        """AcceptanceTest is a plain dataclass — title is positional-or-keyword."""
        assert mod.check_snippet("doc.md", 1, "AcceptanceTest('t', 'c', 'd')") == []

    def test_starargs_are_not_flagged(self, mod: Any) -> None:
        assert mod.check_snippet("doc.md", 1, "HookResult(*args)") == []


class TestImportValidity:
    """A documented import must resolve. Zero guessing involved."""

    def test_flags_a_symbol_that_does_not_exist(self, mod: Any) -> None:
        snippet = "from claude_code_hooks_daemon.daemon.server import DaemonServer"
        found = mod.check_snippet("doc.md", 1, snippet)
        assert _rules(found) == [mod.RULE_UNKNOWN_IMPORT]
        assert "DaemonServer" in found[0].message

    def test_accepts_a_real_symbol(self, mod: Any) -> None:
        snippet = "from claude_code_hooks_daemon.daemon.server import HooksDaemon"
        assert mod.check_snippet("doc.md", 1, snippet) == []

    def test_accepts_a_real_core_symbol(self, mod: Any) -> None:
        assert (
            mod.check_snippet("doc.md", 1, "from claude_code_hooks_daemon.core import Handler")
            == []
        )

    def test_ignores_third_party_imports(self, mod: Any) -> None:
        assert mod.check_snippet("doc.md", 1, "from pathlib import NoSuchThing") == []

    def test_unimportable_daemon_module_is_skipped_not_failed(self, mod: Any) -> None:
        snippet = "from claude_code_hooks_daemon.no_such_module import Thing"
        assert mod.check_snippet("doc.md", 1, snippet) == []


class TestHandlerIdentifier:
    """Handler requires handler_id or name — the constructor itself raises."""

    def test_flags_super_init_without_an_identifier(self, mod: Any) -> None:
        snippet = (
            "class MyHandler(Handler):\n"
            "    def __init__(self):\n"
            "        super().__init__(priority=50)\n"
        )
        assert _rules(mod.check_snippet("doc.md", 1, snippet)) == [mod.RULE_MISSING_IDENTIFIER]

    def test_accepts_handler_id(self, mod: Any) -> None:
        snippet = (
            "class MyHandler(Handler):\n"
            "    def __init__(self):\n"
            "        super().__init__(handler_id=HandlerID.X, priority=50)\n"
        )
        assert mod.check_snippet("doc.md", 1, snippet) == []

    def test_accepts_the_deprecated_name_alias(self, mod: Any) -> None:
        snippet = (
            "class MyHandler(Handler):\n"
            "    def __init__(self):\n"
            "        super().__init__(name='x', priority=50)\n"
        )
        assert mod.check_snippet("doc.md", 1, snippet) == []

    def test_flags_unknown_kwarg_on_super_init(self, mod: Any) -> None:
        snippet = (
            "class MyHandler(Handler):\n"
            "    def __init__(self):\n"
            "        super().__init__(name='x', prio=50)\n"
        )
        assert mod.RULE_UNKNOWN_KEYWORD in _rules(mod.check_snippet("doc.md", 1, snippet))

    def test_super_init_outside_a_handler_subclass_is_ignored(self, mod: Any) -> None:
        snippet = (
            "class Other(SomethingElse):\n"
            "    def __init__(self):\n"
            "        super().__init__(whatever=1)\n"
        )
        assert mod.check_snippet("doc.md", 1, snippet) == []


class TestUnparseableSnippets:
    """An abbreviated snippet cannot be judged, so it is skipped, not failed."""

    def test_ellipsis_body_does_not_raise(self, mod: Any) -> None:
        assert mod.check_snippet("doc.md", 1, "AcceptanceTest(\n    ...\n") == []

    def test_prose_placeholder_does_not_raise(self, mod: Any) -> None:
        assert mod.check_snippet("doc.md", 1, "handler = <your handler here>") == []


class TestLineAttribution:
    """A violation points at the line inside the document, not inside the block."""

    def test_offsets_by_block_start(self, mod: Any) -> None:
        found = mod.check_snippet("doc.md", 10, "x = 1\nAcceptanceTest(test_id='x')")
        assert found[0].line == 11


class TestJsonReportContract:
    """llm_qa.py's summarisers read summary.total_violations on every check."""

    def test_writes_summary_total_violations(self, mod: Any, tmp_path: Path) -> None:
        (tmp_path / "untracked" / "qa").mkdir(parents=True)
        doc = tmp_path / "README.md"
        doc.write_text("```python\nAcceptanceTest(test_id='x')\n```\n", encoding="utf-8")

        assert mod.main(["--json", "--root", str(tmp_path)]) == 1

        report = json.loads(
            (tmp_path / "untracked" / "qa" / "doc_snippets.json").read_text(encoding="utf-8")
        )
        assert report["summary"]["total_violations"] == 1
        assert report["summary"]["passed"] is False
        assert report["violations"][0]["rule"] == mod.RULE_UNKNOWN_KEYWORD

    def test_writes_summary_passed_true_when_clean(self, mod: Any, tmp_path: Path) -> None:
        """llm_qa._is_passed defaults `passed` to False — omitting it reads as
        a failure with zero violations, which is exactly how this check first
        shipped."""
        (tmp_path / "untracked" / "qa").mkdir(parents=True)
        (tmp_path / "README.md").write_text("```python\nx = 1\n```\n", encoding="utf-8")

        assert mod.main(["--json", "--root", str(tmp_path)]) == 0

        report = json.loads(
            (tmp_path / "untracked" / "qa" / "doc_snippets.json").read_text(encoding="utf-8")
        )
        assert report["summary"]["passed"] is True
        assert report["summary"]["total_violations"] == 0

    def test_exit_zero_when_clean(self, mod: Any, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("```python\nx = 1\n```\n", encoding="utf-8")
        assert mod.main(["--root", str(tmp_path)]) == 0


class TestRepositoryIsClean:
    """The real documentation must pass — this is the regression lock."""

    def test_no_violations_in_shipped_docs(self, mod: Any) -> None:
        violations = mod.scan(Path(__file__).resolve().parents[3])
        assert violations == [], "\n".join(v.describe() for v in violations)
