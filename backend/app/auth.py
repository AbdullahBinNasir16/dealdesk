"""Admin authentication: PBKDF2 password hashes + HMAC-signed bearer tokens (no extra deps)."""
import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Header, HTTPException

from . import config

TOKEN_TTL_SECONDS = 12 * 3600


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
    except ValueError:
        return False
    check = hash_password(password, bytes.fromhex(salt_hex)).split("$", 1)[1]
    return hmac.compare_digest(check, digest_hex)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def make_token(agency_id: str) -> str:
    payload = _b64(json.dumps({"agency_id": agency_id, "exp": int(time.time()) + TOKEN_TTL_SECONDS}).encode())
    sig = _b64(hmac.new(config.ADMIN_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str) -> str | None:
    try:
        payload, sig = token.split(".", 1)
        expected = _b64(hmac.new(config.ADMIN_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(_unb64(payload))
        if data.get("exp", 0) < time.time():
            return None
        return data["agency_id"]
    except Exception:
        return None


def require_agency(authorization: str = Header(default="")) -> str:
    """FastAPI dependency: returns the agency_id of the logged-in dealer or raises 401."""
    token = authorization.removeprefix("Bearer ").strip()
    agency_id = read_token(token) if token else None
    if not agency_id:
        raise HTTPException(status_code=401, detail="Login required")
    return agency_id
