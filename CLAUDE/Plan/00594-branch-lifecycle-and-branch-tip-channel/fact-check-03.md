# Fact check 03: Plan 00594 (DESIGN.md section 2.7 and section 3 corrections)

Scope: claims added or changed by the diff. Tree: /workspace on `main`. The added `fact-check-02.md` is a report, not a plan claim set. Its two line-number refutations are checked here because they bear on the DESIGN text.

## REFUTED

None among the DESIGN claims.

One note on fact-check-02.md, which the diff adds. Its items 1 and 4 hold against the branch it checked but not on `main`:

- Item 1: on `main`, `ROLLBACK_REF` is assigned at `scripts/upgrade_version.sh:898` and `ensure_venv` is called at `:936`. The DESIGN citations are right, so no fix is needed there. The other `ensure_venv` call is at `:1306`.
- Item 4: on `main`, `mkplan.bash:622-628` is already single-spaced. The new DESIGN wording "used to add" is therefore correct.

## Claim table

| #   | Claim                                                                                                         | Verdict           | Evidence                                                                                                                                                                        |
| --- | ------------------------------------------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `mkplan.bash:517` defaults the ref to `—`                                                                     | VERIFIED          | `local ref="—" entry_title=""` at line 517                                                                                                                                      |
| 2   | `mkplan.bash:625-627` used to add three spaces; now a single space                                            | VERIFIED          | Lines 622-627 on `main` read "Single spaces only ... heading="$heading — $entry_title"". The old behaviour is not in the tree.                                                  |
| 3   | Every heading the tool writes carries the `· REF` slot                                                        | VERIFIED          | `heading="## $journal_time · $category · $ref"`, with `ref` defaulting to `—`                                                                                                   |
| 4   | `plan_qa/model.py:358` makes the slot optional                                                                | VERIFIED          | Lines 356-358: `r"^## (\d{2}):(\d{2})\b(?: · (\S+) · (\S+))?"`. The `?` makes the group optional.                                                                               |
| 5   | `version_check._branch_install_context` (`:447`) is a static method returning fixed text, no cache or network | VERIFIED          | `@staticmethod def _branch_install_context(stamp)` at 446-447 returns a literal list and touches no cache or network.                                                           |
| 6   | The branch-install path returns before the TTL cache is consulted                                             | VERIFIED          | `version_check.py:228-233` returns the advisory before `cache_file` and `_is_cache_valid` (`:245-248`).                                                                         |
| 7   | `utils/remote_refs.py:48` `list_remote_refs`, called with `patterns=("refs/heads/<ref>",)`                    | VERIFIED          | Line 48 defines it. `patterns: tuple[str, ...]` (the tuple form now matches).                                                                                                   |
| 8   | `daemon/metadata.py:27` is the `.daemon-metadata.json` filename                                               | VERIFIED          | `_DAEMON_METADATA_FILENAME = ".daemon-metadata.json"` at line 27. `tracked_ref`, `tracked_sha` and `last_release_tag` have no hits in `src`, so they are new, as the plan says. |
| 9   | `ROLLBACK_REF` at `scripts/upgrade_version.sh:898`                                                            | VERIFIED          | Line 898: `ROLLBACK_REF=$(git -C "$DAEMON_DIR" describe --tags --exact-match ...`                                                                                               |
| 10  | `ensure_venv` at `scripts/upgrade_version.sh:936`, installs from the target's `uv.lock`                       | VERIFIED          | Line 936: `VENV_PATH=$(ensure_venv "$DAEMON_DIR" "$INSTALL_STAMP" ...)`. `scripts/venv-include.bash:175` says "Install from uv.lock".                                           |
| 11  | `ensure_venv` is keyed by the lock hash, not the stamp                                                        | VERIFIED          | `scripts/install/venv.sh:1230-1236`: "lock_hash is authoritative"; an unchanged lock reuses the venv. A changed lock rebuilds (`:1242`).                                        |
| 12  | A new sha with an unchanged lock reuses the venv and re-stamps it                                             | VERIFIED          | `_reuse_venv_if_fresh` (`venv.sh:1266-1273`) calls `stamp_venv_version` on a reuse. PLAN.md:209 marks Task 5.3 done.                                                            |
| 13  | Plan 00535 Task 2.1 owns the handover                                                                         | VERIFIED          | `CLAUDE/Plan/00535-*/PLAN.md:40`, "Red test, then the chosen handover (stop-then-start ...", still open.                                                                        |
| 14  | `upgrade --track`, `upgrade --release` and the metadata changes (`last_release_tag` and the rest)             | UNVERIFIABLE-HERE | These are plan intentions about the future (the "What is new" list), so they are not checked as current-state claims.                                                           |
