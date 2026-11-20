# Plan 00614: second independent adversarial review (round 6 tip)

**Verdict: FAIL.** There are 3 security defects (2 Low-Medium, 1 Low), each no worse than main, and the DENY-to-ALLOW count is **0** in every run. There is also 1 usability finding (Medium), which is not counted as a security defect.

The FAIL is on the second half of the invariant, "any placement that cannot complete denies". It does not hold in two places:

- **D-C:** the round's own new exemption, the `git rev-parse --show-toplevel` idiom. Past the cap it is placed by an assumption the guard cannot check.
- **D-A:** a placement whose stat fails is read as "no such path" and allowed.

Branch `agent-a13d7c8504105d4c9-aeae03b4` was reviewed read-only at `2ae46b106`. main was at `0bbc9f23d`; nothing under `src/` changed on main since the merge base.

## Method

- **Import check.** With `PYTHONPATH` set to the branch, `resolution_failure.py` resolves to the worktree `src`. With main's path, the package resolves to `/workspace/src`. Python is the repository venv.
- **Harness.** The previous reviewer's `harness.py` was copied, unmodified, to `untracked/scratch/00614-review2/tools/`. It runs the real `SecretFileGuardHandler` (`matches` then `handle`) with the process cwd at `/` and the project root patched.
- **New tools:**
  - `newprobes.py`: 217 probes;
  - `extra.py`: follow-ups;
  - `one.py`: ad hoc commands;
  - `qharness.py`: the same harness driving `QuarantineArtefactReadGuardHandler`.
- **Fixtures** (synthetic, under `untracked/scratch/00614-review2/`):
  - `fx/`, `fxn/`, `fxl/` are rebuilt from the prior harness;
  - `fy/` is under the scan cap, with link loops of length 2 and 3 at the root;
  - `cap511/`, `cap512/`, `cap513/` hold that many directories, with the link directory listed last;
  - `caplinks512/`, `caplinks513/` hold that many directory links;
  - `big/` has 600 directories, no link and no protected file;
  - `fq/` is the quarantine variant.
- No real secret file was read. Kernel checks used `stat -L` on a synthetic dummy.

## 1. The previous reviewer's probes, re-run

| Run              | Cases | main deny | branch deny | DENY to ALLOW | ALLOW to DENY | Errors |
| ---------------- | ----- | --------- | ----------- | ------------- | ------------- | ------ |
| `probes()` fx    | 157   | 27        | 145         | **0**         | 118           | 0      |
| `probes()` fxn   | 157   | 27        | 145         | **0**         | 118           | 0      |
| `probes()` fxl   | 157   | 27        | 145         | **0**         | 118           | 0      |
| `probes2()` ×3   | 59    | 10        | 51          | **0**         | 41            | 0      |
| `cwdcheck.py` fx | 36    | –         | –           | **0**         | 7             | 0      |
| quarantine p1    | 157   | 27        | 60          | **0**         | 33            | 0      |
| quarantine p2    | 59    | 9         | 15          | **0**         | 6             | 0      |

**Still allowed by the secret guard.** What the branch still allows is exactly the recorded residuals and the "not counted" list:

- **Recorded residuals:** `fli[n]k`, `olin?`, N2 `..` after a link, absolute globs, `*/*`.
- **Not counted:** `git -C … cat-file`, `cat loopa`, `ls -R`, a brace through a link, a time-of-check `ln -s`, `nsenter`/`unshare`/`systemd-run`, in-language chdir, a NUL-bearing name and a 5,000-character name.

**Quarantine guard.**

- **Its many allows predate the branch.** The branch allows 97 and 44 of these probes, where the secret guard allows 12 and 8. Every extra allow is a relative read after a `cd`, `env -C`, `sudo -D` or `pushd`, or a Grep or Read of a relative link. main allows all of them too.
- **Its text route never walks directory changes, on either tree.** So the round's claim, that it denies an unplaceable call, is about the search walker only.
- **That claim holds.** Every `grep -r` probe past the caps denies there.
- **Caveat on the glob probes.** The probes spell `i*` and `i?_rsa`, and those cannot match the DETAIL-named targets. The glob probes therefore test nothing for that guard.
- **No quarantine corpus run.** The quarantine guard's own corpus run (its test literals) was **not done**.

**The prior round's defects:**

- **D1 (link loop), under the cap.** On `fy/`, with loops of length 2 and 3 at the root and a complete scan, `cd $(printf plain); cat late`, `grep -r x latedir` and `cat latedir/i*` all deny. main allows them. Fixed.
- **D2 (the 512 cap).** Fixed.
  - `cap511` and `cap512`: the scan is complete and the last-listed link is found, so the command denies.
  - `cap513`: the scan is incomplete and the command denies.
  - `caplinks512` is complete and `caplinks513` is incomplete, and both deny.
- **D3 and D4.** Every form in `probes2()` denies.
- **D5.**
  - `cachecheck.py` and `loopcheck.py` were **not run**: they call the removed `_link_scans` and `computed_move_directories`.
  - The original shape was reproduced on `fy/` instead. `cd $(printf plain/q); cat fresh` gives allow, then a link is created in the same process, then **deny**. main gives allow, then allow. Fixed.
- **D6.** A pathless Grep from a `cwd` of `P/olink` or `P/inner/irel` denies.

## 2. Corpus comparison, main versus branch (secret guard)

The corpus has 2,451 distinct commands. They are the prior 2,390, with fixture paths retargeted, plus every string literal in the guard, matching and search test files of both trees. This is the implementer's count.

| Fixture | main deny | branch deny | DENY to ALLOW | ALLOW to DENY | Errors |
| ------- | --------- | ----------- | ------------- | ------------- | ------ |
| `fx/`   | 784       | 1189        | **0**         | 405           | 0      |
| `fxn/`  | 781       | 1189        | **0**         | 408           | 0      |

## 3. New probes (secret guard): DENY-to-ALLOW 0

Each shape below was probed on both trees.

| Shape                                                                                                | Branch                                       | main                  |
| ---------------------------------------------------------------------------------------------------- | -------------------------------------------- | --------------------- |
| Link loop of length 2 and 3 beside a computed `cd`, under the cap                                    | deny                                         | allow                 |
| 511 / 512 / 513 directories, secret listed last                                                      | deny / deny / deny (incomplete)              | allow                 |
| 512 / 513 directory links                                                                            | deny / deny                                  | allow                 |
| Trailing `/`, `//`, `./x/.` in `cat`, `cd`, `grep -r`, Grep tool, Read tool                          | all deny                                     | mostly allow          |
| Relative link target starting with `..` (`up/x/r -> ../../../outside`), 10 forms                     | all deny                                     | allow (1 deny)        |
| `cd -P` / `-L` / `-LP` / `-P --` / `-e -P` into a link                                               | deny                                         | allow                 |
| `cd -P inner/irel/.. && cat outside/i*`                                                              | allow                                        | allow (N2 residual)   |
| `pushd`/`popd` sequences (`-n`, `+1`, `popd -n`, rotations, computed), 10 forms                      | all deny                                     | allow                 |
| `git -C <rel>` after a computed `cd`, `$D`, or the top-level idiom, 7 forms                          | all deny                                     | allow                 |
| Top-level idiom variants under the cap (`fy/`)                                                       | all deny where a link is reachable           | allow                 |
| Top-level idiom past the cap with `core.worktree` persisted                                          | **allow** (D-C)                              | allow                 |
| Hard link to the protected file under a harmless name                                                | allow                                        | allow (out of model)  |
| `/proc/self/cwd/flink`, `/proc/self/cwd/olink/i*`, `grep -r x /proc/self/cwd/olink`                  | **allow** (D-D)                              | allow                 |
| Bind mount                                                                                           | not testable: `mount --bind` is refused here | –                     |
| Same-command swap (`ln -sfn`, `mv -T`)                                                               | allow                                        | allow (time of check) |
| Swap between two calls                                                                               | deny after the repoint                       | allow                 |
| 16 to 21 failable `cd`s, then `cd lk17` / `cat fl17` / `grep -r lk17` (the suspected `[:CAP]` slice) | all deny, so the slice did not reproduce     | allow                 |
| `./`×2000 and `./`×3000 paths in `cat`, `cd`, `grep`, Read, Grep                                     | deny                                         | allow                 |
| `plain/../`×N followed by `flink`                                                                    | deny up to N=448, **allow at N≥449** (D-A)   | allow                 |

### N662 residuals: confirmed known, and no worse than main

- **A `..`-led word after a computed `cd`.** `cd $(printf plain/q); cat ../late` is allowed on both trees.
- **`env -C inner cat rel` nested 5 or 7 `bash -c` levels deep.** Allowed on both trees.
- **A missing or relative hook `cwd`.** Allowed on both trees.
- **A pathless Grep from a `cwd` that passes through no link.** Allowed on both trees.
- **The A1 no-search advisory route.** It was **not** newly probed.
- **N662 under-describes the depth limit.** It also stops the **search** walker, with no `cd` involved.
  - `bash -c` nesting of `grep -r x sec` on `fx/`: depths 1, 3 and 4 deny on both trees; depths 5 and 6 allow on both.
  - `grep -r x olink` on `fy/`: depths 3 and 4 deny on the branch; depths 5 and 6 allow on both.
  - This is an older unwrap limit and not a branch defect, but the N662 entry should say so.

## Defects, by severity

### D-C (Low-Medium): past the cap, the top-level idiom is placed by an assumption that persisted git config breaks

**Where:** the round's new exemption. `cd "$(git rev-parse --show-toplevel)"` is placed at the ancestors of the command's directory, and it is excused from the incomplete-scan deny (round-6 report, "D2's cost").

**What the guard checks, and what it misses.** The guard demotes the idiom to plain computed only when the **same command**:

- sets `core.worktree`;
- names a `GIT_` variable;
- defines a function or alias;
- changes `PATH`.

It cannot see repository config written by an earlier call. Once `core.worktree` is persisted, `git rev-parse --show-toplevel` prints that work tree, which is not an ancestor. This was confirmed with git on the fixture.

**Probe** on `cap513` (past the cap), with `core.worktree` set to `P/w000/zz`, where `late` is a file link out and `latedir` a directory link out. From a cwd of `P/w001` or `P`, all three of these are **allowed** on the branch, and main allows them too:

- `cd "$(git rev-parse --show-toplevel)" && cat late`
- `… && grep -r x latedir`
- `… && cat latedir/*`

The other idiom variants deny: `/w000/zz` suffix, `&& cd w000/zz`, `-C`, `--show-cdup`, and a literal `w000/zz/late`.

**Why this counts.** Under the cap the same commands deny, because the scan finds the links. So it is precisely the cap exemption that leaves the move unjudged. A placement that cannot be verified is allowed.

**Fix.** Read `core.worktree` (and `GIT_WORK_TREE` in the hook environment) at decision time, or keep the exemption only when the top level the guard computes equals the project root or a checkout nested in it.

### D-A (Low-Medium): a relative word that fits `PATH_MAX` only relative to the hook `cwd` is never resolved, and is allowed

**Where:**

- `secret_file_matching.py:4295`: `_link_targets` places a relative word as `str(Path(cwd) / token)`.
- `secret_file_matching.py:4269`: `_realpath_if_resolvable` then calls `os.path.lexists`. That call returns False on ENAMETOOLONG, so the candidate counts as "no such path".

**What happens.** Bash opens the word relative to its own cwd, and the limit of 4,096 bytes applies to the word alone. So there is a window of `len(project_root) + 1` characters in which:

- the kernel resolves the path;
- the guard cannot place it;
- the guard allows.

**Probe** on `fy/`, with a 50-character root:

| Command                            | Word length | Branch    | main  |
| ---------------------------------- | ----------- | --------- | ----- |
| `cat $(plain/../ × 448)flink`      | 4,037       | deny      | allow |
| `cat $(plain/../ × 449)flink`      | 4,046       | **allow** | allow |
| `cat $(plain/../ × 450)plain/late` | –           | **allow** | allow |
| `cat $(plain/../ × 450)inner/rel`  | –           | **allow** | allow |

At ×450, `stat -L` on the same relative word succeeds in the kernel and reports the dummy's 6 bytes. The glob, `grep -r` and `cd` forms at the same length deny, because they take other routes.

**Fix.** Treat an `OSError` other than ENOENT from the placement stat as unresolvable, so it denies.

**Why tests miss it:** no test uses a word near `PATH_MAX`.

### D-D (Low, no worse than main): a path through `/proc/self/cwd` is judged from the daemon's cwd

**Allowed on both trees:**

- `cat /proc/self/cwd/flink`
- `cat /proc/self/cwd/olink/i*`
- `grep -r x /proc/self/cwd/olink`
- `cat /dev/fd/../cwd/flink`

**Why.** The daemon's `/proc/self/cwd` is `/`, while the shell's is the project. `cd /proc/self/cwd && cat flink` denies on the branch. Treat a `/proc/self/`, `/proc/thread-self/` or `/dev/fd/` prefix as unplaceable.

## Usability finding (Medium; accepted by the implementer, quantified here)

The 132 corpus commands that the branch newly denies on `fx/` and name no link or protected file were re-run on `big/`. That fixture has 600 directories, **no link and no protected file**, so it is the large clean project.

| Fixture | main deny | branch deny | ALLOW to DENY |
| ------- | --------- | ----------- | ------------- |
| `big/`  | 0         | 94          | **94 of 132** |

About 27 of the 94 are ordinary developer commands rather than adversarial fixtures or templates. Five representative ones:

1. `cd "$D" && grep -r x .`
2. `cd - && cat r.md` and `cd && cat r.md`
3. `cd $(echo x) && ls`
4. `cd ~/vault`, and `cd ~- && echo hi`: denied because `hi` is a relative word.
5. `bash -c 'cd clean && cat plain.txt'`: a literal `cd`, read loosely as computed (recorded in N662).

On `cap513` the same holds for:

- `cd "$TMPDIR" && python3 x.py` and `cd "$(mktemp -d)" && git clone …`: moves outside the project, which no project link can affect;
- `for d in w00*/; do (cd "$d" && make); done`;
- `cd "$(dirname "$0")" && ./run.sh`.

Only the top-level idiom is allowed there. On `fxn/`, which holds more than 16 link directories, even the idiom denies.

Most real repositories are past 512 directories, so ordinary agent commands will be denied routinely. An off-hot-path link index, or at least placing `~`, `$HOME`, `-` and `$TMPDIR`, would remove most of this cost.

## Claims verified

- **0 DENY-to-ALLOW.** Holds: corpus ×2, prior probes ×6, `cwdcheck`, quarantine probes ×2, 217 new probes and the follow-ups.
- **The scan reports completion, and the walkers deny when it is incomplete.** Holds at both 512 boundaries, with loops, and for a link created between calls.
- **The quarantine guard denies an unplaceable search.** Holds.
- **The top-level placement "only adds".** Holds under the cap. Past the cap it is an unverified exemption (D-C).
- **Any placement that cannot complete denies.** Does **not** hold (D-A, D-C).
