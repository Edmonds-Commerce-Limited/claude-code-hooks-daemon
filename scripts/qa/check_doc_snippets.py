#!/usr/bin/env python3
"""Documented-snippet check — a Python example must construct real symbols.

Plan 00243 Phase 4, built under DBF (``CLAUDE.md`` Core Standard 15).
``CLAUDE/CodeLifecycle/Features.md`` taught
``AcceptanceTest(test_id=..., hook_input={...})``. Neither keyword argument
exists on the dataclass, so an agent copying the documented example got a
``TypeError`` on construction. The example was corrected by hand — but a
defect fixed by hand recurs, and nothing validated the other snippets. An
audit then found seven more across the tree.

**Ground truth is introspected, never restated.** Symbols come from
``claude_code_hooks_daemon`` itself and their signatures from
``inspect.signature``. There is no hardcoded registry to drift: a renamed
field changes what this check enforces on the same commit that renames it.

Rules — every one MECHANICALLY DECIDABLE, no type inference, no guessing:

``unknown-keyword``
    A keyword the callee does not accept. Note this is not always a crash:
    ``HookResult`` is a Pydantic model with ``extra`` unset, so an unknown
    keyword is silently DISCARDED — producing a handler that appears to work
    and does nothing. That is worse than a ``TypeError``, not better.

``positional-arg``
    A positional argument to a symbol whose parameters are keyword-only.

``unknown-import``
    ``from claude_code_hooks_daemon... import X`` where ``X`` does not exist.

``missing-identifier``
    ``super().__init__()`` inside a ``Handler`` subclass supplying neither
    ``handler_id`` nor ``name``. The constructor itself raises ``ValueError``.

**Deliberately OUT of scope**, because catching them would require guessing
and a gate that guesses gets switched off:

- A doc that re-declares a real class (``class HookResult: ...``) to describe
  its shape. Whether that is a claim about the real class or an illustration
  cannot be decided from the syntax.
- Method calls on an instance (``self._run_command(...)``), which need type
  inference to resolve the receiver.
- Missing REQUIRED arguments generally. Documentation abbreviates constantly,
  so this would fail on nearly every example in the tree. ``missing-identifier``
  is the one exception, and only because ``Handler`` raises on it explicitly.

A snippet that does not parse is SKIPPED, not failed: an example written with
``...`` or ``<placeholder>`` cannot be judged, and reporting it would be a
false positive.

Usage:
    python scripts/qa/check_doc_snippets.py [--json] [--root DIR]

Exit codes:
    0 - No violations found
    1 - Violations found
"""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import inspect
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR_PARTS: Final[tuple[str, str]] = ("untracked", "qa")
_OUTPUT_FILENAME: Final[str] = "doc_snippets.json"

_SRC_DIR_NAME: Final[str] = "src"
_PACKAGE: Final[str] = "claude_code_hooks_daemon"
_CORE_MODULE: Final[str] = f"{_PACKAGE}.core"

RULE_UNKNOWN_KEYWORD: Final[str] = "unknown-keyword"
RULE_POSITIONAL_ARG: Final[str] = "positional-arg"
RULE_UNKNOWN_IMPORT: Final[str] = "unknown-import"
RULE_MISSING_IDENTIFIER: Final[str] = "missing-identifier"

_FENCE_RE: Final[re.Pattern[str]] = re.compile(
    r"^```(?:python|py)\s*$(?P<body>.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)

_HANDLER_BASE_NAME: Final[str] = "Handler"
_SUPER_NAME: Final[str] = "super"
_INIT_NAME: Final[str] = "__init__"
_SELF_PARAM: Final[str] = "self"
_HANDLER_IDENTIFIERS: Final[tuple[str, str]] = ("handler_id", "name")

_SCANNED_GLOBS: Final[tuple[str, ...]] = (
    "CLAUDE/**/*.md",
    "docs/**/*.md",
    ".claude/*.md",
    ".claude/agents/*.md",
    # Docs under src/ are DEPLOYED into client projects (the hooks-daemon
    # skill, its references, the per-package CLAUDE.md files). A broken
    # example there reaches every install, so this is the highest-impact
    # surface of all — it was missed on the first pass.
    "src/**/*.md",
    "examples/**/*.md",
    "README.md",
    "CONTRIBUTING.md",
)

# Plans and release notes are HISTORICAL RECORDS, not instructions. A snippet
# in a completed plan documents what the code looked like at the time and must
# not be rewritten to match today's source.
_EXCLUDED_PARTS: Final[tuple[str, ...]] = ("Plan", "RELEASES", "UPGRADES", "node_modules")


@dataclass(frozen=True)
class PythonBlock:
    """A fenced ``python`` block and the document line its first line sits on."""

    source: str
    start_line: int


@dataclass(frozen=True)
class Violation:
    """A documented snippet that cannot work against the real source."""

    file: str
    line: int
    rule: str
    symbol: str
    message: str

    def describe(self) -> str:
        return f"{self.file}:{self.line}: [{self.rule}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "symbol": self.symbol,
            "message": self.message,
        }


def extract_python_blocks(text: str) -> list[PythonBlock]:
    """Return every fenced ``python`` block with its true document line."""
    blocks: list[PythonBlock] = []
    for match in _FENCE_RE.finditer(text):
        body = match.group("body")
        # The fence line itself is line N; the first code line is N + 1.
        fence_line = text.count("\n", 0, match.start()) + 1
        blocks.append(PythonBlock(source=body.strip("\n"), start_line=fence_line + 1))
    return blocks


def _ensure_src_on_path() -> None:
    src = _PROJECT_ROOT / _SRC_DIR_NAME
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


@dataclass(frozen=True)
class SymbolSignature:
    """What a documented symbol will actually accept."""

    keywords: tuple[str, ...]
    accepts_positional: bool
    accepts_var_keyword: bool


def _describe_signature(obj: Any) -> SymbolSignature:
    """Describe what ``obj`` accepts.

    Deliberately NOT guarded: every symbol exported from ``core`` is a Python
    class or function, so ``inspect.signature`` always succeeds. Measured — no
    exported symbol fails it. A guard here would swallow the one thing worth
    knowing, namely that the public API grew something uninspectable.
    """
    params = inspect.signature(obj).parameters

    keywords: list[str] = []
    accepts_positional = False
    accepts_var_keyword = False
    for name, param in params.items():
        if name == _SELF_PARAM:
            continue
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            accepts_var_keyword = True
            continue
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            accepts_positional = True
            continue
        keywords.append(name)
        if param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            accepts_positional = True
    return SymbolSignature(
        keywords=tuple(keywords),
        accepts_positional=accepts_positional,
        accepts_var_keyword=accepts_var_keyword,
    )


def _load_core_signatures() -> dict[str, SymbolSignature]:
    """Introspect the public ``core`` API — the symbols documentation teaches."""
    _ensure_src_on_path()
    core = importlib.import_module(_CORE_MODULE)

    signatures: dict[str, SymbolSignature] = {}
    for name in dir(core):
        if name.startswith("_"):
            continue
        obj = getattr(core, name)
        if not (inspect.isclass(obj) or inspect.isfunction(obj)):
            continue
        signatures[name] = _describe_signature(obj)
    return signatures


_SIGNATURES: dict[str, SymbolSignature] | None = None


def core_signatures() -> dict[str, SymbolSignature]:
    """Memoised accessor for the introspected ``core`` signatures."""
    global _SIGNATURES
    if _SIGNATURES is None:
        _SIGNATURES = _load_core_signatures()
    return _SIGNATURES


def _handler_subclass_ranges(tree: ast.Module) -> list[tuple[int, int]]:
    """Line ranges of every class whose bases include ``Handler``."""
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        base_names = {b.id for b in node.bases if isinstance(b, ast.Name)}
        base_names |= {b.attr for b in node.bases if isinstance(b, ast.Attribute)}
        if _HANDLER_BASE_NAME in base_names:
            end = node.end_lineno if node.end_lineno is not None else node.lineno
            ranges.append((node.lineno, end))
    return ranges


def _is_super_init(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == _INIT_NAME
        and isinstance(func.value, ast.Call)
        and isinstance(func.value.func, ast.Name)
        and func.value.func.id == _SUPER_NAME
    )


def _target_symbol(node: ast.Call, handler_ranges: list[tuple[int, int]]) -> str | None:
    """Resolve which documented symbol this call constructs, if any."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if _is_super_init(node):
        inside = any(start <= node.lineno <= end for start, end in handler_ranges)
        return _HANDLER_BASE_NAME if inside else None
    return None


def _check_call(
    node: ast.Call,
    symbol: str,
    signature: SymbolSignature,
    rel_file: str,
    line: int,
    is_handler_super: bool,
) -> list[Violation]:
    found: list[Violation] = []

    def add(rule: str, message: str) -> None:
        found.append(Violation(file=rel_file, line=line, rule=rule, symbol=symbol, message=message))

    # A `*args` unpack does not tell us how many positionals it supplies, and
    # a doc using it is illustrating rather than calling. Only literal
    # positional arguments are decidable.
    literal_positionals = [a for a in node.args if not isinstance(a, ast.Starred)]
    if literal_positionals and not signature.accepts_positional:
        add(
            RULE_POSITIONAL_ARG,
            f"{symbol}(...) takes keyword arguments only; "
            f"a positional argument raises TypeError",
        )

    if not signature.accepts_var_keyword:
        for kw in node.keywords:
            if kw.arg is None or kw.arg in signature.keywords:
                continue
            accepted = ", ".join(signature.keywords)
            add(
                RULE_UNKNOWN_KEYWORD,
                f"{symbol}(...) has no keyword argument '{kw.arg}'. Accepted: {accepted}",
            )

    if is_handler_super:
        supplied = {kw.arg for kw in node.keywords if kw.arg is not None}
        if not supplied.intersection(_HANDLER_IDENTIFIERS) and not node.args:
            add(
                RULE_MISSING_IDENTIFIER,
                "Handler requires handler_id (or the deprecated name alias); "
                "supplying neither raises ValueError",
            )
    return found


def _submodule_exists(parent: Any, package: str, name: str) -> bool:
    """True when ``package.name`` resolves to a real module.

    ``find_spec`` locates without executing, so this is a lookup rather than a
    swallowed import failure. It requires a PACKAGE parent — asking it about a
    child of a plain module raises, so that case short-circuits to False.
    """
    if not hasattr(parent, "__path__"):
        return False
    return importlib.util.find_spec(f"{package}.{name}") is not None


def _check_import(node: ast.ImportFrom, rel_file: str, line: int) -> list[Violation]:
    module = node.module or ""
    if not module.startswith(_PACKAGE):
        return []
    _ensure_src_on_path()
    try:
        imported = importlib.import_module(module)
    except ImportError:
        # The documented MODULE may legitimately not exist in this checkout
        # (a plugin path, a client-side module). Only a missing SYMBOL in a
        # module that does exist is decidable.
        return []
    return [
        Violation(
            file=rel_file,
            line=line,
            rule=RULE_UNKNOWN_IMPORT,
            symbol=alias.name,
            message=f"'{module}' has no attribute or submodule '{alias.name}'",
        )
        for alias in node.names
        if alias.name != "*" and not hasattr(imported, alias.name)
        # `from pkg import submodule` is legal even though the submodule is not
        # an attribute of the package until it has first been imported.
        and not _submodule_exists(imported, module, alias.name)
    ]


def check_snippet(rel_file: str, start_line: int, source: str) -> list[Violation]:
    """Return violations for one snippet. Unparseable snippets yield none."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # An abbreviated example cannot be judged. Reporting it would be a
        # false positive, and a check with false positives gets disabled.
        return []

    signatures = core_signatures()
    handler_ranges = _handler_subclass_ranges(tree)
    violations: list[Violation] = []

    for node in ast.walk(tree):
        node_line = getattr(node, "lineno", None)
        line = start_line if node_line is None else start_line + node_line - 1

        if isinstance(node, ast.ImportFrom):
            violations.extend(_check_import(node, rel_file, line))
            continue

        if not isinstance(node, ast.Call):
            continue
        symbol = _target_symbol(node, handler_ranges)
        if symbol is None or symbol not in signatures:
            continue
        violations.extend(
            _check_call(
                node,
                symbol,
                signatures[symbol],
                rel_file,
                line,
                is_handler_super=_is_super_init(node),
            )
        )
    return violations


def _documents(root: Path) -> list[Path]:
    seen: set[Path] = set()
    for pattern in _SCANNED_GLOBS:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            if any(part in _EXCLUDED_PARTS for part in path.relative_to(root).parts):
                continue
            seen.add(path)
    return sorted(seen)


def scan(root: Path) -> list[Violation]:
    """Scan every in-scope document and return all violations."""
    violations: list[Violation] = []
    for path in _documents(root):
        rel = str(path.relative_to(root))
        text = path.read_text(encoding="utf-8", errors="replace")
        for block in extract_python_blocks(text):
            violations.extend(check_snippet(rel, block.start_line, block.source))
    return violations


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Python snippets in documentation")
    parser.add_argument("--json", action="store_true", help="write a JSON report")
    parser.add_argument("--root", type=Path, default=_PROJECT_ROOT, help="repository root")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root.resolve()
    violations = scan(root)

    if args.json:
        out_dir = root.joinpath(*_QA_OUTPUT_DIR_PARTS)
        out_dir.mkdir(parents=True, exist_ok=True)
        by_rule = {
            rule: sum(1 for v in violations if v.rule == rule)
            for rule in (
                RULE_UNKNOWN_KEYWORD,
                RULE_POSITIONAL_ARG,
                RULE_UNKNOWN_IMPORT,
                RULE_MISSING_IDENTIFIER,
            )
        }
        payload = {
            "tool": "doc_snippets",
            # Shape matches every sibling check. `passed` is REQUIRED:
            # llm_qa._is_passed reads summary["passed"] and defaults it to
            # False, so a report that omits it is shown as a failure with
            # zero violations.
            "summary": {
                "passed": not violations,
                "total_violations": len(violations),
                "by_rule": by_rule,
            },
            "violations": [v.to_dict() for v in violations],
        }
        (out_dir / _OUTPUT_FILENAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if not violations:
        print("✅ Documented snippets: every example matches the real source")
        return 0

    print(f"❌ Documented snippets: {len(violations)} violation(s)")
    for violation in violations:
        print(f"  {violation.describe()}")
    print()
    print("A documented example must be constructible. Correct it against the")
    print("real signature — copy from a shipped caller rather than inventing one.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
