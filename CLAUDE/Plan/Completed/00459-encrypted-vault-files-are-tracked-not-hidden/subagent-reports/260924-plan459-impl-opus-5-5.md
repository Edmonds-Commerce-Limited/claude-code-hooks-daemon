# Plan 00459 Phase 1 implementation report

**Branch**: `worktree-plan-459-vault` (not pushed, not merged)
**Commits**: `5d76a94e`, `7d955396`, `c11eaf66`, `4adf4083`, `9f6c4065`,
`ac696f0e`, plus the follow-up-round commit carrying this revision
**QA**: first round `QA: 35/35 PASSED` (tests `25654 passed, 0 failed, 24 skipped`, coverage 95.1%), worktree daemon RUNNING. The follow-up round's QA
runs in the foreground on the commit carrying this revision, with nothing
committed after it, so its result is in the reply to the lead rather than
here.

## What was built

One detector, two callers.

- `src/claude_code_hooks_daemon/utils/encrypted_at_rest.py`:
  `classify_at_rest(path, project_root)` returns `ansible-vault`,
  `ansible-vault-inline` or `none`. `is_encrypted_at_rest()` is True only for
  the first. It is the single definition, and both handlers call it.
- `secret_file_guard` calls it on every path tool, on the Bash mention route
  (through `secret_file_matching.is_encrypted_target_invocation`) and on the
  directory-rooted Grep walk.
- `secret_file_hygiene_checker` calls it for every protected path it finds.

Format sources vendored with `remote-docs add`: the Ansible vault guide
(converted) and `lib/ansible/parsing/vault/__init__.py` (verbatim). The
SOPS reference is cited by URL, commit and sha256 in the journal, not
vendored (see the 12:51 journal entry).

## Security decisions and why

01. **The whole file is verified, not a prefix.** The header must match
    `$ANSIBLE_VAULT;1.1;AES256` or `;1.2;AES256;<label>` exactly. Every
    following line must be lowercase hex. The armour must decode to
    `hex(salt) \n hex(64) \n hex(32k)` (salt, HMAC-SHA256, PKCS7-padded AES
    ciphertext), per `format_vaulttext_envelope` and `VaultAES256.encrypt`.
    The inner structure is what rejects a lookalike header followed by a
    plaintext hex token. Plaintext appended after valid armour is rejected.
02. **Bounded read: 4 MiB.** A larger file is not confirmed. `st_size` is
    checked first, and the bound is enforced again on the bytes actually
    read, because the file can grow in between.
03. **Fails closed.** These all answer `none`: a relative path, no project
    root, a realpath outside the project root, a non-regular file (`lstat`
    before open), an inode or device changed between `lstat` and `open`
    (`fstat` compare), any `OSError`, `1.0;AES` legacy, a label on 1.1, or no
    label on 1.2. The file is opened with `O_NOFOLLOW | O_NONBLOCK`, so a FIFO
    swapped in cannot hang a PreToolUse handler.
04. **No cache.** Every call re-reads. The decrypted-in-place tests flip the
    same path encrypted, plaintext, encrypted and check the verdict each time.
05. **Content never leaves.** The only return value is the enum. The only
    thing logged is the exception class name.
06. **Bash: every mention must be confirmed, but that alone is not
    sufficient, so the exemption is deny-by-default.** Ansible finds a vault
    password from config (`DEFAULT_VAULT_PASSWORD_FILE`,
    `ANSIBLE_VAULT_PASSWORD_FILE`) without the command naming it. `git diff|log|show|blame` decrypt under the common `diff=ansible-vault`
    textconv setup. So naming only an encrypted file does not make a command
    safe, and a list of commands that decrypt could never be complete. The
    exemption applies only when ALL of these hold:
    - It is one simple command, split into words by shlex. There is no `;`,
      `&&`, `||`, `|`, background `&`, subshell or process substitution, and
      redirections are the only operators.
    - No `$`, backtick, backslash, newline, glob or brace character, or `~`
      appears anywhere in it.
    - The head is `git` followed immediately by
      `add|commit|status|mv|rm|ls-files|check-ignore`. Git global options are
      refused, so `-C` cannot move the read. `-p/-i/-e/-v` and their long
      forms are refused because they render diffs. Otherwise the head is one
      of `cat head tail wc ls stat file cp mv`.
    - Every protected mention is a complete literal shell word that resolves,
      absolute or joined to the event's absolute `cwd`, to a confirmed file.
      This defeats a glob that also reaches a plaintext sibling, `cd x && ...`,
      `"$D"<file>`, `x<file>`, `--flag=<file>`, and a commit message naming
      the file.
07. **`grep` was taken off the allowlist while going GREEN.** `grep -r p <vault file> .` names only the encrypted file but reads the whole tree.
    The Grep TOOL still works on an encrypted file.
08. **The existing exemptions come first and are unchanged.** `secret-meta`,
    the consumer allowlist and `git rm --cached` behave as before.
    `ansible-vault view|decrypt|edit` stay denied, as does every `ansible*`
    head, because none is on the encrypted-target allowlist.
09. **Script authoring is NOT exempted.** This departs from the plan's
    "every surface" wording on purpose. A script runs later, from a Bash call
    that need not name the file, so no check happens at the time of use, and
    the file may have been decrypted by then. The lead's time-of-use rule
    decides it.
10. **Path tools.** A relative path is resolved against `cwd`; with no `cwd`
    it is not confirmed. A Grep rooted at a directory is allowed only if
    every protected file under it is confirmed (`is_exempt` predicate on the
    existing bounded walk).
11. **Hygiene checker.** An encrypted file gets no gitignore, untrack or
    permissions finding. Tracked ciphertext is readable by the repository's
    readers by design, so `chmod 600` on the working copy protects nothing.
    If an encrypted file is the only match, there is no output at all: the
    owner's "the warning should stop". When the advisory prints for another
    file, encrypted files are listed as "tracking is correct".
12. **Task 1.2(a), inline `!vault |` YAML:** the plan's recommendation was
    adopted. The file stays read-protected. The hygiene checker replaces the
    gitignore/untrack findings with one statement: tracking is correct only
    if every secret value in it is vaulted, which the daemon cannot verify.
    The permissions finding is kept.
13. **Task 1.2(b), SOPS: excluded.** The `sops:` block with `mac` and
    `lastmodified` proves the file is SOPS-managed, not that it is safe to
    read. Keys are cleartext by design, `encrypted_suffix|regex` and
    `unencrypted_*` leave values unencrypted by configuration,
    `mac_only_encrypted` narrows the MAC, and proving "no plaintext" needs a
    full structured parse of a possibly-plaintext file. That is case (a)
    again, so the file stays protected.
14. **Flaggable/quarantine guards** use their own glob sets, not the secret
    globs, so they do not re-block a vault file by name. Nothing changed.

## Adversarial tests (all RED first; evidence in the journal)

Detector (`tests/unit/utils/test_encrypted_at_rest.py`, 44):

- a lookalike header followed by plaintext
- a lookalike header followed by a plaintext hex secret
- plaintext appended after valid armour
- a blank line inside the armour, uppercase hex, leading whitespace, odd
  length, and armour that does not decode to three fields
- seven malformed or unsupported headers
- empty file, header only, and binary data
- decrypted in place, then re-encrypted
- one byte over the bound, and exactly at it
- a FIFO (no hang), a directory, a missing file, an unreadable file
- an inode swapped between `lstat` and `open`
- a relative path, no project root, and a file outside the project
- symlinks: to a vault inside the project (allowed), to a vault outside
  (denied), named like a vault but pointing at plaintext (denied), and
  dangling (denied)
- inline `!vault` YAML, and an inline file over the bound

Bash exemption (`tests/unit/utils/test_secret_file_matching.py`):

- **Allowed:** each allowed head, then the same heads with a plaintext
  sibling added (denied)
- **Commands that decrypt:** 15 of them, including `EDITOR=cat ansible-vault edit`, `ansible ... -e @<file>`, `git diff|log -p|show|blame|grep|cat-file --textconv`, and `python3 decrypt.py`
- **Wrapped or path-spelled heads:** `sh -c`, `env`, `command`, `sudo`,
  `xargs`, `/bin/cat`, `./cat`, and an assignment prefix
- **Git options:** global options, and flags that render diffs
- **Compound and shell tricks:** 8 compound shapes, `cd` before the read,
  13 expansion shapes (globs covering a plaintext sibling included), 5 ways
  a token can be only part of a shell word, process substitution and
  here-strings, a redirect into a plaintext protected name, and unbalanced
  quoting

Guard (`test_secret_file_guard.py`):

- Read and `git add` of the same path, encrypted and then decrypted in place
- a glob covering the encrypted file and a plaintext `.bak` sibling
- the encrypted file named together with a plaintext `.vault-pass`
- a symlink named like a vault file pointing at plaintext (Read and Bash)
- a huge file, an empty file, and an encrypted file outside the root
- a relative path with no `cwd`
- `ansible-vault view|decrypt|edit` and `git diff`
- directory Grep over only encrypted files, and with a plaintext sibling
- script authoring (still denied)
- plaintext `.vault_pass`, `.vault-pass` and `vault_pass.txt`, each on Read,
  Grep, `cat` and `git add`

Hygiene (`test_secret_file_hygiene_checker.py`):

- an encrypted file alone is silent (RED reproduced the owner's report)
- an encrypted file beside a real finding
- decrypted in place, the advice comes back
- inline YAML, both tracked and gitignored
- the non-git fallback
- armour and plaintext content never appear in the output

Acceptance probes:

- ALLOW `allows naming an encrypted vault file`, and DENY `blocks the same vault file decrypted in place`.
- Both were confirmed EXECUTED (not skipped) and passing by the in-process
  contract harness against this repository's real config.

## Residual risks (documented, not new capability)

- **`cwd` trust.** A relative mention is resolved against the hook's `cwd`.
  If that ever differed from the shell's real working directory, a relative
  token could name a different file. Other path-resolving handlers make the
  same assumption.
- **Ciphertext in context.** An agent that has read ciphertext could write
  it under an unprotected name and decrypt it with a configured password.
  That was already true for every vault file whose name matches no glob.
  Plan 00272 states the scope: it protects the password file, not the
  vaulted payload.
- **Hardlinks.** `ansible-vault decrypt` removes and recreates the file
  (`write_data`, `O_CREAT | O_EXCL`), so a hardlink to the ciphertext keeps
  ciphertext. `ln` is not on the allowlist, so the exemption cannot create
  one. An in-place-rewriting tool on a pre-existing hardlink is the existing
  class-(d) residual.
- **Time of check.** If a concurrent process decrypts the file between the
  check and the tool's read, the read gets plaintext. This is inherent to a
  PreToolUse check.

## Friction the exemption deliberately keeps

- A commit message naming the file is denied. Name the file as its own
  argument, or use `git commit -F <file>`.
- `git mv` to a new protected name is denied, because the destination does
  not exist yet.
- `git add <file> && git commit ...` is denied. Use two calls.
- An agent cannot create a new encrypted file at a protected name
  (`ansible-vault create|encrypt --output`). That was the case before this
  plan too.
- A human running the playbook cannot run the ALLOW probe's setup through
  the Bash tool, because it names a protected path that does not exist yet.
  The probe's `safety_notes` say so.

## Follow-up round (lead's request): both open ends fixed on this branch

- **`gitignore_safety_checker` is content-aware** (it previously asked for a
  bare `.gitignore` line per protected glob, which would ignore every NEW
  encrypted vars file at a matching name).
  - Every session, uncached, it checks the protected files git knows about
    with the same detector.
  - A protected glob it advises is followed by a `!/<path>` negation for
    each existing ciphertext file that glob would catch.
  - Ciphertext that a present rule already ignores is reported with its
    negation.
  - Plaintext stays required-ignored.
  - With no file yet, the advice carries a one-line caveat.
  - A test applies the advised lines verbatim and asks git that the
    ciphertext is not ignored and the plaintext is.
- **Recovery.** `secret_file_hygiene_checker` tells untracked and/or ignored
  ciphertext that it SHOULD be tracked: remove the rule or add `!/<path>`,
  then `git add <path>`. The release note says so plainly for projects that
  followed the old advice.
- **Shared code.** `utils/git_file_states.py` is the one `git ls-files`
  scan (now including tracked files an ignore rule matches). It also holds
  `gitignore_negation()` (root-anchored, pattern characters escaped, proven
  against git) and `unignore_advice()`, the one wording both handlers use,
  including git's limit on re-including a file under an ignored directory.
- **Truth-change filename: kept `v3.67.0.yaml`.** The README and
  `RELEASING.md` require version-named files. The loader skips any stem that
  is not `N.N.N`, so `vUNRELEASED.yaml` would be ignored. Plan 00427 staged
  `v3.66.0.yaml` four days before that release. Evidence is in the 13:19
  journal entry.

## Out of scope, for the lead

- **Payload capture and `lint_on_edit`/`staged_lint_gate`** still exclude an
  encrypted file as protected. This is harmless over-exclusion and was left
  alone.
- **Deny message.** It names the FIRST mention, which may be the encrypted
  file when the plaintext one is later in the command. This is a UX nicety
  only.
- **Vendored source path.** The Ansible source capture sits under a path
  containing `lib/`, which the root `.gitignore` rule `lib/` catches, so it
  was force-added. Anchoring that rule is a possible tidy-up.
- **SOPS capture in history.** Commit `c11eaf66` briefly added the SOPS
  reference capture, and `9f6c4065` removed it. It remains in branch
  history. The `git_history` QA sweep passed with it present, because its
  UUID-shaped strings are upstream examples, not session ids.
