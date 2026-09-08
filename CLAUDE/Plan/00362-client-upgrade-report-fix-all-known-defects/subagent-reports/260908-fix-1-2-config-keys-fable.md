# Task 1.2 — stale handler keys reported; nitpick detectors migrate

**Branch**: `agent-a2255868b5ce183c4-05b72d48` (commit `0332a858`)
**Worktree**: `/workspace/.claude/worktrees/agent-a2255868b5ce183c4-05b72d48`
**Report §**: 2

## What was found

- `config-validate` ran the Pydantic schema plus one business rule only; the
  schema allows any key under `handlers.<event>`, so a key that does nothing
  was reported `valid: true`. Daemon startup DOES reject an unknown key
  (degraded mode) but accepts every name in `RETIRED_HANDLERS` silently —
  and both nitpick detectors are in that list, so nothing anywhere said they
  had moved.
- `check-config-migrations` is manifest-driven and version-gated; a stale key
  is stale against the installed code, which no manifest describes.
- The reference config (`.claude/hooks-daemon.yaml.example`) already lists
  every registered handler for every real event (the report's "missing" keys
  are all retired handlers — `validate_instruction_content` IS listed). What
  it genuinely lacked was the entire `pseudo_events.nitpick` block, which is
  why an upgrade could never carry the detectors to their new home.
- In the client shape (old default AND user config both carry the key) the
  differ saw a priority change on a handler the new default removed and
  reported a conflict; the user's `enabled`/`priority` were dropped.

## What was done (TDD: tests first, all green)

1. `constants/handlers.py`: `HandlerRelocation` + `RELOCATED_HANDLERS`
   (both nitpick detectors → `pseudo_events.nitpick.handlers.*`); a test pins
   that every relocation is also in `RETIRED_HANDLERS`.
2. New `install/handler_key_audit.py`: `audit_handler_keys` classifies every
   `handlers.<event>.<key>` the registry does not know for that event as
   `relocated` / `wrong_event` (names the right event or pseudo-event) /
   `retired` ("no longer exists — <reason>") / `unknown` (with did-you-mean);
   `migrate_relocated_handler_keys` (moves the whole entry, keeps an existing
   target, scaffolds `enabled`/`triggers` when asked); `applied_relocations`
   (backup vs written config); `scaffold_pseudo_event_blocks`.
3. `install/config_validator.py` (`config-validate`): relocated/retired →
   warnings, `valid` stays true and `guidance` now lists warnings; wrong-event
   and unknown → errors, mirroring daemon startup (Plan 00304 lesson: `valid`
   must not diverge from "the daemon would start").
4. `install/config_migrations.py` + `config_cli.py`: `MigrationAdvisory. stale_handler_keys`, a "⚠️ Stale handler keys" text section, counted in
   `has_warnings` (so upgrade.sh prints it, exit 1), JSON key
   `stale_handler_keys`.
5. `config-merge`: relocation runs on user AND old-default configs before the
   diff (`scaffold=False`), so the user's entry lands under `pseudo_events`
   as a custom section and deep-merges over the new default (user values win,
   triggers come from the default); `ConfigMerger.merge` also relocates and
   scaffolds post-merge as a backstop. `MergeResult.handler_key_migrations`
   is in the JSON; `config_preserve.sh` prints each move.
6. New CLI verb `audit-handler-keys --config --format --migrated-from`
   (exit 0/1/2). `upgrade.sh` runs it against the backup and appends
   `; moved: <src> -> <dst>` to `config_diff_summary`.
7. Reference config gains the `pseudo_events.nitpick` block;
   `tests/unit/install/test_reference_config_completeness.py` asserts the
   reference lists every registered handler per event, carries no
   unregistered key, and lists every pseudo-event handler with triggers.
8. Docs: `.claude/skills/hooks-daemon/upgrade.md`, `CLAUDE/LLM-UPDATE.md`;
   release-notes callout `UNRELEASED/release-notes/13-...md`.

## Verification

- `pytest tests/unit/install tests/unit/config tests/unit/constants tests/unit/daemon/test_cli_audit_handler_keys.py` (worktree `.venv`): all pass.
- `ruff check`, `ruff format --check`, `mypy --strict` on all 13 touched
  Python files: clean. (`tests/unit/install/test_config_validator.py:156`
  has a pre-existing mypy annotation error from February, untouched.)
- `bash -n` and `shellcheck -x` on `scripts/upgrade.sh`,
  `scripts/install/config_preserve.sh`: clean.
- End-to-end script over the real example config: a v3.41-shaped user config
  with the two detectors (priority 31/58) merges to a clean `handlers.stop`,
  `pseudo_events.nitpick.handlers` with those priorities, two `moved`
  records, and a zero-finding audit afterwards.

## Not done / for the coordinator

- Daemon not restarted (per instruction). No `sed`, no stash, no destructive git.
- The `scripts/upgrade.sh` summary path was verified by shell syntax/shellcheck
  and the CLI unit tests, not by a live client-mode upgrade run — Task 3.1's
  `dummy-client-repo.sh` smoke is the place to exercise it.
