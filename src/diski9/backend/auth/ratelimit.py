"""Application-side rate limits for authentication endpoints (in addition to
Supabase Auth's own limits). Keys (IP addresses, email addresses) are stored only
as keyed hashes."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Connection, delete, func, insert, select

from ..db import db_now
from ..db.schema import auth_rate_events
from .crypto import derive


@dataclass(frozen=True)
class Limit:
    bucket: str
    limit: int
    window: timedelta


# (per client IP, per email address, per user) - deliberately conservative
SIGN_IN_IP = Limit("sign_in:ip", 20, timedelta(minutes=15))
SIGN_IN_EMAIL = Limit("sign_in:email", 8, timedelta(minutes=15))
SIGN_UP_IP = Limit("sign_up:ip", 5, timedelta(hours=1))
RECOVERY_IP = Limit("recovery:ip", 10, timedelta(hours=1))
RECOVERY_EMAIL = Limit("recovery:email", 3, timedelta(hours=1))
REAUTH_USER = Limit("reauth:user", 6, timedelta(minutes=15))
CONFIRM_IP = Limit("confirm:ip", 30, timedelta(minutes=15))


def hit(conn: Connection, secret: bytes, limit: Limit, key: str) -> bool:
    """Record an attempt; False when the limit for ``key`` is already reached."""
    key_hash = derive(secret, f"rl:{limit.bucket}", key.strip().lower())
    now = db_now(conn)
    count = conn.execute(
        select(func.count())
        .select_from(auth_rate_events)
        .where(
            auth_rate_events.c.bucket == limit.bucket,
            auth_rate_events.c.key_hash == key_hash,
            auth_rate_events.c.at > now - limit.window,
        )
    ).scalar_one()
    if count >= limit.limit:
        return False
    conn.execute(insert(auth_rate_events).values(bucket=limit.bucket, key_hash=key_hash))
    if secrets.randbelow(50) == 0:  # occasional purge of old events
        conn.execute(
            delete(auth_rate_events).where(auth_rate_events.c.at < now - timedelta(days=1))
        )
    return True
