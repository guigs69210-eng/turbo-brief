"""
Sous-agent News & Sentiment
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

RSS_FEEDS = {
    "reuters_markets":  "https://feeds.reuters.com/reuters/businessNews",
    "reuters_economy":  "https://feeds.reuters.com/reuters/economicsNews",
    "fed_press":        "https://www.federalreserve.gov/feeds/press_all.xml",
    "bfm_bourse":       "https://www.bfmtv.com/rss/economie/bourse/",
}

FLASH_KEYWORDS = {
    "critical": [
        "fed rate", "rate hike", "rate cut", "emergency meeting",
        "taux directeur", "réunion d'urgence",
    ],
    "high": [
        "fomc", "cpi", "nfp", "payroll", "gdp", "recession",
        "iran", "hormuz", "brent spike",
        "récession", "inflation", "vix", "crash",
    ],
    "medium": [
        "cac40", "nasdaq", "schneider", "lvmh", "bnp",
        "earnings", "résultats",
    ],
}

SENTIMENT_POSITIVE = [
    "surge", "rally", "beat", "strong", "record", "growth",
    "hausse", "rebond", "croissance", "record",
]
SENTIMENT_NEGATIVE = [
    "plunge", "crash", "miss", "weak", "recession", "loss",
    "chute", "récession", "perte", "baisse",
]


async def scan_news(mode: Literal["full", "flash"] = "full") -> dict:
    feeds_to_scan = RSS_FEEDS if mode == "full" else dict(list(RSS_FEEDS.items())[:2])

    results = await asyncio.gather(
        *[_fetch_feed(name, url) for name, url in feeds_to_scan.items()],
        return_exceptions=True
    )

    all_articles = []
    for r in results:
        if isinstance(r, list):
            all_articles.extend(r)

    seen = set()
    unique = []
    for a in all_articles:
        h = hashlib.md5(a["title"].encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(a)

    for article in unique:
        article["urgency"]   = _get_urgency(article["title"] + " " + article.get("summary", ""))
        article["sentiment"] = _get_sentiment(article["title"] + " " + article.get("summary", ""))
        article["id"]        = hashlib.md5(article["title"].encode()).hexdigest()[:12]

    urgency_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    unique.sort(key=lambda x: (urgency_order.get(x["urgency"], 3), -x.get("age_minutes", 999)))

    flash_alerts = [
        a for a in unique
        if a["urgency"] in ("critical", "high") and a.get("age_minutes", 999) < 60
    ]

    sentiments = [a["sentiment"] for a in unique[:20]]
    avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0

    themes = _extract_themes(unique[:30])

    log.info(f"News: {len(unique)} articles, {len(flash_alerts)} flash, sentiment={avg_sentiment:+.2f}")

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
            headers = {"User-Agent": "TurboBrief/1.0"}
            async with session.get(url, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return []
                content = await resp.read()

        feed = feedparser.parse(content)
        articles = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=12)

        for entry in feed.entries[:15]:
            try:
                pub = _parse_date(entry)
                if pub and pub < cutoff:
                    continue
                age_minutes = int((datetime.now(timezone.utc) - pub).total_seconds() / 60) if pub else 999

                articles.append({
                    "title":       entry.get("title", ""),
                    "summary":     _clean_html(entry.get("summary", ""))[:300],
                    "url":         entry.get("link", ""),
                    "source":      name,
                    "published":   pub.isoformat() if pub else None,
                    "age_minutes": age_minutes,
                })
            except Exception:
                continue

        return articles

    except Exception as e:
        log.debug(f"{name} feed error: {e}")
        return []


def _get_urgency(text: str) -> str:
    text_lower = text.lower()
    for kw in FLASH_KEYWORDS["critical"]:
        if kw in text_lower: return "critical"
    for kw in FLASH_KEYWORDS["high"]:
        if kw in text_lower: return "high"
    for kw in FLASH_KEYWORDS["medium"]:
        if kw in text_lower: return "medium"
    return "low"


def _get_sentiment(text: str) -> float:
    text_lower = text.lower()
    pos = sum(1 for w in SENTIMENT_POSITIVE if w in text_lower)
    neg = sum(1 for w in SENTIMENT_NEGATIVE if w in text_lower)
    total = pos + neg
    if total == 0: return 0.0
    return (pos - neg) / total


def _extract_themes(articles: list) -> list:
    theme_groups = {
        "Fed / Politique monétaire": ["fed", "fomc", "rate", "taux", "inflation", "cpi"],
        "Géopolitique / Énergie":    ["iran", "oil", "brent", "hormuz", "ukraine"],
        "Tech / IA":                 ["ai", "nvidia", "tech", "nasdaq"],
        "Macro US":                  ["gdp", "nfp", "payroll", "recession"],
        "Europe / CAC":              ["cac", "schneider", "lvmh", "bnp"],
    }
    scores = {theme: 0 for theme in theme_groups}
    for article in articles:
        text = (article["title"] + " " + article.get("summary", "")).lower()
        for theme, keywords in theme_groups.items():
            scores[theme] += sum(1 for kw in keywords if kw in text)

    sorted_themes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [{"theme": t, "count": c} for t, c in sorted_themes[:3] if c > 0]


def _parse_date(entry) -> datetime | None:
    import calendar
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            ts = calendar.timegm(parsed)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


def _clean_html(text: str) -> str:
    if not text: return ""
    try:
        return BeautifulSoup(text, "html.parser").get_text(separator=" ").strip()
    except Exception:
        return re.sub(r"<[^>]+>", " ", text).strip()
