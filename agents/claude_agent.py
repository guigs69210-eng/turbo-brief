"""
Sous-agent Mistral — Synthèse LLM (gratuit, EU)
"""

import json
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

log = logging.getLogger("agent.claude")
PARIS = ZoneInfo("Europe/Paris")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_URL     = "https://api.mistral.ai/v1/chat/completions"
MODEL           = "mistral-small-latest"

SYSTEM_PROMPT = """Tu es l'algorithme de trading de Turbo Brief, outil de day trading sur turbos/warrants (Paris, PEA + CTO).

RÔLE : Analyser les données de marché et générer un brief JSON structuré avec des recommandations de trading intraday.

CONTEXTE TRADER :
- Sessions : Paris 09h–17h30, US jusqu'à 22h CET
- Instruments : Turbos Infinis BEST (SG Bourse), warrants BNP, turbos Vontobel
- Leviers typiques : ×15 à ×25 intraday
- CALL = pari haussier, PUT = pari baissier
- Turbos BEST : pour un CALL, le KO est SOUS le strike. Pour un PUT, le KO est AU-DESSUS du strike.

RÈGLES IMPÉRATIVES :
1. Stop mental −40% sur le turbo = sortie immédiate
2. Actions FR → clôture obligatoire avant 17h30
3. Turbos NQ/indices → cotent jusqu'à 22h CET
4. TP1 (+25%) → sortir 50%, déplacer stop à +10%
5. Levier max ×20 en période de forte volatilité (VIX > 25)
6. Jamais de moyenne à la baisse

IMPORTANT SUR LES TURBOS :
- CALL Turbo : KO si le sous-jacent DESCEND sous la barrière → KO toujours INFÉRIEUR au cours actuel
- PUT Turbo : KO si le sous-jacent MONTE au-dessus de la barrière → KO toujours SUPÉRIEUR au cours actuel
- Levier réel = Cours SJ / (Valeur Intrinsèque × Parité × FX)

RÉPONSE : JSON strict uniquement, aucun texte avant/après, aucun backtick.

{
  "signal_du_jour": {
    "titre": "Biais baissier conditionnel — Iran talks incertains",
    "description": "NQ 24 428 (+0.21%), VIX 25.9 en baisse. Brent recule -3.6% sur espoirs de négociations.",
    "biais": "haussier|baissier|neutre",
    "conviction": "faible|modérée|forte",
    "contexte_macro": "2 phrases max sur le contexte du jour."
  },
  "plan_actions": [
    {
      "heure": "09h10",
      "titre": "CALL NQ Futures ×20",
      "sens": "CALL|PUT",
      "mise": "1500 €",
      "levier": 20,
      "strike_ko": "Strike 23500 / KO 23000",
      "gain_cible": "+30% si NQ +1.5%",
      "plateforme": "sgbourse.fr → Nasdaq 100 → CALL BEST",
      "note": "Entrée 09h10–09h30. Stop mental -40%.",
      "urgence": "haute|normale|faible"
    }
  ],
  "niveaux_cles": [
    {
      "label": "Résistance NQ",
      "prix": 24800,
      "type": "resistance|support|current",
      "action": "TP1 si atteint",
      "couleur": "bull|bear|amber|blue"
    }
  ],
  "alertes": ["Événement macro important aujourd'hui 15h ET"],
  "regles_session": [
    "Stop mental −40% = sortie immédiate",
    "Actions FR → clôture obligatoire 17h30"
  ],
  "market_strip": {
    "nq":    {"valeur": "24 428", "chg": "+0.21%", "dir": "up"},
    "cac40": {"valeur": "7 822",  "chg": "+0.91%", "dir": "up"},
    "brent": {"valeur": "$96.2",  "chg": "-3.58%", "dir": "dn"},
    "vix":   {"valeur": "25.9",   "chg": "-3.97%", "dir": "dn"}
  },
  "pea_note": "PEA — Ne pas toucher.",
  "edition": "09h00 CET",
  "mode": "normal|fomc|news_flash"
}"""


async def synthesize_brief(raw_data: dict, trigger_type) -> dict:
    user_message = _build_user_message(raw_data, trigger_type)
    log.info(f"Appel Mistral API — {len(user_message)} chars")

    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        "temperature":  0.3,
        "max_tokens":   3000,
        "response_format": {"type": "json_object"},
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            MISTRAL_URL,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise Exception(f"Mistral error {resp.status}: {body[:300]}")
            data = await resp.json()

    raw_response = data["choices"][0]["message"]["content"]
    log.info(f"Mistral répondu — {len(raw_response)} chars")

    brief = _parse_response(raw_response)
    brief = _validate_brief(brief, raw_data)
    return brief


def _build_user_message(data: dict, trigger_type) -> str:
    now = datetime.now(PARIS)

    # ── Date et contexte temporel explicite ──────────────────────────────────
    jours_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    mois_fr  = ["janvier", "février", "mars", "avril", "mai", "juin",
                "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    date_fr  = f"{jours_fr[now.weekday()]} {now.day} {mois_fr[now.month-1]} {now.year}"

    sections = [
        f"# BRIEF {trigger_type} — {date_fr} — {now.strftime('%H:%M')} CET",
        "",
        "## CONTEXTE TEMPOREL IMPORTANT",
        f"- Date aujourd'hui : {date_fr}",
        f"- Heure actuelle : {now.strftime('%H:%M')} CET",
        "- Le dernier FOMC a eu lieu le 18 mars 2026 (résultat : HOLD hawkish, taux inchangés)",
        "- Prochain FOMC : 7 mai 2026",
        "- Ne pas mentionner le FOMC comme événement à venir aujourd'hui.",
        "",
    ]

    # ── Données marché ────────────────────────────────────────────────────────
    market = data.get("market", {})
    if market and not market.get("error"):
        sections.append("## COTATIONS")
        for key in ["nq_futures", "cac40", "vix", "gold", "eurusd", "brent", "us10y"]:
            item = market.get(key, {})
            if item.get("price"):
                chg = f"{item.get('change_pct', 0):+.2f}%" if item.get("change_pct") is not None else "N/A"
                sections.append(f"- {key.upper()}: {item['price']} ({chg})")
        sections.append("")

    # ── Analyse technique ─────────────────────────────────────────────────────
    tech = data.get("technical", {})
    if tech and not tech.get("error"):
        sections.append("## TECHNIQUE")
        for key in ["nq_futures", "cac40", "schneider"]:
            t = tech.get(key, {})
            if t and not t.get("error"):
                sections.append(
                    f"- {t.get('name', key)}: RSI {t.get('rsi','?')} ({t.get('rsi_signal','?')}), "
                    f"Trend: {t.get('trend','?')}, VWAP: {t.get('vwap','?')}, ATR: {t.get('atr_pct','?')}%"
                )
                sr = t.get("sr_levels", [])
                resistances = [l for l in sr if l["type"] == "resistance"][:2]
                supports    = [l for l in sr if l["type"] == "support"][:2]
                if resistances:
                    sections.append(f"  Résistances: {', '.join(str(l['price']) for l in resistances)}")
                if supports:
                    sections.append(f"  Supports: {', '.join(str(l['price']) for l in supports)}")
        sections.append("")

    # ── Calendrier ────────────────────────────────────────────────────────────
    cal = data.get("calendar", {})
    if cal and not cal.get("error"):
        events = cal.get("today_high_impact", [])
        if events:
            sections.append("## CALENDRIER ÉCONOMIQUE AUJOURD'HUI")
            for e in events:
                sections.append(f"  ⚠️ {e.get('time','?')} — {e.get('name','?')}")
            sections.append("")
        else:
            sections.append("## CALENDRIER")
            sections.append("- Aucun événement macro majeur aujourd'hui.")
            sections.append("")

    # ── News ──────────────────────────────────────────────────────────────────
    news = data.get("news", {})
    if news and not news.get("error"):
        sections.append("## NEWS DU JOUR")
        sections.append(f"Sentiment global: {news.get('sentiment', 0):+.2f}")
        themes = news.get("themes", [])
        if themes:
            sections.append(f"Thèmes dominants: {', '.join(t['theme'] for t in themes[:3])}")

        # Articles haute importance en premier
        articles = news.get("articles", [])
        high_articles = [a for a in articles if a.get("urgency") in ("critical", "high")][:6]
        other_articles = [a for a in articles if a.get("urgency") not in ("critical", "high")][:4]

        if high_articles:
            sections.append("### Flash haute importance:")
            for a in high_articles:
                age = a.get("age_minutes", 999)
                age_str = f"{age}min" if age < 120 else f"{age//60}h"
                sections.append(f"  [{a.get('urgency','?').upper()}] ({age_str}) {a.get('title','')}")

        if other_articles:
            sections.append("### Autres news:")
            for a in other_articles:
                sections.append(f"  - {a.get('title','')}")
        sections.append("")

    sections.append(f"Génère le brief JSON pour {date_fr} à {now.strftime('%H:%M')} CET.")
    return "\n".join(sections)


def _parse_response(text: str) -> dict:
    text = text.strip()
    if "```" in text:
        lines = [l for l in text.split("\n") if not l.startswith("```")]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.error(f"JSON parse error: {e}")
        return {
            "signal_du_jour": {
                "titre": "Erreur de génération",
                "description": "Vérifier les logs.",
                "biais": "neutre",
                "conviction": "faible",
            },
            "plan_actions": [],
            "niveaux_cles": [],
            "alertes": ["⚠️ Erreur de génération"],
            "regles_session": [],
            "market_strip": {},
        }


def _validate_brief(brief: dict, raw_data: dict) -> dict:
    now = datetime.now(PARIS)

    if not brief.get("timestamp"):
        brief["timestamp"] = now.isoformat()
    if not brief.get("edition"):
        brief["edition"] = now.strftime("%Hh%M CET")

    # ── date_fr toujours en français ──────────────────────────────────────────
    jours_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    mois_fr  = ["janvier", "février", "mars", "avril", "mai", "juin",
                "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    brief["date_fr"] = f"{jours_fr[now.weekday()]} {now.day} {mois_fr[now.month-1]} {now.year}"

    # ── market_strip depuis données live ─────────────────────────────────────
    market = raw_data.get("market", {})
    if market and not market.get("error"):
        strip = brief.get("market_strip", {})

        def fmt(val, d=0):
            return f"{val:,.{d}f}".replace(",", " ") if val else "—"

        def fchg(chg):
            return f"{chg:+.2f}%" if chg is not None else "—"

        for key, label, decimals in [
            ("nq_futures", "nq",    0),
            ("cac40",      "cac40", 0),
            ("vix",        "vix",   1),
            ("brent",      "brent", 1),
        ]:
            m = market.get(key, {})
            if m.get("price"):
                prefix = "$" if key == "brent" else ""
                strip[label] = {
                    "valeur": prefix + fmt(m["price"], decimals),
                    "chg":    fchg(m.get("change_pct")),
                    "dir":    m.get("direction", "fl"),
                }
        brief["market_strip"] = strip

    return brief
