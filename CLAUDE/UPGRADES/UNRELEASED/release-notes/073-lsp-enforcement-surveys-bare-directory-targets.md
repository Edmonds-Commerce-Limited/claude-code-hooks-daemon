# Callout: lsp_enforcement judges a bare directory search by the files it holds

**Plan**: 00527
**Audience**: client projects

`lsp_enforcement` decides whether an enabled language server can answer a search from the file type it names (a glob, an rg type, a file path). A search naming only a directory, such as `rg -n "agent_bus_lxc_bridge" playbooks`, names no type, so any enabled server counted as covering it. A snake_case Ansible variable searched in a YAML-only tree drew the `block_once` deny and was pointed at a Python language server that cannot read YAML. Now, when every target is an existing directory and no type is named, a bounded survey of the files those directories hold decides: no file a served language handles means advice, not a deny. A survey that cannot decide (over 2000 entries, or an unreadable directory) keeps the previous answer.
