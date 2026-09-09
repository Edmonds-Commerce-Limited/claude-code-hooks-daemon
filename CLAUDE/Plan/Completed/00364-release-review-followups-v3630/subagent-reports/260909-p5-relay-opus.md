# Plan 00364 Phase 5 — worktree relay, project-handler priority, QA-from-a-worktree

**Agent**: p5-relay (Opus)
**Worktree**: `untracked/worktrees/worktree-plan-00364-p5-relay`
**Branch**: `worktree-plan-00364-p5-relay` (based on main at `befa2c8e`), committed, NOT pushed
**Tasks**: 5.1, 5.2, 5.3, 5.4, 5.5 — all five shipped, each with a failing test first

## What each task turned out to be

### Task 5.1 — the relay guard belongs to one checkout

The plan text proposed resolving the relay directory at hook-run time. That
was not taken, for two reasons visible only in the code: the guard is a
zero-spawn hot path (its whole value is that it costs nothing when the relay
is absent), and `normalise_project_root` / `recorded_untracked_dir` depend on
the literal being present to read back out of the artefact.

So the guard bakes one MORE literal — the hooks directory it was generated
for — and tests `${BASH_SOURCE[0]}` against it:

```bash
if [[ "${1:-}" != "--no-relay" && "${BASH_SOURCE[0]}" == "/workspace/.claude/hooks/"* ]]; then
```

A worktree's inherited copy fails that test and falls through to `init.sh`,
which computes its own project-scoped socket. One string comparison, no spawn,
and the failure direction is safe: an unrecognised path costs a legacy round
trip, never a wrong answer.

Consequences worth knowing:

- **A relative-path invocation no longer relays**, even in the main checkout.
  Claude Code always invokes hooks absolutely (`bash "$CLAUDE_PROJECT_DIR"/…`
  in `settings.json`), so this is hand-run probes only. Pinned by a test
  rather than left to be discovered.
- **`recorded_project_root` joins `recorded_untracked_dir`.** The artefact now
  bakes two roots, and a comparison that declares only one reports the other
  as machine-specific from every foreign checkout — the defect Plan 00250 Task
  2.4c fixed, one path along. Both the dogfooding comparison and the
  machine-specific-path guard now declare both.
- **The tracked forwarders were regenerated for the RECORDED root**
  (`--project-root /workspace --hooks-dir <worktree>/.claude/hooks`), not for
  this worktree, so the committed artefact still belongs to the main checkout.
  Exactly one line changed in each of 27 files; the four relay-ineligible
  forwarders are untouched.

Second half: `scripts/setup_worktree.sh` provisions `.claude/hooks-daemon.env`
through `install.py`'s own `create_daemon_env` — written fresh, never copied
across checkouts, and the content is checkout-agnostic
(`HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"`, expanded by `init.sh` at source
time). The not-installed answer now names the checkout it is answering for, in
both encoders (`jq` and the `python3` fallback), including the Stop-family
`decision: block` — the shape that reads exactly like a working stop gate.

### Task 5.2 — priority 20 → 51

Free PreToolUse slots on the live chain: 24-29, 32, 39, 51-54, 56, 59. 51 is
in the workflow band (36-55), where a plan-status gate belongs, and sits after
`plan_qa_edit` (44) and `plan_workflow` (46) so their advisories are attached
before this handler's terminal DENY lands.

**The plan's stated verification cannot work, and this is worth carrying
forward**: `bin/hooks-daemon logs` cannot witness a collision either way. The
in-memory ring buffer starts after handler registration, so a restart's log
holds six records (socket + server lines) and no `Registered project handler`
or `priority collision` line ever reaches it. Verified instead by
`tests/integration/test_project_handler_priority_collisions.py`, which
reproduces the controller's own rule against the real registry: it fails at 20
naming `block-git-message-backtick` and `lock-file-edit-blocker`, and passes at
51\. The daemon was restarted in the worktree and logs no collision line.

### Task 5.4 — the audits were scanning nothing

Both audits matched their exclusion patterns against the ABSOLUTE path, so a
checkout living under a matching directory excluded itself. They now match on
the path relative to the tree being scanned, and `audit_error_hiding` fails
with a named workspace when it collected zero candidate files, so "no
violations" can no longer mean "nothing was looked at".

Two adjacent defects surfaced and were fixed with their own tests:
`format_violation_report` raised `KeyError: 'description'` on a
stale-exclusion finding (text path only, so the JSON the pipeline consumes
never saw it), and the audit read its exclusions from the SCRIPT's directory
rather than the workspace under audit, which reported all 177 as stale for any
other tree.

### Task 5.5 — the QA runner resolves the venv

`llm_qa.py` calls `scripts/lib/resolve_venv.sh`. The design point worth
recording: when the resolver is PRESENT but FAILS, that is an error, not a
fallback. Falling back to the legacy path there would let a stale symlink
answer for a venv the resolver had just rejected — the silent-fallback class
the fingerprint layout exists to remove. The legacy path is consulted only
when the resolver file is missing entirely; either failure names both places
tried and the resolver's own stderr.

## Evidence

The Success Criterion, measured from inside the worktree with no environment
override:

```
$ printf '{"tool_name":"Bash",...,"session_id":"p5-probe"}' | bash .claude/hooks/pre-tool-use
{}
$ ./bin/hooks-daemon logs -n 3 | grep -c p5-probe
1
```

## QA

`./scripts/qa/llm_qa.py all` from inside the worktree: **26/26 PASSED**
(21526 tests passed, 0 failed, 21 skipped, coverage 95.4%).

Before this phase the same command reported 22/26 here, with `error_hiding`,
`capture_corruption` and their two unit tests failing because nothing was
scanned, and `smoke_test` vacuous.

## For the coordinator

- Commits on `worktree-plan-00364-p5-relay`, not pushed. The daemon
  auto-committed a CLAUDE.md handler-block regeneration on restart
  (`3e9feef7`); left in place as briefed.
- `.claude/hooks-daemon.env` was provisioned in this worktree (gitignored, so
  it is not in any commit). A worktree created before this change needs the
  same file; re-running `setup_worktree.sh` is the supported route.
- The first hook call in a freshly provisioned worktree can start a daemon,
  and that start regenerates the CLAUDE.md handler block. It tripped the
  conftest guard once during `test_forwarder_socket_stdin.py`; the guard
  restored the file and the test passed on the next run.
