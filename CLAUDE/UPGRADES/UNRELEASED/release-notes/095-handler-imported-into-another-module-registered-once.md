### Fixed: a handler imported into another handler's module was registered twice

Handler discovery scanned every attribute of each handler module, so a handler
class imported by another handler (the owner-wait stop guard imports
`AutoContinueStopHandler`) was found in both modules. `auto-continue-stop` sat
on the Stop chain twice. A class is now registered only from the module that
defines it. No configuration change is needed.

The config validator's handler scan now applies the same defined-in-this-module rule as registration, so validation and registration can no longer disagree about which handlers exist.

A handler chain now logs an ERROR, once per name, when a second handler with the same name is added (the duplicate is still registered, never skipped), so a future duplicate registration is no longer silent.
