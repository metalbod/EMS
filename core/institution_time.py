"""Today's date in a company's own timezone (institutions.timezone, default UTC)."""
from datetime import datetime
from zoneinfo import ZoneInfo


def institution_today(conn, inst_id: int) -> str:
    """Today's date (YYYY-MM-DD) in the institution's own timezone — what 'overdue' or 'is it their birthday'
    is judged against, not the server's UTC date (which is a day behind for the first hours of a UTC+ day)."""
    row = conn.execute("SELECT timezone FROM institutions WHERE id=?", (inst_id,)).fetchone()
    try:
        tz = ZoneInfo((row["timezone"] if row else None) or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date().isoformat()
