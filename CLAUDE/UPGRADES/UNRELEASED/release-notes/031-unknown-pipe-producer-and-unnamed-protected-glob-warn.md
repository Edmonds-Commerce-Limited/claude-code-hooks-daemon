# Callout: pipe_blocker and write_protected_paths warn instead of denying when they cannot decide

**Plan**: 00478
**Audience**: client projects

Under the owner's "warn dont block" ruling, two more guards allow with an advisory (and one log line starting `UNKNOWN-VERDICT <handler>`) where they used to deny for lack of a verdict.

`pipe_blocker`: a producer on neither the whitelist nor the blacklist (for example `my_report --all | tail`) is no longer blocked. The advisory names `bin/echd-capture` for an expensive command and `extra_whitelist` for a cheap one. These still deny:

- A known expensive producer (`pytest`, `npm test`, `cargo`, `make`, ...). This includes one run through a wrapper or runner: leading `VAR=x`, `env`, `timeout N`, `sudo`, `nice`, `nohup`, `uv run`, `poetry run`, `pipenv run`, `npx`, `xargs`, `python3 -m`, a `bash -c '...'` body and a path-qualified name (`.venv/bin/pytest`).
- A prose-shaped match, and a pipe fed by a whole loop, `if`, `case` or group.
- Every pipe in a command is judged. An unknown pipe never excuses another one: `docker ps | tail -1 && pytest | tail -5` denies on `pytest`.

An expensive command that is on no list (a project script such as `./scripts/qa/run_all.sh`) now only warns. Add it to `extra_blacklist` to keep the deny. An entry is matched against the bare command name as well, so `^run_all\.sh\b` covers the script at any path.

`write_protected_paths`: when a command cannot be read (unclosed quote, brace group past the spelling cap, text too deep or large to scan) and no listed path is literally named in it, the command is now allowed with an advisory. This is what a protected-path glob with no literal part (such as `**`) used to turn into a deny. An awk program writing to a computed destination (`print > FILENAME`, `> $1`) is in the same position only when neither the program nor any of its file operands names a listed path. A listed path named among its operands (`awk '{print > FILENAME}' protected/x`) still denies. Wherever a listed path IS named in the command, an unknown verb or unreadable text still denies. If you relied on that deny as a backstop, list a literal path to keep it.
