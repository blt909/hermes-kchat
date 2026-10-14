"""Shared test constants (imported by conftest.py and tests)."""

# Namespace upstream gives a bundled platform plugin. hermes-agent >= 0.22
# derives it from the plugin's PATH-derived manifest key ("platforms/mattermost"
# -> "platforms__mattermost"); before the 2026-10-09 update it used the manifest
# name ("mattermost-platform" -> "mattermost_platform"). The plugin must work
# under both, so tests exercise both.
PKG_NAME = "hermes_plugins.mattermost_platform"
MODULE_NAME = PKG_NAME + ".adapter"
SLUG_PKG_NAME = "hermes_plugins.platforms__mattermost"
SLUG_MODULE_NAME = SLUG_PKG_NAME + ".adapter"

FAKE_ADAPTER_SRC = '''\
"""Minimal stand-in for Hermes Agent's Mattermost adapter (test double)."""

def _with_mentions_disabled(payload):
    payload = dict(payload)
    payload["props"] = {"disable_mentions": True}
    return payload


class MattermostAdapter:
    async def _ws_loop(self):
        return "original_ws_loop"

    async def _ws_connect_and_listen(self):
        return "original_ws_connect"

    async def _handle_ws_event(self, event):
        return "handled"
'''

# Fake adapter missing _with_mentions_disabled (upstream may drop it).
FAKE_NO_PROPS_SRC = '''\
"""Fake adapter WITHOUT _with_mentions_disabled."""


class MattermostAdapter:
    async def _ws_loop(self):
        return "original_ws_loop"

    async def _ws_connect_and_listen(self):
        return "original_ws_connect"
'''

# Fake adapter missing MattermostAdapter (class renamed upstream).
FAKE_NO_CLASS_SRC = '''\
"""Fake adapter WITHOUT MattermostAdapter."""


def _with_mentions_disabled(payload):
    payload = dict(payload)
    payload["props"] = {"disable_mentions": True}
    return payload
'''

# --- Adapter resolution (shared by unit and functional tests) ---

import os  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

_HERMES_HOME = os.environ.get("HERMES_HOME")
_CANDIDATES = []
if _HERMES_HOME:
    _CANDIDATES.append(Path(_HERMES_HOME) / "hermes-agent")
_CANDIDATES.append(Path.home() / ".hermes" / "hermes-agent")

HERMES_AGENT_ROOT = next(
    (
        p
        for p in _CANDIDATES
        if p is not None
        and (p / "plugins" / "platforms" / "mattermost" / "adapter.py").is_file()
    ),
    None,
)


def adapter_file(adapter_dir=None):
    """Resolved path of the adapter.py under test (real checkout or fake env)."""
    if adapter_dir is not None:
        return (Path(adapter_dir) / "adapter.py").resolve()
    for root in _CANDIDATES:
        candidate = root / "plugins" / "platforms" / "mattermost" / "adapter.py"
        if candidate.is_file():
            return candidate.resolve()
    raise AssertionError("no hermes-agent Mattermost adapter.py resolvable")


def loaded_adapters(adapter_dir=None):
    """``[(name, module)]`` for every imported copy of that adapter.py.

    Namespace-agnostic — that is the point of v1.0.9: the loader's module name
    is upstream's business, the plugin locates the adapter by file. Patched
    copies come first.
    """
    target = adapter_file(adapter_dir)
    found = []
    for name, mod in list(sys.modules.items()):
        if mod is None:
            continue
        origin = getattr(mod, "__file__", None)
        if not origin:
            continue
        try:
            if Path(origin).resolve() != target:
                continue
        except OSError:  # pragma: no cover - defensive
            continue
        found.append((name, mod))
    found.sort(key=lambda pair: not getattr(pair[1], "_hermes_kchat_props_patched", False))
    return found


def adapter_module(adapter_dir=None):
    """The (patched) adapter module loaded from that adapter.py."""
    found = loaded_adapters(adapter_dir)
    assert found, "adapter module not loaded from %s" % adapter_file(adapter_dir)
    return found[0][1]
