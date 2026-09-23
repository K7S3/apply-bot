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
    python -m candid master init --resume resume.md
    python -m candid bullets score resume.md
    python -m candid linkedin optimize
    python -m candid narrative
    python -m candid redteam --resume resume.md

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
    "followup", "offer", "negotiate", "salary", "mock", "jobs",
    "dashboard", "import", "gmail", "linkedin", "master", "bullets",
    "narrative", "narrative-arc", "pitch", "references",
    "networking-brief", "portfolio", "redteam", "pivot",
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
    "jobs": ["curate", "refresh", "list"],
    "gmail": ["import", "proposals", "confirm", "reject", "guide"],
    "linkedin": ["import", "guide", "optimize", "polish-about"],
    "master": ["init", "show", "update", "diff", "lineage"],
    "bullets": ["score", "reword"],
    "references": ["add", "list", "remove", "sheet"],
    "portfolio": ["describe", "section"],
    "pivot": ["suggest", "reframe", "plan", "brief"],
}

#: Expected (non-bug) failures: reported cleanly, no tracebacks.
_EXPECTED_ERRORS = {
    "OnboardError", "MatchError", "TrackerError", "PrepError",
    "OfferError", "SalaryError", "MockError", "JudgeError",
    "GmailError", "LinkedInError", "DashboardError", "JobsError",
    "MasterResumeError", "BulletScorerError", "LinkedInOptimizeError",
    "NarrativeError", "ReferencesError", "NetworkingError",
    "PortfolioError", "RedTeamError", "PivotError",
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
    "MasterResumeError": "python -m candid master --help",
    "BulletScorerError": "python -m candid bullets --help",
    "LinkedInOptimizeError": "python -m candid linkedin optimize --help",
    "NarrativeError": "python -m candid narrative --help",
    "ReferencesError": "python -m candid references --help",
    "NetworkingError": "python -m candid networking-brief --help",
    "PortfolioError": "python -m candid portfolio --help",
    "RedTeamError": "python -m candid redteam --help",
    "PivotError": "python -m candid pivot --help",
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
    elif a.what == "optimize":
        _cmd_linkedin_optimize(a)
    elif a.what == "polish-about":
        _cmd_linkedin_polish_about(a)


def cmd_master(a):
    from candid import master_resume as M
    if a.what == "init":
        meta = M.init_master(resume_path=a.resume, note=a.note or "")
        print(f"Master resume initialized: {meta['version_id']} "
              f"({meta.get('note', '')}) — source: {meta['source']}")
        print("Tailored variants are derived from this master and traced back to it.")
    elif a.what == "show":
        cur = M.get_master()
        print(f"Master resume {cur['version_id']} — {cur.get('note', '')}")
        print()
        print(cur["markdown"])
    elif a.what == "update":
        with open(a.file, encoding="utf-8") as f:
            text = f.read()
        meta = M.update_master(text, note=a.note or "")
        if meta.get("unchanged"):
            print(f"No changes — master is still {meta['version_id']}.")
        else:
            print(f"Master updated to {meta['version_id']} "
                  f"({meta.get('note', '')}). History kept under master_resume/versions/.")
    elif a.what == "diff":
        print(M.diff_versions(a.v1, a.v2))
    elif a.what == "lineage":
        lin = M.lineage(a.variant_id)
        print(f"Variant {lin.get('variant_id', a.variant_id)} was derived from "
              f"master {lin.get('master_version', '?')} "
              f"({lin.get('kind', '')}, {lin.get('recorded_at', '')}).")


def cmd_bullets(a):
    from candid import bullet_scorer as B
    if a.what == "score":
        res = B.score_file(a.file)
        print(f"Bullet score: {res['overall']}/100 across {res['bullet_count']} bullets\n")
        for s in res["bullets"]:
            print(f"[{s['score']:>3}] {s['bullet']}")
            for fl in s["flags"]:
                print(f"       - {fl['type']}: {fl.get('detail', '')}")
        if res["fixes"]:
            print("\nFix first (lowest score first):")
            for fx in res["fixes"]:
                print(f"  [{fx['score']}] {fx['bullet']}")
                line = f"    issue: {fx['top_issue']}"
                if fx.get("detail"):
                    line += f" — {fx['detail']}"
                print(line)
                if fx.get("question"):
                    print(f"    ask yourself: {fx['question']}")
    else:
        prof = _profile()
        r = B.suggest_reword(a.text, prof.get("skills") or None)
        print(f"Original:  {r['original']}")
        print(f"Reworded:  {r['reworded']}")
        if not r["changed"]:
            print("(no weak lead-in found — bullet left as-is)")
        for n in r["notes"]:
            print(f"  note: {n}")
        for q in r["questions"]:
            print(f"  question: {q}")
        print("Grounded: only facts already in the bullet were used — nothing invented.")


def _cmd_linkedin_optimize(a):
    from candid import linkedin_optimize as L
    report = L.full_report(_profile(), open_to_work=a.open_to_work)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"LinkedIn optimization report saved to {a.out}")
    else:
        print(report)


def _cmd_linkedin_polish_about(a):
    from candid import linkedin_optimize as L
    if a.file:
        with open(a.file, encoding="utf-8") as f:
            text = f.read()
    elif a.text:
        text = a.text
    else:
        sys.exit("Provide --text or --file.\n"
                 "Next: run `python -m candid linkedin polish-about --help`.")
    res = L.polish_about(text, _profile())
    print(res["polished"])
    if a.voice_notes:
        print("\nVoice preserved:")
        for v in res["voice_notes"]:
            print(f"  - {v}")
    if a.changes:
        print("\nChanges made:")
        for c in res["changes"]:
            print(f"  - {c}")


def cmd_narrative(a):
    from candid import narrative as N
    print(N.build_narrative(_profile(), length=a.length))


def cmd_narrative_arc(a):
    from candid import narrative as N
    print(N.story_arc(_profile()))


def cmd_pitch(a):
    from candid import narrative as N
    print(N.elevator_pitch(_profile(), audience=a.audience))


def cmd_references(a):
    from candid import references as R
    if a.what == "add":
        ref = R.add_reference(a.name, a.relationship,
                              contact=a.contact or "", notes=a.notes or "")
        print(f"Added reference: {ref['name']} ({ref['relationship']})")
    elif a.what == "list":
        refs = R.list_references()
        if not refs:
            print("No references stored yet. "
                  "Add one: python -m candid references add --help")
            return
        for r in refs:
            line = f"- {r['name']} ({r['relationship']})"
            if r.get("contact"):
                line += f" — {r['contact']}"
            print(line)
            if r.get("notes"):
                print(f"    notes: {r['notes']}")
    elif a.what == "remove":
        R.remove_reference(a.name)
        print(f"Removed reference: {a.name}")
    elif a.what == "sheet":
        prof = _profile()
        name = prof.get("name") or "Your Name"
        print(R.render_sheet(name, output=a.format, on_request=a.on_request))


def cmd_networking_brief(a):
    from candid import networking as W
    roles = [r.strip() for r in (a.roles or "").split(",") if r.strip()] or None
    path = W.save_brief(_profile(), target_roles=roles, ask=a.ask or None,
                        path=a.out or None)
    print(f"Networking brief saved to {path}")
    if roles:
        print(f"Target roles: {', '.join(roles)}")
    else:
        print("(target roles inferred from your profile — pass --roles to set them)")


def _render_repo_description(d: dict):
    print(f"# {d['headline']}")
    for b in d["bullets"]:
        print(f"- {b}")
    if d.get("caveat"):
        print(f"\n⚠️  {d['caveat']}")


def cmd_portfolio(a):
    from candid import portfolio as P
    repos = P.load_repos(a.repos)
    if a.what == "describe":
        if a.name:
            picked = [r for r in repos
                      if r.get("name", "").lower() == a.name.lower()]
            if not picked:
                sys.exit(f"No repo named {a.name!r} in {a.repos}.\n"
                         "Next: run `python -m candid portfolio describe --help`.")
            _render_repo_description(P.describe_repo(picked[0]))
        else:
            for r in repos:
                _render_repo_description(P.describe_repo(r))
                print()
    else:
        prof = _profile()
        ranked = P.rank_repos(repos, prof.get("skills") or [])
        print(P.portfolio_section(ranked, top_n=a.top_n))


def cmd_redteam(a):
    from candid import redteam as RT
    if a.resume:
        with open(a.resume, encoding="utf-8") as f:
            src = f.read()
    else:
        src = _profile()
    findings = RT.review(src)
    print(RT.hiring_manager_summary(findings))
    if findings:
        print("\nPrioritized fixes:")
        for fx in RT.prioritized_fixes(findings):
            print(f"  [{fx['severity']}] {fx['category']}: {fx['fix']}")
            print(f"       in: {fx['quote'][:120]}")
    else:
        print("\nNo issues found — this reads clean to a skeptical eye.")


def _render_pivot_reframe(r: dict) -> str:
    lines = [f"# Reframed toward: {r['target_title']}", "",
             r["honest_read"], "",
             "## Reframed summary", "", r["reframed_summary"], "",
             "## Skills to foreground", ""]
    for s in r["skills_to_foreground"]:
        lines.append(f"- {s}")
    lines += ["", "## Roles (bullets reordered by relevance, verbatim)", ""]
    for role in r["roles"]:
        lines.append(f"### {role['title']} — {role['company']} ({role['dates']})")
        lines.append(f"> {role['angle']}")
        for b in role["bullets"]:
            lines.append(f"- {b}")
        lines.append("")
    lines += ["## Credibility gaps", ""]
    for g in r["credibility_gaps"]:
        lines.append(f"- {g}")
    return "\n".join(lines).rstrip() + "\n"


def _render_pivot_plan(p: dict) -> str:
    lines = [f"# 30/60/90-day plan: {p['target_title']}", "",
             p["honest_read"], "",
             "## Gaps to close", ""]
    for g in p["gaps"]:
        lines.append(f"- {g}")
    lines += ["", "## Steps", ""]
    for s in p["steps"]:
        lines.append(f"### Day {s['phase']}: {s['action']}")
        lines.append(f"Deliverable: {s['outcome']} (addresses: {s['addresses']})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def cmd_pivot(a):
    from candid import pivot as PV
    prof = _profile()
    if a.what == "suggest":
        sug = PV.suggest_pivots(prof, n=a.n)
        if not sug:
            print("No adjacent pivots found — try a broader skill set in your profile.")
            return
        for s in sug:
            print(f"- {s['target']} ({s['overlap_pct']}% skill overlap)")
            if s["transferable"]:
                print(f"    transferable: {', '.join(s['transferable'])}")
            if s["gaps"]:
                print(f"    gaps: {', '.join(s['gaps'])}")
            if s["why"]:
                print(f"    why: {s['why']}")
    elif a.what == "reframe":
        out = _render_pivot_reframe(PV.reframe(prof, a.target))
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"Reframe saved to {a.out}")
        else:
            print(out)
    elif a.what == "plan":
        out = _render_pivot_plan(PV.pivot_plan(prof, a.target))
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"Pivot plan saved to {a.out}")
        else:
            print(out)
    elif a.what == "brief":
        out = PV.pivot_brief(prof, a.target)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"Pivot brief saved to {a.out}")
        else:
            print(out)


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
    t = _sub(ls, "optimize", "Headline variants, about draft, experience rewrite, keyword gaps.", [
        "python -m candid linkedin optimize",
        "python -m candid linkedin optimize --open-to-work",
        "python -m candid linkedin optimize --out linkedin-report.md",
    ])
    t.add_argument("--open-to-work", action="store_true",
                   help="Include an 'open to work' line in the about draft")
    t.add_argument("--out", default="",
                   help="Write the full report to a file instead of stdout")
    t = _sub(ls, "polish-about", "Clean up an existing about section, keeping your voice.", [
        'python -m candid linkedin polish-about --text "I am a data scientist..."',
        "python -m candid linkedin polish-about --file about.txt --voice-notes --changes",
    ])
    t.add_argument("--text", default="", help="The current about text")
    t.add_argument("--file", default="", help="File holding the current about text")
    t.add_argument("--voice-notes", action="store_true",
                   help="Show what voice markers were preserved")
    t.add_argument("--changes", action="store_true",
                   help="List every edit that was made")
    s.set_defaults(func=cmd_linkedin)

    # master
    s = _sub(sub, "master", "Master resume: source of truth for all variants.", [
        "python -m candid master init --resume resume.md --note \"seed from resume\"",
        "python -m candid master init   # from your onboarded profile",
        "python -m candid master show",
        "python -m candid master update new-master.md --note \"added metrics\"",
        "python -m candid master diff v0001 v0002",
        "python -m candid master lineage acme_ds_2026",
    ])
    ms_ = _nested(s)
    t = _sub(ms_, "init", "(Re-)initialize the master resume; resets version history.", [
        "python -m candid master init",
        "python -m candid master init --resume resume.md --note \"seed from resume\"",
    ])
    t.add_argument("--resume", default=None, help="Resume markdown/text file to seed from")
    t.add_argument("--note", default="", help="Note for this version")
    _sub(ms_, "show", "Show the current master resume.", [
        "python -m candid master show",
    ])
    t = _sub(ms_, "update", "Save a new master version (history kept).", [
        "python -m candid master update master-v2.md --note \"added Q3 metrics\"",
    ])
    t.add_argument("file", help="File with the new master markdown")
    t.add_argument("--note", default="", help="Note for this version")
    t = _sub(ms_, "diff", "Diff two master versions.", [
        "python -m candid master diff v0001 v0002",
    ])
    t.add_argument("v1"); t.add_argument("v2")
    t = _sub(ms_, "lineage", "Which master version a tailored variant came from.", [
        "python -m candid master lineage acme_ds_2026",
    ])
    t.add_argument("variant_id", help="Variant id recorded by the tailor step")
    s.set_defaults(func=cmd_master)

    # bullets
    s = _sub(sub, "bullets", "Score resume bullets; grounded rewording suggestions.", [
        "python -m candid bullets score resume.md",
        'python -m candid bullets reword "Responsible for maintaining the data pipeline"',
    ])
    bs = _nested(s)
    t = _sub(bs, "score", "Score every bullet in a resume markdown file (0-100).", [
        "python -m candid bullets score resume.md",
    ])
    t.add_argument("file", help="Resume markdown/text file")
    t = _sub(bs, "reword", "Suggest a stronger rewording using only the bullet's own facts.", [
        'python -m candid bullets reword "Responsible for maintaining the data pipeline"',
    ])
    t.add_argument("text", help="The bullet text to reword")
    s.set_defaults(func=cmd_bullets)

    # narrative
    s = _sub(sub, "narrative", "Your career narrative in 60 seconds or 2 minutes.", [
        "python -m candid narrative",
        "python -m candid narrative --length 2min",
    ])
    s.add_argument("--length", default="60s", choices=["60s", "2min"])
    s.set_defaults(func=cmd_narrative)

    # narrative-arc
    s = _sub(sub, "narrative-arc", "Your story arc: where you started, the turn, where you're headed.", [
        "python -m candid narrative-arc",
    ])
    s.set_defaults(func=cmd_narrative_arc)

    # pitch
    s = _sub(sub, "pitch", "Elevator pitch tuned to the audience.", [
        "python -m candid pitch",
        "python -m candid pitch --audience hiring-manager",
    ])
    s.add_argument("--audience", default="recruiter",
                   choices=["recruiter", "hiring-manager", "networking"])
    s.set_defaults(func=cmd_pitch)

    # references
    s = _sub(sub, "references", "Reference list + printable reference sheet.", [
        "python -m candid references add \"Jane Doe\" \"former manager\" --contact jane@example.com",
        "python -m candid references list",
        "python -m candid references remove \"Jane Doe\"",
        "python -m candid references sheet --format markdown --on-request",
    ])
    rs = _nested(s)
    t = _sub(rs, "add", "Add a reference.", [
        "python -m candid references add \"Jane Doe\" \"former manager\"",
        'python -m candid references add "Jane Doe" "former manager" --contact jane@example.com --notes "managed me 2022-24"',
    ])
    t.add_argument("name"); t.add_argument("relationship")
    t.add_argument("--contact", default=""); t.add_argument("--notes", default="")
    _sub(rs, "list", "List stored references.", [
        "python -m candid references list",
    ])
    t = _sub(rs, "remove", "Remove a reference.", [
        "python -m candid references remove \"Jane Doe\"",
    ])
    t.add_argument("name")
    t = _sub(rs, "sheet", "Render a reference sheet (omit contact details with --on-request).", [
        "python -m candid references sheet",
        "python -m candid references sheet --format text --on-request",
    ])
    t.add_argument("--format", dest="format", default="markdown",
                   choices=["markdown", "text"])
    t.add_argument("--on-request", action="store_true",
                   help="Print 'Available on request' instead of contact details")
    s.set_defaults(func=cmd_references)

    # networking-brief
    s = _sub(sub, "networking-brief", "One-pager for networking chats: your story + ask.", [
        "python -m candid networking-brief",
        "python -m candid networking-brief --roles \"Data Scientist,ML Engineer\" --ask \"intro to your hiring manager\"",
        "python -m candid networking-brief --out /tmp/brief.md",
    ])
    s.add_argument("--roles", default="",
                   help="Comma-separated target roles (default: inferred from profile)")
    s.add_argument("--ask", default="", help="Your ask for the conversation")
    s.add_argument("--out", default="", help="Output path (default: candid_data/networking_brief.md)")
    s.set_defaults(func=cmd_networking_brief)

    # portfolio
    s = _sub(sub, "portfolio", "Turn repos.json into resume-ready project blurbs.", [
        "python -m candid portfolio describe --repos repos.json",
        "python -m candid portfolio describe --repos repos.json --name my-project",
        "python -m candid portfolio section --repos repos.json --top-n 4",
    ])
    ps = _nested(s)
    t = _sub(ps, "describe", "Headline + resume-ready bullets for one repo or all.", [
        "python -m candid portfolio describe --repos repos.json",
        "python -m candid portfolio describe --repos repos.json --name my-project",
    ])
    t.add_argument("--repos", required=True, help="Path to repos.json")
    t.add_argument("--name", default="", help="Describe only this repo")
    t = _sub(ps, "section", "Rank repos by skill overlap; render a resume section.", [
        "python -m candid portfolio section --repos repos.json",
        "python -m candid portfolio section --repos repos.json --top-n 3",
    ])
    t.add_argument("--repos", required=True, help="Path to repos.json")
    t.add_argument("--top-n", type=int, default=4)
    s.set_defaults(func=cmd_portfolio)

    # redteam
    s = _sub(sub, "redteam", "Hostile review of a resume: vague bullets, overclaims, ATS risk.", [
        "python -m candid redteam",
        "python -m candid redteam --resume resume.md",
    ])
    s.add_argument("--resume", default="",
                   help="Resume markdown/text to review (default: your onboarded profile)")
    s.set_defaults(func=cmd_redteam)

    # pivot
    s = _sub(sub, "pivot", "Career pivots: ranked targets, reframe, 30/60/90 plan.", [
        "python -m candid pivot suggest",
        "python -m candid pivot suggest --n 3",
        'python -m candid pivot reframe --target "Product Manager"',
        'python -m candid pivot plan --target "Product Manager" --out plan.md',
        'python -m candid pivot brief --target "Product Manager"',
    ])
    pv = _nested(s)
    t = _sub(pv, "suggest", "Rank adjacent titles by transferable-skill overlap.", [
        "python -m candid pivot suggest",
        "python -m candid pivot suggest --n 3",
    ])
    t.add_argument("--n", type=int, default=5)
    for name_, desc in [
        ("reframe", "Reframe your profile toward a target title."),
        ("plan", "30/60/90-day pivot plan from the credibility gaps."),
        ("brief", "Full markdown pivot brief for a target title."),
    ]:
        t = _sub(pv, name_, desc, [
            f'python -m candid pivot {name_} --target "Product Manager"',
            f'python -m candid pivot {name_} --target "Product Manager" --out pivot-{name_}.md',
        ])
        t.add_argument("--target", required=True, help="Target job title")
        t.add_argument("--out", default="", help="Write to file instead of stdout")
    s.set_defaults(func=cmd_pivot)

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
