"""candid draft: context-aware email drafter.

Builds email drafts from your tracker state and thread history. Drafts are
printed or saved to files for you to review, copy, and send yourself.
Nothing here ever sends email.
"""

from __future__ import annotations

import json


def _dump(obj):
    print(json.dumps(obj, indent=2, default=str))


def _base_context(company, app_id=None):
    from candid.drafting import context as CX
    return CX.build_context(company, app_id=app_id)


def _print_draft(d):
    print(f"Subject: {d.get('subject', '')}\n")
    print(d.get("body", ""))
    missing = d.get("missing")
    if missing:
        print(f"\n[needs your input: {', '.join(missing)}]")


def context(a):
    _dump(_base_context(a.company, app_id=a.app_id))


def thread(a):
    from candid.drafting import threads as T
    s = T.summarize_thread(a.company)
    print(f"Thread history: {s.get('company', a.company)}\n")
    for b in s.get("bullets", []):
        print(f"- {b}")
    if s.get("last_contact"):
        print(f"\nLast contact: {s['last_contact']}")
    for q in s.get("open_questions", []):
        print(f"Open: {q}")


def _enrich(ctx, a):
    for key in ("contact_name", "role", "last_contact_date"):
        val = getattr(a, key, None)
        if val:
            ctx[key] = val
    try:
        from candid import profile as P
        prof = P.load_profile()
        ctx.setdefault("sender_name", prof.get("name", ""))
    except Exception:
        pass
    return ctx


def generate(a):
    from candid.drafting import drafts as D, hygiene as H, personalize as P
    ctx = _enrich(_base_context(a.company, app_id=a.app_id), a)
    d = D.generate(a.kind, ctx, tone=a.tone)
    if a.personalize:
        try:
            from candid import profile as PF
            prof = PF.load_profile()
        except Exception:
            prof = {}
        d["body"], missing = P.apply_tokens(d["body"], prof)
        d["missing"] = sorted(set(d.get("missing", [])) | set(missing))
    _print_draft(d)
    if a.check:
        issues = H.check(d)
        if issues:
            print("\nHygiene:")
            for i in issues:
                print(f"  [{i['severity']}] {i['check']}: {i['message']}")


def ladder(a):
    from candid.drafting import ladder as L
    ctx = _enrich(_base_context(a.company, app_id=a.app_id), a)
    days = ctx.get("days_since_last_contact")
    days = days if isinstance(days, int) and days >= 0 else 0
    lad = L.ladder_for(days, ctx.get("stage") or "")
    print(f"Rung {lad['rung']}: {lad['rung_name']} ({lad['tone']})")
    print(f"Guidance: {lad['guidance']}\n")
    _print_draft(L.render_ladder_draft(lad, ctx))


def followups(a):
    from candid.drafting import scheduler as S
    _dump(S.suggest_followups())


def check(a):
    from candid.drafting import hygiene as H, store as ST
    if a.draft_id:
        d = ST.get_draft(a.draft_id)
    else:
        d = {"subject": a.subject or "", "body": a.body or ""}
    issues = H.check(d)
    if not issues:
        print("Clean: no issues found.")
    for i in issues:
        print(f"[{i['severity']}] {i['check']}: {i['message']}")


def send_time(a):
    from candid.drafting import hygiene as H
    st = H.best_send_time()
    print(f"Best window: {st['weekday']}, {st['window']}")
    print(f"Rationale: {st['rationale']}")


def revise(a):
    from candid.drafting import revise as R, store as ST
    if a.draft_id:
        d = ST.get_draft(a.draft_id)
        d = {"subject": d.get("subject", ""), "body": d.get("body", "")}
    else:
        d = {"subject": a.subject or "", "body": a.body or ""}
    r = R.revise(d, a.instruction or "")
    _print_draft(r)
    if r.get("applied"):
        print(f"\n[applied: {', '.join(r['applied'])}]")
    if a.save_to and a.app_id:
        did = ST.save_draft(a.app_id, {"subject": r["subject"], "body": r["body"]},
                            kind=a.save_to)
        print(f"\nSaved as {did}")


def save(a):
    from candid.drafting import store as ST
    did = ST.save_draft(a.app_id, {"subject": a.subject, "body": a.body},
                        kind=a.kind)
    print(f"Saved draft {did} for app {a.app_id}")


def list_drafts(a):
    from candid.drafting import store as ST
    for d in ST.list_drafts(a.app_id):
        print(f"{d['draft_id']}  [{d.get('kind') or '-'}]  {d.get('created', '')}")


def show(a):
    from candid.drafting import store as ST
    _print_draft(ST.get_draft(a.draft_id))


def diff(a):
    from candid.drafting import store as ST
    print(ST.diff_drafts(a.a, a.b) or "(identical)")


def voice_learn(a):
    from candid.drafting import voice as V
    with open(a.samples_file) as f:
        samples = json.load(f)
    _dump(V.learn_style(samples))
