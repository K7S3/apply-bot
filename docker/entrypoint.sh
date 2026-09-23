#!/bin/sh
# candid Docker entrypoint.
# - Ensures the data dir exists and is writable.
# - Offers the interactive onboarding wizard on first run when attached to a TTY.
# - execs the requested command (defaults to --help).
#
# Set CANDID_SKIP_WIZARD=1 to skip the wizard even on a TTY.

set -u

DATA_DIR="${CANDID_DATA_DIR:-/data}"

# 1. Data directory: create it if missing, warn if we cannot write to it.
if [ ! -d "$DATA_DIR" ]; then
    if ! mkdir -p "$DATA_DIR" 2>/dev/null; then
        echo "candid-entrypoint: warning: cannot create data dir '$DATA_DIR'." >&2
    fi
fi
if [ -d "$DATA_DIR" ] && [ ! -w "$DATA_DIR" ]; then
    echo "candid-entrypoint: warning: data dir '$DATA_DIR' is not writable; " \
         "your profile and tracker data may not persist." >&2
fi

# 2. First-run onboarding: interactive wizard on a TTY, quickstart hint otherwise.
if [ ! -f "$DATA_DIR/profile.json" ]; then
    if [ -t 0 ] && [ -z "${CANDID_SKIP_WIZARD:-}" ]; then
        echo "candid: no profile found in '$DATA_DIR'. Starting the onboarding wizard..."
        echo "candid: (set CANDID_SKIP_WIZARD=1 to skip this step)"
        python -m candid onboard || {
            echo "candid-entrypoint: warning: onboarding wizard exited with status $?; continuing." >&2
        }
    else
        echo "candid: quickstart — no profile yet. Run:" >&2
        echo "candid:   docker run --rm -it -v candid-data:$DATA_DIR candid onboard" >&2
        echo "candid: or mount a CANDID_DATA_DIR volume and pass your own command." >&2
    fi
fi

# 3. Run the requested command; default to --help when nothing was given.
if [ "$#" -eq 0 ]; then
    set -- --help
fi

exec python -m candid "$@"
