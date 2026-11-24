# Callout: the human-approval check now verifies cites and judges a coordinator's sub-agents

**Plan**: 00634
**Audience**: operators

`human_approval_check` now checks a cited questions-room line with `teamchat verify <id> --room questions` (fedora-desktop issue 369). It replaces the placeholder that refused every cite. A cite passes only when the answer is one `verified` record for that exact id and team, in the questions room, from a declared human. Anything else refuses: a missing or extra key, a wrong type, an exit code outside the contract, a timeout, or oversized output. The line's text is never kept or logged. Event ids must now be `$` plus 43 characters of `[A-Za-z0-9_-]`. The contract is the one fedora-desktop's peer seat relayed, and has not yet been checked against a live teamchat.

A sub-agent of a seat that is declared coordinator is now judged as that seat, because a sub-agent can push or merge for the coordinator. Sub-agents of a worker, unreadable or seatless session are untouched.

Three binding switches are added, all off by default: `require_question`, `max_line_age_seconds` and `single_use_cites`.

Keep `mode: advise`. It only annotates and never denies.
