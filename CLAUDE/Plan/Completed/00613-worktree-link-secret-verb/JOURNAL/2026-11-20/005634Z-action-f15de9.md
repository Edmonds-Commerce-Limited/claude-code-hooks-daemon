## 00:56 · action · —

Task 2.1 built (ruling Q3): a `mode: copy` seed of a protected source is refused before `git worktree add` runs.

- `validate_seed_sources` now takes a REQUIRED keyword `protected_patterns` (a loader), so no caller can skip the check. It is called once, and only when a copy-mode entry exists: a link-only config behaves as before whatever state the guard config is in.
- The worktree_create handler passes `load_protected_patterns_strict` (new, in the secret-file matching module): reads the daemon config freshly with `Config.load`, no default fallback, no cache. Uninitialised context, missing/malformed/schema-invalid config, or a wrongly typed `mode`/`protected_paths` raises `ProtectedSetUnreadable`, which refuses EVERY copy entry.
- Matching is the guard's own matcher over paths only (spelled + realpath). New `protecting_pattern_under(path, patterns, project_root)` so anchored globs are tried at the seeding root (given and resolved) as well as the daemon root; `protecting_pattern` delegates to it unchanged.
- A directory copy is judged on every path copytree would copy, following symlinks as copytree does; a symlink loop, an unreadable directory or more than 10,000 paths refuses unjudged.
- The refusal names the check (secret_file_guard) and the seed by position (`seed entry #N (mode: copy)`), never its path or the matching glob.
- Decided deliberately: an EMPTY effective set (`mode: replace` with no list) protects nothing, so a copy is allowed; pinned by a test.
- Not changed: `seed_worktree` still assumes a validated list (only caller is the handler, which validates first).

RED commit 9702d82c9 (49 failing), then green. Remaining: Tasks 2.2 (audit line), 2.3 (pin hand-typed ln/cp denial), 2.4 (release note).
