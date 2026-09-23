"""Posting-age analysis: how response rate varies with how fresh a posting was.

`curve` shows a per-bucket table (bucket | n | response rate) with ASCII bars.
`analyze` is the full timing report: best/worst buckets with sample sizes,
overall response rate, and 2-4 plain-language guidance lines derived ONLY
from the user's own data. No claims are invented; small samples are hedged.
"""

from __future__ import annotations

import json

from candid import timing as T


def _dated_apps(apps: list[dict]) -> list[dict]:
    """Applications with a computable posting age."""
    return [a for a in apps if T.posting_age_days(a) is not None]


def _curve_data(apps: list[dict]) -> dict:
    dated = _dated_apps(apps)
    groups = {b: [] for b in T.BUCKETS}
    for app in dated:
        groups[T.bucket_posting_age(T.posting_age_days(app))].append(app)
    buckets = []
    for b in T.BUCKETS:
        g = groups[b]
        pos = sum(1 for a in g if T.is_positive(a))
        buckets.append({
            "bucket": b,
            "n": len(g),
            "positives": pos,
            "response_rate": (pos / len(g)) if g else None,
        })
    pos_total = sum(1 for a in dated if T.is_positive(a))
    return {
        "buckets": buckets,
        "overall": {
            "n": len(dated),
            "positives": pos_total,
            "response_rate": (pos_total / len(dated)) if dated else None,
        },
        "total_applications": len(apps),
        "undated_applications": len(apps) - len(dated),
        "enough_data": T.enough_data(dated),
        "honesty_note": T.honesty_note(dated),
    }


def _bar(rate: float | None, width: int = 20) -> str:
    if rate is None:
        return ""
    return "█" * max(1, int(round(rate * width))) if rate > 0 else ""


def cmd_curve(a) -> None:
    """Bucket applications by posting age at apply time; print n + rate."""
    data = _curve_data(T.load_applications())
    if getattr(a, "json", False):
        print(json.dumps(data, indent=2))
        return
    lines = ["Posting age at apply time", ""]
    lines.append(f"{'Bucket':<12}{'n':>5}  {'Rate':<8}Bar")
    for b in data["buckets"]:
        if data["enough_data"] and b["response_rate"] is not None:
            rate_txt = f"{b['response_rate']:.1%}"
            bar = _bar(b["response_rate"])
        else:
            rate_txt, bar = "n/a", ""
        lines.append(f"{b['bucket']:<12}{b['n']:>5}  {rate_txt:<8}{bar}")
    lines.append("")
    ov = data["overall"]
    if ov["n"]:
        lines.append(f"Overall: {ov['positives']}/{ov['n']} positive "
                     f"({ov['response_rate']:.1%})")
    else:
        lines.append("No applications with posting dates yet.")
    lines.append("")
    lines.append(data["honesty_note"])
    print("\n".join(lines))


def _guidance(data: dict) -> list[str]:
    """2-4 plain-language lines, grounded only in the data. Hedged if small."""
    ov = data["overall"]
    n = ov["n"]
    if n < T.MIN_SAMPLE:
        return [
            f"Only {n} application{'s' if n != 1 else ''} with posting dates  -  "
            "too few to spot reliable patterns.",
            "Pass --posted-date when you `track add`, or fill it in later "
            "with `track update <id> --posted-date YYYY-MM-DD`.",
        ]
    lines: list[str] = []
    buckets = [b for b in data["buckets"] if b["n"] > 0]
    best = max(buckets, key=lambda b: (b["response_rate"], b["n"]))
    worst = min(buckets, key=lambda b: (b["response_rate"], -b["n"]))
    br, wr = best["response_rate"], worst["response_rate"]
    ratio = (br / wr) if wr else None
    if ratio is not None and ratio >= 1.25:
        lines.append(
            f"Your response rate is {ratio:.1f}x higher applying {best['bucket']} "
            f"after posting ({br:.0%}, n={best['n']}) than {worst['bucket']} "
            f"({wr:.0%}, n={worst['n']}).")
    else:
        lines.append(
            f"No strong timing pattern yet: best window {best['bucket']} "
            f"({br:.0%}, n={best['n']}) vs weakest {worst['bucket']} "
            f"({wr:.0%}, n={worst['n']}).")
    if min(best["n"], worst["n"]) < T.MIN_SAMPLE:
        lines.append("Sample sizes are small  -  treat this as a hint, not a rule.")
    if data["undated_applications"]:
        u, t = data["undated_applications"], data["total_applications"]
        lines.append(f"{u} of {t} applications are missing posting dates; "
                     "adding --posted-date sharpens this.")
    if best["bucket"] in ("0-3 days", "4-7 days"):
        lines.append("Early applications (within a week of posting) are your "
                     "strongest window so far.")
    lines.append("Keep recording --posted-date on new applications to sharpen "
                 "this picture.")
    return lines[:4]


def cmd_analyze(a) -> None:
    """Full timing report: best/worst buckets, overall rate, data-only guidance."""
    data = _curve_data(T.load_applications())
    guidance = _guidance(data)
    if getattr(a, "json", False):
        buckets = [b for b in data["buckets"] if b["n"] > 0]
        report = {
            "overall": data["overall"],
            "best_bucket": max(buckets, key=lambda b: (b["response_rate"], b["n"])) if buckets else None,
            "worst_bucket": min(buckets, key=lambda b: (b["response_rate"], -b["n"])) if buckets else None,
            "guidance": guidance,
            "enough_data": data["enough_data"],
            "honesty_note": data["honesty_note"],
        }
        print(json.dumps(report, indent=2))
        return
    ov = data["overall"]
    lines = ["Timing analysis", ""]
    if ov["n"]:
        lines.append(f"Overall response rate: {ov['positives']}/{ov['n']} "
                     f"({ov['response_rate']:.1%})")
        buckets = [b for b in data["buckets"] if b["n"] > 0]
        best = max(buckets, key=lambda b: (b["response_rate"], b["n"]))
        worst = min(buckets, key=lambda b: (b["response_rate"], -b["n"]))
        lines.append(f"Best window:    {best['bucket']:<10} {best['response_rate']:.0%} (n={best['n']})")
        lines.append(f"Weakest window: {worst['bucket']:<10} {worst['response_rate']:.0%} (n={worst['n']})")
    else:
        lines.append("No applications with posting dates yet.")
    lines += ["", "Guidance:"]
    lines += [f"  - {g}" for g in guidance]
    lines += ["", data["honesty_note"]]
    print("\n".join(lines))
