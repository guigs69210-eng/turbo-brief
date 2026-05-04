"""
agents/signaux.py
─────────────────
Pipeline auto pour onglet Signaux de trade.html.

Sources fetchées :
  - Atlanta Fed GDPNow         (HTML scrape)
  - Cleveland Fed nowcast       (CSV public)
  - Investing.com calendar      (HTML scrape, filtre US 3★)
  - Yahoo Finance               (cours live NQ / SP500 / CAC40)

Sortie : dict prêt à merger dans report_data.json sous la clé "signaux".

Robustesse : si une source fail, on garde l'état précédent du JSON.
"""

import re
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

import requests
from bs4 import BeautifulSoup

LOG = logging.getLogger(__name__)
PARIS_TZ = timezone(timedelta(hours=1))  # CET; ajuster pour DST si besoin
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}

# ─── BETAS empiriques (calibration historique 12M) ───
BETAS = {
    "nq":  0.90,   # Nasdaq, rate-sensitive
    "sp":  0.70,   # S&P 500
    "cac": 0.45,   # CAC 40, dampened
}

# Cluster weights (IC × variance contribution recalibrés)
WEIGHTS = {
    "inflation":  0.35,
    "growth":     0.30,
    "financial":  0.20,
    "activity":   0.10,
    "employment": 0.05,
}

# Sigma historiques pour Z-score
SIGMA = {
    "GDP":      1.0,    # pt SAAR
    "PCE":      0.07,   # pt m/m
    "CPI":      0.10,
    "CLAIMS":   15000,  # initial claims
    "ISM":      1.5,
    "NFP":      50000,
}


# ════════════════════════════════════════════════
# 1. FETCHERS
# ════════════════════════════════════════════════

def fetch_gdpnow() -> Optional[float]:
    """Atlanta Fed GDPNow latest estimate (% SAAR)."""
    try:
        url = "https://www.atlantafed.org/cqer/research/gdpnow"
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        # Regex sur le format "X.X percent"
        match = re.search(r'GDPNow.*?(-?\d+\.\d+)\s*percent', r.text, re.IGNORECASE | re.DOTALL)
        if match:
            return float(match.group(1))
    except Exception as e:
        LOG.warning(f"GDPNow fetch failed: {e}")
    return None


def fetch_cleveland_nowcast() -> Dict[str, Optional[float]]:
    """Cleveland Fed inflation nowcasting CPI/PCE."""
    out = {"core_pce_mm": None, "core_pce_yy": None, "headline_pce_mm": None}
    try:
        url = "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting"
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        # Le site publie un tableau avec headers nowcast/forecast
        text = soup.get_text(" ", strip=True)
        # Recherche pattern "Core PCE 0.XX%"
        m1 = re.search(r'core\s+pce.*?(\d+\.\d+)\s*%', text, re.IGNORECASE)
        if m1:
            out["core_pce_mm"] = float(m1.group(1))
        m2 = re.search(r'headline\s+pce.*?(\d+\.\d+)\s*%', text, re.IGNORECASE)
        if m2:
            out["headline_pce_mm"] = float(m2.group(1))
    except Exception as e:
        LOG.warning(f"Cleveland Fed fetch failed: {e}")
    return out


def fetch_investing_calendar() -> List[Dict[str, Any]]:
    """
    Scrape Investing.com economic calendar — US 3★ only, today.
    Returns list of dicts: time, name, currency, consensus, previous, importance.
    """
    events = []
    try:
        # Endpoint widget calendar
        url = "https://sslecal2.investing.com"
        params = {
            "importance": 3,
            "countries": 5,        # 5 = US
            "calType": "day",
            "timeZone": 58,        # CET
            "lang": 5,
        }
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Le widget Investing rend un tableau avec lignes .js-event-item
        rows = soup.find_all("tr", class_=lambda c: c and "js-event-item" in c)
        for row in rows:
            try:
                time_el = row.find("td", class_="first")
                name_el = row.find("td", class_="event")
                cons_el = row.find("td", class_="forecast")
                prev_el = row.find("td", class_="previous")
                imp_el = row.find("td", class_="sentiment")
                # Compter les étoiles (full bull icons)
                stars = len(imp_el.find_all("i", class_="grayFullBullishIcon")) if imp_el else 0
                if stars < 3:
                    continue
                events.append({
                    "time": time_el.get_text(strip=True) if time_el else "",
                    "name": name_el.get_text(strip=True) if name_el else "",
                    "consensus": cons_el.get_text(strip=True) if cons_el else "",
                    "previous": prev_el.get_text(strip=True) if prev_el else "",
                    "stars": stars,
                })
            except Exception as e:
                LOG.debug(f"row parse failed: {e}")
                continue
    except Exception as e:
        LOG.warning(f"Investing calendar fetch failed: {e}")
    return events


def fetch_indices_live() -> Dict[str, Optional[float]]:
    """Fetch live levels for NQ futures, SP500, CAC40 via Yahoo Finance."""
    out = {"nq": None, "sp": None, "cac": None}
    tickers = {"nq": "NQ=F", "sp": "ES=F", "cac": "^FCHI"}
    for k, sym in tickers.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d"
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.raise_for_status()
            data = r.json()
            price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
            out[k] = float(price)
        except Exception as e:
            LOG.warning(f"Yahoo {sym} fetch failed: {e}")
    return out


# ════════════════════════════════════════════════
# 2. EVENT CLASSIFIER & MAPPER
# ════════════════════════════════════════════════

def classify_event(name: str) -> Optional[Dict[str, str]]:
    """
    Map raw Investing event name → cluster + nowcast key.
    Returns None if event isn't actionable for our system.
    """
    n = name.lower()
    if "gdp" in n or "pib" in n:
        return {"cluster": "growth", "nowcast_key": "gdpnow", "sigma_key": "GDP"}
    if "core pce" in n and ("m/m" in n or "mensuel" in n or "mom" in n):
        return {"cluster": "inflation", "nowcast_key": "core_pce_mm", "sigma_key": "PCE"}
    if "core pce" in n and ("y/y" in n or "annuel" in n or "yoy" in n):
        return {"cluster": "inflation", "nowcast_key": "core_pce_yy", "sigma_key": "PCE"}
    if "pce" in n and "core" not in n:
        return {"cluster": "inflation", "nowcast_key": "headline_pce_mm", "sigma_key": "PCE"}
    if "cpi" in n or "inflation" in n:
        return {"cluster": "inflation", "nowcast_key": None, "sigma_key": "CPI"}
    if "non-farm" in n or "nfp" in n or "payrolls" in n:
        return {"cluster": "employment", "nowcast_key": None, "sigma_key": "NFP"}
    if "claims" in n or "chômage" in n.replace("ô", "o").replace("ó", "o"):
        return {"cluster": "employment", "nowcast_key": None, "sigma_key": "CLAIMS"}
    if "ism" in n or "pmi" in n:
        return {"cluster": "activity", "nowcast_key": None, "sigma_key": "ISM"}
    if "fomc" in n or "fed" in n or "rate" in n or "taux" in n:
        return {"cluster": "financial", "nowcast_key": None, "sigma_key": None}
    return None


def parse_pct(s: str) -> Optional[float]:
    """Parse '2.2%' or '0,3%' or '213K' → float."""
    if not s or s == "":
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
# 3. COMPOSITE Z-SCORE
# ════════════════════════════════════════════════

def compute_event_signal(event: Dict[str, Any], nowcasts: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pour un event, calcule:
    - z_signal = (nowcast - consensus) / sigma
    - direction (bear/bull/neut)
    - conviction /10
    """
    cls = classify_event(event["name"])
    consensus = parse_pct(event.get("consensus", ""))
    previous = parse_pct(event.get("previous", ""))

    # Defaults
    out = {
        **event,
        "cluster": cls["cluster"] if cls else None,
        "nowcast": None,
        "z_signal": 0.0,
        "direction": "neutral",
        "conviction": 0,
        "delta": "—",
        "delta_dir": "flat",
    }

    if not cls or consensus is None:
        return out

    # Get nowcast
    nc_val = None
    if cls["nowcast_key"] == "gdpnow":
        nc_val = nowcasts.get("gdpnow")
    elif cls["nowcast_key"]:
        nc_val = nowcasts.get(cls["nowcast_key"])

    if nc_val is None:
        # Fallback : utilise previous comme proxy nowcast (faible signal)
        if previous is not None:
            nc_val = previous
        else:
            return out

    out["nowcast"] = nc_val
    sigma = SIGMA.get(cls["sigma_key"], 1.0)
    delta = nc_val - consensus
    z = delta / sigma if sigma else 0
    out["z_signal"] = z

    # Direction selon cluster
    # Inflation soft = bull pour stocks
    # Growth strong = bull
    if cls["cluster"] == "inflation":
        direction = "bullish" if z < -0.5 else "bearish" if z > 0.5 else "neutral"
    elif cls["cluster"] == "growth":
        direction = "bullish" if z > 0.5 else "bearish" if z < -0.5 else "neutral"
    elif cls["cluster"] == "employment":
        direction = "bullish" if z > 0.5 else "bearish" if z < -0.5 else "neutral"
    else:
        direction = "neutral"

    out["direction"] = direction

    # Conviction /10 = abs(z) * 5, capped at 10
    conv = min(10, max(1, int(abs(z) * 5)))
    out["conviction"] = conv

    # Delta display
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


def compute_composite(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate per-cluster Z then weighted sum.
    Returns: composite_z, direction, conviction.
    """
    cluster_z = {k: [] for k in WEIGHTS.keys()}
    for ev in events:
        c = ev.get("cluster")
        if c and c in cluster_z:
            # Conventionnel : Z négatif si bearish pour stocks
            z = ev["z_signal"]
            if c == "inflation":
                z = -z  # inflation positive = bear
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


def compute_projections(composite_z: float, indices_live: Dict[str, float]) -> Dict[str, Any]:
    """β-mapped index projections."""
    out = {}
    for k, beta in BETAS.items():
        now = indices_live.get(k)
        if now is None:
            out[k] = {"now": None, "target": None, "pct": 0.0}
            continue
        pct = beta * composite_z  # signe : composite < 0 → pct < 0
        target = now * (1 + pct / 100)
        out[k] = {
            "now": round(now, 0) if now > 100 else round(now, 2),
            "target": round(target, 0) if now > 100 else round(target, 2),
            "pct": round(pct, 1),
        }
    return out


# ════════════════════════════════════════════════
# 4. ORCHESTRATOR
# ════════════════════════════════════════════════

def build_signaux(prev_state: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Main entry point.
    prev_state : dict signaux précédent (utilisé en fallback si fetch fail).
    Returns : dict prêt à merger sous report_data["signaux"].
    """
    LOG.info("Building signaux...")

    # 1. Fetch all sources
    gdpnow = fetch_gdpnow()
    cleveland = fetch_cleveland_nowcast()
    raw_events = fetch_investing_calendar()
    indices = fetch_indices_live()

    nowcasts = {"gdpnow": gdpnow, **cleveland}
    LOG.info(f"GDPNow={gdpnow}, Cleveland={cleveland}, "
             f"events={len(raw_events)}, indices={indices}")

    # 2. If everything fails AND we have prev_state → return prev
    fetch_failed = (
        gdpnow is None and
        all(v is None for v in cleveland.values()) and
        len(raw_events) == 0
    )
    if fetch_failed and prev_state:
        LOG.warning("All fetches failed, returning previous state")
        prev_state["_stale"] = True
        prev_state["_last_attempt"] = datetime.now(PARIS_TZ).strftime("%Y-%m-%d %H:%M")
        return prev_state

    # 3. Process each event
    processed = [compute_event_signal(ev, nowcasts) for ev in raw_events]
    actionable = [ev for ev in processed if ev.get("cluster")]

    # 4. Composite
    if actionable:
        comp = compute_composite(actionable)
    else:
        comp = {"composite_z": 0.0, "direction": "neutral", "conviction": 0}

    # 5. Projections
    proj = compute_projections(comp["composite_z"], indices)

    # 6. Format pour trade.html
    today_str = datetime.now(PARIS_TZ).strftime("%d %b").lower()
    direction_label = {
        "bearish": "Bearish",
        "bullish": "Bullish",
        "neutral": "Neutre"
    }[comp["direction"]]

    # Window : prend la 1ère heure du 1er event 3★
    first_time = actionable[0]["time"] if actionable else "—"

    sub = f"{len(actionable)} event{'s' if len(actionable)>1 else ''} 3★ aujourd'hui · max vol {first_time} CET"

    # Format events pour rendering
    events_out = []
    for ev in actionable:
        cluster = ev.get("cluster")
        cls_short = {"inflation": "Inflation", "growth": "Croissance",
                     "employment": "Emploi", "activity": "Activité",
                     "financial": "Fed/BCE"}.get(cluster, "—")
        # Determine label1/label2
        if cluster in ("financial",):
            label1, label2 = "Marché", "Pricé"
        else:
            label1, label2 = "Marché", "Modèle"

        val1 = ev.get("consensus", "—")
        val2 = (
            f"{ev['nowcast']:.1f}%" if cluster == "growth" and ev.get("nowcast") is not None
            else f"{ev['nowcast']:.2f}%" if ev.get("nowcast") is not None
            else val1
        )

        events_out.append({
            "time": ev["time"],
            "name": ev["name"],
            "stars": ev["stars"],
            "direction": ev["direction"],
            "label1": label1,
            "val1": val1,
            "label2": label2,
            "val2": val2,
            "delta": ev["delta"],
            "delta_dir": ev["delta_dir"],
            "conviction": ev["conviction"],
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
            "window_note": f"vol max post-{first_time}" if first_time != "—" else "",
        },
        "events": events_out,
        "_generated_at": datetime.now(PARIS_TZ).strftime("%Y-%m-%d %H:%M"),
        "_stale": False,
    }


# ════════════════════════════════════════════════
# CLI test
# ════════════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s · %(message)s")
    result = build_signaux()
    print(json.dumps(result, indent=2, ensure_ascii=False))
