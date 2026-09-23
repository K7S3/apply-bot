#!/usr/bin/env sh
# candid one-liner installer: curl -sSL https://raw.githubusercontent.com/K7S3/candid/main/scripts/install.sh | sh
#
# Detects python3, installs candid (prefers pipx, falls back to
# `pip install --user candid`), then verifies with `candid --version`.
set -eu

log() { printf '%s\n' "$*"; }

if ! command -v python3 >/dev/null 2>&1; then
    log "ERROR: python3 not found. Install Python 3.10+ first, then re-run."
    exit 1
fi
log "Found: $(python3 --version 2>&1)"

installed=0

if command -v pipx >/dev/null 2>&1; then
    log "Installing with pipx..."
    pipx install candid
    installed=1
elif python3 -m pipx --version >/dev/null 2>&1; then
    log "Installing with pipx..."
    python3 -m pipx install candid
    installed=1
fi

if [ "$installed" -eq 0 ]; then
    log "pipx not found; falling back to 'pip install --user candid'."
    python3 -m pip install --user candid
fi

# Make sure the user install dir is on PATH for the verification step.
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *)
        if [ -x "$HOME/.local/bin/candid" ]; then
            export PATH="$HOME/.local/bin:$PATH"
        fi
        ;;
esac

log "Verifying install..."
if command -v candid >/dev/null 2>&1; then
    candid --version
    log "Done. Run 'candid --help' to get started."
else
    log "ERROR: installed but 'candid' is not on PATH."
    log "Add this to your shell profile and re-open your terminal:"
    log '  export PATH="$HOME/.local/bin:$PATH"'
    exit 1
fi
