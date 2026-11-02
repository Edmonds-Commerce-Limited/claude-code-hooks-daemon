# Fix: a trusted consumer command that redirects stderr with `2>&1` is no longer denied

**Plan**: 00556
**Issue**: #146
**Audience**: operators

`secret_file_guard` lets a trusted consumer name a protected file in flag position, because the tool reads the file itself and never prints it. An example is `ansible-playbook ... --vault-password-file <path>`. That exemption is voided when the command is compound.

Until now, any `&` counted as making the command compound, including the `&` inside a redirection operator. So the same command was allowed with `> out.log` and denied with `> out.log 2>&1`.

Redirection operators no longer void the exemption: `2>&1`, `>&2`, `&>file`, `&>>file`, `>&file` and `<&0`. The redirection's target is still judged, so these are still denied:

- `&> <protected path>`;
- `2> <protected path>`;
- a real background `&` followed by another command;
- `&&`, `;` and pipes.

Nothing to do on upgrade.
