# Callout: tdd_enforcement finds the Maven/Gradle test source set

**Plan**: 00520
**Audience**: client projects

A Java or Kotlin file under `src/main/<lang>/<pkg>/` could never satisfy the TDD gate in a conventionally laid-out Maven or Gradle project: the gate searched `tests/...` mirrors but never the sibling `src/test/<lang>/<pkg>/<Name>Test.<ext>`. That location is now searched too, anchored on the first `src` segment, and it is listed in the deny message. The change is additive; every location searched before is still searched in the same order.
