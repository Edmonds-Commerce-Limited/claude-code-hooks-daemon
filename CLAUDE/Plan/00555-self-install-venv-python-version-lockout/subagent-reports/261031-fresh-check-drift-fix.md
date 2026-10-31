# Plan 00555: freshness check ignored interpreter drift (drift demo Finding 1-4)

## Finding 1: LOCKOUT fixed

`_venv_is_fresh` (`scripts/install/venv.sh`) now refuses to call a venv fresh
unless `_venv_load_gate && venv_python_usable "<venv>/bin/python"` passes. The
check sits before the `_VENV_FORCE_REBUILD`-independent lock-hash and stamp
fast paths, so neither can rescue a venv the version-aware gate rejects. A gate
library that cannot be loaded fails closed (the venv is rebuilt). The unusable
reason (`_RV_PROBE_OUTPUT`) is printed with the "not reusing" line.

Tests (`tests/integration/test_ensure_venv.py`, new class
`TestEnsureVenvInterpreterDriftIsNeverFresh`; the fake-venv builders were lifted
to module functions `_stamped_venv` / `_freshness_verdict`, shared with the
existing lock-change class):

- lock hash matches + `pyvenv.cfg` records 3.11 -> STALE (red before the fix:
  `assert 'FRESH' == 'STALE'`, green after);
- stamp matches + drifted cfg -> STALE;
- lock hash matches + cfg records the running minor -> still FRESH;
- slow end-to-end: `ensure_venv` on a venv at the current key with a drifted cfg
  wipes and rebuilds it in place (sentinel gone, cfg no longer says 3.11.2).
  This is the build the self-heal and `repair` paths both run, so they now
  recover from the Variant A shape instead of recording `.failed`.

All 16 tests in the file pass.

## Finding 2: `status` with no venv

`bin/hooks-daemon` (and `src/claude_code_hooks_daemon/install/templates/hooks-daemon`,
byte-identical, checked with `cmp`) gained `_print_last_build`, a pure-bash read
of `untracked/.venv-bootstrap.result`. The exit-5 refusal path prints
`Last venv build: <result> at <finished_at>` and `Build log: <log>` to stderr
before the "Build the venv ... repair" line. Silent when no result is recorded.
It applies to every refused verb, not only `status` (one refusal path, DRY).

Tests (`tests/integration/test_bin_hooks_daemon_repair_without_venv.py`): a failed
hook build then `status` prints both lines with the recorded values (red first:
lines absent); no record prints neither. The file and the unimportable-venv repair
file pass (27 tests).

## Finding 3: `diagnose_venv_start` consistency

`paths.py`: the expected site-packages is now
`lib/python<interpreter's own minor>/site-packages` (what `site.py` adds), not the
cfg minor. A cfg-vs-interpreter mismatch adds an explicit line
`drift: pyvenv.cfg records X but the interpreter runs Y: ...`, and a drifted venv
is never `healthy` even when the package imports. The old "cause: ... changed
under the venv" line was replaced by the drift line (nothing else referenced it).

Tests (`tests/unit/daemon/test_paths_diagnose_venv_start.py`, new class
`TestCfgDriftAtTheCurrentSitePackages`): in the demo's shape the site-packages
line says yes next to importable yes, and the drift line is present with the repair
fix. Red first (2 failed), green after; the 8 existing tests in the file and the
drift test file still pass (20 passed together).

## Finding 4: `untracked/lsp-venv` after self-heal (investigated, not changed)

The only maintainer is `_ensure_self_install_lsp_venv_symlink`
(`src/claude_code_hooks_daemon/core/project_context.py:75`, called from
`ProjectContext` at line 265 in self-install mode). It repoints the link, atomically,
from `sys.prefix` of the DAEMON PROCESS when it starts. The venv build never touches
it. So after a self-heal the link follows as soon as the daemon starts on the new
venv; between the build and that start, and for as long as no daemon runs, it points
at the old (orphaned) venv. The demo's note most likely read /workspace's own link
(the demo's cleanup section lists /workspace's `lsp-venv`), not the scratch tree's,
so I could not confirm a stale link after the daemon had started; I did not
reproduce it. The orphan drifted venv itself is never pruned by the self-heal. A fix
(repoint in the build, prune the orphan) is not small and local; record both as a
niggle: "self-heal leaves the orphan old-key venv and does not repoint lsp-venv
until the daemon starts".

## QA

Targeted tests: `test_ensure_venv.py` (16), `test_bin_hooks_daemon_repair_without_venv.py`

- `..._unimportable_venv.py` (27), `test_paths_diagnose_venv_start.py` +
  `test_paths_venv_interpreter_drift.py` (20), all passed.

`./scripts/qa/llm_qa.py lint type_check format pyright shell_check venv_interpreter_trust error_hiding bare_python_invocation semgrep`
(first run flagged `format` as NOT RECORDED because the post-edit hook reformatted
`test_ensure_venv.py` mid-run; re-run of `format lint` was clean):

```
✅ lint: 0 violations
✅ type_check: 0 errors
✅ format: 0 files need reformatting      (re-run: QA: 2/2 PASSED)
✅ pyright: 0 errors (2579 files analysed)
✅ shell_check: 0 issues (75 total files checked)
✅ venv_interpreter_trust: 0 violations (1024 files scanned)
✅ error_hiding: 0 violations
✅ bare_python_invocation: 0 violations (150 files scanned)
✅ semgrep: 0 violations
```

`./scripts/qa/llm_qa.py changed` result lines (verbatim):

```
❌ plan_qa: 1 findings (0 block, 1 advise)
     journal-freshness  Plans whose JOURNAL/ has gone quiet (Plan 00163): - 00554-rust-relay-transport-default: 4 days since last j...
⚪ project_handlers: 297 passed, 0 failed   [NOT MEANINGFUL: detector failed: plan_qa]
❌ changed_tests: 943 passed, 1 failed, 0 skipped | 39 test files from 7 changed files (2 unmapped)
   unmapped (each FAILS the run: add a test, a changed_tests_map.yaml rule, or pass --allow-unmapped): bin/hooks-daemon [too-broad], src/claude_code_hooks_daemon/daemon/paths.py [too-broad]
   failed: tests/unit/install/test_bin_wrapper_project_anchoring.py::TestTheAnchorReachesTheCommand::test_a_global_anchor_selects_the_tree_the_command_reads
QA: 39/42 PASSED, 2/42 FAILED, 1/42 NOT MEANINGFUL (detector failed: plan_qa)
```

All other 39 checks in `changed` passed (incl. docs_qa, shell_check, shell_audit,
venv_interpreter_trust, security, semgrep, pyright).

Explanations for the three non-green lines:

- `plan_qa`: advisory about plan 00554's quiet JOURNAL/, not this change (0 block).
  It marks `project_handlers` NOT MEANINGFUL, which itself reports 297 passed.
- `test_a_global_anchor_selects_the_tree_the_command_reads`: environmental. The test
  runs the real wrapper and needs a venv under `untracked/venv-*`; this worktree's
  venv is `.venv`, so the wrapper exits 5 at venv resolution (before any code I
  changed). With a temporary `untracked/venv-*` symlink to `.venv` the whole file
  passed (15 passed); the symlink was removed afterwards.
- `unmapped` (`bin/hooks-daemon`, `paths.py` "too-broad"): the changed-tests mapper
  cannot narrow these two files. Coordinator's full gate covers them; I ran their
  tests above by hand.
