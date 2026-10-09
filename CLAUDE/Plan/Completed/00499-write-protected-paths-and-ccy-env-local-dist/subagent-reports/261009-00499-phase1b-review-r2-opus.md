# Plan 00499 Phase 1b review, round 2 (opus)

Branch `agent-a46aaf37c1a16d458-6185c9b3`, tip 731019d7a (main merged in). Worktree untouched. Scope: the coordinator's
round-1 ruling under the careless-not-hostile threat model; out-of-scope shapes are not re-raised.

**Verdict: REQUEST CHANGES.** Counts: 0 BLOCKER, 4 SHOULD-FIX, 5 NIT.

Every in-scope round-1 fix holds through the real handler (table below), B1 is gone (linear to 20 KB), main's QA is clean
and the targeted tests pass. The four SHOULD-FIX items are small: one in-scope xargs shape that regressed from round 1,
and three false positives on ordinary commands that the new S3/S6/S2 code introduced.

Probes: `/workspace/untracked/scratch/00499-review-1b-probe.py` (round-1 batch, output `00499-r2-probe.out`),
`00499-review-1b-probe3.py -f 00499-r2-inscope.txt` / `-f 00499-r2-reads.txt` / `-f 00499-review-1b-reads3.txt`,
`00499-review-1b-scaling.py` (output `00499-r2-scaling.out`), `00499-r2-profile.py`. Worktree src confirmed imported.

## SHOULD-FIX

### S1. `xargs` fed by a here-string is not read (regression from round 1, in-scope S2)

`xargs rm <<< P`, `xargs -I{} rm {} <<< P` and `xargs -0 bash -c 'rm "$0"' <<< P` are ALLOWED. The last was DENIED in
round 1 (the removed `_XARGS_MUTATION_RE` text check caught it). `_xargs_violation`
(`handlers/pre_tool_use/write_protected_paths.py`, the loop over `commands` with `other.group != command.group`) only
looks at OTHER commands in the pipeline for the producer, so input carried on the xargs command itself (`<<< WORD`,
`< FILE`) is never judged. `echo P | xargs rm` and `xargs rm < <(echo P)` are denied.
**Fix:** when the inner command does not only read, also judge the xargs command's own here-string word (and an input
redirect's target, by name) with `_wide_naming`. Red test: the three shapes.

### S2. A `read` loop that reads the file and writes elsewhere is denied (new false positive, from the S3 fix)

DENIED, all reads of P:

- `while read -r l; do echo "$l" >> /tmp/out; done < P`
- `while IFS='=' read -r k v; do printf '%s\n' "$k" > /tmp/keys; done < P`
- `grep -v '^#' P | while read -r l; do echo "$l" >> /tmp/out; done`

`_read_loop_violation` counts any reader with an output redirect and a `$` operand as a mutator, then judges every word
of the text, so the loop's INPUT (the protected file) becomes the denial. Here the `$var` is content, and the write
target is a literal `/tmp` path. **Fix:** count a mutator only when the `$var` is in a file position: an operand of a
non-reader (`rm "$f"`), or the target of an output redirect (`> "$f"`). A reader whose redirect target is literal is
not a mutator of the loop variable. Keep `ls dir/* | while read f; do rm "$f"` denied.

### S3. Copying the file's directory OUT is denied (new false positive, from the S6 fix)

`cp -r .claude/ccy /tmp/ccy-copy` and `cp -a .claude/ccy/. /tmp/ccy-copy` are DENIED; both only read the directory.
`_tree_copy_violation` runs `_protecting_parent` over every non-option operand, sources included.
**Fix:** judge only the destination: the last file operand, or the `-t`/`--target-directory` value. Red test: both
shapes allowed, `cp -r /tmp/dir/. .claude/ccy` still denied.

### S4. `find . -name '*.pyc' | xargs rm -f` is denied while `find . -name '*.pyc' -delete` is allowed

A routine cleanup run from the project root. `_xargs_violation` judges the producer's words with `_wide_naming`, so
`.` (the root, a directory above the file) names it, and the `-name` filter that `_find_violation` honours via
`_could_select` is ignored. `grep -rl foo . | xargs sed -i ...` being denied is defensible; the find form is not.
**Fix:** when the producer is `find`, reuse `_find_violation`'s name-filter test (no `-path`/`-regex`, and no `-name`
that `_could_select` the listed name, means allow). Red test: the `*.pyc` and `__pycache__` forms allowed, the
`-name 'ccy.env.*'` form denied.

## NIT

- **N1.** The parent-directory rule for unknown verbs also denies `tree .claude/ccy`, `ruff check .claude/ccy` and
  `docker build -t ccy .claude/ccy` (the ccy Dockerfile lives there). Add `tree` to `READ_ONLY_VERBS`; consider treating
  a `docker build` context as a read.
- **N2.** An unquoted heredoc whose prose names the path (`cat > notes.md <<EOF` / `rm P would be bad` / `EOF`) was
  ALLOWED in round 1 and is DENIED now. The guidance already says to quote the delimiter, so this is consistent with the
  documented behaviour; noted only as a behaviour change.
- **N3.** `_deep_violation`'s docstring mentions `MAX_DEEP_BODIES`, which does not exist.
- **N4.** Shapes that run a scan-judged verb many times still grow about x3.3-3.5 per doubling: `rm x{a,b} ×2000`
  (14 KB) takes 5.2 s (round 1: 3.1 s), and `for … do rm …` ×2000 (74 KB) takes 13.7 s. The cause is the shared scan:
  `core/utils.py:484 substitute_cwd_expansions` re-searches the whole command per path (16k regex searches for a
  4000-operand `rm`, 3.8 s). That code predates this branch, but the B3 fix runs the scan a second time per scan-judged
  command (`rm` with 4000 operands: main 3.5 s, branch 8.2 s). `_LINEAR_SHAPES` in the handler tests uses `echo` for the
  brace and loop shapes, so it does not reach this path. These are not careless-agent sizes; add an `rm` variant to
  `_LINEAR_SHAPES` when the shared scan is fixed.
- **N5.** `10k cd parts` (60 KB) takes 7.0 s (round 1: 5.1 s); `cd-parts` 4000 (24 KB) is 1.1 s. Not a careless shape.

## In-scope fixes verified (all DENY unless noted)

| round-1 item | shapes probed                                                                                                                                                                                                                                                                   | result                             |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| B1           | `F=a ×n; cd a; echo x`: 250/500/1000/2000/4000 → 136/248/366/773/1643 ms (x1.5-2.1)                                                                                                                                                                                             | fixed (round 1: 6.5 s at n=250)    |
| B2           | depth-4 `bash -c` with `ccy/*`, `{local,x}`, `rm -rf .claude`, `cd .claude && rm -rf ccy`                                                                                                                                                                                       | all DENY                           |
| B3 (scoped)  | `time -p rm`, `time rm`, `command rm`, `nohup rm`, `> >(tee P)`, `export`/`export -n`/`declare`/`local`/`readonly F=P; rm $F`                                                                                                                                                   | all DENY                           |
| S2 xargs     | `echo P \| xargs shred -u`, `xargs -n1 cp /dev/null`, `ls ccy/* \| xargs rm`, `-I{}`, `printf … \| xargs -0 rm -f`, `xargs rm < <(echo P)`                                                                                                                                      | DENY; here-string forms ALLOW (S1) |
| S3 read loop | `ls ccy/* \| while read f; do rm "$f"`, `while read f; do rm $f; done <<< P`                                                                                                                                                                                                    | DENY                               |
| S5 find      | `-name '*.local' -delete`, `-name ccy.env.local -delete`, `-exec rm {} +`, `-type f -exec rm {} \;`, `.claude/ccy -delete`, `.claude -delete`, `-path '*ccy*' -delete`                                                                                                          | all DENY                           |
| S6 parent    | `rsync … ccy/`, `rsync -a --delete … ccy/`, `tar -C ccy`, `unzip -d ccy`, `cp -r /tmp/dir/. ccy`                                                                                                                                                                                | all DENY (over-reach: S3, N1)      |
| S9           | `git diff --output[=]P`, `git log --output=P`, `less -o P`/`-oP`, `sort -o P`/`-oP`/`--output=P`, `xxd x P`, `uniq x P`, `awk -i inplace`, `awk '{print > "P"}'`, `awk 'BEGIN{system("rm P")}'`                                                                                 | all DENY                           |
| S10 reads    | `sort`, `sort -u`, `awk 1`, `awk -F= '{print $1}'`, `awk '$1 > 0'`, `awk '{print … \| "sort"}'`, `xxd`, `hexdump -C`, `column -t`, `bat`, `shellcheck`, `uniq P`, `diff <(sort P) <(sort P.dist)`, `docker run --env-file P`, `docker compose --env-file P`, `dotenv -f P list` | all ALLOW                          |
| S11          | the sweep now configures `paths`; handler has 8 linear shapes                                                                                                                                                                                                                   | in place (gap: N4)                 |

Reads still allowed: `cat`, `grep`, `less`, `git diff/log -p`, `source`, `.`, `set -a; . P`, `ls -la .claude/ccy`,
`du -sh .claude/ccy`, `cp P /tmp/backup`, `echo P | xargs cat`, `echo P | xargs -I{} cp {} /tmp/backup`,
`find . -name '*.pyc' -delete`, `find . -name __pycache__ -exec rm -rf {} +`, `grep -rl foo src | xargs sed -i`.
Remaining write misses in the round-1 batch (21) are all out of scope or informational: bracket globs, links, piped or
here-stringed shells, interpreters, `$(...)`, `${…:+P}`, `git stash/apply/add`, `split`.

## QA on 731019d7a (cwd = worktree)

| check                                                                                                                                    | result                                      |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| ruff, black --check, mypy, bandit (changed src and tests)                                                                                | clean                                       |
| `audit_error_hiding.py`, `check_magic_values.py`, `check_module_length.py`, `check_handler_reference.py`, `check_generated_doc_drift.py` | all pass (round-1 N4 resolved by the merge) |
| pytest: hostile-input file + `test_write_protected_paths.py` + `test_simple_commands.py`                                                 | 587 passed                                  |
