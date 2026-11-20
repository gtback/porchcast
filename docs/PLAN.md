# Porchcast session plan

The brief is `docs/project-brief.md` on this branch. This file tracks the six
sessions and records decisions the brief doesn't cover. This branch is never
merged; each session builds on `main`.

## Sessions

| # | Session | Version | Status |
| --- | --- | --- | --- |
| 1 | Scaffold and pipeline | 0.1.0 | Done 2026-11-20 (PR #1; installed via Marketplace) |
| 2 | Items and storage | 0.2.0 | Done 2026-11-20 (PR #2; owner added items in real HA) |
| 3 | UPS end to end | 0.3.0 | Merged 2026-11-20 (PR #3); owner real-package test pending |
| 4 | FedEx | 0.4.0 | Not started |
| 5 | USPS | 0.5.0 | Not started |
| 6 | Finish | 0.6.0 | Not started |

Scope per session is in the brief, "Sessions". Each session ends with a merged
PR whose body says what the owner must do in real HA.

### Session 1 done-when

- [x] `main` has the scaffold; CI green (lint, tests, version check, hassfest, HACS validation).
- [x] Repo settings: description, topics, issues enabled; default branch `main`.
- [x] `release.yml` published v0.1.0.
- [x] Owner installed 0.1.0 through the Marketplace and sees an empty "Porchcast Packages" list.

## Decisions

### 2026-11-19 (Session 1)

- **Dev pins: HA 2026.10.4 + phcc 0.13.375, not the 2026.11 line.** The brief asks
  for 2026.11 pins, but no `pytest-homeassistant-custom-component` release for
  2026.11 exists on PyPI yet (newest is 0.13.375 → `homeassistant==2026.10.4`,
  published 2026-10-25). Both must match, so dev/test runs on 2026.10.4 while
  `hacs.json` requires 2026.11.0 at install time. Python is 3.14 (HA requires
  >=3.14.2). Move both pins to 2026.11 as soon as phcc publishes it (Dependabot
  should open that PR).
- **Config flow in 0.1.0 has no fields.** It confirms and creates a single entry
  (`single_config_entry`). Carrier credentials arrive with the UPS session, as
  a config-entry migration (VERSION 1 → 2).
- **The 0.1.0 to-do entity supports no features.** It shows an empty list so the
  install path can be tested; create/update/delete arrive in Session 2.
- **Entity ID** is `todo.porchcast_packages` (device "Porchcast", entity name
  "Packages").
- **Brand icon** ships in `custom_components/porchcast/brand/` (`icon.png`,
  `icon@2x.png`); HA 2026.10+ serves brand images from a custom integration's
  `brand/` folder, and HACS validation requires brand assets.
- **License: MIT**, because HACS validation checks for an OSI license.
- **Releases use `gh release create`**, not a third-party release action.
- **Pre-releases** are `vX.Y.ZbN` built from a branch whose manifest is already
  bumped above `main`'s, so HA sees them as newer than the installed release.
  The pre-release tag points at a commit (not on any branch) whose manifest
  carries the `bN` version.
- **Marketplace facts** are recorded in `DEPLOY.md` on `main`. Two surprises:
  custom repositories are only checked for updates every 48 hours, and the
  Marketplace docs advise restoring a backup instead of "Install another
  version" to go back after an update.
- **PR #1 merged with `hacs` red on `license`** (owner's call). HACS reads the
  license from the default branch, which was still the empty `main`. The same
  check passed on `main` right after the merge.
- **Manifest `categories`**: the HACS validator warns that the manifest has
  none. The key is newer than the 2026.10 dev pin, and its docs host
  (contributors.home-assistant.io) is blocked here. Revisit when the pins move
  to 2026.11.
- **First install needed a restart** (owner, 2026-11-20). DEPLOY.md's "First
  install" step 4 says no restart is needed; change it to "restart if HA asks"
  in Session 2's PR. Not yet known why HA couldn't load it without restarting.

### 2026-11-20 (Session 2)

- **Tracking-number formats and check digits** are in `docs/carriers.md`.
- **Store**: one `Store` per entry, key `porchcast.<entry_id>`, version 1.1,
  holding `{"items": [...]}` in list order. Each item is `uid` (ULID),
  `summary`, `notes`, `status`, `due` (ISO date or aware datetime),
  `completed`, and `tracking` (`number`, `carriers`, `forced`). HA doesn't
  store to-do items for an integration, so the store keeps our text too.
- **Migration approach**: schema changes add keys and bump the minor version.
  HA's `Store` passes a different minor version through unchanged, and
  loading ignores unknown keys but keeps them on save (per item and at the top
  level), so a rollback reads newer data and a later upgrade loses nothing. The stored
  `tracking` object is written back exactly as loaded until an edit changes
  that item's tracking (number, carriers or override); then it is replaced
  for good. Session 3's poll bookkeeping goes inside `tracking`, so it resets
  when the number changes. A
  change that can't be additive bumps the major version and adds a step to
  `_PackageStore._async_migrate_func`.
- **Separator survival** (mobile app edits): the separator matches any run of
  ASCII, en or em dashes, in any case, with extra spaces and CRLF line endings.
  If the separator line is gone but the text still ends with the status block
  we last rendered, that block is dropped; otherwise all the text is notes.
  Notes are what's above the separator, trimmed.
- **The tracking number is re-read on every edit**. Session 3 must reset poll
  state when the number changes, and keep it when it doesn't.
- **Due date** is whatever the user set, for now. Session 3's coordinator will
  overwrite it with the carrier's ETA.
- **Move is supported** (cheap, and list order matters on a phone).
- **Removing the entry deletes the store** (`async_remove_entry`).
- **DEPLOY.md first install** now says to restart if HA asks (fixed in PR #2).

### 2026-11-20 (owner, after Session 2)

- **Due date is the end of the expected range, everywhere.** This replaces the
  brief's "use the window start". A multi-day range ("Nov 24-28") sets the due
  date to the last day; a same-day time window ("2-6 pm") sets the due
  datetime to the window's end. Reason: HA marks an item overdue once its due
  passes, so a start date shows on-time packages as overdue.
- **The status block shows the full range or window** ("Expected Nov 24-28",
  "Expected Nov 24, 2-6 pm").
- **`porchcast_eta_changed` carries both ends** (old and new start and end), so
  a later "start watching at this time" automation can trigger on the start.
  No such automation ships for now.
- **A due date the owner typed in is kept until the carrier gives an
  estimate**; from then on the carrier's estimate replaces it on each poll.
- **Estimate history is deferred.** Store only the current estimate. Each
  change still fires `porchcast_eta_changed` with old and new values, so an
  automation can log slips. If history on the item is wanted later, add a
  free-text line to the status block (not the notes); no structured history.
- **Session 2 closed** 2026-11-20: the owner updated to 0.2.0 and added items
  in real HA.

### 2026-11-20 (Session 3)

- **UPS API details** are in `docs/carriers.md`. The fixtures are synthetic
  (shaped after UPS's OpenAPI spec); real ones come from `live_check.py --save`.
- **Config entry stays version 1** (not 1 → 2 as Session 1 planned). HA
  refuses to load an entry whose major version is above the handler's, so a
  bump would break rolling back to 0.2.0. An entry with no credentials (0.1.0
  and 0.2.0 made those) still loads; its items say "UPS isn't set up in
  Porchcast", and the owner adds keys with **Reconfigure**. Removing and
  re-adding the integration would delete the stored packages.
- **Entry data**: `{"ups": {"client_id", "client_secret", "sandbox"}}`, one
  key per carrier. The form has one section per carrier; at least one carrier
  is required, and each is checked by fetching a token. The sandbox switch
  selects UPS's CIE test environment.
- **Reconfigure and a minimal reauth** landed now, because the coordinator
  starts reauth on rejected credentials. Session 6 still owns the options
  flow.
- **Polling**: per-status intervals from the brief. A failed poll retries in
  30 min (or the status interval, if shorter); after 5 failures in a row the
  block says so and polling drops to every 6 h. Carrier backoff on 429, 5xx or
  network errors: `Retry-After` in full (up to a day), else 15 min doubling
  to 2 h. A 400 for one number doesn't back off the carrier (Copilot review). A rejected
  credential stops that carrier until reauth reloads the entry; it doesn't
  count as a package failure. Polls never run concurrently.
- **New or re-numbered items are polled at once** (in a task, so adding an
  item doesn't wait on UPS), not at the next tick.
- **Delivered**: the item is checked off (completed time = delivery time) and
  polling stops for good. Unchecking a delivered item doesn't resume polling
  or fire again; unchecking an item checked off by hand does resume. The due
  date stays the last ETA.
- **ETA kept when the carrier stops giving one** (e.g. on delivery), and
  reapplied to the due date on every successful poll, and
  `porchcast_eta_changed` fires only for a new, known ETA.
- **Events**: `porchcast_eta_changed` carries `old_eta_start`, `old_eta_end`,
  `new_eta_start`, `new_eta_end` (ISO dates or datetimes) and `status`;
  `porchcast_status_changed` carries `old_status` (None the first time),
  `new_status` and `description`; `porchcast_delivered` carries
  `delivered_at` and `location`. All carry `uid`, `summary`, `carrier`,
  `tracking_number`.
- **Store 1.2**: poll state lives in `tracking.poll` (carrier that answered,
  status, description, ETA, last event, delivery time and place, checked,
  next poll, failures, problem line). Unknown keys inside it are kept. Never
  polled → no `poll` key.
- **Status block** lines: number, `Status: ...`, `Expected ...` or
  `Delivered ...`, `Last scan: ...`, a problem line if any, `Checked ...`.
  Times are in HA's time zone.
- **mypy** now uses `explicit_package_bases`, so modules are named
  `custom_components.porchcast.*`. Before this the strict override for
  `tracking` and `carriers.*` matched no module; it now applies (and passes).
