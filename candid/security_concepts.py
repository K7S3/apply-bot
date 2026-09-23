"""Security concept deep-dives for the security-engineer interview track.

Each concept is keyed by slug and carries a title, a short summary, the
key points a candidate must know cold, how the topic gets asked in
interviews, and the question-bank categories it maps to. Used by the
interview-prep packs for security-engineer roles. Content is written to be
timeless: fundamentals and patterns, not version-specific trivia.
"""

from __future__ import annotations

VALID_CATEGORIES = ("appsec", "cloudsec", "threat-modeling", "crypto",
                    "incident-response", "iam-network", "detection",
                    "behavioral")

SECURITY_CONCEPTS: dict[str, dict] = {
    "owasp-top-10": {
        "title": "OWASP Top 10: Web Application Risk Categories",
        "summary": (
            "The OWASP Top 10 is the industry's standard taxonomy of the most "
            "critical web application security risks, maintained by the Open "
            "Web Application Security Project and used in interviews as a "
            "shared vocabulary. It covers broken access control, cryptographic "
            "failures, injection, insecure design, misconfiguration, "
            "vulnerable components, authentication failures, software and "
            "data integrity failures, logging and monitoring failures, and "
            "server-side request forgery."
        ),
        "key_points": [
            "Broken access control is consistently the top category: missing "
            "authorization checks on endpoints, IDOR, and privilege "
            "escalation via tampered roles or object references.",
            "Injection (SQL, NoSQL, command, LDAP) is prevented by "
            "parameterized queries and safe APIs, never by escaping user "
            "input at the presentation layer.",
            "Cryptographic failures means data exposed in transit or at rest: "
            "no TLS, weak or hardcoded crypto, or sensitive data stored in "
            "plaintext.",
            "Security misconfiguration is the most operationally common: "
            "default credentials, verbose errors, unnecessary services, and "
            "missing hardening on frameworks and cloud storage.",
            "Vulnerable and outdated components: know your dependency "
            "inventory (SBOM) and have a patching story, because most "
            "breaches reuse known CVEs.",
            "Logging and monitoring failures mean attacks go undetected: log "
            "auth events and anomalies, alert on them, and test that the "
            "alerts actually fire.",
            "Use the Top 10 as a checklist in design reviews and code "
            "reviews, not as a memorized list: map each new feature to the "
            "categories it could violate.",
        ],
        "interview_angles": [
            "Walk me through how you'd threat-model a login page: expect "
            "you to name injection, auth failures, misconfiguration, and "
            "logging gaps from the list.",
            "We found an IDOR in our API: diagnose the root cause and "
            "propose systemic fixes beyond that one endpoint.",
            "How would you prioritize these categories for a startup with "
            "no security team: tests judgment about risk, not recall.",
        ],
        "related_categories": ["appsec", "threat-modeling"],
    },
    "authentication": {
        "title": "Authentication: Passwords, MFA, and Session Management",
        "summary": (
            "Authentication answers who you are, and interviewers care about "
            "the full lifecycle: credential storage, multi-factor "
            "enrollment, session issuance, and revocation. The modern best "
            "practice is phishing-resistant MFA (WebAuthn/FIDO2 security "
            "keys) plus short-lived sessions with server-side revocation, "
            "replacing SMS codes and long-lived tokens wherever possible."
        ),
        "key_points": [
            "Store passwords with a memory-hard hash (Argon2id, scrypt, or "
            "bcrypt) plus a unique per-user salt; never MD5, SHA-1, or "
            "plain SHA-256.",
            "MFA strength hierarchy: FIDO2/WebAuthn security keys and "
            "passkeys at the top, then TOTP authenticator apps, then push "
            "approvals, with SMS one-time codes last because of SIM-swap "
            "and interception.",
            "Sessions should be short-lived, rotated on privilege change, "
            "and revocable server-side; keep a session allowlist so logout "
            "and compromise response actually work.",
            "Protect login endpoints with rate limiting, account lockout or "
            "progressive delays, and CAPTCHA-style bot defenses to blunt "
            "credential stuffing.",
            "Password reset flows are authentication too: time-limited "
            "single-use tokens, no user enumeration via distinct error "
            "messages, and notification to the account owner.",
            "Prefer delegation to a vetted identity provider over building "
            "your own login system; custom auth is where subtle bugs live.",
        ],
        "interview_angles": [
            "Design a login system: they expect MFA options compared by "
            "phishing resistance, session handling, and reset flows.",
            "A user's session token was leaked: walk through detection, "
            "containment, and what changes afterward.",
            "Why is SMS 2FA considered weak, and what would you migrate "
            "to: tests understanding of SIM-swap and phishing.",
        ],
        "related_categories": ["appsec", "iam-network", "crypto"],
    },
    "oauth2-oidc": {
        "title": "OAuth 2.0 and OpenID Connect: Delegated Authorization",
        "summary": (
            "OAuth 2.0 is a delegation framework: it lets a user grant a "
            "third-party app limited access to their resources without "
            "sharing their password, using access tokens issued after an "
            "authorization flow. OpenID Connect adds an identity layer on "
            "top, issuing ID tokens (JWTs) so apps can authenticate users "
            "via single sign-on. Interviews focus on the authorization code "
            "flow with PKCE, token handling, and the classic "
            "misconfigurations."
        ),
        "key_points": [
            "Use the authorization code flow with PKCE for user-facing apps; "
            "the implicit flow is deprecated because tokens land in the "
            "browser URL.",
            "PKCE (code verifier/challenge) binds the authorization code to "
            "the client that started the flow, defeating code interception "
            "attacks.",
            "OAuth 2.0 is authorization, not authentication: using an access "
            "token to decide who someone is is a classic misuse; OIDC ID "
            "tokens exist for that.",
            "Validate ID tokens properly: signature, issuer, audience, "
            "expiration, and nonce; never trust unsigned or unvalidated "
            "JWTs.",
            "Keep tokens out of URLs and localStorage where feasible; use "
            "short-lived access tokens plus refresh-token rotation.",
            "Common misconfigurations to name: open redirectors in "
            "redirect_uri validation, overly broad scopes, and missing "
            "state parameter enabling CSRF on the login flow.",
        ],
        "interview_angles": [
            "Explain the OAuth 2.0 authorization code flow end to end: "
            "draw the redirects, the code exchange, and where PKCE fits.",
            "Our app accepts JWTs from an identity provider: what do you "
            "validate and what breaks if you skip a check.",
            "When would you use OAuth vs API keys vs mutual TLS: tests "
            "judgment about delegation vs service identity.",
        ],
        "related_categories": ["appsec", "iam-network", "crypto"],
    },
    "tls": {
        "title": "TLS: How Encrypted Transport Actually Works",
        "summary": (
            "TLS provides confidentiality, integrity, and server "
            "authentication for traffic in transit, negotiated through a "
            "handshake that agrees on a protocol version, cipher suite, and "
            "session keys. Modern practice is TLS 1.2+ (preferably 1.3), "
            "certificates from a trusted CA with automated renewal, and "
            "HSTS to prevent downgrade. Interviewers probe the handshake, "
            "certificate validation, and the operational side of running "
            "TLS well."
        ),
        "key_points": [
            "TLS 1.3 simplified the handshake to one round trip, removed "
            "legacy cipher suites and static RSA key exchange, and encrypts "
            "more of the handshake; disable TLS 1.0/1.1 and weak ciphers.",
            "Certificate validation checks the chain to a trusted root, "
            "hostname match, and expiry; clients must actually perform all "
            "three, and pinning or CT logs add assurance.",
            "Forward secrecy (ephemeral Diffie-Hellman key exchange) means a "
            "stolen long-term key cannot decrypt past traffic; prefer cipher "
            "suites that provide it.",
            "HSTS tells browsers to only use HTTPS for a domain, defeating "
            "SSL-stripping downgrade attacks; preload it for full coverage.",
            "Mutual TLS (mTLS) authenticates both sides and is the standard "
            "for service-to-service identity in zero-trust architectures.",
            "Operational hygiene: automate renewal (short-lived certs), "
            "monitor expiry, and terminate TLS at the load balancer only if "
            "you re-encrypt or explicitly accept plaintext inside the VPC.",
        ],
        "interview_angles": [
            "Walk me through the TLS handshake: what is exchanged, what "
            "is encrypted, and where authentication happens.",
            "How would you detect and respond to a certificate expiring in "
            "production: monitoring, automation, and rollback.",
            "Design service-to-service auth in a microservice mesh: mTLS "
            "vs tokens, and the tradeoffs.",
        ],
        "related_categories": ["iam-network", "crypto", "appsec"],
    },
    "crypto-primitives": {
        "title": "Cryptographic Primitives: Hashes, Ciphers, Signatures",
        "summary": (
            "Security interviews expect you to pick the right primitive for "
            "the job and, more importantly, to never invent your own. "
            "Symmetric ciphers (AES-GCM) encrypt bulk data, asymmetric "
            "crypto (RSA, elliptic curves) handles key exchange and "
            "signatures, hashes (SHA-256 family) provide integrity and "
            "commitments, and all of it fails if the randomness or key "
            "management is wrong."
        ),
        "key_points": [
            "Use authenticated encryption (AES-GCM or ChaCha20-Poly1305): "
            "encryption without integrity lets attackers tamper with "
            "ciphertext undetected.",
            "Hashing is not encryption: SHA-256 gives integrity and "
            "commitments but is reversible by brute force on low-entropy "
            "inputs, which is why passwords need slow KDFs instead.",
            "Digital signatures (ECDSA, Ed25519, RSA-PSS) prove authenticity "
            "and non-repudiation; signing is not encrypting, and verification "
            "must check the signature before trusting any payload.",
            "Key exchange (Diffie-Hellman, ECDH) lets two parties agree on a "
            "secret over a public channel; use ephemeral variants for "
            "forward secrecy.",
            "All crypto depends on randomness: use the OS CSPRNG "
            "(getrandom, CryptGenRandom), never Math.random or a seeded PRNG "
            "for keys, IVs, or nonces.",
            "Rule zero: never roll your own cipher, protocol, or clever "
            "combination; use vetted libraries and standard constructions, "
            "and keep keys in a KMS or HSM, not in code or config files.",
        ],
        "interview_angles": [
            "We need to store credit card numbers: walk through "
            "encryption choice, key management, and what the threat model "
            "covers.",
            "Explain the difference between hashing, encryption, and "
            "signing, with one use case each.",
            "Review this homegrown token scheme: spot the crypto "
            "misuse (unauthenticated encryption, weak randomness, custom "
            "construction).",
        ],
        "related_categories": ["crypto", "appsec"],
    },
    "password-hashing": {
        "title": "Password Hashing and Key Derivation",
        "summary": (
            "Password hashing exists because credential databases get "
            "stolen: the goal is to make offline brute force as expensive "
            "as possible while staying fast enough for logins. The answer "
            "is adaptive, memory-hard functions: Argon2id first choice, "
            "then scrypt, then bcrypt, with a unique random salt per "
            "password. Fast hashes like SHA-256, even salted, fall to GPUs "
            "in hours, and peppering plus breach monitoring are the "
            "defense-in-depth extras."
        ),
        "key_points": [
            "Use Argon2id (memory-hard, side-channel resistant) with tuned "
            "memory, iteration, and parallelism parameters; scrypt and "
            "bcrypt are acceptable fallbacks.",
            "Every password gets a unique random salt (16+ bytes): salts "
            "defeat rainbow tables and force per-password cracking.",
            "Never use MD5, SHA-1, or plain SHA-256 for passwords: GPUs try "
            "billions of fast hashes per second, so iteration count must be "
            "tunable upward over time.",
            "A server-side pepper (secret stored outside the DB, e.g., in an "
            "HSM or KMS) means a DB-only breach still does not yield "
            "crackable hashes.",
            "Tune cost parameters so a login takes on the order of a few "
            "hundred milliseconds: slow enough to hurt attackers, fast "
            "enough for users, and re-tune as hardware improves.",
            "Complement hashing with breached-password screening at "
            "registration and reset, so users cannot pick credentials "
            "already in attacker wordlists.",
        ],
        "interview_angles": [
            "Our user table leaked: explain exactly what the attacker can "
            "and cannot do given your hashing scheme.",
            "Compare bcrypt, scrypt, and Argon2: what does memory-hardness "
            "buy you against GPU cracking rigs.",
            "How do you migrate a legacy SHA-1 password store without "
            "forcing a mass reset: wrap-and-upgrade on next login.",
        ],
        "related_categories": ["crypto", "appsec"],
    },
    "zero-trust": {
        "title": "Zero Trust Architecture",
        "summary": (
            "Zero trust replaces the castle-and-moat model (trusted inside, "
            "hostile outside) with never trust, always verify: every "
            "request is authenticated, authorized, and encrypted regardless "
            "of network location. In practice this means strong identity "
            "for users and workloads, least-privilege access with continuous "
            "evaluation, micro-segmentation, and comprehensive logging. "
            "Interviews test whether you can translate the slogan into "
            "concrete controls."
        ),
        "key_points": [
            "Identity is the new perimeter: users via SSO plus "
            "phishing-resistant MFA, workloads via SPIFFE/SPIRE identities "
            "or mTLS certificates, not IP addresses.",
            "Least privilege with just-in-time elevation: default-deny "
            "policies, short-lived credentials, and approval workflows for "
            "sensitive access instead of standing admin rights.",
            "Micro-segmentation limits blast radius: workloads only reach "
            "the services they need, enforced by network policy or "
            "service-mesh authorization, so one compromised host cannot "
            "roam.",
            "Assume breach: encrypt traffic even inside the VPC, log "
            "everything centrally, and design for detection and containment "
            "rather than perfect prevention.",
            "Device posture matters: endpoint health checks (OS patches, "
            "disk encryption, EDR present) feed into access decisions.",
            "Zero trust is a journey of incremental controls, not a product: "
            "start with identity and MFA everywhere, then segment, then "
            "continuous authorization.",
        ],
        "interview_angles": [
            "Our VPN just died and 500 engineers need access: how would a "
            "zero-trust design have avoided the single point of failure.",
            "An attacker lands on one EC2 instance: walk through what "
            "stops lateral movement in your architecture.",
            "What is the first zero-trust control you would roll out at a "
            "startup, and why: tests prioritization.",
        ],
        "related_categories": ["iam-network", "cloudsec", "threat-modeling"],
    },
    "supply-chain-security": {
        "title": "Software Supply Chain Security",
        "summary": (
            "Modern applications are mostly third-party code, so attackers "
            "target the chain: compromised packages, typosquatting, build "
            "system intrusions, and malicious updates. Defense layers "
            "include vetting and pinning dependencies, verifying signatures "
            "and provenance, generating SBOMs, scanning for known "
            "vulnerabilities, and hardening the build pipeline itself with "
            "reproducible builds and artifact signing."
        ),
        "key_points": [
            "Pin dependencies with lockfiles and verify integrity hashes; "
            "floating version ranges let a malicious or broken release flow "
            "in silently.",
            "Know the attack patterns: typosquatting, dependency confusion "
            "(private package names shadowed on public registries), and "
            "maintainer account takeover pushing malicious versions.",
            "Generate and maintain an SBOM (software bill of materials) so "
            "you can answer 'are we affected by CVE-X' in minutes, not days.",
            "Scan continuously: SCA tools for known CVEs in dependencies, "
            "plus policies that block or flag critical vulnerabilities in "
            "CI.",
            "Verify provenance: signed commits, signed artifacts "
            "(Sigstore/cosign), and build attestation (SLSA) proving the "
            "binary came from the expected source and build.",
            "Harden the pipeline: minimal build permissions, ephemeral "
            "builders, separated deploy credentials, and code review on "
            "dependency updates, not just first-party code.",
        ],
        "interview_angles": [
            "A popular npm package we depend on was compromised: walk "
            "through detection, containment, and remediation.",
            "Design the dependency-update process for a security-conscious "
            "team: automation, review, and rollback.",
            "What is an SBOM and when does it actually help in incident "
            "response: tests practical understanding.",
        ],
        "related_categories": ["appsec", "threat-modeling", "cloudsec"],
    },
    "detection-soc": {
        "title": "Detection Engineering and SOC Operations",
        "summary": (
            "Detection is how you find attackers who bypassed prevention: "
            "writing high-signal rules over centralized logs, tuning out "
            "false positives, and running a SOC workflow of triage, "
            "investigation, containment, and lessons learned. Strong "
            "candidates talk about detection-as-code, the pyramid of pain "
            "(detect on TTPs, not just IOCs), and measuring mean time to "
            "detect and respond rather than alert counts."
        ),
        "key_points": [
            "Centralize logs first (auth, endpoint, cloud audit, network, "
            "application) with synchronized clocks; you cannot detect what "
            "you cannot see or correlate.",
            "Write detections as code with tests: version-controlled rules, "
            "sample true/false positives, and tuning that survives analyst "
            "turnover.",
            "Prefer TTP-based detections (mapped to MITRE ATT&CK) over "
            "IOC-based ones: hashes and IPs are trivially changed, behaviors "
            "are expensive for attackers to change (pyramid of pain).",
            "Tune aggressively: an alert nobody investigates is worse than "
            "no alert, because it trains the team to ignore the queue; "
            "measure precision and time-to-triage per rule.",
            "Baseline normal behavior for anomaly detection (impossible "
            "travel, off-hours admin activity, unusual data egress), and "
            "pair it with allowlisted automation to cut noise.",
            "Track MTTD and MTTR, run tabletop exercises, and feed every "
            "real incident back into new or improved detections.",
        ],
        "interview_angles": [
            "Design a detection for credential-stuffing against our login "
            "API: data sources, rule logic, and how you handle false "
            "positives.",
            "An alert fires at 3 AM for unusual outbound traffic: walk "
            "through your triage and investigation steps.",
            "How do you measure whether a SOC is effective: MTTD/MTTR, "
            "alert precision, coverage of ATT&CK techniques.",
        ],
        "related_categories": ["detection", "incident-response",
                               "behavioral"],
    },
    "cloud-iam": {
        "title": "Cloud IAM: Roles, Policies, and Least Privilege",
        "summary": (
            "Cloud breaches are usually IAM breaches: over-broad roles, "
            "long-lived credentials, and confused-deputy privilege "
            "escalation. The discipline is least privilege via roles and "
            "short-lived credentials, policy conditions that scope access "
            "tightly, and continuous auditing of who can do what. "
            "Interviewers want concrete policy reasoning, not just the "
            "phrase 'least privilege'."
        ),
        "key_points": [
            "Prefer roles with temporary credentials over long-lived access "
            "keys; rotate and scope down anything long-lived, and never "
            "commit keys to repos.",
            "Write narrow policies: specific actions on specific resources "
            "with conditions (source IP/VPC, MFA present, time windows), "
            "and default-deny everything else.",
            "Understand privilege escalation paths: e.g., an IAM user who "
            "can attach policies or launch instances with an admin role can "
            "become admin; audit for these chains, not just direct grants.",
            "Use permission boundaries and SCPs (service control policies) "
            "as guardrails that cap what delegated admins can grant, even "
            "if their own policies are looser.",
            "Separate duties with distinct roles for humans, CI/CD, and "
            "workloads (instance/pod identities), each with only the "
            "permissions its job needs.",
            "Audit continuously: access advisors showing unused permissions, "
            "CloudTrail/ audit logs for anomalous calls, and periodic "
            "access reviews that actually remove stale grants.",
        ],
        "interview_angles": [
            "Review this IAM policy and find the privilege escalation: "
            "they hand you an over-broad policy and watch your reasoning.",
            "A CI job needs to deploy to production: design its identity "
            "and permissions from scratch.",
            "How would you discover overly permissive roles across 200 "
            "accounts: tooling, access advisor data, and remediation "
            "workflow.",
        ],
        "related_categories": ["cloudsec", "iam-network", "threat-modeling"],
    },
    "network-security": {
        "title": "Network Security: Segmentation, Firewalls, and TLS Everywhere",
        "summary": (
            "Network security is defense in depth for traffic: segment "
            "networks so compromise does not spread, filter with firewalls "
            "and security groups on least-privilege rules, and encrypt in "
            "transit even inside your own VPC. The modern shift is from "
            "perimeter VPNs toward identity-aware access, but the "
            "fundamentals of segmentation, egress control, and DDoS "
            "resilience still decide how bad an incident gets."
        ),
        "key_points": [
            "Segment into tiers (public, application, data) with explicit "
            "allow rules between them; a compromised web server should not "
            "reach the database subnet directly.",
            "Default-deny firewall and security-group rules: allow only "
            "required ports, protocols, and sources, and review rules "
            "periodically because they accrete.",
            "Control egress, not just ingress: restrict outbound traffic so "
            "a compromised host cannot easily exfiltrate data or fetch "
            "second-stage payloads.",
            "Encrypt in transit everywhere, including inside the VPC, and "
            "terminate TLS deliberately rather than letting plaintext "
            "appear by accident.",
            "Plan for DDoS at multiple layers: CDN/WAF absorption at the "
            "edge, rate limiting at the app, and autoscaling plus "
            "anycast for volumetric attacks.",
            "Prefer identity-aware proxies and short-lived access over flat "
            "VPNs that put every connected device on the corporate network.",
        ],
        "interview_angles": [
            "Design the network for a three-tier web app in the cloud: "
            "subnets, security groups, and where TLS terminates.",
            "We are seeing suspicious outbound connections from a server: "
            "how do network controls help you detect and contain it.",
            "VPN vs zero-trust network access: compare the security models "
            "and migration path.",
        ],
        "related_categories": ["iam-network", "cloudsec", "incident-response"],
    },
    "web-security-headers": {
        "title": "Web Security Headers and Browser-Side Defenses",
        "summary": (
            "Browsers enforce powerful security boundaries, but only if the "
            "server asks: response headers like Content-Security-Policy, "
            "Strict-Transport-Security, and cookie flags turn on the "
            "browser's built-in defenses against XSS, clickjacking, and "
            "protocol downgrade. These headers are cheap, high-leverage, "
            "and a favorite interview topic because misconfiguring them is "
            "so common."
        ),
        "key_points": [
            "Content-Security-Policy (CSP) restricts where scripts, styles, "
            "and other resources may load from; a strict CSP with nonces or "
            "hashes neuters most XSS payloads even when injection occurs.",
            "Cookie flags: HttpOnly blocks JavaScript access (blunts XSS "
            "session theft), Secure requires HTTPS, and SameSite=Lax or "
            "Strict blocks most CSRF.",
            "Strict-Transport-Security (HSTS) forces HTTPS and kills "
            "SSL-stripping; X-Frame-Options or frame-ancestors in CSP "
            "prevents clickjacking.",
            "CSRF defense in depth: SameSite cookies plus anti-CSRF tokens "
            "on state-changing requests, and never accept state changes via "
            "GET.",
            "Treat headers as layers, not fixes: CSP does not excuse "
            "unescaped output, and HSTS does not excuse mixed content; "
            "validate and encode server-side first.",
            "Verify with tooling: scan responses in CI, use reporting "
            "endpoints (CSP report-uri) to catch breakage before enforcing, "
            "and roll out CSP in report-only mode first.",
        ],
        "interview_angles": [
            "Our app has reflected XSS: what do you fix first, the "
            "encoding bug or the CSP, and why.",
            "Explain how SameSite cookies mitigate CSRF and where they "
            "fall short.",
            "Audit these response headers: spot what is missing or "
            "misconfigured and rank by risk.",
        ],
        "related_categories": ["appsec", "threat-modeling"],
    },
    "secrets-management": {
        "title": "Secrets Management: Storage, Rotation, and Leak Response",
        "summary": (
            "Secrets (API keys, DB passwords, signing keys, certificates) "
            "are the keys to the kingdom, so they need a lifecycle: "
            "generated securely, stored in a dedicated secrets manager, "
            "injected at runtime rather than baked into artifacts, rotated "
            "regularly, and revoked fast when leaked. Interviews focus on "
            "the lifecycle and on what you do in the first hour after a "
            "secret hits a public repo."
        ),
        "key_points": [
            "Store secrets in a dedicated manager (cloud KMS/secrets "
            "service, HashiCorp Vault): encrypted at rest, access-logged, "
            "and never in code, config files, or container images.",
            "Inject at runtime via environment or mounted files with "
            "minimal permissions; builds and images should contain zero "
            "secrets.",
            "Rotate on a schedule and on events (employee departure, "
            "suspected leak): rotation must be automated and tested, or it "
            "will not happen.",
            "Scope secrets narrowly: per-service credentials with least "
            "privilege, so one leaked key has a bounded blast radius.",
            "Scan proactively: pre-commit hooks and repo scanning for key "
            "patterns, plus alerts on secrets appearing in logs or error "
            "messages.",
            "Leak response playbook: revoke/rotate immediately, audit usage "
            "logs for exploitation during the exposure window, then fix the "
            "process that allowed the leak.",
        ],
        "interview_angles": [
            "An AWS key was committed to a public GitHub repo: walk "
            "through the first hour of response.",
            "Design secrets handling for a twelve-factor app from local "
            "dev to production: storage, injection, and rotation.",
            "How do you balance rotation frequency against operational "
            "risk: automation, staged rollout, and dual-secret support.",
        ],
        "related_categories": ["appsec", "cloudsec", "incident-response"],
    },
    "secure-sdlc": {
        "title": "Secure SDLC: Shifting Security Left",
        "summary": (
            "A secure software development lifecycle bakes security into "
            "every phase instead of bolting it on before release: threat "
            "modeling in design, secure coding standards and SAST in "
            "development, dependency and container scanning in CI, DAST and "
            "pen testing before launch, and monitoring after deploy. The "
            "interview signal is pragmatism: how you get developers to adopt "
            "these practices without grinding velocity to a halt."
        ),
        "key_points": [
            "Threat model during design (STRIDE or similar): enumerate "
            "assets, trust boundaries, and abuse cases before code exists, "
            "when fixes are cheapest.",
            "Secure coding baselines: input validation, parameterized "
            "queries, output encoding, and auth checks as team standards, "
            "reinforced by code review checklists.",
            "Automate in CI: SAST for code patterns, SCA for dependencies, "
            "secret scanning, and container/image scanning, with policies "
            "that block only high-confidence criticals to avoid alert "
            "fatigue.",
            "Test like an attacker before release: DAST against staging, "
            "periodic penetration tests, and bug bounty programs for "
            "continuous external scrutiny.",
            "Security champions scale the program: embed trained engineers "
            "in product teams who triage findings and spread practices, "
            "rather than a central team that just says no.",
            "Close the loop: track mean time to remediate by severity, run "
            "postmortems on escaped vulnerabilities, and feed root causes "
            "back into training and guardrails.",
        ],
        "interview_angles": [
            "You join a startup with no security process: what do you "
            "introduce in the first 90 days, in what order.",
            "Developers ignore SAST findings: how do you fix adoption "
            "without becoming the team everyone avoids.",
            "Walk through threat modeling a new file-upload feature: "
            "assets, threats, and mitigations.",
            "Tell me about a time you pushed a security fix through "
            "resistance: tests influence without authority.",
        ],
        "related_categories": ["appsec", "threat-modeling", "behavioral"],
    },
}


def get(slug: str) -> dict:
    """Return the concept dict for *slug*.

    Raises KeyError if the slug is unknown.
    """
    try:
        return SECURITY_CONCEPTS[slug]
    except KeyError:
        raise KeyError(f"unknown security concept: {slug!r}") from None


def names() -> list[str]:
    """Return all concept slugs in definition order."""
    return list(SECURITY_CONCEPTS)


__all__ = ["SECURITY_CONCEPTS", "VALID_CATEGORIES", "get", "names"]
