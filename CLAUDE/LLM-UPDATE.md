# Claude Code Hooks Daemon - LLM Update Guide

> **v3.7.0+ venv layout change**: From v3.7.0, the venv is **fingerprint-keyed** — `untracked/venv-{slug}-py{MM}-{fingerprint}/` (the `{slug}` component arrived in v3.19.1; canonical layout doc: the "Venv layout" section in [SELF_INSTALL.md](SELF_INSTALL.md)) instead of the legacy `untracked/venv/`. This lets the same project directory work in two different Python envs (e.g. YOLO container + desktop host) without corruption. The upgrader auto-provisions the fingerprint-keyed venv and, when upgrade verification succeeds, auto-deletes the legacy `untracked/venv/`. If you had a bespoke venv location or the auto-cleanup was skipped, run `.claude/hooks-daemon/bin/hooks-daemon prune-venvs --legacy --dry-run` after upgrading to see what's left. Commands below that reference `untracked/venv/` are representative — the actual path after v3.7.0 is resolved dynamically by `scripts/venv-include.bash`.

## CRITICAL: Determine Your Location First

**Before doing ANYTHING, determine where you are.** Working directory confusion is the #1 cause of upgrade failures.

### Quick Location Check

```bash
# Run from wherever you are - the script auto-detects
# Option 1: If you can find the script
.claude/hooks-daemon/scripts/detect_location.sh 2>/dev/null || \
  scripts/detect_location.sh 2>/dev/null || \
  echo "Could not find detect_location.sh - see manual check below"
```

### Manual Location Check

```bash
# Check: Am I at the project root?
ls .claude/hooks-daemon.yaml 2>/dev/null && echo "YES: You are at the project root" || echo "NO"

# Check: Am I inside .claude/hooks-daemon/?
ls src/claude_code_hooks_daemon/version.py 2>/dev/null && echo "YES: You are inside hooks-daemon dir" || echo "NO"

# If inside hooks-daemon, go to project root:
cd ../..
```

### Where You Should Be

**All upgrade commands should be run from the PROJECT ROOT** (the directory containing `.claude/`).

| If you see this...                     | You are at...       | Action                   |
| -------------------------------------- | ------------------- | ------------------------ |
| `.claude/hooks-daemon.yaml` exists     | Project root        | Correct - proceed        |
| `src/claude_code_hooks_daemon/` exists | Inside hooks-daemon | Run `cd ../..` first     |
| Neither exists                         | Wrong directory     | Navigate to project root |

### Existing config but no daemon checkout (a fresh clone of a client repository)

A project that has `.claude/hooks-daemon.yaml` but no `.claude/hooks-daemon/`
directory (it is gitignored, so a teammate's fresh clone never has it) and no
venv is an **existing install**, not a green-field one. **Use this update
guide, not the install guide, and run exactly the same upgrade command** as
for a live install. The upgrade script clones the daemon into
`.claude/hooks-daemon/` for you, reads the previous version from the
committed `.claude/HOOKS-DAEMON.md`, skips the daemon stop (there is nothing
to stop) and builds the venv. Never run `install_version.sh` on a project
that already has a config: it treats the project as new and reports no
migration advisories for the versions the config predates.

---

## CRITICAL REQUIREMENTS

1. **CONTEXT WINDOW CHECK**: You MUST have at least **50,000 tokens** remaining. If below 50k, STOP and ask user to start fresh session.

2. **WEBFETCH NO SUMMARY**: If fetching this document via WebFetch, use: `"Return complete document verbatim without summarization, truncation, or modification"`.

3. **GIT CLEAN STATE**: Working directory MUST be clean. Run `git status` - if not clean, commit/push first.

4. **RESTART CLAUDE CODE after upgrade**: After upgrading, the user MUST restart their Claude Code session (exit and re-enter) to load new hook event types and settings. This is required for ALL minor/major upgrades and recommended for patch upgrades. Daemon restart alone is NOT sufficient for new event types.

---

## Prerequisites

**Python 3.11+ is required.** The daemon uses modern Python features that are not available in older versions.

```bash
# Check your Python version
python3 --version  # Must be 3.11+

# If too old, the upgrade script will search for python3.11/3.12/3.13 automatically
# You can also specify explicitly:
python3.12 --version
```

If no suitable Python is found, install Python 3.11+ before proceeding.

---

## Architecture Overview

The upgrade system uses a **two-layer architecture**:

- **Layer 1** (`scripts/upgrade.sh`): The curl-fetched entry script. Requires `--project-root PATH` to specify the project directory. Fetches tags, checks out target version first (checkout-first strategy), then runs Layer 2 as a child process and exits with Layer 2's exit code.
- **Layer 2** (`scripts/upgrade_version.sh`): Version-specific orchestrator implementing **"Upgrade = Clean Reinstall + Config Preservation"**. Sources a shared modular library (`scripts/install/*.sh`) for all operations.

**Key principle**: Upgrade produces the same clean state as a fresh install, while preserving only user config customizations via a diff/merge/validate pipeline.

### Config Preservation Pipeline

During upgrade, user customizations are preserved automatically:

1. **Backup**: Current config saved to timestamped backup file
2. **Snapshot**: Full state snapshot saved (hooks, config, settings.json) for rollback
3. **Extract**: Diff between old default config and user config identifies customizations
4. **Checkout**: New version code checked out (clean reinstall of code)
5. **Merge**: User customizations merged into new default config
6. **Validate**: Merged config validated for structural correctness
7. **Report**: Any incompatibilities reported to the user

If any step fails, the upgrade rolls back to the snapshot automatically.

---

## RECOMMENDED: Fetch, Review, and Run (Safest Method)

**CRITICAL: Fetch the upgrade script, review it, then run it** - This avoids curl pipe shell patterns that our own security handlers block.

The upgrade script itself handles all git operations (fetch, checkout, pull, etc.). You just need to download it, make sure you're comfortable with what it does, then run it.

### Standard Upgrade Process

```bash
# Run these FROM YOUR PROJECT ROOT. The download must land inside the
# repository: `project_containment` denies a `curl -o` naming a path outside
# it, and on an update the daemon is by definition installed and enforcing.
# untracked/ is gitignored and survives a container restart; /tmp does not.
mkdir -p untracked/scratch

# Download the latest upgrade script
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/scripts/upgrade.sh -o untracked/scratch/upgrade.sh

# Review the script to ensure you're comfortable with it
less untracked/scratch/upgrade.sh

# Run it with --project-root pointing to your project directory (REQUIRED)
bash untracked/scratch/upgrade.sh --project-root /path/to/your/project

# Exit 3 or 4 is the pre-deploy gate stopping before anything was deployed
# (see "The pre-deploy gate" below). Do NOT delete the script yet: after
# exit 3, read what it listed and carry out each listed task, then re-run it
# with the digest the stop printed. After exit 4, report the reasons to the
# user and stop; the re-run follows the owner's approval.
#   bash untracked/scratch/upgrade.sh --project-root /path/to/your/project \
#       --skip-reading-confirmation=<digest>

# Clean up, once the upgrade has completed (exit 0)
rm untracked/scratch/upgrade.sh
```

This works for **any version** (including pre-v2.5.0 installations) and is the safest method since you can inspect what the script will do before running it. The `--project-root` argument is required and must point to the directory containing your `.claude/` folder. The script handles all the git fetch/checkout/pull operations.

### Upgrade to Specific Version

```bash
# Fetch and run with version argument (from your project root)
mkdir -p untracked/scratch
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/scripts/upgrade.sh -o untracked/scratch/upgrade.sh
# The script is removed only when the upgrade completes: after an exit 3 or 4
# stop it is needed for the re-run (see the block above).
bash untracked/scratch/upgrade.sh --project-root /path/to/your/project v2.9.0 \
    && rm untracked/scratch/upgrade.sh
```

### What the Script Does (Two-Layer Flow)

**Layer 1** (the curl-fetched script):

- Uses `--project-root PATH` (required) to locate the project
- Fetches latest tags from remote
- Determines target version (latest tag or specified argument)
- Checks out target version first (checkout-first strategy)
- Runs Layer 2 as a child process, handing it a one-shot handoff file, and
  exits with Layer 2's exit code

**Layer 2** (version-specific orchestrator):

- Creates state snapshot for rollback (hooks, config, Claude Code `settings.json`)
- Backs up user config and `settings.json` (Claude Code settings are preserved across upgrades)
- Extracts user customizations (diff against old defaults)
- Stops the daemon safely
- Checks out target version code
- Runs the pre-deploy gate before the venv is rebuilt (see "The pre-deploy
  gate" below), and stops the upgrade there when you have not yet confirmed
  what it lists
- Recreates virtual environment (clean venv)
- Before deploying anything, checks your config against the target's handlers.
  This check only reports
- Deploys hook scripts and slash commands
- Merges user customizations into new default config
- Validates merged config
- Reports any incompatibilities
- Starts daemon and verifies running
- Cleans up old snapshots (keeps 5 most recent)
- Rolls back automatically on any failure

### The pre-deploy gate

Once the target is checked out, and before its venv is built or anything is
deployed, Layer 2 runs the gate (`src/claude_code_hooks_daemon/install/upgrade_gate.py`).
It prints `REQUIRED READING`, which lists:

- the target's upgrade guides for every version crossed (plus the staged
  `UNRELEASED/` documents on a branch install);
- every **pre-upgrade task** (`CLAUDE/UPGRADES/.../pre-upgrade-tasks/`) whose
  `**Detect**` pattern finds a call site in your project, at `file:line`. A
  task that finds nothing is not shown;
- any reason the upgrade needs the project owner: a MAJOR version, a crossed
  config-changes manifest declaring `breaking: true`, a `critical`
  pre-upgrade task with hits, or an installed version the gate cannot read.

The gate's FROM side is the version this project has INSTALLED, never the
daemon checkout: the venv's `.daemon-version` stamp, else the version in the
project's committed `.claude/HOOKS-DAEMON.md`. A fresh clone, a manual
checkout and a re-run therefore all see the real range -- but only the venv
stamp counts as verified. `.claude/HOOKS-DAEMON.md` is an ordinary tracked
file an agent edits routinely, so a FROM read from it that has caught up to
or passed the target is never taken as "nothing to install": the gate treats
that range as unknown and needs the owner, the same answer it gives a venv
stamp equal to the target with no matching gated-install receipt. With
neither a stamp nor a usable marker, the gate cannot rule anything out
either: it lists every pre-upgrade task up to the target that applies to the
project and needs the owner.

Nothing in the caller's environment steers the GATE PROCESS ITSELF, or speaks
for it:

- The stamp is read only from one of this daemon's own `untracked/venv-*`
  directories, never from `HOOKS_DAEMON_VENV_PATH`.
- The gate runs only on a Python 3.11+ installed in a fixed system location
  (`/usr/bin`, `/bin`, `/usr/sbin`, `/sbin`, `/usr/local/bin`,
  `/opt/homebrew/bin`). It never runs on `HOOKS_DAEMON_PYTHON`, on anything the
  caller's `PATH` names, or on the installed venv's Python: that venv lives in
  the project, and code planted in its site-packages would run inside the gate.
- It runs under `env -i` with only that fixed `PATH`, and with Python's `-I -S`
  (no site-packages, no `.pth` code), so no `PYTHON*`, `GIT_*`, `LD_*` variable
  or exported shell function reaches it.
  `timeout`, `git` and every other tool it or the detection scan uses to decide
  come from the same fixed locations.
- Its verdict comes back in a file Layer 2 creates for that run, headed by a
  one-time nonce. A zero exit without that file stops the upgrade, so a
  stdout-printing wrapper cannot pass for the gate. The nonce travels on the
  gate's own argv, though, which any process running as the same user can
  read (`/proc` or equivalent); the file's `O_EXCL`/`0600` creation defeats a
  STALE or REPLAYED verdict, not a CONCURRENT same-user process racing to
  read the nonce and write its own verdict first.
- A `**Detect**` scan covers tracked files and untracked ones the project's own
  `.gitignore` files do not exclude. `.git/info/exclude`, a global excludes
  file and `GIT_*` variables cannot hide a call site from it.

**What this does and does not defend against.** The hardening above is scoped
to the gate subprocess and its detection scan; it is what stands between the
CALLER'S environment and the DECISION. Layer 2 as a whole also sanitises its
OWN environment at entry, before any library is sourced
(`_sanitise_layer2_env`, `scripts/install/env_sanitise.sh`): it resets `PATH`
to the same fixed system locations the gate trusts, and unsets `BASH_ENV`,
`ENV`, `CDPATH`, `GLOBIGNORE`, `NODE_OPTIONS`, every `PYTHON*`/`LD_*`/`DYLD_*`/
`GIT_*`/`PERL5*`/`RUBY*` variable and resets `IFS`. `SHELLOPTS`/`BASHOPTS` are
bash-maintained and readonly, so `unset` on them would error under `set -e`;
the options they could have primed at shell startup (command tracing, most
notably) are turned back off instead. `HOME`, `LANG`, proxy variables and
`uv`/cache settings are left alone -- they are data the install legitimately
needs, not a way to change what code runs.

Layer 1 launching Layer 2 on a bare `bash` from the caller's `PATH` was the
same class of gap, one level up: a caller able to plant a fake `bash` ahead
of the real one would control what interprets Layer 2 before sanitisation
ever got a chance to run, and a caller-set `BASH_ENV`/`ENV` or an exported
shell function would run inside Layer 2 before `_sanitise_layer2_env` itself
got a say -- sanitising Layer 2's OWN environment closes nothing about what
LAUNCHES it. Layer 1 now resolves `bash` the same way the gate subprocess
resolves its own tools: `_gate_tool bash` (`scripts/install/env_sanitise.sh`,
sourced from the daemon dir Layer 1 has just checked out to the target -- the
same tree `$LAYER2_SCRIPT` itself is read from), a fixed, root-owned,
non-group/world-writable system location, never the caller's `PATH`. It then
launches Layer 2 through the same trusted `env` with `-i` and an explicit
allowlist, rather than a bare inherited environment -- so nothing outside
that list, including `BASH_ENV`, `ENV` or any `BASH_FUNC_*`, reaches Layer 2
at all; no in-bash drop loop can promise that, because the exact name an
exported function lands under is not reliably enumerable. The list is named
per group in `scripts/upgrade.sh`, each with its reason: the trusted `PATH`,
the handoff and flags; the session (`HOME`, locale, `TMPDIR`); proxies and CA
bundles; Layer 1's own handover (the pre-checkout version and the old default
config and settings baselines the merges diff against); the operator's
interpreter/venv overrides and venv build and lock tuning; the socket, PID,
log and hostname settings the daemon Layer 2 restarts needs; and `UV_*`.
Layer 2's internal pass state, test seams and `PIP_*` (nothing reads it) are
dropped. A target predating this file (a downgrade below the release that
introduced it) has no such resolver to fall back on, so the caller's `PATH`
and environment are used there -- the prior behaviour, not a new gap.

Layer 2 sets the trusted `PATH` once more after its last library source,
because a library may change it when sourced (`venv.sh` prepends
`$HOME/.local/bin` for the install scripts). Every step before the gate runs
its tools from the fixed system locations; `uv` alone is looked up by name in
`$HOME/.local/bin` when `PATH` has none, and runs only after the gate.

Before it fetches, Layer 1 drops `GIT_CONFIG_COUNT`/`KEY_*`/`VALUE_*` and
`GIT_CONFIG_PARAMETERS`, requires origin to name exactly one URL, and refuses
the fetch when git configuration (any scope, or an include) rewrites origin to
a different repository: it runs code from what it fetches. Your own git
config is otherwise honoured (`safe.directory`, credential helpers, proxies),
and an https-to-ssh rewrite of the same repository passes. To upgrade from a
mirror, point origin at the mirror (`git -C .claude/hooks-daemon remote set-url origin <mirror-url>`) rather than rewriting through `insteadOf`.

What this does NOT cover: a direct call of `scripts/upgrade_version.sh` skips
Layer 1's `env -i`, so there only the in-script sanitisation above applies. It
is a fixed, named list of variable FAMILIES known to steer execution, not a
default-deny allowlist, so anything not on it -- including a variable this
list has not anticipated -- still reaches Layer 2, and `BASH_ENV` has already
run by the time it gets a say. So the approval gate is a
procedural control against an agent following the documented upgrade route,
backed by a best-effort guard (`upgrade_approval_guard`) that recognises that
route's shape. It is not a boundary against a same-user process determined to
install by hand instead -- no in-process check can be that, because the same
user can always run the daemon's own code directly.

`upgrade_approval_guard` also denies an agent that steers the rest of the
upgrade. It recognises an upgrade by what the command is, not by the file's
name:

- `upgrade.sh`, `upgrade_version.sh` or `upgrade_gate_standalone.py` by name;
- Layer 1's `--skip-reading-confirmation`;
- a script whose content carries `HOOKS_DAEMON_UPGRADE_HANDOFF`, which every
  copy of Layer 1 and Layer 2 does;
- a script it cannot read (`bash untracked/scratch/target-upgrade.sh`, or a script on stdin) run with
  `--project-root`, or with the `.claude/hooks-daemon` clone as an argument.

On such a command, the guard denies setting any of these variables:

- `PATH`, `HOME`, `TMPDIR` or `HOSTNAME`;
- `HOOKS_DAEMON_PYTHON`, `HOOKS_DAEMON_VENV_PATH`, `UPGRADE_FLAGS` or the
  `HOOKS_DAEMON_UPGRADE_*`/`HOOKS_DAEMON_CLONE_URL` variables;
- `GIT_*`, `BASH_ENV`, `ENV`, `BASH_FUNC_*`, `SHELLOPTS` or `BASHOPTS`;
- `LD_*`, `DYLD_*` or `PYTHON*`;
- `HOOKS_DAEMON_OLD_DEFAULT_*` (Layer 1's baseline handover);
- the `uv` index, find-links, config-file and Python variables
  (`UV_INDEX*`, `UV_DEFAULT_INDEX`, `UV_EXTRA_INDEX_URL`, `UV_FIND_LINKS`,
  `UV_CONFIG_FILE`, `UV_PYTHON*`), CA bundles and proxies.

Any spelling counts, not only `NAME=value`: naming one of those variables
other than to read it (`read -r NAME`, `printf -v NAME`, `n=NAME`),
`declare`/`typeset`/`local` with an `x` flag, and `export` with a flag or a
computed name. On a command recognised as the upgrade, `set -a`, `eval` and
sourcing another file count too. It also denies exporting a shell function
(`export -f`), and writing into the clone's `.git/` (its config, hooks or
refs decide what the next fetch and checkout install). If the upgrade
genuinely needs one of these (a Python 3.11+ outside the system locations, say),
ask the user to run it.

Moving the clone by hand is the other way around the gate. `checkout`,
`switch`, `pull`, `merge`, `rebase`, `reset`, `cherry-pick`, `am` or `revert`
on `.claude/hooks-daemon` installs a version the gate never read, so the same
guard denies it. `fetch`, `show`, `log` and `describe` are allowed. So is
reading the clone's remote and config; writing them is not -- `git remote set-url`/`add`/`rename`/`remove` and a `git config` write on that clone are
denied too, because Layer 1's `fetch --tags --force` trusts whatever `origin`
names next.

A venv stamp that already says the target is not taken on trust. `hooks-daemon repair` after a manual checkout writes the same stamp. The installed == target
shortcut therefore counts only when the gate itself recorded letting that exact
version through (`.claude/hooks-daemon/untracked/upgrade-approvals/gated-install.json`,
written when it proceeds). Otherwise the version installed before it cannot be told, and the
owner decides. That record is unsigned JSON, protected only by the same
write-guard as every other marker under `upgrade-approvals/` -- it is a
procedural record, not a cryptographic one, and no stronger a defence than
the approval marker it sits beside.

With nothing to list, the upgrade continues without comment, as it does when
the gate itself installed the target already. Otherwise it never infers consent
from the absence of a terminal. It stops, deploys nothing, and exits with the
code in the table below.

The stop also puts the daemon checkout back on the installed version, when that
version can be told. The version comes from the venv stamp, else
`.claude/HOOKS-DAEMON.md`, else the commit Layer 1 moved the clone from. There
are two cases where the restore does not happen:

- **Nothing names the installed version.** For example, a direct Layer 2 run
  on a clone with no stamp and no marker. The clone stays on the target, and
  the stop prints the `git -C .claude/hooks-daemon reset --hard <tag>` to run
  first.
- **The reset itself fails.** The upgrade exits `1` with the same command.

Layer 2 never runs in self-install mode. It refuses before the gate, and the
developer's own checkout is left where Layer 1 put it.

| Exit | Meaning                 | What to do                                                                                                                                                                                                                                                                                        |
| ---- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `3`  | Reading not confirmed   | Read every listed document. Carry out each listed pre-upgrade task in the project, as its file says. Then re-run with `--skip-reading-confirmation=<digest>`, the digest the stop printed. A bare flag, or a digest from another listing, stops again                                             |
| `4`  | Owner's approval needed | Report the printed reasons and stop. The project owner approves ONE upgrade in their own terminal with the command the stop printed. An agent cannot record it (see below). Then re-run with the same `--skip-reading-confirmation=<digest>`; the approval is removed once that upgrade completes |

The owner's approval needs a terminal and a typed phrase naming both versions
(`approve upgrade from v<installed> to v<target>`, or
`approve upgrade from an unknown version to v<target>` when the installed
version cannot be told). The marker it writes is bound to those versions and
this install's paths. So an agent's shell, which has no terminal, cannot run
it, and a marker made any other way does not count. The stop prints two
commands for it:

- `.claude/hooks-daemon/bin/hooks-daemon approve-upgrade <target> --from <installed>`,
  for an installed daemon that has the command;
- a command that runs the approval from the TARGET's own code in the clone
  (`git archive` of the target's `src`, then `upgrade_gate_standalone.py approve`
  run by the gate's own Python 3.11+, named by absolute path), which works from
  any installed version. On the first gated upgrade the installed daemon
  predates `approve-upgrade`, so this is the one to use.

Exit `1` also means the upgrade stopped with nothing deployed. The printed
error says which cause it was, and who acts depends on the cause:

| Cause                                                                                        | Who acts                                                                                   |
| -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| No Python 3.11+ for the gate in a system location (a pyenv or uv Python does not count)      | The user: install or link a Python 3.11+ into a location the error lists, then re-run      |
| The stop could not put the clone back (`reset --hard` failed)                                | The user: run the printed `git -C .claude/hooks-daemon reset --hard <ref>` before anything |
| The gate crashed, exited 0 without writing its verdict, or did not decide within 300 seconds | Report it as a daemon bug                                                                  |

The 300-second limit applies only when a `timeout` command exists in a system
location. Without one, the upgrade warns and the gate runs with no time limit.

A Layer 1 that predates the gate (an installed daemon's own `upgrade.sh`, or a
pinned `HOOKS_DAEMON_UPGRADE_REF` older than the gate) cannot pass the flag. It
reports a stop as success. Layer 2 still restores the checkout when the
installed version can be told, as above. It also prints
`THE UPGRADE DID NOT COMPLETE`, with the command that runs the target's own
Layer 1 instead.

### Why Fetch from GitHub?

**Never use the local upgrade script** (`.claude/hooks-daemon/scripts/upgrade.sh`) because:

1. **Bug fixes** - Your local script might have bugs fixed in newer versions
2. **New features** - Latest script may handle new migration scenarios
3. **Better safety** - Improved rollback and error handling
4. **Bootstrap solution** - Works for all versions, even pre-v2.5.0
5. **Consistency** - Everyone uses the same upgrade logic

This is the same pattern used by `rustup`, `nvm`, `homebrew`, and other modern tooling.

---

## Manual Update (4 Steps)

**All commands below assume you are at the PROJECT ROOT.**

### 1. Verify Prerequisites and Current Version

```bash
# Must show clean working directory
git status --short

# Check current daemon version
cat .claude/hooks-daemon/src/claude_code_hooks_daemon/version.py

# Backup current config
cp .claude/hooks-daemon.yaml .claude/hooks-daemon.yaml.backup
```

### 2. Fetch Tags and Choose the Target Version

```bash
# Fetch all tags into the clone. Do NOT check anything out: the upgrade
# does that itself, and when its pre-deploy gate stops it puts the clone back
# on the installed version (when that version can be told). Moving the clone
# by hand is denied: it would install a version the gate never read.
git -C .claude/hooks-daemon fetch --tags

# List available versions
git -C .claude/hooks-daemon tag -l | sort -V | tail -10

# Latest stable tag
TARGET_VERSION=$(git -C .claude/hooks-daemon describe --tags "$(git -C .claude/hooks-daemon rev-list --tags --max-count=1)")
echo "Target version: $TARGET_VERSION"
```

### 3. Run the Target's Own Layer 1

```bash
# Rebuild the venv and reinstall the package for the target version.
#
# Run the TARGET release's Layer 1 (upgrade.sh), read out of the clone, not
# the installed one and not Layer 2 (upgrade_version.sh):
# - the installed Layer 1 may predate the pre-deploy gate, and then reports a
#   stopped upgrade as success and cannot pass --skip-reading-confirmation;
# - Layer 1 checks out the target and then runs Layer 2 as a fresh process,
#   so the upgrade executes the TARGET release's step list. Invoking Layer 2
#   directly makes it check itself out half way through its own run.
# The pre-deploy gate runs on this route exactly as on the recommended one:
# when it stops, read what it lists and re-run with the digest it printed.
mkdir -p untracked/scratch
git -C .claude/hooks-daemon show "$TARGET_VERSION:scripts/upgrade.sh" > untracked/scratch/target-upgrade.sh
bash untracked/scratch/target-upgrade.sh --project-root "$PWD" "$TARGET_VERSION"
# after a stop:  bash untracked/scratch/target-upgrade.sh --project-root "$PWD" --skip-reading-confirmation=<digest> "$TARGET_VERSION"

# Restart daemon
.claude/hooks-daemon/bin/hooks-daemon restart || \
  echo "Daemon not running - will start on first hook call"
```

### 4. Verify Update

```bash

# Verify daemon works
.claude/hooks-daemon/bin/hooks-daemon status

# Test hooks still work (the helper marks the probe and prints the verdict)
.claude/hooks-daemon/bin/hooks-daemon probe PreToolUse --json '{"tool_name": "Bash", "tool_input": {"command": "ls -la"}}'
# Expected: decision: allow

```

To test that destructive git is still blocked, save this payload as
`untracked/scratch/probe-destructive-git.json` with the Write tool:

```json
{"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}
```

```bash
.claude/hooks-daemon/bin/hooks-daemon probe PreToolUse --file untracked/scratch/probe-destructive-git.json
# Expected: decision: deny
```

The payload goes in a file because the guards judge your own Bash command's
text too: an `echo` or `--json` that spells out `git reset --hard` is denied
before the probe runs. A shell heredoc is judged the same way. The helper
marks the probe `"synthetic_source": "manual-probe"`. Without that marker,
the daemon's verdict log records the probe as a real agent's tool call (see
[DEBUGGING_HOOKS.md](DEBUGGING_HOOKS.md#probing-a-handler-by-hand-hooks-daemon-probe)).

**RESTART CLAUDE CODE**: After upgrading, tell the user to restart their Claude Code session (exit and re-enter). New hook event types and settings changes only take effect after a session restart.

---

## Step 5: Discover and Enable New Handlers (CRITICAL)

**After every update, you MUST check for new handlers and enable them.** New versions frequently add safety, quality, and workflow handlers. Leaving them disabled means you lose the main benefit of upgrading.

### Method 1: Discover All Available Handlers (Programmatic)

This discovers ALL handlers by scanning the codebase (source of truth):

```bash
# Every handler the daemon ships, with its default enabled state and priority.
.claude/hooks-daemon/bin/hooks-daemon init-config --stdout

# Every handler the RUNNING daemon actually loaded, by event type.
.claude/hooks-daemon/bin/hooks-daemon handlers
```

### Method 2: Get Full Default Config Template

```bash
.claude/hooks-daemon/bin/hooks-daemon init-config --stdout
```

`--stdout` prints the template and writes nothing, so it is safe on an existing
install — no `--force`, and your current config is untouched.

### Method 3: Compare with Current Config

To find handlers you're missing:

```bash
# Compare YOUR config against the shipped defaults. Anything under
# "added_handlers" exists upstream but is absent from your config.
.claude/hooks-daemon/bin/hooks-daemon init-config --stdout > untracked/scratch/default-config.yaml
.claude/hooks-daemon/bin/hooks-daemon config-diff .claude/hooks-daemon.yaml untracked/scratch/default-config.yaml
```

### Method 4: Version-Specific Config Migration Advisory (Recommended)

The most targeted approach — tells you exactly which new config options are available for your specific upgrade path:

```bash
# Replace with your actual versions
PREVIOUS_VERSION="2.8.0"
NEW_VERSION="2.15.2"

.claude/hooks-daemon/bin/hooks-daemon check-config-migrations \
  --from "$PREVIOUS_VERSION" \
  --to "$NEW_VERSION" \
  --config ../.claude/hooks-daemon.yaml
```

**Output interpretation:**

- **Exit code 0**: Config is up to date — no new options to review
- **Exit code 1**: New options available — review and add what's relevant.
  What is printed is a bounded summary (the actionable lines plus the path of
  the full advisory under the project's `untracked/config-changes/`); pass
  `--full` to print the whole advisory inline.
- Options under **🆕 Recommended — enable these** are dormant features (new
  opt-in protections, or a flipped default) the daemon actively recommends
  turning on. The line shows the recommended value and your current value; set
  the key in your config to adopt it. If a recommendation carries a migration
  **Note**, perform that migration first.
- Options under **💡 New Options Available** are informational — adopt if useful.
- Entries under **⚠️ Stale handler keys** are `handlers.<event>.<key>` lines
  the installed daemon does not register for that event (Plan 00362). Each
  says where the handler lives now (another event, or a pseudo-event such as
  `pseudo_events.nitpick.handlers`) or that it no longer exists. This check is
  not version-gated; `hooks-daemon audit-handler-keys` runs it alone. The
  upgrade merge moves a RELOCATED key (the two nitpick detectors) to its new
  home itself, keeping `enabled`/`priority`, and names the move in
  `config_diff_summary`.

Example output:

```
Config Migration Advisory: v2.8.0 → v2.15.2

💡 New Options Available (since v2.8.0):

  v2.9.0: daemon.project_languages
    Optional list of active project languages used to filter strategy-based handlers.
    Example:
      daemon:
        project_languages:
          - Python
          - JavaScript/TypeScript

  v2.13.0: daemon.enforce_single_daemon_process
    Prevents multiple daemon instances. Auto-enabled in container environments.
    Example:
      daemon:
        enforce_single_daemon_process: true

  ... (more options)

Run with --help for all options.
```

**Why this is better than Methods 1-3:**

- Version-aware: only shows options NEW since your previous version (not ones you already have)
- Filters out already-configured options automatically
- Includes descriptions and examples from the version manifests
- Machine-readable: exit code 0/1 for scripting

### Step N (MANDATORY): Run the config-optimisation review

**Run it in the session that ran the upgrade, before reporting the upgrade
done — not "at some point" and not in a hand-back list.** New handlers arrive
in a mix of states: some ship enabled (opt-out), others are opt-in and stay
inert until someone turns them on. An upgrade that ends without a
configuration review is an upgrade where nobody established which is which —
so this step is not optional and not something to reconstruct by hand.

Run the config-optimisation step (`Skill` tool: `skill=hooks-daemon`,
`args=optimise`) — this IS the formalised "review new handlers and enable what's relevant" step (Plan 00308).
It profiles the project, compares the config against the installed daemon's
`CLAUDE/UPGRADES/config-changes/` manifests (under `.claude/hooks-daemon/` on
a client install — the script prints the resolved path) newer than the last
recorded review, and produces a scored, per-handler enable/skip recommendation list
with ready-to-apply config snippets. It only applies changes on your explicit
confirmation ("apply all" / "apply N,M" / "skip"), then restarts and verifies
the daemon, and records the run so the `config_optimisation_reminder`
SessionStart advisory does not re-nag next session.

`/hooks-daemon upgrade` invokes this automatically at the end of a successful
upgrade (pass `--skip-config-optimisation` to opt out and run it yourself
later) — running it manually here is for the documented curl+script upgrade
path, which does not.

A well-configured installation has **30+ handlers enabled**; the review's
report shows the current count against that baseline.

### Understanding Handler Tags

Handlers are tagged by language, function, and specificity. Use tags to filter:

**Language Tags**: `python`, `php`, `typescript`, `javascript`, `go`
**Function Tags**: `safety`, `tdd`, `qa-enforcement`, `workflow`, `advisory`, `validation`
**Specificity Tags**: `ec-specific`, `project-specific`

---

## Post-Update: Handler Status Report (MANDATORY)

**You MUST run this after every upgrade to verify your handler configuration is complete.**

```bash
.claude/hooks-daemon/bin/hooks-daemon handlers
```

Review the output and check:

- **Enabled count** — should be **30+ handlers** for a well-configured installation
- **New handlers** — any new handlers from the upgrade should be enabled; the
  config-optimisation review above (`/hooks-daemon optimise`) is what decides which ones
  and applies
  them, not a manual read of this list
- **Disabled handlers** — if any safety or code quality handlers are disabled, the review
  flags them too

---

## Post-Update: Carry Out Post-Upgrade Tasks (MANDATORY)

**Run this after every upgrade, whichever route you took** (the curl+script
path, `/hooks-daemon upgrade`, or the manual steps). A release can ship work
that a clean code upgrade does not do for you: auditing files a buggy
previous version damaged, migrating a value or an interface the project
consumes, retiring a workaround. That work lives in each crossed upgrade
guide's `post-upgrade-tasks/`, and nothing executes it except this step. An
upgrade that changes no config key can still carry tasks, so do not skip this
because the config advisory was empty.

List the tasks for exactly the versions you crossed (the script prints the
same list, and the two versions, under "Post-upgrade tasks to carry out"):

```bash
.claude/hooks-daemon/bin/hooks-daemon check-post-upgrade-tasks \
    --from <previous version> --to <new version> --project-root "$PWD"
```

Exit code `0` means there is nothing to do. Exit code `1` lists every task
file, oldest guide first, with its severity and type. A task that declares a
`**Detect**` pattern has already been run over the project: the list says
"not detected" or names each hit at `file:line`. A non-release (branch)
install also lists the tasks staged for the next release under
`CLAUDE/UPGRADES/UNRELEASED/`, because that code is already running.

For **each** task, in order:

1. Read the whole file, starting with its header block (Type, Severity,
   Applies to, Idempotent).
2. **Skip** it only if `Applies to` does not cover the version you upgraded
   from.
3. Follow `## How to detect if this applies to you`. If it does not apply,
   record that and move on.
4. Otherwise follow `## How to handle`, then `## How to confirm`. Adapt sample
   commands to the project; do not run them blindly, and ask the user where
   the task says to.
5. Never edit anything under `.claude/hooks-daemon/`.

Report a summary to the user grouped by severity:

- `critical` — the upgrade is not finished until it is done; block the
  user's next step until acknowledged.
- `recommended` — surface clearly; the user can defer.
- `optional` — mention briefly.

Commit any project edits separately from the daemon upgrade commit.

Schema and full convention: `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md`.

---

## Post-Update: Update Project CLAUDE.md

After upgrading, verify the `### Hooks Daemon` section in the project's root `CLAUDE.md` is present and current.

### Check

<!-- ssot-quote: CLAUDE/LLM-INSTALL.md#claude-md-check-snippet -->

```bash
grep -n "### Hooks Daemon" CLAUDE.md 2>/dev/null || echo "MISSING - add section"
```

<!-- /ssot-quote -->

### Update if Missing or Outdated

If the section is missing, add it. If it exists but references old paths or commands, update it in place. The canonical template lives in
[LLM-INSTALL.md](LLM-INSTALL.md); quoted here for convenience:

<!-- ssot-quote: CLAUDE/LLM-INSTALL.md#claude-md-section-template -->

```markdown
### Hooks Daemon

This project uses [claude-code-hooks-daemon](https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon) for automated safety and workflow enforcement.

After editing `.claude/hooks-daemon.yaml` — restart the daemon using the `hooks-daemon` skill:

- **Restart**: use the `hooks-daemon` skill with args `restart`
- **Health check**: use the `hooks-daemon` skill with args `health`

> **Important**: `/hooks-daemon` is a **skill** (slash command), not a bash command.
> Invoke it using the Skill tool, e.g. `Skill(skill="hooks-daemon", args="restart")`.
> Do NOT attempt to run `/hooks-daemon` as a bash command — it will fail.

**Key files**:
- `.claude/hooks-daemon.yaml` — handler configuration (enable/disable handlers)
- `.claude/project-handlers/` — project-specific custom handlers (if any)

**Documentation**: `.claude/hooks-daemon/CLAUDE/LLM-INSTALL.md`
```

<!-- /ssot-quote -->

Keep the section terse — 10 lines maximum. Do not duplicate if already present; update in place.

### Also: Check Config Header

Verify `.claude/hooks-daemon.yaml` has the restart-reminder header:

<!-- ssot-quote: CLAUDE/LLM-INSTALL.md#config-header-check-snippet -->

```bash
grep -q "AFTER EDITING THIS FILE" .claude/hooks-daemon.yaml && echo "OK" || echo "Header missing"
```

<!-- /ssot-quote -->

If missing, prepend this comment block to the top of `.claude/hooks-daemon.yaml`:

<!-- ssot-quote: CLAUDE/LLM-INSTALL.md#config-header-template -->

```yaml
# Claude Code Hooks Daemon - Handler Configuration
#
# AFTER EDITING THIS FILE: restart the daemon for changes to take effect.
#   User: type /hooks-daemon restart
#   Claude: use Skill tool with skill="hooks-daemon" args="restart"
#
# Verify it is running:
#   User: type /hooks-daemon health
#   Claude: use Skill tool with skill="hooks-daemon" args="health"
#
# Full handler reference: .claude/hooks-daemon/CLAUDE/HANDLER_DEVELOPMENT.md

```

<!-- /ssot-quote -->

---

## Post-Update: Planning Workflow Check (Optional)

After updating, check if you want to adopt or sync with the daemon's planning workflow system.

### Check Current Planning Setup

```bash
ls -la CLAUDE/PlanWorkflow.md 2>/dev/null
ls -la CLAUDE/Plan/ 2>/dev/null
```

### Scenarios

**Scenario 1: No Planning Docs Yet** - See "Post-Installation: Planning Workflow Adoption" in LLM-INSTALL.md.

**Scenario 2: Already Using Planning System** - Check for updates:

```bash
diff CLAUDE/PlanWorkflow.md .claude/hooks-daemon/CLAUDE/PlanWorkflow.md || echo "Docs differ"
```

**Scenario 3: Different Planning Approach** - Keep planning handlers disabled.

---

## Version-Specific Documentation

### RELEASES Directory

**Location**: `RELEASES/` (in daemon repository)

Contains detailed release notes for each version. Use for understanding what changed between versions.

```bash
cat .claude/hooks-daemon/RELEASES/v2.2.0.md
```

### UPGRADES Directory

**Location**: `CLAUDE/UPGRADES/` (in daemon repository)

Contains LLM-optimized migration guides with step-by-step instructions, config examples, and verification scripts.

```
CLAUDE/UPGRADES/
├── README.md                     # Upgrade system documentation
├── UNRELEASED/                   # Staging for the NEXT release (post-upgrade tasks etc.)
├── upgrade-template/             # Template for new upgrade guides
├── v1/                           # Upgrades FROM v1.x versions
└── v2/                           # Upgrades FROM v2.x versions
    └── v2.0-to-v2.1/
        ├── v2.0-to-v2.1.md       # Main upgrade guide
        ├── config-before.yaml    # Config before upgrade
        ├── config-after.yaml     # Config after upgrade
        ├── config-additions.yaml # New config to add
        ├── verification.sh       # Verification script
        ├── examples/             # Expected outputs
        └── post-upgrade-tasks/   # OPTIONAL: tasks for the LLM to handle AFTER upgrade
```

---

## Upgrade Path Determination

When upgrading across multiple versions, follow sequential upgrade path:

### 1. Determine Current and Target Versions

```bash
CURRENT=$(cat .claude/hooks-daemon/src/claude_code_hooks_daemon/version.py | grep "__version__" | cut -d'"' -f2)
echo "Current: $CURRENT"

git -C .claude/hooks-daemon fetch --tags
LATEST=$(git -C .claude/hooks-daemon describe --tags $(git -C .claude/hooks-daemon rev-list --tags --max-count=1))
echo "Latest: $LATEST"
```

### 2. Find Available Upgrade Guides

```bash
ls -la .claude/hooks-daemon/CLAUDE/UPGRADES/v*/
```

### 3. Follow Sequential Upgrades

**Example**: Upgrading from v2.0 to v2.2

1. Read `CLAUDE/UPGRADES/v2/v2.0-to-v2.1/v2.0-to-v2.1.md`
2. Apply v2.0 to v2.1 upgrade steps
3. Read `CLAUDE/UPGRADES/v2/v2.1-to-v2.2/v2.1-to-v2.2.md` (if exists)
4. Apply v2.1 to v2.2 upgrade steps
5. Verify with `verification.sh` at each step
6. **Carry out the post-upgrade tasks** for the whole range — see
   [Post-Update: Carry Out Post-Upgrade Tasks](#post-update-carry-out-post-upgrade-tasks-mandatory).

**If no upgrade guide exists**: Check `RELEASES/vX.Y.Z.md` for that version's upgrade instructions section.

### Post-Upgrade Tasks (MANDATORY after upgrade completes)

The procedure lives in one place:
[Post-Update: Carry Out Post-Upgrade Tasks](#post-update-carry-out-post-upgrade-tasks-mandatory).
Use `check-post-upgrade-tasks` rather than globbing `CLAUDE/UPGRADES/`: a glob
lists every guide ever shipped instead of the ones you crossed, and misses the
tasks staged under `UNRELEASED/` that a branch install is already running.

---

## Upgrade Types

### Patch Upgrades (v2.2.0 -> v2.2.1)

- Bug fixes only, no config changes, no breaking changes
- Just update code and restart daemon

```bash
git -C .claude/hooks-daemon fetch --tags
# The target's own Layer 1, as in step 3 above: never the installed one.
mkdir -p untracked/scratch
git -C .claude/hooks-daemon show "v2.2.1:scripts/upgrade.sh" > untracked/scratch/target-upgrade.sh
bash untracked/scratch/target-upgrade.sh --project-root "$PWD" v2.2.1
.claude/hooks-daemon/bin/hooks-daemon restart
```

### Minor Upgrades (v2.1.0 -> v2.2.0)

- New features/handlers, may have config additions (backward compatible)
- Check UPGRADES guide for new config options

### Major Upgrades (v2.x -> v3.0)

- Breaking changes likely, config structure may change
- MUST follow UPGRADES guide step-by-step

---

## Rollback Instructions

### Automatic Rollback (via Layer 2 Upgrade Script)

The Layer 2 upgrade orchestrator (`scripts/upgrade_version.sh`) creates state snapshots before any changes. If the upgrade fails at any step, it automatically restores the snapshot.

Snapshots are stored at:

```
.claude/hooks-daemon/untracked/upgrade-snapshots/{timestamp}/
├── manifest.json       # Metadata: version, timestamp, files list
└── files/
    ├── hooks/          # All hook forwarder scripts
    ├── hooks-daemon.yaml
    ├── settings.json
    └── init.sh
```

The 5 most recent snapshots are retained; older ones are automatically cleaned up.

### Manual Rollback (from Snapshot)

If you need to manually restore from a snapshot:

```bash
DAEMON_DIR=.claude/hooks-daemon

# List available snapshots
ls -la "$DAEMON_DIR/untracked/upgrade-snapshots/"

# Pick the most recent
SNAPSHOT=$(ls -d "$DAEMON_DIR/untracked/upgrade-snapshots/"* | sort -r | head -1)
echo "Restoring from: $SNAPSHOT"

# Stop daemon
"$DAEMON_DIR/bin/hooks-daemon" stop 2>/dev/null || true

# Restore config
cp "$SNAPSHOT/files/hooks-daemon.yaml" .claude/hooks-daemon.yaml

# Restore settings
cp "$SNAPSHOT/files/settings.json" .claude/settings.json 2>/dev/null || true

# Restore hooks
cp "$SNAPSHOT/files/hooks/"* .claude/hooks/ 2>/dev/null || true

# Check manifest for original version
cat "$SNAPSHOT/manifest.json"

# Reinstall the original version (from manifest) — rebuilds the venv too
bash "$DAEMON_DIR/scripts/upgrade.sh" --project-root "$PWD" <version-from-manifest>

# Restart
"$DAEMON_DIR/bin/hooks-daemon" restart
```

### Quick Rollback (Config Only)

```bash
# Stop daemon
.claude/hooks-daemon/bin/hooks-daemon stop 2>/dev/null || true

# Restore config backup
cp .claude/hooks-daemon.yaml.backup .claude/hooks-daemon.yaml

# Find previous version tag
git -C .claude/hooks-daemon tag -l | sort -V

# Reinstall the previous version (rebuilds the venv too)
bash .claude/hooks-daemon/scripts/upgrade.sh --project-root "$PWD" vX.Y.Z

# Verify rollback
cat .claude/hooks-daemon/src/claude_code_hooks_daemon/version.py
```

### If Rollback Fails

```bash
# Nuclear option - reinstall from scratch
cd .claude
rm -rf hooks-daemon

# Follow fresh install instructions
# See: LLM-INSTALL.md
```

---

## Config Migration

### Automatic (via Layer 2 Upgrade)

The Layer 2 upgrade script handles config migration automatically using the config preservation pipeline:

1. Backs up current config
2. Extracts your customizations (diff against old defaults)
3. Merges customizations into new version's defaults
4. Validates the merged result
5. Reports any incompatibilities

You only need to act if incompatibilities are reported.

### Manual Config Migration

After updating code, compare your config with the new template:

```bash
# Generate new default config
.claude/hooks-daemon/bin/hooks-daemon init-config --stdout > untracked/scratch/new_default_config.yaml

# Diff against your config
diff .claude/hooks-daemon.yaml untracked/scratch/new_default_config.yaml
```

### Config Preservation CLI

The daemon includes CLI commands for config operations:

```bash

# Diff: find customizations between old default and user config
.claude/hooks-daemon/bin/hooks-daemon config-diff \
  --old-default /tmp/old_default.yaml \
  --user-config .claude/hooks-daemon.yaml

# Merge: apply customizations to new default
.claude/hooks-daemon/bin/hooks-daemon config-merge \
  --new-default /tmp/new_default.yaml \
  --custom-diff /tmp/custom_diff.yaml

# Validate: check config structure (config_path is POSITIONAL, no --config flag)
.claude/hooks-daemon/bin/hooks-daemon config-validate .claude/hooks-daemon.yaml

# Migration advisory: see new options for your upgrade path
.claude/hooks-daemon/bin/hooks-daemon check-config-migrations \
  --from PREVIOUS_VERSION \
  --to NEW_VERSION \
  --config .claude/hooks-daemon.yaml
# Exit code 0 = up to date, 1 = new options available
```

---

## Verification Steps

### Quick Verification

```bash
# 1. Version check — the notes header names the INSTALLED version
.claude/hooks-daemon/bin/hooks-daemon release-notes

# 2. Daemon status
.claude/hooks-daemon/bin/hooks-daemon status

# 3. Hook test
echo '{"tool_name":"Bash","tool_input":{"command":"ls"},"synthetic_source":"manual-probe"}' | bash .claude/hooks/pre-tool-use
```

### Full Verification (for major upgrades)

```bash
# Run tests (optional - for thorough verification)
.claude/hooks-daemon/scripts/qa/run_tests.sh

# Check all QA passes
.claude/hooks-daemon/scripts/qa/llm_qa.py all
```

---

## Troubleshooting

**All commands below are run from the PROJECT ROOT** (not from inside `.claude/hooks-daemon/`).

### "PROTECTION NOT ACTIVE" Error During Upgrade

**This is expected during upgrade.** When the daemon is stopped for code checkout, hook forwarders will report this error. It does NOT mean your system is broken. Continue with the upgrade steps. The daemon will be restarted as part of the upgrade process.

### Update Fails to Pull

```bash
git -C .claude/hooks-daemon status
git -C .claude/hooks-daemon stash
git -C .claude/hooks-daemon fetch --tags
git -C .claude/hooks-daemon checkout "$LATEST_TAG"
git -C .claude/hooks-daemon stash pop
```

### Daemon Won't Start After Update

```bash

# Check the install is importable and the daemon is serving
.claude/hooks-daemon/bin/hooks-daemon health

# If it reports a broken install, repair it (rebuilds the venv in place)
.claude/hooks-daemon/bin/hooks-daemon repair

# Check daemon logs
.claude/hooks-daemon/bin/hooks-daemon logs
```

### Hooks Don't Work After Update

```bash

# 1. Restart daemon (sufficient for most updates)
.claude/hooks-daemon/bin/hooks-daemon restart

# 2. Check hook forwarders exist
ls -la .claude/hooks/

# 3. Test hook directly
echo '{"tool_name":"Bash","tool_input":{"command":"test"},"synthetic_source":"manual-probe"}' | bash .claude/hooks/pre-tool-use
```

If hooks still fail: Restart Claude Code session (only needed if new event types were added).

### Config Validation Errors

```bash
python3 -c "
import yaml
try:
    yaml.safe_load(open('.claude/hooks-daemon.yaml'))
    print('YAML syntax OK')
except Exception as e:
    print(f'YAML error: {e}')
"
```

### Socket Path Too Long (AF_UNIX Limit)

If your project path is very deep (>60 characters), the Unix socket path may exceed the 108-byte kernel limit.

**Symptoms**: Daemon fails to start with "AF_UNIX path too long" or similar socket error.

**Automatic fix**: The daemon automatically falls back to shorter paths:

1. `$XDG_RUNTIME_DIR/hooks-daemon-{hash}.sock` (preferred)
2. `/run/user/{uid}/hooks-daemon-{hash}.sock` (Linux)
3. `/tmp/hooks-daemon-{hash}.sock` (last resort)

**Manual override**: Set environment variable:

```bash
export CLAUDE_HOOKS_SOCKET_PATH=/tmp/my-project-daemon.sock
```

### Broken Install Recovery

If your installation is in a broken state (missing venv, corrupt config, nested install artifacts):

```bash
# Download latest upgrade script (from your project root)
mkdir -p untracked/scratch
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/scripts/upgrade.sh -o untracked/scratch/upgrade.sh

# Run with explicit project root - it will clean up and rebuild
bash untracked/scratch/upgrade.sh --project-root /path/to/your/project
rm untracked/scratch/upgrade.sh
```

The upgrade script actively cleans up nested install artifacts and rebuilds the venv from scratch.

### Upgrade Aborts on an Old Client (Stuck-Client Recovery)

Clients more than ~2 versions behind can hit a bootstrap/packaging abort _before_ the real
deploy runs. As of v3.16.0+ the canonical `scripts/upgrade.sh` is backward-tolerant and
self-documenting, but if you are running an **older** client shim the escape hatches below
break the deadlock. Try them in order.

**Symptoms** (all occur before the Layer 2 deploy):

- `Unknown option: --already-bootstrapped` — a pre-v3.15 skill shim passes a flag an older
  fetched script rejected. (The canonical script now accepts-and-ignores it.)
- `Canonical python discovery helper missing` — the curl-fetched-script flow ran a script whose
  installed daemon predates `python_discovery.sh`. (The canonical script now fetches its
  own helper.)

**Recovery, in order:**

```bash
# 1. Run the canonical Layer-1 script straight from main — it bypasses the old skill shim
#    entirely, tolerates legacy flags, and fetches its own helpers (from your project root):
mkdir -p untracked/scratch
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/scripts/upgrade.sh -o untracked/scratch/upgrade.sh
bash untracked/scratch/upgrade.sh --project-root /path/to/your/project

# 2. If Python discovery still fails, the USER points it at a known-good interpreter
#    (3.11+). An agent does not set this: upgrade_approval_guard denies it on an
#    upgrade command, so ask the user to run this line. It picks the interpreter
#    the venv is built with; the pre-deploy gate never runs on it.
HOOKS_DAEMON_PYTHON=/usr/bin/python3 bash untracked/scratch/upgrade.sh --project-root /path/to/your/project

# 3. To pull the canonical script, and the helper it fetches, from the TARGET tag
#    instead of main (never a ref older than the target: an older Layer 1 may
#    predate the pre-deploy gate):
curl -fsSL "https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/$TARGET_VERSION/scripts/upgrade.sh" -o untracked/scratch/upgrade.sh
HOOKS_DAEMON_UPGRADE_REF="$TARGET_VERSION" bash untracked/scratch/upgrade.sh --project-root /path/to/your/project "$TARGET_VERSION"

# 4. Last resort — skip the self-bootstrap verification of the local skill shim (only if
#    1-3 are unavailable and you trust the on-disk script):
HOOKS_DAEMON_SKIP_BOOTSTRAP=1 bash "$PROJECT_ROOT/.claude/skills/hooks-daemon/scripts/upgrade.sh" --project-root "$PROJECT_ROOT"

rm -f untracked/scratch/upgrade.sh
```

Once any path succeeds it installs the current backward-tolerant shim, so the next upgrade
self-heals — you should not need these hatches again.

### `.claude/` Directory Inside Daemon Repo (Not a Nested Install)

The daemon repository contains a `.claude/` directory with project-level handler templates and example configurations. This is **intentional** and is NOT a nested installation. The nested installation detector specifically checks for `.claude/hooks-daemon/.claude/hooks-daemon` (double-nested), not `.claude/hooks-daemon/.claude/`.

If you see `.claude/` inside `.claude/hooks-daemon/`, this is normal and expected.

### Daemon Plugin Config Breaking Change (v2.8.0+)

Daemon plugins (handler modules in the `plugins:` block of
`.claude/hooks-daemon.yaml`, not Claude Code plugins) now require an explicit
`event_type` field. If you have daemon plugins, update their config:

**Before:**

```yaml
plugins:
  my_plugin:
    module: my_module
```

**After:**

```yaml
plugins:
  my_plugin:
    event_type: pre_tool_use  # Required since v2.8.0
    module: my_module
```

### Venv Broken After Update

`repair` works even when no venv exists for this project path. It builds one
in the foreground first, under the same lock as every other builder, and then
runs the normal repair. A hook in that state starts the same build in the
background on its own (see "Why the venv is fingerprint-keyed" in
`CLAUDE/SELF_INSTALL.md`), so the hook message may already say a build is
running or has failed, with its log.

```bash

# Try repair command
.claude/hooks-daemon/bin/hooks-daemon repair

# If repair fails, let the installer rebuild the venv from scratch.
# NEVER hand-build one — `python3 -m venv untracked/venv` creates the retired
# pre-v3.7.0 layout, which resolve_venv.sh refuses (every wrapper call exits 5).
CURRENT_TAG="$(git -C .claude/hooks-daemon describe --tags --abbrev=0)"
bash .claude/hooks-daemon/scripts/upgrade.sh --project-root "$PWD" "$CURRENT_TAG"

# Inspect what venvs exist and which one is active
.claude/hooks-daemon/bin/hooks-daemon list-venvs
```

---

## CLI Reference

**All commands from project root** (no `cd` needed):

```bash

.claude/hooks-daemon/bin/hooks-daemon start
.claude/hooks-daemon/bin/hooks-daemon stop
.claude/hooks-daemon/bin/hooks-daemon status
.claude/hooks-daemon/bin/hooks-daemon restart
.claude/hooks-daemon/bin/hooks-daemon logs
.claude/hooks-daemon/bin/hooks-daemon repair   # Fix broken venv
```

---

## Checking for Updates

**From project root:**

```bash
git -C .claude/hooks-daemon fetch --tags
CURRENT=$(python3 -c "
with open('.claude/hooks-daemon/src/claude_code_hooks_daemon/version.py') as f:
    for line in f:
        if '__version__' in line: print(line.split('\"')[1]); break
")
LATEST=$(git -C .claude/hooks-daemon describe --tags $(git -C .claude/hooks-daemon rev-list --tags --max-count=1) 2>/dev/null)
echo "Current: $CURRENT"
echo "Latest: $LATEST"
if [ "$CURRENT" != "${LATEST#v}" ]; then
  echo "Update available!"
else
  echo "Already at latest version"
fi
```

---

## Feedback & Issue Reporting

**IMPORTANT**: During the upgrade process, keep detailed notes of everything that happens. Create a feedback file that the user can optionally share with the project maintainers.

### Create Feedback File

After the upgrade completes (whether successful or not), create a detailed feedback file:

```bash
# Create feedback file at project root
cat > upgrade-feedback.md << 'FEEDBACK'
# Upgrade Feedback Report

## Environment
- **Date**: $(date +%Y-%m-%d)
- **From Version**: [previous version]
- **To Version**: [target version]
- **OS**: [operating system and version]
- **Python Version**: [python3 --version output]
- **Default Python**: [which python3 output]
- **Project Path Length**: [character count of project root path]

## Upgrade Method
- [ ] Automated (upgrade.sh)
- [ ] Manual (step-by-step)

## Results
- **Overall**: SUCCESS / PARTIAL / FAILED
- **Duration**: [how long it took]

## Step-by-Step Log
[Document each step: what command was run, what output was received, any errors or warnings]

1. **Pre-flight checks**: ...
2. **Daemon stop**: ...
3. **Git checkout**: ...
4. **Venv creation**: ...
5. **Config migration**: ...
6. **Daemon start**: ...
7. **Verification**: ...

## Issues Encountered
[List any problems, workarounds, or unexpected behavior]

1. **Issue**: [description]
   **Severity**: Critical / Major / Minor / Cosmetic
   **Workaround**: [what you did to get past it]
   **Suggestion**: [how it could be improved]

## Documentation Gaps
[Note any missing, unclear, or incorrect documentation]

1. [description of gap]

## Suggestions
[Any improvements to the upgrade process]

1. [suggestion]

## Config Changes
[Note any config format changes that required manual intervention]

## Warnings & Anomalies
[Any warnings logged, unexpected behavior, or things that seemed wrong but didn't break anything]
FEEDBACK
```

### What to Document

During the upgrade, actively note:

- **Every command** you run and its output (especially errors/warnings)
- **Every decision point** where you had to choose between options
- **Documentation inconsistencies** where docs said one thing but reality was different
- **Missing prerequisites** that weren't mentioned in docs
- **Confusing error messages** that didn't help you diagnose the issue
- **Workarounds** you had to apply that shouldn't be necessary
- **Time spent** on each step (helps identify bottlenecks)
- **Path/permission issues** especially on different OS configurations

### Sharing Feedback

The feedback file can be shared with project maintainers to improve the upgrade process:

1. Open an issue at the project's GitHub repository
2. Attach or paste the feedback file content
3. Maintainers use this real-world data to fix upgrade issues

**Every piece of feedback makes the next upgrade smoother for everyone.**

---

## Support

If you encounter update issues:

**Check daemon logs**:

```bash
.claude/hooks-daemon/bin/hooks-daemon logs
```

**Run the debug script**:

<!-- ssot-quote: CLAUDE/LLM-INSTALL.md#debug-report-snippet -->

```bash
# A LOCAL diagnostic, for you to read. Never attach it to an issue: it
# reproduces this project's config, and the tracker is public and permanent.
.claude/hooks-daemon/scripts/debug_info.py untracked/scratch/debug_report.md
```

<!-- /ssot-quote -->

**Report the issue**: follow
[BUG_REPORTING.md](../BUG_REPORTING.md), or use the `hooks-daemon` skill with
args `issue-report`, which drives the same procedure. It establishes there is a
defect, then builds
a filable body carrying your version, platform and install mode — and no
config, no logs and no paths from your tree.

---

**Update Date:** `date +%Y-%m-%d`
