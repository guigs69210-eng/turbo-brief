#!/usr/bin/env python3
"""
agent_makecom.py — Agent Turbo Brief pour Make.com
====================================================
Ce script est appelé par Make.com chaque matin via Claude API.
Il retourne le PDF encodé en base64 + un résumé texte pour Telegram.

FLOW MAKE.COM :
  1. Schedule (08h00 lun-ven)
  2. HTTP Module → POST https://api.anthropic.com/v1/messages
     Body = prompt ci-dessous
  3. Parse la réponse → extraire PDF base64 + texte résumé
  4. Telegram → sendDocument (PDF) + sendMessage (résumé)

PROMPT À COPIER DANS MAKE.COM :
────────────────────────────────
Tu es un agent de trading. Exécute turbo_nl pour aujourd'hui.
Fetch les cours NQ, VIX, Thales, Brent sur Yahoo Finance.
Génère le rapport PDF complet (2 pages).
Retourne UNIQUEMENT un JSON valide avec cette structure exacte :
{
  "date": "DD/MM/YYYY",
  "signal": "HAUSSIER|BAISSIER|NEUTRE",
  "nq": 24470,
  "vix": 24.4,
  "thales": 248.0,
  "brent": 101.0,
  "positions_resume": "PUT NQ -58% KO dist 1.6% | CALL HO +56%",
  "alerte": "STOP -40% ATTEINT PUT NQ",
  "reco_principale": "Vendre PUT NQ maintenant - stop atteint",
  "pdf_b64": "BASE64_DU_PDF",
  "telegram_message": "MESSAGE_FORMATÉ_MARKDOWN"
}
────────────────────────────────
"""

import os as _os, sys as _sys

# Robuste : fonctionne avec exec(), subprocess, GitHub Actions
try:
    _BASE = _os.path.dirname(_os.path.abspath(__file__))
except NameError:
    _BASE = _os.path.dirname(_os.path.abspath(_sys.argv[0]))
if not _BASE or _BASE == '/':
    _BASE = _os.getcwd()

def _path(filename):
    return _os.path.join(_BASE, filename)



import json, os, sys, base64, urllib.request, urllib.parse
from datetime import datetime, date

# ═══════════════════════════════════════════════════════════════════════
# PARTIE 1 : FETCH COURS LIVE (appelé par l'agent)
# ═══════════════════════════════════════════════════════════════════════

def fetch_cours_live():
    """Fetch NQ, VIX, Thales, Brent depuis Yahoo Finance (pas d'API key requise)"""
    tickers = {
        'NQ':     'NQ=F',      # NQ Futures
        'VIX':    '^VIX',
        'HO':     'HO.PA',     # Thales Paris
        'BRENT':  'BZ=F',      # Brent Futures
        'EURUSD': 'EURUSD=X',
        'GOLD':   'GC=F',
        'US10Y':  '^TNX',
    }
    results = {}
    headers = {'User-Agent': 'Mozilla/5.0'}

    for key, ticker in tickers.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
            req = urllib.request.Request(url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            price = data['chart']['result'][0]['meta']['regularMarketPrice']
            results[key] = round(price, 4)
        except Exception as e:
            results[key] = None
            print(f"  ⚠ {key} ({ticker}): {e}")

    return results

# ═══════════════════════════════════════════════════════════════════════
# PARTIE 2 : MISE À JOUR REPORT_DATA ET GÉNÉRATION PDF
# ═══════════════════════════════════════════════════════════════════════

def update_and_generate(cours):
    """Met à jour report_data.json avec les cours live et génère le PDF"""
    sys.path.insert(0, _BASE)

    with open(_path('report_data.json'), encoding='utf-8') as f:
        r = json.load(f)

    NQ    = cours.get('NQ')    or r.get('nasdaq_current', 24470)
    HO    = cours.get('HO')    or 248.0
    VIX   = cours.get('VIX')   or r['additional_kpis'].get('vix', 24.4)
    BRENT = cours.get('BRENT') or r['oil'].get('brent', 101.0)
    FX    = cours.get('EURUSD')or 1.1534
    GOLD  = cours.get('GOLD')  or r['additional_kpis'].get('gold', 4620)
    US10Y = cours.get('US10Y') or r['additional_kpis'].get('us10y', 4.28)

    today = date.today()
    jours = ['Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi','Dimanche']
    mois  = ['janvier','février','mars','avril','mai','juin',
             'juillet','août','septembre','octobre','novembre','décembre']
    date_fr = f"{jours[today.weekday()]} {today.day} {mois[today.month-1]} {today.year}"

    r['date']              = date_fr
    r['heure']             = datetime.now().strftime('%Hh%M')
    r['nasdaq_current']    = NQ
    r['nasdaq_change_pct'] = round((NQ - r.get('nasdaq_prev_close', NQ)) / max(r.get('nasdaq_prev_close', NQ), 1) * 100, 2)
    r['additional_kpis']['vix']    = VIX
    r['additional_kpis']['gold']   = GOLD
    r['additional_kpis']['us10y']  = US10Y
    r['additional_kpis']['eur_usd']= FX
    r['oil']['brent']              = BRENT

    # P&L positions ouvertes
    total_pnl = 0
    alertes   = []
    pos_lines = []

    for pos in r.get('positions_ouvertes', []):
        sj = NQ if ('NQ' in pos.get('sous_jacent','') or 'Nasdaq' in pos.get('sous_jacent','')) else HO
        fx = FX if pos.get('devise','EUR') == 'USD' else 1.0
        strike = pos['strike']
        parite = pos['parite']
        sens   = pos['sens']

        if sens == 'CALL':
            vi = max((sj - strike) / parite / fx, 0)
        else:
            vi = max((strike - sj) / parite / fx, 0)

        px_achat = pos['prix_achat']
        nb       = pos['nb_titres']
        pnl_pct  = round((vi - px_achat) / px_achat * 100, 1) if px_achat > 0 else 0
        pnl_eur  = round((vi - px_achat) * nb, 0)
        ko_dist  = round((sj - strike) / sj * 100 if sens == 'CALL' else (strike - sj) / sj * 100, 1)

        pos.update({
            'sj_live': sj, 'pnl_live_pct': pnl_pct,
            'pnl_live_eur': pnl_eur, 'ko_dist_live': ko_dist,
            'status_live': f'{pnl_pct:+.1f}% / {pnl_eur:+.0f}€'
        })
        total_pnl += pnl_eur
        pos_lines.append(f"{pos['sens']} {pos.get('sous_jacent','')} {pnl_pct:+.1f}% KO {ko_dist:.1f}%")

        if pnl_pct <= -40:
            alertes.append(f"🚨 STOP -40% {pos['sens']} {pos.get('sous_jacent','')} — VENDRE")
        elif ko_dist < 2.5:
            alertes.append(f"⚠️ KO {ko_dist:.1f}% {pos['sens']} {pos.get('sous_jacent','')} — DANGER")
        elif pnl_pct >= 25:
            alertes.append(f"🎯 TP1 +{pnl_pct:.0f}% {pos['sens']} {pos.get('sous_jacent','')} — Vendre 50%")

        # Alerte fermeture 17h30
        h = datetime.now().hour
        if h >= 17 and 'HO' in pos.get('sous_jacent',''):
            alertes.append("⏰ 17h30 APPROCHE — Clore Thales MAINTENANT")

    r['pnl_live_total'] = total_pnl
    r['cto_recap']['pnl_live_total'] = total_pnl

    with open(_path('report_data.json'), 'w', encoding='utf-8') as f:
        json.dump(r, f, ensure_ascii=False, indent=2)

    # Signal auto
    vix_delta = VIX - 22
    if VIX > 27:
        signal = "FORT BAISSIER"
    elif VIX > 23:
        signal = "BAISSIER"
    elif VIX < 18:
        signal = "HAUSSIER"
    else:
        signal = "NEUTRE"

    return {
        'date': date_fr, 'signal': signal,
        'nq': NQ, 'vix': VIX, 'thales': HO, 'brent': BRENT,
        'positions_resume': ' | '.join(pos_lines) if pos_lines else 'Aucune position',
        'alerte': ' | '.join(alertes) if alertes else 'Aucune alerte',
        'total_pnl': total_pnl,
        'reserve': r['cto_recap'].get('reserve_dispo', 5494),
        'nb_positions': len([p for p in r.get('positions_ouvertes',[])]),
    }

# ═══════════════════════════════════════════════════════════════════════
# PARTIE 3 : GÉNÉRATION PDF ET ENCODAGE
# ═══════════════════════════════════════════════════════════════════════

def generate_pdf():
    """Genere le PDF v7 et retourne le base64"""
    import subprocess, sys, re
    PDF_PATH = _path('turbo_brief_daily.pdf')

    with open(_path('make_pdf_v7.py'), 'r', encoding='utf-8') as f:
        code = f.read()

    # Remplacer le chemin de sortie par regex
    code = re.sub(
        r"""["'][^"']*\.pdf["']""",
        '"' + PDF_PATH + '"',
        code,
        count=1
    )

    tmp_script = _path('_make_pdf_tmp.py')
    with open(tmp_script, 'w', encoding='utf-8') as f:
        f.write(code)

    result = subprocess.run(
        [sys.executable, tmp_script],
        capture_output=True, text=True, timeout=60,
        cwd=_BASE
    )
    try:
        os.remove(tmp_script)
    except Exception:
        pass

    if result.returncode != 0:
        raise RuntimeError("PDF error: " + result.stderr[-400:] + result.stdout[-200:])
    if not _os.path.exists(PDF_PATH):
        raise FileNotFoundError(
            f"PDF absent dans {PDF_PATH}.\n"
            f"stdout: {result.stdout[-300:]}\n"
            f"stderr: {result.stderr[-300:]}"
        )

    with open(PDF_PATH, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    os.remove(PDF_PATH)
    return b64


def format_telegram_message(data, cours):
    """Formate le message Telegram Markdown"""
    nq_chg = data.get('nq_chg', 0)
    sign   = '+' if data['total_pnl'] >= 0 else ''
    signal_icon = {'HAUSSIER':'🟢','BAISSIER':'🔴','FORT BAISSIER':'🔴🔴',
                   'NEUTRE':'🟡'}.get(data['signal'], '🟡')

    alerte_line = f"\n⚠️ *ALERTE : {data['alerte']}*" if data['alerte'] != 'Aucune alerte' else ''

    msg = f"""📊 *TURBO BRIEF — {data['date']}*
━━━━━━━━━━━━━━━━━━━━━━━━
{signal_icon} Signal : *{data['signal']}*

📈 *Marchés*
• NQ Futures : *{data['nq']:,.0f}*
• VIX : *{data['vix']}*
• Thales : *{data['thales']}€*
• Brent : *${data['brent']}*

💼 *Positions ({data['nb_positions']} ouvertes)*
{data['positions_resume']}
P&L live : *{sign}{data['total_pnl']:.0f}€*
Réserve : *{data['reserve']:.0f}€*
{alerte_line}
━━━━━━━━━━━━━━━━━━━━━━━━
📄 PDF ci-dessous ↓"""

    return msg

# ═══════════════════════════════════════════════════════════════════════
# PARTIE 5 : ENVOI TELEGRAM DIRECT (mode standalone)
# ═══════════════════════════════════════════════════════════════════════

def send_telegram_document(token, chat_id, pdf_b64, caption):
    """Envoie le PDF via Telegram Bot API"""
    pdf_bytes = base64.b64decode(pdf_b64)

    # Multipart form data pour sendDocument
    boundary = '----TurboBriefBoundary'
    today_str = date.today().strftime('%Y%m%d')
    filename  = f"turbo_brief_{today_str}.pdf"

    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
        f'{chat_id}\r\n'
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="caption"\r\n\r\n'
        f'{caption}\r\n'
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="parse_mode"\r\n\r\n'
        f'Markdown\r\n'
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        f'Content-Type: application/pdf\r\n\r\n'
    ).encode('utf-8') + pdf_bytes + f'\r\n--{boundary}--\r\n'.encode('utf-8')

    url = f'https://api.telegram.org/bot{token}/sendDocument'
    req = urllib.request.Request(url, data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        return result.get('ok', False)
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

# ═══════════════════════════════════════════════════════════════════════
# PARTIE 6 : MAIN — MODE STANDALONE (cron / Termux / PythonAnywhere)
# ═══════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Turbo Brief Daily Agent')
    parser.add_argument('--token',  default=os.environ.get('TELEGRAM_TOKEN',''),
                        help='Telegram Bot Token (ou var env TELEGRAM_TOKEN)')
    parser.add_argument('--chat',   default=os.environ.get('TELEGRAM_CHAT',''),
                        help='Telegram Chat ID (ou var env TELEGRAM_CHAT)')
    parser.add_argument('--test',   action='store_true', help='Mode test sans envoi')
    parser.add_argument('--no-fetch', action='store_true', help='Utiliser cours existants')
    args = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"TURBO BRIEF AGENT — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*55}\n")

    # 1. Fetch cours live
    if args.no_fetch:
        print("⏭  Cours live : utilisation des données existantes")
        cours = {}
    else:
        print("🌐 Fetch cours live...")
        cours = fetch_cours_live()
        for k, v in cours.items():
            status = f"{v}" if v else "⚠ ERREUR"
            print(f"   {k:8} : {status}")

    # 2. Mise à jour report_data + calcul P&L
    print("\n📊 Mise à jour rapport...")
    data = update_and_generate(cours)
    print(f"   Signal     : {data['signal']}")
    print(f"   NQ         : {data['nq']:,.0f}")
    print(f"   P&L live   : {data['total_pnl']:+.0f}€")
    if data['alerte'] != 'Aucune alerte':
        print(f"   ⚠  ALERTE  : {data['alerte']}")

    # 3. Génération PDF
    print("\n📄 Génération PDF...")
    try:
        pdf_b64 = generate_pdf()
        print(f"   PDF généré : {len(pdf_b64)//1024} KB (base64)")
    except Exception as e:
        print(f"   ❌ Erreur PDF : {e}")
        pdf_b64 = None

    # 4. Message Telegram
    msg = format_telegram_message(data, cours)
    print(f"\n📱 Message Telegram préparé ({len(msg)} chars)")

    if args.test:
        print("\n" + "─"*55)
        print("MODE TEST — Pas d'envoi")
        print("─"*55)
        print(msg)
        return

    # 5. Envoi Telegram
    if not args.token or not args.chat:
        print("\n❌ Token et Chat ID requis.")
        print("   Usage : python3 turbo_agent.py --token TON_TOKEN --chat TON_CHAT_ID")
        print("   Ou    : export TELEGRAM_TOKEN=... && export TELEGRAM_CHAT=...")
        return

    print("\n📤 Envoi Telegram...")
    if pdf_b64:
        ok = send_telegram_document(args.token, args.chat, pdf_b64, msg)
        if ok:
            print("   ✅ PDF envoyé avec succès !")
        else:
            print("   ❌ Erreur envoi PDF — envoi message texte seul...")
            # Fallback : message texte
            url = f"https://api.telegram.org/bot{args.token}/sendMessage"
            data_msg = urllib.parse.urlencode({
                'chat_id': args.chat, 'text': msg, 'parse_mode': 'Markdown'
            }).encode()
            urllib.request.urlopen(urllib.request.Request(url, data_msg), timeout=10)
    else:
        print("   ⚠  PDF non disponible — envoi résumé texte")

    print(f"\n✅ Turbo Brief envoyé — {datetime.now().strftime('%H:%M:%S')}")

if __name__ == '__main__':
    main()
