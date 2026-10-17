# rfix-yaml-remote-docs: block-nesting segfault in the YAML loader, and silent remote-docs refresh failures

## Assumptions

- Part 2's release-note rule applies as the lead stated: the defect shipped, so a new callout was added (082). Part 1 followed the common rule: no new callout, existing callout 068 edited so it stays true.
- The block-depth bound is a text prefix bound (below), chosen over a real depth parse because it is one regex pass and over-estimates only (a false route to the pure-Python loader costs speed, never correctness).

## Part 1: block nesting reached libyaml (reviewer F D2)

Red, before the fix (`tests/unit/config/test_yaml_loading.py`, child process):

- `"- " * 100000 + "x"` and `"? " * 100000 + "x"`: `AssertionError: exit -11` (SIGSEGV in the child, pytest survived).
- 1001-deep indented mapping: `assert 0 == 1` (the pure-Python loader was never selected).

Fix (`src/claude_code_hooks_daemon/config/yaml_loading.py`): block depth cannot exceed the longest run of indentation and `-`/`?`/`:` characters leading a line, since each level starts at least one column right of its parent. `_DEEP_LINE_PREFIX` matches a line (after `\n`, `\r`, NEL, LS or PS, or at the start) that opens with more than `C_LOADER_MAX_OPEN_BRACKETS` of those characters; such a document, like one with too many brackets, goes to `yaml.SafeLoader` and raises `RecursionError` (reported as ValueError by `Config.load`). Ordinary configs stay on the C loader (`test_an_ordinary_config_stays_on_the_c_loader` passes).

Start-up budget (`scripts/release/check_startup_budget.py`, worktree venv, median CPU of 5): before 0.84 s (0.87, 0.84, 0.95, 0.83, 0.79), after 0.82 s (0.82, 0.76, 0.82, 0.89, 0.86). No change.

Tests added: three child-process rows (inline `- `, inline `? `, mixed with brackets), deep indentation routing, and indicator-run routing across `\n`, `\r` and `\r\n`. The deep-indentation test expects `RecursionError` from the pure-Python loader at 1001 levels, which is the intended outcome.

Callout 068 edited: one sentence saying a config nested past libyaml's stack is parsed by the pure-Python loader and reported invalid.

Limit: the 30,000-level indentation form itself (about 450 MB of text) was not run; the bound is argued from the YAML column rule and tested at the routing threshold.

## Part 2: remote-docs refresh failures (ledger N478)

Race, proved. With `agent-browser-lite-headless`, fifteen back-to-back `read https://example.com/ --json` each followed by `close --all` (what `fetchers._close_session` did): 7 of 15 failed, repeatably, with `{"code":"outcome_unknown","error":"Invalid response: EOF while parsing a value ... the command reached the daemon but no response came back"}`. `close` reports success while the session is still listed for a moment afterwards (`session list` showed it after `✓ Browser closed`), so the next read reaches the dying daemon. The same loop with one named session per read (`read ... --session S`, `close --session S`): 0 of 15 failed. Six earlier sequential reads had passed, so the race is intermittent. `close --all` also ends other agents' browsers.

Red: eight new or changed tests failed before the fix (four store rows, three fetcher rows, one CLI row).

Fix:

- `remote_docs/fetchers.py`: each `agent_browser_fetch` read gets its own session name (`hooks-daemon-remote-docs-<pid>-<8 hex>`) passed as `--session`, and `_close_session` closes only that session. No `close --all`.
- `remote_docs/store.py`: `refresh_document` retries a failed fetch once after `_RETRY_DELAY_SECONDS` (2.0, `sleep` injectable) and takes `on_failure`, which receives the cause of a final failure (fetch error, or the write error).
- `daemon/cli.py` `_remote_docs_refresh`: prints `  <path>: <cause>` under `<path>: failed`.

Tests changed: `test_it_asks_for_json_so_the_metadata_is_available` now compares the first four argv items (the read gained `--session <name>` after them); `test_it_closes_the_session_it_opened` and `test_the_session_is_closed_even_when_the_fetch_fails` previously asserted the literal `close --all` argv and now assert the named-session close. Intent kept (a session is closed, also on failure). New: never `--all`, one session per read, retry once and bounded, cause reported, recovered fetch reports no failure, CLI prints the cause.

Callout added: `CLAUDE/UPGRADES/UNRELEASED/release-notes/082-remote-docs-refresh-explains-and-retries-failures.md`.

Checked for the same shape: `grep` of `src` for other `close --all` uses and other `refresh_document` callers found only the CLI path above.

Targeted pytest: `tests/unit/remote_docs` and `tests/unit/config/test_yaml_loading.py`, 308 passed.
