"""Shared helpers for the supervisor plugin tests (Plan 00487).

Plugin worker halves are real files on disk, because the loader's whole job is
to vet and import a file. These helpers write them with the ownership and mode
the loader accepts, and build the idle tick the cascade needs.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from tests.unit.supervise._load import load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

_mod = load_supervisor_module()

PLUGIN_FILE_MODE = 0o600
PLUGIN_DIR_MODE = 0o700
NOW = 50_000.0
OWN_SESSION = "plugin-sess-1"

# A worker half that does nothing, parameterised on its name. `@NAME@` is
# replaced; every other body below is spliced into the class body.
_TEMPLATE = '''
PLUGIN_API = {api}
class Half:
    name = "@NAME@"
    version = "1.2.3"
    def __init__(self, api):
        self.api = api
        self.starts = 0
        self.idles = 0
{body}
def create_worker_half(api):
    return Half(api)
'''

GOOD_BODY = """
    def on_start(self):
        self.starts += 1
    def on_idle(self, tick):
        self.idles += 1
        return None
"""


def plugin_source(name: str, body: str = GOOD_BODY, *, api: object = 1) -> str:
    """Source text of a plugin worker half named ``name`` with ``body`` as its hooks."""
    return _TEMPLATE.format(api=repr(api), body=body).replace("@NAME@", name)


def write_plugin(
    directory: Path, name: str, body: str = GOOD_BODY, *, api: object = 1, source: str | None = None
) -> Path:
    """Write ``<directory>/<name>.py`` with safe ownership/mode and return it."""
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(PLUGIN_DIR_MODE)
    path = directory / f"{name}.py"
    path.write_text(source if source is not None else plugin_source(name, body, api=api))
    path.chmod(PLUGIN_FILE_MODE)
    return path


def spec(name: str, path: Path) -> str:
    """The ``--plugin`` flag value for ``name`` at ``path``."""
    return f"{name}={path}"


def idle_facts(*, now: float = NOW, idle: bool = True, input_line_empty: bool = True) -> object:
    """A TickFacts for a settled session whose input box is empty."""
    return _mod.TickFacts(
        now_wall=now,
        idle=idle,
        input_line_empty=input_line_empty,
        human_compact_submitted=False,
        work_idle=True,
    )


def make_runtime(
    tmp_path: Path,
    names_to_bodies: dict[str, str] | None = None,
    *,
    sessions: frozenset[str] = frozenset({OWN_SESSION}),
    hook_budget: float | None = None,
    tick_budget: float | None = None,
    disabled: frozenset[str] = frozenset(),
) -> object:
    """Load a ``PluginRuntime`` over freshly written plugin files and start it."""
    plugin_dir = tmp_path / "plugins"
    specs = [
        (name, write_plugin(plugin_dir, name, body))
        for name, body in (names_to_bodies or {}).items()
    ]
    kwargs: dict[str, object] = {}
    if hook_budget is not None:
        kwargs["hook_budget_seconds"] = hook_budget
    if tick_budget is not None:
        kwargs["tick_budget_seconds"] = tick_budget
    runtime = _mod.PluginRuntime(
        state_root=tmp_path / "state",
        status_dir=tmp_path / "untracked",
        marker_path=tmp_path / "untracked" / "supervise" / "plugin-in-hook.json",
        session_ids=lambda: sessions,
        allowed_uids=frozenset({os.getuid(), 0}),
        **kwargs,
    )
    runtime.load(specs, disabled)
    runtime.start()
    return runtime
