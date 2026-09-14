# Reference Repositories (`untracked/repos/`)

Read-only clones of OTHER projects, kept so an agent can consult real source
instead of guessing at an API. The convention is a directory of checkouts:

```
untracked/repos/
  some-upstream-library/     # a clone you read
  php-qa-ci/                 # this repo's client-mode canary (special — see below)
```

They are untracked and disposable. Nothing here is this project's code, and
nothing here is edited as part of normal work.

## The failure this exists to prevent

An agent reads a clone that was pulled three weeks ago, reasons carefully from
it, and produces a conclusion that is **indistinguishable from a correct one**.
There is no error, no stack trace and no failing test — just an answer built on
source that no longer exists upstream. The cost is paid later, by someone who
cannot tell which parts of the reasoning to re-check.

A stale clone is worse than a missing one. A missing clone announces itself.

## How freshness is kept

One checker (`src/claude_code_hooks_daemon/reference_repos/`) backs three
surfaces, so a behaviour change needs one edit and the three can never disagree:

| Surface                        | When                    | What it does                                                        |
| ------------------------------ | ----------------------- | ------------------------------------------------------------------- |
| `reference_repo_sweep`         | SessionStart (new only) | Fetches every governed repo, fast-forwards the safe ones, caches it |
| `reference_repo_freshness`     | PreToolUse              | Gates a read against that cache. **Never touches the network**      |
| `hooks-daemon reference-repos` | On demand / CI          | Fetches, reports everything, exits non-zero on a stale repo         |

**Only the sweep and the CLI do network work.** `GIT_FETCH_SESSION` and
`GIT_PULL_SESSION` are 30s apiece against a 30s hook socket budget, so a fetch
inside PreToolUse could spend the entire budget on ONE repo. The gate therefore
reads the cache and nothing else, and a test asserts it spawns no subprocess.

### Pulling happens only when it is provably safe

A clean tree, no local commits, no divergence — then `pull --ff-only`. Anything
else is reported and **never touched**. The asymmetry is deliberate: staleness
costs an agent some wrong reasoning, which is recoverable, while a pull into a
repo holding uncommitted work costs a person their work, which is not.

### Configuration

All of it lives in the **top-level `reference_repos:` block**, not in either
handler's options — one block feeds all three surfaces:

```yaml
reference_repos:
  enabled: true
  roots: ["untracked/repos"]   # may not escape the repository
  exclude: []                  # gitignore-style globs
  mode: block_once             # block_once | block | advise | off
  auto_pull: true              # false = report only, never mutate
  cache_ttl_minutes: 15
```

`block_once` is the default and means what it says: the first read of a given
stale repo in a given session is denied with a runnable `fix:` command, and the
retry goes through. The block is there to inform, not to obstruct.

## Two verdicts that are NOT the same

| Verdict        | Meaning                                       | What to do                                |
| -------------- | --------------------------------------------- | ----------------------------------------- |
| stale          | Checked, and it IS behind / on a wrong branch | Run the printed `fix:` command            |
| `NOT VERIFIED` | Nobody checked — no in-date cache reading     | `hooks-daemon reference-repos` to refresh |

Collapsing them would either cry wolf about repos that are fine, or give false
comfort about repos nobody looked at.

## The un-fetchable carve-out, and why it is not a contradiction

**A repo that cannot be checked never blocks anything and never nags.** No
remote, no upstream, a detached HEAD, or a remote that cannot be reached: each
is stated once and then left alone.

This is what reconciles the freshness system with
[CLIENT-MODE-TESTING.md](development/CLIENT-MODE-TESTING.md)'s canary rule,
which at first glance says the opposite. The canary (`untracked/repos/php-qa-ci`)
is deliberately made **unpushable** — its origin is removed or pointed at an
invalid host — precisely so that nothing inside it can ever reach a real remote.
It is a disposable observation chamber: deleted and re-cloned, never repaired.

So the canary is permanently un-fetchable **by design**, and that is correct.
Two rules follow, and both matter:

- **Do not "fix" the canary to satisfy a freshness report.** Restoring its
  origin would destroy the safety property the canary exists for. If you see it
  named in a report, that is the system working.
- **An un-fetchable repo is never counted as up to date.** It is reported as
  unverifiable and excluded from the all-clear. "Nobody could check this" and
  "this is current" are different facts, and a report that merges them is a
  confident all-clear about a repo nobody checked.

That second rule was not obvious. The canary's LOCAL refs say it is not behind,
so an earlier version of the report counted it as fresh and printed
`all 1 up to date` for a repo whose fetch had failed outright.

## `git` is never intercepted

Every `git` command against a governed repo passes through untouched. The remedy
the gate PRINTS is a `git` command, so a handler that intercepted it could never
be satisfied — and inspecting or fixing a clone is exactly the work the system
is trying to provoke.
