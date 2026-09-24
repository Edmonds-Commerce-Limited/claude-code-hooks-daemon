# Callout: encrypted Ansible Vault files are no longer treated as secrets

**Plan**: 00459
**Audience**: client projects

An encrypted Ansible Vault file whose name matches a protected glob (for
example `group_vars/all/vault_passwords.yml` against `*vault_pass*`) is now
allowed. The session-start hygiene advisory no longer tells you to gitignore
or untrack it. `secret_file_guard` lets you read it and `git add`/`git commit`
it. The file's content is checked on every use, so the same file decrypted in
place is fully protected again, and a plaintext vault password file keeps
every protection it had. Nothing a project tracked needs to change: the
wrong warning simply stops.
