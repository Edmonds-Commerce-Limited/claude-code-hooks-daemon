# Callout: the symbol-lookup guard no longer mistakes a grep option value for a searched file

**Plan**: 00474
**Audience**: client projects

A `grep` that filters another command's output was still treated as a symbol lookup when it carried an option that takes a value, such as `-A 3`, `-m 2` or `-e PATTERN`, because the value was read as a file name. The guard now knows which options consume a value, so those output filters are left alone, while a grep that really names a file is still judged.
