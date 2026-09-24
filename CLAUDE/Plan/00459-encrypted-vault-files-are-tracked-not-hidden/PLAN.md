# Plan 00459: encrypted vault files are tracked not hidden

**Status**: In Progress
**Created**: 2026-09-24
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration (worktree, TDD)

## Overview

The owner reported that a client project's session-start output told it to
gitignore and untrack its own Ansible Vault files ("WRONG"). An Ansible Vault
file is encrypted at rest and starts with a `$ANSIBLE_VAULT;` header.
Committing it is the whole point of Vault, so following that advice would
drop a project's encrypted secrets from version control.

**Cause.** The secret-file protection from Plan 00272 selects files by name
alone. Its default globs include `*vault_pass*`, which exists for the
plaintext vault PASSWORD file (`.vault_pass`, `vault_pass.txt`), and
`*.secret*`. Both also match encrypted files:
`group_vars/<group>/vault_passwords.yml` is an encrypted vars file whose name
describes its contents, and a `*.secrets` template may be vault-encrypted
too. Two consequences follow for an encrypted file:

1. `secret_file_hygiene_checker` (SessionStart) reports it as unsafe and
   prescribes `.gitignore` plus `git rm --cached`. That advice is wrong.
2. `secret_file_guard` (PreToolUse) treats it as secret. That includes
   denying any Bash command that MENTIONS the path, so `git add <vault file>`
   is refused, and the project cannot commit an update to its own encrypted
   vars.

**The distinction is the content, not the name.** The plaintext password
file must stay protected. The ciphertext file is safe to read, to track and
to name in a command. The daemon can tell the two apart by reading the first
line locally. That line is the format header, never secret material, and
reading it happens inside the daemon, not in the model's context. The check
has to be made at the time of each use: `ansible-vault decrypt` rewrites the
file IN PLACE as plaintext, and at that point the header is gone and full
protection must return on the very next check.

## Goals

- A protected-glob match whose content is a whole-file Ansible Vault payload
  (a first line `$ANSIBLE_VAULT;<version>;<cipher>`, per the format spec) is
  treated as safe to track. The hygiene checker gives no gitignore or
  untrack advice for it, and the guard does not deny reading it, naming it,
  or `git add`/`git commit` of it.
- The same file, once decrypted in place, is fully protected again at the
  next check, with no cache to go stale.
- A plaintext vault password file keeps every protection it has today.
- The advice text says why an encrypted file is fine and what would make
  it unsafe.

## Non-Goals

- Changing the default globs. The content check makes a name-only
  exemption unnecessary, and narrowing `*vault_pass*` would weaken
  protection of real password files.
- `git-crypt`. Its working-tree files are PLAINTEXT (smudge filter), so they
  are correctly protected as they are.

## Tasks

### Phase 1: TDD in a worktree

- [x] ✅ **Task 1.1**: One shared detector, e.g.
  `utils/encrypted_at_rest.py`. It reads a bounded prefix of the file,
  never the whole file, and returns whether the content is a whole-file
  Ansible Vault payload. The rule comes from the format specification:
  the header line, then hex-only body lines. It fails closed. An unreadable
  file, a symlink out of the project, a non-regular file or a malformed
  header means NOT encrypted, so protection stays on. Tests include a
  decrypted-in-place file and a lookalike header.
- [x] ✅ **Task 1.2**: Decide, with evidence, two adjacent formats. (a) YAML
  with inline `!vault |` values: plaintext keys, and possibly plaintext
  values beside the vaulted ones. The daemon cannot prove every secret is
  vaulted, so the recommendation is to keep read protection but replace the
  untrack advice with a statement that tracking is correct only if every
  secret value is vaulted. (b) SOPS files (a top-level `sops:` metadata
  block): include them only if detection is unambiguous. Record both
  decisions in the journal.
- [x] ✅ **Task 1.3**: `secret_file_hygiene_checker` uses the detector. It
  gives no gitignore or untrack findings for an encrypted file, and reports
  it as "encrypted at rest, tracking is correct". Existing findings for
  plaintext protected files are unchanged.
- [x] ✅ **Task 1.4**: `secret_file_guard` uses the detector on every
  surface it guards (Read/Grep/Edit, the Bash mention check, script
  authoring). An encrypted file is allowed through, and so is `git add` or
  `git commit` naming it. The guard's explicit denials of `ansible-vault view|decrypt` and of `--vault-password-file` misuse are unchanged, because
  those print plaintext. A decrypted-in-place file is denied again. Check
  that the flaggable-content and quarantine guards do not re-block the same
  file by name.
- [x] ✅ **Task 1.5**: Docs (the handlers' guidance, `explain-rule`
  text, the secret-file docs) and a release note. Full QA green.

### Phase 2: Deliver

- [ ] ⬜ **Task 2.1**: Merge `--no-ff`, verify ancestry and CI, and restart
  the daemon.
- [ ] ⬜ **Task 2.2**: Tell the owner what the client project must do after
  upgrading. Its hygiene warning will simply stop, and nothing it tracked
  needs to change.

## Success Criteria

- [x] Test: an encrypted `vault_passwords.yml` under `group_vars/` yields no
  hygiene finding, can be Read, and `git add` naming it is allowed.
- [x] Test: the same path decrypted in place is denied on Read and on a Bash
  mention, and gets the hygiene advice.
- [x] Test: a plaintext `.vault_pass` is protected exactly as before.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00459-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet delivered.
