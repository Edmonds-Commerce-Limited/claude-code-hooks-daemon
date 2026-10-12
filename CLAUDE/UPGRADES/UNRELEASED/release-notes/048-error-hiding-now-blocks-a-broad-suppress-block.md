# Callout: error hiding now blocks a `suppress()` that names Exception or BaseException

**Plan**: 00474
**Audience**: client projects

`error_hiding_blocker` blocked `except Exception: pass` but allowed `with contextlib.suppress(Exception):`, which discards every error in the same way. A Python `Write`/`Edit` is now denied when a `suppress(...)` call (through `contextlib.suppress` or a bare imported `suppress`) names `Exception` or `BaseException` as a whole name, alone or among other exceptions (`suppress(OSError, Exception)`). A narrow `suppress(OSError)` names the exception it accepts and stays allowed, as do `ExceptionGroup`, `MyException` and `asyncio.CancelledError`. The deny says to suppress only the specific exception you expect, or handle it. The matching is textual, so a string literal that holds the broad form is judged like code; a trailing comment that mentions it is not. The `audit_error_hiding.py` QA audit reports the same form as the new `broad-suppress` rule. A client whose code already uses the broad form is not affected until it next writes that code.
