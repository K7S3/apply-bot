"""Email the run summary to Sree via SMTP.

SMTP settings live in profile.yaml; the password comes ONLY from the
SMTP_PASSWORD environment variable. If SMTP is not configured, the
mailer skips gracefully (the run log still has everything).
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage


class MailError(Exception):
    """Raised when the summary email cannot be sent."""


def build_summary(results: list[dict], dry_run: bool) -> str:
    mode = "DRY-RUN (nothing was actually submitted)" if dry_run else "LIVE RUN"
    lines = [
        f"Hi! Here's the apply-bot summary ({mode}):",
        "",
    ]
    for r in results:
        status = r.get("status", "?")
        reason = r.get("reason", "")
        lines.append(f"- {r.get('role', '?')} @ {r.get('company', '?')}: {status}")
        if reason:
            lines.append(f"    {reason}")
    lines += [
        "",
        "Full details are in the run log (output/run_<timestamp>.log).",
        "Rows marked needs_manual need a human: login wall, CAPTCHA, or a custom form.",
        "",
        "— applybot",
    ]
    return "\n".join(lines)


def send_summary(profile: dict, results: list[dict], dry_run: bool) -> bool:
    """Send the summary email. Returns True if sent, False if skipped.

    Skips (with a printed note) when smtp settings or SMTP_PASSWORD are missing.
    Raises MailError on SMTP failures.
    """
    import os  # local import keeps module import light

    smtp = (profile or {}).get("smtp") or {}
    host = smtp.get("host")
    port = int(smtp.get("port", 587))
    user = smtp.get("username")
    to_addr = smtp.get("to") or (profile or {}).get("email")
    password = os.environ.get("SMTP_PASSWORD")

    if not (host and user and to_addr):
        print("[mailer] SMTP not configured in profile.yaml — skipping email.")
        return False
    if not password:
        print("[mailer] SMTP_PASSWORD env var not set — skipping email.")
        return False

    mode = "dry-run" if dry_run else "live"
    msg = EmailMessage()
    msg["Subject"] = f"[applybot] Job applications summary ({mode})"
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(build_summary(results, dry_run))

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        raise MailError(f"SMTP send failed: {exc}") from exc

    print(f"[mailer] Summary sent to {to_addr}")
    return True
