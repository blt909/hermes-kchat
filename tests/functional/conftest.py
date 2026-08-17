"""Functional-test fixtures: the REAL hermes-agent adapter, temp HERMES_HOME.

Requires a hermes-agent checkout. Resolution order:
  1. $HERMES_HOME/hermes-agent   (CI layout: workspace/hermes-home/hermes-agent)
  2. ~/.hermes/hermes-agent      (local dev layout)

If the gateway package is not importable the whole module skips — missing
environment must never turn CI red; only real regressions do.
"""

import sys

import pytest

from helpers import HERMES_AGENT_ROOT

if HERMES_AGENT_ROOT is not None and str(HERMES_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(HERMES_AGENT_ROOT))

try:
    import gateway.config  # noqa: F401  (hermes-agent's gateway package)
    _HAS_GATEWAY = True
except Exception:
    _HAS_GATEWAY = False

pytestmark = pytest.mark.skipif(
    not _HAS_GATEWAY,
    reason=(
        "hermes-agent (gateway package) not importable — set PYTHONPATH / "
        "HERMES_HOME to a hermes-agent checkout"
    ),
)


@pytest.fixture
def real_env(tmp_path, monkeypatch):
    """Temp HERMES_HOME with the real hermes-agent checkout reachable two ways:

    1. ``tmp_path/hermes-agent`` symlink — for the plugin's
       ``_load_adapter_module`` path resolution ($HERMES_HOME layout).
    2. A real ``tmp_path/hermes_plugins/mattermost_platform`` package on
       ``sys.path`` (adapter.py symlinked) — so a purge of the platform slug
       from ``sys.modules`` can be re-imported through the normal import
       machinery, exactly like the gateway's plugin loader does.
    """
    assert HERMES_AGENT_ROOT is not None
    link = tmp_path / "hermes-agent"
    link.symlink_to(HERMES_AGENT_ROOT, target_is_directory=True)

    pkg = tmp_path / "hermes_plugins" / "mattermost_platform"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "adapter.py").symlink_to(
        HERMES_AGENT_ROOT / "plugins" / "platforms" / "mattermost" / "adapter.py"
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.syspath_prepend(str(tmp_path))
    # Fresh import state so the plugin (re)loads the real adapter next time.
    sys.modules.pop("hermes_plugins.mattermost_platform.adapter", None)
    sys.modules.pop("hermes_plugins.mattermost_platform", None)
    return link