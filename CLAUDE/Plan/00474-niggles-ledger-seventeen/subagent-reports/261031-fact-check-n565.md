# Fact check: N565 in NIGGLES.md (Plan 00474)

Diff: untracked/plan-fact-check/00474-niggles-ledger-seventeen.diff. Checked against the current tree on main.

Result: 8 claims: 8 verified, 0 refuted, 0 unverifiable.

| #   | Claim                                                                                                                                    | Verdict  | Evidence                                                                                                                                                                              |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Source: Plan 00555's drift self-heal demo, `261031-drift-self-heal-demo.md`, followed up in `261031-fresh-check-drift-fix.md`, finding 4 | VERIFIED | Both files exist in 00555 `subagent-reports/`. `261031-fresh-check-drift-fix.md:57` is "Finding 4: `untracked/lsp-venv` after self-heal".                                             |
| 2   | After a hook self-heals a drifted py311 venv by building a py313 one, the py311 directory stays under `untracked/`                       | VERIFIED | Demo report line 192: "after self-heal, the drifted py311 venv is left in place as an orphan". Fix report line 68: "The orphan drifted venv itself is never pruned by the self-heal." |
| 3   | `untracked/lsp-venv` is maintained only by `_ensure_self_install_lsp_venv_symlink`                                                       | VERIFIED | grep over `src` and `scripts` finds only the definition (`core/project_context.py:75`) and one call (`:265`). Fix report line 59 says "The only maintainer".                          |
| 4   | The function is at `core/project_context.py:75`                                                                                          | VERIFIED | `def _ensure_self_install_lsp_venv_symlink` is at line 75.                                                                                                                            |
| 5   | It runs at daemon start, so the link keeps naming the old venv until the daemon next starts                                              | VERIFIED | It is called from `ProjectContext` (`project_context.py:265`) and repoints from `sys.prefix` of the daemon process (lines 102-114). The venv build never calls it.                    |
| 6   | The follow-up could not reproduce a stale link once the daemon had started                                                               | VERIFIED | Fix report lines 65-68: "I could not confirm a stale link after the daemon had started; I did not reproduce it".                                                                      |
| 7   | The demo most likely read `/workspace`'s link rather than the scratch tree's                                                             | VERIFIED | Fix report lines 65-67 say this, citing the demo's cleanup section. It is stated there as a likelihood, and N565 keeps the "most likely" wording.                                     |
| 8   | Prune already keeps any venv a running process uses                                                                                      | VERIFIED | `daemon/cli.py:3496-3506` logs "Kept stale venv %s: process %d uses it" from `in_use`. `cli.py:3924` also calls `processes_using_venvs` on the unproven path.                         |

REFUTED claims: none.

Notes, not defects:

- N565 sits above N564 in the file. The ledger is newest first (N565, N564, N563, ...), so the order is consistent.
- The wording of the 00474 ledger is correct for the repo state (clean main at c9c0b8f82).
