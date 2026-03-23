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
    bb_lower = round(bb_mid - 2 * bb_std, 2)

    sr_levels = _find_sr_levels(high, low, close, current_price)
    trend     = _determine_trend(close, ma20, ma50, ema9, ema21)

    return {
        "symbol":        symbol,
        "name":          name,
        "current_price": round(current_price, 2),
        "rsi":           round(rsi, 1),
        "rsi_signal":    _rsi_signal(rsi),
        "ma20":          round(ma20, 2),
        "ma50":          round(ma50, 2),
        "ema9":          round(ema9, 2),
        "ema21":         round(ema21, 2),
        "vwap":          round(vwap, 2) if vwap else None,
        "bb_upper":      bb_upper,
        "bb_lower":      bb_lower,
        "atr":           round(atr, 2),
        "atr_pct":       round(atr / current_price * 100, 2),
        "trend":         trend,
        "sr_levels":     sr_levels,
        "above_ma20":    current_price > ma20,
        "above_ma50":    current_price > ma50,
    }


def _calc_rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.rolling(period).mean()
    avg_l = loss.rolling(period).mean()
    rs    = avg_g / avg_l
    rsi   = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def _calc_vwap(df: pd.DataFrame) -> float | None:
    if df.empty: return None
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    vwap = (typical * df["Volume"]).cumsum() / df["Volume"].cumsum()
    return float(vwap.iloc[-1])


def _calc_atr(high, low, close, period: int = 14) -> float:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def _find_sr_levels(high, low, close, current_price: float) -> list:
    pivot_highs, pivot_lows = [], []
    for i in range(2, len(close) - 2):
        if high.iloc[i] == high.iloc[i-2:i+3].max():
            pivot_highs.append(float(high.iloc[i]))
        if low.iloc[i] == low.iloc[i-2:i+3].min():
            pivot_lows.append(float(low.iloc[i]))

    all_pivots = sorted(pivot_highs + pivot_lows)
    if not all_pivots: return []

    clusters, current_cluster = [], [all_pivots[0]]
    for p in all_pivots[1:]:
        if (p - current_cluster[-1]) / current_cluster[0] < 0.005:
            current_cluster.append(p)
        else:
            clusters.append(sum(current_cluster) / len(current_cluster))
            current_cluster = [p]
    clusters.append(sum(current_cluster) / len(current_cluster))

    top = sorted(clusters, key=lambda x: abs(x - current_price))[:6]
    result = []
    for level in top:
        pct = (level - current_price) / current_price * 100
        result.append({
            "price":    round(level, 2),
            "pct_away": round(pct, 2),
            "type":     "resistance" if level > current_price else "support",
        })
    return sorted(result, key=lambda x: x["price"], reverse=True)


def _determine_trend(close, ma20, ma50, ema9, ema21) -> str:
    current = float(close.iloc[-1])
    score = sum([current > ma20, current > ma50, ema9 > ema21])
    if score >= 3: return "haussier"
    if score <= 1: return "baissier"
    return "neutre"


def _rsi_signal(rsi: float) -> str:
    if rsi >= 70:   return "suracheté"
    if rsi <= 30:   return "survendu"
    if rsi >= 60:   return "haussier"
    if rsi <= 40:   return "baissier"
    return "neutre"
