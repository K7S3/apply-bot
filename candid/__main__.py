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
import json
import sys


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
        sys.exit("No JD available: pass --jd, or curate the job first so its description is stored.")
    return M.fetch_jd(src)


def _job_meta_for(app_id: int) -> dict:
    from candid import jobs as J
    from candid import tracker as T
    apps = T.list_apps()
    if not any(a["id"] == app_id for a in apps):
        sys.exit(f"No tracked application with id {app_id}.")
    return J.get_job_meta(app_id)


def _company_role_from_app(a) -> tuple[str, str]:
    """Fill --company/--role from a tracker record when --app-id is given."""
    from candid import tracker as T
    company, role = a.company or "", a.role or ""
    if getattr(a, "app_id", None):
        rec = next((x for x in T.list_apps() if x["id"] == a.app_id), None)
        if rec is None:
            sys.exit(f"No tracked application with id {a.app_id}.")
        company = company or rec["company"]
        role = role or rec["role"]
    return company, role


def cmd_match(a):
    from candid import match as M
    jd = _jd_text(a)
    company, role = _company_role_from_app(a)
    result = M.score_match(_profile(), jd, title=role, company=company,
                           location=a.location or "")
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
        print(f"Added application #{rec['id']}: {rec['role']} @ {rec['company']} [{rec['status']}]")
    elif a.what == "list":
        apps = T.list_apps(status=a.status, company=a.company)
        print(T.render_list(apps))
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
    elif a.what in ("list", "compare"):
        print(O.render_comparison(O.list_offers()))


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
        print(S.render_lookup(S.lookup(company=a.company or "", title=a.title or "",
                                       location=a.location or ""),
                              company=a.company or "", title=a.title or "",
                              location=a.location or ""))
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
            sys.exit("Provide --text or --jd.")
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
    if a.what == "curate" or a.what == "refresh":
        if not a.role:
            sys.exit("--role is required (e.g. --role \"Data Scientist\").")
        fn = J.refresh if a.what == "refresh" else J.curate
        result = fn(_profile(), role=a.role, location=a.location or "",
                    remote=a.remote, level=a.level, limit=a.limit,
                    sources=a.sources or None)
        print(J.render_curated(result))
    elif a.what == "list":
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m candid",
                                description="The generic job-search copilot.")
    sub = p.add_subparsers(dest="cmd", required=True)

    # onboard
    s = sub.add_parser("onboard", help="Ingest resume/LinkedIn into your profile.")
    s.add_argument("--resume", help="Resume file (.pdf/.md/.txt)")
    s.add_argument("--linkedin", help="LinkedIn export file (.txt/.md)")
    s.add_argument("--out", help="Where to write profile.json (default: candid_data/)")
    s.set_defaults(func=cmd_onboard)

    # profile
    s = sub.add_parser("profile", help="Show your stored profile.")
    s.add_argument("what", nargs="?", default="show", choices=["show"])
    s.set_defaults(func=cmd_profile_show)

    # match
    s = sub.add_parser("match", help="Score a job description against your profile.")
    s.add_argument("--jd", default="", help="JD text, file path, URL, or - for stdin")
    s.add_argument("--app-id", type=int, default=None,
                   help="Tracked job id — pulls company/role/JD from the tracker")
    s.add_argument("--company", default="", help="Company name")
    s.add_argument("--role", default="", help="Role title")
    s.add_argument("--location", default="", help="Location")
    s.set_defaults(func=cmd_match)

    # tailor
    s = sub.add_parser("tailor", help="Tailored resume / cover letter.")
    s.add_argument("what", choices=["resume", "cover-letter"])
    s.add_argument("--jd", default="", help="JD text, file path, URL, or - for stdin")
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
    s = sub.add_parser("track", help="Application tracker.")
    ts = s.add_subparsers(dest="what", required=True)
    t = ts.add_parser("add"); t.add_argument("--company", required=True); t.add_argument("--role", required=True)
    t.add_argument("--jd-link", default=""); t.add_argument("--status", default="saved")
    t.add_argument("--notes", default="")
    t = ts.add_parser("list"); t.add_argument("--status", default=None); t.add_argument("--company", default=None)
    t = ts.add_parser("update"); t.add_argument("id", type=int)
    t.add_argument("--status", default=None); t.add_argument("--notes", default=None)
    t = ts.add_parser("remove"); t.add_argument("id", type=int)
    t = ts.add_parser("stats")
    s.set_defaults(func=cmd_track)

    # prep
    s = sub.add_parser("prep", help="Build an interview prep pack.")
    s.add_argument("--company", required=True)
    s.add_argument("--role", required=True)
    s.add_argument("--jd", default="", help="JD text, file path, URL, or - for stdin")
    s.add_argument("--location", default="")
    s.add_argument("--app-id", type=int, default=None, help="Tracker id to link the pack to")
    s.set_defaults(func=cmd_prep)

    # followup
    s = sub.add_parser("followup", help="Draft thank-you / check-in / referral emails.")
    fs = s.add_subparsers(dest="what", required=True)
    for name in ("thank-you", "check-in", "referral"):
        t = fs.add_parser(name)
        t.add_argument("--person", required=True, help="Interviewer / recruiter / contact name")
        t.add_argument("--role", required=True); t.add_argument("--company", required=True)
        t.add_argument("--tone", default="warm", choices=["warm", "formal", "concise"])
        if name == "thank-you":
            t.add_argument("--topics", default=""); t.add_argument("--standout", default="")
        elif name == "check-in":
            t.add_argument("--last-contact", default="")
        else:
            t.add_argument("--topics", default="", help="Your connection to them")
    s.set_defaults(func=cmd_followup)

    # offer
    s = sub.add_parser("offer", help="Record and compare offers.")
    os_ = s.add_subparsers(dest="what", required=True)
    t = os_.add_parser("add")
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
    t.add_argument("--start", dest="start_date", default=""); t.add_argument("--notes", default="")
    os_.add_parser("list"); os_.add_parser("compare")
    s.set_defaults(func=cmd_offer)

    # negotiate
    s = sub.add_parser("negotiate", help="Negotiation playbook, scripts, counter drafts.")
    ns = s.add_subparsers(dest="what", required=True)
    ns.add_parser("playbook")
    t = ns.add_parser("script"); t.add_argument("--which", required=True,
        choices=["lowball_anchor", "competing_offer", "exploding_deadline", "level_pushback"])
    t.add_argument("--set", action="append", default=[], help="key=value template fields")
    t = ns.add_parser("counter")
    t.add_argument("--person", required=True); t.add_argument("--role", required=True)
    t.add_argument("--company", required=True); t.add_argument("--location", default="")
    t.add_argument("--base-ask", required=True); t.add_argument("--second-item", default="Sign-on bonus")
    t.add_argument("--second-ask", default=""); t.add_argument("--target", default="")
    t.add_argument("--call-time", default="tomorrow")
    s.set_defaults(func=cmd_negotiate)

    # salary
    s = sub.add_parser("salary", help="Salary intelligence database.")
    ss = s.add_subparsers(dest="what", required=True)
    t = ss.add_parser("lookup")
    t.add_argument("--company", default=""); t.add_argument("--title", default="")
    t.add_argument("--location", default="")
    t = ss.add_parser("import-lca"); t.add_argument("file"); t.add_argument("--limit", type=int, default=None)
    t = ss.add_parser("parse-range")
    t.add_argument("--company", required=True); t.add_argument("--role", required=True)
    t.add_argument("--jd", default=""); t.add_argument("--text", default="")
    t.add_argument("--location", default="")
    s.set_defaults(func=cmd_salary)

    # mock
    s = sub.add_parser("mock", help="Mock interviews: coding judge, AI interviewer, behavioral, design.")
    ms = s.add_subparsers(dest="what", required=True)
    t = ms.add_parser("list", help="List coding problems")
    t.add_argument("--topic", default=None); t.add_argument("--difficulty", default=None)
    t = ms.add_parser("coding", help="Interactive coding session")
    t.add_argument("--topic", default=None); t.add_argument("--difficulty", default=None)
    t.add_argument("--problem", default=None); t.add_argument("--file", default=None)
    t = ms.add_parser("run", help="Judge a solution file non-interactively")
    t.add_argument("--problem", required=True); t.add_argument("--file", required=True)
    t = ms.add_parser("solution", help="Show reference solution + complexity")
    t.add_argument("--problem", required=True)
    t = ms.add_parser("hint", help="Show hints for a problem")
    t.add_argument("--problem", required=True)
    t = ms.add_parser("ai", help="Conversational AI interviewer (uses Gemini)")
    t.add_argument("--track", default="coding", choices=["coding", "behavioral", "ml"])
    t.add_argument("--topic", default=None); t.add_argument("--difficulty", default=None)
    t.add_argument("--problem", default=None)
    t = ms.add_parser("behavioral", help="STAR behavioral practice")
    t.add_argument("--theme", default=None); t.add_argument("--ai", action="store_true")
    t = ms.add_parser("design", help="System design practice")
    t.add_argument("--level", default=None); t.add_argument("--ai", action="store_true")
    s.set_defaults(func=cmd_mock)

    # jobs
    s = sub.add_parser("jobs", help="Curate open jobs and feed the tracker.")
    js = s.add_subparsers(dest="what", required=True)
    t = js.add_parser("curate", help="Discover jobs, score them, save the best as 'saved'")
    t.add_argument("--role", required=True, help="Wanted title, e.g. \"Data Scientist\"")
    t.add_argument("--location", default="")
    t.add_argument("--remote", action="store_true")
    t.add_argument("--level", default=None, help="entry|junior|mid|senior|lead|staff|principal")
    t.add_argument("--limit", type=int, default=15)
    t.add_argument("--sources", nargs="*", default=None, help="subset of: arbeitnow remoteok")
    t = js.add_parser("refresh", help="Re-run curation; report only new jobs")
    t.add_argument("--role", required=True)
    t.add_argument("--location", default="")
    t.add_argument("--remote", action="store_true")
    t.add_argument("--level", default=None)
    t.add_argument("--limit", type=int, default=15)
    t.add_argument("--sources", nargs="*", default=None)
    js.add_parser("list", help="Show the curated pipeline (status=saved)")
    s.set_defaults(func=cmd_jobs)

    # dashboard
    s = sub.add_parser("dashboard", help="Launch the local web dashboard (127.0.0.1 only).")
    s.add_argument("--port", type=int, default=8765, help="Preferred port (tries the next 10 if busy)")
    s.add_argument("--no-browser", action="store_true", help="Don't auto-open the browser")
    s.set_defaults(func=cmd_dashboard)

    # import (general entry point for user-supplied exports)
    s = sub.add_parser("import", help="Import your own data exports (mbox, LinkedIn ZIP, ...).")
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
    s = sub.add_parser("gmail", help="Gmail Takeout mbox import: parse, propose, confirm.")
    gs = s.add_subparsers(dest="what", required=True)
    t = gs.add_parser("import", help="Import a Google Takeout .mbox file (or directory of them).")
    t.add_argument("file", help="Path to the .mbox file or a directory of .mbox files")
    t.add_argument("--max", type=int, default=0, help="Max messages to read (0 = all)")
    t = gs.add_parser("proposals", help="List pending Gmail proposals.")
    t = gs.add_parser("confirm", help="Confirm a proposal -> writes to the tracker.")
    t.add_argument("id", type=int)
    t = gs.add_parser("reject", help="Dismiss a proposal.")
    t.add_argument("id", type=int)
    gs.add_parser("guide", help="How to export Gmail via Google Takeout.")
    s.set_defaults(func=cmd_gmail)

    # linkedin
    s = sub.add_parser("linkedin", help="Import LinkedIn's official data export (no scraping).")
    ls = s.add_subparsers(dest="what", required=True)
    t = ls.add_parser("import", help="Import a LinkedIn export ZIP into your profile.")
    t.add_argument("--zip", required=True, help="Path to the LinkedIn export .zip")
    t.add_argument("--mode", default="merge", choices=["merge", "replace"],
                   help="merge: fold into existing profile (default); replace: overwrite")
    ls.add_parser("guide", help="How to download your LinkedIn data export.")
    s.set_defaults(func=cmd_linkedin)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except Exception as e:  # friendly errors, no tracebacks
        etype = type(e).__name__
        if etype in ("OnboardError", "MatchError", "TrackerError", "PrepError",
                     "OfferError", "SalaryError", "MockError", "JudgeError",
                     "GmailError", "LinkedInError", "DashboardError",
                     "ValueError"):
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
