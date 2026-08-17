"""Shared test constants (imported by conftest.py and tests)."""

PKG_NAME = "hermes_plugins.mattermost_platform"
MODULE_NAME = PKG_NAME + ".adapter"

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

# --- Real hermes-agent checkout resolution (shared by functional tests) ---

import os
from pathlib import Path

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