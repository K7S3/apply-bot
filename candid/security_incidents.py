"""Security incident case studies for the security-engineer interview track.

A curated library of public, well-documented breaches and incidents used to
answer questions like "tell me about a security incident you have studied."
Each entry sticks to publicly reported facts (vendor postmortems, regulators,
reputable press) and includes root cause, lessons, interview framing, and
sources. Keep entries free of speculation and of em dashes.
"""

from __future__ import annotations

INCIDENTS: list[dict] = [
    {
        "id": "capital-one-2019",
        "title": "Capital One 2019 AWS breach (SSRF via misconfigured WAF)",
        "year": 2019,
        "summary": (
            "Between March and July 2019, an attacker exfiltrated the personal "
            "data of about 106 million Capital One credit card applicants and "
            "customers (roughly 100 million in the US and 6 million in "
            "Canada), including names, addresses, credit scores, and about "
            "140,000 Social Security numbers. The entry point was a "
            "server-side request forgery (SSRF) flaw in a misconfigured "
            "open-source ModSecurity web application firewall running on an "
            "EC2 instance, which let the attacker reach the EC2 instance "
            "metadata service and pull temporary IAM credentials for an "
            "overly broad WAF role. Those credentials were used to list and "
            "download data from hundreds of S3 buckets. The attacker, Paige "
            "Thompson, was identified after posting about the theft and was "
            "arrested by the FBI. Capital One paid an $80 million OCC civil "
            "money penalty in 2020 and a $190 million class-action settlement."
        ),
        "root_cause": (
            "A misconfigured WAF allowed SSRF to the EC2 metadata service, "
            "and the instance's IAM role carried far broader S3 permissions "
            "than it needed, turning a server-side request forgery into a "
            "106-million-record breach. Encryption at rest did not help "
            "because the stolen credentials were legitimate callers."
        ),
        "lessons": [
            "SSRF against cloud metadata services is a top-tier cloud "
            "attack path: enforce IMDSv2 and block metadata access at the "
            "network layer so application bugs cannot reach it.",
            "Least privilege for IAM roles is not cosmetic: the blast radius "
            "was decided by the role's S3 permissions, not by the initial "
            "bug.",
            "Cloud security needs risk assessment and controls designed for "
            "the cloud, not lifted from on-prem: the OCC penalty centered on "
            "Capital One's failure to establish effective cloud risk "
            "processes before migrating.",
            "Detection must catch valid-credential abuse, not just malware: "
            "the theft used normal AWS API calls that looked legitimate.",
            "Data minimization and retention limits shrink the prize: "
            "application data going back years multiplied the damage.",
        ],
        "interview_framing": (
            "This is the go-to story for cloud security, SSRF, and least "
            "privilege. Walk through the kill chain in order (WAF SSRF, "
            "metadata service, IAM role, S3) to show you understand how "
            "cloud failures compose, and finish with concrete mitigations "
            "(IMDSv2, scoped roles, egress controls). It shows you think in "
            "blast radius and defense in depth rather than single bugs."
        ),
        "sources": [
            {
                "label": "OCC news release: $80M civil money penalty against Capital One (2020)",
                "url": "https://occ.gov/news-issuances/news-releases/2020/nr-occ-2020-101.html",
            },
            {
                "label": "Wiz incident writeup: Capital One incident (March 2019)",
                "url": "http://threats.wiz.io/all-incidents/capital-one-incident-march-2019",
            },
        ],
    },
    {
        "id": "solarwinds-sunburst-2020",
        "title": "SolarWinds SUNBURST supply-chain compromise (2020)",
        "year": 2020,
        "summary": (
            "Attackers attributed to Russia's SVR compromised SolarWinds' "
            "software build environment and inserted a backdoor called "
            "SUNBURST into legitimate, code-signed Orion network-monitoring "
            "updates released between March and June 2020. About 18,000 "
            "organizations installed a trojanized update, and the attackers "
            "then selectively exploited a smaller set of high-value targets, "
            "including US federal agencies and major companies, using the "
            "backdoor plus forged SAML tokens for cloud access. The compromise "
            "was discovered in December 2020 when FireEye found it had been "
            "breached and traced the intrusion to the Orion update. CISA "
            "issued Emergency Directive 21-01 ordering federal agencies to "
            "disconnect or power down Orion, and in 2021 the US government "
            "formally attributed the campaign to Russia and imposed "
            "sanctions."
        ),
        "root_cause": (
            "The build pipeline itself was the attack surface: once the "
            "attackers controlled the build, their malware inherited "
            "SolarWinds' legitimate code signature and the trust customers "
            "place in signed updates. Victim-side monitoring largely trusts "
            "signed vendor software, so the backdoor ran with high privilege "
            "inside protected networks."
        ),
        "lessons": [
            "Signed does not mean safe: protect the build as tier-zero "
            "infrastructure with isolated builders, minimal secrets, and "
            "integrity checks on what the pipeline emits.",
            "Software bills of materials (SBOM) and provenance (SLSA-style "
            "attestations) make supply-chain compromise detectable instead "
            "of an act of faith.",
            "Identity is a perimeter: SUNBURST's follow-on activity forged "
            "SAML tokens to reach cloud data, so federation trust and token "
            "signing keys need the same protection as domain admin.",
            "Privilege matters for trusted software: Orion ran with deep "
            "network access, so one trojanized update meant domain-wide "
            "footholds in thousands of customers.",
            "Staged rollouts and out-of-band behavior monitoring for vendor "
            "updates catch what signature checks cannot.",
        ],
        "interview_framing": (
            "Use this when asked about supply chain, trust models, or "
            "nation-state tradecraft. Emphasize that the decisive move was "
            "attacking the build rather than the product, and talk about "
            "what you would change in your own pipeline (hermetic builds, "
            "provenance, staged updates). It shows you reason about trust "
            "boundaries instead of assuming the vendor is the trusted party."
        ),
        "sources": [
            {
                "label": "CISA Emergency Directive 21-01: Mitigate SolarWinds Orion Code Compromise",
                "url": "https://www.cisa.gov/news-events/directives/ed-21-01-mitigate-solarwinds-orion-code-compromise",
            },
            {
                "label": "CISA: Remediating Networks Affected by the SolarWinds and AD/M365 Compromise",
                "url": "https://www.cisa.gov/news-events/news/remediating-networks-affected-solarwinds-and-active-directorym365-compromise",
            },
        ],
    },
    {
        "id": "log4shell-2021",
        "title": "Log4Shell (CVE-2021-44228) Log4j remote code execution (2021)",
        "year": 2021,
        "summary": (
            "Log4Shell was a critical remote code execution vulnerability in "
            "Apache Log4j 2 (versions 2.0-beta9 through 2.14.1), disclosed on "
            "December 9, 2021, after a private report from Alibaba's security "
            "team on November 24. A crafted string in logged data triggered "
            "JNDI lookups that made the application fetch and execute "
            "attacker-controlled Java classes, a one-line unauthenticated "
            "RCE with a CVSS score of 10.0. Because Log4j is embedded in "
            "countless Java applications, including Minecraft servers and "
            "enterprise products, exploitation began within days and ranged "
            "from cryptominers to ransomware crews and nation-state actors. "
            "The initial fix proved incomplete, producing follow-on CVEs "
            "(CVE-2021-45046, CVE-2021-45105, CVE-2021-44832), and the safe "
            "versions converged on Log4j 2.17.1."
        ),
        "root_cause": (
            "A logging library performed message-lookup substitution, "
            "including JNDI, on untrusted input, so data that was only meant "
            "to be written to a log was interpreted as code. The feature "
            "existed since 2013 and the blast radius came from Log4j's "
            "near-universal, often invisible, presence as a transitive "
            "dependency."
        ),
        "lessons": [
            "Know your transitive dependencies: most organizations learned "
            "about their Log4j exposure only after the disclosure, so SBOMs "
            "and dependency inventories are prerequisites, not nice-to-haves.",
            "Egress controls and network segmentation blunt RCE: blocking "
            "outbound LDAP/RMI from app servers would have broken the "
            "exploit chain for many victims.",
            "Features that interpret untrusted input are vulnerabilities "
            "waiting for an audience: message lookups in a logger were a "
            "convenience with catastrophic downside.",
            "Patch verification beats patch deployment: the 2.15.0 fix was "
            "bypassed, so defenders had to track follow-on CVEs and "
            "confirm the final safe versions.",
            "Incident response needs an internet-scale plan: CISA's "
            "emergency guidance and mass scanning showed that comms, "
            "detection signatures, and coordinated rollout matter as much "
            "as the patch.",
        ],
        "interview_framing": (
            "Log4Shell is the modern answer to questions about dependency "
            "risk, zero-days, and incident response at scale. Describe the "
            "mechanism crisply (JNDI lookup in logged input, one unauthenticated "
            "request, full RCE) and pivot to what you would do on day one: "
            "inventory, WAF rules, egress blocks, and staged patching. It "
            "shows you can go from technical detail to operational plan."
        ),
        "sources": [
            {
                "label": "CISA Advisory AA21-356A: Mitigating Log4Shell and Other Log4j Vulnerabilities",
                "url": "https://www.cisa.gov/news-events/cybersecurity-advisories/aa21-356a",
            },
            {
                "label": "JFrog: Log4Shell zero-day vulnerability (CVE-2021-44228) writeup and timeline",
                "url": "https://jfrog.com/blog/log4shell-0-day-vulnerability-all-you-need-to-know/",
            },
        ],
    },
    {
        "id": "equifax-2017",
        "title": "Equifax 2017 breach (unpatched Apache Struts CVE-2017-5638)",
        "year": 2017,
        "summary": (
            "From May through July 2017, attackers breached Equifax and "
            "stole the personal data of about 147 million people, including "
            "names, Social Security numbers, dates of birth, and addresses. "
            "The way in was CVE-2017-5638, a remote code execution flaw in "
            "the Jakarta Multipart parser of Apache Struts, exploitable with "
            "a crafted Content-Type header and patched by Apache in March "
            "2017, more than two months before the intrusion. Equifax failed "
            "to apply the patch to its online dispute portal despite an "
            "internal notification, and the attackers operated undetected "
            "for 76 days, partly because an expired certificate had silently "
            "blinded a network-monitoring sensor. Equifax disclosed the "
            "breach in September 2017 and later settled with the FTC, CFPB, "
            "and states for at least $575 million, up to $700 million."
        ),
        "root_cause": (
            "A known, patched, actively exploited RCE stayed live on an "
            "internet-facing system because patching was a notification "
            "process rather than a verified one, and detection silently "
            "failed at the same time: a dead monitoring sensor looks exactly "
            "like a quiet network."
        ),
        "lessons": [
            "Treat public RCE on internet-facing systems as an emergency: "
            "confirm the patch landed on every system, because an accurate "
            "asset inventory is what makes patching verifiable.",
            "Test that detection actually works: expired certificates, "
            "broken log pipelines, and silent sensor failures must be "
            "caught by the monitoring that watches the monitors.",
            "Flat networks and plaintext credentials turn one foothold "
            "into 147 million records: segment and manage secrets so the "
            "entry bug is not the whole story.",
            "Borrowed identifiers (SSNs, dates of birth) cannot be rotated "
            "like passwords, so the data you hold decides how much care it "
            "deserves: minimize and encrypt it.",
            "Accountability follows process failures: the CEO, CIO, and "
            "CSO all departed, and the FTC settlement imposed a "
            "comprehensive security program.",
        ],
        "interview_framing": (
            "This is the canonical patching and detection story. The "
            "memorable framing is that nobody needed a zero-day: the "
            "attackers used a two-month-old patch against a company that "
            "thought it had patched. Use it to argue for verification over "
            "notification, tested detection, and segmentation, which shows "
            "you think in operational realities, not just vulnerability "
            "lists."
        ),
        "sources": [
            {
                "label": "TechTarget: Equifax to pay up to $700 million in data breach settlement",
                "url": "https://www.techtarget.com/cybersecurity/news/252467172/Equifax-to-pay-up-to-700-million-in-data-breach-settlement",
            },
            {
                "label": "techearl: Equifax Breach, unpatched Apache Struts RCE explained",
                "url": "https://techearl.com/equifax-breach-apache-struts-rce",
            },
        ],
    },
    {
        "id": "target-2013",
        "title": "Target 2013 breach (HVAC vendor credentials, POS malware)",
        "year": 2013,
        "summary": (
            "Over the 2013 holiday season, attackers stole about 40 million "
            "payment card numbers and the personal data of up to 70 million "
            "customers from Target. The intrusion began with a malware-laced "
            "phishing email to Fazio Mechanical Services, Target's HVAC "
            "contractor, which installed the Citadel password-stealing "
            "malware and yielded the contractor's credentials for Target's "
            "vendor portal. The attackers pivoted from the portal into "
            "Target's internal network, which lacked adequate segmentation "
            "between vendor access and payment systems, and deployed "
            "BlackPOS memory-scraping malware to point-of-sale terminals. "
            "Target's own FireEye alerts fired but were not acted on, and "
            "the breach was confirmed only after an external payment "
            "processor flagged fraud in December 2013."
        ),
        "root_cause": (
            "A third party's weak security became Target's breach because "
            "the vendor portal was not segmented from the payment network: "
            "once the attackers held contractor credentials, nothing stood "
            "between the portal and the point-of-sale environment."
        ),
        "lessons": [
            "Third-party risk is first-party risk: your attack surface "
            "includes every vendor with network access, so assess and "
            "constrain what they can reach.",
            "Segment by function, not by org chart: contractor access, "
            "corporate IT, and payment systems must be isolated so one "
            "compromised credential cannot traverse the company.",
            "An alert nobody acts on is not a control: FireEye fired and "
            "the SOC deprioritized it, so alert triage and escalation paths "
            "need the same testing as the sensors.",
            "Memory-scraping malware defeats at-rest encryption: encrypting "
            "card data in transit and at rest did not protect data read "
            "live from POS RAM, which is why end-to-end encryption and "
            "tokenization of card data became the retail standard.",
            "Assume the vendor will be phished: phishing-resistant access "
            "controls for third parties reduce the value of a stolen "
            "password.",
        ],
        "interview_framing": (
            "This is the third-party risk and segmentation case study, and "
            "it is disarming because the entry point was an HVAC company. "
            "Use it to show you think about the whole kill chain, not just "
            "the first hop: phishing, credential theft, lateral movement, "
            "POS malware, ignored alerts. It signals that you design for "
            "the reality that partners are softer targets."
        ),
        "sources": [
            {
                "label": "Krebs on Security: Target Hackers Broke in Via HVAC Company",
                "url": "https://krebsonsecurity.com/2014/02/target-hackers-broke-in-via-hvac-company/",
            },
            {
                "label": "Computerworld: Target breach happened because of a basic network segmentation error",
                "url": "https://www.computerworld.com/article/1517305/target-breach-happened-because-of-a-basic-network-segmentation-error.html",
            },
        ],
    },
    {
        "id": "uber-2016",
        "title": "Uber 2016 breach and cover-up (AWS keys in GitHub)",
        "year": 2016,
        "summary": (
            "In October 2016, two attackers accessed a private GitHub "
            "repository used by Uber engineers, found AWS credentials, and "
            "used them to download the names, email addresses, and phone "
            "numbers of 57 million riders and drivers, plus the driver's "
            "license numbers of about 600,000 US drivers, from an AWS-hosted "
            "data store. Instead of disclosing the breach, Uber paid the "
            "attackers $100,000 through its bug bounty program to delete the "
            "data and keep quiet, and did not notify regulators or victims. "
            "The breach was concealed for over a year until new CEO Dara "
            "Khosrowshahi disclosed it in November 2017, fired chief "
            "security officer Joe Sullivan, and Uber later paid $148 million "
            "to settle with all 50 states."
        ),
        "root_cause": (
            "Hardcoded cloud credentials in source control gave attackers a "
            "direct path to customer data, and then the company compounded "
            "a technical failure with a governance one: leadership chose "
            "concealment, routed the payment through the bug bounty "
            "program, and skipped legally required breach notification."
        ),
        "lessons": [
            "Never hardcode credentials: secret scanning in CI, short-lived "
            "credentials, and instance roles exist precisely to keep keys "
            "out of Git.",
            "Bug bounty programs are for vuln reports, not ransom: "
            "channeling a payoff through the bounty program corrupted the "
            "program and deepened the cover-up.",
            "Disclosure is a legal obligation, not a PR choice: the "
            "concealment turned a breach into a $148 million settlement, "
            "regulatory investigations, and executive terminations.",
            "Cloud data stores need the same access hygiene as production "
            "databases: credential rotation, least privilege, and anomaly "
            "detection on bulk downloads.",
            "Culture is a security control: the cover-up decision was made "
            "at the top, so security culture has to be owned by "
            "leadership, not just the security team.",
        ],
        "interview_framing": (
            "This is the secrets-management and ethics case study in one. "
            "The technical hook is hardcoded AWS keys, but the interview "
            "value is in discussing the cover-up: why disclosure laws "
            "exist, how you would handle pressure to stay quiet, and what "
            "governance separates a bounty from a bribe. It shows integrity "
            "and judgment, which interviewers weigh heavily for security "
            "roles."
        ),
        "sources": [
            {
                "label": "Threatpost: Uber Reveals 2016 Breach of 57 Million User Accounts",
                "url": "https://threatpost.com/uber-reveals-breach-of-57-million-users-admits-to-covering-up-incident/128969/",
            },
            {
                "label": "TechCrunch: Uber data breach from 2016 affected 57 million riders and drivers",
                "url": "https://techcrunch.com/2017/11/21/uber-data-breach-from-2016-affected-57-million-riders-and-drivers/",
            },
        ],
    },
    {
        "id": "lastpass-2022",
        "title": "LastPass 2022-2023 breach (DevOps engineer's home PC to vault backups)",
        "year": 2022,
        "summary": (
            "In August 2022, LastPass disclosed that attackers had accessed "
            "its development environment through a single compromised "
            "employee account, taking source code and technical "
            "information. In December 2022, LastPass disclosed a second, "
            "worse phase: the same actor had stolen backup copies of "
            "customer vault data from cloud storage, including both "
            "AES-256-encrypted vault contents and unencrypted metadata "
            "like website URLs and usernames. LastPass later revealed that "
            "the actor had compromised a DevOps engineer's personal home "
            "computer by exploiting a remote code execution flaw in a "
            "third-party media software package, installed a keylogger, and "
            "captured the engineer's master password after MFA. The "
            "stolen vaults were then brute-forced where customers used weak "
            "master passwords, and researchers linked over $35 million in "
            "cryptocurrency thefts to the breach."
        ),
        "root_cause": (
            "A privileged engineer's personal device became corporate "
            "infrastructure: the keylogger captured credentials that "
            "unlocked production backup keys, because access to cloud "
            "storage decryption keys did not require a hardened, "
            "company-managed endpoint."
        ),
        "lessons": [
            "BYOD and remote work expand the trust boundary to home PCs: "
            "access to crown-jewel systems should require managed, "
            "hardened endpoints with EDR.",
            "Keyloggers defeat passwords and post-auth capture defeats "
            "MFA in session: phishing-resistant MFA and hardware keys "
            "matter for privileged access.",
            "Secrets belong in vaults with access controls, not in "
            "development environments: the cloud storage keys the "
            "attacker needed were reachable from the dev network.",
            "Encrypt metadata too when you can: unencrypted URLs and "
            "usernames turned stolen vaults into phishing target lists "
            "even before any brute forcing.",
            "Iteration matters in incident response: the first disclosure "
            "understated the impact and the follow-ups eroded trust, so "
            "communicate what is known, what is not, and what changes.",
        ],
        "interview_framing": (
            "This is the privileged-access and incident-response case "
            "study, and it is especially sharp for a password-manager "
            "company: the defenders' own vault product was not the failure "
            "point, endpoint and key management were. Use it to discuss "
            "how you would scope privileged access and how you would "
            "handle disclosure when the facts are still developing. It "
            "shows you think about trust boundaries at the human layer."
        ),
        "sources": [
            {
                "label": "Infosecurity Magazine: Keylogger on Employee Home PC Led to LastPass 2022 Breach",
                "url": "https://www.infosecurity-magazine.com/news/lastpass-data-breach-update/",
            },
            {
                "label": "The Hacker News: LastPass Reveals Second Attack Resulting in Breach of Encrypted Password Vaults",
                "url": "http://thehackernews.com/2023/02/lastpass-reveals-second-attack.html?hl=ru",
            },
        ],
    },
    {
        "id": "moveit-2023",
        "title": "MOVEit 2023 mass exploitation (Cl0p, SQL injection zero-day)",
        "year": 2023,
        "summary": (
            "Starting on Memorial Day weekend 2023, the Cl0p ransomware "
            "group mass-exploited CVE-2023-34362, a SQL injection zero-day in "
            "the web interface of Progress Software's MOVEit Transfer "
            "managed file transfer product. The attackers deployed the "
            "LEMURLOOT web shell, pulled files and database records from "
            "internet-facing servers, and pivoted to pure data-theft "
            "extortion, threatening to publish stolen data on a leak site "
            "without encrypting anything. Progress patched the flaw on May "
            "31, 2023, but by then the campaign had hit more than 2,500 "
            "organizations and tens of millions of individuals, including "
            "the BBC, British Airways, Shell, and US government agencies. "
            "CISA published emergency guidance in advisory AA23-158A, and "
            "further MOVEit SQL injection CVEs surfaced through the summer."
        ),
        "root_cause": (
            "A classic SQL injection in an internet-facing file-transfer "
            "application became a supply-chain catastrophe: MOVEit servers "
            "aggregate the sensitive data of many downstream organizations, "
            "so one zero-day in one product exposed thousands of companies "
            "that had never heard of it."
        ),
        "lessons": [
            "SQL injection is not a legacy problem: a 2023 SQLi zero-day "
            "produced one of the year's largest breaches, so parameterized "
            "queries and input validation remain foundational.",
            "Internet-facing data-aggregation systems are high-value "
            "targets: file-transfer appliances hold everyone's sensitive "
            "data, so patch them on an emergency cadence and minimize what "
            "they retain.",
            "Extortion without encryption is a viable business model: "
            "ransomware groups no longer need to encrypt to get paid, so "
            "backups alone do not defeat modern extortion.",
            "Know your vendors' vendors: most victims learned about their "
            "MOVEit exposure from their suppliers, so map which third "
            "parties move your data through which products.",
            "Speed of patching is the whole game for zero-days: the "
            "attackers stockpiled the exploit and struck over a holiday "
            "weekend, compressing the response window.",
        ],
        "interview_framing": (
            "This is the supply-chain and extortion case study for the "
            "modern era. The striking detail is that SQL injection, a bug "
            "class people call solved, drove a multi-thousand-victim "
            "campaign because of shared infrastructure. Use it to argue "
            "for patching SLAs, vendor mapping, and data minimization, "
            "which shows you connect a code-level bug class to "
            "organizational-scale consequences."
        ),
        "sources": [
            {
                "label": "CISA Advisory AA23-158A: CL0P Ransomware Gang Exploits CVE-2023-34362 MOVEit Vulnerability",
                "url": "https://www.cisa.gov/news-events/cybersecurity-advisories/aa23-158a",
            },
            {
                "label": "techearl: MOVEit Breach, SQL Injection at Supply-Chain Scale",
                "url": "https://techearl.com/moveit-breach-sql-injection",
            },
        ],
    },
]


def get(iid: str) -> dict:
    """Return the incident dict for *iid*.

    Raises KeyError if the id is unknown.
    """
    for incident in INCIDENTS:
        if incident["id"] == iid:
            return incident
    raise KeyError(f"unknown security incident: {iid!r}")


def list_incidents() -> list[dict]:
    """Return lightweight {id, title, year} summaries in definition order."""
    return [
        {"id": incident["id"], "title": incident["title"],
         "year": incident["year"]}
        for incident in INCIDENTS
    ]


def search(keyword: str) -> list[dict]:
    """Case-insensitive search of *keyword* over title, summary, lessons.

    Returns the full incident dicts that match, in definition order.
    """
    needle = keyword.lower()
    results = []
    for incident in INCIDENTS:
        haystack = "\n".join(
            [incident["title"], incident["summary"]] + incident["lessons"]
        ).lower()
        if needle in haystack:
            results.append(incident)
    return results


__all__ = ["INCIDENTS", "get", "list_incidents", "search"]
