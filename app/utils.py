from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC now -- matches the naive DateTime columns used throughout
    the schema (SQLite/PostgreSQL DateTime without timezone)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
