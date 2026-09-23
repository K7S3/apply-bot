"""SRE runbooks: troubleshooting playbooks, blameless postmortems, IaC review drills.

This module is self-contained and dependency-free: no network calls, no paid
APIs, no secrets. All content is static reference material, so every function
here is pure and safe to call from tests.

CLI contract (wired by the parent `sre` command group):
  - register(subparsers): adds the `playbook`, `postmortem`, and `iac-review`
    subcommands, each with func=dispatch.
  - dispatch(args): reads args.sre_cmd and runs the right logic, returns an
    exit code.
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

from candid import config as C

# ---------------------------------------------------------------------------
# 1. Troubleshooting playbooks
# ---------------------------------------------------------------------------

PLAYBOOKS: dict[str, dict[str, object]] = {
    "disk-full": {
        "title": "Disk Full",
        "symptoms": [
            "Writes fail with 'No space left on device' even though df shows some free inodes.",
            "Applications crash on startup or refuse to accept uploads / write temp files.",
            "Database reports 'could not extend file' or goes read-only.",
            "Log shipping agents (fluentd, filebeat) back up and lag grows.",
        ],
        "diagnosis": [
            "Run `df -h` and `df -i` to separate byte-full from inode-full conditions.",
            "Run `du -sh /*` then drill into the largest directories with "
            "`du -sh /var/* | sort -h`.",
            "Check for deleted-but-open files: `lsof +L1` (space is not freed "
            "until the process closes the handle).",
            "Check journald usage: `journalctl --disk-usage`; check Docker: "
            "`docker system df` and dangling volumes with `docker volume ls -f dangling=true`.",
            "Look for runaway growth: `find /var/log -type f -size +1G` and "
            "core dumps in `/var/crash` or the app working dir.",
        ],
        "root_causes": [
            "Log files growing without rotation (logrotate missing or misconfigured).",
            "A deleted log file still held open by a long-running process.",
            "Unbounded temp / upload directories with no cleanup job.",
            "Docker overlay layers, unused images, and volumes accumulating.",
            "Core dumps or heap dumps left behind after a crash.",
        ],
        "fix": [
            "Truncate (do not delete) logs held open by processes: `: > /path/to/app.log`.",
            "Vacuum journald: `journalctl --vacuum-size=500M` or `--vacuum-time=7d`.",
            "Prune Docker: `docker system prune -af --volumes` (confirm nothing needed first).",
            "Remove stale temp files older than N days: `find /tmp -type f -atime +7 -delete`.",
            "Move the service's data or logs to a larger volume if the partition is undersized.",
        ],
        "verification": [
            "`df -h` shows usage back under 80% and `df -i` shows free inodes.",
            "Application can write: `touch /data/.write-test && rm /data/.write-test`.",
            "Log shipping lag returns to near zero and error logs stop.",
        ],
        "prevention": [
            "Alert at 80% and page at 90% disk usage on every partition.",
            "Ensure logrotate (or equivalent) covers every log path, with size caps.",
            "Add tmpwatch / scheduled cleanup for temp and upload directories.",
            "Run `docker system prune` on a schedule or set Docker log limits in daemon.json.",
        ],
    },
    "oomkilled": {
        "title": "Container / Process OOMKilled",
        "symptoms": [
            "Container exits with code 137, or Kubernetes shows `OOMKilled` in `kubectl get pods`.",
            "Process disappears with no application-level error; dmesg shows 'Out of memory: Killed process'.",
            "Restarts happen under load or during batch / GC-heavy work, then recover.",
        ],
        "diagnosis": [
            "Confirm the kill: `dmesg -T | grep -i 'killed process'` or "
            "`kubectl describe pod <name>` and read Last State.",
            "Compare actual usage vs limit: `kubectl top pod` and the container's "
            "memory limit in the Deployment / docker run flags.",
            "Check the app's own memory settings: JVM -Xmx, Node --max-old-space-size, "
            "Go GOGC / GOMEMLIMIT, Python worker count.",
            "Look for growth over time (leak) vs sudden spike: graph container memory "
            "for the hours before the kill.",
            "Correlate with load: request rate, queue depth, or batch job start times.",
        ],
        "root_causes": [
            "Memory limit set below the app's steady-state need (common after copy-pasting a template).",
            "Heap sized larger than the container limit (JVM defaults to 1/4 of host RAM, not container RAM).",
            "Memory leak: unbounded caches, unclosed connections, or growing in-memory queues.",
            "Traffic or batch spike that legitimately needs more headroom.",
        ],
        "fix": [
            "Short term: raise the memory limit (and request) to give headroom; "
            "restart the workload.",
            "Set the runtime heap explicitly below the limit (e.g. -Xmx at 75% of the limit).",
            "For leaks: take a heap dump before the kill (e.g. -XX:+HeapDumpOnOutOfMemoryError) "
            "and fix the leak; add heap profiling to CI load tests.",
            "For spikes: add autoscaling (HPA on memory or custom metric) or rate limiting.",
        ],
        "verification": [
            "No further OOMKilled events for 24h under normal load.",
            "Peak container memory stays under ~80% of the limit on the dashboard.",
            "Load test at peak traffic completes without restarts.",
        ],
        "prevention": [
            "Always set both requests and limits; derive them from load-test data, not guesses.",
            "Alert when container memory exceeds 85% of its limit for 10 minutes.",
            "Make OOM events a deploy-gate metric: a canary that OOMs never promotes.",
            "Document the app's memory model (heap vs off-heap, worker count) in the runbook.",
        ],
    },
    "tls-expiry": {
        "title": "TLS Certificate Expiry",
        "symptoms": [
            "Browsers and API clients fail with certificate expired / not trusted errors.",
            "curl fails: 'SSL certificate problem: certificate has expired'.",
            "Monitoring shows HTTPS checks red while HTTP and the app itself are fine.",
        ],
        "diagnosis": [
            "Check the served cert: `echo | openssl s_client -connect host:443 -servername host "
            "2>/dev/null | openssl x509 -noout -dates -issuer`.",
            "Check what the automation last did: `certbot certificates`, renewal logs in "
            "/var/log/letsencrypt/, or the cron / systemd timer status.",
            "Verify which cert the server actually loads (nginx -T, apachectl -S) vs the renewed file.",
            "Check intermediate / CA expiry too, not just the leaf.",
        ],
        "root_causes": [
            "Auto-renewal broken: expired ACME account key, failed HTTP-01/DNS-01 challenge, "
            "or firewall blocking port 80.",
            "Renewed cert never reloaded: web server not restarted / reloaded by the deploy hook.",
            "Cert pinned or hardcoded in a config, client trust store, or mobile app bundle.",
            "Monitoring only checked HTTP 200, never cert validity.",
        ],
        "fix": [
            "Renew now: `certbot renew --force-renewal` (or your CA's flow) and reload "
            "the web server: `nginx -s reload` / `systemctl reload apache2`.",
            "If the challenge fails, fix DNS / port 80 reachability first, then renew.",
            "For pinned clients, ship an updated bundle and communicate the rotation window.",
        ],
        "verification": [
            "`openssl s_client` shows notAfter at least 60 days out.",
            "Clients and synthetic HTTPS monitors go green end to end.",
            "`certbot renew --dry-run` succeeds so the next renewal will work unattended.",
        ],
        "prevention": [
            "Alert at 30 days and page at 14 days before expiry on every public endpoint.",
            "Use short-lived certs with automated renewal (ACME) and a reload hook; "
            "test the hook on staging.",
            "Track renewal in the deploy pipeline: a staging dry-run on every infra change.",
        ],
    },
    "latency-spike": {
        "title": "Latency Spike (p95 / p99)",
        "symptoms": [
            "p95 or p99 latency jumps while p50 stays flat (tail latency problem).",
            "Timeouts and retries increase; downstream queues grow.",
            "Users report slowness on specific pages or API endpoints, not everything.",
        ],
        "diagnosis": [
            "Scope it: which endpoints, regions, and time window? Check the latency "
            "dashboard split by endpoint and status code.",
            "Check saturation: CPU, memory, connection pools, thread pools, file descriptors "
            "on the hot services.",
            "Check dependencies: DB slow-query log, cache hit rate, and latency of each "
            "downstream call in traces.",
            "Look for GC pauses, noisy neighbors (shared hosts / throttled CPU), or a "
            "deploy that coincides with the spike.",
            "Sample a slow trace end to end: where do the milliseconds actually go?",
        ],
        "root_causes": [
            "Slow database queries: missing index, lock contention, or a plan flip after stats change.",
            "Cache stampede or eviction dropping hit rate to near zero.",
            "Thread / connection pool exhaustion serializing requests.",
            "GC pauses or CPU throttling on burstable instances.",
            "A bad deploy: heavier serialization, N+1 queries, or a new blocking call.",
        ],
        "fix": [
            "Add the missing index or kill the blocking query; enable statement timeouts.",
            "Warm the cache gradually (request coalescing, jittered TTLs) instead of all at once.",
            "Raise pool sizes to match measured concurrency, or shed load with rate limits.",
            "Roll back the suspect deploy if the spike correlates with a release.",
        ],
        "verification": [
            "p95 and p99 return to baseline for a full traffic cycle (including peak).",
            "Dependency latencies and cache hit rates recover on the dashboards.",
            "Error and timeout rates drop to pre-incident levels.",
        ],
        "prevention": [
            "SLOs on p95/p99 per critical endpoint with alerts on burn rate.",
            "Load tests in CI that fail the build on tail-latency regression.",
            "DB migration review: every query over the hot path gets EXPLAIN before merge.",
            "Capacity headroom policy: scale out before pools sit above 70% sustained.",
        ],
    },
    "bad-deploy": {
        "title": "Bad Deploy / Release Regression",
        "symptoms": [
            "Error rate, crash rate, or latency jumps within minutes of a release.",
            "New exceptions appear in logs that did not exist in the previous version.",
            "Feature works in staging but fails in production (config / data difference).",
        ],
        "diagnosis": [
            "Establish the timeline: exactly when did the deploy finish, and when did metrics move?",
            "Diff the release: code changes, config changes, migrations, and infra changes.",
            "Check canary / staged traffic: did the canary show the signal before full rollout?",
            "Read the new errors: first occurrence, stack trace, and which code path they come from.",
            "Check external differences: feature flags, env vars, secrets, and production data shape.",
        ],
        "root_causes": [
            "Backward-incompatible change: API contract, schema, or serialization format.",
            "Database migration that locks tables or breaks the old code still running.",
            "Config or secret missing / wrong in production but present in staging.",
            "Untested path: the change was covered by unit tests but not by an integration path.",
            "Dependency version bump with breaking behavior.",
        ],
        "fix": [
            "Roll back first, investigate second: revert to the last known-good version "
            "via the standard rollback (previous image, blue-green flip, or feature flag off).",
            "If rollback is unsafe (migrations ran), roll forward with a hotfix instead.",
            "Disable the offending feature flag while keeping the rest of the release.",
        ],
        "verification": [
            "Error rate and latency return to baseline on the rolled-back version.",
            "Smoke tests and synthetic transactions pass in production.",
            "The root-cause fix is verified on staging with production-like data before re-release.",
        ],
        "prevention": [
            "Canary or progressive rollout with automatic rollback on SLO breach.",
            "Backward-compatible migrations: expand then contract, never both at once.",
            "Feature flags for every user-facing change; flags default to off.",
            "Deploy freeze checklist: migrations reviewed, rollback tested, on-call aware.",
        ],
    },
    "dns-failure": {
        "title": "DNS Resolution Failure",
        "symptoms": [
            "'Could not resolve host' / NXDOMAIN errors from apps, curl, or builds.",
            "Some hosts resolve and others do not; failures are intermittent.",
            "Internal service names fail while public names work (or vice versa).",
        ],
        "diagnosis": [
            "Reproduce directly: `dig +short example.com`, `nslookup example.com`, and "
            "`getent hosts example.com` to separate resolver vs app issues.",
            "Check which resolver is used: /etc/resolv.conf, systemd-resolve --status, "
            "or kube-dns / CoreDNS pods in Kubernetes.",
            "Query the authoritative servers directly: `dig @8.8.8.8` vs `dig @<corp-dns>` "
            "to see if it is local or upstream.",
            "Check CoreDNS / resolver logs for SERVFAIL, timeouts, or loop warnings.",
            "Check domain health: expiry, nameserver delegation (`dig +trace`), and DNSSEC validity.",
        ],
        "root_causes": [
            "Upstream resolver outage or network path to it broken.",
            "CoreDNS / kube-dns pods crashlooping or resource-starved.",
            "Stale or wrong search domains / ndots causing internal names to leak externally.",
            "Expired domain or changed nameservers not yet propagated.",
            "DNSSEC validation failure after a key rollover.",
        ],
        "fix": [
            "Short term: point resolvers at a healthy upstream (or add a secondary) to restore service.",
            "Restart / scale the CoreDNS deployment and raise its CPU/memory if throttled.",
            "Fix the delegation or renew the domain at the registrar if it expired.",
            "Flush bad cache entries: `systemd-resolve --flush-caches` or restart nscd.",
        ],
        "verification": [
            "`dig` returns correct answers consistently over several minutes.",
            "Applications reconnect without restart (or after a rolling restart if they cache DNS).",
            "DNS query success rate and latency recover on the resolver dashboard.",
        ],
        "prevention": [
            "Monitor DNS resolution success rate and latency as a first-class SLO.",
            "Alert on domain expiry 60 days out; auto-renew where the registrar allows.",
            "Run at least two independent resolvers; never a single point of failure.",
            "Set explicit ndots and search-domain policy in Kubernetes to avoid lookup storms.",
        ],
    },
}

SECTION_ORDER = ["symptoms", "diagnosis", "root_causes", "fix", "verification", "prevention"]
SECTION_TITLES = {
    "symptoms": "Symptoms",
    "diagnosis": "Diagnosis (in order)",
    "root_causes": "Common root causes",
    "fix": "Fix",
    "verification": "Verification",
    "prevention": "Prevention",
}


def list_incidents() -> list[str]:
    """Incident keys with playbooks, sorted."""
    return sorted(PLAYBOOKS)


def render_playbook(incident: str) -> str:
    """Render the playbook for `incident` as markdown. Raises KeyError if unknown."""
    key = incident.strip().lower().replace(" ", "-").replace("_", "-")
    pb = PLAYBOOKS[key]
    lines = [f"# Playbook: {pb['title']}", ""]
    for section in SECTION_ORDER:
        lines.append(f"## {SECTION_TITLES[section]}")
        lines.append("")
        for item in pb[section]:  # type: ignore[index]
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_playbook(incident: str, dest: str | Path) -> Path:
    """Write the rendered playbook markdown to `dest`. Returns the path."""
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_playbook(incident), encoding="utf-8")
    return path


def cmd_playbook(args: argparse.Namespace) -> int:
    """CLI handler for `sre playbook`."""
    try:
        text = render_playbook(args.incident)
    except KeyError:
        print(f"Unknown incident '{args.incident}'. Known incidents: "
              f"{', '.join(list_incidents())}")
        return 2
    if args.export:
        path = export_playbook(args.incident, args.export)
        print(f"Playbook saved to {path}")
    else:
        print(text, end="")
    return 0


# ---------------------------------------------------------------------------
# 2. Blameless postmortems
# ---------------------------------------------------------------------------

POSTMORTEM_DIRNAME = "sre_postmortems"

# Fields prompted interactively, in order. (key, prompt)
POSTMORTEM_FIELDS: list[tuple[str, str]] = [
    ("summary", "One-line summary of the incident"),
    ("impact", "Impact (users affected, duration, severity)"),
    ("timeline", "Timeline (one event per line; blank line to finish)"),
    ("root_cause", "Root cause (system/process focused, not people)"),
    ("went_well", "What went well"),
    ("went_poorly", "What went poorly"),
]

# Patterns that suggest individual blame rather than a blameless narrative.
_BLAME_PATTERNS = [
    (re.compile(r"\bblam\w*\b", re.I), "uses the word 'blame'"),
    (re.compile(r"\b(fault|screwed|incompetent|negligent|careless|lazy)\b", re.I),
     "assigns fault to a person"),
    (re.compile(r"\b(his|her|their) (mistake|error|fault)\b", re.I),
     "attributes the failure to someone's mistake"),
    (re.compile(r"\b\w+'s fault\b", re.I), "says it was someone's fault"),
]


def check_blameless(data: dict[str, object]) -> list[str]:
    """Scan postmortem text for blame language. Returns warning strings (empty = clean)."""
    warnings: list[str] = []
    for field, _prompt in POSTMORTEM_FIELDS:
        text = str(data.get(field, "") or "")
        for rx, why in _BLAME_PATTERNS:
            if rx.search(text):
                warnings.append(f"Section '{field}' {why}; rewrite around systems and process.")
                break
    for i, item in enumerate(data.get("action_items", []) or []):
        text = str((item or {}).get("task", ""))  # type: ignore[union-attr]
        for rx, why in _BLAME_PATTERNS:
            if rx.search(text):
                warnings.append(f"Action item {i + 1} {why}; focus on the fix, not the person.")
                break
    return warnings


def _norm_section_name(name: str) -> str | None:
    name = name.strip().lower().replace(" ", "_")
    mapping = {
        "summary": "summary",
        "impact": "impact",
        "timeline": "timeline",
        "root_cause": "root_cause",
        "root-cause": "root_cause",
        "what_went_well": "went_well",
        "went_well": "went_well",
        "what_went_poorly": "went_poorly",
        "went_poorly": "went_poorly",
        "action_items": "action_items",
        "action-items": "action_items",
        "actions": "action_items",
    }
    return mapping.get(name)


def parse_notes(text: str) -> dict[str, object]:
    """Parse a notes file into postmortem fields.

    Supports `## Section` headers and `Key: value` lines. The timeline and
    action items sections collect one entry per non-empty line; action items
    may be written as `owner: task` or `- owner: task`.
    Never raises on messy input; unknown sections are ignored.
    """
    data: dict[str, object] = {
        "summary": "", "impact": "", "timeline": "",
        "root_cause": "", "went_well": "", "went_poorly": "",
        "action_items": [],
    }
    current: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if current is None:
            return
        joined = "\n".join(buf).strip()
        if current == "action_items":
            items: list[dict[str, str]] = []
            for line in buf:
                line = line.strip().lstrip("-*").strip()
                if not line:
                    continue
                if ":" in line:
                    owner, task = line.split(":", 1)
                    items.append({"owner": owner.strip(), "task": task.strip()})
                else:
                    items.append({"owner": "", "task": line})
            data["action_items"] = items
        else:
            data[current] = joined

    for raw in (text or "").splitlines():
        line = raw.rstrip()
        m = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        key: str | None = None
        rest = ""
        if m:
            key = _norm_section_name(m.group(1))
        else:
            m2 = re.match(r"^([A-Za-z][A-Za-z _-]{1,30}):\s*(.*)$", line)
            if m2 and _norm_section_name(m2.group(1)):
                key = _norm_section_name(m2.group(1))
                rest = m2.group(2)
        if key:
            flush()
            current = key
            buf = [rest] if rest else []
        elif current:
            buf.append(line)
    flush()
    return data


def render_postmortem(data: dict[str, object]) -> str:
    """Render postmortem data as markdown."""
    title = str(data.get("summary") or "Untitled incident").splitlines()[0][:80]
    lines = [f"# Postmortem: {title}", "",
             f"_Date: {data.get('date', date.today().isoformat())}_", ""]
    labels = {
        "impact": "Impact",
        "timeline": "Timeline",
        "root_cause": "Root cause",
        "went_well": "What went well",
        "went_poorly": "What went poorly",
    }
    for field, label in labels.items():
        lines.append(f"## {label}")
        lines.append("")
        body = str(data.get(field, "") or "").strip()
        if field == "timeline" and body:
            for tl in body.splitlines():
                tl = tl.strip()
                if tl:
                    lines.append(f"- {tl.lstrip('-* ').strip()}")
        else:
            lines.append(body if body else "_Not recorded._")
        lines.append("")
    lines.append("## Action items")
    lines.append("")
    items = data.get("action_items") or []
    if items:
        for item in items:  # type: ignore[union-attr]
            owner = item.get("owner", "").strip()  # type: ignore[union-attr]
            task = item.get("task", "").strip()  # type: ignore[union-attr]
            who = f"**{owner}**" if owner else "**Unassigned**"
            lines.append(f"- [ ] {task} ({who})")
    else:
        lines.append("_None recorded._")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save_postmortem(data: dict[str, object], data_dir: Path | None = None) -> Path:
    """Save the rendered postmortem under candid_data/sre_postmortems/. Returns the path."""
    base = data_dir or C.DATA_DIR
    outdir = base / POSTMORTEM_DIRNAME
    outdir.mkdir(parents=True, exist_ok=True)
    slug_src = str(data.get("summary") or "incident").splitlines()[0][:40].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug_src).strip("-") or "incident"
    path = outdir / f"{date.today().isoformat()}-{slug}.md"
    data = dict(data)
    data.setdefault("date", date.today().isoformat())
    path.write_text(render_postmortem(data), encoding="utf-8")
    return path


def prompt_postmortem() -> dict[str, object]:
    """Interactively prompt for postmortem fields. Returns the data dict."""
    data: dict[str, object] = {}
    for field, prompt in POSTMORTEM_FIELDS:
        if field == "timeline":
            print(f"{prompt}:")
            lines: list[str] = []
            while True:
                line = input("  > ").rstrip()
                if not line:
                    break
                lines.append(line)
            data[field] = "\n".join(lines)
        else:
            data[field] = input(f"{prompt}: ").strip()
    print("Action items (blank task to finish):")
    items: list[dict[str, str]] = []
    while True:
        task = input("  task: ").strip()
        if not task:
            break
        owner = input("  owner: ").strip()
        items.append({"owner": owner, "task": task})
    data["action_items"] = items
    return data


def cmd_postmortem(args: argparse.Namespace) -> int:
    """CLI handler for `sre postmortem`."""
    if args.from_notes:
        notes_path = Path(args.from_notes)
        if not notes_path.exists():
            print(f"Notes file not found: {notes_path}")
            return 2
        data = parse_notes(notes_path.read_text(encoding="utf-8"))
    else:
        data = prompt_postmortem()
    warnings = check_blameless(data)
    if warnings:
        print("Blameless-language check flagged:")
        for w in warnings:
            print(f"  - {w}")
        print("Consider rewording around systems and process before sharing.\n")
    path = save_postmortem(data)
    print(render_postmortem(data), end="")
    print(f"\nSaved to {path}")
    return 0


# ---------------------------------------------------------------------------
# 3. IaC review drill
# ---------------------------------------------------------------------------

SNIPPETS: list[dict[str, object]] = [
    {
        "id": "sg-open-world",
        "title": "Security group wide open",
        "kind": "terraform",
        "difficulty": "easy",
        "code": (
            'resource "aws_security_group" "web" {\n'
            '  name = "web-sg"\n\n'
            '  ingress {\n'
            '    from_port   = 22\n'
            '    to_port     = 22\n'
            '    protocol    = "tcp"\n'
            '    cidr_blocks = ["0.0.0.0/0"]\n'
            '  }\n\n'
            '  ingress {\n'
            '    from_port   = 3306\n'
            '    to_port     = 3306\n'
            '    protocol    = "tcp"\n'
            '    cidr_blocks = ["0.0.0.0/0"]\n'
            '  }\n'
            '}\n'
        ),
        "issues": [
            {"title": "SSH open to the world",
             "detail": "Port 22 allows 0.0.0.0/0, so anyone on the internet can attempt SSH logins. Restrict to a bastion host or VPN CIDR.",
             "keywords": ["ssh", "22", "bastion", "vpn", "open"]},
            {"title": "Database port open to the world",
             "detail": "MySQL port 3306 allows 0.0.0.0/0. The database should only accept traffic from the app security group, never the public internet.",
             "keywords": ["3306", "mysql", "database", "db"]},
        ],
    },
    {
        "id": "deploy-no-limits",
        "title": "Deployment with no guardrails",
        "kind": "kubernetes",
        "difficulty": "easy",
        "code": (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: api\n"
            "spec:\n"
            "  replicas: 3\n"
            "  template:\n"
            "    spec:\n"
            "      containers:\n"
            "      - name: api\n"
            "        image: myapp:latest\n"
        ),
        "issues": [
            {"title": "Mutable `latest` image tag",
             "detail": "Using :latest means you cannot tell which code is running and rollbacks are unreliable. Pin an immutable tag or digest.",
             "keywords": ["latest", "tag", "pin", "digest", "immutable"]},
            {"title": "No resource requests or limits",
             "detail": "Without requests the scheduler cannot place pods well, and without limits one pod can starve the node or get OOMKilled unpredictably.",
             "keywords": ["resource", "limit", "request", "cpu", "memory"]},
            {"title": "No liveness or readiness probes",
             "detail": "Kubernetes cannot detect a hung container or hold traffic until the app is ready, so bad pods keep serving (or failing) traffic.",
             "keywords": ["probe", "liveness", "readiness", "health"]},
        ],
    },
    {
        "id": "ebs-unencrypted",
        "title": "Unencrypted EBS volume",
        "kind": "terraform",
        "difficulty": "easy",
        "code": (
            'resource "aws_ebs_volume" "data" {\n'
            '  availability_zone = "us-east-1a"\n'
            '  size              = 100\n'
            '  type              = "gp3"\n'
            '}\n'
        ),
        "issues": [
            {"title": "Volume is not encrypted",
             "detail": "No encrypted = true, so data is stored in plaintext. Anyone with snapshot access can read it. Enable encryption, ideally with a customer-managed KMS key.",
             "keywords": ["encrypt", "kms", "plaintext"]},
            {"title": "No backup or snapshot policy",
             "detail": "There is no snapshot lifecycle or backup plan, so losing the volume means losing the data. Add automated snapshots with retention.",
             "keywords": ["backup", "snapshot", "retention", "lifecycle"]},
        ],
    },
    {
        "id": "pod-privileged",
        "title": "Privileged pod on the host network",
        "kind": "kubernetes",
        "difficulty": "medium",
        "code": (
            "apiVersion: v1\n"
            "kind: Pod\n"
            "metadata:\n"
            "  name: debug-agent\n"
            "spec:\n"
            "  hostNetwork: true\n"
            "  containers:\n"
            "  - name: agent\n"
            "    image: debugtools:1.4.0\n"
            "    securityContext:\n"
            "      privileged: true\n"
        ),
        "issues": [
            {"title": "Privileged container",
             "detail": "privileged: true gives the container nearly full host access. A compromise becomes a node compromise. Drop privileges and add only needed capabilities.",
             "keywords": ["privileged", "capabilit", "root"]},
            {"title": "Host network enabled",
             "detail": "hostNetwork: true lets the pod see and bind host ports and traffic. It should use the pod network with explicit ports instead.",
             "keywords": ["hostnetwork", "host network", "network"]},
            {"title": "No resource limits",
             "detail": "A debug tool with no limits can consume the node's CPU and memory. Set requests and limits even for utilities.",
             "keywords": ["resource", "limit", "request"]},
        ],
    },
    {
        "id": "s3-public",
        "title": "Public S3 bucket",
        "kind": "terraform",
        "difficulty": "medium",
        "code": (
            'resource "aws_s3_bucket" "assets" {\n'
            '  bucket = "company-assets"\n'
            '}\n\n'
            'resource "aws_s3_bucket_acl" "assets" {\n'
            '  bucket = aws_s3_bucket.assets.id\n'
            '  acl    = "public-read"\n'
            '}\n'
        ),
        "issues": [
            {"title": "Bucket is publicly readable",
             "detail": "acl = public-read exposes every object to the internet. Serve through CloudFront with origin access control, or keep the bucket private.",
             "keywords": ["public", "acl", "cloudfront", "private"]},
            {"title": "No server-side encryption",
             "detail": "There is no encryption configuration, so objects rest unencrypted. Enable SSE-S3 or SSE-KMS by default.",
             "keywords": ["encrypt", "sse", "kms"]},
            {"title": "No versioning",
             "detail": "Without versioning an overwrite or delete is permanent. Enable versioning for recovery.",
             "keywords": ["version"]},
        ],
    },
    {
        "id": "secret-in-configmap",
        "title": "Secrets hiding in a ConfigMap",
        "kind": "kubernetes",
        "difficulty": "medium",
        "code": (
            "apiVersion: v1\n"
            "kind: ConfigMap\n"
            "metadata:\n"
            "  name: app-config\n"
            "data:\n"
            '  DB_PASSWORD: "s3cret-pw-123"\n'
            '  API_KEY: "ak-live-9f8e7d6c"\n'
        ),
        "issues": [
            {"title": "Credentials stored in a ConfigMap",
             "detail": "ConfigMaps are not encrypted at rest by default and are readable by many roles. Secrets belong in a Secret object or an external secrets manager.",
             "keywords": ["secret", "configmap", "credential", "password"]},
            {"title": "Hardcoded credentials in YAML",
             "detail": "Plaintext credentials in a manifest end up in git history and CI logs. Inject them from a vault or secrets manager at deploy time.",
             "keywords": ["hardcod", "plaintext", "git", "vault"]},
        ],
    },
    {
        "id": "rds-public",
        "title": "Publicly accessible database",
        "kind": "terraform",
        "difficulty": "medium",
        "code": (
            'resource "aws_db_instance" "main" {\n'
            '  engine                 = "postgres"\n'
            '  instance_class         = "db.t3.micro"\n'
            '  allocated_storage      = 50\n'
            '  publicly_accessible    = true\n'
            '  skip_final_snapshot    = true\n'
            '  multi_az               = false\n'
            '  storage_encrypted      = false\n'
            '}\n'
        ),
        "issues": [
            {"title": "Database is publicly accessible",
             "detail": "publicly_accessible = true puts the database on the public internet. It should live in private subnets reachable only from the app tier.",
             "keywords": ["public", "private subnet", "internet"]},
            {"title": "Final snapshot skipped",
             "detail": "skip_final_snapshot = true means deleting the instance destroys all data with no backup. Always keep the final snapshot.",
             "keywords": ["snapshot", "skip_final_snapshot", "backup"]},
            {"title": "No encryption at rest",
             "detail": "storage_encrypted = false leaves data unencrypted on disk. Enable encryption with a KMS key.",
             "keywords": ["encrypt", "kms"]},
            {"title": "Single AZ deployment",
             "detail": "multi_az = false means an AZ failure takes the database down. Use Multi-AZ for production workloads.",
             "keywords": ["multi_az", "multi-az", "az", "ha", "availability"]},
        ],
    },
    {
        "id": "ingress-no-tls",
        "title": "Ingress without TLS",
        "kind": "kubernetes",
        "difficulty": "easy",
        "code": (
            "apiVersion: networking.k8s.io/v1\n"
            "kind: Ingress\n"
            "metadata:\n"
            "  name: web\n"
            "spec:\n"
            "  rules:\n"
            "  - host: app.example.com\n"
            "    http:\n"
            "      paths:\n"
            "      - path: /\n"
            "        pathType: Prefix\n"
            "        backend:\n"
            "          service:\n"
            "            name: web\n"
            "            port:\n"
            "              number: 80\n"
        ),
        "issues": [
            {"title": "No TLS termination",
             "detail": "There is no tls: section, so traffic is plain HTTP. Add a TLS block with a certificate (e.g. via cert-manager) and redirect HTTP to HTTPS.",
             "keywords": ["tls", "https", "ssl", "cert"]},
            {"title": "No ingress class specified",
             "detail": "Without ingressClassName the cluster may pick an unexpected controller or ignore the resource. Set it explicitly.",
             "keywords": ["ingressclass", "class", "controller"]},
        ],
    },
    {
        "id": "provider-hardcoded-keys",
        "title": "Hardcoded cloud credentials",
        "kind": "terraform",
        "difficulty": "easy",
        "code": (
            'provider "aws" {\n'
            '  region     = "us-east-1"\n'
            '  access_key = "AKIAIOSFODNN7EXAMPLE"\n'
            '  secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"\n'
            '}\n'
        ),
        "issues": [
            {"title": "Credentials hardcoded in config",
             "detail": "Access keys in the provider block get committed to version control and shared with everyone who can read the repo. Use environment variables, SSO, or instance roles instead.",
             "keywords": ["hardcod", "credential", "key", "secret", "env", "sso", "iam"]},
            {"title": "Long-lived static keys",
             "detail": "Static keys never expire unless rotated. Prefer short-lived credentials from SSO or instance profiles so a leak has a short blast radius.",
             "keywords": ["rotat", "static", "short-lived", "instance profile"]},
        ],
    },
    {
        "id": "deployment-no-securitycontext",
        "title": "Container running as root",
        "kind": "kubernetes",
        "difficulty": "medium",
        "code": (
            "apiVersion: apps/v1\n"
            "kind: Deployment\n"
            "metadata:\n"
            "  name: worker\n"
            "spec:\n"
            "  template:\n"
            "    spec:\n"
            "      containers:\n"
            "      - name: worker\n"
            "        image: worker:2.3.1\n"
            "        resources:\n"
            "          requests:\n"
            "            cpu: 100m\n"
            "            memory: 128Mi\n"
        ),
        "issues": [
            {"title": "Container runs as root",
             "detail": "No securityContext means the container runs as root by default. Set runAsNonRoot: true and a runAsUser so a breakout is contained.",
             "keywords": ["root", "runasnonroot", "runasuser", "securitycontext", "non-root"]},
            {"title": "No memory limit (request only)",
             "detail": "Only a request is set, so the container can grow without bound until the node OOMs. Always pair requests with limits.",
             "keywords": ["limit", "oom", "memory"]},
            {"title": "No health probes",
             "detail": "Without readiness/liveness probes Kubernetes cannot tell a stuck worker from a healthy one.",
             "keywords": ["probe", "liveness", "readiness", "health"]},
        ],
    },
]


def list_snippets(difficulty: str | None = None) -> list[dict[str, object]]:
    """Snippets, optionally filtered by difficulty ('easy' or 'medium')."""
    if difficulty:
        return [s for s in SNIPPETS if s["difficulty"] == difficulty]
    return list(SNIPPETS)


def get_snippet(index: int = 0, difficulty: str | None = None) -> dict[str, object]:
    """Pick a snippet deterministically: index-th of the (optionally filtered) list."""
    pool = list_snippets(difficulty)
    if not pool:
        raise ValueError(f"No snippets for difficulty {difficulty!r}")
    return pool[index % len(pool)]


def render_challenge(snippet: dict[str, object]) -> str:
    """Render the drill prompt: snippet shown, answers hidden."""
    n = len(snippet["issues"])  # type: ignore[arg-type]
    return (
        f"# IaC Review Drill ({snippet['difficulty']})\n\n"
        f"**{snippet['title']}** [{snippet['kind']}]\n\n"
        f"This snippet contains {n} misconfiguration{'s' if n != 1 else ''}. "
        "List the issues you spot, one per line. Enter a blank line when done.\n\n"
        f"```{snippet['kind']}\n{snippet['code']}```\n"
    )


def render_answers(snippet: dict[str, object]) -> str:
    """Render the answer key with explanations."""
    lines = [f"## Answers: {snippet['title']}", ""]
    for i, issue in enumerate(snippet["issues"], 1):  # type: ignore[union-attr]
        lines.append(f"{i}. **{issue['title']}**")  # type: ignore[index]
        lines.append(f"   {issue['detail']}")  # type: ignore[index]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def match_issues(snippet: dict[str, object], user_text: str) -> list[bool]:
    """Score free-text answers: True per issue if any of its keywords appear."""
    hay = (user_text or "").lower()
    matched: list[bool] = []
    for issue in snippet["issues"]:  # type: ignore[union-attr]
        kws = issue.get("keywords", [])  # type: ignore[union-attr]
        matched.append(any(kw.lower() in hay for kw in kws))  # type: ignore[union-attr]
    return matched


def render_score(snippet: dict[str, object], matched: list[bool]) -> str:
    """Render the score line after a drill attempt."""
    got = sum(matched)
    total = len(matched)
    lines = [f"**Score: {got}/{total}**", ""]
    for issue, hit in zip(snippet["issues"], matched):  # type: ignore[union-attr]
        mark = "found" if hit else "missed"
        lines.append(f"- [{mark}] {issue['title']}")  # type: ignore[index]
    return "\n".join(lines) + "\n"


def run_drill(snippet: dict[str, object], answers: list[str] | None = None) -> int:
    """Run one drill. If `answers` is None, read from stdin interactively."""
    print(render_challenge(snippet), end="")
    if answers is None:
        print("Your findings (blank line to finish):")
        given: list[str] = []
        while True:
            try:
                line = input("> ").rstrip()
            except EOFError:
                break
            if not line:
                break
            given.append(line)
    else:
        given = answers
    matched = match_issues(snippet, "\n".join(given))
    print()
    print(render_score(snippet, matched), end="")
    print()
    print(render_answers(snippet), end="")
    return 0


def cmd_iac_review(args: argparse.Namespace) -> int:
    """CLI handler for `sre iac-review`."""
    difficulty = args.difficulty
    if difficulty not in (None, "easy", "medium"):
        print(f"Unknown difficulty '{difficulty}'. Use easy or medium.")
        return 2
    try:
        snippet = get_snippet(args.index or 0, difficulty)
    except ValueError as e:
        print(str(e))
        return 2
    if args.answers:
        print(render_challenge(snippet), end="")
        print(render_answers(snippet), end="")
        return 0
    return run_drill(snippet)


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Add the three `sre` subcommands to the given subparsers object."""
    try:
        subparsers.dest = "sre_cmd"
    except AttributeError:
        pass

    p = subparsers.add_parser(
        "playbook", help="Show a troubleshooting playbook for a common incident.")
    p.add_argument("incident", choices=list_incidents(),
                   help="Incident type, e.g. disk-full, oomkilled.")
    p.add_argument("--export", metavar="FILE.md",
                   help="Save the playbook markdown to a file.")
    p.set_defaults(func=dispatch)

    p = subparsers.add_parser(
        "postmortem", help="Write a blameless postmortem (interactive or from notes).")
    p.add_argument("--from-notes", metavar="NOTES.txt",
                   help="Parse a notes file instead of prompting interactively.")
    p.set_defaults(func=dispatch)

    p = subparsers.add_parser(
        "iac-review", help="IaC misconfiguration review drill.")
    p.add_argument("--difficulty", choices=["easy", "medium"], default=None,
                   help="Filter snippets by difficulty.")
    p.add_argument("--index", type=int, default=0,
                   help="Pick the Nth snippet (0-based) for a deterministic drill.")
    p.add_argument("--answers", action="store_true",
                   help="Non-interactive mode: print the snippet and its answer key.")
    p.set_defaults(func=dispatch)


def dispatch(args: argparse.Namespace) -> int:
    """Route to the right subcommand based on args.sre_cmd. Returns exit code."""
    cmd = getattr(args, "sre_cmd", None)
    if cmd == "playbook":
        return cmd_playbook(args)
    if cmd == "postmortem":
        return cmd_postmortem(args)
    if cmd == "iac-review":
        return cmd_iac_review(args)
    print("Unknown sre subcommand. Use: playbook, postmortem, iac-review.")
    return 2
