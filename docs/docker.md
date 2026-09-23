# Running candid with Docker

The one-command way to run candid without installing Python locally. Docker
Compose builds the image, runs the interactive onboard wizard on first run,
and starts the dashboard. Your data persists in a Docker named volume.

## Prerequisites

- **Docker** (Docker Desktop, or Docker Engine + the Compose plugin). That's
  it. No Python install, no `pip`, no virtualenv on your host.

## Quickstart

```bash
git clone https://github.com/K7S3/candid.git
cd candid
docker compose up --build
```

On first run the CLI service runs the **onboard wizard**: point it at your
résumé (see [Importing your files](#importing-your-files) below) and it
builds your profile. After the wizard, Compose starts the **dashboard** on
<http://localhost:8765>.

Use `docker compose up --build -d` to run it detached, and
`docker compose down` to stop. Removing containers never deletes your data
(see [Data persistence](#data-persistence)).

## Using the CLI inside the container

Run any `python -m candid` command through the CLI service with `docker
compose run`. Data lives in the shared named volume, so the CLI and the
dashboard see the same profile, tracker, and imports:

```bash
# Run the onboard wizard again (re-import a résumé)
docker compose run --rm candid onboard --resume /imports/my_resume.pdf

# Score a job description
docker compose run --rm candid match --jd samples/candid/sample_jd.txt \
    --company "Acme Corp" --role "Senior Data Scientist"

# Track an application and build a prep pack
docker compose run --rm candid track add --company "Acme Corp" \
    --role "Senior Data Scientist"
docker compose run --rm candid prep --company "Acme Corp" \
    --role "Senior Data Scientist" --app-id 1

# Interactive shell inside the container
docker compose run --rm candid bash
```

The `Makefile` wraps the common Compose commands (build, up, down, logs,
one-off CLI runs, shell) as short targets; see the `Makefile` for the exact
target names.

## Data persistence

Inside the container, candid reads and writes everything under
`CANDID_DATA_DIR`, which the image sets to **`/data`** (a declared Docker
volume). The Compose setup mounts that as a **named volume**
(`candid-data`), so:

- Stopping, rebuilding, or removing containers keeps your data. Only
  `docker volume rm candid-data` (or `docker compose down -v`) deletes it.
- You can wipe your candid data the same way as a local install: delete the
  volume.
- **`docker compose up` with a rebuild after code changes**: `docker compose
  up --build` rebuilds the image but keeps the volume, so your profile and
  tracker survive upgrades.

**Bind mount (dev mode) vs named volume.** The production Compose file uses
the named volume. For development, `compose.dev.yml` overlays a bind mount of
your checkout onto the container so code edits take effect immediately
without rebuilding:

```bash
docker compose -f docker-compose.yml -f compose.dev.yml up --build
```

In dev mode your data still lives in the named volume unless you also bind
mount `candid_data/`; see `compose.dev.yml` for the exact mounts.

**Back up your data.** The named volume is not part of your git repo. Back
it up before major changes:

```bash
docker run --rm -v candid-data:/data -v "$(pwd)":/backup \
    alpine tar czf /backup/candid-data-backup.tar.gz -C /data .
```

To restore: `docker run --rm -v candid-data:/data -v "$(pwd)":/backup alpine
tar xzf /backup/candid-data-backup.tar.gz -C /data`.

## Importing your files

The container can't see your host's files unless you share them. Two ways:

1. **Bind-mount an imports folder.** The Compose file includes a commented
   `./imports` bind mount: uncomment the `- ./imports:/imports:ro` line under
   `volumes:` in `docker-compose.yml`, create the folder on your host, and drop
   your résumé PDF, Gmail Takeout `.mbox`, or LinkedIn ZIP into it. Reference
   the files from CLI commands or the wizard as `/imports/...`:

   ```bash
   mkdir -p imports
   cp ~/Downloads/my_resume.pdf imports/
   cp ~/Downloads/linkedin_export.zip imports/
   docker compose run --rm candid onboard --resume /imports/my_resume.pdf
   docker compose run --rm candid import \
       --linkedin-zip /imports/linkedin_export.zip --mode merge
   ```

2. **Dashboard upload.** Open <http://localhost:8765> and use the
   **Import your data** section to drag-and-drop `.mbox` / `.zip` files
   directly. No host folder needed.

The sample data under `samples/` is baked into the image, so
`samples/candid/sample_resume.md` works out of the box for a first dry run.

## Dashboard access

The dashboard service listens on port **8765** and Compose publishes it to
your host, so the UI lives at <http://localhost:8765> on your machine.

Inside the container the dashboard runs with `--host 0.0.0.0` (required for
the container's port to be reachable from the host). That bind is scoped to
the container's own network namespace: only what you publish in the Compose
file is reachable from your host or LAN. The dashboard is still the local
single-user UI, not a multi-user service.

## Troubleshooting

**Permissions on `/data`.** The image runs as a **non-root user**, so if you
bind-mount your own host directory over `/data`, the files in it must be
writable by that user (UID 1000). Fix with `chown -R 1000:1000
candid_data/` on the host before mounting, or keep using the named volume
(which is created with the right ownership automatically).

**The wizard never ran.** The entrypoint runs the interactive onboard wizard
only on first run (when no profile exists yet). Setting
`CANDID_SKIP_WIZARD=1` skips it, which is useful in CI or when you seed your
data another way:

```bash
docker compose run --rm -e CANDID_SKIP_WIZARD=1 candid onboard
```

To onboard later (or re-onboard with a different résumé), just run
`docker compose run --rm candid onboard`.

**Code changes not showing up.** If you edited Python files on your host but
aren't using `compose.dev.yml`, the running image still has the old code.
Rebuild: `docker compose up --build`.

**Port 8765 already in use.** Change the published port in
`docker-compose.yml` (`"8766:8765"`) and open
<http://localhost:8766> instead.

**Starting from scratch.** `docker compose down -v` removes containers *and*
the named volume. Back up first if you want your data (see above).

## Security notes

- The image runs as a **non-root user**; nothing in it needs root at runtime.
- **No secrets in the image.** candid needs no API keys or credentials at
  all (its only network calls are the public job feeds and pages *you*
  point it at). Don't bake anything sensitive into the image or Compose
  file. Your résumé and exports live in the data volume, which stays on
  your machine.
- The dashboard binds `0.0.0.0` **only inside the container network**.
  Nothing listens on your host beyond the ports you explicitly publish in
  the Compose file. Don't publish the dashboard port to the open internet.
- Images are built locally (`candid:local`) from the `Dockerfile` in this
  repo. Review it before building, as you would any container.
