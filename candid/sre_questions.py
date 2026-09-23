"""SRE interview prep: a question bank and reliability deep-dives.

This module powers the `sre` command's `questions` and `deepdive`
subcommands. Every question in the bank (candid/data/sre_questions.json)
carries a source label: either a topic genuinely covered in Google's SRE
books, or a question widely reported from real SRE/DevOps interview loops.
Nothing here is presented as asked at a specific company on a specific
date; categories with no verified questions would say so rather than
invent entries.

Coordinator contract:
- `register(subparsers)` adds the `questions` and `deepdive` subcommands.
- `dispatch(args)` reads `args.sre_cmd` and returns an exit code.
- All logic lives in pure functions; CLI parsing stays thin.
"""

from __future__ import annotations

import argparse
import json
from functools import lru_cache
from pathlib import Path

from candid import config

DATA_PATH = Path(__file__).resolve().parent / "data" / "sre_questions.json"

CATEGORIES = ["linux", "networking", "kubernetes", "cicd", "observability", "reliability"]

TOPICS = [
    "slos",
    "error-budgets",
    "redundancy",
    "backpressure",
    "circuit-breakers",
    "chaos-engineering",
    "incident-management",
]

TOPIC_TITLES = {
    "slos": "Service Level Objectives (SLOs)",
    "error-budgets": "Error Budgets",
    "redundancy": "Redundancy and Failure Domains",
    "backpressure": "Backpressure and Load Shedding",
    "circuit-breakers": "Circuit Breakers and Dependency Isolation",
    "chaos-engineering": "Chaos Engineering",
    "incident-management": "Incident Management and Postmortems",
}


# ---------------------------------------------------------------------------
# Question bank
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_questions() -> dict:
    """Load the SRE question bank from the JSON data file."""
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def list_categories() -> list[str]:
    """Category names that have at least one verified question."""
    data = load_questions()
    cats = data.get("categories", {})
    return [c for c in CATEGORIES if c in cats and cats[c]]


def get_questions(category: str | None = None) -> list[dict]:
    """Return questions for one category, or all categories if None."""
    data = load_questions()
    cats = data.get("categories", {})
    if category is None:
        out: list[dict] = []
        for c in CATEGORIES:
            out.extend(cats.get(c, []))
        return out
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category {category!r}. Valid: {', '.join(CATEGORIES)}")
    return list(cats.get(category, []))


def render_questions(questions: list[dict], category: str | None = None) -> str:
    """Render questions as plain text for the terminal."""
    label = category if category else "all categories"
    lines = [f"SRE interview questions: {label} ({len(questions)} questions)", ""]
    for i, q in enumerate(questions, 1):
        lines.append(f"{i}. [{q.get('difficulty', 'medium')}] {q['q']}")
        lines.append(f"   Source: {q.get('source', 'unknown')}")
        points = q.get("talking_points", [])
        if points:
            lines.append("   Key points: " + " / ".join(points))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_category_list() -> str:
    """Render the available categories with question counts."""
    lines = ["SRE question categories:", ""]
    for c in list_categories():
        lines.append(f"  {c} ({len(get_questions(c))} questions)")
    lines.append("")
    lines.append("Use: candid sre questions --category <name>")
    return "\n".join(lines) + "\n"


def questions_output(category: str | None = None, list_categories_flag: bool = False) -> tuple[int, str]:
    """Pure logic for `sre questions`. Returns (exit_code, text)."""
    if list_categories_flag:
        return 0, render_category_list()
    try:
        questions = get_questions(category)
    except ValueError as e:
        return 2, str(e) + "\n"
    if category is not None and not questions:
        return 0, f"No verified questions for category {category!r} yet.\n"
    return 0, render_questions(questions, category)


# ---------------------------------------------------------------------------
# Deep-dives
# ---------------------------------------------------------------------------

DEEPDIVES: dict[str, str] = {
    "slos": """# Service Level Objectives (SLOs)

## The short version
An SLO is a target level of reliability for a service, measured by a
Service Level Indicator (SLI). It turns "be reliable" into a number you
can alert on, argue about, and budget against.

## The three S's
- **SLI**: what you measure. A ratio of good events to total valid events,
  for example successful requests / total requests, or requests under
  300ms / total requests.
- **SLO**: the target, for example 99.9% of requests succeed over 30 days.
- **SLA**: a contract with consequences, usually financial. SLOs are
  internal engineering targets; SLAs are business promises. Keep the SLO
  tighter than the SLA so you get warned before you owe money.

## Choosing good SLIs
Measure from the user's perspective: what the user asked for and what
they got. Two common shapes:
- **Request-based**: good events / total events (success rate).
- **Time-based**: good minutes / total minutes (useful when request
  volume is spiky or near zero).
Pick SLIs users feel: availability, latency, correctness, freshness,
throughput. Instrument at the load balancer or client when you can,
because server-side metrics miss failures that happen before the
request reaches you.

## The math that matters
- 99% over 30 days allows about 7h 12m of downtime.
- 99.9% over 30 days allows about 43m 12s.
- 99.99% over 30 days allows about 4m 19s.
Each extra nine roughly multiplies cost. This is why "five nines for
everything" is a fantasy: the cost curve is steep and most users cannot
tell the difference.

## Anti-patterns
- SLOs on things you do not control (a third-party API, someone else's
  database).
- Too many SLOs: nobody can hold twenty targets in their head. A few
  that cover the user journey beat a dashboard of vanity metrics.
- SLOs nobody alerts on: a target without alerting is a poster on the
  wall.
- Perfectionism: an SLO of 100% removes the error budget and with it
  any room to ship.

## How this shows up in interviews
Expect "define an SLO for this service" or "what SLI would you use for
a checkout API". A strong answer: pick a user-visible SLI, justify the
target with user impact and cost, name what you excluded (planned
maintenance, bad client input), and connect it to alerting and the
error budget.
""",
    "error-budgets": """# Error Budgets

## The short version
An error budget is 1 minus the SLO: the amount of unreliability you
are allowed over the measurement window. It converts reliability from
a moral argument into a resource you spend and replenish.

## The core idea
With a 99.9% SLO over 30 days, the budget is 0.1% of events, about
43 minutes of downtime. Spend it on launches, experiments, and risky
changes. When it is gone, you stop shipping features and work on
reliability until the budget recovers. This gives product and SRE a
shared, quantitative policy instead of a recurring argument about
whether to "slow down".

## Burn rate and alerting
Raw budget consumption is too slow to page on, so you alert on burn
rate: how fast you are consuming the budget relative to the window.
- **Fast burn**: consuming the 30-day budget in hours or a couple of
  days. Page immediately.
- **Slow burn**: consuming it over the full window. Ticket it for
  investigation during business hours.
The standard technique is multi-window, multi-burn-rate alerting: a
short window to detect fast burns and a long window to confirm, so
you page fast on real emergencies without paging on noise.

## Budget policy in practice
- Budgets are per service, agreed between the service owners and the
  teams that depend on them.
- Exhausting the budget freezes risky changes: no launches, no
  experiments, only reliability work and emergency fixes.
- Near-misses count: if you almost exhausted the budget, that is
  signal, not luck.
- Some orgs reset policies quarterly; the window should match how
  the team actually plans work.

## Traps
- Treating the budget as permission to be sloppy. It is permission to
  take calculated risks, and the calculation is the point.
- Alerting on burn rate without a budget policy behind it: pages with
  no agreed response are just noise with extra math.
- Applying one global budget to services with wildly different user
  impact.

## How this shows up in interviews
Expect "what is an error budget and how would you use it". A strong
answer: define it from the SLO, do the 99.9% math, describe the
spend-versus-freeze policy, and explain burn-rate alerting with a
fast-burn versus slow-burn example.
""",
    "redundancy": """# Redundancy and Failure Domains

## The short version
Redundancy means having more capacity than you need, spread across
independent failure domains, so that losing any one domain does not
lose the service.

## Failure domains
Hardware fails in correlated ways: a rack loses power, an availability
zone loses networking, a region loses both. Design for the domain
boundaries your provider actually gives you:
- Spread stateless serving across at least two availability zones,
  with no single zone required for quorum or capacity.
- Replicate state with known consistency tradeoffs; synchronous
  replication is safer but slower and couples failure domains.
- Remember the control plane: if your deploy tooling or DNS lives in
  one place, your "multi-region" service has a single point of failure.

## Patterns
- **N+1**: carry one extra unit of capacity so a single failure is
  absorbed without degradation. Cheap, covers the common case.
- **Active-active**: all regions serve traffic. Best failover story,
  hardest data story.
- **Active-passive**: standby capacity waits. Simpler data story, but
  failover is a procedure that must be tested, and idle capacity
  costs money.
- **Cell-based / shuffle sharding**: partition users into small
  independent cells so a bad deploy or failure hits a fraction of
  users, not everyone. This is how large providers contain blast
  radius without full regional duplication.

## Quorum math
Consensus needs a majority: 3 nodes tolerate 1 failure, 5 tolerate 2.
Never run an even number of voters, and never stretch a quorum across
a WAN link you cannot afford to lose.

## The cost conversation
Redundancy is the most expensive reliability lever. Interviewers want
to hear you trade it off explicitly: what is the cost of an hour of
downtime for this service, and does it justify active-active? For
most internal tools the answer is no, and saying so is a sign of
judgment, not weakness.

## How this shows up in interviews
Expect "design a system that survives a region failure" or "how many
replicas do you need". A strong answer: name the failure domains,
pick active-active versus active-passive with a cost argument, handle
data replication and failover explicitly, and mention how you would
test the failover before you need it.
""",
    "backpressure": """# Backpressure and Load Shedding

## The short version
Backpressure is a overloaded downstream telling upstream to slow down,
instead of silently queueing work until everything collapses at once.
It is the difference between degrading gracefully and falling over.

## Why queues alone are not enough
An unbounded queue turns a traffic spike into a latency spike and
then into an outage: memory fills, garbage collection stalls, timeouts
cascade. Every queue needs a bound and a policy for what happens when
the bound is hit: reject fast, drop the lowest-priority work, or shed
load deliberately.

## The mechanism toolkit
- **Bounded queues with fast rejection**: when the queue is full, say
  no immediately. A fast 503 with Retry-After beats a 60-second
  timeout.
- **Concurrency limits**: cap in-flight work per dependency. Fixed
  limits are simple; adaptive limits (additive increase, multiplicative
  decrease on errors) track real capacity.
- **Load shedding by priority**: drop background work before user
  work, writes before reads where safe, or shed the most expensive
  requests first.
- **Graceful degradation**: serve cached, stale, or reduced
  functionality instead of failing. A recommendations widget that
  shows popular items instead of personalized ones is backpressure
  made visible.
- **Client-side cooperation**: exponential backoff with jitter on
  retries, so a recovering service is not hit by a synchronized
  retry storm. Naive retries are how small incidents become big ones.

## Signals that you need it
Latency climbing while throughput is flat, queues growing without
bound, thread pools saturated, and downstream timeouts that trigger
retries that make the timeouts worse. If you see a retry storm in a
postmortem, the missing piece was almost always backpressure.

## How this shows up in interviews
Expect "your downstream dependency is slow; your service is falling
over; what do you do". A strong answer: bound the work, shed load by
priority, degrade gracefully, fix the retry behavior, and add an
adaptive concurrency limit so it self-tunes next time.
""",
    "circuit-breakers": """# Circuit Breakers and Dependency Isolation

## The short version
A circuit breaker watches calls to a dependency and, when failures
pass a threshold, stops calling it for a while. It converts a slow,
cascading failure into a fast, local one.

## The three states
- **Closed**: calls flow normally; failures are counted.
- **Open**: the failure threshold was crossed; calls fail immediately
  without touching the dependency, giving it room to recover.
- **Half-open**: after a cooldown, a few trial calls are allowed
  through. If they succeed, the breaker closes; if not, it opens
  again.
Thresholds are usually a failure ratio over a sliding window (for
example 50% of requests failing over 30 seconds), not a raw count,
so low-traffic services do not trip on a single error.

## The surrounding patterns
- **Timeouts**: every outbound call needs a deadline, or one slow
  dependency holds your threads forever. Timeouts are the cheapest
  reliability mechanism and the most commonly missing.
- **Retries with backoff and jitter**: retry transient failures, but
  bound the attempts and spread them out so clients do not retry in
  lockstep.
- **Bulkheads**: isolate thread pools, connection pools, and queues
  per dependency, so one bad downstream cannot starve the others.
  The name comes from ship hulls: one flooded compartment should not
  sink the ship.
- **Hedging**: after a latency percentile is exceeded, send the same
  request to a second replica and take whichever answers first. It
  trades a little extra load for much better tail latency.
- **Fallbacks**: when the breaker is open, serve a default, cached,
  or degraded response instead of an error where the product allows
  it.

## Traps
- A breaker with no fallback just fails fast; sometimes that is
  correct, but say so deliberately.
- Breakers on the wrong granularity: one breaker for "the database"
  trips on one bad query pattern and blocks healthy ones.
- Forgetting that the breaker itself needs observability: state
  changes should be metrics and, when unexpected, alerts.

## How this shows up in interviews
Expect "your service depends on three downstream services and one is
flaky". A strong answer: timeouts first, bounded retries with jitter,
a breaker per dependency with a fallback, bulkheads between them, and
an explanation of what the user sees in each state.
""",
    "chaos-engineering": """# Chaos Engineering

## The short version
Chaos engineering is the practice of deliberately injecting failure
into systems to verify they behave as designed before real failure
does it for you. The key word is deliberately: controlled, bounded,
and observed.

## The principles
- **Start from a steady-state hypothesis**: define what "healthy"
  looks like in metrics first, then check whether it holds during
  the experiment.
- **Vary real-world events**: kill processes, sever network links,
  exhaust disk, expire certificates, take down a zone. Test the
  failures you actually fear.
- **Minimize blast radius**: start in staging, then run in production
  against a small slice of traffic with a big red abort button.
- **Automate and repeat**: a one-off game day is theater; a scheduled
  experiment suite is engineering. Netflix's Simian Army, which the
  company has written about publicly, is the canonical example of
  making this continuous.

## How teams actually do it
- **Game days**: scheduled, staffed failure drills with defined
  scenarios, observers, and a debrief. Great for testing the humans
  and the runbooks, not just the machines.
- **Fault injection in CI/CD**: kill a dependency in a staging
  environment on every deploy and verify the service degrades
  instead of dying.
- **Production experiments**: only after staging is boring, with
  guardrails: automatic abort on SLO burn, business-hours only, and
  explicit sign-off from service owners.

## Guardrails that matter
Every experiment needs a hypothesis, a blast-radius limit, an abort
condition tied to real user metrics, and a written result. "We took
down a zone and nothing happened" is a result worth celebrating and
documenting; "we took down a zone and paged everyone" is a result
worth fixing.

## Common objections, answered
- "We cannot afford the risk": you are already taking the risk; chaos
  engineering just schedules it.
- "Our staging does not match prod": then your first chaos finding
  is that staging is untrustworthy, which is valuable on its own.

## How this shows up in interviews
Expect "how would you test that your failover actually works" or
"what is chaos engineering". A strong answer: steady-state
hypothesis, start small, guardrails and abort conditions, and a
concrete example like zone failure or dependency loss with the
metrics you would watch.
""",
    "incident-management": """# Incident Management and Postmortems

## The short version
Incident management is the discipline of restoring service quickly
and learning permanently. The two phases have opposite mindsets:
during the incident, mitigate first and ask questions later; after
the incident, ask every question and fix the system, not the person.

## Roles
- **Incident commander**: owns the response, makes decisions, keeps
  the timeline. Does not debug; commands.
- **Operations / responders**: do the technical work.
- **Communications**: status updates to stakeholders and users on a
  regular cadence. Silence during an outage is its own incident.
- **Scribe**: keeps the timeline. Memory is unreliable under stress;
  the timeline is what the postmortem runs on.
Small incidents need one person wearing several hats; the hats still
exist.

## Severity levels
Define them before you need them, roughly: SEV1 is user-facing
outage or data loss, SEV2 is degraded or at-risk, SEV3 is minor.
Each level names who gets paged, how fast, and what communication
is expected. The point is a shared vocabulary so "how bad is it"
takes seconds, not a meeting.

## During the incident
1. Declare it and assign a commander.
2. Mitigate: roll back, fail over, shed load, disable the feature
   flag. Restoring service beats understanding the bug.
3. Communicate on a schedule, even if the update is "no change".
4. Preserve evidence: logs, graphs, config diffs.
5. Stand down explicitly; do not just drift away.

## Blameless postmortems
The postmortem asks what allowed the failure, not who caused it.
People do not come to work to break production; if a reasonable
engineer could make the same mistake, the system is at fault. A good
postmortem has: a timeline, the impact in user terms, root causes
(plural; there is never just one), and action items with owners and
deadlines. The "five whys" technique is a useful starting prompt but
a weak stopping rule: keep asking until you reach something you can
fix in the system, and be skeptical of answers that end at human
error.

## Making it stick
Track action items like production work, with the same priority.
Review past postmortems before big launches. Measure repeat
incidents: the same outage twice means the learning loop is broken.

## How this shows up in interviews
Expect "walk me through how you handle a production outage" or
"tell me about a time you caused an outage". A strong answer: roles
and communication, mitigate before root-causing, and a blameless
postmortem story that ends with a systemic fix, not a person being
retrained.
""",
}


def list_topics() -> list[str]:
    """Deep-dive topic slugs."""
    return list(TOPICS)


def topic_title(topic: str) -> str:
    """Human-readable title for a topic slug."""
    if topic not in TOPIC_TITLES:
        raise ValueError(f"Unknown topic {topic!r}. Valid: {', '.join(TOPICS)}")
    return TOPIC_TITLES[topic]


def get_deepdive(topic: str) -> str:
    """Return the deep-dive markdown for a topic slug."""
    if topic not in DEEPDIVES:
        raise ValueError(f"Unknown topic {topic!r}. Valid: {', '.join(TOPICS)}")
    return DEEPDIVES[topic]


def save_deepdive(topic: str, base_dir: Path | None = None) -> Path:
    """Write a deep-dive to <base_dir>/<topic>.md. Returns the path.

    Defaults to config.DATA_DIR / "sre" (honors CANDID_DATA_DIR).
    """
    content = get_deepdive(topic)
    dest_dir = Path(base_dir) if base_dir is not None else config.DATA_DIR / "sre"
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{topic}.md"
    path.write_text(content, encoding="utf-8")
    return path


def deepdive_output(topic: str, save: bool = False, base_dir: Path | None = None) -> tuple[int, str]:
    """Pure logic for `sre deepdive`. Returns (exit_code, text)."""
    try:
        content = get_deepdive(topic)
    except ValueError as e:
        return 2, str(e) + "\n"
    if save:
        path = save_deepdive(topic, base_dir=base_dir)
        return 0, content + f"\nSaved to {path}\n"
    return 0, content


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `questions` and `deepdive` subcommands to an `sre` subparsers."""
    q = subparsers.add_parser("questions", help="SRE interview question bank")
    q.add_argument("--category", choices=CATEGORIES,
                   help="Filter by category (default: all)")
    q.add_argument("--list-categories", action="store_true",
                   help="List available categories and exit")
    q.set_defaults(func=dispatch)

    d = subparsers.add_parser("deepdive", help="Reliability concept deep-dive")
    d.add_argument("topic", choices=TOPICS, help="Deep-dive topic")
    d.add_argument("--save", action="store_true",
                   help="Also save the markdown to candid_data/sre/<topic>.md")
    d.set_defaults(func=dispatch)


def cmd_questions(args: argparse.Namespace) -> int:
    code, text = questions_output(
        category=getattr(args, "category", None),
        list_categories_flag=getattr(args, "list_categories", False),
    )
    print(text, end="")
    return code


def cmd_deepdive(args: argparse.Namespace) -> int:
    code, text = deepdive_output(
        topic=getattr(args, "topic", ""),
        save=getattr(args, "save", False),
    )
    print(text, end="")
    return code


def dispatch(args: argparse.Namespace) -> int:
    """Route to the right subcommand based on args.sre_cmd."""
    cmd = getattr(args, "sre_cmd", None)
    if cmd == "questions":
        return cmd_questions(args)
    if cmd == "deepdive":
        return cmd_deepdive(args)
    print(f"Unknown sre subcommand: {cmd!r}. Valid: questions, deepdive")
    return 2
