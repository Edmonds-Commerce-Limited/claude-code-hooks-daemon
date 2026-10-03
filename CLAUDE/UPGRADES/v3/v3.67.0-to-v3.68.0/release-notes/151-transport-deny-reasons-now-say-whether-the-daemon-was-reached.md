# Callout: transport deny reasons now say whether the daemon was reached

**Plan**: 00466
**Audience**: operators

When `PreToolUse` is denied because no verdict came back, the reason now
says "Hooks daemon unreachable" only when the connection itself failed, and
"reached" only when it succeeded. A socket the client cannot open no longer
carries the fail-open "safety handlers are inactive" text or points at the
Skill tool, which is denied the same way. The relay names an expired budget
"timed out" instead of "Resource temporarily unavailable (os error 11)".
