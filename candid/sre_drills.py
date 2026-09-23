"""SRE incident-response drills and war-room simulator.

Two subcommands (registered by `register()` for the top-level `sre` group):

  drill    -- timed, multiple-choice incident-response drills built as
              decision trees. At each step you get the situation plus
              3-4 action choices; each choice is scored and explained,
              and the tree branches. Final score + debrief are saved to
              candid_data/sre_drills/.
  warroom  -- war-room simulator. An incident commander and teammates
              drive a simulated incident and you respond as the on-call
              engineer. An optional Gemini AI commander mirrors the
              credential handling of candid.mock (surrogate auth via the
              google-gemini skill, never hardcoded keys); when AI is
              unavailable it falls back to a fully scripted local
              simulation that works offline. Transcripts are saved to
              candid_data/sre_drills/.

Usage (after wiring into the top-level CLI):
    python -m candid sre drill --list
    python -m candid sre drill --scenario latency-spike
    python -m candid sre drill --scenario disk-full-cascade --no-timer
    python -m candid sre drill --scenario bad-deploy --auto --answers 1,2,3,2
    python -m candid sre warroom --scenario dns-outage
    python -m candid sre warroom --scenario bad-deploy --auto

Everything except the optional AI commander runs locally and
deterministically. No network calls, no keys, no secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from candid import config as C


class SreDrillsError(Exception):
    """Raised for SRE-drill usage errors."""


def _drills_dir() -> Path:
    """Results dir. Lazily resolved so tests can override CANDID_DATA_DIR."""
    d = C.DATA_DIR / "sre_drills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Scenario decision trees
# ---------------------------------------------------------------------------
# Each scenario: title, intro, steps. A step has id, situation, choices.
# A choice has text, points (0-100), explain (why this scores that way),
# and next (id of the following step, or None to end the drill).

SCENARIOS: dict[str, dict] = {
    "latency-spike": {
        "title": "Latency spike on the checkout API",
        "intro": (
            "You are the on-call SRE. It is 02:14. PagerDuty fires: p99 "
            "latency on POST /checkout has been above 4s for 10 minutes. "
            "Traffic is normal. Make the right calls, fast."
        ),
        "steps": [
            {
                "id": "detect",
                "situation": (
                    "PagerDuty: p99 latency on POST /checkout > 4s for 10 min. "
                    "p50 is fine, traffic volume is flat, no deploy in the "
                    "last 6 hours. What is your first move?"
                ),
                "choices": [
                    {
                        "text": "Open the latency dashboard and split by endpoint, AZ, and instance to scope the blast radius.",
                        "points": 100,
                        "explain": "Scoping first is correct: p50 fine + p99 bad hints at a tail-latency cause (a slow dependency, a hot instance, one bad AZ), not a global overload. Scoping drives every later decision.",
                        "next": "scope",
                    },
                    {
                        "text": "Immediately scale the checkout service to 3x replicas.",
                        "points": 20,
                        "explain": "Scaling before you know the cause can mask the signal and wastes capacity. If the bottleneck is downstream (DB pool), more replicas can make it worse.",
                        "next": "scope",
                    },
                    {
                        "text": "Acknowledge the page and wait 15 minutes to see if it recovers.",
                        "points": 0,
                        "explain": "A 10-minute sustained p99 breach is already a real incident. Waiting burns your error budget and delays mitigation with no upside.",
                        "next": "scope",
                    },
                    {
                        "text": "Post in #incidents that you are investigating and share the alert link.",
                        "points": 60,
                        "explain": "Declaring early is good practice, but communication alone does not scope the problem. Do this in parallel with scoping, not instead of it.",
                        "next": "scope",
                    },
                ],
            },
            {
                "id": "scope",
                "situation": (
                    "Dashboard: the spike is isolated to instances in us-east-1b. "
                    "p99 on DB query time from those instances is 8s vs 40ms "
                    "elsewhere. Connection pool on the 1b app instances is "
                    "saturated (50/50 in use), while 1a/1c pools are idle. "
                    "What is the most likely cause?"
                ),
                "choices": [
                    {
                        "text": "Connection pool exhaustion against the primary DB, possibly from stuck or long-running queries pinned to 1b.",
                        "points": 100,
                        "explain": "Saturated pool + huge DB query time in one AZ is the textbook signature of pool exhaustion, often from a few stuck queries holding connections. This points your mitigation at the pool and the queries.",
                        "next": "mitigate",
                    },
                    {
                        "text": "The 1b AZ itself is degraded; fail all traffic out of 1b.",
                        "points": 40,
                        "explain": "Possible, but the app instances in 1b are otherwise healthy and reachable. The smoking gun is the DB pool, not the AZ. Failing over treats the symptom.",
                        "next": "mitigate",
                    },
                    {
                        "text": "A bad deploy, since latency started suddenly.",
                        "points": 10,
                        "explain": "There has been no deploy in 6 hours, and a bad deploy would hit all AZs equally. Do not chase the deploy timeline when the data says pool.",
                        "next": "mitigate",
                    },
                    {
                        "text": "A DDoS attack targeting the checkout endpoint.",
                        "points": 0,
                        "explain": "Traffic is flat, so there is no attack. Reaching for DDoS without a traffic anomaly is a red herring.",
                        "next": "mitigate",
                    },
                ],
            },
            {
                "id": "mitigate",
                "situation": (
                    "Confirmed: three reporting queries from a new analytics "
                    "cron are holding 47 of 50 connections open in 1b, each "
                    "running for 20+ minutes. Checkout requests are queueing "
                    "behind them. What do you do right now?"
                ),
                "choices": [
                    {
                        "text": "Kill the three long-running reporting queries and temporarily raise the pool size while you verify recovery.",
                        "points": 100,
                        "explain": "Correct order: stop the bleeding (kill the runaway queries), restore headroom (raise pool), verify p99 recovers. Killing first is safe here because they are read-only analytics queries, rerunnable later.",
                        "next": "harden",
                    },
                    {
                        "text": "Restart the checkout service pods in 1b.",
                        "points": 30,
                        "explain": "Restarting drops in-flight checkout requests and takes minutes to warm up, while the stuck queries keep running. It treats the app, not the DB-side cause.",
                        "next": "harden",
                    },
                    {
                        "text": "Fail over the primary DB to the standby.",
                        "points": 10,
                        "explain": "A DB failover is the riskiest move on the board and does not fix pool saturation: the stuck queries will just re-pin on the new primary. Save failover for actual DB failure.",
                        "next": "harden",
                    },
                    {
                        "text": "Just raise the pool size to 200 and monitor.",
                        "points": 50,
                        "explain": "More headroom buys time, but the runaway queries will eventually eat the bigger pool too. Mitigation without stopping the leak is temporary.",
                        "next": "harden",
                    },
                ],
            },
            {
                "id": "harden",
                "situation": (
                    "p99 is back under 300ms. The incident is mitigated. The "
                    "analytics cron owner says the queries are needed for a "
                    "morning report. What is the right follow-through?"
                ),
                "choices": [
                    {
                        "text": "Move analytics queries to the read replica with a statement timeout, and add pool-saturation + long-query alerts.",
                        "points": 100,
                        "explain": "This fixes the structural cause: analytics traffic leaves the primary pool, statement timeouts cap future runaways, and alerts catch the next one before it pages checkout users.",
                        "next": None,
                    },
                    {
                        "text": "Leave the pool at the raised size and close the incident.",
                        "points": 20,
                        "explain": "The raised pool is a bandage. Without moving the analytics load or adding guardrails, the next heavy query run replays this exact incident.",
                        "next": None,
                    },
                    {
                        "text": "Ban all analytics queries against production.",
                        "points": 40,
                        "explain": "Overcorrection. Analytics on the read replica is a legitimate pattern; banning it punishes the business instead of fixing the routing.",
                        "next": None,
                    },
                    {
                        "text": "Write a long post-mortem blaming the cron owner.",
                        "points": 0,
                        "explain": "Blameless post-mortems exist because the system allowed a cron to take down checkout. Fix the guardrails (replica routing, timeouts, alerts), not the person.",
                        "next": None,
                    },
                ],
            },
        ],
    },
    "disk-full-cascade": {
        "title": "Disk-full cascade on the API fleet",
        "intro": (
            "You are the on-call SRE. Alerts are firing for disk usage > 90% "
            "on 12 of 40 API hosts, and one host just went read-only. "
            "Stop the cascade."
        ),
        "steps": [
            {
                "id": "triage",
                "situation": (
                    "12 hosts above 90% disk, one read-only. Error rate is "
                    "climbing as hosts drop out of the load balancer. Your "
                    "first action?"
                ),
                "choices": [
                    {
                        "text": "Check what is consuming disk (largest dirs/files) on an affected host before touching anything.",
                        "points": 100,
                        "explain": "You cannot safely free space until you know what is filling it. Blind deletion risks removing data you need; sizing the culprit takes 30 seconds and guides a safe fix.",
                        "next": "identify",
                    },
                    {
                        "text": "Delete the oldest log files on all hosts immediately.",
                        "points": 40,
                        "explain": "Fast, but blind. If the filler is a runaway core dump or a stuck queue, log deletion frees little and you lose forensic evidence.",
                        "next": "identify",
                    },
                    {
                        "text": "Reboot the read-only host.",
                        "points": 0,
                        "explain": "Rebooting a full, read-only disk does not free space and can leave the host unable to boot. Never reboot your way out of a disk-full.",
                        "next": "identify",
                    },
                    {
                        "text": "Add 12 fresh hosts to the fleet to replace the sick ones.",
                        "points": 20,
                        "explain": "Fresh hosts will fill up the same way if the cause is systemic (it usually is). Capacity without diagnosis just delays the cascade by hours.",
                        "next": "identify",
                    },
                ],
            },
            {
                "id": "identify",
                "situation": (
                    "The culprit: /var/log/app is 78% of disk on every sick "
                    "host. A debug flag flipped on in yesterday's config "
                    "push is logging every request body at DEBUG level, "
                    "about 2 GB/hour/host. What is the safe immediate fix?"
                ),
                "choices": [
                    {
                        "text": "Flip the debug flag back off via config push, then rotate and compress the existing logs.",
                        "points": 100,
                        "explain": "Stops the inflow first (config), then reclaims space safely (rotate + compress keeps recent logs for debugging). Order matters: freeing space without stopping the leak refills the disk in hours.",
                        "next": "prevent",
                    },
                    {
                        "text": "rm -rf /var/log/app/* on all hosts.",
                        "points": 30,
                        "explain": "Frees space now, but open file handles mean the space may not actually release until processes restart, and you destroy evidence. Rotation is the safe equivalent.",
                        "next": "prevent",
                    },
                    {
                        "text": "Mount a bigger volume on each host.",
                        "points": 40,
                        "explain": "Buys time at 2 GB/hour/host but never stops the leak, and resizing 40 volumes under pressure is slow, risky work.",
                        "next": "prevent",
                    },
                    {
                        "text": "Restart the app on all hosts to release file handles.",
                        "points": 10,
                        "explain": "A rolling restart of the whole fleet during an active cascade maximizes blast radius. Only restart if rotation does not release the space.",
                        "next": "prevent",
                    },
                ],
            },
            {
                "id": "prevent",
                "situation": (
                    "Disks are draining back to healthy levels. The debug "
                    "flag was flipped by a well-meaning engineer chasing a "
                    "bug. What prevents the next cascade?"
                ),
                "choices": [
                    {
                        "text": "Cap log volume per host, alert on disk at 70/85%, and require config-flag changes to go through review with a volume estimate.",
                        "points": 100,
                        "explain": "Defense in depth: a hard cap bounds the damage, earlier alerts give you hours instead of minutes, and review on high-volume flags catches the next debug accident before it ships.",
                        "next": None,
                    },
                    {
                        "text": "Tell the engineer not to enable debug logging again.",
                        "points": 10,
                        "explain": "People forget, people rotate. A verbal warning is not a control; the system must make the mistake hard or harmless.",
                        "next": None,
                    },
                    {
                        "text": "Double disk size on all hosts.",
                        "points": 30,
                        "explain": "More headroom without a cap just moves the same failure further out. At 2 GB/hour, doubled disks still fill; the failure mode is unchanged.",
                        "next": None,
                    },
                    {
                        "text": "Ship logs to a remote aggregator and stop storing locally.",
                        "points": 60,
                        "explain": "Good hygiene and worth doing, but remote shipping alone does not bound local buffer growth during an outage of the shipper. Pair it with caps and alerts.",
                        "next": None,
                    },
                ],
            },
        ],
    },
    "bad-deploy": {
        "title": "Bad deploy: error rate spike after release",
        "intro": (
            "You are the on-call SRE. Release v2.14.0 finished rolling out "
            "20 minutes ago. Error rate on the API is climbing: 0.1% to "
            "4% and rising. Decide fast, but do not make it worse."
        ),
        "steps": [
            {
                "id": "correlate",
                "situation": (
                    "Error rate 4% and rising, 20 minutes after v2.14.0 "
                    "finished deploying. Dashboards show errors only on "
                    "pods running the new version. What do you conclude "
                    "and do first?"
                ),
                "choices": [
                    {
                        "text": "Treat the deploy as the prime suspect: halt the rollout pipeline and pull up the canary/error diff for v2.14.0.",
                        "points": 100,
                        "explain": "Errors scoped to new-version pods right after a release is the strongest possible deploy correlation. Halting the pipeline stops it getting worse while you confirm.",
                        "next": "decide",
                    },
                    {
                        "text": "Assume a downstream dependency is flaky and start checking vendor status pages.",
                        "points": 20,
                        "explain": "A dependency issue would hit old and new pods equally. The version-scoped errors rule this out as the primary cause.",
                        "next": "decide",
                    },
                    {
                        "text": "Wait for the error rate to stabilize before acting.",
                        "points": 0,
                        "explain": "A rising 4% error rate is user-facing damage accumulating by the minute. Waiting is the most expensive option on the board.",
                        "next": "decide",
                    },
                    {
                        "text": "Page the whole backend team into a bridge.",
                        "points": 40,
                        "explain": "A bridge is reasonable at higher severity, but paging everyone before you have scoped the cause burns goodwill. Page the deploy owner first, widen if needed.",
                        "next": "decide",
                    },
                ],
            },
            {
                "id": "decide",
                "situation": (
                    "Confirmed: v2.14.0 throws NullPointerExceptions on a "
                    "code path hit by ~5% of requests. The deploy owner is "
                    "awake and says a fix will take about 45 minutes. "
                    "Error rate is now 6%. Your call?"
                ),
                "choices": [
                    {
                        "text": "Roll back to v2.13.9 now; let the fix go through the normal pipeline later.",
                        "points": 100,
                        "explain": "Rollback is the fastest path to healthy: minutes, well-practiced, reversible. A 45-minute forward fix means 45 more minutes of 6% errors. Roll back first, fix calmly after.",
                        "next": "verify",
                    },
                    {
                        "text": "Wait for the forward fix; rolling back loses the new features.",
                        "points": 20,
                        "explain": "Features are worthless while 6% of requests fail. Availability outranks feature velocity during an active incident, every time.",
                        "next": "verify",
                    },
                    {
                        "text": "Roll forward with a hotfix pushed straight to prod, skipping tests.",
                        "points": 0,
                        "explain": "Skipping tests under pressure is how one bad deploy becomes two. The hotfix can introduce a worse bug with no safety net.",
                        "next": "verify",
                    },
                    {
                        "text": "Drain traffic from the new pods gradually and watch.",
                        "points": 50,
                        "explain": "Draining is a partial rollback and better than waiting, but it is slower and fiddlier than a full rollback when 100% of new pods are affected.",
                        "next": "verify",
                    },
                ],
            },
            {
                "id": "verify",
                "situation": (
                    "Rollback complete. Error rate is falling back toward "
                    "baseline. What closes out this incident properly?"
                ),
                "choices": [
                    {
                        "text": "Verify error rate and key business metrics are fully back to baseline, keep the deploy freeze until the post-mortem lands, and schedule a blameless review.",
                        "points": 100,
                        "explain": "Full loop: confirm recovery on both technical and business metrics, protect the fleet with a freeze while the cause is understood, and learn via a blameless review.",
                        "next": "harden",
                    },
                    {
                        "text": "Error rate looks better; resolve the incident and move on.",
                        "points": 20,
                        "explain": "Closing before metrics fully recover risks missing a partial rollback or a second issue hiding under the first. Verify, then close.",
                        "next": "harden",
                    },
                    {
                        "text": "Immediately re-deploy v2.14.0 with the fix to restore the features.",
                        "points": 10,
                        "explain": "Re-deploying minutes after a rollback, before the post-mortem, repeats the exact conditions that caused the incident. The freeze exists for this reason.",
                        "next": "harden",
                    },
                    {
                        "text": "Ask the deploy owner to be more careful next time.",
                        "points": 0,
                        "explain": "'Be more careful' is not a control. The review should ask why the canary did not catch a 5%-of-traffic NPE, and fix that gate.",
                        "next": "harden",
                    },
                ],
            },
            {
                "id": "harden",
                "situation": (
                    "Post-mortem time. The NPE slipped through because the "
                    "canary analysis only watched overall error rate, and "
                    "5% of traffic on one code path did not trip it. What "
                    "is the durable fix?"
                ),
                "choices": [
                    {
                        "text": "Add per-endpoint and per-exception-type canary gates, plus a production smoke test that exercises the affected code path.",
                        "points": 100,
                        "explain": "The canary was blind to this failure shape. Per-endpoint gates and a smoke test covering the path make this class of bug fail the canary instead of your users.",
                        "next": None,
                    },
                    {
                        "text": "Make canary analysis longer, from 10 minutes to 60.",
                        "points": 30,
                        "explain": "A longer canary with the same blind metrics still would not have caught it. Duration is not the gap; metric granularity is.",
                        "next": None,
                    },
                    {
                        "text": "Require two reviewers on every deploy.",
                        "points": 20,
                        "explain": "Reviewers miss NPEs too. Process gates on humans do not substitute for automated canary signals.",
                        "next": None,
                    },
                    {
                        "text": "Nothing; rollbacks worked fine, so the system is healthy.",
                        "points": 10,
                        "explain": "Fast rollback is good, but relying on users to find your bugs is expensive. The goal is catching it before it needs a rollback.",
                        "next": None,
                    },
                ],
            },
        ],
    },
    "dns-outage": {
        "title": "DNS outage: the site is unreachable",
        "intro": (
            "You are the on-call SRE. Reports are flooding in: the site "
            "will not load for many users. Your own monitoring shows the "
            "app servers healthy. Figure out what broke."
        ),
        "steps": [
            {
                "id": "scope",
                "situation": (
                    "Users report the site will not load. Your synthetic "
                    "monitors from three regions also fail, but the app "
                    "servers, load balancers, and DB all look healthy. "
                    "curl by IP works; curl by hostname fails. Diagnosis?"
                ),
                "choices": [
                    {
                        "text": "DNS resolution is broken: check the authoritative nameservers and recent DNS changes first.",
                        "points": 100,
                        "explain": "IP works but hostname does not, with healthy app tiers: that isolates the failure to name resolution. Going straight at DNS skips hours of app-layer debugging.",
                        "next": "identify",
                    },
                    {
                        "text": "Restart the load balancers; they must be dropping traffic.",
                        "points": 10,
                        "explain": "The LBs are healthy and curl-by-IP through them works. Restarting healthy infra during an incident adds risk for zero signal.",
                        "next": "identify",
                    },
                    {
                        "text": "Assume a CDN outage and fail over to origin.",
                        "points": 20,
                        "explain": "A CDN issue would not break hostname resolution itself. Failing over without evidence just moves the broken DNS lookups to a new path.",
                        "next": "identify",
                    },
                    {
                        "text": "Tell users to flush their DNS cache and wait.",
                        "points": 0,
                        "explain": "Synthetic monitors fail too, so this is not client cache. Asking users to fix your outage is never the move.",
                        "next": "identify",
                    },
                ],
            },
            {
                "id": "identify",
                "situation": (
                    "dig against your authoritative nameservers times out. "
                    "Your DNS provider's status page shows a major incident. "
                    "A teammate suggests lowering the TTL 'to fix it faster'. "
                    "What is actually going on, and is the TTL idea right?"
                ),
                "choices": [
                    {
                        "text": "Provider-side authoritative DNS outage; lowering TTL now does nothing because resolvers cannot reach your nameservers to learn the new TTL.",
                        "points": 100,
                        "explain": "Correct on both counts. TTL only matters when resolvers can talk to you. During an authoritative outage, the fix is at the provider or via your secondary DNS, not TTL tuning.",
                        "next": "mitigate",
                    },
                    {
                        "text": "Your DNS records were deleted; re-create them with a low TTL.",
                        "points": 20,
                        "explain": "No evidence of record deletion, and you cannot publish anything while the provider is down. Do not rewrite zone data blind during a provider outage.",
                        "next": "mitigate",
                    },
                    {
                        "text": "A DDoS on your nameservers; lower the TTL to spread the load.",
                        "points": 10,
                        "explain": "The provider status page says it is their incident, not an attack on you. TTL changes do not spread authoritative load anyway.",
                        "next": "mitigate",
                    },
                    {
                        "text": "BGP hijack of your prefixes; contact your ISP.",
                        "points": 0,
                        "explain": "Nothing points at BGP: IP-direct access works fine, which means routing to your network is intact. This is purely DNS.",
                        "next": "mitigate",
                    },
                ],
            },
            {
                "id": "mitigate",
                "situation": (
                    "Confirmed provider outage, ETA unknown. You have a "
                    "secondary DNS provider configured but it has never "
                    "served production traffic. What is the safest "
                    "mitigation?"
                ),
                "choices": [
                    {
                        "text": "Fail over to the secondary DNS provider after verifying its zone data matches, then monitor resolution from multiple vantage points.",
                        "points": 100,
                        "explain": "This is what the secondary is for. Verifying zone data first avoids trading an outage for wrong answers, and multi-vantage monitoring confirms real recovery.",
                        "next": "harden",
                    },
                    {
                        "text": "Switch to the secondary immediately without checking zone data.",
                        "points": 50,
                        "explain": "Speed is good, but stale or mismatched zone data on the secondary can turn an outage into misdirected traffic. The check takes minutes and is worth it.",
                        "next": "harden",
                    },
                    {
                        "text": "Wait for the primary provider to recover; ETA unknown.",
                        "points": 20,
                        "explain": "Waiting on an unknown ETA with a tested secondary available leaves users down for no reason. Use the redundancy you pay for.",
                        "next": "harden",
                    },
                    {
                        "text": "Email all users the raw IP addresses to use meanwhile.",
                        "points": 0,
                        "explain": "TLS certificates will not validate against bare IPs, so this does not even work, and it trains users into terrible security habits.",
                        "next": "harden",
                    },
                ],
            },
            {
                "id": "harden",
                "situation": (
                    "Traffic is recovering via the secondary. The primary "
                    "provider is still degraded. What do you do for the "
                    "long term?"
                ),
                "choices": [
                    {
                        "text": "Keep both providers active (active-active DNS), run regular failover game-days, and extend TTLs on stable records to ride out future blips.",
                        "points": 100,
                        "explain": "Active-active removes the single provider as a single point of failure, game-days prove the failover works before you need it, and longer TTLs let cached records survive short outages.",
                        "next": None,
                    },
                    {
                        "text": "Switch back to the primary as soon as it recovers and forget the secondary.",
                        "points": 20,
                        "explain": "Returning to a single provider restores the exact single point of failure that just bit you. The secondary only helps if it stays warm.",
                        "next": None,
                    },
                    {
                        "text": "Set all TTLs to 60 seconds so future changes propagate fast.",
                        "points": 30,
                        "explain": "Short TTLs help planned changes, not provider outages: during an outage resolvers cannot refresh at all, and 60s TTLs increase your query load and fragility.",
                        "next": None,
                    },
                    {
                        "text": "Move DNS in-house to save the provider bill.",
                        "points": 10,
                        "explain": "Running authoritative DNS well is its own specialty; self-hosting usually reduces resilience unless you invest heavily. Fix the architecture, not the invoice.",
                        "next": None,
                    },
                ],
            },
        ],
    },
}


def list_scenarios() -> list[str]:
    """Scenario ids in stable order."""
    return list(SCENARIOS.keys())


def get_scenario(name: str) -> dict:
    """Return the scenario tree; raises SreDrillsError for unknown names."""
    try:
        return SCENARIOS[name]
    except KeyError:
        raise SreDrillsError(
            f"Unknown scenario '{name}'. Choose from: {', '.join(list_scenarios())}"
        ) from None


def _step_by_id(scenario: dict, step_id: str) -> dict:
    for s in scenario["steps"]:
        if s["id"] == step_id:
            return s
    raise SreDrillsError(f"Scenario step '{step_id}' not found.")


# ---------------------------------------------------------------------------
# Drill engine (pure logic)
# ---------------------------------------------------------------------------

def grade(pct: float) -> str:
    """Letter grade for a drill percentage."""
    if pct >= 90:
        return "A"
    if pct >= 75:
        return "B"
    if pct >= 60:
        return "C"
    if pct >= 40:
        return "D"
    return "F"


def best_choice_index(step: dict) -> int:
    """0-based index of the highest-scoring choice for a step."""
    return max(range(len(step["choices"])), key=lambda i: step["choices"][i]["points"])


def run_drill_scripted(scenario_name: str, answers: list[int],
                       time_limit_s: float | None = None) -> dict:
    """Run a drill with scripted answers (1-based choice numbers).

    Pure and deterministic: no stdin, no timer. Returns a result dict with
    per-step outcomes, score, grade, and a debrief. Used by --auto and tests.
    """
    scenario = get_scenario(scenario_name)
    steps_out: list[dict] = []
    strengths: list[str] = []
    gaps: list[str] = []
    score = 0
    max_score = 0
    timed_out_steps = 0

    step = scenario["steps"][0]
    ai = 0  # answer cursor
    while step is not None:
        choices = step["choices"]
        step_max = max(c["points"] for c in choices)
        max_score += step_max

        if ai < len(answers) and (answers[ai] is None or answers[ai] == 0):
            # scripted timeout marker: no answer, follow first choice's branch
            timed_out_steps += 1
            picked: dict | None = None
            earned = 0
            note = "No answer before the timer expired."
            nxt = step["choices"][0].get("next")
        else:
            idx = (answers[ai] - 1) if ai < len(answers) else 0
            if not 0 <= idx < len(choices):
                idx = 0
            picked = choices[idx]
            earned = picked["points"]
            note = picked["explain"]

        score += earned
        best = choices[best_choice_index(step)]
        if picked is not None and picked["points"] >= step_max:
            strengths.append(f"{step['id']}: {picked['text']}")
        else:
            gaps.append(
                f"{step['id']}: chose "
                f"'{(picked['text'] if picked else 'no answer')}' "
                f"({earned}/{step_max}). Better: '{best['text']}'"
            )

        steps_out.append({
            "step": step["id"],
            "situation": step["situation"],
            "choice": picked["text"] if picked else None,
            "points": earned,
            "max_points": step_max,
            "explanation": note,
            "best_choice": best["text"],
        })

        nxt = picked.get("next") if picked else nxt
        step = _step_by_id(scenario, nxt) if nxt else None
        ai += 1

    pct = round(100.0 * score / max_score, 1) if max_score else 0.0
    return {
        "kind": "drill",
        "scenario": scenario_name,
        "title": scenario["title"],
        "finished_at": _stamp(),
        "steps": steps_out,
        "score": score,
        "max_score": max_score,
        "pct": pct,
        "grade": grade(pct),
        "timed_out_steps": timed_out_steps,
        "strengths": strengths,
        "gaps": gaps,
    }


def save_result(result: dict) -> Path:
    """Persist a drill or warroom result; returns the file path."""
    d = _drills_dir()
    kind = result.get("kind", "result")
    name = result.get("scenario", "unknown")
    path = d / f"{kind}-{name}-{result.get('finished_at', _stamp())}.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# War-room simulator
# ---------------------------------------------------------------------------
# Beats: scripted teammate/commander messages. The user replies as on-call;
# each reply is scored by keyword coverage against `expect`. When the optional
# AI commander is enabled and available, it adds flavor between beats.

WARROOMS: dict[str, dict] = {
    "latency-spike": {
        "title": "War room: checkout latency spike",
        "brief": (
            "You are the on-call SRE. IC Rhea opens a war room with Sam "
            "(backend) and Priya (DBA). Respond to each message as the "
            "on-call: short, decisive, technical."
        ),
        "beats": [
            {
                "from": "IC Rhea",
                "say": (
                    "War room open. p99 on POST /checkout is over 4s, "
                    "sustained 10 minutes. On-call, what is your read and "
                    "your first move?"
                ),
                "expect": ["dashboard", "scope", "p99", "az", "instance"],
                "hint": "Mention scoping: dashboards, p99 vs p50, per-AZ or per-instance split.",
                "good": (
                    "Scope first: p50 is fine so this is tail latency. "
                    "Opening the dashboard split by AZ and instance to find "
                    "where the p99 is coming from."
                ),
            },
            {
                "from": "Sam",
                "say": (
                    "1b instances show DB query time at 8s and the connection "
                    "pool is pegged at 50/50. Smells like the DB. Should I "
                    "just bounce the 1b pods?"
                ),
                "expect": ["pool", "quer", "kill", "stuck", "long-running"],
                "hint": "Name the pool exhaustion and the fix: find and kill the stuck queries, not the pods.",
                "good": (
                    "Do not bounce the pods, that drops in-flight checkouts. "
                    "The pool is exhausted by long-running queries. Find the "
                    "stuck queries and kill them, then raise the pool "
                    "temporarily."
                ),
            },
            {
                "from": "Priya",
                "say": (
                    "Found them: three analytics reporting queries from the "
                    "new cron, running 20+ minutes, holding 47 connections. "
                    "They are read-only. Kill them?"
                ),
                "expect": ["kill", "yes", "read", "replica", "timeout"],
                "hint": "Approve the kill (read-only, rerunnable) and note the follow-up: replica + statement timeout.",
                "good": (
                    "Yes, kill them, they are read-only and rerunnable. "
                    "After recovery, move that cron to the read replica with "
                    "a statement timeout so it cannot pin the primary pool again."
                ),
            },
            {
                "from": "IC Rhea",
                "say": (
                    "p99 is back under 300ms. Nice work. Before we close the "
                    "room: what do we tell the wider team, and what is the "
                    "one follow-up you want tracked?"
                ),
                "expect": ["post-mortem", "alert", "replica", "summary", "track"],
                "hint": "Mention the customer/team update and the tracked follow-up: post-mortem, alerts on pool saturation, replica routing.",
                "good": (
                    "I will post the all-clear and a summary in #incidents. "
                    "Follow-up to track: blameless post-mortem plus alerts on "
                    "pool saturation and long queries, and routing analytics "
                    "to the replica."
                ),
            },
        ],
        "resolution": (
            "Incident mitigated: p99 recovered after killing the runaway "
            "analytics queries. Follow-ups: replica routing, statement "
            "timeouts, pool-saturation alerts, blameless post-mortem."
        ),
    },
    "disk-full-cascade": {
        "title": "War room: disk-full cascade on the API fleet",
        "brief": (
            "You are the on-call SRE. IC Rhea opens a war room with Sam "
            "(backend) and Priya (platform). Respond as the on-call."
        ),
        "beats": [
            {
                "from": "IC Rhea",
                "say": (
                    "12 API hosts over 90% disk, one already read-only, error "
                    "rate climbing. On-call, how do we stop the bleeding?"
                ),
                "expect": ["disk", "du", "largest", "log", "identify", "find"],
                "hint": "Say you will identify the disk hog first (du / largest dirs), not delete blindly.",
                "good": (
                    "First run du to find the largest disk hogs (likely "
                    "under /var/log) and identify what is filling disk "
                    "before deleting anything, so we free the right thing "
                    "safely."
                ),
            },
            {
                "from": "Priya",
                "say": (
                    "/var/log/app is 78% of disk everywhere. A debug flag "
                    "from yesterday's config push is logging full request "
                    "bodies, 2 GB/hour/host. I can rm the logs right now."
                ),
                "expect": ["config", "flag", "rotate", "compress", "off", "stop"],
                "hint": "Stop the inflow first (flip the config flag off), then rotate/compress logs. Do not just rm.",
                "good": (
                    "Hold the rm. Flip the debug flag off via config push "
                    "first to stop the inflow, then rotate and compress the "
                    "logs to reclaim space safely."
                ),
            },
            {
                "from": "Sam",
                "say": (
                    "Disks draining, fleet stabilizing. The engineer who "
                    "flipped the flag feels awful. What do we change so this "
                    "cannot cascade again?"
                ),
                "expect": ["alert", "cap", "review", "70", "volume", "blameless"],
                "hint": "Propose systemic guardrails: log volume caps, earlier disk alerts, review for high-volume flags.",
                "good": (
                    "Blameless: add per-host log volume caps, disk alerts at "
                    "70 and 85 percent, and require review with a volume "
                    "estimate for config flags that change log verbosity."
                ),
            },
        ],
        "resolution": (
            "Cascade stopped: debug flag off, logs rotated. Follow-ups: log "
            "volume caps, earlier disk alerts, flag-change review."
        ),
    },
    "bad-deploy": {
        "title": "War room: bad deploy, error rate climbing",
        "brief": (
            "You are the on-call SRE. IC Rhea opens a war room with Sam "
            "(deploy owner) and Priya (backend). Respond as the on-call."
        ),
        "beats": [
            {
                "from": "IC Rhea",
                "say": (
                    "v2.14.0 finished 20 minutes ago and errors are climbing "
                    "past 4%. On-call, what is your assessment?"
                ),
                "expect": ["deploy", "rollback", "halt", "canary", "correlat", "version"],
                "hint": "Correlate with the deploy: halt the pipeline, check the canary diff.",
                "good": (
                    "The errors correlate with the deploy: they are scoped "
                    "to new-version pods. Halting the rollout pipeline now, "
                    "pulling the canary diff, and preparing a rollback."
                ),
            },
            {
                "from": "Sam",
                "say": (
                    "It is my change, a null pointer on a path hit by 5% of "
                    "requests. I can have a fix in 45 minutes. Should we "
                    "wait for it?"
                ),
                "expect": ["rollback", "now", "minutes", "pipeline"],
                "hint": "Say rollback now; a 45-minute forward fix means 45 more minutes of errors.",
                "good": (
                    "No. Rollback to v2.13.9 now: minutes and reversible, "
                    "versus 45 more minutes of failing requests. Ship the "
                    "fix through the normal pipeline after."
                ),
            },
            {
                "from": "Priya",
                "say": (
                    "Rollback done, errors falling. Can I re-deploy the fixed "
                    "version right away to get the features back?"
                ),
                "expect": ["freeze", "verify", "baseline", "post-mortem", "not yet"],
                "hint": "Say no: verify full recovery first, keep the deploy freeze until the post-mortem.",
                "good": (
                    "Not yet. Verify errors and business metrics are fully "
                    "back to baseline first, keep the deploy freeze until the "
                    "post-mortem lands, then re-deploy through the normal pipeline."
                ),
            },
        ],
        "resolution": (
            "Rolled back to v2.13.9, errors recovered. Follow-ups: per-endpoint "
            "canary gates, smoke test for the affected path, blameless review."
        ),
    },
    "dns-outage": {
        "title": "War room: DNS outage, site unreachable",
        "brief": (
            "You are the on-call SRE. IC Rhea opens a war room with Sam "
            "(networking) and Priya (platform). Respond as the on-call."
        ),
        "beats": [
            {
                "from": "IC Rhea",
                "say": (
                    "Site will not load for users across regions, but app "
                    "servers and load balancers look healthy. On-call, where "
                    "do you look first?"
                ),
                "expect": ["dns", "dig", "nameserver", "resol", "hostname"],
                "hint": "curl by IP works but hostname fails, so this is DNS. Say dig / nameservers.",
                "good": (
                    "IP-direct curl works but hostname fails with healthy app "
                    "tiers, so this is name resolution. Checking DNS: dig "
                    "against our authoritative nameservers and recent zone changes."
                ),
            },
            {
                "from": "Sam",
                "say": (
                    "dig times out against our authoritative nameservers and "
                    "the provider status page shows a major incident. Should "
                    "I lower the TTL to speed up recovery?"
                ),
                "expect": ["ttl", "provider", "secondary", "fail over"],
                "hint": "TTL changes do nothing while resolvers cannot reach the nameservers. Point at the secondary provider.",
                "good": (
                    "No, lowering TTL does nothing now: resolvers cannot "
                    "reach our nameservers to learn the new TTL. This is a "
                    "provider outage, so we fail over to the secondary DNS "
                    "provider."
                ),
            },
            {
                "from": "Priya",
                "say": (
                    "Secondary is configured but never served prod traffic. "
                    "Its zone was synced last week. Flip it now?"
                ),
                "expect": ["verify", "zone", "monitor", "confirm"],
                "hint": "Verify the secondary's zone data matches first, then fail over and monitor from multiple vantage points.",
                "good": (
                    "Verify its zone data matches the primary first, then "
                    "fail over and monitor resolution from multiple vantage "
                    "points to confirm real recovery."
                ),
            },
        ],
        "resolution": (
            "Failed over to secondary DNS, traffic recovering. Follow-ups: "
            "active-active DNS, failover game-days, longer TTLs on stable records."
        ),
    },
}


def list_warroom_scenarios() -> list[str]:
    """War-room scenario ids in stable order."""
    return list(WARROOMS.keys())


def get_warroom(name: str) -> dict:
    """Return the war-room script; raises SreDrillsError for unknown names."""
    try:
        return WARROOMS[name]
    except KeyError:
        raise SreDrillsError(
            f"Unknown war-room scenario '{name}'. "
            f"Choose from: {', '.join(list_warroom_scenarios())}"
        ) from None


def score_reply(reply: str, expect: list[str]) -> dict:
    """Score a free-text reply by keyword coverage. Pure function."""
    text = reply.lower()
    hits = [k for k in expect if k in text]
    pct = round(100.0 * len(hits) / len(expect), 1) if expect else 100.0
    return {"hits": hits, "missed": [k for k in expect if k not in hits], "pct": pct}


def run_warroom_scripted(scenario_name: str, replies: list[str]) -> dict:
    """Run a war-room with scripted replies. Pure and deterministic.

    Returns the transcript with per-beat scores, overall score, and grade.
    """
    room = get_warroom(scenario_name)
    transcript: list[dict] = []
    total = 0.0
    beats = room["beats"]
    for i, beat in enumerate(beats):
        reply = replies[i] if i < len(replies) else ""
        s = score_reply(reply, beat["expect"])
        total += s["pct"]
        transcript.append({
            "from": beat["from"],
            "said": beat["say"],
            "you_replied": reply,
            "score_pct": s["pct"],
            "hits": s["hits"],
            "missed": s["missed"],
            "hint": beat["hint"] if s["pct"] < 100 else "",
            "model_reply": beat["good"] if s["pct"] < 70 else "",
        })
    pct = round(total / len(beats), 1) if beats else 0.0
    return {
        "kind": "warroom",
        "scenario": scenario_name,
        "title": room["title"],
        "finished_at": _stamp(),
        "transcript": transcript,
        "score_pct": pct,
        "grade": grade(pct),
        "resolution": room["resolution"],
    }


# ---------------------------------------------------------------------------
# Optional Gemini AI commander (mirrors candid.mock credential handling)
# ---------------------------------------------------------------------------

def _gemini_chat(system: str, messages: list[dict],
                 model: str = "gemini-3.6-flash") -> str:
    """One Gemini call. Same surrogate-credential pattern as candid.mock.

    Raises SreDrillsError on any failure; callers fall back to scripted lines.
    """
    sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
    from dynamic_credentials import url_with_surrogate_query_param, read_json_response
    import urllib.error
    import urllib.request
    import json as _json

    base = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    url = url_with_surrogate_query_param(base, "custom.google-gemini",
                                         allowed_hosts=["generativelanguage.googleapis.com"])
    payload = {
        "contents": messages,
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 512},
    }
    req = urllib.request.Request(url, data=_json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        data = read_json_response(resp)
    except urllib.error.HTTPError as e:
        raise SreDrillsError(f"Gemini request failed (HTTP {e.code}). Check the google-gemini skill.") from e
    except Exception as e:
        raise SreDrillsError(f"Gemini request failed: {e}. The AI commander needs network + the stored credential.") from e
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        raise SreDrillsError("Gemini returned an unexpected response shape.") from e


_AI_SYSTEM = (
    "You are Rhea, an incident commander running a simulated SRE war room. "
    "Stay in character: terse, decisive, technical. React to the on-call "
    "engineer's last message in 1-3 sentences, then drive the incident "
    "forward. Never break character or mention you are an AI."
)


def ai_commander_line(history: list[str]) -> str | None:
    """Ask Gemini for the commander's next line. Returns None when the AI
    path is unavailable, so the caller can fall back to scripted beats."""
    try:
        convo = "\n".join(history[-8:])
        return _gemini_chat(_AI_SYSTEM, [{
            "role": "user",
            "parts": [{"text": f"War-room so far:\n{convo}\n\nYour next line as IC Rhea:"}],
        }])
    except SreDrillsError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Interactive layer (thin CLI wrappers)
# ---------------------------------------------------------------------------

def _input_with_timeout(prompt: str, timeout_s: float) -> str | None:
    """Read a line from stdin, returning None on timeout. Never raises."""
    result: list[str] = []

    def _read() -> None:
        try:
            result.append(input(prompt))
        except EOFError:
            result.append("")

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        return None
    return result[0] if result else ""


def _print_drill_step(step: dict, idx: int, total: int) -> None:
    print(f"\n--- Step {idx}/{total} ---")
    print(step["situation"])
    for i, c in enumerate(step["choices"], 1):
        print(f"  {i}. {c['text']}")


def cmd_drill(args: argparse.Namespace) -> int:
    """`sre drill` implementation."""
    if getattr(args, "list", False):
        print("Available drill scenarios:")
        for name in list_scenarios():
            print(f"  {name}: {SCENARIOS[name]['title']}")
        return 0

    name = getattr(args, "scenario", None) or "latency-spike"
    scenario = get_scenario(name)
    no_timer = getattr(args, "no_timer", False)
    auto = getattr(args, "auto", False)
    raw_answers = getattr(args, "answers", "") or ""
    scripted = [int(x) for x in raw_answers.split(",") if x.strip().isdigit()]

    print(f"DRILL: {scenario['title']}")
    print(scenario["intro"])
    if not no_timer and not auto:
        print("You have 60 seconds per decision. (--no-timer to disable)")

    answers: list[int] = []
    step = scenario["steps"][0]
    cursor = 0
    while step is not None:
        _print_drill_step(step, cursor + 1, len(scenario["steps"]))
        n = len(step["choices"])
        if auto:
            if cursor < len(scripted):
                choice = scripted[cursor]
            else:
                choice = best_choice_index(step) + 1
            print(f"[auto] choice: {choice}")
        elif no_timer:
            try:
                choice = int(input(f"Your choice (1-{n}): ").strip())
            except (ValueError, EOFError):
                choice = 1
        else:
            line = _input_with_timeout(f"Your choice (1-{n}) [60s]: ", 60.0)
            if line is None:
                print("\nTime expired for this decision.")
                answers.append(0)  # timeout sentinel
                nxt = step["choices"][0].get("next")
                step = _step_by_id(scenario, nxt) if nxt else None
                cursor += 1
                continue
            try:
                choice = int(line.strip())
            except ValueError:
                choice = 1
        if not 1 <= choice <= n:
            print(f"Out of range, using 1.")
            choice = 1
        picked = step["choices"][choice - 1]
        answers.append(choice)
        print(f"\n[{picked['points']}/100] {picked['explain']}")
        nxt = picked.get("next")
        step = _step_by_id(scenario, nxt) if nxt else None
        cursor += 1

    result = run_drill_scripted(name, answers)
    print(f"\n=== Drill complete: {result['score']}/{result['max_score']} "
          f"({result['pct']}%) grade {result['grade']} ===")
    if result["gaps"]:
        print("\nDebrief, gaps to study:")
        for g in result["gaps"]:
            print(f"  - {g}")
    if result["strengths"]:
        print("\nWhat you did well:")
        for s in result["strengths"]:
            print(f"  + {s}")
    path = save_result(result)
    print(f"\nResult saved to {path}")
    return 0


def cmd_warroom(args: argparse.Namespace) -> int:
    """`sre warroom` implementation."""
    name = getattr(args, "scenario", None) or "latency-spike"
    room = get_warroom(name)
    auto = getattr(args, "auto", False)
    use_ai = getattr(args, "use_ai", False)
    raw_replies = getattr(args, "replies", "") or ""
    scripted = [r for r in raw_replies.split("|||")] if raw_replies else []

    print(f"WAR ROOM: {room['title']}")
    print(room["brief"])
    if use_ai:
        print("(AI incident commander enabled; falls back to scripted if unavailable.)")
    print("Type your replies as the on-call engineer. 'quit' ends the simulation.\n")

    replies: list[str] = []
    history: list[str] = [room["brief"]]
    for i, beat in enumerate(room["beats"]):
        print(f"[{beat['from']}] {beat['say']}")
        history.append(f"{beat['from']}: {beat['say']}")
        if auto:
            reply = scripted[i] if i < len(scripted) else beat["good"]
            print(f"[auto] you: {reply}")
        else:
            try:
                reply = input("you: ").strip()
            except EOFError:
                reply = ""
            if reply.lower() == "quit":
                break
        replies.append(reply)
        history.append(f"on-call: {reply}")
        if use_ai and not auto:
            ai_line = ai_commander_line(history)
            if ai_line:
                print(f"[IC Rhea (AI)] {ai_line}")
                history.append(f"IC Rhea: {ai_line}")

    result = run_warroom_scripted(name, replies)
    print(f"\n=== War room complete: {result['score_pct']}% "
          f"grade {result['grade']} ===")
    for t in result["transcript"]:
        mark = "OK " if t["score_pct"] >= 70 else "MISS"
        print(f"[{mark} {t['score_pct']}%] {t['from']}: you replied "
              f"'{t['you_replied'][:80]}'")
        if t["missed"]:
            print(f"      missed: {', '.join(t['missed'])} | hint: {t['hint']}")
        if t["model_reply"]:
            print(f"      model reply: {t['model_reply']}")
    print(f"\nResolution: {result['resolution']}")
    path = save_result(result)
    print(f"Transcript saved to {path}")
    return 0


def dispatch(args: argparse.Namespace) -> int:
    """Route to the right subcommand. Reads args.sre_cmd."""
    cmd = getattr(args, "sre_cmd", None)
    if cmd == "drill":
        return cmd_drill(args)
    if cmd == "warroom":
        return cmd_warroom(args)
    raise SreDrillsError(
        f"Unknown sre subcommand '{cmd}'. Expected 'drill' or 'warroom'."
    )


def register(subparsers: argparse._SubParsersAction) -> None:
    """Add the `drill` and `warroom` subcommands to the `sre` group."""
    p = subparsers.add_parser(
        "drill",
        help="Timed incident-response drills as decision trees.",
        description="Run an SRE incident-response drill: situations with "
                    "scored action choices, a final score, and a debrief.",
    )
    p.add_argument("--scenario", default="latency-spike",
                   choices=list_scenarios(),
                   help="Which drill scenario to run.")
    p.add_argument("--list", action="store_true",
                   help="List available scenarios and exit.")
    p.add_argument("--no-timer", action="store_true",
                   help="Disable the 60s-per-decision timer.")
    p.add_argument("--auto", action="store_true",
                   help="Non-interactive mode: answer from --answers or pick "
                        "the best choice at each step.")
    p.add_argument("--answers", default="",
                   help="Comma-separated 1-based choice numbers for --auto "
                        "(e.g. --answers 1,2,3,2).")
    p.set_defaults(func=dispatch, sre_cmd="drill")

    w = subparsers.add_parser(
        "warroom",
        help="War-room simulator: respond as on-call to a driven incident.",
        description="Simulated incident war room. An incident commander and "
                    "teammates drive the incident; you respond as the on-call "
                    "engineer and get scored on each reply.",
    )
    w.add_argument("--scenario", default="latency-spike",
                   choices=list_warroom_scenarios(),
                   help="Which incident scenario to simulate.")
    w.add_argument("--auto", action="store_true",
                   help="Non-interactive mode: reply with --replies or the "
                        "built-in model replies.")
    w.add_argument("--replies", default="",
                   help="'|||' separated scripted replies for --auto.")
    w.add_argument("--use-ai", action="store_true",
                   help="Try the Gemini AI incident commander (same credential "
                        "handling as candid mock ai); falls back to scripted "
                        "when unavailable.")
    w.set_defaults(func=dispatch, sre_cmd="warroom")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="candid sre")
    sub = parser.add_subparsers(dest="sre_cmd", required=True)
    register(sub)
    a = parser.parse_args()
    sys.exit(a.func(a))
