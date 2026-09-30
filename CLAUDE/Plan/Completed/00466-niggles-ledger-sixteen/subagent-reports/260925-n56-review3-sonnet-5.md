NOT READY

# N56 review 3 (final, bounded) — branch `worktree-n466-n56` @ 18a0b61ec

Reviewer: Sonnet 5. Ran everything as uid 0. Probes are in
`/workspace/untracked/scratch/n56r3/` (my new material) and
`/workspace/untracked/scratch/n56r2/` (review 2's, reused unmodified). The
worktree was clean at both start and end of this review (`git status --short`
printed nothing); one mutation-proof edit was made only in a `git archive`
scratch copy at `/workspace/untracked/scratch/n56r3/head_copy/`, never in the
worktree.

## Verdict

Fix round 2's own report claims "All 41 of review 2's hand-written evasion
shapes were folded into `_SHOULD_FIND`... all pass." That claim is false: I
re-ran review 2's own `evasions.py` against the detector at HEAD and **3 of
41 are still missed**. This is the specific check the brief asked me to run
first, and it fails. Everything else checked out: the exclusion list is gone
and the whole-repo scan is clean, the five converted tests plus the two new
fix-round-2 tests are mutation-proven RED, my 10 new hand-written shapes are
caught (bar one deep-indirection edge case), and I found no false positives.

## Item 1: review 2's 41 evasions at HEAD — FAILS (B1, still open)

`python3 n56r2/evasions.py tests/integration/test_no_root_conditioned_skips.py`
(output: `n56r3/evasions_head.txt`) — **38/41 caught, 3 missed**:

| Shape                        | What it is                                                                                                                                                                                | In scope per the file's own docstring/QA.md wording?                                                                                                                                                                                                                                |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `match_guard_pass`           | `if os.geteuid()==0: pass\nelse: assert 1==2` — as root the `pass` branch runs and the real assertion never executes                                                                      | Yes — `pass` is functionally the same early-exit-for-root shape as `return`/`skip`, and `_guarded_action` (`:731-749`) only recognises `Return`/`Raise`/a skip-like `Call`, so a bare `pass` guard is invisible to it even though the `if` guard itself is a proven root expression |
| `assert_only_when_nonroot`   | `if os.geteuid() != 0: assert not os.access(p, os.R_OK)` — no assertion at all when root                                                                                                  | Borderline — not a skip/xfail/return, but it is exactly the "vacuous as root" shape the owner's rule and review 2's B1 both name explicitly, and review 2's own fixture `getuid_used_non_skip` (`:1201-1206`) is a simplified stand-in for it, still whitelisted                    |
| `try_except_permission_pass` | `try: open(...).read()\nexcept PermissionError: return\npytest.skip(...)` — root never raises `PermissionError`, so the `skip` always runs as root, with no syntactic root check anywhere | No realistic static AST fix; review 2's own remediation for this class was a *runtime* probe (patch the identity calls and diff the collected/skipped set), which nothing in this round attempted                                                                                   |

This is not a request to catch all three by Friday — `try_except_permission_pass`
in particular needs the runtime-probe approach review 2 already proposed, not
another AST special case, and I don't think withholding merge for that one
specific shape is proportionate. The blocking problem is narrower and more
serious: **the fix-round report asserts a fact ("all pass") that a five-second
rerun of the reviewer's own script disproves.** Two fixes needed, either is
sufficient to close this:

1. Fix `match_guard_pass` (a real, cheap gap — teach `_guarded_action` that a
   `pass`-only branch opposite a non-trivial `orelse`/`body` is itself
   root-conditioned control flow) and `assert_only_when_nonroot` (extend
   `_is_root_expr`'s callers to also flag an `if <root>: assert ...` /
   `if not <root>: assert ...` with no `else`, since that's a vacuous
   assertion, not a skip, but the owner's rule covers it too), **or**
2. Leave them, but replace the "all 41 pass" claim with an accurate one that
   names the 3 residuals and why each is or isn't in scope for a static
   scanner — and get the coordinator's sign-off that `try_except_permission_pass`'s
   class is accepted as a documented residual (per the standing rule, "documented
   limit" is not itself a terminal state, so this needs to be a real decision,
   not a silent gap).

Either way, the report text must stop claiming something untrue.

## Item 2: 10 new hand-written shapes — 9/10 caught

`n56r3/new_shapes.py` (repo): two-level helper chain, a class attribute set
via `self`-style access, a lambda stored in a dict and called via subscript,
`os.getuid() in (0,)` / `in [0, -1]`, a `pytest.mark.skipif(...)` built in a
variable then applied via `@_marker`, an autouse fixture calling
`pytest.skip`, a non-autouse fixture dependency calling `pytest.skip`, a
ternary assigned to a variable then used as the skip condition, and a
reversed `0 == os.geteuid()` comparison.

9/10 caught. The two-level helper chain (`_raw_uid()` → `_is_root()`) is
caught as a definite finding (not merely `unproven`), which is better than
the brief asked for — both helpers are same-module and zero-arg, so full
resolution is legitimate rather than a guess. Only `lambda_in_dict`
(`_checks = {'root': lambda: ...}` then `_checks['root']()`) is missed — a
dict-subscript indirection on top of a lambda. This is a narrow, unlikely
construct; I'd file it as a MINOR/NIT rather than block on it.

## Item 3: exclusion list and whole-repo scan — PASSES

`grep -n "_EXCLUDED\|fixtures.*assets" tests/integration/test_no_root_conditioned_skips.py`
finds no exclusion list, only the docstring/comment recounting review 2's B1
finding as history. `TestTheRepositoryItself` (the whole-`tests/`-tree scan)
ran green: **1281 passed**, including the two deliberately-broken
`syntax_error_handler.py` fixtures (correctly treated as "pytest would never
collect this" rather than a scan failure) — `n56r3/detector_test_run.txt`.

**Mutation-proof, M1** (chmod failure contract): reverted
`hooks_deploy.sh`'s `chmod_failed -gt 0` branch from `return 1` to
`return 0` in a `git archive` copy
(`n56r3/head_copy/scripts/install/hooks_deploy.sh`) and reran
`TestSetHookPermissionsFailsLoudly::test_a_failed_chmod_returns_nonzero_and_names_the_file`
directly against that copy (via `PYTHONPATH`, since the worktree's venv
symlinks back to itself and `source_tree_guard` correctly refuses to run
against the wrong checkout otherwise): **RED**, `assert 0 == 1` — confirms
fix round 2's claim.

**Mutation-proof, m1** (auto_continue OSError count): swapped
`path.open("rb")` for `open(path, "rb")` in the same scratch copy's
`transcript_reader.py` and reran
`test_matches_handles_oserror_reading_transcript`: **RED**,
`fault_calls == 0` — confirms fix round 2's claim; the count assertion does
its job.

Both scratch copies were used read/write only under
`/workspace/untracked/scratch/n56r3/`, never in the worktree; the worktree
was never touched by either mutation.

## Item 4: false positives — none found

`n56r3/fp_shapes.py`: a `shutil.which` skip, a platform skip, `os.getuid()`
used only to build an expected path string, `os.access` used in a bare
assertion (not a skip), an unrelated `CI` env-var skip, `Path.home()` used in
an assertion, an unrelated boolean helper (`_has_docker`), `getpass.getuser()`
used only for a log line, and `os.stat('/').st_uid == 0` used in a bare
assertion (Plan 00351's own original false-trigger shape, now correctly
clean since it's not a skip condition at all). All 9 came back clean — no
false positives.

## Other checks

- Detector RED on `main` / GREEN at HEAD for the three original sites: not
  re-verified independently this round (review 2 already did this and fix
  round 2's diff to the detector since then is additive — new coverage, no
  narrowing of the three original findings — so I relied on that prior
  result rather than re-spend the run).
- `m2` (merge conflict with N59 in `test_paths.py`): still open, still
  correctly left for the coordinator per the agent rules — unchanged since
  review 2, nothing to add.
- Root: `id` confirms `uid=0(root)` throughout this review.

## Findings summary

- **BLOCKER**: fix round 2's report claims all 41 of review 2's evasion
  shapes pass; 3 do not (`match_guard_pass`, `assert_only_when_nonroot`,
  `try_except_permission_pass`). Fix `match_guard_pass` and
  `assert_only_when_nonroot` (both are cheap, in-scope extensions to
  `_guarded_action`/`_is_root_expr`), and either fix or get an explicit,
  justified residual decision recorded for `try_except_permission_pass`
  (a genuine static-analysis limit, per review 2's own runtime-probe
  suggestion) — then correct the claim in the report.
- **NIT**: `lambda_in_dict` (a lambda behind a dict-subscript indirection) is
  a silent miss. Rare construct; ledger-later is fine.

## Gate

Not run — the brief says the gate is already queued and not mine to run.
