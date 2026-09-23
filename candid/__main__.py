"""candid CLI: the generic job-search copilot.

    python -m candid onboard --resume resume.pdf [--linkedin linkedin.txt]
    python -m candid match --jd job_description.txt --company "X" --role "Y"
    python -m candid tailor resume --jd jd.txt --company X --role Y
    python -m candid track add --company X --role Y
    python -m candid prep --company X --role Y
    python -m candid mock coding
    python -m candid salary lookup --company X --title Y
    python -m candid dashboard            # local web UI (127.0.0.1 only)
    python -m candid gmail import mail.mbox  # propose tracker entries from a Takeout mbox
    python -m candid linkedin import --zip LinkedIn-export.zip
    python -m candid import --gmail-takeout mail.mbox  # general import entry point

Run `python -m candid <command> --help` for details on each command.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys

from candid import __version__

# ---------------------------------------------------------------------------
# command inventory (kept in sync with build_parser below)
# ---------------------------------------------------------------------------

COMMANDS = [
    "onboard", "profile", "match", "tailor", "track", "prep",
    "followup", "offer", "negotiate", "salary", "mock", "jobs", "gems",
    "dashboard", "import", "gmail", "linkedin",
]

SUBCOMMANDS = {
    "profile": ["show"],
    "tailor": ["resume", "cover-letter"],
    "track": ["add", "list", "update", "remove", "stats", "search", "export-csv"],
    "followup": ["thank-you", "check-in", "referral"],
    "offer": ["add", "list", "compare", "export"],
    "negotiate": ["playbook", "script", "counter"],
    "salary": ["lookup", "import-lca", "parse-range"],
    "mock": ["list", "coding", "run", "solution", "hint", "ai",
             "behavioral", "design"],
    "jobs": ["curate", "refresh", "list", "gems", "why-gem"],
    "gems": ["employers"],
    "gmail": ["import", "proposals", "confirm", "reject", "guide"],
    "linkedin": ["import", "guide"],
}

#: Expected (non-bug) failures: reported cleanly, no tracebacks.
_EXPECTED_ERRORS = {
    "OnboardError", "MatchError", "TrackerError", "PrepError",
    "OfferError", "SalaryError", "MockError", "JudgeError",
    "GmailError", "LinkedInError", "DashboardError", "JobsError",
    "ValueError",
}

#: Exact next command to run after each expected failure.
_NEXT_COMMAND = {
    "OnboardError": "python -m candid onboard --help",
    "MatchError": "python -m candid match --help",
    "TrackerError": "python -m candid track list",
    "PrepError": "python -m candid prep --help",
    "OfferError": "python -m candid offer --help",
    "SalaryError": "python -m candid salary --help",
    "MockError": "python -m candid mock --help",
    "JudgeError": "python -m candid mock --help",
    "GmailError": "python -m candid gmail --help",
    "LinkedInError": "python -m candid linkedin guide",
    "DashboardError": "python -m candid dashboard --help",
    "JobsError": "python -m candid jobs --help",
}


def _suggest_typo(message: str) -> list[str]:
    """Closest command / subcommand names for a mistyped word."""
    m = re.search(r"invalid choice: '([^']+)'", message)
    if not m:
        return []
    word = m.group(1)
    pool = list(COMMANDS)
    for subs in SUBCOMMANDS.values():
        pool.extend(subs)
    seen, out = set(), []
    for s in difflib.get_close_matches(word, pool, n=6, cutoff=0.55):
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out[:3]


class CandidParser(argparse.ArgumentParser):
    """ArgumentParser that suggests commands on typos instead of a bare error."""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        sug = _suggest_typo(message)
        if sug:
            sys.stderr.write("\nDid you mean:\n")
            for s in sug:
                sys.stderr.write(f"  python -m candid {s}\n")
        sys.stderr.write("\nRun `python -m candid --help` to list all commands.\n")
        sys.exit(2)


def _examples(*lines: str) -> str:
    return "examples:\n" + "\n".join(f"  {l}" for l in lines)


def _sub(subparsers, name, help, examples=(), **kwargs):
    """add_parser with examples epilog + raw formatting."""
    return subparsers.add_parser(
        name, help=help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_examples(*examples) if examples else None,
        **kwargs)


def _nested(parser, dest="what"):
    return parser.add_subparsers(dest=dest, required=True,
                                 title="subcommands", metavar="<subcommand>",
                                 parser_class=CandidParser)


JD_HELP = ("JD text, file path, URL, or - to read the JD from stdin "
           "(e.g. `cat jd.txt | python -m candid match --jd -`)")


def _profile():
    from candid import profile as P
    return P.load_profile()


def cmd_onboard(a):
    from candid import profile as P
    prof = P.onboard(resume_path=a.resume, linkedin_path=a.linkedin, out_path=a.out)
    print("Profile saved.")
    print(P.profile_card(prof))
    if not prof.get("name"):
        print("\n⚠️  Couldn't detect your name — check the file parsed correctly.")
    if not prof.get("skills"):
        print("⚠️  No skills detected — the parser may need a cleaner export.")


def cmd_profile_show(a):
    from candid import profile as P
    print(P.profile_card(_profile()))


def _jd_text(a) -> str:
    from candid import match as M
    if getattr(a, "app_id", None):
        meta = _job_meta_for(a.app_id)
        if meta.get("jd_text"):
            return meta["jd_text"]
        # fall through to --jd if the curated record has no stored JD
    src = a.jd
    if src == "-":
        src = sys.stdin.read()
    if not src:
        sys.exit("No JD available: pass --jd <file | url | ->, or curate the job "
                 "first so its description is stored.\n"
                 "Tip: pipe it in — `cat jd.txt | python -m candid match --jd -`.")
    return M.fetch_jd(src)


def _job_meta_for(app_id: int) -> dict:
    from candid import jobs as J
    from candid import tracker as T
    apps = T.list_apps()
    if not any(a["id"] == app_id for a in apps):
        sys.exit(f"No tracked application with id {app_id}. "
                 "Run `python -m candid track list` to see ids.")
    return J.get_job_meta(app_id)


def _company_role_from_app(a) -> tuple[str, str]:
    """Fill --company/--role from a tracker record when --app-id is given."""
    from candid import tracker as T
    company, role = a.company or "", a.role or ""
    if getattr(a, "app_id", None):
        rec = next((x for x in T.list_apps() if x["id"] == a.app_id), None)
        if rec is None:
            sys.exit(f"No tracked application with id {a.app_id}. "
                     "Run `python -m candid track list` to see ids.")
        company = company or rec["company"]
        role = role or rec["role"]
    return company, role


def cmd_match(a):
    from candid import match as M
    jd = _jd_text(a)
    company, role = _company_role_from_app(a)
    result = M.score_match(_profile(), jd, title=role, company=company,
                           location=a.location or "")
    if a.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(M.render_report(result, company=company, title=role))


def cmd_tailor(a):
    from candid import tailor as T
    jd = _jd_text(a)
    company, role = _company_role_from_app(a)
    prof = _profile()
    if a.what == "resume":
        out = T.build_resume(prof, jd, company=company, role=role,
                             tone=a.tone, length=a.length)
    else:
        if not company or not role:
            sys.exit("Cover letters need --company and --role (or --app-id of a tracked job).")
        out = T.build_cover_letter(prof, jd, company=company, role=role,
                                   tone=a.tone, hook=a.hook or "")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"Saved to {a.out}")
    else:
        print(out)


def cmd_track(a):
    from candid import tracker as T
    if a.what == "add":
        rec = T.add(a.company, a.role, jd_link=a.jd_link or "", status=a.status,
                    notes=a.notes or "")
        if rec.get("duplicate"):
            print(f"Already tracked as #{rec['id']}: {rec['role']} @ {rec['company']} "
                  f"[{rec['status']}] — not duplicated.")
        else:
            print(f"Added application #{rec['id']}: {rec['role']} @ {rec['company']} [{rec['status']}]")
    elif a.what == "list":
        apps = T.list_apps(status=a.status, company=a.company)
        if a.json:
            print(json.dumps(apps, indent=2, default=str))
            return
        limit = a.limit if a.limit and a.limit > 0 else 25
        shown = apps[:limit]
        print(f"{len(apps)} application(s) tracked"
              + (f" — showing first {limit} (use --limit N for more)"
                 if len(apps) > limit else ""))
        print(T.render_list(shown))
    elif a.what == "update":
        rec = T.update(a.id, status=a.status, notes=a.notes)
        print(f"Updated #{rec['id']}: status={rec['status']}")
        if rec["status"] == "selected_for_interview":
            print("\n🎯 Interview! Generate a prep pack with:")
            print(f"   python -m candid prep --company \"{rec['company']}\" "
                  f"--role \"{rec['role']}\" --app-id {rec['id']}")
    elif a.what == "remove":
        T.remove(a.id)
        print(f"Removed application #{a.id}.")
    elif a.what == "stats":
        print(T.render_stats(T.stats()))
    elif a.what == "search":
        results = T.search(a.query)
        if not results:
            print(f"No applications match {a.query!r}.")
        else:
            print(T.render_list(results))
    elif a.what == "export-csv":
        path = T.export_csv(a.dest)
        print(f"Exported {len(T.list_apps())} applications to {path}")


def cmd_prep(a):
    from candid import prep as P
    jd = _jd_text(a) if a.jd else ""
    markdown, path = P.build_pack(_profile(), a.company, a.role, jd=jd,
                                  app_id=a.app_id, location=a.location or "")
    print(f"Prep pack saved to {path}\n")
    print(markdown[:3000])
    if len(markdown) > 3000:
        print(f"\n... ({len(markdown) - 3000} more chars in the file)")


def cmd_followup(a):
    from candid import followup as F
    prof = _profile()
    name = prof.get("name") or "Your Name"
    if a.what == "thank-you":
        print(F.thank_you(name, a.person, a.role, a.company, topics=a.topics or "",
                          standout=a.standout or "", tone=a.tone))
    elif a.what == "check-in":
        print(F.check_in(name, a.person, a.role, a.company,
                         last_contact=a.last_contact or "", tone=a.tone))
    elif a.what == "referral":
        print(F.referral_ask(name, a.person, a.role, a.company, connection=a.topics or ""))


def cmd_offer(a):
    from candid import offer as O
    if a.what == "add":
        fields = {k: v for k, v in vars(a).items()
                  if k not in ("func", "what") and v is not None}
        rec = O.add(fields)
        print(f"Added offer #{rec['id']}: {rec['company']} — "
              f"normalized ${rec['normalized_annual']:,.0f}/yr")
    if a.what in ("list", "compare"):
        print(O.render_comparison(O.list_offers()))
    elif a.what == "export":
        path = O.export_comparison(O.list_offers(),
                                   path=a.out or None)
        print(f"Offer comparison exported to {path}")


def cmd_negotiate(a):
    from candid import negotiate as N
    if a.what == "playbook":
        print(N.render_playbook())
    elif a.what == "script":
        fields = dict(kv.split("=", 1) for kv in (a.set or []))
        print(N.get_script(a.which, **fields))
    elif a.what == "counter":
        prof = _profile()
        print(N.counter_email(name=prof.get("name") or "Your Name", recruiter=a.person,
                              role=a.role, company=a.company, location=a.location or "",
                              base_ask_reason=a.base_ask, second_item=a.second_item,
                              second_ask_reason=a.second_ask or "",
                              target_summary=a.target or "", call_time=a.call_time))


def cmd_salary(a):
    from candid import salary as S
    if a.what == "lookup":
        result = S.lookup(company=a.company or "", title=a.title or "",
                          location=a.location or "")
        if a.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(S.render_lookup(result, company=a.company or "",
                                  title=a.title or "", location=a.location or ""))
    elif a.what == "import-lca":
        print(f"Importing {a.file} ...")
        res = S.import_lca(a.file, limit=a.limit)
        print(f"Imported {res['imported']} rows, skipped {res['skipped']}.")
    elif a.what == "parse-range":
        if a.text:
            text = a.text
        elif a.jd:
            with open(a.jd, encoding="utf-8") as f:
                text = f.read()
        else:
            text = None
        if text is None:
            sys.exit("Provide --text or --jd.\n"
                     "Next: run `python -m candid salary parse-range --help`.")
        parsed = S.ingest_posted_range(a.company, a.role, text,
                                       location=a.location or "",
                                       source_detail=a.jd or "pasted")
        if parsed:
            print(f"Stored range: ${parsed['low']:,.0f}–${parsed['high']:,.0f}/yr")
        else:
            print("No pay range found in that text.")


def cmd_mock(a):
    from candid import mock as M
    if a.what == "list":
        problems = M.list_problems(topic=a.topic, difficulty=a.difficulty)
        if not problems:
            print("No problems match. Try without filters.")
            return
        print(f"{'ID':<20}{'Title':<46}{'Topic':<14}Difficulty")
        for p in problems:
            print(f"{p['id']:<20}{p['title'][:45]:<46}{p['topic']:<14}{p['difficulty']}")
    elif a.what == "coding":
        M.interactive_coding(topic=a.topic, difficulty=a.difficulty,
                             problem_id=a.problem, solution_file=a.file)
    elif a.what == "run":
        code = open(a.file, encoding="utf-8").read()
        result = M.run_problem(a.problem, code)
        print(M.render_verdict(a.problem, result))
        sys.exit(0 if result["verdict"] == "accepted" else 1)
    elif a.what == "solution":
        print(M.show_solution(a.problem))
    elif a.what == "hint":
        p = M.get_problem(a.problem)
        for i, h in enumerate(p.get("hints", []), 1):
            print(f"Hint {i}: {h}\n")
    elif a.what == "ai":
        M.ai_interview(track=a.track, topic=a.topic, difficulty=a.difficulty,
                       problem_id=a.problem)
    elif a.what == "behavioral":
        M.behavioral_session(theme=a.theme, ai_feedback=a.ai)
    elif a.what == "design":
        M.design_session(level=a.level, ai_feedback=a.ai)


def cmd_jobs(a):
    from candid import jobs as J
    from candid import tracker as T
    if a.what == "curate" or a.what == "refresh":
        if not a.role:
            sys.exit("--role is required (e.g. --role \"Data Scientist\").\n"
                     "Next: run `python -m candid jobs curate --help`.")
        fn = J.refresh if a.what == "refresh" else J.curate
        result = fn(_profile(), role=a.role, location=a.location or "",
                    remote=a.remote, level=a.level, limit=a.limit,
                    sources=a.sources or None,
                    days=getattr(a, "days", None),
                    min_score=getattr(a, "min_score", 0) or 0,
                    exclude_megacorps=getattr(a, "exclude_megacorps", False))
        print(J.render_curated(result))
    elif a.what == "list":
        if a.json:
            saved = []
            for app in T.list_apps(status="saved"):
                meta = J.get_job_meta(app["id"])
                saved.append({
                    "app_id": app["id"],
                    "company": app["company"],
                    "role": app["role"],
                    "score": meta.get("match_score"),
                    "source": meta.get("source"),
                    "url": meta.get("source_url") or app.get("jd_link") or "",
                    "date_added": app.get("date_added", ""),
                    "has_jd": bool(meta.get("jd_text")),
                })
            print(json.dumps(saved, indent=2, default=str))
        else:
            print(J.render_saved())
    elif a.what == "gems":
        _cmd_jobs_gems(a)
    elif a.what == "why-gem":
        _cmd_jobs_why_gem(a)


# ---------------------------------------------------------------------------
# hidden-gem detector (candid.gems) — CLI wiring only
# ---------------------------------------------------------------------------
#
# The scoring core lives in candid/gems.py (owned by another worker). This
# module talks to it through a defensive lookup so the CLI keeps working even
# if gems.py is momentarily incomplete: missing functions fall back to neutral
# stubs instead of crashing.

def _gems_module():
    """Import candid.gems lazily; None if the module is not importable yet.

    Checks sys.modules first so tests can inject a fake gems module without
    tripping over the ``candid.gems`` attribute set by an earlier real import.
    """
    import sys
    mod = sys.modules.get("candid.gems")
    if mod is not None:
        return mod
    try:
        from candid import gems as G
        return G
    except ImportError:
        return None


def _gem_score_fallback(job, profile=None, all_jobs=None):
    return {"gem_score": 0.0, "fit_score": 0.0, "signals": {},
            "reasons": [], "sleeper": False, "megacorp": False}


def _top_gems_fallback(jobs, profile=None, limit=15, exclude_megacorps=False,
                       min_fit=0.0):
    return [{**j, "_gem": _gem_score_fallback(j, profile)} for j in jobs[:limit]]


def _employer_ranking_fallback(jobs):
    return []


def _gem_fn(name, fallback):
    G = _gems_module()
    return getattr(G, name, fallback) if G is not None else fallback


_SIGNAL_EXPLANATIONS = {
    # real signals from candid.gems
    "freshness": "Posting recency — newer postings tend to have less applicant pile-up.",
    "repost_rarity": "Whether the job is reposted across many sources — less reposting means less competition.",
    "company_volume": "The employer's posting volume — lower volume can mean a more focused hire.",
    "source_niche": "How niche the job board/source is — niche sources draw fewer applicants.",
    "salary_opacity": "Pay disclosure in the posting — transparent pay usually signals a serious, funded role.",
    "remote_pool": "Remote-friendliness — remote roles draw wider applicant pools, which the score accounts for.",
    # generic names the scoring core may also use
    "applicant_ratio": "Estimated applicants per opening — lower means less competition.",
    "posting_velocity": "How fast the employer is posting new roles — faster can mean a hiring surge.",
    "salary_transparency": "Whether the posting discloses pay — transparent pay usually signals a serious, funded role.",
    "growth_hiring": "Headcount growth signals (funding, expansion) behind the posting.",
    "obscure_employer": "How under-the-radar the employer is — lesser-known names get fewer applicants.",
    "remote": "Remote-friendly roles draw wider pools; the gem score accounts for that.",
    "recency": "How fresh the posting is — newer postings have less pile-up.",
    "fit": "How well the role matches your profile (skills, seniority, title).",
}


def _curated_jobs() -> list:
    """Rebuild the curated job pool from tracker (status=saved) + jobs state.

    No network calls — everything comes from locally stored curation data.
    """
    from candid import jobs as J
    from candid import tracker as T
    state = J._load_state()
    seen = state.get("seen") or {}
    sid_by_app = {v: k for k, v in seen.items()}
    out = []
    for app in T.list_apps(status="saved"):
        meta = J.get_job_meta(app["id"])
        desc = meta.get("jd_text") or ""
        out.append({
            "title": app.get("role", ""),
            "company": app.get("company", ""),
            "description": desc,
            "location": app.get("location", "") or "",
            "url": meta.get("source_url") or app.get("jd_link") or "",
            "source": meta.get("source", "") or "",
            "source_id": sid_by_app.get(app["id"], "") or "",
            "match_score": meta.get("match_score", 0) or 0,
            "app_id": app["id"],
            "remote": ("remote" in (app.get("location", "") or "").lower()
                       or "remote" in desc.lower()),
        })
    return out


def _filter_gem_pool(jobs: list, role: str, location: str, remote: bool) -> list:
    out = []
    for j in jobs:
        if role and role.lower() not in (j.get("title") or "").lower():
            continue
        if location:
            loc = j.get("location") or ""
            if loc and location.lower() not in loc.lower():
                continue
            # jobs without stored location pass the filter (can't disprove)
        if remote and not (j.get("remote") or
                           "remote" in (j.get("location") or "").lower()):
            continue
        out.append(j)
    return out


def _profile_or_none():
    """Load the user profile; None (with a hint) when onboarding is missing."""
    from candid import profile as P
    try:
        return P.load_profile()
    except Exception:
        return None


def _gem_json(job: dict) -> dict:
    gem = job.get("_gem") or {}
    return {
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "url": job.get("url", ""),
        "source": job.get("source", ""),
        "source_id": job.get("source_id", ""),
        "match_score": job.get("match_score", 0),
        "gem_score": gem.get("gem_score", 0),
        "fit_score": gem.get("fit_score", 0),
        "sleeper": bool(gem.get("sleeper")),
        "megacorp": bool(gem.get("megacorp")),
        "signals": gem.get("signals") or {},
        "reasons": gem.get("reasons") or [],
    }


def _fmt_score(v) -> str:
    """Format a score that may legitimately be None (e.g. fit without profile)."""
    return f"{v:.0f}" if isinstance(v, (int, float)) else "—"


def _render_gems(gems: list) -> str:
    lines = [f"{'#':<3}{'Gem':<6}{'Fit':<6}{'Company':<24}{'Title':<32}Why it's a gem"]
    for i, job in enumerate(gems, 1):
        gem = job.get("_gem") or {}
        reasons = gem.get("reasons") or []
        why = "; ".join(str(r) for r in reasons[:2]) or "—"
        flag = " [sleeper]" if gem.get("sleeper") else ""
        if gem.get("megacorp"):
            flag += " [megacorp]"
        lines.append(f"{i:<3}{_fmt_score(gem.get('gem_score')):<6}"
                     f"{_fmt_score(gem.get('fit_score')):<6}"
                     f"{str(job.get('company', ''))[:23]:<24}"
                     f"{str(job.get('title', ''))[:31]:<32}"
                     f"{why[:60]}{flag}")
    return "\n".join(lines)


def _cmd_jobs_gems(a):
    pool = _curated_jobs()
    if not pool:
        print("No curated jobs yet — there is nothing to rank.\n"
              "Next: run `python -m candid jobs curate --role \"Your Title\"` "
              "to build your curated pipeline first.")
        return
    pool = _filter_gem_pool(pool, a.role or "", a.location or "", a.remote)
    if not pool:
        print("No curated jobs match those filters.\n"
              "Next: loosen --role / --location / --remote and run "
              "`python -m candid jobs gems` again.")
        return
    profile = _profile_or_none()
    if profile is None:
        note = ("Note: no profile found — gem scoring runs without fit personalization.\n"
                "      Run `python -m candid onboard --resume your_resume.pdf` to personalize.")
        if a.json:
            sys.stderr.write(note + "\n")  # keep stdout pure JSON
        else:
            print(note + "\n")
    top_gems = _gem_fn("top_gems", _top_gems_fallback)
    gems = top_gems(pool, profile=profile, limit=a.limit,
                    exclude_megacorps=a.no_megacorps,
                    min_fit=a.min_fit or 0.0)
    if not gems:
        if a.json:
            print("[]")
            return
        print("No hidden gems in this pool right now.\n"
              "Next: lower --min-fit, drop --no-megacorps, or curate more jobs.")
        return
    if a.json:
        print(json.dumps([_gem_json(g) for g in gems], indent=2, default=str))
        return
    print(_render_gems(gems))


def _render_why(job: dict, gem: dict) -> str:
    lines = [
        f"Why \"{job.get('title', '')}\" at {job.get('company', '')} is a hidden gem",
        f"Gem score: {_fmt_score(gem.get('gem_score'))}/100"
        f"   Fit: {_fmt_score(gem.get('fit_score'))}/100"
        f"   Sleeper: {'yes' if gem.get('sleeper') else 'no'}"
        f"   Megacorp: {'yes' if gem.get('megacorp') else 'no'}",
        "",
        "Signals:",
    ]
    signals = gem.get("signals") or {}
    if isinstance(signals, dict):
        items = signals.items()
    elif isinstance(signals, (list, tuple)):
        items = ((s.get("name", "?"), s.get("value", "?")) if isinstance(s, dict)
                 else (str(s), "") for s in signals)
    else:
        items = ()
    any_sig = False
    for name, value in items:
        any_sig = True
        expl = _SIGNAL_EXPLANATIONS.get(str(name),
                                        "Signal contribution to the gem score.")
        lines.append(f"  {name:<20}{value}\n      {expl}")
    if not any_sig:
        lines.append("  (no signal detail available)")
    reasons = gem.get("reasons") or []
    lines.append("")
    lines.append("Why this is a gem:")
    if reasons:
        for r in reasons:
            lines.append(f"  - {r}")
    else:
        lines.append("  (no reasons recorded)")
    if job.get("url"):
        lines.append("")
        lines.append(f"Apply: {job['url']}")
    return "\n".join(lines)


def _cmd_jobs_why_gem(a):
    pool = _curated_jobs()
    if not pool:
        print("No curated jobs yet — there is nothing to explain.\n"
              "Next: run `python -m candid jobs curate --role \"Your Title\"` first.")
        return
    target = (a.target or "").strip()
    job = None
    if target.isdigit():
        idx = int(target)
        if 1 <= idx <= len(pool):
            job = pool[idx - 1]
    else:
        tl = target.lower()
        for j in pool:
            if (j.get("source_id") or "").lower() == tl:
                job = j
                break
    if job is None:
        sys.exit(f"No curated job {target!r}: the curated pool has "
                 f"{len(pool)} job(s).\n"
                 "Next: run `python -m candid jobs list` for the 1-based index, "
                 "or `python -m candid jobs gems` for the ranking.")
    profile = _profile_or_none()
    gem_score = _gem_fn("gem_score", _gem_score_fallback)
    gem = gem_score(job, profile=profile, all_jobs=pool)
    if a.json:
        print(json.dumps({"job": {"title": job.get("title", ""),
                                  "company": job.get("company", ""),
                                  "location": job.get("location", ""),
                                  "url": job.get("url", ""),
                                  "source": job.get("source", ""),
                                  "source_id": job.get("source_id", ""),
                                  "match_score": job.get("match_score", 0)},
                          "gem": gem}, indent=2, default=str))
        return
    print(_render_why(job, gem))


def _render_employers(ranking: list) -> str:
    lines = [f"{'#':<3}{'Employer':<26}{'Postings':<10}{'Obscurity':<11}"
             f"{'Median $':<12}{'Velocity':<10}Gem score"]
    for i, e in enumerate(ranking, 1):
        med = e.get("median_salary_usd")
        med_s = f"${med:,.0f}" if isinstance(med, (int, float)) and med else "—"
        lines.append(f"{i:<3}{str(e.get('company', ''))[:25]:<26}"
                     f"{e.get('postings', 0):<10}"
                     f"{e.get('obscurity', 0):<11.2f}"
                     f"{med_s:<12}"
                     f"{str(e.get('velocity', ''))[:9]:<10}"
                     f"{e.get('gem_employer_score', 0):.0f}")
    return "\n".join(lines)


def cmd_gems(a):
    pool = _curated_jobs()
    if not pool:
        print("No curated jobs yet — there is nothing to rank.\n"
              "Next: run `python -m candid jobs curate --role \"Your Title\"` "
              "to build your curated pipeline first.")
        return
    employer_ranking = _gem_fn("employer_ranking", _employer_ranking_fallback)
    ranking = employer_ranking(pool) or []
    ranking = ranking[:a.limit or 15]
    if not ranking:
        print("Not enough employer signal in the curated pool to rank anyone yet.\n"
              "Next: curate more jobs with `python -m candid jobs curate --role \"Your Title\"`.")
        return
    if a.json:
        print(json.dumps(ranking, indent=2, default=str))
        return
    print(_render_employers(ranking))


def cmd_dashboard(a):
    from candid import dashboard as D
    D.serve(port=a.port, open_browser=not a.no_browser)


def cmd_import(a):
    """General entry point: import user-supplied exports.

    Pattern for new sources: add a module under candid/ that parses the
    export and proposes changes, then wire it here and in the dashboard's
    "Import your data" section.
    """
    if a.gmail_takeout:
        from candid import gmail as G
        res = G.import_mbox(a.gmail_takeout, max_messages=a.max)
        print(G.render_import_summary(res))
    elif a.linkedin_zip:
        from candid import linkedin as L
        res = L.import_zip(a.linkedin_zip, mode=a.mode)
        prof = res["profile"]
        print(f"✅ LinkedIn import ({res['mode']}): {res['positions']} positions, "
              f"{res['skills']} skills, {res['education']} education entries.")
        print(f"Profile now: {prof.get('name', '')} — {prof.get('headline', '')} "
              f"({prof.get('seniority')}, ~{prof.get('years_experience')} yrs)")
    else:
        raise ValueError("Nothing to import. Use --gmail-takeout FILE.mbox "
                         "or --linkedin-zip FILE.zip")


def cmd_gmail(a):
    from candid import gmail as G
    if a.what == "import":
        res = G.import_mbox(a.file, max_messages=a.max)
        print(G.render_import_summary(res))
    elif a.what == "proposals":
        print(G.render_proposals(G.list_proposals(status="pending")))
    elif a.what == "confirm":
        rec = G.confirm_proposal(a.id)
        print(f"\u2705 Confirmed \u2192 tracker #{rec['id']}: {rec['role']} @ {rec['company']} [{rec['status']}]")
    elif a.what == "reject":
        G.reject_proposal(a.id)
        print(f"Dismissed proposal #{a.id}.")
    elif a.what == "guide":
        print(G.TAKEOUT_GUIDE)


def cmd_linkedin(a):
    from candid import linkedin as L
    if a.what == "guide":
        print(L.EXPORT_GUIDE)
    elif a.what == "import":
        res = L.import_zip(a.zip, mode=a.mode)
        prof = res["profile"]
        print(f"✅ LinkedIn import ({res['mode']}): {res['positions']} positions, "
              f"{res['skills']} skills, {res['education']} education entries.")
        print(f"Profile now: {prof.get('name', '')} — {prof.get('headline', '')} "
              f"({prof.get('seniority')}, ~{prof.get('years_experience')} yrs)")


def build_parser() -> argparse.ArgumentParser:
    p = CandidParser(prog="python -m candid",
                     description="The generic job-search copilot.",
                     formatter_class=argparse.RawDescriptionHelpFormatter,
                     epilog=_examples(
                         "python -m candid onboard --resume resume.pdf",
                         "python -m candid match --jd jd.txt --company Acme --role \"Data Scientist\"",
                         "python -m candid jobs curate --role \"Data Scientist\" --remote",
                         "python -m candid dashboard",
                     ))
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}",
                   help="Show the candid version and exit.")
    sub = p.add_subparsers(dest="cmd", required=True,
                           title="commands", metavar="<command>",
                           parser_class=CandidParser)

    # onboard
    s = _sub(sub, "onboard", "Ingest resume/LinkedIn into your profile.", [
        "python -m candid onboard --resume resume.pdf",
        "python -m candid onboard --resume resume.pdf --linkedin linkedin.txt",
        "python -m candid onboard --resume resume.md --out /tmp/profile.json",
    ])
    s.add_argument("--resume", help="Resume file (.pdf/.md/.txt)")
    s.add_argument("--linkedin", help="LinkedIn export file (.txt/.md)")
    s.add_argument("--out", help="Where to write profile.json (default: candid_data/)")
    s.set_defaults(func=cmd_onboard)

    # profile
    s = _sub(sub, "profile", "Show your stored profile.", [
        "python -m candid profile",
        "python -m candid profile show",
    ])
    s.add_argument("what", nargs="?", default="show", choices=["show"])
    s.set_defaults(func=cmd_profile_show)

    # match
    s = _sub(sub, "match", "Score a job description against your profile.", [
        "python -m candid match --jd jd.txt --company Acme --role \"Data Scientist\"",
        "cat jd.txt | python -m candid match --jd - --company Acme",
        "python -m candid match --app-id 3",
        "python -m candid match --jd jd.txt --json   # machine-readable output",
    ])
    s.add_argument("--jd", default="", help=JD_HELP)
    s.add_argument("--app-id", type=int, default=None,
                   help="Tracked job id — pulls company/role/JD from the tracker")
    s.add_argument("--company", default="", help="Company name")
    s.add_argument("--role", default="", help="Role title")
    s.add_argument("--location", default="", help="Location")
    s.add_argument("--json", action="store_true",
                   help="Print the raw match result as JSON (for scripting)")
    s.set_defaults(func=cmd_match)

    # tailor
    s = _sub(sub, "tailor", "Tailored resume / cover letter.", [
        "python -m candid tailor resume --jd jd.txt --company Acme --role \"Data Scientist\"",
        "python -m candid tailor cover-letter --app-id 3 --hook \"I loved your infra blog\"",
        "python -m candid tailor resume --jd jd.txt --out tailored-acme.md",
    ])
    s.add_argument("what", choices=["resume", "cover-letter"],
                   help="resume: tailored resume · cover-letter: tailored cover letter")
    s.add_argument("--jd", default="", help=JD_HELP)
    s.add_argument("--app-id", type=int, default=None,
                   help="Tracked job id — pulls company/role/JD from the tracker")
    s.add_argument("--company", default="")
    s.add_argument("--role", default="")
    s.add_argument("--tone", default="confident", choices=["concise", "confident", "formal", "warm"])
    s.add_argument("--length", default="one-page", choices=["one-page", "detailed"])
    s.add_argument("--hook", default="", help="One-line 'why this company' for cover letters")
    s.add_argument("--out", help="Write to file instead of stdout")
    s.set_defaults(func=cmd_tailor)

    # track
    s = _sub(sub, "track", "Application tracker.", [
        "python -m candid track add --company Acme --role \"Data Scientist\" --status applied",
        "python -m candid track list",
        "python -m candid track update 3 --status selected_for_interview",
        "python -m candid track stats",
    ])
    ts = _nested(s)
    t = _sub(ts, "add", "Add an application to the tracker.", [
        "python -m candid track add --company Acme --role \"Data Scientist\"",
        "python -m candid track add --company Acme --role \"Data Scientist\" --status applied --notes \"referral from Sam\"",
    ])
    t.add_argument("--company", required=True); t.add_argument("--role", required=True)
    t.add_argument("--jd-link", default=""); t.add_argument("--status", default="saved")
    t.add_argument("--notes", default="")
    t = _sub(ts, "list", "List tracked applications (default view: newest first, up to --limit).", [
        "python -m candid track list",
        "python -m candid track list --status applied",
        "python -m candid track list --company Acme --json",
    ])
    t.add_argument("--status", default=None); t.add_argument("--company", default=None)
    t.add_argument("--limit", type=int, default=25,
                   help="Max rows in the default view (default: 25)")
    t.add_argument("--json", action="store_true",
                   help="Print the application list as JSON (for scripting)")
    t = _sub(ts, "update", "Update an application's status or notes.", [
        "python -m candid track update 3 --status applied",
        "python -m candid track update 3 --status selected_for_interview",
        "python -m candid track update 3 --notes \"met hiring manager at meetup\"",
    ])
    t.add_argument("id", type=int)
    t.add_argument("--status", default=None); t.add_argument("--notes", default=None)
    t = _sub(ts, "remove", "Remove an application.", [
        "python -m candid track remove 3",
    ])
    t.add_argument("id", type=int)
    t = _sub(ts, "stats", "Funnel stats and rates.", [
        "python -m candid track stats",
    ])
    t = _sub(ts, "search", "Free-text search over company/role/notes.", [
        "python -m candid track search acme",
        "python -m candid track search \"machine learning\"",
    ])
    t.add_argument("query", help="Search text (matches company, role, notes)")
    t = _sub(ts, "export-csv", "Export the tracker to CSV.", [
        "python -m candid track export-csv tracker.csv",
    ])
    t.add_argument("dest", help="Destination CSV file path")
    s.set_defaults(func=cmd_track)

    # prep
    s = _sub(sub, "prep", "Build an interview prep pack.", [
        "python -m candid prep --company Acme --role \"Data Scientist\"",
        "python -m candid prep --company Acme --role \"Data Scientist\" --jd jd.txt",
        "python -m candid prep --company Acme --role \"Data Scientist\" --app-id 3",
    ])
    s.add_argument("--company", required=True)
    s.add_argument("--role", required=True)
    s.add_argument("--jd", default="", help=JD_HELP)
    s.add_argument("--location", default="")
    s.add_argument("--app-id", type=int, default=None, help="Tracker id to link the pack to")
    s.set_defaults(func=cmd_prep)

    # followup
    s = _sub(sub, "followup", "Draft thank-you / check-in / referral emails.", [
        "python -m candid followup thank-you --person \"Jane Doe\" --role \"Data Scientist\" --company Acme",
        "python -m candid followup check-in --person \"Jane Doe\" --role \"Data Scientist\" --company Acme",
        "python -m candid followup referral --person Sam --role \"Data Scientist\" --company Acme",
    ])
    fs = _nested(s)
    t = _sub(fs, "thank-you", "Draft a post-interview thank-you email.", [
        "python -m candid followup thank-you --person \"Jane Doe\" --role \"Data Scientist\" --company Acme",
        "python -m candid followup thank-you --person \"Jane\" --role DS --company Acme --topics \"team culture\" --standout \"my churn model\"",
    ])
    t.add_argument("--person", required=True, help="Interviewer / recruiter / contact name")
    t.add_argument("--role", required=True); t.add_argument("--company", required=True)
    t.add_argument("--tone", default="warm", choices=["warm", "formal", "concise"])
    t.add_argument("--topics", default=""); t.add_argument("--standout", default="")
    t = _sub(fs, "check-in", "Draft a check-in email after applying.", [
        "python -m candid followup check-in --person \"Jane Doe\" --role \"Data Scientist\" --company Acme",
        "python -m candid followup check-in --person \"Jane\" --role DS --company Acme --last-contact \"2026-09-01\"",
    ])
    t.add_argument("--person", required=True, help="Interviewer / recruiter / contact name")
    t.add_argument("--role", required=True); t.add_argument("--company", required=True)
    t.add_argument("--tone", default="warm", choices=["warm", "formal", "concise"])
    t.add_argument("--last-contact", default="")
    t = _sub(fs, "referral", "Draft a referral request.", [
        "python -m candid followup referral --person Sam --role \"Data Scientist\" --company Acme",
    ])
    t.add_argument("--person", required=True, help="Interviewer / recruiter / contact name")
    t.add_argument("--role", required=True); t.add_argument("--company", required=True)
    t.add_argument("--tone", default="warm", choices=["warm", "formal", "concise"])
    t.add_argument("--topics", default="", help="Your connection to them")
    s.set_defaults(func=cmd_followup)

    # offer
    s = _sub(sub, "offer", "Record and compare offers.", [
        "python -m candid offer add --company Acme --role \"Data Scientist\" --base 180000 --equity 200000",
        "python -m candid offer list",
        "python -m candid offer compare",
        "python -m candid offer export --out offers.md",
    ])
    os_ = _nested(s)
    t = _sub(os_, "add", "Record an offer.", [
        "python -m candid offer add --company Acme --role \"Data Scientist\" --base 180000",
        "python -m candid offer add --company Acme --role DS --base 180000 --bonus-pct 15 --equity 200000 --location \"New York\"",
    ])
    t.add_argument("--company", required=True); t.add_argument("--role", required=True)
    t.add_argument("--level", default=""); t.add_argument("--location", default="")
    t.add_argument("--base", type=float, default=0)
    t.add_argument("--bonus-pct", dest="bonus_target_pct", type=float, default=0)
    t.add_argument("--bonus-first", dest="bonus_first_year_guaranteed", type=float, default=0)
    t.add_argument("--equity", dest="equity_total", type=float, default=0)
    t.add_argument("--equity-type", dest="equity_type", default="rsu")
    t.add_argument("--vest-years", dest="vest_years", type=int, default=4)
    t.add_argument("--vest-schedule", dest="vest_schedule", default="")
    t.add_argument("--benefits", dest="benefits_value", type=float, default=0)
    t.add_argument("--sign-on", dest="sign_on", type=float, default=0,
                   help="One-time sign-on bonus $ (amortized over 2 yrs in comparisons)")
    t.add_argument("--start", dest="start_date", default=""); t.add_argument("--notes", default="")
    _sub(os_, "list", "List recorded offers.", [
        "python -m candid offer list",
    ])
    _sub(os_, "compare", "Compare offers side by side.", [
        "python -m candid offer compare",
    ])
    t = _sub(os_, "export", "Export the offer comparison as markdown.", [
        "python -m candid offer export",
        "python -m candid offer export --out offers.md",
    ])
    t.add_argument("--out", default="", help="Output path (default: candid_data/offer_comparisons/<date>_offer_comparison.md)")
    s.set_defaults(func=cmd_offer)

    # negotiate
    s = _sub(sub, "negotiate", "Negotiation playbook, scripts, counter drafts.", [
        "python -m candid negotiate playbook",
        "python -m candid negotiate script --which competing_offer --set company=Acme",
        "python -m candid negotiate counter --person Jane --role \"Data Scientist\" --company Acme --base-ask \"190k base\"",
    ])
    ns = _nested(s)
    _sub(ns, "playbook", "Show the negotiation playbook.", [
        "python -m candid negotiate playbook",
    ])
    t = _sub(ns, "script", "Get a script for a specific scenario.", [
        "python -m candid negotiate script --which lowball_anchor",
        "python -m candid negotiate script --which competing_offer --set company=Acme --set number=190000",
    ])
    t.add_argument("--which", required=True,
        choices=["lowball_anchor", "competing_offer", "exploding_deadline",
                 "level_pushback", "leveling_up_push", "remote_flexibility"])
    t.add_argument("--set", action="append", default=[], help="key=value template fields")
    t = _sub(ns, "counter", "Draft a counter-offer email.", [
        "python -m candid negotiate counter --person Jane --role \"Data Scientist\" --company Acme --base-ask \"190k base\"",
    ])
    t.add_argument("--person", required=True); t.add_argument("--role", required=True)
    t.add_argument("--company", required=True); t.add_argument("--location", default="")
    t.add_argument("--base-ask", required=True); t.add_argument("--second-item", default="Sign-on bonus")
    t.add_argument("--second-ask", default=""); t.add_argument("--target", default="")
    t.add_argument("--call-time", default="tomorrow")
    s.set_defaults(func=cmd_negotiate)

    # salary
    s = _sub(sub, "salary", "Salary intelligence database.", [
        "python -m candid salary lookup --company Acme --title \"Data Scientist\"",
        "python -m candid salary import-lca dol_h1b.csv --limit 5000",
        "python -m candid salary parse-range --company Acme --role \"Data Scientist\" --jd jd.txt",
    ])
    ss = _nested(s)
    t = _sub(ss, "lookup", "Look up pay ranges for a company/title.", [
        "python -m candid salary lookup --company Acme --title \"Data Scientist\"",
        "python -m candid salary lookup --company Acme --title \"Data Scientist\" --location \"New York\"",
        "python -m candid salary lookup --company Acme --title \"Data Scientist\" --json",
    ])
    t.add_argument("--company", default=""); t.add_argument("--title", default="")
    t.add_argument("--location", default="")
    t.add_argument("--json", action="store_true",
                   help="Print the raw lookup result as JSON (for scripting)")
    t = _sub(ss, "import-lca", "Import DOL H-1B LCA disclosure data.", [
        "python -m candid salary import-lca dol_h1b.csv",
        "python -m candid salary import-lca dol_h1b.csv --limit 5000",
    ])
    t.add_argument("file"); t.add_argument("--limit", type=int, default=None)
    t = _sub(ss, "parse-range", "Extract and store a pay range from JD text.", [
        "python -m candid salary parse-range --company Acme --role \"Data Scientist\" --jd jd.txt",
        "python -m candid salary parse-range --company Acme --role DS --text \"Pay range $120k-$150k\"",
    ])
    t.add_argument("--company", required=True); t.add_argument("--role", required=True)
    t.add_argument("--jd", default=""); t.add_argument("--text", default="")
    t.add_argument("--location", default="")
    s.set_defaults(func=cmd_salary)

    # mock
    s = _sub(sub, "mock", "Mock interviews: coding judge, AI interviewer, behavioral, design.", [
        "python -m candid mock list --topic arrays",
        "python -m candid mock coding --difficulty medium",
        "python -m candid mock run --problem two-sum --file sol.py",
        "python -m candid mock behavioral --theme leadership",
    ])
    ms = _nested(s)
    t = _sub(ms, "list", "List coding problems.", [
        "python -m candid mock list",
        "python -m candid mock list --topic arrays --difficulty easy",
    ])
    t.add_argument("--topic", default=None); t.add_argument("--difficulty", default=None)
    t = _sub(ms, "coding", "Interactive coding session.", [
        "python -m candid mock coding",
        "python -m candid mock coding --topic arrays --difficulty medium",
    ])
    t.add_argument("--topic", default=None); t.add_argument("--difficulty", default=None)
    t.add_argument("--problem", default=None); t.add_argument("--file", default=None)
    t = _sub(ms, "run", "Judge a solution file non-interactively.", [
        "python -m candid mock run --problem two-sum --file sol.py",
    ])
    t.add_argument("--problem", required=True); t.add_argument("--file", required=True)
    t = _sub(ms, "solution", "Show reference solution + complexity.", [
        "python -m candid mock solution --problem two-sum",
    ])
    t.add_argument("--problem", required=True)
    t = _sub(ms, "hint", "Show hints for a problem.", [
        "python -m candid mock hint --problem two-sum",
    ])
    t.add_argument("--problem", required=True)
    t = _sub(ms, "ai", "Conversational AI interviewer (uses Gemini).", [
        "python -m candid mock ai --track coding",
        "python -m candid mock ai --track behavioral",
    ])
    t.add_argument("--track", default="coding", choices=["coding", "behavioral", "ml"])
    t.add_argument("--topic", default=None); t.add_argument("--difficulty", default=None)
    t.add_argument("--problem", default=None)
    t = _sub(ms, "behavioral", "STAR behavioral practice.", [
        "python -m candid mock behavioral",
        "python -m candid mock behavioral --theme leadership --ai",
    ])
    t.add_argument("--theme", default=None); t.add_argument("--ai", action="store_true")
    t = _sub(ms, "design", "System design practice.", [
        "python -m candid mock design",
        "python -m candid mock design --level senior --ai",
    ])
    t.add_argument("--level", default=None); t.add_argument("--ai", action="store_true")
    s.set_defaults(func=cmd_mock)

    # jobs
    s = _sub(sub, "jobs", "Curate open jobs and feed the tracker.", [
        "python -m candid jobs curate --role \"Data Scientist\" --location \"New York\" --remote",
        "python -m candid jobs refresh --role \"ML Engineer\" --limit 10",
        "python -m candid jobs list",
        "python -m candid jobs gems --no-megacorps",
    ])
    js = _nested(s)
    t = _sub(js, "curate", "Discover jobs, score them, save the best as 'saved'.", [
        "python -m candid jobs curate --role \"Data Scientist\" --remote",
        "python -m candid jobs curate --role \"Data Scientist\" --location \"New York\" --level senior --limit 10",
        "python -m candid jobs curate --role \"Data Scientist\" --sources arbeitnow",
    ])
    t.add_argument("--role", required=True, help="Wanted title, e.g. \"Data Scientist\"")
    t.add_argument("--location", default="")
    t.add_argument("--remote", action="store_true")
    t.add_argument("--level", default=None, help="entry|junior|mid|senior|lead|staff|principal")
    t.add_argument("--limit", type=int, default=15)
    t.add_argument("--sources", nargs="*", default=None, help="subset of: arbeitnow remoteok")
    t.add_argument("--days", type=int, default=None,
                   help="Only postings from the last N days (unparseable dates are kept)")
    t.add_argument("--min-score", type=float, default=0,
                   help="Only save to tracker when match score >= N (default 0 = off)")
    t.add_argument("--exclude-megacorps", action="store_true",
                   help="Drop megacorp/high-volume employers from curation")
    t = _sub(js, "refresh", "Re-run curation; report only new jobs.", [
        "python -m candid jobs refresh --role \"Data Scientist\"",
        "python -m candid jobs refresh --role \"ML Engineer\" --remote --limit 10",
    ])
    t.add_argument("--role", required=True)
    t.add_argument("--location", default="")
    t.add_argument("--remote", action="store_true")
    t.add_argument("--level", default=None)
    t.add_argument("--limit", type=int, default=15)
    t.add_argument("--sources", nargs="*", default=None)
    t.add_argument("--days", type=int, default=None,
                   help="Only postings from the last N days (unparseable dates are kept)")
    t.add_argument("--min-score", type=float, default=0,
                   help="Only save to tracker when match score >= N (default 0 = off)")
    t.add_argument("--exclude-megacorps", action="store_true",
                   help="Drop megacorp/high-volume employers from curation")
    t = _sub(js, "list", "Show the curated pipeline (status=saved).", [
        "python -m candid jobs list",
        "python -m candid jobs list --json   # machine-readable output",
    ])
    t.add_argument("--json", action="store_true",
                   help="Print the curated job list as JSON (for scripting)")
    t = _sub(js, "gems", "Rank curated jobs as hidden gems (high fit, low competition).", [
        "python -m candid jobs gems",
        "python -m candid jobs gems --role \"ML Engineer\" --remote --limit 10",
        "python -m candid jobs gems --no-megacorps --min-fit 50 --json",
    ])
    t.add_argument("--role", default="",
                   help="Only rank jobs whose title contains this (case-insensitive)")
    t.add_argument("--location", default="",
                   help="Only rank jobs matching this location (case-insensitive)")
    t.add_argument("--remote", action="store_true",
                   help="Only rank remote-friendly jobs")
    t.add_argument("--limit", type=int, default=15,
                   help="Max gems to show (default 15)")
    t.add_argument("--no-megacorps", action="store_true",
                   help="Exclude megacorp employers from the ranking")
    t.add_argument("--min-fit", type=float, default=0.0,
                   help="Only rank jobs with fit score >= N (default 0 = off)")
    t.add_argument("--json", action="store_true",
                   help="Print the gem ranking as JSON (for scripting)")
    t = _sub(js, "why-gem", "Explain the gem signals for one curated job.", [
        "python -m candid jobs why-gem 1",
        "python -m candid jobs why-gem arbeitnow-12345 --json",
    ])
    t.add_argument("target",
                   help="1-based index into the curated list (see `jobs list` order) "
                        "or the job's source-id")
    t.add_argument("--json", action="store_true",
                   help="Print the signal breakdown as JSON (for scripting)")
    s.set_defaults(func=cmd_jobs)

    # gems
    s = _sub(sub, "gems", "Under-the-radar employer rankings from your curated jobs.", [
        "python -m candid gems employers",
        "python -m candid gems employers --limit 10",
        "python -m candid gems employers --json   # machine-readable output",
    ])
    gs = _nested(s)
    t = _sub(gs, "employers", "Rank under-the-radar employers in your curated pool.", [
        "python -m candid gems employers",
        "python -m candid gems employers --limit 10 --json",
    ])
    t.add_argument("--limit", type=int, default=15,
                   help="Max employers to show (default 15)")
    t.add_argument("--json", action="store_true",
                   help="Print the employer ranking as JSON (for scripting)")
    s.set_defaults(func=cmd_gems)

    # dashboard
    s = _sub(sub, "dashboard", "Launch the local web dashboard (127.0.0.1 only).", [
        "python -m candid dashboard",
        "python -m candid dashboard --port 8888",
        "python -m candid dashboard --no-browser",
    ])
    s.add_argument("--port", type=int, default=8765, help="Preferred port (tries the next 10 if busy)")
    s.add_argument("--no-browser", action="store_true", help="Don't auto-open the browser")
    s.set_defaults(func=cmd_dashboard)

    # import (general entry point for user-supplied exports)
    s = _sub(sub, "import", "Import your own data exports (mbox, LinkedIn ZIP, ...).", [
        "python -m candid import --gmail-takeout mail.mbox",
        "python -m candid import --linkedin-zip LinkedIn-export.zip",
        "python -m candid import --gmail-takeout mail.mbox --max 500",
    ])
    s.add_argument("--gmail-takeout", metavar="FILE.mbox",
                   help="Google Takeout mbox file (or directory of .mbox files)")
    s.add_argument("--linkedin-zip", metavar="FILE.zip",
                   help="LinkedIn official data-export archive")
    s.add_argument("--mode", default="merge", choices=["merge", "replace"],
                   help="LinkedIn import mode (default: merge)")
    s.add_argument("--max", type=int, default=0,
                   help="Max mbox messages to read (0 = all)")
    s.set_defaults(func=cmd_import)

    # gmail
    s = _sub(sub, "gmail", "Gmail Takeout mbox import: parse, propose, confirm.", [
        "python -m candid gmail import mail.mbox",
        "python -m candid gmail proposals",
        "python -m candid gmail confirm 1",
        "python -m candid gmail reject 2",
        "python -m candid gmail guide",
    ])
    gs = _nested(s)
    t = _sub(gs, "import", "Import a Google Takeout .mbox file (or directory of them).", [
        "python -m candid gmail import mail.mbox",
        "python -m candid gmail import takeout-mail/ --max 1000",
    ])
    t.add_argument("file", help="Path to the .mbox file or a directory of .mbox files")
    t.add_argument("--max", type=int, default=0, help="Max messages to read (0 = all)")
    t = _sub(gs, "proposals", "List pending Gmail proposals.", [
        "python -m candid gmail proposals",
    ])
    t = _sub(gs, "confirm", "Confirm a proposal -> writes to the tracker.", [
        "python -m candid gmail confirm 1",
    ])
    t.add_argument("id", type=int)
    t = _sub(gs, "reject", "Dismiss a proposal.", [
        "python -m candid gmail reject 2",
    ])
    t.add_argument("id", type=int)
    t = _sub(gs, "guide", "How to export Gmail via Google Takeout.", [
        "python -m candid gmail guide",
    ])
    s.set_defaults(func=cmd_gmail)

    # linkedin
    s = _sub(sub, "linkedin", "Import LinkedIn's official data export (no scraping).", [
        "python -m candid linkedin guide",
        "python -m candid linkedin import --zip LinkedIn-export.zip",
        "python -m candid linkedin import --zip LinkedIn-export.zip --mode replace",
    ])
    ls = _nested(s)
    t = _sub(ls, "import", "Import a LinkedIn export ZIP into your profile.", [
        "python -m candid linkedin import --zip LinkedIn-export.zip",
        "python -m candid linkedin import --zip LinkedIn-export.zip --mode replace",
    ])
    t.add_argument("--zip", required=True, help="Path to the LinkedIn export .zip")
    t.add_argument("--mode", default="merge", choices=["merge", "replace"],
                   help="merge: fold into existing profile (default); replace: overwrite")
    t = _sub(ls, "guide", "How to download your LinkedIn data export.", [
        "python -m candid linkedin guide",
    ])
    s.set_defaults(func=cmd_linkedin)

    return p


def _next_command(args, etype: str) -> str:
    """The exact command to run after an expected failure."""
    hint = _NEXT_COMMAND.get(etype)
    if hint:
        return hint
    cmd = getattr(args, "cmd", None)
    if cmd:
        return f"python -m candid {cmd} --help"
    return "python -m candid --help"


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except SystemExit as e:
        # sys.exit("message") from helpers → friendly error + next step
        if isinstance(e.code, str):
            sys.stderr.write(f"Error: {e.code}\n")
            sys.stderr.write(f"Next: run `{_next_command(args, '')}`\n")
            sys.exit(1)
        raise
    except Exception as e:  # friendly errors, no tracebacks
        etype = type(e).__name__
        if etype in _EXPECTED_ERRORS:
            sys.stderr.write(f"Error: {e}\n")
            sys.stderr.write(f"Next: run `{_next_command(args, etype)}`\n")
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
