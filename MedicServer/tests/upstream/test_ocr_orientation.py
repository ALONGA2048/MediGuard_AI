import unittest

import ocr


class OrientationConfidenceOverrideTests(unittest.TestCase):
    def test_zoloft_quality_overrides_fragment_count_score(self):
        selected_180 = {
            "count": 4,
            "confidence_sum": 2.974886,
            "confidence_average": 0.743722,
        }
        alternative_0 = {
            "count": 3,
            "confidence_sum": 2.979270,
            "confidence_average": 0.993090,
        }

        self.assertTrue(
            ocr.orientation_confidence_dominates(
                alternative_0,
                selected_180,
            )
        )

    def test_average_gap_alone_does_not_override(self):
        score_winner = {
            "count": 4,
            "confidence_sum": 3.1,
            "confidence_average": 0.75,
        }
        alternative = {
            "count": 3,
            "confidence_sum": 2.9,
            "confidence_average": 0.96,
        }

        self.assertFalse(
            ocr.orientation_confidence_dominates(alternative, score_winner)
        )

    def test_total_confidence_alone_does_not_override(self):
        score_winner = {
            "count": 4,
            "confidence_sum": 3.0,
            "confidence_average": 0.75,
        }
        alternative = {
            "count": 4,
            "confidence_sum": 3.1,
            "confidence_average": 0.94,
        }

        self.assertFalse(
            ocr.orientation_confidence_dominates(alternative, score_winner)
        )


if __name__ == "__main__":
    unittest.main()
