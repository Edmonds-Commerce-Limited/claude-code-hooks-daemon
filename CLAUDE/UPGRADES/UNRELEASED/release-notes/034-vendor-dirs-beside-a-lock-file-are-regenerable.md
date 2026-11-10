# Callout: dependency directories beside a lock file no longer block worktree removal

**Plan**: 00594
**Audience**: client projects

Removing a merged branch's worktree was refused when it held a package
manager's install directories (`vendor/`, `node_modules/` and similar),
particularly ones nested several levels below the repository root beside
their manifest. They can be rebuilt, but a root-level name list could not
describe them.

An ignored directory now counts as regenerable when it sits beside a
manifest and lock file that are both committed at that location:

| Manifest         | Lock file                                          | Directory                                                                           |
| ---------------- | -------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `composer.json`  | `composer.lock`                                    | `vendor/`, `vendor/bin/` (or the manifest's `config.vendor-dir` / `config.bin-dir`) |
| `package.json`   | `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml` | `node_modules/`                                                                     |
| `Gemfile`        | `Gemfile.lock`                                     | `vendor/bundle/`                                                                    |
| `Cargo.toml`     | `Cargo.lock`                                       | `target/`                                                                           |
| `pyproject.toml` | `uv.lock`, `poetry.lock`                           | `.venv/`                                                                            |

Only ignored, untracked content qualifies: a directory holding a committed
file, an unignored file, or no committed lock file still blocks, and
`untracked/scratch/` is never regenerable. The configurable list
`branches.cleanup_after_merge.regenerable` is unchanged and additive.
