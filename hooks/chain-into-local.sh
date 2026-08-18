#!/usr/bin/env bash
# Chain ioc-guard into a repository that sets its own core.hooksPath.
#
# Such a repo (husky, .githooks, ...) overrides the global hooks directory, so
# the globally installed ioc-guard pre-push hook never runs there. This script
# inserts a call to it at the TOP of that directory's pre-push, leaving the
# repo's existing hook in place and intact.
#
# It inserts at the top, not the end, because git feeds the ref list on stdin:
# a hook appended after one that reads stdin would receive nothing and would
# scan nothing, silently. The inserted block captures stdin, runs ioc-guard
# with it, and hands the same list on to the repo's own hook.
#
# Usage: hooks/chain-into-local.sh [repo-path]
# Exit:  0 chained (or already chained), 2 operational error.
# Idempotent: running it twice changes nothing.
set -uo pipefail

repo="${1:-$PWD}"

if [ ! -d "$repo" ]; then
  echo "ioc-guard: ERROR: not a directory: $repo" >&2
  exit 2
fi

toplevel="$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null)"
if [ -z "${toplevel:-}" ]; then
  echo "ioc-guard: ERROR: not a git repository: $repo" >&2
  exit 2
fi

hookspath="$(git -C "$repo" config --local --get core.hooksPath 2>/dev/null)"
if [ -z "${hookspath:-}" ]; then
  echo "ioc-guard: ERROR: $toplevel has no repo-local core.hooksPath." >&2
  echo "  Nothing to chain into — the global hook already applies here." >&2
  exit 2
fi

case "$hookspath" in
  /*) dir="$hookspath" ;;
  *)  dir="$toplevel/$hookspath" ;;
esac

# husky owns .husky/_ and regenerates it on `husky install`, which would wipe
# anything written there. Its wrapper dispatches to ../<hook-name>, so chain
# into the file husky itself expects the project to own.
case "$dir" in
  */.husky/_)
    dir="${dir%/_}"
    echo "ioc-guard: core.hooksPath is husky's generated .husky/_; chaining into $dir instead," >&2
    echo "  which husky dispatches to and does not overwrite." >&2
    ;;
esac

target="$dir/pre-push"

if [ -f "$target" ] && grep -q '>>> ioc-guard' "$target" 2>/dev/null; then
  echo "ioc-guard: already chained into $target — nothing to do."
  exit 0
fi

block_file="$(mktemp)" || { echo "ioc-guard: ERROR: mktemp failed." >&2; exit 2; }
cat > "$block_file" <<'BLOCK'
# >>> ioc-guard (chained) — do not edit between these markers >>>
# This repo sets its own core.hooksPath, so the global ioc-guard pre-push hook
# does not run. Call it here, first, and pass the ref list on untouched.
__ioc_guard_hook="${IOC_GUARD_HOOKS_DIR:-$HOME/.git-hooks}/pre-push"
if [ -x "$__ioc_guard_hook" ]; then
  __ioc_guard_refs="$(mktemp)" || exit 2
  cat > "$__ioc_guard_refs"
  "$__ioc_guard_hook" "$@" < "$__ioc_guard_refs"
  __ioc_guard_rc=$?
  if [ "$__ioc_guard_rc" != "0" ]; then
    rm -f "$__ioc_guard_refs"
    exit "$__ioc_guard_rc"
  fi
  exec < "$__ioc_guard_refs"
  rm -f "$__ioc_guard_refs"
fi
# <<< ioc-guard <<<
BLOCK

mkdir -p "$dir" || { rm -f "$block_file"; echo "ioc-guard: ERROR: cannot create $dir" >&2; exit 2; }

if [ ! -f "$target" ]; then
  {
    echo '#!/usr/bin/env bash'
    cat "$block_file"
  } > "$target" || { rm -f "$block_file"; echo "ioc-guard: ERROR: cannot write $target" >&2; exit 2; }
  chmod 0755 "$target"
  rm -f "$block_file"
  echo "ioc-guard: created $target with the ioc-guard call."
  exit 0
fi

first="$(head -n 1 "$target")"
case "$first" in
  '#!'*)
    case "$first" in
      *sh|*sh\ *|*bash|*bash\ *|*zsh|*zsh\ *|*dash|*dash\ *) ;;
      *)
        echo "ioc-guard: ERROR: $target is not a shell script ($first)." >&2
        echo "  Refusing to edit it. Chain ioc-guard manually, or run:" >&2
        echo "      git -C $toplevel config --local --unset core.hooksPath" >&2
        rm -f "$block_file"
        exit 2 ;;
    esac
    merged="$(mktemp)" || { rm -f "$block_file"; exit 2; }
    head -n 1 "$target" > "$merged"
    cat "$block_file" >> "$merged"
    tail -n +2 "$target" >> "$merged"
    ;;
  *)
    # husky v9 hook files carry no shebang; they are still sh scripts.
    merged="$(mktemp)" || { rm -f "$block_file"; exit 2; }
    cat "$block_file" > "$merged"
    cat "$target" >> "$merged"
    ;;
esac

cat "$merged" > "$target" || {
  rm -f "$block_file" "$merged"
  echo "ioc-guard: ERROR: cannot write $target" >&2
  exit 2
}
chmod 0755 "$target"
rm -f "$block_file" "$merged"
echo "ioc-guard: chained into $target (existing hook preserved)."
exit 0
