# Callout: a read-only scratch sweep, with a TTL per untracked directory

**Plan**: 00627
**Audience**: everyone

`hooks-daemon scratch-sweep` judges every entry under `untracked/scratch/` (LIVE, STUCK, REPOSITORY, DISPOSABLE or UNCERTAIN) and changes nothing: it is a report only in this release. How long an entry may sit before it is due is set per directory under `untracked/` by the new `scratch.untracked_ttl` map (`scratch: 24h` and `repos: "*"` by default; `"*"` means never cleared, and must be quoted in YAML). `untracked/repos`, every reference-repository root and the archive store are never swept whatever the map says, and a directory the map does not name is never swept unless you set `scratch.untracked_default_ttl`.
