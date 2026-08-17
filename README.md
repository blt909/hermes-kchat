# hermes-kchat

Compatibility plugin that makes [Hermes Agent](https://github.com/NousResearch/hermes-agent)'s
Mattermost adapter work with **Infomaniak kChat** — Infomaniak's hosted
Mattermost service.

kChat diverges from stock Mattermost in two ways that break the bundled
adapter. This plugin applies two idempotent, fail-open patches at runtime:

## The two incompatibilities

1. **`props` must be an array.** kChat rejects the standard object form with
   HTTP `422` (`The props must be an array`). The bundled adapter injects
   `props={"disable_mentions": true}` on every outbound post — so **all
   posts fail**, cron delivery included. This plugin neutralises that
   injection (omitting `props` is valid on both stock Mattermost and kChat).

2. **No WebSocket endpoint.** kChat does not expose `/api/v4/websocket`
   (HTTP `404` on connect). The adapter's WebSocket listener can never
   attach and its reconnect loop spams `Mattermost WS error: 404` forever;
   inbound messages (DMs, @mentions) are never received. This plugin adds a
   **REST polling fallback**: when the WebSocket handshake fails with 404,
   it polls `/api/v4/channels/{id}/posts?since=` every 30 seconds and feeds
   posts through the exact same `_handle_ws_event` → `handle_message`
   pipeline the WebSocket would have used (mention gating, dedup, file
   download, thread resolution all preserved).

Both patches are idempotent and fail open: if upstream fixes either issue,
the corresponding patch detects it and leaves the module untouched.

## Requirements

- Hermes Agent with the bundled `mattermost-platform` plugin configured
  (`MATTERMOST_URL`, `MATTERMOST_TOKEN`, …). This plugin **patches** that
  adapter at runtime — it does not bundle a copy of it.

## Installation

### Option 1 — `hermes plugins install` (recommended)

```bash
# Install from GitHub and enable in one step
hermes plugins install blt909/hermes-kchat --enable

# Reproducible install: pin a full commit SHA (tags/branches are not accepted)
hermes plugins install blt909/hermes-kchat --ref <full-commit-sha> --enable

# Restart the Hermes gateway (or the agent process)
hermes gateway restart   # or however you run your gateway
```

### Option 2 — Manual drop-in

```bash
# Clone into the Hermes plugins directory
git clone https://github.com/blt909/hermes-kchat.git ~/.hermes/plugins/hermes-kchat

# Plugins are opt-in: enable it (or add to plugins.enabled in config.yaml)
hermes plugins enable hermes-kchat

# Restart the Hermes gateway (or the agent process)
hermes gateway restart   # or however you run your gateway
```

### Option 3 — Web dashboard

1. `hermes dashboard` (or `hermes gui`), open the **Plugins** page
2. **Install from GitHub / Git URL** → enter `blt909/hermes-kchat`
3. Tick **Enable after install** (plugins are opt-in by default)
4. **Install**, then restart the gateway

The panel also accepts subdirectory paths (`owner/repo/path/to/plugin`) and a
*Force reinstall* checkbox equivalent to `--force`.

Plugins are opt-in by default: nothing loads until the plugin name is in
`plugins.enabled` (handled by the `--enable` flag or `hermes plugins enable`).
Because the plugin lives in `~/.hermes/plugins/` (outside the Hermes git
repo), a `hermes update` that reverts or changes the bundled adapter cannot
remove it — the patches re-apply on the next gateway start.

## Configuration

None beyond the standard `mattermost-platform` configuration. kChat has no
global home channel (each cron job targets its own channel via
`deliver=mattermost:<channel_id>`).

## Compatibility

Tested against Hermes Agent commit `06b91411` (v0.20.2, August 2026). The patches are
fail-open, but the adapter's method names can change across versions — if a
Hermes update changes the adapter, re-test.

## Testing

Unit tests run standalone; functional tests need a hermes-agent checkout
(resolved automatically from `$HERMES_HOME/hermes-agent` or
`~/.hermes/hermes-agent`):

```bash
pip install pytest            # unit only (fake adapter, no hermes-agent)
pytest tests/unit -q

pip install pytest aiohttp pyyaml python-dotenv   # functional too
pytest -q
```

CI (GitHub Actions, `.github/workflows/ci.yml`) runs both jobs on every push
and PR:

- **unit** — patch behaviour against a fake adapter;
- **functional** — against the exact hermes-agent commit pinned in the
  "Tested against" line above. If that line goes stale, the functional job
  fails at ref resolution — freshness is enforced mechanically;
- **drift** (weekly, Monday) — the same functional suite against
  hermes-agent `main`, to catch upstream interface changes early.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Sébastien Coget (blt909).

This is a **third-party project**: it is not affiliated with, endorsed by, or
maintained by Nous Research, Mattermost Inc., or Infomaniak. See
[NOTICE.md](NOTICE.md) for upstream attribution (Hermes Agent, MIT, Copyright
(c) 2025 Nous Research).
