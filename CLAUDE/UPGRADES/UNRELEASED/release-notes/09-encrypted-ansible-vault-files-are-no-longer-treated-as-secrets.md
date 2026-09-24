# Callout: encrypted Ansible Vault files are no longer treated as secrets

**Plan**: 00459
**Audience**: client projects

An encrypted Ansible Vault file whose name matches a protected glob (for
example `group_vars/all/vault_passwords.yml` against `*vault_pass*`) is now
allowed. The session-start hygiene advisory no longer tells you to gitignore
or untrack it, and `secret_file_guard` lets you read it and `git add`/`git commit` it. The gitignore safety advisory no longer asks for a glob line that
would ignore it: an existing encrypted file gets a `!/<path>` negation after
the glob. The file's content is checked on every use, so the same file
decrypted in place is fully protected again, and a plaintext vault password
file keeps every protection it had.

If you kept tracking your vault files, nothing needs to change: the wrong
warning simply stops. If you FOLLOWED the old advice and untracked or
gitignored them, put them back: remove the ignore rule (or add
`!/<path>` after it) and `git add <path>`. The hygiene advisory now names
each such file with the exact lines to use.
