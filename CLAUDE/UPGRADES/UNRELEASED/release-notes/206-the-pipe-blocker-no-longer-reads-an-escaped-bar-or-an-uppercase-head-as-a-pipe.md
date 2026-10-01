# Callout: the pipe blocker no longer reads an escaped bar or an uppercase `HEAD` as a pipe

**Plan**: 00474
**Audience**: operators

`pipe_blocker` matched `| tail` and `| head` case-insensitively and without regard to a backslash before the bar, so `grep -rn "HEAD:notes.txt\|rev:path" a/ b.md | cut -c1-200` was denied as a pipe to `head`, with the quoted pattern named as the producer. Inside double quotes `\|` is two literal characters, and unquoted it is one escaped character; neither is the pipe operator. The bar is now a pipe only when it is preceded by an even run of backslashes (`\\|` is an escaped backslash and a real pipe), and the consumer word is matched case-sensitively, because a command word is case-sensitive on Linux. Real pipes are unchanged: `pytest | head`, `pytest|head`, a pipe inside `$( )` or backticks within double quotes, and a real pipe that follows a quoted alternation are all still judged on their own producer. Expect one new allowance: `cmd | TAIL` and `cmd | Head` are no longer denied, since they run no `tail` or `head`.
