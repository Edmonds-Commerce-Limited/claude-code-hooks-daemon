# Callout: the prompt-cache status segment is now compact colour-coded chips

**Plan**: 00452
**Audience**: operators

The prompt-cache segment used to be a run of text, `⚡ 99% 1h ⚠EXPIRING 4m sub 87% 5m total 97%`. It is now `⚡ main|⑂|Σ`: one background-coloured chip for the main thread, and, once a sub-agent has run, one for the sub-agents (`⑂`) and one for the whole session (`Σ`). Each chip is coloured by its own cache hit ratio, using the same chip colours as the context and usage segments: green at 90% or more, yellow from 75%, orange from 50%, red below that. A healthy chip is its label alone, so a good session is just `⚡ main`; a chip that is not green adds what is worth reading, as in `main 82% 1h`, `⑂ 62% 5m` or `Σ 70%`.

A high ratio is good, so the thresholds run the opposite way from the usage segment's. The main chip also reflects the cache's state, and the worse of ratio and state wins: a cold cache is a red `❄ 509k` (the tokens the next request pays to rebuild it), a cache in the tail of its TTL is at least yellow with `⏳4m`, and a cache rebuilt in the last few minutes is at least yellow with `↻ <cause>`. Nothing is shown before any caching has been observed. The thresholds are the options `healthy_pct`, `warn_pct` and `critical_pct` under `handlers.status_line.prompt_cache_indicator`.
