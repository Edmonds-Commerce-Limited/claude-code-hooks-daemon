STOPPING BECAUSE: round-3 review complete.

**Verdict: REQUEST CHANGES, for one new false negative.** The fix is small. The rest of round 3 does what was asked.

**Blocking: a protected path stored in a variable before a `cd` is no longer caught (confidence 85).**
- **Where:** `write_protected_paths.py`, `_runs` and `_bash_violation`. When a command contains a `cd`, it is now split into parts and each part is scanned on its own. A variable set in an earlier part is lost by the time a later part uses it.
- **Effect:** the `rm "$F"` part is judged on its own, `$F` cannot be resolved, and the unresolved-token check ignores a final component that is just `$F`.
- **Probed, with `<root>` the project root:**
  - `F=<root>/.claude/ccy/ccy.env.local; cd /tmp; rm $F`
  - `F=… && cd /tmp && rm "$F"`
  - `F=…; cd /tmp && echo x > "$F"`

  All three are now ALLOWED, and all three really delete or overwrite the protected file. Round 1 and round 2 denied them. The command names the protected path directly, which meets your blocking bar.
- **Fix:** before scanning each part, prepend the plain `NAME=value` parts that came before it. Alternatively, pass the whole command's known variables into each part's scan. Add the three commands above as tests.

**Verified fixed:**
- **#1 (bare `.claude` or `ccy` matched):** `_names_chain` now requires the file name, or a folder together with its parent. `$TMPDIR/.claude`, `$SRC/.claude` and `$WORK/ccy` are allowed. `cd .claude && rm -rf ccy` and `cd "$D" && rm -rf ccy` are still denied.
- **#2 (`cd` judged from the original directory):** each part is now judged from the directory it actually runs in. `cd /tmp/otherclone && rm -rf .claude` is allowed, and `cd /tmp && rm -rf .claude/ccy` is allowed (round 1 denied it). Subshells, groups, substitutions and heredocs fall back to judging the whole command from every directory, which can only over-deny, never miss.
- **#4 (`xargs`):** `cp`, `install` and `tee` are dropped, and the check runs per command (cut at `;`, `&&`, `||`), so an unrelated pipeline no longer counts. Both of my false-positive cases now pass, and `xargs rm` / `xargs unlink` are still denied.
- **#7 (stale cache):** only partly fixed, not blocking. The cache is cleared in `handle()`, but that only runs when `matches()` is true, so a cached ALLOW is never cleared. A stale answer needs the same command twice in a row with the files changed outside any hooked call in between, so it is unlikely. Clearing it at the start of `matches()` would close it.

**The unrequested change to how commands are split (`_is_command_boundary`, `core/utils.py:991`):** it cannot change results for existing callers. It is called only from `_is_command_word` and `_parse_command_words`, and both are reached only when `include_mutations=True`. I confirmed this two ways:
- Three fused-punctuation commands, such as `{ cp a b; }&& tee c < d`, give identical results through the default `scan_bash_write_destinations` and `get_bash_write_targets` on the round-1 and round-3 source.
- 3603 tests pass across `tests/unit/core`, project_containment, markdown_organization, evasion triage and the new test files.

**Remaining probe misses, all accepted or deferred:** `perl -i`, `rsync`, `find -delete`, removing a symlink, brace expansion, `flock`, `bash -c`, `/bin/rm`, and a `for` loop over the path.

One small gap was already there in round 1 and is not blocking: `cd .claude 2>/dev/null && rm -rf ccy` is allowed, because a `cd` with a redirect is not followed. It could be added to Phase 1b.

**Probes:**
- `/workspace/untracked/scratch/00499-review-probe.py`
- `/workspace/untracked/scratch/00499-review-probe-r2.py`
- `/workspace/untracked/scratch/00499-review-probe-r3.py`
- Round-1 source used for comparison: `/workspace/untracked/scratch/00499-r1-tree`

**Test output:** `/workspace/untracked/scratch/00499-review-r3-pytest.txt`