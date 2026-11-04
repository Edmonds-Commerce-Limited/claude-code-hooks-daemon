# Callout: a pattern-only grep is no longer denied just because another statement follows it

**Plan**: 00556
**Issue**: #144
**Audience**: operators

`secret_file_guard` already let a grep-family search through when the protected name was only the search pattern, because searching for a name does not open the file. That exemption was lost as soon as the grep was one statement of a compound command, so a search that was allowed alone was denied once `; echo done` followed it.

A compound command is now judged statement by statement. It is allowed only when every statement either carries no protected mention or is itself a grep search whose file arguments are not protected. `;`, `&&` and `||` separate statements, and so does a newline, provided the command has no heredoc.

Everything that could read the file is still denied:

- a later statement that names a protected file;
- a pipe into a reader, a background `&` or a subshell;
- a redirect into a protected path;
- a `-f` or `--file` pattern file;
- a pattern assigned in one statement and expanded in another, since expansion characters are still refused across the whole command;
- a multi-line command with a heredoc, or a newline inside quotes.

Nothing to do on upgrade.
