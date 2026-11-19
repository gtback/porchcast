#!/usr/bin/env bash
# Set up a Claude Code cloud session: uv, the pinned Python, and the locked
# dependencies. Does nothing on a local machine.
#
# Sandbox notes (also in AGENTS.md, "Cloud gotchas"):
# - The network allows package registries, GitHub, hacs.xyz and the
#   home-assistant.io docs hosts. PyPI and uv's Python downloads
#   (python-build-standalone on GitHub) work through the proxy.
# - Carrier APIs are blocked; tests use recorded fixtures only.
# - The environment sets UV_NATIVE_TLS, which uv 0.11+ warns is deprecated.
#   We map it to UV_SYSTEM_CERTS (needed so uv trusts the proxy's CA) and unset
#   the old name to keep output quiet.
set -euo pipefail

if [[ "${CLAUDE_CODE_REMOTE:-}" != "true" ]]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

if [[ -n "${UV_NATIVE_TLS:-}" ]]; then
  export UV_SYSTEM_CERTS="${UV_NATIVE_TLS}"
  unset UV_NATIVE_TLS
  if [[ -n "${CLAUDE_ENV_FILE:-}" ]]; then
    {
      echo "export UV_SYSTEM_CERTS=${UV_SYSTEM_CERTS}"
      echo "unset UV_NATIVE_TLS"
    } >> "${CLAUDE_ENV_FILE}"
  fi
fi

if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --quiet uv >&2
fi

# .python-version pins the version; uv downloads it if missing.
uv python install >&2
uv sync --locked >&2

echo "Porchcast dev environment ready: run scripts/lint and scripts/test."
