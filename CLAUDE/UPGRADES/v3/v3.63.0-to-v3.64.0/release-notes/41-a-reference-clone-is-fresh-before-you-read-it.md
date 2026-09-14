# Callout: a reference clone is fresh before you read it

**Plan**: 00401
**Audience**: client projects

Tracking read-only clones of upstream repositories under `untracked/repos/` is
a convention this project and its siblings share: an agent consults real source
instead of recalling it. The failure it invites is that agents read such a
clone **without pulling first**, reason from a checkout that may be weeks
behind, and produce conclusions that are wrong — with no error, no failing
test, and nothing that looks different from a correct answer. Stale reasoning
is indistinguishable from correct reasoning at the moment it is produced, which
is exactly why nothing caught it.

**What changes.** Reference repos under configured roots are discovered
automatically, made fresh at SessionStart, and gated at PreToolUse:

```text
SessionStart   fetch every governed clone, pull where provably safe, cache the reading
PreToolUse     read the CACHE only — deny a read of a clone that is stale or off-branch
CLI            hooks-daemon reference-repos — the same checker, on demand
```

One checker feeds all three surfaces, so they cannot drift apart about what
"stale" means.

**PreToolUse performs no network I/O, and that is forced rather than
preferred.** A fetch and pull inside a hook can consume the entire 30s socket
budget for ONE repo, and a project can have several — which reproduces the
`socket_timeout` failure the daemon already has dedicated error text for. The
gate therefore reads a cached reading and nothing else; the network work
happens at SessionStart, where a slow remote costs latency instead of a failed
tool call.

**Three verdicts, not two, and the third is the interesting one.** "Stale" and
"nobody has checked this" are different facts, and collapsing them either cries
wolf or gives false comfort:

- `R-REFERENCE-REPO-STALE` — the clone is behind, or off its default branch.
- `R-REFERENCE-REPO-NOT-VERIFIED` — no in-date reading exists, so its state is
  unknown.
- **Unconfirmed** — a sweep ran, but this clone's contents were never compared
  against an upstream. This is not a fault to fix, and it is reported as a note
  rather than a denial.

That third verdict exists because **a reference clone can be un-fetchable by
design**. A clone whose `origin` has been deliberately replaced with an invalid
URL — so that a push cannot happen even by accident — can never be brought up
to date, and a system that blocked reads of anything "not up to date" would
lock it out permanently.

**Two more properties come from measuring a real clone rather than assuming.**
The default branch is resolved from `origin/HEAD`, not hardcoded to `main`: the
one clone available here is on `php8.4`, and anything assuming `main` reports a
false "off default branch" for it. And auto-pull runs only when it is provably
safe — a clean tree, no local commits, fast-forward only. The same clone was
`ahead 1` with uncommitted changes, where a blind `git pull` would conflict or
destroy work; it is reported and never touched.

**Git is never intercepted.** The gate denies a READ of a stale clone, so the
remedy it prints stays available: `git -C <clone> pull --ff-only` runs, as does
anything with `git` at its head anywhere in a command chain. A gate that
blocked the fix it recommends would be unusable.

**Block once per repo, per session, and configurable.** The default reports a
given clone once and then stays quiet, because repeating the same denial every
read trains the reader to skim past it.

**Configuration.** Roots default to `untracked/repos/`; `exclude` globs,
`auto_pull` and the enforcement mode are all settable under
`handlers.pre_tool_use.reference_repo_freshness`. A project with no such
directory gets nothing — discovery finds no clones, and every surface stays
silent.
