# Callout: pipe_blocker and write_protected_paths warn instead of denying when they cannot decide

**Plan**: 00478
**Audience**: client projects

Under the owner's "warn dont block" ruling, two more guards allow with an advisory (and one log line starting `UNKNOWN-VERDICT <handler>`) where they used to deny for lack of a verdict.

`pipe_blocker`: a pipe to `tail`/`head` whose producer is on neither the whitelist nor the blacklist is allowed with an advisory **only when no blacklisted command is named anywhere in the command**. The advisory names `bin/echd-capture` for an expensive command and `extra_whitelist` for a cheap one. For example, `my_report --all | tail` and `docker ps | tail -1` warn. These still deny:

- A known expensive producer (`pytest`, `npm test`, `cargo`, `make`, ...) feeding the pipe, including through a wrapper or runner the guard reads through (`VAR=x`, `env`, `timeout N`, `sudo`, `uv run`, `npx`, `xargs`, `python3 -m`, a `bash -c '...'` body, `.venv/bin/pytest`).
- Any pipe whose producer is unknown, when a blacklisted command appears anywhere in the command text: in another statement, a substitution, a `-c` body or a here-string. The match is per word: as written, as a path's basename (`scripts/qa/run_all.sh`) and with a glued `-m` removed (`-mpytest`). Whole words only, so `pytester` does not count. This is the rule that catches `unbuffer pytest | tail`, `sleep 1 & pytest | tail` and `bash -euo pipefail -c 'pytest' | tail`, whatever wrapper is in front. The deny names the command and says the guard could not tell which pipe it feeds; if it feeds none, run it as a separate command.
- A prose-shaped match, and a pipe fed by a whole loop, `if`, `case` or group.
- Every pipe in a command is judged, and a single `&` ends a statement. An unknown pipe never excuses another one: `docker ps | tail -1 && pytest | tail -5` denies on `pytest`.

An expensive command that is on no list (a project script such as `run_all.sh`) now only warns. Add it to `extra_blacklist` to keep the deny. An entry is matched against every word of the command and its basename, so `'^run_all\.sh(\s|$)'` covers `./scripts/qa/run_all.sh`, `bash scripts/qa/run_all.sh` and `timeout 600 scripts/qa/run_all.sh`. End an entry with `(\s|$)` rather than `\b` if a longer file name (`run_all.sh.bak`) must not match.

`write_protected_paths`: when a command cannot be read (unclosed quote, brace group past the spelling cap, text too deep or large to scan) and no listed path is literally named in it, the command is now allowed with an advisory. A protected-path glob with no literal part (such as `**`) used to turn this case into a deny.

An awk program that writes is handled by where it writes:

- **Only to string literals** (`print > "/tmp/out"`, `print | "sort"`): its file operands are only read. It is judged by its program text, as before.
- **To a computed destination** (`print > FILENAME`, `> $1`, `| cmd`, `system()`): it denies when a file operand names a listed path (`awk '{print > FILENAME}' protected/x`). An operand built from an expansion (`$PWD/protected/x`, `~+/protected/x`) counts when its literal part names a listed path or directory, and always counts under a glob with no literal part.
- **Run inside a listed directory** (`cd protected && awk '{print > $1}' ...`): it denies whatever its destination.
- **Otherwise**: it is allowed with the advisory, unless the program names a listed path.

Wherever a listed path IS named in the command, an unknown verb or unreadable text still denies. If you relied on that deny as a backstop, list a literal path to keep it.
