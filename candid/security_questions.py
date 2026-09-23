"""Researched security-engineer interview question bank.

Every question in SECURITY_QUESTIONS was found through public web research
(interview guides, question banks, and candidate experience reports from
Glassdoor, Blind, GitHub repos, and career blogs). Each entry carries its
source and, where known, when it was reported, so prep packs and the
mock-interview scorer never invent "recently asked" questions.

Optional per-question key: "expected_points" (a short list of points a
strong answer should cover; used by the mock-interview scorer). These are
deliberately generic so they stay true to the underlying question.
"""

from __future__ import annotations

CATEGORIES: list[str] = [
    "appsec",
    "cloudsec",
    "threat-modeling",
    "crypto",
    "incident-response",
    "iam-network",
    "detection",
    "behavioral",
]

# Fields: q, category, source, url, reported, [expected_points]
SECURITY_QUESTIONS: list[dict] = [
    # ------------------------------------------------------------------
    # appsec
    # ------------------------------------------------------------------
    {
        "q": "During code review you see a user-controlled URL used in a server-side HTTP call. How would you confirm and mitigate SSRF, and what checks or libraries would you recommend to harden outbound requests?",
        "category": "appsec",
        "source": "vintti.com, Interview Questions for Remote Application Security Engineer (junior tier)",
        "url": "https://www.vintti.com/interview-questions/application-security-engineer",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Confirm by controlling the URL and observing the server fetch an internal-only resource (e.g. metadata endpoint 169.254.169.254) or via DNS rebinding",
            "Allowlist outbound domains, resolve and validate the IP (no private/loopback/link-local ranges), re-check after redirects",
            "Layered fix: egress firewall rules, disable unused URL schemes, timeouts, and response-size limits",
        ],
    },
    {
        "q": "A new feature uses JWTs in the browser. Which configuration would you choose for storage, lifetime, signing and rotation, and how would you prevent token leakage and confused-deputy issues in OAuth and OpenID Connect flows?",
        "category": "appsec",
        "source": "vintti.com, Interview Questions for Remote Application Security Engineer (junior tier)",
        "url": "https://www.vintti.com/interview-questions/application-security-engineer",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Short-lived access tokens, refresh-token rotation, HttpOnly/Secure/SameSite cookies rather than localStorage for session-bound tokens",
            "Strong signing (RS256/ES256, never 'none'), strict audience/issuer validation, validate state/PKCE in OAuth flows",
            "Mitigate confused deputy by binding tokens to the intended recipient (aud claim) and validating redirect URIs exactly",
        ],
    },
    {
        "q": "Your pipeline runs SAST and SCA and flags a high-severity finding in a transitive dependency. How would you verify exploitability, choose between upgrade, patch, or compensating control, and document the decision?",
        "category": "appsec",
        "source": "vintti.com, Interview Questions for Remote Application Security Engineer (junior tier)",
        "url": "https://www.vintti.com/interview-questions/application-security-engineer",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Verify reachability: is the vulnerable code path actually called by the application, and is the sink exploitable in context",
            "Decide by risk and cost: upgrade first, vendor/backported patch second, compensating control (WAF rule, input filter) when neither is feasible",
            "Record the decision in the ticket and SBOM with rationale, residual risk, owner, and expiry/review date",
        ],
    },
    {
        "q": "Dynamic testing finds an IDOR leading to broken access control. How would you reproduce the issue, propose a defense-in-depth fix at the controller and data layers, and add an automated check to prevent regression?",
        "category": "appsec",
        "source": "vintti.com, Interview Questions for Remote Application Security Engineer (semi-senior tier)",
        "url": "https://www.vintti.com/interview-questions/application-security-engineer",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Reproduce with two accounts: swap object IDs and confirm unauthorized access, ruling out direct reference vs missing check",
            "Fix at both layers: authorization check in the controller/handler plus ownership scoping in the data-access query, not just UI hiding",
            "Add a regression test that requests another user's object and asserts denial, wired into CI",
        ],
    },
    {
        "q": "You are given a code sample and asked to perform a secure code review: find and list the security bugs in the code.",
        "category": "appsec",
        "source": "Tech Industry - Blind, 'Let's make a Security Engineer interview experience mega thread' (Amazon security engineer loop, secure code review round)",
        "url": "https://www.teamblind.com/post/lets-make-a-security-engineer-interview-experience-mega-thread-f1ur1j53",
        "reported": "candidate experience reports (ongoing)",
        "expected_points": [
            "Talk through the review methodically: entry points, trust boundaries, data flow from source to sink",
            "Look for the classics: injection, auth/authz gaps, crypto misuse, sensitive data exposure, insecure defaults",
            "Rank findings by exploitability and impact, and note what you would ask the author about unclear intent",
        ],
    },
    {
        "q": "Can you explain SAST, DAST, IAST, and SCA, and where each fits in a CI/CD pipeline at a startup?",
        "category": "appsec",
        "source": "startup.jobs, Application Security Engineer Interview Questions",
        "url": "https://startup.jobs/interview-questions/application-security-engineer",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "SAST scans source/bytecode without running it; DAST tests the running app from outside; IAST instruments the app during tests; SCA inventories third-party dependencies",
            "Pipeline placement: SAST and SCA on every pull request, IAST in integration tests, DAST against staging/preview deploys",
            "At a startup, gate only on high-confidence findings to avoid blocking the build, and tune noise down fast",
        ],
    },
    {
        "q": "What is your approach to secrets management across local dev, CI, and production?",
        "category": "appsec",
        "source": "startup.jobs, Application Security Engineer Interview Questions",
        "url": "https://startup.jobs/interview-questions/application-security-engineer",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "No secrets in code or chat: use a secrets manager (e.g. AWS Secrets Manager, Vault) with short-lived, scoped credentials",
            "Environment separation: different secrets and access paths for local, CI, staging, and production",
            "Rotation, audit logging of access, and a defined revocation procedure for leaked credentials",
        ],
    },
    # ------------------------------------------------------------------
    # cloudsec
    # ------------------------------------------------------------------
    {
        "q": "How would you detect and prevent IAM privilege escalation attacks in a production AWS environment?",
        "category": "cloudsec",
        "source": "Medium (@shivamrana_14416), 'AWS IAM Interview Questions: Can You Answer This Production-Level Security Challenge?' (Aug 2026)",
        "url": "https://medium.com/@shivamrana_14416/aws-iam-interview-questions-can-you-answer-this-production-level-security-challenge-420327a17eed",
        "reported": "Aug 2026",
        "expected_points": [
            "Detect with CloudTrail (iam:Attach*Policy, CreateAccessKey, UpdateAssumeRolePolicy) plus GuardDuty and Security Hub findings",
            "Prevent with least-privilege policies, permission boundaries, and SCPs that block privilege-granting actions",
            "Continuous hygiene: IAM Access Analyzer for unused grants, credential reports, and MFA enforcement on privileged roles",
        ],
    },
    {
        "q": "You are on-call and your SOC team detects that a developer has suddenly gained AdministratorAccess in your production AWS environment. How would you detect it, investigate it, and stop it before any damage is done?",
        "category": "cloudsec",
        "source": "Medium (@shivamrana_14416), 'AWS IAM Interview Questions: Can You Answer This Production-Level Security Challenge?' (Aug 2026)",
        "url": "https://medium.com/@shivamrana_14416/aws-iam-interview-questions-can-you-answer-this-production-level-security-challenge-420327a17eed",
        "reported": "Aug 2026",
        "expected_points": [
            "Stop the bleeding: revoke the session (deactivate keys, remove policy attachment, rotate affected credentials)",
            "Investigate via CloudTrail: who granted it, when, and what API calls followed; look for persistence (new users, keys, roles)",
            "Post-incident: root-cause the grant path, tighten boundaries/SCPs, add alerting on privilege-granting events",
        ],
    },
    {
        "q": "What is the confused deputy problem in AWS IAM, and how do you prevent it?",
        "category": "cloudsec",
        "source": "GitHub (adityagaurav13a/devops-interview-questions), IAM/AWS_IAM.md rapid-fire questions",
        "url": "https://github.com/adityagaurav13a/devops-interview-questions/blob/HEAD/IAM/AWS_IAM.md",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "A trusted service is tricked into acting on behalf of an attacker who lacks permissions (e.g. cross-account resource access via the service)",
            "Prevent with External ID in cross-account role trust policies",
            "Add aws:SourceAccount and aws:SourceArn conditions when granting permissions to AWS services",
        ],
    },
    {
        "q": "Explain the following IAM policy and what each element does: an MFA-enforcement policy with Effect 'Deny', NotAction 'iam:*', Resource '*', and a Condition requiring aws:MultiFactorAuthPresent to be true.",
        "category": "cloudsec",
        "source": "GitHub (jassics/security-interview-questions), aws-security-interview-questions.md, 'Explain below IAM policy'",
        "url": "https://github.com/jassics/security-interview-questions/blob/main/aws-security-interview-questions.md",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Effect/NotAction combo: denies every action except IAM itself when the condition matches",
            "BoolIfExists on aws:MultiFactorAuthPresent means the deny fires when MFA is absent (or the key is missing)",
            "Net effect: forces MFA for all non-IAM API activity, with IAM calls left for bootstrapping MFA enrollment",
        ],
    },
    {
        "q": "Explain the following IAM policy. What is wrong with it? It denies s3:* on everything except an HR payroll bucket, using NotResource for 'arn:aws:s3:::HRBucket/Payroll' and 'arn:aws:s3:::HRBucket/Payroll/*'.",
        "category": "cloudsec",
        "source": "GitHub (jassics/security-interview-questions), aws-security-interview-questions.md, 'Explain below policy. What's wrong with this policy'",
        "url": "https://github.com/jassics/security-interview-questions/blob/main/aws-security-interview-questions.md",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "NotResource in a Deny inverts the match: it denies S3 on every bucket except the payroll one, which is backwards from the likely intent",
            "Splitting bucket ARN and bucket/* ARNs matters because object-level and bucket-level actions match different resource patterns",
            "Fix by stating the intent explicitly: allow only the intended bucket, or scope the deny to the exact resources",
        ],
    },
    {
        "q": "What comes to mind when a service needs cross-account access in AWS?",
        "category": "cloudsec",
        "source": "GitHub (jassics/security-interview-questions), aws-security-interview-questions.md, IAM section",
        "url": "https://github.com/jassics/security-interview-questions/blob/main/aws-security-interview-questions.md",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Options: assume a role in the target account (trust policy) or resource-based policies (S3, KMS, SQS) granting the foreign principal",
            "No long-lived access keys shared across accounts; use short-lived assumed-role credentials",
            "Guardrails: External ID, least-privilege scope, and CloudTrail logging on both sides",
        ],
    },
    {
        "q": "An audit finds an IAM user with AdministratorAccess who left the company six months ago. What steps do you take?",
        "category": "cloudsec",
        "source": "GitHub (anjaligrt/top-10-aws-services-cohort), Day-03/INTERVIEW_QA.md, Q5",
        "url": "https://github.com/anjaligrt/top-10-aws-services-cohort/blob/HEAD/Day-03/INTERVIEW_QA.md",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Immediate: deactivate access keys, disable console password, remove from groups, then delete the user",
            "Investigate: review CloudTrail for the past six months for suspicious activity (new users, policy changes, data access)",
            "Prevent recurrence: tie offboarding to automated IAM disablement and review the credential report on a cadence",
        ],
    },
    # ------------------------------------------------------------------
    # threat-modeling
    # ------------------------------------------------------------------
    {
        "q": "Threat model an application from an open-ended prompt, for example 'threat model a vending machine'.",
        "category": "threat-modeling",
        "source": "Tech Industry - Blind, 'Let's make a Security Engineer interview experience mega thread' (Amazon security engineer loop, threat modeling round)",
        "url": "https://www.teamblind.com/post/lets-make-a-security-engineer-interview-experience-mega-thread-f1ur1j53",
        "reported": "candidate experience reports (ongoing)",
        "expected_points": [
            "Start with assets, actors, and trust boundaries before enumerating threats",
            "Apply a framework (e.g. STRIDE) to stay systematic, and call out abuse cases beyond the happy path",
            "Prioritize by risk and close with concrete mitigations mapped to each threat",
        ],
    },
    {
        "q": "What is your approach to threat modeling a new customer-facing API or feature?",
        "category": "threat-modeling",
        "source": "startup.jobs, Application Security Engineer Interview Questions",
        "url": "https://startup.jobs/interview-questions/application-security-engineer",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Draw the data flow: entry points, trust boundaries, data stores, and third parties",
            "Enumerate threats per component (spoofing, tampering, auth bypass, abuse of business logic)",
            "Convert outcomes into prioritized requirements with owners, tied to the release timeline",
        ],
    },
    {
        "q": "You are asked to threat model a payments API. How would you run a lightweight STRIDE session with the team, identify abuse cases, prioritize risks, and translate outcomes into OWASP ASVS requirements and test cases?",
        "category": "threat-modeling",
        "source": "vintti.com, Interview Questions for Remote Application Security Engineer (semi-senior tier)",
        "url": "https://www.vintti.com/interview-questions/application-security-engineer",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Timebox the session, walk the team through STRIDE per trust boundary, and capture attacker-centric abuse cases",
            "Prioritize by likelihood and impact on money movement and PII",
            "Map findings to ASVS control categories and write testable acceptance criteria for each",
        ],
    },
    {
        "q": "Tell me about a time you had to perform a threat modeling exercise for a complex system. What methodology did you use, and what were the key outcomes?",
        "category": "threat-modeling",
        "source": "yardstick.team, Interview Questions for Assessing Application Security Engineer",
        "url": "https://yardstick.team/interview-questions-by-role/application-security-engineer",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Name the methodology and why it fit (STRIDE, PASTA, attack trees)",
            "Describe a concrete threat the exercise surfaced that the team had missed",
            "Show the outcome: design change, new control, or risk acceptance with a named owner",
        ],
    },
    # ------------------------------------------------------------------
    # crypto
    # ------------------------------------------------------------------
    {
        "q": "Walk through how TLS works, when you would use mutual TLS, and how you would manage certificates in production.",
        "category": "crypto",
        "source": "Tech Industry - Blind, 'Let's make a Security Engineer interview experience mega thread' (Amazon security engineer loop, cryptography round: TLS, mTLS, certificate management)",
        "url": "https://www.teamblind.com/post/lets-make-a-security-engineer-interview-experience-mega-thread-f1ur1j53",
        "reported": "candidate experience reports (ongoing)",
        "expected_points": [
            "TLS handshake: cipher negotiation, certificate authentication, key exchange, then symmetric session encryption",
            "mTLS where both sides need strong identity (service-to-service, zero trust); weigh the operational cost",
            "Certificate lifecycle: issuance from a trusted CA, automated rotation, revocation (CRL/OCSP), and short lifetimes",
        ],
    },
    {
        "q": "What is the difference between symmetric and asymmetric encryption, and when would you use each?",
        "category": "crypto",
        "source": "Protecto, Top Security Engineer Interview Questions & Tips",
        "url": "https://www.protecto.ai/blog/security-engineer-interview-questions",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Symmetric uses one shared key (fast, e.g. AES); asymmetric uses a public/private key pair (slower, e.g. RSA)",
            "Use symmetric for bulk data encryption, asymmetric for key exchange and signatures",
            "In practice they are combined (hybrid): asymmetric to agree a key, symmetric for the data",
        ],
    },
    {
        "q": "How do you secure data transfer in transit?",
        "category": "crypto",
        "source": "GitHub (jassics/security-interview-questions), aws-security-interview-questions.md, Data Security section",
        "url": "https://github.com/jassics/security-interview-questions/blob/main/aws-security-interview-questions.md",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "TLS everywhere with modern versions and strong cipher suites; HSTS and certificate pinning where appropriate",
            "Encrypt at the application layer too when the transport is not fully trusted (e.g. message-level encryption)",
            "Validate certificates properly: chain, hostname, expiry, revocation",
        ],
    },
    {
        "q": "Do you agree that data encryption at rest should be enabled by default? Defend your position.",
        "category": "crypto",
        "source": "GitHub (jassics/security-interview-questions), aws-security-interview-questions.md, Data Security section",
        "url": "https://github.com/jassics/security-interview-questions/blob/main/aws-security-interview-questions.md",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Yes in general: cheap baseline protection for lost media, decommissioned disks, and compliance",
            "Acknowledge the limits: at-rest encryption does not protect against a compromised running system or key exposure",
            "Key management is the real question: KMS/HSM, envelope encryption, rotation, and separation of duties",
        ],
    },
    {
        "q": "What is the difference between encryption and hashing, and how would you use hashing alongside encryption?",
        "category": "crypto",
        "source": "Xobin (via HubSpot CDN PDF), Interview Questions to Ask a Cyber Security Analyst",
        "url": "https://f.hubspotusercontent10.net/hubfs/7752519/InterviewGlossary/Interview_Questions_to_Ask_a_Cyber_Security_Analyst_Xobin_Downloaded.pdf",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Encryption is reversible with a key; hashing is one-way and deterministic",
            "Use hashing for integrity checks and password storage (with salt and a slow KDF like bcrypt/argon2, not plain SHA)",
            "Combine them: e.g. encrypt the payload, hash for integrity, or HMAC for authenticated integrity",
        ],
    },
    # ------------------------------------------------------------------
    # incident-response
    # ------------------------------------------------------------------
    {
        "q": "You are the IR lead and receive a call at 2 AM: a major financial institution suspects it is in the middle of an active ransomware deployment. What are your first 15 minutes?",
        "category": "incident-response",
        "source": "GitHub (visionsecuritylabs/awesome-cybersecurity-interview-questions), Incident Response, Senior",
        "url": "https://github.com/visionsecuritylabs/awesome-cybersecurity-interview-questions/blob/HEAD/README.md",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Activate the IR plan and establish command structure immediately",
            "Contain first: isolate affected systems before deep investigation, but preserve forensic state (avoid wiping memory)",
            "Open communication channels with legal, executives, and external comms early",
        ],
    },
    {
        "q": "At 3:00 AM, you notice an EDR alert showing rapid file renaming activity on a file server, with extensions changing to '.locked'. What is your immediate containment action, and how do you determine the scope of the infection?",
        "category": "incident-response",
        "source": "GitHub (nutthakorn7/soc-sop), 05_Incident_Response/Interview_Guide.en.md, Scenario 2: Ransomware Detection",
        "url": "https://github.com/nutthakorn7/soc-sop/blob/HEAD/05_Incident_Response/Interview_Guide.en.md",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Contain immediately: isolate the host via EDR (network isolation, not power-off, to preserve memory)",
            "Scope via SIEM: hunt for the same file-rename behavior, lateral movement (SMB), and the patient zero entry vector",
            "Cut the propagation path: disable compromised accounts, block C2, check backups before any recovery",
        ],
    },
    {
        "q": "A DLP alert shows a senior engineer downloading large amounts of source code to a USB drive at 11 PM on a Friday. Is this necessarily malicious? What factors would you consider, and how would you investigate without alerting the employee?",
        "category": "incident-response",
        "source": "GitHub (nutthakorn7/soc-sop), 05_Incident_Response/Interview_Guide.en.md, Scenario 3: Insider Threat",
        "url": "https://github.com/nutthakorn7/soc-sop/blob/HEAD/05_Incident_Response/Interview_Guide.en.md",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Not necessarily malicious: consider role legitimacy, project context, resignation signals, and past behavior baseline",
            "Investigate quietly: endpoint/DLP logs, badge and VPN records, scope of data vs their normal access",
            "Escalate with evidence to the right owners (manager chain, HR, legal) and preserve evidence with chain of custody",
        ],
    },
    {
        "q": "You are notified of a ransomware attack on your organization. What steps would you prioritize in your response?",
        "category": "incident-response",
        "source": "MockInterviewPro, Top 31 Incident Responder Interview Questions and Answers (2026)",
        "url": "https://www.mockinterviewpro.com/interview-questions/incident-responder",
        "reported": "2026",
        "expected_points": [
            "Isolate affected systems first to prevent spread",
            "Notify the IR team and escalate to management per the response plan",
            "Assess extent and impacted data, then drive recovery from clean backups while communicating status to stakeholders",
        ],
    },
    {
        "q": "A host was reported performing suspicious activities. How would you investigate it, and what things would you check?",
        "category": "incident-response",
        "source": "Glassdoor, Information Security Engineer interview questions, candidate report (Senior Information Security Engineer, interviewed at Wells Fargo, 3 Jul 2026)",
        "url": "https://www.glassdoor.co.uk/Interview/welwyn-garden-city-information-security-engineer-interview-questions-SRCH_IL.0,18_IC2670200_KO19,48_SDRD.htm",
        "reported": "Jul 2026",
        "expected_points": [
            "Start with triage: process list, network connections, scheduled tasks, and recent file changes",
            "Check persistence mechanisms, auth logs, and EDR telemetry; compare against a known-good baseline",
            "Decide contain vs observe based on risk, and preserve evidence before remediation",
        ],
    },
    {
        "q": "Imagine we are facing a supply chain attack via a compromised dependency. What is your response plan?",
        "category": "incident-response",
        "source": "startup.jobs, Application Security Engineer Interview Questions",
        "url": "https://startup.jobs/interview-questions/application-security-engineer",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Determine blast radius: which builds, services, and releases pulled the compromised version (SBOM helps)",
            "Contain: pin or roll back to a known-good version, rotate any exposed secrets, rebuild and redeploy",
            "Harden afterward: dependency pinning, hash verification, private mirror, and monitoring for similar advisories",
        ],
    },
    {
        "q": "How do you perform root cause analysis for security incidents?",
        "category": "incident-response",
        "source": "Hirevire, Pre-Screening Interview Questions to Ask a Cybersecurity Incident Responder",
        "url": "https://hirevire.com/pre-screening-interview-questions/cybersecurity-incident-responder",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Go past the malware to how access was obtained: initial vector, privilege path, and dwell time",
            "Preserve evidence before remediation so the timeline is trustworthy",
            "Close the loop: fix the root cause (patch, config, control gap) and turn the lesson into a detection or process change",
        ],
    },
    # ------------------------------------------------------------------
    # iam-network
    # ------------------------------------------------------------------
    {
        "q": "How would you design authentication and authorization for a multi-tenant SaaS application?",
        "category": "iam-network",
        "source": "startup.jobs, Application Security Engineer Interview Questions",
        "url": "https://startup.jobs/interview-questions/application-security-engineer",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Strong tenant isolation: tenant-scoped identities and data partitioning, enforced server-side on every request",
            "Authentication: SSO/OIDC, MFA enforcement, session management with short lifetimes",
            "Authorization: RBAC or ABAC with least privilege, and tests proving cross-tenant access is impossible",
        ],
    },
    {
        "q": "What is the CIA triad?",
        "category": "iam-network",
        "source": "Glassdoor, Information Security Engineer interview questions (top questions guide)",
        "url": "https://www.glassdoor.co.uk/Interview/welwyn-garden-city-information-security-engineer-interview-questions-SRCH_IL.0,18_IC2670200_KO19,48_SDRD.htm",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Confidentiality: only authorized parties can access the data",
            "Integrity: data is not altered by unauthorized parties",
            "Availability: data and systems are accessible when needed",
        ],
    },
    {
        "q": "What is the difference between a vulnerability, a threat, and a risk?",
        "category": "iam-network",
        "source": "DumpsGate, Cybersecurity Interview Questions That Actually Get Asked in 2026",
        "url": "https://dumpsgate.com/cybersecurity-interview-questions/",
        "reported": "2026",
        "expected_points": [
            "Vulnerability is a weakness; threat is a potential actor or event that could exploit it",
            "Risk is likelihood times impact if the threat exploits the vulnerability",
            "Use the distinction to prioritize: fix high-risk items first, accept or transfer low-risk ones",
        ],
    },
    {
        "q": "What is the OSI model, and why does it matter for security?",
        "category": "iam-network",
        "source": "DumpsGate, Cybersecurity Interview Questions That Actually Get Asked in 2026",
        "url": "https://dumpsgate.com/cybersecurity-interview-questions/",
        "reported": "2026",
        "expected_points": [
            "Seven-layer network model from physical to application",
            "Security controls map to layers: firewalls at L3/L4, TLS at the transport/session boundary, WAF at L7",
            "Use it to reason about where an attack operates and where a control should sit",
        ],
    },
    {
        "q": "What is your process for securing a server?",
        "category": "iam-network",
        "source": "Glassdoor, Information Security Engineer interview questions (top questions guide)",
        "url": "https://www.glassdoor.co.uk/Interview/welwyn-garden-city-information-security-engineer-interview-questions-SRCH_IL.0,18_IC2670200_KO19,48_SDRD.htm",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Harden the OS: minimal install, disable unused services, patch on a cadence",
            "Lock down access: SSH keys only, MFA, least-privilege accounts, host firewall rules",
            "Monitor: centralized logging, integrity monitoring, and a defined patch and backup routine",
        ],
    },
    # ------------------------------------------------------------------
    # detection
    # ------------------------------------------------------------------
    {
        "q": "How do you check for lateral movement activity on a host?",
        "category": "detection",
        "source": "Glassdoor, Information Security Engineer interview questions, candidate report (Senior Information Security Engineer, interviewed at Wells Fargo, 3 Jul 2026)",
        "url": "https://www.glassdoor.co.uk/Interview/welwyn-garden-city-information-security-engineer-interview-questions-SRCH_IL.0,18_IC2670200_KO19,48_SDRD.htm",
        "reported": "Jul 2026",
        "expected_points": [
            "Look for remote logons, new services/scheduled tasks, credential access (LSASS), and unusual SMB/RDP/WinRM activity",
            "Correlate EDR process ancestry with authentication logs to trace the path between hosts",
            "Baseline normal admin behavior first so the anomalies stand out",
        ],
    },
    {
        "q": "What are the different kinds of persistence you can see on a host, how do you investigate them, and what logs do you check?",
        "category": "detection",
        "source": "Glassdoor, Information Security Engineer interview questions, candidate report (Senior Information Security Engineer, interviewed at Wells Fargo, 3 Jul 2026)",
        "url": "https://www.glassdoor.co.uk/Interview/welwyn-garden-city-information-security-engineer-interview-questions-SRCH_IL.0,18_IC2670200_KO19,48_SDRD.htm",
        "reported": "Jul 2026",
        "expected_points": [
            "Common mechanisms: registry run keys, scheduled tasks, services, startup folders, WMI subscriptions, cron/systemd on Linux",
            "Investigate with autoruns-style enumeration, timeline analysis, and hash/signature checks on the binaries",
            "Logs: Sysmon, Windows Security event log, EDR telemetry, and for Linux, auditd and systemd journals",
        ],
    },
    {
        "q": "What are living-off-the-land attacks, and how do you detect them?",
        "category": "detection",
        "source": "Glassdoor, Information Security Engineer interview questions, candidate report (Senior Information Security Engineer, interviewed at Wells Fargo, 3 Jul 2026)",
        "url": "https://www.glassdoor.co.uk/Interview/welwyn-garden-city-information-security-engineer-interview-questions-SRCH_IL.0,18_IC2670200_KO19,48_SDRD.htm",
        "reported": "Jul 2026",
        "expected_points": [
            "Attackers use legitimate built-in tools (PowerShell, WMI, certutil, bitsadmin) so there is no malware to signature",
            "Detect via command-line logging, parent-child process anomalies, and script-block logging",
            "Reduce noise by baselining normal admin use and allowlisting known-good patterns",
        ],
    },
    {
        "q": "Tell me about a recent true positive case that you worked on, and map it to MITRE ATT&CK tactics.",
        "category": "detection",
        "source": "Glassdoor, Information Security Engineer interview questions, candidate report (Senior Information Security Engineer, interviewed at Wells Fargo, 3 Jul 2026)",
        "url": "https://www.glassdoor.co.uk/Interview/welwyn-garden-city-information-security-engineer-interview-questions-SRCH_IL.0,18_IC2670200_KO19,48_SDRD.htm",
        "reported": "Jul 2026",
        "expected_points": [
            "Tell a structured story: initial signal, triage steps, confirmation, and outcome",
            "Map each observed behavior to ATT&CK tactics/techniques (e.g. initial access, execution, persistence)",
            "Close with what changed: detection tuned, gap documented, or hunt launched for similar activity",
        ],
    },
    {
        "q": "What is an IPS and how does it differ from an IDS?",
        "category": "detection",
        "source": "Protecto, Top Security Engineer Interview Questions & Tips",
        "url": "https://www.protecto.ai/blog/security-engineer-interview-questions",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "IDS detects and alerts; IPS sits inline and can actively block the traffic",
            "Trade-off: IPS false positives can break legitimate traffic, while IDS false positives only create alert noise",
            "Placement and tuning matter: run new signatures in detect mode before promoting to block",
        ],
    },
    {
        "q": "What are some common log sources for a SIEM system?",
        "category": "detection",
        "source": "HelloIntern, Security Information And Event Management (SIEM) Interview Questions and Answers",
        "url": "https://hellointern.in/blog/security-information-and-event-management-siem-interview-questions-and-answers-6040",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Name the core sources: firewalls, IDS/IPS, EDR, Windows/Linux servers, web servers, databases",
            "Add network devices, email gateways, identity providers, and cloud audit logs (CloudTrail, Azure Activity)",
            "Note the challenges: normalization, volume, and tuning out false positives",
        ],
    },
    {
        "q": "An external server is making connections toward malicious sites. How would you investigate this?",
        "category": "detection",
        "source": "Glassdoor, Information Security Engineer interview questions, candidate report (Senior Information Security Engineer, interviewed at Wells Fargo, 3 Jul 2026)",
        "url": "https://www.glassdoor.co.uk/Interview/welwyn-garden-city-information-security-engineer-interview-questions-SRCH_IL.0,18_IC2670200_KO19,48_SDRD.htm",
        "reported": "Jul 2026",
        "expected_points": [
            "Validate the intel: check the reputation of the destinations, DNS logs, and proxy/firewall records",
            "Identify the process and user behind the connections on the host, plus the initial access vector",
            "Contain and scope: isolate if malicious, hunt for other hosts contacting the same infrastructure",
        ],
    },
    # ------------------------------------------------------------------
    # behavioral
    # ------------------------------------------------------------------
    {
        "q": "Tell me about a time you discovered a critical vulnerability right before a release. How did you balance risk and timeline?",
        "category": "behavioral",
        "source": "startup.jobs, Application Security Engineer Interview Questions",
        "url": "https://startup.jobs/interview-questions/application-security-engineer",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Frame the risk in business terms: exploitability, blast radius, and what shipping it would cost",
            "Show the trade-off explicitly: what you proposed to defer vs what had to block the release",
            "End with the outcome and the process change that prevented a repeat",
        ],
    },
    {
        "q": "Share an experience where you had to balance security requirements with development timelines and business needs. How did you manage the tension?",
        "category": "behavioral",
        "source": "yardstick.team, Interview Questions for Assessing Application Security Engineer (Decision Making)",
        "url": "https://yardstick.team/interview-questions-by-role/application-security-engineer",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Acknowledge both sides: security risk and legitimate business pressure",
            "Show risk-based prioritization: what shipped with compensating controls, what was non-negotiable",
            "Demonstrate partnership with engineering rather than gatekeeping",
        ],
    },
    {
        "q": "Describe a situation where you had to convince skeptical stakeholders to prioritize a security initiative. How did you approach the conversation, and what was the result?",
        "category": "behavioral",
        "source": "yardstick.team, Interview Questions for Assessing Application Security Engineer (Influence)",
        "url": "https://yardstick.team/interview-questions-by-role/application-security-engineer",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Translated the technical risk into business impact (revenue, customers, compliance, reputation)",
            "Brought evidence: data, precedent incidents, or a cheap proof of concept",
            "State the result honestly, including what you would do differently",
        ],
    },
    {
        "q": "Can you discuss a time you handled a significant security breach?",
        "category": "behavioral",
        "source": "Hirevire, Pre-Screening Interview Questions to Ask a Cybersecurity Incident Responder (Incidents they ran)",
        "url": "https://hirevire.com/pre-screening-interview-questions/cybersecurity-incident-responder",
        "reported": "question bank (ongoing)",
        "expected_points": [
            "Anonymize the incident: timeline, first signal, and what you got wrong before you got it right",
            "Show judgment: containment decisions, escalation, and communication under pressure",
            "Extract the lesson: what changed in detections, process, or architecture afterward",
        ],
    },
]


def by_category(cat: str) -> list[dict]:
    """Return all questions in a category; raise ValueError on unknown category."""
    if cat not in CATEGORIES:
        raise ValueError(f"Unknown security category: {cat!r}. Valid: {CATEGORIES}")
    return [q for q in SECURITY_QUESTIONS if q["category"] == cat]


def search(keyword: str) -> list[dict]:
    """Case-insensitive substring search over question text."""
    kw = keyword.lower()
    return [q for q in SECURITY_QUESTIONS if kw in q["q"].lower()]
