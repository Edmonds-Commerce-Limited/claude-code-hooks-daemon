# Security review — the check inventory

The canonical list of what a security review of this repository looks at, and
the one thing about each check that decides how it can be run: **whether a diff
can answer it.**

Read by both security-review routines —
[00001 full](ROUTINE.md) and
[00002 delta](../00002-security-review-delta/ROUTINE.md). It lives here, in the
full routine's folder, because the full routine is the one that owns the
complete set; the delta routine owns a subset and names it by reference rather
than restating it.

## The distinction that matters

A check is **delta-able** when the interval's diff contains everything needed
to answer it. Ask of each check: *if nothing in the diff changed, can the
answer still have changed?* If yes, the check is **full-only**, and no amount
of diff review will ever find it.

Two failure shapes produce almost all of the full-only column:

- **The world moved, the file did not.** A dependency pinned in an untouched
  lock file acquires a CVE. Nothing in this repository changed; the risk did.
- **The nth item was the one too many.** Every entry added to an exemption list
  was defensible on the day it was added. No single diff shows the guard being
  hollowed out, because no single diff hollows it out.

A delta run that quietly counted as a full one would retire the compensating
control without anyone deciding to. That is why a delta run **must record which
checks it did not run**, and why the two routines keep separate ledgers.

## Delta-able checks

Each is answerable from the diff over the run's interval.

| ID       | Check                                                                                                                                                    |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `D-EXEC` | New or changed process spawns: `shell=True`, a string-built command line, a spawn that does not go through `utils.git_repo.run_git` where it should.     |
| `D-EVAL` | New dynamic execution or deserialisation: `eval`, `exec`, `pickle`, `yaml.load`, a regex assembled from input.                                           |
| `D-PATH` | New filesystem writes, and whether each is inside project containment; new path handling that a `..` or a symlink could walk out of.                     |
| `D-NET`  | New network egress — any new fetch, and what it does with the response.                                                                                  |
| `D-SEC`  | New reads of protected material: the secret word list, `.env`, credentials, anything `secret_file_guard` covers, by any route including a subprocess.    |
| `D-RULE` | **Changed rules.** A deny that became an allow, an exemption widened, a severity lowered, a handler default flipped to disabled. The reason, per change. |
| `D-DEP`  | Dependencies added or bumped in the interval, and what the new code is trusted to do.                                                                    |
| `D-PUB`  | New code paths that publish outward — a `gh` body, an issue, a comment — and what they can carry out of a private tree.                                  |

## Full-only checks

Each can change its answer while the diff is empty. A delta run does not
attempt these, and says so.

| ID       | Check                                                                                                                                                       | Why a diff cannot answer it                                                                                                                                                                |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `F-CVE`  | Every pin in `uv.lock` against current advisories, runtime closure reported separately from dev-only. **And: is anything automated checking these at all?** | The lock file is unchanged and the advisory is new. The canonical case. The second question is worse: a scanner that never runs reports nothing, which reads exactly like reporting clean. |
| `F-EXPT` | The **union** of every exemption: `exclude_paths`, whitelists, `extra_whitelist`, per-handler opt-outs. Is any guard now hollow?                            | Each entry was fine alone. Only the accumulated set is the finding.                                                                                                                        |
| `F-BYPS` | The bypass inventory: for each guard, every route that reaches its protected outcome without passing it.                                                    | A bypass is created by the INTERACTION of files, and both can be unchanged. The Bash-write-vs-Write-tool split is the known example.                                                       |
| `F-GAP`  | Dangerous constructs no handler judges at all.                                                                                                              | An absent handler appears in no diff, ever. This is the `routine-never-run` argument applied to coverage.                                                                                  |
| `F-DEPL` | Deployed artefacts in client installs against their templates here.                                                                                         | Drift is a property of the other repository's state, not of this diff.                                                                                                                     |
| `F-HYG`  | On-disk hygiene of protected material: modes, gitignore coverage, stray copies under `untracked/`.                                                          | A stray copy is created by a command, not a commit.                                                                                                                                        |
| `F-PRIV` | What this repository's public surface — issues, releases, generated bodies — has actually disclosed to date.                                                | The disclosure is in published output, not in the tree.                                                                                                                                    |

## Adding a check

Add it to one column, never both, and write the "why a diff cannot answer it"
cell before deciding which. A check whose blindness cannot be stated is a check
that has not been understood yet, and guessing puts it in the delta column —
where being wrong is silent.
