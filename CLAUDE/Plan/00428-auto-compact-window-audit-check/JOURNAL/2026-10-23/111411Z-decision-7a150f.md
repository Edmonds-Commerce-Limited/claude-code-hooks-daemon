## 11:14 · decision · —   — Autocompact backstop at 480k (supervisor red 400k + 20%)

Owner request: set a Claude Code autocompact safety net at the supervisor's compact threshold plus 20%, so that a
supervisor fault still ends in a compaction.

- Supervisor threshold: the ccy supervisor compacts when the context sidecar reads red. The default tiers
  (`src/claude_code_hooks_daemon/handlers/status_line/context_tiers.py`; the yaml override lines are commented out)
  put red at 40% on the 1M tier = 400k tokens. The prompt-compaction midpoint is 50% (500k) and critical is 60% (600k).
- Backstop: 400k x 1.2 = 480k. `"autoCompactWindow": 480000` added to the project `.claude/settings.json`.
  The patient red band (400k-480k, where the supervisor waits for an idle turn) is unchanged. Above 480k Claude Code
  compacts by itself.
- NOT YET IN EFFECT: the container environment sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW=600000`, and that variable beats
  every settings key. It is set nowhere in this repository or in `.claude/ccy/`, so it comes from the host launcher.
  The owner has to change it to 480000 there, or remove it. Until then sessions compact at 600k (1.5x).
- Settings tests (ssot drift, dogfood keys, permission sync, hook paths, hook registration): 115 passed.
