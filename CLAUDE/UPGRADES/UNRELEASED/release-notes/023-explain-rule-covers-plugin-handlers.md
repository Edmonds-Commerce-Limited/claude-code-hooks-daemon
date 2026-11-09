# Callout: explain-rule and explain-handler now resolve handlers loaded through `plugins:`

**Plan**: 00589
**Audience**: client projects

(GitHub #171.) Every deny ends with "Full detail: `hooks-daemon explain-rule <ID>`", but for a rule declared by a handler registered under the `plugins:` config section the command answered `unknown rule ID`; `explain-handler <name>` had the same gap. The lookup read the library handlers and the `project_handlers:` directory and never the plugin loader. It now also loads the `plugins:` entries through the same `PluginLoader` the daemon uses, so a plugin handler's rules and docs resolve, and a disabled entry contributes nothing. A plugin that fails to load is logged and left out; library and project lookups still answer. The block-report fingerprint index is unchanged (library handlers only).
