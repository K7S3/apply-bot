"""SRE/DevOps interview guides for candid: on-call STAR story builder,
observability and tooling cheatsheets/quizzes, and an SRE career ladder guide.

Top-level command: ``sre``. Subcommands: ``stories``, ``cheatsheet``,
``quiz``, ``ladder``. The coordinator wires this module via ``register()``;
all heavy logic lives in pure functions below, the CLI layer stays thin.

This module is offline and dependency-free: no network, no paid APIs, no
keys. Saved stories live under the candid data dir (``candid_data/sre_stories/``,
git-ignored, overridable with CANDID_DATA_DIR). There is currently no
central story-bank API in candid (no candid/stories.py), so stories are saved
as standalone JSON files using the STAR schema defined here; when a story-bank
API lands, point ``save_story()`` at it.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Shared data-dir helpers
# ---------------------------------------------------------------------------

_DATA_DIR_ENV = "CANDID_DATA_DIR"


def data_dir() -> Path:
    override = os.environ.get(_DATA_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent.parent / "candid_data"


def stories_dir() -> Path:
    return data_dir() / "sre_stories"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "story"


# ---------------------------------------------------------------------------
# Feature 1: on-call STAR story builder
# ---------------------------------------------------------------------------

STORY_COMPETENCIES = [
    "incident-command",
    "debugging",
    "communication",
    "prevention",
    "on-call-excellence",
    "automation",
    "reliability-engineering",
]

STORY_PROMPTS = {
    "incident-command": [
        "Describe a time you led or coordinated an incident response (sev1/sev2).",
        "Who did you page in, how did you keep the war room focused, and what decided 'resolved'?",
    ],
    "debugging": [
        "Describe the hardest production bug you debugged under time pressure.",
        "What was the misleading signal, and what finally cracked it?",
    ],
    "communication": [
        "Describe a time you had to communicate a production outage to stakeholders or customers.",
        "How did you balance speed of updates with accuracy?",
    ],
    "prevention": [
        "Describe something you built or changed so an incident class could never happen again.",
        "What was the postmortem action item, and what did you do about it?",
    ],
    "on-call-excellence": [
        "Describe your on-call rotation: load, alert quality, and what you improved.",
        "How did you measure and reduce toil or page noise?",
    ],
    "automation": [
        "Describe a runbook or automation you wrote to make on-call safer or faster.",
        "What did the responder have to do before, and what happens now?",
    ],
    "reliability-engineering": [
        "Describe a reliability initiative you drove: SLOs, error budgets, capacity, or chaos work.",
        "What moved on the dashboard, and what did the team learn?",
    ],
}

STORY_SCHEMA_FIELDS = ["title", "competencies", "tags", "situation", "task",
                       "action", "result", "metrics", "created_at"]


def build_story_record(title: str, competencies: list[str], situation: str,
                       task: str, action: str, result: str,
                       metrics: str = "", tags: list[str] | None = None) -> dict:
    """Build a STAR story record dict following this module's schema."""
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    return {
        "title": title.strip(),
        "competencies": [c for c in competencies if c in STORY_COMPETENCIES],
        "tags": tags or [],
        "situation": situation.strip(),
        "task": task.strip(),
        "action": action.strip(),
        "result": result.strip(),
        "metrics": metrics.strip(),
        "created_at": now,
    }


def validate_story(record: dict) -> list[str]:
    """Return a list of problems with a story record; empty means valid."""
    problems = []
    for field in ("title", "situation", "task", "action", "result"):
        if not record.get(field):
            problems.append(f"missing or empty: {field}")
    for field in ("situation", "task", "action", "result"):
        text = record.get(field, "")
        if text and len(text.split()) < 10:
            problems.append(f"{field} looks too thin (under 10 words); add detail")
    unknown = [c for c in record.get("competencies", []) if c not in STORY_COMPETENCIES]
    if unknown:
        problems.append(f"unknown competencies: {', '.join(unknown)}")
    return problems


def save_story(record: dict, dest_dir: Path | None = None) -> Path:
    """Persist a story record as JSON. Returns the file path."""
    target = dest_dir or stories_dir()
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{_slugify(record['title'])}.json"
    counter = 1
    while path.exists():
        counter += 1
        path = target / f"{_slugify(record['title'])}-{counter}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def list_stories(dest_dir: Path | None = None) -> list[dict]:
    target = dest_dir or stories_dir()
    if not target.exists():
        return []
    out = []
    for path in sorted(target.glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def render_story(record: dict) -> str:
    lines = [f"# {record['title']}", ""]
    if record.get("competencies"):
        lines.append("Competencies: " + ", ".join(record["competencies"]))
    if record.get("tags"):
        lines.append("Tags: " + ", ".join(record["tags"]))
    lines.append("")
    for field in ("situation", "task", "action", "result"):
        lines.append(f"## {field.capitalize()}")
        lines.append(record.get(field, "(not filled in)"))
        lines.append("")
    if record.get("metrics"):
        lines.append("## Metrics")
        lines.append(record["metrics"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{text}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def stories_interactive(tag: str, out: Any = sys.stdout) -> int:
    """Interactive STAR story builder. Returns exit code."""
    print("On-call STAR story builder", file=out)
    print("Competencies: " + ", ".join(STORY_COMPETENCIES), file=out)
    print("", file=out)
    title = _prompt("Story title (e.g. 'payments outage on Black Friday')")
    if not title:
        print("No title given; aborting.", file=out)
        return 1
    comp_raw = _prompt("Competencies (comma-separated, from the list above)",
                       "incident-command")
    competencies = [c.strip() for c in comp_raw.split(",") if c.strip()]
    competencies = [c for c in competencies if c in STORY_COMPETENCIES] or ["incident-command"]
    for comp in competencies:
        for line in STORY_PROMPTS.get(comp, []):
            print(f"  ({comp}) {line}", file=out)
    print("", file=out)
    situation = _prompt("Situation: what happened, team, stakes (one or two sentences)")
    task = _prompt("Task: what were YOU responsible for")
    action = _prompt("Action: what did you actually do (be specific)")
    result = _prompt("Result: outcome, with numbers if you have them")
    metrics = _prompt("Metrics to remember (e.g. MTTR 12 min, 99.99% SLO)", "")
    record = build_story_record(title, competencies, situation, task, action,
                                result, metrics, tags=[tag])
    problems = validate_story(record)
    if problems:
        print("", file=out)
        print("This story could be stronger:", file=out)
        for p in problems:
            print(f"  - {p}", file=out)
    path = save_story(record)
    print("", file=out)
    print(f"Saved to {path}", file=out)
    return 0


def cmd_stories(args: argparse.Namespace, out: Any = sys.stdout) -> int:
    if getattr(args, "list", False):
        stories = list_stories()
        if not stories:
            print("No SRE stories saved yet. Run `sre stories` to build one.", file=out)
            return 0
        for s in stories:
            comps = ", ".join(s.get("competencies", []))
            print(f"- {s.get('title')} [{comps}]", file=out)
        return 0
    return stories_interactive(getattr(args, "tag", "on-call"), out=out)


# ---------------------------------------------------------------------------
# Feature 2: observability/tooling cheatsheets and quizzes
# ---------------------------------------------------------------------------

TOOLS = ["kubectl", "prometheus", "grafana", "linux", "terraform"]

CHEATSHEETS: dict[str, list[tuple[str, str]]] = {
    "kubectl": [
        ("kubectl get pods -A", "list pods in all namespaces"),
        ("kubectl get pods -n <ns> -o wide", "pods with node and IP in a namespace"),
        ("kubectl describe pod <name> -n <ns>", "events and config for one pod (first stop for CrashLoopBackOff)"),
        ("kubectl logs <pod> -n <ns> --previous", "logs from the previous (crashed) container"),
        ("kubectl logs -f deployment/<name> -n <ns>", "follow logs of all pods in a deployment"),
        ("kubectl exec -it <pod> -n <ns> -- sh", "shell into a running pod"),
        ("kubectl top pods -n <ns> --sort-by=cpu", "live CPU/memory per pod (needs metrics-server)"),
        ("kubectl rollout status deployment/<name> -n <ns>", "watch a rollout progress"),
        ("kubectl rollout undo deployment/<name> -n <ns>", "roll back to the previous ReplicaSet"),
        ("kubectl get events -n <ns> --sort-by=.lastTimestamp", "recent cluster events, newest last"),
        ("kubectl port-forward svc/<name> 8080:80 -n <ns>", "forward a service port to localhost"),
        ("kubectl apply -f manifest.yaml", "apply a manifest (declarative update)"),
        ("kubectl diff -f manifest.yaml", "preview what apply would change"),
        ("kubectl scale deployment/<name> --replicas=5 -n <ns>", "scale a deployment"),
        ("kubectl cordon <node> / kubectl drain <node> --ignore-daemonsets", "mark node unschedulable / evict its pods"),
    ],
    "prometheus": [
        ('up{job="api"} == 0', "targets currently down for a job"),
        ("rate(http_requests_total[5m])", "per-second request rate over 5 minutes"),
        ('sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))',
         "global 5xx error ratio (SLO burn signal)"),
        ("histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))",
         "p99 latency from a histogram"),
        ("avg by (instance) (rate(node_cpu_seconds_total{mode='idle'}[5m]))", "idle CPU fraction per node"),
        ("node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes", "memory available fraction per node"),
        ("predict_linear(disk_free_bytes[1h], 4*3600) < 0", "disk predicted to fill within 4h"),
        ("increase(prometheus_notifications_dropped_total[1h]) > 0", "alert notifications being dropped"),
        ("sum by (pod) (rate(container_cpu_usage_seconds_total[5m]))", "CPU usage per pod"),
        ("ALERT example: expr: job:up == 0, for: 5m", "alert rule skeleton: fire only if down for 5m"),
        ("topk(5, sum by (route) (rate(http_requests_total[5m])))", "top 5 routes by traffic"),
        ("changes(process_start_time_seconds[1h]) > 2", "processes restarting often (crash looping)"),
    ],
    "grafana": [
        ("Explore > Metrics browser", "ad-hoc PromQL without building a dashboard"),
        ("$__rate_interval in queries", "auto rate window that follows the dashboard time range"),
        ("Dashboard variables: label_values(up, job)", "templating dropdown of job names"),
        ("Transform: 'Add field from calculation'", "derive new series without editing queries"),
        ("Alert rules: Grafana-managed vs Mimir/Prometheus", "know which backend evaluates your rule"),
        ("Contact points + notification policies", "route alerts to Slack/PagerDuty by label matchers"),
        ("Silences (Alerting > Silences)", "mute alerts during deploys; always set an expiry"),
        ("Dashboard JSON model (Dashboard settings > JSON)", "version-control dashboards; export before big edits"),
        ("Provisioning: /etc/grafana/provisioning", "dashboards-as-code via YAML + JSON files"),
        ("Explore logs with Loki: {app='api'} |= 'error'", "LogQL filter for error lines in an app stream"),
        ("{app='api'} | json | status >= 500", "parse JSON logs and filter on a field"),
        ("Annotations from Loki/Prometheus", "overlay deploys and incidents on every panel"),
    ],
    "linux": [
        ("journalctl -u <service> --since '30 min ago'", "service logs from systemd"),
        ("journalctl -f -u <service>", "follow service logs live"),
        ("ss -tlnp", "listening TCP ports and owning processes (modern netstat)"),
        ("ps aux --sort=-%cpu | head", "top CPU consumers"),
        ("top -o %MEM / htop", "interactive process viewer"),
        ("df -h / iostat -x 1", "disk space / disk IO pressure"),
        ("free -h / vmstat 1", "memory overview / paging and swap activity"),
        ("dmesg -T | tail -50", "kernel messages (OOM killer lives here)"),
        ("grep -c 'OOM' via dmesg", "check whether the OOM killer fired: dmesg | grep -i oom"),
        ("strace -p <pid> -e trace=network", "syscalls of a live process, network only"),
        ("lsof -i :8080", "what is bound to port 8080"),
        ("curl -sS -o /dev/null -w '%{http_code} %{time_total}s'", "probe an endpoint, print code and latency"),
        ("systemctl status <service> / systemctl restart <service>", "service state and restart"),
        ("ulimit -n / cat /proc/<pid>/limits", "file descriptor limits (the classic 'too many open files')"),
    ],
    "terraform": [
        ("terraform init", "download providers and set up the working dir (run first)"),
        ("terraform fmt -recursive", "canonical formatting before every commit"),
        ("terraform validate", "syntax and consistency check, no state needed"),
        ("terraform plan -out=tfplan", "preview changes and save the plan file"),
        ("terraform apply tfplan", "apply exactly the saved plan"),
        ("terraform plan -detailed-exitcode", "exit 2 when changes exist (CI gate)"),
        ("terraform state list / terraform state show <addr>", "inspect resources tracked in state"),
        ("terraform import <addr> <id>", "bring an existing resource under management"),
        ("terraform taint <addr> (or -replace with apply)", "force recreation of a resource next apply"),
        ("terraform workspace list / new / select", "separate state per environment"),
        ("terraform output <name>", "print an output value"),
        ("terraform destroy -target=<addr>", "destroy one resource (use with care)"),
        ("moved { from / to } blocks", "rename resources without destroy/recreate"),
        ("terraform.lock.hcl committed", "pin provider versions; commit the lock file"),
    ],
}

QUIZ_BANK: dict[str, list[dict[str, Any]]] = {
    "kubectl": [
        {"q": "A pod is CrashLoopBackOff. What is the single most useful first command?",
         "options": ["kubectl delete pod", "kubectl describe pod", "kubectl get nodes", "kubectl top pods"],
         "answer": "kubectl describe pod",
         "why": "describe shows events: image pull errors, failed probes, OOMKilled reasons."},
        {"q": "You need logs from the container that already crashed. Which flag?",
         "options": ["--previous", "--since=1h", "-f", "--tail=0"],
         "answer": "--previous",
         "why": "kubectl logs --previous reads the last terminated container instance."},
        {"q": "How do you roll back a bad deployment?",
         "options": ["kubectl rollout restart", "kubectl rollout undo deployment/<name>",
                     "kubectl delete deployment", "kubectl scale --replicas=0"],
         "answer": "kubectl rollout undo deployment/<name>",
         "why": "undo reverts to the previous ReplicaSet; restart just recreates pods."},
        {"q": "What does 'kubectl drain <node>' do that 'cordon' does not?",
         "options": ["deletes the node", "evicts running pods", "upgrades kubelet", "taints the node forever"],
         "answer": "evicts running pods",
         "why": "cordon only marks unschedulable; drain also evicts pods (respecting PodDisruptionBudgets)."},
        {"q": "Where do you look to see why a pod never got scheduled?",
         "options": ["kubectl logs kubelet", "kubectl get events --sort-by=.lastTimestamp",
                     "kubectl top nodes", "kubectl describe service"],
         "answer": "kubectl get events --sort-by=.lastTimestamp",
         "why": "scheduler decisions and FailedScheduling reasons surface as events."},
    ],
    "prometheus": [
        {"q": "Why is rate(http_requests_total[5m]) correct but delta(http_requests_total[5m]) misleading for QPS?",
         "options": ["delta ignores labels", "rate normalizes by time and handles counter resets",
                     "delta is slower", "rate only works on gauges"],
         "answer": "rate normalizes by time and handles counter resets",
         "why": "Counters reset on restart; rate() extrapolates per-second and tolerates resets."},
        {"q": "How do you compute p99 latency from a Prometheus histogram?",
         "options": ["avg(http_request_duration_seconds)", "max_over_time(...[5m])",
                     "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))",
                     "quantile(0.99, http_request_duration_seconds)"],
         "answer": "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))",
         "why": "Quantiles must be computed from buckets, never averaged from summaries across instances."},
        {"q": "What does 'up == 0' mean?",
         "options": ["no traffic", "a scrape target is down/unreachable", "zero CPU", "alert resolved"],
         "answer": "a scrape target is down/unreachable",
         "why": "up is 1 when Prometheus successfully scraped the target, 0 otherwise."},
        {"q": "In an alert rule, what is 'for: 5m' for?",
         "options": ["evaluation interval", "how long the condition must hold before firing",
                     "retention of the alert", "silence duration"],
         "answer": "how long the condition must hold before firing",
         "why": "for: prevents flapping by requiring the expression to stay true for the duration."},
        {"q": "Which function detects a process restarting repeatedly?",
         "options": ["changes(process_start_time_seconds[1h]) > 2", "rate(up[1h])",
                     "increase(restarts[1h])", "absent(process_start_time_seconds)"],
         "answer": "changes(process_start_time_seconds[1h]) > 2",
         "why": "Each restart bumps process_start_time_seconds; changes() counts how often."},
    ],
    "grafana": [
        {"q": "What does $__rate_interval do in a PromQL query?",
         "options": ["sets the alert interval", "auto-scales the rate window to the dashboard time range",
                     "limits rows returned", "caches the query"],
         "answer": "auto-scales the rate window to the dashboard time range",
         "why": "Hardcoded [5m] breaks on long ranges; $__rate_interval keeps rate() accurate."},
        {"q": "You want a dropdown of all job names on a dashboard. Which variable query?",
         "options": ["label_values(up, job)", "query_result(up)", "jobs()", "metrics(job)"],
         "answer": "label_values(up, job)",
         "why": "label_values(metric, label) is the standard templating query for label values."},
        {"q": "Where should dashboards live so they survive a Grafana reinstall?",
         "options": ["browser localStorage", "provisioned JSON files in version control",
                     "the default sqlite db only", "screenshot exports"],
         "answer": "provisioned JSON files in version control",
         "why": "Provisioning loads dashboards-as-code from disk on startup; the sqlite db is ephemeral."},
        {"q": "How do you temporarily mute alerts during a deploy without deleting rules?",
         "options": ["pause the datasource", "create a Silence with an expiry", "edit each rule's for:",
                     "stop Grafana"],
         "answer": "create a Silence with an expiry",
         "why": "Silences suppress notifications by matcher; always set an expiry so they cannot be forgotten."},
        {"q": "In Loki/LogQL, how do you filter a stream to lines containing 'error' for app 'api'?",
         "options": ["{app='api'} |= 'error'", "{app='api'} == 'error'",
                     "search('error', app='api')", "{app='api'} | error"],
         "answer": "{app='api'} |= 'error'",
         "why": "|= is the LogQL line-filter operator for 'contains'."},
    ],
    "linux": [
        {"q": "A service died overnight. Where do you read its logs on a systemd box?",
         "options": ["/var/log/messages only", "journalctl -u <service>", "dmesg", "/proc/<pid>/logs"],
         "answer": "journalctl -u <service>",
         "why": "journalctl -u queries the systemd journal for that unit, with time filtering."},
        {"q": "The OOM killer may have fired. Where is the evidence?",
         "options": ["journalctl -u app", "dmesg | grep -i oom", "/var/log/auth.log", "kubectl top"],
         "answer": "dmesg | grep -i oom",
         "why": "The kernel logs OOM-killer actions to the kernel ring buffer (dmesg)."},
        {"q": "Which command shows listening TCP ports and their processes?",
         "options": ["ps aux", "ss -tlnp", "df -h", "lsblk"],
         "answer": "ss -tlnp",
         "why": "ss -tlnp lists listening TCP sockets with numeric ports and owning PIDs."},
        {"q": "'Too many open files' errors appear. What do you check first?",
         "options": ["disk space", "ulimit -n and /proc/<pid>/limits", "CPU load", "DNS"],
         "answer": "ulimit -n and /proc/<pid>/limits",
         "why": "The error means the process hit its file-descriptor limit; check and raise the limit."},
        {"q": "How do you see what a stuck process is doing right now without restarting it?",
         "options": ["kill -9 it", "strace -p <pid>", "reboot", "chmod +x the binary"],
         "answer": "strace -p <pid>",
         "why": "strace attaches to a live PID and shows its syscalls in real time."},
    ],
    "terraform": [
        {"q": "What is the correct order for a first-time Terraform run?",
         "options": ["apply, init, plan", "init, plan, apply", "plan, init, apply", "validate, apply, init"],
         "answer": "init, plan, apply",
         "why": "init installs providers, plan previews, apply executes."},
        {"q": "How do you rename a resource without destroying and recreating it?",
         "options": ["edit the name in place", "moved { from / to } blocks", "terraform import",
                     "delete state and re-apply"],
         "answer": "moved { from / to } blocks",
         "why": "moved blocks tell Terraform the resource only changed address, preserving it."},
        {"q": "Why commit terraform.lock.hcl?",
         "options": ["it stores state", "it pins exact provider versions for reproducible runs",
                     "it is required by AWS", "it caches credentials"],
         "answer": "it pins exact provider versions for reproducible runs",
         "why": "The lock file records provider hashes so every run uses identical providers."},
        {"q": "How do you bring an already-existing cloud resource under Terraform management?",
         "options": ["terraform refresh", "terraform import <addr> <id>", "terraform taint", "recreate it"],
         "answer": "terraform import <addr> <id>",
         "why": "import maps an existing real-world resource ID to a state address."},
        {"q": "What does 'terraform plan -detailed-exitcode' give you in CI?",
         "options": ["faster plans", "exit code 2 when changes are pending, so CI can gate on it",
                     "auto-approve", "a JSON plan"],
         "answer": "exit code 2 when changes are pending, so CI can gate on it",
         "why": "Exit 0 = no changes, 1 = error, 2 = changes present; CI uses 2 to require approval."},
    ],
}


def list_tools() -> list[str]:
    return list(TOOLS)


def render_cheatsheet(tool: str) -> str:
    """Render the cheatsheet text for a tool. Raises ValueError for unknown tools."""
    if tool not in CHEATSHEETS:
        raise ValueError(f"unknown tool {tool!r}; choose from: {', '.join(TOOLS)}")
    lines = [f"# {tool} cheatsheet", ""]
    for command, desc in CHEATSHEETS[tool]:
        lines.append(f"$ {command}")
        lines.append(f"  # {desc}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def grade_quiz(tool: str, answers: list[str]) -> dict:
    """Grade a quiz non-interactively. ``answers`` aligns with the question order.

    Returns {score, total, details: [{question, expected, given, correct, why}]}.
    Comparison is case-insensitive and whitespace-tolerant; for multiple choice,
    a 1-based option number also counts.
    """
    if tool not in QUIZ_BANK:
        raise ValueError(f"unknown tool {tool!r}; choose from: {', '.join(TOOLS)}")
    questions = QUIZ_BANK[tool]
    details = []
    score = 0
    for i, item in enumerate(questions):
        given = answers[i] if i < len(answers) else ""
        correct = _answer_matches(item, given)
        score += 1 if correct else 0
        details.append({
            "question": item["q"],
            "expected": item["answer"],
            "given": given,
            "correct": correct,
            "why": item["why"],
        })
    return {"tool": tool, "score": score, "total": len(questions), "details": details}


def _answer_matches(item: dict, given: str) -> bool:
    given = (given or "").strip().lower()
    expected = item["answer"].strip().lower()
    if not given:
        return False
    if given == expected:
        return True
    if given.isdigit():
        idx = int(given) - 1
        options = item.get("options", [])
        if 0 <= idx < len(options) and options[idx].strip().lower() == expected:
            return True
    return False


def quiz_interactive(tool: str, out: Any = sys.stdout) -> int:
    """Ask the quiz questions via stdin. Returns exit code."""
    if tool not in QUIZ_BANK:
        print(f"Unknown tool {tool!r}; choose from: {', '.join(TOOLS)}", file=out)
        return 2
    questions = QUIZ_BANK[tool]
    answers = []
    print(f"{tool} quiz: {len(questions)} questions. Type the answer or the option number.", file=out)
    print("", file=out)
    for i, item in enumerate(questions, 1):
        print(f"Q{i}. {item['q']}", file=out)
        for n, opt in enumerate(item.get("options", []), 1):
            print(f"   {n}. {opt}", file=out)
        try:
            answers.append(input("Your answer: ").strip())
        except EOFError:
            answers.append("")
        print("", file=out)
    result = grade_quiz(tool, answers)
    print(f"Score: {result['score']}/{result['total']}", file=out)
    for d in result["details"]:
        mark = "OK " if d["correct"] else "MISS"
        print(f"[{mark}] {d['question']}", file=out)
        if not d["correct"]:
            print(f"      expected: {d['expected']}", file=out)
        print(f"      why: {d['why']}", file=out)
    return 0


def cmd_cheatsheet(args: argparse.Namespace, out: Any = sys.stdout) -> int:
    tool = getattr(args, "tool", None)
    if not tool:
        print("Available tools: " + ", ".join(TOOLS), file=out)
        return 0
    try:
        print(render_cheatsheet(tool), file=out, end="")
    except ValueError as e:
        print(str(e), file=out)
        return 2
    return 0


def cmd_quiz(args: argparse.Namespace, out: Any = sys.stdout) -> int:
    tool = getattr(args, "tool", None)
    if not tool:
        print("Available tools: " + ", ".join(TOOLS), file=out)
        print("Run `sre quiz --tool kubectl` to start.", file=out)
        return 0
    return quiz_interactive(tool, out=out)


# ---------------------------------------------------------------------------
# Feature 3: SRE career ladder guide (general guidance, not company-specific)
# ---------------------------------------------------------------------------

LADDER_LEVELS = ["L3", "L4", "L5", "L6"]

LADDER: dict[str, dict[str, str]] = {
    "L3": {
        "title": "L3 - SRE (early career)",
        "scope": "Owns well-scoped tasks and small services end to end: deploys, dashboards, "
                 "runbooks. Works from tickets and playbooks with guidance from senior engineers.",
        "technical_bar": "Solid Linux, networking, and one scripting language; can read and extend "
                         "existing Terraform/Kubernetes manifests; debugs common failure modes "
                         "(OOM, disk pressure, bad deploys) with a runbook.",
        "leadership": "Asks good questions, documents what they learn, takes clear on-call notes. "
                      "No expectation to lead projects yet.",
        "on_call": "Shadow or secondary on-call with a buddy; expected to follow the runbook, "
                   "escalate early, and write clear incident notes.",
        "promotion_to_next": "Consistently closes on-call follow-ups, writes runbooks others use, "
                             "automates one toil source, shows independent debugging of novel issues.",
        "interview_probes": "Linux and networking fundamentals; a debugging story from a past "
                            "outage or lab; how they learn new tooling; comfort being paged.",
    },
    "L4": {
        "title": "L4 - SRE (mid-level, independent)",
        "scope": "Owns a service or subsystem end to end: SLOs, runbooks, deploys, capacity. "
                 "Expected to handle incidents independently and drive postmortem action items to done.",
        "technical_bar": "Deep in one of Kubernetes/Terraform/observability; writes PromQL and "
                         "builds dashboards others rely on; designs safe rollouts and rollbacks; "
                         "understands distributed-systems failure modes (cascading failure, retry storms).",
        "leadership": "Mentors L3s; leads small projects; writes clear postmortems and design docs; "
                      "pushes back on alert noise and toil.",
        "on_call": "Primary on-call for their services; runs incident command for sev2/sev3; "
                   "expected to reduce toil quarter over quarter.",
        "promotion_to_next": "Leads a multi-quarter reliability project (e.g. SLO program, toil "
                             "reduction); influences beyond their team; demonstrates system design "
                             "thinking in reviews and incidents.",
        "interview_probes": "Walk through a real incident end to end; design a deployment pipeline "
                            "for a stateful service; tradeoffs in alerting (signal vs noise); a toil "
                            "automation they built and its measured impact.",
    },
    "L5": {
        "title": "L5 - Senior SRE",
        "scope": "Owns reliability for a product area or org: sets SLO strategy, error-budget "
                 "policy, capacity planning. Projects span teams and quarters.",
        "technical_bar": "Designs systems for failure: multi-region, graceful degradation, chaos "
                         "testing; deep observability architecture (metrics, tracing, logging at "
                         "scale); evaluates build-vs-buy for platforms.",
        "leadership": "Tech-leads projects with engineers from other teams; mentors across the "
                      "org; drives postmortem culture; communicates outages to leadership and "
                      "customers with clarity.",
        "on_call": "Incident commander for sev1; defines on-call policy, paging standards, and "
                   "escalation paths; accountable for MTTR and alert-quality trends.",
        "promotion_to_next": "Org-level impact: reliability programs adopted by multiple teams; "
                             "recognized technical authority; shapes hiring bar and engineering "
                             "standards; sustained mentorship record.",
        "interview_probes": "Design an SLO/error-budget framework for a new product; tell me about "
                            "a time you said no to a launch on reliability grounds; how you "
                            "reduced incident volume org-wide; a conflict with product over velocity "
                            "vs reliability and how you resolved it.",
    },
    "L6": {
        "title": "L6 - Staff SRE",
        "scope": "Owns reliability strategy for a large org or business-critical platform. "
                 "Impact is measured in org-level outcomes: availability targets, incident cost, "
                 "engineering velocity.",
        "technical_bar": "Sets technical direction: platform architecture, reliability roadmaps, "
                         "build-vs-buy at scale; anticipates failure modes years out; deep in "
                         "distributed systems and capacity economics.",
        "leadership": "Leads through influence across orgs; sponsors and grows senior engineers; "
                      "partners with product and executive leadership on risk tradeoffs; "
                      "represents reliability externally (talks, hiring brand).",
        "on_call": "Rarely primary, but owns the on-call system itself: rotation health, burnout, "
                   "compensation/recognition for on-call load; called in for the hardest sev1s.",
        "promotion_to_next": "Company-level impact beyond one org; creates leverage used by many "
                             "teams (platforms, frameworks, standards); develops staff-level "
                             "successors.",
        "interview_probes": "How would you take an org from 99.9 to 99.99 and what would it cost; "
                            "a reliability strategy you set and how you got buy-in; how you measure "
                            "and price toil; a time you killed a project or changed direction based "
                            "on reliability data.",
    },
}

_LADDER_DISCLAIMER = (
    "General guidance: leveling varies by company (titles, numbers, and bars differ). "
    "Use this to calibrate expectations, not as a promise of any employer's ladder."
)


def render_ladder(level: str | None = None) -> str:
    """Render the ladder guide for one level or all levels."""
    if level is not None and level not in LADDER:
        raise ValueError(f"unknown level {level!r}; choose from: {', '.join(LADDER_LEVELS)}")
    levels = [level] if level else LADDER_LEVELS
    lines = ["# SRE career ladder", "", _LADDER_DISCLAIMER, ""]
    for lvl in levels:
        info = LADDER[lvl]
        lines.append(f"## {info['title']}")
        lines.append("")
        for key in ("scope", "technical_bar", "leadership", "on_call",
                    "promotion_to_next", "interview_probes"):
            label = key.replace("_", " ").capitalize()
            lines.append(f"- {label}: {info[key]}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def cmd_ladder(args: argparse.Namespace, out: Any = sys.stdout) -> int:
    level = getattr(args, "level", None)
    try:
        print(render_ladder(level), file=out, end="")
    except ValueError as e:
        print(str(e), file=out)
        return 2
    return 0


# ---------------------------------------------------------------------------
# CLI wiring (coordinator contract)
# ---------------------------------------------------------------------------

def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the sre subcommands to an argparse subparsers object."""
    p = subparsers.add_parser("stories", help="on-call STAR story builder")
    p.add_argument("--tag", default="on-call", help="tag applied to new stories")
    p.add_argument("--list", action="store_true", help="list saved stories")
    p.set_defaults(func=dispatch, sre_cmd="stories")

    p = subparsers.add_parser("cheatsheet", help="print an observability/tooling cheatsheet")
    p.add_argument("tool", nargs="?", choices=TOOLS, help="tool to show")
    p.set_defaults(func=dispatch, sre_cmd="cheatsheet")

    p = subparsers.add_parser("quiz", help="practice quiz for SRE tooling")
    p.add_argument("--tool", choices=TOOLS, default=None, help="tool to be quizzed on")
    p.set_defaults(func=dispatch, sre_cmd="quiz")

    p = subparsers.add_parser("ladder", help="SRE career ladder guide")
    p.add_argument("--level", choices=LADDER_LEVELS, default=None,
                   help="show one level (default: all)")
    p.set_defaults(func=dispatch, sre_cmd="ladder")


def dispatch(args: argparse.Namespace) -> int:
    """Route to the right subcommand based on args.sre_cmd. Returns exit code."""
    cmd = getattr(args, "sre_cmd", None)
    if cmd == "stories":
        return cmd_stories(args)
    if cmd == "cheatsheet":
        return cmd_cheatsheet(args)
    if cmd == "quiz":
        return cmd_quiz(args)
    if cmd == "ladder":
        return cmd_ladder(args)
    print("Unknown sre subcommand. Try: stories, cheatsheet, quiz, ladder")
    return 2
