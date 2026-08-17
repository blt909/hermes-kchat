"""Unit tests: patch application and behaviour against a FAKE adapter."""

import asyncio
import json
import sys

import pytest

from helpers import FAKE_ADAPTER_SRC, FAKE_NO_CLASS_SRC, FAKE_NO_PROPS_SRC, MODULE_NAME


# ---------------------------------------------------------------------------
# The noop props patch — the payload must pass through untouched.
# ---------------------------------------------------------------------------


def test_noop_preserves_payload(plugin):
    payload = {"channel_id": "ch1", "message": "hello"}
    out = plugin._noop_with_mentions_disabled(payload)
    assert out == payload
    assert "props" not in out


def test_noop_preserves_existing_props(plugin):
    payload = {"channel_id": "ch1", "message": "hi", "props": {"custom": 1}}
    out = plugin._noop_with_mentions_disabled(payload)
    assert out is payload
    assert out["props"] == {"custom": 1}


def test_noop_does_not_inject_disable_mentions(plugin):
    out = plugin._noop_with_mentions_disabled({"channel_id": "ch1"})
    assert "disable_mentions" not in (out.get("props") or {})


# ---------------------------------------------------------------------------
# register() against a fake adapter
# ---------------------------------------------------------------------------


def test_register_applies_props_patch(plugin, fake_adapter_env):
    fake_adapter_env(FAKE_ADAPTER_SRC)
    plugin.register(None)
    adapter = sys.modules.get(MODULE_NAME)
    assert adapter is not None
    assert adapter._hermes_kchat_props_patched is True
    assert getattr(adapter._with_mentions_disabled, "_hermes_kchat_noop", False)


def test_register_applies_polling_patches(plugin, fake_adapter_env):
    fake_adapter_env(FAKE_ADAPTER_SRC)
    plugin.register(None)
    cls = sys.modules[MODULE_NAME].MattermostAdapter
    assert cls._hermes_kchat_polling_patched is True
    assert cls._hermes_kchat_ws_connect_patched is True
    assert cls._ws_loop.__name__ == "_ws_loop_patched"
    assert cls._ws_connect_and_listen.__name__ == "_ws_connect_and_listen_patched"


def test_register_idempotent(plugin, fake_adapter_env):
    fake_adapter_env(FAKE_ADAPTER_SRC)
    plugin.register(None)
    cls = sys.modules[MODULE_NAME].MattermostAdapter
    patched_loop = cls._ws_loop
    patched_connect = cls._ws_connect_and_listen
    adapter = sys.modules[MODULE_NAME]

    plugin.register(None)  # second register must be a no-op

    assert sys.modules[MODULE_NAME] is adapter
    assert cls._ws_loop is patched_loop  # not wrapped a second time
    assert cls._ws_connect_and_listen is patched_connect


def test_register_fail_open_missing_props(plugin, fake_adapter_env):
    fake_adapter_env(FAKE_NO_PROPS_SRC)
    plugin.register(None)  # must not raise
    adapter = sys.modules[MODULE_NAME]
    # props patch skipped quietly; polling still armed on the class
    assert not getattr(adapter, "_hermes_kchat_props_patched", False)
    assert adapter.MattermostAdapter._hermes_kchat_polling_patched is True


def test_register_fail_open_missing_class(plugin, fake_adapter_env):
    fake_adapter_env(FAKE_NO_CLASS_SRC)
    plugin.register(None)  # must not raise
    adapter = sys.modules[MODULE_NAME]
    assert adapter._hermes_kchat_props_patched is True
    assert not getattr(adapter, "MattermostAdapter", None)


# ---------------------------------------------------------------------------
# Polling event shape — exactly what _handle_ws_event parses upstream.
# ---------------------------------------------------------------------------


def test_polling_event_shape(plugin, fake_adapter_env, monkeypatch):
    fake_adapter_env(FAKE_ADAPTER_SRC)
    plugin.register(None)

    events = []

    class FakeAdapter:
        _closing = False

        def __init__(self):
            self.calls = []

        async def _api_get(self, path):
            self.calls.append(path)
            if path == "users/me/channels":
                return [{"id": "ch1", "type": "O"}]
            if path == "channels/ch1/posts?per_page=1":
                return {"posts": {"p0": {"id": "p0", "create_at": 1000}}}
            if "channels/ch1/posts?since=1000&per_page=50" in path:
                return {
                    "order": ["p1"],
                    "posts": {
                        "p1": {
                            "id": "p1",
                            "create_at": 1500,
                            "message": "nouveau message",
                            "user_id": "u2",
                            "type": "",
                            "channel_id": "ch1",
                        }
                    },
                }
            return {"posts": {}, "order": []}

        async def _handle_ws_event(self, event):
            events.append(event)

    async def _sleep_immediately_cancelled(*_a, **_k):
        raise asyncio.CancelledError()

    monkeypatch.setattr(plugin.asyncio, "sleep", _sleep_immediately_cancelled)

    fake = FakeAdapter()
    asyncio.run(plugin._polling_fallback_loop(fake))  # one cycle, then cancel

    # Anchor post p0 is used for `since` only; p1 is the only event fed.
    assert len(events) == 1
    ev = events[0]
    assert ev["event"] == "posted"
    assert json.loads(ev["data"]["post"])["id"] == "p1"
    assert ev["data"]["channel_type"] == "O"
    assert ev["data"]["sender_name"] == ""
    assert fake.calls[0] == "users/me/channels"
    assert "since=1000" in fake.calls[-1]