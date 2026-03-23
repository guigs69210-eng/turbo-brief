"""
Sous-agent Marché — Cotations temps réel
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf

log = logging.getLogger("agent.market")

SYMBOLS = {
    "nq_futures":  "NQ=F",
    "cac40":       "^FCHI",
    "vix":         "^VIX",
    "gold":        "GC=F",
    "brent":       "BZ=F",
    "eurusd":      "EURUSD=X",
    "us10y":       "^TNX",
    "sp500":       "ES=F",
    "schneider":   "SU.PA",
    "lvmh":        "MC.PA",
    "airliquide":  "AI.PA",
    "bnpparibas":  "BNP.PA",
    "stellantis":  "STLAM.MI",
}


async def fetch_market_data(fields: Optional[list] = None) -> dict:
    if fields:
        symbols_to_fetch = {k: v for k, v in SYMBOLS.items() if k in fields}
    else:
        symbols_to_fetch = SYMBOLS

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _fetch_yfinance, symbols_to_fetch)

    result["fetched_at"] = datetime.now(timezone.utc).isoformat()
    result["source"] = "yfinance"
    log.info(f"Marché: {len([v for v in result.values() if isinstance(v,dict) and v.get('price')])} cotations")
    return result


def _fetch_yfinance(symbols_map: dict) -> dict:
    tickers_str = " ".join(symbols_map.values())
    data = {}

    try:
        tickers = yf.Tickers(tickers_str)
        for name, yfkey in symbols_map.items():
            try:
                ticker = tickers.tickers.get(yfkey)
                if not ticker:
                    continue
                info = ticker.fast_info
                price      = getattr(info, "last_price", None)
                prev_close = getattr(info, "previous_close", None)
                change_pct = ((price - prev_close) / prev_close * 100) if price and prev_close else None

                data[name] = {
                    "symbol":     yfkey,
                    "price":      round(price, 4) if price else None,
                    "prev_close": round(prev_close, 4) if prev_close else None,
                    "change_pct": round(change_pct, 2) if change_pct else None,
                    "direction":  "up" if (change_pct or 0) > 0 else "dn" if (change_pct or 0) < 0 else "fl",
                }
            except Exception as e:
                log.debug(f"Erreur {name}: {e}")
                data[name] = {"symbol": yfkey, "price": None, "error": str(e)}

    except Exception as e:
        log.error(f"yfinance error: {e}")

    return data
