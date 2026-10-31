"""Root pytest conftest.

Kept at the repo root so pytest (default "prepend" import mode) inserts this
directory onto ``sys.path`` before collecting tests. That makes the top-level
modules ``poller`` and ``ui`` importable from the test suite regardless of how
pytest is launched (``pytest`` or ``python -m pytest``) — CI runs the bare
``pytest`` entry point, which does not add the CWD to ``sys.path``.

The ``vinted`` module stub (used only when the real ``vinted-api-kit`` is not
installed) lives in ``tests/conftest.py``.
"""
