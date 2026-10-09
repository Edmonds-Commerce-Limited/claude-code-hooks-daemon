STOPPING BECAUSE: review complete; findings are below.

# Code Review: Plan 00499 Phase 1, `write_protected_paths` and the `include_mutations` scan extension

I did not write `/workspace/untracked/agent-reports/261009-00499-phase1-review-opus.md`. This session has no Write tool, and my operating instructions say to return findings in the reply rather than as a report file. The daemon's report-persistence handler saves this reply. The probe that reproduces every finding is at `/workspace/untracked/scratch/00499-review-probe.py`. Run it as `<venv>/bin/python -I <probe> <worktree>/src`. It builds the real handler over a temporary project, and no real `ccy.env.local` was read or touched.

**Verdict: REQUEST CHANGES.** The handler is switched on in this repo's `.claude/hooks-daemon.yaml`, and it denies ordinary wildcard cleanup commands in any directory.

- **Default-off flag:** confirmed to leave existing callers unchanged. Every existing caller (project_containment, markdown_organization, sed_blocker, bash_file_writes, lint) calls without the flag, and nothing unpacks `BashWriteDestination` by position.
- **Tests:** the 142 new tests pass. The adjacent suites give 668 passed and 1 failed. The failure is the already-known `test_claude_md_guidance_coverage` red, which needs a daemon restart to regenerate `CLAUDE.md`. The merge gate has to allow for it.

## Critical / must fix before merge

### 1. Any bare `*` wildcard is treated as naming the protected file, in any directory (confidence 95)
**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/write_protected_paths.py:222-227` (`_token_naming`)

`fnmatch.fnmatchcase(spelling, token)` is not shell globbing in two ways:
- fnmatch's `*` matches across `/`.
- It ignores the shell's rule that `*` never matches a leading dot.

The bare spelling `.claude/ccy/ccy.env.local` is tried whatever the cwd is. So any unresolved operand such as `*`, `*/*`, `*.local` or `*env*` "matches" the protected path.

**Probed failures (all denied, all wrong):**
- `rm -f *` run in `untracked/scratch`
- `rm -rf *` in the project root (bash does not expand `*` to `.claude`)
- `rm -rf */*`
- `rm -f *.local`
- `rm -- *.log *`
- `mv * ../dest/`
- `truncate -s0 *`

The deny message also says "do not look for another route", so the agent is pushed off a routine cleanup.

**Fix:**
- Expand the token against the cwd the way the shell would: join it to the cwd, split both into path segments, and match segment by segment with `_matches_in_full`, where `*` never crosses `/` or matches a leading `.`.
- Keep the loose by-name match only when `_UNTRUSTED_PATH_RE` fires.
- Add regression tests for `rm -f *` in an unrelated directory, and `rm -rf *` in the root, both expected to ALLOW. Keep `cd .claude/ccy && rm -rf *` expected to DENY.

## Important

### 2. Mutation verbs are recognised at any word position, so reading the file is denied (confidence 85)
**Location:** `src/claude_code_hooks_daemon/core/utils.py:959` (and the `ln` case at 946)

`token in _MUTATION_VERBS` is tested on every token, not only where a command starts. The test `git rm {p}` relies on this.

**Probed failures:** `grep rm .claude/ccy/ccy.env.local` and `grep -n truncate .claude/ccy/ccy.env.local` are both DENIED. That breaks the stated rule that reading is never denied, and the existing "reading is never denied" tests do not cover it.

**Fix:** report mutation verbs only where a command starts. That means the first word, or the word after a wrapper (`sudo`, `xargs`, `git`, `env`, `command`, `nice`, `timeout`), or after `-exec`. Add the two read commands above to `test_reading_is_never_denied`.

### 3. Common create/delete verbs are not covered, and the guidance claims they are (confidence 80)
**Location:** `utils.py:74` (`_MUTATION_VERBS`); guidance text at `write_protected_paths.py` `get_claude_md()`

`touch`, `unlink`, `find … -delete` and `cd .claude && rm -rf ccy` all reach the file and are all ALLOWED (probed).

`touch` matters most. The owner ruling is "We need to know that the file is created by IaC", and `touch .claude/ccy/ccy.env.local` creates exactly the file only IaC may create. The guidance tells agents that any command that "truncates or deletes one" is denied, which is not true.

The `cd` case fails because `_protecting_by_name` (line 201) matches the file name only. It never applies the ancestor-directory check that `_protecting` does.

**Fix:**
- Add `touch` and `unlink` to `_MUTATION_VERBS`; both take only file operands. For `touch`, skip the value of `-d`, `-r` and `-t`.
- In the by-name fallback, also deny a path whose final segment matches an ancestor directory of a listed path (`ccy`, `.claude`).
- Either narrow the guidance wording or list the known gaps there. `perl -i`, `rsync` and `find -delete` are acceptable as documented gaps.

### 4. Wildcard globs in `paths` produce project-wide false positives (confidence 75)
**Location:** `write_protected_paths.py:52` and `:269` (by-name fallback); `:219` and `:234` (substring needles)

With the documented example glob `deploy/*.env`:
- `cd frontend && echo A=1 > .env` is DENIED. Any `cd` in the command makes every `*.env` write anywhere a violation.
- `echo x > "$X/.envrc"` is DENIED, because the needle `.env` is a substring of `.envrc`.

This repo's literal glob is not affected, but the `.yaml.example` advertises this exact pattern.

**Fix:**
- In the by-name fallback, also require the resolved path to sit under one of the roots.
- Match needles against the token's final path segment with `fnmatch`, not as a substring.
- Add a test using the documented example glob.

## Suggestions (non-blocking; each should become a plan task)

- **`validate_options` disables everything on one bad entry** (`write_protected_paths.py:158`, `_option_problem`). A single absolute or `..` entry withholds the whole `paths` list, so a guard keeping several files protects none of them. The session-start alert does fire. Fix: drop only the bad entries and report them.
- **`rm` of a symlink pointing at the protected file is denied** (`_relative`, which applies `realpath` to mutation targets). `rm`, `mv` or `ln -sf` on the link does not touch the target. Rare. Fix: for `mutation=True` candidates, resolve only the parent directory, not the last component.
- **Priority values disagree.** `constants/priority.py` and `init_config.py:144` say 10; this repo's yaml and `.yaml.example` say 22, and HANDLER_REFERENCE shows both. Pick one.
- **The scan runs twice per Bash call.** `matches()` and `handle()` both call `_violation`, which tokenises the command each time. Cache the result per `hook_input`, or deny from `matches`' result.
- **`git rm {p}` in `test_a_command_that_changes_the_listed_path_is_denied` tests the position-blind matching behind finding 2.** If finding 2 is fixed, keep the test by recognising `git` explicitly as a wrapper; then the test is asserting intended behaviour rather than an accident.

## Positive observations

- The opt-in flag is tidy and pinned by `TestExistingCallersAreUnchanged`.
- `sed` option parsing is careful: `-ni`, `-i.bak`, `-e`/`-f` and `--in-place=` are all handled, and the probe confirmed it.
- `mv` sources and `-t` are covered, and a moved or removed ancestor directory is denied.
- Worktree roots and `..` and symlink spellings for the file tools are handled and tested.
- All tests drive the real handler over `tmp_path` with real assertions; I saw no theatre.
- Declaring the deny acceptance probe undrivable is the right call.

**Files:**
- Handler: `/workspace/.claude/worktrees/agent-a2d5407c7d12c4478-bd9fcea3/src/claude_code_hooks_daemon/handlers/pre_tool_use/write_protected_paths.py`
- Scan: `/workspace/.claude/worktrees/agent-a2d5407c7d12c4478-bd9fcea3/src/claude_code_hooks_daemon/core/utils.py`
- Probe: `/workspace/untracked/scratch/00499-review-probe.py`
- Test output: `/workspace/untracked/scratch/00499-review-pytest.txt`, `/workspace/untracked/scratch/00499-review-pytest2.txt`