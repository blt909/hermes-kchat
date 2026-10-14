"""Functional tests against the REAL Hermes Agent Mattermost adapter.

These are the regressions the unit tests cannot see: upstream interface
renames, method signature changes, the plugin loader purging the patched
module from sys.modules on every boot (v0.20.2 / v1.0.2), and the loader
renaming that module after a path-derived manifest key (2026-10-09 / v1.0.9).
"""

import importlib
import sys

import pytest

from helpers import HERMES_AGENT_ROOT, adapter_module  # noqa: F401  (re-export for tests)

LOADER_PKG_NAME = "hermes_plugins.platforms__mattermost"
LOADER_MODULE_NAME = LOADER_PKG_NAME + ".adapter"
LEGACY_PKG_NAME = "hermes_plugins.mattermost_platform"
LEGACY_MODULE_NAME = LEGACY_PKG_NAME + ".adapter"


def test_register_against_real_adapter(plugin, real_env):
    plugin.register(None)
    adapter = adapter_module()

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


def test_loader_path_derived_namespace_is_patched(plugin, real_env):
    """The 2026-10-09 regression: the live adapter must be the patched one.

    hermes-agent's loader names a bundled platform plugin after its
    path-derived manifest key, so the Mattermost adapter is imported as
    ``hermes_plugins.platforms__mattermost.adapter``. v1.0.8 had the older
    ``hermes_plugins.mattermost_platform.adapter`` hardcoded and therefore
    patched a second, unused module object: on the live gateway the native WS
    404 reconnect loop kept running (no inbound messages) and every outbound
    post kept the native ``props`` dict (HTTP 422 → cron delivery lost).
    """
    plugin.register(None)
    # The gateway's loader imports the platform package; its
    # ``from .adapter import register`` resolves through sys.modules to the
    # adapter module — the one that must carry the patches.
    importlib.import_module(LOADER_PKG_NAME)
    adapter = sys.modules[LOADER_MODULE_NAME]

    assert adapter is adapter_module(), "the live adapter namespace is unpatched"
    assert adapter._hermes_kchat_props_patched is True
    assert getattr(adapter._with_mentions_disabled, "_hermes_kchat_noop", False)
    cls = adapter.MattermostAdapter
    assert cls._hermes_kchat_polling_patched is True
    assert cls._hermes_kchat_ws_connect_patched is True
    assert cls._ws_loop.__name__ == "_ws_loop_patched"
    assert cls._ws_connect_and_listen.__name__ == "_ws_connect_and_listen_patched"

    # …and the patches are functional, not just flagged.
    out = adapter._with_mentions_disabled({"channel_id": "ch1"})
    assert "props" not in out


@pytest.mark.parametrize("pkg_name", [LOADER_PKG_NAME, LEGACY_PKG_NAME])
def test_loader_eviction_survival(plugin, real_env, pkg_name):
    """The v1.0.2 regression test: patches survive a purge + re-import.

    Simulates exactly what the plugin loader does: it evicts the platform slug
    from sys.modules BEFORE loading it, then imports a fresh copy. Without the
    meta-path finder, the re-import would come back pristine and the kChat
    patches would silently vanish — under whichever namespace the loader uses.
    """
    mod_name = pkg_name + ".adapter"
    plugin.register(None)
    original = importlib.import_module(mod_name)
    cls = original.MattermostAdapter
    assert cls._hermes_kchat_polling_patched is True
    orig_loop = cls._ws_loop
    orig_connect = cls._ws_connect_and_listen

    # --- simulate the loader purge ---
    sys.modules.pop(mod_name, None)
    sys.modules.pop(pkg_name, None)
    reimported = importlib.import_module(mod_name)

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


def test_other_platform_adapters_are_left_alone(plugin, real_env, tmp_path):
    """The finder must not wrap an unrelated platform's adapter."""
    plugin.register(None)
    target = sys.modules[LOADER_MODULE_NAME]

    # Never write inside the checkout: real_env is a symlink to it.
    foreign = tmp_path / "foreign" / "otherchat"
    foreign.mkdir(parents=True)
    (foreign / "__init__.py").write_text("")
    (foreign / "adapter.py").write_text("MARKER = 'foreign adapter'\n")

    import types
    from importlib import util as importlib_util

    spec = importlib_util.spec_from_file_location(
        "hermes_plugins.otherchat.adapter", foreign / "adapter.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib_util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
        assert not hasattr(mod, "_hermes_kchat_props_patched")
        assert mod.MARKER == "foreign adapter"
        assert isinstance(mod, types.ModuleType)
    finally:
        sys.modules.pop(spec.name, None)
    assert sys.modules[LOADER_MODULE_NAME] is target


def test_fails_if_upstream_interface_vanishes(plugin, real_env):
    """Early warning for upstream drift: the symbols we depend on."""
    plugin.register(None)
    adapter = adapter_module()
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
