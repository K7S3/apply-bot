"""Duplicate-detection checks for the candid tracker.

Checks:
  duplicate_applications        (error)   - same normalized (company, role) >1 record
  near_duplicate_applications   (warning) - same normalized company, role ~ same
  duplicate_jd_content          (warning) - same JD text posted at different companies
"""

from __future__ import annotations

import difflib
import re
import string

try:  # primary contract
    from candid.quality import Issue
except ImportError:  # pragma: no cover - local fallback, identical fields
    from dataclasses import dataclass, field

    @dataclass
    class Issue:
        check: str
        severity: str
        record_id: "int | None"
        message: str
        suggestion: str = ""
        auto_fix: "str | None" = None
        fix_args: dict = field(default_factory=dict)


# Corporate suffixes dropped when normalizing a company name.
CORP_SUFFIXES = {"inc", "llc", "corp", "ltd", "co", "company", "corporation",
                 "incorporated", "limited", "gmbh", "sa", "plc", "pvt", "lp",
                 "llp", "pa"}

_PUNCT_RE = re.compile("[" + re.escape(string.punctuation) + "]+")
_WS_RE = re.compile(r"\s+")


def _strip_suffix(tokens: list[str]) -> list[str]:
    """Drop trailing corporate suffixes (e.g. 'Inc', 'LLC')."""
    while tokens and tokens[-1] in CORP_SUFFIXES:
        tokens.pop()
    return tokens


def _norm_company(name: str) -> str:
    name = (name or "").lower()
    name = _PUNCT_RE.sub(" ", name)
    tokens = _strip_suffix(_WS_RE.sub(" ", name).split())
    return " ".join(tokens)


def _norm_role(role: str) -> str:
    role = (role or "").lower()
    role = _PUNCT_RE.sub(" ", role)
    return _WS_RE.sub(" ", role).strip()


def _norm_text(text: str) -> str:
    """Normalize free text for similarity: lowercase, collapse whitespace."""
    return _WS_RE.sub(" ", (text or "").lower()).strip()


def _duplicate_applications(apps: list[dict]) -> list[Issue]:
    issues: list[Issue] = []
    groups: dict[tuple[str, str], list[dict]] = {}
    for app in apps:
        key = (_norm_company(str(app.get("company", ""))),
               _norm_role(str(app.get("role", ""))))
        groups.setdefault(key, []).append(app)
    for key, members in groups.items():
        if len(members) < 2:
            continue
        keeper = members[0]
        for dup in members[1:]:
            issues.append(Issue(
                check="duplicate_applications",
                severity="error",
                record_id=dup.get("id"),
                message=(
                    f"Application id={dup.get('id')} looks like a duplicate of "
                    f"id={keeper.get('id')} ('{keeper.get('company')}' / "
                    f"'{keeper.get('role')}')."
                ),
                suggestion=(
                    f"Keep id={keeper.get('id')} as the canonical record and "
                    f"archive id={dup.get('id')} via track update."
                ),
            ))
    return issues


def _near_duplicate_applications(apps: list[dict]) -> list[Issue]:
    issues: list[Issue] = []
    # Skip pairs already reported as exact duplicates.
    exact = {
        (_norm_company(str(a.get("company", ""))), _norm_role(str(a.get("role", ""))))
        for a in apps
    }
    by_company: dict[str, list[dict]] = {}
    for app in apps:
        by_company.setdefault(_norm_company(str(app.get("company", ""))), []).append(app)
    for company, members in by_company.items():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                ra, rb = _norm_role(str(a.get("role", ""))), _norm_role(str(b.get("role", "")))
                if ra == rb:
                    continue  # already covered by duplicate_applications
                ratio = difflib.SequenceMatcher(None, ra, rb).ratio()
                if ratio >= 0.85:
                    issues.append(Issue(
                        check="near_duplicate_applications",
                        severity="warning",
                        record_id=b.get("id"),
                        message=(
                            f"Application id={b.get('id')} ('{b.get('role')}') has a "
                            f"role very similar to id={a.get('id')} "
                            f"('{a.get('role')}') at the same company "
                            f"('{a.get('company')}')."
                        ),
                        suggestion=(
                            "Verify these are distinct applications; merge or "
                            "archive one if they refer to the same role."
                        ),
                    ))
    return issues


def _duplicate_jd_content(apps: list[dict]) -> list[Issue]:
    issues: list[Issue] = []
    with_jd = [
        app for app in apps
        if isinstance(app.get("jd_text"), str) and _norm_text(app.get("jd_text", ""))
    ]
    for i in range(len(with_jd)):
        for j in range(i + 1, len(with_jd)):
            a, b = with_jd[i], with_jd[j]
            if _norm_company(str(a.get("company", ""))) == _norm_company(
                    str(b.get("company", ""))):
                continue  # same company -> covered by the application checks
            ta, tb = _norm_text(a["jd_text"]), _norm_text(b["jd_text"])
            ratio = difflib.SequenceMatcher(None, ta, tb).ratio()
            if ratio > 0.9:
                issues.append(Issue(
                    check="duplicate_jd_content",
                    severity="warning",
                    record_id=b.get("id"),
                    message=(
                        f"Job description on id={b.get('id')} "
                        f"('{b.get('company')}') is nearly identical to the one "
                        f"on id={a.get('id')} ('{a.get('company')}')."
                    ),
                    suggestion=(
                        "This may be a reposted or cross-listed role; verify it "
                        "is a genuinely separate posting before applying twice."
                    ),
                ))
    return issues


def run(apps: list[dict], ctx: dict) -> list[Issue]:
    """Run all duplicate checks. ctx is accepted for the shared signature."""
    _ = ctx
    return (
        _duplicate_applications(apps)
        + _near_duplicate_applications(apps)
        + _duplicate_jd_content(apps)
    )
