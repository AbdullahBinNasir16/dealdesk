"""Central configuration, read from environment variables (.env supported locally)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("MODEL", "claude-haiku-5-5")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "600"))

# Postgres (Neon / Supabase) in production. Falls back to a local SQLite file for development only.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_PATH = os.getenv("SQLITE_PATH", str(ROOT / "dealdesk.db"))

# Signs admin login tokens. MUST be set to a long random string in production.
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "dev-secret-change-me")

# Comma separated list of allowed browser origins for the website, "*" for any.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

TIMEZONE = os.getenv("TIMEZONE", "Asia/Karachi")
BUSINESS_OPEN_HOUR = 10   # visits / test drives allowed from 10:00
BUSINESS_CLOSE_HOUR = 19  # ... until 19:00 (last slot 18:30)
MAX_MESSAGE_CHARS = 2000
HISTORY_TRIGGER = 16      # summarise when the thread holds more messages than this
HISTORY_KEEP = 6          # keep roughly this many recent messages verbatim


def is_postgres() -> bool:
    return DATABASE_URL.startswith(("postgres://", "postgresql://", "postgresql+psycopg://"))


def sqlalchemy_url() -> str:
    if not is_postgres():
        return f"sqlite:///{SQLITE_PATH}"
    url = DATABASE_URL
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def psycopg_url() -> str:
    """Plain libpq URL for the LangGraph Postgres checkpointer."""
    return DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)
