# Plan 00499 Phase 1b review, round 1 (opus)

Branch `agent-a46aaf37c1a16d458-6185c9b3` (tip c2371a189), worktree
`/workspace/.claude/worktrees/agent-a46aaf37c1a16d458-6185c9b3`. Nothing in the worktree was edited.

**Verdict: CHANGES REQUESTED.** Counts: 4 BLOCKER, 11 SHOULD-FIX, 8 NIT.

Phase 1b is a large step forward. Run through the real handler, 51 write routes that main allows are now denied,
and no write that main denied is now allowed. Every 1b test class is red against main's src and green on the branch.
The open problems are: a quadratic path, which Phase 1 introduced and 1b made slower, that no test catches; nesting
past depth 3 that fails open; a class of scan-judged verbs that neither the scan nor the new verb pass judges; and the
1b invariant ("a command naming the path whose verb is not read-only is denied") breaking for multi-word operands.

Paths below are relative to `src/claude_code_hooks_daemon/` unless absolute. Line numbers are at c2371a189.

## Method

- Probes drive `WriteProtectedPathsHandler.matches`/`handle` with `apply_handler_options(paths=[".claude/ccy/ccy.env.local"])`
  over a `tempfile.mkdtemp()` project. They never touch the real file. The worktree src was confirmed imported
  (`imported from: /workspace/.claude/worktrees/agent-a46aaf37c1a16d458-6185c9b3/src/...`).
- Scripts: `/workspace/untracked/scratch/00499-review-1b-probe.py` (175 writes, 58 reads, hostile timings),
  `00499-review-1b-probe2.py` (follow-ups), `00499-review-1b-probe3.py` (single commands or `-f file`),
  `00499-review-1b-scaling.py` (size doubling per shape), `00499-review-1b-parse.py` (what `simple_commands` reads),
  `00499-redcheck/drive.py` (runs the branch's 1b test classes against any src).
- Full outputs: `/workspace/untracked/scratch/00499-review-1b-probe.out` (branch), `00499-review-1b-probe-main.out`
  (same probe against main), `00499-review-1b-probe2.out`, `00499-review-1b-scaling.out`.

## BLOCKER

### B1. Quadratic cost from carried assignments: a 2.5 KB command takes 22 s

`handlers/pre_tool_use/write_protected_paths.py:515-523` (`_runs`). Every part of a cd-bearing sequence is re-judged
with all the assignments before it prepended (`"; ".join([*assignments, part])`). Each run then goes through the
shared scan plus, since 1b, `brace_variants`, `unroll_for_loops` and `simple_commands`, so the cost is O(n²) heavy
passes:

| shape `F=a; ×n; cd a; echo x` | len  | branch | main   |
| ----------------------------- | ---- | ------ | ------ |
| n=250                         | 1262 | 6.5 s  | 2.8 s  |
| n=500                         | 2512 | 22.5 s | 12.6 s |
| n=1000                        | 5012 | 80.8 s | 55.2 s |

The shape comes from Phase 1, and 1b made it about 1.5 to 2.3 times slower. Nothing catches it (see S11). The
handler is enabled in this repository, so any long script-like command that holds a `cd` stalls the hook.

**Fix:** carry a bounded map, not text. Keep the last value per name (`dict`), cap it at about 32 names and mark the
run `untrusted` past the cap. Alternatively, compute `known_variables` once for the whole command and substitute it into each
part. Add a doubling test for this shape: `n=200` against `n=1600`, ratio below 8×4, like the existing one.

### B2. Past `MAX_SHELL_DEPTH` the check fails open

`write_protected_paths.py:744-745`. Past depth 3 a body is judged only by `_text_naming`, which looks for the
literal file name. Depth-4 `bash -c` (built with `shlex.quote`) is ALLOWED for:

- `rm $R/.claude/ccy/*`
- `rm $R/.claude/ccy/ccy.env.{local,x}`
- `rm $R/.claude/ccy/ccy.env.loc''al`
- `cd $R/.claude && rm -rf ccy`
- `rm -rf $R/.claude`
- `eval bash -c '…4 deep… rm $R/.claude/ccy/*'`

The brief requires a fail-closed result past the bound.

**Fix:** at the bound, run `simple_commands(body)` without recursing (linear) and deny unless every verb is in
`READ_ONLY_VERBS` with no nested body. Then update `test_nesting_deeper_than_the_bound_is_judged_by_name`: an 8-deep
harmless `bash -c 'true'` becomes a deny, which is acceptable for a shape no agent writes. Add red tests for the five
shapes above at depth 4.

### B3. Scan-judged verbs the shared scan never saw are not re-judged

`utils/simple_commands.py:253` computes `reread` against words that `strip_reserved_word_prefix` and `_substituted`
have already rewritten. `write_protected_paths.py:697/708` then skips every `SCAN_JUDGED_VERBS` command as "judged by
the scan", even when the scan never saw it. All of these are ALLOWED:

- `time -p rm P`. `simple_commands` gives `verb='rm', reread=False`.
- `X=rm; $X P` (`verb='rm', reread=False`).
- `cat /dev/null > >(tee P)`. The `tee` inside the process substitution is found, but `reread=False`.
- `export F=P; rm $F`, `declare F=P; shred $F`, `local F=P; rm $F`, `readonly F=P; rm $F`. Plain `F=P; rm $F` is
  denied. `export`, `declare` and the like are in `READ_ONLY_VERBS`, so their `F=P` operand is never judged, and the
  variable is not propagated.

`time -p` is a wrapper, which 1b says it reads through.

**Fix:** for every simple command whose verb is in `SCAN_JUDGED_VERBS`, always call `self._rescanned(command.text, where)`.
It is linear, and `command.text` already carries substituted operands. Also, or instead, set `reread` from the
segment's first raw word. Teach `known_variables` the `export|declare|local|readonly|typeset NAME=` prefixes. Add a
red test for each shape.

### B4. An unknown command whose operand is code naming the path is allowed

`write_protected_paths.py:764-781` (`_operand_naming`) treats each operand as a path, so a multi-word operand never
matches. All of these are ALLOWED:

- `watch 'rm P'`
- `ssh localhost 'rm P'`
- `tmux new -d 'rm P'`
- `env -S 'rm P'`
- `git -c alias.x='!rm P' x`

This breaks the stated 1b invariant: the command visibly names the path, and its verb is not read-only.

**Fix:** if an operand contains whitespace or a shell metacharacter (`` ;|&<>$`  ``), judge it by `_text_naming`, and
as nested code through `_nested_violation` within the depth bound. Add `env -S`/`--split-string` to
`nested_command_strings`.

## SHOULD-FIX

### S1. Code piped or here-stringed into a shell is not read

`echo 'rm P' | bash`, `| sh`, `bash <<< 'rm P'`, `bash /dev/stdin <<< …` and `source /dev/stdin <<< …` are all
ALLOWED. The heredoc form, `bash <<EOF`, is denied. **Fix:** a shell interpreter, or `source`/`.` given
`/dev/stdin` or `-`, with no `-c` and no script operand, gets its here-string word judged as nested code. When such
a shell is piped into, apply `_text_naming` to the earlier pipeline stages (fail closed).

### S2. `xargs` is still a denylist regex and needs the literal name

`write_protected_paths.py:179` and `655-661`. `… | xargs shred -u`, `… | xargs -n1 cp /dev/null` and
`ls .claude/ccy/* | xargs rm` are all ALLOWED. **Fix:** read `xargs` as a wrapper. When the verb it runs is not
read-only, judge the producer's words with `_token_naming`/`_protecting(directories=True)` as well as `_text_naming`.

### S3. `while read` loops are not read

`ls .claude/ccy/* | while read f; do rm "$f"; done` and `while read f; do rm $f; done <<< P` are ALLOWED.
**Fix:** when a mutating verb's operand is an unresolved `$var` bound by `read`, judge the loop's input: a
here-string, a `<` file, or the producer before the pipe.

### S4. Bracket globs slip past the scan-judged verbs and redirects

`rm …/ccy.env.[l]ocal`, `cp /tmp/x …/ccy.env.loca[l]` and `echo x > …/ccy.env.[l]ocal` are ALLOWED. `*`, `?` and
`shred …[l]ocal` are denied. **Fix:** in `_scan_text` (`write_protected_paths.py:623-628`), route a scan path
containing `_WILDCARDS` through `_token_naming`.

### S5. `find` with an action is allowed, though the guidance lists it as denied

These are ALLOWED:

- `find .claude/ccy -name '*.local' -delete`
- `find .claude -name ccy.env.local -delete`
- `find .claude -name 'ccy.env.*' -exec rm {} +`
- `find .claude/ccy -delete`

The guidance at `write_protected_paths.py:821` lists `find -delete` among the denied commands. **Fix:** when `find`
carries `-delete`, `-exec`/`-execdir`/`-ok`/`-okdir` with a verb that is not read-only, or `-fprint*`, judge its start
paths with `directories=True`. Otherwise, narrow the guidance.

### S6. A listed file's own directory, given as a destination, is allowed for unknown tools

These are ALLOWED, while `cp` and `install` of the same shape are denied:

- `rsync /tmp/ccy.env.local .claude/ccy/`
- `tar -xf a.tar -C .claude/ccy`
- `unzip -o a.zip -d .claude/ccy`
- `rsync -a --delete /tmp/empty/ .claude/ccy/`
- `cp -r /tmp/dir/. .claude/ccy`

**Fix:** for unknown verbs, treat an operand (or `-C`/`-d`/`--directory=` value) that is the immediate parent
directory of a literal listed file as naming it. `.claude` and `.` stay allowed, so `ruff check .claude` and
`pytest .` still pass.

### S7. Links create a second route to the same file

`ln P /tmp/hard && echo x > /tmp/hard` is ALLOWED. The hard link shares the inode, so this is a real write.
`ln -s P /tmp/alias && echo x > /tmp/alias` and `ln -s .claude/ccy alias && rm alias/ccy.env.local` are also
ALLOWED. **Fix:** deny `ln`, and `cp -l/-s/--link/--symbolic-link`, when any operand, the source included, names a
listed path or a directory above one.

### S8. A substitution can hide a mutator's operand or verb

`rm $(echo P)`, `` rm `echo P` ``, `$(echo rm) P`, `"$(which rm)" P` and `rm ${HOME:+P}` are ALLOWED.
`simple_commands` splits at `(`, so `$(echo rm) P` becomes three commands, the last with verb `a` (the file's own
basename). **Fix:** when a verb is `$` or begins with an expansion, or a mutator's operands were cut at a
substitution, judge the whole segment with `_text_naming` plus `_token_naming` over its words.

### S9. Some "read-only" verbs write files

`git diff --output=P`, `git log --output=P` and `less -o P` (also `-O` and `--log-file`) are ALLOWED. **Fix:** for
`GIT_READ_ONLY_SUBCOMMANDS` and `less`, judge `--output[=]`, `-o`, `-O` and `--log-file` values with
`_operand_naming`, or drop `less` from `READ_ONLY_VERBS`.

### S10. Reads are now denied, but the docs still say reading is never denied

These are DENIED: `sort P`, `sort -u P`, `awk 1 P`, `awk -F= '{print $1}' P`, `xxd P`, `hexdump -C P`,
`column -t P`, `bat P`, `vim -R P`, `diff <(sort P) <(sort P.dist)`, `shellcheck P`,
`docker run --env-file P img`, `dotenv -f P list` and `python3 tool.py --config P`. The first eight were measured as
ALLOWED on main.

Some of this is the price of an allowlist. But `docs/guides/HANDLER_REFERENCE.md` (the 1b paragraph) still says
"Reading is never denied", and the guidance says "You may read them". **Fix:**

- Add pure readers: `hexdump`, `column`, `bat`, `shellcheck`, `comm`, `paste`, `fold`, `base64`.
- Add guarded readers: `xxd` with at most one operand, `sort` without `-o`/`--output`, `uniq` with at most one operand
  (its second operand is written).
- Reword the docs: reading with a known reader is never denied, any other command naming the file is, so pipe it
  instead (`cat P | tool`).

### S11. The linearity guard does not cover this handler

`tests/unit/handlers/test_safety_handlers_hostile_input_performance.py:178-189` builds each SAFETY handler as
`handler_cls()`, with no `paths`, so `write_protected_paths._judge` returns at once and the sweep is vacuous. The
handler's own test (`test_write_protected_paths.py:944-958`) covers only one shape and passes on main too, so it
cannot go red. Measured superlinear growth that nothing catches:

| shape        | per doubling | largest case                        |
| ------------ | ------------ | ----------------------------------- |
| B1           | x3.5         | see B1                              |
| for-loops    | x3.6         | 74 KB, 15.8 s                       |
| brace groups | x2 to x2.9   | 14 KB, 3.1 s (main: 0.38 s at 7 KB) |

**Fix:** sweep the handler configured with `paths`, and add doubling tests for cd plus assignments, loops and brace
groups.

## NIT

- **N1.** Wrapper heuristic (`simple_commands.py:213-218`). "The first later known word" can be an option value:
  `doas -u echo shred P` is ALLOWED. Skip the option values of `sudo/doas/runuser -u`, `timeout DURATION` and
  `nice -n N` first.
- **N2.** sed's own write commands (`sed -n 'w P'`, `s/a/b/w P`) are not judged. This is moot here, because
  `sed_blocker` denies all sed.
- **N3.** Guidance and HANDLER_REFERENCE name `rsync` and `find -delete` as caught, which is only partly true (S5,
  S6).
- **N4.** The branch base (104f989ca) predates 06ab3658e. As a result, `scripts/qa/audit_error_hiding.py` fails on
  `utils/plan_fact_check.py:514,524`, and `check_generated_doc_drift.py` reports 416 lines. Both are clean on main,
  and neither comes from this branch: merge main before the gate.
  - `.claude/HOOKS-DAEMON.md` is untouched, and its row (the docstring summary) is unchanged, so 1b causes no drift
    there.
  - CLAUDE.md's daemon block will change at the next restart, because `get_claude_md` changed. That is expected.
- **N5.** `test_every_safety_handler_stays_linear[nesting]` failed once (`UpgradeApprovalGuardHandler` 27x) while the
  host ran the probes. It passes alone in 14 s. It is unrelated to this branch.
- **N6.** The journal says "tests first" but records no red run. My red check (below) confirms the tests are
  sensitive. Record the red run next time.
- **N7.** The file is gitignored (`.claude/ccy/.gitignore`: `*`), so `git checkout/restore/stash` cannot touch it.
  `git clean -fdX` could, but `destructive_git` already denies `git clean -f`. No action.
- **N8.** The declared interpreter gaps behave as documented: `python3 -c open(...)`, `node -e`, and a Python heredoc
  are all ALLOWED.

## QA on the branch (cwd = worktree)

| check                                                                                  | result                                      |
| -------------------------------------------------------------------------------------- | ------------------------------------------- |
| ruff, black --check, mypy, bandit (4 changed files / 2 src)                            | clean                                       |
| `scripts/qa/check_magic_values.py`                                                     | pass                                        |
| `check_module_length.py`, `check_handler_reference.py`, `check_fail_open_inventory.py` | pass                                        |
| `audit_error_hiding.py`                                                                | FAIL, stale base only (N4)                  |
| `check_generated_doc_drift.py`                                                         | FAIL, stale base only (N4)                  |
| pytest: the 3 targeted files (perf + handler + simple_commands)                        | 442 passed, 1 failed (N5, flaky, unrelated) |

## Red check of the 1b tests (branch tests run against main's src, then the branch's)

| class                                          | main: pass / red | branch: pass / red |
| ---------------------------------------------- | ---------------- | ------------------ |
| TestUnlistedWrappersHideNothing (1b.1)         | 54 / 18          | 72 / 0             |
| TestBraceExpansion (1b.2)                      | 11 / 19          | 30 / 0             |
| TestShellStringsAndAbsoluteCommands (1b.3)     | 15 / 29          | 44 / 0             |
| TestDirectoryChangeWithRedirectAndLoops (1b.4) | 13 / 14          | 27 / 0             |
| TestHostileInputStaysLinear                    | 1 / 0            | 1 / 0              |
| TestGuidanceAndAcceptance                      | 5 / 1            | 6 / 0              |

Each 1b task has tests that go red without the implementation, and they run through the real handler with
`apply_handler_options`. The linear test is the exception: it cannot go red (S11).

## Probe output (MISS lines; `$R` is the temp project root)

Batch 1, branch: 37 write misses out of 175 and 8 read false positives out of 58. On main the same batch gives 88
write misses and 0 read false positives.

```
MISS ALLOW echo $R/.claude/ccy/ccy.env.local | xargs shred -u
MISS ALLOW echo $R/.claude/ccy/ccy.env.local | xargs -n1 cp /dev/null
MISS ALLOW ls $R/.claude/ccy/* | xargs rm
MISS ALLOW rm $R/.claude/ccy/ccy.env.[l]ocal
MISS ALLOW ln -s $R/.claude/ccy/ccy.env.local /tmp/alias && echo x > /tmp/alias
MISS ALLOW ln -s $R/.claude/ccy $R/alias && rm $R/alias/ccy.env.local
MISS ALLOW cat /dev/null > >(tee $R/.claude/ccy/ccy.env.local)
MISS ALLOW split -l1 /tmp/a $R/.claude/ccy/ccy.env.loc
MISS ALLOW tar -xf /tmp/a.tar -C $R/.claude/ccy
MISS ALLOW unzip -o /tmp/a.zip -d $R/.claude/ccy
MISS ALLOW git stash                                    (informational: file is gitignored)
MISS ALLOW git apply /tmp/p.diff                        (informational)
MISS ALLOW git add P && git commit -m x                 (informational: not a working-tree write)
MISS ALLOW rsync -a --delete /tmp/empty/ $R/.claude/ccy/
MISS ALLOW rmdir $R/.claude/ccy                         (informational: fails on a non-empty dir)
MISS ALLOW while read f; do rm $f; done <<< P
MISS ALLOW ls $R/.claude/ccy/* | while read f; do rm "$f"; done
MISS ALLOW bash -c "bash -c \"bash -c \\\"bash -c 'rm $R/.claude/ccy/*'\\\"\""   (depth 4)
MISS ALLOW echo 'rm P' | bash
MISS ALLOW echo 'rm P' | sh
MISS ALLOW bash <<< 'rm P'
MISS ALLOW bash /dev/stdin <<< 'rm P'
MISS ALLOW source /dev/stdin <<< 'rm P'
MISS ALLOW find $R/.claude -delete                      (declared gap)
MISS ALLOW find $R/.claude -name ccy.env.local -delete
MISS ALLOW find $R/.claude -name 'ccy.env.*' -exec rm {} +
MISS ALLOW find $R/.claude/ccy -type f -exec rm {} \;
MISS ALLOW find $R -path '*ccy*' -delete
MISS ALLOW python3 -c "open('P','w')"                   (declared gap)
MISS ALLOW python3 - <<'EOF' open('P','w') EOF          (declared gap)
MISS ALLOW node -e "require('fs').unlinkSync('P')"      (declared gap)
MISS ALLOW export F=P; rm "$F"
MISS ALLOW rm $(echo P)
MISS ALLOW rm `echo P`
MISS ALLOW rm $(printf %s $R/.claude/ccy/ccy.env.lo cal)
MISS ALLOW rm ${HOME:+P}
MISS ALLOW ln P /tmp/hard && echo x > /tmp/hard
-- reads denied --
MISS DENY  awk -F= '{print $1}' P
MISS DENY  sort P
MISS DENY  bat P
MISS DENY  xxd P
MISS DENY  hexdump -C P
MISS DENY  diff <(sort P) <(sort P.dist)
MISS DENY  column -t P
MISS DENY  vim -R P
```

Batch 2, branch (selected):

```
MISS ALLOW bash -c ×4 'rm $R/.claude/ccy/*' | ccy.env.{local,x} | ccy.env.loc''al | cd .claude && rm -rf ccy | rm -rf .claude
MISS ALLOW eval bash -c ×4 '... rm $R/.claude/ccy/*'
MISS ALLOW export F=P; rm $F            MISS ALLOW declare F=P; rm $F
MISS ALLOW echo x > …/ccy.env.[l]ocal
MISS ALLOW watch 'rm P'                 MISS ALLOW ssh localhost 'rm P'
MISS ALLOW tmux new -d 'rm P'           MISS ALLOW env -S 'rm P'
MISS ALLOW git -c alias.x='!rm P' x
MISS ALLOW git diff --output=P          MISS ALLOW git log --output=P
MISS ALLOW less -o P /tmp/x
MISS ALLOW sed -n 'w P' /tmp/x          MISS ALLOW sed 's/a/b/w P' /tmp/x
MISS ALLOW "$(which rm)" P              MISS ALLOW $(echo rm) P
MISS ALLOW X=rm; $X P                   MISS ALLOW time -p rm P
MISS ALLOW xargs -a /tmp/list rm        (no visible name: acceptable)
MISS ALLOW find …/ccy -name '*.local' -delete      MISS ALLOW find …/ccy -delete
MISS ALLOW rsync /tmp/ccy.env.local …/ccy/         MISS ALLOW cp -r /tmp/dir/. …/ccy
MISS ALLOW cd …/ccy && tar -xf /tmp/a.tar          MISS ALLOW cd …/ccy && unzip -o /tmp/a.zip
MISS ALLOW doas -u echo shred P         (N1)
-- reads denied (batch 3) --
DENY python3 tool.py --config P | docker run --env-file P img | shellcheck P | dotenv -f P list
DENY sort -u P | awk 1 P | xxd P | less | code P
```

The reads that stay allowed include all of these:

- `cat`, `grep`, `wc`, `diff`, `stat`, `cmp`, `file`, `md5sum`
- `git diff/log/show/status/blame`, `git -C … diff`
- `source P`, `. P`, `set -a; . P; set +a`
- `ls -la .claude/ccy`, `find … -name … -print`
- `cp P /tmp/backup`, `bash -c 'cat P'`, `sudo cat P`, `timeout 5 cat P`
- quoted and unquoted heredoc prose naming the path, `git commit -m` naming it, `gh … --body` naming it

`source` and `.` are right to allow: they execute the protected file's own content and write nothing.

Hostile inputs (batch 1): 40-deep and 200-`eval` nesting, a 2^20 brace product, `{1..100000}`, 5000 loop words,
30 nested `for` loops, 2000-deep parentheses and 300-deep `$(` each finish in 0.2 to 63 ms. The capped paths are
bounded. Outliers: 10k `cd` parts (60 KB) takes 5.1 s, 2000 brace groups (14 KB) takes 1.8 to 3.1 s, and the B1
assignment shape is quadratic.
