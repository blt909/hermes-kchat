# hermes-kchat — compatibility patches for Hermes Agent's Mattermost adapter
# Copyright (c) 2026 Sébastien Coget (blt909)
# SPDX-License-Identifier: MIT
#
# This plugin patches, at runtime, the bundled Mattermost adapter of Hermes
# Agent (https://github.com/NousResearch/hermes-agent — MIT License,
# Copyright (c) 2025 Nous Research). It contains no copied code from that
# project; it is interface-coupled to the adapter's method names and to the
# Mattermost WebSocket event shape. See NOTICE.md for full attribution.
"""Make the Mattermost adapter compatible with Infomaniak kChat.

kChat (Infomaniak's Mattermost) has two incompatibilities with the bundled
adapter:

1. Post ``props`` validation. kChat validates ``props`` as a JSON array and
   rejects the standard object form with HTTP 422 (\"The props must be an
   array\"). The bundled adapter unconditionally injects
   ``props={\"disable_mentions\": true}`` on every outbound post, so ALL posts
   fail on kChat — cron delivery included. We neutralise that injection.

2. WebSocket support. kChat does not expose ``/api/v4/websocket`` (HTTP 404
   on connect), so the adapter's WebSocket listener can never attach and its
   reconnect loop spams ``Mattermost WS error: 404`` forever. Inbound
   messages (DMs, @mentions) are never received. We add a REST polling
   fallback: when the WebSocket handshake fails with 404, we switch to
   polling ``/api/v4/channels/{id}/posts?since=`` every 30 seconds and feed
   the posts through the exact same ``_handle_ws_event`` → ``handle_message``
   pipeline the WebSocket would have used (mention gating, dedup, file
   download, thread resolution all preserved).

Both patches are idempotent and fail open: if upstream fixes either issue,
the corresponding patch detects it and leaves the module untouched.

Because this plugin lives in ``~/.hermes/plugins/`` (outside the git repo),
a ``hermes update`` that reverts or changes the bundled adapter cannot
remove it — the patches re-apply on the next gateway start.

v1.0.1: also patch ``_ws_connect_and_listen`` — the attribute is resolved on
every call (including from the native reconnect loop), so the fallback
engages even if ``register()`` runs after the instance's WS task was created.

v1.0.2: survive adapter re-import. The v0.20.2 plugin loader
(``_load_directory_module``) evicts stale ``sys.modules`` entries for a
platform slug BEFORE loading it. Because user plugins are loaded BEFORE
bundled platform plugins, the loader purged the very adapter module this
plugin had patched and re-imported a pristine copy — the patches silently
vanished every boot. A meta-path finder now re-applies the patches after
EVERY real import of the adapter module (named
``hermes_plugins.mattermost_platform.adapter`` at the time), so they survive
any loader order. All diagnostics logs are WARNING so the plugin's activity
is visible in gateway.log/errors.log.

v1.0.3: no runtime changes — repository tooling only. Adds the test suite
(unit + functional, incl. the loader-eviction regression test), GitHub
Actions CI (unit, functional against the README-pinned hermes-agent commit,
daily drift with auto-PR), and the update watcher.

v1.0.4: no runtime changes — advance the tested-against pin to
ab173e26d2aa0300f22f5a5944c0284d732cfa8f (hermes-agent v0.20.4) after the
2026-08-19 `hermes update`. Verified green (13/13 tests) and live on kChat
(polling fallback engaged in gateway logs).

v1.0.5: no runtime changes — advance the tested-against pin to
fc9cbc872d8050c22f1192b16bc5ff4aed471e10 (hermes-agent v2026.8.18+,
post-2026-08-21 update) after re-testing against the new adapter. Verified
green (13/13 tests), all patched interfaces present, and live on kChat
(WS 404 → REST polling fallback engaged in gateway logs after restart).

v1.0.6: no runtime changes — advance the tested-against pin to
aff5125f8edf5095aef5d3d79bbbb101c95b9413 (hermes-agent, after v2026.8.27,
post-2026-08-29 update) after re-testing against the new adapter. Verified
green (13/13 tests), all patched interfaces present, and live on kChat
(WS 404 → REST polling fallback engaged in gateway logs after restart).

v1.0.7: no runtime changes — advance the tested-against pin to
08b140d14e6c1d49f9b7ad02c9437fe940d54d65 (hermes-agent, after v2026.8.31,
post-2026-09-07 update) after re-testing against the new adapter. Verified
green (13/13 tests), all patched interfaces present, and live on kChat
(WS 404 → REST polling fallback engaged in gateway logs after restart).

v1.0.8: no runtime changes — advance the tested-against pin to
36842e639a178741b70c821e0f4cdd129cd0dfe3 (hermes-agent, after v2026.9.14,
post-2026-09-17 update) after re-testing against the new adapter. Verified
green (13/13 tests), all 6 patched interfaces present in the new adapter, and
live on kChat (WS 404 → REST polling fallback engaged in gateway logs after
restart).

v1.0.9: fix the module namespace. Upstream's plugin loader now names a
bundled platform plugin after its PATH-DERIVED manifest key, so the
Mattermost adapter is imported as
``hermes_plugins.platforms__mattermost.adapter`` (key ``platforms/mattermost``
→ slug) instead of ``hermes_plugins.mattermost_platform.adapter`` (the old
manifest-name-derived slug). v1.0.8 and earlier had that name hardcoded, so
from the 2026-10-09 update onward ``register()`` patched a second, unused
module object: the live adapter kept the native WS 404 reconnect loop (no
inbound messages, ~1300 log lines/day) and the native ``props`` dict (every
cron delivery to Mattermost → HTTP 422, falling back to standalone). The
adapter is now located by FILE (module ``__file__`` == bundled
``plugins/platforms/mattermost/adapter.py``) and the auto-patch finder
matches any ``hermes_plugins.*.adapter`` whose spec origin is that file, so
the plugin no longer depends on the namespace upstream picks. Module-name
candidates are derived from the plugin path for the pre-import case. Tested
against Hermes Agent c5fc0958b49f415041c7f356c8bdf9f914037e89 (v0.22.0).

v1.0.10: no runtime changes — advance the tested-against pin to
d923a5eb487a17c0a68801bba9ef0f56c81040a8 (hermes-agent v0.22.2, the first
release on the new v0.22.x versioning scheme; 2068 commits past the previous
pin). Re-verified against the new adapter: the offline replay probe passes
(patch applied in every namespace — platforms__mattermost,
mattermost_platform and the profile-scoped variant — with a synthetic 404
handing off to REST polling), 17/17 tests green, and the live gateway shows
REST polling armed with zero native WS 404 loop lines after restart.
"""

import asyncio
import importlib.abc
import json
import logging
import os
import sys
import time
import types
from importlib import util as _importlib_util
from pathlib import Path

log = logging.getLogger(__name__)

_NS_PARENT = "hermes_plugins"
# Namespace used before the path-derived manifest keys (hermes-agent <= 0.21).
_LEGACY_PKG_NAME = _NS_PARENT + ".mattermost_platform"
_LEGACY_MODULE_NAME = _LEGACY_PKG_NAME + ".adapter"
_POLL_INTERVAL_S = 30
_FINDER_INSTALLED = False


# ---------------------------------------------------------------------------
# Patch 1: mentions-disable props injection (kChat rejects dict props)
# ---------------------------------------------------------------------------


def _noop_with_mentions_disabled(payload):
    """Return the payload untouched.

    kChat rejects dict ``props`` with HTTP 422. Omitting ``props`` is valid
    on both standard Mattermost and kChat, so a no-op is the compatible
    behaviour.
    """
    return payload


# ---------------------------------------------------------------------------
# Patch 2: REST polling fallback when the WebSocket is unavailable (404)
# ---------------------------------------------------------------------------


async def _polling_fallback_loop(self, adapter_log=None):
    """Poll all channels the bot is in every _POLL_INTERVAL_S seconds.

    Feeds new posts into ``_handle_ws_event`` — the same pipeline the
    WebSocket listener uses — so mention gating, dedup, file downloads and
    thread resolution behave identically.
    """
    adapter_log = adapter_log or logging.getLogger(_LEGACY_MODULE_NAME)
    since_map = {}  # channel_id -> ms timestamp of last processed post

    async def _poll_once():
        channels = await self._api_get("users/me/channels")
        if not isinstance(channels, list):
            return
        now_ms = int(time.time() * 1000)
        for ch in channels:
            ch_id = ch.get("id")
            if not ch_id:
                continue
            ch_type = ch.get("type", "O")
            if ch_id in since_map:
                since = since_map[ch_id]
            else:
                # First cycle: anchor on the channel's most recent post's
                # create_at (server clock). The host clock can be skewed vs
                # the server (observed ~70s on kChat); using local time as
                # `since` would skip every post newer than the skew.
                anchor = await self._api_get(
                    f"channels/{ch_id}/posts?per_page=1"
                )
                a_posts = anchor.get("posts") or {}
                if a_posts:
                    since = max(
                        (p.get("create_at") or 0) for p in a_posts.values()
                    )
                else:
                    since = now_ms
            data = await self._api_get(
                f"channels/{ch_id}/posts?since={since}&per_page=50"
            )
            order = data.get("order") or []
            posts = data.get("posts") or {}
            max_create = since
            for pid in order:
                post = posts.get(pid)
                if not post:
                    continue
                create_at = post.get("create_at") or 0
                if create_at > max_create:
                    max_create = create_at
                # Reuse the exact WebSocket event shape the adapter parses.
                event = {
                    "event": "posted",
                    "data": {
                        "post": json.dumps(post),
                        "channel_type": ch_type,
                        "sender_name": "",
                    },
                }
                try:
                    await self._handle_ws_event(event)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    adapter_log.warning(
                        "Mattermost polling: error handling post %s: %s",
                        pid, exc,
                    )
            since_map[ch_id] = max_create + 1

    adapter_log.warning(
        "Mattermost: WebSocket unavailable — REST polling fallback active "
        "(%ds interval)",
        _POLL_INTERVAL_S,
    )
    while not self._closing:
        try:
            await _poll_once()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            adapter_log.warning("Mattermost polling error: %s", exc)
        try:
            await asyncio.sleep(_POLL_INTERVAL_S)
        except asyncio.CancelledError:
            return


def _make_ws_loop_polling_aware(adapter_cls, adapter_log=None):
    """Replace ``_ws_loop`` so a 404 handshake switches to REST polling.

    Any other failure delegates to the original loop (backoff, auth-stop).
    """
    if getattr(adapter_cls, "_hermes_kchat_polling_patched", False):
        return
    original_ws_loop = adapter_cls._ws_loop

    async def _ws_loop_patched(self):
        import aiohttp
        try:
            await self._ws_connect_and_listen()
        except asyncio.CancelledError:
            return
        except aiohttp.WSServerHandshakeError as exc:
            if getattr(exc, "status", None) == 404:
                # kChat: no WebSocket endpoint. Poll instead of retrying.
                await _polling_fallback_loop(self, adapter_log)
                return
        except Exception:
            pass  # any other failure → original reconnect loop
        await original_ws_loop(self)

    adapter_cls._ws_loop = _ws_loop_patched
    adapter_cls._hermes_kchat_polling_patched = True


def _make_ws_connect_polling_aware(adapter_cls, adapter_log=None):
    """Replace ``_ws_connect_and_listen`` so a 404 engages polling.

    Unlike the ``_ws_loop`` patch, this one is also effective when the
    plugin's ``register()`` runs *after* the instance's WebSocket task was
    created: the native loop resolves ``self._ws_connect_and_listen()`` on
    every reconnect attempt, so the next attempt hits the patched method,
    sees the 404, and hands control to the polling loop (which never
    returns until shutdown).
    """
    if getattr(adapter_cls, "_hermes_kchat_ws_connect_patched", False):
        return
    original = adapter_cls._ws_connect_and_listen
    adapter_log = adapter_log or logging.getLogger(_LEGACY_MODULE_NAME)

    async def _ws_connect_and_listen_patched(self):
        import aiohttp
        try:
            await original(self)
        except asyncio.CancelledError:
            raise
        except aiohttp.WSServerHandshakeError as exc:
            if getattr(exc, "status", None) == 404:
                adapter_log.warning(
                    "Mattermost: WS connect 404 (%s) — engaging REST polling "
                    "fallback (kChat compatibility plugin)",
                    exc,
                )
                await _polling_fallback_loop(self, adapter_log)
                return
            raise

    adapter_cls._ws_connect_and_listen = _ws_connect_and_listen_patched
    adapter_cls._hermes_kchat_ws_connect_patched = True


def _apply_adapter_patches(mod):
    """Apply all kChat patches to an adapter module (idempotent, fail-open)."""
    mod_name = getattr(mod, "__name__", _LEGACY_MODULE_NAME)
    adapter_log = logging.getLogger(mod_name)

    if not getattr(mod, "_hermes_kchat_props_patched", False):
        original = getattr(mod, "_with_mentions_disabled", None)
        if original is None:
            adapter_log.warning(
                "hermes-kchat: adapter has no _with_mentions_disabled; "
                "props patch skipped (upstream may have fixed it)"
            )
        elif getattr(original, "_hermes_kchat_noop", False):
            setattr(mod, "_hermes_kchat_props_patched", True)
        else:
            mod._with_mentions_disabled = _noop_with_mentions_disabled
            _noop_with_mentions_disabled._hermes_kchat_noop = True
            setattr(mod, "_hermes_kchat_props_patched", True)
            adapter_log.warning(
                "hermes-kchat: patched _with_mentions_disabled → no-op "
                "(kChat props-array compatibility)"
            )

    adapter_cls = getattr(mod, "MattermostAdapter", None)
    if adapter_cls is None:
        adapter_log.warning(
            "hermes-kchat: MattermostAdapter class not found; "
            "polling fallback NOT applied"
        )
        return

    _make_ws_loop_polling_aware(adapter_cls, adapter_log)
    _make_ws_connect_polling_aware(adapter_cls, adapter_log)
    adapter_log.warning(
        "hermes-kchat: polling fallback armed on %s (_ws_loop=%s, "
        "_ws_connect_and_listen=%s)",
        mod_name,
        adapter_cls._ws_loop.__name__,
        adapter_cls._ws_connect_and_listen.__name__,
    )


# ---------------------------------------------------------------------------
# Locating the adapter (v1.0.9)
#
# The plugin must not depend on the module NAME upstream gives the bundled
# Mattermost platform: hermes-agent's loader derives it from the plugin's
# path-based manifest key (``platforms/mattermost`` →
# ``hermes_plugins.platforms__mattermost``), and that scheme has already
# changed once (it used the manifest name before, giving
# ``hermes_plugins.mattermost_platform``). Everything below therefore keys off
# the adapter's FILE, and the meta-path finder matches on the spec's origin.
# ---------------------------------------------------------------------------


def _candidate_dirs():
    """Return likely locations of the bundled Mattermost adapter directory."""
    dirs = []
    env_home = os.environ.get("HERMES_HOME")
    if env_home:
        dirs.append(Path(env_home) / "hermes-agent" / "plugins" / "platforms" / "mattermost")
    dirs.append(Path.home() / ".hermes" / "hermes-agent" / "plugins" / "platforms" / "mattermost")
    return dirs


def _adapter_file():
    """Absolute path of the bundled Mattermost ``adapter.py``, or ``None``."""
    for pkg_dir in _candidate_dirs():
        candidate = pkg_dir / "adapter.py"
        if candidate.is_file():
            try:
                return candidate.resolve()
            except OSError:  # pragma: no cover - defensive
                return candidate
    return None


def _is_adapter_origin(origin, adapter_file=None):
    """True when a module/ spec ``origin`` is the bundled Mattermost adapter."""
    if not origin:
        return False
    adapter_file = adapter_file or _adapter_file()
    if adapter_file is None:
        return False
    try:
        return Path(origin).resolve() == adapter_file
    except OSError:  # pragma: no cover - defensive
        return False


def _slug_pkg_name(pkg_dir):
    """``<...>/plugins/platforms/mattermost`` → ``hermes_plugins.platforms__mattermost``.

    Mirrors the loader's ``manifest_key(...).replace("/", "__").replace("-", "_")``
    for a bundled platform plugin, whose key is its path below the plugins root.
    """
    pkg_dir = Path(pkg_dir)
    root = next((anc for anc in pkg_dir.parents if anc.name == "plugins"), None)
    try:
        rel = pkg_dir.relative_to(root).as_posix() if root is not None else pkg_dir.name
    except ValueError:  # pragma: no cover - defensive
        rel = pkg_dir.name
    return "%s.%s" % (_NS_PARENT, rel.replace("/", "__").replace("-", "_"))


def _candidate_pkg_names(pkg_dir=None):
    """Package prefixes the adapter may be importable under, likeliest first."""
    names = []
    if pkg_dir is not None:
        names.append(_slug_pkg_name(pkg_dir))
    names.append(_LEGACY_PKG_NAME)
    return list(dict.fromkeys(names))


def _loaded_adapter_modules(adapter_file=None):
    """Yield ``(name, module)`` for every imported copy of the bundled adapter.

    Located by ``__file__``, so a copy is found whatever namespace the loader
    chose for it.
    """
    adapter_file = adapter_file or _adapter_file()
    if adapter_file is None:
        return []
    found = []
    for name, mod in list(sys.modules.items()):
        if mod is None or not name.startswith(_NS_PARENT + "."):
            continue
        if _is_adapter_origin(getattr(mod, "__file__", None), adapter_file):
            found.append((name, mod))
    return found


def _load_adapter_module():
    """Return the bundled adapter module, importing it by path if needed.

    Order: an already-imported copy (whatever its namespace), then the file
    imported under the namespace the loader is expected to use, then under the
    legacy namespace. ``None`` when no adapter file exists.
    """
    adapter_file = _adapter_file()
    if adapter_file is None:
        return None

    for _name, mod in _loaded_adapter_modules(adapter_file):
        return mod

    pkg_dir = adapter_file.parent
    for pkg_name in _candidate_pkg_names(pkg_dir):
        mod_name = pkg_name + ".adapter"
        cached = sys.modules.get(mod_name)
        if cached is not None and _is_adapter_origin(
            getattr(cached, "__file__", None), adapter_file
        ):
            return cached

        # Ensure the namespace parent package exists so the gateway's later
        # ``from .adapter import register`` reuses this exact module instead
        # of re-importing the file.
        parent = sys.modules.get(pkg_name)
        if parent is None:
            parent = types.ModuleType(pkg_name)
            sys.modules[pkg_name] = parent
        parent.__path__ = [str(pkg_dir)]
        parent.__package__ = pkg_name

        spec = _importlib_util.spec_from_file_location(mod_name, adapter_file)
        if spec is None or spec.loader is None:
            continue
        mod = _importlib_util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:  # pragma: no cover - defensive
            log.warning(
                "hermes-kchat: failed to exec adapter from %s",
                adapter_file,
                exc_info=True,
            )
            sys.modules.pop(mod_name, None)
            continue
        if not _is_adapter_origin(getattr(mod, "__file__", None), adapter_file):
            continue
        return mod
    return None


# ---------------------------------------------------------------------------
# Auto re-patch on import (v1.0.2, file-based since v1.0.9)
#
# The plugin loader evicts sys.modules entries for a platform slug before
# loading it, and user plugins load BEFORE bundled platform plugins — so the
# adapter module this plugin patched gets purged and re-imported pristine on
# every boot. A meta-path finder intercepts the real import of the adapter and
# re-applies the patches right after the module executes, whatever the loader
# order and whatever name it gives the module.
# ---------------------------------------------------------------------------


class _AdapterAutoPatchLoader(importlib.abc.Loader):
    """Wrap the real adapter loader; re-apply patches after exec."""

    def __init__(self, original):
        self._orig = original

    def create_module(self, spec):
        if hasattr(self._orig, "create_module"):
            return self._orig.create_module(spec)
        return None  # default module creation

    def exec_module(self, module):
        self._orig.exec_module(module)
        try:
            _apply_adapter_patches(module)
        except Exception:
            logging.getLogger(getattr(module, "__name__", _LEGACY_MODULE_NAME)).warning(
                "hermes-kchat: auto re-patch after import failed",
                exc_info=True,
            )

    def __getattr__(self, name):
        # Forward any other loader API the import machinery may ask for.
        return getattr(self._orig, name)


class _AdapterAutoPatchFinder(importlib.abc.MetaPathFinder):
    """Intercept imports of the bundled Mattermost adapter to re-apply patches.

    Matched by FILE, not by module name: the loader names the module after the
    plugin's path-derived manifest key, a scheme that already changed once.
    """

    def find_spec(self, fullname, path=None, target=None):
        if not (fullname.startswith(_NS_PARENT + ".") and fullname.endswith(".adapter")):
            return None
        adapter_file = _adapter_file()
        if adapter_file is None:
            return None
        for finder in sys.meta_path:
            if finder is self:
                continue
            find_spec = getattr(finder, "find_spec", None)
            if find_spec is None:
                continue
            spec = find_spec(fullname, path, target)
            if spec is None:
                continue
            # Someone else's adapter (telegram, slack, …) — leave it alone.
            if not _is_adapter_origin(getattr(spec, "origin", None), adapter_file):
                return None
            if spec.loader is not None:
                spec.loader = _AdapterAutoPatchLoader(spec.loader)
            return spec
        return None


def _install_auto_patch_finder():
    """Install the meta-path finder once, at the front of sys.meta_path."""
    global _FINDER_INSTALLED
    if _FINDER_INSTALLED:
        return
    # Front of the chain so we can wrap the spec before PathFinder imports
    # the module outright.
    sys.meta_path.insert(0, _AdapterAutoPatchFinder())
    _FINDER_INSTALLED = True


def register(ctx):
    """Apply the kChat compatibility patches to the Mattermost adapter.

    Installs the auto re-patch import hook first (so patches survive the
    loader's later eviction+re-import of the platform module), then patches
    every already-imported copy of the adapter, then loads it by path if it
    was not imported yet.
    """
    del ctx  # unused; loading and patching the adapter is the whole job

    _install_auto_patch_finder()

    adapter_file = _adapter_file()
    if adapter_file is None:
        log.warning(
            "hermes-kchat: could not locate Mattermost adapter; patches will "
            "apply on next import (auto-patch finder armed)"
        )
        return
    log.warning(
        "hermes-kchat: auto-patch finder armed (adapter=%s, module names=%s)",
        adapter_file,
        ", ".join(n + ".adapter" for n in _candidate_pkg_names(adapter_file.parent)),
    )

    already = _loaded_adapter_modules(adapter_file)
    if already:
        for name, mod in already:
            _apply_adapter_patches(mod)
            log.warning("hermes-kchat: patched already-imported adapter %s", name)
        return

    mod = _load_adapter_module()
    if mod is None:
        log.warning(
            "hermes-kchat: could not load the Mattermost adapter from %s; "
            "patches will apply on next import (auto-patch finder armed)",
            adapter_file,
        )
        return

    _apply_adapter_patches(mod)
