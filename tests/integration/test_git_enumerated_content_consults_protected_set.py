"""git-enumerated CONTENT must be filtered through the protected set (Plan 00412).

Class 9, `daemon-as-reader-skips-the-protected-set`: the daemon obtains file
content from a path set it did not choose, and never asks whether a path in that
set is protected. D-SEC's framing is the load-bearing one and survives here: the
boundary is drawn at BEHAVIOUR, not purpose. Every member is itself a security
guard, and each was skipped by the audit that closed the sibling seams precisely
because it was classified as a guard rather than as a reader.

`secret_file_guard` is not bypassed by these routes -- it is *not on the path*.
It keys on a path appearing in a tool call, and `git commit -m "wip"` names no
path at all.

The two instances, both confirmed by reading the code that runs:

* `handlers/pre_tool_use/sensitive_content.py` -- `_staged_added_lines` runs
  `git diff --unified=0` over the index and yields the added lines of every
  staged file. The only exclusions applied when selecting those paths are the
  configured `exclude_paths` and the word-list file itself. A protected file
  reached the index via `git add -A`, which names no path, so nothing earlier
  objected; its added lines are then materialised into a handler instance that
  lives for the whole daemon process. If any configured public pattern matches,
  `Matched: <bytes>` becomes the deny reason -- the guard emits the protected
  bytes in its own denial, while reporting that it protected something. The read
  and the retention are unconditional; only the echo needs a matching pattern.

* `scripts/qa/check_sensitive_content.py` -- enumerates with `git ls-files` and
  reads every tracked file, echoing `match.group(0)` to stdout and into a JSON
  artefact that `llm_qa.py` publishes for an agent to read as fact.

**What the rule actually pins, which is not what it looks like.** Nine modules in
the scanned tree invoke a content-bearing git subcommand. Seven of them are safe,
and each is safe for a STRUCTURAL reason this scanner reproduces rather than
assumes: `--name-only` / `--name-status` (`merge_scope`, `staged_lint_gate`,
`remote_docs_commit_gate`) and `ls-files` with no content read
(`worktree_seed_suggestions`, `secret_file_hygiene_checker`) obtain names and
never bytes; `--error-unmatch` (`generated_doc_hand_edit`) is a membership test
on a path the module already chose; and `git show HEAD:./<name>`
(`claude_md_injector`) names its own project-owned file.

So the member set today is exactly the two offenders, and a guard that fired on
nothing else could be mistaken for one that merely restates them. It is not.
**The classifier is the load-bearing part**: nothing in the codebase currently
records that `merge_scope` is safe only because of its `--name-only`. Delete that
one flag and the module silently starts handing diff bodies to a caller with no
protected-path check anywhere in it. This rule is a tripwire on that boundary,
not a census of known defects.

**What it does not catch.** It reasons per call site about flags that are
LITERALS. `sensitive_content` builds one of its two diff invocations as a list
assigned to a name and splatted (`run_git(repo_root, *args)`), which this
resolves; an argument list built by a function call, a conditional, or a
comprehension is invisible, and such a call reads as having no flags at all --
which fails SAFE here (it counts as content) but would misreport the reason. It
also says nothing about a module that reads a path set obtained any way other
than from git, which is the larger arm of D-SEC's original hypothesis and needs
taint tracking this deliberately shallow AST subset does not do.

`F-HYG-3` is NOT an instance of this class, though the worklist groups it here.
`staged_lint_gate.py:249` does consult `path_is_protected` and uses the answer to
`continue` -- and its comment gives the reason, that a lint diagnostic can quote
the offending source line verbatim (Plan 00272). Skipping is the
disclosure-correct behaviour. The F-HYG-3 argument is that it should DENY the
commit instead, which is a policy question about unlinted protected files, not a
guard leaking protected bytes.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final, NamedTuple

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: The trees where a module may reach repository content through git.
_SCANNED_ROOTS: Final[tuple[Path, ...]] = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon",
    _REPO_ROOT / "scripts" / "qa",
)

#: git subcommands that ENUMERATE a file set the caller did not name. `show` and
#: `cat-file` are deliberately absent: both take an explicit path, so the caller
#: chose it and there is no set to be surprised by.
_ENUMERATING: Final[frozenset[str]] = frozenset({"diff", "grep", "ls-files"})

#: Subcommands whose own output is content rather than a list of names.
_CONTENT_BEARING: Final[frozenset[str]] = frozenset({"diff", "grep"})

#: Flags that reduce a call to names, or to a test about one named path.
_NAMES_ONLY_FLAGS: Final[frozenset[str]] = frozenset(
    {"--name-only", "--name-status", "--error-unmatch"}
)

#: Any reference to one of these means the module consults the protected set.
_PROTECTED_HELPERS: Final[tuple[str, ...]] = (
    "path_is_protected",
    "resolve_configured_patterns",
    "secret_file_matching",
)

#: Ways a module obtains bytes from a path it enumerated.
_CONTENT_READS: Final[frozenset[str]] = frozenset({"read_text", "read_bytes"})


class _Violation(NamedTuple):
    """A module reaching git-enumerated content with no protected-path check."""

    relative_path: str
    line: int
    subcommand: str

    def __str__(self) -> str:
        return f"{self.relative_path}:{self.line} — git {self.subcommand}"


def _constant_strings(elements: list[ast.expr]) -> list[str]:
    """The string constants among ``elements``, narrowed at the point of use.

    Filtering here rather than at the end keeps the declared `list[str]` honest:
    `ast.Constant.value` is untyped, so collecting first and filtering later
    type-checks as a list of anything.
    """
    return [
        element.value
        for element in elements
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    ]


def _list_literals(tree: ast.Module) -> dict[str, list[str]]:
    """Names bound to a list/tuple of string constants, for splatted argv."""
    bound: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.List | ast.Tuple)):
            continue
        strings = _constant_strings(node.value.elts)
        for target in node.targets:
            if isinstance(target, ast.Name):
                bound[target.id] = strings
    return bound


def _call_strings(call: ast.Call, literals: dict[str, list[str]]) -> list[str]:
    """Every string argument of ``call``, resolving splatted list literals."""
    strings: list[str] = []
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            strings.append(arg.value)
        elif isinstance(arg, ast.List | ast.Tuple):
            strings += _constant_strings(arg.elts)
        elif isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Name):
            strings += literals.get(arg.value.id, [])
    return strings


def _is_git_call(call: ast.Call, strings: list[str]) -> bool:
    """A call that runs git, whether through ``run_git`` or a raw subprocess."""
    func = call.func
    if isinstance(func, ast.Name) and func.id == "run_git":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "run_git":
        return True
    return "git" in strings


def _reads_file_content(tree: ast.Module) -> bool:
    """Whether the module ever turns a path into bytes."""
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _CONTENT_READS
        for node in ast.walk(tree)
    )


def _content_enumerating_calls(tree: ast.Module) -> list[tuple[int, str]]:
    """Call sites that obtain CONTENT from a git-enumerated file set."""
    literals = _list_literals(tree)
    reads_content = _reads_file_content(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        strings = _call_strings(node, literals)
        if not _is_git_call(node, strings):
            continue
        if any(flag in strings for flag in _NAMES_ONLY_FLAGS):
            continue
        for subcommand in sorted(set(strings) & _ENUMERATING):
            # `ls-files` yields names; it only reaches content when the module
            # goes on to read what it enumerated.
            if subcommand not in _CONTENT_BEARING and not reads_content:
                continue
            found.append((node.lineno, subcommand))
    return found


def _violations(roots: tuple[Path, ...]) -> list[_Violation]:
    """Every module that reaches git-enumerated content unprotected."""
    found: list[_Violation] = []
    for root in roots:
        if not root.is_dir():
            continue
        for module in sorted(root.rglob("*.py")):
            text = module.read_text(encoding="utf-8")
            if any(helper in text for helper in _PROTECTED_HELPERS):
                continue
            tree = ast.parse(text, filename=str(module))
            # Repository-relative when the scan is the real one; root-relative
            # when a test points it at a temporary directory instead.
            anchor = _REPO_ROOT if module.is_relative_to(_REPO_ROOT) else root
            relative = module.relative_to(anchor).as_posix()
            found += [
                _Violation(relative, line, subcommand)
                for line, subcommand in _content_enumerating_calls(tree)
            ]
    return found


class TestGitEnumeratedContentIsProtectedPathAware:
    """The guard."""

    def test_no_module_reads_git_enumerated_content_unprotected(self) -> None:
        violations = _violations(_SCANNED_ROOTS)

        assert violations == [], (
            "These call sites obtain file CONTENT from a path set git chose — "
            "whatever the user staged, or whatever is tracked — and their module "
            "never asks whether a path in that set is protected:\n\n  "
            + "\n  ".join(str(violation) for violation in violations)
            + "\n\nFix: filter the enumerated paths through "
            "`secret_file_matching.path_is_protected(path, "
            "resolve_configured_patterns())` before the content is read, "
            "mirroring staged_lint_gate.py:249."
        )


class TestTheScannerIsNotVacuous:
    """An empty-list assertion is what a BROKEN scanner also produces."""

    def _scan(self, tmp_path: Path, source: str) -> list[str]:
        (tmp_path / "offender.py").write_text(source, encoding="utf-8")
        return [f"{v.line}:{v.subcommand}" for v in _violations((tmp_path,))]

    def test_a_staged_diff_body_is_caught(self, tmp_path: Path) -> None:
        source = 'result = run_git(root, "diff", "--cached", "--unified=0")\n'

        assert self._scan(tmp_path, source) == ["1:diff"]

    def test_a_splatted_argument_list_is_resolved(self, tmp_path: Path) -> None:
        """sensitive_content builds one of its two diff calls exactly this way."""
        source = 'args = ["diff", "--unified=0"]\nresult = run_git(root, *args)\n'

        assert self._scan(tmp_path, source) == ["2:diff"]

    def test_ls_files_plus_a_content_read_is_caught(self, tmp_path: Path) -> None:
        source = (
            'out = subprocess.run(["git", "-C", root, "ls-files", "-z"])\n'
            "body = path.read_text(encoding='utf-8')\n"
        )

        assert self._scan(tmp_path, source) == ["1:ls-files"]

    def test_name_only_is_not_flagged(self, tmp_path: Path) -> None:
        """merge_scope, staged_lint_gate and remote_docs_commit_gate are safe here."""
        source = 'result = run_git(root, "diff", "--name-only", "ORIG_HEAD", "HEAD")\n'

        assert self._scan(tmp_path, source) == []

    def test_error_unmatch_is_not_flagged(self, tmp_path: Path) -> None:
        """A membership test on a path the module already named."""
        source = 'r = run_git(root, "ls-files", "--error-unmatch", "--", rel_path)\n'

        assert self._scan(tmp_path, source) == []

    def test_ls_files_without_a_content_read_is_not_flagged(self, tmp_path: Path) -> None:
        """`ls-files` yields names; with no read, no content was ever obtained."""
        source = 'result = run_git(root, "ls-files", *flags)\n'

        assert self._scan(tmp_path, source) == []

    def test_git_show_of_a_chosen_path_is_not_flagged(self, tmp_path: Path) -> None:
        """claude_md_injector names its own project-owned file."""
        source = 'show = run_git(cwd, "show", f"HEAD:./{filename}")\n'

        assert self._scan(tmp_path, source) == []

    def test_consulting_the_protected_set_clears_a_module(self, tmp_path: Path) -> None:
        source = (
            'result = run_git(root, "diff", "--unified=0")\n'
            "if sfm.path_is_protected(p, sfm.resolve_configured_patterns()):\n"
            "    continue\n"
        )

        assert self._scan(tmp_path, source) == []
