# Plan 00253 — finding evidence

Per-finding evidence for the six review findings, extracted from `PLAN.md`
when it crossed the plan-doc size advisory. `PLAN.md` keeps the verdict table
and the task tree; this holds the reproductions, which are durable detail
that a session only needs when it follows the link.

Every block below was produced by EXECUTION against real git 2.39.5 or by
running the suite — none is inferred from reading. Where the peer review's
description differed from what executing showed, the correction is recorded
in place (finding F).

### A — reproduced: `tier=merged`, `is_safe=True`, and git refuses

`_is_merged_into_its_upstream` returns `True` when no upstream resolves, on the
stated grounds that "git then falls back to HEAD, which the caller's ancestry
proof already covers". The caller's proof is against `protected_ref` (default
`main`), **not** HEAD, so the fallback is not covered at all.

Executed against real git — branch `done` merged into `main`, HEAD on `work`,
`done` with no upstream:

```
done in main? : True        done in HEAD? : False      upstream: (rev-parse exit 128)
CLASSIFIER  tier='merged' is_safe=True
            detail='tip is an ancestor of the protected ref — nothing can be lost'
            argv=('branch', '--delete')
REAL GIT    exit=1  error: The branch 'done' is not fully merged.
            branch still present: True
```

This is the exact dry-run/real-run contradiction Plan 00249 was opened to
remove, reappearing on the HEAD axis rather than the upstream axis — both come
from git's single `branch_merged()` rule. The trigger is an ordinary workflow:
tidying a merged branch while standing on another one.

It also dead-ends the agent: `-d` refuses, `delete-branch` refuses, and
`git branch -D` is denied by `destructive_git` — so the guidance at
`handlers/pre_tool_use/destructive_git.py:248` ("that specific gap is what
`delete-branch` fills") now has a third refusal reason it does not fill.

Pre-diff this state crashed, so the diff did improve it. The label and the dry
run are still wrong.

### B — reproduced end to end: three inaccuracies in one message

`delete_branches` (`branch_safety.py:555-578`) deliberately allows
`refused=True` with a non-empty `deleted`, and deliberately KEEPS the bundle when
something was deleted. The CLI was not updated for that: `if report.refused:`
prints a hard-coded "REFUSED — nothing was deleted." and returns 1 at `:3024`,
before the bundle disclosure at `:3030-3033`.

Executed through the real `cmd_delete_branch` (only the project-marker lookup
stubbed) with one `merged-unpushed` branch that force-deletes plus one
plain-`merged` branch that git refuses via F-A:

```
CLI exit=1
stderr: REFUSED — nothing was deleted. Blockers:
          - done: git refused the delete (proven merged) — …not fully merged.
        …re-run with --allow-unproven and --reason…
GROUND TRUTH
  branches now       : ['done', 'main', 'work']      <- 'shipped' IS gone
  bundle on disk     : True  829 bytes
  bundle path shown  : False
```

So: a branch WAS deleted; the only recovery route for it is withheld; and the
remediation offered is irrelevant because no tier was `unproven`.
`--format json` is correct (`:2978-2979`), so only the human path lies.

### C and D — two tests that cannot fail for the reason they name

C: `test_the_bundle_gets_a_larger_budget_than_the_reads` asserts only
`Timeout.GIT_BUNDLE_CREATE > Timeout.GIT_BRANCH_SAFETY`. It names neither
`write_recovery_bundle` nor `run_git`, and that assertion is the ONLY mention of
the constant anywhere under `tests/`. Verified by execution: downgrading the call
site at `:417` to the read budget leaves **64 tests passing** — while the
docstring at `:412-414` calls that call the one "that must not be killed
part-way".

D: `test_a_timed_out_bundle_is_reported_as_a_refusal` asserts
`pytest.raises(subprocess.CalledProcessError)` — the raise, not a refusal. The
refusal conversion lives at `cli.py:2957`; deleting that `except` clause leaves
this test passing. It re-tests `_git`'s pre-existing raise-on-nonzero.

### E — the fix is right, the comment is not

`_CWD_IMMATERIAL = Path("/")` correctly stops `Path.cwd()` raising
`FileNotFoundError` in a deleted working directory. But the comment asserts
"which directory it runs in is immaterial", and that is false: `git -C <dir>`
selects which repo-local config applies, and `ls-remote` reads
`url.<base>.insteadOf`, `http.proxy`, `http.sslCAInfo` and `credential.*` from
it. A project with a repo-local mirror or proxy silently loses it, and the
upgrade advisory just goes quiet.

### F — the mechanism is quoting, not decoding (correction to the report)

The report attributed this to `errors="replace"` turning raw non-UTF-8 bytes into
U+FFFD. Executed, the cause is narrower and broader at once — it is
`core.quotePath`, and it bites for **any** non-ASCII path, valid UTF-8 included:

```
ls-tree           -> b'"caf\\303\\251.txt"'     (octal-escaped AND quoted)
rev-list --objects -> b'…sha caf\xc3\xa9.txt'   (raw)
the two path texts MATCH: False
```

So `_paths_in_tree` (`ls-tree`) and `_paths_in_history` (`rev-list --objects`)
can never agree on a non-ASCII path, and the `"{len(unique_paths)} path(s) are new"` message at `:399` miscounts. Pre-existing, but pre-diff it aborted loudly
(`UnicodeDecodeError` is a `ValueError`, caught at `cli.py:2954` → exit 2); it is
now a silent miscount in the text a human reads before abandoning work.

The report's own verification that `_reachable_object_shas` is byte-identical was
re-confirmed as sound: the safety-critical content proof is unaffected. This is a
message defect, not a safety defect.
