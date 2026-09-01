# Hooks daemon: handlers that assume a single-project repository

Feedback for the hooks-daemon maintainers. Written from a client install whose
repository layout the daemon does not currently model. All examples below are
abstract — no project detail is reproduced here.

## The repository shape in question

One git repository containing **several sibling application workspaces**, each
independently tooled:

```
<repo root>/            # git root. No package manifest of any kind lives here.
  web/                  # Node/TypeScript workspace
    package.json        #   its own scripts, incl. the llm: wrappers
    <lockfile>
    node_modules/.bin/  #   its linters and type-checker live HERE
    src/  tests/
  service/              # PHP workspace
    composer.json
    <lockfile>
    vendor/bin/         #   its static analyser and test runner live HERE
    src/  tests/
  infra/                # a third toolchain again (config-driven, no manifest)
  <docs, planning dirs, CI config>
```

Three properties matter, and the daemon models none of them:

1. **There is no manifest at the repository root**, and adding one would be a
   bodge — it would exist purely to satisfy a tool, declaring dependencies the
   repository does not have and creating a lockfile nobody installs.
2. **Every toolchain concept is workspace-scoped, not repo-scoped**: the
   manifest, the lockfile, the linter config, the test layout, and — critically
   — the **tool binary directory**.
3. **A file's workspace is derivable from its own path.** Nothing needs
   configuring: walk up from the edited file to the nearest manifest.

## The core defect: there is no shared workspace abstraction

`ProjectContext.project_root()` is the daemon's only notion of "where the
project is", and it returns the **git root**. There is no
`workspace_for(path)`. Consequently each handler that needs sub-repo awareness
has invented its own partial version, and they are mutually incompatible:

| Mechanism                                                  | Where                                     | Notion of "a workspace"                   |
| ---------------------------------------------------------- | ----------------------------------------- | ----------------------------------------- |
| `ProjectContext.project_root()`                            | everywhere                                | the git root, always                      |
| `monorepo_subproject_patterns` + `strip_monorepo_prefix()` | `markdown_organization`                   | configured path prefixes                  |
| `_DEPENDENCY_DIRECTORIES` implicit monorepos               | `markdown_organization`                   | `vendor/*/*`, `node_modules/[@scope/]*`   |
| `workspace_root` constructor arg                           | `validate_eslint_on_write`                | a single scalar, documented "for testing" |
| everything-before-`src/`                                   | `tdd_enforcement`                         | inferred per file path                    |
| `_MODULE_ROOT_MARKERS`                                     | `lint_on_edit`                            | nearest `go.mod` / `ansible.cfg`          |
| `_is_foreign_repo()`                                       | `staged_lint_gate`, `plan_qa_commit_gate` | a *different* git root                    |

Six mechanisms, no shared type, no shared resolution, and only one of them
(`markdown_organization`) is reachable from config. `core/utils.py`'s
`get_workspace_root()` does not help — it is `__file__`-anchored to the daemon's
own installation, not a project concept.

The recurring symptom is not a false denial. It is **silent degradation**: the
handler resolves nothing, falls back to the repo root, finds no manifest and no
tooling, and concludes the project simply doesn't have that thing.

---

## Findings

### 1. `utils/npm.py::has_llm_commands_in_package_json()` — root-only, and it picks a handler's entire mode

The case in point. The whole function is a single-root lookup:

```python
if project_root is None:
    project_root = ProjectContext.project_root()

package_json_path = project_root / "package.json"

if not package_json_path.exists():
    logger.debug("No package.json found at %s", package_json_path)
    return False
```

In the layout above this returns `False` unconditionally — the `llm:` scripts
exist, in `web/package.json`, and this lookup can never see them. The docstring's
"Returns False gracefully for … non-Node.js projects" is exactly the
misclassification: **a monorepo with a Node workspace is indistinguishable, to
this function, from a repository with no Node in it at all.**

Two handlers consume it, and for both the return value is a *mode selector*.

#### 1a. `npm_command` — enforcement silently downgrades to advisory

```python
self.has_llm_commands: bool = has_llm_commands_in_package_json()
```

Evaluated once at construction. `False` means every non-`llm:` npm/npx command
gets an advisory ALLOW instead of a DENY. So on the repository that has actually
gone to the trouble of defining `llm:` wrappers, the handler that exists to
enforce them **does nothing**, and reports nothing about why.

This is worse than a plain miss, because the failure is invisible from the
outside: the handler is enabled, healthy, and permanently inert. Working out
that this was happening required reading the handler source. Nothing in
`status`, `handlers`, or the logs at INFO says "enforcement disabled: no
manifest at root".

Two secondary observations from the same read, both independent of monorepo
support:

- The **piped-command branch denies regardless of mode**, ahead of the advisory
  return. So a repo in "advisory" mode still gets hard denials for
  `npx <tool> … | <cmd>` — including piped `llm:` commands. Worth documenting;
  the mode name implies otherwise.
- `NPX_TOOL_SUGGESTIONS` covers `tsc, eslint, prettier, cspell, playwright, tsx`. A common test runner invoked as `npx <runner>` is not matched at all, so
  the handler's coverage of "raw tool invocations" already has holes unrelated
  to layout.

#### 1b. `validate_eslint_on_write` — half-aware, and internally inconsistent

This handler *does* have a workspace notion, and then declines to use it for the
one call that needs it:

```python
self.workspace_root = (
    Path(workspace_root) if workspace_root else ProjectContext.project_root()
)
self.has_llm_commands: bool = has_llm_commands_in_package_json()   # no argument
```

`self.workspace_root` is honoured for the ESLint subprocess `cwd` and for
prepending `<workspace_root>/node_modules/.bin` to `PATH` — i.e. the handler
already knows that ESLint and its binaries are workspace-scoped. But the mode
detection on the very next line ignores it and reads the repo root.

Passing `self.workspace_root` there is a one-line fix and strictly more correct
even single-root. But it only papers over the real problem, which is that
`workspace_root` is:

- **a single scalar**, so it cannot express "TS files under `web/`, and a second
  TS workspace elsewhere"; and
- **documented `(for testing)`** — a test-isolation seam, not a configuration
  surface. There is no supported way for a project to set it.

### 2. `lint_on_edit` — the linter is installed, and the handler says it isn't

Two independent single-root assumptions compound here.

**Working directory.** Only two languages get a root marker:

```python
_MODULE_ROOT_MARKERS: ClassVar[dict[str, str]] = {
    "Go": "go.mod",
    "Ansible": "ansible.cfg",
}
```

TypeScript and PHP get no marker, so `working_dir` stays `None` and the linter
runs from the daemon's own cwd — where the workspace's linter config, plugin
resolution and path aliases are not visible.

**Executable resolution.** `_resolve_executable` looks in exactly two places:

```python
candidate = _INTERPRETER_BIN_DIR / executable
if candidate.is_file():
    return str(candidate)

return shutil.which(executable)
```

The interpreter's own bin dir (the daemon's venv) and `PATH`. Never
`<workspace>/node_modules/.bin`, never `<workspace>/vendor/bin` — which is where
a Node or PHP project's linters actually are, always, by construction of those
package managers.

**Observed all session, on every PHP edit:**

```
⚠️ PHP lint tool not found (<analyser>) - install to enable lint checking
```

The analyser was installed the whole time, in the PHP workspace's `vendor/bin`.
The guard was inert and the advice was wrong.

The docstring already names this exact failure for Python — "the guard silently
inert, and the advice wrong, because ruff was already installed" — and fixes it
by adding the daemon's *own* venv bin dir. That is the same bug, one workspace
over, and the fix generalises: **look in the edited file's workspace bin
directory too.**

The design note about returning `None` rather than guessing (a missing tool must
never block anyone) is right and should be kept. The problem is not the fallback
behaviour; it is that the search path is too narrow to ever find the tool.

### 3. `tdd_enforcement` — inference is workspace-aware, declaration is not

The mirror inference gets this right, and demonstrates the resolution strategy
already works:

```python
src_idx = path_parts.index(_SRC_DIR)
# Workspace root is everything before src/
workspace_parts = path_parts[:src_idx]
workspace_root = Path(*workspace_parts) if workspace_parts else Path(_DEFAULT_WORKSPACE)
```

Then `test_path_map`, the documented escape hatch for when inference fails, uses
a different model: `test_dir` is **project-root-relative and flat**, resolved via
`resolve_project_root()`. One glob to one directory. It can *name* a path inside
a workspace, so this is the least broken finding — but the two halves of one
handler disagree about what a workspace is, and the config half cannot express
"tests live beside their source, in whichever workspace that is".

Also worth flagging: `_DEFAULT_WORKSPACE = "/workspace"` is a hardcoded absolute
path as a fallback. It happens to be correct in a container that mounts the repo
there, and silently wrong anywhere else.

### 4. `markdown_organization` — the need is recognised, but solved once, locally

This handler has `monorepo_subproject_patterns`, `strip_monorepo_prefix()`, and
treats `vendor/` and `node_modules/` as implicit monorepos with per-package
rules. That is genuinely good, and it is the proof that the requirement is
already understood inside the codebase.

The problem is that it stops there. The abstraction is private to one handler,
expressed as regex prefixes a human must maintain by hand, and duplicates
information that is already on disk (a manifest marks a workspace root; no
config needed). The handler's own `self._workspace_root` remains
`ProjectContext.project_root()`.

### 5. `staged_lint_gate` / `plan_qa_commit_gate` — a sixth notion

`_is_foreign_repo()` compares `GitRepo.resolve_for(cwd).root != project_root`.
This is *nested git repositories*, which is a real and different concern from
workspaces-within-one-repo. Listing it not as a defect but to show the count:
the codebase now has six distinct answers to "which sub-tree am I in", none of
which share a type.

---

## Suggested direction

The fix that generalises is a **shared workspace resolver**, not a per-handler
option. Something like:

```python
Workspace.for_path(file_path) -> Workspace | None
    root: Path            # nearest ancestor containing a manifest
    kind: str             # node | php | python | go | ...
    manifest: Path
    bin_dirs: tuple[Path, ...]   # node_modules/.bin, vendor/bin, .venv/bin
```

Resolution: walk up from the file being acted on to the nearest recognised
manifest (`package.json`, `composer.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`,
…), stopping at the git root. Fall back to the git root, which makes single-root
repositories behave exactly as they do today — **the change is backwards
compatible by construction**, and single-root projects need no config and see no
behaviour change.

Then:

- `has_llm_commands_in_package_json(workspace.root)` — mode decided per
  workspace, evaluated per invocation rather than once at construction.
- `lint_on_edit`: `working_dir = workspace.root`; `_resolve_executable` searches
  `workspace.bin_dirs` before the interpreter venv and `PATH`.
- `validate_eslint_on_write`: derive `workspace_root` per file; keep the
  constructor arg as the test seam it is documented to be.
- `tdd_enforcement`: resolve a relative `test_dir` against the file's workspace,
  falling back to project root for compatibility.
- `markdown_organization`: `monorepo_subproject_patterns` becomes a manual
  override of an otherwise automatic result, not the only way to get one.

### One more thing worth having regardless

A handler whose enforcement has silently downgraded should **say so** —
in `handlers` output, in `check`, or at session start. The most costly part of
this was not that `npm_command` was in the wrong mode; it was that the only way
to discover the mode was to read the handler's source. Any of these would have
saved the trip:

```
npm_command: ADVISORY (no package.json with llm: scripts at <root>)
lint_on_edit: PHP linter unresolved (searched <venv>/bin, PATH)
```

Both facts are already computed. Neither is currently surfaced.
