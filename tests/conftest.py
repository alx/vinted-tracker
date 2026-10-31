"""Pytest setup.

`poller` imports `vinted` at module import time. The real `vinted-api-kit` is
installed in CI, but unit tests never touch the network (they stub
`fetch_items` and the senders), so if the real package isn't importable we
install a minimal stub to satisfy `import poller`.
"""

import sys
import types


def _install_vinted_stub() -> None:
    try:
        import vinted  # noqa: F401

        return  # real package present — nothing to do
    except Exception:
        pass

    mod = types.ModuleType("vinted")

    class VintedError(Exception):
        pass

    class VintedRateLimitError(VintedError):
        pass

    class VintedClient:  # never instantiated by unit tests
        pass

    mod.VintedError = VintedError
    mod.VintedRateLimitError = VintedRateLimitError
    mod.VintedClient = VintedClient
    sys.modules["vinted"] = mod


_install_vinted_stub()
