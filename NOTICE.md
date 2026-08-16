# NOTICE — Third-party attribution

## Hermes Agent

This plugin patches, at runtime, the bundled Mattermost platform adapter of
[Hermes Agent](https://github.com/NousResearch/hermes-agent), which is
distributed under the MIT License:

```
MIT License

Copyright (c) 2025 Nous Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Provenance of this plugin's code

The code in `__init__.py` is original. It does **not** copy any file from
Hermes Agent; it is *interface-coupled* to the bundled Mattermost adapter
(`plugins/platforms/mattermost/adapter.py`):

- it calls the adapter's methods (`_api_get`, `_handle_ws_event`,
  `_ws_connect_and_listen`) by name;
- it reuses the Mattermost WebSocket event shape (`event`, `data.post`,
  `channel_type`, `sender_name`), which is part of the Mattermost server
  protocol itself, not a Nous Research creation.

A token-level similarity analysis against the upstream adapter shows only
boilerplate overlap (standard Python imports and exception-handling
patterns).

Tested against Hermes Agent commit `56dc01d` (August 2026).
