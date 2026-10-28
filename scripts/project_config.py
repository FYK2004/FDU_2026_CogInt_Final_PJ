"""Shared paths and explicit information cutoff, never inferred from run time."""
from pathlib import Path
import datetime as dt
import os

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = Path(os.environ.get("PJ_PROCESSED", str(ROOT / "data" / "processed")))
AS_OF = dt.date.fromisoformat(os.environ.get("PJ_AS_OF", "2026-10-14"))
SEED = 20261007


def market_deadline(row):
    """Inclusive ET deadline from contract label; UTC endDate is metadata."""
    return dt.datetime.strptime(row["deadline"], "%B %d, %Y").date()


def cutoff_utc(day=AS_OF):
    from zoneinfo import ZoneInfo
    return dt.datetime.combine(day + dt.timedelta(days=1), dt.time(),
                               ZoneInfo("America/New_York")).astimezone(dt.timezone.utc)
