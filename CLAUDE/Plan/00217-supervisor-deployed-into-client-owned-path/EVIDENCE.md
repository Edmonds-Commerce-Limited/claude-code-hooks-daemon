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

## E3 — option (d) (`qa_suppression` `exclude_paths`) cannot affect a client's ruff

`src/claude_code_hooks_daemon/handlers/pre_tool_use/qa_suppression.py`:
`_is_excluded()` is consulted inside `matches()` (line 132) to decide whether
the **handler** inspects a `Write`/`Edit` payload. It is a scan-scope control
for the daemon's own PreToolUse gate. Nothing in that path emits, reads, or
influences a `ruff`/`flake8`/`pylint` configuration. Shipping
`.claude/ccy/claude-supervise*` in its defaults would only permit an agent to
hand-write a suppression that E2 shows we cannot accept anyway.

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

## E7 — the boundary is genuinely unmarked

`.claude/hooks-daemon/` announces itself three ways: it is git-ignored, it
carries `src/CLAUDE.md` and `tests/CLAUDE.md` "DO NOT EDIT — Hooks Daemon
Internal" markers, and `daemon_location_guard` blocks `cd` into it.

`.claude/ccy/claude-supervise.py` has none of these. Its first 59 lines are a
technical docstring about PTY forwarding and thread safety; nothing states that
it is daemon-owned, that local edits are discarded on upgrade, or that it
belongs outside the project's own QA scope. A client — or a client's agent —
opening it has no way to tell whose file it is.
