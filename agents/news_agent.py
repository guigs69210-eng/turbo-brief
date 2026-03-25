"""
Sous-agent News & Sentiment — Sources actives 2026
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

import aiohttp
import feedparser
from bs4 import BeautifulSoup

log = logging.getLogger("agent.news")

# ── Sources RSS actives en 2026 ───────────────────────────────────────────────
RSS_FEEDS = {
    # Marchés US & global
    "marketwatch_markets":  "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
    "marketwatch_economy":  "https://feeds.content.dowjones.io/public/rss/mw_bulletins",
    "investing_news":       "https://www.investing.com/rss/news.rss",
    "investing_economy":    "https://www.investing.com/rss/news_285.rss",
    # Fed & Macro US
    "fed_press":            "https://www.federalreserve.gov/feeds/press_all.xml",
    "nasdaq_original":      "https://www.nasdaq.com/feed/nasdaq-originals/rss.xml",
    # France & Europe
    "bfm_bourse":           "https://www.bfmtv.com/rss/economie/bourse/",
    "lesechos_marches":     "https://www.lesechos.fr/rss/rss_finance.xml",
    # Google News — top business/marchés (générique)
    "google_news_markets":  "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlBQVAB?hl=en&gl=US&ceid=US:en",
    "google_news_business": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pGUWlBQVAB?hl=fr&gl=FR&ceid=FR:fr",
    "google_news_economy":  "https://news.google.com/rss/topics/CAAqIggKIhxDQkFTRHdvSkwyMHZNR2RtY0hNekVnSmxiaUFBUAE?hl=en&gl=US&ceid=US:en",
    # Yahoo Finance RSS
    "yahoo_finance":        "https://finance.yahoo.com/rss/topfinstories",
    "yahoo_markets":        "https://finance.yahoo.com/rss/2.0/headline?s=^IXIC,^FCHI&region=US&lang=en-US",
}

FLASH_KEYWORDS = {
    "critical": [
        "fed rate", "rate hike", "rate cut", "emergency meeting",
        "taux directeur", "réunion d'urgence", "market crash",
        "circuit breaker", "trading halt",
    ],
    "high": [
        # Macro US
        "fomc", "cpi", "nfp", "payroll", "gdp", "recession",
        "inflation", "fed", "powell", "rate decision", "rate cut", "rate hike",
        # Marchés
        "vix spike", "flash crash", "market crash", "sell-off", "correction",
        "circuit breaker", "trading halt", "short squeeze",
        # Énergie & géopolitique (générique)
        "oil surge", "oil plunge", "brent spike", "energy crisis",
        "war", "conflict", "sanctions", "ceasefire", "geopolitical",
        # Europe
        "ecb", "bce", "banque centrale", "récession", "crise",
        # Earnings chocs
        "earnings miss", "profit warning", "guidance cut", "bankruptcy",
        "faillite", "résultats manqués",
    ],
    "medium": [
        "cac40", "nasdaq", "schneider", "lvmh", "bnp", "thales",
        "earnings", "résultats", "quarterly", "guidance",
        "s&p 500", "dow jones", "tech stocks",
    ],
}

SENTIMENT_POSITIVE = [
    "surge", "rally", "beat", "strong", "record", "growth", "rebound",
    "hausse", "rebond", "croissance", "record", "gain", "rise",
    "ceasefire", "deal", "accord", "relief", "recovery",
]
SENTIMENT_NEGATIVE = [
    "plunge", "crash", "miss", "weak", "recession", "loss", "drop",
    "chute", "récession", "perte", "baisse", "fall", "decline",
    "war", "strike", "escalation", "sanctions", "default",
]


async def scan_news(mode: Literal["full", "flash"] = "full") -> dict:
    if mode == "full":
        feeds_to_scan = RSS_FEEDS
    else:
        # Flash : seulement les sources les plus rapides
        feeds_to_scan = {k: v for k, v in RSS_FEEDS.items()
                         if k in ("investing_news", "google_news_iran",
                                  "google_news_fed", "yahoo_finance")}

    results = await asyncio.gather(
        *[_fetch_feed(name, url) for name, url in feeds_to_scan.items()],
        return_exceptions=True
    )

    all_articles = []
    for r in results:
        if isinstance(r, list):
            all_articles.extend(r)

    # Déduplication
    seen = set()
    unique = []
    for a in all_articles:
        h = hashlib.md5(a["title"].encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(a)

    # Scoring
    for article in unique:
        text = article["title"] + " " + article.get("summary", "")
        article["urgency"]   = _get_urgency(text)
        article["sentiment"] = _get_sentiment(text)
        article["id"]        = hashlib.md5(article["title"].encode()).hexdigest()[:12]

    # Tri par urgence puis fraîcheur
    urgency_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    unique.sort(key=lambda x: (urgency_order.get(x["urgency"], 3),
                               x.get("age_minutes", 999)))

    flash_alerts = [
        a for a in unique
        if a["urgency"] in ("critical", "high") and a.get("age_minutes", 999) < 120
    ]

    sentiments = [a["sentiment"] for a in unique[:20]]
    avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0

    themes = _extract_themes(unique[:30])

    log.info(f"News: {len(unique)} articles, {len(flash_alerts)} flash, "
             f"sentiment={avg_sentiment:+.2f}")

    return {
        "articles":     unique[:20] if mode == "full" else unique[:5],
        "flash_alerts": flash_alerts,
        "sentiment":    round(avg_sentiment, 2),
        "themes":       themes,
        "scanned_at":   datetime.now(timezone.utc).isoformat(),
        "mode":         mode,
    }


async def _fetch_feed(name: str, url: str) -> list:
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; TurboBrief/1.0)",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            }
            async with session.get(url, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    log.debug(f"{name}: HTTP {resp.status}")
                    return []
                content = await resp.read()

        feed = feedparser.parse(content)
        if not feed.entries:
            log.debug(f"{name}: 0 entrées")
            return []

        articles = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        for entry in feed.entries[:20]:
            try:
                pub = _parse_date(entry)
                if pub and pub < cutoff:
                    continue
                age_minutes = (
                    int((datetime.now(timezone.utc) - pub).total_seconds() / 60)
                    if pub else 999
                )
                title = entry.get("title", "").strip()
                if not title or len(title) < 10:
                    continue

                articles.append({
                    "title":       title,
                    "summary":     _clean_html(entry.get("summary", ""))[:300],
                    "url":         entry.get("link", ""),
                    "source":      name,
                    "published":   pub.isoformat() if pub else None,
                    "age_minutes": age_minutes,
                })
            except Exception:
                continue

        log.debug(f"{name}: {len(articles)} articles")
        return articles

    except Exception as e:
        log.debug(f"{name} feed error: {e}")
        return []


def _get_urgency(text: str) -> str:
    text_lower = text.lower()
    for kw in FLASH_KEYWORDS["critical"]:
        if kw in text_lower:
            return "critical"
    for kw in FLASH_KEYWORDS["high"]:
        if kw in text_lower:
            return "high"
    for kw in FLASH_KEYWORDS["medium"]:
        if kw in text_lower:
            return "medium"
    return "low"


def _get_sentiment(text: str) -> float:
    text_lower = text.lower()
    pos = sum(1 for w in SENTIMENT_POSITIVE if w in text_lower)
    neg = sum(1 for w in SENTIMENT_NEGATIVE if w in text_lower)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def _extract_themes(articles: list) -> list:
    theme_groups = {
        "Fed / Politique monétaire": ["fed", "fomc", "rate", "taux", "inflation",
                                       "cpi", "powell", "monetary"],
        "Géopolitique / Énergie":    ["iran", "oil", "brent", "hormuz", "ukraine",
                                       "war", "ceasefire", "sanctions", "energy"],
        "Tech / IA":                 ["ai", "nvidia", "tech", "nasdaq", "semiconductor",
                                       "apple", "microsoft", "google"],
        "Macro US":                  ["gdp", "nfp", "payroll", "recession", "jobs",
                                       "unemployment", "consumer"],
        "Europe / CAC":              ["cac", "schneider", "lvmh", "bnp", "thales",
                                       "eurostoxx", "ecb", "europe"],
    }
    scores = {theme: 0 for theme in theme_groups}
    for article in articles:
        text = (article["title"] + " " + article.get("summary", "")).lower()
        for theme, keywords in theme_groups.items():
            scores[theme] += sum(1 for kw in keywords if kw in text)

    sorted_themes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [{"theme": t, "count": c} for t, c in sorted_themes[:4] if c > 0]


def _parse_date(entry) -> datetime | None:
    import calendar
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                ts = calendar.timegm(parsed)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                continue
    return None


def _clean_html(text: str) -> str:
    if not text:
        return ""
    try:
        return BeautifulSoup(text, "html.parser").get_text(separator=" ").strip()
    except Exception:
        return re.sub(r"<[^>]+>", " ", text).strip()
