# Callout: a handler imported into another handler's module is registered once

**Plan**: 00636
**Audience**: handler authors

Handler discovery scanned every attribute of each handler module, so a handler class imported by another handler was found in both modules and registered twice. The owner-wait stop guard imports `AutoContinueStopHandler`, so `auto-continue-stop` sat on the Stop chain twice. A class is now registered only from the module that defines it. No configuration change is needed.

The config validator's handler scan applies the same defined-in-this-module rule, so validation and registration can no longer disagree about which handlers exist.

A handler chain now logs an ERROR, once per name, when a second handler with the same name is added. The duplicate is still registered, never skipped, so a future duplicate registration is no longer silent.
