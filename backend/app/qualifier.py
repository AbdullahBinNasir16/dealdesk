"""Qualifier node logic: pulls structured lead fields out of free text (no LLM tokens).

Extracts category (property/car), budget in PKR, city, area, property type, car make/model,
timeline, name and phone, then scores the lead. The LLM agent can fill anything this misses
through the update_profile tool.
"""
import re

L, CR = 100_000, 10_000_000

CITIES = ["lahore", "islamabad", "karachi", "rawalpindi", "pindi", "faisalabad", "multan", "peshawar"]

AREA_PATTERNS = [
    r"\bdha(?:\s+phase\s*\d+)?\b", r"\bdefen[cs]e(?:\s+phase\s*\d+)?\b",
    r"\bbahria\s+town(?:\s+phase\s*\d+)?\b", r"\bbahria\s+enclave\b", r"\bbahria\b",
    r"\bgulberg\s+greens\b", r"\bgulberg(?:\s+(?:i{1,3}|[1-3]))?\b", r"\bjohar\s+town\b", r"\bmodel\s+town\b",
    r"\bwapda\s+town\b", r"\baskari(?:\s+\d+)?\b", r"\bcantt\b", r"\bclifton\b", r"\bpechs\b",
    r"\bgulshan(?:-e-iqbal)?\b", r"\b[defgi]-\d{1,2}\b",
]

PROPERTY_TYPES = {
    "plot": r"\bplots?\b|\bland\b", "house": r"\bhouses?\b|\bhomes?\b|\bbungalow\b|\bvilla\b",
    "apartment": r"\bapartments?\b|\bflats?\b|\bpenthouse\b", "commercial": r"\bcommercial\b|\bshops?\b|\boffices?\b",
}

CAR_MODELS = {
    "corolla": "Toyota", "yaris": "Toyota", "fortuner": "Toyota", "hilux": "Toyota", "revo": "Toyota",
    "prado": "Toyota", "land cruiser": "Toyota", "civic": "Honda", "honda city": "Honda", "br-v": "Honda",
    "hr-v": "Honda", "alto": "Suzuki", "cultus": "Suzuki", "swift": "Suzuki", "wagon r": "Suzuki",
    "mehran": "Suzuki", "sportage": "KIA", "picanto": "KIA", "stonic": "KIA", "sorento": "KIA",
    "tucson": "Hyundai", "elantra": "Hyundai", "sonata": "Hyundai", "h6": "Haval", "jolion": "Haval",
    "mg hs": "MG", "mg zs": "MG", "alsvin": "Changan", "oshan": "Changan",
}
CAR_MAKES = ["toyota", "honda", "suzuki", "kia", "hyundai", "haval", "mg", "changan", "nissan", "mercedes",
             "bmw", "audi"]
CAR_WORDS = r"\b(cars?|gaa?ri|vehicle|sedan|suv|hatchback|pickup|test\s*drive|automatic|manual|mileage|cc)\b"
PROPERTY_WORDS = (r"\b(propert(y|ies)|plots?|houses?|homes?|apartments?|flats?|villa|marla|kanal|sq ?ft|"
                  r"commercial|possession|site\s*visit|society|dha|bahria|phase)\b")

_NUM = r"(\d+(?:[.,]\d+)?)"
BUDGET_PATTERNS = [
    (rf"{_NUM}\s*(crores?|cr)\b", CR),
    (rf"{_NUM}\s*(lakhs?|lacs?|lac|lakh|l)\b", L),
    (rf"{_NUM}\s*(million|mn|m)\b", 1_000_000),
    (rf"{_NUM}\s*(k|thousand)\b", 1_000),
    (r"(?:rs\.?|pkr)\s*([\d,]{6,})", 1),
    (r"\b(\d{1,3}(?:,\d{3}){2,})\b", 1),
]

TIMELINE_PATTERN = re.compile(
    r"\b(asap|urgent(ly)?|immediately|right away|today|tomorrow|this (week|weekend|month)|next (week|month|year)|"
    r"(in|within|next|after)\s+(\d+|a|an|one|two|three|four|six|few|couple of)\s+(days?|weeks?|months?|years?)|"
    r"just (browsing|looking)|not sure|no rush)\b",
    re.IGNORECASE,
)
PHONE_PATTERN = re.compile(r"(?:\+92|0092|0)\s?3\d{2}[\s-]?\d{7}\b")
NAME_PATTERN = re.compile(r"\bmy name is\s+([A-Za-z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.IGNORECASE)
SENSITIVE_PATTERN = re.compile(r"\b\d{5}-?\d{7}-?\d\b|\b(?:\d[ -]?){13,19}\b")  # CNIC / card numbers


def format_pkr(amount: int | float | None) -> str:
    if not amount:
        return "n/a"
    if amount >= CR:
        return f"{amount / CR:.2f}".rstrip("0").rstrip(".") + " crore"
    if amount >= L:
        return f"{amount / L:.1f}".rstrip("0").rstrip(".") + " lakh"
    return f"Rs {int(amount):,}"


def parse_budget(text: str) -> int | None:
    """Returns the (max) budget in PKR mentioned in the text, if any."""
    t = text.lower()
    found = []
    for pattern, mult in BUDGET_PATTERNS:
        for m in re.finditer(pattern, t):
            raw = m.group(1).replace(",", "") if mult == 1 else m.group(1).replace(",", ".")
            try:
                value = float(raw) * mult
            except ValueError:
                continue
            if 50_000 <= value <= 5_000_000_000:
                found.append(int(value))
        if found:
            break
    return max(found) if found else None


def extract(text: str) -> dict:
    t = text.lower()
    out: dict = {}

    for model, make in CAR_MODELS.items():
        if re.search(rf"\b{re.escape(model)}\b", t):
            out["car_make"], out["car_model"] = make, model.replace("honda ", "").replace("mg ", "").title()
            if model in ("h6", "mg hs", "mg zs", "br-v", "hr-v"):
                out["car_model"] = model.split()[-1].upper()
            break
    if "car_make" not in out:
        for make in CAR_MAKES:
            if re.search(rf"\b{make}\b", t):
                out["car_make"] = make.upper() if make in ("kia", "mg", "bmw") else make.title()
                break

    is_car = "car_make" in out or re.search(CAR_WORDS, t)
    is_property = re.search(PROPERTY_WORDS, t)
    if is_car and not is_property:
        out["category"] = "car"
    elif is_property and not is_car:
        out["category"] = "property"

    for ptype, pattern in PROPERTY_TYPES.items():
        if re.search(pattern, t):
            out["property_type"] = ptype
            break

    for city in CITIES:
        if re.search(rf"\b{city}\b", t):
            out["city"] = "Rawalpindi" if city == "pindi" else city.title()
            break

    for pattern in AREA_PATTERNS:
        m = re.search(pattern, t)
        if m:
            area = m.group(0)
            area = re.sub(r"\bdefen[cs]e\b", "dha", area)
            out["area"] = " ".join(w.upper() if w in ("dha", "pechs") else w.title() for w in area.split())
            break

    budget = parse_budget(t)
    if budget:
        out["budget_max_pkr"] = budget

    m = TIMELINE_PATTERN.search(t)
    if m:
        out["timeline"] = m.group(0)

    m = PHONE_PATTERN.search(text)
    if m:
        out["phone"] = re.sub(r"[\s-]", "", m.group(0))
    m = NAME_PATTERN.search(text)
    if m:
        out["name"] = m.group(1).title()
    return out


def score(fields: dict, has_visit: bool = False) -> tuple[int, str]:
    """Lead score 0-100 and pipeline stage."""
    s = 0
    s += 20 if fields.get("category") else 0
    s += 25 if fields.get("budget_max_pkr") else 0
    s += 20 if (fields.get("area") or fields.get("city") or fields.get("car_model")) else 0
    tl = (fields.get("timeline") or "").lower()
    if tl:
        s += 15
        if not re.search(r"browsing|looking|not sure|no rush|year", tl):
            s += 10
    s += 10 if (fields.get("phone") or fields.get("name")) else 0
    s = min(s, 100)
    if has_visit:
        return max(s, 90), "visit_booked"
    if fields.get("category") and fields.get("budget_max_pkr") and (
            fields.get("area") or fields.get("city") or fields.get("car_model")):
        return s, "qualified"
    if fields.get("category") or fields.get("budget_max_pkr"):
        return s, "qualifying"
    return s, "new"


def strip_sensitive(text: str) -> str:
    return SENSITIVE_PATTERN.sub("[removed]", text)
