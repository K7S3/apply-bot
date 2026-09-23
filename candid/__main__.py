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
    python -m candid apply --job jobs/example.yaml    # supervised application (parks at review)

Run `python -m candid <command> --help` for details on each command.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

from candid import __version__

# ---------------------------------------------------------------------------
# command inventory (kept in sync with build_parser below)
# ---------------------------------------------------------------------------

COMMANDS = [
    "onboard", "profile", "match", "tailor", "track", "prep",
    "followup", "offer", "benefits", "vesting", "negotiate", "salary", "mock",
    "jobs", "dashboard", "import", "gmail", "linkedin", "patterns", "tracks",
    "apply",
]

SUBCOMMANDS = {
    "profile": ["show"],
    "tailor": ["resume", "cover-letter"],
    "track": ["add", "list", "update", "remove", "stats", "search", "export-csv"],
    "followup": ["thank-you", "check-in", "referral"],
    "offer": ["add", "list", "compare", "export"],
    "benefits": ["health", "healthcare", "match", "vesting", "pto", "espp",
                 "hsa", "fsa", "commute", "leave", "stipends",
                 "normalize", "compare"],
    "vesting": ["timeline", "chart", "compare", "depart", "handcuffs",
                "refresher", "tax", "export"],
    "negotiate": ["playbook", "script", "counter"],
    "salary": ["lookup", "import-lca", "parse-range"],
    "mock": ["list", "coding", "run", "solution", "hint", "ai",
             "behavioral", "design"],
    "jobs": ["curate", "refresh", "list"],
    "gmail": ["import", "proposals", "confirm", "reject", "guide"],
    "linkedin": ["import", "guide"],
    "patterns": ["list", "tags", "plan", "log", "due", "review",
                 "drill", "mastery", "cheatsheet", "reset"],
    "tracks": ["list", "show", "questions", "concepts", "drills", "plan",
               "progress", "done", "undone", "reset", "mock", "suggest"],
    "apply": ["run", "status", "answer", "approve", "submit"],
}

#: Expected (non-bug) failures: reported cleanly, no tracebacks.
_EXPECTED_ERRORS = {
    "OnboardError", "MatchError", "TrackerError", "PrepError",
    "OfferError", "BenefitsError", "SalaryError", "MockError", "JudgeError",
    "OfferError", "VestingError", "SalaryError", "MockError", "JudgeError",
    "GmailError", "LinkedInError", "DashboardError", "JobsError",
    "PatternsError", "AlumniError", "ApplyError",
    "ValueError",
    "TrackError", "ValueError",
}

#: Exact next command to run after each expected failure.
_NEXT_COMMAND = {
    "OnboardError": "python -m candid onboard --help",
    "MatchError": "python -m candid match --help",
    "TrackerError": "python -m candid track list",
    "PrepError": "python -m candid prep --help",
    "OfferError": "python -m candid offer --help",
    "BenefitsError": "python -m candid benefits --help",
    "VestingError": "python -m candid vesting --help",
    "SalaryError": "python -m candid salary --help",
    "MockError": "python -m candid mock --help",
    "JudgeError": "python -m candid mock --help",
    "GmailError": "python -m candid gmail --help",
    "LinkedInError": "python -m candid linkedin guide",
    "DashboardError": "python -m candid dashboard --help",
    "JobsError": "python -m candid jobs --help",
    "PatternsError": "python -m candid patterns --help",
    "TrackError": "python -m candid tracks list",
    "ApplyError": "python -m candid apply --help",
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


def _money(value: float) -> str:
    return f"${value:,.0f}"


def cmd_benefits(a):
    from candid import benefits as B
    if a.what == "health":
        r = B.health_plan_cost(a.premium, a.deductible, a.coinsurance,
                               a.oop_max, a.spend)
        print(f"Annual premium: {_money(r['annual_premium'])}")
        print(f"Out-of-pocket at {_money(a.spend)} spend: {_money(r['oop_cost'])}")
        print(f"Total annual cost: {_money(r['total_cost'])}")
    elif a.what == "healthcare":
        scenarios = None
        if a.scenario:
            scenarios = []
            for spec in a.scenario:
                try:
                    p, s = spec.split(":")
                    scenarios.append((float(p), float(s)))
                except ValueError:
                    raise B.BenefitsError(
                        f"bad --scenario {spec!r}: use prob:spend, e.g. 0.5:1500")
        r = B.healthcare_expected_cost(a.premium, a.deductible, a.coinsurance,
                                       a.oop_max, scenarios=scenarios)
        for row in r["scenarios"]:
            print(f"  p={row['probability']:.0%} spend={_money(row['spend'])} "
                  f"-> cost={_money(row['cost'])}")
        print(f"Expected annual cost: {_money(r['expected_cost'])}")
    elif a.what == "match":
        r = B.match_401k(a.salary, a.contrib_pct, a.formula)
        print(f"Eligible pay: {_money(r['eligible_pay'])}")
        for t in r["tiers"]:
            print(f"  {t['tier']}: {_money(t['amount'])}")
        print(f"Annual employer match: {_money(r['annual_match'])}")
    elif a.what == "vesting":
        r = B.vesting_value(a.balance, a.years, a.schedule)
        print(f"Vested: {r['vested_pct']:.0%} = {_money(r['vested_value'])} "
              f"(unvested {_money(r['unvested_value'])})")
    elif a.what == "pto":
        r = B.pto_value(a.salary, a.pto_days, a.sick_days, a.holidays)
        print(f"{r['paid_days_off']:.0f} paid days off at {_money(r['daily_rate'])}/day "
              f"= {_money(r['value'])}/yr")
    elif a.what == "espp":
        r = B.espp_value(a.salary, a.contrib_pct, a.discount_pct,
                         lookback=a.lookback)
        print(f"Annual contribution: {_money(r['annual_contribution'])}")
        print(f"Estimated annual gain: {_money(r['estimated_annual_gain'])}"
              + (" (with lookback)" if a.lookback else ""))
    elif a.what == "hsa":
        r = B.hsa_value(a.seed, a.contribution, a.tax_rate)
        print(f"Employer seed: {_money(r['employer_seed'])} + "
              f"tax savings {_money(r['tax_savings'])} = {_money(r['total_value'])}/yr")
    elif a.what == "fsa":
        r = B.fsa_value(a.election, a.tax_rate)
        print(f"FSA tax savings on {_money(r['election'])}: {_money(r['tax_savings'])}/yr")
        print(f"Note: {r['note']}")
    elif a.what == "commute":
        r = B.commute_value(a.pretax, a.subsidy, a.tax_rate)
        print(f"Tax savings: {_money(r['tax_savings'])} + "
              f"subsidy {_money(r['subsidy_value'])} = {_money(r['total_value'])}/yr")
    elif a.what == "leave":
        r = B.leave_value(a.salary, a.full_weeks, a.partial_weeks, a.partial_pct)
        print(f"Paid leave value: {_money(r['value'])} "
              f"({r['weeks_full_pay']:.0f} wks full + {r['weeks_partial_pay']:.0f} wks "
              f"at {a.partial_pct:.0%})")
    elif a.what == "stipends":
        stipends = {}
        for spec in a.set or []:
            try:
                k, v = spec.split("=", 1)
                stipends[k.strip()] = float(v)
            except ValueError:
                raise B.BenefitsError(
                    f"bad --set {spec!r}: use name=amount, e.g. wellness=1200")
        r = B.stipends_value(stipends)
        for item in r["stipends"]:
            print(f"  {item['name']}: {_money(item['amount'])}")
        print(f"Total stipends: {_money(r['total_value'])}/yr")
    elif a.what == "normalize":
        pkg = B.load_package(a.package)
        print(B.render_normalized(B.normalize_package(pkg)))
    elif a.what == "compare":
        pa = B.load_package(a.package_a)
        pb = B.load_package(a.package_b)
        print(B.render_comparison(B.compare_packages(pa, pb)))
def _vesting_spec(a):
    """Build a normalized grant spec from CLI flags or a recorded offer."""
    from candid import vesting as V
    if getattr(a, "offer_id", 0):
        return V.grant_by_offer_id(a.offer_id)
    if a.shares and a.value:
        sys.exit("Use --shares or --value, not both.\n"
                 "Next: run `python -m candid vesting timeline --help`.")
    if a.shares:
        if not a.grant_price:
            sys.exit("--shares needs --grant-price for value math.\n"
                     "Next: run `python -m candid vesting timeline --help`.")
        spec = {"kind": "shares", "total": a.shares,
                "grant_price": a.grant_price}
    elif a.value:
        spec = {"kind": "dollars", "total": a.value}
    else:
        sys.exit("Provide --shares N, --value V, or --offer-id N.\n"
                 "Next: run `python -m candid vesting timeline --help`.")
    spec.update({
        "start": a.start or None,
        "years": a.years,
        "freq": a.freq,
        "cliff_months": a.cliff_months,
        "schedule": a.schedule,
        "label": a.label,
    })
    return V.normalize_grant(spec)


def _vesting_prices(a, spec, months):
    """Monthly price path for share grants, or None for dollar grants."""
    from candid import vesting as V
    if spec["kind"] != "shares":
        return None
    start = a.price_start or spec["grant_price"]
    return V.price_path(start, months, a.growth)


def cmd_vesting(a):
    from candid import vesting as V
    if a.what == "compare":
        from candid import offer as O
        rows = V.compare_offers(O.list_offers())
        print(V.render_offer_vesting_comparison(rows))
        return
    spec = _vesting_spec(a)
    months = spec["years"] * 12
    if a.what == "timeline":
        events = V.build_schedule(spec)
        print(V.render_table(events, title=f"Vesting timeline — {spec['label']}"))
        cs = V.cliff_summary(events)
        if cs:
            unit = "shares" if spec["kind"] == "shares" else "dollars"
            print(f"\nCliff: {cs['units']:,.0f} {unit} vest on "
                  f"{cs['date'].isoformat()} (month {cs['month']}, "
                  f"{cs['pct_of_grant']:.1f}% of grant).")
    elif a.what == "chart":
        events = V.build_schedule(spec)
        if spec["kind"] == "shares":
            start = a.price_start or spec["grant_price"]
            series = V.scenario_series(
                events, months, start,
                {"bear": a.bear, "base": a.growth, "bull": a.bull},
                grant_price=spec["grant_price"])
            print(V.render_chart(
                series, months,
                title=f"Cumulative vested value — {spec['label']} "
                      f"(price scenarios, %/yr)"))
        else:
            series = {"vested $": V.cumulative_value_series(events, months)}
            print(V.render_chart(series, months,
                                 title=f"Cumulative vested value — {spec['label']}"))
    elif a.what == "depart":
        events = V.build_schedule(spec)
        print(V.render_departure(V.departure_analysis(events, a.at_month),
                                 spec["label"]))
    elif a.what == "handcuffs":
        events = V.build_schedule(spec)
        prices = _vesting_prices(a, spec, months)
        print(V.render_handcuffs(events, months, prices,
                                 spec.get("grant_price"), spec["label"]))
    elif a.what == "refresher":
        events = V.add_refreshers(spec, a.refresher or [])
        print(V.render_refresher_summary(spec, a.refresher or [], events))
        print()
        print(V.render_chart(
            {"combined vested $": V.cumulative_value_series(events, months)},
            months, title="Combined cumulative vested value"))
    elif a.what == "tax":
        events = V.build_schedule(spec)
        prices = _vesting_prices(a, spec, months)
        print(V.render_tax_events(
            V.tax_events(events, prices, spec.get("grant_price")),
            spec["label"]))
    elif a.what == "export":
        path = V.export_report(
            spec, path=a.out or None, refresher_specs=a.refresher or [],
            price_start=(a.price_start or None),
            annual_growth_pct=a.growth)
        print(f"Vesting report exported to {path}")


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


def cmd_patterns(a):
    from candid import patterns as P
    if a.what == "list":
        if a.pattern:
            p = P.get_pattern(a.pattern)
            print(f"{p['name']} (`{p['id']}`)\n\n{p['blurb']}\n")
            print("Recognize it:")
            for c in p["cues"]:
                print(f"  - {c}")
            print(f"\nComplexity: {p['complexity']}")
            banked = P.problems_for_pattern(a.pattern)
            if banked:
                print("\nBank problems:")
                for b in banked:
                    print(f"  {b['id']:<20}{b['title'][:40]:<42}{b['difficulty']}")
            else:
                print("\nNo bank problems tagged with this pattern yet.")
        else:
            cov = P.coverage()
            print(f"{'ID':<20}{'Name':<34}{'Bank':>5}")
            for p in P.PATTERNS:
                n = len(cov.get(p["id"], []))
                print(f"{p['id']:<20}{p['name'][:33]:<34}{n:>5}")
    elif a.what == "tags":
        if a.by_pattern:
            problems = P.problems_for_pattern(a.by_pattern)
            if not problems:
                print(f"No bank problems tagged '{a.by_pattern}' yet.")
            for b in problems:
                print(f"{b['id']:<20}{b['title'][:45]:<47}{b['difficulty']}")
        else:
            r = P.validate_bank()
            if r["errors"]:
                sys.exit("Tag errors:\n" + "\n".join(f"- {e}" for e in r["errors"]))
            print(f"{r['problems']} problems tagged across "
                  f"{len(r['patterns_used'])} patterns.")
            if r["patterns_unused"]:
                print("No bank problems yet for: "
                      + ", ".join(r["patterns_unused"]))
    elif a.what == "plan":
        gaps = [g.strip() for g in a.gaps.split(",") if g.strip()] \
            if a.gaps else None
        plan = P.build_plan(gaps=gaps, total=a.total, weeks=a.weeks)
        if a.json:
            print(json.dumps(plan, indent=2))
        elif a.out:
            fp = P.export_plan(plan, a.out)
            print(f"Wrote {plan['total']}-problem plan to {fp}")
        else:
            print(P.render_plan(plan))
    elif a.what == "log":
        rec = P.log_attempt(a.problem, solved=a.solved, quality=a.quality,
                            minutes=a.minutes,
                            at=a.date if a.date else None)
        status = "solved" if rec["solved"] else "not solved"
        print(f"Logged {a.problem}: {status}, quality {rec['quality']}/5 "
              f"on {rec['date']}.")
    elif a.what == "due":
        due = P.due_cards(as_of=a.as_of if a.as_of else None)
        if a.json:
            print(json.dumps(due, indent=2))
        elif not due:
            print("Nothing due for review.")
        else:
            print(f"{'Problem':<20}{'Next due':<12}Interval  Ease")
            for c in due:
                print(f"{c['problem_id']:<20}{c['next_due']:<12}"
                      f"{c['interval']:>5}d  {c['easiness']}")
    elif a.what == "review":
        card = P.review(a.problem, a.quality,
                        today=a.date if a.date else None)
        print(f"{a.problem}: quality {a.quality}/5 -> next review "
              f"{card['next_due']} (interval {card['interval']}d, "
              f"ease {card['easiness']}).")
    elif a.what == "drill":
        drill = P.build_drill(minutes_per_day=a.minutes_per_day, days=a.days,
                              seed=a.seed,
                              start=a.start if a.start else None)
        if a.json:
            print(json.dumps(drill, indent=2))
        else:
            print(P.render_drill(drill))
    elif a.what == "mastery":
        report = P.mastery_report()
        if a.json:
            print(json.dumps(report, indent=2))
        else:
            print(P.render_mastery(report))
    elif a.what == "cheatsheet":
        text = P.cheatsheet(a.pattern)
        if a.out:
            fp = Path(a.out).expanduser()
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(text, encoding="utf-8")
            print(f"Wrote cheat sheet to {fp}")
        else:
            print(text)
    elif a.what == "reset":
        if not a.yes:
            sys.exit("This deletes your patterns attempts and review cards.\n"
                     "Re-run with --yes to confirm.")
        removed = P.reset_progress()
        print(f"Removed {removed['attempts']} attempts and "
              f"{removed['cards']} review cards.")
def cmd_tracks(a):
    from candid import prep_tracks as PT
    if a.what == "list":
        tracks = PT.list_tracks()
        print(f"{'ID':<14}{'Title':<28}{'Q':>4}{'Concepts':>9}{'Drills':>7}  Tagline")
        for t in tracks:
            print(f"{t['id']:<14}{t['title'][:27]:<28}{t['questions']:>4}"
                  f"{t['concepts']:>9}{t['drills']:>7}  {t['tagline'][:60]}")
    elif a.what == "show":
        print(PT.render_track(a.track, include_deep_dives=a.deep_dives))
    elif a.what == "questions":
        if a.sample:
            qs = PT.sample_questions(a.track, n=a.sample, seed=a.seed,
                                     difficulty=a.difficulty)
        else:
            qs = PT.track_questions(a.track, category=a.category,
                                    difficulty=a.difficulty, round_name=a.round)
        if not qs:
            print("No questions match those filters.")
            return
        for q in qs:
            print(f"{q['n']}. [{q['category']} · {q['difficulty']} · {q['round']}]")
            print(f"   {q['q']}\n")
    elif a.what == "concepts":
        for c in PT.track_concepts(a.track):
            print(f"### {c['tag'].replace('_', ' ')}")
            print(f"Why this track: {c['why']}\n")
            if a.deep_dives:
                print(c["deep_dive"] + "\n")
    elif a.what == "drills":
        drills = PT.track_drills(a.track, kind=a.kind)
        for d in drills:
            print(f"### {d['name']} ({d['minutes']} min) [{d['kind']}]")
            print(f"id: {d['id']}\n{d['instructions']}\n")
            for item in d["checklist"]:
                print(f"  - [ ] {item}")
            print()
        print(f"Total drill time: {PT.total_drill_minutes(a.track)} minutes.")
    elif a.what == "plan":
        plan = PT.build_plan(a.track, days=a.days, hours_per_day=a.hours)
        print(PT.render_plan(plan))
    elif a.what == "progress":
        print(PT.render_coverage(PT.coverage(a.track)))
    elif a.what == "done":
        print(PT.render_coverage(PT.mark_done(a.track, a.kind, a.key)))
    elif a.what == "undone":
        print(PT.render_coverage(PT.mark_undone(a.track, a.kind, a.key)))
    elif a.what == "reset":
        PT.reset_progress(a.track)
        print(f"Progress reset for track '{a.track}'.")
    elif a.what == "mock":
        for m in PT.mock_preset(a.track):
            print(f"### {m['round']}\n  {m['command']}\n  {m['note']}\n")
    elif a.what == "suggest":
        gaps = (a.gaps or "").split(";") if a.gaps else []
        suggestions = PT.suggest_tracks([g.strip() for g in gaps if g.strip()])
        if not suggestions:
            print("No gap text given. Try: tracks suggest --gaps \"Missing must-have skill: sql; Seniority gap: leadership\"")
            return
        for s in suggestions:
            print(f"- {s['id']}: {s['title']} ({s['hits']} gap hit(s))")
            print(f"  {s['tagline']}")


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
                    min_score=getattr(a, "min_score", 0) or 0)
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


def _alumni_profile():
    """Profile for alumni features — optional; features degrade gracefully."""
    from candid import profile as P
    try:
        return P.load_profile()
    except P.OnboardError:
        return {}


def cmd_alumni(a):
    from candid import alumni as A
    net = A.load_network()
    if a.what == "import":
        src = a.csv or a.zip
        if not src:
            sys.exit("Give --csv <Connections.csv> or --zip <LinkedIn export>.zip.")
        res = A.import_connections(src, replace=a.replace)
        print(f"✅ Imported {res['added']} new, updated {res['updated']} "
              f"(total {res['total']} contacts).")
        if not A.load_network()["contacts"]:
            print("Tip: enrich with schools/past jobs: "
                  "`python -m candid alumni enrich --csv schools.csv`")
    elif a.what == "enrich":
        rows = A.parse_enrichment_csv(a.csv)
        res = A.enrich_contacts(rows)
        print(f"✅ Enriched {res['matched']} contact(s) with {res['facts_added']} "
              f"fact(s) ({res['unmatched']} name(s) not found in network).")
    elif a.what == "overlap":
        prof = _alumni_profile()
        if a.json:
            print(json.dumps({
                "schools": [{"contact": h["contact"]["name"], "schools": h["schools"]}
                            for h in A.school_overlap(net, prof)],
                "companies": [{"contact": h["contact"]["name"],
                                "companies": h["companies"]}
                               for h in A.company_overlap(net, prof)],
            }, indent=2))
            return
        if not a.companies:
            print(A.render_overlap("School overlap", A.school_overlap(net, prof),
                                   "schools"))
        if not a.schools:
            so = A.school_overlap(net, prof)
            if so and not a.companies:
                print()
            print(A.render_overlap("Company overlap", A.company_overlap(net, prof),
                                   "companies"))
        if not prof.get("education") and not prof.get("experience"):
            print("\nNote: no profile found — onboard first (`python -m candid "
                  "onboard`) so school/company overlap has something to match.")
    elif a.what == "warm-path":
        wp = A.warm_paths(net, _alumni_profile(), a.company, a.role or "",
                          limit=a.limit)
        if a.json:
            print(json.dumps(wp, indent=2, default=str))
        else:
            print(A.render_warm_paths(wp))
    elif a.what == "prioritize":
        targets = [(a.company, a.role or "")] if a.company else None
        queue = A.prioritize(net, _alumni_profile(), targets=targets,
                             limit=a.limit)
        if a.json:
            print(json.dumps(
                [{**e, "contact": e["contact"]["name"]} for e in queue],
                indent=2, default=str))
        else:
            print(A.render_queue(queue))
    elif a.what == "draft":
        c = A.find_contact(net, a.name)
        print(A.draft_outreach(c, _alumni_profile(), kind=a.kind,
                               target_company=a.company or "",
                               target_role=a.role or ""))
    elif a.what == "coverage":
        if not a.company:
            sys.exit("Give at least one --company (repeatable).")
        cov = A.coverage(net, _alumni_profile(), a.company)
        if a.json:
            print(json.dumps(cov, indent=2, default=str))
        else:
            print(A.render_coverage(cov))
    elif a.what == "log":
        rec = A.log_interaction(a.name, a.kind, a.note or "", a.date or "")
        print(f"✅ Logged {rec['kind']} with {rec['name']} on {rec['date']}.")
    elif a.what == "freshness":
        queue = A.freshness(net, _alumni_profile(),
                            stale_days=a.stale_days, quiet_days=a.quiet_days)
        if a.json:
            print(json.dumps(
                [{**e, "contact": e["contact"]["name"]} for e in queue],
                indent=2, default=str))
        else:
            print(A.render_freshness(queue))
    elif a.what == "stats":
        s = A.stats(net)
        if a.json:
            print(json.dumps(s, indent=2, default=str))
        else:
            print(A.render_stats(s))


def _render_apply_status(info: dict) -> str:
    """Human-readable one-job apply summary."""
    lines = [f"job {info['job_id']}: {info['state']}"]
    job = info.get("job") or {}
    if job.get("company"):
        lines.append(f"  {job.get('role')} @ {job.get('company')}")
        lines.append(f"  {job.get('url')}")
    if info.get("needs_open"):
        lines.append(f"needs input ({info['needs_open']}):")
        for label in info["needs"]:
            lines.append(f"  - {label}")
    appr = info.get("approval")
    if appr:
        lines.append(f"approved by {appr.get('by')} at {appr.get('at')}")
    return "\n".join(lines)


def cmd_apply(a):
    from candid import apply_runner as R
    runner = R.Runner()
    action = a.action or "run"

    def _seen(job_id: str) -> dict:
        data = runner.store.load(job_id)
        if (data.get("state") == "new" and not data.get("history")
                and not data.get("job")):
            raise R.ApplyError(
                f"no apply record for job id {job_id!r}; "
                "run `python -m candid apply --job <spec.yaml>` first."
            )
        return data

    if action == "run":
        if not a.job:
            sys.exit("apply run needs --job jobs/x.yaml "
                     "(try jobs/example.yaml).")
        data = runner.apply(a.job, headless=a.headless,
                            auto_submit=a.auto_submit and not a.park)
        needs = data.get("needs", [])
        if needs:
            print(f"{len(needs)} question(s) need your answers; "
                  f"the run is parked.")
            for n in needs:
                print(f"  - [{n.get('kind')}] {n.get('label')}")
            jid = data.get("job_id")
            print("answer with: python -m candid apply answer "
                  f"--job-id {jid} --answers '{{\"field\": \"value\"}}'")
        else:
            print(f"job {data.get('job_id')}: {data.get('state')}")
    elif action == "status":
        if not a.job_id:
            sys.exit("apply status needs --job-id ID.")
        _seen(a.job_id)
        info = runner.status(a.job_id)
        if a.json:
            print(json.dumps(info, indent=2))
        else:
            print(_render_apply_status(info))
    elif action == "answer":
        if not a.job_id:
            sys.exit("apply answer needs --job-id ID.")
        if not a.answers:
            sys.exit("apply answer needs --answers "
                     "'{\"field\": \"value\"}'.")
        try:
            answers = json.loads(a.answers)
        except json.JSONDecodeError as e:
            raise R.ApplyError(f"--answers is not valid JSON: {e}")
        if not isinstance(answers, dict):
            raise R.ApplyError(
                "--answers must be a JSON object: "
                "'{\"field\": \"value\"}'")
        _seen(a.job_id)
        runner.answer(a.job_id, answers)
    elif action == "approve":
        if not a.job_id:
            sys.exit("apply approve needs --job-id ID.")
        if not a.by:
            sys.exit("apply approve needs --by NAME "
                     "(who is approving?).")
        _seen(a.job_id)
        runner.approve(a.job_id, a.by)
    elif action == "submit":
        if not a.job_id:
            sys.exit("apply submit needs --job-id ID.")
        if not a.job:
            sys.exit("apply submit needs --job jobs/x.yaml.")
        _seen(a.job_id)
        runner.submit(a.job_id, a.job, headless=a.headless)


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

    # benefits
    s = _sub(sub, "benefits", "Normalize benefits into dollars and compare packages.", [
        "python -m candid benefits health --premium 300 --deductible 1500 --coinsurance 0.2 --oop-max 6000 --spend 8000",
        "python -m candid benefits match --salary 150000 --contrib-pct 0.10 --formula 100:3,50:2",
        "python -m candid benefits pto --salary 150000 --pto-days 20 --sick-days 5",
        "python -m candid benefits normalize --package samples/candid/sample_benefits_a.json",
        "python -m candid benefits compare --package-a samples/candid/sample_benefits_a.json --package-b samples/candid/sample_benefits_b.json",
    ])
    bs = _nested(s)
    t = _sub(bs, "health", "Annual cost of a health plan at a given spend level.", [
        "python -m candid benefits health --premium 300 --deductible 1500 --coinsurance 0.2 --oop-max 6000 --spend 8000",
    ])
    t.add_argument("--premium", type=float, required=True, help="Employee monthly premium $")
    t.add_argument("--deductible", type=float, required=True)
    t.add_argument("--coinsurance", type=float, required=True, help="Fraction 0-1, e.g. 0.2")
    t.add_argument("--oop-max", type=float, required=True)
    t.add_argument("--spend", type=float, required=True, help="Expected annual medical spend $")
    t = _sub(bs, "healthcare", "Scenario-weighted expected healthcare cost.", [
        "python -m candid benefits healthcare --premium 300 --deductible 1500 --coinsurance 0.2 --oop-max 6000",
        "python -m candid benefits healthcare --premium 300 --deductible 1500 --coinsurance 0.2 --oop-max 6000 --scenario 0.6:1000 --scenario 0.4:12000",
    ])
    t.add_argument("--premium", type=float, required=True)
    t.add_argument("--deductible", type=float, required=True)
    t.add_argument("--coinsurance", type=float, required=True)
    t.add_argument("--oop-max", type=float, required=True)
    t.add_argument("--scenario", action="append", default=[],
                   help="prob:spend, repeatable (default low/mid/high mix)")
    t = _sub(bs, "match", "Annual 401(k) employer match in dollars.", [
        "python -m candid benefits match --salary 150000 --contrib-pct 0.10 --formula 100:3,50:2",
    ])
    t.add_argument("--salary", type=float, required=True)
    t.add_argument("--contrib-pct", type=float, default=0.06,
                   help="Your contribution as fraction of pay, e.g. 0.10")
    t.add_argument("--formula", default="100:3,50:2",
                   help="Tiered formula, e.g. '100:3,50:2'")
    t = _sub(bs, "vesting", "Vested fraction of an employer-match balance.", [
        "python -m candid benefits vesting --balance 20000 --years 2 --schedule cliff:3",
    ])
    t.add_argument("--balance", type=float, required=True)
    t.add_argument("--years", type=float, required=True, help="Years of service")
    t.add_argument("--schedule", default="graded:6", help="'cliff:N' or 'graded:N'")
    t = _sub(bs, "pto", "Convert PTO / sick / holidays to dollars.", [
        "python -m candid benefits pto --salary 150000 --pto-days 20 --sick-days 5",
    ])
    t.add_argument("--salary", type=float, required=True)
    t.add_argument("--pto-days", type=float, default=0)
    t.add_argument("--sick-days", type=float, default=0)
    t.add_argument("--holidays", type=float, default=0)
    t = _sub(bs, "espp", "Estimated annual ESPP gain.", [
        "python -m candid benefits espp --salary 150000 --contrib-pct 0.10 --discount-pct 0.15",
        "python -m candid benefits espp --salary 150000 --contrib-pct 0.10 --discount-pct 0.15 --lookback",
    ])
    t.add_argument("--salary", type=float, required=True)
    t.add_argument("--contrib-pct", type=float, default=0.10)
    t.add_argument("--discount-pct", type=float, default=0.15)
    t.add_argument("--lookback", action="store_true")
    t = _sub(bs, "hsa", "HSA annual value: employer seed + tax savings.", [
        "python -m candid benefits hsa --seed 1000 --contribution 3000 --tax-rate 0.24",
    ])
    t.add_argument("--seed", type=float, default=0)
    t.add_argument("--contribution", type=float, default=0)
    t.add_argument("--tax-rate", type=float, default=0.24, help="Marginal rate 0-1")
    t = _sub(bs, "fsa", "FSA annual value: tax savings on the election.", [
        "python -m candid benefits fsa --election 3000 --tax-rate 0.24",
    ])
    t.add_argument("--election", type=float, required=True)
    t.add_argument("--tax-rate", type=float, default=0.24)
    t = _sub(bs, "commute", "Commuter/parking benefit annual value.", [
        "python -m candid benefits commute --pretax 200 --subsidy 100 --tax-rate 0.24",
    ])
    t.add_argument("--pretax", type=float, default=0, help="Monthly pre-tax deduction $")
    t.add_argument("--subsidy", type=float, default=0, help="Monthly employer subsidy $")
    t.add_argument("--tax-rate", type=float, default=0.24)
    t = _sub(bs, "leave", "Paid parental/family leave converted to dollars.", [
        "python -m candid benefits leave --salary 150000 --full-weeks 12",
        "python -m candid benefits leave --salary 150000 --partial-weeks 8 --partial-pct 0.6",
    ])
    t.add_argument("--salary", type=float, required=True)
    t.add_argument("--full-weeks", type=float, default=0)
    t.add_argument("--partial-weeks", type=float, default=0)
    t.add_argument("--partial-pct", type=float, default=0.6)
    t = _sub(bs, "stipends", "Sum named stipends into annual dollars.", [
        "python -m candid benefits stipends --set wellness=1200 --set learning=3000",
    ])
    t.add_argument("--set", action="append", default=[], help="name=amount, repeatable")
    t = _sub(bs, "normalize", "Roll a benefits package JSON into one annual $ number.", [
        "python -m candid benefits normalize --package samples/candid/sample_benefits_a.json",
    ])
    t.add_argument("--package", required=True, help="Path to package JSON file")
    t = _sub(bs, "compare", "Side-by-side comparison of two package JSON files.", [
        "python -m candid benefits compare --package-a samples/candid/sample_benefits_a.json --package-b samples/candid/sample_benefits_b.json",
    ])
    t.add_argument("--package-a", required=True)
    t.add_argument("--package-b", required=True)
    s.set_defaults(func=cmd_benefits)
    # vesting
    s = _sub(sub, "vesting", "Vesting schedule visualizer.", [
        "python -m candid vesting timeline --value 200000 --start 2026-06-01",
        "python -m candid vesting chart --shares 1000 --grant-price 50 --start 2026-06-01 --schedule amazon",
        "python -m candid vesting compare",
        "python -m candid vesting depart --offer-id 1 --at-month 18",
    ])
    vs = _nested(s)

    def _grant_args(t):
        t.add_argument("--offer-id", type=int, default=0,
                       help="Build the grant from recorded offer #N (equity fields)")
        t.add_argument("--shares", type=float, default=0,
                       help="Total RSU/option shares")
        t.add_argument("--value", type=float, default=0,
                       help="Total grant value in $ (cash-settled)")
        t.add_argument("--grant-price", type=float, default=0,
                       help="$/share at grant (required with --shares)")
        t.add_argument("--start", default="",
                       help="Vesting start YYYY-MM-DD (default: today)")
        t.add_argument("--years", type=int, default=4)
        t.add_argument("--freq", default="monthly",
                       choices=["monthly", "quarterly", "annual"])
        t.add_argument("--cliff-months", type=int, default=12)
        t.add_argument("--schedule", default="straight",
                       help="straight | amazon | front | custom:a/b/c/...")
        t.add_argument("--label", default="Grant")
        return t

    def _price_args(t):
        t.add_argument("--price-start", type=float, default=0,
                       help="$/share path start (default: grant price)")
        t.add_argument("--growth", type=float, default=0.0,
                       help="Annual $/share growth %% for value math")
        return t

    t = _grant_args(_sub(vs, "timeline", "Vesting timeline table with cliff markers.", [
        "python -m candid vesting timeline --value 200000 --start 2026-06-01",
        "python -m candid vesting timeline --offer-id 1",
        "python -m candid vesting timeline --shares 1000 --grant-price 50 --schedule amazon --freq annual",
    ]))

    t = _price_args(_grant_args(_sub(vs, "chart", "Cumulative vested-value chart (price scenarios for share grants).", [
        "python -m candid vesting chart --value 200000",
        "python -m candid vesting chart --shares 1000 --grant-price 50 --growth 5 --bear -10 --bull 25",
    ])))
    t.add_argument("--bear", type=float, default=-10.0, help="Bear annual growth %%")
    t.add_argument("--bull", type=float, default=20.0, help="Bull annual growth %%")

    _sub(vs, "compare", "Compare recorded offers by vested equity at 12/24/36/48 months.", [
        "python -m candid vesting compare",
    ])

    t = _price_args(_grant_args(_sub(vs, "depart", "Vested vs forfeited if you leave at month N.", [
        "python -m candid vesting depart --offer-id 1 --at-month 18",
        "python -m candid vesting depart --value 200000 --at-month 30",
    ])))
    t.add_argument("--at-month", type=int, required=True,
                   help="Months after vesting start")

    t = _price_args(_grant_args(_sub(vs, "handcuffs", "Golden handcuffs: unvested-$ remaining over time.", [
        "python -m candid vesting handcuffs --offer-id 1",
        "python -m candid vesting handcuffs --shares 1000 --grant-price 50 --growth 5",
    ])))

    t = _grant_args(_sub(vs, "refresher", "Stack refresher grants on the base grant.", [
        "python -m candid vesting refresher --value 200000 --refresher 40000:2:12 --refresher 40000:2:24",
    ]))
    t.add_argument("--refresher", action="append", default=[],
                   help="Repeatable: VALUE:YEARS:START (START = month offset or YYYY-MM-DD). "
                        "Refreshers vest straight-line monthly, no cliff.")

    t = _price_args(_grant_args(_sub(vs, "tax", "Taxable-income events per vest (estimate).", [
        "python -m candid vesting tax --offer-id 1",
        "python -m candid vesting tax --shares 1000 --grant-price 50 --growth 5",
    ])))

    t = _price_args(_grant_args(_sub(vs, "export", "Export a full vesting report as markdown.", [
        "python -m candid vesting export --offer-id 1",
        "python -m candid vesting export --value 200000 --out vesting.md --refresher 40000:2:12",
    ])))
    t.add_argument("--out", default="",
                   help="Output path (default: candid_data/vesting_reports/<date>_vesting_<label>.md)")
    t.add_argument("--refresher", action="append", default=[],
                   help="Repeatable: VALUE:YEARS:START, stacked onto the base grant.")
    s.set_defaults(func=cmd_vesting)

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

    # patterns
    s = _sub(sub, "patterns", "Coding patterns curriculum: study plans, spaced repetition, drills.", [
        "python -m candid patterns list",
        "python -m candid patterns plan --gaps sliding-window,dp-1d",
        "python -m candid patterns log --problem two-sum --solved --quality 4",
        "python -m candid patterns drill --minutes-per-day 45",
        "python -m candid patterns mastery",
    ])
    ps = _nested(s)
    t = _sub(ps, "list", "List the pattern taxonomy (or detail one pattern).", [
        "python -m candid patterns list",
        "python -m candid patterns list --pattern sliding-window",
    ])
    t.add_argument("--pattern", default=None, help="Pattern id for detail view")
    t = _sub(ps, "tags", "Validate problem pattern tags / list by pattern.", [
        "python -m candid patterns tags",
        "python -m candid patterns tags --by-pattern hashmap",
    ])
    t.add_argument("--by-pattern", default=None, help="List bank problems for a pattern")
    t = _sub(ps, "plan", "Blind-75-style study plan from your skill gaps.", [
        "python -m candid patterns plan",
        "python -m candid patterns plan --gaps sliding-window,dp-1d --total 30",
        "python -m candid patterns plan --out plan.md",
    ])
    t.add_argument("--gaps", default=None,
                   help="Comma-separated pattern ids, weakest first (default: from your attempts)")
    t.add_argument("--total", type=int, default=75, help="Cap on problems (default: 75)")
    t.add_argument("--weeks", type=int, default=None, help="Weeks to spread over")
    t.add_argument("--out", default=None, help="Write plan markdown to file")
    t.add_argument("--json", action="store_true", help="Print the raw plan as JSON")
    t = _sub(ps, "log", "Log a practice attempt (updates spaced repetition).", [
        "python -m candid patterns log --problem two-sum --solved --quality 4",
        "python -m candid patterns log --problem coin-change --failed --minutes 30",
    ])
    t.add_argument("--problem", required=True)
    g = t.add_mutually_exclusive_group(required=True)
    g.add_argument("--solved", action="store_true")
    g.add_argument("--failed", action="store_true")
    t.add_argument("--quality", type=int, default=None, help="Self-rating 0-5")
    t.add_argument("--minutes", type=float, default=None)
    t.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    t = _sub(ps, "due", "Show spaced-repetition cards due for review.", [
        "python -m candid patterns due",
        "python -m candid patterns due --as-of 2026-10-01",
    ])
    t.add_argument("--as-of", default=None, help="YYYY-MM-DD (default: today)")
    t.add_argument("--json", action="store_true")
    t = _sub(ps, "review", "Record a review and reschedule (SM-2).", [
        "python -m candid patterns review --problem two-sum --quality 5",
    ])
    t.add_argument("--problem", required=True)
    t.add_argument("--quality", type=int, required=True, help="Recall quality 0-5")
    t.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    t = _sub(ps, "drill", "Day-by-day drill: new weak-pattern problems + due reviews.", [
        "python -m candid patterns drill",
        "python -m candid patterns drill --minutes-per-day 30 --days 5",
    ])
    t.add_argument("--minutes-per-day", type=int, default=45)
    t.add_argument("--days", type=int, default=7)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--start", default=None, help="YYYY-MM-DD (default: today)")
    t.add_argument("--json", action="store_true")
    t = _sub(ps, "mastery", "Per-pattern mastery dashboard.", [
        "python -m candid patterns mastery",
    ])
    t.add_argument("--json", action="store_true")
    t = _sub(ps, "cheatsheet", "One-page pattern cheat sheet.", [
        "python -m candid patterns cheatsheet sliding-window",
        "python -m candid patterns cheatsheet heap-top-k --out heap.md",
    ])
    t.add_argument("pattern", help="Pattern id")
    t.add_argument("--out", default=None, help="Write markdown to file")
    t = _sub(ps, "reset", "Delete patterns attempts and review cards.", [
        "python -m candid patterns reset --yes",
    ])
    t.add_argument("--yes", action="store_true", help="Confirm deletion")
    s.set_defaults(func=cmd_patterns)
    # tracks
    s = _sub(sub, "tracks", "Role-family prep tracks: questions, concepts, drills, plans.", [
        "python -m candid tracks list",
        "python -m candid tracks show mle",
        "python -m candid tracks questions --track backend --difficulty medium",
        "python -m candid tracks plan --track data-science --days 14",
    ])
    ts = s.add_subparsers(dest="what", required=True)
    t = _sub(ts, "list", "List all prep tracks.", [
        "python -m candid tracks list",
    ])
    t = _sub(ts, "show", "Show a track: loop, concepts, questions, drills, mock presets.", [
        "python -m candid tracks show mle",
        "python -m candid tracks show pm --deep-dives",
    ])
    t.add_argument("track", help="Track id: mle, backend, frontend, data-science, pm, em")
    t.add_argument("--deep-dives", action="store_true",
                   help="Include full concept deep-dive text")
    t = _sub(ts, "questions", "Browse or sample a track's question bank.", [
        "python -m candid tracks questions --track backend",
        "python -m candid tracks questions --track mle --difficulty hard",
        "python -m candid tracks questions --track frontend --sample 5 --seed 42",
    ])
    t.add_argument("--track", required=True)
    t.add_argument("--category", default=None)
    t.add_argument("--difficulty", default=None, choices=["easy", "medium", "hard"])
    t.add_argument("--round", default=None, help="Filter by loop round name (substring)")
    t.add_argument("--sample", type=int, default=0,
                   help="Deterministic sample of N questions (use --seed to vary)")
    t.add_argument("--seed", type=int, default=0)
    t = _sub(ts, "concepts", "Concept deep-dives for a track.", [
        "python -m candid tracks concepts --track data-science",
        "python -m candid tracks concepts --track mle --deep-dives",
    ])
    t.add_argument("--track", required=True)
    t.add_argument("--deep-dives", action="store_true")
    t = _sub(ts, "drills", "Timed practice drills for a track.", [
        "python -m candid tracks drills --track backend",
        "python -m candid tracks drills --track em --kind qna",
    ])
    t.add_argument("--track", required=True)
    t.add_argument("--kind", default=None, help="Filter by drill kind")
    t = _sub(ts, "plan", "Build an N-day study plan spreading the track across days.", [
        "python -m candid tracks plan --track frontend --days 14",
        "python -m candid tracks plan --track pm --days 7 --hours 2",
    ])
    t.add_argument("--track", required=True)
    t.add_argument("--days", type=int, default=14)
    t.add_argument("--hours", type=float, default=1.0, help="Study hours per day")
    t = _sub(ts, "progress", "Show completion coverage for a track.", [
        "python -m candid tracks progress --track mle",
    ])
    t.add_argument("--track", required=True)
    t = _sub(ts, "done", "Mark a concept, question, or drill done.", [
        "python -m candid tracks done --track mle --kind concept --key ml_system_design",
        "python -m candid tracks done --track backend --kind drill --key be-design-45",
    ])
    t.add_argument("--track", required=True)
    t.add_argument("--kind", required=True, choices=["concept", "question", "drill"])
    t.add_argument("--key", required=True, help="Concept tag, q<N>, or drill id")
    t = _sub(ts, "undone", "Un-mark an item.", [
        "python -m candid tracks undone --track mle --kind concept --key ml_system_design",
    ])
    t.add_argument("--track", required=True)
    t.add_argument("--kind", required=True, choices=["concept", "question", "drill"])
    t.add_argument("--key", required=True)
    t = _sub(ts, "reset", "Clear all progress for a track.", [
        "python -m candid tracks reset --track mle",
    ])
    t.add_argument("--track", required=True)
    t = _sub(ts, "mock", "Suggested mock sessions aligned to the track's loop.", [
        "python -m candid tracks mock --track data-science",
    ])
    t.add_argument("--track", required=True)
    t = _sub(ts, "suggest", "Suggest tracks from match-gap text.", [
        "python -m candid tracks suggest --gaps \"Missing must-have skill: sql; Seniority gap: leadership\"",
    ])
    t.add_argument("--gaps", default="", help="Semicolon-separated gap strings")
    s.set_defaults(func=cmd_tracks)

    # jobs
    s = _sub(sub, "jobs", "Curate open jobs and feed the tracker.", [
        "python -m candid jobs curate --role \"Data Scientist\" --location \"New York\" --remote",
        "python -m candid jobs refresh --role \"ML Engineer\" --limit 10",
        "python -m candid jobs list",
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
    t = _sub(js, "list", "Show the curated pipeline (status=saved).", [
        "python -m candid jobs list",
        "python -m candid jobs list --json   # machine-readable output",
    ])
    t.add_argument("--json", action="store_true",
                   help="Print the curated job list as JSON (for scripting)")
    s.set_defaults(func=cmd_jobs)

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

    # alumni
    s = _sub(sub, "alumni", "Map your alumni network for warm outreach.", [
        "python -m candid alumni import --csv Connections.csv",
        "python -m candid alumni warm-path --company Stripe --role \"ML Engineer\"",
        "python -m candid alumni prioritize --company Stripe --role \"ML Engineer\"",
    ])
    als = _nested(s)
    t = _sub(als, "import", "Import LinkedIn Connections.csv or export ZIP.", [
        "python -m candid alumni import --csv Connections.csv",
        "python -m candid alumni import --zip LinkedIn-export.zip",
        "python -m candid alumni import --csv samples/candid/sample_connections.csv",
    ])
    t.add_argument("--csv", default="", help="Path to Connections.csv")
    t.add_argument("--zip", default="", help="Path to LinkedIn export .zip")
    t.add_argument("--replace", action="store_true",
                   help="Replace the network instead of merging")
    t = _sub(als, "enrich", "Add schools/past jobs per contact from a CSV.", [
        "python -m candid alumni enrich --csv schools.csv",
        "python -m candid alumni enrich --csv samples/candid/sample_enrichment.csv",
    ])
    t.add_argument("--csv", required=True,
                   help="CSV with name,school,grad_year,prev_company,start_year,end_year,notes")
    t = _sub(als, "overlap", "Contacts sharing your schools/employers.", [
        "python -m candid alumni overlap",
        "python -m candid alumni overlap --schools",
        "python -m candid alumni overlap --json",
    ])
    t.add_argument("--schools", action="store_true", help="Only school overlap")
    t.add_argument("--companies", action="store_true", help="Only company overlap")
    t.add_argument("--json", action="store_true")
    t = _sub(als, "warm-path", "Ranked warm routes into a target company.", [
        "python -m candid alumni warm-path --company Stripe",
        "python -m candid alumni warm-path --company Stripe --role \"ML Engineer\"",
    ])
    t.add_argument("--company", required=True)
    t.add_argument("--role", default="")
    t.add_argument("--limit", type=int, default=10)
    t.add_argument("--json", action="store_true")
    t = _sub(als, "prioritize", "Ranked outreach queue with tiers.", [
        "python -m candid alumni prioritize",
        "python -m candid alumni prioritize --company Stripe --role \"ML Engineer\"",
    ])
    t.add_argument("--company", default="", help="Target company")
    t.add_argument("--role", default="", help="Target role")
    t.add_argument("--limit", type=int, default=25)
    t.add_argument("--json", action="store_true")
    t = _sub(als, "draft", "Draft a warm outreach message.", [
        "python -m candid alumni draft --name \"David Kim\" --kind referral --company Stripe --role \"ML Engineer\"",
        "python -m candid alumni draft --name \"Grace Liu\" --kind reconnect",
    ])
    t.add_argument("--name", required=True, help="Contact name")
    t.add_argument("--kind", default="referral",
                   choices=["referral", "info-chat", "reconnect"])
    t.add_argument("--company", default="")
    t.add_argument("--role", default="")
    t = _sub(als, "coverage", "Warm-contact coverage vs target companies.", [
        "python -m candid alumni coverage --company Stripe --company OpenAI",
    ])
    t.add_argument("--company", action="append", default=[],
                   help="Target company (repeatable)")
    t.add_argument("--json", action="store_true")
    t = _sub(als, "log", "Log an interaction with a contact.", [
        "python -m candid alumni log --name \"David Kim\" --kind coffee --note \"great chat about ML platform\"",
    ])
    t.add_argument("--name", required=True)
    t.add_argument("--kind", default="coffee",
                   choices=["met", "emailed", "called", "coffee", "messaged", "other"])
    t.add_argument("--note", default="")
    t.add_argument("--date", default="", help="YYYY-MM-DD (default: today)")
    t = _sub(als, "freshness", "Stale contacts needing re-engagement.", [
        "python -m candid alumni freshness",
        "python -m candid alumni freshness --stale-days 180 --quiet-days 90",
    ])
    t.add_argument("--stale-days", type=int, default=365)
    t.add_argument("--quiet-days", type=int, default=180)
    t.add_argument("--json", action="store_true")
    t = _sub(als, "stats", "Network overview.", [
        "python -m candid alumni stats",
    ])
    t.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_alumni)

    # apply
    s = _sub(sub, "apply", "Supervised job applications: fill safe fields, park at review, approve, submit.", [
        "python -m candid apply --job jobs/example.yaml",
        "python -m candid apply --job jobs/acme.yaml --auto-submit",
        "python -m candid apply status --job-id acme-swe-1",
        "python -m candid apply status --job-id acme-swe-1 --json",
        "python -m candid apply answer --job-id acme-swe-1 --answers '{\"salary\": \"150k\"}'",
        "python -m candid apply approve --job-id acme-swe-1 --by Keshavan",
        "python -m candid apply submit --job-id acme-swe-1 --job jobs/acme.yaml",
    ])
    s.add_argument("action", nargs="?", default="run",
                   choices=["run", "status", "answer", "approve", "submit"],
                   help="run (default): fill the form and park at review; "
                        "status/answer/approve/submit manage an in-flight application")
    s.add_argument("--job", default=None,
                   help="Job spec YAML, e.g. jobs/example.yaml (run, submit)")
    s.add_argument("--park", action="store_true",
                   help="Park at review instead of submitting (this is the "
                        "default; also overrides --auto-submit)")
    s.add_argument("--auto-submit", action="store_true",
                   help="Only submits when zero needs_input items are "
                        "unresolved; otherwise parks for review. Explicit "
                        "approval is the default.")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--headless", dest="headless", action="store_true",
                   default=True, help="Run the browser headless (default)")
    g.add_argument("--no-headless", dest="headless", action="store_false",
                   help="Show the browser window while applying")
    s.add_argument("--job-id", default=None,
                   help="Job id (status, answer, approve, submit)")
    s.add_argument("--answers", default=None,
                   help="JSON object of answers for open questions, "
                        "e.g. '{\"salary\": \"150k\"}' (answer)")
    s.add_argument("--by", default=None,
                   help="Approver name (approve)")
    s.add_argument("--json", action="store_true",
                   help="Print status as JSON (status)")
    s.set_defaults(func=cmd_apply)

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
