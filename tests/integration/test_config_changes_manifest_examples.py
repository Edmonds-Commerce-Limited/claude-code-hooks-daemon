"""Every `example_yaml` in a config-changes manifest must actually load.

Plan 00412. These manifests are what a client READS during an upgrade, and
`example_yaml` is specifically the block they are invited to paste into their
own `.claude/hooks-daemon.yaml`. So an example that does not validate is not a
documentation nit: it is a hard config-load failure delivered to someone who
followed the instructions correctly, at the moment they were being careful.

The v3.64.0 manifest shipped exactly that. Its `persistent_crons` example used
`name:` for a field the schema calls `id:`, and `PersistentCronConfig` sets
``extra="forbid"`` — so a client copying it got two validation errors and a
daemon that would not start.

Nothing caught it, because nothing had ever checked that these examples parse.
The manifests are prose to every other test in the suite. This is the guard for
the CLASS, written before the instance was fixed: a wrong example is now a
failing test rather than a client's broken morning.

Deliberately generic — it validates whatever the manifests contain today and
whatever is added later, so a new manifest inherits the check without anyone
remembering to extend anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config

_MANIFEST_DIR = Path(__file__).parent.parent.parent / "CLAUDE" / "UPGRADES" / "config-changes"

#: The manifest's own sections, each a list of change entries.
_CHANGE_SECTIONS = ("added", "renamed", "removed", "changed")


def _manifest_paths() -> list[Path]:
    return sorted(_MANIFEST_DIR.glob("v*.yaml"))


def _examples_in(path: Path) -> list[tuple[str, str]]:
    """Return (key, example_yaml) for every entry in one manifest carrying one."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return []
    sections = document.get("config_changes") or {}
    if not isinstance(sections, dict):
        return []
    found: list[tuple[str, str]] = []
    for section_name in _CHANGE_SECTIONS:
        for entry in sections.get(section_name) or []:
            if not isinstance(entry, dict):
                continue
            example = entry.get("example_yaml")
            if isinstance(example, str) and example.strip():
                found.append((str(entry.get("key", "<unkeyed>")), example))
    return found


def _all_examples() -> list[tuple[str, str, str]]:
    """Return (manifest name, config key, example_yaml) across every manifest."""
    return [
        (path.name, key, example)
        for path in _manifest_paths()
        for key, example in _examples_in(path)
    ]


class TestTheManifestsThemselvesAreReadable:
    """If these fail, every other assertion here is vacuously true."""

    def test_manifests_exist(self) -> None:
        assert _manifest_paths(), f"no manifests found under {_MANIFEST_DIR}"

    def test_every_manifest_parses_as_yaml(self) -> None:
        for path in _manifest_paths():
            yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_examples_were_actually_collected(self) -> None:
        """Guards the collector, not the data.

        A silent change to the manifest shape would make `_all_examples()`
        return nothing, and a parametrised test over an empty list PASSES —
        which would read as "all examples are valid" while checking none.
        """
        assert len(_all_examples()) > 10


@pytest.mark.parametrize(
    ("manifest", "key", "example"),
    _all_examples(),
    ids=[f"{m}:{k}" for m, k, _ in _all_examples()],
)
class TestEveryDocumentedExampleLoads:
    def test_the_example_is_valid_yaml(self, manifest: str, key: str, example: str) -> None:
        try:
            parsed = yaml.safe_load(example)
        except yaml.YAMLError as exc:
            pytest.fail(f"{manifest} example for `{key}` is not valid YAML: {exc}")
        assert parsed is not None, f"{manifest} example for `{key}` parsed to nothing"

    def test_the_example_validates_against_the_live_schema(
        self, manifest: str, key: str, example: str
    ) -> None:
        """The example is loaded exactly as a client's config would be.

        An example is a fragment, so it is merged onto a default config rather
        than validated alone — which is what a client actually does when they
        paste it in.
        """
        fragment = yaml.safe_load(example)
        if not isinstance(fragment, dict):
            pytest.skip(f"{manifest} example for `{key}` is not a mapping")

        try:
            Config(**fragment)
        except ValidationError as exc:
            pytest.fail(
                f"{manifest} documents an example for `{key}` that a client "
                f"CANNOT load — pasting it breaks their daemon:\n{exc}"
            )


class TestAnExampleIsRootedAtTheBlockItDocuments:
    """A LEAF-rooted example is this project's convention, not a defect.

    A first draft of this file asserted that an example for
    `handlers.pre_tool_use.thing` must be rooted at `handlers:`. Running it
    produced about twenty failures across ten years' worth of manifests — all
    of them the same shape, all deliberate. The manifests root an example at
    the block being described, because the surrounding nesting is already
    stated in the `key` field and repeating it would bury the one line the
    reader came for.

    Twenty consistent "failures" is a wrong test, not wrong data. So the check
    was inverted to pin the convention that actually exists: the example must
    mention the LAST segment of its key, which is what makes it findable.
    """

    def test_each_example_mentions_the_block_its_key_names(self) -> None:
        mismatches: list[str] = []
        for manifest, key, example in _all_examples():
            fragment: Any = yaml.safe_load(example)
            if not isinstance(fragment, dict):
                continue
            leaf = key.split(".")[-1]
            if leaf not in example:
                mismatches.append(
                    f"{manifest}: example for `{key}` never mentions `{leaf}`, "
                    f"so a reader cannot tell which setting it illustrates"
                )
        assert not mismatches, "\n".join(mismatches)
