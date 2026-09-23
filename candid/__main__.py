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
from pathlib import Path

from candid import __version__

# ---------------------------------------------------------------------------
# command inventory (kept in sync with build_parser below)
# ---------------------------------------------------------------------------

COMMANDS = [
    "onboard", "profile", "match", "tailor", "track", "prep",
    "followup", "offer", "benefits", "negotiate", "salary", "mock", "jobs",
    "dashboard", "import", "gmail", "linkedin", "patterns",
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
    "negotiate": ["playbook", "script", "counter"],
    "salary": ["lookup", "import-lca", "parse-range"],
    "mock": ["list", "coding", "run", "solution", "hint", "ai",
             "behavioral", "design"],
    "jobs": ["curate", "refresh", "list"],
    "gmail": ["import", "proposals", "confirm", "reject", "guide"],
    "linkedin": ["import", "guide"],
    "patterns": ["list", "tags", "plan", "log", "due", "review",
                 "drill", "mastery", "cheatsheet", "reset"],
}

#: Expected (non-bug) failures: reported cleanly, no tracebacks.
_EXPECTED_ERRORS = {
    "OnboardError", "MatchError", "TrackerError", "PrepError",
    "OfferError", "BenefitsError", "SalaryError", "MockError", "JudgeError",
    "GmailError", "LinkedInError", "DashboardError", "JobsError",
    "PatternsError",
    "ProjectError",
    "ValueError",
}

#: Exact next command to run after each expected failure.
_NEXT_COMMAND = {
    "OnboardError": "python -m candid onboard --help",
    "MatchError": "python -m candid match --help",
    "TrackerError": "python -m candid track list",
    "PrepError": "python -m candid prep --help",
    "OfferError": "python -m candid offer --help",
    "BenefitsError": "python -m candid benefits --help",
    "SalaryError": "python -m candid salary --help",
    "MockError": "python -m candid mock --help",
    "JudgeError": "python -m candid mock --help",
    "GmailError": "python -m candid gmail --help",
    "LinkedInError": "python -m candid linkedin guide",
    "DashboardError": "python -m candid dashboard --help",
    "JobsError": "python -m candid jobs --help",
    "PatternsError": "python -m candid patterns --help",
    "ProjectError": "python -m candid project --help",
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


def _project_jd(a) -> str:
    """Optional JD for project subcommands; empty string when not given."""
    if not getattr(a, "jd", None) and not getattr(a, "app_id", None):
        return ""
    return _jd_text(a)


def cmd_project(a):
    from candid import projects as PR
    what = a.what
    if what == "gaps":
        jd = _jd_text(a)
        analysis = PR.analyze_gaps(_profile(), jd,
                                   existing=PR.list_projects())
        print(PR.render_gaps(analysis))
    elif what in ("ideas", "rank"):
        jd = _project_jd(a)
        ideas = PR.generate_ideas(_profile(), jd_text=jd, role=a.role or "",
                                  n=a.n)
        if a.json:
            print(json.dumps(ideas, indent=2, default=str))
        else:
            print(PR.render_ideas(ideas))
    elif what == "scope":
        print(PR.render_scope(PR.weekend_scope(a.idea_id)))
    elif what == "stack":
        jd = _project_jd(a)
        print(PR.render_stack(PR.suggest_stack(a.idea_id, jd_text=jd)))
    elif what == "estimate":
        e = PR.estimate(a.idea_id, _profile(),
                        hours_per_weekend=a.hours_per_weekend,
                        start=a.start or "")
        print(PR.render_estimate(e))
    elif what == "learn":
        t = PR.get_idea(a.idea_id)
        print(PR.render_learn(PR.learning_plan(a.idea_id), t["title"]))
    elif what == "scaffold":
        path = PR.scaffold(a.idea_id, a.dir)
        print(f"Scaffolded '{a.idea_id}' at {path}")
        print("Next: `cd` in, read the README milestones, and start weekend 1.")
    elif what == "story":
        print(PR.render_story(PR.build_story(a.ref)))
    elif what == "add":
        skills = [s.strip() for s in (a.skills or "").split(",")]
        rec = PR.add_project(a.name, skills, status=a.status,
                             url=a.url or "", description=a.desc or "")
        print(f"Added '{rec['name']}' [{rec['status']}] "
              f"({', '.join(rec['skills']) or 'no skills'}).")
    elif what == "list":
        projects = PR.list_projects(status=a.status)
        if a.json:
            print(json.dumps(projects, indent=2, default=str))
        else:
            print(PR.render_ledger(projects))
    elif what == "rm":
        rec = PR.remove_project(a.name)
        print(f"Removed '{rec['name']}' from the ledger.")
    elif what == "done":
        rec = PR.update_project(a.name, status="done")
        print(f"Marked '{rec['name']}' done. It now covers its skills in "
              "gap analysis - nice work.")
    elif what == "browse":
        ideas = PR.list_ideas()
        if a.json:
            print(json.dumps(ideas, indent=2, default=str))
        else:
            for i in ideas:
                print(f"- {i['id']}: {i['title']} "
                      f"({', '.join(i['skills'])}; ~{i['weekends']} wknd)")
    else:  # pragma: no cover - argparse required=True guards this
        sys.exit(f"Unknown project subcommand: {what}")


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

    # project (side-project ideator)
    s = _sub(sub, "project", "Side-project ideator: gap-driven ideas, weekend scopes, stacks.", [
        "python -m candid project gaps --jd jd.txt",
        "python -m candid project ideas --jd jd.txt",
        "python -m candid project scope rag-support-bot",
        "python -m candid project scaffold rag-support-bot --dir ~/code/rag-bot",
    ])
    ps = _nested(s)
    t = _sub(ps, "gaps", "Rank the JD skills missing from your resume.", [
        "python -m candid project gaps --jd jd.txt",
        "cat jd.txt | python -m candid project gaps --jd -",
    ])
    t.add_argument("--jd", required=True, help=JD_HELP)
    t.add_argument("--app-id", type=int, default=None,
                   help="Use the JD stored for a tracked application")
    t = _sub(ps, "ideas", "Generate project ideas that fill your gaps.", [
        "python -m candid project ideas --jd jd.txt",
        "python -m candid project ideas --role ml --n 5",
        "python -m candid project ideas --jd jd.txt --json",
    ])
    t.add_argument("--jd", default=None, help=JD_HELP + " (optional)")
    t.add_argument("--app-id", type=int, default=None,
                   help="Use the JD stored for a tracked application")
    t.add_argument("--role", default="",
                   help="Role family to bias toward (ml, data, backend, frontend, platform)")
    t.add_argument("--n", type=int, default=8, help="Max ideas to show")
    t.add_argument("--json", action="store_true")
    t = _sub(ps, "rank", "Alias for ideas (ranked output).", [
        "python -m candid project rank --jd jd.txt",
    ])
    t.add_argument("--jd", default=None, help=JD_HELP + " (optional)")
    t.add_argument("--app-id", type=int, default=None)
    t.add_argument("--role", default="")
    t.add_argument("--n", type=int, default=8)
    t.add_argument("--json", action="store_true")
    t = _sub(ps, "browse", "List every curated idea in the library.", [
        "python -m candid project browse",
    ])
    t.add_argument("--json", action="store_true")
    t = _sub(ps, "scope", "Weekend-by-weekend plan for an idea.", [
        "python -m candid project scope rag-support-bot",
    ])
    t.add_argument("idea_id", help="Idea id (see `project browse`)")
    t = _sub(ps, "stack", "Tech-stack recommendation for an idea.", [
        "python -m candid project stack rag-support-bot",
        "python -m candid project stack rag-support-bot --jd jd.txt",
    ])
    t.add_argument("idea_id", help="Idea id (see `project browse`)")
    t.add_argument("--jd", default=None, help=JD_HELP + " (optional; tunes the stack)")
    t.add_argument("--app-id", type=int, default=None)
    t = _sub(ps, "estimate", "Hours + weekend calendar for an idea.", [
        "python -m candid project estimate rag-support-bot",
        "python -m candid project estimate rag-support-bot --hours-per-weekend 6",
    ])
    t.add_argument("idea_id", help="Idea id (see `project browse`)")
    t.add_argument("--hours-per-weekend", type=float, default=10)
    t.add_argument("--start", default="", help="Start date YYYY-MM-DD (default: today)")
    t = _sub(ps, "learn", "Free learning resources for the idea's stack.", [
        "python -m candid project learn rag-support-bot",
    ])
    t.add_argument("idea_id", help="Idea id (see `project browse`)")
    t = _sub(ps, "scaffold", "Generate a starter repo for an idea.", [
        "python -m candid project scaffold rag-support-bot --dir ~/code/rag-bot",
    ])
    t.add_argument("idea_id", help="Idea id (see `project browse`)")
    t.add_argument("--dir", required=True, help="Target directory (must not exist or be empty)")
    t = _sub(ps, "story", "Resume bullets + talking points for a project.", [
        "python -m candid project story rag-support-bot",
        "python -m candid project story \"My Churn Model\"",
    ])
    t.add_argument("ref", help="Idea id or ledger project name")
    t = _sub(ps, "add", "Record one of your projects in the ledger.", [
        "python -m candid project add --name \"Churn model\" --skills \"python,xgboost,sql\" --status done",
    ])
    t.add_argument("--name", required=True)
    t.add_argument("--skills", default="", help="Comma-separated canonical skills it demonstrates")
    t.add_argument("--status", default="planned",
                   choices=["planned", "in_progress", "done", "archived"])
    t.add_argument("--url", default="", help="Repo/demo URL")
    t.add_argument("--desc", default="", help="One-line description")
    t = _sub(ps, "list", "Show the project ledger.", [
        "python -m candid project list",
        "python -m candid project list --status done",
    ])
    t.add_argument("--status", default=None,
                   choices=["planned", "in_progress", "done", "archived"])
    t.add_argument("--json", action="store_true")
    t = _sub(ps, "done", "Mark a ledger project done (covers its skills).", [
        "python -m candid project done \"Churn model\"",
    ])
    t.add_argument("name", help="Ledger project name")
    t = _sub(ps, "rm", "Remove a project from the ledger.", [
        "python -m candid project rm \"Churn model\"",
    ])
    t.add_argument("name", help="Ledger project name")
    s.set_defaults(func=cmd_project)

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
