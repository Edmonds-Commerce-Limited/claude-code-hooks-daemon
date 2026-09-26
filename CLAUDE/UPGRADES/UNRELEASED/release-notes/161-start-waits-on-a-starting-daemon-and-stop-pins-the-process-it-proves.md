# Callout: start waits on a starting daemon, and stop pins the process it proves

**Plan**: 00466
**Audience**: operators

- `hooks-daemon start` and `restart` wait while the daemon is still
  starting. Before, they waited a fixed 5 seconds for its PID file, which
  the daemon writes only after it has loaded its handlers. On a busy host
  they reported "Daemon failed to start (no PID file created)" and exited
  1 while the daemon came up behind them. They now wait while the daemon
  is alive and making progress, up to 30 seconds. They report a failure
  when it exits, when it makes no progress for 10 seconds, or when the 30
  seconds run out. The message says which, and what the PID file held: no
  file, a pid that is no longer running, or a pid still waiting to be
  proven. A daemon waiting for another start to finish with the start
  lock says so, and is not given up on as stuck.
- A hook that has to start the daemon no longer waits for `start` to
  finish. It waits at most 15 seconds from its own start. If the daemon is
  still starting then, a PreToolUse call is denied with "the daemon is
  starting; retry" instead of the hook running into Claude Code's 60-second
  timeout, which lets the call through unchecked. Retry the call; nothing
  needs fixing.
- In CI, a start still under way when the hook must answer is not treated
  as "daemon not installed". Without `ci_enabled`, the call is denied as
  "starting; retry" instead of passing through, so a start that keeps
  hanging denies every call: it fails closed. With `ci_enabled: true`, it
  is denied with the CI-enforced reason, and the recovery command is not
  exempt, as it is not for any CI-enforced denial.
- Only one start of a project's daemon runs at a time, whatever socket it
  uses. A `start` that finds another still under way waits for it, up to
  30 seconds, and then uses the daemon it started. It launches its own
  only if that start failed. Before, two hooks at once, or a hook retried
  while the daemon was starting, found no PID file yet and started a
  second daemon. In a container, that start's single-daemon enforcement
  stopped the daemon still starting, so a start slower than the hook's 15
  seconds never finished. The lock is `daemon.launch.lock` in the
  project's untracked directory.
- Single-daemon enforcement stops only a daemon that serves a socket. A
  launcher has its daemon's command line, since the daemon is its fork,
  so enforcement also stopped a second `start` waiting its turn, and a
  daemon still starting. Neither has bound a socket, and neither is
  stopped now.
- A start that never finishes blocks later ones and says so. `stop` (and
  `restart`) ends it, after proving its pid the way it proves a running
  daemon's. Before its daemon has named itself, `stop` finds the
  launcher holding the lock in the kernel's lock table (`/proc/locks`),
  checks that it has the lock file open, and proves it the same way. If
  nothing can be identified or proven, `stop` says so, signals nothing,
  and exits 1. `stop` also exits 1 when it cannot read the lock, instead
  of reporting "Daemon not running".
- A `start` whose caller has gone, such as a hook that timed out while the
  start waited its turn, still launches the daemon. Its output goes
  nowhere instead of ending the start with a broken pipe.
- **Mixed versions during an upgrade.** A launcher of the version before
  this one does not know the launch lock, and one already running when
  the upgrade begins can still stop a new start's daemon in a container.
  The upgrade stops the old daemon before it starts the new one (step 4,
  and again in step 15's restart), but it does not wait for an old
  launcher already running. That window lasts as long as such a launcher
  does, which is a few seconds. The upgrade's restart already checks that
  a daemon is running rather than trusting the starter's exit code, so a
  starter stopped this way does not fail the upgrade.
- The proof of which project a daemon serves reads its `--project-root`
  the way the daemon's own argument parser did. When there are two, it
  uses the last one. An abbreviated `--project-r` and the
  `--project-root=PATH` form are also read correctly. Before, the first
  was used. So `bin/hooks-daemon --project-root B start`, run from project
  A's wrapper, started B's daemon but was attributed to A. A's
  single-daemon enforcement could then stop it, and B could not. A
  command line that the parser would reject, or that names a relative
  root or a root containing `..`, now proves nothing. A `..` after a
  symlink goes somewhere other than where it seems to. For example,
  `/var/run/../workspace` is `/workspace` when `/var/run` links to `/run`.
  The daemon's root is compared as written, never resolved: a link it
  named may have been re-pointed since, and a path from another mount
  namespace means something else here.
- **Symlinked projects.** Every launcher now names the project root with
  its symlinks resolved: `init.sh`, the CLI, `bin/hooks-daemon`, the
  install and upgrade scripts, and the skill's `daemon-cli.sh`. Before,
  `init.sh` named it the way `pwd` spelt it, link and all, so for a
  project reached through a symlink, `bin/hooks-daemon stop` and
  `restart` refused the daemon a hook had started. The upgrade's stop was
  refused silently, and the upgrade then reported success with the old
  daemon still running. A daemon's root matches the caller's root as
  given, with its symlinks resolved, or as the caller reached it before
  resolving (`bin/hooks-daemon` and the scripts pass that on in
  `CLAUDE_HOOKS_DAEMON_CALLER_ROOT`). The last is used only when it leads
  to the same directory. So a daemon an older version started through the
  link is stopped by a `stop`, `restart` or upgrade run through the same
  link. A daemon naming a link that has since been pointed at another
  directory is refused by a caller that reaches that directory any other
  way. A caller that goes through the re-pointed link matches the
  daemon's text, and the pid it signals is the one its own PID file names.
- `stop`, `restart` and single-daemon enforcement open a pidfd for the
  process before they check its identity, and send every signal through
  it. A process id reused at any point after that can only make the
  signal fail. Where the kernel has no pidfds, the checked psutil handle
  still sends the signal, as before. Any other failure to open the pidfd
  now stops the signal and gives a warning, instead of crashing `start` or
  the installer.
- Stale runtime files are removed only under the start lock, and only
  while they are dead. This covers the installer's pre-install check and
  cleanup, and single-daemon enforcement outside a container. A live
  socket, or a PID file naming a live process (another user's
  included), is left in place. The installer takes the start lock that
  sits next to the daemon's real socket. That is true even when a long
  project path moves the socket to the short fallback directory.
