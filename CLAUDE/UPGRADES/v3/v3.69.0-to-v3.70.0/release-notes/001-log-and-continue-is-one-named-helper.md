# Callout: a deliberate log-and-continue is one named, reasoned helper

**Plan**: 00474
**Audience**: handler authors

The error-hiding audit now flags any `except` body that only logs and then continues, returns a fallback or passes, not just a lone inline log call. The one accepted form is `claude_code_hooks_daemon.utils.deliberate_swallow.log_and_continue(logger, exc, reason=...)`, whose required `reason` states why swallowing is correct. The daemon's own swallow sites were converted to it, so a failure that is deliberately skipped is now recorded with its reason and traceback. Project handlers that log and carry on should use the helper.
