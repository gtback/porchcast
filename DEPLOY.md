# Deploying Porchcast

Porchcast ships through the Home Assistant Marketplace (built into HA since
2026.11; formerly HACS) as a custom repository. A merge to `main` that bumps the
version publishes a GitHub release, and HA offers it as an update. Nothing in CI
connects to the house.

## Marketplace facts

Checked on 2026-11-19 against the HA 2026.11 release notes
(home-assistant.io/blog/2026/11/04/release-202611), the Marketplace docs
(home-assistant.io/integrations/marketplace) and the HACS publishing docs
(hacs.xyz/docs/publish), which still apply to the Marketplace.

| Question | Answer |
| --- | --- |
| Private repos? | **No.** A custom repository "is a public repository on GitHub." The GitHub connection "cannot access private repositories." So this repo is public. |
| `hacs.json` needed? | **Yes**, at the repo root. "A custom repository without a hacs.json file stays installed, but the Marketplace cannot update it." It is in every tag, so every release has it. |
| Releases | The Marketplace uses the tag of the latest GitHub **release** as the version ("just publishing tags is not enough"). `release.yml` publishes releases, not just tags. |
| Pre-releases | **Yes**, per repository: a *Pre-release* switch entity on the repository's device under Settings → Devices & services → Marketplace. It is disabled by default: enable the entity, then turn the switch on. |
| GitHub connection | **Required** to add a custom repository and to keep it updated. It uses GitHub device sign-in and reads only public data. |
| Update checks | With a GitHub connection, custom repositories are checked for new versions **every 48 hours** (the catalog every 6 hours). So a release can take up to two days to show as an update unless you check by hand. |
| Brand icon | Required. Shipped in `custom_components/porchcast/brand/icon.png` (HA serves brand images from a custom integration's `brand/` folder). |
| Validation | `hacs/action` (category `integration`) checks: description, topics, issues enabled, OSI license, `hacs.json`, README, brand assets. `home-assistant/actions/hassfest` validates the manifest. Neither was renamed. |
| Rolling back | The docs say not to use *Install another version* to go back after an update: restore a backup instead. See Rollback below. |

## First install (once)

1. Create carrier developer accounts and apps; keep sandbox and production
   keys apart. See "Carrier credentials" below.
2. Settings → Marketplace → accept the community-content notice (first time
   only).
3. Settings → Marketplace → ⋮ → **Add from link** → `gtback/porchcast`. Connect
   GitHub when asked (device sign-in). Pick **Integration** if it asks for a
   type.
4. Open Porchcast in the list → **Install**. Restart HA if it asks (the first
   install on 2026-11-20 needed one), then Settings → Devices & services →
   Add integration → Porchcast.
5. Enter the carrier credentials (UPS from 0.3.0). A "Porchcast Packages"
   to-do list appears.
6. Add the to-do list to a dashboard.

## Carrier credentials

Porchcast checks each set of credentials by fetching a token when you save
them. To change them later, or to add them to an entry made by 0.1.0 or 0.2.0
(which had none): Settings → Devices & services → Porchcast → ⋮ →
**Reconfigure**. Don't remove and re-add the integration: removing it deletes
the stored packages.

If a carrier later rejects the credentials, HA shows a "Reauthentication
required" notice for Porchcast, and the items say "sign-in failed". Polling
for that carrier stops until you enter new credentials.

### UPS

1. Sign in at developer.ups.com with a ups.com account and create an app.
   (Porchcast's token request doesn't send a UPS account number; the spec
   makes it optional.)
2. Make sure the app includes the **Tracking** API.
3. Copy the app's **Client ID** and **Client Secret** into Porchcast.

"Use the UPS test environment (CIE)" is for `scripts/develop` only: CIE
returns canned data, not your packages.

### Trying a number from your machine

`scripts/live_check.py <number>` looks a number up with the real API, using
credentials from `.env` (`UPS_CLIENT_ID`, `UPS_CLIENT_SECRET`). `--save NAME`
writes the response, scrubbed of numbers, names and addresses, as a test
fixture. Never run it in a cloud session.

## Updates

After a release, Porchcast shows up under Settings → Updates once the
Marketplace next checks (up to 48 hours for a custom repository). Install it,
then restart; a repair offers to restart for you.

## Trying a branch (pre-release)

1. Make sure the branch's manifest version is already bumped above `main`'s.
2. Actions → Release → Run workflow → pick the branch. It publishes
   `vX.Y.ZbN` as a GitHub pre-release.
3. Settings → Devices & services → Marketplace → the Porchcast device → enable
   the *Pre-release* entity (first time only), turn it on, update, test.
4. Turn the *Pre-release* switch back off. When the final version is released,
   it replaces the pre-release as a normal update.

## Rollback

Preferred: revert on `main` and let a new patch release go out. Releases are
never deleted.

The Marketplace's ⋮ → *Install another version* can reinstall an older
release, but its docs say not to use it to go back after an update and to
restore a backup instead. Porchcast's stored data is designed so an older
version still loads newer data (unknown keys are ignored), so for Porchcast a
reinstall is expected to be safe; a backup restore is the fallback.

## Data

Stored data lives in HA's `.storage/` and is covered by normal HA backups.

## Escape hatch: sideload

`scripts/sideload` (added in a later version) will copy the integration to HA
over the SSH add-on and restart HA. It is for emergencies only: it leaves the
Marketplace's idea of the installed version out of date.
