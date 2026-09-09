# Release Code Review — v3.63.0 — core / daemon / config / config_optimisation

Scope reviewed: `git diff v3.62.1..HEAD` restricted to
`src/claude_code_hooks_daemon/core/`, `daemon/`, `config/`,
`config_optimisation/`.

29 files, +4077 / -246. Diff captured at
`/workspace/untracked/scratch/diff-core.txt`.

## Verification performed

- Full diff read in five passes.
- `pytest tests/unit/core tests/unit/config_optimisation tests/unit/config tests/config`
  plus the venv-lock, worktree-reap, housekeeping and controller suites:
  **2610 passed**, 0 failed.
- Every changed module in this slice has a corresponding changed or existing
  test file. `core/front_controller.py` is the one module whose behaviour
  changed with no test change (an existing `tests/unit/core/test_front_controller.py`
  covers the old shape).
- No leftover TODO / FIXME / HACK / debug print / breakpoint in any added line.
- Three reproduction probes written and kept as evidence:
  - `/workspace/untracked/scratch/probe_allow_merge.py` — minimal two-handler
    chain, HEAD vs v3.62.1.
  - `/workspace/untracked/scratch/probe_corpus2.py` — all 205 handler-declared
    acceptance payloads through the real registry chain, HEAD vs v3.62.1.
  - `/workspace/untracked/scratch/probe_reap_path.py` — worktree reap path
    reconstruction, via the CLI's own `run_fn` injection point.
  - `/workspace/untracked/scratch/old_chain.py` — v3.62.1 `chain.py`, loaded
    standalone by the first two probes.

---

## BLOCKER 1 — A contentless early ALLOW now silently swallows every later handler's `guidance`

**Location:** `src/claude_code_hooks_daemon/core/chain.py:385-388`
(and the identical rule at `src/claude_code_hooks_daemon/core/front_controller.py:117-121`)

**Confidence: 95%** — reproduced against the shipped registry with default
config, using the project's own acceptance payloads.

### Problem

Plan 00242 replaced the terminal/non-terminal branch pair with one merge rule:

```python
if final_result is None or (
    restrictive and not is_restrictive(final_result.decision)
):
    final_result = result
```

For restrictive results this is correct and is what the plan intends. For
ALLOW results it silently inverts the previous behaviour:

| | which ALLOW result becomes the response |
|---|---|
| v3.62.1 | the LAST matching handler's |
| HEAD | the FIRST matching handler's |

`context` is unaffected — it is accumulated from every handler. But
`HookResult` carries four other fields that travel on an ALLOW and are taken
from `final_result` alone: `guidance`, `updated_input`, `worktree_path` and
`rule`. `guidance` is serialised into the response by
`hook_result.py` (`output["guidance"] = self.guidance`), so losing it is
user-visible.

The damaging case is a handler whose `matches()` is a deliberately broad
pre-filter but whose `handle()` returns a bare ALLOW. `verification_result_gate`
is exactly that, and says so:

```python
def matches(self, hook_input: dict[str, Any]) -> bool:
    """Cheap pre-filter: a Bash command that could contain a mutator."""
    ...
    return any(word in command for word in self._mutator_head_words())
```
(`handlers/pre_tool_use/verification_result_gate.py:268-275`)

At priority 34 it matches a large share of Bash commands and returns
`GatingResult(decision=Decision.ALLOW)` with no context and no guidance when
`_find` reports nothing. Under HEAD that empty result becomes `final_result`
and owns the response, so every later PreToolUse handler's `guidance` is
dropped.

### Evidence

Running all 205 handler-declared acceptance payloads through the real
registry chain (114 handlers registered, 57 on PreToolUse), HEAD vs v3.62.1:

```
205 declared payloads

DIFF verification-result-gate: Verification result gate - newline-separated verif
   matched: ['verification-result-gate', 'bash-safe-mode']
   guidance HEAD='VERIFICATION RESULT NOT CONSUMED: `yamllint` -> `git tag` ...'
   guidance OLD ='BASH SAFE MODE: this multi-statement invocation declares no ...'

DIFF bash-safe-mode: Bash safe mode - sequenced statements without a pr
   matched: ['verification-result-gate', 'bash-safe-mode']
   guidance HEAD=''
   guidance OLD ='BASH SAFE MODE: this multi-statement invocation declares no ...'

TOTAL DIFFS: 2 / 205
```

The second diff is the defect. On `bash_safe_mode`'s OWN acceptance-test
payload, HEAD emits **no guidance at all** where v3.62.1 emitted the
handler's full remedy text. `bash_safe_mode` is default-on and defaults to
`warn` mode, so the ALLOW-with-guidance path is its normal path.

The one-line `context` summary still reaches the agent, so the advisory is
degraded rather than invisible. What is lost is the actionable remedy.

The minimal form is `probe_allow_merge.py`:

```
HEAD    : guidance=None       updated_input=None
v3.62.1 : guidance='SUGGESTION: ...'  updated_input={'command': 'rewritten'}
```

### Why it matters

- Six shipped PreToolUse handlers return ALLOW with guidance
  (`ancestry_preserving_merge`, `ask_user_question_blocker`, `bash_safe_mode`,
  `git_stash`, `verification_result_gate`, `web_search_year`). Any of them
  sitting behind a broader-matching earlier handler now loses its remedy text.
- `updated_input` is the PreToolUse input-rewrite channel. No shipped handler
  uses it today, but a project handler is a supported extension point, and one
  at a higher priority number would have its rewrite silently discarded — a
  much worse failure than lost advisory text.
- `worktree_path` is safe only because `worktree_create` has exactly one
  handler. A second handler on that event returning ALLOW first would drop the
  path the forwarder prints.
- **Nothing tests this.** `tests/unit/core/test_chain.py` covers terminal ALLOW
  not stopping the chain, deny-survives-later-allow, and collect-all, but no
  test asserts which of two ALLOW results owns `guidance` / `updated_input`.
  The invariant can drift further with no signal.

### Suggested fix

Either of these, plus a test pinning the chosen rule:

1. **Prefer a content-bearing ALLOW.** Replace an incumbent non-restrictive
   `final_result` when the incumbent carries no `reason`, `guidance`,
   `updated_input` or `worktree_path` and the new one does. This restores the
   observable behaviour without reintroducing last-wins.
2. **Merge the ALLOW-only fields** the way `context` is already merged: carry
   the first non-None `guidance` / `updated_input` / `worktree_path` forward
   onto whichever result wins.

Option 2 is the more honest fit for a chain documented as
most-restrictive-wins-with-accumulation, since `guidance` is accumulated
information, not a decision.

Apply the same change to `front_controller.py:117-121`, which carries the
identical rule.

---

## BLOCKER 2 — `worktree-reap` rebuilds the worktree path from a hardcoded root

**Location:** `src/claude_code_hooks_daemon/daemon/cli.py:5578`

**Confidence: 92%** — reproduced through the command's own `run_fn` injection point.

### Problem

```python
path = repo_root / ".claude" / "worktrees" / state.name
```

`collect_worktree_states` accepts worktrees under BOTH sanctioned roots, from
the single source of truth:

```python
WORKTREE_DIR_PATTERNS: tuple[str, ...] = (
    "untracked/worktrees/",
    ".claude/worktrees/",
)
```
(`core/worktree_paths.py:22-25`)

`WorktreeState` carries only `name`, discarding the path the collector already
read out of `git worktree list --porcelain`, so the CLI has to guess it back
and guesses one of the two roots unconditionally.

### Evidence

With a worktree at `/workspace/untracked/worktrees/agent-aa`:

```
DRY-RUN would remove /workspace/.claude/worktrees/agent-aa and its branch agent-aa
```

The command names a path that does not exist. With `--reap` it would issue
`git worktree remove` against that wrong path. Git rejects it, so nothing is
destroyed — the module's "ask git to disagree" design holds — but the reported
outcome is wrong and an `untracked/worktrees/` worktree can never be reaped.

### Suggested fix

Add a `path: Path` field to `WorktreeState`, populated by
`collect_worktree_states` from the listing it already parses, and have
`cmd_worktree_reap` use `state.path`. This removes the guess rather than
teaching the CLI the second root.

---

## NOTE 1 — `reap_worktree` deletes a branch by directory name, and by bare name

**Location:** `src/claude_code_hooks_daemon/core/worktree_reaping.py:263`

**Confidence: 80%**

```python
branch = run_fn(repo_root, "branch", "-d", state.name)
```

Two problems, both of which the same module argues against elsewhere:

1. `state.name` is the worktree DIRECTORY name, not the branch the worktree
   has checked out. The porcelain listing already carries
   `branch refs/heads/<name>`, and `_attached_branches` in this very file
   parses exactly that. If the two differ, this either fails harmlessly or
   deletes an unrelated same-named branch.
2. It uses the bare name where `prune_branch` deliberately uses the full ref
   (`worktree_reaping.py:418`), with a comment citing Plan 00254 on tag
   shadowing. Two sibling functions, opposite conventions, one stated rationale.

The blast radius is bounded because the delete is `-d`, which git refuses for
an unmerged branch. Fix: record the attached branch on `WorktreeState` and
address it by full ref, as `prune_branch` does.

---

## NOTE 2 — Venv mkdir-lock stale check races, and the failure is misreported as "uv not found"

**Location:** `src/claude_code_hooks_daemon/daemon/venv_lock.py:128-129`

**Confidence: 85%**

```python
except FileExistsError:
    age = time.time() - lock_dir.stat().st_mtime
```

If the holder releases the lock (`shutil.rmtree`) between this process's
failed `mkdir()` and its `stat()`, the `stat()` raises `FileNotFoundError`.
That escapes `venv_lock` into `cmd_repair`, whose handler at
`daemon/cli.py:1624` catches `FileNotFoundError` and prints:

```
ERROR: 'uv' not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh
```

The contention window is exactly when two daemons or a daemon and a repair
race, which is the scenario the lock exists for.

Fix: catch `FileNotFoundError` around the `stat()` and `continue` (the lock
just became free), and narrow `cmd_repair`'s handler so a lock-layer error
cannot be reported as a missing toolchain.

Related, lower confidence (60%): two waiters can both judge the lock stale and
both `rmtree` it, letting the second delete a lock the first has just
recreated. The module states it mirrors the bash implementation deliberately,
so this may be an accepted property rather than a defect — worth confirming
against `scripts/install/venv.sh` rather than fixing unilaterally.

---

## NOTE 3 — `release-slate-check` reads a git failure as "nothing in flight"

**Location:** `src/claude_code_hooks_daemon/core/release_slate.py:1687-1691`

**Confidence: 80%**

```python
def _git_lines(run_fn: RunGit, repo_root: Path, *args: str) -> list[str]:
    result = run_fn(repo_root, *args)
    if result.returncode != 0:
        return []
```

`_branches_ahead` and `_worktrees` both consume this, and `is_clean` reads
"no branches, no worktrees" as clean. So a failing `git for-each-ref` or
`git worktree list` contributes to a CLEAN verdict.

This contradicts the module's own stated rule, applied to CI two functions
away:

```python
def _head_ci(ci_lookup: CiLookup, sha: str) -> CiRunState:
    """Never lets a lookup failure read as clean: a problem is reported, and is not green."""
```

The CLI reserves exit 1 for "could not determine" precisely for this, and
`--accept` deliberately does not rescue exit 1. A git failure should reach
that path.

Partial mitigation exists: if `git rev-parse` fails the head sha is empty, the
CI lookup finds nothing, and the slate is NOT CLEAN. The gap is a partial
failure — rev-parse works and CI is green, but the worktree or branch listing
fails.

Fix: let `_git_lines` signal failure (return `None`) and have `collect_slate`
carry it into a field that forces `RELEASE_SLATE_UNDETERMINED`.

---

## NOTE 4 — The optimise checklist re-implements the registry's enablement gates, and the copy is already incomplete

**Location:** `src/claude_code_hooks_daemon/config_optimisation/checklist.py:417-434`

**Confidence: 78%**

The docstring claims:

> Mirror ``HandlerRegistry.register_all``'s three gates exactly.

`register_all` applies four:

1. `handler_config.enabled` — mirrored
2. `self.is_disabled(attr.__name__)` (`handlers/registry.py:445`) — **not mirrored**
3. `enable_tags` — mirrored
4. `disable_tags` — mirrored

There is also a small divergence in gate 3/4 handling: the registry treats any
truthy `enable_tags` value as tags, the checklist requires a `list`.

No test pins the two implementations together.
`tests/unit/config_optimisation/test_checklist.py` exercises `disable_tags`
against the checklist's own copy only, so a change to `register_all` will not
fail anything here — the report will just start disagreeing with the daemon
about which handlers are on.

Gate 2 is registry runtime state rather than config, so today's practical
impact is low. The drift risk is the finding.

Fix: extract the gating predicate into one function both call, or add a test
that registers handlers for a given config and asserts the checklist's
`enabled` matches the registry's registration outcome for every handler.

---

## NOTE 5 — `build_checklist` instantiates every handler with no error containment

**Location:** `src/claude_code_hooks_daemon/config_optimisation/checklist.py:467-468`

**Confidence: 70%**

```python
for ref in iter_builtin_handler_classes():
    instance = ref.handler_cls()
```

One constructor raising aborts the whole `optimise-checklist` verb with a
traceback, losing the other 113 handlers' verdicts. `register_all` wraps its
own instantiation in `try`. A report is a lower-stakes context than dispatch,
which argues for MORE tolerance here, not less: a handler that cannot be
constructed should appear in the report as such.

Fix: wrap the instantiation, and emit a `ChecklistItem` recording the failure
so the handler is visibly unassessed rather than absent.

---

## NOTE 6 — Language detection duplicates the `HandlerTag` language spellings as literals

**Location:** `src/claude_code_hooks_daemon/core/relevance.py:1871-1879`

**Confidence: 72%**

```python
#: The keys are the ``HandlerTag`` language
#: spellings.
_LANGUAGE_MARKERS: Final[dict[str, tuple[str, ...]]] = {
    "python": (...),
    "javascript": (...),
    ...
}
```

The comment names `HandlerTag` as the authority and then hardcodes the strings
instead of referencing it. `config_optimisation/areas.py:279-280` does the
same for event names (`"stop"`, `"subagent_stop"`, `"session_start"`,
`"status_line"`, `"nitpick"`) where `EventKey` / the event config keys exist.

Neither is wrong today. Both are the shape that goes wrong quietly: a renamed
tag or event key leaves these dicts matching nothing, and the failure is a
handler silently classified as irrelevant or filed under "Other guards" — not
an exception.

Fix: key `_LANGUAGE_MARKERS` on `HandlerTag` members and the area sets on the
event-key constants.

---

## NOTE 7 — `hook_input` + `dispatch_as_bash` raises with a message naming neither

**Location:** `src/claude_code_hooks_daemon/core/acceptance_test.py:806-827`

**Confidence: 75%**

`AcceptanceTest.__post_init__` runs `_derive_bash_payload()` first, which sets
`self.tool_payload`. The later `hook_input` check then sees a populated
`tool_payload` and raises:

> hook_input and tool_payload are mutually exclusive

The author declared `dispatch_as_bash`, not `tool_payload`. The invariant is
correctly enforced; only the message misdirects. Fix: check the
`hook_input` / `dispatch_as_bash` pair before deriving.

---

## Positive observations

Several things in this slice are notably well done and worth keeping.

- **Failure directions are chosen, stated, and consistent** in
  `core/worktree_reaping.py`. `UNKNOWN_COUNT = -1` is negative specifically so
  every `!= 0` refusal rule reads a collection failure as "keep", the delete is
  `-d` so git independently re-checks the predicate, and an unreadable
  `git status` becomes a sentinel refusal path rather than an empty tuple.
  This is the right instinct for a deletion path.
- **`core/utils.py:360-391`** turns an `OSError` from `Path.is_dir()` into a
  logged warning plus the conservative answer, and the comment explains which
  errno pathlib already swallows and why `EACCES` is different. This is the
  correct treatment of an error the code genuinely cannot resolve, and it is
  the opposite of the silent-fallback pattern.
- **`config/models.py:329-341`** — `_check_wired_event_field_coverage` failing
  at import is the right severity for the defect it guards. Silently dropping
  an event's config is exactly the class of bug that survives for releases.
- **`daemon/server.py:882-895`** — refusing the whole per-event socket rung
  when `events_dir` is already a symlink, checked before any `rmtree` or
  `mkdir` touches the path, is a correct fix for a predictable-path attack on a
  shared `/tmp` fallback. Replacing `ignore_errors=True` with a logged `OSError`
  handler in the same function is a genuine improvement.
- **`daemon/playbook_harness.py`** — the closed list of permitted fixture
  command shapes, translated into `FixtureAction` values performed as plain
  filesystem calls with no shell anywhere, and the `is_relative_to` containment
  check done on the RESOLVED path, is a well-constructed way to make a test
  harness safe. The `try/except OSError` around resolution that returns a
  refusal rather than a quiet "outside" verdict is the right call.
- **`daemon/controller.py:890-905`** — recording each handler's OWN verdict
  instead of attributing the merged decision to every matched handler is a
  real correctness fix, and the comment names the concrete symptom it cures.

## Security review

No security regressions found in this slice.

- No `shell=True`, no string-interpolated shell, no `eval` / `exec` /
  `pickle`. Every subprocess in the diff uses a fixed argv list.
- `_gh_ci_lookup` (`daemon/cli.py:2874-2889`) builds a fixed argv and passes
  the branch name as a separate argument. `check=True` means a `gh` failure
  raises `CalledProcessError`, which `_head_ci` catches and turns into a
  non-green "could not determine" verdict rather than a silent pass.
- `contract_status.compare_contract` hashes the raw bytes before any decoding,
  and `render_status` never interpolates fetched content into a command.
- The `server.py` symlink refusal is a net improvement to a predictable-path
  surface.
- `playbook_harness` is inert by construction: a command payload is data placed
  in `tool_input`, never executed.

## SOLID / structure

No architectural objections. The Plan 00242 split — terminality as a property
of the decision, `allow_is_final` as a per-event opt-in owned by the router
rather than a handler flag, `commit_side_effects` as a concrete no-op on the
base class — is a genuine simplification of a primitive that was previously
overloaded. `SideEffectJournal` is small, single-purpose and honest about its
shallow-copy limit. `housekeeping.py` being pure data and pure functions with
the CLI as the only renderer is the right shape.

The DRY concerns are NOTE 4 (registry gate duplication) and NOTE 6 (constant
spellings duplicated as literals).

## Verdict

REQUEST CHANGES. Two blockers, both demonstrated with reproductions against
the shipped code, both with contained fixes.
