"""
agents/signaux.py — v2 robust
─────────────────────────────
Sources qui passent depuis GitHub Actions :
  - Atlanta Fed GDPNow         (HTML scrape — OK)
  - Cleveland Fed              (multiple regex)
  - ForexFactory JSON          (calendrier 3★, pas d'anti-bot)
  - Stooq CSV                  (cours indices, pas de rate limit)
"""

import re
import csv
import json
import logging
from io import StringIO
from datetime import datetime, timezone, timedelta, date
from typing import Dict, List, Optional, Any

import requests
from bs4 import BeautifulSoup

LOG = logging.getLogger(__name__)
PARIS_TZ = timezone(timedelta(hours=1))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

BETAS = {"nq": 0.90, "sp": 0.70, "cac": 0.45}
WEIGHTS = {"inflation": 0.35, "growth": 0.30, "financial": 0.20, "activity": 0.10, "employment": 0.05}
SIGMA = {"GDP": 1.0, "PCE": 0.07, "CPI": 0.10, "CLAIMS": 15000, "ISM": 1.5, "NFP": 50000}


# ════════════════════════════════════════════════
# 1. NOWCASTS
# ════════════════════════════════════════════════
def fetch_gdpnow() -> Optional[float]:
    try:
        r = requests.get("https://www.atlantafed.org/cqer/research/gdpnow",
                         headers=HEADERS, timeout=15)
        r.raise_for_status()
        m = re.search(r'GDPNow.*?(-?\d+\.\d+)\s*percent', r.text, re.I | re.S)
        if m:
            return float(m.group(1))
    except Exception as e:
        LOG.warning(f"GDPNow fetch failed: {e}")
    return None


def fetch_cleveland_nowcast() -> Dict[str, Optional[float]]:
    out = {"core_pce_mm": None, "core_pce_yy": None, "headline_pce_mm": None,
           "core_cpi_mm": None, "headline_cpi_mm": None}
    try:
        r = requests.get("https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting",
                         headers=HEADERS, timeout=15)
        r.raise_for_status()
        text = r.text
        patterns = {
            "core_pce_mm":     [r'Core PCE[^<]*Month[^<]*<[^>]*>\s*(\d+\.\d+)',
                                r'core[_\s-]?pce[_\s-]?mm["\s:>]+(\d+\.\d+)'],
            "core_pce_yy":     [r'Core PCE[^<]*Year[^<]*<[^>]*>\s*(\d+\.\d+)'],
            "headline_pce_mm": [r'PCE Inflation[^<]*Month[^<]*<[^>]*>\s*(\d+\.\d+)'],
            "core_cpi_mm":     [r'Core CPI[^<]*Month[^<]*<[^>]*>\s*(\d+\.\d+)'],
            "headline_cpi_mm": [r'CPI Inflation[^<]*Month[^<]*<[^>]*>\s*(\d+\.\d+)'],
        }
        for key, pats in patterns.items():
            for pat in pats:
                m = re.search(pat, text, re.I | re.S)
                if m:
                    try:
                        out[key] = float(m.group(1))
                        break
                    except ValueError:
                        continue
    except Exception as e:
        LOG.warning(f"Cleveland fetch failed: {e}")
    return out


# ════════════════════════════════════════════════
# 2. CALENDRIER ECO — ForexFactory JSON
# ════════════════════════════════════════════════
def fetch_forexfactory_calendar() -> List[Dict[str, Any]]:
    """ForexFactory expose un JSON public avec events de la semaine, pas d'anti-bot."""
    events = []
    try:
        r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                         headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        today_str = date.today().strftime("%Y-%m-%d")

        for ev in data:
            try:
                if ev.get("country") != "USD":
                    continue
                if ev.get("impact") != "High":
                    continue
                ev_date_full = ev.get("date", "")
                ev_date = ev_date_full[:10]
                if ev_date != today_str:
                    continue

                # Time format ISO: "2026-04-30T14:30:00-04:00" → convert to Paris
                time_str = "—"
                if "T" in ev_date_full:
                    try:
                        # Parse with timezone
                        dt = datetime.fromisoformat(ev_date_full.replace("Z", "+00:00"))
                        # Convert to Paris (UTC+1 simple)
                        dt_paris = dt.astimezone(PARIS_TZ)
                        time_str = dt_paris.strftime("%H:%M")
                    except Exception:
                        time_str = ev_date_full[11:16]

                events.append({
                    "time": time_str,
                    "name": ev.get("title", ""),
                    "consensus": ev.get("forecast", ""),
                    "previous": ev.get("previous", ""),
                    "stars": 3,
                })
            except Exception as e:
                LOG.debug(f"FF row parse: {e}")
                continue
        LOG.info(f"ForexFactory events fetched: {len(events)}")
    except Exception as e:
        LOG.warning(f"ForexFactory fetch failed: {e}")
    return events


# ════════════════════════════════════════════════
# 3. INDICES — Stooq CSV
# ════════════════════════════════════════════════
def fetch_stooq(symbol: str) -> Optional[float]:
    try:
        r = requests.get(f"https://stooq.com/q/l/?s={symbol}&i=d",
                         headers=HEADERS, timeout=10)
        r.raise_for_status()
        reader = csv.DictReader(StringIO(r.text))
        for row in reader:
            close = row.get("Close")
            if close and close != "N/D":
                return float(close)
    except Exception as e:
        LOG.warning(f"Stooq {symbol} failed: {e}")
    return None


def fetch_indices_live() -> Dict[str, Optional[float]]:
    return {
        "nq":  fetch_stooq("nq.f"),
        "sp":  fetch_stooq("es.f"),
        "cac": fetch_stooq("^cac"),
    }


# ════════════════════════════════════════════════
# 4. CLASSIFIER
# ════════════════════════════════════════════════
def classify_event(name: str) -> Optional[Dict[str, str]]:
    n = name.lower()
    if "gdp" in n or "pib" in n:
        return {"cluster": "growth", "nowcast_key": "gdpnow", "sigma_key": "GDP"}
    if "core pce" in n and ("m/m" in n or "mom" in n or "month" in n):
        return {"cluster": "inflation", "nowcast_key": "core_pce_mm", "sigma_key": "PCE"}
    if "core pce" in n and ("y/y" in n or "yoy" in n or "year" in n):
        return {"cluster": "inflation", "nowcast_key": "core_pce_yy", "sigma_key": "PCE"}
    if "pce" in n and "core" not in n:
        return {"cluster": "inflation", "nowcast_key": "headline_pce_mm", "sigma_key": "PCE"}
    if "core cpi" in n:
        return {"cluster": "inflation", "nowcast_key": "core_cpi_mm", "sigma_key": "CPI"}
    if "cpi" in n:
        return {"cluster": "inflation", "nowcast_key": "headline_cpi_mm", "sigma_key": "CPI"}
    if "non-farm" in n or "nonfarm" in n or "nfp" in n or "payrolls" in n:
        return {"cluster": "employment", "nowcast_key": None, "sigma_key": "NFP"}
    if "claims" in n or "unemployment" in n:
        return {"cluster": "employment", "nowcast_key": None, "sigma_key": "CLAIMS"}
    if "ism" in n or "pmi" in n:
        return {"cluster": "activity", "nowcast_key": None, "sigma_key": "ISM"}
    if "fomc" in n or "fed" in n or "interest rate" in n:
        return {"cluster": "financial", "nowcast_key": None, "sigma_key": None}
    return None


def parse_pct(s: str) -> Optional[float]:
    if not s:
        return None
    s = s.replace(",", ".").strip()
    m = re.search(r"(-?\d+\.?\d*)", s)
    if not m:
        return None
    val = float(m.group(1))
    if "K" in s.upper():
        val *= 1000
    if "M" in s.upper():
        val *= 1_000_000
    return val


# ════════════════════════════════════════════════
# 5. SIGNAL & COMPOSITE
# ════════════════════════════════════════════════
def compute_event_signal(event: Dict, nowcasts: Dict) -> Dict:
    cls = classify_event(event["name"])
    consensus = parse_pct(event.get("consensus", ""))
    previous = parse_pct(event.get("previous", ""))

    out = {**event, "cluster": cls["cluster"] if cls else None,
           "nowcast": None, "z_signal": 0.0, "direction": "neutral",
           "conviction": 0, "delta": "—", "delta_dir": "flat"}

    if not cls or consensus is None:
        return out

    nc_val = None
    if cls["nowcast_key"] == "gdpnow":
        nc_val = nowcasts.get("gdpnow")
    elif cls["nowcast_key"]:
        nc_val = nowcasts.get(cls["nowcast_key"])

    if nc_val is None:
        if previous is not None:
            nc_val = previous
        else:
            return out

    out["nowcast"] = nc_val
    sigma = SIGMA.get(cls["sigma_key"], 1.0)
    delta = nc_val - consensus
    z = delta / sigma if sigma else 0
    out["z_signal"] = z

    if cls["cluster"] == "inflation":
        direction = "bullish" if z < -0.5 else "bearish" if z > 0.5 else "neutral"
    elif cls["cluster"] in ("growth", "employment"):
        direction = "bullish" if z > 0.5 else "bearish" if z < -0.5 else "neutral"
    else:
        direction = "neutral"
    out["direction"] = direction

    conv = min(10, max(1, int(abs(z) * 5)))
    out["conviction"] = conv

    sign = "+" if delta > 0 else "−" if delta < 0 else ""
    if cls["sigma_key"] == "GDP":
        out["delta"] = f"{sign}{abs(delta):.1f}pt"
    elif cls["sigma_key"] in ("PCE", "CPI"):
        out["delta"] = f"{sign}{abs(delta):.2f}"
    else:
        out["delta"] = f"{sign}{abs(delta):.0f}"

    out["delta_dir"] = "dn" if (
        (cls["cluster"] == "inflation" and z > 0) or
        (cls["cluster"] in ("growth", "employment") and z < 0)
    ) else "up" if z != 0 else "flat"

    return out


def compute_composite(events: List[Dict]) -> Dict:
    cluster_z = {k: [] for k in WEIGHTS.keys()}
    for ev in events:
        c = ev.get("cluster")
        if c and c in cluster_z:
            z = ev["z_signal"]
            if c == "inflation":
                z = -z
            cluster_z[c].append(z)

    composite = 0.0
    for cluster, w in WEIGHTS.items():
        zs = cluster_z[cluster]
        avg = sum(zs) / len(zs) if zs else 0.0
        composite += w * avg

    direction = "bearish" if composite < -0.3 else "bullish" if composite > 0.3 else "neutral"
    conviction = min(10, max(1, int(abs(composite) * 5)))
    return {
        "composite_z": round(composite, 2),
        "direction": direction,
        "conviction": conviction,
    }


def compute_projections(composite_z: float, indices_live: Dict) -> Dict:
    out = {}
    for k, beta in BETAS.items():
        now = indices_live.get(k)
        if now is None:
            out[k] = {"now": None, "target": None, "pct": 0.0}
            continue
        pct = beta * composite_z
        target = now * (1 + pct / 100)
        out[k] = {
            "now": round(now, 0) if now > 100 else round(now, 2),
            "target": round(target, 0) if now > 100 else round(target, 2),
            "pct": round(pct, 1),
        }
    return out


# ════════════════════════════════════════════════
# 6. ORCHESTRATOR
# ════════════════════════════════════════════════
def build_signaux(prev_state: Optional[Dict] = None) -> Dict:
    LOG.info("Building signaux v2...")

    gdpnow = fetch_gdpnow()
    cleveland = fetch_cleveland_nowcast()
    raw_events = fetch_forexfactory_calendar()
    indices = fetch_indices_live()

    nowcasts = {"gdpnow": gdpnow, **cleveland}
    LOG.info(f"GDPNow={gdpnow}, Cleveland set={sum(1 for v in cleveland.values() if v)}, "
             f"events={len(raw_events)}, indices set={sum(1 for v in indices.values() if v)}")

    fetch_failed = (
        gdpnow is None and
        all(v is None for v in cleveland.values()) and
        len(raw_events) == 0 and
        all(v is None for v in indices.values())
    )
    if fetch_failed and prev_state:
        LOG.warning("All fetches failed, returning previous state")
        prev_state["_stale"] = True
        prev_state["_last_attempt"] = datetime.now(PARIS_TZ).strftime("%Y-%m-%d %H:%M")
        return prev_state

    processed = [compute_event_signal(ev, nowcasts) for ev in raw_events]
    actionable = [ev for ev in processed if ev.get("cluster")]

    if actionable:
        comp = compute_composite(actionable)
    else:
        comp = {"composite_z": 0.0, "direction": "neutral", "conviction": 0}

    proj = compute_projections(comp["composite_z"], indices)

    today_str = datetime.now(PARIS_TZ).strftime("%d %b").lower()
    direction_label = {"bearish": "Bearish", "bullish": "Bullish",
                       "neutral": "Neutre"}[comp["direction"]]

    first_time = actionable[0]["time"] if actionable else "—"
    n_events = len(actionable)
    if n_events == 0:
        if len(raw_events) == 0:
            sub = "Aucun event 3★ aujourd'hui · marché calme"
        else:
            sub = f"{len(raw_events)} event(s) 3★ non actionnable(s)"
    else:
        sub = f"{n_events} event{'s' if n_events>1 else ''} 3★ aujourd'hui · max vol {first_time} CET"

    events_out = []
    for ev in actionable:
        cluster = ev.get("cluster")
        cls_short = {"inflation": "Inflation", "growth": "Croissance",
                     "employment": "Emploi", "activity": "Activité",
                     "financial": "Fed/BCE"}.get(cluster, "—")
        if cluster == "financial":
            label1, label2 = "Marché", "Pricé"
        else:
            label1, label2 = "Marché", "Modèle"

        val1 = ev.get("consensus", "—") or "—"
        if ev.get("nowcast") is not None:
            val2 = (f"{ev['nowcast']:.1f}%" if cluster == "growth"
                    else f"{ev['nowcast']:.2f}%")
        else:
            val2 = val1

        events_out.append({
            "time": ev.get("time", "—"),
            "name": ev.get("name", "—"),
            "stars": ev.get("stars", 3),
            "direction": ev.get("direction", "neutral"),
            "label1": label1,
            "val1": val1,
            "label2": label2,
            "val2": val2,
            "delta": ev.get("delta", "—"),
            "delta_dir": ev.get("delta_dir", "flat"),
            "conviction": ev.get("conviction", 0),
            "cluster_label": cls_short,
        })

    return {
        "recap": {
            "tag": f"Recap macro · {today_str}",
            "date": today_str,
            "direction": comp["direction"],
            "direction_label": direction_label,
            "conviction": comp["conviction"],
            "composite_z": comp["composite_z"],
            "sub": sub,
            "indices": proj,
            "window": f"Fenêtre {first_time}" if first_time != "—" else "Pas d'event",
            "window_note": f"vol max post-{first_time}" if first_time != "—" else "Marché calme",
        },
        "events": events_out,
        "_generated_at": datetime.now(PARIS_TZ).strftime("%Y-%m-%d %H:%M"),
        "_stale": False,
        "_diag": {
            "gdpnow": gdpnow,
            "cleveland_set": {k: v for k, v in cleveland.items() if v is not None},
            "events_total_fetched": len(raw_events),
            "events_actionable": len(actionable),
            "indices_set": {k: v for k, v in indices.items() if v is not None},
        },
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s · %(message)s")
    result = build_signaux()
    print(json.dumps(result, indent=2, ensure_ascii=False))
