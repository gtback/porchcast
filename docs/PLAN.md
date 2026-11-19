# Porchcast session plan

The brief is `docs/project-brief.md` on this branch. This file tracks the six
sessions and records decisions the brief doesn't cover. This branch is never
merged; each session builds on `main`.

## Sessions

| # | Session | Version | Status |
| --- | --- | --- | --- |
| 1 | Scaffold and pipeline | 0.1.0 | In progress (started 2026-11-19) |
| 2 | Items and storage | 0.2.0 | Not started |
| 3 | UPS end to end | 0.3.0 | Not started |
| 4 | FedEx | 0.4.0 | Not started |
| 5 | USPS | 0.5.0 | Not started |
| 6 | Finish | 0.6.0 | Not started |

Scope per session is in the brief, "Sessions". Each session ends with a merged
PR whose body says what the owner must do in real HA.

### Session 1 done-when

- [ ] `main` has the scaffold; CI green (lint, tests, version check, hassfest, HACS validation).
- [ ] Repo settings: description, topics, issues enabled (owner does this by hand; no tool for it here).
- [ ] `release.yml` published v0.1.0.
- [ ] Owner installed 0.1.0 through the Marketplace and sees an empty "Porchcast Packages" list.

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
