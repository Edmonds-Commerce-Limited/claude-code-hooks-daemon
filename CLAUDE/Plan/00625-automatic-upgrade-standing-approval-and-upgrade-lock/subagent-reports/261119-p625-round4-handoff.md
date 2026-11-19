# Plan 00625 round 4: handoff

Worktree `/workspace/.claude/worktrees/agent-a5947fd1e83f03452-ba288018`, branch
`agent-a5947fd1e83f03452-ba288018`. `main` was merged at the start. Every
commit below is pushed. Read `261119-p625-round3-handoff.md` for the
whole design; this note covers only what changed and what is left.

## Done (test first, RED seen failing, then GREEN)

- **Item 5** (`620002875`, then a pathspec follow-up in `01354d8ee`).
  - `upgrade.sh` gains `_is_upgrade_owned_path`. An unattended run now
    refuses only for dirty paths under the step-7 list, or when the daemon
    clone's own status is dirty (M11). Other dirty project files proceed.
    No attempt record is written, so the next session retries.
  - `auto_upgrade.UPGRADE_OWNED_PATHS` and `check_eligibility(daemon_dir=...)`
    mirror this, with a pathspec-limited `git status`. `version_check`
    passes `daemon_dir`.
  - The fixture's fake origin now has `.gitignore` with `untracked/`.
  - Evidence: `test_upgrade_sh_unattended.py` had 30 passed. RED was seen
    on the unrelated-file test, which got exit 5 before the change. The
    `test_auto_upgrade.py` and `version_check` tests had 83 passed.
- **Item 4** (`542f55e1d`, then `01354d8ee`). Skill `upgrade.md` (both
  copies are identical) gains "Under `--unattended`, never answer for the
  user":
  - Leave any ask-the-user step undone.
  - Still run the other steps, including the 7-8 commit.
  - Skip step 9.
  - Print one line, `AUTO-UPGRADE PAUSED: ...`.
  - Post-upgrade tasks have no machine-readable "ask" marker; their metadata
    is only Type, Severity, Applies to and Idempotent. The text says so.
  - Test: `tests/acceptance/test_upgrade_md_unattended_ask_stop.py`. Its
    RED run had 2 failed; GREEN had 3 passed.
- **Items 2+3+M1, part 1 of 3** (`215acd249`).
  `scripts/lib/release_tag_verify.sh` defines
  `release_tag_verify <daemon_dir> <tag> <signers_file>`.
  - It returns 0 or 1 and sets the exported globals
    `RELEASE_TAG_VERIFY_SHA` (the tag OBJECT sha) and
    `RELEASE_TAG_VERIFY_REASON` (one line). It prints nothing.
  - It runs every check in the round-3 design, plus the advisor's hardening:
    - the physical path is resolved through symlinks;
    - only the exact `ls-remote --refs` line counts;
    - the tag header is parsed only up to the first blank line;
    - verification runs with `gpg.program=false` and `gpg.x509.program=false`;
    - an absent signers file and a comment-only one get the same refusal;
    - the `GIT_CONFIG_*` variables are unset.
  - The signature is a cross-version contract, as its header says.
  - Test: `tests/integration/test_release_tag_verify.py`. RED had 18
    failed; GREEN had 18 passed.
  - Probe result: with a wrong key, `verify-tag` exits 1 ("No principal
    matched"). The script is `untracked/scratch/sigprobe.sh`.

## Left, in order

1. **Entry script, shim and Layer 1, one commit, test first** (the fixture
   is shared).
   - **Fixture (`test_upgrade_sh_unattended.py` `_build`).**
     - Generate a throwaway ed25519 key in `tmp_path`.
     - Copy the worktree's `scripts/upgrade.sh`,
       `scripts/upgrade_unattended.sh` and `scripts/lib/release_tag_verify.sh`
       into EVERY fake release.
     - Sign each tag with
       `git -c gpg.format=ssh -c user.signingkey=K tag -s -m m vX`.
     - Write `project/.claude/hooks-daemon-release-signers` as
       `release <pubkey>` and commit it.
     - Also check the other fixtures that use `--unattended`:
       `test_upgrade_pre_deploy_phase_runs_on_layer1.py` and
       `test_upgrade_unattended_rollback.py`. They break once verification
       is mandatory.
   - **New tests.**
     - With the key absent: exit 5, the one-line refusal, HEAD unchanged,
       no attempt record. Then add the key and the same version proceeds.
     - A release whose `upgrade.sh` differs from the script run is refused
       ("never main").
     - One run through the installed entry script.
     - Unattended with no VERSION: exit 1.
   - **Layer 1 (`scripts/upgrade.sh`).**
     - In the argument-refusal block (about line 895, under
       `_UNATTENDED`), `_fail` when `TARGET_VERSION` is empty.
     - In the unattended block, after the attempt-file check (about line
       1473\) and before the Layer 2 probe:
       - Source `$DAEMON_DIR/scripts/lib/release_tag_verify.sh`, using a
         `# shellcheck source=lib/release_tag_verify.sh` directive as at
         line 1359. If it is missing, `_needs_human`.
       - Call it with `"$PROJECT_ROOT/.claude/hooks-daemon-release-signers"`.
         On failure, `_needs_human "$RELEASE_TAG_VERIFY_REASON"`.
       - Set
         `_VERIFIED_COMMIT=$(git rev-parse --verify --quiet "$RELEASE_TAG_VERIFY_SHA^{commit}")`.
       - Require
         `cmp -s "${BASH_SOURCE[0]}" <(git show "$_VERIFIED_COMMIT:scripts/upgrade.sh")`.
       - Use `$_VERIFIED_COMMIT` in the Layer 2 probe `git show` and in the
         Step 6 `reset --hard` (about line 1555), as
         `"${_VERIFIED_COMMIT:-$TARGET_VERSION}"`.
       - Layer 2 still receives the tag name.
       - Keep all of it outside the lockstep lock block (`TestLockstep` in
         `tests/integration/test_upgrade_lock.py`, line 107).
     - A Layer 1 `_needs_human` writes no attempt record. Only Layer 2's
       exit at about line 1728 records one.
   - **`scripts/upgrade_unattended.sh`** (new; the TDD gate needs its test
     first). It takes `--project-root P [flags] [VERSION]`.
     - Refuse if `HOOKS_DAEMON_UPGRADE_REF` or `_BASE_URL` is set, and
       refuse self-install (no `P/.claude/hooks-daemon/.git`).
     - The target is the given VERSION, normalised to `v`, or else the
       highest `^v[0-9]+\.[0-9]+\.[0-9]+$` from
       `git ls-remote --tags --refs origin` sorted with `sort -V`.
     - Source its sibling `lib/release_tag_verify.sh`. On failure print
       `AUTO-UPGRADE REFUSED: <reason>. Nothing changed; the installed version keeps running.`
       and exit 5, with no attempt record.
     - Otherwise run
       `git show "<sha>^{commit}:scripts/upgrade.sh"` into
       `$D/untracked/upgrade-from-tag/<sha>.sh` (temp file then `mv`,
       because two sessions can race before the lock).
     - Then exec `bash` on it with
       `--project-root P <flags incl. --unattended> <tag>`.
   - **Shim** (both copies: `src/.../skills/hooks-daemon/scripts/upgrade.sh`
     and `.claude/skills/...`).
     - After the project-root loop, a `case " $* " in *" --unattended "*)`
       branch execs the installed entry.
     - If the entry is missing, print the same one-line refusal and exit 5.
     - Stay within 30 non-blank, non-comment lines
       (`tests/acceptance/test_skill_upgrade_shim.py`); it is about 22 now.
2. **`check_eligibility` reason.** Refuse with "no trusted release-signing
   key in .claude/hooks-daemon-release-signers" when that file is missing or
   holds only comments (M3). This needs a `signers_file` parameter that
   `version_check` passes.
3. **Item 1.** Add the once-only default-ON notice, recorded in
   `<clone>/untracked/auto-upgrade/default-on-notice-shown`, and amend
   Plan 00223 in the live sources (see the round-3 note). **Owner choice to
   state:** with no key there is never an invitation, so this notice cannot
   show until a key exists.
4. **Item 6.** Make `_AUTO_UPGRADE_TEXT` and `_AUTO_UPGRADE_DEFAULT_TEXT`
   one short line each. Also fix `_AUTO_UPGRADE_BODY`'s "a tree with
   uncommitted changes" for item 5.
5. **Lock tests.** Run `test_upgrade_lock.py` once, backgrounded and in
   chunks.
6. **Docs.**
   - DESIGN sections 2, 5, 11 and 11a: replace the OWNER DECISION items
     with the relayed ruling, still marked relayed.
   - `CLAUDE/LLM-UPDATE.md` "Unattended upgrades" probably still describes
     the whole-project dirty refusal.
   - Release note 003 (leave the numbering; it collides with Plan 00626),
     `config-changes/v3.76.0.yaml` and PLAN.md.

## Owner

- Supply the release-signing public key and confirm where it lives
  (`.claude/hooks-daemon-release-signers`, allowed-signers format), plus a
  rotation rule. Until then every unattended upgrade fails closed.
- Confirm items 1 and 5 directly, because both loosen guards.
