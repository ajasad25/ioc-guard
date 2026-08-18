#!/usr/bin/env bash
# Install ioc-guard as the global git pre-push hook.
#
#   hooks/install.sh                 install (or refresh) and then report any
#                                    repository that overrides core.hooksPath
#   hooks/install.sh --scan-repos [dir ...]
#                                    only report those repositories; install
#                                    nothing and change no configuration
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${IOC_GUARD_HOOKS_DIR:-$HOME/.git-hooks}"
ENGINE="$DEST/ioc-guard"

if [ "${1:-}" = "--scan-repos" ]; then
  shift
  IOC_GUARD_HOOKS_DIR="$DEST" exec "$SRC/hooks/scan-hookspath.sh" "$@"
fi

existing="$(git config --global --get core.hooksPath || true)"
if [ -n "$existing" ] && [ "$existing" != "$DEST" ]; then
  echo "ERROR: core.hooksPath is already set to '$existing'." >&2
  echo "Merge the hooks manually rather than letting this script clobber it." >&2
  exit 1
fi

mkdir -p "$ENGINE"
# Remove first: cp -R merges into an existing tree, so a refresh would leave
# behind modules deleted upstream and stale __pycache__ shadowing new code.
rm -rf "$ENGINE/ioc_guard"
cp -R "$SRC/ioc_guard" "$ENGINE/"
rm -rf "$ENGINE/ioc_guard/__pycache__"
cp "$SRC/iocs.txt" "$ENGINE/iocs.txt"
install -m 0755 "$SRC/hooks/pre-push" "$DEST/pre-push"
git config --global core.hooksPath "$DEST"

echo "Installed. core.hooksPath = $(git config --global --get core.hooksPath)"
echo "Refresh indicators later with: hooks/install.sh"
echo

# A repo-local core.hooksPath silently overrides the global one. Without this
# report the install would claim coverage it does not have.
set +e
IOC_GUARD_HOOKS_DIR="$DEST" "$SRC/hooks/scan-hookspath.sh"
scan_rc=$?
set -e
if [ "$scan_rc" = "1" ]; then
  echo
  echo "Installation finished, but the repositories listed above are NOT covered." >&2
fi
exit 0
