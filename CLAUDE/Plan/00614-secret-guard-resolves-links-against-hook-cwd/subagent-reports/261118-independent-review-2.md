# Plan 00614: second independent adversarial review (round 6 tip)

**Verdict: FAIL.** The DENY-to-ALLOW count is **0** across every run. There are 2 new security defects, both Low and both no worse than main. There is also 1 usability finding (Medium) that is not counted as a security defect.

The FAIL is on the second half of the invariant, "any placement that cannot complete denies". D-A below is a placement that cannot complete and allows. It is narrow and was already allowed on main, but it contradicts the round's stated rule.

Branch `agent-a13d7c8504105d4c9-aeae03b4` was reviewed read-only at `2ae46b106`. main was at `0bbc9f23d`; nothing under `src/` changed on main since the merge base.

## Method

- **Import check.** With `PYTHONPATH` set to the branch, `resolution_failure.py` resolves to the worktree `src`. With main's path, the package resolves to `/workspace/src`. Python is the repository venv.
- **Harness.** The previous reviewer's `harness.py` was copied, unmodified, to `untracked/scratch/00614-review2/tools/`. It runs the real `SecretFileGuardHandler` (`matches` then `handle`) with the process cwd at `/` and the project root patched.
- **New tools:**
  - `newprobes.py` (new fixtures and probes);
  - `one.py` (ad hoc commands);
  - `qharness.py` (the same harness driving `QuarantineArtefactReadGuardHandler`, with every target renamed to a DETAIL artefact).
- **Fixtures** (synthetic, under `untracked/scratch/00614-review2/`):
  - `fx/`, `fxn/`, `fxl/` are rebuilt from the prior harness;
  - `fy/` is a small tree under the scan cap, with link loops of length 2 and 3 at the root;
  - `cap511/`, `cap512/`, `cap513/` hold that many directories, with the link directory listed **last**;
  - `caplinks512/`, `caplinks513/` hold that many directory links;
  - `fq/` is the quarantine variant.
- No real secret file was read. The one kernel check used `stat -L` on a synthetic dummy.

## 1. The previous reviewer's probes, re-run

| Run              | Cases | main deny | branch deny | DENY to ALLOW | ALLOW to DENY | Errors |
| ---------------- | ----- | --------- | ----------- | ------------- | ------------- | ------ |
| `probes()` fx    | 157   | 27        | 145         | **0**         | 118           | 0      |
| `probes()` fxn   | 157   | 27        | 145         | **0**         | 118           | 0      |
| `probes()` fxl   | 157   | 27        | 145         | **0**         | 118           | 0      |
| `probes2()` ×3   | 59    | 10        | 51          | **0**         | 41            | 0      |
| `cwdcheck.py` fx | 36    | –         | –           | **0**         | 7             | 0      |
| quarantine `p1`  | 157   | 27        | 60          | **0**         | 33            | 0      |
| quarantine `p2`  | 59    | 9         | 15          | **0**         | 6             | 0      |

What is still allowed on the branch is exactly the previously recorded residuals and the "not counted" list:

- **Recorded residuals:** `fli[n]k`, `olin?`, N2 `..` after a link, absolute globs, `*/*`.
- **Not counted:** `git -C … cat-file`, `cat loopa`, `ls -R`, a brace through a link, a time-of-check `ln -s`, `nsenter`/`unshare`/`systemd-run`, in-language chdir, a NUL-bearing name and a 5,000-character name.

The specific defects of the prior round:

- **D1 (link loop), under the cap.** On `fy/`, where the scan completes, `cd $(printf plain); cat late`, `grep -r x latedir` and `cat latedir/i*` all deny, with loops of length 2 and 3 at the root. They are allowed on main. Fixed.
- **D2 (512 cap).** Fixed. On `cap511` and `cap512` the scan is complete and the link in the last-listed directory is found, so the command denies on the link. On `cap513` the scan is incomplete and the command denies as "could not be worked out". `caplinks512` is complete and `caplinks513` is incomplete, and both deny. `scan_project_links` reports `complete` correctly at each boundary.
- **D3 and D4.** Every cluster, abbreviation and `exec` form in `probes2()` denies.
- **D5.** `cachecheck.py` no longer runs, because `_link_scans` was removed. The replacement probe in `newprobes.py` repoints `sw` from `plain` to `../outside` between two calls. The second call now denies for the glob, computed and search forms. main allows them.
- **D6.** A pathless Grep from a `cwd` of `P/olink` or `P/inner/irel` denies.

## 2. Corpus comparison, main versus branch

The corpus has 2,451 distinct commands. They are the prior 2,390, with fixture paths retargeted, plus every string literal in the guard, matching and search test files of both trees. This is the same count as the implementer's.

| Fixture | main deny | branch deny | DENY to ALLOW | ALLOW to DENY | Errors |
| ------- | --------- | ----------- | ------------- | ------------- | ------ |
| `fx/`   | 784       | 1189        | **0**         | 405           | 0      |
| `fxn/`  | 781       | 1189        | **0**         | 408           | 0      |

The ALLOW-to-DENY commands on `fx/` were filtered for ordinary-looking commands, meaning ones naming no link, fixture link or protected name:

- 132 of the 405 remain;
- 106 of those 132 contain a `cd` or `pushd`.

Many of the 132 are adversarial test literals, such as `t/*/*/*` globs or templates. The usability cost is measured directly in section 4.

## 3. New probes: 217 cases on `fy`, cap and caplinks, plus `fx`/`fxn` slices

**DENY-to-ALLOW: 0.** Each item below was probed on both trees.

| Shape                                                                                                                                                 | Branch                                                                                           | main                  |
| ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | --------------------- |
| Link loop of length 2 and 3 beside a computed `cd` (under the cap)                                                                                    | deny                                                                                             | allow                 |
| 511 / 512 / 513 directories, secret listed last                                                                                                       | deny / deny / deny (incomplete)                                                                  | allow                 |
| 512 / 513 directory links                                                                                                                             | deny / deny                                                                                      | allow                 |
| Trailing `/`, `//`, `./x/.` in `cat`, `cd`, `grep -r`, Grep tool, Read tool                                                                           | all deny                                                                                         | mostly allow          |
| Relative link target starting with `..` (`up/x/r -> ../../../outside`)                                                                                | all 10 forms deny                                                                                | allow (1 deny)        |
| `cd -P` / `-L` / `-LP` / `-P --` / `-e -P` into a link                                                                                                | deny                                                                                             | allow                 |
| `cd -P inner/irel/.. && cat outside/i*`                                                                                                               | allow                                                                                            | allow (N2 residual)   |
| `pushd`/`popd` sequences (`-n`, `+1`, `popd -n`, rotations, computed)                                                                                 | all 10 deny                                                                                      | allow                 |
| `git -C <rel>` after a computed `cd` / `$D` / top-level idiom                                                                                         | all 7 deny                                                                                       | allow                 |
| Top-level idiom variants (`/inner`, `--work-tree=`, `-C`, `-c core.worktree`, `--show-cdup`, nested checkout, shadowing function, unquoted, backtick) | all deny when a link is reachable                                                                | allow                 |
| Hard link to the protected file under a harmless name                                                                                                 | allow                                                                                            | allow (out of model)  |
| Same-command swap (`ln -sfn …`, `mv -T`)                                                                                                              | allow                                                                                            | allow (time of check) |
| Swap between two calls                                                                                                                                | deny after the repoint                                                                           | allow                 |
| Bind mount (same inode through two paths)                                                                                                             | **not testable**: `mount --bind` is refused in this container                                    | –                     |
| 16 to 21 failable `cd`s, then `cd lk17` / `cat fl17` / `grep -r lk17` (the suspected `[:CAP]` slice in N662)                                          | all deny ("existing directories" overflow), so the suspected slice did not reproduce as an allow | allow                 |
| Very long paths: `./`×2000, `./`×3000 (over `PATH_MAX`), in `cat`, `cd`, `grep`, Read, Grep                                                           | deny                                                                                             | allow                 |
| `plain/../`×N followed by `flink`                                                                                                                     | deny up to N=448; **allow at N≥449** (D-A)                                                       | allow                 |

### N662 residuals: confirmed known, and no worse than main

- **A `..`-led word after a computed `cd`.** `cd $(printf plain/q); cat ../late` is allowed on both trees. The glob and search forms (`../latedir/i*`, `grep -r x ../latedir`) deny on the branch.
- **`env -C inner cat rel` nested 5 or 7 `bash -c` levels deep.** Allowed on both trees.
- **A missing or relative hook `cwd`.** `cat flink`, `grep -r x olink` and a pathless Grep are allowed on both trees.
- **A pathless Grep from a `cwd` that passes through no link.** Allowed on both trees.

## Defects, by severity

### D-A (Low): a relative word that fits `PATH_MAX` only relative to the hook `cwd` is never resolved, and is allowed

**Where:**

- `secret_file_matching.py:4295`: `_link_targets` places a relative word as `str(Path(cwd) / token)`.
- `secret_file_matching.py:4269`: `_realpath_if_resolvable` then calls `os.path.lexists(candidate)`. That call returns False on ENAMETOOLONG, so the candidate is read as "no such path" and resolves to nothing.

**What happens.** Bash opens the word relative to its own cwd, and the kernel limit of 4,096 bytes applies to the word, not to cwd plus word. So there is a window of `len(project_root) + 1` characters in which:

- the kernel resolves the path;
- the guard cannot place it;
- the guard allows.

**Probe** on `fy/`, with a 51-character root:

| Command                            | Word length | Branch    | main  |
| ---------------------------------- | ----------- | --------- | ----- |
| `cat $(plain/../ × 448)flink`      | 4,037       | deny      | allow |
| `cat $(plain/../ × 449)flink`      | 4,046       | **allow** | allow |
| `cat $(plain/../ × 450)plain/late` | –           | **allow** | allow |
| `cat $(plain/../ × 450)inner/rel`  | –           | **allow** | allow |

At ×450, `stat -L` on the same relative word succeeds in the kernel and reports the dummy's 6 bytes.

The glob, `grep -r` and `cd` forms at the same length deny, because they take other routes.

**Why this counts.** It is not a regression, but it is a placement that cannot finish and allows. That is exactly the class this round claims to have closed. The word is long but trivially generated.

**Fix shape.** Treat an `OSError` other than ENOENT from the placement stat as unresolvable, so it denies. Alternatively, resolve the relative word with `dir_fd` / `openat` semantics.

**Why tests miss it:** no test uses a word near `PATH_MAX`.

### D-B (Low): a recursive search nested 5 or more `bash -c` levels deep is not seen

**Probe** on `fy/`: the branch denies `grep -r x olink` at nesting depths 3 and 4, and **allows** it at depths 5 and 6. main allows it at every depth. In the same nesting, `cat flink` and `cat olink/i*` deny at every depth from 3 to 6.

**What N662 records.** N662 lists the depth limit only for a hidden chdir (`_MAX_DIRECTORY_CHANGE_DEPTH`). The same silent stop on the **search** side, where no `cd` is involved, is not recorded.

**Fix.** It is the same fix as the N662 item: make the depth limit an incomplete signal that denies. This needs at least a line in N662.

## Usability finding (Medium; accepted by the implementer, quantified here)

In a project past 512 directories (`cap513`, one directory link, no protected file inside the project), main allows all of the following. The branch denies every one as "could not be worked out":

1. `cd "$D" && grep -r x .`
2. `cd - && cat README.md`
3. `cd && cat .bashrc` and `cd ~/proj && npm test`: a home-relative move, which is computed only because of `~`.
4. `cd "$TMPDIR" && python3 x.py` and `cd "$(mktemp -d)" && git clone https://example.invalid/r.git`: moves that land outside the project, where no project link can be met.
5. `for d in w00*/; do (cd "$d" && make); done` and `cd "$(dirname "$0")" && ./run.sh`.

Only the top-level idiom passes there:

- `cd "$(git rev-parse --show-toplevel)" && ls` and `… && make test` are allowed on `cap513`.
- On `fxn/`, which holds more than 16 link directories, even the idiom denies ("existing directories" overflow).

Under the cap (`cap511`), `cd $OLDPWD; git status`, `cd "${PWD%/*}" && ls src` and `cd "$(mktemp -d)" && tar xf /tmp/a.tgz` also deny. This is the accepted reader-of-every-directory-link over-deny.

Most real repositories exceed 512 directories, so ordinary agent commands will routinely be denied. The off-hot-path link index proposed in the round-6 report, or at minimum placing `~`, `$HOME` and `$TMPDIR`, would remove most of this cost.

## Claims verified

- **0 DENY-to-ALLOW.** Holds: corpus ×2, prior probes ×6, `cwdcheck`, quarantine ×2, and 217 new probes.
- **The scan reports completion, and both walkers deny when it is incomplete.** Holds for the 512-directory and 512-link boundaries, loops, and swaps between calls. The quarantine guard denies an unplaceable call: its probes show no allow route.
- **The top-level placement only adds.** No variant probed was allowed where a link was reachable.
- **Any placement that cannot complete denies.** Does **not** hold: D-A shows a resolution that fails and allows, and D-B a silent depth stop on the search side.
