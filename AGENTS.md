# AGENTS.md

Porchcast is a Home Assistant custom integration that tracks UPS, FedEx and
USPS packages as items on one HA to-do list. It is personal software for one
household. Favor simple over general.

## The plan

The project brief and the session plan live on the `plan` branch, which is
never merged. Read them at the start of every session:

```sh
git fetch origin plan
git show origin/plan:docs/project-brief.md
git show origin/plan:docs/PLAN.md
```

Each session builds on `main`. A decision the plan doesn't cover is committed
to `plan` (for example in `docs/PLAN.md` or `docs/carriers.md`), not to the
feature branch.

## Default change workflow

Once a plan is approved, take changes all the way to merged without asking for
a review of the finished work:

1. Implement on the designated feature branch.
2. Verify locally: `scripts/lint` (ruff check, ruff format --check, mypy) and
   `scripts/test` (pytest). Add tests for every data-path change and every bug
   fix.
3. If the PR touches `custom_components/`, bump the version with
   `scripts/bump_version.py` (patch by default, `minor` for new features) as
   the last commit.
4. Open a PR and request a Copilot review. Address its feedback and push fixes.
5. Wait for CI to pass, then squash-merge.

Pause for the owner only when Copilot flags a real conceptual problem, or when
a question comes up that only the owner can answer. If Copilot can't review
(for example, its quota is used up), self-review the diff carefully and merge
on green CI if it's clean.

The PR body ends with what the owner needs to do in real HA: "Nothing",
"Update and check the to-do list", or "Test the pre-release first". When a
feature needs a real-HA look, merging isn't the end: schedule a check-in
(`send_later`) and ask how it went.

## Running checks in a cloud session

The session-start hook (`.claude/hooks/session-start.sh`) installs uv, the
Python in `.python-version` and the locked dependencies. Then:

```sh
scripts/lint          # ruff check, ruff format --check, mypy
scripts/test          # pytest; extra args go to pytest, e.g. scripts/test -k flow
```

If the hook didn't run, run it by hand:
`CLAUDE_CODE_REMOTE=true .claude/hooks/session-start.sh`.

## Cloud gotchas

- Only package registries and GitHub are reachable. home-assistant.io,
  developers.home-assistant.io, hacs.xyz and every carrier API are blocked.
  Read HA's APIs from the installed source under
  `.venv/lib/python3.14/site-packages/homeassistant/` instead.
- HA has moved off voluptuous: core config flows use `probatio` schemas. Copy
  patterns from a similar core integration in `.venv` (for example
  `local_todo` for the to-do entity), not from memory.
- `pytest-homeassistant-custom-component` (phcc) is published per HA release
  and can lag HA by weeks. The dev pins are the newest matching pair on PyPI,
  which may be older than the `hacs.json` minimum. Bump both together.
- The environment sets `UV_NATIVE_TLS`; uv warns it is deprecated. The hook
  maps it to `UV_SYSTEM_CERTS`. Ignore the warning if you see it.
- mypy: don't use `strict = true` in a per-module override; it turns off
  implicit re-export globally and breaks imports from HA packages. The strict
  flags are spelled out in `pyproject.toml`.

## Releases

- The version lives in `custom_components/porchcast/manifest.json` only (SemVer).
  `hacs.json` carries the minimum HA version.
- CI fails a PR that changes `custom_components/` without raising the version
  above the base branch's. PRs that only touch docs, tests or CI skip the bump.
- `release.yml` runs on push to `main`: it reruns CI and, if the manifest
  version has no tag yet, tags `vX.Y.Z` and publishes a GitHub release. A merge
  without a bump publishes nothing.
- Pre-release: run `release.yml` by hand (`workflow_dispatch`) on a PR branch
  that is already bumped. It publishes `vX.Y.ZbN` as a GitHub pre-release.
- See `DEPLOY.md` for installing and updating in HA.

## Repo rules

- HA moves fast. Before using an HA API, check the pinned version's source (and
  developer docs, where reachable), not memory, and heed deprecation warnings in
  test output.
- No network in tests. Every carrier test runs against recorded fixtures.
- Never run `scripts/live_check.py` or `scripts/sideload` in a cloud session.
- The repo is public. No credentials, real tracking numbers, names or addresses,
  including in fixtures and PR text.
- Never name any other project anywhere in this repo, its branches, issues, PRs
  or commit messages. If a comparison helps, say "a container-based,
  database-backed web app deployed to a VM via GitHub Actions."
- Pin every GitHub Action by commit SHA with its version in a comment.
