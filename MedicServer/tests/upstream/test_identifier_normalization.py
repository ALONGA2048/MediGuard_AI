import unittest

from drug_matching.license_extractor import extract_licenses
from drug_matching.strength_parser import normalize_dose_text, strengths


class DoseOcrNormalizationTests(unittest.TestCase):
    def test_ma_is_repaired_for_any_numeric_dose(self):
        self.assertEqual(normalize_dose_text("10ma"), "10mg")
        self.assertEqual(normalize_dose_text("0.2 mA"), "0.2mg")
        self.assertEqual(strengths("Each tablet contains 25ma"), {"25mg"})

    def test_valid_units_are_preserved(self):
        self.assertEqual(strengths("10mg 250mcg 1g"), {"10mg", "250mcg", "1g"})

    def test_ma_repair_is_limited_to_dose_looking_spans(self):
        self.assertEqual(strengths("Vitamin B12ma"), set())
        self.assertEqual(strengths("10maX"), set())


class LicenseExtractionTests(unittest.TestCase):
    def test_five_digit_manufacturing_license(self):
        self.assertEqual(
            extract_licenses(["藥製字第09250號"])[0]["normalized_identifier"],
            "製:09250",
        )

    def test_six_digit_import_license(self):
        result = extract_licenses(["衛部藥輸字第012345號"])[0]
        self.assertEqual(result["normalized_identifier"], "輸:012345")
        self.assertFalse(result["corrected"])

    def test_ocr_kind_confusion_is_repaired_only_in_license_context(self):
        result = extract_licenses(["衡暑藥數字第046013號"])[0]
        self.assertEqual(result["normalized_identifier"], "製:046013")
        self.assertTrue(result["corrected"])

    def test_fullwidth_digits_and_number_ocr_confusions(self):
        fullwidth = extract_licenses(["藥製字第０９２５０號"])[0]
        confused = extract_licenses(["藥製字第O92I0號"])[0]
        self.assertEqual(fullwidth["number"], "09250")
        self.assertEqual(confused["number"], "09210")
        self.assertTrue(confused["corrected"])

    def test_standalone_dates_lots_and_numbers_are_rejected(self):
        texts = ["046013", "EXP 202811", "批號 1012A0509", "202811"]
        self.assertEqual(extract_licenses(texts), [])

    def test_seven_digit_number_is_rejected(self):
        self.assertEqual(extract_licenses(["藥製字第1234567號"]), [])


if __name__ == "__main__":
    unittest.main()
