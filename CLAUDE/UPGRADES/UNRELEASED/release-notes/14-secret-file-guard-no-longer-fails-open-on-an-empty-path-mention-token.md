# Callout: `secret_file_guard` no longer fails open on an empty path-mention token

**Plan**: 00466
**Audience**: everyone

A security fix. Writing or editing a file whose content declared a bare
shell/Python path-expansion operand — a quoted `"~/"`, `"$PWD/"` or
`"${PWD}/"` string literal, with nothing following it — crashed
`secret_file_guard`'s content scan with `ValueError: no path specified`.
Because that crash happened inside the handler's `matches()` check, the
daemon treated it as "this handler has nothing to say" and skipped the
whole secret-file guard for that write, including any genuine protected-path
mention elsewhere in the same content. The guard is now total on this input
shape at two independent layers, and a write carrying both an affected
operand and a real protected mention is confirmed still denied. No action
needed: this was never an intentional bypass route, just an unhandled edge
case, and it is closed.
