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

## The contract

```python
from claude_code_hooks_daemon.core.workspace import Workspace

workspace = Workspace.for_path(edited_file, ProjectContext.project_root())
```

Walk up from the file's own directory to the **nearest** recognised manifest,
stopping at and including the project root. The returned `Workspace` is frozen
and carries four facts:

| Field      | Meaning                                                                        |
| ---------- | ------------------------------------------------------------------------------ |
| `root`     | Directory holding the resolved manifest, or the project root when none found   |
| `kind`     | `node`, `php`, `python`, `go`, `rust`, or `unknown` for the fallback           |
| `manifest` | Absolute path to the manifest that resolved it, or `None` for the fallback     |
| `bin_dirs` | Absolute tool-binary directories, ecosystem order; existence is not guaranteed |

### Manifest precedence

`_MANIFEST_KINDS` is the extension point — one entry per ecosystem, in
precedence order, used only to break ties **within a single directory**:

| Manifest         | Kind     | Bin dirs                |
| ---------------- | -------- | ----------------------- |
| `package.json`   | `node`   | `node_modules/.bin`     |
| `composer.json`  | `php`    | `vendor/bin`            |
| `pyproject.toml` | `python` | `.venv/bin`, `venv/bin` |
| `go.mod`         | `go`     | —                       |
| `Cargo.toml`     | `rust`   | —                       |

Depth beats precedence: a `package.json` two directories up loses to a
`composer.json` in the file's own directory. Nearest always wins.

### Why the fallback is the git root

When no manifest is found the resolver returns the project root with kind
`unknown`. This is what makes adoption safe: **a single-root repository
resolves exactly what `ProjectContext.project_root()` used to return**, so
routing a handler through the resolver is a no-op there and needs no
configuration. Monorepo support is therefore not a mode to switch on.

### Files outside the project root

The project-root stop only applies to files under it. For a file elsewhere on
the filesystem the walk still never ascends past that file's own filesystem
root, and a manifest found on the way up is honoured; failing that, the
project-root fallback applies.

## Configuration: declared, then derived, then root

Resolution has three layers, tried in order:

1. **Declared** — a `projects:` entry in `.claude/hooks-daemon.yaml`.
2. **Derived** — the manifest walk-up described above.
3. **Project root** — the fallback, so a single-project repo needs nothing.

Declaration exists because **derivation cannot see a workspace that has no
manifest**. A config-driven toolchain directory — an Ansible tree, a docs site
with its own `docs/` and `CLAUDE/` — has no `package.json` to walk up to, so
the walk falls through to the repo root and enforcement silently degrades:
exactly the failure this whole mechanism exists to remove.

Declaring projects to the daemon is NOT the same as adding a manifest to the
repository. The latter is a bodge — it would declare dependencies the
repository does not have and create a lockfile nobody installs. A `projects:`
block puts that knowledge in the daemon's own config, where it costs the
repository nothing.

**Declaration is a precedence layer, never a requirement.** Omit `projects:`
and behaviour is exactly the derived-then-root ladder. Making it mandatory
would charge every single-project repo for a monorepo feature, and a stale
list would silently disable enforcement for a workspace nobody remembered to
add — the same silent-degradation class as the original defect.

**To support a new ecosystem's automatic detection, add a row to
`_MANIFEST_KINDS`.** That benefits every consumer at once, and is the right
fix whenever the ecosystem does have a manifest worth recognising.

### The knobs that remain, and what they now mean

These are *not* workspace overrides and are not replaced by the resolver:

- **`markdown_organization.monorepo_subproject_patterns`** — a *documentation
  layout* sub-project, which need not coincide with a manifest (a docs site
  with its own `docs/` and `CLAUDE/` and no `package.json` is a real case).
  This is the same need `projects:` serves, so it becomes a deprecated alias
  for a `projects:` entry rather than a second mechanism.
- **`tdd_enforcement.test_path_map`** — declares where tests for a source glob
  live. Orthogonal to *which* workspace; the resolver only changes what a
  relative `test_dir` is resolved against.
- **`validate_eslint_on_write`'s `workspace_root` constructor argument** — a
  test seam, not user configuration. It is not read from YAML.
- **`layout.source_dirs` and friends** — roles *within* a workspace, a
  different axis entirely.

## Known limits

- **Marker files that are not manifests.** `lint_on_edit` resolves a working
  directory for Go and Ansible via its own `_MODULE_ROOT_MARKERS`. `go.mod` is
  a manifest and resolves normally; `ansible.cfg` is not, so an Ansible tree
  with no other manifest would resolve to the fallback. That handler therefore
  consults its marker FIRST and uses the workspace root only as a fallback —
  the pattern to copy. A consumer needing such a marker either contributes it
  to `_MANIFEST_KINDS` or keeps a supplementary lookup ordered ahead of the
  resolver; it must not silently lose the working directory it had.
- **Nested git repositories are a different concern.** A *different git root*
  (what the commit gates' `_is_foreign_repo()` detects) is not a workspace.
  The resolver never crosses into that question.
- **`bin_dirs` are paths, not promises.** They are constructed, not probed;
  callers check existence. This keeps resolution free of filesystem cost
  beyond the walk itself.

## Adoption

Which handlers currently resolve through this rather than through
`ProjectContext.project_root()` is tracked in
[Plan 00296](../Plan/00296-monorepo-workspace-resolver/PLAN.md), along with the
field report that motivated it. A handler that needs a project — not a git
root — should use this resolver.
