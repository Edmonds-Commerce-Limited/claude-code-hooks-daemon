# Review 3: adversarial review of the two loosening commits

Scope: (A) 6c16ce510 (a plain file under `/proc/self` or `/proc/thread-self` is
placed) and (B) fc3a2dc79 (`git commit`/`git status` after a computed `cd` is
not a tree reader). The builders' reports were not relied on.

**Verdict.** (A) PASS. (B) FAIL as built, and PASS after the fix.

- As built, (B) let 16 distinct commands print the dummy that the previous tip
  denied. It let 3 more through by running a `pre-commit` hook already in the
  landing repo.
- The fix is in this commit, RED then GREEN. After it:
  - no non-hook escape remains;
  - DENY-to-ALLOW against main is 0, comparing like for like.
- Two things go to the owner:
  1. **Playbook probe #350 is denied again.** It is
     `git commit --dry-run && cd - && git commit --dry-run`. That command
     prints a staged diff under an ambient `commit.verbose`, so the fix denies
     it by design. The harness expects ALLOW, so the probe or its expectation
     needs an owner decision.
  2. **The hook residual.** On a commit the guard allows, a hook already in the
     landing repo still runs. The previous tip and main also allow running that
     hook directly (`cd - && .git/hooks/pre-commit`), so the residual adds no
     new capability.

## Method

- Tools are in `review3-tools/`:
  - `probe3.py judge` runs `corpus3.txt` (142 commands) through
    `SecretFileGuardHandler` in-process.
  - `probe3.py oracle` runs every command the branch allowed in real bash.
- Fixture (built under `untracked/scratch/p623rev3/`):
  - `outside/` is a git repo holding a DUMMY-content protected-named file. It
    is committed, then modified, so any diff prints `DUMMY`.
  - `outside/` also holds an innocently named link `m` to the dummy.
  - `proj/` holds `sub/dl -> outside`, `flink -> dummy` and `olink -> outside`.
  - The oracle runs from `proj` with `OLDPWD=proj/sub/dl`, so `cd -` lands in
    the foreign repo.
- Trees compared, each a `git archive` of `src`:
  - main (7a24f0cf7);
  - prior tip 178cab629, before both commits;
  - the fixed tree.
- Modes:
  - main and the fix each ran with the daemon cwd at `/` and at the project
    root;
  - the fix also ran cold, with no link index.
- Oracle variants:
  - plain;
  - `commit.verbose=true` in the landing repo's `.git/config`;
  - the same setting in `HOME/.gitconfig`;
  - a `pre-commit` hook in the landing repo that prints `m`.
- Positive controls (`cat flink`, `grep -r DUMMY olink`, `cat sub/dl/m`):
  - main with the daemon cwd at the root denies `cat flink` and
    `cat sub/dl/m`;
  - the fix denies all three.

## Results

**DENY-to-ALLOW against main (like for like): 0.** The three comparisons were:

- main to the fix, daemon cwd `/`;
- main to the fix, daemon cwd at the root;
- main to the fix cold.

Main allows 140 of the 142 commands at cwd `/`; only the two `cd ~-` rows are
denied there.

**(A) adds no new escape.** These all still deny:

- `cat /proc/self/cwd/flink`
- `cat /dev/fd/../cwd/flink`
- `grep -r DUMMY /proc/self/cwd/olink`
- `status/../cwd`, `/./cwd`, `//cwd`, `task/..`, `thread-self/cwd`,
  `thread-self/../self`
- `mountinfo/..`, `fdinfo/..`
- `stat*`, `{status,cwd/flink}`
- `cd /proc/self && cat cwd/flink`
- `cd /proc && cat self/cwd/flink`
- `/proc/./self`
- `/proc/self/root/proc/self/cwd`

The only rows it newly allows are `cat /proc/self/status`,
`cat /proc/thread-self/status`, `grep -r foo /proc/self/status` and
`cd /proc && cat self/status`. None of them leaked.

**(B) as built: 16 non-hook escapes against the prior tip**, counted from the
oracle over all four variants on the as-built tree (`out-cur*.json`):

- 10 in the plain variant;
- 6 more under ambient `commit.verbose`: `--dry-run -a`, `-a -m x --dry-run`,
  `GIT_EDITOR=cat`/`EDITOR=cat`/exported `GIT_EDITOR` with `commit -a`, and
  `-e`.

Examples:

- An option word the literal check cannot read:
  - `V=-vv; cd - && git status $V`
  - `git status ${V:--vv}`
  - `git status $'-vv'`
  - `git status $'\x2dvv'`
  - `git status {-v,-v}`
  - `git commit --dry-run -a $'-v'`
- Config carried in the environment:
  - `GIT_CONFIG_COUNT/KEY_0/VALUE_0=commit.verbose` with `git commit --dry-run -a`, inline or `export`ed in an earlier statement;
  - `GIT_CONFIG_PARAMETERS` with `GIT_EDITOR=cat git commit -a`.
- Ambient config the guard cannot see: with `commit.verbose` set in the landing
  repo or in `~/.gitconfig`, a plain `cd - && git commit --dry-run -a` (or
  `--long`) prints the diff with no suspicious word on the command line.
  - So the builders' NOT_READERS row
    `git commit --dry-run && cd - && git commit --dry-run` was wrong. It moved
    to the denied list.

**Fix: an allowlist** (`src/claude_code_hooks_daemon/utils/recursive_search.py`,
`_git_reads_no_tree`):

- Every word must be literal: no `$`, backtick, glob, brace, `\`, `~`,
  parentheses or `!`.
- Every option must be in a per-subcommand grammar, matched exactly, with no
  abbreviations.
- `commit` is trusted only with a message (`-m`/`--message`/`-F`/`--file`) and
  never with a dry-run, editor or verbose option.
- The command must name no `GIT_*`, `HOME`, `EDITOR` or `VISUAL` (a context
  variable set per `search_reads`).
- Anything else stays a reader.
- Probe #351 (`cd - && git commit -m acceptance -- no-such-acceptance-path`)
  is still allowed.
- Probe #350 (`git commit --dry-run && cd - && git commit --dry-run`) is denied
  again, by design (see the verdict). The acceptance harness was not rerun.
- Tests: `tests/unit/handlers/pre_tool_use/test_secret_file_guard_git_after_computed_cd.py`
  gained `HIDDEN_DIFF_OPTIONS` (19 rows).
  - The rows are judged twice: by the guard with the index built, and by
    `search_reads` with the scan unfinished, which must fail closed.
  - All 19 decision rows were RED before the fix.
  - The unscanned variant's RED could not be run against the as-built code: the
    conftest refuses a foreign `src` on `PYTHONPATH`.
  - The file passes 68/68.
- Targeted chunks pass: the `recursive_search`/`resolution_failure` utils
  (294) and `-k secret_file_guard` over `pre_tool_use` (2526).
- Cold-mode corpus runs are omitted: on this small fixture the fallback walk
  finishes, so they do not exercise the unscanned gate. The unit test above
  covers it.
- Daemon cwd `/` is not a meaningful baseline for main, which allows even
  `cat flink` there. The root-cwd comparison is the one that counts, and it
  is 0.
- Usability cost: after a computed `cd`, a message holding `(`, `!`, `$`, a
  glob character, or the text `HOME`/`GIT_`/`EDITOR` makes the commit a reader
  again. This only over-denies.

## Left open

- **Hooks and command-running config (accepted residual).** After the fix, all
  the plain, repo-config and home-config rows are clean. In the hook variant,
  `cd - && git commit -a -q --message=done` and `git commit --amend -m x` run
  the landing repo's `pre-commit` hook, and that hook printed the dummy.
  - This was probed, not assumed. Main, the prior tip and the fix all allow
    running the hook directly, and it leaks every time:
    - `cd - && .git/hooks/pre-commit`
    - `sh sub/dl/.git/hooks/pre-commit`
    - `./sub/dl/.git/hooks/pre-commit`
  - The prior tip also allows `cd sub/dl && git commit -m x`, which runs the
    hook.
  - It needs a hook planted in advance. `core.fsmonitor`/`core.hooksPath` in a
    landing repo's config are the same class.
  - Closing it means dropping `commit` from the carve-out, which costs probes
    #350/#351. That is the owner's call.
- **Pre-existing `/proc` escapes, ledgered as N674 and not introduced by (A).**
  All of these were allowed on main and on the prior tip, and all leaked:
  - `cat /proc/$$/cwd/flink`
  - `cat /proc/$BASHPID/cwd/flink`
  - `cat /proc/[0-9]*/cwd/flink`
  - with the daemon cwd not at the root: `cat /proc/sys/../self/cwd/flink` and
    `cat /proc/1/../self/cwd/flink`
- `cd - && git commit -am 'a message'` is still denied in the probe fixture (as
  it was on the prior tip), apparently by the word scan reading `-am` against a
  landing-dir file named `m`. It over-denies only and is not investigated
  further.
