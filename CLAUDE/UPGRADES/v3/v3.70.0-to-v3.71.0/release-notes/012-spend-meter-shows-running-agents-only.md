# Callout: the spend-meter status segment shows only the sub-agents running now

**Plan**: 00545
**Audience**: everyone

The `Σ⚙ 89.7M tok-eq · 1 live (1 sonnet) · max 127k · 54 unmeasured` segment is replaced by `⚙ 1 agent (sonnet) · 127k`, which appears only while sub-agents are running (`⚙ 2 agents (opus, sonnet) · 140k`) and is absent otherwise. The cumulative `tok-eq` total only ever grew and had no reference point, so it is gone from the bar; `hooks-daemon spend` and the ledger are unchanged. A measurement-failure count is appended in red (`2 unmeasured`) only when it is non-zero, and shows alone when no agent is running. It counts a missing or unreadable transcript, a usage-less tail in a transcript that has usage, and a handler error; an agent that has not written its first reply yet is never counted. Run `hooks-daemon status-line-explained` for the text.
