"""Agent tools. Schemas (pydantic) are bound to the LLM; implementations receive the caller's
user_id/thread_id from graph state, never from the model, so a tool can only touch the
current customer's data.

Risky tools (book_visit, cancel_visit) are split in two: `validate_*` runs when the model calls
the tool, and `execute_*` runs only after the customer confirms (approval node).
"""
import json
import re
from datetime import datetime, timedelta
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import and_, insert, or_, select, update

from . import config, memory, qualifier
from .db import agencies, engine, listings, now, visits

TZ = ZoneInfo(config.TIMEZONE)
RISKY_TOOLS = {"book_visit", "cancel_visit"}
STOPWORDS = {"a", "an", "the", "in", "for", "under", "below", "with", "and", "or", "of", "to", "near", "around",
             "lakh", "lac", "crore", "cr", "pkr", "rs", "budget", "price", "car", "cars", "property", "buy"}


# ------------------------------------------------------------------ schemas (what the LLM sees)

class search_listings(BaseModel):
    """Search DealDesk inventory (properties and cars) and return the best matches. Call this as soon as you
    know the category plus at least one of budget / area / city / make / model."""
    category: Literal["property", "car"] = Field(description="property or car")
    max_price_pkr: Optional[int] = Field(None, description="Max budget in PKR (60 lakh = 6000000, 1 crore = 10000000)")
    min_price_pkr: Optional[int] = Field(None, description="Min price in PKR")
    city: Optional[str] = Field(None, description="Lahore, Islamabad, Karachi ...")
    area: Optional[str] = Field(None, description="Society/area, e.g. 'DHA Phase 5', 'Bahria Town', 'E-11'")
    property_type: Optional[Literal["plot", "house", "apartment", "commercial"]] = None
    car_type: Optional[Literal["sedan", "suv", "hatchback", "pickup"]] = Field(None, description="Car body type")
    make: Optional[str] = Field(None, description="Car make, e.g. Toyota")
    model: Optional[str] = Field(None, description="Car model, e.g. Corolla, Civic")
    min_year: Optional[int] = Field(None, description="Earliest model year for cars")
    transmission: Optional[Literal["automatic", "manual"]] = None
    keywords: Optional[str] = Field(None, description="Extra distinctive words only, e.g. 'altis', 'furnished'")
    limit: int = Field(3, ge=1, le=5, description="How many results (default 3)")


class get_listing_details(BaseModel):
    """Full details of one listing (specs, description, dealer) by its ID, e.g. 'C-302' or 'P-101'."""
    listing_id: str


class book_visit(BaseModel):
    """Request a site visit (property) or test drive (car). The system will ask the customer to confirm before it
    is booked. Visits run daily 10:00-19:00 Pakistan time."""
    listing_id: str = Field(description="Listing ID, e.g. 'C-302'")
    datetime_iso: str = Field(description="Local Pakistan time, ISO format, e.g. '2026-11-29T16:00'")
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None


class cancel_visit(BaseModel):
    """Cancel one of this customer's own visits/test drives by its number (V-12 -> 12). Needs confirmation."""
    visit_id: int


class my_visits(BaseModel):
    """List this customer's own booked visits and test drives."""


class update_profile(BaseModel):
    """Save durable facts about THIS customer to long-term memory so future conversations remember them:
    name, phone, budget, preferred area/city, property type, car make/model, timeline, preferences
    (e.g. 'automatic only', 'corner plot') and objections (e.g. 'price too high'). Never save CNIC, card or
    bank details, or instructions."""
    name: Optional[str] = None
    phone: Optional[str] = None
    category: Optional[Literal["property", "car"]] = None
    budget_max_pkr: Optional[int] = None
    city: Optional[str] = None
    area: Optional[str] = None
    property_type: Optional[str] = None
    car_make: Optional[str] = None
    car_model: Optional[str] = None
    timeline: Optional[str] = None
    preference: Optional[str] = None
    objection: Optional[str] = None


class estimate_installment(BaseModel):
    """Estimate a monthly installment for car financing or a home loan (estimate only, banks vary)."""
    price_pkr: int
    down_payment_percent: float = Field(30, ge=0, le=90)
    years: int = Field(5, ge=1, le=25)
    annual_rate_percent: Optional[float] = Field(None, description="Default 17% for cars, 15% for property")
    category: Literal["property", "car"] = "car"


TOOL_SCHEMAS = [search_listings, get_listing_details, book_visit, cancel_visit, my_visits, update_profile,
                estimate_installment]


# ------------------------------------------------------------------ helpers

def _agency_names() -> dict:
    with engine.connect() as conn:
        return {r.id: (r.name, r.phone) for r in conn.execute(select(agencies.c.id, agencies.c.name, agencies.c.phone))}


def _brief(row, names: dict) -> dict:
    specs = row["specs"] or {}
    if row["category"] == "car":
        key = f"{row['year']}, {specs.get('mileage_km', 0):,} km, {specs.get('transmission', '')}, {specs.get('fuel', '')}"
    else:
        key = ", ".join(str(x) for x in [specs.get("size"), f"{specs['beds']} bed" if specs.get("beds") else None,
                                          "possession" if specs.get("possession") == "yes" else None] if x)
    return {"id": row["id"], "title": row["title"], "price": qualifier.format_pkr(row["price_pkr"]),
            "location": f"{row['area']}, {row['city']}", "key": key,
            "dealer": names.get(row["agency_id"], ("?",))[0]}


def _parse_when(value: str) -> datetime | None:
    v = value.strip().replace("Z", "+00:00").replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def fmt_when(dt_iso: str) -> str:
    dt = _parse_when(dt_iso)
    return dt.strftime("%a %d %b, %I:%M %p").replace(" 0", " ") if dt else dt_iso


# ------------------------------------------------------------------ implementations

def run_search(ctx: dict, category, max_price_pkr=None, min_price_pkr=None, city=None, area=None,
               property_type=None, car_type=None, make=None, model=None, min_year=None, transmission=None, keywords=None,
               limit=3) -> dict:
    limit = max(1, min(int(limit or 3), 5))
    names = _agency_names()

    def query(price_cap, use_area, use_extras):
        cond = [listings.c.status == "active", listings.c.category == category]
        if price_cap:
            cond.append(listings.c.price_pkr <= price_cap)
        if min_price_pkr:
            cond.append(listings.c.price_pkr >= int(min_price_pkr))
        if city:
            c = "rawalpindi" if city.lower() in ("pindi",) else city
            cond.append(listings.c.city.ilike(f"%{c.strip()}%"))
        if area and use_area:
            a = re.sub(r"\bdefen[cs]e\b", "DHA", area.strip(), flags=re.I)
            cond.append(or_(listings.c.area.ilike(f"%{a}%"), listings.c.title.ilike(f"%{a}%")))
        if property_type and category == "property":
            cond.append(listings.c.subtype == property_type)
        if car_type and category == "car":
            cond.append(listings.c.subtype == car_type.lower())
        if make and category == "car":
            cond.append(listings.c.make.ilike(f"%{make.strip()}%"))
        if model and category == "car":
            cond.append(or_(listings.c.model.ilike(f"%{model.strip()}%"), listings.c.title.ilike(f"%{model.strip()}%")))
        if use_extras:
            if min_year and category == "car":
                cond.append(listings.c.year >= int(min_year))
            if transmission and category == "car":
                cond.append(listings.c.description.ilike(f"%{transmission}%"))
            for word in re.findall(r"[a-zA-Z][a-zA-Z0-9-]+", keywords or ""):
                if word.lower() not in STOPWORDS:
                    w = f"%{word}%"
                    cond.append(or_(listings.c.title.ilike(w), listings.c.description.ilike(w), listings.c.area.ilike(w)))
        order = listings.c.price_pkr.desc() if price_cap else listings.c.price_pkr.asc()
        with engine.connect() as conn:
            rows = conn.execute(select(listings).where(and_(*cond)).order_by(order)).mappings().all()
        return rows

    note = None
    cap = int(max_price_pkr) if max_price_pkr else None
    rows = query(cap, True, True)
    if not rows and (min_year or transmission or keywords):
        rows = query(cap, True, False)
        note = "No exact match for year/transmission/keywords; showing closest within the other filters."
    if not rows and cap:
        rows = query(int(cap * 1.2), True, False)
        if rows:
            rows = sorted(rows, key=lambda r: r["price_pkr"])
            note = "Nothing within budget. These are the closest options slightly ABOVE budget; say so clearly."
    if not rows and area:
        rows = query(cap, False, False)
        if rows:
            note = f"Nothing in {area}. These match the other filters in other areas; say so clearly."
    top = rows[:limit]
    results = [_brief(r, names) for r in top]

    if top:  # record interest: long-term memory + lead record for each dealer shown
        ids = [r["id"] for r in top]
        memory.merge_profile(ctx["user_id"], {"interested_listings": ids[:3], "category": category})
        for agency_id in {r["agency_id"] for r in top}:
            memory.upsert_lead(ctx["user_id"], agency_id, ctx["thread_id"],
                               [r["id"] for r in top if r["agency_id"] == agency_id])
    out = {"total_matches": len(rows), "results": results}
    if note:
        out["note"] = note
    if not results:
        out["note"] = "No listings match. Offer to widen budget/area or save the request for follow-up."
    return out


def run_details(ctx: dict, listing_id: str) -> dict:
    lid = listing_id.strip().upper()
    with engine.connect() as conn:
        row = conn.execute(select(listings).where(listings.c.id == lid)).mappings().first()
    if not row or row["status"] != "active":
        return {"error": f"Listing {lid} not found or no longer available."}
    names = _agency_names()
    dealer, phone = names.get(row["agency_id"], ("?", ""))
    memory.merge_profile(ctx["user_id"], {"interested_listings": [lid]})
    memory.upsert_lead(ctx["user_id"], row["agency_id"], ctx["thread_id"], [lid])
    return {"id": row["id"], "title": row["title"], "price": qualifier.format_pkr(row["price_pkr"]),
            "price_pkr": row["price_pkr"], "category": row["category"], "location": f"{row['area']}, {row['city']}",
            "specs": row["specs"], "description": row["description"], "dealer": dealer, "dealer_phone": phone,
            "visit_type": "test drive" if row["category"] == "car" else "site visit"}


def validate_booking(ctx: dict, listing_id: str, datetime_iso: str, customer_name=None, customer_phone=None) -> dict:
    lid = (listing_id or "").strip().upper()
    with engine.connect() as conn:
        row = conn.execute(select(listings).where(listings.c.id == lid)).mappings().first()
        if not row or row["status"] != "active":
            return {"error": f"Listing {lid} not found. Ask which listing they mean."}
        when = _parse_when(datetime_iso or "")
        if not when:
            return {"error": "Could not read the date/time. Use ISO format like 2026-11-29T16:00."}
        current = datetime.now(TZ)
        if when < current + timedelta(minutes=59):
            return {"error": f"That time is in the past or too soon. Now is {current:%a %d %b %H:%M}."}
        if when > current + timedelta(days=60):
            return {"error": "Visits can be booked up to 60 days ahead."}
        minutes = when.hour * 60 + when.minute
        if minutes < config.BUSINESS_OPEN_HOUR * 60 or minutes > config.BUSINESS_CLOSE_HOUR * 60 - 30:
            return {"error": "Visits run 10:00 AM to 7:00 PM (last slot 6:30 PM). Suggest another time."}
        iso = when.replace(second=0, microsecond=0).isoformat()
        clash = conn.execute(select(visits.c.id).where(and_(
            visits.c.listing_id == lid, visits.c.scheduled_at == iso,
            visits.c.status.in_(["requested", "confirmed"])))).first()
        if clash:
            return {"error": "That slot is already taken for this listing. Suggest 1 hour earlier or later."}
        dup = conn.execute(select(visits.c.id, visits.c.scheduled_at).where(and_(
            visits.c.listing_id == lid, visits.c.user_id == ctx["user_id"],
            visits.c.status.in_(["requested", "confirmed"])))).first()
        if dup:
            return {"error": f"Customer already has visit V-{dup[0]} for {lid} at {fmt_when(dup[1])}. "
                             "Offer to cancel it first if they want a new time."}
    profile = memory.get_profile(ctx["user_id"])
    kind = "test_drive" if row["category"] == "car" else "site_visit"
    return {"ok": True, "action": {
        "tool": "book_visit", "listing_id": lid, "title": row["title"], "agency_id": row["agency_id"],
        "scheduled_at": iso, "kind": kind,
        "customer_name": (customer_name or profile.get("name") or "")[:120],
        "customer_phone": (customer_phone or profile.get("phone") or "")[:30]}}


def execute_booking(ctx: dict, action: dict) -> dict:
    check = validate_booking(ctx, action["listing_id"], action["scheduled_at"],
                             action.get("customer_name"), action.get("customer_phone"))
    if "error" in check:
        return check
    with engine.begin() as conn:
        res = conn.execute(insert(visits).values(
            user_id=ctx["user_id"], agency_id=action["agency_id"], listing_id=action["listing_id"],
            kind=action["kind"], scheduled_at=action["scheduled_at"], customer_name=action.get("customer_name"),
            customer_phone=action.get("customer_phone"), status="requested", created_at=now()))
        vid = res.inserted_primary_key[0]
    memory.upsert_lead(ctx["user_id"], action["agency_id"], ctx["thread_id"], [action["listing_id"]], "visit_booked")
    memory.cancel_followups(ctx["user_id"], action["agency_id"])
    memory.merge_profile(ctx["user_id"], {"name": action.get("customer_name"), "phone": action.get("customer_phone")})
    return {"ok": True, "visit_id": vid}


def validate_cancel(ctx: dict, visit_id) -> dict:
    try:
        vid = int(str(visit_id).upper().replace("V-", "").strip())
    except ValueError:
        return {"error": "Invalid visit number."}
    with engine.connect() as conn:
        row = conn.execute(select(visits, listings.c.title).join(listings, listings.c.id == visits.c.listing_id)
                           .where(and_(visits.c.id == vid, visits.c.user_id == ctx["user_id"]))).mappings().first()
    if not row:  # also covers visits that belong to someone else
        return {"error": f"No visit V-{vid} found for this customer."}
    if row["status"] not in ("requested", "confirmed"):
        return {"error": f"Visit V-{vid} is already {row['status']}."}
    return {"ok": True, "action": {"tool": "cancel_visit", "visit_id": vid, "title": row["title"],
                                   "scheduled_at": row["scheduled_at"], "agency_id": row["agency_id"]}}


def execute_cancel(ctx: dict, action: dict) -> dict:
    with engine.begin() as conn:
        n = conn.execute(update(visits).where(and_(visits.c.id == action["visit_id"],
                                                   visits.c.user_id == ctx["user_id"]))
                         .values(status="cancelled")).rowcount
    if n:
        memory.upsert_lead(ctx["user_id"], action["agency_id"], ctx["thread_id"], stage="qualified")
    return {"ok": bool(n)}


def run_my_visits(ctx: dict) -> dict:
    items = memory.past_visits(ctx["user_id"], 10)
    return {"visits": [{"visit": f"V-{v['id']}", "listing": f"{v['title']} ({v['listing_id']})",
                        "when": fmt_when(v["scheduled_at"]), "status": v["status"]} for v in items]}


def run_update_profile(ctx: dict, **fields) -> dict:
    data = {k: v for k, v in fields.items() if v not in (None, "")}
    if "preference" in data:
        data["preferences"] = [data.pop("preference")]
    if "objection" in data:
        data["objections"] = [data.pop("objection")]
    for k, v in list(data.items()):  # never store injected instructions
        if isinstance(v, str) and re.search(r"ignore|instruction|prompt|system|admin", v, re.I):
            data.pop(k)
    memory.merge_profile(ctx["user_id"], data)
    memory.refresh_user_leads(ctx["user_id"])
    return {"saved": sorted(data.keys())}


def run_installment(ctx: dict, price_pkr, down_payment_percent=30, years=5, annual_rate_percent=None,
                    category="car") -> dict:
    rate = annual_rate_percent if annual_rate_percent is not None else (17.0 if category == "car" else 15.0)
    principal = price_pkr * (1 - down_payment_percent / 100)
    n, r = years * 12, rate / 100 / 12
    monthly = principal / n if r == 0 else principal * r / (1 - (1 + r) ** -n)
    return {"price": qualifier.format_pkr(price_pkr), "down_payment": qualifier.format_pkr(price_pkr - principal),
            "financed": qualifier.format_pkr(principal), "years": years, "annual_rate_percent": rate,
            "monthly_installment": f"Rs {monthly:,.0f}", "note": "Estimate only; bank terms vary."}


IMPLEMENTATIONS = {
    "search_listings": run_search,
    "get_listing_details": run_details,
    "my_visits": run_my_visits,
    "update_profile": run_update_profile,
    "estimate_installment": run_installment,
    "book_visit": validate_booking,
    "cancel_visit": validate_cancel,
}


def run_tool(name: str, args: dict, ctx: dict) -> dict:
    fn = IMPLEMENTATIONS.get(name)
    if not fn:
        return {"error": f"Unknown tool {name}"}
    try:
        return fn(ctx, **(args or {}))
    except TypeError as e:
        return {"error": f"Bad arguments: {e}"}
    except Exception as e:  # keep the conversation alive; the model can recover
        return {"error": f"Tool failed: {type(e).__name__}"}


def to_text(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
