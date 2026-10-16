import re
import unicodedata

# A number is a licence only when the same text contains an explicit
# manufacturing/import context.  Corrections are deliberately restricted to
# that structured context; standalone 5/6-digit strings may be dates, lot
# numbers, or other package identifiers and must never become licences.
LICENSE_KIND_ALIASES = {
    "製": "製",
    "制": "製",
    "劑": "製",
    "數": "製",
    "輸": "輸",
    "輪": "輸",
}

LICENSE_RE = re.compile(
    r"(?:(?:衛署|衛部)?[藥药](?P<type_after>[製制劑數輸輪])"
    r"|(?P<type_before>[製制劑數輸輪])[藥药])"
    r"字第?(?P<number>[0-9OIl]{5,6})(?![0-9OIl])號?",
    re.IGNORECASE,
)

LICENSE_NUMBER_TRANSLATION = str.maketrans(
    {"O": "0", "o": "0", "I": "1", "i": "1", "l": "1"}
)


def extract_licenses(texts, confidence_by_text=None):
    output = []
    for text in texts:
        source = str(text or "")
        compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", source))
        for match in LICENSE_RE.finditer(compact):
            raw_kind = match.group("type_after") or match.group("type_before")
            kind = LICENSE_KIND_ALIASES[raw_kind]
            raw_number = match.group("number")
            number = raw_number.translate(LICENSE_NUMBER_TRANSLATION)
            output.append({
                "kind": kind,
                "number": number,
                "corrected": kind != raw_kind or number != raw_number,
                "source": source,
                "identifier_source": "LICENSE_OCR",
                "raw_text": source,
                "normalized_identifier": f"{kind}:{number}",
                "ocr_confidence": (confidence_by_text or {}).get(source),
                "database_match": None,
            })
    return output
