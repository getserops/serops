"""
SerOps Enterprise.

Everything under this directory is licensed under the SerOps Enterprise
License (ee/LICENSE), not the AGPL-3.0 that covers the rest of the
repository. SerOps runs as the complete Community edition without it.

Rules for code in here:

* Community code never imports ``ee``. Enterprise code may import Community
  code. CI runs the whole test suite with this directory deleted.
* Community code asks ``Utils.edition.has_feature(code)``; this app
  registers the provider that answers it (apps.py).
* Enterprise features only add to Community. Without a valid license key
  they are hidden, and when a key expires they switch off without touching
  data or blocking anything else.
"""
