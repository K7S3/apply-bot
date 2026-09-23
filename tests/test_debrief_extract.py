"""Tests for the debrief extractor (candid/debrief_extract.py).

Run: python -m unittest discover -s tests
(The extractor is fully offline; only the LLM-tier test needs to fail fast
when Ollama is unreachable.)
"""

import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import debrief_extract as E  # noqa: E402


FIXTURE_TRANSCRIPT = [
    {
        "prompt": "Tell me about yourself.",
        "answer": ("I'm a data scientist with four years of experience. At my "
                   "current role I build ranking models for ads, mostly "
                   "gradient-boosted trees and some deep learning. Before that "
                   "I worked on experimentation infrastructure and A/B testing "
                   "platforms at a large consumer company."),
        "ts": "2026-09-22T10:00:00",
    },
    {
        "prompt": "Walk me through how you would debug a sudden drop in model AUC.",
        "answer": ("Hmm, let me think. Uh... first I'd check, um, data "
                   "freshness? I guess the features could have shifted. Sort "
                   "of... I'm not confident here, maybe look at the "
                   "distribution of predictions? ... Honestly I might be wrong."),
        "ts": "2026-09-22T10:05:00",
    },
    {
        "prompt": "Explain the difference between bagging and boosting.",
        "answer": ("Bagging trains models in parallel on bootstraps; boosting "
                   "fits sequentially on residuals. I was stumped on the exact "
                   "loss derivation for gradient boosting though - didn't know "
                   "the second-order expansion. I should review the XGBoost "
                   "paper and I'll follow up with a worked example."),
        "ts": "2026-09-22T10:10:00",
    },
    {
        "prompt": "Any questions for me?",
        "answer": "Just what's the team structure like?",
        "ts": "2026-09-22T10:15:00",
    },
]


class ExtractorTest(unittest.TestCase):
    def test_extract_questions_and_answers(self):
        res = E.extract(FIXTURE_TRANSCRIPT)
        self.assertEqual(len(res["key_questions"]), 4)
        self.assertIn("Tell me about yourself.", res["key_questions"])
        self.assertEqual(len(res["key_answers"]), 4)
        # answers are condensed, not the full text
        self.assertLess(len(res["key_answers"][0]),
                        len(FIXTURE_TRANSCRIPT[0]["answer"]))
        self.assertIn("data scientist", res["key_answers"][0].lower())

    def test_extract_weak_spots(self):
        res = E.extract(FIXTURE_TRANSCRIPT)
        spots = res["weak_spots"]
        self.assertGreaterEqual(len(spots), 2)
        joined = " ".join(spots).lower()
        self.assertIn("stumped", joined)
        self.assertIn("auc", joined)  # heavy hedging on the AUC question
        # the strong "about yourself" answer is not flagged
        self.assertNotIn("tell me about yourself", joined)

    def test_extract_action_items(self):
        res = E.extract(FIXTURE_TRANSCRIPT)
        items = res["action_items"]
        self.assertTrue(any("xgboost" in i.lower() for i in items))

    def test_extract_summary_shape(self):
        res = E.extract(FIXTURE_TRANSCRIPT)
        self.assertFalse(res["enhanced"])
        self.assertIn("4 question", res["one_paragraph_summary"])
        for key in ("key_questions", "key_answers", "weak_spots",
                    "action_items", "one_paragraph_summary", "enhanced"):
            self.assertIn(key, res)

    def test_extract_empty_raises(self):
        with self.assertRaises(ValueError):
            E.extract([])
        with self.assertRaises(ValueError):
            E.extract(["not a dict"])

    def test_dedupe_questions(self):
        t = [{"prompt": "Q?", "answer": "A1"}, {"prompt": "Q?", "answer": "A2"}]
        res = E.extract(t)
        self.assertEqual(res["key_questions"], ["Q?"])

    def test_transcript_from_pairs(self):
        t = E.transcript_from_pairs([("Q?", "A.")])
        self.assertEqual(len(t), 1)
        self.assertIn("ts", t[0])

    def test_accepts_debrief_voice_transcript_dict(self):
        # worker A's transcript format: dict with a "turns" key
        voice_style = {
            "company": "Acme", "role": "DS", "app_id": 1, "mode": "voice",
            "turns": [
                {"n": 1, "prompt_id": "about", "prompt": "Tell me about yourself.",
                 "answer": "I build models.", "answered_at": "2026-09-22T10:00:00"},
                {"n": 2, "prompt_id": "sql", "prompt": "Explain window functions.",
                 "answer": "I was stumped on the partition-by clause, didn't know it.",
                 "answered_at": "2026-09-22T10:05:00"},
            ],
        }
        res = E.extract(voice_style)
        self.assertEqual(len(res["key_questions"]), 2)
        self.assertTrue(any("stumped" in s for s in res["weak_spots"]))


class LLMTierTest(unittest.TestCase):
    def test_enhanced_degrades_cleanly_when_ollama_unreachable(self):
        # Point at a port nothing can be listening on; must fail fast.
        old = E._OLLAMA_URL
        E._OLLAMA_URL = "http://127.0.0.1:1"
        try:
            t0 = time.time()
            res = E.extract_enhanced(FIXTURE_TRANSCRIPT)
            dt = time.time() - t0
        finally:
            E._OLLAMA_URL = old
        self.assertFalse(res["enhanced"])
        self.assertEqual(len(res["key_questions"]), 4)
        self.assertLess(dt, 20, f"fallback took too long: {dt:.1f}s")


if __name__ == "__main__":
    unittest.main()
