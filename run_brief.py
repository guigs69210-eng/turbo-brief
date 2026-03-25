import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S", stream=sys.stdout)
log = logging.getLogger("run_brief")
PARIS = ZoneInfo("Europe/Paris")


def detect_trigger_from_time() -> str:
    now = datetime.now(PARIS)
    h = now.hour
    if h == 8:   return "morning"
    if h in (13, 14): return "us"
    if h == 17:  return "eod"
    return "refresh"


def _is_fomc_day() -> bool:
    fomc_dates = {
        "2026-03-19", "2026-05-07", "2026-06-18",
        "2026-07-30", "2026-09-17", "2026-11-05", "2026-12-10",
    }
    return datetime.now(PARIS).date().isoformat() in fomc_dates


async def main(trigger: str):
    log.info(f"=== Turbo Brief — trigger: {trigger} ===")

    from agents.market_agent    import fetch_market_data
    from agents.news_agent      import scan_news
    from agents.calendar_agent  import get_eco_calendar
    from agents.technical_agent import get_technicals
    from agents.claude_agent    import synthesize_brief
    from agents.notifier        import send_telegram, send_email, send_telegram_pdf
    from output.html_updater    import update_turbo_brief_html

    run_all = trigger in ("morning", "us", "fomc", "manual")

    tasks = {"market": fetch_market_data()}
    if run_all:
        tasks["news"]      = scan_news(mode="full")
        tasks["calendar"]  = get_eco_calendar()
        tasks["technical"] = get_technicals()
    else:
        tasks["news"] = scan_news(mode="flash")

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    raw_data = {}
    for key, result in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            log.warning(f"Agent '{key}' erreur: {result}")
            raw_data[key] = {"error": str(result)}
        else:
            raw_data[key] = result
            log.info(f"Agent '{key}' ✓")

    raw_data["trigger"]   = trigger
    raw_data["timestamp"] = datetime.now(PARIS).isoformat()
    raw_data["context"]   = {
        "note":       os.getenv("BRIEF_NOTE", ""),
        "github_run": os.getenv("GITHUB_RUN_NUMBER", "local"),
        "is_fomc":    _is_fomc_day(),
    }

    from orchestrator import TriggerType
    trigger_map = {
        "morning": TriggerType.MORNING_OPEN,
        "us":      TriggerType.US_OPEN,
        "fomc":    TriggerType.FOMC,
        "refresh": TriggerType.MANUAL,
        "eod":     TriggerType.MANUAL,
        "manual":  TriggerType.MANUAL,
    }
    trigger_type = trigger_map.get(trigger, TriggerType.MANUAL)

    if trigger == "eod":
        brief = _build_eod_brief(raw_data)
    else:
        brief = await synthesize_brief(raw_data, trigger_type)

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    (output_dir / "logs").mkdir(exist_ok=True)

    json_path = output_dir / "brief_latest.json"
    json_path.write_text(json.dumps(brief, indent=2, ensure_ascii=False))
    log.info(f"JSON: {json_path}")

    ts = datetime.now(PARIS).strftime("%Y%m%d_%H%M")
    hist = output_dir / "logs" / f"brief_{trigger}_{ts}.json"
    hist.write_text(json.dumps({"raw": raw_data, "brief": brief}, indent=2, ensure_ascii=False))

    try:
        update_turbo_brief_html(brief)
    except Exception as e:
        log.warning(f"HTML update: {e}")

    # 1. Message Telegram texte
    telegram_msg = _format_telegram(brief, trigger)
    ok = await send_telegram(telegram_msg)
    log.info(f"Telegram: {'✓' if ok else '✗'}")

    # 2. PDF Telegram — toujours pour morning/fomc/manual, jamais pour eod/refresh
    if trigger in ("morning", "us", "fomc", "manual"):
        ok_pdf = await send_telegram_pdf(brief)
        log.info(f"Telegram PDF: {'✓' if ok_pdf else '✗'}")

    if trigger in ("morning", "us", "fomc"):
        await send_email(brief)

    log.info("=== Brief terminé ✓ ===")
    _print_summary(brief)


def _build_eod_brief(raw_data: dict) -> dict:
    market = raw_data.get("market", {})
    now = datetime.now(PARIS)

    def fmt(key):
        val = market.get(key, {}).get("price")
        return f"{val:.0f}" if val else "—"

    def chg(key):
        val = market.get(key, {}).get("change_pct")
        return f"{val:+.2f}%" if val else "—"

    return {
        "signal_du_jour": {
            "titre": f"Clôture Paris — {now.strftime('%H:%M')}",
            "description": f"NQ: {fmt('nq_futures')} ({chg('nq_futures')}) · CAC: {fmt('cac40')} ({chg('cac40')})",
            "biais": "neutre", "conviction": "faible",
        },
        "plan_actions": [],
        "niveaux_cles": [],
        "alertes": ["Actions FR clôturées 17h30 — Turbos NQ cotent jusqu'à 22h"],
        "regles_session": [],
        "market_strip": {},
        "date_fr": now.strftime("%A %d %B %Y").capitalize(),
        "edition": now.strftime("%Hh%M CET"),
        "mode": "eod",
        "trigger": "eod",
    }


def _format_telegram(brief: dict, trigger: str) -> str:
    signal  = brief.get("signal_du_jour", {})
    actions = brief.get("plan_actions", [])
    alertes = brief.get("alertes", [])

    # Cours marchés — depuis market_strip (clés valeur/chg/dir)
    strip = brief.get("market_strip", {})

    def _price(key):
        return strip.get(key, {}).get("valeur", "—")

    def _chg(key):
        return strip.get(key, {}).get("chg", "")

    emoji = {"morning":"🌅","us":"🇺🇸","fomc":"🏛️","refresh":"🔄","eod":"🔔","manual":"📋"}.get(trigger,"🗞")

    biais = signal.get("biais","").upper()
    biais_icon = "🟢" if "haussier" in biais.lower() else "🔴" if "baissier" in biais.lower() else "🟡"

    lines = [
        f"{emoji} *TURBO BRIEF — {datetime.now(PARIS).strftime('%H:%M')} CET — {brief.get('date_fr', datetime.now(PARIS).strftime('%d/%m/%Y'))}*",
        f"{biais_icon} *{signal.get('titre','—')}*",
        f"_{signal.get('description','')[:120]}_",
        "",
        f"📈 NQ `{_price('nq')}` {_chg('nq')} · CAC `{_price('cac40')}` {_chg('cac40')}",
        f"📊 VIX `{_price('vix')}` · Brent `{_price('brent')}`",
        "",
    ]

    if actions:
        lines.append("*Plan d'action :*")
        for action in actions[:4]:
            e = "🟢" if action.get("sens") == "CALL" else "🔴" if action.get("sens") == "PUT" else "⚪"
            mise = action.get("mise","?")
            lev  = action.get("levier","?")
            gain = action.get("gain_cible","")
            lines.append(f"{e} *{action.get('heure','?')}* — {action.get('titre','?')}")
            if mise != "?" or lev != "?":
                lines.append(f"   `{mise}` · ×{lev}" + (f" · {gain}" if gain else ""))
        lines.append("")

    for a in alertes[:3]:
        lines.append(f"⚠️ {a}")

    lines.append(f"\n📄 PDF ci-dessous")

    return "\n".join(lines)


def _print_summary(brief: dict):
    signal  = brief.get("signal_du_jour", {})
    actions = brief.get("plan_actions", [])
    print("\n" + "="*50)
    print(f"BRIEF — {brief.get('edition','?')}")
    print(f"Signal: {signal.get('titre','?')}")
    for a in actions:
        print(f"  • {a.get('heure','?')} {a.get('sens','?')} {a.get('titre','?')}")
    print("="*50 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger", default=None)
    args = parser.parse_args()
    trigger = args.trigger or os.getenv("BRIEF_TRIGGER") or detect_trigger_from_time()
    log.info(f"Trigger: {trigger}")
    asyncio.run(main(trigger))
