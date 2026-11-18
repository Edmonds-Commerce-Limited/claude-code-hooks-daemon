# Plan 00614: independent adversarial review of the secret-guard link change

**Verdict: FAIL.** There are 6 defects and the DENY-to-ALLOW count is **0**.

Nothing that main denies is allowed on the branch. The FAIL is against the second half of the invariant: a scan that does not finish must fail closed. Two scans in the new computed-move code stop early and allow:

- one stops silently, triggered by a single link loop;
- one stops at its directory cap, logs it, and allows anyway.

## How it was checked

- Branch `agent-a13d7c8504105d4c9-aeae03b4` was reviewed read-only at `be92e10d1`. The source diff and tests were read before the implementer's report.
- Harness: `untracked/scratch/00614-review/tools/harness.py`. It runs the real `SecretFileGuardHandler` (`matches()` then `handle()`) with the process cwd set to `/`, as in the daemon, and the project root patched to a synthetic repository.
- Import check: the branch run imports `resolution_failure.py` from the worktree `src`. main runs use `/workspace/src`.
- Three synthetic fixtures. Each has an `outside/` sibling holding dummy protected files, plus file links, directory links, chains, a loop, an `above -> ..` link, 80 sibling directories (links in n15–17 and n62–66), a 600-directory `wide/` tree and a 70-deep chain:

| Fixture | Protected file inside the project | Link loop |
| ------- | --------------------------------- | --------- |
| `fx/`   | yes                               | yes       |
| `fxn/`  | no (the plan's worktree case)     | yes       |
| `fxl/`  | no                                | no        |

- Probes:
  - `probes()`: 157 probes;
  - `probes2()`: 59 probes;
  - `loopcheck.py`, `cachecheck.py`, `cwdcheck.py`.

## DENY-to-ALLOW comparison (main vs branch)

The corpus is 2,390 distinct commands:

- every string literal in the secret-guard, secret-matching and recursive-search test files, from both main and the branch;
- every `command` in the earlier review case files (`untracked/scratch/cases614*.json` and `rv614c/*.json`).

Each was run as a Bash call through my harness on both code trees. Only the commands were taken from the case files, not their verdict code.

| Run                            | main denies | branch denies | DENY to ALLOW | ALLOW to DENY | Errors |
| ------------------------------ | ----------- | ------------- | ------------- | ------------- | ------ |
| corpus, `fx/`                  | 783         | 1074          | **0**         | 291           | 0      |
| corpus, `fxn/`                 | 780         | 1074          | **0**         | 294           | 0      |
| 216 probes, `fx/`              | –           | –             | **0**         | 115+          | 0      |
| 216 probes, `fxn/`             | –           | –             | **0**         | –             | 0      |
| exec and cluster extras, `fx/` | –           | –             | **0**         | –             | 0      |

Notes on the table:

- `cases614b.json` is not valid JSON and was skipped, as the implementer also did.
- On `fxn/`, every cap-boundary and search probe still denies: 16-cap chains, 63–67 subshell `cd`s, the 70-step chain, and 5–8 failed `cd`s. So the search caps fail closed even with no protected file inside the project to fall back on.

## Defects, by severity

### D1 (High): one unlistable entry ends the computed-move scan, and the scan fails open

**Where:** `src/claude_code_hooks_daemon/utils/secret_file_matching.py:3551-3570`, in `computed_move_directories`.

**Cause.** `entry.is_dir()` at line 3557 follows the link. On a link loop it raises `OSError` (ELOOP); `DirEntry.is_dir` swallows only ENOENT. The raise escapes the `for entry` loop:

- the directory is recorded as "holding a link", but every sibling not yet iterated is never queued;
- when this happens at the project root, the breadth-first scan ends after about three directories;
- the queue is empty, so even the "scan stopped" log line does not fire.

By the same code path, any other `OSError` from `is_dir()` should end the scan the same way, for example EACCES on a link whose target is under an unsearchable directory. That case was inferred from the code, not probed.

**Probe** (`tools/loopcheck.py`, `plain/late` is a file link out, `plain/latedir` a directory link out):

| Command                                 | `fxl/` (no loop) | `fx/` (one `loopa <-> loopb` loop at the root) |
| --------------------------------------- | ---------------- | ---------------------------------------------- |
| scan                                    | 30 entries       | 10 entries, `plain` missing                    |
| `cd $(printf plain); cat late`          | deny             | **allow**                                      |
| `cd $(printf plain); grep -r x latedir` | deny             | **allow**                                      |
| `cd $(printf plain); cat latedir/*`     | deny             | deny (base-out rule)                           |

**Effect.** Any project with a link loop, or with an unstat-able link, early in its breadth-first order switches off the review 614b R4 and 614c N1 protection project-wide. That covers both the text walker and `recursive_search._SearchCwds.indeterminate`, which share this scan.

**Why tests miss it:** no fixture puts a loop or unstat-able link beside a computed `cd`.

The same `entry.is_dir()` call exists elsewhere, with these outcomes:

| Place                   | Outcome on a raise                                                                       |
| ----------------------- | ---------------------------------------------------------------------------------------- |
| `CwdSet._listing`       | Fails closed: the listing becomes `None` and the word is denied.                         |
| `expand_directory_glob` | Drops the whole directory's matches; a no-match globbed `cd` then becomes indeterminate. |

The `expand_directory_glob` case still relies on the scan above, so it inherits D1.

### D2 (Medium): the 512-directory cap on the computed-move scan fails open, and the residual is not recorded

**Where:** `secret_file_matching.py:3455` (`LINK_SCAN_DIRECTORY_CAP`) and `3548-3577`.

**Probe** (`fxl/`, no loop, 600 directories under `wide/`, the link in `wide/w599/zz`):

- `cd $(printf wide/w599/zz); cat wl`: **allow** on every fixture.
- The glob form, `cat wdl/*`, denies.

**Effect.** Any real repository is far past 512 directories, so after a computed `cd`, a plain relative link read in an unscanned directory goes unjudged.

**Records.** The docstring calls this "a residual recorded in the plan", but:

- neither `PLAN.md` Task 3.3 nor ledger N650 mentions it;
- the finish report's residual list does not mention it either.

**Why tests miss it:** the computed-`cd` tests use small trees.

**Note:** main does not follow computed `cd`s at all, so this is not a loosening.

### D3 (Medium): env/sudo chdir options are read only in their exact spellings

**Where:** `secret_file_matching.py:3831-3850` (`chdir_wrapper_targets`). The option tables are `_CHDIR_OPTIONS` at `3421` and the `sudo` entry in `shell_segmentation.COMMAND_WRAPPERS`.

Only `-C X`, `-CX`, `--chdir X` and `--chdir=X` are read.

**Allowed on the branch** (and on main):

- clustered short options:
  - `env -iC inner cat rel`, `env -iCinner …`, `env -0C …`, `env -vC …`;
  - `sudo -nD inner cat rel`, `sudo -bD …`, `sudo -nDinner …`;
  - `env -iC olink cat i*`, `sudo -nD olink cat i*`;
- getopt long-option abbreviations: `env --chd=inner cat rel`, `env --ch inner …`, `sudo --chd=inner …`.

The search side mostly holds: `env -iC olink grep -r` and `sudo -nD olink grep -r` deny.

**Why tests miss it:** the RED tests (`7567f736d`) cover path-qualified names, not option clusters or abbreviations. tar already handles both (`tar --dir=`, `tar -cC` deny).

### D4 (Low-Medium): an `exec` prefix hides a chdir wrapper

**Where:** `secret_file_matching.py:3428` (`_BUILTIN_PREFIXES` = builtin and command only) and `recursive_search.py:905` (`_past_command_prefix`).

**Allowed on the branch and on main:**

- `exec env -C inner cat rel`
- `exec env -C olink cat i*`
- `exec sudo -D inner cat rel`
- `exec env -C olink grep -r x .`

The search form is allowed too. `command env -C`, `time env -C`, `nice -n 5 env -C` and `stdbuf -oL env -C` all deny.

### D5 (Low): a link made between two calls is missed for 5 seconds

**Where:** `secret_file_matching.py:3457` and `3540-3543` (`_link_scans`, keyed by root, module-level and so shared across calls in the long-lived daemon).

**Probe** (`tools/cachecheck.py`, `fxl/`), running `cd $(printf plain); cat late` three times:

1. before the link exists: allow (correct);
2. with the link just created: **allow**;
3. after 5.5 s: deny.

An agent can create the link in one call and read through it in the next within the window.

### D6 (Low, existed before): the Grep tool with no `path`, from a hook cwd that is itself a link out of the project

**Where:** `handlers/pre_tool_use/secret_file_guard.py:1596-1616`. An empty `path` is never placed from `cwd`, and `placed` is `None`.

**Probe** (`tools/cwdcheck.py`): `cwd = P/olink`, `Grep {"pattern": "x"}` is **allow** on both sides. With the same cwd, the Bash `cat i*` and `grep -r x .` now deny on the branch, so the Grep tool is the remaining route.

## Recorded residuals, confirmed and not counted

These match the finish report and N650:

- **N2**: `cat olink/../outside/i*`, `cd -P olink/.. && cat outside/i*`, `cd -P olink/..; cat outside/sub/*`.
- **A glob matching a file link**: `cat fli[n]k`.
- **An absolute glob outside the project**: `cat /…/outside/i*`, `cat /…/fx/*/i*`.
- **`cat */*`**.
- **CDPATH from the environment.**

## Not counted, and why

- **Outside this change's model:** other chdir tools (`nsenter --wd`, `unshare --wd`, `systemd-run --working-directory`) and an in-language chdir (`python3 -c "os.chdir(…)"`, `perl -e 'chdir …'`). All allowed on both sides.
- **Time of check:** `ln -s ../outside q && cat q/i*` is allowed on both sides. Static analysis cannot see a link the same command creates.
- **No read follows:** `git -C inner cat-file -p :rel`, `cat loopa`, `cat olin?`, `ls -R olink/`, `cat olink/{plain.txt,sub}`, a `cd` to a NUL-bearing or 5,000-character name.
- **A missing or relative hook `cwd`:** every relative probe is allowed on both sides. This existed before, and Claude Code always sends an absolute cwd.
- **Wall time** of the 70-step and 67-subshell probes against the scan deadline was not measured. None of them reached the advisory route.

## Held up under probing

- **Relative links placed from the command's directory:** `cd`, `;`, subshells, brace groups, `$( )`, backticks, `pushd`/`popd`, `bash -c` (nested), `eval`, `builtin`/`command`, a redirect before `cd`, `if`/`while`/`for`/function bodies, and newline or heredoc-fed bash.
- **Computed or unplaceable `cd`s:** `cd -`, `~-`, `$OLDPWD`, an unset variable, `$( )` and backtick substitution, `${D:-x}`, arrays, brace lists, globs, extglob, inline `CDPATH`, and a `read` variable.
- **Wrappers:** `/usr/bin/env -C`, `/usr/bin/sudo -D`, `sudo -u root -D`, `nohup`/`timeout`/`time`/`nice`/`stdbuf` before `env -C`, and `tar -C`/`--directory`/`--dir=`/`-cC`.
- **Chains and directory links:** chains (`c1 -> c2 -> c3`, `dc1 -> dc2`), `above -> ..`, `olink/*`, `ol*/*`, `cd olink && cat *`, and `cd inner/irel && cat *`.
- **Finding-based search routes:** `grep -r`/`-R`, `rg -L`, `find -L … -exec`, `find olink/ -execdir`, and `xargs`.
- **Grep tool:** relative and absolute link-out paths.
- **Fail-closed paths:** brace-expansion size-limit cases with a relative link, a link-out glob, `grep -r` through a link, `env -C`, a computed `cd`, and a 17-directory chain all deny. These go through the literal fallback or the review 614c P2 deny.
- **Every cap boundary probed** (16 and 64; 15, 16, 17 and 62–67 directories, with the link in the last directory) **denies on all fixtures.**
