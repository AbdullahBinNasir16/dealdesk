"""Database schema + engine (SQLAlchemy Core). Works on Postgres (prod) and SQLite (local dev)."""
from datetime import datetime, timezone

from sqlalchemy import (JSON, Column, DateTime, Integer, MetaData, String, Table, Text,
                        UniqueConstraint, create_engine)

from . import config

metadata = MetaData()

agencies = Table(
    "agencies", metadata,
    Column("id", String(40), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("kind", String(20), nullable=False),          # property | car
    Column("city", String(60)),
    Column("phone", String(30)),
    Column("username", String(60), unique=True, nullable=False),
    Column("password_hash", String(200), nullable=False),
)

listings = Table(
    "listings", metadata,
    Column("id", String(20), primary_key=True),          # P-101 (property) / C-201 (car)
    Column("agency_id", String(40), nullable=False, index=True),
    Column("category", String(20), nullable=False, index=True),  # property | car
    Column("title", String(200), nullable=False),
    Column("subtype", String(40)),                       # plot/house/apartment/commercial | sedan/suv/hatchback
    Column("make", String(40)),
    Column("model", String(60)),
    Column("year", Integer),
    Column("city", String(60), index=True),
    Column("area", String(120)),
    Column("price_pkr", Integer, nullable=False, index=True),
    Column("specs", JSON, default=dict),                 # size, beds, mileage, transmission, ...
    Column("description", Text),
    Column("status", String(20), default="active"),      # active | sold | hidden
    Column("created_at", DateTime(timezone=True)),
)

# Long-term memory: one row per customer (user_id), shared by every thread of that customer.
profiles = Table(
    "profiles", metadata,
    Column("user_id", String(120), primary_key=True),
    Column("data", JSON, default=dict),
    Column("updated_at", DateTime(timezone=True)),
)

# A lead = one customer's interest in one agency's inventory. Agencies only ever see their own rows.
leads = Table(
    "leads", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("agency_id", String(40), nullable=False, index=True),
    Column("user_id", String(120), nullable=False, index=True),
    Column("stage", String(30), default="new"),          # new|qualifying|qualified|visit_booked|visited|won|lost
    Column("score", Integer, default=0),
    Column("interested", JSON, default=list),            # listing ids shown / asked about
    Column("last_thread_id", String(200)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    UniqueConstraint("agency_id", "user_id", name="uq_lead_agency_user"),
)

visits = Table(
    "visits", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", String(120), nullable=False, index=True),
    Column("agency_id", String(40), nullable=False, index=True),
    Column("listing_id", String(20), nullable=False),
    Column("kind", String(20)),                          # site_visit | test_drive
    Column("scheduled_at", String(40), nullable=False),  # ISO-8601 with offset (PKT)
    Column("customer_name", String(120)),
    Column("customer_phone", String(30)),
    Column("status", String(20), default="requested"),   # requested|confirmed|declined|cancelled|completed
    Column("created_at", DateTime(timezone=True)),
)

followups = Table(
    "followups", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("lead_id", Integer, nullable=False, index=True),
    Column("agency_id", String(40), nullable=False, index=True),
    Column("user_id", String(120), nullable=False),
    Column("day_offset", Integer),
    Column("due_at", DateTime(timezone=True)),
    Column("message", Text),
    Column("status", String(20), default="pending"),     # pending | sent | cancelled
)

# Readable transcript for the admin dashboard (the agent's own short-term memory lives in the
# LangGraph checkpointer tables, keyed by thread_id).
chat_log = Table(
    "chat_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", String(120), nullable=False, index=True),
    Column("thread_id", String(200), nullable=False, index=True),
    Column("role", String(20)),
    Column("content", Text),
    Column("tool_calls", JSON, default=list),
    Column("tokens_in", Integer, default=0),
    Column("tokens_out", Integer, default=0),
    Column("created_at", DateTime(timezone=True)),
)

_engine_kwargs = {"pool_pre_ping": True, "future": True}
if config.is_postgres():
    _engine_kwargs.update(pool_size=5, max_overflow=5, pool_recycle=280)
else:
    _engine_kwargs.update(connect_args={"check_same_thread": False})

engine = create_engine(config.sqlalchemy_url(), **_engine_kwargs)


def now() -> datetime:
    return datetime.now(timezone.utc)


def init_db() -> None:
    metadata.create_all(engine)
