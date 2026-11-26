# Callout: A missing Ansible vault key file no longer blocks edits of a play

**Plan**: 00474
**Audience**: client projects

Where the vault key file named by `ansible.cfg` does not exist (a fresh container, a CI checkout), `ansible-playbook --syntax-check` stops on that line before it reads the play, so every edit of every play was denied by the edit-time lint and the commit gate with a failure that said nothing about the file. That output is now treated as an environment gap: the write or commit goes ahead with an advisory that the play was not checked. Both the `ERROR!` and the newer `[ERROR]:` prefix are recognised, with or without colour. Any other Ansible output, including a real syntax error, is still denied.
