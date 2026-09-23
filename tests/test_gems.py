"""Tests for candid.gems — hidden-gem scoring engine.

Run: python -m pytest tests/test_gems.py -q
"""
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import gems
from candid.gems import (
    GEM_THRESHOLD,
    employer_ranking,
    gem_score,
    is_megacorp,
    sleeper_posting,
    top_gems,
)

PROFILE = {
    "name": "Test User",
    "skills": ["python", "machine learning", "sql", "deep learning"],
    "years_experience": 5,
    "seniority": "senior",
    "experience": [{"title": "Senior Data Scientist", "company": "OldCorp"}],
}

DS_DESC = ("We need Python and machine learning for our ranking team. "
           "5+ years of experience with SQL and deep learning required. "
           "Requirements: Python, SQL, machine learning.")


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def _job(**kw) -> dict:
    base = {
        "source": "greenhouse",
        "source_id": "gh:1",
        "title": "Senior Data Scientist",
        "company": "Northwind Labs",
        "location": "New York, NY",
        "url": "https://example.com/1",
        "description": DS_DESC,
        "salary_text": "",
        "remote": False,
        "posted_at": _days_ago(1),
    }
    base.update(kw)
    return base


class TestGemScoreContract(unittest.TestCase):
    def test_returns_all_contract_keys(self):
        g = gem_score(_job())
        self.assertEqual(set(g.keys()),
                         {"gem_score", "fit_score", "signals", "reasons",
                          "sleeper", "megacorp"})

    def test_scores_in_range(self):
        g = gem_score(_job(), PROFILE, [_job()])
        self.assertGreaterEqual(g["gem_score"], 0)
        self.assertLessEqual(g["gem_score"], 100)
        for v in g["signals"].values():
            self.assertGreaterEqual(v, 0)
            self.assertLessEqual(v, 100)

    def test_signal_keys(self):
        g = gem_score(_job())
        self.assertEqual(set(g["signals"].keys()),
                         {"freshness", "repost_rarity", "company_volume",
                          "source_niche", "salary_opacity", "remote_pool"})

    def test_no_profile_gives_none_fit_and_pure_competition(self):
        g = gem_score(_job(), all_jobs=[_job()])
        self.assertIsNone(g["fit_score"])
        comp_signals = g["signals"]
        self.assertAlmostEqual(g["gem_score"], sum(
            comp_signals[k] * gems._SIGNAL_WEIGHTS[k] for k in comp_signals),
            places=1)

    def test_profile_gives_fit_and_blend(self):
        job = _job()
        g = gem_score(job, PROFILE, [job])
        self.assertIsNotNone(g["fit_score"])
        self.assertGreaterEqual(g["fit_score"], 0)
        self.assertLessEqual(g["fit_score"], 100)
        comp = sum(g["signals"][k] * gems._SIGNAL_WEIGHTS[k]
                   for k in g["signals"])
        self.assertAlmostEqual(g["gem_score"], 0.65 * g["fit_score"] + 0.35 * comp,
                               places=1)

    def test_reasons_is_list_of_strings(self):
        g = gem_score(_job(), PROFILE, [_job()])
        self.assertIsInstance(g["reasons"], list)
        self.assertTrue(all(isinstance(r, str) for r in g["reasons"]))
        self.assertTrue(g["reasons"])

    def test_sleeper_and_megacorp_are_bools(self):
        g = gem_score(_job())
        self.assertIsInstance(g["sleeper"], bool)
        self.assertIsInstance(g["megacorp"], bool)

    def test_missing_keys_do_not_crash(self):
        g = gem_score({})
        self.assertIn("gem_score", g)
        self.assertGreaterEqual(g["gem_score"], 0)

    def test_threshold_constant(self):
        self.assertEqual(GEM_THRESHOLD, 60.0)

    def test_json_serializable(self):
        g = gem_score(_job(), PROFILE, [_job()])
        json.dumps(g)

    def test_deterministic(self):
        job, batch = _job(), [_job()]
        self.assertEqual(gem_score(job, PROFILE, batch),
                         gem_score(job, PROFILE, batch))

    def test_high_fit_beats_low_fit_same_competition(self):
        good = _job(source_id="gh:good")
        bad = _job(source_id="gh:bad", title="Junior Barista",
                   description="Make espresso and pour lattes. Smile.")
        batch = [good, bad]
        self.assertGreater(gem_score(good, PROFILE, batch)["gem_score"],
                           gem_score(bad, PROFILE, batch)["gem_score"])


class TestSignalDirections(unittest.TestCase):
    def _comp(self, job, batch=None):
        return gem_score(job, all_jobs=batch)["gem_score"]

    def test_fresher_beats_staler(self):
        fresh = _job(source_id="a", posted_at=_days_ago(1))
        stale = _job(source_id="b", posted_at=_days_ago(20))
        self.assertGreater(self._comp(fresh, [fresh]),
                           self._comp(stale, [stale]))

    def test_stale_past_window_scores_zero_freshness(self):
        job = _job(posted_at=_days_ago(60))
        self.assertEqual(gem_score(job)["signals"]["freshness"], 0.0)

    def test_fewer_reposts_beats_many(self):
        solo = _job(source_id="s1", title="Unique Title Xyz")
        dup = _job(source_id="d1", title="Common Title")
        batch = [solo] + [dict(dup, source_id=f"d{i}") for i in range(4)]
        self.assertGreater(gem_score(solo, all_jobs=batch)["signals"]["repost_rarity"],
                           gem_score(dup, all_jobs=batch)["signals"]["repost_rarity"])

    def test_niche_source_beats_mass_source(self):
        niche = _job(source="hn_hiring")
        mass = _job(source="arbeitnow")
        self.assertGreater(gem_score(niche)["signals"]["source_niche"],
                           gem_score(mass)["signals"]["source_niche"])

    def test_unknown_source_neutral(self):
        g = gem_score(_job(source="some_new_board"))
        self.assertEqual(g["signals"]["source_niche"], 55.0)

    def test_salary_transparency_penalized(self):
        opaque = _job(salary_text="")
        disclosed = _job(salary_text="$150k - $180k")
        self.assertGreater(gem_score(opaque)["signals"]["salary_opacity"],
                           gem_score(disclosed)["signals"]["salary_opacity"])

    def test_remote_penalized(self):
        onsite = _job(remote=False)
        remote = _job(remote=True)
        self.assertGreater(gem_score(onsite)["signals"]["remote_pool"],
                           gem_score(remote)["signals"]["remote_pool"])

    def test_low_company_volume_beats_high(self):
        small = _job(company="Tiny Startup Qq")
        big = _job(company="Big Employer Zz")
        batch = [small] + [dict(big, source_id=f"b{i}") for i in range(12)]
        self.assertGreater(
            gem_score(small, all_jobs=batch)["signals"]["company_volume"],
            gem_score(big, all_jobs=batch)["signals"]["company_volume"])

    def test_unparseable_date_neutral_freshness(self):
        g = gem_score(_job(posted_at="not a date"))
        self.assertEqual(g["signals"]["freshness"], 50.0)


class TestMegacorp(unittest.TestCase):
    def _batch(self, company, n):
        return [_job(source_id=f"{company}:{i}", company=company,
                     title=f"Role {i}") for i in range(n)]

    def test_top_volume_company_is_megacorp(self):
        jobs = self._batch("Acme Mega", 12) + self._batch("Tiny", 1)
        self.assertTrue(is_megacorp("Acme Mega", jobs))

    def test_small_company_not_megacorp(self):
        jobs = self._batch("Acme Mega", 12)
        for i in range(11):  # 12 distinct companies -> Tiny misses top-10
            jobs += self._batch(f"Tiny{i}", 1)
        self.assertFalse(is_megacorp("Tiny9", jobs))

    def test_top_n_parameter(self):
        jobs = self._batch("Big", 10) + self._batch("Mid", 5) + self._batch("Small", 1)
        self.assertTrue(is_megacorp("Mid", jobs, top_n=2))
        self.assertFalse(is_megacorp("Mid", jobs, top_n=1))

    def test_known_giant_by_name(self):
        self.assertTrue(is_megacorp("Google", []))
        self.assertTrue(is_megacorp("Meta Platforms Inc", []))
        self.assertTrue(is_megacorp("Amazon Web Services", []))

    def test_unknown_company_empty_batch(self):
        self.assertFalse(is_megacorp("Northwind Labs", []))

    def test_empty_company_name(self):
        self.assertFalse(is_megacorp("", self._batch("Acme", 5)))

    def test_case_insensitive(self):
        jobs = self._batch("Acme Mega", 12)
        self.assertTrue(is_megacorp("ACME MEGA", jobs))


class TestSleeper(unittest.TestCase):
    def test_old_posting_is_sleeper(self):
        self.assertTrue(sleeper_posting(_job(posted_at=_days_ago(60))))

    def test_recent_posting_not_sleeper(self):
        self.assertFalse(sleeper_posting(_job(posted_at=_days_ago(2))))

    def test_boundary_45_days(self):
        # 44 vs 46 avoids time-of-day fuzz on the exact 45-day boundary
        self.assertFalse(sleeper_posting(_job(posted_at=_days_ago(44))))
        self.assertTrue(sleeper_posting(_job(posted_at=_days_ago(46))))

    def test_unparseable_date_not_sleeper(self):
        self.assertFalse(sleeper_posting(_job(posted_at="someday")))

    def test_gem_sleeper_flag_stricter_with_reposts(self):
        old = _job(source_id="o1", posted_at=_days_ago(60), title="Old Role")
        batch = [old] + [dict(old, source_id=f"o{i}") for i in range(2, 5)]
        g = gem_score(old, all_jobs=batch)
        self.assertTrue(sleeper_posting(old))
        self.assertFalse(g["sleeper"])  # 4 copies -> too crowded to be a sleeper


class TestEmployerRanking(unittest.TestCase):
    def _batch(self):
        jobs = []
        for i in range(12):
            jobs.append(_job(source_id=f"mega:{i}", company="Acme MegaCorp",
                             title=f"Engineer {i}", salary_text="$100k - $120k",
                             posted_at=_days_ago(i % 5)))
        jobs.append(_job(source_id="gem:1", company="Quixotic Data Labs",
                         title="ML Engineer", salary_text="$150k - $180k"))
        jobs.append(_job(source_id="gem:2", company="Quixotic Data Labs",
                         title="Data Engineer", salary_text=""))
        return jobs

    def test_entry_keys(self):
        r = employer_ranking(self._batch())
        self.assertTrue(r)
        self.assertEqual(set(r[0].keys()),
                         {"company", "postings", "obscurity",
                          "median_salary_usd", "velocity", "gem_employer_score"})

    def test_obscure_employer_outranks_megacorp(self):
        r = employer_ranking(self._batch())
        scores = {e["company"]: e["gem_employer_score"] for e in r}
        self.assertGreater(scores["Quixotic Data Labs"], scores["Acme MegaCorp"])
        self.assertEqual(r[0]["company"], "Quixotic Data Labs")

    def test_postings_counted(self):
        r = employer_ranking(self._batch())
        counts = {e["company"]: e["postings"] for e in r}
        self.assertEqual(counts["Acme MegaCorp"], 12)
        self.assertEqual(counts["Quixotic Data Labs"], 2)

    def test_median_salary(self):
        r = employer_ranking(self._batch())
        med = {e["company"]: e["median_salary_usd"] for e in r}
        self.assertAlmostEqual(med["Acme MegaCorp"], 110000.0)
        self.assertAlmostEqual(med["Quixotic Data Labs"], 165000.0)

    def test_median_salary_none_when_undisclosed(self):
        r = employer_ranking([_job(company="Stealth Co", salary_text="")])
        self.assertIsNone(r[0]["median_salary_usd"])

    def test_obscurity_range_and_direction(self):
        r = employer_ranking(self._batch())
        obs = {e["company"]: e["obscurity"] for e in r}
        for v in obs.values():
            self.assertGreaterEqual(v, 0)
            self.assertLessEqual(v, 100)
        self.assertGreater(obs["Quixotic Data Labs"], obs["Acme MegaCorp"])

    def test_velocity_positive(self):
        r = employer_ranking(self._batch())
        for e in r:
            self.assertGreater(e["velocity"], 0)

    def test_empty_input(self):
        self.assertEqual(employer_ranking([]), [])

    def test_json_serializable(self):
        json.dumps(employer_ranking(self._batch()))

    def test_deterministic(self):
        batch = self._batch()
        self.assertEqual(employer_ranking(batch), employer_ranking(batch))


class TestTopGems(unittest.TestCase):
    def _batch(self, n=6):
        jobs = []
        for i in range(n):
            jobs.append(_job(source_id=f"g:{i}", company=f"Boutique {i}",
                             title=f"Data Scientist {i}",
                             posted_at=_days_ago(1 + i)))
        # one stale, low-quality job that should miss the threshold
        jobs.append(_job(source_id="bad:1", company="Acme MegaCorp",
                         title="Data Scientist", source="arbeitnow",
                         remote=True, salary_text="$90k - $110k",
                         posted_at=_days_ago(30),
                         description="Make espresso and pour lattes."))
        return jobs

    def test_attaches_gem_key(self):
        out = top_gems(self._batch(), PROFILE)
        self.assertTrue(out)
        for j in out:
            self.assertIn("_gem", j)
            self.assertIn("gem_score", j["_gem"])

    def test_sorted_descending(self):
        out = top_gems(self._batch(), PROFILE)
        scores = [j["_gem"]["gem_score"] for j in out]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_threshold_applied(self):
        out = top_gems(self._batch(), PROFILE)
        for j in out:
            self.assertGreaterEqual(j["_gem"]["gem_score"], GEM_THRESHOLD)

    def test_limit_respected(self):
        out = top_gems(self._batch(10), PROFILE, limit=3)
        self.assertLessEqual(len(out), 3)

    def test_exclude_megacorps(self):
        out = top_gems(self._batch(), PROFILE, exclude_megacorps=True)
        for j in out:
            self.assertFalse(j["_gem"]["megacorp"])
        self.assertNotIn("Acme MegaCorp", [j["company"] for j in out])

    def test_min_fit_filters(self):
        batch = self._batch()
        fits = [gem_score(j, PROFILE, batch)["fit_score"] for j in batch]
        cutoff = max(f for f in fits if f is not None)
        out = top_gems(batch, PROFILE, min_fit=cutoff)
        self.assertTrue(out)
        for j in out:
            self.assertGreaterEqual(j["_gem"]["fit_score"], cutoff)

    def test_min_fit_zero_keeps_no_profile_jobs(self):
        out = top_gems(self._batch(), profile=None, min_fit=0.0)
        self.assertTrue(out)

    def test_min_fit_positive_drops_no_profile_jobs(self):
        out = top_gems(self._batch(), profile=None, min_fit=10.0)
        self.assertEqual(out, [])

    def test_does_not_mutate_inputs(self):
        batch = self._batch()
        snapshot = [dict(j) for j in batch]
        top_gems(batch, PROFILE)
        for orig, now in zip(snapshot, batch):
            self.assertEqual(orig, now)
            self.assertNotIn("_gem", now)

    def test_empty_input(self):
        self.assertEqual(top_gems([]), [])

    def test_limit_zero(self):
        self.assertEqual(top_gems(self._batch(), PROFILE, limit=0), [])

    def test_json_serializable(self):
        json.dumps(top_gems(self._batch(), PROFILE))

    def test_deterministic(self):
        batch = self._batch()
        first = top_gems(batch, PROFILE)
        second = top_gems(batch, PROFILE)
        self.assertEqual(
            [j["_gem"]["gem_score"] for j in first],
            [j["_gem"]["gem_score"] for j in second])


if __name__ == "__main__":
    unittest.main()
