import re
from dataclasses import dataclass

from .normalization import normalize_text


MAX_DATABASE_STRENGTH_MG = 10_000.0


@dataclass(frozen=True)
class Dose:
    value: float
    unit: str
    per_unit: str = ""

    @property
    def canonical(self):
        base = f"{self.value:g}{self.unit}"
        return f"{base}/{self.per_unit}" if self.per_unit else base


def _milligrams(value, unit):
    if unit == "g":
        return value * 1000.0
    if unit in ("mcg", "ug"):
        return value / 1000.0
    return value


def normalize_dose_text(text):
    """Normalize OCR confusions only inside dose-looking spans."""
    value = str(text or "")
    value = re.sub(r"(?<=\d{6})\s*G(?=\s*-|\s*$)", " ", value)
    value = value.replace("，", ",").replace("．", ".")
    value = re.sub(r"(?i)(\d{1,3})\s*,\s*(\d)(?=\s*(?:m[cg]|mg|g)\b)", r"\1.\2", value)
    value = re.sub(r"(?i)(\d{2})\s+(\d)(?=\s*(?:m[cg]|mg|g)\b)", r"\1.\2", value)
    dose_like = re.compile(
        r"(?i)(?<![a-z0-9])([0-9oOcC]{1,5}(?:[.,][0-9oO]+)?)\s*"
        r"(m[g9a]|[uμ]g|mcg|g)(?![a-z])"
    )

    def repair(match):
        number, unit = match.group(1), match.group(2)
        number = number.translate(
            str.maketrans({"O": "0", "o": "0", "C": "0", "c": "0"})
        ).replace(",", ".")
        unit = (
            unit.lower()
            .replace("m9", "mg")
            .replace("ma", "mg")
            .replace("μ", "u")
        )
        return f"{number}{unit}"

    return dose_like.sub(repair, value)


def parse_doses(text):
    value = normalize_dose_text(text).lower()
    pattern = re.compile(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*(mcg|ug|mg|g)"
        r"(?:\s*/\s*(gm|g|ml|tablet|tab|cap))?(?![a-z])"
    )
    found = []
    for number, unit, per_unit in pattern.findall(value):
        numeric = float(number)
        if _milligrams(numeric, unit) > MAX_DATABASE_STRENGTH_MG:
            continue
        found.append(Dose(numeric, "mcg" if unit == "ug" else unit, per_unit))
    return found


def strengths(text):
    return {dose.canonical for dose in parse_doses(text)}


def dose_equivalent(observed, candidate):
    return any(
        abs(_milligrams(left.value, left.unit) - _milligrams(right.value, right.unit)) < 1e-6
        for left in parse_doses(observed)
        for right in parse_doses(candidate)
    )


def name_line_has_matching_strength(text, database_name, candidate_strength):
    """Match ``<exact product name> <strength>`` even if OCR drops the unit.

    This is intentionally limited to a single database strength and an exact
    normalized name prefix.  It accepts ``Concor 5`` for a database product
    named ``Concor`` with strength ``5mg``, but it does not turn arbitrary
    name containment or a different numeric suffix into an exact match.
    """
    observed = normalize_text(text)
    name = normalize_text(database_name)
    parsed = parse_doses(candidate_strength)
    if not observed or not name or len(parsed) != 1 or not observed.startswith(name):
        return False

    suffix = observed[len(name):]
    dose = parsed[0]
    number = f"{dose.value:g}"
    units = {dose.unit}
    if dose.unit == "mcg":
        units.add("ug")
    allowed_suffixes = {number, *(number + unit for unit in units)}
    return suffix in allowed_suffixes
