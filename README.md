# ioc-guard

Detects the `A9-1800-1` / EtherHiding worm in git repositories. See the incident
write-up for background on the campaign.

## Updating indicators

Edit `iocs.txt` — one Python regex per line, matched case-insensitively. Blank
lines and `#` comments are ignored. Every repo calling this workflow picks up the
change on its next run; nothing else needs a commit.

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

## Local use

    python3 -m ioc_guard --root /path/to/repo

Exit codes: `0` clean, `1` findings, `2` scanner error. `2` is never a pass.

## Client-side hook

    ./hooks/install.sh

Blocks force-pushes and pushes containing indicators, from any repo on this
machine. Override for the one legitimate case (cleaning an infected repo) with
`IOC_GUARD=off git push ...`; overrides are logged.
