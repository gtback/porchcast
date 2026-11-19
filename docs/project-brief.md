# Porchcast for Home Assistant — Project Brief

Nov 18, 2026

## Overview

Build a Home Assistant custom integration that tracks our UPS, FedEx and USPS packages as items on one HA to-do list, keeps each item's expected delivery date current, and fires events when that date or time window changes. It is personal software for one household: no public release, no support burden, and every design choice should favor simple over general.

**Name:** Porchcast (it forecasts what's landing on the porch), tagline "Ship happens", integration domain `porchcast`. Keep the display name in one constant (`const.py`) so it is easy to change. The domain is fixed from 0.1.0, because changing it after install breaks existing setups. The README opens with the tagline and a line saying this is a personal project with no support promised.

**What v1 does**

- Adds a to-do list entity, "Packages". We add an item by typing or pasting text that contains a tracking number, plus whatever notes we want (sender, contents, order link).
- Finds the tracking number in the item, works out the carrier from its format, and polls that carrier's official API.
- Sets the item's due date (or date and time, when the carrier gives a window) to the expected delivery, and writes the latest status into the description without overwriting our notes.
- Fires `porchcast_eta_changed` when the expected date or window changes, and `porchcast_delivered` on delivery. Automations decide which of these reach our phones.
- Marks delivered items complete and removes them after a configurable number of days (default 3).

**Not in v1:** Amazon Logistics (no public API, and one-day delivery makes it low value), parsing a pasted email to pull out sender and contents automatically, a calendar view, other carriers, and any web UI outside HA.

**Why HA instead of a web app:** HA already gives us polling, a phone-friendly list UI, mobile notifications and automations. A container-based, database-backed web app deployed to our VM would rebuild all of that for a handful of rows. The cost is a different packaging and install story, which most of this brief is about.

## Design

One config entry creates one to-do list entity, backed by HA's storage helper and refreshed by one update coordinator that calls thin async clients for each carrier.

### Entity model

- **One `TodoListEntity`, not one entity per package.** Packages come and go; the entity registry should not fill with dead sensors. Support create, update, delete, set due date, set due datetime and set description.
- **Item text is ours; tracking data is the integration's.** Persist state with `homeassistant.helpers.storage.Store`, keyed by item UID: tracking number, carrier, last result, poll bookkeeping. The description is rendered as our notes, then a `--- tracking ---` separator, then the managed status block (status, last scan and location, last update time). When we edit an item, keep only the text above the separator as notes.
- **Due date** is the carrier's expected delivery date, or a datetime when it gives a window (use the window start, and put the full window in the status block).
- **Completed** means delivered. Marking an item complete by hand stops polling for it. Unchecking it resumes polling.
- **Cleanup:** remove completed items N days after delivery (option, default 3).

### Adding a package

1. We create an item whose text contains a tracking number, for example "Bike rack, REI 1Z999AA10123456784 https://rei.com/order/...". This works the same from the HA app, the dashboard or `todo.add_item`.
2. The integration extracts candidate numbers with per-carrier patterns and validates check digits where the format has them.
3. If a number fits more than one carrier (long all-digit FedEx and USPS numbers can collide), try each in turn and keep the first that returns data. A prefix such as `fedex:` in the text forces the carrier.
4. No number found → leave the item alone, and add a status line saying so.

### Carriers

Write small async clients per carrier using HA's shared aiohttp session (`async_get_clientsession`). Avoid third-party carrier libraries, so `manifest.json` requirements stay empty or tiny. Each client handles its own OAuth client-credentials token and caching, and returns one normalized result: carrier, status, ETA date, optional window, last event (text, location, time) and delivered time.

| Carrier | API to use | Notes for Claude Code |
| --- | --- | --- |
| UPS | UPS Developer Portal Tracking API (OAuth client credentials) | Build first; simplest to get keys for. |
| FedEx | FedEx Developer Portal Track API (OAuth client credentials) | Separate sandbox and production keys. |
| USPS | The current USPS APIs platform (developers.usps.com), OAuth | Do not use the legacy Web Tools XML API. |

Read each carrier's current docs before coding; endpoint paths, field names and rate limits change. Record what you found in `docs/carriers.md` on the plan branch.

Normalized statuses: `pre_transit`, `in_transit`, `out_for_delivery`, `delivered`, `exception`, `unknown`.

### Polling

One `DataUpdateCoordinator` ticks every 15 minutes, and each package is due for a poll based on its status:

| Status | Poll every |
| --- | --- |
| `out_for_delivery` | 20 min |
| `in_transit`, `exception` | 2 h |
| `pre_transit`, `unknown` | 6 h |
| `delivered` or completed | never |

Back off per carrier on errors and HTTP 429. After 5 straight failures for one package, say so in its status block and keep trying at the slow rate. On an auth failure, start HA's reauth flow instead of retrying.

### Events and notifications

The integration never sends notifications itself. It fires events, and we write automations.

- `porchcast_eta_changed`: the ETA date or window changed, including first being known. Payload: item UID, summary, carrier, tracking number, old and new ETA, old and new window, status.
- `porchcast_status_changed`: any normalized status change, such as out for delivery or exception.
- `porchcast_delivered`: delivered, with time and location if given.

Ship two example automations in `examples/` (ETA changed → phone notification; out for delivery → notification), not as code that runs.

### Configuration

- **Config flow:** credentials per carrier, each optional. Validate a set of credentials by fetching a token. At least one carrier is required.
- **Options flow:** cleanup days, and a switch to pause all polling.
- **Reauth flow** for expired or revoked credentials.
- **Diagnostics** download with credentials and tracking numbers redacted.
- Credentials live only in the config entry. Nothing secret goes in the repo, which matters because the repo must be public (see Packaging).

## Repo layout and dev environment

A public GitHub repo under `gtback`, laid out the way the Marketplace (formerly HACS) expects, with Python tooling that runs the same in a Claude Code cloud session, in CI and on my machine.

```
custom_components/porchcast/
  __init__.py        # setup/unload entry, coordinator wiring
  manifest.json      # domain, name, version, config_flow, iot_class: cloud_polling
  const.py           # DOMAIN, display name, defaults, poll intervals
  config_flow.py     # config, options and reauth flows
  coordinator.py     # per-package scheduling, backoff, events
  todo.py            # the TodoListEntity
  store.py           # Store wrapper, notes/status description rendering
  tracking.py        # number extraction, check digits, carrier detection
  carriers/          # base.py (normalized model), ups.py, fedex.py, usps.py
  diagnostics.py
  strings.json, translations/en.json
tests/
  conftest.py
  fixtures/{ups,fedex,usps}/*.json   # recorded, scrubbed API responses
  test_tracking.py, test_carriers_*.py, test_todo.py, test_coordinator.py, test_config_flow.py
config/configuration.yaml            # throwaway HA config for local runs
examples/                            # automation YAML
scripts/  setup, develop, lint, test, live_check.py, bump_version.py
hacs.json, pyproject.toml, AGENTS.md, CLAUDE.md, DEPLOY.md, README.md
.claude/settings.json, .claude/hooks/session-start.sh
.github/workflows/{ci.yml,release.yml}, .github/dependabot.yml
```

### Toolchain

- **Python:** whatever version the HA release we target requires. Pin it in `.python-version` and `pyproject.toml`, and check it against the current HA release, not from memory.
- **uv** for the virtualenv and lockfile (`uv.lock`). Pin `homeassistant` and `pytest-homeassistant-custom-component` to matching versions; the test package is generated for a specific HA release.
- **Ruff** for lint and format, using HA core's rule set as a starting point. **mypy** in strict mode on `tracking.py` and `carriers/`.
- **Tests:** `pytest-homeassistant-custom-component`, with its `hass` fixture, `MockConfigEntry`, the `enable_custom_integrations` fixture and `aioclient_mock` for HTTP. Set `asyncio_mode = auto`.
- `scripts/develop` runs a real HA (`hass -c config --debug`) with the integration on its path, for checking the UI on my machine.

### Cloud-session constraints

The Claude Code cloud sandbox only reaches package registries and GitHub, so:

- **Carrier APIs are unreachable from the sandbox.** Every test runs against recorded fixtures. Never write a test that needs the network.
- `scripts/live_check.py <tracking number>` hits the real APIs with credentials from a local `.env` (gitignored). I run it on my machine; its output, scrubbed, becomes new fixtures.
- `.claude/hooks/session-start.sh`: only when `CLAUDE_CODE_REMOTE=true`, install uv, the pinned Python, and the locked dependencies. Document anything the proxy blocks in its comments and in AGENTS.md, so the next session doesn't rediscover it.
- Fixtures must not contain real tracking numbers, names or addresses. Scrub them in `live_check.py` before they are written.

## Packaging and install workflows

Ship through the Home Assistant Marketplace as a custom repository: a merge to `main` publishes a GitHub release, and HA offers it as an update. That replaces the web-app habit of "merge = deploy to the VM" with "merge = update waiting in HA", and nothing in CI ever connects to the house.

### What changed in HA, and what it means here

- Since HA 2026.11 (released November 4, 2026), HACS is built into HA as the **Marketplace** under Settings, and the standalone HACS integration can no longer be installed. Existing custom repositories carried over.
- Reported for the Marketplace: a repository's release must contain `hacs.json` to install or update.
- HACS only ever worked with **public** GitHub repos. Assume the Marketplace is the same, so this repo is public, which is fine because credentials live only in HA's config entry. Claude Code: confirm both points in the current Marketplace docs during Session 1, and record the answer in `DEPLOY.md`.
- Adding a custom repository may need HA's GitHub connection; `DEPLOY.md` covers that step.

**Our HA:** Home Assistant OS, Core 2026.11.2 (Supervisor 2026.11.0, OS 18.2), so the Marketplace is available. Set the `hacs.json` minimum to 2026.11.0, and pin the dev `homeassistant` and `pytest-homeassistant-custom-component` packages to the 2026.11 line, using its required Python.

### The three loops

| Loop | Where it runs | Turnaround | Used for |
| --- | --- | --- | --- |
| Tests | Cloud session, CI, my machine | Seconds | All logic: parsing, carriers (fixtures), coordinator, to-do entity, config flow |
| Local HA | `scripts/develop` on my machine, carrier sandbox keys | About a minute | Looking at the to-do UI, config flow screens, events in Developer Tools |
| Real HA | Our HA via the Marketplace | A few minutes | Real packages, real notifications |

Most sessions should only need the first loop. The second and third are for me, and each session's PR says whether it needs a look in real HA before or after merge.

### Versioning and release

- **SemVer, starting at 0.1.0.** The version lives in `manifest.json` only; `hacs.json` carries the minimum HA version.
- **Every PR that changes `custom_components/` bumps the version** with `scripts/bump_version.py` (patch by default, minor for new features). CI fails a PR whose version is not higher than `main`'s. PRs that only touch docs, tests or CI skip the bump and the check.
- **`release.yml` runs on push to `main`.** It reruns CI, and if the manifest version has no tag yet, it tags `vX.Y.Z` and creates a GitHub release with generated notes. A merge without a bump publishes nothing.
- **Pre-releases for trying a branch on real HA:** run `release.yml` by hand (`workflow_dispatch`) on a PR branch. It publishes `vX.Y.ZbN` as a GitHub pre-release. I turn on beta versions for this repo in the Marketplace, update, test, then turn betas back off. Claude Code: confirm the Marketplace still has a per-repository beta toggle; if not, document the sideload below as the way to test a branch.
- Validate in CI with `hassfest` and the HACS/Marketplace repository validation action (check the current names of both after the Marketplace move). The validator wants a repo description, topics and issues enabled; set those in Session 1.

### First install (once, by me)

1. Create carrier developer accounts and apps; keep sandbox and production keys apart.
2. In HA: Settings → Marketplace → Custom repositories → add the repo URL as an Integration → install.
3. Restart HA if it asks.
4. Settings → Devices & services → Add integration → Porchcast → enter production keys.
5. Add the to-do list to a dashboard, and copy the example automations.

### Updates, rollback and data

- **Update:** HA shows an update for Porchcast after each release. Install it, and restart if HA asks.
- **Rollback:** reinstall an earlier version from the Marketplace's version picker, or revert on `main` and let a new patch release go out. Releases are never deleted.
- **Stored data** lives in HA's `.storage/` and is covered by normal HA backups. The `Store` has a schema version from day one, with a migration function for every change; a rollback must not break on newer data (ignore unknown keys).

### Escape hatch: sideload

`scripts/sideload` copies `custom_components/porchcast/` to HA over the SSH add-on (`rsync`) and restarts HA through its API with a long-lived token from a local `.env`. It is for emergencies or for a broken Marketplace, not the normal path, because it leaves the Marketplace's idea of the installed version out of date. The next Marketplace update overwrites it.

## Agent workflow

This repo follows the same agent conventions as my other projects, written out here in full so it depends on nothing outside itself. **Never name any other project anywhere in this repo, its branches, issues, PRs or commit messages.** If a comparison helps, say "a container-based, database-backed web app deployed to a VM via GitHub Actions."

### Files

- **`CLAUDE.md`** is one line: `@AGENTS.md`. Everything lives in `AGENTS.md`.
- **`AGENTS.md`** has these sections: The plan, Default change workflow, Running checks in a cloud session, Cloud gotchas, Releases, and Repo rules.
- **`.claude/settings.json`** allows the PR-activity subscribe/unsubscribe and `send_later` tools without a prompt, and registers the session-start hook.
- **`.claude/hooks/session-start.sh`** exits at once unless `CLAUDE_CODE_REMOTE=true`. Otherwise it installs uv, the pinned Python and the locked dependencies, sending noisy output to stderr. Its comments explain every workaround for the sandbox's proxy.

### The plan

This brief goes to `docs/project-brief.md` and the session plan to `docs/PLAN.md` on a `plan` branch that is never merged. `AGENTS.md` tells each session to read them with `git fetch origin plan` and `git show origin/plan:docs/PLAN.md`. Each session builds on `main`. A decision the plan doesn't cover is committed to `plan`, not to the feature branch.

### Default change workflow

Once a plan is approved, take changes all the way to merged without asking me to review the finished work:

1. Implement on the designated feature branch.
2. Verify locally: `scripts/lint` (ruff check, ruff format --check, mypy) and `scripts/test` (pytest). Add tests for every data-path change and every bug fix.
3. If the PR touches `custom_components/`, bump the version with `scripts/bump_version.py` as the last commit.
4. Open a PR and request a Copilot review. Address its feedback and push fixes.
5. Wait for CI to pass, then squash-merge.

Pause for me only when Copilot flags a real conceptual problem, or when a question comes up that only I can answer. If Copilot can't review (its quota is used up, say), self-review the diff carefully and merge on green CI if it's clean.

The PR body ends with what I need to do in real HA: "Nothing", "Update and check the to-do list", or "Test the pre-release first". When a feature needs a real-HA look, merging isn't the end: schedule a check-in and ask me how it went.

### CI and dependencies

- `ci.yml` runs on pull requests and as a reusable workflow (`workflow_call`), with concurrency that cancels superseded runs. `release.yml` runs on push to `main`, calls `ci.yml` first, and never runs two at once.
- **Every Action is pinned by commit SHA**, with its version in a comment.
- **Dependabot weekly** for Python dependencies and GitHub Actions, with minor and patch updates grouped. Its weekly HA bump is the early warning for API changes: fix its failures promptly instead of pinning back.

### Repo rules for AGENTS.md

- **HA moves fast.** Before using an HA API, check the pinned version's developer docs and source, not memory, and heed deprecation warnings in test output.
- **No network in tests**, and never run `live_check.py` or `sideload` in a cloud session.
- **The repo is public.** No credentials, real tracking numbers, names or addresses, including in fixtures and PR text.
- **No other project names**, as above.

## Sessions, acceptance and open questions

Six sessions, each ending in a merged PR. Session 1 proves the whole release-and-install path with an integration that does almost nothing, so packaging problems show up before any carrier code exists.

### Sessions

1. **Scaffold and pipeline.** Repo settings (description, topics, issues), layout, uv/ruff/mypy/pytest, session-start hook, `AGENTS.md`, CI, `release.yml`, `bump_version.py`, `hacs.json`, Dependabot. The integration loads, has a config flow, and shows an empty "Packages" list. Confirm the Marketplace facts (public repos, `hacs.json` in releases, betas) and write `DEPLOY.md`. Release 0.1.0; I install it through the Marketplace.
2. **Items and storage.** Tracking-number extraction, check digits and carrier detection (heavily tested), the `Store` with a schema version, notes/status description rendering, and to-do create, update, delete and complete. No carrier calls yet.
3. **UPS end to end.** UPS client, coordinator scheduling and backoff, due-date updates, the three events, `live_check.py`, and the first scrubbed fixtures. Then I test a real UPS package in HA.
4. **FedEx.** Client, fixtures and the multi-carrier fallback for ambiguous numbers.
5. **USPS.** Client and fixtures.
6. **Finish.** Cleanup of delivered items, options and reauth flows, diagnostics, example automations, and README.

### Acceptance criteria for v1

- Pasting "Bike rack 1Z999AA10123456784 https://..." into the list creates an item that shows the UPS ETA as its due date within one coordinator tick.
- Editing an item's notes never loses the status block, and the next poll never overwrites the notes.
- A changed ETA fires `porchcast_eta_changed` exactly once, with old and new values; the example automation sends a phone notification.
- Delivered items are checked off, then disappear after the configured number of days.
- Revoked credentials produce a reauth prompt, not a log full of errors.
- A merge with a version bump appears as an update in HA without my touching CI or the HA host; a pre-release can be installed and removed.
- Restarting HA, or rolling back one version, keeps every item.
- The repo contains no credentials, real tracking numbers or addresses.

### Open questions for me

- **SSH add-on:** we're on HA OS 2026.11.2, so only the sideload escape hatch depends on it. Install it before the first time we need a sideload, not up front.
- **Delivered events:** keep firing them even though the doorbell camera covers delivery? They're cheap, so the default is yes.

### Decisions for Claude Code to make and document

- Exact tracking-number patterns and check-digit rules per carrier.
- How the description separator survives edits from the HA mobile app.
- Store schema and migration approach.
- How to model per-carrier rate limits found in their docs.

### Sources

- [HACS: private repositories](https://hacs.xyz/faq/private_repositories/) and [publishing requirements](https://hacs.xyz/docs/publish/start)
- [Home Assistant 2026.11 Marketplace overview (raspberry.tips)](https://raspberry.tips/en/smart-home/home-assistant-2026-11-whats-new)
- [Marketplace and hacs.json in releases (byteiota)](https://byteiota.com/?p=26953)
- [pytest-homeassistant-custom-component](https://pypi.org/project/pytest-homeassistant-custom-component)
