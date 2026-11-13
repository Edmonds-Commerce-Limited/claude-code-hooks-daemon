# Callout: a skipped venv of unknown ownership no longer prints an interpreter-drift line on every run

**Plan**: 00474
**Audience**: client projects

When the venv scan passed over a legacy, un-slugged venv whose interpreter had drifted, it printed a warning on every command even though another venv was then used. That warning is now printed only when no venv turns out usable; a venv built for this checkout still warns at once.
