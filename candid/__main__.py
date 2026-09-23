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
    "followup", "offer", "negotiate", "salary", "mock", "jobs",
    "dashboard", "deadlines", "import", "gmail", "linkedin", "bulk",
    "refreq", "schedule", "thanks", "note", "attach", "packet",
    "references", "reapproach",
]

SUBCOMMANDS = {
    "profile": ["show"],
    "tailor": ["resume", "cover-letter"],
    "track": ["add", "list", "update", "remove", "stats", "search", "export-csv"],
    "followup": ["thank-you", "check-in", "referral"],
    "offer": ["add", "list", "compare", "export", "deadline"],
    "refreq": ["add", "list", "update", "remind"],
    "schedule": ["parse", "reply"],
    "thanks": ["plan", "list", "mark-sent"],
    "note": ["add", "list"],
    "attach": ["add", "list"],
    "references": ["add", "list"],
    "reapproach": ["add", "list", "due", "mark", "remove"],
    "negotiate": ["playbook", "script", "counter"],
    "salary": ["lookup", "import-lca", "parse-range"],
    "mock": ["list", "coding", "run", "solution", "hint", "ai",
             "behavioral", "design"],
    "jobs": ["curate", "refresh", "list"],
    "gmail": ["import", "proposals", "confirm", "reject", "guide"],
    "linkedin": ["import", "guide"],
}

#: Expected (non-bug) failures: reported cleanly, no tracebacks.
_EXPECTED_ERRORS = {
    "OnboardError", "MatchError", "TrackerError", "PrepError",
    "OfferError", "SalaryError", "MockError", "JudgeError",
    "GmailError", "LinkedInError", "DashboardError", "JobsError",
    "ValueError",
    "BulkError", "RefRequestError", "SchedulingError", "ThankYouError",
    "OfferDeadlineError", "ReapproachError", "AppNotesError", "PacketError",
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
    "BulkError": "python -m candid bulk --help",
    "RefRequestError": "python -m candid refreq --help",
    "SchedulingError": "python -m candid schedule --help",
    "ThankYouError": "python -m candid thanks --help",
    "OfferDeadlineError": "python -m candid offer deadline --help",
    "ReapproachError": "python -m candid reapproach --help",
    "AppNotesError": "python -m candid track list",
    "PacketError": "python -m candid tailor --help",
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


def cmd_bulk(a):
    from candid import bulk as B
    prof = _profile()  # raises OnboardError with next step if missing
    out = B.score_all(prof, jd_dir=a.jd_dir or None,
                      jd_files=a.jd_files or None,
                      manifest=a.manifest or None,
                      min_score=a.min_score)
    if a.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(B.render_table(out["results"], top=a.top))
        for w in out["warnings"]:
            print(f"warning: {w}", file=sys.stderr)


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
        rec = T.update(a.id, status=a.status, notes=a.notes, deadline=a.deadline)
        print(f"Updated #{rec['id']}: status={rec['status']}")
        if rec.get("deadline"):
            print(f"  deadline: {rec['deadline']}")
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
    elif a.what == "deadline":
        cmd_offer_deadline(a)


def _parse_weight_list(text):
    """Parse 'comp=5,growth=4,team=3' into {criterion: float}."""
    out = {}
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = float(v)
    return out


def cmd_offer_deadline(a):
    from candid import offer_deadlines as OD
    if a.deadline_what == "set":
        if a.clear:
            removed = OD.remove_deadline(a.id)
            print(f"Deadline removed for offer #{a.id}." if removed
                  else f"No deadline was set for offer #{a.id}.")
        else:
            rec = OD.set_deadline(a.id, a.date)
            print(f"Deadline set: offer #{a.id} ({rec['company']}) — "
                  f"decide by {rec['decision_deadline']}")
    elif a.deadline_what == "list":
        print(OD.render_countdown())
    elif a.deadline_what == "remove":
        removed = OD.remove_deadline(a.id)
        print(f"Deadline removed for offer #{a.id}." if removed
              else f"No deadline was set for offer #{a.id}.")
    elif a.deadline_what == "decide":
        import json as _json
        weights = _parse_weight_list(a.weights)
        scores = _json.loads(a.scores) if a.scores else {}
        scores = {int(k): v for k, v in scores.items()}
        print(OD.render_decision(weights, scores=scores))


def cmd_reapproach(a):
    from candid import reapproach as R
    if a.what == "add":
        rec = R.add(a.company, a.last_contact, reason=a.reason)
        print(f"Watching #{rec['id']} {rec['company']} — retry "
              f"{rec['retry_6mo']} (6mo) / {rec['retry_12mo']} (12mo)")
    elif a.what == "list":
        print(R.render_list())
    elif a.what == "due":
        print(R.render_due())
    elif a.what == "mark":
        rec = R.mark(a.company_or_id, a.status)
        print(f"#{rec['id']} {rec['company']} marked {rec['status']}.")
    elif a.what == "remove":
        print("Removed." if R.remove(a.company_or_id)
              else f"No watchlist entry for '{a.company_or_id}'.")


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


# ---------------------------------------------------------------------------
# batch-4 dispatchers: deadlines, refreq, schedule, thanks,
#                     note, attach, packet, references
# ---------------------------------------------------------------------------

def cmd_deadlines(a):
    """List upcoming application deadlines, most urgent first."""
    from candid import dashboard as D
    rows = D.deadline_alerts()
    days = getattr(a, "days", None)
    if days is not None:
        rows = [r for r in rows if r["days_remaining"] <= days]
    if not rows:
        print("No application deadlines on the books.")
        print("Set one with: python -m candid track update ID --deadline YYYY-MM-DD")
        return
    print(f"{len(rows)} deadline(s):")
    for r in rows:
        dr = r["days_remaining"]
        when = f"{-dr}d OVERDUE" if dr < 0 else "due TODAY" if dr == 0 else f"{dr}d left"
        print(f"  [{r['bucket']}] {r['company']} — {r['role']} "
              f"({r['deadline']}, {when}) [{r['status']}]")


def cmd_refreq(a):
    from candid import refrequests as R
    prof = _profile()
    name = prof.get("name") or "Your Name"
    if a.what == "add":
        rec = R.add(a.contact, a.company, a.role,
                    connection=a.connection or "", status=a.status,
                    notes=a.notes or "")
        if rec.get("duplicate"):
            print(f"Already tracked as request #{rec['id']} - not duplicated.")
        else:
            print(f"Added referral request #{rec['id']}: {rec['contact']} - "
                  f"{rec['role']} @ {rec['company']} [{rec['status']}]")
        print()
        print("Draft the ask (copy, edit, send yourself):")
        print(R.draft(rec["id"], name=name))
        print(f"\nAfter sending: python -m candid refreq update {rec['id']} --status sent")
    elif a.what == "list":
        print(R.render_list(R.list_requests(status=a.status or None)))
    elif a.what == "update":
        rec = R.update(a.id, status=a.status or None, note=a.note or "")
        print(f"Updated request #{rec['id']} -> {rec['status']}.")
    elif a.what == "remind":
        rems = R.remind(days=a.days, name=name)
        print(R.render_reminders(rems))


def cmd_schedule(a):
    from candid import scheduling as S
    if a.what == "parse":
        text = S.read_source(a.source, file=a.file,
                             stdin_text=None if sys.stdin.isatty() else sys.stdin.read())
        print(S.render_parse(S.parse_invite(text)))
    elif a.what == "reply":
        prof = _profile()
        name = prof.get("name") or "Your Name"
        raw = a.source or a.file
        parsed = None
        if raw or not sys.stdin.isatty():
            text = S.read_source(a.source, file=a.file,
                                 stdin_text=None if sys.stdin.isatty() else sys.stdin.read())
            parsed = S.parse_invite(text)
            unconfirmed = parsed["needs_confirm"]
            if unconfirmed:
                print("The invite has ambiguities - confirm these before "
                      "sending your reply:")
                for f in unconfirmed:
                    print(f"  - {f}")
                print()
        print(S.reply_draft(name, interviewer=a.person or "", role=a.role or "",
                            company=a.company or "", slots=a.slots, parsed=parsed))


def cmd_thanks(a):
    from candid import thankyou as TK
    prof = _profile()
    name = prof.get("name") or "Your Name"
    if a.what == "plan":
        people = []
        for spec in (a.person or []):
            parts = [p.strip() for p in spec.split(":", 1)]
            iv = {"name": parts[0], "round": parts[1] if len(parts) > 1 else ""}
            if not people:  # --topics/--standout feed the first step's draft
                iv["topics"] = a.topics or ""
                iv["standout"] = a.standout or ""
            people.append(iv)
        seq = TK.plan(a.app_id, role=a.role, company=a.company, interviewers=people)
        print(TK.render_sequence(seq))
        print()
        for st in seq["steps"]:
            print(f"--- step {st['step']}: {st['interviewer']} ---")
            print(TK.draft(a.app_id, st["step"], name=name))
            print()
    elif a.what == "list":
        seqs = TK.list_sequences(status=a.status or None)
        if a.app_id is not None:
            seqs = [s for s in seqs if s["app_id"] == a.app_id]
        if not seqs:
            print("No thank-you sequences yet. "
                  "Plan one with `python -m candid thanks plan`.")
        else:
            print("\n\n".join(TK.render_sequence(s) for s in seqs))
            print()
            print(TK.render_pending(TK.pending_steps()))
    elif a.what == "mark-sent":
        seq = TK.mark_sent(a.app_id, a.step)
        print(TK.render_sequence(seq))


def cmd_note(a):
    from candid import appnotes as A
    if a.what == "add":
        entry = A.add_note(a.app_id, a.text)
        print(f"Note added to application #{a.app_id} [{entry['timestamp']}].")
    elif a.what == "list":
        print(A.render_notes(a.app_id, A.list_notes(a.app_id)))


def cmd_attach(a):
    from candid import appnotes as A
    if a.what == "add":
        rec = A.attach(a.app_id, a.src)
        mb = rec["size_bytes"] / 1024 / 1024
        print(f"Attached {rec['filename']} ({mb:.1f} MiB) "
              f"to application #{a.app_id}.")
    elif a.what == "list":
        print(A.render_attachments(a.app_id, A.list_attachments(a.app_id)))


def cmd_packet(a):
    from candid import packet as P
    from candid import match as M
    jd = M.fetch_jd(a.jd) if a.jd else ""
    out = a.out or f"packet-{a.app_id}.pdf"
    dest = P.save_packet(a.app_id, out, jd=jd,
                         company=a.company or "", role=a.role or "",
                         tone=a.tone, length=a.length, hook=a.hook or "",
                         include_references=a.include_references)
    print(f"Packet saved to {dest}")


def cmd_references(a):
    from candid import packet as P
    if a.what == "add":
        rec = P.add_reference(a.name, a.relationship, contact=a.contact or "")
        print(f"Added reference: {rec['name']} ({rec['relationship']}).")
    elif a.what == "list":
        print(P.render_references(P.list_references()))


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

    # bulk
    s = _sub(sub, "bulk", "Score many JDs at once and rank them by fit.", [
        "python -m candid bulk --jd-dir ./jds/",
        "python -m candid bulk --jd-files a.txt b.txt --top 10",
        "python -m candid bulk --jd-dir ./jds/ --manifest meta.csv --min-score 60 --json",
        "python -m candid bulk --jd-dir ./jds/ --json > ranked.json   # scripting",
    ])
    s.add_argument("--jd-dir", default="",
                   help="Directory of JD text files (.txt/.md, non-recursive)")
    s.add_argument("--jd-files", nargs="+", default=[],
                   help="Explicit JD file paths (combined with --jd-dir)")
    s.add_argument("--manifest", default="",
                   help="CSV with file,company,role columns to override "
                        "filename metadata (e.g. AcmeCorp__Data-Scientist.txt)")
    s.add_argument("--top", type=int, default=None,
                   help="Show only the top N results")
    s.add_argument("--min-score", type=float, default=0.0,
                   help="Only show results scoring at least this (0-100)")
    s.add_argument("--json", action="store_true",
                   help="Print {results, warnings} as JSON (for scripting)")
    s.set_defaults(func=cmd_bulk)

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
        "python -m candid track update 3 --deadline 2026-10-01",
    ])
    t.add_argument("id", type=int)
    t.add_argument("--status", default=None); t.add_argument("--notes", default=None)
    t.add_argument("--deadline", default=None,
                   help="Application deadline (YYYY-MM-DD; empty string clears it)")
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
    # offer decision deadlines
    od = _sub(os_, "deadline", "Manage decision deadlines on offers.", [
        "python -m candid offer deadline set --id 1 --date 2026-10-15",
        "python -m candid offer deadline list",
    ])
    # distinct dest so it does not clobber the outer "what"
    ods = od.add_subparsers(dest="deadline_what", required=True,
                            title="subcommands", metavar="<subcommand>",
                            parser_class=CandidParser)

    t = _sub(ods, "set", "Set or clear a decision deadline on an offer.", [
        "python -m candid offer deadline set --id 1 --date 2026-10-15",
        "python -m candid offer deadline set --id 1 --clear",
    ])
    t.add_argument("--id", type=int, required=True,
                   help="Offer id (see: python -m candid offer list)")
    t.add_argument("--date", default="",
                   help="Decision deadline, YYYY-MM-DD")
    t.add_argument("--clear", action="store_true",
                   help="Remove the deadline instead of setting it")

    _sub(ods, "list", "Deadline countdown, most urgent first.", [
        "python -m candid offer deadline list",
    ])

    t = _sub(ods, "remove", "Remove a decision deadline.", [
        "python -m candid offer deadline remove --id 1",
    ])
    t.add_argument("--id", type=int, required=True,
                   help="Offer id (see: python -m candid offer list)")

    t = _sub(ods, "decide",
             "Ranked weighted comparison of offers.", [
                 "python -m candid offer deadline decide "
                 "--weights comp=5,growth=4,team=3,location=2,stability=3 "
                 "--scores '{\"1\": {\"growth\": 8, \"team\": 7}}'",
             ])
    t.add_argument("--weights", default="",
                   help="Comma list k=v, e.g. "
                        "comp=5,growth=4,team=3,location=2,stability=3")
    t.add_argument("--scores", default="",
                   help="JSON {\"offer_id\": {\"growth\": 8, \"team\": 7, ...}}; "
                        "comp is derived from the offers, not scored")
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

    # deadlines
    s = _sub(sub, "deadlines", "Upcoming application deadlines, most urgent first.", [
        "python -m candid deadlines",
        "python -m candid deadlines --days 7",
    ])
    s.add_argument("--days", type=int, default=None,
                   help="Only show deadlines within N days (e.g. --days 7)")
    s.set_defaults(func=cmd_deadlines)

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

    # refreq
    s = _sub(sub, "refreq", "Track referral requests: draft, status, reminders.", [
        "python -m candid refreq add --contact \"Priya Nair\" --company Acme --role \"ML Engineer\"",
        "python -m candid refreq list",
        "python -m candid refreq update 1 --status sent",
        "python -m candid refreq remind",
    ])
    rs = _nested(s)
    t = _sub(rs, "add", "Add a referral request and print the ask draft.", [
        "python -m candid refreq add --contact \"Priya Nair\" --company Acme --role \"ML Engineer\" --connection \"your ranking stack work\"",
    ])
    t.add_argument("--contact", required=True, help="Contact name")
    t.add_argument("--company", required=True); t.add_argument("--role", required=True)
    t.add_argument("--connection", default="", help="Your connection to them / why you're excited")
    t.add_argument("--status", default="drafted",
                   choices=["drafted", "sent", "reminded", "connected", "declined"])
    t.add_argument("--notes", default="")
    t = _sub(rs, "list", "List tracked referral requests.", [
        "python -m candid refreq list",
        "python -m candid refreq list --status sent",
    ])
    t.add_argument("--status", default=None,
                   choices=["drafted", "sent", "reminded", "connected", "declined"])
    t = _sub(rs, "update", "Update a request's status and/or append a note.", [
        "python -m candid refreq update 1 --status sent",
        "python -m candid refreq update 1 --status connected --note \"referred 2026-09-22\"",
    ])
    t.add_argument("id", type=int, help="Request id from `refreq list`")
    t.add_argument("--status", default=None,
                   choices=["drafted", "sent", "reminded", "connected", "declined"])
    t.add_argument("--note", default="")
    t = _sub(rs, "remind", "Nudge list: sent requests quiet longer than --days.", [
        "python -m candid refreq remind",
        "python -m candid refreq remind --days 10",
    ])
    t.add_argument("--days", type=int, default=7,
                   help="Quiet-day threshold (default 7)")
    s.set_defaults(func=cmd_refreq)

    # schedule
    s = _sub(sub, "schedule", "Parse an interview invite; draft a scheduling reply.", [
        "python -m candid schedule parse --file invite.txt",
        "python -m candid schedule reply --company Acme --role \"ML Engineer\" --slots \"Tue 2-4pm ET\" \"Wed 10am-12pm ET\"",
    ])
    ss = _nested(s)
    t = _sub(ss, "parse", "Parse pasted invite text into dates/times/timezone/interviewers/links.", [
        "python -m candid schedule parse --file invite.txt",
        "cat invite.txt | python -m candid schedule parse",
    ])
    t.add_argument("source", nargs="?", default=None,
                   help="Invite text or a file path; omit to read stdin")
    t.add_argument("--file", default=None, help="Read the invite from this file")
    t = _sub(ss, "reply", "Draft a reply proposing 2-3 time slots.", [
        "python -m candid schedule reply --company Acme --role \"ML Engineer\" --slots \"Tue 2-4pm ET\" \"Wed 10am-12pm ET\"",
        "python -m candid schedule reply --file invite.txt --slots \"Tue 2-4pm ET\" \"Wed 10am-12pm ET\"",
    ])
    t.add_argument("source", nargs="?", default=None,
                   help="Invite text or a file path; omit to read stdin (optional context)")
    t.add_argument("--file", default=None, help="Read the invite from this file")
    t.add_argument("--slots", nargs="+", required=True,
                   help="2-3 proposed slots, e.g. \"Tue 2-4pm ET\"")
    t.add_argument("--person", default="", help="Interviewer / recruiter name")
    t.add_argument("--role", default=""); t.add_argument("--company", default="")
    s.set_defaults(func=cmd_schedule)

    # thanks
    s = _sub(sub, "thanks", "Per-application thank-you sequences, one step per interviewer.", [
        "python -m candid thanks plan --app-id 3 --company Acme --role \"ML Engineer\" --person \"Jane Doe: phone screen\"",
        "python -m candid thanks list",
        "python -m candid thanks mark-sent --app-id 3 --step 1",
    ])
    ts = _nested(s)
    t = _sub(ts, "plan", "Plan a thank-you sequence for an application and print the drafts.", [
        "python -m candid thanks plan --app-id 3 --company Acme --role \"ML Engineer\" --person \"Jane Doe: phone screen\" --person \"Sam Reed: onsite\"",
    ])
    t.add_argument("--app-id", type=int, required=True, help="Application id from `track list`")
    t.add_argument("--company", required=True); t.add_argument("--role", required=True)
    t.add_argument("--person", action="append", default=[],
                   help='Interviewer as "Name" or "Name: round" (repeatable)')
    t.add_argument("--topics", default="", help="Topics for the first step's draft")
    t.add_argument("--standout", default="", help="Standout moment for the first step's draft")
    t = _sub(ts, "list", "List thank-you sequences and pending steps.", [
        "python -m candid thanks list",
        "python -m candid thanks list --status pending",
        "python -m candid thanks list --app-id 3",
    ])
    t.add_argument("--app-id", type=int, default=None)
    t.add_argument("--status", default=None, choices=["pending", "sent"])
    t = _sub(ts, "mark-sent", "Mark one thank-you step as sent.", [
        "python -m candid thanks mark-sent --app-id 3 --step 1",
    ])
    t.add_argument("--app-id", type=int, required=True)
    t.add_argument("--step", type=int, required=True, help="Step number from `thanks list`")
    s.set_defaults(func=cmd_thanks)

    # note
    s = _sub(sub, "note", "Per-application timestamped notes.", [
        'python -m candid note add --app-id 3 "met hiring manager at meetup"',
        "python -m candid note list --app-id 3",
    ])
    ns = _nested(s)
    n = _sub(ns, "add", "Add a timestamped note to a tracked application.", [
        'python -m candid note add --app-id 3 "referral from Sam"',
    ])
    n.add_argument("--app-id", type=int, required=True,
                   help="Tracked application id")
    n.add_argument("text", help="Note text")
    n = _sub(ns, "list", "List notes for a tracked application.", [
        "python -m candid note list --app-id 3",
    ])
    n.add_argument("--app-id", type=int, required=True,
                   help="Tracked application id")
    s.set_defaults(func=cmd_note)

    # attach
    s = _sub(sub, "attach", "File attachments per application.", [
        "python -m candid attach add --app-id 3 resume_tailored.pdf",
        "python -m candid attach list --app-id 3",
    ])
    ns = _nested(s)
    t = _sub(ns, "add", "Attach a file (copied into the git-ignored data dir).", [
        "python -m candid attach add --app-id 3 offer_letter.pdf",
    ])
    t.add_argument("--app-id", type=int, required=True,
                   help="Tracked application id")
    t.add_argument("src", help="File to attach")
    t = _sub(ns, "list", "List attachments for a tracked application.", [
        "python -m candid attach list --app-id 3",
    ])
    t.add_argument("--app-id", type=int, required=True,
                   help="Tracked application id")
    s.set_defaults(func=cmd_attach)

    # packet
    s = _sub(sub, "packet",
             "Export one PDF: tailored resume + cover letter (+ references).", [
                 "python -m candid packet --app-id 3",
                 "python -m candid packet --app-id 3 --include-references --out packet-acme.pdf",
                 "python -m candid packet --app-id 3 --jd jd.txt --tone formal",
             ])
    s.add_argument("--app-id", type=int, required=True,
                   help="Tracked application id")
    s.add_argument("--jd", default="",
                   help="JD text/file/URL/- (falls back to the curated JD for the app)")
    s.add_argument("--company", default=""); s.add_argument("--role", default="")
    s.add_argument("--tone", default="confident",
                   choices=["concise", "confident", "formal", "warm"])
    s.add_argument("--length", default="one-page",
                   choices=["one-page", "detailed"])
    s.add_argument("--hook", default="",
                   help="One-line 'why this company' for the cover letter")
    s.add_argument("--include-references", action="store_true",
                   help="Append the references page (requires saved references)")
    s.add_argument("--out", default="",
                   help="Write to file (default: packet-<app-id>.pdf in cwd)")
    s.set_defaults(func=cmd_packet)

    # references
    s = _sub(sub, "references", "Manage your reference list.", [
        'python -m candid references add --name "Sam Rivera" '
        '--relationship "former manager" --contact sam@example.com',
        "python -m candid references list",
    ])
    ns = _nested(s)
    r = _sub(ns, "add", "Add a reference.", [
        'python -m candid references add --name "Sam Rivera" '
        '--relationship "former manager"',
    ])
    r.add_argument("--name", required=True)
    r.add_argument("--relationship", required=True,
                   help="e.g. former manager, colleague, professor")
    r.add_argument("--contact", default="", help="Email or phone")
    r = _sub(ns, "list", "List saved references.", [
        "python -m candid references list",
    ])
    s.set_defaults(func=cmd_references)

    # reapproach
    s = _sub(sub, "reapproach",
             "Track companies worth re-approaching after 6-12 months.", [
                 "python -m candid reapproach add --company Acme "
                 "--last-contact 2026-09-01 --reason \"hiring freeze\"",
                 "python -m candid reapproach list",
                 "python -m candid reapproach due",
                 "python -m candid reapproach mark Acme "
                 "--status re-approached",
             ])
    rs = _nested(s)

    t = _sub(rs, "add", "Add a company to the re-approach watchlist.", [
        "python -m candid reapproach add --company Acme "
        "--last-contact 2026-09-01 --reason \"hiring freeze\"",
    ])
    t.add_argument("--company", required=True)
    t.add_argument("--last-contact", dest="last_contact", required=True,
                   help="Last contact date, YYYY-MM-DD")
    t.add_argument("--reason", default="",
                   help="Why it is worth retrying later")

    _sub(rs, "list", "List the watchlist, soonest retry date first.", [
        "python -m candid reapproach list",
    ])

    _sub(rs, "due", "Show companies whose retry date has arrived.", [
        "python -m candid reapproach due",
    ])

    t = _sub(rs, "mark", "Change a watchlist entry's status.", [
        "python -m candid reapproach mark Acme --status re-approached",
    ])
    t.add_argument("company_or_id", help="Company name or numeric id")
    t.add_argument("--status", required=True,
                   choices=["watching", "due", "re-approached"])

    t = _sub(rs, "remove", "Remove a watchlist entry.", [
        "python -m candid reapproach remove Acme",
    ])
    t.add_argument("company_or_id", help="Company name or numeric id")

    s.set_defaults(func=cmd_reapproach)

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
