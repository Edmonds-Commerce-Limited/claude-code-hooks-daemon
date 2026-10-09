STOPPING BECAUSE: round-2 review complete.

**Verdict: REQUEST CHANGES.** All four round-1 findings are fixed for the right reason, but the new name and `cd` matching denies ordinary commands. The fix is small.

On the round-1 probe (`/workspace/untracked/scratch/00499-review-probe.py`) every case now passes except the gaps you accepted (`perl -i`, `rsync`, `find -delete`, symlink `rm`). 544 targeted tests pass.

- **#1 bare `*`:** fixed. Wildcards are now matched one path component at a time, and a leading dot is honoured. `rm -rf *` in the root and `rm -f *` elsewhere are allowed; `cd .claude/ccy && rm -rf *` and `rm -rf .*` in the root are denied.
- **#2 position-blind verbs:** fixed. Verbs count only where a command starts or after a listed wrapper, and only when `include_mutations` is set.
- **#3 coverage:** fixed. `touch`, `unlink`, `cd .claude && rm -rf ccy` and `xargs rm` are all denied now.
- **#4 wildcard-glob false positives:** fixed for `.env` / `.envrc`.

New probe: `/workspace/untracked/scratch/00499-review-probe-r2.py`. I also ran it against an archive of the round-1 source (`untracked/scratch/00499-r1-tree`) to separate new regressions from old behaviour.

**Blocking**

1. **New false positive: any directory named `.claude` or `ccy` now counts as the protected file** (80). `write_protected_paths.py`: `_names_segment`, used by `_token_naming` (expansion branch) and `_protecting_by_name`.
   - The name-only fallback now matches every component of the glob. So any unresolved token, or any path in a command containing `$(` or a backtick, that ends in `.claude` or `ccy` is denied.
   - Denied now, allowed in round 1: `rm -rf "$TMPDIR/.claude"`, `cp -r "$SRC/.claude" "$DEST/.claude"`, `rm -rf "$WORK/ccy"`, `rm -rf /tmp/x/.claude && echo $(date)`.
   - Making a temp project and removing its `.claude` is routine in this repository.
   - Fix: in name-only mode, match the file name, or a directory only with at least its parent component (`…/.claude/ccy`). Never match the glob's first component on its own.
2. **Old false positive, now built into the design: a followed `cd` is still judged from the original directory** (75). `_bases` and `_bash_violation` judge every relative path from every directory the command visits, regardless of order. `cd /tmp/otherclone && rm -rf .claude` (or `.claude/ccy`) is denied because the path is also resolved from the project root.
   - Fix: give each command segment the directory in effect at that point, and judge a relative path only from that directory.

**Non-blocking (file as plan tasks)**

3. **New false negative: wrappers missing from the list** (70). `core/utils.py`, `_WRAPPER_COMMANDS`. `flock /tmp/l cp /tmp/x .claude/ccy/ccy.env.local` was denied in round 1 and is now allowed. `chronic`, `unbuffer`, `fakeroot` and `strace` behave the same way.
   - Fix: invert the rule. Treat a verb as an argument only after a known reading command (`grep`, `rg`, `echo`, `printf`, `man`, `which`, `type`, and `git` other than `rm`/`mv`), so an unknown wrapper fails closed.
4. **New false positive: the `xargs` text check is too loose** (70). `_XARGS_MUTATION_RE` and `_bash_violation`.
   - `ls <protected> | xargs -I{} cp {} /tmp/backup` is denied; copying the file away is a read.
   - `cat <protected>; find /tmp -name '*.log' | xargs rm` is denied; the name is in a different pipeline.
   - Fix: drop `cp`, `install` and `tee` from the regex, and require the name to appear in the same pipeline as the `xargs`.
5. **Old false negative: brace expansion** (70). `rm -f .claude/ccy/ccy.env.{local,bak}` and `touch .claude/ccy/ccy.env.{local,dist}` are allowed. This was already true in round 1, because `{…}` is resolved as a literal path. Fix: expand simple comma braces before matching.
6. **Old false negatives** (60): `bash -c 'rm <protected>'` and `/bin/rm <protected>` are allowed. Either scan `bash -c` / `sh -c` bodies and compare `rm`'s base name, or list both as known gaps in the guidance.
7. **The `_last` cache can return a stale answer** (55). It is never cleared, so an identical later command gets the earlier answer even if the filesystem has changed since. Clear it in `handle()`.

Everything from the round-2 run is in `/workspace/untracked/scratch/00499-review-r2-pytest.txt`.