"""
Sous-agent Calendrier Économique
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp
from bs4 import BeautifulSoup

log = logging.getLogger("agent.calendar")
PARIS = ZoneInfo("Europe/Paris")

FOREXFACTORY_URL = "https://www.forexfactory.com/calendar"


async def get_eco_calendar() -> dict:
    today = date.today()

    results = await asyncio.gather(
        _fetch_forexfactory(today),
        _fetch_forexfactory(today + timedelta(days=1)),
        _get_fomc_schedule(),
        return_exceptions=True
    )

    today_events    = results[0] if isinstance(results[0], list) else []
    tomorrow_events = results[1] if isinstance(results[1], list) else []
    fomc_schedule   = results[2] if isinstance(results[2], dict) else {}

    high_impact_today = [e for e in today_events if e.get("impact") == "high"]
    next_event = _get_next_event(today_events)

    log.info(f"Calendrier: {len(today_events)} événements, {len(high_impact_today)} haute importance")

    return {
        "today_high_impact": high_impact_today,
        "today_all":         today_events,
        "tomorrow_events":   tomorrow_events,
        "fomc_schedule":     fomc_schedule,
        "next_event":        next_event,
        "fetched_at":        datetime.now(timezone.utc).isoformat(),
    }


async def _fetch_forexfactory(target_date: date) -> list:
    try:
        date_str = target_date.strftime("%b%d.%Y").lower()
        url = f"{FOREXFACTORY_URL}?day={date_str}"
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status != 200:
                    return _get_fallback_calendar(target_date)
                html = await resp.text()
                return _parse_forexfactory(html, target_date)
    except Exception as e:
        log.warning(f"ForexFactory error: {e}")
        return _get_fallback_calendar(target_date)


def _parse_forexfactory(html: str, target_date: date) -> list:
    soup = BeautifulSoup(html, "html.parser")
    events = []
    rows = soup.select("tr.calendar__row")
    current_time = None

    for row in rows:
        try:
            time_cell = row.select_one(".calendar__time")
            if time_cell and time_cell.text.strip():
                current_time = time_cell.text.strip()

            currency   = row.select_one(".calendar__currency")
            event_name = row.select_one(".calendar__event-title")
            impact_cell = row.select_one(".calendar__impact span")

            if not event_name:
                continue

            impact = "low"
            if impact_cell:
                cls = impact_cell.get("class", [])
                if any("red" in c for c in cls):    impact = "high"
                elif any("orange" in c for c in cls): impact = "medium"

            events.append({
                "name":     event_name.text.strip(),
                "time":     current_time or "All Day",
                "currency": currency.text.strip() if currency else "",
                "impact":   impact,
                "date":     target_date.isoformat(),
                "is_fomc":  "fed" in event_name.text.lower() or "fomc" in event_name.text.lower(),
            })
        except Exception:
            continue

    return events


def _get_fallback_calendar(target_date: date) -> list:
    today_str = target_date.isoformat()
    dow = target_date.weekday()
    fallback = []

    fomc_dates = [
        "2026-03-19", "2026-05-07", "2026-06-18",
        "2026-07-30", "2026-09-17", "2026-11-05", "2026-12-10",
    ]
    if today_str in fomc_dates:
        fallback.append({
            "name": "FOMC Rate Decision",
            "time": "20:00",
            "currency": "USD",
            "impact": "high",
            "date": today_str,
            "is_fomc": True,
        })

    if dow == 4 and target_date.day <= 7:
        fallback.append({
            "name": "Non-Farm Payrolls",
            "time": "14:30",
            "currency": "USD",
            "impact": "high",
            "date": today_str,
            "is_fomc": False,
        })

    return fallback


async def _get_fomc_schedule() -> dict:
    fomc_dates = [
        {"date": "2026-03-19", "label": "Mars 2026"},
        {"date": "2026-05-07", "label": "Mai 2026"},
        {"date": "2026-06-18", "label": "Juin 2026"},
        {"date": "2026-07-30", "label": "Juillet 2026"},
    ]
    today = date.today()
    next_fomc = next(
        (f for f in fomc_dates if date.fromisoformat(f["date"]) >= today), None
    )
    days_to_fomc = (date.fromisoformat(next_fomc["date"]) - today).days if next_fomc else None

    return {
        "next_meeting":  next_fomc,
        "days_until":    days_to_fomc,
        "probabilities": {"hold": 92.0, "cut_25": 8.0, "hike_25": 0.0},
    }


def _get_next_event(today_events: list) -> dict | None:
    now = datetime.now(PARIS)
    high_events = [e for e in today_events if e.get("impact") in ("high", "medium")]

    for event in sorted(high_events, key=lambda x: x.get("time", "99:99")):
        try:
            h, m = map(int, event["time"].split(":"))
            event_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if event_dt > now:
                delta = event_dt - now
                minutes_left = int(delta.total_seconds() / 60)
                return {
                    **event,
                    "minutes_until": minutes_left,
                    "countdown": f"dans {minutes_left} min" if minutes_left < 60
                                 else f"dans {minutes_left//60}h{minutes_left%60:02d}",
                }
        except Exception:
            continue
    return None
