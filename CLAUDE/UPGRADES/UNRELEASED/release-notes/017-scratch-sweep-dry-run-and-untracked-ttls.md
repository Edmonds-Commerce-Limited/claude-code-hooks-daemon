# Callout: a read-only scratch sweep, with a TTL per untracked directory

**Plan**: 00627
**Audience**: everyone

`hooks-daemon scratch-sweep` judges every entry under `untracked/scratch/` (LIVE, STUCK, PROTECTED, DISPOSABLE or UNCERTAIN) and changes nothing: it is a report only in this release. A repository inside an entry is classified: a registered worktree, or a related clone with unpushed, stashed or dirty work, makes the entry PROTECTED; a standalone repository is ordinary content. `--root` accepts only a directory inside the project's `untracked/` that is not inside a repository. How long an entry may sit before it is due is set per directory under `untracked/` by the new `scratch.untracked_ttl` map (`scratch: 24h` and `repos: "*"` by default; `"*"` means never cleared, and must be quoted in YAML). `untracked/repos`, every reference-repository root and the archive store are never swept whatever the map says, and a directory the map does not name is never swept unless you set `scratch.untracked_default_ttl`.
