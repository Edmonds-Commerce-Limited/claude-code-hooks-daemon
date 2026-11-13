# Callout: the declared dependency floors now match what the daemon imports (jsonschema 4.18 or newer)

**Plan**: 00474
**Audience**: client projects

The daemon imports `referencing` (schema validation) and `pydantic_core` (config error reporting) directly, but declared neither, and its `jsonschema>=4.0` floor admitted releases that do not depend on `referencing` at all. The package now requires `jsonschema>=4.18`, `referencing>=0.28.4` and `pydantic-core>=2.14`. A client environment already on current releases changes nothing; one pinned to an older jsonschema is upgraded on the next install or upgrade.
