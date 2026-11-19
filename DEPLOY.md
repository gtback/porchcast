# Deploying Porchcast

Porchcast ships through the Home Assistant Marketplace (built into HA since
2026.11; formerly HACS) as a custom repository. A merge to `main` that bumps the
version publishes a GitHub release, and HA offers it as an update. Nothing in CI
connects to the house.

## Marketplace facts

These are what the plan assumes. The cloud session that set this repo up could
not reach hacs.xyz or home-assistant.io, so they are **not yet confirmed**
against current docs. Confirm each one by hand and update this table.

| Assumption | Status |
| --- | --- |
| The Marketplace only installs from public GitHub repos (as HACS did), so this repo is public. | Unconfirmed |
| A release must contain `hacs.json` to install or update. (It does: `hacs.json` is at the repo root, so every tag's source has it.) | Unconfirmed; handled either way |
| Each custom repository has a "show beta versions" toggle, so pre-releases can be tried. | Unconfirmed; if it's gone, use the sideload below |
| Adding a custom repository may need HA's GitHub connection. | Unconfirmed |
| The validation actions are still `hacs/action` and `home-assistant/actions/hassfest`. | Both still exist on GitHub (checked 2026-11-19); CI runs them |

## First install (once)

1. Create carrier developer accounts and apps; keep sandbox and production
   keys apart. (Needed from 0.3.0, when UPS tracking lands.)
2. In HA: Settings → Marketplace → Custom repositories → add
   `https://github.com/gtback/porchcast` as an **Integration** → install.
   If HA asks to connect GitHub first, do that.
3. Restart HA if it asks.
4. Settings → Devices & services → Add integration → Porchcast.
5. Add the Packages to-do list to a dashboard.

## Updates

HA shows an update for Porchcast after each release. Install it, and restart if
HA asks.

## Trying a branch (pre-release)

1. Make sure the branch's manifest version is already bumped above `main`'s.
2. Actions → Release → Run workflow → pick the branch. It publishes
   `vX.Y.ZbN` as a GitHub pre-release.
3. In the Marketplace, turn on beta versions for Porchcast, update, test, then
   turn betas back off.

## Rollback

Reinstall an earlier version from the Marketplace's version picker, or revert on
`main` and let a new patch release go out. Releases are never deleted.

## Data

Stored data lives in HA's `.storage/` and is covered by normal HA backups.

## Escape hatch: sideload

`scripts/sideload` (added in a later version) will copy the integration to HA
over the SSH add-on and restart HA. It is for emergencies only: it leaves the
Marketplace's idea of the installed version out of date.
