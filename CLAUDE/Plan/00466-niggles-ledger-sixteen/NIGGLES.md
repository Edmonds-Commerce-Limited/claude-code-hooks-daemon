# Niggles ledger sixteen: write-ups

Newest first. Each entry says how it was found, why it happens, and the
candidate remedies.

N34 is taken on the `worktree-n466-n24` branch (the chain deadline cannot
interrupt a running handler) and lands with that branch. N40 is taken there too
(the fail-open classes behind that branch's security-review blockers). N41 is
taken on the N38 fix branch (the chain's remaining linear per-token cost, which
waits for the shell-parser consolidation).

### N56 — Tests skip when run as root, so this container never runs them

**Found by the owner, who set the rule:** every test must run as root, and
no test may skip because the process is root. This container, and the
dogfood server, run as root. So a root-guarded skip is a test that never runs
where the work happens. Tests that skip on `os.geteuid() == 0` today:

- `tests/claude_code_hooks_daemon/install/test_skills.py:146`
- `tests/integration/test_settings_deploy_lib.py:189`
- `tests/unit/daemon/test_bootstrap_decision.py:206`
- `tests/integration/test_skipif_reasons_match_their_conditions.py:88`

Plan 00351's `test_skipif_reasons_match_their_conditions.py` also endorses
the pattern: it checks that a root skip's condition is written correctly
rather than forbidding it.

**Candidate remedy:** rewrite each test so it proves its behaviour as root.
Permission checks are ineffective for root, so use a fault that root cannot
bypass: an injected opener or os call that raises `PermissionError`, a
directory or dangling symlink in place of a file, or a read-only bind or
immutable file where one is available. Replace Plan 00351's check with a
detector that fails on any root-conditioned skip. Record the rule in the
testing standards doc.

### N55 — `register_all` ignores a handler's `get_default_enabled()` when its config block is absent

**Found by goal-flip review 8 (RV8-n3), filed at review 9's request.** When a
handler has no block in `.claude/hooks-daemon.yaml`, `register_all` registers
it as enabled whatever its `get_default_enabled()` says. So a handler that is
opt-in by design runs on an install whose config never mentions it, such as
one made by `init minimal`. The goal-flip branch changed the docs to describe
this behaviour accurately, but the underlying behaviour is still unsettled.

**Candidate remedy:** decide which source is authoritative for an absent
block: `get_default_enabled()` or "absent means enabled". Make
`register_all`, `init minimal`'s generated config and the docs agree on it.
RED test: an opt-in handler with no config block is not registered, or the
docs and the handler's own default are changed to say it is.

### N54 — Every Stop and SubagentStop pays about 50 ms rebuilding `Config()` while the config is broken

**Found by goal-flip review 8, measured again by review 9.** With an
unloadable `.claude/hooks-daemon.yaml`, five callers fall back to building a
default `Config()` on every event, and each build costs about 50 ms.
`cron_stop_enforcer` and `cron_subagent_stop_enforcer` are among them, so
every Stop and SubagentStop pays it for as long as the config stays broken.
The evidence is in `untracked/scratch/probe_gf9_cache/callers_out.txt` in the
goal-flip worktree. The config cache already caches the load failure itself;
the fallback default is what is rebuilt each time.

**Candidate remedy:** build the fallback default once per cached failure (key
it on the same `(st_mtime_ns, st_size)` signature) or share one immutable
default instance. RED test: two consecutive events on a broken config build
the default once.

### N53 — WorktreeCreate fails with exit 127 when the daemon runs `git worktree add` that succeeds from a shell

**Found by the coordinator.** An Agent dispatch with `isolation: worktree`
failed. The WorktreeCreate hook reported "Handler exception:
CalledProcessError: Command \['git', '-C', '/workspace', 'worktree', 'add',
'-b', '<branch>', '<path>'\] returned non-zero exit status 127". The same
command, run from the coordinator's shell, exits 0. It takes over 2 minutes
on this host, with 4,076 files. The main daemon's own PATH includes
`/usr/bin`, and the repo has no post-checkout hook. So the daemon runs git
in an environment where something git executes cannot be found. An agent
dispatch then fails outright, with no fallback.

**Candidate remedy:** reproduce through the handler with the daemon's real
environment. Suspects: an env the handler builds for the subprocess (PATH
or HOME stripped, or GIT_EXEC_PATH), or a timeout wrapper. Fix the root
cause. Make the handler report the command's stderr in the failure, so the
next such failure names what was not found. Check whether a slow checkout
on a loaded host needs a longer timeout. RED test: the handler, given the
daemon's environment, creates a worktree.

### N52 — The sensitive_content commit gate let a matching session UUID into a commit

**Found by N46 review 2.** Commit `3da8c1ed` on the N46 branch added a review
report containing a real session UUID. The project's `session-uuid` public
pattern matches that blob, and no `exclude_paths` entry covers
`CLAUDE/Plan/`. Yet the commit gate, which scans the added lines of staged
files, allowed the commit. Nothing later caught it either:
`check_sensitive_content.py` scans only the current tree, and
`check_git_history.py` scans metadata but not historical blobs. A `--no-ff`
merge followed by a push would have published it permanently.

**Candidate remedy:** reproduce the miss in a scratch repo first. The
reviewer's untested hypothesis is that the commit ran with a cwd or `-C`
target different from the checkout the gate diffed, which is the Plan 00464
class. Then fix the gate. Add a merge and push check that runs the public
patterns over the added lines of `git log -p <upstream>..HEAD`, since that
is exactly the window this leak survived in. RED tests: the reproduced
commit shape is denied; a merge carrying the blob is denied.

### N51 — `pipe_blocker` reads an escaped alternation inside a quoted grep pattern as a pipe into `head`

**Found by Plan 00421 review 2.** `grep -i -n "a\|HEAD\|b" file` was denied.
The `\|HEAD` inside the double-quoted pattern is a basic-regex alternation,
not a pipe. The blocker split on the `|` and matched the next word
case-insensitively against `head`. That is the N32 class (a `|` inside quotes
read as a pipe stage), plus a case-insensitive match on the producer name.

**Candidate remedy:** find pipe stages with the shared shell segmentation, so
a `|` inside any quoted span, or escaped, never splits. Match the stage's
command name case-sensitively, as bash does. RED tests: this grep is allowed;
`pytest | head` is still denied. This belongs to the shell-parser consolidation
(N41) alongside N32.

### N50 — A handler option whose name matches a method overwrites that method, and the handler then crashes open

**Found by N23 review 2.** `registry.py:592` injects each configured option onto
the handler with `setattr`. An option named like one of the handler's methods
replaces the method. For example, the pre-Plan-00288 option `human_docs_dir`, or
`pauses_path`. The handler then raises on every dispatch. For
`markdown_organization` that lets a misplaced `.md` file through.

**Candidate remedy:** never let an option overwrite a callable or any attribute
the class defines. Options go into a dedicated mapping, or the injection
refuses a name that collides with a class attribute, with a clear config error
naming the option and the handler. Known renamed options get a migration
message. RED tests: a colliding option gives a config error and never crashes
the handler; `markdown_organization` still denies with the stale option set.

### N49 — `daemon_location_guard` denies a `cd` into the daemon directory that is only text inside a quoted argument

**Found by the coordinator.** A `printf '...'` whose single-quoted string
mentioned the words cd, then the daemon directory path, was denied
R-DAEMON-DIR-CD. The command appended a note to a queue file and changed no
directory. So the guard matches the shape anywhere in the command text and
does not look for a real `cd` command.

**Candidate remedy:** judge real command heads through the shared shell
segmentation, so only an actual `cd` (or `pushd`) whose target resolves into
the daemon directory is denied. Text inside a quoted argument, a heredoc body
or a commit message is not a directory change. RED tests: the printf case is
allowed; a real `cd` and a `cd` after `&&` or `;` are still denied. This
belongs to the shell-parser consolidation (N41).

### N48 — `sed_blocker`'s git-commit exemption reaches across a newline

**Found by N38 review 2** (pre-existing, not caused by that branch). The
exemption lets `sed` through when it follows `git commit` with no command
separator in between. A newline is a command separator, but the exemption
does not treat it as one. So `git commit -m x` on one line, followed by a
line that runs `sed -i`, is allowed. The command runs sed.

**Candidate remedy:** use the shared shell segmentation, so that a newline
ends the `git commit` segment. The exemption then covers only a `sed` inside
that segment's message argument. RED tests: sed on the next line is denied;
sed after a newline inside a quoted message is still exempt. This belongs to
the shell-parser consolidation (N41).

### N47 — The ccy supervisor and Claude Code's settings.json both own effort, and they fight

**Found by the owner.** They asked for medium effort. Claude Code reads effort
from `settings.json` (`effortLevel`, and `modelSettings.<model-id>.effortLevel`
per model). The supervisor (`.claude/ccy/claude-supervise.py`) keeps its own
answer and types `/effort` over it:

- `_DEFAULT_MIN_EFFORT_LEVELS` (opus=high, sonnet=high) is a floor the
  supervisor raises live effort to. It knows nothing of `settings.json`, and
  has a second override channel of its own, the `CCY_MIN_EFFORT_LEVELS` env
  var in `ccy.env`.
- `_coupled_effort_target` sends `/effort xhigh` after EVERY `/model` switch to
  a non-top family, including the restore back to the session's own Opus. And
  the floor only ever raises. So one downgrade-and-restore cycle leaves the
  session at xhigh for good, whatever `settings.json` says.

Setting medium therefore needed two edits in two formats (`settings.json` and
`ccy.env`, commits 909f9591 and e52bd9e5). Even then the restore path still
lands on xhigh.

**Candidate remedy:** make `settings.json` the single source of truth for the
effort a model runs at.

- The supervisor resolves a family's effort from the settings Claude Code
  itself reads, in its precedence order: per-model `modelSettings` over
  `effortLevel`, project over user.
- The separate floor map and `CCY_MIN_EFFORT_LEVELS` are retired, and the
  `ccy.env` lines go with them.
- A switch back to a configured model sets that model's configured effort.
  `xhigh` compensation applies only while a downgrade leaves the session on a
  fallback model.
- The fable anchor clamp (Plan 00297) stays as a ceiling.

RED tests:

- the restore lands on the configured effort, not xhigh;
- no `/effort` is sent while live effort equals the configured effort;
- a downgrade still gets xhigh;
- a missing or unreadable settings file degrades to the current defaults with a
  logged reason.

### N46 — `budget_exhaustion_detector` fires on a tool result that merely contains budget wording

**Found by the guard-defects review-6 agent.** Reading a diff whose source
code contained the string "exceeded its byte budget" raised the "budget
exhausted" alert. That text belonged to the file under review; the agent's
own budget had not run out. So the detector matches words anywhere in tool
output. A false alarm like this teaches agents to ignore the real one.

**Candidate remedy:** match only the harness's own budget-exhaustion signal,
meaning its exact shape and source. Never match free text inside a tool
result's content, such as a file or a diff. Add a RED test that reads a file
containing the phrase and expects no alert, and keep the real signal firing.

### N45 — A NUL byte in a configured word-list path makes the never-raising secret-term lookup raise

**Found by the Plan 00421 agent** while fixing N43. A NUL byte in a HEALTHY
config's `sensitive_content.secret_word_list_path` gets through
`normalise_repo_relative_path`. It then reaches `get_cached_secret_terms`,
where `path.stat()` raises ValueError, and the code there catches only
OSError. So `get_active_secret_terms` raises, although it is documented as
never raising. It does so on every leak-vector call site: the router's debug
log, the front controller and payload capture. That is where redaction must
never fail.

**Candidate remedy:**

- Validate every configured path option at config load, and reject NUL and
  other non-path bytes with a clear config error.
- Make the term lookup honour its never-raise contract: catch ValueError
  beside OSError, and treat a list that cannot be resolved as a reported
  problem that never means "redact nothing".
- Sweep the other `Path.stat`, `open` and `resolve` calls on config-supplied
  paths for the same gap.

RED tests cover the config error and each leak-vector site.

### N44 — ✅ Remedied — A PreToolUse handler raises `ValueError: no path specified` on an Edit, and the Edit goes through

**Found by the Plan 00464 agent** while editing
`src/claude_code_hooks_daemon/utils/git_command_target.py` in its worktree,
with its hooks served by the main `/workspace` daemon. The hook context
returned `Handler exception: ValueError: no path specified`, and the Edit was
allowed. That message is what `os.path.relpath("")` raises.

**Root cause, confirmed by reproducing through the real chain with the
project's real config and word list**: the `secret_file_guard` Bash-mention
scanner (`R-SECRET-BASH-MENTION`, `utils/secret_file_matching.py`) tokenises a
command and, for a token that starts with a home-directory prefix such as
`~/`, appends the token with the prefix stripped as an additional spelling to
match against protected globs. A token that IS the prefix and nothing else
(a bare `~/`, as in `cp ~/ /tmp/x`) strips to the EMPTY string. That empty
candidate then reaches `utils/path_exclusion.path_matches_globs` (via
`utils/path_segments.matches_path_segment` on a second call path), the shared
chokepoint every content-guard handler funnels a candidate path through,
which computed `os.path.relpath("", project_root)` and raised. The exception
propagated out of the handler and was swallowed upstream, so the command it
was judging went through unblocked — the fail-open half of this defect is
ledger N24's class, closed separately on the n24 branch.

**Fix**: `_normalised_token_forms` now drops the stripped-home form when it is
empty instead of appending it, and — independently, since other callers can
still hand these two chokepoints an empty candidate — both
`path_exclusion._candidate_paths` and `path_segments._project_relative_or_none`
now treat an empty `file_path` as "no match"/`None`, the same answer they
already give a path that resolves outside `project_root`, before it ever
reaches `os.path.relpath`. Swept the rest of `src/` for `relpath`/`commonpath`
calls on hook-input-derived paths: no other call site was reachable with an
empty candidate.

### N43 — Log and payload redaction is inert while the daemon runs degraded on an unloadable config

**Found by the Plan 00421 agent** while closing Task 4.9 on `worktree-d-00421`.
`secret_redaction._resolve_active_path` resolves the secret word list through
the configuration. When the config cannot load (the Plan 00421 degraded
mode), that lookup raises ValueError, and redaction falls back to inert. So a
degraded daemon writes its logs and payload captures UNREDACTED, which is
exactly when a broken config makes a protective fallback matter most. The
same root cause left degraded `sensitive_content` with no secret terms; that
was fixed on the branch by pinning the default list explicitly.

**Candidate remedy:** while degraded, redaction uses the default word list
UNION the last-known-good snapshot's lists, the same set degraded
`sensitive_content` uses. A redaction failure to resolve a list must never
mean "redact nothing". Pin it with a degraded-start test that captures a
payload containing a term and asserts the term is redacted. Being fixed on
`worktree-d-00421`.

### N42 — Quoted-heredoc blanking hides text that bash executes from the Bash command guards

**Found by the N38 review** (its M3), confirmed against real bash, and
unchanged between the old regex and the new N38 scanner. `shell_segmentation`
treats a quoted-heredoc body as inert data. Several guards then blank that
text and never judge it, among them destructive_git, pipe_blocker,
curl_pipe_shell, force-push detection and, for one shape, sed_blocker. There
are seven shapes where the blanked text is not a heredoc body at all, and
bash runs it:

- an EMPTY body (`cat > n <<'E'` with `E` on the very next line, followed by
  a command and a second `E` line), with its `<<-` form and a
  `git commit -F -` form;
- an opener inside a `#` comment;
- an opener inside a double-quoted string;
- a `<<<'E'` here-string read as an opener;
- a quoted opener inside an UNQUOTED heredoc's body;
- the same inside a multi-line double-quoted string;
- an unquoted heredoc followed by a quoted one on the same line.

In each shape, a destructive or piped command is ALLOWED. The probes are in
`untracked/scratch/probe_n38r_*`. This is a fail-open in the guards
themselves, so it is fixed now on the N38 branch and not deferred to the
consolidation.

**Candidate remedy:** recognise an opener only where bash would: outside
quotes, comments and here-strings, and not inside another heredoc's body.
Close an empty body on the first delimiter line. Keep the scan to one linear,
quote-aware pass. Pin every shape through the real chain.

### N39 — Nine unit tests fail in a whole-suite run and pass when their files run alone

**Partially Remedied on this branch (main-based worktree, commit below):**
the widened-scope items 2 (socket-listener fixed-sleep race,
`started_event`) and 3 (`blocking_gate_guard` skip-to-failure escalation) are
fixed here. Widened item 1 (docs-rewrite mid-run) is recorded as a procedure
note plus a sharpened teardown-guard message, not a code fix (no test-side
leak was found). **The original defect** (the two-layer-patch leak in
`test_project_containment.py`) is diagnosed but NOT fixed on this branch — it
is being fixed on `worktree-n466-guard-defects` by a different agent, per the
fix recipe below.

**Found by the guard-defects agent** (its review-4 fix round). A plain whole
unit-suite run on `worktree-n466-guard-defects` (main merged at `e14cdca4`)
gave 9 failures. They were in `test_model_fallback_detector.py`,
`test_absolute_path.py`, `test_lookup.py` and
`test_dangerous_invocation_corpus_checker.py`. The same four files run alone
gave 105 passed, 0 failed. So some earlier test leaks state (a module global,
a singleton, the environment or the cwd) into these. The full gate passed on
`main`, so the leak depends on order or on how the suite is split across
workers.

A suite that fails in one order is a hidden defect: it can hide a real
failure behind a "flaky" label, and it breaks the first time the ordering
shifts.

**Diagnosed by a follow-up agent.** `main` does NOT reproduce it: a plain
sequential `pytest tests/unit -p no:xdist -q` on `main` at `c92bfbc1` gives
22451 passed, 0 failed. The same run on `worktree-n466-guard-defects` at
`ef0600ed` reproduces exactly 9 failures (22606 passed) in
`tests/unit/handlers/session_start/test_model_fallback_detector.py` (6),
`tests/unit/handlers/test_absolute_path.py` (1),
`tests/unit/rule_explain/test_lookup.py` (1, NOT
`tests/unit/remote_docs/test_lookup.py` — the two victim files share a
basename) and `tests/unit/scripts/test_dangerous_invocation_corpus_checker.py`
(1). So the leak's source exists only on `worktree-n466-guard-defects`, not
on `main`.

**Root cause, bisected to two exact test methods and confirmed with an
isolated 20-line repro (independent of this project's own code).**
`tests/unit/handlers/pre_tool_use/test_project_containment.py` carries a
class-wide `autouse` fixture, `_project_root` (added long before this defect):

```python
@pytest.fixture(autouse=True)
def _project_root() -> Any:
    with patch("...ProjectContext.project_root") as mock:
        mock.return_value = _ROOT  # Path("/repo")
        yield mock
```

Two tests added by commit `d0de526d1`
(`TestFailsClosedOnEvaluationError::test_an_uninitialised_project_root_still_denies`
and `::test_an_evaluation_error_denial_uses_its_own_rule_id`), plus one added
by commit `3e3164bd`
(`TestChainLevelFailClosedBehaviour::test_an_evaluation_exception_still_denies_through_the_chain`),
each ALSO calls
`monkeypatch.setattr("...ProjectContext.project_root", classmethod(lambda cls: _raise()))`
— a SECOND, independent patcher layered on top of the first,
targeting the exact same attribute. `monkeypatch`'s own finalizer runs AFTER
the `_project_root` fixture's `with patch(...)` block has already exited and
restored the TRUE original classmethod, so `monkeypatch.setattr`'s teardown
overwrites it AGAIN — with whatever it had captured as "current" at
`setattr()` time, which is the `_project_root` fixture's own `MagicMock`.
Result: `ProjectContext.project_root` is left PERMANENTLY pointing at that
mock (`return_value=Path("/repo")`, no `_initialized` check at all) for the
rest of the pytest PROCESS. Confirmed with a minimal repro outside this
project (`untracked/scratch/repro_fixture_order/test_order.py`, not
committed): a class with the same two-layer-patch shape leaves the SAME kind
of leak, reproducibly.

Every later test that calls `ProjectContext.project_root()` in that process
then gets the fake `/repo` root, unconditionally — explaining all four victim
files:

- `test_absolute_path.py`: `_absolute_example()` calls
  `ProjectContext.project_root()` directly; the leak makes it return `/repo`
  instead of raising `RuntimeError`, so `"Example: /repo/test.py"` appears
  where the test expects it omitted.
- `test_model_fallback_detector.py` (6 tests): `_resolve_snapshot_dir()`
  (`model_fallback_detector.py:558`) returns `ProjectContext.project_root() / configured` once "initialised", instead of falling back to the cwd its own
  `handler` fixture `monkeypatch.chdir`s to `tmp_path` for; snapshots land
  under `/repo/reports` (off the sandboxed `tmp_path`), so every
  `(tmp_path / "reports").glob("*.md")` in these tests finds nothing.
- `rule_explain/test_lookup.py::TestProjectHandlersAreDiscoverable:: test_project_handlers_included_when_requested`: project-handler discovery
  resolves against the fake `/repo` instead of the real project root, so it
  cannot find `.claude/project-handlers/`'s `daemon_restart_verifier`.
- `test_dangerous_invocation_corpus_checker.py::TestRealTree:: test_the_real_corpus_matches_the_real_chain`: the REAL chain's
  `ProjectContainmentHandler` resolves its containment boundary via the same
  leaked mock, so `supply-pip-index-url` is newly (and wrongly, for the
  corpus's purposes) denied via `enforce-project-containment` against a
  boundary of `/repo` instead of the real repository root.

Bisection evidence (`worktree-n466-guard-defects`, read-only, its own venv):
`pytest -p no:xdist -q TestFailsClosedOnEvaluationError:: test_an_uninitialised_project_root_still_denies test_absolute_path.py::...test_handle_omits_the_example_rather_than_guessing_a_root`
→ 1 failed, 1 passed (same failure as the whole-suite run). Each of the three
leaking test methods reproduces it alone paired with the victim;
`test_get_rules_includes_the_evaluation_error_rule` (same class, does not
touch `project_root`) does not.

**Status.** This agent's own worktree is based on `main`
(`c92bfbc1`), which does not contain this defect — `test_project_containment.py`
there has no `TestFailsClosedOnEvaluationError`/
`TestChainLevelFailClosedBehaviour` classes at all, so there is nothing to
edit or commit here. `worktree-n466-guard-defects` is a separate, git-isolated
worktree this agent could read but not write or commit to. **The original
leak (the two-layer-patch in `test_project_containment.py`) stays diagnosed
but unfixed here — the fix is being applied on
`worktree-n466-guard-defects`** (a different agent has been handed the recipe
below; not yet landed there as of this writing). Items 2 and 3 of the widened
scope below (the socket-listener race and `blocking_gate_guard`'s escalation)
turned out to live on `main` itself, reachable from this worktree, and **are
Remedied here** — see each item for the commit. Item 1 (docs-rewrite) is
recorded as a procedure note only; no test-side leak was found to fix.

**Fix recipe (for `worktree-n466-guard-defects`):** in the three offending
tests, stop introducing a second patcher. Request the class's own
`_project_root` fixture by name (it already yields its `mock`) and reconfigure
THAT mock instead of calling `monkeypatch.setattr` on the same target —
e.g. `mock.side_effect = _raise` in place of the `monkeypatch.setattr(..., classmethod(lambda cls: _raise()))` call, dropping the `monkeypatch` parameter
from tests that no longer need it. As a structural tripwire against the same
class of bug from ANY future test in this file, add a post-`yield` assertion
to `_project_root` itself:

```python
    yield mock
    assert isinstance(ProjectContext.__dict__["project_root"], classmethod), (
        "ProjectContext.project_root leaked past this fixture's teardown "
        "(Plan 00466 N39) -- a test double-patched it instead of "
        "reconfiguring this fixture's own mock"
    )
```

Pin the specific pair with a regression test appended to the file (runs after
the fixed `TestFailsClosedOnEvaluationError`, so it exercises real,
unpatched behaviour exactly like `test_absolute_path.py` does downstream):
mirror that test's own assertion — `monkeypatch.setattr` `ProjectContext. _initialized`/`_instance` to a clean, uninitialised state, run
`AbsolutePathHandler().handle(...)`, assert `"Example:"` is absent from the
reason.

**Candidate remedy (superseded by the diagnosis above):** ~~reproduce it on
`main` with a plain sequential run, then bisect for the polluting test.~~
Done; see above.

**Widened scope (coordinator directive).** A separate agent's whole-suite
`pytest tests/ -q` on `worktree-n466-goal-flip` (tip `95ac6de9`) found three
more defects in the same suite-isolation class: 1 failed, 26782 passed, 35
skipped, 3 xfailed, 13 errors. `worktree-n466-goal-flip` is, like
`worktree-n466-guard-defects`, a separate git-isolated worktree: this agent
verified directly that even `git worktree add` of a brand-new path from its
own worktree is refused ("a worktree-isolated agent's git operations must
target its own worktree"), so none of the three fixes below could be
committed from here either. All three are diagnosed to a concrete fix.

**Follow-up (coordinator directive): items 2 and 3 are NOT branch-only — the
affected files (`tests/unit/daemon/test_event_socket_listeners.py`,
`tests/acceptance/blocking_gate_guard.py`) are on `main`, hence reachable
from this agent's own `main`-based worktree. Both are Remedied HERE** (see
each item for the commit and tests added); the fix does not need to land on
`worktree-n466-goal-flip` separately — merging `main` forward carries it.
Item 1 remains diagnosis-only: the coordinator accepted the external-daemon-
restart evidence and asked for a procedure note plus, if cheap, a sharper
teardown-guard message — also done here, see item 1.

1. **Docs-rewrite-mid-run, evidence points to an EXTERNAL daemon restart, not
   a test.** `tests/conftest.py`'s `no_test_writes_tracked_generated_docs`
   fixture (autouse, per-test baseline+diff) caught `CLAUDE.md` mutated during
   the run, attributed to whichever test's window the write fell into (3
   errors: `test_skill_scripts_venv_resolution.py`,
   `test_skipif_reasons_match_their_conditions.py` x2 — the fixture already
   names these as VICTIMS, not culprits, and its own docstring anticipates
   exactly this). Timestamp correlation: `CLAUDE.md`'s mtime is
   `2026-09-25 01:48:53`, to the second the same moment a REAL
   `claude_code_hooks_daemon.daemon.cli --project-root .../worktree-n466-goal-flip restart` process (pid 612977, still running)
   started — squarely inside the run's `01:37`-`01:58` window. `CLAUDE.md`'s
   own header states it is regenerated on daemon restart. This reads as a
   live, concurrent session restarting that worktree's own daemon while the
   21-minute suite happened to be running — an external edit landing inside
   an unrelated test's window, not a test bug. A `grep` for
   `ClaudeMdInjector`/`DaemonController(` still names ~19 candidate test
   files that construct a real controller, so an actual test-side leak is not
   fully ruled out, but the second-precision timestamp match is strong
   evidence against it. **Recipe if further evidence implicates a test
   instead:** point its `workspace_root` at `tmp_path` (as the fixture's own
   docstring instructs) rather than the real repo.

   **Accepted as a procedure note (coordinator directive): do not restart
   this project's own daemon while a test run is in progress.** A restart
   re-runs `ClaudeMdInjector` against the real repository exactly like a
   misconfigured test would, and lands inside whichever test's window the
   restart happens to overlap — there is nothing test-side to fix for this
   part.

   **Guard sharpened (cheap, done here on `main`):**
   `no_test_writes_tracked_generated_docs` now also stats this project's own
   daemon pid file (`get_pid_path(_REPO_ROOT)`) at fixture setup and
   teardown. When a mutation is caught AND the pid file's mtime changed
   across that same window, the assertion names the pid file and its
   before/after mtimes directly ("an external daemon restart/start/stop
   happened WHILE THIS TEST RAN") instead of only the generic "IF NO TEST
   TOUCHES THESE FILES, suspect an EXTERNAL edit" text — precisely the signal
   that would have named pid 612977's restart above without needing the
   manual timestamp correlation. The extracted helper,
   `_daemon_pid_file_mtime`, has 3 regression tests in
   `tests/unit/test_conftest_docs_guard_culprit.py` (does-not-exist ->
   `None`, exists -> its mtime, restart-shaped unlink+recreate -> mtimes
   differ). This does not fully close the gap (an external edit that does
   NOT touch the pid file, e.g. a hand edit, still falls back to the generic
   text — the fixture still cannot distinguish that from a test's own write),
   but it now names the one external cause actually observed here.

2. **`test_bind_time_rmtree_failure_is_logged_not_swallowed[asyncio]` is a
   plain fixed-sleep race.** `tests/unit/daemon/test_event_socket_listeners.py`:
   `server_task = asyncio.create_task(daemon.start()); await asyncio.sleep(0.1); assert len(daemon._event_servers) > 0`.
   `HooksDaemon.start()` (`src/claude_code_hooks_daemon/daemon/server.py:687`)
   awaits `_acquire_socket_and_bind` then `_bind_event_sockets` (which sets
   `self._event_servers`) before reaching `shutdown_event.wait()` — under host
   load those two awaits can outlast a fixed 100 ms, and the test observes
   `_event_servers` still empty. **The same fixed-`asyncio.sleep(0.1)` +
   assert shape appears 13 times in this ONE file** (lines 104, 119, 137, 167,
   195, 246, 291, 315, 330, 362, 396, 445, 470) — a pre-existing, repo-wide
   copy-paste pattern this defect merely surfaced once under load; every one
   of the 13 is equally racy. **Fix recipe:** replace the fixed sleep with a
   bounded poll shared by all 13 call sites, e.g.
   `for _ in range(100): \n    if daemon._event_servers or server_task.done(): break \n    await asyncio.sleep(0.01)`
   (1 s bound, typically resolves in under 10 ms), or — more robust — give
   `HooksDaemon` its own `self.started_event = asyncio.Event()` set right
   after `_bind_event_sockets()` (there is currently no such readiness
   signal, only `shutdown_event`) and `await asyncio.wait_for(daemon.started_event.wait(), timeout=1.0)` in the tests.

   **Remedied here, on `main`.** Added `HooksDaemon.started_event: asyncio.Event()` (`src/claude_code_hooks_daemon/daemon/server.py`,
   `__slots__` + `__init__`), `.set()`'d in `start()` immediately after both
   `_acquire_socket_and_bind` and `_bind_event_sockets` complete — TDD'd via
   `TestStartedEvent` in `test_event_socket_listeners.py` (RED: attribute
   missing; GREEN: 3 tests, added before implementing, 2 of which exercise
   the new readiness signal directly). All 13 original
   `asyncio.sleep(0.1)`-then-assert call sites in that file now await
   `daemon.started_event.wait()` bounded by
   `Timeout.SOCKET_CONNECT` (5 s; `magic_values` QA forbids the bare literal).
   **Swept the rest of `tests/` for the identical daemon-startup-race shape**
   (not the generic `asyncio.sleep` pattern, which has legitimate unrelated
   uses elsewhere) and found the same
   `create_task(daemon.start()); await asyncio.sleep(0.1)` idiom in 4 more
   files, all converted the same way:
   `tests/daemon/test_server_response_schema.py` (2),
   `tests/integration/test_relay_event_socket_real_payloads.py` (1),
   `tests/unit/daemon/test_event_socket_hook_event_name_enrichment.py` (2),
   `tests/daemon/test_server.py` (34), `tests/daemon/test_log_level_override.py`
   (11). `tests/unit/daemon/test_server_liveness_reuse.py` and
   `tests/integration/test_parallel_start_reuse.py` were inspected and left
   alone — both already use a bounded poll or an unrelated background-thread
   loop, not the broken fixed-sleep-then-assert shape. All 132 tests across
   the 6 converted files pass; `magic_values` QA: 0 violations.

3. **10 BLOCKING-release-gate acceptance tests ERROR on a plain run by
   design, not by accident — but the design over-fires.**
   `tests/acceptance/blocking_gate_guard.py` is a session-wide
   `pytest_runtest_makereport` hook: it reads `CLAUDE/development/RELEASING.md`
   Step 12.0's own pytest command line (the SOLE declaration of the blocking
   set — `test_diagnostic_scripts.py`, `test_install_sh_end_to_end.py`,
   `test_tool_use_error_recovery.py`, `test_stop_hook_hard_block.py`,
   `test_skill_install_python_discovery.py`, `test_playbook_harness.py`) and
   turns ANY skip of those files into a hard failure, unconditionally —
   Plan 00250's fix for CI silently reporting a never-run gate as green.
   `.github/workflows/qa.yml` starts a real daemon BEFORE running the whole
   suite, so in CI these tests never skip (they run and pass genuinely) and
   the hook is inert there; RELEASING.md's own Step 12.0 invocation also
   always runs with the daemon already started, so the hook firing there is
   correct — that IS an abort condition. The break is a THIRD case neither
   of those anticipated: any OTHER whole-suite run with no daemon running
   (exactly the ad hoc `pytest tests/ -q` that produced this run) now hard
   ERRORs instead of getting the ordinary, harmless skip every other
   daemon-dependent test in the suite gets. **Fix recipe:** gate the
   skip-to-failure escalation on an explicit signal that THIS invocation
   means to be the release gate, not on file identity alone — e.g. an
   environment variable (`HOOKS_DAEMON_ACCEPTANCE_GATE=1`) that RELEASING.md
   Step 12.0's own command block sets before the `pytest` call, checked
   alongside `skip_is_an_abort_condition(item.path)` in
   `pytest_runtest_makereport`. CI needs no change (the tests never skip
   there, daemon or no signal), and RELEASING.md's own invocation still fails
   closed once it sets the variable — a marker-based `addopts` deselection
   was considered and rejected: it would also deselect these tests from CI's
   OWN full-suite run, which the coordinator's brief explicitly said not to
   weaken.

   **Remedied here, on `main`.** `blocking_gate_guard.py` gained
   `_RELEASE_GATE_ENV_VAR = "HOOKS_DAEMON_RELEASE_GATE"`,
   `release_gate_invocation()` (exact `"1"` match only — a stray truthy
   string set for an unrelated purpose must not silently opt a run in) and
   `should_escalate_skip(test_file)` (`declared_blocking_gate_files()` match
   AND `release_gate_invocation()`, both required — the signal alone is not
   enough, or every skip anywhere would fail). `pytest_runtest_makereport`
   now calls `should_escalate_skip` in place of the old
   `skip_is_an_abort_condition`. `CLAUDE/development/RELEASING.md` Step 12.0's
   command block now sets `HOOKS_DAEMON_RELEASE_GATE=1` before the `pytest`
   call; `.github/workflows/qa.yml`'s daemon-start step now exports the same
   variable via `GITHUB_ENV` so CI's protective behaviour (a daemon that
   silently failed to start there still fails the job) is preserved, not
   weakened. A third caller was found by checking every acceptance-reaching
   entry point named in the coordinator's directive:
   `scripts/qa/run_tests.sh` (the `tests` tool in `llm_qa.py`, `live_daemon=True`)
   calls `ensure_live_daemon` first, but a daemon-start failure there does
   not abort the script — it only prints a message and `run_tests.sh` still
   runs. That script now also exports `HOOKS_DAEMON_RELEASE_GATE=1` before
   invoking pytest, for the identical reason. `run_smoke_test.sh` was checked
   and does not invoke pytest against `tests/acceptance/` at all (a separate
   live-daemon-probe mechanism), so it needed no change. Verified end-to-end
   against a real acceptance file
   (`test_playbook_harness.py`, no daemon running): plain run — 5 skipped,
   exit 0; `HOOKS_DAEMON_RELEASE_GATE=1` — 5 errors naming the file as a
   BLOCKING release gate, exit 1. 6 new unit tests in
   `tests/unit/scripts/test_blocking_gate_guard.py` cover both functions and
   both modes (absent/exact-match/wrong-value for the env var; declared vs
   undeclared file under each).

### N38 — The PreToolUse chain takes quadratic time on a command of quoted heredoc openers

**Found by the Plan 00463 sixth review** (its nit n6), measured on `main` and
on the 463 branch alike (`untracked/scratch/probe_463v6_chain_main_heredoc.py`).
A main-thread Bash command made of repeated `cat <<'E'` openers takes the
whole in-process PreToolUse chain 1.9 s at 16 KiB, 6.8 s at 32 KiB and 51.7 s
at 94 KiB. So the cost roughly quadruples when the size doubles. The verdict
is allow, but at 94 KiB it runs past the client's 30 s budget. Until N25's
fail-closed client lands, that timeout is itself an ALLOW for the whole chain.
After it lands, it is a false deny of a harmless command, and the daemon
keeps burning a worker thread on it either way.

The handler, or handlers, carrying the quadratic heredoc scan has not yet
been identified; profiling is the first step.

**Candidate remedy:** profile the chain per handler on the 94 KiB fixture, and
make each heredoc scan linear. The likely shape is one that re-scans the rest
of the command for each opener. Pin it with a test: the 94 KiB fixture takes
the whole chain under 2 s.

### N37 — `resolve_venv.sh` caches an override's interpreter for later callers that set no override

**Found by the Plan 00376 agent** while closing the upgrade gate's
interpreter bypass. `scripts/lib/resolve_venv.sh` writes
`untracked/.python-cmd-cache` even when the answer came from
`HOOKS_DAEMON_PYTHON` or `HOOKS_DAEMON_VENV_PATH`. A later call that sets
neither override is then served the overridden interpreter from the cache.
So a one-off override sticks, and a caller that deliberately runs without
overrides still inherits one. Layer 2 of the upgrade now works around this
with its own containment check. Every other caller still inherits it.

**Candidate remedy:** never write the cache from an override-derived answer.
Also key the cache on the absence of overrides, or skip it whenever an
override is set. RED test: resolve with `HOOKS_DAEMON_PYTHON=/x`, then with
no override, and the second call must not return `/x`. Being fixed on
`worktree-d-00376`.

### N36 — `destructive_git` denies a `grep` whose search pattern is the text of a force branch delete

**Found by the Plan 00463 agent** (review-5 fix round, its nit n9). Searching
the tree for the literal force-branch-delete command text (a grep argument,
for example `grep -rn "git branch -D" docs/`) is denied as
R-GIT-BRANCH-FORCE-DELETE. Nothing in the command deletes a branch: the
text is data given to `grep`. It is the same class as N22
(`lsp_enforcement` takes another command's argument for a symbol lookup)
and the N32 pipe split: a guard matches a dangerous shape anywhere in the
command string instead of at a command position.

**Candidate remedy:** judge destructive-git shapes only at a real command
position, using the shared shell lexer from the Plan 00464 shell-parser
consolidation. Treat a quoted argument to a known data consumer (`grep`,
`rg`, `echo`, `printf`, a git `-m` message) as data. RED tests: the grep
above is allowed; `git branch -D x`, `cd r && git branch -D x`, and
`bash -c 'git branch -D x'` are still denied.

### N35 — `daemon_sync_after_merge` judges a `cd <worktree> && git merge` against the session root's ORIG_HEAD

**Found by the Plan 00421 agent.** It ran `cd <worktree> && git merge main`
inside a worktree. The advisory then reported the MAIN checkout's own
`ORIG_HEAD..HEAD` and named `.claude/hooks-daemon.yaml` and project-handlers
as changed. The worktree merge had touched neither.

**Why:** `_is_foreign_repo` and the diff both use the hook payload's cwd,
which is the session root. They ignore the directory the command itself
`cd`s into. This is the same attribution family as N28 (project_containment
ignoring a same-command `cd`) and N33 (which daemon, or which checkout,
a worktree agent's action is judged against).

**Candidate remedy:** resolve the merge's working directory from the
command, using the shell lexer's `cd` tracking from Plan 00464 (the
shell-parser consolidation). Run the ORIG_HEAD diff in THAT repository, and
say nothing when it is a different checkout from the one the daemon
serves. RED test: `cd <other-worktree> && git merge main` emits no advisory
about the session root.

### N33 — a worktree agent's `secret_file_guard.exclude_paths` change had no effect after a daemon restart

**Found by the integration-B2 fix agent.** The agent was writing tests in
`worktree-integration-b2` that must name protected-looking filenames.
R-SECRET-SCRIPT-AUTHOR kept denying the writes. It added the two test files
to `secret_file_guard.options.exclude_paths` in the WORKTREE's
`.claude/hooks-daemon.yaml` and restarted the worktree's daemon. The denials
continued. It worked around it by building the filenames at runtime.

**Why (unverified):** the likeliest cause is that a sub-agent's hook calls
are served by the daemon of the Claude Code session's project root (the
main checkout), not by the worktree's own daemon. If so, a worktree config
change cannot affect that agent's own enforcement until it lands on main.
The docs say "restart the daemon" without saying WHICH daemon enforces a
worktree agent's tool calls, so the agent could not diagnose it.

**Candidate remedy:** first reproduce it and establish which daemon served
the denial (the hook log's project root and socket). Then either make the
deny reason name the config file it was judged against, or document
worktree-agent enforcement in CLAUDE/Worktree.md. Also consider an advisory
when a worktree's handler config differs from the enforcing daemon's.

### N32 — `pipe_blocker` splits at a `\|` inside double quotes and reads the next word as a pipe stage

**Found by the Plan 00463 agent.** The command
`grep -n "a\|--finish\|head-moved\|^#" CLAUDE/QA.md | bin/echd-capture --head 80`
was denied as R-PIPE-TO-HEAD. The only real pipe goes to the whitelisted
`bin/echd-capture`. The `\|` alternations inside the double-quoted grep
pattern were split as pipes, and the "stage" `head-moved` was read as `head`.
Two defects: a quoted `|` is not a pipe, and `head-moved` is not the
command `head`.

**Candidate remedy:** move pipe_blocker onto the shared shell lexer from
Plan 00464 (the shell-parser consolidation), so pipe boundaries come from
real tokenisation. Match a stage's command by whole word. RED tests: the
command above is allowed; `pytest | head -1` is still denied; and
`grep "x|y" f | head` is judged on `grep` (whitelisted), not on `y`.

**Widened (Plan 00463 agent, review-5 n9):** an UNESCAPED `|` inside double
quotes trips it too, not only `\|`. The RED tests must cover both spellings.

### N31 — ✅ Remedied — the dispatch-declaration advisory does not recognise "File to write to: <path>"

**Found by the 00467 dogfood agent.** A dispatch brief that named its report
path as `File to write to: <path>` still drew the Plan 00307
dispatch-declaration advisory saying no report destination was declared.
The advisory matches a narrower set of phrasings than briefs actually use,
so it nags on a correct dispatch, and a nag that is often wrong teaches
people to skim it.

**Candidate remedy:** recognise any phrasing that pairs a write verb or noun
("write", "report", "file", "output", "save") with a path in the brief, not
only fixed phrases. RED tests: the phrasing above is recognised, and a brief
with no path at all still draws the advisory.

**Remedy:** `dispatch_declaration.py`'s destination check no longer requires
a fixed "verb + to/in/under/into + path" grammar. `_prompt_declares_destination`
now pairs any destination KEYWORD ("write"/"save"/"report"/"output"/"store",
now including the noun "file") with a path-shaped token in the SAME CLAUSE
(split on sentence-ending punctuation or a newline) — a keyword match that
falls INSIDE the path token itself (e.g. "file"/"report" as hyphen-bounded
substrings of a plan-folder name like `...-file-based-report-handoff`) is
excluded, which is what keeps the Plan 00460 review finding m4 distinction
intact (a bare plan-folder mention in one sentence, with the actual verb in
the next, still does not count). Five new RED-then-GREEN tests in
`TestDestinationPhrasingRecognition`
(`tests/unit/handlers/pre_tool_use/test_dispatch_declaration.py`) cover the
exact reported phrasing, two other natural phrasings ("save ... at ...", a
bare "<label>: <path>"), a keyword-with-no-path prompt (still advises), and
the m4 clause-boundary regression guard.

### N30 — ✅ Remedied — more shell code that must survive a hostile PATH depends on a PATH command

**Found by the 00467 dogfood agent**, applying the Defence Before Fix method
to the watchdog defect fixed at 766677c1 (00466 N1's follow-up). An
independent search for the same class ("shell code that must survive a
hostile or stripped `PATH` runs a command looked up on `PATH`, and its
absence silently takes a wrong branch") found four more candidates:

- `scripts/venv_bootstrap.sh:443` and `:474` (`date`). The agent reproduced
  this idiom.
- `scripts/install/venv.sh:427` (`date`).
- `scripts/install/daemon_control.sh:40-43` (`pgrep`).

These are the venv and install paths, which exist to work when the host's
tools are broken, exactly as `resolve_venv.sh` does.

**Candidate remedy:**

1. Fix each instance: use a bash builtin (`printf '%(...)T'` for dates,
   `/proc` or `kill -0` for process checks). Where there is no builtin,
   make the missing command a loud, explicit failure rather than a silent
   wrong branch.
2. The detector the method asks for: a check over the scripts that must
   survive a hostile PATH (`resolve_venv.sh`, `venv_bootstrap.sh`,
   `scripts/install/*.sh`, the `bin/` wrappers) that flags an external
   command whose failure is not handled. It could be a `shell_audit` rule, or
   a test that runs each such script's functions under an empty `PATH`. It
   must catch the original watchdog shape, verified by reverting 766677c1 in
   a scratch copy.

**Remedy:** a new shared library, `scripts/lib/portable_time.sh`
(`_hp_epoch_seconds`, `_hp_timestamp <fmt> [--utc]`), gives every hostile-PATH
script a PATH-lookup-free way to get the time: bash's own `printf '%(...)T'`
builtin (>= 4.2) first, `date` on PATH second (the bash-3.2/macOS fallback,
since that builtin needs 4.2+), a loud stderr diagnostic + non-zero return
last — never a silently-empty/zero value feeding a decision. All five
`venv_bootstrap.sh` call sites, `venv.sh`'s `_venv_detached_build_wait`, and
three more instances the sweep (below) found in `config_preserve.sh`,
`rollback.sh` (x2) and `settings_deploy.sh` now go through it, each restructured
so a failure is either an explicit loud abort (`set -e` on a standalone
assignment, or an explicit `state=error`/`print_error` + `return 1`) or a
documented graceful fallback (`_venv_detached_build_wait` returning 1, which
its caller already treats as "use the generic wait bound") — never a garbled
or wrongly-branching value. `daemon_control.sh`'s `_daemon_process_exists`
gained a `/proc/*/cmdline` fallback (pure bash glob + `read -d ''`, no
external command) for when `pgrep` is unreachable, and when NEITHER is
available it says so loudly and answers "maybe" (assumes the daemon might be
running) rather than silently "no" — the caller only uses the answer to
decide whether to retry a status poll a little longer, so a false positive
costs a few seconds and a false negative costs a failed restart report.
`bin/hooks-daemon` and `bin/echd-capture` were reviewed and found not to need
this: the wrapper's PATH-dependent lookups are all standalone assignments
under `set -euo pipefail`, which already abort loudly, and the capture
helper's `date` use already has an explicit `|| echo 0` fallback for a
non-decision-affecting filename-uniqueness suffix.

The detector has both halves DBF asks for. Dynamic (primary): empty/narrowed-PATH
integration tests exercise every fixed call site directly —
`tests/integration/test_venv_bootstrap_hostile_path_epoch.py` (9 tests, all
five `venv_bootstrap.sh` sites), `test_venv_lock_wait_hostile_path.py` (3
tests), `test_daemon_control_pgrep_portability.py` (+3 new hostile-PATH
tests, using a FIXTURE `/proc` via the test-only `_HP_PROC_DIR` seam rather
than the host's real `/proc`, which could already hold an unrelated real
daemon process in this shared container). Static (complement, not the only
guard): `audit_shell.py` gained a `hostile-path-unguarded-command` rule,
scoped to the declared file list, flagging `date`/`pgrep` used without a
file-wide `command -v` guard — it does not judge control flow, just "the
fallback is still there". `test_hostile_path_detector_proof.py` is the DBF
step-3 proof: a scratch copy of `resolve_venv.sh` with 766677c1's fix
literally reverted (`_rv_wait_secs` swapped back for the bare `( sleep ...; kill -KILL ... ) &` list) reproducibly fails under a `sleep`-less PATH
(RED), while the real, current file passes the same scenario (GREEN) — using
a candidate that takes ~2 real seconds via a pure-bash `$SECONDS` busy-wait
(no external `sleep`/`date` needed in the fixture itself) so the proof is
not a timing race.

The sweep found and fixed 3 more instances beyond the 4 named in this
niggle's candidate remedy (all `date`, all `scripts/install/*.sh` siblings
of `daemon_control.sh`, sourced only from the same interactive
`install_version.sh`/`upgrade_version.sh` entry points as `daemon_control.sh`
itself — so architecturally the same class, not scope creep): a backup
timestamp in `config_preserve.sh`, a snapshot ID + manifest timestamp in
`rollback.sh`, and a backup timestamp in `settings_deploy.sh`. Total
instance count: 7 (4 named + 3 swept), all fixed.

### N29 — ✅ Remedied — `error_hiding`'s return-None-in-except check is evaded by returning a local assigned in the handler

**Found by the coordinator** reading the goal-flip agent's report. To clear the
`error_hiding` finding on a literal `return None` inside an `except` handler,
that agent assigned `None` to a local in the handler and returned the local
after the `try`. The behaviour is identical, and the detector no longer sees
it. So the check keys on syntax, not on the flow it exists to catch, and an
agent under QA pressure finds the gap on the first try. The goal-flip branch
has been told to undo the evasion and fix the code honestly.

**Candidate remedy:** judge the flow, not the token. An `except` handler that
binds a name read by a later `return`, where that name's only values are
`None` or a default and the handler logs or re-raises nothing, is the same
finding as a literal `return None`. RED tests: the evasion shape is flagged,
a handler that logs at warning or above and returns a documented sentinel is
not, and the literal form is still flagged. Then sweep the tree for existing
instances of the evasion shape, which would currently pass unseen.

**Remedied on the d-fresh branch** (`worktree-d-fresh`). `audit_error_hiding.py`
has a new rule, `return-none-via-local`. It flags an `except` handler that binds
`None` or an empty default (`[]`, `{}`, `()`, `""`, `list()`, ...) to a local
when the function returns that local after the `try`, or returns `None` under
`if local is None:` / `if not local:`, with no real rebinding in between. It
does not flag a handler that re-raises or logs at warning or above. A named
sentinel constant is not this finding. The rule has its own id, so none of the
existing `return-none-on-error` exclusions can cover it. The literal check is
unchanged, and it now runs on `async def` too, which it silently skipped
before. Tests: `TestReturnNoneThroughALocal` in
`tests/unit/qa/test_audit_error_hiding.py`.

The flow now also follows these variants, each pinned by a RED-first test:

- a tuple-unpacked binding (`value, extra = None, []`);
- a binding under a condition inside the handler;
- an augmented assignment after the `try` (`rows += more`), which builds on
  the fallback and so does not clear it;
- a return in the `try`'s own `finally:`, later in the same handler, or in an
  enclosing `try`'s `else:`.

The same `try`'s `else:` is not flagged, because it never runs after a
handler. Appending to a list counts as surfacing only when the function
returns that list, raises it, or passes it to a logging call at warning or
above, `print`, `sys.stderr.write`, or a callee named for reporting
(`report`, `render`, `emit`). A caller-owned list does not count. The re-sweep
found no new instance. It also fixed an `IndexError` that ended the whole
audit on a single-part relative path such as `install.py`.

The sweep found 8 sites, and each was fixed with no exclusion. Two fixes
removed now-stale `silent-fallback` exclusions:
`sensitive_content._compiled_public_pattern` and
`flaggable_content_channel_guard._compiled_shape_pattern`. A guard regex
that does not compile now logs at WARNING once, naming the pattern.
`secret_redaction._resolve_active_path` logs an unreadable config at WARNING
(INERT), the same as a config that fails validation. `staged_lint_gate` says
at WARNING that a file was NOT checked when its lint tool cannot run.
`auto_continue_stop._parse_iso_timestamp` logs an unparseable transcript
timestamp at WARNING. `merge_to_main_approval` handles the unbalanced-quote
`ValueError` by running the next tokenising strategy inside the handler.
`server._handle_event_client` (the async literal) moves the success path into
`else:`. In `cli._qa_run_lock_holder`, a comment described the evasion as
deliberate. The site also hid a bug: a held lock with an unreadable pid was
reported as "nothing holds it", which dropped the restart warning. It now
reports `"unknown"`, and "cannot tell" is logged at WARNING.

### N28 — `project_containment` resolves a relative target against the payload cwd and ignores a same-command `cd`

**Found by the Plan 00464 agent** during its re-review fix round (S12). It is
an instance of 00464's own defect class: the payload `cwd` is where the
session started, not where the command runs. So `cd <elsewhere> && <write to a relative path>` was judged against the wrong directory, and the containment
verdict could be wrong in both directions.

**Remedied on the 00464 branch** (`worktree-plan-464-commit-gate-repo`,
827c45df) through the new `find_command_placements`, which every
path-judging guard is meant to share. Two sibling walkers still resolve
their own way: `reference_repo_freshness` (the 00464 agent fixes it on that
branch) and `secret_file_matching` (after the guard-defects branch merges,
in the shell-parser consolidation). Mark Remedied when 00464 lands; the
siblings are tracked in the coordinator's consolidation work.

### N27 — ✅ Remedied — `skill_scan` and `tool_report` build the transcript directory name two different ways

**Found by the 00468 core agent** (report on its branch,
`subagent-reports/260924-p468-core-opus-5-5.md`). Claude Code keeps a
project's transcripts under a directory named after the project path, with
characters it cannot use in a name replaced. `skill_scan` and `tool_report`
each derive that name with their own code, and they disagree for a path
containing `.` or `_`. So for such a project one of them reads the wrong
directory, finds nothing, and reports "no data" rather than an error.

**Candidate remedy:** one helper derives the transcript directory from the
project path, pinned to Claude Code's real rule (checked against a real
`~/.claude/projects/` entry for a path with `.`, `_` and `-`). Both commands
and every other derivation site use it (sweep for the other derivations).
The helper raises, not returns empty, when the directory does not exist and
the caller asked for it. RED test: a project path with `.` and `_` resolves
to the same directory from both commands.

**Remedy** (branch `worktree-p468-core`): Claude Code's real rule was read
from its shipped bundle. The per-project directory is
`join(<config dir>, "projects", uC(realpath(cwd)))`. `uC` replaces each UTF-16
code unit outside `[a-zA-Z0-9]` with `-`, and a name over 200 characters is
cut to 200 and suffixed with `-` plus the base-36 absolute value of a 32-bit
Java-style string hash. No real `projects/` entry for a path with `.` or `_`
exists in this container (only `-workspace`). So the expected values in the
tests were computed by running that JavaScript under node.

- `utils/claude_config.project_dir_name()` and `claude_project_dir(project_root, *, config_dir=None, must_exist=False)`
  implement it. `must_exist` raises `FileNotFoundError` naming the directory.
- Every derivation site delegates: `skill_scan.extraction.derive_transcript_dir`,
  `tool_report.analyser.transcripts_root_for` (which `block_report` re-exports),
  and the `cache-gaps` auto-discovery.
- `cache-gaps` names the directory it looked in. `tool-report` and
  `block-report` name a missing derived directory on stderr.
- Tests: `tests/unit/utils/test_transcript_dir_derivations_agree.py` (RED:
  skill_scan named the wrong directory), `TestProjectDirName`,
  `TestClaudeProjectDir`, and a
  `test_a_missing_derived_directory_is_named_on_stderr` test in both cli
  report test files. Release note 39.

### N26 — ✅ Remedied — `check_skill_references.py` scans zero files when run from a worktree

**Found by the 00468 core agent.** Run from any worktree, the skill
references QA check reports success after scanning 0 files. A check that
examines nothing and passes is a fail-open gate: every sub-agent's targeted
QA runs from a worktree, so the check has been silently vacuous exactly
where branches are verified.

**Candidate remedy:** find why the file discovery comes up empty in a
worktree (a `.git` file rather than a directory, or a path anchored to the
main checkout), and fix it. Separately, the check FAILS when it scans zero
files where skills exist, so a vacuous pass cannot recur. Audit the other
`scripts/qa/check_*.py` for the same "0 examined, PASS" shape and pin the
class with a test that runs each check from a worktree fixture.

**The cause, and two more instances (integration B2).** Each checker drops a
file whose path contains a noise-directory name such as `untracked` or
`worktrees`, and it tests the ABSOLUTE path. Every agent checkout lives at
`untracked/worktrees/<name>/`, so every file matches:

- `check_doc_truth.py` `_iter_markdown`: 0 docs scanned in every worktree.
  **Fixed on the B2 branch** (08c4be0e): it tests the path below `--root`.
  1785 docs scanned after, 0 violations. The test is
  `test_a_checkout_inside_a_worktrees_directory_is_still_scanned`.
- `audit_shell.py` `_is_excluded`: it keeps 0 of the worktree's `.sh` files, so
  `shell_audit` passes vacuously. Not fixed. B2 ran it by hand over the
  relative `scripts/` and skill-scripts directories: 52 files, no violations.
- `check_skill_references.py` (this entry): `_EXCLUDED_DIRS` holds both names
  and is tested against `path.parts`, so it is very likely the same cause.
  `check_github_urls.py` tests `path.parts` the same way and should be checked.

**Remedy** (branch `worktree-p468-core`):

- **Cause.** Not the `.git` file: `_should_exclude` matched `_EXCLUDED_DIRS`
  against the ABSOLUTE path's parts. `untracked` and `worktrees` are
  excluded names, and every worktree lives under `untracked/worktrees/`.

- **Audit.** All 22 `check_*.py` were audited. Two more had the same shape:
  `check_doc_truth.py` (0 docs from a worktree) and `check_github_urls.py`
  (0 files). `check_magic_values.py` matched `constants`, `fixtures` and
  `test` the same way, which is latent here and live for a checkout under
  such a directory. Only `check_project_handler_tests.py` had a zero guard.

- **Fix.** New `utils/scan_scope.py`:

  - `relative_parts(path, root)` gives the components below the scan root;
  - `vacuous_scan_failure(examined=, candidates=, noun=)` turns "examined 0 of
    N" into a failure.

  The four checks use both. From this worktree they now scan 699 (skill
  refs), 1,774 (doc truth), 4,038 (GitHub URLs) and 1,763 (magic values)
  files, with no new violations.

- **Class pin.** `tests/integration/test_qa_walkers_examine_files_from_any_checkout.py`
  copies the tracked tree under a path made of every excluded name
  (`test/fixtures/constants/build/examples/Completed/venv/ccy/untracked/worktrees/wt`).
  It runs each of the 14 tree-walking checks there and requires a non-zero
  examined count. RED: 4 failed (skill refs, doc truth, GitHub URLs, magic
  values). A second test requires every `check_*.py` to be listed as a
  walker or a fixed-input check, so a new check cannot skip the pin.

- **Existing tests.** The exclusion tests that asserted `passed` over a tree
  holding only the excluded file (the vacuous shape itself) now scan a clean
  companion file and assert the examined count. Release note 40.

The other 10 walkers are worktree-safe, and are pinned by the integration
test rather than given their own zero guard.

- **`audit_*.py` too.** The first audit globbed only `check_*.py`, so it
  missed `audit_shell.py`, which had the same absolute-path exclusion
  (`untracked`) and passed on 0 scripts from a worktree (the B2 integration
  found it too). It now uses `relative_parts`, reports `files_scanned`
  (62 from this worktree) and fails on examining 0 of N scripts. The pin
  classifies `audit_*.py` as well. `audit_error_hiding.py` and
  `audit_capture_corruption.py` were already relative, and already exit 1
  when they collect nothing (Plan 00364 Task 5.4). They are pinned by
  requiring their artefact from the hostile location.

- **Reconciled with B2.** B2's doc_truth fix (08c4be0e) and its git-visible
  and protected-path filter (fd6c5438) are kept. The noise-name test in
  `_iter_markdown` now goes through `scan_scope.relative_parts`, the one
  mechanism. B2's `test_a_checkout_inside_a_worktrees_directory_is_still_scanned`
  is kept. There was no duplicate helper to delete: B2 had used an inline
  `relative_to`. B2's new `check_unreachable_handle_branch.py` is classified in
  the pin as a counted walker.

- **The missing-root variant.** A walker could also examine 0 of 0, and pass,
  when its scan root was absent or empty. `check_unreachable_handle_branch`
  was the first one found. `vacuous_scan_failure` now fails on 0 examined in
  every case, and names the root as missing or empty. Every walker applies it
  now:

  - the five that already used it get the stricter rule;
  - it is added to `check_authored_path_stat`, `check_british_english`,
    `check_doc_snippets`, `check_eacces_safe_predicates`,
    `check_python_var_guidance`, `check_repo_hygiene`,
    `check_security_downgrade_flags`, `check_sensitive_content`,
    `check_skip_list_substring` and `check_unreachable_handle_branch`;
  - `check_git_history` fails on a `--repo` that is not a git repository. It
    no longer passes as "inert". 0 commits in a real repository still passes:
    a baseline at HEAD leaves nothing new to sweep.
  - `check_python_var_guidance` also fails when one of its declared default
    roots or files is gone, rather than skipping it.

  Pins in the same integration test:

  - every walker, run from a checkout that holds only `scripts/qa/` minus its
    shell scripts, fails or examines something. RED: 6 walkers passed on 0.
  - every walker pointed at a missing root, and at an empty one, through its
    own root option, exits non-zero. RED: 3 more (`check_git_history`,
    `check_python_var_guidance`, `check_sensitive_content`), then
    `check_repo_hygiene` on an empty git repository.
  - `ROOT_OPTIONS` must name every walker's root option except
    `check_magic_values`, which has none (the gutted checkout covers it), and
    `audit_error_hiding`.

  Tests that asserted a pass over a tree with nothing to scan now add a clean
  scanned file, or assert the failure. Release note 40.

- **`.git` and nested checkouts.** In `--path` mode, `check_sensitive_content`
  walked the tree with a raw `rglob("*")`. That read `.git` internals (commit
  messages, hook samples) and nested repositories as the tree's own files.
  `git ls-files` lists neither in the default mode. Sixteen walkers had the
  same raw recursive walk (`rglob`, or a `**/` glob in `check_doc_snippets`).

  - **Fix.** New `scan_scope.walk_files(root, pattern)` never enters `.git`, and
    it skips any directory below the root that holds a `.git` entry (a
    worktree, submodule or clone). Every walker now enumerates through it.
    `audit_capture_corruption` runs under a bare `python3`, so it loads the
    stdlib-only module by file path. A test pins that `scan_scope` imports only
    the standard library.
  - **RED.** A `--path` tree reported a planted term from `.git/COMMIT_EDITMSG`,
    from a nested repository and from a linked worktree. Only `real.txt` is
    reported now. The pin
    `test_a_walker_enumerates_through_the_shared_walk` failed for all 16
    walkers. Examined counts on this repository are unchanged.

### N25 — a slow handler runs out the client's 30 s budget, and a timeout is an ALLOW for the whole PreToolUse chain

**Found by the guard-defects security review 2**
([report](subagent-reports/260924-n466-guards-review2-opus-5-5.md), B1 and
m3). `.claude/hooks/pre-tool-use` gives the daemon `--timeout-ms 30000`. On a
read-side socket timeout, `.claude/init.sh` (about lines 1654-1661) emits
`hookSpecificOutput` with context only, which is an ALLOW for every non-Stop
event. So any handler that can be made slow enough bypasses every guard
behind it, not just itself. Two instances are measured:

- `destructive_git`'s `strip_inert_spans` takes 99 s on a 200 KB command.
  That is already on main.
- The guard-defects branch's interior-wildcard DP takes 31 s on a crafted
  60 KB command. That one is fixed on its branch as review 2's B1.

Fixing each slow handler one by one leaves the class open: the next
super-linear regex or DP reopens it silently.

**Candidate remedies (the class, not the instance):**

1. The daemon enforces a per-event deadline well under the client budget
   (for example 20 s for the whole chain). When it passes, the remaining
   SAFETY+BLOCKING handlers are treated as having raised, which means DENY
   with a "not judged in time" reason under N24's fail-closed rule.
   Advisory handlers are skipped with a note.
2. Fix the measured instance: `strip_inert_spans` becomes linear, with a
   timing test at 200 KB.
3. A test harness drives every SAFETY handler with large hostile inputs
   (long runs of quotes, backslashes, wildcards and nesting) under a time
   bound, so a super-linear path fails CI rather than a client.

Deliberately NOT a remedy: making the client fail closed on timeout. A
daemon that is merely slow (an overloaded host) would then block every tool
call. The deadline belongs inside the daemon, where it can tell safety
handlers from advisories.

### N24 — `daemon.strict_mode` never reaches the live daemon, so every guard fails OPEN on a handler exception

**Found by the guard-defects security review 2**
([report](subagent-reports/260924-n466-guards-review2-opus-5-5.md), M3), with a
live probe against this repository's own daemon. `.claude/hooks-daemon.yaml`
sets `strict_mode: true`. A Write payload that makes a handler raise
(`ValueError: no path specified`, the still-live N5 shape) came back as
`additionalContext: "Handler exception: ..."`: an ALLOW, not the strict-mode
`SYSTEM ERROR ... blocking for safety` deny.

`daemon/controller.py:959` reads `self._config.strict_mode if self._config else False`. The constructor's own comment (`:162-166`) says the `config`
parameter "is not populated by the real daemon startup path", and
`get_controller()` (`:1210`) builds `DaemonController()` with no config. So
`strict_mode` is inert in every install. Every SAFETY guard treats its own
crash as "no match". The per-guard wrapper that N11 adds to `secret_file_guard`
is the only thing between a crash and a bypass, and no other guard has one.
The N5 and N11 entries' claim that "this repository runs `strict_mode: true`,
so here the crash denied" is false.

**Candidate remedy (both halves):**

1. Plumb `config.daemon.strict_mode` into the controller's real startup path,
   through the same narrow-slice injection already used for `ChainConfig`.
   Test it through `get_controller()` and a real daemon start, not by
   constructing the controller with a config the daemon never passes.
2. Independently of `strict_mode`, the chain denies when a handler tagged
   SAFETY and BLOCKING raises, because a safety guard that crashes has not
   judged the call. That closes the class for every guard at once, including
   the review's m1 (`handle()` outside the fail-closed wrapper).

RED tests: a live-path daemon with `strict_mode: true` denies on a raising
handler; a SAFETY+BLOCKING handler that raises denies even with `strict_mode`
off; a non-safety advisory handler that raises still allows, and says so.

### N23 — `recovery_cron_advisor` hands one request's lifecycle phase to another, through the singleton

**Found by Plan 00449's agent** while fixing the eviction race in the same handler. `matches()` stores the detected phase on the handler (`self._cached_phase`) and `handle()` consumes it. The handler is a daemon-lifetime singleton and `server.py` dispatches on a thread pool, so request B's `matches()` can overwrite the value between request A's `matches()` and `handle()`. A then advises on B's phase (CREATION guidance for a PROGRESS edit, say), and B finds the cache already cleared and detects again. It raises nothing, so no test or log shows it. This is a different class from Plan 00449's select-then-evict: per-call state parked on a shared object between two calls. It is out of that plan's scope by its own Non-Goals ("no audit of every mutable handler attribute").

**Candidate remedy:** stop caching on the instance (detect in `handle()`, or key the cache by thread with `threading.local`), with a RED test that interleaves two requests' `matches()` and `handle()`. Then treat it as a class: sweep for any `self._x` assigned in `matches()` and read in `handle()`. That shape is mechanical enough for a semgrep rule like `scripts/qa/semgrep/unlocked-eviction.yaml`.

**Checked against main after integration B2 (2026-09-24): still Open, not
fixed.** `recovery_cron_advisor.py` still declares `self._cached_phase: LifecyclePhase | None = None` in `__init__`, sets it in `matches()`
(`self._cached_phase = _detect_lifecycle_phase(...)`) and reads/clears it in
`handle()` (`cached = self._cached_phase; self._cached_phase = None`) — the
exact shape this entry names. `tests/unit/handlers/post_tool_use/test_recovery_cron_advisor.py`
has `test_matches_then_handle_uses_cached_phase` but no interleaving/
concurrency test. d-00449's `BoundedFifoMap` work (Plan 00449) fixed the
select-then-evict class across 12 sites in 10 handlers, including three
other spots in this same file, but explicitly excluded this per-call-state
class from its Non-Goals and recorded it here instead — see its report,
"Recorded, not fixed". Nothing else in integration batch B2 touches this
attribute. Remains a candidate for whoever picks up this ledger.

### N22 — `lsp_enforcement` takes another command's argument for a grep symbol lookup

**Found by the coordinator**, live. The command was `python scripts/qa/llm_qa.py format lint ... plan_qa docs_qa ... > out.txt; grep -E '^(✅|❌)|^QA:' out.txt`. It was denied with `BLOCKED [R-LSP-SYMBOL-LOOKUP]: ... pattern 'plan_qa' looks like a symbol search`. `plan_qa` is a positional argument to `llm_qa.py`, not to `grep`. The grep's real pattern, `^(✅|❌)|^QA:`, is not symbol-shaped at all. The handler found a `grep` somewhere in the command and then took a symbol-like word from elsewhere in it. `block_once` let the identical retry through, so the cost was one wasted turn. But every "run a QA tool, then grep its capture" command is the everyday shape here, and each one is a coin toss on which word gets picked.

**Candidate remedy:** tokenise the command into its separate simple commands (`;`, `&&`, `||`, `|`), and judge only the pattern argument of a `grep`/`rg` command, never a word belonging to a different command. RED test: the command above is allowed, and `python x.py foo; grep -rn 'def my_function' src/` is still caught on `my_function`. Once 00463/00464 land, this belongs on the shared shell lexer that the parser consolidation (coordinator queue) produces.

### N21 — ✅ Remedied — the semgrep QA gate passes when a rule times out

**Found by the 00414/00415 agent.** Its first version of a new semgrep rule timed out on `daemon/cli.py`, and `scripts/qa/run_semgrep_check.sh` reported PASS. A rule that times out has checked nothing for that file, so the gate fails OPEN, and the slower and more complex a rule is, the more likely it is to be silently skipped on exactly the large files it exists for.

**Candidate remedy:** a timeout, or any semgrep error entry in its JSON output (`errors[]`), fails the gate and names the rule and file. RED test: a rule forced to time out on a fixture makes the gate exit non-zero with the rule named. Check the other QA wrappers for the same "tool error reads as clean" shape, and pin the class.

**Remedied on the d-fresh branch** (`worktree-d-fresh`, 7946008c). Every `errors[]` entry is a violation naming the rule and file. A crash or an empty report fails as `semgrep-did-not-run`. RED test: `tests/unit/qa/test_run_semgrep_check.py`. The fixed gate caught a real timeout of `bounded-intent-unbounded-read-deferred` on `daemon/cli.py`, so the per-rule timeout is now 30 s. The same shape was fixed and pinned in 13 more wrappers. Separately, `github_urls`, `shell_audit`, `skill_refs` and `doc_truth` scanned 0 files from any worktree and passed; that overlaps N26. Detail: `subagent-reports/260924-d-fresh-opus-5-5.md`.

### N20 — ✅ Remedied — the capture-corruption auditor judges a multi-line single-quoted string one line at a time

**Found by the B1 integration agent**, as the stated limit of its fix for the auditor's backslash-continuation false positive. `scripts/qa/audit_capture_corruption.py` now joins `\`-continued lines, but a single-quoted string that spans physical lines (`echo 'x` followed by `y' >&2`) is still judged per line. So the redirect on the second line is not seen, and the echo is flagged. Nothing in the repository has that shape today, so it is latent. The same false positive that broke B1's gate would come back the first time someone writes one.

**Candidate remedy:** carry the open-quote state across physical lines for single-quoted strings too, joining the logical line the same way continuations are joined. RED test: the two-line single-quoted echo with the redirect on the second line is not flagged, and one without the redirect is.

**Remedy:** the auditor now reads each file through one tokeniser (`_logical_lines`), not a heredoc regex plus a per-line continuation join. The tokeniser tracks a stack of single, double and `$'` quotes, `$(...)`, backticks and arithmetic across physical lines. A command stays open while a quote or substitution is open, or while a line ends in a backslash. Each command is joined onto the line it starts on, and the lines it swallows are blanked, so findings keep their physical line numbers. Double-quoted strings, backticks and `$(` captures are covered too. A capture that names its function on the line after `$(` is now seen.

Checking the rest of the file for the same one-line-at-a-time assumption found three more defects in heredoc detection, fixed in the same change:

- **A heredoc operator was recognised anywhere on a line**, including inside quotes and comments. `scripts/upgrade.sh:949` (`printf '\n<<<UPGRADE_METADATA\n'`) made the auditor skip the last 12 non-empty lines of that file. That was a latent false negative: code nobody was auditing.
- **`<<"EOF"` and `<<\EOF` were not recognised**, so their bodies were audited as code.
- **Here-strings (`<<<`) and arithmetic shifts** could both be misread as heredocs.

A heredoc operator now counts only in code. A heredoc body starts after the first newline that is real shell syntax.

Because quote state now decides which lines are judged, a file whose quote, substitution or heredoc never closes is reported as `unparseable-shell`. Before, it was silently audited as one run-on line. Inside a `$(...)` it also tracks `case ... esac`, so a pattern's `)` never closes the substitution. That covers a pattern's optional leading `(`, extglob parens, `;;`, `;&` and `;;&`, a last clause without `;;`, and a `case` nested in a substitution inside a clause. `case` counts as a reserved word only where a command can start.

On all 65 scanned scripts, the new tokeniser extracts the same 227 functions and the same captured names as before, and reports no unclosed spans. Report: [subagent-reports/260924-n466-n20-opus-5-5.md](subagent-reports/260924-n466-n20-opus-5-5.md).

N16 is filed on the unmerged `worktree-n466-guard-defects` branch; it joins this file at integration.

### N19 — ✅ Remedied — the registry's options-collection failure is logged at debug level

**Found by the N13/N14 agent.** The handler registry's pass-1 `except Exception` logs a failure to collect a handler's options at debug level only. During the N14 work, a local variable that shadowed the new accessor made the registry silently drop EVERY handler's options, and only an existing registry test caught it before commit. In production, that failure would have looked like every handler running on defaults, with nothing at a visible log level.

**Candidate remedy:** narrow the catch to the exceptions that option collection can legitimately raise, and log anything else at error level with the handler name. If a handler's configured options cannot be applied, that is a degraded protection state and should surface in `health`. RED test: an injected failure while collecting options is visible at error level and in health.

**Remedy** (`worktree-n466-n13n14`, 4bb2a733 and fd8778a3): the pass-1 `try` covers only the `handler_options` call, which reads every block shape without raising, so anything it catches is a daemon defect. Each failure is logged at ERROR with the handler's registry key and a traceback, and recorded in `HandlerRegistry.option_failures`. The handler still registers, on its defaults: loud fail-open, which the coordinator chose over fail-fast because a daemon that will not start protects nothing. `health` lists the failures under "Handler options" and exits 1. Because `health` is only seen when someone runs it, `project_handler_load_checker` also receives the failures and opens each session with a "HANDLER OPTIONS NOT APPLIED" advisory naming each handler. Pinned by `tests/unit/handlers/test_registry_option_collection_failure.py` and `TestOptionFailures` in the checker's tests. Release note 62.

### N18 — ✅ Remedied — PlanWorkflow.core.md says the plan index is linted against one rule

**Found by the N13/N14 agent.** `CLAUDE/core/PlanWorkflow.core.md:407` and its deployed template copy say the plan index is linted "against one rule". `index-no-log` already made that false, and N13 adds `plan-stats-arithmetic` to the commit gate. The page is a deployed template pair, so it ships to clients.

**Candidate remedy:** name the rules, or better, point at the plan QA rule list, which is the source of truth, instead of counting. Change both copies of the pair together, and pin it with a doc-truth test that the page names no count that disagrees with the registry.

**Remedy** (`worktree-n466-n13n14`, e00a16c4): both copies now name `index-row-length` only as an example and point at a new `plan-qa --list-checks`, which prints every registered check with its `stage:level` pairs straight from `all_checks()`. `tests/unit/plan_qa/test_plan_qa_doc_truth.py` pins both copies: no count of rules or checks, the listing is named, every named check is registered, and the two sections are identical. Release note 63.

### N17 — ✅ Remedied — `skill_opportunity_detector` never receives its configured options

**Found by the N13/N14 agent.** `_options()` reads `self.config["options"]`, which only `configure()` populates. Nothing in `src/` calls `configure()`; the registry injects options as `_<key>` attributes instead. So a configured `check_interval_days` is ignored at runtime, and only the unit tests, which call `configure()` directly, exercise the option.

**Candidate remedy:** read options the way the registry delivers them, through the shared accessor. RED test: a handler built by the real registry from a config with a non-default `check_interval_days` uses it. Then audit every handler for a `configure()`-only options path, and pin the class with a test that instantiates each handler through the registry with a non-default value for every declared option and checks that it is honoured.

**Remedy** (`worktree-n466-n13n14`, bcd9bf61): two class pins in `tests/unit/handlers/test_registry_option_injection.py`. One builds every handler through the real `register_all` with a non-default value for each option in its `HANDLER_REFERENCE.md` Options table, and fails if the value is not delivered or never read. The other fails on any read of an option from a `self.config` dict. They failed on exactly three handlers, all now fixed: `skill_opportunity_detector`; `hook_registration_checker`, which ignored `auto_migrate_settings: false` (set in this repository's own config) and `auto_repair_registrations`; and `version_check`, which ignored `cache_ttl_hours` (now documented). Release note 61.

### N15 — ✅ Remedied — `remote-docs add` scans a capture with an unconfigured `sensitive_content` handler

**Found by the Plan 00468 docs agent.** `daemon/cli.py` (~:6377) builds `SensitiveContentHandler()` with none of its configured options for the capture-time `scan_text` in `remote-docs add`. So the scan at the moment a page is vendored runs with no public patterns at all. That is how 28 example UUIDs were vendored into `hooks.md` without a warning, to be caught only later by the tree-wide QA scan. The secret word list happens to be found only because the configured path equals the default. This is the same class as N14: a component reads a handler's behaviour without that handler's configured options.

**Candidate remedy:** construct the handler from the project's resolved config, through the same shared handler-options accessor N14 introduces. RED test: `remote-docs add` of a page carrying a configured public-pattern match reports it at capture time, and a non-default `secret_word_list_path` is honoured. Add the construct-without-config shape to N14's class audit.

**Remedy** (`worktree-n466-n13n14`, 0881dc94): `_sensitive_content_guard(project_root)` builds the handler from the project's config through `handler_options` and a new shared `registry.apply_handler_options`, with the word-list path resolved against the project root. `remote-docs add` and `refresh` now refuse a page matching a configured public pattern or a term from a non-default word list (`TestCaptureScanUsesTheConfiguredHandler`). The class audit found one more instance, `hooks-daemon check` probing `lint_on_edit` without its languages, also fixed. A new pin fails on any built-in handler constructed outside the registry without `apply_handler_options`. Release note 59.

### N14 — ✅ Remedied — log and payload redaction ignore a configured secret word list path

**Found by the 00414/00415 agent**, outside its brief. `utils/secret_redaction.py` `_resolve_active_path` reads `handler_cfg.get("options", {})` only when `isinstance(handler_cfg, dict)`. But `Config` coerces every handler entry to a `HandlerConfig` model (`type(c.handlers.pre_tool_use.get("sensitive_content"))` is `HandlerConfig`), so the isinstance test is never true. The daemon-wide resolver therefore never reads a configured `secret_word_list_path`, and always falls back to the default `.claude/block-words.secret`. The `sensitive_content` handler reads its own option correctly, so blocking still works. But payload capture and log redaction silently use the wrong list, or no list, in any project whose word list lives somewhere else. That is exactly how a secret term reaches a log. This repository is unaffected only because its configured path equals the default. `secret_file_matching.resolve_configured_patterns` carries a comment about this same mistake and fixed its own copy, so this is the second sighting of the class.

**Candidate remedy:** read the option through `HandlerConfig.options`, via one shared accessor for handler options that accepts either shape. RED test: with a non-default `secret_word_list_path`, a term from that list is redacted from a captured payload and a log line. Then audit every `isinstance(<handler config>, dict)` read of handler config across `src/`, and pin the class with a test or QA check that fails when handler config is read as a dict.

**Remedy** (`worktree-n466-n13n14`, e7f6b3d8): one accessor, `config.models.handler_options`, reads a block's options whichever shape it arrives in, and all 17 hand reads of `options` in `src/` go through it. A configured `secret_word_list_path` now reaches payload capture and log redaction (`TestConfiguredWordListPathReachesEveryLeakVector`). `tests/unit/config/test_handler_options_accessor.py` fails on any hand read of `options` outside the accessor, and on any local that shadows it. Release note 57, plus post-upgrade task 02 for projects with a non-default path to audit files written before the fix.

### N13 — ✅ Remedied — the plan-index statistics arithmetic is checked only by full QA, so a wrong count reaches main

**Found by the coordinator**, through Plan 00421's agent. Opening Plan 00468 updated the README statistics bullets (468 allocated, 455 distinct) but missed the closing self-check line (`454 + 13 = 467`). `check_repo_hygiene.py`'s `plan-stats-arithmetic` check catches exactly this. But it runs only in `llm_qa.py all`, and the commit-time plan QA gate that runs on every README commit does not include it. The inconsistent index was therefore committed and pushed (d10bbf13), and was found only when an agent ran the hygiene checker by hand. The same README gate already enforces row length and the 30-row completed window at commit time.

**Candidate remedy:** run the `plan-stats-arithmetic` check in the commit-time plan QA gate whenever the staged tree touches the plan index, or move the check into plan QA and have repo_hygiene call it. Either way there is one implementation. RED test: a commit staging a README whose statistics disagree with the self-check line is denied, and names the line to fix.

**Remedy** (`worktree-n466-n13n14`, 724c2d7f): the check moved into plan QA as `plan_qa/checks/stats_arithmetic.py`, and `check_repo_hygiene.py` keeps only a thin adapter, so there is one implementation (pinned). It blocks at commit when the commit stages the plan index and the disagreement is not already in HEAD, advises otherwise so inherited drift traps no unrelated commit, blocks in the sweep and advises at edit time. The denial names the line (`TestPlanStatsArithmetic`). Release note 58. It also delivers Plan 00408 Task 3.2.

### N12 — ✅ Remedied — a hand-built probe payload is logged as real traffic, because nothing tells a prober to mark it

**Found by the Plan 00467 plugin audit.** The audit fed synthetic PreToolUse payloads through `.claude/hooks/pre-tool-use` to probe handler verdicts. They carried no `synthetic_source` field, and their session ids (`plugin-audit-probe` and similar) match no known synthetic shape. So `daemon/synthetic_traffic.py` classed them as REAL traffic in `verdicts.jsonl`, including the orchestrator-simulate record that Plan 00418's enforcement decision will be read from. The marker (`SYNTHETIC_SOURCE_FIELD`, `synthetic_traffic.py:39`) is documented only in that module's docstring. CLAUDE/DEBUGGING_HOOKS.md, the handler-development guide and the agent-facing docs never mention it, so a prober cannot know to set it.

**Candidate remedy:** document the marker wherever probing a handler is taught (DEBUGGING_HOOKS.md, HANDLER_DEVELOPMENT.md, and the acceptance and playbook guidance), with a copy-paste payload that sets it. Consider a small `bin/hooks-daemon probe <event> <json>` helper that sets the marker itself. Add a test that the probing docs name the field.

**Remedied on `worktree-n466-n12`** (8fa4c354 to f813156a, merged in integration B3). `hooks-daemon probe <event> --json|--file [--as main|sub]` sends a payload through the project's own hook script with `synthetic_source: manual-probe` filled in, and refuses a marker the classifier would ignore. A probe names the thread it stands for with `probe_as`, so marking it no longer costs it the scoped handler it was probing. Every test and script that probes the live daemon is marked, and a guard pins that class. The probing docs name the field. Detail: [subagent-reports/260924-n466-n12-opus-5-5.md](subagent-reports/260924-n466-n12-opus-5-5.md).

### N11 — any exception in `secret_file_guard.matches()` lets the call through unless `strict_mode` is on

**Found by the 00466 review** (major M4, `subagent-reports/260924-n466-review-opus-5-5.md`). N5's crash was the second time an exception in this guard's `matches()` skipped the guard entirely; Plan 00357 was the first. Under the default `strict_mode: false` the chain logs the exception and allows the call. This repository runs `strict_mode: true`, so here the crash denied, but a client on the defaults fails open. One raise path is still live after N5, though it isn't exploitable: a file path containing a NUL byte.

**Candidate remedy:** make the guard structurally fail closed. A raise anywhere in its match or route computation becomes a deny naming the internal error, whatever the global `strict_mode`, because a protected-read guard that fails open is worse than a false deny. Pin it with a test that injects an exception at each stage. Then audit the other security guards that should behave the same (`sensitive_content`, `project_containment`, the destructive-git rules) and decide each one explicitly.

### N10 — a wildcard in the middle of a protected filename gets past `secret_file_guard`

**Found by the 00466 review** as a pre-existing problem on main, security-relevant. `cat .vault-pas?word` and `cat prod.vault-passw*rd` name a protected file through a glob the shell expands, and the guard does not deny them. The mention scan handles a leading or trailing wildcard (the N4 overlap logic), but not a `?`, `*` or `[...]` inside the name.

**Candidate remedy:** treat any shell-glob token as a pattern, and deny when the pattern could match a protected name. Compare against the protected basenames and stems, or expand it against the directory when that exists. Keep it no looser than the N4 rule. RED tests: interior `?`, `*` and bracket globs of each shipped protected pattern are denied, while unrelated globs such as `*.py` and `src/*.md` are allowed.

### N9 — ✅ Remedied — `docs_qa` judges gitignored markdown, so installing a Claude Code plugin fails local full QA

**Found by the coordinator** right after installing the Defence Before Fix plugin at project scope (Plan 00467). In this container Claude Code's config directory is `.claude/ccy/`, so the plugin's cache (`.claude/ccy/plugins/cache/...`) and marketplace clone (`.claude/ccy/plugins/marketplaces/...`) land inside the repository. Both are gitignored (`.claude/ccy/.gitignore:3: *`). `llm_qa.py docs_qa` then reported 12 `source-tree-markdown` findings, one per vendored spec file, and the tool FAILED. It reported 0 findings at batch A's gate, before the install. CI does not see this, because a fresh checkout has no `.claude/ccy/`. Every local full QA run, including the coordinator's integration gate, now fails on files that are not part of the project.

The docs corpus walks the filesystem without honouring `.gitignore` (`docs_qa/corpus.py`; it already special-cases `.claude/ccy/CLAUDE.md`, lines 149 and 421).

**Candidate remedy:** the corpus considers only tracked files plus untracked files that are NOT ignored, i.e. `git ls-files --cached --others --exclude-standard`, with a defined fallback outside a git repository. Keep any deliberate inclusion that is ignored but meant to be scanned explicit and named. RED test: a gitignored markdown file under a source-like directory produces no finding, and a tracked one still does. Audit the other QA corpora (plan_qa, doc_snippets, doc_truth, repo_hygiene, sensitive_content, british_english) for the same filesystem-walk assumption, and pin the class.

**Remedied.** `utils/git_repo.py` gained `git_visible_paths(project_root)`: one combined `git ls-files --cached --others --exclude-standard -z` call returning every path git would add, or `None` outside a git repository (callers then fall back to their pre-existing unfiltered walk). `docs_qa/corpus.py`'s `iter_markdown_paths` and `iter_corpus_paths` both filter through it; `.claude/ccy/CLAUDE.md` — deliberately untracked and gitignored, yet named in scope by `is_module_doc_path`'s own docstring — is kept via a small named exception set (`_GITIGNORED_MARKDOWN_INCLUDES`) rather than left an accidental gap, with a directory-descent rule (`_git_visible_ancestor_dirs`) so the walk still reaches it.

The class audit found a SECOND live instance of the same defect: `scripts/qa/check_doc_truth.py`'s `_iter_markdown` denylisted `.claude/ccy/plugins/marketplaces/` by name but not its sibling `cache/` directory, so a plugin's cached spec markdown could still reach `_check_shell_fences` as a false finding. Fixed the same way (filtered through `git_visible_paths`) and reproduced directly with a fixture that git-ignores `.claude/ccy/` and plants a violation inside it.

The rest of the named corpora were audited and left unmigrated, each for a stated, mechanically-pinned reason: `repo_hygiene`, `sensitive_content` and `british_english` already scan `git ls-files` directly by design (tracked-only is deliberate for hygiene/secret-scanning); `magic_values` and `error_hiding` are scoped to `src/`/`tests/`/`scripts/` only, which carry no `.gitignore` gap; `doc_snippets`'s glob set never reaches a nested `.claude/ccy/` subtree; `handler_reference` never walks a directory at all (it introspects the live `HandlerRegistry`); `plan_qa`'s `PlanTree.scan` descends only the configured plan directory via `iterdir()`, never a project-root-wide walk. `tests/unit/qa/test_qa_corpus_git_visibility_audit.py` pins this table as a ratchet: every `MIGRATED` entry is verified by AST to actually import and call `git_visible_paths`, every declared source path is checked to still exist, and every `ALLOWLISTED` entry must carry a non-trivial reason — mirroring `test_qa_package_dependency_direction.py`'s shape.

### N8 — ✅ Remedied — `reference_repo_freshness` says BLOCKED on a call it allows

**Found by the coordinator.** A Read of a fresh clone under `untracked/repos/` was denied (`R-REFERENCE-REPO-NOT-VERIFIED`), as the default `block_once` posture intends. The next command that named that clone, a `mv` moving it to `untracked/work/`, RAN. Its hook context still opened with `BLOCKED [R-REFERENCE-REPO-NOT-VERIFIED]: a read of a governed reference clone...`.

`_verdict()` (`handlers/pre_tool_use/reference_repo_freshness.py:575-576`) returns `GatingResult(decision=Decision.ALLOW, context=[message])` for a repeat in `block_once` mode, and for `advise` mode at :565. `message` is the verbose DENY rendering (`self._formatter.verbose(rule)`), which starts with `BLOCKED`. An agent reading its context is therefore told a call was blocked when it ran. It either retries something that already happened, or learns that "BLOCKED" means nothing.

**Remedy:** `RuleFormatter` gained a fourth rendering, `advisory(rule)` (`core/rule.py`) — same `rule_id` and the same `Rule.verbose` teaching content as `verbose()`, headed `ADVISORY` instead of `BLOCKED`, matching the "ADVISORY:" convention several handlers already use for their own hand-rolled non-blocking reports (no new format was invented). `reference_repo_freshness.handle()` now computes `_is_blocking(session_id, subject, mode)` — a preview of `_verdict()`'s own decision, pinned to it by `TestIsBlockingMatchesVerdict` — BEFORE building the message, and `_not_verified`/`_stale` select `verbose()` when the call will actually be denied and `advisory()` when it will not (an `advise`-mode result or a `block_once` repeat). `_verdict()` itself is unchanged; it stays the sole place that decides and records.

An AST-based static sweep of every handler for `Decision.ALLOW` built from `formatter.verbose`/`terse` content (directly or through an assignment chain) found exactly one other confirmed occurrence: `reference_repo_freshness` itself — the fix above. Two structurally similar but SAFE call sites surfaced for manual review (`lint_on_edit._run_lint_command`'s `language_name` parameter, `plan_qa_edit._advisory_result`'s `findings` parameter) and were confirmed not to carry deny-shaped content. `lsp_enforcement`, named by name as a suspect, was confirmed already correct: its `block_once` repeat and `advisory` mode both return a plain `dynamic_detail` string with no rule-id/BLOCKED prefix.

The class-wide guard lives at `tests/integration/test_allow_never_carries_deny_headline.py`: it drives every handler's own declared BLOCKING acceptance test twice against the SAME instance, replicating the history-recording step `DaemonController.dispatch()` performs after every route (`daemon/controller.py`) so a handler whose block-once state lives in the shared `HandlerHistory` data layer (not an in-instance dict, e.g. `lsp_enforcement`) genuinely sees its repeat call transition to ALLOW — and asserts the repeat's `reason`/`context` never contains the `"BLOCKED ["` signature. Confirmed RED against a deliberately reintroduced defect in `lsp_enforcement` (caught it), then GREEN once reverted. `reference_repo_freshness`'s own regression coverage lives in its unit tests (`TestBlockOnce`, `TestConfiguredModes`, `TestNotVerified`) instead, RED/GREEN-verified the same way — its only DENY acceptance test declares `harness_cannot_produce` (no fixture can build a real governed checkout), so the integration harness cannot reach it.

### N7 — ✅ Remedied — the regenerated CLAUDE.md guidance block is not deterministic, so every daemon restart can commit a reorder

**Found by the coordinator** at the batch A merge. The integration worktree's daemon had just regenerated CLAUDE.md, and that result was committed. The main checkout's daemon then restarted on the same tree and auto-committed `ce31d6d8` ("Auto: hooks daemon regenerated CLAUDE.md handler guidance"). The commit changed 18 lines both ways. Every change is the same handler markers in a new order: `tool-disable-advisor`, `project-handler-load-checker`, `hook-registration-checker`, `routine-qa-sweep` and `secret-file-hygiene-checker` among them. The earlier 00462 merge restart committed `6359ad0c`, changing 83 lines both ways, with the same shape.

`ClaudeMdInjector._collect_tiers()` emits handlers in the order of `self._handlers` (`core/claude_md_injector.py:642`) and never sorts them. Two daemons on one tree can therefore produce different blocks, apparently for handlers that share a priority. The results:

- A spurious auto-commit on restart.
- A CLAUDE.md conflict whenever two branches merge. This happened twice while building batch A.
- A worktree's regenerated block that never matches main's.

**Candidate remedy:** emit in a total order that depends only on the handler set, for example tier, then priority, then handler name. Test that two injector runs over the same handlers in shuffled input order produce byte-identical blocks. Check whether `HOOKS-DAEMON.md` generation has the same tie problem, and give it the same fix.

**Remedy shipped in commit `0dba7bfb`.** `_collect_tiers()`
(`core/claude_md_injector.py`) now sorts each of the three tier lists
(`promoted`, `progressive`, `fallback`) by handler name before returning
them — name alone is a complete total order because two active handlers
never share a name, and priority is not consulted because handlers from
different event chains are mixed into one flat CLAUDE.md tier where
priority carries no meaningful cross-event-type ordering. `daemon/ controller.py`'s handler collection was reading the chain's private,
unsorted `_handlers` list instead of its public `handlers` property (which
already sorts by `(priority, name)` on access, the same pattern
`EventRouter.get_all_handlers()` uses) — fixed to use `chain.handlers`.
`TestGuidanceOrderIsIndependentOfDiscoveryOrder`
(4 tests, RED against the pre-fix code) asserts forward- and
reverse-ordered handler lists inject byte-identical `<hooksdaemon>`
blocks. The sibling tie in `.claude/HOOKS-DAEMON.md` generation
(`daemon/docs_generator.py`'s `_render_handler_table()`) sorted by
priority only, so same-priority handlers kept registry order; fixed to
sort by `(priority, config_key)`, pinned by
`test_same_priority_handlers_are_order_independent` (1 test, RED against
the pre-fix code). Verified idempotent: `regenerate-docs` run twice in a
row produces the identical diff both times.

**Correction (00466 review, minor m6):** the commit message and the
paragraph above blamed `pkgutil.walk_packages()` for the unsorted input.
That is wrong — `pkgutil` sorts `os.listdir` output internally
(`_iter_file_finder_modules` calls `filenames.sort()`). The real unsorted
source is `HandlerRegistry`'s two `event_dir.glob("*.py")` loops
(`handlers/registry.py:467` and `:511`), which iterate in `os.scandir`
order; a third loop in the same file (line 198) already wraps its glob in
`sorted(...)`. The injector-level and docs_generator-level sorts above
still make each rendered artefact a pure function of the handler set on
their own — this correction is to the narrative, not to the fix's
soundness. Both `registry.py` glob loops are now wrapped in `sorted(...)`
too, so discovery order is deterministic at its source as well as at
every rendering layer.

**Also fixed (00466 review, nit n6):** the promoted tier's alphabetical
sort lost the reason a handler is promoted at all — the config author's
own `promoted_handlers` list order, chosen so the most-triggered guidance
reads first. `_collect_tiers()` now sorts the promoted tier by each
entry's INDEX in `self._promoted_handlers_order` (the author-authored
config list, kept alongside the pre-existing `frozenset` used for the O(1)
membership check) instead of alphabetically — still a complete,
deterministic total order, because that config list is a fixed value, not
a filesystem walk. The progressive and fallback tiers are unaffected;
alphabetical is the right call there, since nothing about them carries
author-chosen intent. Pinned by
`test_promoted_tier_follows_the_authors_promoted_handlers_order` (RED
against the pre-fix alphabetical code).

### N3 — ✅ Remedied — `goal_injection` treats any edit of an In Progress plan as the plan starting, and displaces the live goal

**Found by the coordinator**, live. The supervisor had set the goal to Plan
00461\. The coordinator then added a table row to this ledger's PLAN.md. That
edit drew `⚠️ GOAL DISPLACED: ... Plan(s) 00461 is now superseded by Plan 00466's goal`, and the handler wrote a goal-intent signal for 00466.

The handler's docstring says it writes the signal "when a plan flips to In
Progress". `handle()` never looks for a flip. It reads the PLAN.md from disk
after the write, and `_STATUS_IN_PROGRESS_RE` matches any plan whose
**Status** line reads In Progress. The once-per-plan-per-session latch is
the only limit. So the first Write or Edit in a session to any plan that is
already In Progress fires, however unrelated to its status. That includes a
ledger row, a task tick or a typo fix. The results:

- The supervisor receives a goal for a plan nobody started. For a rolling
  ledger that goal cannot complete.
- The displacement advisory tells the session that the goal it is really
  working was superseded.
- The ledger now tracks the edited plan as owed work, and the Stop hook
  challenges stops on its behalf.

**Candidate remedy:** fire only on a real transition. For `Edit`, the
`old_string` → `new_string` pair changes the **Status** line to In Progress.
For `Write`, the file's previous content (for example the pre-write copy
`write_clobber_guard` already reasons about, or git's `HEAD` version) did
not read In Progress, or the file is new. An edit that leaves an In
Progress status unchanged emits nothing and displaces nothing. RED tests:
an Edit that adds a table row to an In Progress plan emits no signal and no
advisory; an Edit flipping Not Started to In Progress still emits; a Write
creating a new In Progress plan still emits.

**Remedy shipped in commit `5676772d`.** `GoalInjectionHandler` gained
`_is_real_flip_to_in_progress`: for `Edit` it parses `old_string` with
`PlanDoc.parse` and answers directly from that fragment's own Status line
(absent → this edit never touched it → not a flip; present and not In
Progress → a flip). For `Write` there is no pre-write disk copy left by the
time PostToolUse runs, so git HEAD stands in for "before" — deliberately
not the Write/Edit `tool_response`, whose shape this codebase has never
verified for either tool (see this same folder's
`POSTTOOLUSE_FIXTURE_VERIFICATION.md`). A path absent at HEAD (new or never
committed) reads as nothing to flip FROM, matching the pre-existing
single-plan contract. The once-per-`(plan, session)` latch and the
retirement-refresh path are unchanged. `TestStatusFlipDetection` (8 tests,
3 RED against the old code) pins the contract; the module docstring, the
class docstring and `get_claude_md()` now state it explicitly.

**Follow-up in commits `6699fbbd` and `4813adc8`**, after review. The first
`_head_plan_text` caught `RuntimeError`/`OSError`/`ValueError` and returned
`None`, which `error_hiding`'s `return-none-on-error` check flagged; the
initial fix added an exclusion, which the review correctly rejected —
this project allows no new QA suppressions. Restructured instead: path
membership is now a plain `Path.is_relative_to` comparison, never a caught
`ValueError`, and `ProjectContext.project_root()` is called unguarded — by
the time any handler dispatches the daemon has always initialised it, so a
`RuntimeError` here means genuine misconfiguration and is left to propagate
to the dispatcher (`core/chain.py`'s existing per-handler exception
handling), rather than being swallowed into a false "nothing to compare
against". The lookup moved out to
`utils.git_facts.project_relative_head_text` so it has one home instead of
a per-handler copy. `error_hiding` now passes with zero violations and no
exclusion for this code.

The review also asked for the sibling to be fixed, not just documented as
accepted: `recovery_cron_advisor`'s Write-path completion check
(`_STATUS_COMPLETE_RE.search(content)` against the whole new file) shared
the exact same state-vs-transition defect shape for `**Status**: Complete`
— "only an advisory" was not a reason to keep it. `_detect_lifecycle_phase`
now calls `_write_is_real_completion`, which reuses
`project_relative_head_text` rather than a second copy: a Write whose
content reads Complete is COMPLETION only when the plan was not already
Complete at HEAD; otherwise the event matches no phase at all (never falls
through to PROGRESS/CREATION). `TestWriteCompletionIsTransitionBased` (4
tests, 1 RED against the pre-fix code) pins the contract. Its Edit path
(`_edit_results_in_status_complete`) already required the edit's own
`old_string`/`new_string` to assert Complete and needed no change.
`plan_close_approval._is_terminal_flip` was already transition-based
(compares `PlanDoc.parse(current).status` against the proposed status).
`plan_qa_edit.py`'s "In Progress" occurrences are guidance prose, not
status-detection logic.

**Second review pass (majors M2/M3, minors m4/m5, nits n3/n4/n7)**, fixed
together on the same branch:

- **M2 — a daemon restart silently disabled the retirement refresh.**
  `_maybe_refresh_on_retirement` gated on the IN-MEMORY `self._fired`
  latch, which a restart (`daemon_restart_verifier` requires one before
  every commit) empties, and N3's flip-only rule meant a later non-flip
  write no longer re-latched either — so a plan flipped in one daemon
  lifetime and completed in the next never dropped out of the combined
  `/goal` signal. Fixed by asking the PERSISTENT `GoalLedger` instead
  (`GoalLedger.has_live_entry` at the time; superseded by
  `owning_sessions` in the third review pass below), which survives the
  restart the latch does not. Pinned by
  `test_completing_a_plan_after_a_daemon_restart_still_refreshes_signal`
  (a fresh `GoalInjectionHandler` instance simulates the restart; RED
  against the pre-fix code).
- **M3 — the "goal survives a session restart" contract was silently
  dropped, not replaced.** Plan 00269 Task 2.1 deliberately chose "the
  first edit to an already-In-Progress plan in a NEW session re-fires" so
  a resumed session got its `/goal` back; N3's flip requirement removed
  that with no replacement, and the original release note wrongly called
  it "no action needed". Restored via `GoalLedger.reassert_session` (two
  new ledger methods: `session_has_entries` decides whether THIS session
  is new at all; `reassert_session` transfers ownership of the plan's
  already-live entry with NONE of `record_emission`'s displacement
  bookkeeping) and `_maybe_reassert_for_new_session`: a session with no
  ledger entries whatsoever that touches an already-live plan without
  itself producing a real flip gets its own signal written, no new ledger
  record, no "GOAL DISPLACED" advisory, and no risk of wrongly displacing
  some OTHER live plan. A session that already has its own live goal is
  unaffected. Pinned by three new tests in
  `TestNewSessionReassertion` (one RED against the pre-fix code) plus
  three new `GoalLedger` test classes. Release note 65 and the module
  docstring corrected to describe the restored contract instead of
  claiming no behaviour changed.
- **m4 — an Edit whose `old_string` carried only the bare status VALUE
  (no `**Status**:` prefix) missed a genuine flip.** `PlanDoc.parse` on
  `old_string` alone then found no Status line and read "never touched
  it". Fixed by reconstructing the pre-edit text from what is already on
  disk when this happens — reversing the SAME substitution the Edit tool
  performed (`_reconstruct_pre_edit_text`, honouring `replace_all`) — and
  parsing that instead of giving up. Pinned by
  `test_edit_whose_old_string_is_only_the_status_value_still_emits` (RED
  against the pre-fix code) plus a no-op control test.
- **m5 — a Write in a nested repository (a linked worktree, any nested
  clone) read HEAD from the PROJECT ROOT's repo, which never tracks the
  nested path, so it always answered "absent" and misread every write
  there as a genuine flip.** `project_relative_head_text` now resolves
  the FILE's own enclosing repository via `GitRepo.resolve_for` (the same
  `git -C <dir> rev-parse --show-toplevel` this project already
  centralises) and reads HEAD relative to THAT root; a project root that
  is itself a plain checkout is unaffected. Pinned by
  `test_a_file_in_a_nested_repository_reads_from_its_OWN_head` (RED
  against the pre-fix code) in `test_git_facts.py`, which also fixes
  `recovery_cron_advisor`'s Write-path COMPLETION check for the same
  reason (it shares the helper).
- **n3 — `git_facts.py` imported `core.project_context`, breaking its own
  documented "docs QA depends on this module alone" claim.**
  `project_relative_head_text` now takes `project_root` as a plain
  parameter instead — both callers already resolve
  `ProjectContext.project_root()` for other purposes, so nothing is lost.
- **n4 — acknowledged, not changed.** `_is_inside_project` fails open on
  an uninitialised `ProjectContext`; `project_relative_head_text` lets it
  propagate (by design, from the first review pass). Both new M2/M3
  helpers (`_maybe_refresh_on_retirement`, `_maybe_reassert_for_new_session`)
  now follow the SAME unguarded-propagation convention for consistency
  (and because `error_hiding` flagged the None-returning one) — the
  review itself called this "only reachable uninitialised", i.e. never on
  the real dispatch path, so the two conventions differing is intentional
  per the first review's explicit design, not an oversight.
- **n7 — release note 65's title said "already-terminal-status"; In
  Progress is not terminal.** Corrected to match the filename's wording.

`TestStatusFlipDetection`, `TestCombinedGoalSignal`,
`TestNewSessionReassertion`, `TestWriteCompletionIsTransitionBased`,
`TestProjectRelativeHeadText` and the new `GoalLedger` test classes all
pass; 518 tests across every touched handler/utils/core/daemon test file.

**Third review pass (major RV-M1, minors RV-m1 through RV-m5, nits RV-n1
through RV-n3)**: the second pass's M3 re-assert and M2 retraction worked
AGAINST each other — fixed together with an ownership schema change:

- **RV-M1 — `reassert_session`'s single-owner TRANSFER broke retraction the
  moment a second session touched a plan.** Once TEAMMATE reasserted a plan
  LEAD had flipped, `has_live_entry`'s exact `session_id` match stopped
  matching LEAD, so LEAD's own signal could never be retracted again when
  the plan completed — and a pre-existing gap on `main` meant a DIFFERENT
  completing session never retracted the flipping session's stale signal
  either. Fixed by making ownership ADDITIVE: `GoalLedgerEntry` gained a
  `sessions: list[str]` field that `record_emission`/`reassert_session` both
  APPEND to, never overwrite; `has_live_entry` checks membership in
  `sessions`; a new `GoalLedger.owning_sessions(plan_number)` (accepting an
  entry retired a moment ago for `RETIRED_TERMINAL_STATUS` too, subsuming
  RV-m2 below) feeds `_maybe_refresh_on_retirement`, which now refreshes
  EVERY owning session's own combined signal on a terminal write, not just
  whichever session's write triggered the check. Pinned by
  `TestOwnershipSurvivesASecondSession` (single plan, two plans, a second
  session owning a plan it never flipped — all RED against the pre-fix
  code) plus `TestReassertSession`/`TestOwningSessions` in
  `test_goal_ledger.py`.
- **RV-m2 — subsumed by RV-M1's fix.** `owning_sessions`' terminal-status
  grace window (live OR just-retired-as-terminal) means a concurrent
  reconciliation racing between a terminal write landing and this read
  cannot suppress a real owner's retraction.
- **RV-m3 — a SAME-session-id resume (`--resume`/`--continue`) never got
  its `/goal` back**, because the M3 gate (`session_has_entries`) reads the
  PERSISTED ledger, which still "knows" the session from its OWN earlier
  real flip even after its signal FILE was lost across a restart. Fixed
  with a second in-memory latch, `self._reasserted: dict[(session_id, plan_number), bool]`, reset every daemon lifetime and independent of
  `self._fired` — "have I, this process, already confirmed a signal for
  this pair" answers both a genuinely new session id and a same-id resume
  identically. The busy-session contract (a session that already
  real-flipped a DIFFERENT plan must not implicitly absorb an unrelated
  one) still holds via `session_has_entries`, now checked only when the
  session is NOT already a stakeholder of THIS specific plan
  (`has_live_entry`). Pinned by
  `test_same_session_id_after_a_restart_gets_its_signal_rewritten` (RED
  against the pre-fix code).
- **RV-m1 — the m4 reconstruction reversed the FIRST occurrence of
  `new_string`, not necessarily the actual edit site.** A table cell or
  title sharing the same text as the Status VALUE (e.g. "In Progress")
  could reconstruct the wrong span and report a false flip. Fixed:
  `_is_flip_via_reconstruction` now tries every occurrence of `new_string`
  as a candidate, keeps only candidates whose reversal leaves `old_string`
  unique (the Edit tool's own precondition for a non-`replace_all` edit),
  and reports a flip only when every surviving candidate agrees; disagreement
  or no viable candidate reads conservatively as "not a flip".
  `replace_all` has no uniqueness precondition to exploit, so it instead
  requires `old_string` to be ABSENT from the post-edit text (a clean
  application leaves none behind) before reversing every occurrence at
  once — otherwise conservatively "not a flip", the same trade-off as a
  contrived title-collision missed-flip case this review accepted as
  out of scope. **The `replace_all` half was not actually fixed by this**:
  review 3 (RV3-m1, below) found the "absent `old_string`" guard never
  fires on real `replace_all` output (a clean application always removes
  every `old_string`), and both pinning tests used a post-edit fixture no
  Edit tool call could produce. See RV3-m1 for the real fix.
- **RV-n1 — the m6 fix narrative still blamed `pkgutil.walk_packages()`**,
  which already sorts its own directory scan; the real (now fixed) source
  was `HandlerRegistry.register_all`'s two previously-unsorted
  `event_dir.glob("*.py")` passes. Corrected in `claude_md_injector.py`,
  `docs_generator.py`, and both files' test docstrings.
- **RV-n2 — the fail-open convention split flagged by the first review's n4
  was read as unresolved, not intentional.** Unified behind one helper,
  `_open_ledger()`, that every ledger-opening call site in the class now
  goes through. The FIRST fix (this bullet, as originally written) caught
  `RuntimeError` inside `_open_ledger()` itself and returned `None`. The
  coordinator's own review of that fix (niggle N29) found it evaded
  `error_hiding`'s `return-none-on-error` check by assigning the caught
  error to a local read by a later, separate `return` — same behaviour,
  different AST shape. Commit `c40d4ce6` undid that: `_open_ledger()` now
  raises with no `try`/`except` at all, and each caller decides its own
  fail-open action explicitly (see its docstring). `error_hiding`'s
  `log-and-continue` check independently confirmed the two callers with
  nothing substantive to fall back to (`_maybe_refresh_on_retirement`,
  `_maybe_reassert_for_new_session`) cannot legitimately catch-and-log
  either, so both now propagate to `core/chain.py`'s own documented
  per-handler fail-open boundary instead.
- **RV-n3 — no test covered the RV-M1 scenarios or RV-m1's collision case
  (now fixed above); a registry test read the chain's PRIVATE
  `._handlers` list, which only worked because the lazy `.handlers` sort
  had not run yet.** Made the precondition explicit: the test now asserts
  `chain._sorted is False` before reading `._handlers`, so an accidental
  earlier `.handlers` access fails loudly instead of silently passing for
  the wrong reason.

Release note 65 and the module/class docstrings corrected again to
describe the ADDITIVE ownership and per-daemon-lifetime reassert latch
instead of the second pass's (now superseded) single-owner transfer.

**Fourth review pass (major RV3-M1, minors RV3-m1 through RV3-m8, nits
RV3-n1/n3/n4)**, fixed together:

- **RV3-M1 — the retirement refresh was state-based, not transition-based,
  and `owning_sessions` answered from the FIRST ledger entry for a plan
  number, including long-retired ones.** A reopened-and-recompleted plan
  retracted the WRONG (original) session, and any later edit to an
  already-Complete, not-yet-archived plan re-signalled every past owner —
  handing a session a goal for a plan it never touched, or clearing a
  session's own unrelated manual `inject-goal` goal. Fixed on both halves:
  `_maybe_refresh_on_retirement` now shares `_is_real_transition` with the
  flip side (target: a terminal status), gated exactly like N3 already
  gates the flip; `GoalLedger.owning_sessions` answers from the plan's LIVE
  entry when one exists, or else its MOST RECENTLY retired terminal one,
  never the first in the list. Pinned by RED tests for a reopened plan
  completed by a different session, the same with a second unrelated live
  plan, a note on an already-Complete plan, and the same note not clearing
  a manual goal.
- **RV3-m1 — the `replace_all` guard from the third pass never fires on
  real Edit-tool output.** A clean `replace_all` application always removes
  every `old_string`, so the "bail if `old_string` survives" guard was
  vacuous, and the reconstruction blindly reversed EVERY occurrence of
  `new_string` — including an untouched Status line that merely already
  read the same text as a genuinely-replaced table cell. Fixed: when an
  occurrence overlaps the real (non-fenced) Status line AND at least one
  other occurrence exists, two verdicts are compared — reverse everything,
  and reverse everything except the Status line's own occurrence;
  disagreement reads conservatively as "not a flip" (the same accepted
  trade-off the third pass already used elsewhere, now correctly extended
  to also miss a genuine bulk Status-line-plus-cells flip, which cannot be
  told apart from the collision from post-edit text alone). A single
  occurrence with nothing to disambiguate against is answered directly, so
  the ordinary single-site case is untouched. Both third-pass tests
  rewritten to use a REAL post-edit fixture (the pre-edit text with the
  transformation actually applied), plus a two-cell variant and a
  single-occurrence regression control.
- **RV3-m2 — the post-write "is it In Progress now?" check used a
  literal-only regex, disagreeing with the fenced-block-aware, first-line-
  wins `PlanDoc` the pre-write side already used.** A fenced example or a
  per-phase second `**Status**:` line could make an unrelated edit look
  like a flip, or (via the Edit fast path trusting `old_string`'s own
  fragment in isolation) make a per-phase Status line edit look like a
  top-level one. Fixed: `handle()`'s post-state check now uses
  `PlanDoc.parse(plan_text).status`, and the Edit fast path is removed —
  every Edit goes through the same reconstruct-and-compare `PlanDoc.parse`
  machinery the Write side already used, so both sides of the transition
  agree on what "the real Status line" is. A useful side effect: a Status
  line carrying a trailing date qualifier (`In Progress (2026-09-24)`),
  which the old literal regex could never match, is now correctly detected
  too.
- **RV3-m3 — a session whose own combined `/goal` text NAMES a plan it
  does not own is never refreshed when that plan later completes.** The
  combined text lists every live ledgered plan project-wide, but ownership
  only grew through a flip or reassert of THAT specific plan, so a session
  reading a plan's number in its own text could still be carrying a stale
  copy of it forever. Fixed: `_write_combined_signal` now registers its
  session as an owner of every plan its own rendered text just named
  (`_extend_ownership`), not only the one that triggered the write.
  Deliberately NOT applied to the retirement-refresh fan-out (RV3-m5 below
  needs that path's cost bounded by EXISTING owners only).
- **RV3-m4 — the flip path never set the reassert latch, and the latch map
  was unbounded.** The session that just flipped a plan could write a
  second, redundant signal on its own very next non-flip edit in the same
  daemon lifetime (the reassert path's own latch had never been armed),
  and 400 distinct reasserting sessions grew `self._reasserted` without
  bound, unlike `self._fired`'s existing 256-entry FIFO cap. Fixed: the
  flip path now sets both latches on a confirmed write, and `_record_latch`
  is a single bounded-insert helper shared by both maps.
- **RV3-m5 — plan ownership grew without bound, and refreshing many owners
  re-derived the combined text once PER owner.** 150 teammate sessions
  touching one live plan gave 151 owners with nothing pruning `sessions`,
  and completing that plan took 0.25s (a full live-plan-directory read per
  owner) against 0.003s on main. Fixed: `GoalLedgerEntry.sessions` is
  capped (`_add_owner`, FIFO-drops the oldest owner past the cap), and
  `_maybe_refresh_on_retirement` renders the combined payload ONCE
  (`_render_combined`) and writes it to every owner, rather than
  recomputing it per owner.
- **RV3-m6 — the Write path still fired on an already-In-Progress plan
  that was not yet committed as such.** git HEAD lagging an uncommitted
  flip meant a teammate's plain Write to an already-live plan could be
  misread as a fresh flip, wrongly re-emitting a ledger record and
  displacing another live plan. Fixed: for a Write only (Edit reads its
  own before/after span directly, immune to this race), a positive
  transition verdict is narrowed further by `_ledger_plan_is_live` — the
  ledger, not HEAD, is authoritative for whether a plan has already
  started.
- **RV3-m7 — documentation drift**, all corrected: the third pass's RV-n2
  bullet still described the round-1 catch-and-log helper after `c40d4ce6`
  reverted it to a propagating raise; two mentions of a
  `_session_ledgered_plan` method that was never actually named that; the
  RV-m1 bullet's "pinned by two RED tests" claim for `replace_all` (see
  RV3-m1 above); release note 65's three over-claims (see the note itself).
  This entry's status is held at 🔄 until this pass lands.
- **RV3-m8 — a non-UTF-8 PLAN.md of any LIVE ledgered plan crashed the
  handler, on more paths than the ledger-file case review RV-m5 already
  fixed.** `goal_ledger.py`'s `_plan_state` and `_find_plan_md_text` (used
  by reconciliation and by rendering the combined text respectively), and
  `goal_injection.py`'s own `_read_plan`, each caught only `OSError`.
  Under `strict_mode` (this repo), an unrelated plan's bad bytes turned a
  routine reassert or refresh into a blocking "SYSTEM ERROR" for the
  handler's whole PostToolUse chain. Fixed: all three now also catch
  `ValueError` (covers `read_text`'s `UnicodeDecodeError`), treating the
  plan as unreadable rather than crashing — matching RV-m5's existing
  tolerance for the ledger file itself.
- **RV3-n1 — held for a follow-up, not code changed.** `c40d4ce6`'s
  propagating `_open_ledger()` is correct; the failure it exposes (a
  `RuntimeError` reaching a real dispatch) cannot happen in a real daemon,
  since the controller initialises `ProjectContext` before
  `register_all`. The one true gap this nit found — the docstrings not
  mentioning that `strict_mode` also STOPS the rest of the PostToolUse
  chain, not just denies — is now documented in `_open_ledger`'s
  docstring.
- **RV3-n3 — review-round narration trimmed from code comments and
  docstrings** (the module docstring, `_open_ledger`'s docstring, and the
  `docs_generator.py`/`claude_md_injector.py` `pkgutil` asides) to describe
  current state; the module docstring now points at this file for full
  history instead of citing review labels inline. This pass was
  incomplete — the method-level docstrings still narrated before/after
  comparisons; see RV4-n1 below.
- **RV4-n1 — the RV3-n3 trim was incomplete: method docstrings still
  narrated before/after comparisons.** Fixed the three the report cited:
  `goal_injection.py`'s `_maybe_refresh_on_retirement` docstring dropped
  the "measured at 0.25s … against 0.003s on main" benchmark comparison
  in favour of the current-state perf rationale it was making;
  `goal_ledger.py`'s `GoalLedgerEntry`/`reassert_session` docstrings
  reworded "the pre-fix shape … broke/let" into a present-tense "a
  transfer would break …" hypothetical; `session_has_entries`'s docstring
  dropped "the previous implementation read" in favour of stating
  directly what the per-entry field does not mean. Rationale comments
  that explain WHY an invariant exists by naming the review finding that
  motivated it (e.g. `RV4-M1: protect names …`) are kept — that is the
  sanctioned rationale pattern, not the narration this nit targets.
- **RV3-n4 — the committed CLAUDE.md block was main's handler order, not
  this branch's own code's order** (last written by a main merge, one
  restart away from a spurious reorder commit). Regenerated by a daemon
  restart before this pass's commit.
- **RV3-n5 — fixed via a PreToolUse ground-truth snapshot, not another
  inference patch.** A value-only real flip missed when "In Progress" also
  appears as a table cell or a plan title (C3b, m4d's C3) was genuinely
  indistinguishable from the Edit payload alone — no amount of layering on
  `_is_transition_via_reconstruction` could resolve it, since the two
  candidate pre-edit texts really do parse to different verdicts. Fixed by
  removing the need to infer anything in the common case: a new PreToolUse
  handler, `plan_status_snapshot`, runs immediately before the SAME
  Write/Edit `goal_injection` sees after it lands, reads the plan's
  CURRENT (pre-write) status straight off disk, and records it in a
  bounded, TTL'd (`utils/plan_status_snapshot.py`) in-memory store keyed by
  `tool_use_id` (carried by both the PreToolUse and PostToolUse payloads
  for the same call). `goal_injection`'s new `_resolve_transition` consumes
  it as ground truth — no reconstruction, no collision possible. The old
  inference (`_is_real_transition` and everything it calls) is KEPT as the
  fallback for the narrow window where no snapshot exists (a daemon
  restart between the two dispatches, or a payload with no `tool_use_id`),
  and that fallback path is logged when taken. RV3-m6's `_ledger_plan_is_live`
  narrowing is scoped to apply ONLY on the fallback path now: a
  snapshot-backed verdict already read the plan's true pre-write status off
  disk, so the git-HEAD race it guards against cannot have occurred. Both
  handlers share one trigger-matching implementation
  (`utils/plan_trigger.py`) so they cannot silently disagree about what
  counts as "the trigger" the snapshot was recorded for. New tests:
  `TestGroundTruthSnapshotResolution` in `test_goal_injection.py` (C3b,
  m4d's C3, a restart-fallback pair, and an empty-`tool_use_id` case),
  `test_plan_status_snapshot.py`, `test_plan_trigger.py`, and
  `tests/unit/handlers/pre_tool_use/test_plan_status_snapshot.py`. Both
  `_read_plan` sites (`goal_injection.py`, `plan_status_snapshot.py`) raise
  a shared `PlanUnreadable` (`utils/plan_trigger.py`) instead of returning
  `None` on a read/decode failure — a missing file is checked BEFORE the
  `try` (not an error; the ordinary brand-new-plan case), so nothing
  inside either function's `except` block ever returns `None`. Each single
  caller catches `PlanUnreadable` explicitly, logs a WARNING naming the
  path and cause, and takes its own documented fail-open branch. This
  replaces the error_hiding exclusion both functions carried; there is no
  exclusion for either any more.
- **RV3-n2 — `session_has_entries` now tracks what its name says, and the
  B4 decision is pinned here.** `record_emission` overwrites an entry's
  single `session_id` field with whoever re-emits for the SAME plan next,
  and `_prune` can drop the entry out of the ledger entirely — either one
  silently lost the "this session once recorded a real emission" fact the
  method's own docstring claimed to answer. Fixed: a ledger-wide, bounded,
  order-preserving `ever_recorded_sessions` list (`_EVER_RECORDED_KEY`),
  populated ONLY by `record_emission` (both the new-entry and re-emission
  branches) and read/persisted through the SAME locked read-modify-write
  every other mutator already uses — it survives both the field overwrite
  and pruning, because it is no longer derived from either. Deliberately
  NOT populated by `reassert_session`: a session that has only ever been
  ADDED to a plan's ownership (never performed a real emission itself)
  must still read as having no entries of its own, so it correctly remains
  free to become a stakeholder of a second, unrelated live plan it is
  asked to track too (Plan 00269's own motivating case, still pinned by
  `TestOwnershipSurvivesASecondSession` in `test_goal_injection.py`).
  **B4 decision (accepted by team-lead, review-4-prep):** review 3's own
  worked example for B4 ("T becomes an owner of 00298") is
  `_extend_ownership`'s (RV3-m3) project-wide combined-signal side effect
  — the combined `/goal` text is global, so absorption only decides WHO IS
  REFRESHED when a plan retires, not who owns what in any sense that needs
  gating. `session_has_entries` is a SEPARATE, narrower question ("has
  this session ever performed a real emission"), and `_extend_ownership`
  is left untouched — this pass did not restrict it further. **Updated by
  RV4-M1:** that premise held only up to the RV3-m5 owner cap, which
  absorption could push the FLIPPING session itself past — evicting the
  one session that most needs its own signal refreshed when the plan it
  started completes (main never had this bug; the cap introduced it once
  combined with absorption). Fixed by pinning the flipper as the entry's
  `primary_owner`, exempt from the cap; absorbed (non-flipping) owners are
  still FIFO-capped exactly as B4 already decided. `session_has_entries`
  and `_extend_ownership` are otherwise unchanged by this. Backing
  `GoalLedger`-level tests: `TestSessionHasEntries` in `test_goal_ledger.py`
  (`test_survives_session_id_overwrite_by_a_different_re_emitting_session`,
  `test_survives_pruning_past_the_entry_cap`,
  `test_false_for_a_reassert_only_session`). `_load_raw` raises a shared
  `LedgerUnreadable` (`utils/goal_ledger.py`) instead of returning `None`
  on a genuine read/parse failure — a missing file (nothing written yet)
  is checked BEFORE the `try`, not an error. Every one of its five public
  callers (`entries`, `record_emission`, `reassert_session`,
  `live_plan_numbers`, `session_has_entries`) catches it explicitly, logs
  its OWN WARNING naming the path, cause, and which fail-open branch it is
  taking, rather than sharing one central catch-and-log. This replaces the
  error_hiding exclusion `_load_raw` carried; there is no exclusion for it
  any more. New tests: `TestUnreadableLedgerRaisesADomainException` in
  `test_goal_ledger.py`.

New tests: `TestOwnershipSurvivesASecondSession`-adjacent scenarios in
`test_goal_injection.py` (`TestReview3Fixes`, inheriting the
`TestNewSessionReassertion` fixture plumbing), new `replace_all`/fenced-
Status/uncommitted-Write cases in `TestStatusFlipDetection`, and new
`GoalLedger` test classes (`TestOwningSessionsAfterReopen`, `TestIsPlanLive`,
`TestNonUtf8PlanMd`) plus a `line_spans_outside_fences` primitive and its
tests in `utils/markdown_fences.py`.

**Fifth review pass (major RV4-M1, minors RV4-m1 through RV4-m7, nits
RV4-n1 through RV4-n7)**, fixed together (report:
`subagent-reports/260924-n466-goalflip-review4-opus-5-5.md`):

- **RV4-M1 — see the B4 decision update above:** the RV3-m5 owner cap
  combined with RV3-m3's absorption could evict the flipping session from
  its own plan's owner set once enough OTHER sessions touched any live
  plan it also named, so completing the plan never refreshed the
  flipper's own `/goal`. Fixed by pinning the flipper as the entry's
  `primary_owner` (never reassigned, exempt from the cap via a `protect`
  parameter threaded through `_add_bounded`), and by always including the
  completing write's own `session_id` in the refresh set regardless of
  what the ledger's owner set says. Pinned by
  `test_flipper_survives_absorption_past_the_owner_cap` (50-teammate
  absorption, `probe_gf4_evict2.py`'s E2) and
  `test_completing_session_is_refreshed_even_if_the_ledger_names_no_owner`
  in `TestReview4Fixes` (`test_goal_injection.py`).
- **RV4-m1 — the snapshot store's dict was mutated and iterated across
  threads with no lock.** The daemon dispatches every hook event through
  a `ThreadPoolExecutor`, and `record`'s eviction racing `consume`'s
  iteration raised `RuntimeError`/`KeyError` under real concurrency.
  Fixed: `PlanStatusSnapshotStore` now holds a `threading.Lock` around
  every mutation and iteration, matching `utils/config_cache.py`'s
  existing pattern. Pinned by a 4-thread stress test in
  `TestConcurrency` (`test_plan_status_snapshot.py`), confirmed RED
  (raised on 3/3 runs) before the lock and GREEN (3/3) after.
- **RV4-m2 — a snapshot could be stale by the time its own write landed.**
  PreToolUse runs before the permission prompt, which can precede the
  write by minutes; another session's write landing in that gap left the
  snapshot describing a file that no longer existed in that form. Fixed:
  `PlanStatusSnapshot` now carries a content hash (`hash_plan_text`) of
  the text it read; for a non-`replace_all` Edit, `_snapshot_is_fresh`
  reconstructs the candidate pre-edit text(s) and requires an exact hash
  match; a `replace_all` Edit or a Write cannot be reconstructed
  unambiguously (a collision can reverse an unrelated site too — the same
  shape RV3-m1 already works around at the verdict level, which does not
  extend to exact byte reconstruction), so those fall back to a
  `_SNAPSHOT_RECENCY_BOUND_SECONDS` (5s) staleness bound instead. On a
  stale snapshot, it is discarded and the existing inference fallback
  runs, logged as a distinct WARNING from the "no snapshot" case. Pinned
  by a race test modelling `probe_gf4_race.py`'s F3 (three plans; a
  second session's later flip of one must not let a first session's
  stale-snapshot-driven tick erase a THIRD plan's own displacement).
- **RV4-m3 — an `EACCES` (or other `OSError`) from the existence
  pre-check itself escaped as a raw, unwrapped exception**, in both
  `goal_ledger.py`'s `_load_raw` and `plan_status_snapshot.py` (the
  PreToolUse handler)'s `_read_plan`: the `is_file()` check ran BEFORE
  the `try`, so an unreadable parent directory or `ENAMETOOLONG` bypassed
  the domain-exception wrapping entirely. Fixed: the existence check now
  runs INSIDE the `try` — `return None` there sits in the try body, not
  an except handler, so it is not the shape `audit_error_hiding.py`
  flags — and every other `OSError` (including from `is_file()` itself)
  is caught and wrapped as the domain exception (`LedgerUnreadable`,
  `PlanUnreadable`) with a WARNING at the caller. Pinned by a
  permission-denied-file test in each affected test file, monkeypatching
  `Path.is_file` to raise `PermissionError`.
- **RV4-m4 — nothing told an operator that `goal_injection`'s
  ground-truth snapshot path needs `plan_status_snapshot` enabled.** The
  handler shipped opt-in (disabled by default), so a fresh install ran on
  inference alone with no signal that the ground-truth path was even
  available. `Handler.depends_on` looked like the natural coupling
  mechanism but has zero consumers anywhere in `src/` — not a real
  option. Fixed the simpler way team-lead offered: `get_default_enabled()`
  flipped from `False` to `True` (opt-out), with the docstring, the
  generated-config template (`daemon/init_config.py`), and the upgrade
  reference config (`.claude/hooks-daemon.yaml.example`) all updated to
  match — three independent sources of truth for one handler's default,
  each with its own drift-guard test
  (`test_default_enabled_template_consistency.py`,
  `test_reference_config_completeness.py`), both of which were ALREADY
  failing before this pass touched anything (the handler was never
  registered in either).
- **RV4-m5 — two gaps in what review 3's own fixes were pinned against.**
  (1) `test_task_tick_on_a_not_started_plan_with_a_fenced_status_example_ stays_silent` (C7b) and the phase-2 collision test (C8) carried
  PRE-edit fixture content, but PostToolUse dispatches AFTER the tool has
  already landed the edit — the fixture defect masked the very collision
  the tests exist to catch. Fixed the fixtures to hold POST-edit content.
  (2) the RV3-m2 fix itself (`handle()`'s `PlanDoc.parse(plan_text).status`
  gate, not a literal `'**Status**: In Progress' in plan_text` check) had
  no direct mutation-testing pin — `probe_gf4_mutate.py` confirmed the
  suite stayed GREEN under that exact literal-substring mutant. Fixed by
  adding `test_terminal_transition_ignores_a_fenced_in_progress_example_ in_the_post_edit_text` to `TestReview4Fixes`, using a recorded
  pre-write snapshot (ground truth, RV3-n5) to isolate the OUTER
  post-write gate from the unrelated INNER reconstruction-uniqueness
  filter a byte-identical fenced collision would otherwise also trip.
  Confirmed RED against the literal mutant, GREEN against HEAD.
- **RV4-m6 — the daemon needed an actual restart and doc regeneration in
  THIS pass, not a stale claim that a previous pass already did it.** Ran
  `bin/hooks-daemon restart` then `bin/hooks-daemon regenerate-docs`;
  `CLAUDE.md` was already correct (no diff) at this point. **Correction
  (this claim was wrong when first written):** `.claude/HOOKS-DAEMON.md`
  was NOT already correct — the full-suite fallout later in this same
  pass (`test_real_repository_handler_doc_is_fresh`, below) found it
  still missing `plan_status_snapshot`'s row and handler count, because
  `regenerate-docs` here talks to the already-running daemon's in-memory
  handler registry rather than a fresh reimport. A plain
  `bin/hooks-daemon generate-docs` afterwards is what actually fixed it.
  The claim in RV3-n4 above is genuinely true only as of that later step,
  not this one.
- **RV4-m7 — documentation drift, corrected:** `HANDLER_REFERENCE.md`'s
  `goal_injection` entry described the OLD state-based trigger
  ("STATE-based … not transition-based") contradicting what N3 actually
  does; reworded to TRANSITION-based with the new-session-reassert
  exception named explicitly. `goal_injection.py`'s `_is_real_transition`
  docstring still described a removed "`old_string` FIRST witness, used
  DIRECTLY" fast path (RV3-m2 removed it); reworded to describe only the
  current always-reconstruct behaviour. `get_claude_md()`'s "every
  session ever handed a plan's goal keeps its own claim" was an overclaim
  past the owner cap even before RV4-M1; reworded to describe the
  pinned-primary-owner/FIFO-capped-absorbed-owners model precisely.
  Release note 65 updated: the terminal-drop claim now names the
  completing session's own guaranteed inclusion; the cap description now
  names the primary-owner exemption; the "can no longer be misread either
  way" claim is now scoped to "while that snapshot is trusted", with the
  staleness fallback named; the closing line now conditions "no action
  needed" on `plan_status_snapshot`'s default-enabled state rather than
  asserting it unconditionally. `auto_continue_stop`'s existing
  "Fail-open: a missing or unreadable ledger" claim (`HANDLER_REFERENCE.md`
  line ~3662) was re-verified rather than reworded — `live_plan_numbers`
  already catches `LedgerUnreadable` explicitly. **Correction (this claim
  was wrong when first written): RV4-m3 did NOT make that catch complete.**
  It fixed only `_load_raw`'s own existence check; `_plan_state` and
  `_find_plan_md_text` — `live_plan_numbers`' own siblings, reached via
  `_reconcile` on every call — kept a raw `PLAN.md.is_file()` outside
  their try, so an `EACCES` on a search-denied plan folder still escaped
  `live_plan_numbers` unwrapped. Not fixed until RV5-m6 below (see
  review-5's entry). `PLAN.md`'s N3 row, shown as ✅ Remedied, corrected
  back to 🔄 In progress per team-lead's standing instruction that it
  stays there until merged.
- **RV4-n1 — see above** (folded into the RV3-n3 entry it follows
  directly, for locality with what it corrects).
- **RV4-n2 — `GoalInjectionHandler.matches()`/`handle()` re-implemented
  `matched_plan_write_or_edit` instead of calling it**, duplicating the
  tool-name/path/`Completed`/project-membership checks `utils/plan_trigger.py`
  already centralises for both handlers (its own module docstring claimed
  they were shared, when only `plan_status_snapshot` actually called it).
  Fixed: both methods now delegate to `matched_plan_write_or_edit`
  directly, which made `_plan_path_pattern()`, `_is_inside_project()` and
  `_COMPLETED_SEGMENT` genuinely dead code — removed along with their
  now-unused imports.
- **RV4-n3 — `record_emission`'s `LedgerUnreadable` warning did not say
  the save about to happen OVERWRITES the unreadable file.** For a
  transient `OSError` (as opposed to corrupt JSON), this silently
  destroys every live entry and `ever_recorded_sessions`. Fixed: the log
  message now says so explicitly.
- **RV4-n4 — `test_goal_injection.py` and `test_recovery_cron_advisor.py`
  each added their own copy of `test_git_facts.py`'s `_git` helper, each
  with its own `# nosec B603 B607` suppression** — two new suppressions
  reviewing the same trusted-subprocess-call shape a third file already
  carried. Fixed: extracted the ONE helper (`run_git`) to
  `tests/support/git_fixtures.py` (a new `tests/support/` package,
  outside the daemon's own `src/`), with a single suppression; all three
  test files now `from tests.support.git_fixtures import run_git as _git`
  instead of defining their own copy.
- **RV4-n5 — `TestOwnershipSurvivesASecondSession`, `TestResumedSameSessionReassertion`
  and `TestReview3Fixes` each SUBCLASSED `TestNewSessionReassertion` to
  reuse its fixtures, so pytest collected and RE-RAN its tests once per
  subclass too** (108 `def test_` methods, 117 collected). Fixed:
  extracted the shared fixture plumbing into `_ReassertionFixtures` (a
  leading underscore keeps it out of pytest's `Test*` collection), and
  every class above now inherits ONLY the fixtures, not each other's test
  methods.
- **RV4-n6 — docstrings asserted unconditionally that this repo's
  `strict_mode` DENIES**, contradicting N24 (`strict_mode` never reaches
  the live daemon, so it is inert in every install including this one).
  Fixed in `goal_ledger.py`'s `_load_raw` and `goal_injection.py`'s
  `_open_ledger` docstrings: both now state that the config DECLARES
  `strict_mode: true` while noting, citing N24, that the setting does not
  currently reach the live daemon, so the fail-open branch is what
  actually runs.
- **RV4-n7 — a symlink-loop `PLAN.md` raised `RuntimeError` from
  `is_inside_project`'s `resolve()` call** (`utils/plan_trigger.py`,
  copied from `goal_injection`'s pre-existing shape) instead of being
  treated as "not inside the project". Fixed: `RuntimeError` added
  alongside `ValueError`/`OSError` in the except tuple. Pinned by
  `test_symlink_loop_never_raises` in `TestIsInsideProject`
  (`test_plan_trigger.py`), confirmed RED (raw `RuntimeError` propagated)
  before the fix.

**Full-suite fallout from RV4-m3/m4, found by a whole-tree run after the
fifth pass above and fixed together (none of these were in the review-4
report itself):**

- **`eacces_safe_predicates_static_check` flagged RV4-m3's own fix.**
  `plan_status_snapshot.py`'s (PreToolUse handler) raw `is_file` predicate
  is exactly the shape that checker exists to catch, regardless of the
  `except OSError` one line below it -- it is a pure regex over the
  source text, not a flow analysis, so it also matched the SAME method's
  own docstring prose describing the predicate. Fixed: the existence
  check now goes through `utils.path_predicates.path_is_file(path, unreadable_means=True)`; on a stat failure this assumes "yes, try to
  read it" rather than silently answering `False`, so an EACCES does not
  vanish -- it reaches the SAME read attempt immediately after, which
  hits the identical permission error and is what the method's own
  `except` still converts to `PlanUnreadable`. The docstring's prose
  mention of the predicate reworded to not contain the literal
  `.is_file()` substring the checker also matches. The RED/GREEN
  permission-denied test updated to patch `Path.read_text` alongside
  `Path.is_file` -- patching only the stat call no longer reproduces the
  failure now that the stat alone does not stop the method.
- **`test_no_handler_is_unclassified` had no `get_claude_md()` verdict
  for `PlanStatusSnapshotHandler`.** It does return guidance text (not
  `None`), so it needed a `_EARNS_GUIDANCE` entry, not an exempt one.
  Added, alongside fixing that handler's own docstring/`get_claude_md()`
  text still saying "ships disabled" after RV4-m4 flipped the default.
- **`test_no_undeclared_module_imports_plan_qa` flagged
  `utils/plan_status_snapshot.py -> plan_qa.model`.** The SAME import
  `utils/goal_ledger.py` already carries, for the same reason (reading a
  plan's status via `PlanDoc`/`PlanStatus`) and already declared in that
  test's `_KNOWN_EDGES` allowlist. Declared alongside it with the same
  rationale, rather than treated as a new design question.
- **`test_real_repository_handler_doc_is_fresh` found `.claude/HOOKS- DAEMON.md` still missing `plan_status_snapshot`'s row and the handler
  count.** The RV4-m6 `regenerate-docs` run earlier in this pass did not
  pick this up (talks to the already-running daemon's in-memory handler
  registry, not a fresh reimport); a plain `bin/hooks-daemon generate-docs`
  run afterwards did. Regenerated again; committed alongside this pass.

**Fifth review pass (review-5, `260925-goal-flip-review5-opus-5-5.md`) — 3
majors, 6 minors, 5 nits, all fixed with a RED test first for each:**

- **RV5-M1 — the RV4-M1 fix was itself a NEW regression against main.**
  `_maybe_refresh_on_retirement`'s unconditional `if session_id and session_id not in owners: owners = [*owners, session_id]` handed a
  `/goal` to a session that never owned the completing plan (K1: a
  non-owner teammate ticking a Plan Completion Checklist box got a goal
  for an unrelated live plan, PERMANENTLY — nothing later retracts it),
  and could WIPE a session's own manually-injected goal (K2: `inject-goal 00400` cleared by an unrelated plan's completion). Fixed: removed the
  unconditional add entirely — only an owner the ledger already names is
  refreshed. `primary_owner` pinning (RV4-M1) alone still fixes the
  original E2 scenario (the flipper survives absorption past the owner
  cap); nothing else was needed for that case. Pinned by
  `test_a_non_owner_completer_gets_no_goal` and
  `test_a_manual_goal_survives_an_unrelated_plans_completion`
  (`test_goal_injection.py`), both confirmed RED against the reverted
  unconditional-add line before the fix.
- **RV5-m4 (paired with RV5-M1) — the retirement-refresh fan-out never
  registered a refreshed owner as an OWNER of the other plans its own
  freshly rewritten text named.** So a session refreshed by one plan's
  retirement, whose combined text now names a SECOND still-live plan,
  never got retracted when THAT plan later completed (K4) — the fan-out
  path never applied RV3-m3's `_extend_ownership` the flip path already
  has. Fixed: `GoalLedger.add_owners(sessions, plan_numbers)`, a new
  BATCHED method registering every refreshed owner as an owner of every
  plan its combined text names, under ONE lock/save (not
  `len(sessions)*len(plans)` individual `reassert_session` calls).
  Pinned by
  `test_a_retirement_refreshed_owner_becomes_an_owner_of_the_plans_its_text_names`,
  confirmed RED with the `add_owners` call temporarily disabled.
- **RV5-M2 — the RV4-m2 5 s recency bound was fundamentally broken, in
  both directions.** PreToolUse runs BEFORE Claude Code's permission
  prompt, so ANY prompt a person takes longer than 5 s to answer made a
  genuinely-correct snapshot look "stale" and fall back to inference —
  reproducing N3's original bug (T1: a real `replace_all` flip missed
  after 6 s; T3/T4: a Write misread after 6 s). A BACKWARD clock step
  (T5) had the opposite failure: it could make an arbitrarily stale
  snapshot look fresh. Fixed by removing the time bound ENTIRELY —
  team-lead's own instruction, over the review report's softer "use
  `time.monotonic()`" suggestion: the store's orphan-eviction is now
  bounded purely by entry count (`_MAX_ENTRIES=256`, FIFO on a full
  store), never by a clock of either kind, which also resolves T5 as a
  side effect (no clock logic left to exploit). Freshness itself is now a
  pure hash comparison: the Pre handler PREDICTS the post-write text by
  applying the same Write/Edit FORWARD to the pre-write text it just read
  (reusing the existing shared `would_be_content` helper, already used by
  three other handlers, rather than inventing a parallel
  implementation), records the hash of that prediction; the Post handler
  hashes the REAL post-edit text and compares directly — no
  reconstruction, no clock, and it handles a deletion Edit (T7,
  `new_string=""`) uniformly, which the OLD reverse-reconstruction design
  could not (`_reconstruct_pre_edit_candidates` returned `[]` for it).
  **Correction (RV6-m2): "uniformly" here is about needing no
  reconstruction for any tool shape, not about detecting every race
  uniformly.** For a Write the predicted image is the write's own
  `content` field, independent of the pre-write text, so the freshness
  check can only ever catch a LATER write landing on the file before this
  one's own Post dispatch runs — it is blind to an EARLIER write that
  changed the plan's status between the Pre snapshot and this Write
  landing (probe W1). An Edit's prediction is built from its own
  before/after span, so the same race IS caught for it (probe W1e). Stated
  explicitly now in `_snapshot_is_fresh`'s own docstring and release note
  13, per the review's Direction.
  `PlanStatusSnapshot.text_hash`/`recorded_at` renamed/removed to
  `predicted_post_hash`; `PlanStatusSnapshotStore`'s `ttl_seconds`
  constructor param and `TestTtlExpiry` removed outright (the whole
  premise is gone). New tests:
  `test_snapshot_freshness_never_consults_the_clock` (the "bound never
  expires" mutant's kill — confirmed RED by temporarily reinserting a
  `time.time()` call into `_snapshot_is_fresh`, then reverted),
  `test_t1_replace_all_bulk_flip_survives_an_arbitrary_pre_post_gap`,
  `test_t3_write_with_unchanged_status_is_not_a_flip`,
  `test_t4_write_reopening_a_complete_plan_is_a_genuine_flip`,
  `test_t7_deletion_edit_is_resolved_by_the_snapshot` (all in
  `test_goal_injection.py`). RV5-m5's test-gap items folded in here: the
  RV3-m2 pin test's `old_string` was non-unique in its own pre-image (the
  real Status line and a fenced example both read
  `**Status**: In Progress`) — a real Edit tool call with that shape is
  REJECTED before this handler ever sees it — rewritten to use a unique
  `old_string` so it genuinely exercises the hash path instead of an
  Edit call that could never happen.
- **RV5-M3 — the `_KNOWN_EDGES` entry this pass's own prior session added
  for `utils/plan_status_snapshot.py -> plan_qa.model` was itself a NEW
  ratchet violation** (`test_qa_package_dependency_direction.py`'s
  allowlist: "Shrink this list when one goes; never grow it to make a
  new edge pass"). Unlike `goal_ledger.py`'s grandfathered entry (predates
  the ratchet, does REAL `PlanDoc` parsing), `plan_status_snapshot.py`
  only imported `PlanStatus` to annotate a dataclass field — no plan-text
  parsing of its own. Fixed per team-lead's simplification of the
  report's three options ("store `status.value` as a plain string, or
  make the store generic; do not move the module"): `PlanStatusSnapshot. status` is now a plain `str | None` (the status VALUE, not the enum);
  the Pre handler converts at its own boundary (`status.value`),
  `goal_injection` rehydrates at its own boundary (`PlanStatus(value)`)
  — both of those modules already import `plan_qa.model` for other
  reasons and sit outside the ratcheted `utils`/`docs_qa` trees, so the
  import moves to where it was always legitimate. The `_KNOWN_EDGES`
  entry and its module docstring's "six ... five that remain" count
  corrected to match.
- **RV5-m1 — `plan_status_snapshot`'s "harmless when goal_injection is
  off" claim was false.** `get_relevance()` is NOT a runtime gate — its
  only caller is `daemon/cli.py`'s `optimise` command (the
  config-optimisation REVIEW), never real dispatch, and `matches()`
  doesn't consult it either. So the handler genuinely runs (a file read,
  a `PlanDoc.parse`, a SHA-256 hash) on EVERY active plan's `PLAN.md`
  write in EVERY client where it is enabled (the shipped default),
  whether or not `goal_injection` is enabled and whether or not a ccy
  supervisor is armed. No existing primitive in this codebase lets one
  handler read another's resolved enabled-state at runtime (`Handler. depends_on` is stored but has zero consumers anywhere in `src/` — not a
  real option, confirmed by grep), so building genuine cross-handler
  gating would be a much larger architecture change than a minor finding
  warrants. Took team-lead's explicit alternative instead: corrected the
  module docstring and `get_claude_md()` to state the true, unconditional
  cost plainly, and to drop the stale "TTL'd" description (RV5-M2 removed
  the TTL — RV6-n1 found the phrase had survived in two OTHER spots this
  pass missed, `plan_status_snapshot.py:13` and its acceptance-test
  `safety_notes`; both fixed now).
  **Correction (RV6-m1): the "no existing primitive" claim above was
  wrong.** Five handlers already read a resolved config at runtime via
  `utils.config_cache.load_config_cached` (`recovery_cron_advisor.py`,
  `cron_stop_enforcer.py`, `cron_subagent_stop_enforcer.py`,
  `failsafe_cron_session_advisor.py`, `remote_docs_routing.py`), and the
  registry's own `handlers.registry.config_skip_reason` decides "enabled"
  from exactly that with a one-line rule. `Handler.depends_on` genuinely
  has zero consumers, as stated — that just was not the only route, and a
  smaller one existed. Fixed properly instead of documented: `matches()`
  is now gated on `goal_injection`'s resolved `enabled` state
  (`PlanStatusSnapshotHandler._goal_injection_enabled`), with an ABSENT
  block resolving to `goal_injection`'s OWN opt-in default (`False`), not
  `config_skip_reason`'s generic "absent means enabled" convention (which
  is tuned for the common opt-out handler shape). Pinned by
  `TestGoalInjectionGate` in `test_plan_status_snapshot.py`.
- **RV5-m2 — registration docs were missing.** Added
  `handlers.pre_tool_use.plan_status_snapshot` to
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.67.0.yaml` and a full
  entry plus summary-table row to `docs/guides/HANDLER_REFERENCE.md`
  (RV4-m4 already asked for the latter and it was never done).
  `check_handler_reference.py`, `check_generated_doc_drift.py` and
  `check_doc_truth.py` all still pass after adding these.
- **RV5-m3/K3 — a resumed lead under a NEW session id is still
  evictable, and the release note over-claimed otherwise.** The
  `primary_owner` pin (RV4-M1) protects only the ORIGINAL flipping
  session's id; a lead that resumes under a genuinely different id and
  reasserts ownership is an absorbed owner like any other, subject to the
  same FIFO cap as 50 teammates ticking a box. Team-lead's own fallback
  instruction: "Fix it if the payload gives you a stable link... If there
  is truly no signal, correct the release note... and record the
  reasoning in NIGGLES." **Researched and confirmed no such signal
  exists**: grepped this codebase for any existing session-lineage
  concept (`parent_session_id`, `previous_session_id`, `lineage`,
  `resumed_from`, `prior_session`, `session_lineage`) — none found.
  Checked the vendored `hooks.md` docs for any hook-payload field linking
  a resumed session's new id back to an old one — PostToolUse carries
  only `session_id` and `transcript_path`; no parent/previous-session
  field is documented anywhere. So there is genuinely nothing to key a
  fix on without fabricating a link the daemon cannot verify — a fix here
  would be a guess dressed as a fix. Corrected release note 65's "can
  never evict the one session that most needs its own signal refreshed"
  claim to name this limitation precisely (the pin is keyed on the
  flipping session's OWN id, not a resumed one), rather than either
  silently leaving the over-claim or inventing an unreliable fix.
- **RV5-m5 — see RV5-M2 above** (the RV3-m2 pin rewrite folded in
  there); the second half, "kill the `primary_owner` reassignment
  mutant" (`goal_ledger.py`'s `record_emission` re-emission branch
  handing `primary_owner` to the re-emitter), addressed separately — see
  the dedicated entry below.
- **RV5-m6 — doc over-claims, several distinct ones, each corrected
  where found rather than in one place:** (1) release note 65's snapshot
  match-check description updated for RV5-M2's forward-prediction design
  (was: "a content hash of the text it read"; now: "a content hash of
  the text it PREDICTS ... will produce", with the no-time-bound
  behaviour stated explicitly). (2) release note 65's terminal-drop
  bullet reworded to drop RV4-M1's now-REMOVED "including the completing
  session itself, always, even ... the ledger's own owner set does not
  (yet) name it" claim (RV5-M1 removed that behaviour) and to describe
  RV5-m4's batched cross-plan ownership instead. (3) release note 65's
  cap description corrected per RV5-m3/K3 above. (4) `NIGGLES.md`'s own
  RV4-m3/RV4-m7 entries corrected in place, above — see the two
  "Correction (this claim was wrong when first written)" notes. (5)
  `plan_status_snapshot.py`'s "harmless" claim — see RV5-m1 above. Also
  fixed as part of this item, the actual `EACCES` gap the RV4-m7 entry's
  false claim had papered over: `goal_ledger.py`'s `_plan_state` and
  `_find_plan_md_text` kept a raw `PLAN.md.is_file()` outside their own
  try (RV4-m3 fixed only `_load_raw`'s equivalent) — a live ledgered
  plan whose folder denies search escaped `live_plan_numbers` as a raw,
  unwrapped `PermissionError`. Fixed with the same
  `path_is_file(unreadable_means=True)` pattern RV4-m3 established;
  pinned by
  `test_live_plan_numbers_does_not_raise_on_eacces_from_plan_md_is_file`,
  confirmed RED against a reverted raw `is_file()` call.
- **RV5-n1 — the consolidated `# nosec` at `tests/support/git_fixtures. py:17` suppresses NOTHING** (bandit only scans `src/`, never `tests/`
  — confirmed via `scripts/qa/run_security_check.sh`/`pyproject.toml`),
  so it was inert in all three OLD per-file locations too, before RV4-n4
  consolidated them. Net change vs main is 3→1 suppressions, not
  "removed" as an earlier NIGGLES entry (RV4-n4, above) implied — noted
  here rather than reworded there, since RV4-n4's own description of
  what it DID (extracted one shared helper) is still accurate; only the
  "3→0" framing this later review corrects was implicit, not stated.
- **RV5-n2 — the legacy `primary_owner` back-fill
  (`goal_ledger.py:423-427`) uses `session_id`, the field for the LAST
  re-emitter, not the original creator.** A documented approximation
  that applies only to pre-upgrade entries (every NEW entry sets
  `primary_owner` at creation, correctly). Left as-is; the imprecision
  was already named in the surrounding comment, so this is a
  confirmation, not a fix.
- **RV5-n3 — a directory literally named `PLAN.md` records `status=None`
  ("no prior status") via `path_is_file` correctly answering `False` for
  a directory.** Harmless: the real Write this models would itself fail
  (a directory cannot be written as a file), so no Post ever fires to
  consume the recorded `None`. No functional fix needed; noted as an
  intentionally benign edge case.
- **RV5-n4 — the RV5-M2-era docstrings (`utils/plan_status_snapshot.py`'s
  module docstring, `_snapshot_is_fresh`) narrate the RV4-m2 → RV5-M2
  design transition at some length.** Rationale keyed to a failure mode
  (the old bound's exact break, T1/T5) is allowed per `comment_changelog`
  — this is not a version changelog — but the reviewer's own softer
  framing ("adds length") was taken as a signal to keep it as-is rather
  than trim further: the transition explanation is load-bearing for
  understanding why the design has NO time-based logic at all, which a
  future reviewer would otherwise reasonably reintroduce.
- **RV5-n5 — `probe_gf4_threads2.py` breaking (2-argument `record()`
  calls, now 3-argument) is confirmed NOT a defect** — the reviewer's own
  report already states this explicitly ("superseded by
  `probe_gf5_threads.py`"); no action taken.

**Review 6 (`260925-goal-flip-review6-opus-5-5.md`).**

- **RV6-M1 — `markdown_table_formatter` rewrote `PLAN.md` before it was hashed.**
  It runs at PostToolUse priority 26, ahead of `goal_injection` at 31, so
  RV5-M2's forward-hash freshness check read STALE on any write whose
  markdown was not already mdformat's canonical form -- worse than main on
  exactly the Write/reopen/bulk-edit shapes RV5-M2 set out to rescue
  (probe `probe_gf6_formatter.py`'s FE and FT4). This project enables all
  three handlers. Fixed by reordering: `Priority.GOAL_INJECTION` is now
  `30` and `Priority.MARKDOWN_TABLE_FORMATTER` is `31`
  (`constants/priority.py`), with the same swap in
  `.claude/hooks-daemon.yaml`, so `goal_injection` hashes exactly what the
  tool wrote, before the formatter ever touches the file. A guard test
  (`test_goal_injection_precedes_markdown_table_formatter`) pins
  `Priority.GOAL_INJECTION < Priority.MARKDOWN_TABLE_FORMATTER` and the
  real chain's resolved handler order, so a future priority shuffle fails
  loudly instead of silently reintroducing this. Two chain-level tests in
  `TestFormatterOrderingChain` (`test_goal_injection.py`) --
  `test_fe_edit_flip_adding_an_unpadded_table_still_writes_a_signal` and
  `test_ft4_write_reopening_a_complete_plan_with_an_unpadded_table_still_writes_a_signal`
  -- build a REAL `HandlerChain` from `PlanStatusSnapshotHandler` +
  `GoalInjectionHandler` + `MarkdownTableFormatterHandler` and confirm
  both that the flip is still detected AND that the formatter still runs
  (not passing merely because it never fired); the old (pre-fix) priority
  order was confirmed to reproduce the miss via a throwaway script,
  matching the reviewer's own repro. The report's Direction #3 ("check
  every other non-terminal Post handler that can rewrite a `.md` file
  before priority 31") was not separately audited this pass --
  `markdown_table_formatter` is the only PostToolUse handler below the new
  `goal_injection` priority that rewrites file CONTENT at all
  (`git_hooks_executable_fixer` only chmods); left as a standing check for
  a future PostToolUse handler that also rewrites `.md` content. The same
  stale ordering was also baked into `.claude/hooks-daemon.yaml.example`
  (the shipped template every fresh client install copies) and
  `daemon/init_config.py`'s generated project config (the string
  `hooks-daemon init` itself writes) -- both fixed the same way, with the
  same `MUST stay below/above` comments, or a fresh install would have
  reproduced this exact regression from day one. Also fixed a stale
  cross-reference comment (`constants/priority.py`'s
  `PLAN_STATUS_SNAPSHOT` docstring cited `GOAL_INJECTION = 31`, the OLD
  value). `tests/integration/test_template_priorities_match_the_constants.py`
  (pre-existing) confirms all three sources now agree with the code.
- **RV6-m1 — the RV5-m1 NIGGLES claim that "no existing primitive...
  lets one handler read another's resolved enabled-state at runtime" was
  wrong**, corrected in place above. Fixed properly instead of merely
  re-documented: `plan_status_snapshot.matches()` is now gated on
  `goal_injection`'s resolved config state
  (`PlanStatusSnapshotHandler._goal_injection_enabled`, via
  `utils.config_cache.load_config_cached`), with an absent block
  resolving to `goal_injection`'s OWN opt-in default (`False`) rather than
  the generic opt-out-shaped "absent means enabled" convention. Pinned by
  `TestGoalInjectionGate` (`test_plan_status_snapshot.py`, PreToolUse).
- **RV6-m2 — a Write's RV5-M2 freshness check only ever catches a LATER
  writer, and three docs claimed it "covers every shape uniformly."**
  `would_be_content` returns a Write's `content` field verbatim,
  independent of the pre-write text, so the comparison cannot see a race
  that changed the plan's status BEFORE this Write landed (probe W1); an
  Edit's prediction is built from its own before/after span and DOES
  catch that race (probe W1e). "Uniformly" in the RV5-M2 design was about
  needing no reconstruction for any tool shape, not about detecting every
  race uniformly — the claim was imprecise, not the design. Corrected in
  `_snapshot_is_fresh`'s own docstring
  (`handlers/post_tool_use/goal_injection.py`), release note 65, and the
  RV5-M2 NIGGLES entry above (this file).
- **RV6-m3 — the "narrow window" framing for `goal_injection`'s inference
  fallback undersold it in three places.** Besides a daemon restart
  between the Pre/Post dispatch of the same call and a payload carrying
  no `tool_use_id`, the fallback is also taken whenever nothing could be
  predicted at Pre time (`would_be_content` returned `None`, or the plan
  file could not be read), whenever the bounded store evicted the entry
  under load, and whenever a recorded snapshot is rejected as STALE
  (RV6-M1 is one concrete source of STALE, not the only one). Consolidated
  into one authoritative list in `_resolve_transition`'s own docstring
  (`goal_injection.py`), with `plan_status_snapshot.py`'s module docstring
  and `get_claude_md()` now pointing at it instead of re-narrating a
  shorter, stale version.
- **RV6-n1 — "TTL'd" survived RV5-m1's claimed removal**, at
  `plan_status_snapshot.py:13` and its acceptance-test `safety_notes`.
  Both fixed (see the RV5-m1 correction above).
- **RV6-n2 — `.claude/hooks-daemon.yaml`'s `plan_status_snapshot` comment
  said "Opt-in (false) elsewhere" while shipping `enabled: true`
  (`hooks-daemon.yaml.example`).** Fixed to state the true, unconditional
  default plainly.
- **RV6-n3 — a symlinked plan folder is ledgered under the link's number,
  not the target's.** ~~Confirmed harmless~~ -- **wrong.** Review 7
  (RV7-m3) reproduced it as a real defect: a plan COMPLETED through the
  real (non-symlink) path leaves a live ledger entry keyed to the link's
  number forever, because that entry was created through the link and
  never retires. See the Review 7 section below for the fix.
- **RV6-n4 — the snapshot store hand-rolled its own select-then-evict.**
  Correct under its own lock (the `unlocked-eviction` semgrep rule exempts
  a held lock) but a duplicate of exactly what `goal_injection`'s own
  `_fired`/`_reasserted` latches already use. Fixed: `PlanStatusSnapshotStore`
  is now backed by `handlers.utils.bounded_fifo_map.BoundedFifoMap` (Plan
  00449 P2), removing the second implementation; pinned by
  `TestUsesTheSharedBoundedMap` in `tests/unit/utils/test_plan_status_snapshot.py`.
  All of `TestRecordAndConsume`, `TestConsumeSnapshot`, `TestBoundedGrowth`
  and `TestConcurrency` (the existing black-box regression suite for this
  store) still pass unchanged.

**Review 7 (`260925-goal-flip-review7-opus-5-5.md`).**

- **RV7-B1 — review 6's renumbering broke four PostToolUse unit tests it
  never ran.** `constants/priority.py:205-218` shifted
  `git_hooks_executable_fixer` (27→26), `background_process_tracker`
  (28→27), `command_hints` (29→28) and `recovery_cron_advisor` (30→29) to
  stay adjacent to the `goal_injection`/`markdown_table_formatter` swap,
  but four `test_priority`-shaped assertions in those handlers' own test
  files still asserted the OLD literal. Fixed by asserting against the
  `Priority` constant instead of a literal in all four (renaming
  `test_priority_is_30` to `test_priority_matches_constant` in
  `test_recovery_cron_advisor.py`, since it is no longer 30) — the same
  fix the report itself directed, so a future priority shuffle cannot
  reintroduce this. The whole `tests/unit/handlers/post_tool_use/`
  directory was run once before finishing, since B1 was itself a missed
  sibling.
- **RV7-M1 — the RV6-m1 gate ran BEFORE the cheap trigger match, so every
  PreToolUse event paid a config read, and a broken config cost ~80ms per
  event.** `plan_status_snapshot.matches()` now checks
  `matched_plan_write_or_edit` (a tuple-membership test, no I/O) FIRST,
  and only consults the config-backed gate for an actual plan Write/Edit —
  the overwhelming majority of PreToolUse events never reach it at all.
  Separately, `utils.config_cache.load_config_cached` now caches a
  RAISED parse failure under the same `(st_mtime_ns, st_size)` signature
  as a successful parse, so a config broken by an edit after startup is
  re-parsed once per change rather than once per event — this benefits
  all six callers of the cache, not just this gate. The misnamed
  `test_gate_runs_before_the_trigger_match_so_a_non_plan_write_is_still_false`
  test already exercised the right shape and needed no change; new tests
  in `TestABrokenConfigIsCachedByFailure`
  (`tests/unit/utils/test_config_cache.py`) pin the caching behaviour.
- **RV7-m1 — the gate disagreed with what the daemon actually registers,
  in two shapes RV7-m1 measured (an absent `goal_injection` block, and
  `disable_tags` covering it), and its own docstring/test asserted the
  disagreement was correct.** `_goal_injection_enabled` now decides from
  `handlers.registry.handler_is_enabled` over the SAME per-event mapping
  `daemon.cli._build_handler_config_mapping` builds for `register_all`
  itself — the checklist's own "would `register_all` register this
  handler" predicate — rather than a hand-rolled reading of the config
  block that (wrongly) tried to honour `goal_injection`'s own opt-in
  default, which `register_all` never actually consults. An absent block
  now resolves to TRUE (matching the registry's own "absent means
  enabled" convention), reversing the RV6-m1 test's assertion; the load-
  failure test now writes genuinely unparseable YAML to a real config
  path instead of monkeypatching `_load_config` past the `except` branch
  it claimed to exercise. A new table-driven test
  (`test_gate_agrees_with_register_all_for_every_shape`) builds a REAL
  `HandlerRegistry`/`EventRouter` and asserts the gate's answer equals
  what got registered, for all six shapes RV7-m1's own table names.
- **RV7-m2 — the FT4 chain test passed against the PRE-fix priority
  order, so review 6's commit message claim "every finding has a
  RED-confirmed test" was false for it; FC3b (review 6's own Direction #2)
  had no chain test at all.** Both `TestFormatterOrderingChain` tests now
  assert the snapshot was consumed FRESH (no "is stale" WARNING in
  `caplog`), not merely that a signal file exists — the file-exists
  assertion alone cannot tell a fresh-snapshot pass from a lucky
  fallback-inference pass. FT4 now runs inside a real git repo whose HEAD
  already reads `**Status**: In Progress` (diverged from the actual,
  uncommitted `Complete` pre-write disk state) — the Write-only fallback
  reads that stale HEAD as "already there, no transition" and would write
  NO signal, so the test genuinely fails without a fresh snapshot; before
  this, `tmp_path` was not a git repo at all, so the fallback's
  `before_text is None -> True` branch always reported a transition
  regardless of ordering. Confirmed RED against the pre-fix priority
  order via a throwaway in-process monkeypatch of `Priority.GOAL_INJECTION`/
  `Priority.MARKDOWN_TABLE_FORMATTER` (matching the reviewer's own repro
  method): all three of FE, FT4 and the new FC3b failed. A new
  `test_fc3b_completion_write_with_reformatted_columns_still_retires_and_clears`
  test mirrors FT4's shape for the terminal-transition detector (a
  completing Write with an unpadded table, HEAD diverged the other way —
  already `Complete` — so the fallback would wrongly conclude no
  transition), first establishing ledger ownership via a real prior flip
  (`clear_goal_signal` only fires for a plan the ledger already names an
  owning session for). This NIGGLES entry — not the immutable `88991a06`
  commit message — is the correction of record for the RED-confirmation
  claim.
- **RV7-m3 — RV6-n3 was wrongly closed as harmless: a plan flipped
  through a symlinked folder is ledgered under the link's number and
  never retires.** `matched_plan_write_or_edit` (`utils/plan_trigger.py`)
  now re-applies the trigger pattern to the FULLY RESOLVED path (symlinks
  followed), expressed relative to the resolved project root, once
  `is_inside_project` has already confirmed containment (which resolves
  the same path itself) — that resolved capture is what both
  `goal_injection` and `plan_status_snapshot` key on, since both share
  this one function. A path that resolves outside the pattern entirely
  returns unmatched (logged), rather than trusting the unresolved
  capture. Regression test
  `test_a_symlinked_plan_folder_resolves_to_the_targets_number`
  (`tests/unit/utils/test_plan_trigger.py`) asserts a plan reached via
  `00301-l -> 00300-c` is captured as `00300-c`; confirmed RED against the
  pre-fix logic via a throwaway in-process comparison against the OLD
  (unresolved-capture) implementation. The RV6-n3 "confirmed harmless"
  text above is struck through and superseded by this entry.
- **RV7-m4 — release artefacts drifted from the RV6-m1/RV7-m1 fixes.**
  `config-changes/v3.67.0.yaml` gained `changed` entries for all six
  priorities RV6-M1 moved, with a `migration_note` on the two that matter
  (an operator who set custom priorities for `goal_injection`/
  `markdown_table_formatter` must keep the former below the latter).
  Both `config-changes/v3.67.0.yaml` and `docs/guides/HANDLER_REFERENCE.md`
  no longer claim `plan_status_snapshot` "runs unconditionally... whether
  or not `goal_injection` itself is enabled" — false since RV6-m1 gated
  it, and doubly false now that RV7-m1 fixed what the gate agrees with.
  The optional `ConfigValidator` startup warning (RV7-m4 Direction #2) was
  NOT added — genuinely optional per the report, and the guard test
  (`test_goal_injection_precedes_markdown_table_formatter`) plus the new
  `changed` migration_notes already cover the cases that matter.
- **RV7-n1 — `.claude/hooks-daemon.yaml`'s commented `options:` block sat
  under `markdown_table_formatter` instead of `goal_injection`,** so
  uncommenting it configured the wrong handler (it names `mode`,
  `once_per_plan_per_session` and `lines`, all `goal_injection` options).
  Moved to sit under `goal_injection`, matching `.claude/hooks-daemon.yaml.example`'s
  arrangement, which was already correct.
- **RV7-n2 — the release note shared ordinal 13 with an unrelated one and
  ran to ~1,300 words against a "one to three sentences" schema.**
  Renumbered to `33` (the next free ordinal, matching main), and cut to
  three sentences naming the operator-facing change, that the snapshot
  sensor ships on by default, and what a project running the inference
  fallback (an explicit opt-out) keeps instead. The mechanism narrative it
  carried is not lost: it already lives in `goal_injection.py`'s and
  `plan_status_snapshot.py`'s own module docstrings, which the shortened
  note now points at instead of re-narrating.
- **RV7-n3 — the "single authoritative list" of fallback triggers
  (`goal_injection.py:909-943`) omitted a trigger this same branch
  introduced:** the sensor not running at all, because
  `plan_status_snapshot` is disabled or its (RV7-m1-corrected) gate reads
  `goal_injection` as off. Added as its own bullet under "No snapshot
  recorded at all".

### N2 — `setup_worktree.sh` tells every agent to run the full suite through `run_all.sh`

**Found by the coordinator** when it set up an integration worktree.
`scripts/setup_worktree.sh` ends with an "Agent prompt template" whose last
line is `Run ./scripts/qa/run_all.sh before committing.`, and a "Run QA" hint
with the same command (lines 389 and 400). Step 7 also treats `run_all.sh` as
the QA entry point (line 343). Two things are wrong with that:

- `enforce_llm_qa` denies `run_all.sh`; `./scripts/qa/llm_qa.py all` is the
  only full-QA entry. An agent that follows the template is denied at once.
- Plan 00463 makes full QA a coordinator gate. A sub-agent runs targeted QA
  only, and the coordinator runs one full pass over the batch of merged
  branches. The template sends every sub-agent to run the full suite, which
  is the concurrent full QA that 00463 exists to stop.

**Candidate remedy:** the template names targeted QA (`llm_qa.py <tools>`
plus the touched tests) and says that full QA is the coordinator's
integration gate. The "Run QA" hint and Step 7 name `llm_qa.py`. A test
checks that the script names no denied QA entry point.

**Graduated to Plan 00463**, which owns the sub-agent QA policy.

### N1 — ✅ Remedied — `resolve_venv_python`'s fallback accepts a venv interpreter that cannot run on this host

**Found by Plan 00457's agent** (#55; recorded in 00457's JOURNAL as a
finding). When the slug-exact venv is absent, `resolve_venv_python` falls
back to globbing `untracked/venv-*/bin/python`, and accepts a candidate on
its executable bit alone. #55 is about a host whose only venv was built
inside a container. That interpreter may be for another architecture or
libc, or may symlink into a path that exists only in the container. It is
executable but cannot run. The fallback would then report "resolved", so
`bin/hooks-daemon` never reaches `_run_venv_free_verb` (the `repair` and
`signal` arms from Plans 00456 and 00457). It would fail when it runs the
interpreter, not with the clear venv-missing path. No test covers it on
either side of #53 or #55.

**Candidate remedies:**

1. The fallback proves a candidate RUNS, e.g.
   `"$candidate" -c 'import sys'` with a short bound, before accepting it.
   It moves on to the next candidate, then to the venv-free path, on
   failure. Test it with a fake executable that exits non-zero, and with a
   dangling symlink.
2. At minimum, a candidate that fails at exec time produces a message
   naming the venv it tried and the `repair` command, not a raw exec error.

**Remedy** (remedy 1, plus remedy 2's diagnostic): every implementation
that trusted a venv interpreter's executable bit alone now proves it RUNS
first.

- Bash: `scripts/lib/resolve_venv.sh::_rv_pick_python`'s two glob loops
  (`venv-*/bin/python`, `venv-*/bin/python3`) probe each candidate with a
  new `_rv_candidate_runs` helper (`"$candidate" -c 'import sys'`) before
  accepting it, falling through to the next candidate — and eventually to
  `bin/hooks-daemon`'s venv-free path — on failure. The bound is enforced
  by a watchdog subprocess (`( sleep N; kill -KILL "$pid" )  &` + a
  blocking `wait "$pid"`), not a `sleep`-poll loop: a poll loop always
  costs at least one full poll interval even for a candidate that exits
  in milliseconds, because the first check almost always lands before the
  process has exited. Measured on this repo's own real venv `bin/python`:
  ~1005ms/candidate under an earlier `sleep 1`-poll draft, ~15-40ms/candidate
  under the watchdog. `HOOKS_DAEMON_VENV_PROBE_TIMEOUT` overrides the
  5-second default bound (mirrors `Timeout.VALIDATION_CHECK`). Both glob
  loops now report which candidate they rejected and why on stderr before
  moving on, closing remedy 2 for the bash side.
- Python: `resolve_existing_venv_python_with_diagnostics`'s shared
  `_pick_interpreter` closure (used by steps 3, 4 and 5) and step 2's
  metadata `python_path` check now all route through a new
  `_venv_interpreter_runs` helper before accepting a candidate — the SAME
  `-c 'import sys'` probe, via `subprocess.run(..., timeout=5)`. Steps 3
  and 5 (single-candidate) and step 4 (scan) each report which candidate(s)
  were executable-but-unrunnable and name the `repair` command, closing
  remedy 2 there too. The "slug-exact" fingerprint-keyed venv (step 3) is
  probed too, not exempted — #55 already showed an exact-fingerprint match
  can be container-built and still unrunnable (e.g. a shared/NFS-mounted
  `untracked/`), and this resolver only runs on a bash-side resolver-cache
  MISS, so the extra spawn never lands on the per-hook hot path.
- `resolve_existing_venv_python` (the simpler, no-diagnostics function)
  deliberately stays un-probed: it is called fresh on every user turn by
  `daemon_upgrade_detector`, which only reads `.daemon-metadata.json` next
  to the returned path and never executes it, so probing there would add
  a real hot-path cost for no correctness gain.
  `client_validator.py::validate_daemon_can_start` — the other caller,
  which DOES execute the result — already ran its own
  `subprocess.run(..., timeout=Timeout.VALIDATION_CHECK)` probe before
  doing so, so it needed no change. Both are recorded in the sibling audit
  in the delivery report.
- `check_canonical_callers.sh` was already the sibling-audit backstop for
  the bash side: it denies any OTHER shell script that iterates
  `untracked/venv-*` directly, so `_rv_pick_python` is the only bash glob
  site that needed the fix.

TDD: RED tests confirmed failing against the pre-fix code first, in both
`tests/unit/daemon/test_paths_resolve_venv_diagnostics.py::TestRunnabilityProbe`
and the new `tests/integration/test_resolve_venv_runnability_probe.py`,
covering a fake executable that exits non-zero, a dangling symlink, a
hanging candidate (bound respected), fall-through to a good second
candidate, all-candidates-bad reaching the venv-free path, and the
slug-exact venv unaffected when it genuinely works.

**Follow-up defect, fixed at integration (766677c1).** The B1 full gate
failed `tests/acceptance/test_v391_field_regression.py`. That test runs the
resolver with a PATH holding only a broken `python3`. The watchdog ran
`sleep` from PATH, so with no `sleep` it went straight to `kill -KILL`. A
working venv was then rejected as "timed out after 5s", which is the v3.9.1
field case this resolver exists to survive. The branch's targeted QA had
not run that acceptance test. `_rv_wait_secs` now uses `sleep` when PATH
has one. Otherwise it waits on `read -t` against a read-write
process-substitution pipe, which needs no PATH lookup, and the kill runs
only if the full bound elapsed. Two regression tests cover a PATH with no
`sleep`: a good candidate still resolves, and a hanging one is still
bounded.

**✅ Remedied** on main (B1, 2e6483a3).
