# ioc-guard

Detects the `A9-1800-1` / EtherHiding worm in git repositories. See the incident
write-up for background on the campaign.

Three components:

- **`ioc_guard/`** — a stdlib-only Python scanner: the literal indicators in
  `iocs.txt`, structural heuristics, and rules that need a base revision.
- **`.github/workflows/scan.yml`** — a reusable workflow each repo calls.
- **`hooks/pre-push`** — the only component that *prevents* rather than detects.

## Updating indicators

Edit `iocs.txt` — one Python regex per line, matched case-insensitively. Blank
lines and `#` comments are ignored. Every repo calling this workflow picks up the
change on its next run; nothing else needs a commit.

The scanner correctly flags its own indicator list, so pushing an update to
`iocs.txt` — or to any document that quotes the markers — needs:

    IOC_GUARD_SKIP_SCAN=1 git push

That skips **only** the content scan. The force-push and branch-deletion blocks
and the `.gitignore`/CRLF rules all still apply. Do not use `IOC_GUARD=off` for
this: it disables *every* check (see below).

**Never add the Ethereum address in `0x`-prefixed form.** The payload stores it as
`\u00..` escape sequences, so a `0x` search returns a false clean on genuinely
infected files. Use the bare hex form.

## Onboarding a repository

Add `.github/workflows/ioc-scan.yml`:

    name: IOC Scan
    on:
      push:
      pull_request:
      schedule:
        - cron: '17 4 * * *'
    jobs:
      ioc-scan:
        uses: ajasad25/ioc-guard/.github/workflows/scan.yml@main

The `schedule` trigger is not optional padding: it re-scans branch tips that were
tampered with in place, which is the mutation `push` events miss when history is
rewritten.

On `pull_request` the workflow diffs against the base branch; on `push` it diffs
against the previous tip (`github.event.before`) when that commit is still
present. Those diffs are what enable the `.gitignore` and CRLF rules — the two
aimed at the incident's actual collateral damage.

## Local use

    python3 -m ioc_guard --root /path/to/repo

Exit codes: `0` clean, `1` findings, `2` scanner error. `2` is never a pass.

Useful flags: `--base-ref` / `--head-ref` enable the diff rules, `--diff-only`
runs just those rules without a whole-tree walk, `--json` and `--summary` write
machine and markdown reports.

## Client-side hook

    ./hooks/install.sh

Installs a global `pre-push` hook that blocks branch deletions, non-fast-forward
pushes, and pushes carrying indicators — from any repo on this machine. It scans
every commit in the range being pushed, not just the tip, because the payload
"rewrote itself out of the working tree after running, to hide"; ranges longer
than 50 commits are truncated with a warning that names how many were skipped.

Overrides:

| Variable | Effect |
|---|---|
| `IOC_GUARD_SKIP_SCAN=1` | Skips the content scan only. Force-push and deletion blocks still apply. Use this to publish indicator updates. |
| `IOC_GUARD=off` | Disables **everything**, including the force-push and deletion blocks. Logged to `~/.git-hooks/override.log`. |

### Repositories that set their own `core.hooksPath`

`git config --local core.hooksPath` **overrides** the global value, so a repo
that uses husky or a `.githooks/` directory does not run the global ioc-guard
hook at all. `install.sh` reports every such repository after installing; you can
also list them at any time without installing anything:

    hooks/scan-hookspath.sh [dir ...]     # defaults to ~/src ~/Desktop ~/Documents
    hooks/install.sh --scan-repos         # same report, installs nothing

Two supported remedies, per repository:

    hooks/chain-into-local.sh <repo>                    # keep the repo's hooks, add ours
    git -C <repo> config --local --unset core.hooksPath # drop the override

`chain-into-local.sh` inserts the ioc-guard call at the **top** of that
directory's `pre-push`, because git delivers the ref list on stdin and a call
appended after a hook that reads stdin would receive nothing and scan nothing.
The inserted block hands the same ref list on to the repo's own hook. It is
idempotent, and it refuses to edit a hook that is not a shell script.

Until one of the two remedies is applied, those repositories have **no
client-side protection**. The workflow still scans them server-side.

## What this does not catch

Be honest with yourself about the boundary of this control.

- **`git push --no-verify` bypasses the hook entirely.** So does any push that
  does not go through this machine — a web edit, a merge performed in the GitHub
  UI, CI pushing on your behalf, or a second clone where the hook is not
  installed. The hook is a guard rail, not a gate.
- **A green check means "no known indicators", not "clean".** The literal list in
  `iocs.txt` is the primary detector, and it only knows what the incident report
  recorded. A rewritten payload with new infrastructure passes it.
- **The heuristics only catch a lazy repack.** A >3000 character line, dense
  `\u00XX` escapes, 300+ spaces before a closing `};`, `child_process` with
  `windowsHide` — every one of those is avoidable by an attacker who bothers.
- **The structural heuristics run on an allowlist of names, not on everything.**
  Only files whose name is in `SOURCE_SUFFIXES` / `SOURCE_BASENAMES` in
  `ioc_guard/walk.py` — JavaScript and TypeScript and the component formats that
  compile to it, `.json`/`.yml`/`.toml`/`.env`, shell/batch/PowerShell/Python,
  `*.config.*`, `Dockerfile`, `Makefile` and friends — get structural analysis.
  **Every other file type is covered by the literal `iocs.txt` list alone**, which
  is most of them: `.rb`, `.go`, `.java`, `.php`, `.rs`, `.c`, `.sql`, anything
  with no extension that is not on the list. The length and density rules are
  narrower still — they are additionally waived for `.svg`, `.html`, `.md`,
  `.json`, `.csv`, `.lock`, `.snap`, `*.min.js` and build output, where they only
  ever produced noise. Widening the allowlist is a one-line change; if your repos
  use a format that is not on it, add it.
- **`node_modules/` and `vendor/` are never scanned** at any depth, and the
  top-level `.ioc-guard/` checkout is skipped. That is a deliberate
  false-positive-and-volume trade; it is also a hiding place. Build output
  (`dist/`, `build/`, `coverage/`, `.next/`) *is* scanned for literal indicators.
- **Server-side scans see only what is pushed.** A repo that never runs the
  workflow, or a branch pushed before onboarding, is unexamined.
- **Detection is not remediation.** The incident report is explicit: any machine
  that ever ran a build of an infected repo must be treated as compromised,
  whether or not the file is still there.

## Tests

    python3 -m pytest tests/ -q

`pytest` and `PyYAML` are test-only dependencies; the scanner and the hook use
the standard library only, and target Python 3.9.
