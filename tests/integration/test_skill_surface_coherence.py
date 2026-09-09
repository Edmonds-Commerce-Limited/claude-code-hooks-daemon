"""The release gate for the hooks-daemon skill surface (Plan 00330, Phase 4).

Generalises the dispatchability test from ``8bbd5bec``
(``tests/unit/scripts/test_skill_subcommands_are_dispatchable.py``): that
test pins one direction of one surface — a subcommand the docs tell a human
to type must route. This module pins the rest of the skill's contract with
the daemon behind it, so a release cannot proceed while the two disagree:

1. Every configurable handler is visible to ``optimise`` (Task 4.1) — the
   checklist is derived, and the skill's procedure consumes the derivation
   rather than carrying a handler list of its own.
2. Every CLI verb the skill documents exists in the daemon CLI (Task 4.2).
3. No skill document names a retired capability (Task 4.2).
4. Every config key the skill references is defined by the schema (Task 4.2).

It lives under ``tests/``, so ``./scripts/qa/llm_qa.py all`` — the release
pipeline's blocking Step 8 — runs it on every release (Task 4.3).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import types
import typing
from pathlib import Path
from typing import Any, Final

import pytest
from pydantic import BaseModel

from claude_code_hooks_daemon.config.models import Config, HandlersConfig
from claude_code_hooks_daemon.config_optimisation.checklist import build_checklist
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.constants.handlers import RETIRED_HANDLERS, HandlerID
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.relevance import RelevanceContext
from claude_code_hooks_daemon.handlers.registry import iter_builtin_handler_classes
from claude_code_hooks_daemon.pseudo_events.registry import pseudo_event_handler_classes

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_SKILL_ROOT: Final[Path] = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills" / "hooks-daemon"
)
_OPTIMISE_SCRIPT: Final[Path] = _SKILL_ROOT / "scripts" / "optimise-invoke.sh"
_CLI_SOURCE: Final[Path] = _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "cli.py"

#: The verb the optimise procedure must run to obtain its checklist.
_CHECKLIST_VERB: Final[str] = "optimise-checklist"

#: Global flags that may sit between the wrapper and the verb
#: (``--project-root X``).
_GLOBAL_FLAGS: Final[str] = r"(?:\s+--[a-z-]+(?:\s+[A-Z_./$\"{}-]+)?)*"

#: A CLI verb reference in skill prose or scripts: the wrapper or the skill's
#: own daemon-cli.sh passthrough, anywhere in the text, followed by a literal
#: verb; or the procedure's ``DAEMON_CLI`` placeholder at the START of a
#: line, which is how the procedure writes a command (in prose it is a noun:
#: "replace DAEMON_CLI with the actual path").
_CLI_VERB_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?:bin/hooks-daemon|daemon-cli\.sh\"?)" + _GLOBAL_FLAGS + r"\s+([a-z][a-z-]+)\b"),
    re.compile(r"^\s*\$?\{?DAEMON_CLI\}?" + _GLOBAL_FLAGS + r"\s+([a-z][a-z-]+)\b", re.MULTILINE),
)

#: The routing arms SKILL.md forwards verbatim to the daemon CLI.
_PASSTHROUGH_ARM_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s{4}([a-z|\-]+)\)\s*\n(?:[^\n]*\n){0,4}?[^\n]*daemon-cli\.sh\" \"\$SUBCOMMAND\"",
    re.MULTILINE,
)

_SUBPARSER_RE: Final[re.Pattern[str]] = re.compile(
    r"subparsers\.add_parser\(\s*\"([a-z][a-z-]*)\"", re.MULTILINE
)
#: ``aliases=["validate-config"]`` — an alias routes exactly like the verb.
_ALIAS_RE: Final[re.Pattern[str]] = re.compile(r"aliases=\[([^\]]*)\]")

#: A handler-name segment that is an EXAMPLE, not a reference
#: (``handlers.pre_tool_use.my_handler.priority`` in troubleshooting.md).
_EXAMPLE_HANDLER_RE: Final[re.Pattern[str]] = re.compile(r"^(?:my|your|example|custom)_")

#: A line that names a retired handler AS retired is documentation of the
#: retirement, which is the one legitimate way to mention it.
_RETIREMENT_WORDS_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:retired|removed)\b", re.I)

#: A dotted config path in skill text, rooted at a top-level Config field.
_CONFIG_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w./-])(" + "|".join(re.escape(name) for name in Config.model_fields) + r")"
    r"((?:\.(?:<[a-z_]+>|[a-z_][a-z0-9_]*))+)"
)

_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"^<[a-z_]+>$")
_EVENT_META_KEYS: Final[frozenset[str]] = frozenset({"enable_tags", "disable_tags"})


def _skill_texts() -> list[tuple[Path, str]]:
    files = sorted(_SKILL_ROOT.rglob("*.md")) + sorted(_SKILL_ROOT.rglob("*.sh"))
    return [(path, path.read_text(encoding="utf-8")) for path in files]


def _cli_verbs() -> frozenset[str]:
    source = _CLI_SOURCE.read_text(encoding="utf-8")
    verbs = set(_SUBPARSER_RE.findall(source))
    for alias_list in _ALIAS_RE.findall(source):
        verbs.update(re.findall(r"\"([a-z][a-z-]*)\"", alias_list))
    return frozenset(verbs)


def _handler_config_keys() -> frozenset[str]:
    return frozenset(
        getattr(HandlerID, attr).config_key for attr in dir(HandlerID) if attr.isupper()
    )


# ── 1. Every configurable handler is visible to optimise ────────────────────


class TestOptimiseCoverage:
    @pytest.fixture(autouse=True)
    def _project_context(self) -> None:
        ProjectContext.initialize(_REPO_ROOT / ".claude" / "hooks-daemon.yaml")

    def test_checklist_covers_the_whole_registry(self) -> None:
        """Adding a handler with no skill change cannot hide it from optimise."""
        expected = {
            f"handlers.{ref.event_dir}.{ref.config_key}" for ref in iter_builtin_handler_classes()
        }
        for name, entries in pseudo_event_handler_classes().items():
            expected.update(f"pseudo_events.{name}.handlers.{key}" for key in entries)

        context = RelevanceContext(project_root=_REPO_ROOT, languages=frozenset())
        covered = {item.config_path for item in build_checklist({}, context)}
        assert covered == expected, (
            f"registered but invisible to optimise: {sorted(expected - covered)}; "
            f"scored but not registered: {sorted(covered - expected)}"
        )

    def test_procedure_runs_the_derived_checklist(self) -> None:
        text = _OPTIMISE_SCRIPT.read_text(encoding="utf-8")
        assert _CHECKLIST_VERB in text, (
            f"{_OPTIMISE_SCRIPT.name} no longer runs `{_CHECKLIST_VERB}`, so its "
            "handler coverage is whatever it hardcodes again."
        )

    def test_procedure_carries_no_handler_list(self) -> None:
        """A handler named in the procedure is a handler the derivation is not trusted for."""
        text = _OPTIMISE_SCRIPT.read_text(encoding="utf-8")
        # `plan_workflow` is also a top-level config SECTION the procedure
        # legitimately checks; a handler reference would be dotted under an
        # event, which the check below still catches.
        # A backticked mention is prose ABOUT a handler (Step 7 explains what
        # `config_optimisation_reminder` tracks); a checklist entry is bare.
        section_names = set(Config.model_fields)
        named = sorted(
            key
            for key in _handler_config_keys()
            if key not in section_names and re.search(rf"(?<![\w.`]){key}(?![\w`])", text)
        )
        assert not named, (
            f"{_OPTIMISE_SCRIPT.name} names handlers {named} by hand. The checklist "
            f"is derived by `{_CHECKLIST_VERB}`; a hand-written name is the drift "
            "Plan 00330 removed."
        )


# ── 2. Every documented CLI verb exists ─────────────────────────────────────


def _documented_cli_verbs() -> dict[str, set[str]]:
    """Verb -> the skill files that document it."""
    found: dict[str, set[str]] = {}
    for path, text in _skill_texts():
        # An `echo` line PRINTS prose ("bin/hooks-daemon wrapper not found");
        # it never runs a verb, so it is not a documented invocation.
        invocations = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("echo ")
        )
        for pattern in _CLI_VERB_RES:
            for verb in pattern.findall(invocations):
                found.setdefault(verb, set()).add(path.name)
        for arm in _PASSTHROUGH_ARM_RE.findall(text):
            for verb in arm.split("|"):
                found.setdefault(verb, set()).add(path.name)
    return found


def test_every_documented_cli_verb_exists() -> None:
    verbs = _cli_verbs()
    assert verbs, "no subparsers found in cli.py — the extraction regex is broken"
    missing = {
        verb: sorted(files) for verb, files in _documented_cli_verbs().items() if verb not in verbs
    }
    assert not missing, (
        f"the skill documents CLI verbs the daemon does not define: {missing}. "
        "Add the verb, or stop telling a human to run it."
    )


def test_documented_verb_extraction_sees_known_verbs() -> None:
    """Guard the regex: a silent zero-match would make the test above vacuous."""
    documented = _documented_cli_verbs()
    assert {"restart", "record-config-optimisation-run", _CHECKLIST_VERB} <= set(documented)


# ── 3. No skill document names a retired capability ─────────────────────────


def _names_retired_handler(line: str, name: str) -> bool:
    """A CODE-context mention of ``name`` on a line that does not call it retired.

    Code context is backticks or a dotted ``handlers.<event>.<name>`` path —
    the two shapes a human copies. A bare prose word is not a reference
    (``cleanup`` is a retired handler AND an English word), and a line that
    says the handler is retired is documenting the retirement, which is the
    one legitimate way to name it.
    """
    if _RETIREMENT_WORDS_RE.search(line):
        return False
    escaped = re.escape(name)
    return bool(re.search(rf"`{escaped}`|handlers\.[a-z_]+\.{escaped}\b", line))


def test_no_skill_document_names_a_retired_handler() -> None:
    hits: dict[str, list[str]] = {}
    for path, text in _skill_texts():
        for line in text.splitlines():
            for name in RETIRED_HANDLERS:
                if _names_retired_handler(line, name):
                    hits.setdefault(path.name, []).append(name)
    assert not hits, (
        f"skill documents name retired handlers: {hits}. A human following them "
        "would configure something that no longer exists."
    )


def test_retired_detection_sees_a_code_reference() -> None:
    """Guard the rule: the shapes it must catch, and the one it must not."""
    name = next(iter(RETIRED_HANDLERS))
    assert _names_retired_handler(f"enable `{name}` in your config", name)
    assert _names_retired_handler(f"set handlers.pre_tool_use.{name}.enabled", name)
    assert not _names_retired_handler(f"written by the retired `{name}` handler", name)
    assert not _names_retired_handler(f"logging/{name} is reserved", name)


# ── 4. Every referenced config key is defined by the schema ─────────────────


def _model_of(annotation: Any) -> type[BaseModel] | None:
    """The BaseModel subclass in ``annotation``, unwrapping Optional/Union."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        for arg in typing.get_args(annotation):
            model = _model_of(arg)
            if model is not None:
                return model
    return None


def _is_mapping(annotation: Any) -> bool:
    origin = typing.get_origin(annotation)
    if origin is dict:
        return True
    if origin in (typing.Union, types.UnionType):
        return any(_is_mapping(arg) for arg in typing.get_args(annotation))
    return False


def _path_defined(parts: list[str]) -> bool:
    """Walk ``Config`` along ``parts``; ``<placeholder>`` segments match anything.

    A ``dict``-typed field ends schema knowledge, EXCEPT under
    ``handlers.<event>``, where the next segment must be a live handler key
    (or ``enable_tags``/``disable_tags``): that is precisely the reference
    the schema cannot see and a human copies most.
    """
    model: type[BaseModel] | None = Config
    handler_keys = _handler_config_keys()
    for index, part in enumerate(parts):
        if model is None:
            return True
        if _PLACEHOLDER_RE.match(part):
            field_names = list(model.model_fields)
            if model is HandlersConfig:
                return _after_event(parts[index + 1 :], handler_keys)
            model = (
                _model_of(model.model_fields[field_names[0]].annotation) if field_names else None
            )
            continue
        if part not in model.model_fields:
            return False
        annotation = model.model_fields[part].annotation
        if model is HandlersConfig:
            return _after_event(parts[index + 1 :], handler_keys)
        if _is_mapping(annotation):
            return True
        model = _model_of(annotation)
    return True


def _after_event(rest: list[str], handler_keys: frozenset[str]) -> bool:
    if not rest:
        return True
    head = rest[0]
    return (
        bool(_PLACEHOLDER_RE.match(head))
        or bool(_EXAMPLE_HANDLER_RE.match(head))
        or head in handler_keys
        or head in _EVENT_META_KEYS
    )


def test_every_referenced_config_key_is_defined() -> None:
    undefined: dict[str, set[str]] = {}
    for path, text in _skill_texts():
        for head, tail in _CONFIG_PATH_RE.findall(text):
            dotted = head + tail
            if not _path_defined(dotted.split(".")):
                undefined.setdefault(dotted, set()).add(path.name)
    assert not undefined, (
        f"the skill references config keys the schema does not define: "
        f"{ {k: sorted(v) for k, v in undefined.items()} }"
    )


def test_config_key_extraction_sees_known_keys() -> None:
    """Guard the regex: the skill genuinely references these today."""
    seen = {
        head + tail
        for _path, text in _skill_texts()
        for head, tail in _CONFIG_PATH_RE.findall(text)
    }
    assert "plan_workflow.enabled" in seen
    assert any(key.startswith("handlers.") for key in seen)


# ── 5. The routing block treats its argument as data ────────────────────────


def _routing_block() -> str:
    """Return the shell routing block SKILL.md's Implementation section holds."""
    text = (_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"## Implementation\b.*?```bash\n(.*?)```", text, re.DOTALL)
    assert match is not None, "SKILL.md no longer carries an Implementation bash block"
    return match.group(1)


def _report_arm() -> str:
    """Return just the ``report)`` arm of the routing block."""
    match = re.search(
        r"^    report\)\n(.*?)^        ;;", _routing_block(), re.DOTALL | re.MULTILINE
    )
    assert match is not None, "SKILL.md no longer routes a `report` subcommand"
    return match.group(1)


class TestReportSubcommandArgumentIsData:
    """The description a human types is DATA, never part of a command.

    ``report`` renders ``report.md`` with the user's description substituted
    for its ``$ARGUMENTS`` placeholder. Interpolating that description into a
    stream-editor script instead made every character in it syntax: a ``/``
    terminated the replacement and the remainder was parsed as further editor
    commands — an injection sink shipped to every client, and a break on the
    benign case of a description naming a file path.
    """

    def _run_report(self, tmp_path: Path, description: str) -> subprocess.CompletedProcess[str]:
        """Execute the routing block's ``report`` arm against a copied skill tree."""
        skill_copy = tmp_path / "hooks-daemon"
        shutil.copytree(_SKILL_ROOT, skill_copy)
        # The block derives SKILL_DIR from its own location, so the runner has
        # to sit in the skill directory it should resolve to.
        runner = skill_copy / "routing-block.sh"
        runner.write_text("#!/bin/bash\n" + _routing_block(), encoding="utf-8")
        return subprocess.run(
            ["bash", str(runner), "report", description],
            capture_output=True,
            text=True,
            check=False,
            timeout=Timeout.VALIDATION_CHECK,
        )

    def test_description_is_substituted_for_the_placeholder(self, tmp_path: Path) -> None:
        result = self._run_report(tmp_path, "daemon stopped responding")
        assert result.returncode == 0, result.stderr
        assert "**daemon stopped responding**" in result.stdout
        assert "$ARGUMENTS" not in result.stdout
        # The rest of the prompt still comes through.
        assert "## Instructions" in result.stdout

    def test_a_description_containing_a_path_survives_verbatim(self, tmp_path: Path) -> None:
        """The benign break: slashes are ordinary characters in a description."""
        result = self._run_report(tmp_path, "Write to src/foo/bar.py hangs")
        assert result.returncode == 0, result.stderr
        assert "**Write to src/foo/bar.py hangs**" in result.stdout

    def test_a_command_shaped_description_is_not_executed(self, tmp_path: Path) -> None:
        """The injection shape: substituted literally, so nothing runs."""
        description = "x/;e echo INJECTED_MARKER/"
        result = self._run_report(tmp_path, description)
        assert result.returncode == 0, result.stderr
        assert f"**{description}**" in result.stdout
        # A line that IS the marker would mean the argument reached a shell.
        assert "INJECTED_MARKER" not in result.stdout.splitlines()

    def test_report_arm_runs_no_external_command(self) -> None:
        """No pipeline in the arm: the rendering is pure builtins."""
        assert "|" not in _report_arm(), (
            "The `report` arm pipes into another command again. The user's "
            "description must be substituted literally by the shell, not "
            "handed to a program that parses it."
        )


# ── The frontmatter advertises what the skill can actually do ───────────────


def _frontmatter_value(key: str) -> str:
    """One scalar key from SKILL.md's YAML frontmatter."""
    text = (_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.MULTILINE)
    assert match is not None, f"SKILL.md frontmatter has no '{key}'"
    return match.group(1).strip().strip('"')


class TestTheDescriptionAdvertisesEverySubcommand:
    """Plan 00364 Task 2.9.

    ``description`` is what the model reads when deciding whether this skill
    answers a request, and it listed seven of the eight subcommands
    ``argument-hint`` names. The omitted one was ``optimise`` -- so a request
    to tune the daemon's configuration matched nothing, for a skill built to
    serve it.
    """

    def test_every_argument_hint_subcommand_appears_in_the_description(self) -> None:
        hint = _frontmatter_value("argument-hint")
        subcommands = re.findall(r"[a-z][a-z-]+", hint.split("]")[0])
        description = _frontmatter_value("description").lower()

        missing = [name for name in subcommands if name not in description]
        assert not missing, f"SKILL.md description omits: {missing}"

    def test_optimise_is_one_of_them(self) -> None:
        """The specific omission, pinned so it cannot come back unnoticed."""
        assert "optimise" in _frontmatter_value("description").lower()


class TestCopyPasteBlocksAreCopyPasteable:
    """A command a human is told to type must not carry ``"$@"``.

    Plan 00364 Task 2.9. Typed into an interactive shell, ``"$@"`` expands to
    that SHELL's own positional parameters -- normally empty -- so the
    command silently does something different from what the reader was
    shown. A placeholder says what to put there instead.

    Scoped to the reference documents, NOT to ``SKILL.md``: its blocks are
    the routing script's own body, executed with arguments the skill runner
    passes, where forwarding ``"$@"`` is exactly right.
    """

    def _reference_docs(self) -> list[Path]:
        return [path for path in sorted(_SKILL_ROOT.rglob("*.md")) if path.name != "SKILL.md"]

    def test_the_reference_docs_are_being_scanned(self) -> None:
        """The scan below must never silently collapse to an empty list."""
        names = {path.name for path in self._reference_docs()}
        assert "dev-handlers.md" in names

    def test_no_reference_doc_tells_a_human_to_type_the_positional_expansion(self) -> None:
        offenders: list[str] = []
        for path in self._reference_docs():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if '"$@"' in line:
                    offenders.append(f"{path.relative_to(_SKILL_ROOT)}:{number}: {line.strip()}")
        assert not offenders, (
            "Use an angle-bracket placeholder instead, e.g. "
            "`<the arguments you were given>`:\n" + "\n".join(offenders)
        )

    def test_the_replacement_still_passes_arguments_through(self) -> None:
        """Dropping ``"$@"`` must not drop the ARGUMENTS.

        ``init-handlers.sh`` reads them, and
        ``tests/unit/scripts/test_skill_scripts_are_referenced.py`` requires
        every invocation of such a script to forward something. An
        angle-bracket placeholder is what satisfies both rules: it tells the
        reader to substitute, and it is not a live expansion.
        """
        text = (_SKILL_ROOT / "dev-handlers.md").read_text(encoding="utf-8")
        invocations = [line for line in text.splitlines() if "init-handlers.sh" in line]
        assert invocations
        assert all("<" in line for line in invocations), invocations
