# Callout: recursive searches are judged by the files they would read

**Plan**: 00483
**Audience**: everyone

A recursive search that never names a protected file is now denied when it would read one: `grep -r x .`, `rg --hidden x`, `find . | xargs rg x`, `find . -exec grep x {} +`, `git grep x` over a tracked file, `ugrep -r`, `ack`, and the same inside `bash -c`, `sh -c` or `eval`. The quarantine guard applies the same check to `*-opus-security-DETAIL*` artefacts. `rg` and `ag` are judged as they behave: they skip hidden and gitignored files unless given `--hidden`, `-u` or `--no-ignore`, while `grep -r` reads everything. `--exclude-dir`, `--exclude` and `rg -g '!dir'` that remove the protected path allow the search. The walk keeps the Grep tool's 5000-file cap, so a very large tree is still only partly checked.
