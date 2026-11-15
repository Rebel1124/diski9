"""Custom column types for exact, portable storage in SQLite."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes stored as ISO-8601 text (sortable)."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"expected datetime, got {type(value).__name__}")
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not allowed; use UTC-aware values")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return datetime.fromisoformat(value).astimezone(UTC)


class DecimalText(TypeDecorator):
    """Exact decimals (odds) stored as normalised text, returned as ``Decimal``."""

    impl = String(20)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        d = Decimal(str(value))
        if not d.is_finite():
            raise ValueError("non-finite decimal")
        return format(d.normalize(), "f")

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)
