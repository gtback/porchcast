# Porchcast

*Ship happens.*

This is a personal project for one household. It is public so Home Assistant
can install it, but no support is promised.

Porchcast is a Home Assistant integration that tracks UPS, FedEx and USPS
packages as items on a single "Packages" to-do list. Add an item containing a
tracking number; Porchcast keeps its due date set to the expected delivery and
fires events when that changes.

## Status

0.2.0 keeps a Packages list and recognizes UPS, FedEx and USPS tracking
numbers in each item. It doesn't contact any carrier yet; that arrives in
later versions.

## Using the list

Add an item whose text contains a tracking number, with any notes you like,
for example `Bike rack, REI 1Z999AA10123456784`. Spaces or hyphens inside the
number are fine. The number can also go in the item's description.

Porchcast writes a status block at the bottom of the description, under a
`--- tracking ---` line. Everything above that line is your notes and is never
changed. Edit the notes freely; leave the line in place.

If Porchcast picks the wrong carrier, or doesn't recognize a number, put the
carrier in front of it with no spaces in the number: `fedex:123456789012`,
`ups:...` or `usps:...`. If an item has several numbers, the first one is used.

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
