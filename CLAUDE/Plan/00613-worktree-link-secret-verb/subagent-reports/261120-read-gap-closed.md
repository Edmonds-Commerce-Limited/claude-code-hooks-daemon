# Plan 00613: the link-following read gap closed, handoff

Branch `agent-a4419afc45dbc6663-82565567`. Not merged. Follows
[261120-owner-decision-link-route.md](261120-owner-decision-link-route.md).

## Commits

- `c38ac096a`: merge of origin/main (release note 015's Callout title)
- `ddbb9219b`: `utils/link_reach.py` and `Read.follows`. The strict-xfail becomes passing cases, with controls.
- `1b7463876`: `seed-worktree` places a protected link only if the config committed at HEAD lists it.
- `fbcf85eba`: a missing root or a file root holds no link. This fixed 13 regressions from the first commit, such as `cp a b`.
- `4428ba659`: release note renumbered from 016 to 018, and PLAN updated
- `538981972`: HANDLER_REFERENCE, DESIGN, the guard's guidance and its search-deny remedy
- The final commit: the journal entry and this report

## What closed

- **Read gap.** From a worktree, a reader that follows links is now judged on what lies behind each link below its root, and denied exactly as the direct path is. The readers are `grep -R`, `-RnI`, `--dereference-recursive`, `rg -L`, `rg --follow`, `find -L -exec`, `find -exec` on file links, `zip -r`, `diff -r`, `tar`, `cp -rL` and `xargs`.
  - This covers a root above the link, at it, or given as an absolute path.
  - It covers both daemon-root placements: the main checkout and the worktree.
  - It covers directory and file links, and link chains.
- **Controls stay allowed:** `grep -r`, `rg`, `git grep`, the Grep tool at the worktree root, an unrelated file, a sibling with no links, and a link to an unprotected directory.
- **Residual 1, narrowed rather than closed.** A link-mode seed entry is refused unless the config committed at HEAD of the main checkout lists the same entry. This applies to an entry whose source is, holds or links to a path protected by either the working config or the committed config. The refusal comes before anything is placed. An agent that commits the edit still passes.
- **Release note** is now `018-*`. It is free on every local and remote ref; 016 and 017 are taken on other branches. It begins `# Callout:`.

## Security surfaces touched

1. `src/claude_code_hooks_daemon/utils/link_reach.py` (new). It lists the links below a root and judges each target.
   - **Where links come from:** the Plan 00623 link index, verified and in memory, when the root is in the project and the index is complete. Otherwise a bounded walk that does not follow links: 4096 directories, 4096 links, 2 s.
   - A root above the project uses only the index, and fails closed without it.
   - **Directory link:** judged by `find_under`, which fails closed when the target is out of the project.
   - **File link:** judged by `find_under` plus `protecting_pattern_under(link, patterns, project_root)`.
   - **Fails closed (denies) on:** a target it cannot stat, a directory it cannot list, either cap, or the deadline.
   - **Allowed:** a dangling link, a loop, a missing root, a file root.
2. `src/claude_code_hooks_daemon/utils/recursive_search.py`
   - `Read.follows` defaults to ALL.
   - `_search_link_follow` and `_find_link_follow` prove NONE or FILES only from literal options.
   - Any of these proves nothing: an uncertain parse, `RIPGREP_CONFIG_PATH`, `GREP_OPTIONS`, or `()`/`function`/`alias` in the command.
   - Index-view `git grep` is NONE.
   - `protected_reached` calls `reached_through_links`. For a glob read, it is called on the glob's literal directory.
   - Inherited by **both** `secret_file_guard` (`_search_reach`) and `quarantine_artefact_read_guard`.
3. `secret_file_guard.py`: guidance text and the search-deny remedy only. There is no logic change; the Grep tool path (`_directory_reach`) is untouched.
4. `utils/worktree_seed_apply.py`: `_committed_config` (`git show HEAD:.claude/hooks-daemon.ya?ml`) and `_refuse_uncommitted_protected_links`.
5. `utils/worktree_seeding.py`: the public wrapper `protecting_pattern_for_source`.

## Residual risks

- **Environment-only tool config.**
  - The hook cannot see a `RIPGREP_CONFIG_PATH` or `GREP_OPTIONS` that is already in the agent's environment but not named in the command.
  - Such a config can make `rg` or `grep -r` follow links while the guard judges them as NONE.
- **Fail-closed false positives.**
  - In a worktree-root daemon, a following read of a tree holding any directory link out of the worktree is denied (`grep -R`, `zip`, `tar`, `cp`); a seeded `node_modules` link is one example.
  - A following read outside the project that is past the walk cap is denied.
  - A following read is also walked while the link index is unbuilt, and walked every time once it has overflowed.
  - `--exclude-dir` and the hidden rules are ignored for links, which over-approximates.
- **Not judged, the same as on the direct path:** wildcard-only globs (`cat */*`), and hard links.
- **TOCTOU:** a link can be retargeted between the judgement and the run.
- **Residual 1 is only narrowed.**
  - An agent can still commit the config edit.
  - The creation hook still reads the daemon's loaded config, so the edit takes effect after a daemon restart.
- **Still open:** the live-daemon socket check, and Task 3.4 (the peer reply).

## QA (targeted)

- **New and touched tests pass.**
  - `test_link_reach.py`: 31.
  - Seeded-link pin, seed apply, the CLI and the audit tests: all pass.
  - The secret, quarantine and flaggable guard suites, plus `tests/unit/utils/`, were run after the regression fix. The result is in the coordinator reply.
- **Static checks:** ruff, black and mypy `--strict` are clean on the 5 touched sources.
- **Pre-existing on main:** `test_pending_release_notes_holding_area.py` fails on `015-idle-compaction-threshold-advisory.md`, which has no `**Plan**: NNNNN` line. This branch did not cause it.
