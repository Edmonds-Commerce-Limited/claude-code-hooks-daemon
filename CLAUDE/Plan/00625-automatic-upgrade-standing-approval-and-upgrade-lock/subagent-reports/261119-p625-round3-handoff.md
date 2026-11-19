# Plan 00625 round 3: handoff (design settled, no code yet)

Worktree `/workspace/.claude/worktrees/agent-a5947fd1e83f03452-ba288018`, branch
`agent-a5947fd1e83f03452-ba288018`. `main` is merged and pushed. This seat
went past its context budget while reading the code, before it changed any.
**Nothing from the relayed ruling (DESIGN 11a) is applied yet.** The design
below was reviewed once by the advisor. Start from it rather than reading
`upgrade.sh` from the top.

## Facts established

- **No trusted key.** No allowed-signers file or release public key is
  tracked anywhere (`git grep -il "allowed.signers"` finds only plan prose
  and tests). So unattended upgrades must FAIL CLOSED until the owner
  supplies the key.

- **Tooling.** This host has git 2.47.3, and `ssh-keygen -Y verify` and
  `-Y find-principals` are available.

- **The skill shim**
  (`src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/upgrade.sh`, and
  its identical `.claude/skills/...` copy) curls `scripts/upgrade.sh` from
  `main`. `tests/acceptance/test_skill_upgrade_shim.py` caps the shim at 30
  non-blank, non-comment lines; it has about 20 now.

- **Layer 1 unattended block.** It is in `scripts/upgrade.sh` at about line
  1421 (Step 5, after `fetch --tags --force` and target resolution, before
  the Step 6 `reset --hard`). The dirty-tree refusal is at about line 1036.
  The target defaults to the highest LOCAL tag, about line 1377 (this is M1).

- **What the upgrade rewrites.** The existing source for that list is skill
  step 7 (`upgrade.md`, about line 211), which stages exactly:

  - `.claude/hooks-daemon/`
  - `.claude/hooks-daemon.yaml`
  - `.claude/skills/hooks-daemon/`
  - `.claude/hooks/`
  - `.claude/settings.json`

  Other dirty paths are never committed by the upgrade, so item 5 is safe.

- **The clone's ignores.** The daemon repo's `.gitignore` ignores
  `untracked/`, `.venv` and `venv/`, so a clean clone shows an empty
  `git status`. The fake origin in `tests/integration/test_upgrade_sh_unattended.py`
  has NO `.gitignore`. Add one (`untracked/`), or `_write_record` will make
  the clone look dirty.

- **Python pre-check.** `install/auto_upgrade.py` `check_eligibility` is the
  pre-check that `version_check` uses to invite.

## Design (items 2, 3 and M1 together, first unit)

1. **`scripts/lib/release_tag_verify.sh`** defines
   `release_tag_verify <daemon_dir> <tag> <signers_file>`. On success it
   prints the tag OBJECT sha. On any failure it prints one reason and returns

   1. The checks, each needing its own RED test:

   - the tag matches `^v[0-9]+\.[0-9]+\.[0-9]+$`;
   - the signers file exists, holds at least one non-comment line, and is
     NOT inside `<daemon_dir>` (a key from the same place as the tag is never
     trusted);
   - `ssh-keygen` is on PATH;
   - `git ls-remote --tags origin refs/tags/<tag>` returns a sha (M1: the tag
     exists upstream);
   - `fetch --no-tags --force origin +refs/tags/<tag>:refs/tags/<tag>`, then
     the local tag must equal the remote sha;
   - `cat-file -t` is `tag` (a lightweight tag is refused);
   - the `tag <name>` header equals `<tag>` (an old signed tag cannot be
     replayed under a new name);
   - the body carries `-----BEGIN SSH SIGNATURE-----` (a GPG signature could
     pass against the user's keyring, so it is refused);
   - `git -c gpg.ssh.allowedSignersFile=<file> -c gpg.ssh.program=<resolved ssh-keygen> verify-tag <sha>`
     exits 0.

   Unset `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT` and `GIT_CONFIG_KEY_*`
   first, as Layer 1 does. Probe empirically whether a wrong key
   ("No principal matched") makes `verify-tag` exit non-zero. The first probe
   script in `untracked/scratch/sigtest` failed only on a `cd`, so re-run it.

2. **Trusted keys location.** The project file
   `.claude/hooks-daemon-release-signers`, in git allowed-signers format. No
   install creates it and the daemon ships no key, so it starts EMPTY and
   unattended runs fail closed. There is deliberately no env var or CLI flag,
   because the unattended agent could set either. Say plainly in DESIGN, the
   release note and the reply that this is where the owner puts the key.

3. **Installed entry `scripts/upgrade_unattended.sh`.** It runs from the
   INSTALLED clone, which is the trust root, never from `main` and never
   from the tag. It:

   - refuses self-install, and refuses `HOOKS_DAEMON_UPGRADE_REF` or
     `_BASE_URL` being set;
   - resolves the target as the highest plain X.Y.Z tag on ORIGIN
     (`ls-remote --tags --refs`, `sort -V`), or the given VERSION;
   - runs `release_tag_verify` with its own sibling lib;
   - on failure prints one line:
     `AUTO-UPGRADE REFUSED: <reason>. Nothing changed; the installed version keeps running.`
     and exits 5;
   - on success runs `git archive <tag-sha> scripts | tar -x` into
     `<clone>/untracked/upgrade-from-tag/` (removed first), then execs that
     `scripts/upgrade.sh --project-root P --unattended ... <tag>`.

4. **The shim.** When `--unattended` is among its args it execs
   `$PROJECT_ROOT/.claude/hooks-daemon/scripts/upgrade_unattended.sh` and
   never curls. Keep it within 30 lines and keep both copies identical.

5. **Layer 1 with `--unattended`.**

   - Require an explicit VERSION.
   - In the unattended block, source the INSTALLED clone's
     `$DAEMON_DIR/scripts/lib/release_tag_verify.sh` (still the installed
     version before Step 6). If it is missing, call `_needs_human`.
   - Re-verify after its own fetch.
   - Require `cmp` of `${BASH_SOURCE[0]}` against `git show <sha>:scripts/upgrade.sh`.
     If they differ, refuse: unattended runs the published tag's script,
     never main's.
   - Use the verified commit (`<sha>^{commit}`) for the Layer 2 capability
     probe (`git show`) and for the Step 6 reset. Resolve it only after
     verification.
   - Layer 2 receives the tag name. It is held under the lock, and Layer 2's
     `TARGET_COMMIT` is resolved from that name at about line 1044.
   - Keep new code OUTSIDE the lockstep lock block (`TestLockstep`).

6. **Fixture changes in `test_upgrade_sh_unattended.py` `_build`.**

   - Copy the worktree's `scripts/upgrade.sh` and
     `scripts/lib/release_tag_verify.sh` into every fake release.
   - Sign each tag annotated with a throwaway key:
     `git -c gpg.format=ssh -c user.signingkey=<key> tag -s -m m vX`.
   - Commit `.claude/hooks-daemon-release-signers` in the project.
   - Add a `.gitignore` with `untracked/`.

7. **Python.** `check_eligibility` gains a reason "no trusted release-signing
   key in .claude/hooks-daemon-release-signers" when the file is missing or
   has no key line. Then `version_check` does not invite a doomed run in
   every session (M3).

## Items 4, 5, 1 and 6 (each a later unit)

- **Item 5.** Replace the whole-project dirty refusal (about line 1040) with
  a refusal only when a dirty path falls under the step-7 list above, or when
  `git -C "$DAEMON_DIR" status --porcelain` is non-empty (this closes M11).
  - No attempt record, so the next session start retries. That is "next
    opportunity, never a loop".
  - Change the test `test_uncommitted_changes_in_the_project` (an unrelated
    dirty file now proceeds), and add tests for a dirty daemon path and a
    dirty clone.
  - Mirror the check in `check_eligibility`, with a cheap `git status` of the
    two scopes.
  - Change "a tree with uncommitted changes" in `_AUTO_UPGRADE_BODY`.
- **Item 4.** "Leaves the current version running" means stopping BEFORE
  deploy.
  - Code-enforced: the gate's `escalations` already does this (exit 5).
  - Skill text only: under `--unattended`, defer step 9 (optimise, "on your
    confirmation") and stop at any post-upgrade task that says to ask. Print
    one line and never guess.
  - Look for a machine-readable "ask" marker on post-upgrade tasks. If there
    is none, say so honestly rather than grepping prose.
- **Item 1.**
  - The code default is already ON for every install.
  - Add a once-only notice: the first time `version_check` issues the
    AUTO-UPGRADE invitation, add one line saying automatic upgrades are now
    on by default and how to switch them off. Record that it was shown in
    `<clone>/untracked/auto-upgrade/default-on-notice-shown`.
  - Amend the Plan 00223 Decision 3 wording in the live sources only, to
    name this one entry as the exception: the `standing_authorisations.py`
    docstring, its test, `docs/guides/HANDLER_REFERENCE.md`, and
    `.claude/hooks-daemon.yaml.example`. Leave `CHANGELOG.md` and
    `v3.53.0.yaml` alone.
- **Item 6.** `_AUTO_UPGRADE_TEXT` and `_AUTO_UPGRADE_DEFAULT_TEXT` become ONE
  short line each.
  - Keep "shipped default" and the opt-out snippet in the default form.
  - Keep F3's fail-closed tests.
  - The short forms may then equal the full forms.

## Then

- Run `test_upgrade_lock.py` once, backgrounded and chunked, right after the
  last `upgrade.sh` edit.
- Update DESIGN sections 2, 5, 11 and 11a (still marked as relayed),
  `CLAUDE/UPGRADES/UNRELEASED/` note 003 and `config-changes/v3.76.0.yaml`,
  and PLAN.md. Leave the numbering alone.

## Owner

- Supply the release-signing public key, and decide whether it lives in the
  project file above or elsewhere, plus a rotation rule.
- Confirm items 1 and 5 directly, because they loosen guards.
