# Self-update checker

candid can tell you when a new release is out and walk you through
upgrading. The checker is opt-out, not opt-in: it runs a lightweight check
on startup, but you can turn it off completely at any time.

## What it checks

The updater queries the public GitHub releases API
(`api.github.com/repos/K7S3/candid/releases`) for the latest release tag
and compares it to the installed `__version__`. That is the only network
call involved: no auth, no tokens, no account needed.

Security releases are flagged explicitly: if the release notes mention
security fixes, the notice says so, so you can decide how urgently to
upgrade.

## Commands

### `candid update check`

Check for a new release right now. Prints your installed version, the
latest release version, and a short preview of what changed (the release
notes headline). Exits quietly with a "you're up to date" message when
there is nothing newer.

### `candid update notes`

Show the changelog for the latest release (or for the version since your
installed one, when you are behind). Useful when you want the details
before deciding to upgrade.

### `candid update`

Upgrade guidance for your environment. By default it prints what to run,
for example:

```bash
git pull --ff-only origin main   # or: pip install -U candid
```

The exact steps depend on how candid is installed (git checkout vs pip);
`candid update` detects the install mode and prints the right commands.

Pass `--apply` and it performs the upgrade for you. Without `--yes` it
shows the exact command and asks for confirmation first (`Proceed?
[y/N]`); `--yes` skips the prompt for scripting. Before touching anything
it reminds you to back up first, preferably with
`python -m candid backup create` (falling back to a manual copy of
`candid_data/`, which also holds your update-check settings) so your
profile, tracker, and settings survive the upgrade.

### `candid update on` / `candid update off`

Turn the startup nudge on or off. `off` disables automatic checks entirely;
`on` re-enables them with the current frequency setting.

### `candid update version`

Print the installed version (same as `python -m candid --version`).

### Bare `candid update`

Without a subcommand, shows upgrade guidance: what version you have, what
is available, the changelog preview, and how to upgrade (including the
`--apply` option).

## Settings

Two settings control the behavior, stored in your candid data directory
(`candid_data/update_settings.json`; the data dir itself is overridable via
the `CANDID_DATA_DIR` environment variable):

- `updates.check_enabled` (true/false): master switch for automatic
  checks. Equivalent to `candid update on|off`.
- `updates.frequency` (daily / weekly / never): how often the startup
  nudge may contact the API. `never` disables automatic checks just like
  `check_enabled: false`.

A manual `candid update check` always runs regardless of these settings.

## Startup nudge

When automatic checks are enabled, candid performs a release check at
startup, at most as often as `updates.frequency` allows. The check uses a
short timeout and fails silently: if you are offline or the network is
slow, nothing is printed and startup continues normally. When a newer
release exists, you get a one-line nudge on stderr pointing at
`candid update`. (The nudge is skipped when you are already running a
`candid update` command.)

## Dashboard banner

The local dashboard (`candid dashboard`) shows a dismissible banner when
a newer release is available, with a link to the release notes and a
pointer to `python -m candid update`. The banner reads the cached check
only, so it adds no extra network traffic; the security-release flag is
shown in the banner too.

## Offline behavior

If there is no network access, every check path degrades to silence:
- the startup nudge is skipped,
- `candid update check` reports that it could not reach the release feed,
- `candid update` still shows upgrade guidance (it does not need the
  network to tell you how to upgrade).

Nothing is retried, cached, or queued.

## Privacy

The checker contacts only `api.github.com`. The request uses a plain
`candid-update-check` `User-Agent` header and nothing else: no personal
data, no profile contents, no tracker data, no telemetry. Disabling
automatic checks means zero network traffic from this feature.

## FAQ

**How do I fully disable it?**

```bash
candid update off
```

That sets `updates.check_enabled: false`, so no automatic check ever
runs. `candid update check` still works on demand when you want it.

**How often does it check?**

Set `updates.frequency` to `daily` (the default) or `weekly`. A startup
check happens at most once per period; manual `candid update check`
runs are always allowed.

**Does upgrading touch my data?**

No. Upgrades replace the code; your data lives in `candid_data/` and your
update-check settings live there too (`update_settings.json`). The
pre-upgrade reminder to back these up is there for safety, not because the
upgrade deletes anything.
