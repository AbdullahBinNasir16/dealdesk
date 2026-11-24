"""DealDesk API: public agent endpoints (/chat, /health), public catalogue, and the dealer admin API."""
import csv
import io
import logging
import random
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, insert, select, update

from . import config, graph as agent, qualifier
from .auth import make_token, require_agency, verify_password
from .db import agencies, chat_log, engine, followups, init_db, leads, listings, now, profiles, visits
from .seed import seed_if_empty

log = logging.getLogger("dealdesk")
logging.basicConfig(level=logging.INFO)
STATE: dict = {}


def make_checkpointer():
    if config.is_postgres():
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
        pool = ConnectionPool(conninfo=config.psycopg_url(), max_size=5, open=True,
                              kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                              check=ConnectionPool.check_connection)
        saver = PostgresSaver(pool)
        saver.setup()
        return saver, pool
    from langgraph.checkpoint.sqlite import SqliteSaver
    conn = sqlite3.connect(config.SQLITE_PATH.replace(".db", "_checkpoints.db"), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver, conn


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_if_empty()
    saver, resource = make_checkpointer()
    STATE["graph"] = agent.build_graph(saver)
    log.info("DealDesk ready (db=%s, model=%s)", "postgres" if config.is_postgres() else "sqlite", config.MODEL)
    yield
    try:
        resource.close()
    except Exception:
        pass


app = FastAPI(title="DealDesk Agent API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


# ================================================================== agent API (graded)

class ChatIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field("default", min_length=1, max_length=200)
    message: str = Field(max_length=20000)


_rate: dict[str, deque] = defaultdict(deque)


def _rate_limited(user_id: str, limit: int = 40, window: int = 60) -> bool:
    q, t = _rate[user_id], time.time()
    while q and q[0] < t - window:
        q.popleft()
    q.append(t)
    return len(q) > limit


@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"


@app.get("/")
def root():
    return {"name": "DealDesk Agent API", "endpoints": ["POST /chat", "GET /health", "GET /api/listings"]}


def _log_chat(user_id: str, thread_id: str, message: str, result: dict) -> None:
    """Written after the response is sent so the customer never waits on it."""
    try:
        with engine.begin() as conn:
            conn.execute(insert(chat_log), [
                {"user_id": user_id, "thread_id": thread_id, "role": "user", "content": message,
                 "tool_calls": [], "tokens_in": 0, "tokens_out": 0, "created_at": now()},
                {"user_id": user_id, "thread_id": thread_id, "role": "assistant", "content": result["reply"],
                 "tool_calls": result["tool_calls"], "tokens_in": result["tokens"]["in"],
                 "tokens_out": result["tokens"]["out"], "created_at": now()}])
    except Exception:
        log.exception("chat log failed")


@app.post("/chat")
def chat(body: ChatIn, background: BackgroundTasks):
    user_id, thread_id = body.user_id.strip(), body.thread_id.strip()
    message = body.message.strip()[: config.MAX_MESSAGE_CHARS]
    if _rate_limited(user_id):
        return {"reply": "You're sending messages very quickly. Please wait a moment and try again.",
                "tool_calls": [], "tokens": {"in": 0, "out": 0}}
    started = time.time()
    try:
        result = agent.run_turn(STATE["graph"], user_id, thread_id, message)
    except Exception:
        log.exception("chat failed")
        result = {"reply": "Sorry, I hit a temporary problem. Please send your message again.",
                  "tool_calls": [], "tokens": {"in": 0, "out": 0}}
    background.add_task(_log_chat, user_id, thread_id, message, result)
    log.info("chat user=%s thread=%s %.2fs tools=%s tokens=%s", user_id, thread_id, time.time() - started,
             [t["name"] for t in result["tool_calls"]], result["tokens"])
    return result


# ================================================================== public catalogue (customer site)

def _listing_out(row, names) -> dict:
    d = dict(row)
    d["price_text"] = qualifier.format_pkr(d["price_pkr"])
    d["dealer"] = names.get(d["agency_id"], "")
    d.pop("created_at", None)
    return d


def _names() -> dict:
    with engine.connect() as conn:
        return dict(conn.execute(select(agencies.c.id, agencies.c.name)).all())


@app.get("/api/listings")
def public_listings(category: Optional[str] = None, city: Optional[str] = None, q: Optional[str] = None,
                    max_price: Optional[int] = None):
    cond = [listings.c.status == "active"]
    if category in ("property", "car"):
        cond.append(listings.c.category == category)
    if city:
        cond.append(listings.c.city.ilike(f"%{city}%"))
    if max_price:
        cond.append(listings.c.price_pkr <= max_price)
    if q:
        for word in q.split()[:5]:
            cond.append(listings.c.title.ilike(f"%{word}%") | listings.c.area.ilike(f"%{word}%"))
    with engine.connect() as conn:
        rows = conn.execute(select(listings).where(and_(*cond)).order_by(listings.c.category, listings.c.price_pkr)).mappings().all()
    names = _names()
    return [_listing_out(r, names) for r in rows]


@app.get("/api/listings/{listing_id}")
def public_listing(listing_id: str):
    with engine.connect() as conn:
        row = conn.execute(select(listings).where(listings.c.id == listing_id.upper())).mappings().first()
    if not row or row["status"] != "active":
        raise HTTPException(404, "Not found")
    return _listing_out(row, _names())


# ================================================================== dealer admin API (login, agency-scoped)

class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/admin/login")
def admin_login(body: LoginIn):
    with engine.connect() as conn:
        row = conn.execute(select(agencies).where(agencies.c.username == body.username.strip().lower())).mappings().first()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Wrong username or password")
    return {"token": make_token(row["id"]),
            "agency": {"id": row["id"], "name": row["name"], "kind": row["kind"], "city": row["city"]}}


@app.get("/admin/me")
def admin_me(agency_id: str = Depends(require_agency)):
    with engine.connect() as conn:
        row = conn.execute(select(agencies.c.id, agencies.c.name, agencies.c.kind, agencies.c.city)
                           .where(agencies.c.id == agency_id)).mappings().first()
    return dict(row)


@app.get("/admin/stats")
def admin_stats(agency_id: str = Depends(require_agency)):
    with engine.connect() as conn:
        by_stage = dict(conn.execute(select(leads.c.stage, func.count()).where(leads.c.agency_id == agency_id)
                                     .group_by(leads.c.stage)).all())
        vis = dict(conn.execute(select(visits.c.status, func.count()).where(visits.c.agency_id == agency_id)
                                .group_by(visits.c.status)).all())
        due = conn.execute(select(func.count()).select_from(followups).where(and_(
            followups.c.agency_id == agency_id, followups.c.status == "pending", followups.c.due_at <= now()))).scalar()
        pending_fu = conn.execute(select(func.count()).select_from(followups).where(and_(
            followups.c.agency_id == agency_id, followups.c.status == "pending"))).scalar()
        active = conn.execute(select(func.count()).select_from(listings).where(and_(
            listings.c.agency_id == agency_id, listings.c.status == "active"))).scalar()
    total = sum(by_stage.values())
    booked = sum(v for k, v in by_stage.items() if k in ("visit_booked", "visited", "won"))
    return {"leads_total": total, "leads_by_stage": by_stage, "visits_by_status": vis,
            "approval_queue": vis.get("requested", 0), "followups_due": due, "followups_pending": pending_fu,
            "active_listings": active, "booking_rate": round(100 * booked / total, 1) if total else 0}


@app.get("/admin/leads")
def admin_leads(agency_id: str = Depends(require_agency)):
    with engine.connect() as conn:
        rows = conn.execute(select(leads, profiles.c.data.label("profile"))
                            .join(profiles, profiles.c.user_id == leads.c.user_id, isouter=True)
                            .where(leads.c.agency_id == agency_id).order_by(leads.c.updated_at.desc())).mappings().all()
    out = []
    for r in rows:
        p = r["profile"] or {}
        out.append({"id": r["id"], "user_id": r["user_id"], "stage": r["stage"], "score": r["score"],
                    "interested": r["interested"], "updated_at": r["updated_at"], "thread_id": r["last_thread_id"],
                    "name": p.get("name"), "phone": p.get("phone"), "budget": qualifier.format_pkr(p.get("budget_max_pkr")),
                    "area": p.get("area") or p.get("city"), "want": p.get("car_model") or p.get("property_type") or p.get("category"),
                    "timeline": p.get("timeline"), "objections": p.get("objections", [])})
    return out


class StageIn(BaseModel):
    stage: str


@app.patch("/admin/leads/{lead_id}")
def admin_lead_stage(lead_id: int, body: StageIn, agency_id: str = Depends(require_agency)):
    if body.stage not in ("new", "qualifying", "qualified", "visit_booked", "visited", "won", "lost"):
        raise HTTPException(400, "Invalid stage")
    with engine.begin() as conn:
        n = conn.execute(update(leads).where(and_(leads.c.id == lead_id, leads.c.agency_id == agency_id))
                         .values(stage=body.stage, updated_at=now())).rowcount
    if not n:
        raise HTTPException(404, "Lead not found")
    return {"ok": True}


@app.get("/admin/visits")
def admin_visits(agency_id: str = Depends(require_agency)):
    with engine.connect() as conn:
        rows = conn.execute(select(visits, listings.c.title).join(listings, listings.c.id == visits.c.listing_id)
                            .where(visits.c.agency_id == agency_id).order_by(visits.c.scheduled_at)).mappings().all()
    return [dict(r) for r in rows]


class VisitStatusIn(BaseModel):
    status: str


@app.patch("/admin/visits/{visit_id}")
def admin_visit_status(visit_id: int, body: VisitStatusIn, agency_id: str = Depends(require_agency)):
    if body.status not in ("confirmed", "declined", "completed", "cancelled"):
        raise HTTPException(400, "Invalid status")
    with engine.begin() as conn:
        row = conn.execute(select(visits.c.user_id).where(and_(visits.c.id == visit_id,
                                                               visits.c.agency_id == agency_id))).first()
        if not row:
            raise HTTPException(404, "Visit not found")
        conn.execute(update(visits).where(visits.c.id == visit_id).values(status=body.status))
        if body.status == "completed":
            conn.execute(update(leads).where(and_(leads.c.agency_id == agency_id, leads.c.user_id == row[0]))
                         .values(stage="visited", updated_at=now()))
    return {"ok": True}


@app.get("/admin/followups")
def admin_followups(agency_id: str = Depends(require_agency)):
    with engine.connect() as conn:
        rows = conn.execute(select(followups, profiles.c.data.label("profile"))
                            .join(profiles, profiles.c.user_id == followups.c.user_id, isouter=True)
                            .where(and_(followups.c.agency_id == agency_id, followups.c.status != "cancelled"))
                            .order_by(followups.c.due_at)).mappings().all()
    return [{"id": r["id"], "user_id": r["user_id"], "day": r["day_offset"], "due_at": r["due_at"],
             "message": r["message"], "status": r["status"], "name": (r["profile"] or {}).get("name"),
             "phone": (r["profile"] or {}).get("phone")} for r in rows]


@app.post("/admin/followups/{fid}/sent")
def admin_followup_sent(fid: int, agency_id: str = Depends(require_agency)):
    with engine.begin() as conn:
        n = conn.execute(update(followups).where(and_(followups.c.id == fid, followups.c.agency_id == agency_id))
                         .values(status="sent")).rowcount
    if not n:
        raise HTTPException(404, "Not found")
    return {"ok": True}


def _agency_user_ids(conn, agency_id: str):
    return select(leads.c.user_id).where(leads.c.agency_id == agency_id)


@app.get("/admin/chats")
def admin_chats(agency_id: str = Depends(require_agency)):
    """Conversations of customers who engaged with THIS agency's listings only."""
    with engine.connect() as conn:
        rows = conn.execute(select(chat_log.c.user_id, chat_log.c.thread_id, func.count().label("messages"),
                                   func.max(chat_log.c.created_at).label("last_at"))
                            .where(chat_log.c.user_id.in_(_agency_user_ids(conn, agency_id)))
                            .group_by(chat_log.c.user_id, chat_log.c.thread_id)
                            .order_by(func.max(chat_log.c.created_at).desc()).limit(100)).mappings().all()
    return [dict(r) for r in rows]


@app.get("/admin/chats/{user_id}/{thread_id}")
def admin_chat(user_id: str, thread_id: str, agency_id: str = Depends(require_agency)):
    with engine.connect() as conn:
        allowed = conn.execute(select(leads.c.id).where(and_(leads.c.agency_id == agency_id,
                                                             leads.c.user_id == user_id))).first()
        if not allowed:
            raise HTTPException(404, "Conversation not found")
        rows = conn.execute(select(chat_log.c.role, chat_log.c.content, chat_log.c.tool_calls, chat_log.c.created_at)
                            .where(and_(chat_log.c.user_id == user_id, chat_log.c.thread_id == thread_id))
                            .order_by(chat_log.c.id)).mappings().all()
    return [dict(r) for r in rows]


@app.get("/admin/listings")
def admin_listings(agency_id: str = Depends(require_agency)):
    with engine.connect() as conn:
        rows = conn.execute(select(listings).where(listings.c.agency_id == agency_id)
                            .order_by(listings.c.id)).mappings().all()
    names = _names()
    return [_listing_out(r, names) for r in rows]


class ListingIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    price_pkr: int = Field(gt=0)
    city: str
    area: str = ""
    subtype: str = ""
    make: str = ""
    model: str = ""
    year: Optional[int] = None
    description: str = ""
    specs: dict = {}


def _new_listing_id(conn, category: str) -> str:
    prefix = "C" if category == "car" else "P"
    while True:
        lid = f"{prefix}-{random.randint(500, 9999)}"
        if not conn.execute(select(listings.c.id).where(listings.c.id == lid)).first():
            return lid


def _insert_listing(conn, agency_id: str, kind: str, item: ListingIn) -> str:
    lid = _new_listing_id(conn, kind)
    conn.execute(insert(listings).values(
        id=lid, agency_id=agency_id, category=kind, title=item.title.strip(), subtype=item.subtype.lower() or None,
        make=item.make or None, model=item.model or None, year=item.year, city=item.city.strip().title(),
        area=item.area.strip(), price_pkr=item.price_pkr, specs=item.specs,
        description=item.description or item.title, status="active", created_at=now()))
    return lid


def _agency_kind(conn, agency_id: str) -> str:
    return conn.execute(select(agencies.c.kind).where(agencies.c.id == agency_id)).scalar()


@app.post("/admin/listings")
def admin_add_listing(item: ListingIn, agency_id: str = Depends(require_agency)):
    with engine.begin() as conn:
        lid = _insert_listing(conn, agency_id, _agency_kind(conn, agency_id), item)
    return {"ok": True, "id": lid}


class CsvIn(BaseModel):
    csv: str = Field(max_length=500_000)


@app.post("/admin/listings/upload")
def admin_upload_csv(body: CsvIn, agency_id: str = Depends(require_agency)):
    """CSV columns: title,price_pkr,city,area,subtype,make,model,year,description (+ any extra columns -> specs)."""
    reader = csv.DictReader(io.StringIO(body.csv.strip()))
    base = {"title", "price_pkr", "city", "area", "subtype", "make", "model", "year", "description"}
    created, errors = [], []
    with engine.begin() as conn:
        kind = _agency_kind(conn, agency_id)
        for i, row in enumerate(reader, start=2):
            try:
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                price = row.get("price_pkr", "").replace(",", "")
                price_val = qualifier.parse_budget(price) if not price.isdigit() else int(price)
                item = ListingIn(title=row["title"], price_pkr=price_val or 0, city=row.get("city", ""),
                                 area=row.get("area", ""), subtype=row.get("subtype", ""), make=row.get("make", ""),
                                 model=row.get("model", ""), year=int(row["year"]) if row.get("year") else None,
                                 description=row.get("description", ""),
                                 specs={k: v for k, v in row.items() if k not in base and v})
                created.append(_insert_listing(conn, agency_id, kind, item))
            except Exception as e:
                errors.append(f"row {i}: {type(e).__name__}")
            if len(created) >= 200:
                break
    return {"created": created, "errors": errors}


class ListingStatusIn(BaseModel):
    status: str


@app.patch("/admin/listings/{listing_id}")
def admin_listing_status(listing_id: str, body: ListingStatusIn, agency_id: str = Depends(require_agency)):
    if body.status not in ("active", "sold", "hidden"):
        raise HTTPException(400, "Invalid status")
    with engine.begin() as conn:
        n = conn.execute(update(listings).where(and_(listings.c.id == listing_id, listings.c.agency_id == agency_id))
                         .values(status=body.status)).rowcount
    if not n:
        raise HTTPException(404, "Listing not found")
    return {"ok": True}
