# Callout: the Effort Source OK line reports what modelSettings actually holds

**Plan**: 00474
**Audience**: everyone

The Effort Source check passed with the text "per-model levels come from settings.json modelSettings" whenever nothing pinned effort, without reading `modelSettings`. With no `modelSettings` entries anywhere, that sentence was false. The check now reads `modelSettings` from the user, project and local settings files: it names each model ID that carries an `effortLevel` (and the file it came from), or, when none does, says that no model has an explicit effort level so each runs at its own default. An entry without an `effortLevel` key is not counted. A top-level `effortLevel` in the user file (not a pin, but the default for every model without an entry) is named too, so the text only says "its own default" when no such level applies. The verdict is unchanged (passed when nothing pins effort) and the check still recommends no level.
