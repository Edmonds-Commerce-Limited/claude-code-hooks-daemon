"""Every `plugins:` example this project ships must validate (Plan 00426).

Issue #44 asked which of two documented `plugins:` schemas was real. The
measured answer was neither: the config template showed a `type`/`class`/
`events` shape that does not parse at all, and the guide plus the basic-setup
example both omitted the REQUIRED `event_type`. Only the daemon's own working
config validated, and nothing documented it.

They drifted because nothing reads them. In both YAML surfaces the block is
COMMENTED OUT, so config validation never sees it -- an example config test can
load the whole file, pass, and say nothing about the one block a user is most
likely to copy.

So these tests read the SHIPPED files and validate what they actually contain.
A test carrying its own copy of the YAML would pass for ever while the real
examples rot, which is precisely the failure that produced the issue.
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import PluginsConfig

_REPO_ROOT = Path(__file__).parent.parent.parent

_YAML_SURFACES = (
    ".claude/hooks-daemon.yaml.example",
    "examples/basic_setup/hooks-daemon.yaml",
)
_MARKDOWN_SURFACES = ("docs/guides/CONFIGURATION.md",)


def _uncomment(lines: list[str]) -> str:
    """Strip one leading comment marker from each line of a commented block."""
    out = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            out.append(line)
            continue
        body = stripped[1:]
        indent = len(line) - len(stripped)
        out.append(" " * indent + (body[1:] if body.startswith(" ") else body))
    return "\n".join(out)


def _commented_blocks(text: str) -> list[str]:
    """Every commented-out `plugins:` block in a YAML surface."""
    lines = text.split("\n")
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].lstrip().startswith("# plugins:"):
            block = [lines[index]]
            index += 1
            while index < len(lines) and lines[index].lstrip().startswith("#"):
                block.append(lines[index])
                index += 1
            blocks.append(_uncomment(block))
            continue
        index += 1
    return blocks


def _fenced_blocks(text: str) -> list[str]:
    """Every fenced yaml block in a markdown surface that defines `plugins:`."""
    blocks: list[str] = []
    current: list[str] | None = None
    for line in text.split("\n"):
        if line.strip().startswith("```yaml"):
            current = []
            continue
        if line.strip().startswith("```") and current is not None:
            body = "\n".join(current)
            if any(row.startswith("plugins:") for row in current):
                blocks.append(body)
            current = None
            continue
        if current is not None:
            current.append(line)
    return blocks


def _plugins_examples() -> list[tuple[str, object]]:
    """(label, parsed plugins block) for every shipped example that defines one.

    A block whose `plugins:` parses to nothing is a skeleton placeholder (the
    `plugins:` line followed by a `# ...` in the config overview), not an
    example of the shape. It claims nothing, so there is nothing to validate.
    """
    found: list[tuple[str, object]] = []
    for relative in _YAML_SURFACES:
        text = (_REPO_ROOT / relative).read_text(encoding="utf-8")
        for number, block in enumerate(_commented_blocks(text), start=1):
            parsed = yaml.safe_load(block)
            if isinstance(parsed, dict) and parsed.get("plugins"):
                found.append((f"{relative} (commented block {number})", parsed["plugins"]))
    for relative in _MARKDOWN_SURFACES:
        text = (_REPO_ROOT / relative).read_text(encoding="utf-8")
        for number, block in enumerate(_fenced_blocks(text), start=1):
            parsed = yaml.safe_load(block)
            if isinstance(parsed, dict) and parsed.get("plugins"):
                found.append((f"{relative} (yaml block {number})", parsed["plugins"]))
    return found


def test_the_shipped_surfaces_are_actually_found() -> None:
    """Guard the guard: an extractor that finds nothing would pass vacuously.

    Without this, a rename or a reformat that breaks extraction turns the whole
    file green while checking nothing -- the same silent-pass shape as the glob
    that missed `hooks-daemon.yaml.example` during this issue's triage.
    """
    assert _plugins_examples(), (
        "no `plugins:` example was extracted from any shipped surface; the "
        "extractor is broken, or the examples moved -- either way these tests "
        "are no longer checking anything"
    )


@pytest.mark.parametrize("label, block", _plugins_examples(), ids=lambda value: str(value)[:60])
def test_a_shipped_plugins_example_validates(label: str, block: object) -> None:
    """A documented example a user copies must load.

    `PluginConfig.event_type` is required and has no default, so an example
    that omits it cannot be pasted into a real config -- which is what made
    both documented shapes unusable.
    """
    try:
        PluginsConfig.model_validate(block)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        )
        pytest.fail(f"{label} does not validate against PluginsConfig -- {problems}")
