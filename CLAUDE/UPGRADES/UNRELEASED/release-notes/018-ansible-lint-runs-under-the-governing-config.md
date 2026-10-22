# Callout: Ansible lint can run under a declared governing ansible.cfg

**Plan**: 00547
**Audience**: client projects

A play outside its `ansible.cfg`'s tree resolved no module root, so `lint_on_edit` ran `ansible-playbook --syntax-check` from the workspace root and `staged_lint_gate` ran it from the daemon's own working directory, neither with the config. A valid play that read `CONFIG_FILE` was then denied for a context error that was not its own defect. New `layout.ansible_configs` maps a play glob to a repo-relative `ansible.cfg` (for example `{"plays/**": "infra/ansible.cfg"}`); a matching play is checked from the config's directory with `ANSIBLE_CONFIG` set, by both gates, and a declared file that does not exist is a loud error. With no marker and no declaration both gates now run from the same workspace root, and a failed Ansible check that ran with no config still denies but adds a line saying no `ansible.cfg` was in effect and naming the option. Other languages are unchanged.
