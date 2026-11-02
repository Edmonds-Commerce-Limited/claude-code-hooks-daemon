# Callout: the sub-agent context budget no longer doubles the context on a turn that used the advisor

**Plan**: 00474
**Issue**: #150
**Audience**: operators

On an assistant turn that used a server-side tool (the advisor), the transcript's top-level usage is the sum of the executor requests in `usage.iterations`. The context reader counted that sum, so a sub-agent at about 229k tokens was told it was at 456k, past the 300k soft budget, and handed off early.

Context is now read from the last `message` entry of `usage.iterations`; `advisor_message` entries are never counted. A turn without `iterations`, or with none of type `message`, is read from the top-level fields as before. The fix is in the shared reader, so `subagent_context_budget`, `resume_guard`, the session-load view and the spend ledger's context figures all get it. Spend totals (summed tokens) still use the top-level fields.

The soft advisory also stops saying "then stop" when `hard_tokens` is off: it now states that continuing is permitted and the handoff is advised, not required. With `hard_tokens` set the wording is unchanged.

Nothing to do on upgrade.
