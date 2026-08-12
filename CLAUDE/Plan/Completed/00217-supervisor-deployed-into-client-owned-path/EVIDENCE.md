# Evidence — measurements behind the Plan 00217 decision

Every claim below was produced by running the named command in this worktree or
in the client-shaped fixture (`untracked/dummy-client-repo`, built by
`scripts/dummy-client-repo.sh create`, which drives the production installer).
Local ruff is **0.15.22**; the report was written against **0.16.2**.

## E1 — the three findings reproduce, but NOT under ruff's default rule set

```
ruff check --isolated --output-format concise .claude/ccy/claude-supervise.py
→ All checks passed!

ruff check --isolated --select BLE,DTZ --output-format concise .claude/ccy/claude-supervise.py
→ 1907:14 DTZ005 / 1907:54 DTZ006 / 2407:16 BLE001   (3 findings)

ruff check --isolated --select E4,E7,E9,F,BLE,PLW1510,B,SIM,RUF ... 
→ 2407:16 BLE001                                      (1 finding)
```

The second and third runs match the report **exactly** — same rules, same
lines, same counts. The first does not: ruff's actual default select is
`E4, E7, E9, F`, which contains neither `BLE` nor `DTZ`, so `--isolated` with
no `--select` is clean.

The report's own numbers corroborate this reading: its widened set
(`E4,E7,E9,F,BLE,PLW1510,B,SIM,RUF`) yields only `BLE001` — no `DTZ` — because
`--select` replaces the default set and `DTZ` is absent from that list. For the
`--isolated` run to have produced `DTZ005`/`DTZ006`, `DTZ` must have been
enabled somewhere. Either ruff 0.16.2 widened its defaults, or the reported
"default" run was not the command as written.

**Consequence for the plan's success criteria**: "a default `ruff check .` in a
client repo reports nothing from daemon-owned files" is already true at 0.15.22
and is not what the client observed. The observed findings require a
client-selected rule set, which upstream cannot predict and therefore cannot
pre-satisfy.

## E2 — option (a) (`# noqa` upstream) breaks this repo's own ruff gate

A probe copy of the supervisor with `# noqa: BLE001` at 2407 and
`# noqa: DTZ005, DTZ006` at 1907, linted under **this repository's own**
`pyproject.toml`:

```
RUF100 [*] Unused `noqa` directive (non-enabled: `DTZ005`, `DTZ006`)   1907:88
RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)             2407:28
Found 2 errors.
```

This repo selects `RUF` but not `BLE`/`DTZ`, so a directive for a non-enabled
rule is itself a violation. Option (a) therefore trades three findings in a
client's gate for two in ours.

The escape route — enabling `BLE` and `DTZ` here so the directives become
"used" — costs:

```
ruff check --isolated --select BLE,DTZ --statistics .
→ 77 BLE001, 49 DTZ005, 4 DTZ001, 4 DTZ011, 2 DTZ006   (136 findings + 6 pre-existing invalid-syntax fixtures)
```

136 findings across the tree. The report ranks option (a) "lowest total cost";
measured here it is the highest.

## E3 — option (d) is unnecessary, not confused

The report does **not** claim `qa_suppression`'s `exclude_paths` fixes a
client's `ruff check`. It offers it as an ENABLER for option (3): shipping
`.claude/ccy/claude-supervise*` in that default "would at least let a client
apply option 3's suppressions inline". That is a correct reading of the
handler.

Two facts nonetheless make it moot.

**First, the scoping fact.** In
`src/claude_code_hooks_daemon/handlers/pre_tool_use/qa_suppression.py`,
`_is_excluded()` is consulted inside `matches()` (line 132) to decide whether
the **handler** inspects a `Write`/`Edit` payload. Nothing in that path emits,
reads or influences a ruff/flake8/pylint configuration. Worth stating, but it
contradicts nobody.

**Second, the documented route is already permitted.** Driving the real handler
with three payloads:

```
allowed   client ruff.toml (documented route)          (/proj/ruff.toml)
allowed   client pyproject.toml (documented route)     (/proj/pyproject.toml)
BLOCKED   inline directive in the .py (report blocker 2) (/proj/.claude/ccy/claude-supervise.py)
```

The strategy registry has no `.toml` strategy, so `matches()` returns False and
a client agent can write the `per-file-ignores` stanza today. Only the *inline*
directive is denied. So the fix we chose needs no `exclude_paths` change, and
(d) would unlock an action whose result the next upgrade discards anyway — the
report's own blocker (1).

## E4 — option (b) (symlink or shim into `.claude/hooks-daemon/`)

The production installer writes this `.gitignore` into a fresh client repo
(`untracked/dummy-client-repo/.gitignore`):

```
# Claude Code Hooks Daemon
.claude/hooks-daemon/
.CLAUDE.md.pre-inject
```

Three consequences, each independently fatal:

1. **The vendor dir is git-ignored.** A symlink at
   `.claude/ccy/claude-supervise.py` pointing into it resolves on the author's
   machine and *dangles* for every teammate who clones — the ccy launcher's
   `exec` then fails. That is precisely the brick `ccy_supervisor_integrity`
   was written to warn about, promoted to the default state.
2. **The integrity handler's diagnosis becomes wrong.** `_find_problems()` uses
   `os.access(script, os.X_OK)`, which follows symlinks; a dangling link
   reports "not executable" and recommends `chmod +x`, which cannot help.
3. **Stale-supervisor detection silently dies.** `_check_supervisor_staleness()`
   compares a sha256 of the on-disk script against the running process's
   fingerprint. Through a symlink to the single vendor copy the two can never
   diverge, so the Plan 00164 upgrade warning would never fire again.

This is also *why* ruff sees the file at all: ruff respects `.gitignore` by
default, so the vendor tree is excluded automatically — no client ever wrote
that exclusion. `install/ccy_supervisor.py::_ensure_ccy_gitignore_allows()`
deliberately whitelists `!claude-supervise.py` back **out** of the ignore so it
can be committed (Plan 00147/00148), and that same act is what puts it into
every Python tool's discovery.

## E5 — renaming the deploy target would brick the reporter

Dropping the `.py` extension at the deploy site (`claude-supervise`, the Unix
convention for an executable program) would remove it from `ruff`, `black`,
`mypy`, `flake8` and `pylint` discovery in one move, tool-agnostically.

It cannot be done safely. `install/ccy_supervisor.py::_arm_ccy_supervisor()`
never overwrites an existing `CCY_CLAUDE_WRAPPER` stance, and
`ccy_supervisor_integrity._is_armed()` matches the literal string
`claude-supervise.py` in `ccy.env`. Every already-armed client would keep
pointing at a filename we had stopped deploying.

The reporter's own environment settles it: their `ccy.env` is hand-modified to
`--dry-run` rather than the generated `--arm` line, so a "rewrite only lines we
generated" migration would not match theirs. The rename bricks the very client
who filed the report.

## E6 — the class: five lintable daemon-owned assets land in client space

From the fixture, daemon-owned files deployed **outside** `.claude/hooks-daemon/`
that a code linter would collect: `.claude/hooks/*` (31 bash forwarders),
`.claude/skills/hooks-daemon/scripts/*.sh` (6), `CLAUDE/Plan/mkplan.bash`,
`bin/hooks-daemon`, and `.claude/ccy/claude-supervise.py`.

Measured under each tool's **default** configuration:

```
shellcheck (no .shellcheckrc) over the deployed hooks + skill scripts
→ 1 informational SC1091 ("Not following: ./../init.sh"), no warnings or errors

shellcheck (no rc) over the deployed mkplan.bash        → clean, exit 0
ruff check --isolated over claude-supervise.py          → clean
```

So the whole deployed surface is currently clean under default tooling — and
nothing anywhere asserts that it stays that way. That absent assertion is the
guard this plan adds (`CLAUDE.md` Core Standard 15).

## E8 — before/after in a real client fixture, both invocations

Fixture rebuilt from this branch by `scripts/dummy-client-repo.sh create`
(production installer), then made a ccy project (`mkdir .claude/ccy`) and the
supervisor deployed through the **production** `deploy_ccy_supervisor_if_enabled`
— the same function `install_version.sh` and `upgrade_version.sh` call:

```
-> Deployed claude-supervise.py to .../.claude/ccy/claude-supervise.py (chmod 755)
-> Armed supervisor: created .../.claude/ccy/ccy.env
deployed=True armed=True
```

The client's config has no `ccy:` block, so `deploy_supervisor` is `None` —
the default path, not a special case.

**A) Realistic client invocation** — the fixture's own `ruff.toml` selecting
`E, F, BLE, DTZ, B, SIM`, run as a client would (`ruff check .`, no
`--isolated`, config discovered from the project root):

```
.claude/ccy/claude-supervise.py:1913:14: DTZ005 ...
.claude/ccy/claude-supervise.py:1913:54: DTZ006 ...
.claude/ccy/claude-supervise.py:2413:16: BLE001 ...
Found 3 errors.
```

The reported symptom, reproduced in a genuine client layout. Note what is
ABSENT: nothing from `.claude/hooks-daemon/` (git-ignored, so ruff skips it)
and nothing from `.claude/hooks/` (shell, not Python). The supervisor is the
only daemon-owned file in a client's Python scope, which is exactly why it was
the one that got reported. Line numbers moved 1907→1913 / 2407→2413 because of
the six-line ownership banner.

**B) Isolated invocation** — `ruff check --isolated .`: **All checks passed**,
confirming E1 in a client layout too.

**C) The shipped remedy, applied verbatim.** Pasting the stanza from
`CLAUDE/LLM-INSTALL.md` into the fixture's `ruff.toml`:

```toml
[lint.per-file-ignores]
".claude/ccy/claude-supervise.py" = ["BLE001", "DTZ005", "DTZ006"]
```

re-running the SAME client invocation as (A): **All checks passed**, exit 0.
The client keeps their strict rules everywhere else and loses nothing.

**D) Ownership banner coverage in the deployed tree**:

```
files carrying "DAEMON-OWNED FILE":  39
deployed asset files in total:       39
```

(`.claude/init.sh`, 31 hook forwarders + status-line, 6 skill scripts, the
supervisor.) `shellcheck -x --source-path=SCRIPTDIR` over the deployed shell
assets: exit 0.

## E9 — upgrade path (Task 2.3), and a fixture limitation

Every asset in the manifest is redeployed by `scripts/upgrade_version.sh`, not
only at install:

| Asset                                | Upgrade call site                                            |
| ------------------------------------ | ------------------------------------------------------------ |
| `.claude/init.sh`, `.claude/hooks/*` | `deploy_all_hooks` — line 247 (fast path), line 726 (Step 8) |
| skill scripts                        | `deploy_skills` — lines 264, 799                             |
| `mkplan.bash`                        | `deploy_plan_workflow_if_enabled` — lines 283, 853           |
| `claude-supervise.py`                | `deploy_ccy_supervisor_if_enabled` — lines 301, 880          |

`scripts/install/hooks_deploy.sh` **copies** the daemon clone's own
`.claude/hooks/*` and `init.sh` (lines 152, 210) rather than regenerating them,
so the bytes a client receives are literally the files this repo tracks — which
is what the lint guard checks.

The v3.24.0 failure class (an asset that installs once and is never refreshed)
**cannot** apply to this fix: the banner lives INSIDE the copied bytes. There is
no separate refresh step to forget — if the deploy runs at all, the banner
arrives with it.

**Fixture limitation, reported not worked around**: `upgrade_version.sh` cannot
be exercised against `untracked/dummy-client-repo`. Its safety check is
`[ ! -d "$DAEMON_DIR/.git" ]` (line 183), and the fixture's daemon dir is a git
WORKTREE whose `.git` is a *file*. A real client's `git clone` gives a
directory, so the check is right for production and wrong for the fixture —
`scripts/dummy-client-repo.sh` currently supports install-mode verification
only. Hence the upgrade evidence above is code-level plus a direct call to the
production deploy function, not an end-to-end upgrade run.

## E7 — the boundary is genuinely unmarked

`.claude/hooks-daemon/` announces itself three ways: it is git-ignored, it
carries `src/CLAUDE.md` and `tests/CLAUDE.md` "DO NOT EDIT — Hooks Daemon
Internal" markers, and `daemon_location_guard` blocks `cd` into it.

`.claude/ccy/claude-supervise.py` has none of these. Its first 59 lines are a
technical docstring about PTY forwarding and thread safety; nothing states that
it is daemon-owned, that local edits are discarded on upgrade, or that it
belongs outside the project's own QA scope. A client — or a client's agent —
opening it has no way to tell whose file it is.
