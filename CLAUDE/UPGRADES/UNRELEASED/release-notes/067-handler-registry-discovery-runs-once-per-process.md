# Callout: handler registry discovery runs once per daemon process

**Plan**: 00495
**Audience**: client projects

`HandlerRegistry.discover` imports and inspects every handler module. The daemon start ran it twice, once inside the config model's handler-dependency validation and once in the controller (four times before the config is parsed once, see the config-parse callout). The result for a package is now kept for the life of the process, and later registries take it instead of scanning the package again.

The measured saving is small: with the handler modules already imported, a repeated scan cost about 6 ms; nearly all the cost of discovery is the first scan's imports, which cannot be skipped. The change removes redundant work and has no effect on which handlers are found, how they are configured or what they do. A package that fails to import is not remembered, so it is retried.
