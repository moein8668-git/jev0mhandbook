import copy
import unittest

from support_router import FIXTURE, build_request, decide, number

class RouterTests(unittest.TestCase):
    def sample(self, p):
        data = copy.deepcopy(FIXTURE)
        data["answers"]["requests_human_agent"]["noul"] = p
        return data

    def test_explicit_request(self):
        self.assertEqual(decide(self.sample(0.92))["queue"], "human-support")

    def test_high_boundary_is_inclusive(self):
        self.assertEqual(decide(self.sample(0.80))["queue"], "human-support")

    def test_low_boundary_enters_review(self):
        self.assertEqual(decide(self.sample(0.25))["queue"], "manual-review")

    def test_clear_negative_uses_department(self):
        self.assertEqual(decide(self.sample(0.10))["queue"], "technical")

    def test_middle_goes_to_review(self):
        self.assertEqual(decide(self.sample(0.55))["queue"], "manual-review")

    def test_low_confidence_requires_review(self):
        data = self.sample(0.10)
        data["answers"]["department"]["confidence"] = 0.20
        self.assertEqual(decide(data)["queue"], "manual-review")

    def test_nan_is_rejected(self):
        with self.assertRaises(ValueError):
            number(float("nan"), "p")

    def test_boolean_is_not_a_probability(self):
        with self.assertRaises(ValueError):
            number(True, "p")

    def test_missing_answer_is_rejected(self):
        data = self.sample(0.1)
        del data["answers"]["department"]
        with self.assertRaises(ValueError):
            decide(data)

    def test_unknown_choice_is_rejected(self):
        data = self.sample(0.1)
        data["answers"]["department"]["choice"] = "invented"
        with self.assertRaises(ValueError):
            decide(data)

    def test_bad_sum_is_rejected(self):
        data = self.sample(0.1)
        data["answers"]["department"]["probabilities"]["billing"] = 0.8
        with self.assertRaises(ValueError):
            decide(data)

    def test_wrong_score_is_rejected(self):
        data = self.sample(0.1)
        data["answers"]["impact"]["score"] = 0.3
        with self.assertRaises(ValueError):
            decide(data)

    def test_blank_message_is_rejected(self):
        with self.assertRaises(ValueError):
            build_request(" ", "ticket-1")

    def test_request_does_not_share_mutable_questions(self):
        first = build_request("hello", "1")
        second = build_request("hello", "2")
        first["questions"]["department"]["criteria"]["billing"] = "changed"
        self.assertNotEqual(first["questions"], second["questions"])

if __name__ == "__main__":
    unittest.main()
