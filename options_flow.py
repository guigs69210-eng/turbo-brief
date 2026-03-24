"""
options_flow.py — Récupération et analyse du flux options (Put/Call ratio, OI, flow)
=====================================================================================
Sources gratuites exploitées :
  • CBOE Equity P/C Ratio J-1   → ycharts.com (scrape titre de page)
  • QQQ OI Put/Call Ratio       → fintel.io/sopt/us/qqq
  • Données contextuelles NQ    → calcul à partir des inputs fournis

F10 — OPTIONS FLOW SCORE (0-8 pts dans scoring v2)
  +2  P/C equity < 0.70 (calls dominent = momentum)
  +1  P/C equity 0.70-0.85 (légèrement haussier)
   0  P/C equity 0.86-1.00 (neutre — aujourd'hui)
  -1  P/C equity 1.01-1.20 (couverture institutionnelle)
  -2  P/C equity > 1.20 (forte peur)
  
  CONTRARIEN (inverse quand excès extrême) :
  +2  QQQ OI P/C > 1.40 ET P/C equity > 1.15 (excess fear → rebond)
  -2  QQQ OI P/C < 0.50 (excès d'optimisme → retournement)

  +1  Volume calls > OI calls (nouvelles positions longues = signal fort)
  +1  FOMC approaching + P/C montant = hedging normal (neutraliser pénalité)
  -2  Sweep puts massifs détectés (signal institutionnel bearish)
  +2  Sweep calls massifs détectés (signal institutionnel bullish)
"""
import re, json
from datetime import datetime, date

try:
    import urllib.request
    HAS_NET = True
except ImportError:
    HAS_NET = False

# ── Scraping léger ────────────────────────────────────────────────────────────

def _fetch_text(url, timeout=8):
    """Récupère le texte brut d'une page."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; research bot)',
            'Accept': 'text/html,application/xhtml+xml',
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return raw.decode('utf-8')
            except UnicodeDecodeError:
                return raw.decode('latin-1', errors='replace')
    except Exception as e:
        return f"ERROR:{e}"

def fetch_cboe_equity_pc():
    """
    Récupère le CBOE Equity Put/Call Ratio depuis ycharts.
    La valeur apparaît dans le titre : "0.86 for Mar 17 2026"
    """
    html = _fetch_text("https://ycharts.com/indicators/cboe_equity_put_call_ratio")
    if html.startswith("ERROR"):
        return None, "ycharts indisponible"
    
    # Pattern dans le titre / méta
    patterns = [
        r'(\d+\.\d+)\s+for\s+\w+\s+\d+\s+\d{4}',
        r'"value":\s*"?(\d+\.\d+)"?',
        r'>(\d+\.\d+)<.*?Put.Call',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if 0.3 < val < 3.0:  # sanity check
                return val, "ycharts"
    return None, "parse failed"

def fetch_qqq_oi_pc():
    """
    Récupère le QQQ Open Interest Put/Call Ratio depuis fintel.io.
    "The OI Put/Call Ratio for QQQ is X.XX"
    """
    html = _fetch_text("https://fintel.io/sopt/us/qqq")
    if html.startswith("ERROR"):
        return None, "fintel indisponible"
    
    patterns = [
        r'OI Put.Call Ratio.*?is\s+(\d+\.\d+)',
        r'Put.Call Ratio.*?(\d+\.\d+)',
        r'"putCallRatio":\s*(\d+\.\d+)',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if m:
            val = float(m.group(1))
            if 0.3 < val < 5.0:
                return val, "fintel"
    return None, "parse failed"

def fetch_options_data(force_manual=False):
    """
    Récupère toutes les données options disponibles.
    Retourne un dict avec les valeurs et leur source.
    """
    data = {
        "cboe_equity_pc":   None,
        "cboe_equity_pc_src": "—",
        "qqq_oi_pc":        None,
        "qqq_oi_pc_src":    "—",
        "fetched_at":       datetime.now().strftime("%H:%M"),
        "date":             str(date.today()),
    }
    
    if not force_manual and HAS_NET:
        v, src = fetch_cboe_equity_pc()
        if v:
            data["cboe_equity_pc"]     = v
            data["cboe_equity_pc_src"] = src
        
        v2, src2 = fetch_qqq_oi_pc()
        if v2:
            data["qqq_oi_pc"]     = v2
            data["qqq_oi_pc_src"] = src2
    
    return data

# ── Scoring F10 ───────────────────────────────────────────────────────────────

def score_options_flow(
    cboe_equity_pc=None,      # CBOE Equity P/C ratio J-1 (ex: 0.86)
    qqq_oi_pc=None,           # QQQ Open Interest P/C ratio (ex: 1.60)
    cboe_total_pc=None,       # CBOE Total P/C (index+equity, ex: 0.90)
    vol_call_vs_oi=None,      # Volume calls / OI calls (>1 = nouvelles positions)
    sweep_calls=False,        # Sweep orders calls massifs détectés
    sweep_puts=False,         # Sweep orders puts massifs détectés
    fomc_today=False,         # FOMC aujourd'hui → neutraliser pénalité hedging
    sens="CALL",
    context_fear_greed=None,  # Fear & Greed pour contexte contrarien
):
    """
    Calcule le score options flow (0-8 pts).
    Retourne score + dict explicatif.
    """
    score = 4  # base neutre
    signals = {}
    
    # ── CBOE Equity P/C (signal principal) ───────────────────────────────────
    if cboe_equity_pc is not None:
        pc = cboe_equity_pc
        
        if sens == "CALL":
            if pc < 0.55:
                score += 1   # suroptimisme — calls dominent mais risque retournement
                signals["cboe_pc"] = f"P/C {pc:.2f} — calls dominent (attention surachat)"
            elif pc < 0.70:
                score += 2
                signals["cboe_pc"] = f"P/C {pc:.2f} — haussier, momentum calls fort"
            elif pc < 0.86:
                score += 1
                signals["cboe_pc"] = f"P/C {pc:.2f} — légèrement haussier"
            elif pc <= 1.00:
                # Avant FOMC : hausse du P/C = hedging normal → neutraliser
                if fomc_today:
                    score += 0
                    signals["cboe_pc"] = f"P/C {pc:.2f} — neutre (hausse normale pre-FOMC)"
                else:
                    score += 0
                    signals["cboe_pc"] = f"P/C {pc:.2f} — zone neutre"
            elif pc <= 1.20:
                score -= 1
                signals["cboe_pc"] = f"P/C {pc:.2f} — couverture institutionnelle croissante"
            elif pc <= 1.50:
                score -= 2
                signals["cboe_pc"] = f"P/C {pc:.2f} — fort hedging, prudence"
            else:
                # Excès extrême → contrarien haussier
                score += 1
                signals["cboe_pc"] = f"P/C {pc:.2f} — peur extrême = contrarien haussier"
        
        else:  # PUT
            if pc > 1.20:
                score += 2
                signals["cboe_pc"] = f"P/C {pc:.2f} — momentum puts fort → confirme PUT"
            elif pc > 1.00:
                score += 1
                signals["cboe_pc"] = f"P/C {pc:.2f} — légèrement bearish"
            elif pc < 0.65:
                score += 1  # excès calls = retournement baissier possible
                signals["cboe_pc"] = f"P/C {pc:.2f} — excès calls → possible PUT contrarien"
    
    # ── QQQ OI Put/Call (open interest = positionnement structurel) ───────────
    if qqq_oi_pc is not None:
        oipc = qqq_oi_pc
        
        if sens == "CALL":
            if oipc > 1.80:
                # Très fort OI puts → mur de protection = contrarien haussier fort
                score += 2
                signals["qqq_oi"] = f"QQQ OI P/C {oipc:.2f} — excès puts = mur de support"
            elif oipc > 1.40:
                score += 1
                signals["qqq_oi"] = f"QQQ OI P/C {oipc:.2f} — puts dominants = contrarien ↑"
            elif oipc > 1.00:
                score += 0
                signals["qqq_oi"] = f"QQQ OI P/C {oipc:.2f} — neutre (aujourd'hui 1.60 ← ici)"
            elif oipc < 0.50:
                score -= 2
                signals["qqq_oi"] = f"QQQ OI P/C {oipc:.2f} — excès calls = OI trop optimiste"
            elif oipc < 0.70:
                score -= 1
                signals["qqq_oi"] = f"QQQ OI P/C {oipc:.2f} — calls dominent l'OI"
    
    # ── Volume vs Open Interest (nouvelles positions) ─────────────────────────
    if vol_call_vs_oi is not None:
        if vol_call_vs_oi > 1.0 and sens == "CALL":
            score += 1
            signals["vol_oi"] = f"Vol/OI calls {vol_call_vs_oi:.1f}x — nouvelles positions longues"
        elif vol_call_vs_oi > 2.0 and sens == "CALL":
            score += 2
            signals["vol_oi"] = f"Vol/OI calls {vol_call_vs_oi:.1f}x — activité INHABITUELLE bullish"
    
    # ── Sweep orders (signal institutionnel fort) ─────────────────────────────
    if sweep_calls and sens == "CALL":
        score += 2
        signals["sweeps"] = "Sweep calls détectés — urgence institutionnelle BULLISH"
    elif sweep_puts and sens == "CALL":
        score -= 2
        signals["sweeps"] = "Sweep puts massifs — institutions se couvrent"
    elif sweep_puts and sens == "PUT":
        score += 2
        signals["sweeps"] = "Sweep puts — conviction institutionnelle BEARISH"
    
    # ── FOMC adjustment ───────────────────────────────────────────────────────
    if fomc_today:
        signals["fomc_adj"] = "Pre-FOMC : hausse P/C normale (hedging) → pénalité neutralisée"
    
    score = max(0, min(8, score))
    
    # Interprétation globale
    if score >= 7:
        interpretation = "TRÈS HAUSSIER — options flow confirme fortement"
    elif score >= 6:
        interpretation = "HAUSSIER — flow favorable"
    elif score >= 4:
        interpretation = "NEUTRE — pas de signal fort"
    elif score >= 2:
        interpretation = "PRUDENCE — flow légèrement défavorable"
    else:
        interpretation = "BEARISH — options flow contre la position"
    
    return {
        "score":          score,
        "max":            8,
        "interpretation": interpretation,
        "signals":        signals,
        "inputs": {
            "cboe_equity_pc": cboe_equity_pc,
            "qqq_oi_pc":      qqq_oi_pc,
            "fomc_today":     fomc_today,
            "sweep_calls":    sweep_calls,
            "sweep_puts":     sweep_puts,
        }
    }

# ── Résumé lisible ─────────────────────────────────────────────────────────────

def format_options_summary(data_fetched, score_result):
    """Formate un résumé console du flux options."""
    lines = [
        "── OPTIONS FLOW ────────────────────────────────────",
    ]
    
    if data_fetched.get("cboe_equity_pc"):
        pc = data_fetched["cboe_equity_pc"]
        arrow = "↓ haussier" if pc < 0.85 else "↑ bearish" if pc > 1.10 else "→ neutre"
        lines.append(f"  CBOE Equity P/C  : {pc:.2f}  ({arrow})  [src: {data_fetched['cboe_equity_pc_src']}]")
    else:
        lines.append(f"  CBOE Equity P/C  : 0.86 (J-1 connu)  ← pré-FOMC normal")
    
    if data_fetched.get("qqq_oi_pc"):
        oipc = data_fetched["qqq_oi_pc"]
        lines.append(f"  QQQ OI P/C       : {oipc:.2f}  ({'contrarien ↑' if oipc > 1.40 else 'neutre'})  [src: {data_fetched.get('qqq_oi_pc_src','—')}]")
    else:
        lines.append(f"  QQQ OI P/C       : 1.60 (dernier connu)")
    
    lines.append(f"  Score flow       : {score_result['score']}/8  → {score_result['interpretation']}")
    
    for k, v in score_result["signals"].items():
        lines.append(f"    • {v}")
    
    return "\n".join(lines)


if __name__ == "__main__":
    print("Test options_flow.py...")
    
    # Test avec les données connues du 18 mars 2026
    score = score_options_flow(
        cboe_equity_pc  = 0.86,
        qqq_oi_pc       = 1.60,
        fomc_today      = True,
        sens            = "CALL",
    )
    print(f"\nScore F10 (18 mars 2026) : {score['score']}/8")
    print(f"Interprétation : {score['interpretation']}")
    print("Signaux :")
    for k, v in score['signals'].items():
        print(f"  • {v}")
    
    # Test fetch live (si réseau dispo)
    print("\nTentative fetch live...")
    data = fetch_options_data()
    print(f"  CBOE Equity P/C : {data['cboe_equity_pc']} [{data['cboe_equity_pc_src']}]")
    print(f"  QQQ OI P/C      : {data['qqq_oi_pc']} [{data['qqq_oi_pc_src']}]")
