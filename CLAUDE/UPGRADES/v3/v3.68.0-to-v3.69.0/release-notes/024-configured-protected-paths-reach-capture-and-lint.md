# Callout: configured protected paths now reach payload capture and lint output

**Plan**: 00483
**Audience**: operators

Extra `protected_paths` set on `secret_file_guard` were ignored by payload capture and lint diagnostics when either ran before the daemon finished initialising; only the shipped defaults were protected for the life of the process. The configured paths are now picked up as soon as initialisation completes.
