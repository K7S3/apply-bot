"""Self-assessment to study plan for the security-engineer interview track.

The user rates themselves 1-5 in each security domain; this module turns the
ratings into a prioritized study plan that references concept slugs from
``candid.security_concepts`` and security question practice.

Usage:
    from candid import security_gaps
    plan = security_gaps.assess({
        "appsec": 4, "cloudsec": 3, "threat-modeling": 2,
        "crypto": 2, "incident-response": 4, "iam": 3,
        "detection": 2, "network-security": 3,
        "supply-chain": 2, "governance": 1,
    })
"""

from __future__ import annotations

DOMAINS: list[dict] = [
    {
        "id": "appsec",
        "name": "Application Security",
        "description": "Secure coding, OWASP Top 10, input validation, auth flaws, code review.",
        "concept_refs": ["owasp_top_10", "secure_code_review", "authentication_attacks"],
        "question_category": "appsec",
    },
    {
        "id": "cloudsec",
        "name": "Cloud Security",
        "description": "IAM policies, misconfiguration, shared responsibility, logging in AWS/GCP/Azure.",
        "concept_refs": ["shared_responsibility", "cloud_misconfiguration", "iam_least_privilege"],
        "question_category": "cloudsec",
    },
    {
        "id": "threat-modeling",
        "name": "Threat Modeling",
        "description": "STRIDE, attack trees, asset/trust boundaries, walking through a feature design.",
        "concept_refs": ["stride", "attack_trees", "trust_boundaries"],
        "question_category": "threat-modeling",
    },
    {
        "id": "crypto",
        "name": "Cryptography",
        "description": "Symmetric/asymmetric crypto, hashing, TLS, key management, common misuse.",
        "concept_refs": ["tls_handshake", "hashing_vs_encryption", "key_management"],
        "question_category": "crypto",
    },
    {
        "id": "incident-response",
        "name": "Incident Response",
        "description": "Detection triage, containment, eradication, postmortems, tabletop exercises.",
        "concept_refs": ["incident_lifecycle", "containment_strategies", "blameless_postmortems"],
        "question_category": "incident-response",
    },
    {
        "id": "iam",
        "name": "Identity & Access Management",
        "description": "SSO/OIDC/SAML, MFA, RBAC vs ABAC, least privilege, secrets management.",
        "concept_refs": ["oidc_saml", "mfa_factors", "rbac_abac", "secrets_management"],
        "question_category": "iam",
    },
    {
        "id": "detection",
        "name": "Detection & Monitoring",
        "description": "SIEM rules, detection engineering, alert tuning, reducing false positives.",
        "concept_refs": ["detection_engineering", "siem_tuning", "false_positive_management"],
        "question_category": "detection",
    },
    {
        "id": "network-security",
        "name": "Network Security",
        "description": "Firewalls, segmentation, zero trust, WAF, DDoS mitigation, packet analysis.",
        "concept_refs": ["zero_trust", "network_segmentation", "waf_ddos"],
        "question_category": "network-security",
    },
    {
        "id": "supply-chain",
        "name": "Supply Chain Security",
        "description": "Dependency risk, SBOM, artifact signing, CI/CD pipeline hardening.",
        "concept_refs": ["sbom", "artifact_signing", "cicd_hardening"],
        "question_category": "supply-chain",
    },
    {
        "id": "governance",
        "name": "Governance, Risk & Compliance",
        "description": "SOC 2, ISO 27001, risk assessments, audits, security questionnaires.",
        "concept_refs": ["soc2_controls", "risk_assessment", "audit_evidence"],
        "question_category": "governance",
    },
]

_DOMAIN_BY_ID = {d["id"]: d for d in DOMAINS}


def _validate(ratings: dict[str, int]) -> None:
    if not isinstance(ratings, dict):
        raise ValueError("ratings must be a dict mapping domain id to an int 1-5")
    for domain_id, rating in ratings.items():
        if domain_id not in _DOMAIN_BY_ID:
            raise ValueError(f"unknown domain id: {domain_id!r}")
        if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5:
            raise ValueError(f"rating for {domain_id!r} must be an int between 1 and 5, got {rating!r}")


def _priority(rating: int) -> str:
    if rating <= 2:
        return "high"
    if rating == 3:
        return "medium"
    return "low"


def assess(ratings: dict[str, int]) -> dict:
    """Turn domain self-ratings into a prioritized study plan.

    ``ratings`` maps domain id to a self-rating int 1-5. Returns
    ``{"plan": [...], "weakest": [...]}`` where each plan entry has
    ``domain``, ``rating``, ``priority`` ("high"/"medium"/"low"), and
    ``actions`` (2-3 concrete next steps referencing concept slugs and
    question practice). ``weakest`` lists ids with rating <= 2.

    Raises ValueError for ratings outside 1-5 or unknown domain ids.
    """
    _validate(ratings)
    plan = []
    for domain in DOMAINS:
        rating = ratings.get(domain["id"])
        if rating is None:
            continue
        refs = ", ".join(domain["concept_refs"])
        plan.append(
            {
                "domain": domain["id"],
                "rating": rating,
                "priority": _priority(rating),
                "actions": [
                    f"Study concept deep-dives: {refs}.",
                    f"Practice {domain['question_category']} interview questions (timed).",
                    f"Write one STAR story from your experience in {domain['name'].lower()}.",
                ],
            }
        )
    plan.sort(key=lambda e: (0 if e["priority"] == "high" else 1 if e["priority"] == "medium" else 2, e["domain"]))
    weakest = [domain["id"] for domain in DOMAINS if ratings.get(domain["id"]) is not None and ratings[domain["id"]] <= 2]
    return {"plan": plan, "weakest": weakest}


def run_assessment() -> dict:
    """Interactively prompt for 1-5 ratings per domain and print a plan."""
    print("Rate yourself 1-5 in each security domain (1 = new to this, 5 = could teach it).\n")
    ratings: dict[str, int] = {}
    for domain in DOMAINS:
        print(f"{domain['name']}: {domain['description']}")
        while True:
            raw = input(f"  Rating for '{domain['id']}' (1-5): ").strip()
            try:
                rating = int(raw)
                if 1 <= rating <= 5:
                    ratings[domain["id"]] = rating
                    break
            except ValueError:
                pass
            print("  Please enter an integer from 1 to 5.")
    result = assess(ratings)
    print("\n=== Your security study plan (highest priority first) ===")
    for entry in result["plan"]:
        domain = _DOMAIN_BY_ID[entry["domain"]]
        print(f"\n[{entry['priority'].upper()}] {domain['name']} (self-rating {entry['rating']}/5)")
        for i, action in enumerate(entry["actions"], 1):
            print(f"  {i}. {action}")
    if result["weakest"]:
        print(f"\nWeakest domains (start here): {', '.join(result['weakest'])}")
    return result
