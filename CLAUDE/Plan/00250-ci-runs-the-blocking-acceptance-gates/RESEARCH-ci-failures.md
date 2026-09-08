# The three CI failures, and why only one was this plan's subject

This plan was written from "the first fully green CI run". That premise expired:
`Tests + coverage` has been RED on `main` for a long stretch — 9 failures per
interpreter across three files when found (while regression-testing Plan 00347),
down to 4 after Task 2.4a.

| File                                               | Why it failed on a runner                                                                                                | Resolution   |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------ |
| `tests/integration/test_deployed_skill_trees.py`   | Asked git about a **directory-only** ignore pattern (`/hooks-daemon/`) for a path absent on a runner                     | Fixed (2.4a) |
| `tests/integration/test_forwarder_socket_stdin.py` | Hardcoded `/workspace`, so the forwarders were never found                                                               | Fixed (2.4a) |
| `tests/integration/test_relay_guard_fail_open.py`  | Re-derived the hostname socket suffix without the `socket.gethostname()` rung, so it dialled a path nothing was bound to | Fixed (2.4b) |

## Only one of the three was really about the daemon

Two were plain defects that would fail on any machine without a deployed
install, and only *looked* like daemon fallout:

- **The directory-only ignore pattern.** A trailing slash in `.gitignore` makes
  a pattern match directories only, and `git check-ignore` will not match it
  against a path it cannot tell is a directory. So any checkout without a
  deployed install answers "not ignored" — the guard was testing the container,
  not the pattern. It now asks about a path *inside* the directory, which is
  existence-independent.
- **The hardcoded `/workspace`.** The forwarders are tracked and not ignored, so
  they exist in any checkout — just not at that path. Wrong independently of any
  daemon, and would still be wrong if CI provisioned one.

Only `test_forwarder_socket_stdin.py`'s *remaining* failure genuinely needs a
daemon, which Task 2.1 now provisions.

## Why the distinction is worth keeping

A failure is louder than a skip — but a run that is *always* red teaches readers
to skim it, which is how the `Format (black)` breakage in Plan 00346 stayed
hidden for hours inside the noise. Misfiling a defect as a provisioning gap
means waiting on provisioning to fix something provisioning will not fix.

Task 4.2 ("a green CI run") needs all three fixed, whatever happens to the
skips — **16** of them, per Task 1.1's measurement; the "11" this plan was
written with was already stale.

## Method worth keeping: reproduce the runner condition, don't read the log

Both separable defects were found by naming the single property of a runner that
differs from this container, and reproducing just that:

| Defect                   | Runner property                      | Local reproduction  |
| ------------------------ | ------------------------------------ | ------------------- |
| directory-only ignore    | no deployed `.claude/hooks-daemon/`  | `git worktree add`  |
| hostname suffix mismatch | `$HOSTNAME` set but **not exported** | `env -u HOSTNAME …` |

Seconds each, no CI round trip. Both beat waiting ~11 minutes for a shared
pipeline, and the second one disproved a hypothesis the plan had recorded as
needing a runner to confirm.
