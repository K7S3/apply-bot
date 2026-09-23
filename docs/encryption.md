# Encryption in candid

candid can encrypt your data at rest (profile, tracker, offers, Gmail
proposals, prep packs, tailored outputs) with a passphrase you choose.
Everything is local: AES-256-GCM, keys derived from your passphrase with
PBKDF2-HMAC-SHA256 (600,000 iterations). There is no server, no account,
and no backdoor.

Requires the optional `cryptography` package (`pip install cryptography`);
without it, the crypto commands fail with a clear message and everything
else keeps working.

## Threat model

What this protects against:

- **Stolen or lost disk while locked.** Encryption keys are derived from
  your passphrase; nothing stored on disk helps an attacker without it.
- **An unattended terminal.** `lock` (or the session timeout) forgets the
  cached passphrase, so `track list` and friends refuse to run until you
  `unlock` again.

What this does NOT protect against:

- **A compromised live account or machine while you are unlocked.** If
  someone is already logged in as you and the session is active, your data
  is readable. Lock when you walk away.
- **Malware / keyloggers / shoulder surfing.** Standard endpoint hygiene
  still applies.

Be honest about one more thing: **while unlocked, the session file holds
your passphrase** at `~/.config/candid/session.json` (mode `0o600`,
owner-only) until you `lock` or the timeout expires. That is the price of
not typing the passphrase on every command. `crypto migrate` encrypts
data files; it does not change the session design.

## Setup walkthrough

```bash
python -m candid crypto init      # choose a passphrase (strength meter shown)
python -m candid unlock           # verify it, start a session
python -m candid crypto migrate   # encrypt your existing data files
python -m candid lock             # forget the passphrase when you're done
```

After `init`, each new shell session needs `unlock` before data commands
run. Locking is automatic when the session expires (default 30 minutes).

## Command reference

| Command | What it does |
|---|---|
| `crypto init [--force]` | Set the encryption passphrase for the first time. Shows a strength meter; score < 2 needs `--force`. |
| `crypto change [--force]` | Verify the current passphrase, then set a new one. |
| `crypto verify` | Prompt for a passphrase and print `ok` / `fail`. |
| `crypto migrate [--decrypt]` | Encrypt every sensitive plaintext file (verifying each copy, then secure-wiping the original). `--decrypt` reverses it. |
| `crypto backup <name>` | Zip the data dir, encrypt it, store `<name>.candidbak` in the backups dir. |
| `crypto restore <name> [--force]` | Decrypt a backup back into the data dir. Snapshots current data first; refuses if current files are newer unless `--force`. |
| `crypto status [--json]` | Keystore, session, per-file encryption, and backup state. |
| `crypto audit [--limit N] [--json]` | Audit log of keystore/session/backup events, newest first. |
| `lock` | Lock now: forget the cached passphrase immediately. |
| `unlock [--timeout MINUTES]` | Verify the passphrase and cache it for a timed session (default 30 min). |

The passphrase is never accepted as a CLI argument: it comes from
interactive prompts or the unlocked session, so it can't leak into shell
history. Nothing here ever logs or prints a passphrase.

## Encrypted backups

`crypto backup work-laptop` creates an encrypted, self-contained copy of
your data dir (including the encrypted files). The backup envelope itself
only needs the passphrase to decrypt, but the CLI restore command expects
a keystore to exist on that machine — so on a new machine, run
`crypto init` with the *same* passphrase first, then `crypto restore`.

The audit log records init / unlock / lock / migrate / backup / restore
events (timestamps and outcomes, never secrets).

## Auto-expiry config

`lock_timeout_minutes` (default `30`) controls how long `unlock` lasts.
Set it in your candid config, or override per session:

```bash
python -m candid unlock --timeout 10   # 10-minute session this time
```

`lock` always forgets the passphrase immediately, regardless of the timer.

## FAQ

**I forgot my passphrase. Can you recover my data?**
No. The keystore only holds a verifier, not the key, and there is no
backdoor. Encrypted data without the passphrase is unrecoverable. Keep the
passphrase in a password manager.

**How do I change my passphrase?**
`python -m candid crypto change`. It verifies the old one first, so a
typo in the "current" field fails safely instead of locking you out.

**How do I remove encryption entirely?**
`python -m candid crypto migrate --decrypt` converts everything back to
plaintext, then delete the keystore (`~/.config/candid/keystore.json`)
and the session file. Your data is plaintext again, including backups.

**Does `lock` wipe the session file securely?**
It deletes the file (unlinking, so the passphrase doesn't linger in the
filesystem journal as a "deleted but recoverable" write any longer than
necessary) and the file itself is `0o600`. On SSDs, no software deletion
is a guarantee against a determined forensic attacker with the raw flash;
the realistic protection is that a locked session leaves no *readable*
copy of the passphrase on the mounted filesystem.

**Why does `crypto status` show files as "missing"?**
It lists the sensitive files it knows about (profile, tracker, offers,
Gmail proposals); "missing" just means you haven't created that file yet.
