"""Today's events from one or more ICS feeds (Google/Outlook/iCloud secret iCal URLs all work)."""
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

from http_util import get_bytes


def fetch(cfg):
    cal_cfg = cfg.get("calendar") or {}
    sources = cal_cfg.get("ics_urls") or []
    tz = ZoneInfo(cfg["location"]["timezone"])
    if not sources:
        return {"configured": False, "events": []}

    import icalendar
    import recurring_ical_events

    now = datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now + timedelta(hours=cal_cfg.get("lookahead_hours", 36))
    events = []
    for src in sources:
        name = src.get("name") if isinstance(src, dict) else None
        url = src["url"] if isinstance(src, dict) else src
        cal = icalendar.Calendar.from_ical(get_bytes(url, timeout=30))
        for ev in recurring_ical_events.of(cal).between(start, end):
            ds = ev.get("DTSTART").dt
            de = ev.get("DTEND").dt if ev.get("DTEND") else None
            all_day = not isinstance(ds, datetime)
            if all_day:
                s = datetime.combine(ds, time.min, tz)
                e = datetime.combine(de, time.min, tz) if isinstance(de, date) else s + timedelta(days=1)
            else:
                s = (ds if ds.tzinfo else ds.replace(tzinfo=tz)).astimezone(tz)
                e = (de if de.tzinfo else de.replace(tzinfo=tz)).astimezone(tz) if de else None
            events.append({
                "title": str(ev.get("SUMMARY") or "(untitled)"),
                "start": s.isoformat(),
                "end": e.isoformat() if e else None,
                "all_day": all_day,
                "location": str(ev.get("LOCATION") or ""),
                "calendar": name,
            })
    events.sort(key=lambda x: (x["start"], not x["all_day"]))
    return {"configured": True, "events": events}
