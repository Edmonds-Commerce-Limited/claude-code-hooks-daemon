# Security review — D-EXEC — delta run (Routine 00002, run 2026-001)

**Check**: `D-EXEC` — "New or changed process spawns: `shell=True`, a
string-built command line, a spawn that does not go through
`utils.git_repo.run_git` where it should."

**Interval**: `v3.63.0..v3.64.0` — 432 commits, 907 files,
75,521 insertions / 3,636 deletions.

**Answerability**: the check was **fully answerable**. The diff was produced
and read; every added line matching a spawn or command-construction shape was
resolved to its file and read in context. Nothing was skipped for a missing
path, an unreadable file or an absent tool.

**Result**: **2 findings**, one of them NEW relative to Routine 00001's
whole-repo sweep of `74b0989c -> 5d59f7ff` (which contains this interval).

---

## How the interval was scoped

Three passes over the interval diff, each answering one clause of the check:

1. **`shell=True` / `os.system` / `os.popen` / `eval` / `bash -c` in added
   lines.** 77 textual hits across the whole delta. **Every one is
   documentation, a handler's own rule text, or a test asserting that a
   *detector* recognises the shape.** There is no new executed `shell=True`,
   no new `os.system`, no new `eval` in an executed position.

2. **New spawns.** Added `import subprocess` lines across the whole delta: 22.
   **Two are production-adjacent** (`scripts/qa/run_corpus_qa.py`,
   `scripts/qa/run_pyright_check.py`, both new files); the other 20 are tests.
   **`src/claude_code_hooks_daemon/` gained no new `subprocess` import at
   all.** The only changed spawns inside `src/` are the two pre-existing ones
   in `daemon/cli.py` (`uv sync`, and the venv interpreter's import probe),
   whose change is the addition of `FileNotFoundError` handling around them —
   argv form, no shell, unchanged argv.

3. **Command lines built as strings.** This is where both findings are. The
   interval adds a whole new subsystem
   (`src/claude_code_hooks_daemon/reference_repos/`, 8 modules) and a new
   guarded-install path (`scripts/install/branch_install.sh` plus its callers).

### The "spawn that does not go through `run_git`" clause: clean

`reference_repos/` does not spawn git itself — `inspection.py:34` and
`refresh.py:29` both go through `utils.git_sync`, which goes through
`git_repo.run_git`. The only change to `git_sync.py` in the interval is
renaming `_remotes` to `remotes` (making it public). The only change to
`git_repo.py` is the addition of `is_linked_worktree`, which is a `.git` stat
plus a text read and spawns nothing. **No new git spawn bypasses `run_git`
anywhere in `src/`.**

---

## N1 — An agent-executed command line built by unquoted interpolation of a filesystem-discovered path and a remote-controlled branch name

**Status: NEW. Routine 00001's full D-EXEC sweep did not find this, and its
report says why — see "Why the full sweep missed it" below.**

### Citation

`src/claude_code_hooks_daemon/reference_repos/report.py:141-161`:

```python
def remediation_command(state: RepoState) -> str | None:
    ...
    if not state.is_on_default_branch and state.default_branch:
        return f"git -C {state.path} checkout {state.default_branch}"
    if state.is_behind:
        return f"git -C {state.path} pull --ff-only"
    return None
```

Both interpolations are unquoted. The module is new in this interval
(`d5a2e618`, "Plan 00401 Task 1.5: one renderer for all three surfaces").

The string is not printed as decoration. It is emitted as a `fix:` line the
agent is instructed to **execute**:

- `reference_repos/report.py:217-219` — `lines.append(f"      fix: {command}")`
- `handlers/pre_tool_use/reference_repo_freshness.py:548-550` — the same
  string inside a **DENY** message.
- `handlers/pre_tool_use/reference_repo_freshness.py:178` — the rule's `fix`
  field: "Run the `fix:` command printed beside the repo, then retry the read".
- `handlers/session_start/reference_repo_sweep.py:134` — "…run the `fix:`
  command printed beside it BEFORE relying on…"
- `CLAUDE.md`, rules `R-REFERENCE-REPO-STALE` and
  `R-REFERENCE-REPO-NOT-VERIFIED`, both carry the same instruction into every
  session's context.

So the executor is the agent's `Bash` tool, and the daemon is the thing that
composed the command. The block is *unsatisfiable* without running it, which
is the pressure that makes the agent comply.

### What it allows

Both interpolated values are outside the program's control.

**`state.path`** is **discovered from the filesystem**, not read from an
allowlist. `reference_repos/discovery.py:83-127` walks every root in
`reference_repos.roots` to `DEFAULT_MAX_DEPTH` (4) and returns **any**
directory carrying a `.git` entry. The default root is `untracked/repos/`.
A directory name is an arbitrary byte string on Linux; `;`, `$`, a backtick,
`&`, `|`, `(`, `)` and space are all legal in one. Nothing between discovery
and the f-string validates or quotes it.

- Mundane outcome: a governed clone under a path containing a space produces
  `git -C /home/me/My Repos/untracked/repos/alpha pull --ff-only`. The agent
  runs it, git reports a path that nobody named, the freshness block stays
  unsatisfiable, and the read stays denied for a repo that is actually fine.
- Deliberate outcome: a directory name carrying a command separator under a
  governed root makes the printed remedy a two-command line. The agent is
  under standing instruction to run it.

**`state.default_branch`** is **remote-controlled**.
`utils/git_sync.py:365-395` derives it from `refs/remotes/origin/HEAD` — a
symref git populates from the *remote's* HEAD at clone time. Reference repos
are third-party checkouts by definition; that is the subsystem's whole
purpose. Git's ref-name rules (`git check-ref-format`) forbid space, `~ ^ : ?
* [ \` and control characters, but **permit** `; $ ( ) & | ' " < > ! #` and a
backtick. A branch name carrying a command substitution is therefore valid,
and it needs no space.

The two values compose: the path is the easier one to influence, the branch
name is the one that crosses a trust boundary from outside the machine.

### The class

*A command line assembled by string interpolation for an executor that is not
this process — the agent — where any interpolated component is not a literal
this module controls.*

Membership test, decidable without asking the author: **does an f-string /
`%` / `.format` / concatenation produce a value that reaches a surface the
project's own instructions tell a reader to run, and does any substituted
component come from the filesystem, from git, from config, or from hook
input?** If yes, it is a member. The remedy is the same one the sibling module
already uses: `shlex.quote` each component (`issue_report/upstream.py:50`
does exactly this, in this same interval).

The boundary that matters, and the reason this class is distinct from the full
sweep's F1-F4: **the process boundary is not where the danger is.**
`subprocess` is absent here. The daemon emits text; a different process runs
it. A reviewer inventorying spawn sites sees nothing.

### Why the test suite does not catch it

`tests/unit/reference_repos/test_report.py:29-30` fixes the whole fixture
space:

```python
_ROOT = Path("/workspace")
_ALPHA = Path("/workspace/untracked/repos/alpha")
```

with `default_branch: str | None = "main"`. Every one of the six
`TestRemediation` cases (lines 132-164) asserts on *substring presence* —
`"pull" in command`, `"--ff-only" in command`, `"checkout main" in command` —
so the shape of the command is never parsed and no shell ever sees it. There
is no fixture whose path contains a space, let alone a metacharacter, and
none whose branch name contains anything but `main` / `wip`.

`tests/unit/handlers/pre_tool_use/test_reference_repo_freshness.py:217-241`
(`test_the_remediation_command_it_prints_is_itself_allowed`) is the closest
thing to a guard, and it tests the **opposite** property: that the emitted
command is not itself blocked by a handler. A command that is
*over*-permissive passes that test by construction.

`tests/integration/test_git_spawns_are_bounded.py` cannot see this either —
its own docstring scopes it to argv-form `subprocess` calls beginning with the
literal `"git"` under `src/claude_code_hooks_daemon`. `remediation_command`
never calls `subprocess`.

### Why the full sweep missed it

Routine 00001's `260915-secreview-D-EXEC-opus.md` opens its inventory with:

> `subprocess.{run,Popen,call,check_call,check_output}` call sites, by AST, in
> `src/` and `scripts/`: 24.

The method was an AST scan for spawner call sites plus a read of the
"generated-shell emitters" (`install/forwarder_generator.py`). Both are
**process-boundary** framings. `report.py` has no spawner call and emits no
`.sh` file — it returns a `str`. It fell between the two nets.

That is the delta routine earning its keep, but the more useful output is the
correction to the *full* routine's method: its D-EXEC inventory should be
"every construction of an executable command line", not "every spawn". The
same blind spot would hide any future handler that prints a remedy.

### Detector hypothesis

A Python AST rule in `scripts/qa/`, wired into `run_all.sh` like the
register's other four Defences.

Fire on: a `JoinedStr` (f-string) whose **first literal segment** begins with a
word in a known-executable set (`git`, `gh`, `rm`, `kill`, `pkill`, `npm`,
`npx`, `uv`, `python`, `python3`, `bash`, `chmod`, `curl`, `crontab`, `cp`,
`mv`, `bin/hooks-daemon`, ...) **and** which contains at least one
`FormattedValue` not wrapped in `shlex.quote`.

Narrowing that raises precision without losing this case: restrict the scan to
the modules that feed agent-visible surfaces — `handlers/`, and any module
whose output reaches `HookResult` / `AcceptanceTest` / a `report_lines`-shaped
renderer.

**Likely false positives, named honestly:**

- **`AcceptanceTest` declarations.** `reference_repo_freshness.py:662, 678,
  709, 724` build `f"git -C {probe} pull --ff-only"` and `f"rm -rf {probe}"`
  where `probe` is a module-level literal two lines up. These are safe and
  would fire. In this repo that is 4 of ~6 hits in the handler tree — **so as
  stated the rule is roughly 40% precision, and I am reporting it as noisy
  rather than clean.** Excluding `AcceptanceTest(...)` keyword arguments drops
  all four and keeps N1; that is how I would ship it.
- Prose that merely *names* a command — the `pkill -f` hint at
  `lsp_noise_checker.py:287`. Safe there, because its only interpolation is a
  per-language strategy constant, but indistinguishable from N1 without
  dataflow.
- Test helpers building command strings to feed a handler. Excluded by scoping
  the scan to `src/`.

A `# command-build: allow -- <reason>` marker, matching `audit_shell.py`'s
existing convention, absorbs the residue.

### Confidence, and what would settle it

**High** that the interpolation is unquoted, that both values are externally
sourced, and that the resulting string is presented to the agent as a command
to run — all four links were read directly off the source and are cited above.

**Medium** on how far the *deliberate* version reaches. Two things I did not
establish, and could not without executing:

1. Whether a real remote can get an arbitrary metacharacter-bearing branch
   name into a clone's `refs/remotes/origin/HEAD` in practice — GitHub's own
   branch-name UI is more restrictive than `check-ref-format`, and a
   self-hosted or hand-crafted remote is the realistic vector. **What would
   settle it**: create a local bare repo whose HEAD symrefs to a
   metacharacter-bearing branch name, clone it under `untracked/repos/`, and
   read the emitted `fix:` line. I am read-only and did not run this.
2. Whether the agent's own `Bash` guards (`destructive_git`, `pipe_blocker`,
   `project_containment`) would deny the injected tail before it ran. They
   might catch *some* payloads; they are a backstop, not the defence, and a
   payload chosen to avoid them is the normal case.

Neither uncertainty affects the mundane outcome — a governed clone under a
path containing a space produces an unsatisfiable block today, with no
attacker at all.

---

## N2 — The branch-install ref reaches `git` with no `--` separator (LOW, operator-gated)

### Citation

`scripts/upgrade.sh:559` and `scripts/upgrade.sh:644`:

```bash
git -C "$DAEMON_DIR" fetch --force --quiet origin "$_TRACK_REF"
...
git -C "$DAEMON_DIR" checkout "$_TRACK_REF" --quiet
```

`_TRACK_REF` is `$HOOKS_DAEMON_UNSAFE_TRACK_REF` (line 539), new in this
interval along with `scripts/install/branch_install.sh`. The value is
correctly **quoted** — so this is not word-splitting — but there is no `--`
separator, so a value beginning with `-` is parsed as an option rather than as
a ref. `scripts/upgrade_version.sh:117` feeds the same value to
`branch_install_stamp`, which uses it only in a `${ref//\//-}` expansion.

### What it allows

`git fetch` and `git checkout` both accept options that change what runs
(`--upload-pack=`, `--exec=`). Supplying one requires setting the environment
variable, which requires already having shell in the agent's environment.

### Why this is reported as LOW and not as a finding of N1's weight

**It crosses no privilege boundary.** Both `HOOKS_DAEMON_UNSAFE_TRACK_REF` and
`HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE` must be exported by the operator, the
gate refuses when only one is set (`branch_install.sh:31-49`), and anyone who
can set them can already run commands. The value of reporting it is
**hygiene** — the same `--` discipline applied everywhere costs nothing and
removes the need to re-derive this argument each time the path changes.

### The class

*An externally-supplied value passed as a positional argument to a command
that also takes options, with no `--` separator.* Membership is mechanical: a
shell variable expanded into an argv position after a command that accepts
`--`, with no `--` preceding it.

### Why the test suite does not catch it

`tests/integration/test_branch_install_gate.py` and
`tests/acceptance/test_guarded_branch_install.py` both set the variable to a
well-formed branch name (`_REF` at `test_guarded_branch_install.py:135`) and
assert on the gate's accept/refuse verdict and the banner text. Neither
supplies a leading-`-` value; there is no test that the ref reaches git as a
*ref* rather than as an option.

### Detector hypothesis

A shell-source rule in `audit_shell.py` (which already owns `.sh`/`.bash`
scanning, the JSON output and the `# shell-audit: allow` marker): flag a
`git`/`gh`/`rm`/`grep` invocation whose last argument is a `"$VAR"` expansion
with no `--` earlier in the argv.

**Likely false positives**: high. Most such invocations are entirely safe, and
the rule would fire dozens of times across `scripts/`. **I would expect this
rule to be suppressed rather than adopted**, and I am reporting it as noisy by
construction. It is listed for completeness, not as a recommendation.

### Confidence

**High** on the mechanism (read directly). **Low** on whether it is worth
acting on, for the privilege-boundary reason above.

---

## What was looked at and found clean

Reported explicitly, because "I looked and found nothing" and "I could not
look" are different results.

- **`scripts/qa/run_corpus_qa.py:91-112`** (new). Argv form built from
  `sys.executable`, `-m`, a module constant, `--project-root`, the verb,
  `--sweep`, `--json`; no shell, `timeout=300`, `check=False`, and the verb
  comes from `argparse` `choices=sorted(CORPORA)` so it cannot be anything
  else. `--root` is operator-supplied but arrives as a single argv word and a
  `cwd`. Clean.
- **`scripts/qa/run_pyright_check.py:188-207`** (new). Argv form, binary
  resolved and `is_file()`-checked before the spawn, `timeout`, `check=False`.
  Clean.
- **`src/claude_code_hooks_daemon/daemon/cli.py:1846-1875`**. The `uv sync`
  and venv-interpreter spawns are unchanged in argv; the delta only wraps each
  in its own `FileNotFoundError` handler so the error names the right missing
  binary. Both remain argv-form with no interpolation. Clean, and the change
  is an improvement.
- **`src/claude_code_hooks_daemon/issue_report/upstream.py:50`**. Builds a
  `gh issue create` command string for the agent to run, so it is the same
  *surface* as N1, but the one runtime value **is** wrapped in `shlex.quote`
  and the other is a module constant. Named here deliberately: it is the
  worked example of the correct shape, in the same interval, which is what
  makes N1 a defect rather than a house-style question.
- **`handlers/session_start/lsp_noise_checker.py:287`**. A `pkill -f` hint
  whose only interpolation is a per-language strategy constant, never runtime
  input. Clean, but it is the nearest false positive for N1's detector and
  should be in that rule's fixture set.
- **`handlers/session_start/persistent_cron_assertor.py:107`**. Emits a cron
  `schedule` and `prompt` from config. This is a prompt surface, not a shell
  command line — out of D-EXEC's scope. Flagged here so the next reviewer does
  not have to re-decide it; if it belongs anywhere it is a prompt-injection
  check, which this inventory does not currently have.
- **`.claude/ccy/claude-supervise.py`**. The pty spawn (`subprocess` + `pty`,
  fixed argv `python3 <self> --worker`) is **unchanged** in this interval —
  the diff touches only an idle/compact comment.
- **`scripts/setup_worktree.sh`**. Two `"${WT_VENV_PATH}/bin/python" - <<'PY'`
  heredocs. The delimiter is quoted so the outer shell expands nothing into
  the interpreter's source, and the one runtime value is passed as argv
  (`- "${WORKTREE_DIR}"`). This is the correct shape, and the exact
  counter-example to the full sweep's F1. Clean.
- **`scripts/upgrade.sh:305-308`**, the daemon clone with
  `protocol.file.allow=always` and `$_CLONE_URL`. Not new in this interval,
  and already registered as open findings in
  `scripts/qa/security-downgrade-inventory.yaml` (D-NET N8 for the protocol
  downgrade, D-NET N5 for the unvalidated URL). Out of D-EXEC's scope and
  already carried elsewhere; recorded here only so it is not re-reported as
  new.
- **`scripts/qa/check_github_urls.py`**, `install/report_offload.py`,
  `daemon/source_fingerprint.py`, `utils/deployed_version.py`,
  `install/install_stamp.py`, all eight `reference_repos/` modules, and the
  eight new `strategies/lsp_noise/` modules: **no process spawn of any kind**.
- **`scripts/debug_info.py`**. The delta adds no `run_command` call site. The
  full sweep's note about its missing timeout stands unchanged.

## Relationship to Routine 00001's full sweep

The full sweep's six findings (F1-F6) are all outside this interval's diff and
none of them regressed within it — I checked each cited file for changes in
`v3.63.0..v3.64.0` and none of the six sites was touched.

The one thing this run changes about the full routine is its **method**, not
its findings: an AST inventory of `subprocess` call sites plus the
generated-shell emitters is not a complete answer to D-EXEC, because this
project's most reliable executor is the agent reading the daemon's own output.
N1 is the first instance; it will not be the last, because every new blocking
handler is under pressure to print a remedy.

If a register category is opened for N1, the honest name for it is
**agent-executed command construction**, and its blind-spot section should
open by saying that the Detector reads only f-strings — a remedy assembled by
a join, by `.format`, or across two statements walks past it.
