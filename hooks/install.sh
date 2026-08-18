#!/usr/bin/env bash
# Install ioc-guard as the global git pre-push hook.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HOME/.git-hooks"
ENGINE="$DEST/ioc-guard"

existing="$(git config --global --get core.hooksPath || true)"
if [ -n "$existing" ] && [ "$existing" != "$DEST" ]; then
  echo "ERROR: core.hooksPath is already set to '$existing'." >&2
  echo "Merge the hooks manually rather than letting this script clobber it." >&2
  exit 1
fi

mkdir -p "$ENGINE"
cp -R "$SRC/ioc_guard" "$ENGINE/"
cp "$SRC/iocs.txt" "$ENGINE/iocs.txt"
install -m 0755 "$SRC/hooks/pre-push" "$DEST/pre-push"
git config --global core.hooksPath "$DEST"

echo "Installed. core.hooksPath = $(git config --global --get core.hooksPath)"
echo "Refresh indicators later with: hooks/install.sh"
