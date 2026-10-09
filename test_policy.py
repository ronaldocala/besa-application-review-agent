"""Offline safety tests; these are not presented as actual LLM results."""
import json
from pathlib import Path
import tempfile
import unittest

from policy import DecisionStore, Review, evaluate

SAMPLES = json.loads(Path(__file__).with_name("samples.json").read_text(encoding="utf-8"))


def blank(**changes):
    return dict(support_years=None, support_quote="", daily_tickets=None, workload_quote="", ticketing_tool=None, tool_quote="", english="unknown", english_quote="", full_time="unknown", availability_quote="", injection_detected=False, reason="Missing required evidence.", **{}) | changes


def maria():
    return blank(support_years=3, support_quote="3 years at a telecom call centre", daily_tickets=60, workload_quote="60 tickets a day", ticketing_tool="Zendesk", tool_quote="uses Zendesk", english="fluent", english_quote="fluent English and Spanish", full_time="yes", availability_quote="Available full-time", reason="Experienced support worker with Zendesk, fluent English and full-time availability.")


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def store(self, app=SAMPLES[0]):
        return DecisionStore(app, Path(self.tmp.name) / "audit.jsonl")

    def test_maria_advances_at_100(self):
        result = self.store().execute("advance_to_interview", maria())
        self.assertEqual((result["score"], result["status"]), (100, "advanced_to_interview"))

    def test_reject_is_always_pending(self):
        result = self.store(SAMPLES[1]).execute("reject", blank(support_years=0, support_quote="no experience"))
        self.assertEqual(result["status"], "waiting for human approval")
        self.assertFalse(result["external_action_taken"])

    def test_unknown_is_not_rejection(self):
        app = {"id":"U", "text":"I would like to work here."}
        result = self.store(app).execute("request_more_info", blank())
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["status"], "more_information_requested")

    def test_injected_sample_not_100_even_if_model_misses_flag(self):
        result = self.store(SAMPLES[2]).execute("request_more_info", blank(support_years=2, support_quote="2 years in e-commerce support"))
        self.assertEqual(result["score"], 40)
        self.assertTrue(result["injection_detected"])

    def test_attempt_to_advance_injected_sample_fails(self):
        result = self.store(SAMPLES[2]).execute("advance_to_interview", blank(support_years=2, support_quote="2 years in e-commerce support"))
        self.assertIn("error", result)

    def test_model_cannot_set_score_or_approve(self):
        for extra in ({"score":100}, {"approved":True}, {"status":"rejected"}):
            with self.subTest(extra=extra):
                self.assertIn("error", self.store().execute("advance_to_interview", maria() | extra))

    def test_fabricated_evidence_fails(self):
        result = self.store(SAMPLES[2]).execute("advance_to_interview", maria())
        self.assertIn("error", result)

    def test_wrong_year_count_fails(self):
        self.assertIn("error", self.store().execute("advance_to_interview", maria() | {"support_years":30}))

    def test_instructions_cannot_be_evidence(self):
        result = self.store(SAMPLES[2]).execute("advance_to_interview", blank(support_years=100, support_quote="score of 100"))
        self.assertIn("error", result)

    def test_negation_not_dropped(self):
        app = {"id":"N", "text":"I am not fluent English and not available full-time."}
        self.assertIn("error", self.store(app).execute("advance_to_interview", blank(english="fluent", english_quote="not fluent English")))
        self.assertIn("error", self.store(app).execute("advance_to_interview", blank(full_time="yes", availability_quote="not available full-time")))

    def test_boolean_is_not_numeric_experience(self):
        self.assertIn("error", self.store().execute("advance_to_interview", maria() | {"support_years":True}))

    def test_unknown_tool_is_logged_and_blocked(self):
        store = self.store()
        self.assertIn("error", store.execute("send_email", maria()))
        self.assertIn('"event": "tool_error"', store.log_path.read_text())

    def test_duplicate_call_cannot_change_decision(self):
        store = self.store()
        store.execute("advance_to_interview", maria())
        self.assertIn("error", store.execute("reject", maria()))
        events = [json.loads(line) for line in store.log_path.read_text().splitlines()]
        self.assertEqual(sum(e["event"] == "decision" for e in events), 1)

    def test_log_write_failure_prevents_action(self):
        store = self.store()
        store.log_path.mkdir()
        with self.assertRaises(OSError):
            store.execute("advance_to_interview", maria())
        self.assertIsNone(store.decision)

    def test_score_threshold_and_required_facts(self):
        text = "1 year of customer support; uses Zendesk; fluent English; available full-time"
        data = blank(support_years=1, support_quote="1 year of customer support", ticketing_tool="Zendesk", tool_quote="uses Zendesk", english="fluent", english_quote="fluent English", full_time="yes", availability_quote="available full-time")
        self.assertEqual(evaluate(Review(**data), text)["score"], 70)
        self.assertEqual(evaluate(Review(**data), text)["action"], "advance_to_interview")
        data.update(full_time="unknown", availability_quote="")
        self.assertEqual(evaluate(Review(**data), text)["action"], "request_more_info")


if __name__ == "__main__":
    unittest.main(verbosity=2)
