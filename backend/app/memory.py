"""Long-term memory (per user_id) and per-agency lead records.

Every function takes user_id explicitly and filters on it, so one customer can never read or
write another customer's memory.
"""
from datetime import timedelta

from sqlalchemy import and_, insert, select, update

from . import qualifier
from .db import engine, followups, leads, listings, now, profiles, visits

# Fields we keep across conversations. Anything else (CNIC, card numbers, small talk,
# instructions found in messages) is never stored.
PROFILE_FIELDS = {"name", "phone", "category", "budget_max_pkr", "city", "area", "property_type",
                  "car_make", "car_model", "transmission", "timeline", "preferences", "objections", "interested_listings"}
LIST_FIELDS = {"preferences", "objections", "interested_listings"}
MAX_LIST = 6


def get_profile(user_id: str) -> dict:
    with engine.connect() as conn:
        row = conn.execute(select(profiles.c.data).where(profiles.c.user_id == user_id)).first()
    return dict(row[0] or {}) if row else {}


def merge_profile(user_id: str, fields: dict) -> dict:
    """Merge new facts into the user's long-term profile and persist. Returns the merged profile."""
    clean = {}
    for k, v in fields.items():
        if k not in PROFILE_FIELDS or v in (None, "", [], {}):
            continue
        if isinstance(v, str):
            v = qualifier.strip_sensitive(v.strip())[:160]
        clean[k] = v
    if not clean:
        return get_profile(user_id)
    with engine.begin() as conn:
        row = conn.execute(select(profiles.c.data).where(profiles.c.user_id == user_id)).first()
        data = dict(row[0] or {}) if row else {}
        for k, v in clean.items():
            if k in LIST_FIELDS:
                items = list(data.get(k, []))
                for item in (v if isinstance(v, list) else [v]):
                    if item not in items:
                        items.append(item)
                data[k] = items[-MAX_LIST:]
            else:
                data[k] = v
        if row:
            conn.execute(update(profiles).where(profiles.c.user_id == user_id).values(data=data, updated_at=now()))
        else:
            conn.execute(insert(profiles).values(user_id=user_id, data=data, updated_at=now()))
    return data


def past_visits(user_id: str, limit: int = 5) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(visits.c.id, visits.c.listing_id, visits.c.scheduled_at, visits.c.status, listings.c.title)
            .join(listings, listings.c.id == visits.c.listing_id)
            .where(visits.c.user_id == user_id)
            .order_by(visits.c.id.desc()).limit(limit)).mappings().all()
    return [dict(r) for r in rows]


def profile_for_prompt(user_id: str) -> str:
    """Compact text version of long-term memory, injected into the agent's system prompt."""
    p = get_profile(user_id)
    parts = []
    labels = [("name", "Name"), ("phone", "Phone"), ("category", "Looking for"), ("property_type", "Property type"),
              ("car_make", "Car make"), ("car_model", "Car model"), ("transmission", "Transmission (pass it to search)"), ("city", "City"), ("area", "Preferred area"),
              ("timeline", "Timeline")]
    for key, label in labels:
        if p.get(key):
            parts.append(f"{label}: {p[key]}")
    if p.get("budget_max_pkr"):
        parts.append(f"Budget: up to {qualifier.format_pkr(p['budget_max_pkr'])}")
    for key, label in (("preferences", "Preferences"), ("objections", "Objections"),
                       ("interested_listings", "Listings viewed")):
        if p.get(key):
            parts.append(f"{label}: {', '.join(map(str, p[key]))}")
    for v in past_visits(user_id, 3):
        parts.append(f"Past booking V-{v['id']}: {v['title']} ({v['listing_id']}) at {v['scheduled_at'][:16]}, {v['status']}")
    return "\n".join(parts) if parts else "New customer, nothing saved yet."


# ---------------------------------------------------------------- leads (agency-scoped)

FOLLOWUP_DAYS = (1, 3, 7)
FOLLOWUP_TEMPLATES = {
    1: "Hi{name}! Thanks for checking {what} on DealDesk. Would you like to book a {visit} this week?",
    3: "Hi{name}, {what} is still available and getting interest. Shall I reserve a {visit} slot for you?",
    7: "Hi{name}, we have new options matching your budget{budget}. Reply to see them or book a {visit}.",
}


def upsert_lead(user_id: str, agency_id: str, thread_id: str, listing_ids: list[str] | None = None,
                stage: str | None = None) -> int:
    profile = get_profile(user_id)
    with engine.begin() as conn:
        row = conn.execute(select(leads).where(and_(leads.c.agency_id == agency_id,
                                                    leads.c.user_id == user_id))).mappings().first()
        has_visit = stage == "visit_booked" or (row is not None and row["stage"] == "visit_booked")
        sc, auto_stage = qualifier.score(profile, has_visit)
        if row:
            interested = list(row["interested"] or [])
            for lid in listing_ids or []:
                if lid not in interested:
                    interested.append(lid)
            # never move a lead backwards from a manual/advanced stage
            keep = row["stage"] in ("visit_booked", "visited", "won", "lost")
            new_stage = stage or (row["stage"] if keep else auto_stage)
            conn.execute(update(leads).where(leads.c.id == row["id"]).values(
                stage=new_stage, score=max(sc, row["score"] or 0), interested=interested[-10:],
                last_thread_id=thread_id, updated_at=now()))
            return row["id"]
        res = conn.execute(insert(leads).values(
            agency_id=agency_id, user_id=user_id, stage=stage or auto_stage, score=sc,
            interested=(listing_ids or [])[-10:], last_thread_id=thread_id, created_at=now(), updated_at=now()))
        return res.inserted_primary_key[0]


def refresh_user_leads(user_id: str) -> None:
    """Re-score this user's leads after their profile changed."""
    profile = get_profile(user_id)
    with engine.begin() as conn:
        rows = conn.execute(select(leads.c.id, leads.c.stage, leads.c.score).where(leads.c.user_id == user_id)).all()
        for lid, stage, old in rows:
            sc, auto_stage = qualifier.score(profile, stage == "visit_booked")
            new_stage = stage if stage in ("visit_booked", "visited", "won", "lost") else auto_stage
            conn.execute(update(leads).where(leads.c.id == lid).values(stage=new_stage, score=max(sc, old or 0)))


def schedule_followups(user_id: str) -> int:
    """Leads that haven't booked a visit get a 1/3/7-day follow-up sequence (scheduled once per lead)."""
    profile = get_profile(user_id)
    created = 0
    with engine.begin() as conn:
        rows = conn.execute(select(leads).where(and_(leads.c.user_id == user_id,
                                                     leads.c.stage.in_(["new", "qualifying", "qualified"])))).mappings().all()
        for lead in rows:
            exists = conn.execute(select(followups.c.id).where(followups.c.lead_id == lead["id"])).first()
            if exists:
                continue
            first = (lead["interested"] or [None])[-1]
            title = None
            if first:
                r = conn.execute(select(listings.c.title, listings.c.category).where(listings.c.id == first)).first()
                title = r
            what = f"the {title[0]}" if title else "our listings"
            visit = "test drive" if (title and title[1] == "car") or profile.get("category") == "car" else "site visit"
            name = f" {profile['name'].split()[0]}" if profile.get("name") else ""
            budget = f" ({qualifier.format_pkr(profile['budget_max_pkr'])})" if profile.get("budget_max_pkr") else ""
            for d in FOLLOWUP_DAYS:
                conn.execute(insert(followups).values(
                    lead_id=lead["id"], agency_id=lead["agency_id"], user_id=user_id, day_offset=d,
                    due_at=now() + timedelta(days=d), status="pending",
                    message=FOLLOWUP_TEMPLATES[d].format(name=name, what=what, visit=visit, budget=budget)))
                created += 1
    return created


def cancel_followups(user_id: str, agency_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(update(followups).where(and_(followups.c.user_id == user_id,
                                                  followups.c.agency_id == agency_id,
                                                  followups.c.status == "pending")).values(status="cancelled"))
