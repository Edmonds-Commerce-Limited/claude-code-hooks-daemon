# Review 614b fixes (R1 to R5, P1)

Branch `agent-a13d7c8504105d4c9-aeae03b4`. It started at 62629e103. Every commit is pushed; nothing is merged. The tests were written first. A red commit lands before each fix, except the R3 red tests, which went into the R1/R2 fix commit (still ahead of the R3 fix).

| Commit    | Content                                                   |
| --------- | --------------------------------------------------------- |
| 109e7894e | RED: R1/R2, a resolution failure must deny, property test |
| 1128215c0 | R1, R2, P1 fix (+ the R3 red tests)                       |
| 50655d51f | R3 fix                                                    |
| 4714f6631 | RED: R4, R5                                               |
| 7d0c8499f | R5 fix                                                    |
| 2b53259f0 | R4 fix, release note 089                                  |
| 6dcbe439f | RED: R4 follow-up                                         |
| (next)    | R4 follow-up fix                                          |

R4 follow-up came from a self-review of 2b53259f0. That commit had two fail-open paths and one unbounded cost:

- An assignment segment skipped the walk of its value. `x="$(env -C inner cat ilink)"` was allowed, where 62629e103 denied it.
- A literal substitution replaced the fail-closed path. A reassignment the walk cannot read (`export D=$(...)`, `declare -x`, `read`, `for D in`, `A=1 D=x`) left the stale value in place.
- Glob expansion used `Path.glob`, which treats `**` as recursive and has no work bound.

The fixes:

- The value is now walked.
- Substitution is additive: `indeterminate()` is still applied.
- Glob expansion is component-wise (`expand_directory_glob`). `**` is read as `*`, and every listing or probe counts toward a 512 cap. Past the cap the target is judged like a computed one. Measured on `/workspace`: `cd */*/*/*/nope` costs 11 ms, `cd /*/*/*/nope` 17 ms.
- A wrapper before a chdir command (`sudo tar -C`, `nice git -C`, `timeout 5 git -C`, `nohup env -C`) is now walked.

The tests are in `tests/unit/handlers/pre_tool_use/test_secret_file_guard_cwd_fail_closed.py` and `tests/unit/utils/test_resolution_failure.py`. The fixture is synthetic: it has directory links only, plus one in-project dummy.

## What changed

- **R1/R2.** Probes on user-supplied words now go through `path_is_dir` with an explicit answer for an unreadable path. This covers the cwd walk (`_add`, `change`, `_list_directory`) and the index (`_wildcard_links`, `link_out_of`, `_matching_symlinked_directories`). A path that cannot be encoded gets its realpath from `find_under` lexically.
- **Structural (R1/R2).** A new module, `utils/resolution_failure.py`, provides `fails_closed` and `ResolutionFailedError`.
  - It wraps `effective_cwds`, `_link_targets`, `CwdSet.could_be_link`, `ProtectedFileIndex.glob_matches`, `link_out_of`, `directories_matching` and `recursive_search.search_reads`.
  - The guard turns `ResolutionFailedError` into a DENY, in the first scan and in the literal fallback. The deny says the paths could not be worked out.
  - Deadline and size-cap errors pass through unchanged, so their advisory routes stand.
  - `find_under` is untouched, so its advisory pin (`test_a_directory_walk_exception`) still holds.
  - `find_protected_mention_strict` now judges every spelling before any filesystem call.
- **P1, fixed.** `recursive_search._place`: `~+` is the cwd, `~-` cannot be placed, and an unknown user stays literal (as bash leaves it).
  - Found while doing this: a failed cd (to a name that is not a directory) kept no directory in the search tracker. So `cd X 2>/dev/null; grep -r . own` was allowed whenever X did not exist. The base is now kept.
- **R3.** Both cd trackers now read past `builtin`, `command [-p]` and a redirection. That covers a redirection before the command, between `cd` and its operand, with or without a descriptor; a number before a redirection is also a candidate target. The chdir options are one table: `env -C`, `git -C`, `tar -C/--directory`, `sudo -D/--chdir`. In `shell_segmentation`, `sudo`'s value flags gained `-D/--chdir/-R/--chroot/-C/-T/-U/-r/-t`, so `sudo -D d grep` finds grep.
- **R5.** `glob_matches` and `link_out_of` now check whether each base a relative glob is placed from leads out of the project.
- **R4.**
  - A globbed target is expanded on disk.
  - A literal assignment in the same command is substituted: `D=x; cd "$D"`, and also `export`, `local`, `declare`, `readonly` and `typeset`.
  - Any other computed target adds the project root plus every project directory holding a link. These are found by `link_holding_directories`: breadth first, at most 512 directories, `.git` skipped, links not followed, an unlistable directory counted, result reused for 5 s. Both trackers use it, and the docstring is corrected.

## Verification

- Secret-guard, recursive-search, index, segmentation and wrapper suites: 5085 passed, 11 skipped.
- Targeted QA (magic_values, lint, type_check, error_hiding, eacces_safe, fail_open_inventory, authored_path_stat, british_english, inline_suppressions): all green on the R1/R2 tree. The final-tree run is recorded in the reply.
- Reviewer harness `rv614b/probe_min.py` over `cases*.json`, full and `MINFIX=1`:
  - no `allow` that LEAKS;
  - no `RAISED`;
  - no command denied by the old tip or main that is now allowed in either fixture.

## Residuals (not fixed)

- A failed `cd` keeps the base after `&&` too. So `mkdir -p b && cd b && grep -r x .` is judged over the starting directory as well. This can over-deny; narrowing it to `;`/`||` needs the separator, which the search tracker does not carry.
- A wrapper before `env -C` in the recursive-search tracker (`nice env -C d grep -r x l`) is not peeled; only the word walker handles it.
- `tar -chf - <dirlink>` (with or without `-C`) is allowed. tar is not a recursive reader to the guard: a separate class, which predates this plan.
- From a computed `cd`, a link deeper than the 512-directory scan is not judged. The scan logs at INFO when it stops early, the project root is still read, and nothing is loosened.
- Overflow mode now applies to a computed `cd` too. When a computed `cd` makes more than 16 link-holding directories exist, a relative word that names a link in any of them is denied. Example: `.venv/bin/python3` beside `cd "$(...)"` in a tree with many venvs. That is a possible false positive.
