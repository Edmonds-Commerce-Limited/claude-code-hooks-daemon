# Callout: the ccy supervisor no longer types into a focused sub-agent

**Plan**: 00537
**Audience**: operators

The ccy supervisor used to type its `continue`, notices, `/compact`, model switch, abandoned-box Enter and restart `/exit` into whichever thread had focus. It now holds every one of those sends after you press a bare Up or Down arrow, because that key may have moved focus into the sub-agent panel or opened a sub-agent's transcript. Nothing is typed until you press Esc. While a send is held, the status line shows "supervisor holding: focus may be on a sub-agent; press Esc to return to the main thread", and `decision.log` records which send is waiting. The banner grows louder after the first escalation bound, which is set with the new `CCY_FOCUS_HOLD_ESCALATE_SECONDS` option (default `300,900`). The hold has no off switch, and it starts working at the next ccy relaunch. (reported as issue #125)
