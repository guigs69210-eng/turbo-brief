#!/usr/bin/env python3
"""
refresh_prices.py — met à jour les prix live dans report_data.json via yfinance.

- Rafraîchit TOUJOURS NQ / SP500 / CAC40 (stockés dans cto_recap.indices_live)
- Rafraîchit les positions OUVERT (VI, P&L, KO dist)
- Push sur GitHub uniquement si quelque chose a changé
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
    PARIS_TZ = ZoneInfo("Europe/Paris")
except ImportError:
    # Fallback Python < 3.9 : offset fixe UTC+2 (été) / UTC+1 (hiver)
    # Approximation simple : on utilise UTC+2 qui couvre mars-octobre
    PARIS_TZ = timezone(timedelta(hours=2))

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

REPORT_FILE = Path("report_data.json")
FX_EURUSD_DEFAULT = 1.1521

# Indices toujours rafraîchis (affichés dans l'UI)
ALWAYS_REFRESH = ["NQ", "SP500", "CAC40"]

# Mapping sous-jacent → ticker yfinance
TICKERS = {
    "NQ":    "NQ=F",
    "SP500": "ES=F",
    "SPX":   "^GSPC",
    "CAC40": "^FCHI",
    "DOW":   "YM=F",
    "DAX":   "^GDAXI",
}

USD_UNDERLYINGS = {"NQ", "SP500", "SPX", "DOW"}


def get_fx_eurusd():
    try:
        t = yf.Ticker("EURUSD=X")
        try:
            price = t.fast_info.get("last_price")
        except Exception:
            price = None
        if not price:
            price = t.info.get("regularMarketPrice")
        if price and 0.8 < price < 1.5:
            return float(price)
    except Exception as e:
        print(f"  ⚠ FX fetch failed: {e}")
    return FX_EURUSD_DEFAULT


def get_underlying_price(sous_jacent):
    ticker = TICKERS.get(sous_jacent.upper())
    if not ticker:
        print(f"  ⚠ Unknown underlying: {sous_jacent}")
        return None
    try:
        t = yf.Ticker(ticker)
        try:
            price = t.fast_info.get("last_price")
            if price:
                return float(price)
        except Exception:
            pass
        price = t.info.get("regularMarketPrice")
        if price:
            return float(price)
        hist = t.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"  ⚠ Price fetch failed for {ticker}: {e}")
    return None


def compute_live(pos, sj_live, fx):
    sens = pos.get("sens", "CALL").upper()
    strike = float(pos.get("strike", 0))
    ko = float(pos.get("ko", 0))
    parite = float(pos.get("parite", 1)) or 1
    pru = float(pos.get("prix_achat", 0))
    nb = float(pos.get("nb_titres", 0))
    devise = pos.get("devise", "EUR")
    effective_fx = fx if devise == "USD" else 1.0

    if sens == "CALL":
        vi = max((sj_live - strike) / parite / effective_fx, 0)
        ko_dist = (sj_live - ko) / sj_live * 100 if sj_live else 0
    else:
        vi = max((strike - sj_live) / parite / effective_fx, 0)
        ko_dist = (ko - sj_live) / sj_live * 100 if sj_live else 0

    pnl_eur = (vi - pru) * nb
    pnl_pct = ((vi - pru) / pru * 100) if pru > 0 else 0

    return {
        "sj_live": round(sj_live, 2),
        "pnl_live_eur": round(pnl_eur),
        "pnl_live_pct": round(pnl_pct, 1),
        "ko_dist_live": round(ko_dist, 1),
        "prix_turbo_live": round(vi, 3),
    }


def main():
    if not REPORT_FILE.exists():
        print(f"ERROR: {REPORT_FILE} not found")
        sys.exit(1)

    with open(REPORT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    fx = get_fx_eurusd()
    print(f"💱 EUR/USD = {fx:.4f}")

    price_cache = {}

    # 1) TOUJOURS rafraîchir les 3 indices de référence
    print(f"\n📊 Rafraîchissement indices : {', '.join(ALWAYS_REFRESH)}")
    for sj in ALWAYS_REFRESH:
        price = get_underlying_price(sj)
        if price:
            price_cache[sj] = price
            print(f"  📈 {sj:8s} = {price:>10,.2f}")
        else:
            print(f"  ⚠ {sj} → pas de prix")

    cto = data.get("cto_recap", {})
    cto["indices_live"] = {sj: price_cache[sj] for sj in ALWAYS_REFRESH if sj in price_cache}
    cto["fx_eurusd"] = round(fx, 4)

    # 2) Rafraîchir les positions OUVERT
    positions = data.get("positions_ouvertes", [])
    ouvertes = [p for p in positions if p.get("status") == "OUVERT"]

    if ouvertes:
        print(f"\n📊 {len(ouvertes)} positions à rafraîchir")
        for pos in ouvertes:
            sj = pos.get("sous_jacent", "").upper()
            if not sj:
                continue
            if sj not in price_cache:
                price = get_underlying_price(sj)
                if price is None:
                    print(f"  ⚠ Skip {pos.get('label')}: no price")
                    continue
                price_cache[sj] = price

            sj_live = price_cache[sj]
            new_values = compute_live(pos, sj_live, fx)

            for key, val in new_values.items():
                pos[key] = val

            print(f"  {pos.get('label','')[:45]:45s} "
                  f"P&L {new_values['pnl_live_eur']:+5d}€ "
                  f"({new_values['pnl_live_pct']:+.1f}%) "
                  f"KO {new_values['ko_dist_live']:.1f}%")

        pnl_total = sum(p.get("pnl_live_eur", 0) for p in ouvertes)
        mise_total = sum(p.get("mise_eur", 0) for p in ouvertes)
        cto["pnl_latent_eur"] = round(pnl_total)
        cto["pnl_latent_pct"] = round(pnl_total / mise_total * 100, 1) if mise_total else 0
    else:
        print("\n✓ Aucune position OUVERT — indices seuls rafraîchis")
        cto["pnl_latent_eur"] = 0
        cto["pnl_latent_pct"] = 0

    cto["last_refresh"] = datetime.now(PARIS_TZ).strftime("%d/%m/%Y %H:%M")
    data["cto_recap"] = cto

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n✓ {REPORT_FILE} mis à jour")


if __name__ == "__main__":
    main()
