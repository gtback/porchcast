# Porchcast

*Ship happens.*

This is a personal project for one household. It is public so Home Assistant
can install it, but no support is promised.

Porchcast is a Home Assistant integration that tracks UPS, FedEx and USPS
packages as items on a single "Packages" to-do list. Add an item containing a
tracking number; Porchcast keeps its due date set to the expected delivery and
fires events when that changes.

## Status

0.3.0 tracks UPS packages: it polls UPS for each item with a UPS number, sets
the item's due date to the expected delivery, writes the status into the
item, checks delivered items off, and fires events. FedEx and USPS numbers are
recognized but not tracked yet.

## Using the list

Add an item whose text contains a tracking number, with any notes you like,
for example `Bike rack, REI 1Z999AA10123456784`. Spaces or hyphens inside the
number are fine. The number can also go in the item's description.

Porchcast writes a status block at the bottom of the description, under a
`--- tracking ---` line. Everything above that line is your notes and is never
changed. Edit the notes freely; leave the line in place.

Porchcast checks a new number right away, then on a schedule that depends on
the status: every 20 minutes when out for delivery, every 2 hours in transit,
every 6 hours before pickup. Delivered items are checked off and no longer
polled. Checking an item off yourself stops polling it; unchecking resumes.

The due date is the end of the expected delivery range or window (so an item
isn't shown overdue while it is still on time). A due date you type is kept
until the carrier gives an estimate; after that the carrier's estimate wins.

If Porchcast picks the wrong carrier, or doesn't recognize a number, put the
carrier in front of it with no spaces in the number: `fedex:123456789012`,
`ups:...` or `usps:...`. If an item has several numbers, the first one is used.

## Events

Porchcast never sends notifications itself. It fires events for automations:

| Event | When | Data |
| --- | --- | --- |
| `porchcast_eta_changed` | The expected delivery changed, or became known | `old_eta_start`, `old_eta_end`, `new_eta_start`, `new_eta_end`, `status` |
| `porchcast_status_changed` | The status changed (e.g. to `out_for_delivery`) | `old_status`, `new_status`, `description` |
| `porchcast_delivered` | Delivered | `delivered_at`, `location` |

Every event also has `uid`, `summary`, `carrier` and `tracking_number`. ETA
values are ISO dates, or datetimes when the carrier gives a time. Statuses are
`pre_transit`, `in_transit`, `out_for_delivery`, `delivered`, `exception` and
`unknown`.

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
