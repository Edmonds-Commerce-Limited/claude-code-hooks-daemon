"""Every external action is pinned to a full commit SHA (Plan 00572 Task 4.2).

A tag such as ``actions/checkout@v4`` is a moving pointer: whoever controls the
action's repository can repoint it, and the next CI run executes the new code
with this repository's token. A 40-character commit SHA cannot be repointed.
The trailing ``# vX.Y.Z`` comment names the release the SHA is, which is also
the form Dependabot's github-actions updates keep current.

A local reference (``./.github/...``) is this repository's own code and is not
pinned.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GITHUB = ROOT / ".github"

_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>\S+)(?P<rest>.*)$")
_PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
_VERSION_COMMENT = re.compile(r"^\s+#\s+v\d+\.\d+\.\d+\s*$")


def _workflow_files() -> list[Path]:
    return sorted(p for p in GITHUB.rglob("*") if p.suffix in {".yml", ".yaml"} and p.is_file())


def _external_uses() -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for path in _workflow_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = _USES.match(line)
            if match is None or match["ref"].startswith("./"):
                continue
            found.append((f"{path.relative_to(ROOT)}:{number}", match["ref"], match["rest"]))
    return found


def test_the_scan_finds_external_actions() -> None:
    assert len(_external_uses()) >= 6


@pytest.mark.parametrize(
    ("where", "ref", "rest"), _external_uses(), ids=[w for w, _, _ in _external_uses()]
)
def test_every_external_action_is_pinned_to_a_full_sha(where: str, ref: str, rest: str) -> None:
    assert _PINNED.match(ref), f"{where}: {ref} is not pinned to a 40-character commit SHA"
    assert _VERSION_COMMENT.match(rest), f"{where}: {ref} has no trailing '# vX.Y.Z' comment"


def test_the_pattern_rejects_a_tag_and_accepts_a_sha() -> None:
    assert not _PINNED.match("actions/checkout@v4")
    assert _PINNED.match("actions/checkout@" + "0" * 40)
    assert _PINNED.match("actions/attest-build-provenance@" + "a" * 40)
