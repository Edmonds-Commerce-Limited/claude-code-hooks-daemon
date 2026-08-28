# Hooks daemon: skill scripts break their own sibling `source` via the self-bootstrap re-exec

> **Generalised.** This report arrived from an external installation. Concrete
> process IDs and socket hostname suffixes below have been replaced with
> neutral placeholders per `.claude/rules/importing-reports.md`; the technical
> argument is unchanged.

**Status**: root cause confirmed by A/B experiment
**Component**: `.claude/skills/hooks-daemon/scripts/` (daemon v3.36.0)
**Severity**: high — `/hooks-daemon restart`, `health`, `status`, `logs` and `dev-handlers` are all unusable via the skill
**Affects**: every installation whose skill scripts differ from the latest GitHub release — not just containerised/agent environments

> **Note on the filename.** This file is named `...bash-tool-dollar0-clobber.md` because that
> was the original hypothesis. **That hypothesis is wrong** and is disproved below. The Bash
> tool does not clobber `$0`. A more accurate name would be
> `hooks-daemon-selfbootstrap-dollar0-clobber.md`. The path was kept as requested.

---

## 1. Symptom

Any skill subcommand that routes through `daemon-cli.sh` fails immediately:

```console
$ ./.claude/skills/hooks-daemon/scripts/daemon-cli.sh status
/tmp/tmp.95vIkdnKrw: line 142: /tmp/_resolve-venv.sh: No such file or directory
$ echo $?
1
```

Two things in that message are the whole story:

- the script reporting the error is `/tmp/tmp.95vIkdnKrw`, **not** the script that was invoked;
- it is looking for `_resolve-venv.sh` in `/tmp`, where that file has never existed.

---

## 2. The disproved hypothesis

I originally reported this to the user as a harness artefact:

> "The script does `source "$(dirname "$0")/_resolve-venv.sh"`, and the Bash tool wraps
> commands in a temp script so `$0` is always `/tmp/tmp.*`. Not a project bug and it'll work
> fine from your terminal."

**This was wrong.** A probe script settles it:

```bash
#!/bin/bash
echo "\$0              = $0"
echo "dirname \$0      = $(dirname "$0")"
echo "BASH_SOURCE[0]  = ${BASH_SOURCE[0]}"
```

Run through the same Bash tool, both invocation styles report the **real** path:

```
$0              = /tmp/claude-0/.../scratchpad/probe0.sh
dirname $0      = /tmp/claude-0/.../scratchpad
BASH_SOURCE[0]  = /tmp/claude-0/.../scratchpad/probe0.sh
```

So the tool harness preserves `$0` correctly. The clobbering is done by the daemon's own
scripts, and it will reproduce in an ordinary interactive terminal.

---

## 3. Root cause

`daemon-cli.sh` opens with a self-bootstrap stanza that compares its own sha256 against the
`bootstrap-checksums.txt` manifest published with the latest GitHub release. On mismatch it
downloads the fresh copy to a `mktemp` file and re-executes it:

```bash
# daemon-cli.sh:101-102
chmod +x "$_bootstrap_tmp_fresh"
exec bash "$_bootstrap_tmp_fresh" --already-bootstrapped "$@"
```

After that `exec`, the running script **is** `/tmp/tmp.XXXXXXXX`. The `--already-bootstrapped`
sentinel makes the second pass skip the bootstrap block (line 42) and fall through to the
real work — which, 95 lines later, does:

```bash
# daemon-cli.sh:135-137
DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"
# shellcheck source=_resolve-venv.sh
source "$(dirname "$0")/_resolve-venv.sh"
```

`dirname "$0"` is now `/tmp`, so the sibling `source` looks for `/tmp/_resolve-venv.sh` and
dies.

The bug is a **latent coupling**: the bootstrap relocates the script, and a later line assumes
the script has not moved. Either half is fine alone; together they are broken.

Note the asymmetry in the same function: `PROJECT_ROOT` (line 121-128) is derived robustly by
walking up from `$(pwd)`, and therefore *survives* the re-exec. Only the `$0`-relative lookup
does not. `DAEMON_DIR` on line 135 is consequently **correct even in the failing run** — which
is what makes the fix trivial.

### Why the re-exec branch is always taken here

All three affected scripts differ from the current release manifest, so the mismatch branch
fires on every invocation:

| Script             | Local sha256       | Manifest sha256    | Match |
| ------------------ | ------------------ | ------------------ | ----- |
| `daemon-cli.sh`    | `52e948b8ecd64a9b` | `152bf04955237e4f` | no    |
| `health-check.sh`  | `d242a23f0cdb15bf` | `3b95a7f6f4a64038` | no    |
| `init-handlers.sh` | `bafb388a45bcbb0b` | `46485b6a31e8f699` | no    |

Corroborating evidence: the bootstrap's cache marker directory
`${TMPDIR:-/tmp}/hooks-daemon-bootstrap` **does not exist at all**. That marker is only written
on the sha-*match* path (lines 105-110), which is never reached. So every invocation pays a
network round-trip to GitHub *and* re-execs — there is no cached fast path masking the problem
intermittently.

---

## 4. Proof by A/B experiment

The bootstrap has a documented off switch (`HOOKS_DAEMON_SKIP_BOOTSTRAP=1`, line 37). Toggling
only that variable, changing nothing else, flips the outcome:

```console
$ ./.claude/skills/hooks-daemon/scripts/daemon-cli.sh status
/tmp/tmp.95vIkdnKrw: line 142: /tmp/_resolve-venv.sh: No such file or directory
exit=1

$ HOOKS_DAEMON_SKIP_BOOTSTRAP=1 ./.claude/skills/hooks-daemon/scripts/daemon-cli.sh status
Daemon: RUNNING
PID: 000000
Socket: /workspace/.claude/hooks-daemon/untracked/daemon-<hostname-suffix>.sock (exists)
PID file: /workspace/.claude/hooks-daemon/untracked/daemon-<hostname-suffix>.pid
exit=0
```

Single variable changed, failure fully attributed. `HOOKS_DAEMON_SKIP_BOOTSTRAP=1` is also a
usable workaround in its own right.

---

## 5. Blast radius

Three scripts pair the bootstrap stanza with a `$0`-relative sibling `source`, and all three
are broken:

| Script             | Bootstrap | `source "$(dirname "$0")/…"` | Broken  |
| ------------------ | --------- | ---------------------------- | ------- |
| `daemon-cli.sh`    | yes       | line 137                     | **yes** |
| `health-check.sh`  | yes       | line 146                     | **yes** |
| `init-handlers.sh` | yes       | line 131                     | **yes** |
| `install.sh`       | no        | none (`DAEMON_DIR` at :44)   | no      |
| `upgrade.sh`       | yes       | none                         | no      |

Because `daemon-cli.sh` is the shared entry point, the user-facing damage covers
`/hooks-daemon restart`, `status`, `logs`, `handlers`, `validate-config`, `check`,
`bug-report`, `release-notes` and `regen-docs`, plus `/hooks-daemon health` and
`/hooks-daemon dev-handlers` directly.

`install.sh` and `upgrade.sh` escape for different reasons — `install.sh` has no bootstrap
stanza, and `upgrade.sh` has one but never sources a sibling. That is why upgrading appears to
work while everything else is dead, which makes the failure look environmental rather than
structural.

**This is not container-specific.** Any user whose skill scripts lag the newest release hits
it from a plain terminal. Ironically the trigger is *being out of date*, and the primary tool
for noticing that (`/hooks-daemon health`) is one of the casualties.

---

## 6. Suggested fixes

**Preferred — drop the shim, use the already-correct variable.** `DAEMON_DIR` is computed two
lines earlier and is re-exec-proof. `_resolve-venv.sh` is itself only a thin shim that requires
`DAEMON_DIR` and delegates to the canonical library, so going direct removes a hop as well as
the bug:

```bash
DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"
source "$DAEMON_DIR/scripts/lib/resolve_venv.sh"
PYTHON=$(resolve_venv_python "$DAEMON_DIR")
```

**Alternative — keep the shim, fix the path.** `${BASH_SOURCE[0]}` also tracks the temp file
after an `exec`, so it is *not* sufficient on its own here; anchor to `DAEMON_DIR` instead:

```bash
source "$DAEMON_DIR/scripts/_resolve-venv.sh"   # not "$(dirname "$0")"
```

**Also worth doing — make the class of bug unrepresentable.** The real lesson is that any
`$0`-relative path resolution after a possible `exec` is unsound. A guard in CI that rejects
`dirname "$0"` in scripts carrying the bootstrap stanza would have caught all three sites at
once, and would catch the fourth when someone adds it.

---

## 7. Secondary observation: `restart` exits 143

Using the workaround, `restart` completes successfully but returns **143** (128 + 15,
SIGTERM). The daemon is restarted and healthy afterwards, so this is a wrong exit status rather
than a failed restart — most likely the stop phase signalling the old process and the signal
status propagating out as the script's own result. It will make `restart` look failed to any
caller that checks exit codes (CI, `set -e` wrappers, the supervisor). Worth a separate look.

---

## 8. Verified workaround

Until the fix lands, bypass the skill wrapper entirely:

```bash
export DAEMON_DIR=/workspace/.claude/hooks-daemon
source "$DAEMON_DIR/scripts/lib/resolve_venv.sh"
PYTHON=$(resolve_venv_python "$DAEMON_DIR")
"$PYTHON" -m claude_code_hooks_daemon.daemon.cli restart
```

Or, more simply, keep the wrapper and disable the bootstrap:

```bash
HOOKS_DAEMON_SKIP_BOOTSTRAP=1 ./.claude/skills/hooks-daemon/scripts/daemon-cli.sh restart
```

Both are confirmed working in this environment.
