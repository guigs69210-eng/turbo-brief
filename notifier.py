"""
Sous-agent Notifications — Telegram + Email + PDF
"""

import logging
import os
import sys
import json
import base64
import subprocess
import smtplib
import urllib.request
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiohttp

log = logging.getLogger("agent.notifier")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT  = os.getenv("TELEGRAM_CHAT_ID")
SMTP_HOST      = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT      = int(os.getenv("SMTP_PORT", 587))
SMTP_USER      = os.getenv("SMTP_USER")
SMTP_PASS      = os.getenv("SMTP_PASS")
EMAIL_TO       = os.getenv("EMAIL_TO")

# Répertoire racine du repo
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        log.warning("Telegram non configuré")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHAT,
        "text":       message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    log.info("Telegram: envoyé ✓")
                    return True
                else:
                    body = await resp.text()
                    log.warning(f"Telegram error {resp.status}: {body[:200]}")
                    return False
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return False


async def send_telegram_pdf(brief: dict) -> bool:
    """Génère le PDF v7 et l'envoie via Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        log.warning("Telegram non configuré — PDF non envoyé")
        return False

    try:
        # 1. Générer le PDF via make_pdf_v7.py
        pdf_path = os.path.join(_BASE, "turbo_brief_daily.pdf")
        make_pdf = os.path.join(_BASE, "make_pdf_v7.py")

        if not os.path.exists(make_pdf):
            log.warning(f"make_pdf_v7.py introuvable dans {_BASE}")
            return False

        # Patcher le chemin de sortie
        with open(make_pdf, "r", encoding="utf-8") as f:
            code = f.read()

        import re
        code = re.sub(
            r"""[\"'][^\"']*\.pdf[\"']""",
            f'"{pdf_path}"',
            code,
            count=1
        )

        tmp = os.path.join(_BASE, "_make_pdf_tmp.py")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(code)

        result = subprocess.run(
            [sys.executable, tmp],
            capture_output=True, text=True, timeout=60,
            cwd=_BASE
        )
        try:
            os.remove(tmp)
        except Exception:
            pass

        if result.returncode != 0:
            log.error(f"PDF generation failed: {result.stderr[-300:]}")
            return False

        if not os.path.exists(pdf_path):
            log.error(f"PDF absent après génération. stdout: {result.stdout[-200:]}")
            return False

        log.info(f"PDF généré : {os.path.getsize(pdf_path)//1024} KB")

        # 2. Envoyer via Telegram sendDocument
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        os.remove(pdf_path)

        from datetime import date
        filename = f"turbo_brief_{date.today().strftime('%Y%m%d')}.pdf"
        caption  = f"📄 Turbo Brief — {brief.get('date_fr', date.today().strftime('%d/%m/%Y'))}"

        boundary = "TurboBriefBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
            f"{TELEGRAM_CHAT}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="caption"\r\n\r\n'
            f"{caption}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
        ).encode("utf-8") + pdf_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result_tg = json.loads(resp.read())

        if result_tg.get("ok"):
            log.info("Telegram PDF: envoyé ✓")
            return True
        else:
            log.warning(f"Telegram PDF error: {result_tg}")
            return False

    except Exception as e:
        log.error(f"send_telegram_pdf error: {e}")
        return False


async def send_email(brief: dict) -> bool:
    if not all([SMTP_USER, SMTP_PASS, EMAIL_TO]):
        log.warning("Email non configuré")
        return False

    try:
        signal  = brief.get("signal_du_jour", {})
        subject = f"🗞 Turbo Brief — {brief.get('edition','?')} — {signal.get('titre','?')}"

        body = _build_email_html(brief)
        msg  = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = EMAIL_TO
        msg.attach(MIMEText(body, "html"))

        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _send_smtp, msg)
        log.info("Email envoyé ✓")
        return True
    except Exception as e:
        log.error(f"Email error: {e}")
        return False


def _send_smtp(msg):
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())


def _build_email_html(brief: dict) -> str:
    signal  = brief.get("signal_du_jour", {})
    actions = brief.get("plan_actions", [])
    alertes = brief.get("alertes", [])
    strip   = brief.get("market_strip", {})

    strip_html = ""
    for key, label in [("nq","NQ"), ("cac40","CAC 40"), ("vix","VIX"), ("brent","Brent")]:
        item = strip.get(key, {})
        if item:
            color = "#1A5C2E" if item.get("dir") == "up" else "#8B1A1A" if item.get("dir") == "dn" else "#666"
            strip_html += f"""
            <td style="text-align:center;padding:8px 12px;border-right:1px solid #D6CCBC">
              <div style="font-size:9px;color:#9E9285">{label}</div>
              <div style="font-size:15px;font-weight:600;font-family:monospace">{item.get('valeur','—')}</div>
              <div style="font-size:10px;color:{color};font-family:monospace">{item.get('chg','—')}</div>
            </td>"""

    actions_html = ""
    for action in actions:
        color = "#1A5C2E" if action.get("sens") == "CALL" else "#8B1A1A"
        actions_html += f"""
        <div style="background:#fff;border:1px solid #D6CCBC;margin-bottom:8px;padding:10px 12px">
          <div style="font-size:11px;color:#9E9285;font-family:monospace">{action.get('heure','?')}</div>
          <div style="font-size:14px;font-weight:600;color:#1A1612">{action.get('titre','?')}</div>
          <div style="font-size:13px;color:{color};font-family:monospace">
            {action.get('mise','?')} · ×{action.get('levier','?')} · {action.get('gain_cible','?')}
          </div>
          <div style="font-size:11px;color:#6B5F50;margin-top:4px;font-style:italic">{action.get('note','')}</div>
        </div>"""

    alertes_html = "".join(
        f'<div style="padding:4px 0;font-size:12px">⚠️ {a}</div>' for a in alertes
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="background:#FBF7F0;font-family:Georgia,serif;margin:0;padding:0">
<div style="max-width:600px;margin:0 auto;padding:16px">
  <div style="border-bottom:3px double #1A1612;padding-bottom:10px;margin-bottom:16px">
    <div style="font-size:26px;font-weight:700">Turbo Brief</div>
    <div style="font-size:11px;color:#6B5F50;font-style:italic">{brief.get('date_fr','?')} — {brief.get('edition','?')}</div>
  </div>
  <div style="font-size:18px;font-weight:700;margin-bottom:4px">{signal.get('titre','—')}</div>
  <div style="font-size:13px;font-style:italic;color:#6B5F50;margin-bottom:16px">{signal.get('description','')}</div>
  <table style="width:100%;border:1px solid #D6CCBC;border-collapse:collapse;margin-bottom:16px">
    <tr>{strip_html}</tr>
  </table>
  <div style="font-size:9px;letter-spacing:2px;color:#9E9285;text-transform:uppercase;margin-bottom:8px">Plan d'action</div>
  {actions_html}
  {"<div style='background:#FDF3DC;border-left:3px solid #7A4F0A;padding:10px 12px;margin-top:12px'>" + alertes_html + "</div>" if alertes else ""}
  <div style="text-align:center;font-size:9px;color:#9E9285;margin-top:20px;border-top:0.5px solid #D6CCBC;padding-top:10px">
    ⚠ Outil pédagogique — pas un conseil financier
  </div>
</div>
</body></html>"""
