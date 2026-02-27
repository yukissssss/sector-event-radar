from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Tuple

from .models import Event


def _is_tz_aware(dt: datetime) -> bool:
    return dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None


def validate_event(event: Event, now: datetime | None = None) -> Tuple[bool, str]:
    """Spec M4: (passed, rejection_reason) を返す。"""
    if now is None:
        now = datetime.now(timezone.utc)

    if event.action == "ignore":
        return (False, "action=ignore")

    # Rule 1
    if not _is_tz_aware(event.start_at):
        return (False, "start_at missing timezone")

    # Rule 2
    if event.end_at is not None:
        if not _is_tz_aware(event.end_at):
            return (False, "end_at missing timezone")
        if event.end_at <= event.start_at:
            return (False, "end_at <= start_at")

    # Rule 3
    if event.action in ("add", "update"):
        if event.start_at < (now - timedelta(days=7)):
            return (False, "start_at is older than now-7d for add/update")

    # Rule 4
    if event.start_at > (now + timedelta(days=365 * 3)):
        return (False, "start_at is later than now+3y")

    # Rule 5
    if len(event.evidence.strip()) < 12:
        return (False, "evidence too short (<12)")

    # Rule 6
    if event.category == "macro" and event.risk_score < 20:
        return (False, "macro risk_score < 20")

    # Rule 7
    if event.category == "shock" and event.risk_score < 30:
        return (False, "shock risk_score < 30")

    return (True, "")
