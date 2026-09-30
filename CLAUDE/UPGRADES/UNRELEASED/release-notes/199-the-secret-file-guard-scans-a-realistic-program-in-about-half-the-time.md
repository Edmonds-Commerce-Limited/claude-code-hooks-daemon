# Callout: the secret file guard scans a large program in about half the time

**Plan**: 00474
**Audience**: operators

`secret_file_guard` spent most of its CPU on a large, ordinary Python heredoc (hundreds of dict and f-string lines) running a glob-intersection grid for every bracket-expanded spelling of every token against every protected pattern. A spelling with no wildcard of its own is now answered by one cached regex match, and two quadratic rescans (the brace-word span lookup and the separator scan of the command splitter) are linear. Verdicts are unchanged. On the field-shaped test program the scan costs roughly half the CPU it did, so a slow or loaded host is much less likely to cross the guard's 5 s deadline and deny a safe write.
