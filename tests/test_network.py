"""Tests for the networking follow-up cadence manager (batch 65).

Covers all 10 features: contacts, sequences, touchpoints, warmth,
value-add, reminders, intros, checkins, thanks, report - plus CLI wiring.

Data paths are redirected into a temp dir by monkeypatching candid.config
attributes (same approach as tests/test_cli_ux.py).
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid.network import (  # noqa: E402
    checkins as CH,
    contacts as CT,
    intros as IN,
    reminders as R,
    report as RP,
    sequences as SQ,
    thanks as TH,
    touchpoints as TP,
    valueadd as VA,
    warmth as W,
)

TODAY = date(2026, 9, 22)


@pytest.fixture()
def net(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DATA_DIR", tmp_path / "candid_data")
    return tmp_path


def _contact(**kw):
    base = dict(name="Jane Doe", role="Eng Manager", company="Acme",
                met_at="2026-09-10", met_at_event="DataConf",
                notes="ML infra", tags=["ml"], value=4)
    base.update(kw)
    return CT.add_contact(**base)


# --- 1. contacts -----------------------------------------------------------

def test_add_and_get_contact(net):
    c = _contact()
    assert c["id"] == 1
    assert CT.get_contact(1)["name"] == "Jane Doe"


def test_add_contact_requires_name(net):
    with pytest.raises(ValueError):
        CT.add_contact("   ")


def test_add_contact_value_range(net):
    with pytest.raises(ValueError):
        _contact(value=9)


def test_search_contacts(net):
    _contact(name="Jane Doe", company="Acme")
    _contact(name="Sam Lee", company="Beta")
    hits = CT.search_contacts("acme")
    assert [h["name"] for h in hits] == ["Jane Doe"]
    assert len(CT.search_contacts("")) == 2


def test_update_and_remove_contact(net):
    c = _contact()
    CT.update_contact(c["id"], role="VP Eng", value=5)
    assert CT.get_contact(c["id"])["role"] == "VP Eng"
    removed = CT.remove_contact(c["id"])
    assert removed["name"] == "Jane Doe"
    with pytest.raises(ValueError):
        CT.get_contact(c["id"])


# --- 2. sequences ----------------------------------------------------------

def test_sequence_templates_exist(net):
    assert "conference" in SQ.templates()
    assert len(SQ.templates()) >= 6


def test_start_sequence_schedules_due_dates(net):
    c = _contact()
    seq = SQ.start_sequence(c["id"], "conference", start_on="2026-09-10")
    assert seq["steps"][0]["due"] == "2026-09-10"
    assert seq["steps"][1]["due"] == "2026-09-11"
    assert seq["steps"][-1]["due"] == "2026-10-10"
    assert all(s["status"] == "pending" for s in seq["steps"])


def test_start_sequence_bad_template(net):
    c = _contact()
    with pytest.raises(ValueError):
        SQ.start_sequence(c["id"], "nope")


def test_start_sequence_bad_contact(net):
    with pytest.raises(ValueError):
        SQ.start_sequence(999, "conference")


def test_complete_and_skip_steps(net):
    c = _contact()
    seq = SQ.start_sequence(c["id"], "meetup", start_on="2026-09-10")
    SQ.complete_step(seq["id"], 0, today=TODAY)
    SQ.skip_step(seq["id"], 1)
    got = SQ.get_sequence(seq["id"])
    assert got["steps"][0]["status"] == "done"
    assert got["steps"][0]["completed_on"] == "2026-09-22"
    assert got["steps"][1]["status"] == "skipped"
    done, total = SQ.sequence_progress(got)
    assert (done, total) == (1, 3)


def test_due_steps(net):
    c = _contact()
    SQ.start_sequence(c["id"], "meetup", start_on="2026-09-10")
    due = SQ.due_steps(TODAY)
    assert len(due) == 2  # offsets 0, 2 due by Sep 22; offset 21 -> Oct 1
    assert due[0][1]["due"] <= due[1][1]["due"]


# --- 3. touchpoints --------------------------------------------------------

def test_log_touch_and_history(net):
    c = _contact()
    TP.log_touch(c["id"], "email", notes="intro note", happened_on="2026-09-11")
    TP.log_touch(c["id"], "coffee", happened_on="2026-09-12")
    hist = TP.touchpoints_for(c["id"])
    assert len(hist) == 2
    assert hist[0]["kind"] == "coffee"  # newest first
    assert TP.days_since_last_touch(c["id"], TODAY) == 10


def test_log_touch_bad_kind(net):
    c = _contact()
    with pytest.raises(ValueError):
        TP.log_touch(c["id"], "telepathy")


def test_log_touch_bad_contact(net):
    with pytest.raises(ValueError):
        TP.log_touch(999, "email")


# --- 4. warmth -------------------------------------------------------------

def test_warmth_fresh_contact_is_cold(net):
    c = _contact(met_at="2026-01-01")
    score = W.warmth_score(c["id"], TODAY)
    assert score < 15
    assert W.tier(score) == "cold"


def test_warmth_rises_with_touches(net):
    c = _contact(met_at="2026-09-20")
    TP.log_touch(c["id"], "coffee", happened_on="2026-09-21")
    TP.log_touch(c["id"], "intro_made", happened_on="2026-09-21")
    s = W.warmth_summary(c["id"], TODAY)
    assert s["tier"] in ("warm", "active")
    assert s["touch_count"] == 2
    assert s["days_since_last_touch"] == 1


def test_warmth_decays_over_time(net):
    c = _contact(met_at="2026-09-21")
    TP.log_touch(c["id"], "coffee", happened_on="2026-09-21")
    fresh = W.warmth_score(c["id"], date(2026, 9, 22))
    stale = W.warmth_score(c["id"], date(2027, 9, 22))
    assert stale < fresh


def test_warmth_tier_boundaries():
    assert W.tier(70) == "warm"
    assert W.tier(69.9) == "active"
    assert W.tier(40) == "active"
    assert W.tier(39.9) == "cooling"
    assert W.tier(15) == "cooling"
    assert W.tier(14.9) == "cold"


def test_all_warmth_sorted(net):
    a = _contact(name="A Warm", met_at="2026-09-21")
    b = _contact(name="B Cold", met_at="2026-01-01")
    TP.log_touch(a["id"], "coffee", happened_on="2026-09-21")
    ranked = W.all_warmth(TODAY)
    assert ranked[0]["name"] == "A Warm"
    assert ranked[-1]["name"] == "B Cold"


# --- 5. value-add ----------------------------------------------------------

def test_suggest_ideas(net):
    c = _contact(notes="hiring ML engineers", tags=["ml"])
    ideas = VA.suggest_ideas(c["id"], n=3)
    assert len(ideas) == 3
    assert all("kind" in i and "title" in i for i in ideas)
    # deterministic: same contact, same ideas
    assert [i["kind"] for i in VA.suggest_ideas(c["id"], n=3)] == \
        [i["kind"] for i in ideas]


def test_draft_value_add(net):
    c = _contact()
    draft = VA.draft_value_add("Alex", c["id"], "article",
                               detail="the new scaling paper")
    assert "Subject:" in draft
    assert "the new scaling paper" in draft
    assert "Jane" in draft
    with pytest.raises(ValueError):
        VA.draft_value_add("Alex", c["id"], "nope")


# --- 6. reminders ----------------------------------------------------------

def test_due_followups_bucketing(net):
    c = _contact()
    SQ.start_sequence(c["id"], "meetup", start_on="2026-09-10")
    buckets = R.due_followups(TODAY, upcoming_days=30)
    assert len(buckets["overdue"]) == 2  # offsets 0, 2
    assert len(buckets["today"]) == 0
    assert len(buckets["upcoming"]) == 1  # offset 21 -> Oct 1
    assert buckets["overdue"][0]["contact"] == "Jane Doe"


def test_reengagement_nudges(net):
    c = _contact(name="Quiet Valuable", value=5, met_at="2026-01-01")
    nudges = R.reengagement_nudges(TODAY)
    assert any(n["contact_id"] == c["id"] for n in nudges)
    low = _contact(name="Quiet Low", value=1, met_at="2026-01-01")
    assert not any(n["contact_id"] == low["id"] for n in nudges)


def test_render_due(net):
    c = _contact()
    SQ.start_sequence(c["id"], "meetup", start_on="2026-09-10")
    out = R.render_due(TODAY)
    assert "OVERDUE" in out
    assert "Jane Doe" in out


# --- 7. intros -------------------------------------------------------------

def test_intro_ask_and_email(net):
    a = _contact(name="Sam Lee", role="ML Engineer", company="Beta")
    b = _contact(name="Jane Doe", role="Eng Manager", company="Acme")
    ask = IN.intro_ask("Alex", a["id"], b["id"], context="ML infra roles")
    assert "Sam Lee" in ask and "Jane" in ask
    assert "ML infra roles" in ask
    email = IN.intro_email("Alex", a["id"], b["id"],
                           shared_context="ML infra hiring")
    assert "Intro: Sam Lee <> Jane Doe" in email
    assert "BCC" in email
    with pytest.raises(ValueError):
        IN.intro_email("Alex", a["id"], a["id"])


def test_intro_checklist():
    assert "double opt-in" in IN.intro_checklist().lower()


# --- 8. checkins -----------------------------------------------------------

def test_checkin_plan(net):
    cold = _contact(name="Cold Star", value=5, met_at="2026-01-01")
    warm = _contact(name="Warm Star", value=5, met_at="2026-09-21")
    TP.log_touch(warm["id"], "coffee", happened_on="2026-09-21")
    plan = CH.build_plan(TODAY, batch_size=5)
    names = [p["name"] for p in plan["this_week"]]
    assert "Cold Star" in names
    assert "Warm Star" not in names
    assert plan["this_week"][0]["idea"] is not None
    rendered = CH.render_plan(plan)
    assert "re-engagement plan" in rendered


def test_checkin_plan_empty(net):
    plan = CH.build_plan(TODAY)
    assert plan["total_candidates"] == 0
    assert "warm" in CH.render_plan(plan).lower()


# --- 9. thanks -------------------------------------------------------------

def test_thank_you_kinds():
    for kind in ("referral", "intro", "advice", "help"):
        draft = TH.thank_you("Alex", "Jane Doe", kind=kind,
                             what="Data Scientist @ Acme",
                             specifics="the prep call")
        assert "Subject:" in draft
        assert "Timing:" in draft
        assert "Jane" in draft
    with pytest.raises(ValueError):
        TH.thank_you("Alex", "Jane", kind="nope")


def test_thank_you_tones():
    concise = TH.thank_you("Alex", "Jane Doe", tone="concise")
    formal = TH.thank_you("Alex", "Jane Doe", tone="formal")
    assert len(concise) < len(formal)
    assert "Dear Jane Doe" in formal


# --- 10. report ------------------------------------------------------------

def test_report_stats(net):
    c = _contact(met_at="2026-09-20", value=4)
    TP.log_touch(c["id"], "coffee", happened_on="2026-09-21")
    SQ.start_sequence(c["id"], "meetup", start_on="2026-09-20")
    st = RP.stats(TODAY)
    assert st["contacts_total"] == 1
    assert st["touchpoints_recent"] == 1
    assert st["touchpoints_by_kind"] == {"coffee": 1}
    assert st["sequences_total"] == 1
    assert len(st["warmest"]) == 1


def test_report_render_and_export(net, tmp_path):
    _contact()
    st = RP.stats(TODAY)
    md = RP.render_report(st)
    assert md.startswith("# Networking report")
    out = RP.export_report(TODAY, path=str(tmp_path / "rep.md"))
    assert out.exists()
    assert "Networking report" in out.read_text()


def test_report_empty(net):
    st = RP.stats(TODAY)
    assert st["contacts_total"] == 0
    assert st["avg_warmth"] == 0.0
    assert "none" in RP.render_report(st).lower()


# --- CLI wiring ------------------------------------------------------------

def test_cli_network_help(net):
    from candid import __main__ as CLI
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            CLI.main(["network", "--help"])
        except SystemExit as e:
            assert e.code == 0
    assert "add-contact" in buf.getvalue()


def test_cli_network_end_to_end(net, capsys):
    from candid import __main__ as CLI
    CLI.main(["network", "add-contact", "--name", "CLI Person",
              "--company", "Acme", "--value", "4"])
    out = capsys.readouterr().out
    assert "Added contact #1" in out
    CLI.main(["network", "warmth"])
    assert "CLI Person" in capsys.readouterr().out
    CLI.main(["network", "templates"])
    assert "conference" in capsys.readouterr().out


def test_cli_network_typo_suggests(net, capsys):
    from candid import __main__ as CLI
    with pytest.raises(SystemExit):
        CLI.main(["netwrok"])
    err = capsys.readouterr().err
    assert "network" in err
