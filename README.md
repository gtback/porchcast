# Porchcast

*Ship happens.*

This is a personal project for one household. It is public so Home Assistant
can install it, but no support is promised.

Porchcast is a Home Assistant integration that tracks UPS, FedEx and USPS
packages as items on a single "Packages" to-do list. Add an item containing a
tracking number; Porchcast keeps its due date set to the expected delivery and
fires events when that changes.

## Status

0.1.0 sets up the integration and an empty Packages list. Tracking arrives in
later versions.

## Install

See [DEPLOY.md](DEPLOY.md).

## Development

```sh
uv sync
scripts/lint
scripts/test
scripts/develop   # run a local HA with this integration, at http://localhost:8123
```

See [AGENTS.md](AGENTS.md) for the workflow and repo rules.
