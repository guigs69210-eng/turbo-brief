"""
Sous-agent Gemini — Synthèse LLM (gratuit)
"""

import json
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from google import genai

log = logging.getLogger("agent.claude")
PARIS = ZoneInfo("Europe/Paris")

CLIENT = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
MODEL  = "gemini-1.5-flash"

SYSTEM_PROMPT = """Tu es l'algorithme de trading de Turbo Brief, un outil de day trading sur turbos/warrants (Paris, PEA + CTO).

TON RÔLE : Analyser les données de marché fournies et générer un brief de trading JSON structuré.

CONTEXTE UTILISATEUR :
- Trader basé à Paris, sessions 09h–17h30 + soirée US jusqu'à 22h
- Instruments : Turbos BEST (SG Bourse), warrants (BNP), turbos infinis (Vontobel)
- Leviers habituels : ×15 à ×25 intraday, ×7 pour couvertures
- Capital day trading : ~10 000 € actif (PEA 26 000 € séparé, ne pas toucher)

RÈGLES IMPÉRATIVES :
1. Stop mental −40% sur le turbo = sortie immédiate
2. Actions FR → clôture obligatoire 17h30
3. Turbos indices/NQ → peuvent être gardés jusqu'à 22h
4. TP1 atteint (+25%) → sortir 50%, déplacer stop à +10%
5. Ne jamais passer un FOMC en levier ×25 → réduire à ×20
6. Jamais de moyenne à la baisse

FORMAT DE RÉPONSE : JSON strict uniquement, pas de texte avant/après, pas de backticks.

{
  "signal_du_jour": {
    "titre": "Neutre — Biais haussier conditionnel",
    "description": "NQ Futures XX (+X%), VIX XX...",
    "biais": "haussier|baissier|neutre",
    "conviction": "faible|modérée|forte",
    "contexte_macro": "Résumé en 2 phrases"
  },
  "plan_actions": [
    {
      "heure": "09h10",
      "titre": "CALL NQ Futures ×25",
      "sens": "CALL|PUT",
      "mise": "2500 €",
      "levier": 25,
      "strike_ko": "Strike 23500 / KO 23000",
      "gain_cible": "+20% si NQ +0,8%",
      "plateforme": "sgbourse.fr → Nasdaq 100 → CALL BEST",
      "note": "Entrée 09h10–09h30...",
      "urgence": "haute|normale|faible"
    }
  ],
  "niveaux_cles": [
    {
      "label": "Résistance haute",
      "prix": 25478,
      "type": "resistance|support|current",
      "action": "Prendre profits TP2",
      "couleur": "bull|bear|amber|blue"
    }
  ],
  "alertes": ["FOMC ce soir 20h ET"],
  "regles_session": ["Stop mental −40% = sortie immédiate"],
  "market_strip": {
    "nq":    {"valeur": "25 112", "chg": "+0,39%", "dir": "up"},
    "cac40": {"valeur": "7 900",  "chg": "-0,10%", "dir": "fl"},
    "brent": {"valeur": "101,0",  "chg": "-0,20%", "dir": "dn"},
    "vix":   {"valeur": "22,4",   "chg": "-17,7%", "dir": "up"}
  },
  "pea_note": "PEA — Ne pas toucher.",
  "edition": "09h00 CET",
  "mode": "normal|fomc|news_flash"
}"""


async def synthesize_brief(raw_data: dict, trigger_type) -> dict:
    user_message = _build_user_message(raw_data, trigger_type)
    log.info(f"Appel Gemini API — {len(user_message)} chars")

    prompt = SYSTEM_PROMPT + "\n\n" + user_message

    import asyncio
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: CLIENT.models.generate_content(
            model=MODEL,
            contents=prompt,
        )
    )

    raw_response = response.text
    log.info(f"Gemini répondu — {len(raw_response)} chars")

    brief = _parse_response(raw_response)
    brief = _validate_brief(brief, raw_data)
    return brief


def _build_user_message(data: dict, trigger_type) -> str:
    now = datetime.now(PARIS)
    sections = [
        f"# BRIEF {trigger_type}",
        f"Date: {now.strftime('%A %d %B %Y — %H:%M CET')}",
        "",
    ]

    market = data.get("market", {})
    if market and not market.get("error"):
        sections.append("## COTATIONS")
        for key in ["nq_futures", "cac40", "vix", "gold", "eurusd", "brent", "us10y"]:
            item = market.get(key, {})
            if item.get("price"):
                chg = f"{item.get('change_pct', 0):+.2f}%" if item.get("change_pct") is not None else "N/A"
                sections.append(f"- {key.upper()}: {item['price']} ({chg})")
        sections.append("")

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

    cal = data.get("calendar", {})
    if cal and not cal.get("error"):
        sections.append("## CALENDRIER")
        for e in cal.get("today_high_impact", []):
            sections.append(f"  ⚠️ {e.get('time','?')} — {e.get('name','?')}")
        fomc = cal.get("fomc_schedule", {})
        if fomc:
            probs = fomc.get("probabilities", {})
            sections.append(f"FOMC: Hold {probs.get('hold','?')}%, Coupe {probs.get('cut_25','?')}%")
        sections.append("")

    news = data.get("news", {})
    if news and not news.get("error"):
        sections.append("## NEWS")
        sections.append(f"Sentiment: {news.get('sentiment', 0):+.2f}")
        themes = news.get("themes", [])
        if themes:
            sections.append(f"Thèmes: {', '.join(t['theme'] for t in themes)}")
        for a in [a for a in news.get("articles", []) if a.get("urgency") in ("high", "critical")][:4]:
            sections.append(f"  - [{a.get('urgency','?').upper()}] {a.get('title','')}")
        sections.append("")

    sections.append("Génère le brief JSON complet. JSON uniquement, aucun texte autour.")
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
    if not brief.get("timestamp"):
        brief["timestamp"] = datetime.now(PARIS).isoformat()
    if not brief.get("edition"):
        brief["edition"] = datetime.now(PARIS).strftime("%Hh%M CET")

    market = raw_data.get("market", {})
    if market and not market.get("error"):
        strip = brief.get("market_strip", {})

        def fmt(val, d=0):
            return f"{val:,.{d}f}".replace(",", " ") if val else "—"

        def fchg(chg):
            return f"{chg:+.2f}%" if chg is not None else "—"

        for key, label, decimals in [
            ("nq_futures", "nq", 0),
            ("cac40", "cac40", 0),
            ("vix", "vix", 1),
            ("brent", "brent", 1),
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

    brief["date_fr"] = datetime.now(PARIS).strftime("%A %d %B %Y").capitalize()
    return brief
