"""Functional tests against the REAL Hermes Agent Mattermost adapter.

These are the regressions the unit tests cannot see: upstream interface
renames, method signature changes, and — worst of all — the v0.20.2 plugin
loader purging the patched module from sys.modules on every boot.
"""

import importlib
import sys

import pytest

from helpers import HERMES_AGENT_ROOT  # noqa: F401  (re-export for tests)

PKG_NAME = "hermes_plugins.mattermost_platform"
MODULE_NAME = PKG_NAME + ".adapter"


def test_register_against_real_adapter(plugin, real_env):
    plugin.register(None)
    adapter = sys.modules.get(MODULE_NAME)
    assert adapter is not None, "plugin could not load the real adapter"

    # Props patch actually neutralises the upstream injection.
    assert adapter._hermes_kchat_props_patched is True
    assert getattr(adapter._with_mentions_disabled, "_hermes_kchat_noop", False)
    out = adapter._with_mentions_disabled({"channel_id": "ch1", "message": "hi"})
    assert "props" not in out
    assert "disable_mentions" not in (out.get("props") or {})

    # Polling patches land on the real class.
    cls = adapter.MattermostAdapter
    assert cls._hermes_kchat_polling_patched is True
    assert cls._hermes_kchat_ws_connect_patched is True
    assert cls._ws_loop.__name__ != "_ws_loop"  # replaced
    assert cls._ws_connect_and_listen.__name__ != "_ws_connect_and_listen"
    assert callable(cls._ws_loop) and callable(cls._ws_connect_and_listen)


def test_loader_eviction_survival(plugin, real_env):
    """The v1.0.2 regression test: patches survive a purge + re-import.

    Simulates exactly what the v0.20.2 plugin loader does: it evicts the
    platform slug from sys.modules BEFORE loading it, then imports a fresh
    copy. Without the meta-path finder, the re-import would come back
    pristine and the kChat patches would silently vanish.
    """
    plugin.register(None)
    original = sys.modules[MODULE_NAME]
    cls = original.MattermostAdapter
    assert cls._hermes_kchat_polling_patched is True
    orig_loop = cls._ws_loop
    orig_connect = cls._ws_connect_and_listen

    # --- simulate the loader purge ---
    sys.modules.pop(MODULE_NAME, None)
    sys.modules.pop(PKG_NAME, None)
    reimported = importlib.import_module(MODULE_NAME)

    assert reimported is not original, "re-import returned the cached module"
    # Finder must have re-applied the patches on the fresh module.
    assert reimported._hermes_kchat_props_patched is True
    fresh_cls = reimported.MattermostAdapter
    assert fresh_cls._hermes_kchat_polling_patched is True
    assert fresh_cls._hermes_kchat_ws_connect_patched is True
    assert fresh_cls._ws_loop is not orig_loop
    assert fresh_cls._ws_connect_and_listen is not orig_connect

    # And the fresh patched methods still behave: noop on props.
    out = reimported._with_mentions_disabled({"channel_id": "ch1"})
    assert "props" not in out


def test_fails_if_upstream_interface_vanishes(plugin, real_env):
    """Early warning for upstream drift: the symbols we depend on."""
    plugin.register(None)
    adapter = sys.modules.get(MODULE_NAME)
    assert adapter is not None, "plugin could not load the real adapter"
    # Module-level symbols the plugin patches or reads.
    for name in ("_with_mentions_disabled", "MattermostAdapter"):
        assert hasattr(adapter, name), f"upstream adapter lost module symbol {name}"
    # Class-level methods the plugin wraps.
    cls = adapter.MattermostAdapter
    for name in ("_ws_loop", "_ws_connect_and_listen", "_handle_ws_event", "_api_get"):
        assert hasattr(cls, name), f"upstream adapter lost class method {name}"


def test_adapter_imports_from_resolved_checkout(real_env):
    """Sanity: the fixture really resolves the checked-out hermes-agent."""
    assert HERMES_AGENT_ROOT is not None
    marker = real_env / "plugins" / "platforms" / "mattermost" / "adapter.py"
    assert marker.is_file()
    # Prove the symlink actually points at the resolved checkout.
    assert marker.resolve().is_file()