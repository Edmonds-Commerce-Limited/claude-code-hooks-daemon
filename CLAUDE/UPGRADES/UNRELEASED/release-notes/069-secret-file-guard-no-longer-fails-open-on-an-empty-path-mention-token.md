# Callout: `secret_file_guard` no longer fails open on an empty path-mention token

**Plan**: 00466
**Audience**: everyone

A security fix. Writing or editing a file whose content declared a bare `"~/"`
string literal, with nothing following it, crashed `secret_file_guard`'s
content scan with `ValueError: no path specified`; the same shape on the
Bash command surface crashed the same way. Because that crash happened
inside the handler's `matches()` check, the daemon's default (non-strict)
config treated it as "this handler has nothing to say" and skipped the whole
secret-file guard for that call, including any genuine protected-path mention
elsewhere in the same content. Under `daemon.strict_mode: true` the crash
denied instead, as a SYSTEM ERROR rather than a silent bypass. The guard is
now total on this input shape at two independent layers, and a call carrying
both an affected token and a real protected mention is confirmed still
denied. No action needed: this was never an intentional bypass route, just
an unhandled edge case, and it is closed.
