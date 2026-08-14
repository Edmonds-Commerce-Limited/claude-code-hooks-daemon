# Task: Files your daemon already created are world-writable — audit and fix them

**Type**: audit
**Severity**: recommended
**Applies to**: every project whose daemon has ever run
**Idempotent**: yes

## Why

Every daemon released before this version daemonised with `os.umask(0)`, clearing
its file-creation mask entirely. That is the textbook daemonise step (Stevens,
*APUE*) and it is safe **only** for a daemon that passes an explicit mode to every
single create. This one did so at exactly **one of 98** create sites.

So everything the daemon wrote landed `0666` (files) and `0777` (directories) —
readable *and writable* by every local user on the machine. On the daemon's own
repository that measured as 10 files and 4 directories, including:

- `untracked/logs/hooks/verdicts.jsonl` — what every handler decided about every
  tool call, including the command strings
- `untracked/payload-capture/` — raw hook payloads, which include the full body of
  every `Write` and `Edit`, when capture is enabled
- `untracked/stop-events.jsonl`, `context-sidecar/`, `thread-registry/`
- the daemon PID file and the `.socket-path` discovery file

The daemon socket itself was never affected: it is `0660` via an explicit
post-bind `chmod`.

## What changed

The daemon now applies `umask 0o077`, so everything it creates from now on is
owner-only (`0600` files, `0700` directories). The three artefacts whose contents
are known-sensitive additionally pass an explicit mode at the create site, so the
guarantee survives a future regression of the umask line. Two tmp-then-replace
writers (`settings_repair`, `retention`) now copy the target's mode across the
replace instead of silently rewriting it — the settings one was doing that to a
**git-tracked** file.

**Nothing here fixes what is already on disk.** A umask governs creates and
nothing else, so a file created last month keeps the mode it was created with,
forever, until something changes it. That is why this task exists.

## How to detect if this applies to you

```bash
.claude/hooks-daemon/bin/hooks-daemon check-permissions
```

It reports every group- or other-**writable** artefact under the daemon's
untracked directory and exits `1` while any remain, so it is usable as a CI or
upgrade gate. Symlinks, virtualenv trees and the daemon socket are excluded
deliberately — see the "Why those exclusions" note below.

Equivalent by hand, if you would rather look yourself:

```bash
find .claude/hooks-daemon/untracked -type l -prune -o -perm /022 -print
```

Note `-perm /022`, not `/077`: the latter also matches a perfectly ordinary
`0644` and buries the real finding in noise.

## What to do

1. **Run the check** above and read what it reports.

2. **Fix it:**

   ```bash
   .claude/hooks-daemon/bin/hooks-daemon check-permissions --fix
   ```

   This strips group and other bits and leaves owner bits alone, so directories
   stay traversable. It is not run automatically at startup: a daemon silently
   rewriting permissions across a tree you own is its own risk, and this is your
   call to make after reading the findings.

3. **Consider whether anything leaked.** If the machine has other local users, or
   the project directory is shared (a bind-mounted volume, a network share, a CI
   runner with multiple jobs), then for as long as the daemon has been running,
   those files have been readable and writable by them. Whether that matters
   depends on what your handlers logged and whether payload capture was on
   (`daemon.payload_capture.enabled`, off by default).

4. **Re-run the check** to confirm it exits `0`.

## Behaviour change you may notice

If a **second user account** was reading the daemon's runtime files — the most
likely case being a container running the daemon as `root` over a bind-mounted
project while you work on the host as a normal user — that user can no longer
read them. This is the intended fix rather than a casualty; those files hold hook
payloads and decision records.

It does not break daemon sharing, because cross-UID sharing was never possible:
the socket is `0660` owned by the daemon's user and no code anywhere sets a shared
group, so a second UID was already refused at `connect()` (verified with a real
second account). If you need a genuinely separate daemon per user, set
`CLAUDE_HOOKS_SOCKET_PATH` / `CLAUDE_HOOKS_PID_PATH` / `CLAUDE_HOOKS_LOG_PATH`.

## Why those exclusions

Each exclusion in `check-permissions` is there because it was measured as a false
positive on a real install, not because it was anticipated:

- **symlinks** are always `lrwxrwxrwx` — the mode belongs to the target, and a
  virtualenv's `bin/python` and `lib64` are symlinks;
- **virtualenv trees** are a package manager's business; `uv` leaves a `0666`
  `.lock` inside one;
- the **socket** is deliberately `0660`.

Other-*readable* is deliberately not flagged: nothing the fixed daemon creates is
other-readable, whereas a virtualenv tree is full of legitimate `0644`, so the
rule would be mostly noise. Group-or-other **writable** is the unambiguous bug
shape.
