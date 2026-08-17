"""Shared test fixtures for hermes-kchat.

The plugin's ``_load_adapter_module`` autodetects the Mattermost adapter
under ``$HERMES_HOME/hermes-agent/plugins/platforms/mattermost/`` (falling
back to ``~/.hermes/...``). Unit tests exploit that: each test plants a
minimal FAKE adapter in a temp HERMES_HOME, so the real installation is
never touched.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from helpers import (
    FAKE_ADAPTER_SRC,
    FAKE_NO_CLASS_SRC,
    FAKE_NO_PROPS_SRC,
    MODULE_NAME,
    PKG_NAME,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PATH = REPO_ROOT / "__init__.py"


@pytest.fixture(scope="session")
def plugin():
    """Load the plugin's __init__.py once (fresh module, one auto-patch finder)."""
    spec = importlib.util.spec_from_file_location("hermes_kchat_under_test", PLUGIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_adapter_env(plugin, tmp_path, monkeypatch):
    """Plant a fake adapter in a temp HERMES_HOME and point the plugin at it.

    Returns a callable: fake_adapter_env(source) -> adapter dir, so each test
    can choose which fake adapter to plant.
    """

    def _plant(source):
        pkg = tmp_path / "hermes-agent" / "plugins" / "platforms" / "mattermost"
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "adapter.py").write_text(source)
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        # Force a fresh load of the adapter from this tmp dir on next register().
        sys.modules.pop(MODULE_NAME, None)
        sys.modules.pop(PKG_NAME, None)
        return pkg

    return _plant