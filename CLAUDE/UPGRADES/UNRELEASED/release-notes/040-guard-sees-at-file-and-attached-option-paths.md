# Callout: a protected path given as `@FILE` or an attached short-option value is now judged

**Plan**: 00483
**Audience**: everyone

Owner ruling A4 (the review's keep, narrow or drop list for in-flight items). `secret_file_guard` did not see a protected path written after a leading `@` (`curl -d @<path>`, `ansible-playbook -e @<path>`) or attached to a short option (`grep -f<path>`, `ansible -i<path>`), so those commands were allowed while the spaced spelling was denied. The mention scan now also reads the text after a leading `@` and after the two characters of a single-dash option. Nothing else changes: an `@` or an attached option value that names no protected path (`git log --author=dev@example.com`, `curl -d @data.json`, `tar -czfout.tgz src`) is still allowed, and the ordinary-command corpus holds rows pinning that.

The Write/Edit content scan also treats `.pyw`, `.pm`, `.cjs`, `.mts`, `.tsx`, `.kt`, `.swift` and `.ps1` files as scripts, so a protected path quoted in one is judged like one in a `.py` file. The per-language launch-call shapes the ledger listed (N75) and the shell-launch argv shapes (N76) are dropped, and the `cd`-then-relative-write containment gap (N28) is deferred.
