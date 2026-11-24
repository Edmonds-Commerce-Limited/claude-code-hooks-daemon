### Fixed: a handler imported into another handler's module was registered twice

Handler discovery scanned every attribute of each handler module, so a handler
class imported by another handler (the owner-wait stop guard imports
`AutoContinueStopHandler`) was found in both modules. `auto-continue-stop` sat
on the Stop chain twice. A class is now registered only from the module that
defines it. No configuration change is needed.
