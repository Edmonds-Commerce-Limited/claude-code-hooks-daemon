# Callout: health now reports a handler whose options were not applied

**Plan**: 00466
**Audience**: operators

If the daemon cannot collect a handler's configured options, it logs the
failure at error level with the handler's name. `hooks-daemon health` then
lists that handler under "Handler options" and exits non-zero. Before this, the
failure was logged at debug level only, so the handler quietly ran on its
defaults. The handler still runs on its defaults, and this is a daemon defect,
so please report it with the traceback from the log.
