## 22:18 · action · —   — Delivered and closed (GitHub #169)

Delivered and closed (GitHub #169). Fix `a0ac71f37`. The branch merged main in (`a94cce609`, plan commits only) and main fast-forwarded to it after targeted QA passed 42/42. The daemon restart committed regenerated guidance (`cf9c87da0`), and main CI run 42706023447 on that head is green. A live probe against the restarted daemon, `printf … | grep -v resolve_venv`, drew no deny and no advisory.

Review decision: the implementer chose never to judge `git grep`, with or without a ref, rather than add a second parser to tell a ref from a pathspec. Accepted, because `lsp_enforcement` steers and is not a safety control; the trade is recorded on the issue. A `grep -r` in a pipe stage is still judged, since it searches the working directory whatever is piped in.
