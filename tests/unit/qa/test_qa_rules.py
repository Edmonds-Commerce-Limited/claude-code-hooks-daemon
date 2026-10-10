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


_PACKAGE: Final[str] = "claude_code_hooks_daemon"


def _imported_constants(tree: ast.Module) -> dict[str, str]:
    """String constants a checker imports from this package, by the name it binds them to."""
    found: dict[str, str] = {}
    for node in tree.body:
        if not (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.split(".")[0] == _PACKAGE
        ):
            continue
        source = PROJECT_ROOT / "src" / Path(*node.module.split(".")).with_suffix(".py")
        if not source.is_file():
            continue
        theirs = _module_constants(ast.parse(source.read_text(encoding="utf-8")), {})
        found.update(
            {
                alias.asname or alias.name: theirs[alias.name]
                for alias in node.names
                if alias.name in theirs
            }
        )
    return found


def _module_constants(tree: ast.Module, imported: dict[str, str]) -> dict[str, str]:
    """Module-level `NAME = "literal"` (or an alias of a known constant), for `rule=NAME`."""
    found: dict[str, str] = dict(imported)
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        text: str | None = None
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            text = value.value
        elif isinstance(value, ast.Name) and value.id in found:
            text = found[value.id]
        if text is not None:
            found.update({t.id: text for t in targets if isinstance(t, ast.Name)})
    return found


class UnresolvedRuleError(AssertionError):
    """A rule expression the discovery cannot turn into IDs: it fails, never skips."""


def _module_lookups(tree: ast.Module) -> dict[str, ast.Dict]:
    """Module-level ``NAME = {key: value, ...}``; resolved only where a rule indexes one."""
    found: dict[str, ast.Dict] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        if isinstance(node.value, ast.Dict):
            found.update(dict.fromkeys(names, node.value))
    return found


def _literals_or_constants(
    node: ast.expr, constants: dict[str, str], lookups: dict[str, ast.Dict]
) -> list[str]:
    """Every string a rule expression can be: its literals, and the constants it names.

    A call is not descended into: ``rule=str(diagnostic.get("rule", ""))`` passes
    a third-party tool's own ID through, which is not a rule of this checker. Any
    other shape that builds an ID the source does not spell out fails closed: an
    f-string, a concatenation, a constant-styled name that is not defined here.
    A lower-case name is a parameter or local, assigned (and found) elsewhere.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name):
        if node.id in constants:
            return [constants[node.id]]
        if node.id.lstrip("_").isupper():
            raise UnresolvedRuleError(f"line {node.lineno}: {node.id} is not a module constant")
        return []
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        if node.value.id in lookups:
            return [
                leaf
                for value in lookups[node.value.id].values
                for leaf in _literals_or_constants(value, constants, {})
            ]
        raise UnresolvedRuleError(f"line {node.lineno}: {node.value.id}[...] is not a lookup here")
    if isinstance(node, ast.JoinedStr):
        first = node.values[0] if node.values else None
        if (
            isinstance(first, ast.FormattedValue)
            and isinstance(first.value, ast.Name)
            and first.value.id in constants
            and _RULE_CONSTANT.match(first.value.id)
        ):
            return [constants[first.value.id]]
        raise UnresolvedRuleError(
            f"line {node.lineno}: an f-string rule ID; give each ID a RULE_* constant"
        )
    if isinstance(node, ast.BinOp):
        raise UnresolvedRuleError(f"line {node.lineno}: a built rule ID; give each a constant")
    if isinstance(node, ast.IfExp):
        return _literals_or_constants(node.body, constants, lookups) + _literals_or_constants(
            node.orelse, constants, lookups
        )
    if isinstance(node, ast.BoolOp):
        return [
            leaf
            for value in node.values
            for leaf in _literals_or_constants(value, constants, lookups)
        ]
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
    constants = _module_constants(tree, _imported_constants(tree))
    lookups = _module_lookups(tree)
    found: set[str] = {value for name, value in constants.items() if _RULE_CONSTANT.match(name)}
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "rule":
            found.update(_literals_or_constants(node.value, constants, lookups))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "rule":
                    found.update(_literals_or_constants(value, constants, lookups))
        elif isinstance(node, ast.Assign) and any(_is_rule_target(t) for t in node.targets):
            found.update(_literals_or_constants(node.value, constants, lookups))
        elif isinstance(node, ast.AnnAssign) and _is_rule_target(node.target) and node.value:
            found.update(_literals_or_constants(node.value, constants, lookups))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_add"
            and len(node.args) >= 2
        ):
            found.update(_literals_or_constants(node.args[1], constants, lookups))
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "VIOLATION_TYPES" for t in node.targets
        ):
            if isinstance(node.value, ast.Dict):
                found.update(
                    key.value
                    for key in node.value.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                )
    malformed = sorted(rule for rule in found if not _RULE_ID.match(rule))
    if malformed:
        raise UnresolvedRuleError(f"{path.name}: rule IDs that are not kebab-case: {malformed}")
    return found


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


class TestDiscoveryFailsClosed:
    """A rule ID the source builds at run time must fail the guard, never slip past it."""

    @staticmethod
    def _discover(tmp_path: Path, source: str) -> set[str]:
        path = tmp_path / "checker.py"
        path.write_text(source, encoding="utf-8")
        return discover_rule_ids(path)

    def test_an_fstring_rule_id_fails(self, tmp_path: Path) -> None:
        with pytest.raises(UnresolvedRuleError, match="f-string"):
            self._discover(tmp_path, 'def f(name):\n    rule = f"shell-{name}"\n')

    def test_a_concatenated_rule_id_fails(self, tmp_path: Path) -> None:
        with pytest.raises(UnresolvedRuleError, match="built rule ID"):
            self._discover(tmp_path, 'def f(name):\n    return dict(rule="shell-" + name)\n')

    def test_an_undefined_constant_fails(self, tmp_path: Path) -> None:
        with pytest.raises(UnresolvedRuleError, match="RULE_MISSING"):
            self._discover(tmp_path, "def f():\n    return dict(rule=RULE_MISSING)\n")

    def test_a_lookup_that_is_not_in_the_module_fails(self, tmp_path: Path) -> None:
        with pytest.raises(UnresolvedRuleError, match="RULES"):
            self._discover(tmp_path, "def f(k):\n    rule = RULES[k]\n")

    def test_a_family_prefix_fstring_resolves_to_the_family(self, tmp_path: Path) -> None:
        source = '_PUBLIC_RULE_PREFIX = "fam"\ndef f(n):\n    return dict(rule=f"{_PUBLIC_RULE_PREFIX}:{n}")\n'
        assert self._discover(tmp_path, source) == {"fam"}

    def test_a_dict_lookup_of_constants_resolves_to_every_value(self, tmp_path: Path) -> None:
        source = (
            'RULE_A = "rule-a"\nRULE_B = "rule-b"\nRULES = {"x": RULE_A, "y": RULE_B}\n'
            "def f(k):\n    rule = RULES[k]\n"
        )
        assert self._discover(tmp_path, source) == {"rule-a", "rule-b"}

    def test_a_parameter_passed_through_is_not_a_finding(self, tmp_path: Path) -> None:
        assert self._discover(tmp_path, "def f(rule):\n    return dict(rule=rule)\n") == set()


class TestEveryShellPatternRuleIsRegistered:
    """B1: the shell error-hiding findings carry stable IDs that `--explain` resolves."""

    SHELL_RULES: Final[tuple[str, ...]] = (
        "shell-or-true",
        "shell-or-colon",
        "shell-set-plus-e",
        "shell-redirect-all-to-null",
        "shell-discard-both-streams",
        "shell-empty-err-trap",
    )

    @pytest.mark.parametrize("rule", SHELL_RULES)
    def test_the_rule_is_discovered_registered_and_explained(self, rule: str) -> None:
        assert discovered()[rule] == {"audit_error_hiding.py"}
        assert llm_qa.explain_rule(rule) is not None


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


class TestBatchDefencesDeclaration:
    """`batch_defences` is the one place the batch-check rows of `defences` are declared."""

    def test_the_declared_checkers_are_exactly_the_three_with_a_defence_counterpart(self) -> None:
        declared = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))["batch_defences"]
        assert (
            "check_british_english.py" not in declared
        )  # a spelling convention, not a defect class
        assert set(declared) == {
            "audit_error_hiding.py",
            "check_sensitive_content.py",
            "check_inline_suppressions.py",
        }

    def test_each_declared_step_runs_its_script_in_the_runner(self) -> None:
        declared = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))["batch_defences"]
        for script, entry in declared.items():
            command = llm_qa.TOOL_REGISTRY[entry["step"]].command
            assert any(part.endswith(script) for part in command), script

    def test_each_declared_handler_is_a_library_handler_config_key(self) -> None:
        from claude_code_hooks_daemon.handlers.registry import HandlerRegistry
        from claude_code_hooks_daemon.utils.naming import class_name_to_config_key

        registry = HandlerRegistry()
        registry.discover("claude_code_hooks_daemon.handlers")
        classes = (registry.get_handler_class(name) for name in registry.list_handlers())
        keys = {class_name_to_config_key(cls.__name__) for cls in classes if cls is not None}
        declared = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))["batch_defences"]
        for script, entry in declared.items():
            assert entry["handler"] in keys, script
            assert "defect_class" not in entry, script
