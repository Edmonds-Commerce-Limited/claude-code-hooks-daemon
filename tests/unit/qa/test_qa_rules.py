"""Every rule ID a `scripts/qa` checker prints resolves offline (Plan 00484 G6).

TOOLING-SPEC 4.2: an identifier a detector prints must resolve, offline, to
documentation that ships with the code, and the project needs a defined place
for a new rule's documentation. The handlers have `explain-rule`; the QA
checkers had neither, so `rule-3` in a failing summary led nowhere.

`scripts/qa/qa-rules.json` is that place: one entry per ID with a statement, a
fix and the scripts that print it. `llm_qa.py --explain <ID>` prints an entry.
This module is the guard over it. The set of IDs is DISCOVERED from the
checkers' source, so a checker that gains a rule without an entry fails here,
and an entry whose rule was deleted fails here too.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

import pytest

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
QA_DIR: Final[Path] = PROJECT_ROOT / "scripts" / "qa"
REGISTRY_FILE: Final[Path] = QA_DIR / "qa-rules.json"

#: Module-level names that hold a rule ID: `RULE_X`, `_RULE`, `X_RULE`, `_RULE_NAME`, and
#: `X_RULE_PREFIX` (the family of an ID computed as `prefix:name`).
_RULE_CONSTANT: Final[re.Pattern[str]] = re.compile(
    r"^_?(?:RULE_[A-Z_]+|[A-Z_]*_RULE(?:_NAME|_PREFIX)?|RULE)$"
)
_RULE_ID: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def _load_llm_qa() -> Any:
    spec = importlib.util.spec_from_file_location("llm_qa_for_rules_test", QA_DIR / "llm_qa.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


llm_qa = _load_llm_qa()


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` assignments, for resolving `rule=NAME`."""
    found: dict[str, str] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            found.update({t.id: value.value for t in targets if isinstance(t, ast.Name)})
    return found


def _literals_or_constants(node: ast.expr, constants: dict[str, str]) -> list[str]:
    """Every string a rule expression can be: its literals, and the constants it names.

    A call is not descended into: ``rule=str(diagnostic.get("rule", ""))`` passes
    a third-party tool's own ID through, which is not a rule of this checker.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name) and node.id in constants:
        return [constants[node.id]]
    if isinstance(node, ast.IfExp):
        return _literals_or_constants(node.body, constants) + _literals_or_constants(
            node.orelse, constants
        )
    if isinstance(node, ast.BoolOp):
        return [leaf for value in node.values for leaf in _literals_or_constants(value, constants)]
    return []


def _is_rule_target(target: ast.expr) -> bool:
    return isinstance(target, ast.Name) and target.id == "rule"


def discover_rule_ids(path: Path) -> set[str]:
    """The rule IDs the checker at ``path`` can print, found statically.

    Recognised, each a shape the shipped checkers really use: a ``RULE``-named
    module constant, ``rule=<literal or constant>``, ``"rule": <literal>``, an
    assignment to a variable called ``rule`` or a ``rule`` field default, a
    ``_add(node, "<id>", ...)`` call, and the keys of ``VIOLATION_TYPES``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants = _module_constants(tree)
    found: set[str] = {value for name, value in constants.items() if _RULE_CONSTANT.match(name)}
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "rule":
            found.update(_literals_or_constants(node.value, constants))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "rule":
                    found.update(_literals_or_constants(value, constants))
        elif isinstance(node, ast.Assign) and any(_is_rule_target(t) for t in node.targets):
            found.update(_literals_or_constants(node.value, constants))
        elif isinstance(node, ast.AnnAssign) and _is_rule_target(node.target) and node.value:
            found.update(_literals_or_constants(node.value, constants))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_add"
            and len(node.args) >= 2
        ):
            found.update(_literals_or_constants(node.args[1], constants))
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "VIOLATION_TYPES" for t in node.targets
        ):
            if isinstance(node.value, ast.Dict):
                found.update(
                    key.value
                    for key in node.value.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                )
    return {rule for rule in found if _RULE_ID.match(rule)}


def discovered() -> dict[str, set[str]]:
    """Every discovered rule ID, with the scripts that print it."""
    by_rule: dict[str, set[str]] = {}
    for path in sorted(QA_DIR.glob("*.py")):
        for rule in discover_rule_ids(path):
            by_rule.setdefault(rule, set()).add(path.name)
    return by_rule


def registry() -> dict[str, dict[str, Any]]:
    data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    rules: dict[str, dict[str, Any]] = data["rules"]
    return rules


class TestTheRegistryIsWellFormed:
    def test_every_entry_has_a_statement_and_a_fix(self) -> None:
        for rule_id, entry in registry().items():
            assert entry["statement"].strip(), rule_id
            assert entry["fix"].strip(), rule_id

    def test_every_entry_names_scripts_that_exist(self) -> None:
        for rule_id, entry in registry().items():
            assert entry["checks"], rule_id
            for script in entry["checks"]:
                assert (QA_DIR / script).is_file(), f"{rule_id}: {script}"

    def test_the_docs_route_exists(self) -> None:
        docs = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))["docs"]
        assert (PROJECT_ROOT / docs).is_file()

    def test_a_statement_is_one_sentence_of_text_not_a_placeholder(self) -> None:
        for rule_id, entry in registry().items():
            assert len(entry["statement"]) >= 25, rule_id
            assert len(entry["fix"]) >= 15, rule_id


class TestTheRegistryAndTheCheckersAgree:
    def test_every_rule_a_checker_can_print_has_an_entry(self) -> None:
        missing = sorted(set(discovered()) - set(registry()))
        assert missing == [], f"add these to scripts/qa/qa-rules.json: {missing}"

    def test_every_entry_is_a_rule_a_checker_still_prints(self) -> None:
        stale = sorted(set(registry()) - set(discovered()))
        assert stale == [], f"these entries name a rule no checker prints: {stale}"

    def test_each_entry_names_exactly_the_scripts_that_print_it(self) -> None:
        found = discovered()
        wrong = {
            rule_id: (sorted(entry["checks"]), sorted(found[rule_id]))
            for rule_id, entry in registry().items()
            if rule_id in found and set(entry["checks"]) != found[rule_id]
        }
        assert wrong == {}, f"(registry, source) per rule: {wrong}"

    def test_discovery_sees_the_shapes_the_checkers_use(self) -> None:
        """A discovery that finds nothing would make the guard above vacuous."""
        found = discovered()
        assert len(found) > 80
        for rule in (
            "magic-handler-name",  # _add(node, "<id>", ...)
            "silent-pass",  # VIOLATION_TYPES key
            "raw-signal",  # a constant resolved through rule=
            "double-suppression",  # rule="<literal>"
            "wrong-github-owner",  # "rule": "<literal>"
            "inline-suppression-without-reason",  # RULE_* constant
        ):
            assert rule in found, rule


class TestExplain:
    def test_a_known_id_prints_statement_fix_checker_and_docs(self) -> None:
        text = llm_qa.explain_rule("silent-pass")
        assert text is not None
        assert "silent-pass" in text
        assert registry()["silent-pass"]["statement"] in text
        assert registry()["silent-pass"]["fix"] in text
        assert "audit_error_hiding.py" in text
        assert "CLAUDE/QA.md" in text

    def test_a_family_id_resolves_to_its_family(self) -> None:
        text = llm_qa.explain_rule("public-pattern:aws-access-key")
        assert text is not None
        assert registry()["public-pattern"]["statement"] in text
        assert "public-pattern:aws-access-key" in text

    def test_an_unknown_id_resolves_to_nothing(self) -> None:
        assert llm_qa.explain_rule("no-such-rule") is None

    def test_the_command_exits_zero_for_a_known_id(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert llm_qa.explain_command(["silent-pass"]) == 0
        assert "silent-pass" in capsys.readouterr().out

    def test_the_command_fails_for_an_unknown_id(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert llm_qa.explain_command(["no-such-rule"]) == 1
        assert "no-such-rule" in capsys.readouterr().err

    def test_the_command_with_no_id_lists_every_rule(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert llm_qa.explain_command([]) == 0
        out = capsys.readouterr().out
        for rule_id in registry():
            assert rule_id in out

    def test_the_command_takes_one_id_only(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert llm_qa.explain_command(["a", "b"]) == 1
        assert "one" in capsys.readouterr().err

    def test_main_routes_explain_before_running_anything(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["llm_qa.py", "--explain", "silent-pass"])
        monkeypatch.setattr(llm_qa, "_run_tools", lambda *a, **k: pytest.fail("ran tools"))
        assert llm_qa.main() == 0
        assert "silent-pass" in capsys.readouterr().out

    def test_help_mentions_explain(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["llm_qa.py", "--help"])
        assert llm_qa.main() == 0
        assert "--explain" in capsys.readouterr().out
