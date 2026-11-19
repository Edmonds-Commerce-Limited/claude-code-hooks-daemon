# Review 3: adversarial review of the two loosening commits

Scope: (A) 6c16ce510 (a plain file under `/proc/self` or `/proc/thread-self` is
placed) and (B) fc3a2dc79 (`git commit`/`git status` after a computed `cd` is
not a tree reader). The builders' reports were not relied on.

**Verdict.** (A) passes. (B) failed as built: 14 commands leaked the dummy. It
is fixed in this commit, RED then GREEN, and now passes with one accepted
residual (below).

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

**(B) as built: 14 escapes against the prior tip.** All of these printed the
dummy in real bash:

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
- Probes #350/#351 (`cd - && git commit -m acceptance -- no-such-acceptance-path`)
  are still allowed.
- Tests: `tests/unit/handlers/pre_tool_use/test_secret_file_guard_git_after_computed_cd.py`
  gained `HIDDEN_DIFF_OPTIONS` (19 rows). All 19 were RED before the fix and all
  pass after it; the file passes 49/49.

## Left open

- **Hooks and command-running config (accepted residual).** After the fix, all
  the plain, repo-config and home-config rows are clean. In the hook variant,
  `cd - && git commit -a -q --message=done` and `git commit --amend -m x` run
  the landing repo's `pre-commit` hook, and that hook printed the dummy.
  - This is the same class as running any script already on disk, which the
    guard does not judge (`./script` is allowed). It needs a hook planted in
    advance. `core.fsmonitor`/`core.hooksPath` in a landing repo's config are
    the same class.
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
