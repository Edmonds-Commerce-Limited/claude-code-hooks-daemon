# Bug report: generated `CLAUDE.md` hardcodes the machine's absolute project path

> **Resolved by Plan 00244** — kept as the origin record for this plan; its
> analysis was accurate and is what the fix was built from. Two corrections to
> its conclusions, both recorded in `PLAN.md`:
>
> 1. The suggested `<repo-root>/…` placeholder was **not** adopted. It is not
>    runnable as printed, which is the exact failure class Plan 00192 removed.
>    The shipped form is project-root-relative
>    (`.claude/hooks-daemon/bin/hooks-daemon status`) — path-agnostic *and*
>    runnable from the project root.
> 2. The report scoped the defect to guidance built from the path builders. A
>    **second class** was found during the fix: `absolute_path` and
>    `root_recursion_guard` hard-code the literal `/workspace` into their
>    guidance *and* their runtime messages. Grepping for the builders cannot
>    find those, which is why the guard asserts on rendered text instead.

**Status:** ✅ FIXED — reported against claude-code-hooks-daemon **v3.51.0**.
**Component:** `utils/cli_command.py` → `daemon_cli_command()` / `daemon_path()`, as consumed by handler `get_claude_md()` and written into the generated `<hooksdaemon>` section of a client project's tracked `CLAUDE.md`.
**Reported from:** `LongTermSupport/fedora-desktop` (client install, public repo).
**Severity:** medium — no runtime breakage, but it writes the developer's home directory into a **tracked file in a public repository** and produces unmergeable per-machine churn.

---

## Summary

Every daemon restart rewrites the auto-generated `<hooksdaemon>` section of the
client project's `CLAUDE.md`, and each daemon-CLI example in that section is
emitted as an **absolute path rooted at the machine's project directory**:

```
<home>/Projects/fedora-desktop/.claude/hooks-daemon/bin/hooks-daemon status
<home>/Projects/fedora-desktop/.claude/hooks-daemon/bin/hooks-daemon restart
<home>/Projects/fedora-desktop/.claude/hooks-daemon/bin/hooks-daemon logs
```

13 occurrences in this project's `CLAUDE.md`. `CLAUDE.md` is tracked, committed,
shared, and in this case **public on GitHub**.

Three consequences:

1. **Leaks the developer's home path / username** into a public repository. Our
   repo's own `SecurityRules.md` lists `git diff | grep "/home/"` as a mandatory
   pre-commit check, and the pre-commit secret scanner rejects the pattern — so
   the daemon's own output fails the client project's security gate.
2. **Wrong for every other clone.** A teammate who clones to a different path
   reads instructions naming a directory that does not exist on their machine.
   Documentation that asserts a specific install path is wrong by construction.
3. **Per-machine churn.** Two developers, or a host and a container view of the
   same bind-mounted repo, each rewrite all 13 lines on daemon restart, so the
   file ping-pongs and conflicts on merge.

## The bug is invisible in dogfooding

Same blind spot as the context-sidecar path mismatch (fixed in v3.34.1, see
`untracked/hooks-daemon-sidecar-path.md`): **self-install mode masks it.**

In the daemon's own repo the project root is `/workspace`, so
`daemon_cli_command()` renders `/workspace/bin/hooks-daemon …` — an absolute
path that *happens to be generic and identical for everyone*. The daemon's own
committed `.claude/HOOKS-DAEMON.md` and `CLAUDE.md` therefore look fine. The
defect only appears in a **client install on a real host**, where the project
root is a developer-specific directory.

## Root cause

`src/claude_code_hooks_daemon/utils/cli_command.py`:

```python
def daemon_cli_command(*args: str) -> str:
    """...
    Returns:
        An absolute command string that runs as printed, such as
        ``/project/.claude/hooks-daemon/bin/hooks-daemon plan-qa --sweep``.
        Never contains a shell variable.
    """
    try:
        wrapper = str(daemon_bin_path())   # <- absolute, from ProjectContext.project_root()
    except RuntimeError:
        wrapper = _fallback_relative_path()
    return _ARG_SEPARATOR.join((wrapper, *args))
```

**Absoluteness is deliberate and correct — for the audience Plan 00192 had in
mind.** That plan replaced an unrunnable `$PYTHON -m …` with a copy-paste
runnable path, so a *runtime* block message or session-start advisory names
something the agent can execute from any cwd. That reasoning is sound and
should not be reverted.

**The defect is that one builder serves two audiences with opposite
requirements**, and only one of them was considered:

| Consumer                                      | Audience                 | Lifetime                       | Correct form                  |
| --------------------------------------------- | ------------------------ | ------------------------------ | ----------------------------- |
| Block reasons, advisory context (`_cli_hint`) | live agent, this machine | ephemeral, never written       | **absolute** ✅ (as designed) |
| `get_claude_md()` → generated `CLAUDE.md`     | every reader of the repo | **tracked, committed, public** | **path-agnostic** ❌ (bug)    |

Confirmed both call sites in v3.51.0. Runtime side, e.g.
`handlers/session_start/plan_qa_sweep.py`:

```python
def _cli_hint() -> str:                       # runtime advisory — absolute is right
    return "Full report / re-check after fixing: " + daemon_cli_command("plan-qa", "--sweep")
```

Tracked-docs side, `core/claude_md_injector.py` — its own module docstring
states the mechanism, and line 299 is where it happens:

```
On daemon startup, the injector collects get_claude_md() from all active
handlers …
```

```python
content = handler.get_claude_md()      # claude_md_injector.py:299
```

That collected content is written verbatim into the `<hooksdaemon>` section of
the client project's tracked `CLAUDE.md` on every daemon startup. So any handler
whose guidance embeds `daemon_cli_command()` output puts an absolute,
machine-specific path into a committed file. 19 modules import
`daemon_cli_command` / `daemon_path`.

## Suggested fix

Keep `daemon_cli_command()` exactly as it is for runtime output. Add a **doc
variant** for anything destined for a tracked file, emitting a path-agnostic
form:

```python
def daemon_cli_command_for_docs(*args: str) -> str:
    """Path-agnostic variant for TRACKED generated documentation.

    Docs are committed and shared, so they must not assert a machine-specific
    install path: it leaks the author's home directory into the repo, is wrong
    for every other clone, and rewrites itself on every machine.
    """
    wrapper = "/".join((_DOCS_ROOT_PLACEHOLDER, *_CLIENT_DAEMON_SEGMENTS,
                        BIN_DIR_NAME, WRAPPER_NAME))
    return _ARG_SEPARATOR.join((wrapper, *args))
```

Two candidate placeholder forms, in order of preference:

1. **`<repo-root>/.claude/hooks-daemon/bin/hooks-daemon`** — unambiguous, obviously
   a placeholder, correct in every install and every clone. This is what we
   applied locally.
2. **`./.claude/hooks-daemon/bin/hooks-daemon`** — runnable verbatim from the
   project root, which the daemon's own docs already state is the documented
   working directory for every daemon command. Slightly better ergonomics, very
   slightly less obvious that it is location-dependent.

`~/…` is **not** an adequate fix: it still assumes the repo lives at a
particular path under `$HOME` (`~/Projects/fedora-desktop/…`), which is just as
wrong for other clones. Only the repo-root-relative form is correct.

Then switch `get_claude_md()` bodies (and anything else feeding
`generate-docs`) to the doc variant. Runtime handlers keep the absolute form.

### Regression test worth adding

A test that renders the generated docs for a **client-mode** fixture whose
project root is a temp directory, and asserts the output contains no absolute
path — i.e. no occurrence of the fixture's own root. That fails today and
cannot pass by accident in self-install mode, so it closes the dogfooding blind
spot rather than just this instance. `scripts/dummy-client-repo.sh` already
provisions exactly such a fixture (`CLIENT-MODE-TESTING.md`).

## Workaround applied here

Replaced all 13 occurrences in `CLAUDE.md` with
`<repo-root>/.claude/hooks-daemon/bin/hooks-daemon`. This is **not durable** —
the next daemon restart regenerates the section and reintroduces the absolute
paths, since the `<hooksdaemon>` block is explicitly marked
"Do not edit this section — changes will be overwritten."

## Reproduce

1. Install the daemon into a client project at any path other than `/workspace`.
2. Restart the daemon so the docs are regenerated.
3. `grep -c "$(git rev-parse --show-toplevel)" CLAUDE.md` → non-zero.
4. Clone the repo to a different path and read `CLAUDE.md` — the commands name a
   directory that does not exist.
