"""The shipped JSON Schemas for the daemon's machine-read ``--json`` output (Plan 00601).

The schemas live in ``claude_code_hooks_daemon/schemas/`` (package data, so a
wheel install carries them). They describe the CLI output, never the layout of
the files under ``untracked/``, which stays internal.

Versioning is semver over the output contract. Every document carries
``schema_version``; a consumer pins the major (``SCHEMA_MAJOR``) and refuses an
unknown one. A new optional field is a minor bump; removing or retyping a field
is a new major. Each schema's ``$id`` ends in ``<name>/<SCHEMA_VERSION>.json``.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from referencing import Registry

#: The contract version stamped into every ``--json`` document.
SCHEMA_VERSION: Final[str] = "1.0.0"

#: The major a consumer pins; the schemas accept only this major.
SCHEMA_MAJOR: Final[int] = int(SCHEMA_VERSION.split(".", maxsplit=1)[0])

SCHEMA_MODE_HISTORY: Final[str] = "mode-history"
SCHEMA_SESSION_STATE: Final[str] = "session-state"
SCHEMA_SESSION_STATE_WATCH: Final[str] = "session-state-watch"

SCHEMA_NAMES: Final[tuple[str, ...]] = (
    SCHEMA_MODE_HISTORY,
    SCHEMA_SESSION_STATE,
    SCHEMA_SESSION_STATE_WATCH,
)

KEY_SCHEMA_VERSION: Final[str] = "schema_version"

_PACKAGE: Final[str] = "claude_code_hooks_daemon"
_SCHEMA_DIR: Final[str] = "schemas"


@cache
def _load(name: str) -> str:
    return (resources.files(_PACKAGE) / _SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8")


def load_schema(name: str) -> dict[str, Any]:
    """The shipped schema called ``name``.

    Raises:
        ValueError: ``name`` is not one of ``SCHEMA_NAMES``.
    """
    if name not in SCHEMA_NAMES:
        raise ValueError(f"unknown schema {name!r}; expected one of {', '.join(SCHEMA_NAMES)}")
    document: dict[str, Any] = json.loads(_load(name))
    return document


def schema_registry() -> Registry[Any]:
    """A registry resolving every shipped schema by its ``$id`` (for cross-schema ``$ref``).

    ``referencing`` ships with ``jsonschema`` 4.18 and later, the version the
    lock file resolves; it is imported here so the daemon's runtime never needs it.
    """
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    registry: Registry[Any] = Registry()
    for name in SCHEMA_NAMES:
        schema = load_schema(name)
        registry = registry.with_resource(
            schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012)
        )
    return registry
