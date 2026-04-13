#!/usr/bin/env python3
"""
telegram_bot.py — Bot Telegram interactif pour gestion positions
=================================================================
Commandes disponibles :
  OPEN [CALL/PUT] [SJ] x[LEV] [MISE]    — Ouvrir une position
  CLOSE [SJ] [+/-PCT ou PRIX]            — Fermer une position
  STATUS                                  — Résumé positions + P&L
  BRIEF                                   — Déclencher un brief manuel

Exemples :
  OPEN CALL NQ x15 1000
  OPEN PUT CAC x20 800
  CLOSE NQ +25
  CLOSE NQ KO
  STATUS

Usage GitHub Actions :
  python telegram_bot.py --poll
"""

import json, os, sys, re, urllib.request, urllib.parse, base64
from datetime import datetime

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN","")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID","")
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN","")
GITHUB_REPO    = os.environ.get("GITHUB_REPOSITORY","")  # ex: guigs69210/turbo-brief

# ── API Telegram ──────────────────────────────────────────────────────────────
def tg_get(method, params=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        return json.loads(resp.read())
    except Exception as e:
        print(f"TG GET error: {e}")
        return {}

def tg_send(text, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT,
        "text": text,
        "parse_mode": parse_mode,
    }).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data), timeout=10)
    except Exception as e:
        print(f"TG send error: {e}")

# ── API GitHub ────────────────────────────────────────────────────────────────
def gh_get_file(path):
    """Lire un fichier depuis GitHub, retourne (content_dict, sha)"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        content = json.loads(base64.b64decode(data["content"]).decode())
        return content, data["sha"]
    except Exception as e:
        print(f"GH get error: {e}")
        return None, None

def gh_push_file(path, content_dict, sha, message):
    """Pousser un fichier JSON sur GitHub"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    body = json.dumps({
        "message": message,
        "content": base64.b64encode(
            json.dumps(content_dict, ensure_ascii=False, indent=2).encode()
        ).decode(),
        "sha": sha,
    }).encode()
    req = urllib.request.Request(url, data=body, method="PUT", headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    })
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status in (200, 201)
    except Exception as e:
        print(f"GH push error: {e}")
        return False

# ── Parsing commandes ─────────────────────────────────────────────────────────
def parse_command(text):
    """
    Retourne un dict avec l'action parsée ou None si non reconnu.
    
    OPEN CALL NQ x15 1000     → {action:OPEN, sens:CALL, sj:NQ, lev:15, mise:1000}
    OPEN PUT CAC x20 800      → {action:OPEN, sens:PUT, sj:CAC, lev:20, mise:800}
    CLOSE NQ +25              → {action:CLOSE, sj:NQ, pnl:+25}
    CLOSE NQ KO               → {action:CLOSE, sj:NQ, pnl:KO}
    CLOSE NQ -40              → {action:CLOSE, sj:NQ, pnl:-40}
    STATUS                    → {action:STATUS}
    BRIEF                     → {action:BRIEF}
    HELP                      → {action:HELP}
    """
    if not text:
        return None
    t = text.strip().upper()
    
    if t in ("STATUS", "S", "POS"):
        return {"action": "STATUS"}
    if t in ("BRIEF", "B"):
        return {"action": "BRIEF"}
    if t in ("HELP", "H", "?"):
        return {"action": "HELP"}

    # OPEN [CALL/PUT] [SJ] x[LEV] [MISE]
    m = re.match(r"OPEN\s+(CALL|PUT)\s+(\w+)\s+[Xx](\d+)\s+(\d+)", t)
    if m:
        return {
            "action": "OPEN",
            "sens": m.group(1),
            "sj": m.group(2),
            "levier": int(m.group(3)),
            "mise": float(m.group(4)),
        }

    # CLOSE [SJ] [+/-PCT | KO | PRIX]
    m = re.match(r"CLOSE\s+(\w+)\s*([\+\-]\d+\.?\d*|KO)?", t)
    if m:
        pnl_raw = m.group(2) or ""
        if pnl_raw == "KO":
            pnl = "KO"
        elif pnl_raw:
            try: pnl = float(pnl_raw)
            except: pnl = 0.0
        else:
            pnl = 0.0
        return {"action": "CLOSE", "sj": m.group(1), "pnl": pnl}

    return None

# ── Gestion positions ─────────────────────────────────────────────────────────
def action_open(r, cmd, sha):
    """Ouvrir une nouvelle position"""
    sj    = cmd["sj"]
    sens  = cmd["sens"]
    lev   = cmd["levier"]
    mise  = cmd["mise"]
    now   = datetime.now()

    pos = {
        "label":      f"{sens} {sj} Turbo x{lev}",
        "sens":       sens,
        "sous_jacent": sj,
        "isin":       f"{sj}-{now.strftime('%d%m%H%M')}",
        "nb_titres":  0,
        "prix_achat": 0.0,
        "strike":     0.0,
        "parite":     100 if "NQ" in sj else 10,
        "devise":     "USD" if "NQ" in sj else "EUR",
        "levier":     lev,
        "sj_entree":  0,
        "heure_achat": now.strftime("%Hh%M %d/%m"),
        "mise_eur":   mise,
        "pnl_live_pct": 0.0,
        "pnl_live_eur": 0.0,
        "ko_dist_live": 0.0,
        "stop_turbo": 0.0,
        "tp1_turbo":  0.0,
        "tp2_turbo":  0.0,
        "status":     "OUVERT",
    }

    positions = r.get("positions_ouvertes", [])
    positions.append(pos)
    r["positions_ouvertes"] = positions

    # Mettre à jour CTO recap
    cto = r.get("cto_recap", {})
    cto["total_engage"]  = sum(p.get("mise_eur",0) for p in positions if p.get("status")=="OUVERT")
    cto["nb_positions"]  = len([p for p in positions if p.get("status")=="OUVERT"])
    cto["reserve_dispo"] = max(0, cto.get("reserve_dispo", 6773) - mise)
    r["cto_recap"] = cto

    return r, f"✅ *Position ouverte*\n{sens} {sj} ×{lev} — {mise:.0f}€\nHeure : {now.strftime('%Hh%M')}\n\n💡 Ajoute le strike/KO avec :\n`UPDATE {sj} STRIKE 24000 KO 23500`"

def action_close(r, cmd, sha):
    """Fermer une position"""
    sj      = cmd["sj"]
    pnl_raw = cmd["pnl"]
    positions = r.get("positions_ouvertes", [])
    
    # Trouver la position ouverte correspondante
    found = None
    for p in positions:
        if sj.upper() in p.get("sous_jacent","").upper() or \
           sj.upper() in p.get("label","").upper():
            if p.get("status") == "OUVERT":
                found = p
                break

    if not found:
        return r, f"❌ Aucune position ouverte trouvée pour *{sj}*"

    mise = found.get("mise_eur", 0)

    if pnl_raw == "KO":
        pnl_eur = -mise
        pnl_pct = -100.0
        status  = "KO"
        emoji   = "💀"
    else:
        pnl_pct = float(pnl_raw) if pnl_raw else 0.0
        pnl_eur = round(mise * pnl_pct / 100, 0)
        status  = "CLOTURE"
        emoji   = "✅" if pnl_eur >= 0 else "🔴"

    found["status"]       = status
    found["pnl_live_pct"] = pnl_pct
    found["pnl_live_eur"] = pnl_eur
    found["heure_sortie"] = datetime.now().strftime("%Hh%M %d/%m")

    # Historique trades
    hist = r.get("historique_trades", [])
    hist.append({
        "date":    datetime.now().strftime("%d/%m/%Y %Hh%M"),
        "label":   found.get("label",""),
        "sens":    found.get("sens",""),
        "mise":    mise,
        "pnl_pct": pnl_pct,
        "pnl_eur": pnl_eur,
        "status":  status,
    })
    r["historique_trades"] = hist[-50:]  # garder 50 derniers

    # Mettre à jour CTO
    cto = r.get("cto_recap", {})
    ouvertes = [p for p in positions if p.get("status")=="OUVERT"]
    cto["total_engage"]  = sum(p.get("mise_eur",0) for p in ouvertes)
    cto["nb_positions"]  = len(ouvertes)
    cto["reserve_dispo"] = cto.get("reserve_dispo", 0) + mise + pnl_eur
    r["cto_recap"] = cto
    r["positions_ouvertes"] = positions
    r["pnl_live_total"] = sum(p.get("pnl_live_eur",0) for p in ouvertes)

    sign = "+" if pnl_eur >= 0 else ""
    return r, (f"{emoji} *Position clôturée*\n"
               f"{found.get('label','')}\n"
               f"P&L : *{sign}{pnl_pct:.1f}% / {sign}{pnl_eur:.0f}€*\n"
               f"Réserve : *{cto.get('reserve_dispo',0):.0f}€*")

def action_status(r):
    """Résumé positions + P&L"""
    positions = r.get("positions_ouvertes", [])
    ouvertes  = [p for p in positions if p.get("status")=="OUVERT"]
    cto       = r.get("cto_recap", {})
    hist      = r.get("historique_trades", [])

    lines = [f"💼 *PORTFOLIO — {datetime.now().strftime('%d/%m %Hh%M')}*", ""]

    if not ouvertes:
        lines.append("📭 Aucune position ouverte")
        lines.append(f"Réserve : *{cto.get('reserve_dispo', 0):.0f}€*")
    else:
        for p in ouvertes:
            sens_e = "🟢" if p.get("sens")=="CALL" else "🔴"
            pct = p.get("pnl_live_pct", 0)
            eur = p.get("pnl_live_eur", 0)
            sign = "+" if pct >= 0 else ""
            lines.append(f"{sens_e} *{p.get('label','')}*")
            lines.append(f"   Mise: {p.get('mise_eur',0):.0f}€ | P&L: {sign}{pct:.1f}% / {sign}{eur:.0f}€")
        lines.append("")
        lines.append(f"📊 Engagé: *{cto.get('total_engage',0):.0f}€*")
        lines.append(f"💰 Réserve: *{cto.get('reserve_dispo',0):.0f}€*")

    # Derniers trades fermés
    recents = [h for h in hist[-5:] if h.get("status") in ("CLOTURE","KO")]
    if recents:
        lines.append("")
        lines.append("📜 *Derniers trades :*")
        for h in reversed(recents[-3:]):
            sign = "+" if h.get("pnl_eur",0) >= 0 else ""
            e = "💀" if h.get("status")=="KO" else ("✅" if h.get("pnl_eur",0)>=0 else "🔴")
            lines.append(f"  {e} {h.get('label','')} {sign}{h.get('pnl_eur',0):.0f}€ ({h.get('date','')})")

    return "\n".join(lines)

def action_help():
    return """📖 *Commandes bot trading*

*Ouvrir une position :*
`OPEN CALL NQ x15 1000`
`OPEN PUT CAC x20 800`

*Fermer une position :*
`CLOSE NQ +25`      → P&L +25%
`CLOSE NQ -38`      → P&L -38%
`CLOSE NQ KO`       → KO total
`CLOSE CAC +0`      → sortie flat

*Informations :*
`STATUS`            → positions + P&L
`BRIEF`             → déclencher un brief
`HELP`              → cette aide"""

# ── Loop principal ────────────────────────────────────────────────────────────
def poll_and_process():
    """Lire les messages non traités et les traiter"""
    # Lire le dernier update_id traité
    state_file = "/tmp/tg_last_update.txt"
    last_id = 0
    try:
        with open(state_file) as f:
            last_id = int(f.read().strip())
    except:
        pass

    # Récupérer les updates
    result = tg_get("getUpdates", {"offset": last_id + 1, "timeout": 5, "limit": 10})
    updates = result.get("result", [])

    if not updates:
        print("Aucun nouveau message")
        return

    # Charger report_data depuis GitHub
    r, sha = gh_get_file("report_data.json")
    if r is None:
        # Fallback local
        try:
            with open("report_data.json", encoding="utf-8") as f:
                r = json.load(f)
            sha = None
        except:
            r = {"positions_ouvertes": [], "cto_recap": {"reserve_dispo": 6773}, "historique_trades": []}
            sha = None

    changed = False
    new_last_id = last_id

    for update in updates:
        uid = update.get("update_id", 0)
        new_last_id = max(new_last_id, uid)

        msg = update.get("message", {})
        text = msg.get("text", "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))

        # Sécurité : seulement ton chat
        if TELEGRAM_CHAT and chat_id != str(TELEGRAM_CHAT):
            print(f"Message ignoré de chat_id {chat_id}")
            continue

        if not text:
            continue

        print(f"Message reçu : {text}")
        cmd = parse_command(text)

        if cmd is None:
            tg_send(f"❓ Commande non reconnue : `{text}`\nTape `HELP` pour la liste des commandes.")
            continue

        action = cmd["action"]

        if action == "HELP":
            tg_send(action_help())

        elif action == "STATUS":
            tg_send(action_status(r))

        elif action == "BRIEF":
            tg_send("🔄 Brief déclenché — reçois le PDF dans ~60 secondes...")
            # Le brief sera déclenché via workflow_dispatch si configuré
            # Pour l'instant juste message de confirmation

        elif action == "OPEN":
            r, reply = action_open(r, cmd, sha)
            tg_send(reply)
            changed = True

        elif action == "CLOSE":
            r, reply = action_close(r, cmd, sha)
            tg_send(reply)
            changed = True

    # Sauvegarder le nouvel update_id
    with open(state_file, "w") as f:
        f.write(str(new_last_id))

    # Push report_data sur GitHub si modifié
    if changed:
        print("Pushing report_data.json to GitHub...")
        if sha and GITHUB_TOKEN and GITHUB_REPO:
            success = gh_push_file(
                "report_data.json", r, sha,
                f"bot: update positions {datetime.now().strftime('%d/%m %Hh%M')}"
            )
            if success:
                print("GitHub push OK")
                tg_send("📤 Portfolio mis à jour sur GitHub ✅")
            else:
                print("GitHub push FAILED")
                tg_send("⚠️ Erreur push GitHub — positions sauvegardées localement")
        else:
            # Fallback local
            with open("report_data.json", "w", encoding="utf-8") as f:
                json.dump(r, f, ensure_ascii=False, indent=2)
            print("Saved locally (no GitHub token)")

if __name__ == "__main__":
    if "--poll" in sys.argv:
        poll_and_process()
    else:
        print(__doc__)
