"""Fact matching for code graders: case-insensitive text, and numbers compared after normalising
separators (1,234,567 and 12,34,567), currency (₹, INR, Rs), scale words (lakh, crore, k, million)
and percentages, with a rounding tolerance. "₹43.7 lakh" matches "₹4,374,000"; "35%" matches
"35.0%"; but "35%" does not match a bare 35 elsewhere in the text."""

import re
from dataclasses import dataclass

REL_TOLERANCE = 0.01  # 1%: "₹44 lakh" for ₹4,374,000 still counts
ABS_TOLERANCE = 0.5  # "35%" vs "35.4%"

_SCALE = {
    "k": 1e3,
    "thousand": 1e3,
    "lakh": 1e5,
    "lakhs": 1e5,
    "lac": 1e5,
    "lacs": 1e5,
    "l": 1e5,
    "crore": 1e7,
    "crores": 1e7,
    "cr": 1e7,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "millions": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
}
_NUMBER = re.compile(
    r"(?P<currency>₹|\binr\b|\brs\.?)?\s*"
    r"(?<![A-Za-z\d_])(?P<sign>[-−])?"
    r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
    r"(?:\s*(?P<pct>%|percent\b|per\s+cent\b|pct\b))?"
    r"(?:\s*(?P<scale>thousand|lakhs?|lacs?|crores?|cr|millions?|mn|billion|bn|k|m|b|l)\b)?"
    r"(?:\s*(?P<pct2>%|percent\b))?",
    re.IGNORECASE,
)
_DASHES = str.maketrans({"–": "-", "—": "-", "‑": "-", "’": "'", "‘": "'", "“": '"', "”": '"'})


@dataclass(frozen=True)
class Quantity:
    value: float
    percent: bool
    money: bool


def normalise_text(text: str) -> str:
    text = text.translate(_DASHES).lower()
    text = text.replace("**", "").replace("`", "")
    return " ".join(text.split())


def extract_quantities(text: str) -> list[Quantity]:
    quantities: list[Quantity] = []
    for match in _NUMBER.finditer(text.translate(_DASHES)):
        raw = match.group("num").replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        scale = (match.group("scale") or "").lower()
        if scale:
            value *= _SCALE[scale]
        if match.group("sign"):
            value = -value
        percent = bool(match.group("pct") or match.group("pct2"))
        quantities.append(Quantity(value, percent, bool(match.group("currency"))))
    return quantities


def parse_expected_number(text: str) -> Quantity | None:
    """A fact alternative is numeric when, stripped of currency/scale/%, it is a single number."""
    stripped = text.strip()
    match = _NUMBER.fullmatch(stripped)
    if not match:
        return None
    quantities = extract_quantities(stripped)
    return quantities[0] if len(quantities) == 1 else None


def numbers_close(expected: float, actual: float) -> bool:
    return abs(expected - actual) <= max(REL_TOLERANCE * abs(expected), ABS_TOLERANCE)


def contains_number(text: str, expected: Quantity) -> bool:
    for quantity in extract_quantities(text):
        if expected.percent and not quantity.percent:
            continue
        # Signs are dropped: "-30.0%" variance and "30% under budget" state the same fact.
        if numbers_close(abs(expected.value), abs(quantity.value)):
            return True
    return False


def contains_text(text: str, needle: str) -> bool:
    """Case-insensitive containment on word boundaries ("Data" does not match "database")."""
    needle_norm = normalise_text(needle)
    if not needle_norm:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(needle_norm) + r"(?![a-z0-9])"
    return re.search(pattern, normalise_text(text)) is not None


def matches_alternative(text: str, alternative: str) -> bool:
    quantity = parse_expected_number(alternative)
    if quantity is not None:
        return contains_number(text, quantity)
    return contains_text(text, alternative)


def find_fact(text: str, any_of: list[str]) -> str | None:
    """The first alternative found in the text, or None."""
    return next((alt for alt in any_of if matches_alternative(text, alt)), None)
