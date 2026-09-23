"""Secure system-design drills for the security-engineer interview track.

Each drill is a classic security-flavored system-design prompt with a
rubric: a checklist of the security considerations a strong answer
covers. Use run_drill() for an interactive walkthrough, or
score_checklist() to self-score a completed answer. Content is written
to be timeless: fundamentals and patterns, not version-specific trivia.
"""

from __future__ import annotations

DRILLS: list[dict] = [
    {
        "id": "secure-auth-saas",
        "title": "Secure authentication for a SaaS app",
        "prompt": (
            "Design the authentication and session management for a "
            "multi-user SaaS application with web and mobile clients. "
            "The system must support login, logout, password reset, and "
            "per-user sessions across devices, and it must resist common "
            "attacks like credential stuffing, session hijacking, and "
            "account takeover. Explain your data model, token strategy, "
            "and how you handle secrets and PII."
        ),
        "checklist": [
            "Hash passwords with a slow, memory-hard KDF (bcrypt, scrypt, "
            "or argon2id) plus a per-user salt; never reversible "
            "encryption or plain MD5/SHA.",
            "Mitigate credential stuffing with rate limiting, CAPTCHA or "
            "risk-based step-up after repeated failures, and breach-"
            "corpus password checks on signup and reset.",
            "Use short-lived access tokens with rotating refresh tokens "
            "stored HttpOnly and Secure; support per-device session "
            "revocation on logout and password change.",
            "Offer MFA (TOTP or WebAuthn/passkeys) and enforce it for "
            "sensitive actions, with documented account-recovery flows "
            "that do not downgrade the second factor.",
            "Secure the password-reset flow: single-use, expiring, "
            "unpredictable tokens sent over a verified channel, no "
            "token in URL logs, and no account enumeration via "
            "differential error messages.",
            "Defend sessions against fixation and hijacking: rotate "
            "session IDs at login, bind sessions to device context, and "
            "alert on anomalous new-device or new-location logins.",
            "Apply least privilege and separation: auth service runs "
            "with its own credentials, secrets live in a managed secret "
            "store, and PII fields are encrypted at rest with envelope "
            "encryption.",
            "Log auth events (logins, failures, resets, MFA changes) "
            "without writing passwords or tokens, and monitor for "
            "anomalies with alerting that has been tested end to end.",
            "Protect transport and clients: TLS 1.2+ everywhere, HSTS, "
            "secure cookie flags, and PKCE for OAuth-style mobile "
            "authorization flows.",
        ],
        "followups": [
            "A user reports their account was taken over despite MFA. "
            "How do you investigate, and what systemic changes would "
            "you consider (e.g. phishing-resistant factors)?",
            "How would you add SSO/SAML/OIDC for enterprise tenants "
            "without weakening the per-tenant isolation of the auth "
            "service?",
            "Your refresh-token database is leaked. Walk me through the "
            "blast radius and your incident response.",
        ],
    },
    {
        "id": "secure-file-sharing",
        "title": "Secure file-sharing service",
        "prompt": (
            "Design a file-sharing service where users upload files and "
            "generate share links with optional expiry and password "
            "protection. Files may be large, links may be public or "
            "restricted, and recipients may be outside the organization. "
            "Cover upload, storage, link generation, access control, and "
            "how you prevent abuse such as malware distribution or "
            "unauthorized access via link guessing."
        ),
        "checklist": [
            "Enforce authorization on every download: never rely on "
            "unlisted URLs alone; use unguessable, high-entropy link "
            "tokens plus explicit ACLs for restricted shares.",
            "Encrypt files at rest with per-file data keys and envelope "
            "encryption; consider client-side (zero-knowledge) "
            "encryption for the highest-sensitivity tier.",
            "Validate and sanitize uploads: enforce size limits, scan "
            "with antivirus, sniff real content types, and re-encode or "
            "sandbox risky formats before serving.",
            "Serve downloads with safe headers: Content-Disposition "
            "attachment for untrusted types, nosniff, and a separate "
            "cookieless domain so uploaded content cannot execute in "
            "the app's origin.",
            "Make link controls real: expiry timestamps enforced "
            "server-side, optional password hashing (not plaintext), "
            "revocation on demand, and per-link download/view counters.",
            "Protect the upload path: pre-signed, short-lived upload "
            "URLs, authentication required, quotas per user, and no "
            "server-side request forgery via fetched remote URLs.",
            "Log who uploaded, shared, and downloaded what; retain "
            "enough metadata for abuse investigation while redacting "
            "file contents from logs.",
            "Plan for malware and abuse: hash-based blocklists, "
            "reporter workflows, admin takedown tooling, and "
            "notification to the sharer before punitive action when "
            "possible.",
        ],
        "followups": [
            "A shared link goes viral and your egress bill explodes. "
            "How do you add throttling and abuse controls without "
            "breaking legitimate sharing?",
            "How would you implement end-to-end encrypted sharing "
            "where the server cannot read the file, including key "
            "exchange for password-protected links?",
            "An attacker uploads files that exploit your thumbnail "
            "generator. How do you isolate and harden the processing "
            "pipeline?",
        ],
    },
    {
        "id": "secrets-rotation",
        "title": "Secrets rotation system",
        "prompt": (
            "Design a secrets management and rotation system for a "
            "company running dozens of microservices across multiple "
            "cloud accounts. Cover how secrets are stored, injected into "
            "services, rotated on a schedule and on demand, and revoked "
            "after an employee departure or a suspected leak. Address "
            "what happens when a rotation fails halfway."
        ),
        "checklist": [
            "Centralize secrets in a managed store (e.g. Vault, cloud "
            "KMS-backed secret manager) with audit logging on every "
            "read; no secrets in code, images, or environment dumps.",
            "Inject secrets at runtime via short-lived leases or mounted "
            "files rather than long-lived environment variables baked "
            "into containers.",
            "Rotate on schedule and on event: versioned secrets, dual-"
            "support windows during rotation, and automated triggers "
            "for departure, incident, or suspected exposure.",
            "Make rotation atomic or idempotent: staged rollout (write "
            "new, deploy, verify, disable old) with rollback if "
            "health checks fail after a rotation.",
            "Scope access with least privilege: per-service identities, "
            "path-based policies, and break-glass access that requires "
            "approval and pages a human.",
            "Encrypt secrets at rest with envelope encryption and "
            "customer-managed keys where required; protect backups "
            "of the secret store with the same rigor as live secrets.",
            "Detect leaks proactively: scan repos and logs for secret "
            "patterns, and have a runbook for revocation, rotation, "
            "and blast-radius assessment within a defined SLA.",
            "Separate human and machine secrets: SSO and short-lived "
            "credentials for engineers; long-lived service credentials "
            "only where unavoidable, with owners and expiry dates.",
        ],
        "followups": [
            "A database password leaks in a public Slack channel. "
            "Walk me through the first 30 minutes of your response.",
            "How do you rotate a secret shared by services owned by "
            "five different teams with different deploy cadences?",
            "Your secret store itself is compromised. What is your "
            "recovery plan, and how do you re-establish trust?",
        ],
    },
    {
        "id": "multitenant-isolation",
        "title": "Multi-tenant data isolation",
        "prompt": (
            "Design the data-isolation strategy for a multi-tenant SaaS "
            "platform where tenants have strict data-residency and "
            "compliance requirements (some need encryption with their "
            "own keys). Choose between silo, pool, and bridge models and "
            "justify the tradeoff. Explain how you prevent cross-tenant "
            "data leaks in application code, queries, caches, and logs."
        ),
        "checklist": [
            "Pick the tenancy model deliberately: silo for regulated "
            "tenants, pooled with row-level security for cost "
            "efficiency, and document which tenants qualify for which.",
            "Enforce tenant scoping at the data-access layer (not in "
            "each controller): mandatory tenant_id filters, query "
            "wrappers, or row-level security policies in the database.",
            "Isolate caches, queues, and search indexes by tenant: "
            "tenant-prefixed keys, per-tenant index aliases, and no "
            "shared cache entries keyed by guessable IDs.",
            "Support per-tenant encryption keys (BYOK/CMK) with "
            "envelope encryption so key revocation actually renders "
            "a tenant's data unreadable.",
            "Prevent IDOR and confused-deputy bugs: validate that every "
            "object ID in a request belongs to the caller's tenant "
            "before acting on it.",
            "Keep tenant data out of shared logs and error reports: "
            "scrub PII, tag log lines with tenant context for "
            "investigation, and restrict log access per tenant where "
            "contracts require it.",
            "Design onboarding and offboarding: provisioning new "
            "tenants, secure data export, cryptographic erasure on "
            "contract end, and verified deletion across backups.",
            "Test isolation continuously: automated tests that attempt "
            "cross-tenant access, plus periodic penetration testing "
            "focused on tenant-boundary escapes.",
        ],
        "followups": [
            "A bug let tenant A see tenant B's records for two hours. "
            "How do you scope the exposure and notify affected "
            "tenants?",
            "A large tenant demands data residency in a specific "
            "region. How does your architecture accommodate that "
            "without forking the codebase?",
            "How do you run analytics across tenants without violating "
            "isolation guarantees?",
        ],
    },
    {
        "id": "secure-webhook-receiver",
        "title": "Secure webhook receiver",
        "prompt": (
            "Design a webhook receiver that accepts event callbacks "
            "from a third-party payment provider. The endpoint is "
            "internet-facing, must verify that events are authentic and "
            "fresh, handle duplicates and out-of-order delivery, and "
            "survive traffic spikes during provider retries. Explain "
            "signature verification, idempotency, and your replay-attack "
            "defenses."
        ),
        "checklist": [
            "Verify authenticity with HMAC signatures over the raw "
            "request body using a per-sender secret; compare with a "
            "constant-time function and reject unsigned or "
            "badly-signed requests.",
            "Enforce freshness: check timestamps against a tight "
            "tolerance window and reject stale deliveries to blunt "
            "replay attacks.",
            "Guarantee idempotency: dedupe on the provider's event ID "
            "with a unique constraint, so retries and duplicates never "
            "double-apply a payment.",
            "Handle out-of-order delivery: model events as state "
            "transitions with versioning or timestamps so a late event "
            "cannot regress state.",
            "Separate receipt from processing: acknowledge quickly, "
            "enqueue to durable storage, and process asynchronously "
            "with retries and a dead-letter queue.",
            "Protect the endpoint itself: IP allowlisting where the "
            "provider publishes ranges, rate limiting, minimal attack "
            "surface, and no sensitive data in error responses.",
            "Rotate webhook secrets without downtime: support multiple "
            "active secrets during rollover and versioned signing "
            "schemes.",
            "Log full delivery metadata (event IDs, signatures "
            "accepted/rejected, timestamps) for reconciliation, "
            "without logging secret material.",
        ],
        "followups": [
            "The provider rotates their signing key with 24 hours "
            "notice. How do you roll without dropping events?",
            "You receive a burst of 100x normal webhook traffic. How "
            "do you distinguish a retry storm from an attack, and how "
            "do you stay up?",
            "An attacker replays a captured 'payment succeeded' event. "
            "Which of your controls catches it, and in what order?",
        ],
    },
    {
        "id": "passwordless-login",
        "title": "Passwordless login",
        "prompt": (
            "Design a passwordless login system for a consumer app: "
            "users sign in with email magic links and WebAuthn "
            "passkeys, with SMS OTP only as a fallback. Cover "
            "enrollment, authentication ceremonies, account recovery "
            "when a user loses their device, and how you resist "
            "phishing, SIM-swap, and token-interception attacks."
        ),
        "checklist": [
            "Make magic links single-use, short-lived (minutes), and "
            "bound to the requesting device/session; invalidate on "
            "use and expire aggressively.",
            "Use WebAuthn properly: server-stored challenge, origin "
            "and RP ID verification, attestation policy, and "
            "per-credential sign counters to detect cloning.",
            "Treat SMS OTP as the weakest factor: rate-limit sends and "
            "attempts, short codes, short windows, and never allow SMS "
            "alone to reset stronger factors.",
            "Design recovery that cannot be social-engineered around "
            "your factors: verified backup passkeys, delayed recovery "
            "with notifications to all registered devices, and human "
            "review for high-risk cases.",
            "Resist phishing end to end: passkeys are phishing-"
            "resistant by design; magic links must be bound and never "
            "forwardable into a working session on another device.",
            "Handle device loss explicitly: remote credential "
            "revocation, re-enrollment flows that re-verify identity, "
            "and clear UX showing registered devices and sessions.",
            "Log authentication ceremonies (factor used, device, "
            "result) and alert on anomalies like impossible travel or "
            "sudden factor changes.",
            "Keep PII minimal in the flow: do not leak which factors a "
            "user has enrolled via enumeration-friendly error "
            "messages.",
        ],
        "followups": [
            "A user loses their only device with no backup passkey. "
            "How do they get back in without opening a social-"
            "engineering hole?",
            "How do you migrate existing password users to "
            "passwordless without a support-ticket avalanche?",
            "An attacker SIM-swaps a victim and requests an SMS code. "
            "What stops the takeover in your design?",
        ],
    },
    {
        "id": "audit-logging-pipeline",
        "title": "Audit-logging pipeline",
        "prompt": (
            "Design an audit-logging pipeline for a fintech platform "
            "where every sensitive action (money movement, permission "
            "changes, data exports) must be recorded immutably and be "
            "queryable for investigations and compliance. Cover event "
            "capture, transport, storage, tamper evidence, retention, "
            "and how analysts search the logs without seeing customer "
            "PII they should not see."
        ),
        "checklist": [
            "Define the audit schema up front: actor, action, target, "
            "timestamp (synchronized clocks), source IP/device, and "
            "before/after values for sensitive mutations.",
            "Capture at the enforcement point (server-side, in the "
            "service that authorizes the action), not in the client; "
            "make event emission part of the transaction or use an "
            "outbox pattern so actions and logs cannot diverge.",
            "Transport reliably: buffered, retried delivery with "
            "backpressure and local spooling so log loss during an "
            "outage is bounded and detectable.",
            "Make logs tamper-evident: append-only storage, hash-"
            "chained records or WORM buckets, and separation of "
            "duties so the team that writes code cannot rewrite "
            "history.",
            "Protect PII in logs: field-level redaction or tokenization "
            "at ingest, with a separate, access-controlled process "
            "for de-tokenization during investigations.",
            "Control access to the logs themselves: role-based access, "
            "query auditing (who searched what), and break-glass "
            "procedures for sensitive investigations.",
            "Set retention and deletion policy: compliance-driven "
            "retention windows, legal-hold overrides, and provable "
            "deletion after expiry.",
            "Test the pipeline: regular restores, integrity "
            "verification jobs, and simulated incident queries so "
            "analysts know the data is there when it matters.",
        ],
        "followups": [
            "An engineer with production access tries to cover their "
            "tracks by deleting logs. Which controls catch or prevent "
            "this?",
            "Regulators ask for 'all actions by user X in the last "
            "year.' How fast can you answer, and what proves the "
            "answer is complete?",
            "Your log volume grows 50x. How do you keep costs sane "
            "without losing audit completeness?",
        ],
    },
    {
        "id": "third-party-api-integration",
        "title": "Third-party API integration",
        "prompt": (
            "Design how your platform integrates with a third-party API "
            "that handles sensitive customer data (for example, a KYC "
            "identity-verification vendor). Cover credential management, "
            "request/response handling, data minimization, and how you "
            "contain the blast radius if the vendor is breached or "
            "their API starts returning malicious payloads."
        ),
        "checklist": [
            "Isolate vendor credentials: per-environment API keys in "
            "the secret store, least-privilege scopes, IP allowlisting "
            "where offered, and rotation on a schedule.",
            "Minimize data sent: transmit only required fields, "
            "prefer tokenized or pseudonymized identifiers, and never "
            "send more PII than the vendor contractually needs.",
            "Validate everything inbound: schema validation, size "
            "limits, and sanitization of vendor-returned content "
            "before rendering or acting on it; treat the vendor as "
            "untrusted input.",
            "Contain the integration: dedicated service account and "
            "network egress controls, timeouts and circuit breakers, "
            "and no direct vendor-to-database access.",
            "Handle vendor failure gracefully: cached or degraded "
            "modes, idempotent retries with backoff, and a kill switch "
            "that disables the integration without deploying code.",
            "Log the integration boundary: request/response metadata, "
            "errors, and latency, with PII redacted; alert on "
            "anomalous error rates or data volumes.",
            "Plan for vendor breach: know exactly what data they hold, "
            "have a revocation and key-rotation runbook, and "
            "contractual data-deletion and breach-notification terms.",
            "Review continuously: periodic vendor security reviews, "
            "pen-test scope that includes the integration, and "
            "monitoring of the vendor's own security advisories.",
        ],
        "followups": [
            "The vendor notifies you of a breach exposing data you "
            "sent them. What do you do in the first 24 hours?",
            "The vendor's API starts returning HTML with embedded "
            "scripts in a 'name' field your UI renders. How does your "
            "design prevent stored XSS?",
            "You need to switch vendors in 30 days. How does your "
            "abstraction layer make that survivable?",
        ],
    },
]


def get_drill(drill_id: str) -> dict:
    """Return the drill dict for a slug, or raise ValueError if unknown."""
    for drill in DRILLS:
        if drill["id"] == drill_id:
            return drill
    raise ValueError(f"Unknown drill: {drill_id!r}")


def score_checklist(drill_id: str, checked: list[int]) -> dict:
    """Score a self-assessment against a drill's checklist.

    checked: indices into the drill's checklist that the user says they
    covered. Out-of-range indices are ignored. Returns covered, total,
    pct (0-100), missed checklist items, and a verdict of "strong"
    (>=80), "developing" (50-79), or "needs work" (<50).
    """
    drill = get_drill(drill_id)
    checklist = drill["checklist"]
    total = len(checklist)
    valid = {i for i in checked if isinstance(i, int) and 0 <= i < total}
    covered = len(valid)
    pct = (covered / total * 100) if total else 0.0
    missed = [item for idx, item in enumerate(checklist) if idx not in valid]
    if pct >= 80:
        verdict = "strong"
    elif pct >= 50:
        verdict = "developing"
    else:
        verdict = "needs work"
    return {
        "covered": covered,
        "total": total,
        "pct": pct,
        "missed": missed,
        "verdict": verdict,
    }


def run_drill(drill_id: str | None = None) -> None:
    """Interactive drill: walk the checklist with y/n prompts, then report.

    With no drill_id, lists the available drills and asks which to run.
    Prints the prompt, asks y/n per checklist item, then prints the score
    report and interviewer follow-up questions.
    """
    if drill_id is None:
        print("Secure system-design drills:")
        for i, drill in enumerate(DRILLS, 1):
            print(f"  {i}. {drill['title']} ({drill['id']})")
        choice = input("Pick a drill (number or id): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(DRILLS):
            drill_id = DRILLS[int(choice) - 1]["id"]
        else:
            drill_id = choice
    drill = get_drill(drill_id)

    print()
    print(f"=== {drill['title']} ===")
    print()
    print(drill["prompt"])
    print()
    print("For each checklist item, answer y if your design covered it.")
    checked: list[int] = []
    for idx, item in enumerate(drill["checklist"], 1):
        answer = input(f"[{idx}/{len(drill['checklist'])}] {item} (y/n): ")
        if answer.strip().lower().startswith("y"):
            checked.append(idx - 1)

    result = score_checklist(drill["id"], checked)
    print()
    print("--- Score report ---")
    print(f"Covered: {result['covered']}/{result['total']} "
          f"({result['pct']:.1f}%)")
    print(f"Verdict: {result['verdict']}")
    if result["missed"]:
        print()
        print("Missed considerations to study:")
        for item in result["missed"]:
            print(f"  - {item}")
    print()
    print("Interviewer follow-ups to practice:")
    for i, question in enumerate(drill["followups"], 1):
        print(f"  {i}. {question}")
