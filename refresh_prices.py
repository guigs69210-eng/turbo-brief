#!/usr/bin/env python3
"""
refresh_prices.py — met à jour les prix live des positions OUVERT
dans report_data.json via yfinance.

- Récupère le cours du sous-jacent pour chaque position
- Recalcule VI turbo, P&L live, KO distance
- Early exit si aucune position ouverte
- Push sur GitHub uniquement si quelque chose a changé
"""
import json
import os
import sys
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

REPORT_FILE = Path("report_data.json")
FX_EURUSD_DEFAULT = 1.1521  # fallback si yfinance EUR/USD échoue

# Mapping sous-jacent → ticker yfinance
TICKERS = {
    "NQ":      "NQ=F",    # Nasdaq 100 futures
    "SP500":   "ES=F",    # S&P 500 futures
    "SPX":     "^GSPC",
    "CAC40":   "^FCHI",
    "DOW":     "YM=F",
    "DAX":     "^GDAXI",
}

USD_UNDERLYINGS = {"NQ", "SP500", "SPX", "DOW"}


def get_fx_eurusd():
    """Récupère le taux EUR/USD live."""
    try:
        t = yf.Ticker("EURUSD=X")
        price = t.info.get("regularMarketPrice") or t.fast_info.get("last_price")
        if price and 0.8 < price < 1.5:
            return float(price)
    except Exception as e:
        print(f"  ⚠ FX fetch failed: {e}")
    return FX_EURUSD_DEFAULT


def get_underlying_price(sous_jacent):
    """Récupère le prix live du sous-jacent."""
    ticker = TICKERS.get(sous_jacent.upper())
    if not ticker:
        print(f"  ⚠ Unknown underlying: {sous_jacent}")
        return None
    try:
        t = yf.Ticker(ticker)
        # Essayer fast_info d'abord (plus rapide)
        try:
            price = t.fast_info.get("last_price")
            if price:
                return float(price)
        except Exception:
            pass
        # Fallback sur info
        price = t.info.get("regularMarketPrice")
        if price:
            return float(price)
    except Exception as e:
        print(f"  ⚠ Price fetch failed for {ticker}: {e}")
    return None


def compute_live(pos, sj_live, fx):
    """Recalcule VI, P&L, KO distance pour une position."""
    sens = pos.get("sens", "CALL").upper()
    strike = float(pos.get("strike", 0))
    ko = float(pos.get("ko", 0))
    parite = float(pos.get("parite", 1)) or 1
    pru = float(pos.get("prix_achat", 0))
    nb = float(pos.get("nb_titres", 0))
    devise = pos.get("devise", "EUR")

    if devise == "USD":
        effective_fx = fx
    else:
        effective_fx = 1.0

    # Valeur intrinsèque turbo
    if sens == "CALL":
        vi = max((sj_live - strike) / parite / effective_fx, 0)
        ko_dist = (sj_live - ko) / sj_live * 100 if sj_live else 0
    else:  # PUT
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

    positions = data.get("positions_ouvertes", [])
    ouvertes = [p for p in positions if p.get("status") == "OUVERT"]

    if not ouvertes:
        print("✓ Aucune position OUVERT, early exit")
        sys.exit(0)

    print(f"📊 {len(ouvertes)} positions à rafraîchir")

    # Récupérer FX une fois
    fx = get_fx_eurusd()
    print(f"💱 EUR/USD = {fx:.4f}")

    # Cache des prix sous-jacent (évite doublon yfinance)
    price_cache = {}
    changed = False

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
            print(f"  📈 {sj} = {price:,.2f}")

        sj_live = price_cache[sj]
        new_values = compute_live(pos, sj_live, fx)

        # Comparer pour savoir si on doit push
        for key, val in new_values.items():
            if pos.get(key) != val:
                changed = True
                pos[key] = val

        print(f"  {pos.get('label'):45s} "
              f"P&L {new_values['pnl_live_eur']:+5d}€ "
              f"({new_values['pnl_live_pct']:+.1f}%) "
              f"KO {new_values['ko_dist_live']:.1f}%")

    # Recalculer cto_recap
    cto = data.get("cto_recap", {})
    pnl_total = sum(p.get("pnl_live_eur", 0) for p in ouvertes)
    mise_total = sum(p.get("mise_eur", 0) for p in ouvertes)
    cto["pnl_latent_eur"] = round(pnl_total)
    cto["pnl_latent_pct"] = round(pnl_total / mise_total * 100, 1) if mise_total else 0
    cto["last_refresh"] = __import__("datetime").datetime.now().strftime("%d/%m/%Y %H:%M")
    data["cto_recap"] = cto

    if changed:
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✓ {REPORT_FILE} mis à jour — P&L latent total : {pnl_total:+.0f}€")
        sys.exit(0)
    else:
        print("✓ Aucun changement, pas de push")
        sys.exit(78)  # exit 78 = neutral → workflow ne commit rien


if __name__ == "__main__":
    main()
