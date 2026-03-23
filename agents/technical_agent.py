"""
Sous-agent Analyse Technique
"""

import asyncio
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

log = logging.getLogger("agent.technical")

INSTRUMENTS = {
    "nq_futures": {"symbol": "NQ=F",  "name": "NQ Futures"},
    "cac40":      {"symbol": "^FCHI", "name": "CAC 40"},
    "schneider":  {"symbol": "SU.PA", "name": "Schneider Electric"},
}


async def get_technicals() -> dict:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _compute_all_technicals)
    result["computed_at"] = datetime.now(timezone.utc).isoformat()
    return result


def _compute_all_technicals() -> dict:
    results = {}
    for key, instrument in INSTRUMENTS.items():
        try:
            analysis = _analyze_instrument(instrument["symbol"], instrument["name"])
            results[key] = analysis
            log.info(f"Technique {key}: RSI={analysis.get('rsi','?')}, trend={analysis.get('trend','?')}")
        except Exception as e:
            log.warning(f"Technical error {key}: {e}")
            results[key] = {"error": str(e), "symbol": instrument["symbol"]}
    return results


def _analyze_instrument(symbol: str, name: str) -> dict:
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="60d", interval="1d")

    if df.empty or len(df) < 20:
        raise ValueError(f"Pas assez de données pour {symbol}")

    df_intraday = ticker.history(period="5d", interval="1h")

    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]

    current_price = float(close.iloc[-1])

    rsi   = _calc_rsi(close, 14)
    ma20  = float(close.rolling(20).mean().iloc[-1])
    ma50  = float(close.rolling(min(50, len(close))).mean().iloc[-1])
    ema9  = float(close.ewm(span=9,  adjust=False).mean().iloc[-1])
    ema21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
    vwap  = _calc_vwap(df_intraday) if not df_intraday.empty else None
    atr   = _calc_atr(high, low, close, 14)

    bb_mid   = float(close.rolling(20).mean().iloc[-1])
    bb_std   = float(close.rolling(20).std().iloc[-1])
    bb_upper = round(bb_mid + 2 * bb_std, 2)
