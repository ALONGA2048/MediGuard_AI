import re
import unicodedata
from difflib import SequenceMatcher


def normalize_text(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", text)


def similarity(left, right):
    a, b = normalize_text(left), normalize_text(right)
    if not a or not b:
        return 0.0
    return 100.0 * SequenceMatcher(None, a, b).ratio()


def edit_distance(a, b):
    a, b = normalize_text(a), normalize_text(b)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def safe_name_similarity(observed, candidate):
    a, b = normalize_text(observed), normalize_text(candidate)
    if a == b:
        return 100.0
    # OCR commonly joins a short brand name to neighbouring dosage text
    # (for example ``Acetal nte50ng``).  Keep the union of OCR evidence useful:
    # an intact database name inside a noisy line is stronger evidence than the
    # whole-line edit distance suggests.  Five characters avoids treating very
    # short names such as "SR" as arbitrary substring hits.
    if len(b) >= 5 and b in a:
        return 100.0
    if any(token in a.upper() or token in b.upper() for token in ("XR", "ER", "SR", "CR", "MR")):
        return 0.0
    if "enteric" in a or "enteric" in b:
        return 0.0
    length = len(a)
    allowed = 0 if length <= 4 else (1 if length <= 8 else 2)
    score = similarity(a, b)
    return score if allowed and edit_distance(a, b) <= allowed and score >= 90 else 0.0
