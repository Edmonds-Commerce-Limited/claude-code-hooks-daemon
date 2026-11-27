# Callout: a teamchat message sent on stdin is no longer judged as a path mention

**Plan**: 00474
**Audience**: everyone

`secret_file_guard` no longer denies a teamchat message because its TEXT quotes a protected glob or names a protected file. It applies to the message verbs only (`say`, `reply`, `report`, `thread`, `ask-human`, `close`, `retitle`), and only when the whole Bash command is one plain statement whose message arrives on stdin in exactly one of three ways: a quoted-delimiter heredoc (`teamchat report <<'EOF'` ... `EOF`, nothing but blank lines after the closing line), a single-quoted here-string (`teamchat report <<< '...'`), or one `printf` or `echo` of literal quoted words piped in by a single `|`. Only space, tab and newline count as blank. The teamchat words themselves are still judged: a `--ref path:...` or member name that names a protected path still denies. Any other shape is judged exactly as before: a pipe out of teamchat, a chain, any redirect, a substitution or variable, an unquoted heredoc, a wrapper or assignment before `teamchat`, an unknown flag, another verb (`run`, `ping`), a producer that opens a file (`cat`, `tee`, `head`), or a `printf`/`echo` option. A script written with Write or Edit is never relaxed: a script is run, not sent. Residual risk: a sink that wrote its stdin to a file would not be covered; teamchat does not.

A quoted argument of several words whose whole text names a file that exists or is indexed (a protected file with a space in its name) is now always a mention, whatever its single words are. Before, `pr 'mid dle.secret.key x'` reached such a file when no single word of it counted.

Unchanged: a word matching an underscore pattern (a Python test name holding the vault-password stem, say) is still judged by the pattern alone, as before.
