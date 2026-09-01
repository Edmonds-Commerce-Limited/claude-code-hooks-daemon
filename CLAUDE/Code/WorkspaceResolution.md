# Workspace Resolution — which sub-tree is this file in?

**This file is the canonical home for workspace resolution**: how a handler
answers "which project sub-tree does the file I am acting on belong to", and
where its toolchain lives. `Workspace.for_path()` in
`src/claude_code_hooks_daemon/core/workspace.py` is the single implementation.

## The problem it solves

A handler that needs a *project* — to read a manifest, to pick a working
directory, to find a linter binary — historically reached for
`ProjectContext.project_root()`, which answers a different question: where the
**git root** is. In a single-project repository those coincide, so the
substitution is invisible. In a repository holding several sibling workspaces,
each with its own manifest, lockfile and tool binaries, they do not.

The failure mode is **silent degradation, not an error**. A handler resolves
nothing at the git root, concludes the project "doesn't have" that toolchain,
and quietly stops enforcing — the guard is inert and nobody is told. That is
strictly worse than a loud failure, because the repository looks protected.

## Projects are declared, never inferred

The fix is **not** to make the daemon work the boundaries out for itself.
Inferring them would reintroduce the very failure being fixed, one level up: a
wrongly-inferred boundary leaves enforcement looking healthy while pointing at
the wrong tree, and nothing says so. The original defect was never "enforcement
was off" — it was "enforcement was off and the only way to find out was to read
the handler source".

So resolution has exactly two layers:

1. **Declared** — a `projects:` entry in `.claude/hooks-daemon.yaml`.
2. **Project root** — when nothing is declared. This is a single-project
   repository's behaviour, unchanged.

A repository that looks like a monorepo but declares nothing keeps today's
behaviour and gets a **loud advisory** naming the workspaces found and the
config block to paste. It does not get a guess. See
[Detection advises, never decides](#detection-advises-never-decides).

## The contract

```python
from claude_code_hooks_daemon.core.workspace import Workspace

workspace = Workspace.for_path(edited_file, ProjectContext.project_root())
```

The returned `Workspace` is frozen and carries four facts:

| Field      | Meaning                                                                        |
| ---------- | ------------------------------------------------------------------------------ |
| `root`     | The declared project's root, or the project root when nothing is declared      |
| `kind`     | `node`, `php`, `python`, `go`, `rust`, or `unknown`                            |
| `manifest` | Absolute path to the manifest found at `root`, or `None` when there is none    |
| `bin_dirs` | Absolute tool-binary directories, ecosystem order; existence is not guaranteed |

## Declaring projects

```yaml
# Omitted entirely == one project at the repo root == today's behaviour.
projects:
  - name: web
    root: "{REPO_ROOT}/web"
  - name: service
    root: service
  - name: infra
    root: infra
    kind: ansible # no manifest here at all — declaration is the ONLY way
    bin_dirs: [.venv/bin]
```

`root` is the only required field beside `name`. The nearest declared root
containing the file wins when two nest.

**Every configured path is repository-root-relative — zero absolute paths.**
`root` and every `bin_dirs` entry are validated: absolute paths, `~`, and
`..` escapes are all rejected. A repository is mounted at different places on
different machines — a container bind mount, a desktop checkout, CI — so an
absolute path in committed config is correct on exactly one of them and
silently wrong everywhere else.

**Path notation: `{REPO_ROOT}`.** Documented path examples across this repo
use the literal token `{REPO_ROOT}` to mean "the repository root" (owner
ruling, Plan 00302 extension) — e.g. `{REPO_ROOT}/web`. In config it is
optional sugar accepted anywhere a repository-relative path is:
`normalise_repo_relative_path` (`utils/repo_relative_path.py`) strips a
leading `{REPO_ROOT}/` before validating, so `{REPO_ROOT}/web` and `web` declare the
same thing, and a bare relative path stays valid without it. On the handful
of fields EXEMPT from the repo-relative-only rule (a plugin path,
`project_handlers.path`) it is the portable alternative to a genuine
absolute path: `expand_repo_root_token` resolves it against the project root
at load time, while a leading `/` still means a deliberate, machine-specific
override. The token is valid only as the very first path segment —
`{REPO_ROOT}` alone means the repository root itself, `{REPO_ROOT}/../x`
still escapes and is rejected, and the token appearing anywhere else in the
string is a validation error.

**A declared project need not contain a manifest.** That is the case
declaration exists for: a config-driven toolchain directory, or a docs site
with its own `docs/` and `CLAUDE/` and no `package.json`, is a real project
with nothing to detect.

Declaring projects to the daemon is NOT the same as adding a manifest to the
repository. The latter is a bodge — it would declare dependencies the
repository does not have and create a lockfile nobody installs. A `projects:`
block puts that knowledge in the daemon's own config, where it costs the
repository nothing.

### Convention inside a declared boundary

`kind` and `bin_dirs` are optional because they can be filled in by convention
once the boundary is known: a declared root containing a `package.json` is
`node` with `node_modules/.bin`. This is not inference about *where a project
is* — the user drew that line — only about what an ecosystem conventionally
looks like inside it. Both fields can be stated explicitly to override.

| Manifest at root | Kind     | Bin dirs                |
| ---------------- | -------- | ----------------------- |
| `package.json`   | `node`   | `node_modules/.bin`     |
| `composer.json`  | `php`    | `vendor/bin`            |
| `pyproject.toml` | `python` | `.venv/bin`, `venv/bin` |
| `go.mod`         | `go`     | —                       |
| `Cargo.toml`     | `rust`   | —                       |

## Detection advises, never decides

The same manifest walk that could resolve a workspace is used instead to
**detect** one: manifests below the repo root with none at it is the signature
of an unconfigured monorepo. When that shape is seen, the daemon reports the
workspaces it found and prints the `projects:` block to paste.

That report changes no enforcement decision. Detection informs a human; config
decides behaviour. Keeping the two apart is the whole point — a detector that
quietly became a resolver would put the daemon back to guessing.

### The other config surfaces, and what they now mean

- **`markdown_organization.monorepo_subproject_patterns`** — **removed**
  outright (Plan 00300 hard cutover). This was the same need `projects:`
  serves, so keeping it as a second mechanism doubled the maintenance surface
  for no gain. `projects:` is now the ONLY sub-project resolution mechanism;
  the option's presence in config is a hard startup error whose message
  prints the equivalent `projects:` block. There is no fallback and no
  override — staying on an older daemon version is the backward-compat path.
- **`tdd_enforcement.test_path_map`** — declares where tests for a source glob
  live. Orthogonal to *which* project; a relative `test_dir` anchors against
  the source file's declared WORKSPACE ONLY (Plan 00300 hard cutover removed
  the extra project-root-anchored candidate — a single anchoring semantics
  everywhere, unchanged in a single-project repo since the workspace IS the
  repo root there).
- **`validate_eslint_on_write`'s `workspace_root` constructor argument** — a
  test seam, not user configuration. It is not read from YAML.
- **`layout.source_dirs` and friends** — roles *within* a project, a
  different axis entirely, but now (Plan 00300) DECLARED PER PROJECT: the
  top-level `layout:` block is the ROOT project's own layout, not a global
  fallback, and a declared `projects:` entry may carry its own `layout:`
  block that governs only its own root. A declared project without one uses
  built-in defaults for its OWN root -- it never inherits the root project's
  declared lists, same declared-not-inferred philosophy as `root`/`kind`.
  `ProjectRegistry.layout_for(path)` resolves the OWNING project's layout for
  one file; `ProjectRegistry.iter_layouts()`/`all_source_dirs()` are the DRY
  aggregation primitives for a handler that needs the union across every
  project. Zero-config (no `projects:` declared) is unaffected: every path
  resolves to the root project, so `layout_for()` always returns
  `root_layout`, built from the top-level `layout:` block exactly as before.

## REPO-level vs PROJECT-level handlers

Plan 00301 left an open caveat: several `ProjectLayout` consumers were never
rewired to per-project resolution, deferred as "not a design gap, just
follow-on work". Sorting which ones NEED rewiring requires a name for the
axis a handler's concern sits on — this section is that name, made
machine-readable via `Handler.workspace_scope`
(`claude_code_hooks_daemon.core.handler.WorkspaceScope`).

**REPO** — the concern is repository-singular: there is exactly ONE of it
per repository, declared `projects:` sub-trees notwithstanding. Examples: the
plan tree (`plan_workflow`, `goal_injection`, `recovery_cron_advisor` — a
repo has one `CLAUDE/Plan/`, never a per-project one), the documentation
corpus taken as a WHOLE (`docs_qa_sweep` — a single sweep, single index),
git metadata, session/cron state. A REPO-scoped handler must NOT consume
per-project layout/workspace resolution (`_project_registry.layout_for`/
`resolve_workspace`) for its core concern — doing so would resolve a
question that has only one right answer per repository, per file, which is
not what per-project resolution is for.

**PROJECT** — the concern belongs to a file's OWNING project: toolchains,
manifests, source/test/config directory roles. A PROJECT-scoped handler MUST
resolve via the injected `ProjectRegistry` helpers
(`resolve_workspace`/`resolve_layout`/`layout_for`/`iter_layouts`/
`all_source_dirs`), never `ProjectContext.project_root()`, for a
project-shaped question — see "The problem it solves" above for what goes
wrong when it does.

**The axis is about the CONCERN, not about whether the handler happens to
process one file at a time.** `british_english` matches per Write/Edit call
(one file), yet is REPO-scoped: `ProjectLayout.for_project` always sources
`agent_docs_dir`/`human_docs_dir` from the ROOT project's
`documentation.trees` config, even when composing a declared sub-project's
layout (there is no per-project override for doc-tree names — see the table
above). Per-file resolution there would be a no-op that only looks
project-aware. Conversely, `worktree_file_copy` judges a Bash COMMAND that
can name paths under ANY declared project's source/test/config dirs — no
single file to resolve an owning project for — so it is PROJECT-scoped but
consumes the AGGREGATE across every project (`iter_layouts`), not a single
`layout_for(file)` answer.

**Declaring it**: override the class attribute, defaulted to `REPO` (the
neutral value — a handler that never touches project layout/workspace
resolution is correctly REPO-scoped by doing nothing):

```python
from claude_code_hooks_daemon.core.handler import WorkspaceScope

class MyHandler(PreToolUseHandlerBase):
    workspace_scope: ClassVar[WorkspaceScope] = WorkspaceScope.PROJECT
```

This is deliberately lightweight — a declaration plus a pinning test per
handler (`tests/unit/core/test_handler_workspace_scope.py`), not a new
enforcement regime. Nothing reads `workspace_scope` at runtime yet; it exists
so a reviewer (human or agent) can answer "which axis does this handler
resolve on?" without reading the handler's source, and so a new handler
picks a scope deliberately instead of copy-pasting whichever pattern was
nearest.

## Known limits

- **Marker files that are not manifests.** `lint_on_edit` resolves a working
  directory for Go and Ansible via its own `_MODULE_ROOT_MARKERS`, consulted
  BEFORE the project root. That ordering is the pattern to copy: a consumer
  with a language-specific marker must not lose the working directory it had.
- **Nested git repositories are a different concern.** A *different git root*
  (what the commit gates' `_is_foreign_repo()` detects) is not a project.
  Resolution never crosses into that question.
- **`bin_dirs` are paths, not promises.** They are constructed, not probed;
  callers check existence, keeping resolution free of filesystem cost.
- **A project nobody declared is invisible.** By design — the daemon reports
  the shape and waits rather than acting on a guess. The cost is that an
  unconfigured monorepo stays degraded until someone reads the advisory, which
  is the trade accepted in exchange for never enforcing against the wrong tree.

## Adoption

Which handlers currently resolve through `Workspace` rather than through
`ProjectContext.project_root()` is tracked in
[Plan 00296](../Plan/Completed/00296-monorepo-workspace-resolver/PLAN.md), along with the
field report that motivated it. A handler that needs a project — not a git
root — should use `Workspace.for_path()`.
