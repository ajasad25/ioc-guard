#!/usr/bin/env bash
# Report every git repository that sets its OWN core.hooksPath.
#
# Why this exists: `git config --local core.hooksPath` overrides the global
# value, so a globally installed pre-push hook never runs in those repos. They
# get zero client-side protection, silently, and nothing at install time says
# so. Read-only: this script never changes any repository's configuration.
#
# Usage: hooks/scan-hookspath.sh [dir ...]
# Exit:  0 no collisions, 1 collisions found, 2 operational error.
set -uo pipefail

DEST="${IOC_GUARD_HOOKS_DIR:-$HOME/.git-hooks}"
MAXDEPTH="${IOC_GUARD_SCAN_DEPTH:-4}"

dirs=("$@")
if [ "${#dirs[@]}" -eq 0 ]; then
  dirs=("$HOME/src" "$HOME/Desktop" "$HOME/Documents")
fi

if ! command -v git >/dev/null 2>&1; then
  echo "ioc-guard: ERROR: git not found on PATH." >&2
  exit 2
fi

found=0
report=""

for d in "${dirs[@]}"; do
  [ -d "$d" ] || continue
  while IFS= read -r gitpath; do
    [ -z "${gitpath:-}" ] && continue
    repo="$(dirname "$gitpath")"
    hp="$(git -C "$repo" config --local --get core.hooksPath 2>/dev/null)"
    [ -z "${hp:-}" ] && continue
    # A repo that already points at our own hooks directory is fine.
    if [ "$hp" = "$DEST" ]; then continue; fi
    found=$((found + 1))
    report="$report$(printf '  %-34s local core.hooksPath = %s\n     %s' \
      "$(basename "$repo")" "$hp" "$repo")
"
  done < <(find "$d" -maxdepth "$MAXDEPTH" -name .git \( -type d -o -type f \) 2>/dev/null)
done

if [ "$found" = "0" ]; then
  echo "ioc-guard: no repository sets its own core.hooksPath — the global hook covers all of them."
  exit 0
fi

cat >&2 <<EOF

ioc-guard: WARNING — $found repositor(y/ies) set their own core.hooksPath.
A repo-local core.hooksPath overrides the global one, so the ioc-guard pre-push
hook will NOT run in these. They have no client-side protection at all:

$report
Two supported remedies, per repository:

  1. Chain ioc-guard from the hook directory the repo already uses:
         hooks/chain-into-local.sh <repo>
     This inserts an ioc-guard call at the top of that directory's pre-push,
     leaving the repo's existing hook in place.

  2. Drop the repo-local override so the global hook applies:
         git -C <repo> config --local --unset core.hooksPath
     Only safe if nothing depends on the repo's own hooks.

Until one of these is done, treat those repositories as unprotected on the
client side. The GitHub workflow still scans them server-side.
EOF
exit 1
