# N130 / N348: capped tree scan, implementation

**Author**: implementation sub-agent (Sonnet), branch `worktree-n130-walk`, from main c2f1a3cd5.
**Design**: [261004-n130-n348-capped-walk-design-opus.md](261004-n130-n348-capped-walk-design-opus.md), with the coordinator
defaults O1 to O5 (module-constant caps, the Grep tool keeps the ALL view, past-cap is a deny, the quarantine guard
fails closed under its own rule, no index).

## What changed

- New `utils/protected_tree_scan.py`: `TreeView` (`ALL`, `UNIGNORED`, `TRACKED`), `find_protected_in_tree(...)` and
  `TREE_SCAN_MAX_ENTRIES = 250_000`. It returns None only after examining the whole view; otherwise it raises
  `TooManyToEnumerateError` (`tree_walk=True`, new attribute) past the cap or `TimeoutError` past the deadline.
  - `ALL`: iterative `os.scandir`, symlinked directories not followed, every entry counted (directories included),
    the deadline read every 1024 entries and on the first, `literal_screen` before `first_matching_glob`.
  - `TRACKED`: `git ls-files -z --cached`, no truncation (closes the `_tracked_protected` 5000 cut). Outside a work
    tree the answer is None, as `git grep` cannot read there either; a git timeout raises.
  - `UNIGNORED`: `git ls-files -z -co --exclude-standard`. Falls back to the `ALL` walk for an ignored root or one under
    a hidden directory of its repository (`rg x node_modules` reads it), and to a walk that excuses git-ignored hits
    (`check-ignore`) outside a repository, on a git failure, and for each nested repository or submodule entry.
    Skip hooks apply component by component to listed paths.
- Callers: `secret_file_guard` Grep branch (creates a deadline) and `_search_reach` (forwards the Bash deadline),
  `recursive_search.protected_reached_by_search` (new `deadline`; `_Read` carries a `TreeView`: `git grep` is
  `TRACKED`, `git grep --no-index/--untracked` is `ALL`, `rg`/`ag` with ignore handling `UNIGNORED`, the rest `ALL`),
  and `quarantine_artefact_read_guard` (Grep and Bash, with a deadline). `_tracked_protected` and `_also_git_ignored`
  moved into the new module.
- `secret_file_matching`: `_expand_glob_token` screens before the matcher; `_MAX_BARE_GLOB_FS_EXPANSIONS` 5000 to
  100_000; `directory_contains_protected` and the old walk are gone from it (see below); `SCAN_COULD_NOT_FINISH` is
  replaced by the shared `scan_incomplete_detail`, which both guards use, so the deny reason says what ran out
  ("a recursive search reads more than N entries" with the `rg` / `--exclude-dir` / narrower-root remedy) and never
  echoes exception text. `DIRECTORY_SCAN_MAX_ENTRIES` stays for `secret_file_hygiene_checker`'s non-git fallback, which
  already reports truncation and is not on the hook path.
- Rules: `R-SECRET-SCAN-INCOMPLETE` now also covers the tree walk and the git listing. New
  `R-QUARANTINE-SCAN-INCOMPLETE` (`RuleID.QUARANTINE_SCAN_INCOMPLETE`, a third `Rule` in
  `quarantine_artefact_read_guard.get_rules()`, the same verbose-first ladder through a shared `_deny_with_ladder`).
  A past-cap or past-deadline call in that guard no longer lands on the evaluation-error rule or the finding rule.
- Guidance: the "best-effort partial enforcement", "capped, so a very large tree is not fully checked" and "NOT
  covered: a Bash recursive content search" wording is removed from the code comments and from
  `secret_file_guard.get_claude_md()`; the recursion paragraph now says a tree too large to examine is denied.
- Release note `017-recursive-searches-are-never-judged-clean-unfinished.md` (Audience: everyone); note 013's
  last sentence (the 5000-file cap) updated. CHANGELOG.md untouched. N130 (TRIAGE-carried-b.md), N348 (NIGGLES.md) and
  the 00483 Task 3.1 bullet updated; journal entry through `mkplan.bash --journal`.

## Deviations from the brief

1. `directory_contains_protected` is not in `secret_file_matching` any more. It lives in `protected_tree_scan` (a thin
   `ALL`-view wrapper, never None for an incomplete scan), because the new module imports `secret_file_matching` and a
   wrapper in the other direction would be a circular import. After migration it has no hook-path caller; it is kept
   per the brief, with its three tests. `secret_file_hygiene_checker` does not use it (it uses only the constant).
2. The three corpus rows cannot reproduce the design's fixtures (a past-cap tree, an ignored protected file, a tracked
   protected file past position 5000): a row runs against the checkout. The generated-tree equivalents are unit tests.
   The rows added hold what a checkout can show: `rg needle src` and `git grep needle -- src` stay allowed
   (UNCOVERED-accepted), and `grep -r needle .` stays denied (COVERED; here by `flaggable_content_channel_guard`, whose
   fixture directory lies under the root, and on a very large checkout also by the secret guard as incomplete).
3. `max_entries` defaults to None and is resolved at call time, so tests can patch `TREE_SCAN_MAX_ENTRIES`.
4. The scan module's tests were written before the module but never run red (the first run was after the module
   existed); the guard-level and caller tests were written after the code and were green on their first run. The old
   behaviour they replace (`directory_contains_protected` returned None at the cap) was not re-run against them.

## Tests

New: `tests/unit/utils/test_protected_tree_scan.py` (38: N130 regression with 5500 files plus a deep protected file,
patched-small-cap raise, deadline raise through a monotonic stub, screened-vs-unscreened agreement including a pattern
with no literal run, TRACKED position-6000 hole, UNIGNORED cases for ignored / hidden / nested repository / non
repository / explicitly named ignored and hidden roots, the entry-count seam proving a 400-file ignored directory is not
visited under a cap of 100, git timeout raising), `tests/unit/handlers/pre_tool_use/test_secret_file_guard_tree_scan.py`
(guard-level denies as incomplete for Grep and Bash, the old-cap regression through the guard, `git grep` past position
6000, a 20000-path bare glob allowed, `rg x .` with a big ignored directory allowed, deadline forwarding), additions to
`test_recursive_search.py` (view per tool, shared scan, cap raise, `rg x .` allowed / `grep -r` raising, `git grep`
past 6000) and `test_quarantine_artefact_read_guard.py` (incomplete rule via Grep and Bash, finding keeps its rule,
deadline forwarded, timeout). Removed: the five `directory_contains_protected` tests from `test_secret_file_matching.py`
(moved and rewritten in the new file).

## Measurements

Guard classes run from this worktree's code with the project root and cwd `/workspace`, read-only
(`untracked/scratch/n130_measure.py`; one warm run, times are `matches()` plus `handle()`):

| Command                                 | Verdict                           | Time    |
| --------------------------------------- | --------------------------------- | ------- |
| `rg x`                                  | ALLOW                             | 0.13 s  |
| `rg x .`                                | ALLOW                             | 0.12 s  |
| `git grep x`                            | ALLOW                             | 0.04 s  |
| `grep -r x .`                           | DENY, `R-SECRET-READ` (a finding) | 0.05 s  |
| `grep -r x src`                         | ALLOW                             | 0.01 s  |
| `ls */*/*`                              | ALLOW                             | 0.03 s  |
| `ls */*/*/*`                            | DENY, `R-SECRET-BASH-MENTION`     | 0.07 s  |
| Grep tool, `path=/workspace/src`        | ALLOW                             | 0.005 s |
| `grep -r x untracked/worktrees` (extra) | ALLOW                             | 0.07 s  |
| `rg x untracked/worktrees` (extra)      | ALLOW                             | 0.33 s  |

`rg x` and `rg x .` are allowed because git's listing has about 5000 entries, where the old behaviour reached its
allow only through the N130 hole. `grep -r x .` is denied as a real finding: the depth-first walk reaches the gitignored
protected file under `untracked/` long before the cap, so the 1.8M-entry checkout is not what ends it (a clean tree that
large would end as `R-SECRET-SCAN-INCOMPLETE`). `ls */*/*/*` genuinely reaches a protected path (design F5), so it is a
finding, not a cap deny.

## Open

- `CLAUDE.md`'s generated rule table does not yet list `R-QUARANTINE-SCAN-INCOMPLETE`; it regenerates on a daemon
  restart, which this task does not do.
- Not done, by default O5: no cached index.
