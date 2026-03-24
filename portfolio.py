"""
portfolio.py v2 — Mémoire portefeuille + Scoring 10 facteurs + Contexte Macro
"""
import json, os, math, sys
from datetime import datetime, date
# Options flow module (graceful fallback si indisponible)
try:
    sys.path.insert(0, os.path.dirname(__file__) or '/home/claude')
    from options_flow import score_options_flow as _score_options_flow_ext
    HAS_FLOW = True
except ImportError:
    HAS_FLOW = False

PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), "portfolio.json")

# ── Calculs turbo ────────────────────────────────────────────────────────────
def turbo_vi(sj, strike, parite, fx=1.0, sens="CALL"):
    if sens == "CALL": return max((sj - strike) / parite / fx, 0)
    return max((strike - sj) / parite / fx, 0)

def turbo_levier(sj, vi, parite, fx=1.0):
    if vi <= 0: return 0
    return round(sj / (vi * parite * fx), 1)

def turbo_pnl(prix_achat, prix_exit, nb):
    pct = (prix_exit - prix_achat) / prix_achat * 100
    eur = (prix_exit - prix_achat) * nb
    return round(pct, 1), round(eur, 0)

def ko_distance(sj, strike, sens="CALL"):
    if sens == "CALL": return round((sj - strike) / sj * 100, 1)
    return round((strike - sj) / sj * 100, 1)

# ── Facteurs v2 ──────────────────────────────────────────────────────────────
FACTEURS_V2 = {
    "momentum_technique": {"weight": 18, "desc": "RSI/MA position + structure tendance"},
    "esperance_ponderee": {"weight": 16, "desc": "E=Σ(prob×gain) pondéré"},
    "ko_niveau":          {"weight": 10, "desc": "Distance KO + support sous barrière"},
    "vix_regime":         {"weight": 8, "desc": "VIX niveau + direction delta 3j"},
    "catalyseur_grille":  {"weight": 10, "desc": "Catalyseur macro/sectoriel/micro"},
    "contexte_macro":     {"weight": 8, "desc": "DXY + yield curve + crédit + sentiment"},
    "correlation_portef": {"weight": 6, "desc": "Concentration CTO + corrélation NQ"},
    "volume_relatif":     {"weight": 6, "desc": "Volume J-1 vs moy.20j + liquidité turbo"},
    "bougie_daily":       {"weight": 8, "desc": "Bougie J-1 : Hammer/Engulfing + niveau"},
    "options_flow":       {"weight": 10, "desc": "Put/Call ratio + OI QQQ + sweep orders"},
}
FACTEURS = FACTEURS_V2  # compat v1

# ── F1 Momentum ──────────────────────────────────────────────────────────────
def _f_momentum(signal, rsi=None, au_dessus_ma20=None, au_dessus_ma50=None, higher_highs=None):
    base = {"FORT_HAUSSIER":14,"HAUSSIER":11,"NEUTRE":6,"BAISSIER":2,"FORT_BAISSIER":0}.get(signal,6)
    b = 0
    if rsi is not None:
        if 30 <= rsi < 40:   b += 3
        elif 40 <= rsi <= 60: b += 2
        elif 60 < rsi <= 70:  b += 1
        elif rsi > 70:        b -= 1
    if au_dessus_ma20 is True and au_dessus_ma50 is True: b += 2
    elif au_dessus_ma20 is True: b += 1
    elif au_dessus_ma20 is False and au_dessus_ma50 is False: b -= 1
    if higher_highs is True: b += 1
    return max(0, min(20, base + b))

# ── F2 Espérance pondérée ────────────────────────────────────────────────────
def _f_esperance(tp1, stop, tp2=None, p1=0.35, p2=0.15, ps=0.45):
    tot = p1 + p2 + ps
    if tot > 0: p1/=tot; p2/=tot; ps/=tot
    t2 = tp2 if tp2 else tp1 * 1.7
    E = p1*tp1 + p2*t2 + ps*stop
    if E >= 15: return 18
    elif E >= 10: return 15
    elif E >= 5:  return 12
    elif E >= 0:  return 8
    elif E >= -5: return 4
    return 0

# ── F3 KO niveau ─────────────────────────────────────────────────────────────
def _f_ko(dist, support_sous=None, sessions_ko=None):
    d = (9 if dist>=10 else 7 if dist>=7 else 5 if dist>=5 else 3 if dist>=3 else 1)
    b = 0
    if support_sous is True: b += 2
    elif support_sous is False: b -= 1
    if sessions_ko is not None:
        if sessions_ko == 0: b += 1
        elif sessions_ko >= 3: b -= 1
    return max(0, min(12, d + b))

# ── F4 VIX régime ─────────────────────────────────────────────────────────────
def _f_vix(vix, delta_3j=None, vix_3j_ago=None):
    if delta_3j is None and vix_3j_ago and vix_3j_ago > 0:
        delta_3j = (vix - vix_3j_ago) / vix_3j_ago * 100
    n = (6 if vix<15 else 5 if vix<20 else 4 if vix<25 else 2 if vix<30 else 1)
    d = 2
    if delta_3j is not None:
        if delta_3j <= -15: d = 4
        elif delta_3j <= -8: d = 3
        elif delta_3j <= -3: d = 2
        elif delta_3j <= +3: d = 2
        elif delta_3j <= +8: d = 1
        else: d = 0
    return max(0, min(10, n + d))

# ── F5 Catalyseur grille ─────────────────────────────────────────────────────
def _f_catalyseur(macro, sectoriel, micro, fomc=False, cpi=False):
    w = {"FORT_POSITIF":4,"POSITIF":3,"NEUTRE":2,"NEGATIF":1,"FORT_NEGATIF":0}
    s = w.get(macro,2)*1.0 + w.get(sectoriel,2)*1.0 + w.get(micro,2)*1.0
    if fomc: s -= 1.5
    if cpi:  s -= 1.0
    return max(0, min(12, round(s/12*12)))

# ── F6 Contexte macro enrichi ────────────────────────────────────────────────
def _f_macro(dxy=None, dxy_d5=None, us10y=None, us10y_d5=None,
             spread_10y_2y=None, hy_oas=None, hy_oas_d5=None,
             gold=None, gold_d5=None, fear_greed=None,
             copper_d5=None, sens="CALL"):
    score = 4
    details = {}

    # DXY — corrélation inverse NQ (source: TradingView NQ/DXY analysis 2025)
    if dxy_d5 is not None:
        if sens == "CALL":
            if dxy_d5 <= -1.5:   score+=2; details["dxy"]="DXY ↓ fort → vent arrière NQ"
            elif dxy_d5 <= -0.5: score+=1; details["dxy"]="DXY ↓ léger → favorable"
            elif dxy_d5 >= +1.5: score-=2; details["dxy"]="DXY ↑ fort → pression NQ"
            elif dxy_d5 >= +0.5: score-=1; details["dxy"]="DXY ↑ léger → défavorable"
            else:                          details["dxy"]="DXY stable → neutre"
        else:
            if dxy_d5 >= +1.5:   score+=1; details["dxy"]="DXY fort → confirme PUT"
            elif dxy_d5 <= -1.5: score-=1; details["dxy"]="DXY faible → contre PUT"

    # Taux US 10Y (pression sur valorisation tech)
    if us10y_d5 is not None:
        if sens == "CALL":
            if us10y_d5 <= -15:   score+=1; details["rates"]="Taux ↓ 15bps → favorable tech"
            elif us10y_d5 >= +20: score-=2; details["rates"]="Taux ↑ 20bps → compression PE tech"
            elif us10y_d5 >= +10: score-=1; details["rates"]="Taux ↑ → léger défavorable"
            else:                           details["rates"]="Taux stables → neutre"

    # Courbe des taux 10Y-2Y (source: YCharts yield curve 2025 — 53bps = normal)
    if spread_10y_2y is not None:
        if spread_10y_2y < -50:   score-=2; details["curve"]=f"Courbe inversée {spread_10y_2y}bps → risque récession"
        elif spread_10y_2y < 0:   score-=1; details["curve"]=f"Légère inversion {spread_10y_2y}bps"
        elif spread_10y_2y >= 50: score+=1; details["curve"]=f"Courbe saine +{spread_10y_2y}bps → expansion"
        else:                               details["curve"]=f"Courbe flat {spread_10y_2y}bps"

    # HY Credit Spread OAS (FRED BAMLH0A0HYM2 — risk appetite proxy)
    # Actuel mars 2026 : ~320bps (normal), >450 = stress
    if hy_oas is not None:
        if hy_oas < 300:   score+=1; details["credit"]=f"HY OAS {hy_oas}bps → crédit serré, risk-on"
        elif hy_oas > 500: score-=2; details["credit"]=f"HY OAS {hy_oas}bps → stress crédit!"
        elif hy_oas > 400: score-=1; details["credit"]=f"HY OAS {hy_oas}bps → spreads élargis"
        else:                         details["credit"]=f"HY OAS {hy_oas}bps → normal"
    if hy_oas_d5 is not None:
        if hy_oas_d5 <= -20:  score+=1; details["credit_dir"]="Spreads ↓ → risk-on"
        elif hy_oas_d5 >= +30: score-=1; details["credit_dir"]="Spreads ↑ → risk-off"

    # Or (refuge — or ↑ fort = risk-off)
    # Source: "Gold will always find a reason to rally in fear" — ACY Education 2025
    if gold_d5 is not None and sens == "CALL":
        if gold_d5 >= +3.0:   score-=2; details["gold"]=f"Or +{gold_d5:.1f}% → fort risk-off"
        elif gold_d5 >= +1.5: score-=1; details["gold"]=f"Or +{gold_d5:.1f}% → prudence"
        elif gold_d5 <= -1.0: score+=1; details["gold"]=f"Or {gold_d5:.1f}% → risk-on"
        else:                            details["gold"]="Or stable → neutre"

    # CNN Fear & Greed (0-100)
    # Actuel 18 mars 2026 : 22 = Extreme Fear → zone rebond pour CALL
    # Source: feargreedmeter.com — mis à jour live
    if fear_greed is not None:
        if sens == "CALL":
            if 25 <= fear_greed <= 50:   score+=2; details["fg"]=f"F&G {fear_greed} → zone rebond optimale"
            elif 51 <= fear_greed <= 65: score+=1; details["fg"]=f"F&G {fear_greed} → favorable"
            elif fear_greed < 20:        score-=1; details["fg"]=f"F&G {fear_greed} → peur extrême, attendre"
            elif fear_greed > 75:        score-=2; details["fg"]=f"F&G {fear_greed} → cupidité, risque retour"
            else:                                  details["fg"]=f"F&G {fear_greed} → neutre"
        else:
            if fear_greed < 30:  score+=2; details["fg"]=f"F&G {fear_greed} → peur confirme PUT"
            elif fear_greed > 70: score-=1; details["fg"]="Trop greed contre PUT"

    # Cuivre (indicateur croissance mondiale)
    # Source: "Copper will always find a reason to rise in hope" — ACY 2025
    if copper_d5 is not None and sens == "CALL":
        if copper_d5 >= +2.0:   score+=1; details["copper"]=f"Cu +{copper_d5:.1f}% → growth↑"
        elif copper_d5 <= -2.0: score-=1; details["copper"]=f"Cu {copper_d5:.1f}% → growth↓"

    return max(0, min(8, score)), details

# ── F7 Corrélation portefeuille ──────────────────────────────────────────────
def _f_correlation(nb_nq, correl_nq, pct_engage):
    s = 6
    if nb_nq >= 2:   s -= 3
    elif nb_nq == 1: s -= 1
    if nb_nq >= 1 and correl_nq >= 0.8: s -= 2
    if pct_engage >= 60:   s -= 2
    elif pct_engage >= 40: s -= 1
    return max(0, min(6, s))

# ── F8 Volume relatif ─────────────────────────────────────────────────────────
def _f_volume(ratio=None, spread=None, liquidite=True):
    s = 3
    if ratio is not None:
        if ratio >= 2.0:   s += 2
        elif ratio >= 1.5: s += 1
        elif ratio < 0.5:  s -= 1
    if spread is not None:
        if spread <= 1.5:   s += 1
        elif spread >= 4.0: s -= 2
        elif spread >= 2.5: s -= 1
    if not liquidite: s -= 2
    return max(0, min(6, s))

# ── F9 Bougie daily J-1 ──────────────────────────────────────────────────────
def _f_bougie(pattern, sur_niveau=False, volume_conf=False, tendance_prev=None):
    """
    Win rates backtestés (56 680 trades, TrendSpider + TradesViz 2025) :
    - Hammer/Inverted Hammer : 60% win rate
    - Bullish Engulfing + volume : 75% sur ES futures
    - Bearish Engulfing : 57%
    RÈGLE : pattern hors niveau technique = -3pts (confluence obligatoire)
    """
    BULL = {"HAMMER":6,"INVERTED_HAMMER":6,"BULLISH_ENGULFING":7,
            "BULLISH_MARUBOZU":5,"MORNING_STAR":7,"DRAGONFLY_DOJI":5,
            "THREE_WHITE_SOLDIERS":8,"PIERCING":5}
    BEAR = {"SHOOTING_STAR":6,"BEARISH_ENGULFING":6,"EVENING_STAR":7,
            "GRAVESTONE_DOJI":5,"BEARISH_MARUBOZU":5,"THREE_BLACK_CROWS":7}
    NEUT = {"DOJI":3,"SPINNING_TOP":3,"INSIDE_BAR":4}

    if pattern is None: return 2
    base = BULL.get(pattern) or BEAR.get(pattern) or NEUT.get(pattern) or 3

    if not sur_niveau: base = max(1, base - 3)  # pénalité critique hors niveau
    if volume_conf and sur_niveau: base = min(8, base + 1)
    if tendance_prev == "BAISSIER" and pattern in BULL: base = min(8, base + 1)
    elif tendance_prev == "HAUSSIER" and pattern in BEAR: base = min(8, base + 1)
    elif tendance_prev == "HAUSSIER" and pattern in BULL: base = max(0, base - 1)

    return max(0, min(8, base))


# ── F10 Options Flow (0-8) ────────────────────────────────────────────────────
def _f_options_flow(cboe_equity_pc=None, qqq_oi_pc=None, cboe_total_pc=None,
                    vol_call_vs_oi=None, sweep_calls=False, sweep_puts=False,
                    fomc_today=False, sens="CALL"):
    """
    P/C Ratio CBOE Equity J-1 + QQQ OI P/C + sweeps institutionnels.
    Sources: ycharts.com (CBOE), fintel.io (QQQ OI)
    Valeurs 18 mars 2026: CBOE Equity P/C=0.86, QQQ OI P/C=1.60
    """
    if HAS_FLOW:
        r = _score_options_flow_ext(
            cboe_equity_pc=cboe_equity_pc, qqq_oi_pc=qqq_oi_pc,
            cboe_total_pc=cboe_total_pc, vol_call_vs_oi=vol_call_vs_oi,
            sweep_calls=sweep_calls, sweep_puts=sweep_puts,
            fomc_today=fomc_today, sens=sens)
        return r["score"], r["signals"]
    # Fallback intégré si module absent
    score = 4
    sigs  = {}
    if cboe_equity_pc is not None:
        pc = cboe_equity_pc
        if sens == "CALL":
            if   pc < 0.55:   score += 1;  sigs["pc"] = f"P/C {pc:.2f} — calls dominent (suroptimisme)"
            elif pc < 0.70:   score += 2;  sigs["pc"] = f"P/C {pc:.2f} — haussier fort"
            elif pc < 0.86:   score += 1;  sigs["pc"] = f"P/C {pc:.2f} — légèrement haussier"
            elif pc <= 1.00:
                if fomc_today: sigs["pc"] = f"P/C {pc:.2f} — neutre (pre-FOMC normal)"
                else:          sigs["pc"] = f"P/C {pc:.2f} — neutre"
            elif pc <= 1.20:  score -= 1;  sigs["pc"] = f"P/C {pc:.2f} — couverture institutionnelle"
            elif pc <= 1.50:  score -= 2;  sigs["pc"] = f"P/C {pc:.2f} — fort hedging"
            else:              score += 1;  sigs["pc"] = f"P/C {pc:.2f} — peur extrême = contrarien ↑"
        else:
            if   pc > 1.20:   score += 2;  sigs["pc"] = f"P/C {pc:.2f} — momentum puts"
            elif pc > 1.00:   score += 1;  sigs["pc"] = f"P/C {pc:.2f} — légèrement bearish"
            elif pc < 0.65:   score += 1;  sigs["pc"] = f"P/C {pc:.2f} — excès calls = PUT contrarien"
    if qqq_oi_pc is not None:
        oipc = qqq_oi_pc
        if sens == "CALL":
            if   oipc > 1.80: score += 2;  sigs["oi"] = f"QQQ OI P/C {oipc:.2f} — mur puts = support"
            elif oipc > 1.40: score += 1;  sigs["oi"] = f"QQQ OI P/C {oipc:.2f} — contrarien ↑"
            elif oipc < 0.50: score -= 2;  sigs["oi"] = f"QQQ OI P/C {oipc:.2f} — excès calls dangereux"
            elif oipc < 0.70: score -= 1;  sigs["oi"] = f"QQQ OI P/C {oipc:.2f} — calls dominent OI"
            else:                          sigs["oi"] = f"QQQ OI P/C {oipc:.2f} — neutre"
    if sweep_calls and sens == "CALL":   score += 2; sigs["sw"] = "Sweeps calls — urgence institutionnelle bullish"
    elif sweep_puts and sens == "CALL":  score -= 2; sigs["sw"] = "Sweeps puts — institutions se couvrent"
    elif sweep_puts and sens == "PUT":   score += 2; sigs["sw"] = "Sweeps puts — conviction bearish"
    if fomc_today: sigs["fomc"] = "Pre-FOMC : hedging P/C normalisé"
    return max(0, min(8, score)), sigs

# ══════════════════════════════════════════════════════════════════════════════
# SCORE PRINCIPAL v2
# ══════════════════════════════════════════════════════════════════════════════
def score_setup_v2(
    # F1
    signal_technique, rsi=None, au_dessus_ma20=None, au_dessus_ma50=None, higher_highs=None,
    # F2
    tp1_pct=40.0, stop_pct=-40.0, tp2_pct=None, prob_tp1=0.35, prob_tp2=0.15, prob_stop=0.45,
    # F3
    ko_dist_pct=5.0, support_sous_ko=None, nb_sessions_ko=None,
    # F4
    vix=22.0, vix_delta_3j=None, vix_3j_ago=None,
    # F5
    catalyseur_macro="NEUTRE", catalyseur_sectoriel="NEUTRE", catalyseur_micro="NEUTRE",
    fomc_risk=False, cpi_risk=False,
    # F6 — MACRO ENRICHI
    dxy=None, dxy_delta_5j=None,
    us10y=None, us10y_delta_5j=None,
    spread_10y_2y=None,
    hy_oas=None, hy_oas_delta_5j=None,
    gold=None, gold_delta_5j=None,
    fear_greed=None,
    copper_delta_5j=None,
    # F7
    nb_positions_nq=0, actif_correl_nq=0.5, pct_cto_engage=25.0,
    # F8
    volume_ratio=None, spread_pct=None, liquidite_ok=True,
    # F9
    bougie_pattern=None, bougie_sur_niveau=False,
    bougie_volume_conf=False, bougie_tendance_prev=None,
    # F10 — Options Flow
    cboe_equity_pc=None,   # CBOE Equity P/C ratio J-1 (ex: 0.86)
    qqq_oi_pc=None,        # QQQ Open Interest P/C (ex: 1.60)
    cboe_total_pc=None,    # CBOE Total P/C (ex: 0.90)
    vol_call_vs_oi=None,   # Volume calls / OI calls
    sweep_calls=False,     # Sweep orders calls institutionnels détectés
    sweep_puts=False,      # Sweep orders puts institutionnels détectés
    # Meta
    sens="CALL", actif_label="",
):
    f = {}
    f["momentum_technique"] = _f_momentum(signal_technique, rsi, au_dessus_ma20, au_dessus_ma50, higher_highs)
    f["esperance_ponderee"] = _f_esperance(tp1_pct, stop_pct, tp2_pct, prob_tp1, prob_tp2, prob_stop)
    f["ko_niveau"]          = _f_ko(ko_dist_pct, support_sous_ko, nb_sessions_ko)
    f["vix_regime"]         = _f_vix(vix, vix_delta_3j, vix_3j_ago)
    f["catalyseur_grille"]  = _f_catalyseur(catalyseur_macro, catalyseur_sectoriel, catalyseur_micro, fomc_risk, cpi_risk)
    macro_s, macro_d         = _f_macro(dxy, dxy_delta_5j, us10y, us10y_delta_5j, spread_10y_2y,
                                         hy_oas, hy_oas_delta_5j, gold, gold_delta_5j, fear_greed, copper_delta_5j, sens)
    f["contexte_macro"]     = macro_s
    f["correlation_portef"] = _f_correlation(nb_positions_nq, actif_correl_nq, pct_cto_engage)
    f["volume_relatif"]     = _f_volume(volume_ratio, spread_pct, liquidite_ok)
    f["bougie_daily"]       = _f_bougie(bougie_pattern, bougie_sur_niveau, bougie_volume_conf, bougie_tendance_prev)
    flow_score, flow_sigs   = _f_options_flow(cboe_equity_pc, qqq_oi_pc, cboe_total_pc,
                                              vol_call_vs_oi, sweep_calls, sweep_puts,
                                              fomc_today=fomc_risk, sens=sens)
    f["options_flow"]       = flow_score

    total = sum(f.values())
    conv  = ("MAXIMALE" if total>=75 else "FORTE" if total>=62 else
             "MODÉRÉE" if total>=48 else "FAIBLE" if total>=35 else "ÉVITER")
    reco  = _reco_v2(conv, fomc_risk, pct_cto_engage)

    detail = {k: {"score":v,"max":FACTEURS_V2[k]["weight"],
                  "pct":round(v/FACTEURS_V2[k]["weight"]*100),
                  "desc":FACTEURS_V2[k]["desc"]} for k,v in f.items()}

    return {
        "version":"v2", "actif":actif_label, "sens":sens,
        "score":total, "conviction":conv,
        "facteurs":f, "detail":detail,
        "macro_details":macro_d,
        "flow_signals":flow_sigs,
        "recommandation":reco,
        "date":str(date.today()),
        "datetime":datetime.now().strftime("%Y-%m-%d %H:%M"),
        "inputs":{
            "signal":signal_technique, "vix":vix, "vix_delta_3j":vix_delta_3j,
            "ko_dist_pct":ko_dist_pct, "bougie":bougie_pattern,
            "bougie_sur_niveau":bougie_sur_niveau,
            "dxy_delta_5j":dxy_delta_5j, "us10y":us10y,
            "us10y_delta_5j":us10y_delta_5j, "fear_greed":fear_greed,
            "hy_oas":hy_oas, "spread_10y_2y":spread_10y_2y,
            "gold_delta_5j":gold_delta_5j, "fomc_risk":fomc_risk,
            "cboe_equity_pc":cboe_equity_pc,"qqq_oi_pc":qqq_oi_pc,
            "sweep_calls":sweep_calls,"sweep_puts":sweep_puts,
        }
    }

def _reco_v2(conv, fomc, pct_engage):
    r = {"MAXIMALE":"ENTRER — setup excellent. Taille normale 15-20% CTO.",
         "FORTE":   "ENTRER — bon setup. Taille 10-15% CTO.",
         "MODÉRÉE": "ATTENDRE confirmation. Taille max 5-8% si conviction persiste.",
         "FAIBLE":  "PASSER — conditions insuffisantes.",
         "ÉVITER":  "NE PAS TRADER — conditions défavorables."}[conv]
    if fomc and conv in ("MAXIMALE","FORTE"):
        r += " ⚠ FOMC ce soir → réduire taille -30% et clore avant 18h15."
    if pct_engage >= 50:
        r += " ⚠ CTO >50% engagé → n'ajouter que si score ≥70."
    return r

# ── Wrapper v1 (compatibilité) ───────────────────────────────────────────────
def score_setup(signal_technique, tp1_pct, stop_pct, ko_dist_pct, vix,
                catalyseur, deja_long_nq, spread_ok=True, volume_ok=True):
    return score_setup_v2(
        signal_technique=signal_technique, tp1_pct=tp1_pct, stop_pct=stop_pct,
        ko_dist_pct=ko_dist_pct, vix=vix,
        catalyseur_micro=catalyseur,
        nb_positions_nq=1 if deja_long_nq else 0,
        actif_correl_nq=0.9 if deja_long_nq else 0.5,
        pct_cto_engage=30.0, liquidite_ok=spread_ok and volume_ok,
    )

# ── Schéma position ───────────────────────────────────────────────────────────
def _empty_position(isin, label, sens, sous_jacent, nb, prix_achat,
                    strike, parite, devise, eurusd, sj_entree, heure_achat, emetteur="SG"):
    return {
        "isin":isin,"label":label,"emetteur":emetteur,"sous_jacent":sous_jacent,
        "sens":sens,"statut":"OUVERT","nb_titres":nb,"prix_achat":prix_achat,
        "mise":round(nb*prix_achat,2),"strike":strike,"parite":parite,
        "devise":devise,"eurusd":eurusd,"sj_entree":sj_entree,
        "heure_achat":heure_achat,"date_achat":str(date.today()),
        "prix_cloture":None,"sj_cloture":None,"heure_cloture":None,
        "date_cloture":None,"pnl_eur":None,"pnl_pct":None,"raison_cloture":None,
    }

# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO CLASS
# ══════════════════════════════════════════════════════════════════════════════
class Portfolio:
    def __init__(self, filepath=PORTFOLIO_FILE):
        self.filepath = filepath; self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            with open(self.filepath, encoding="utf-8") as f: self.data = json.load(f)
        else:
            self.data = {"created":str(date.today()),"updated":str(date.today()),
                         "positions":[],"historique":[],
                         "stats":{"total_trades":0,"trades_gagnants":0,"trades_perdants":0,
                                  "pnl_total_eur":0.0,"win_rate":0.0,"pnl_moyen_eur":0.0,
                                  "meilleur_trade":None,"pire_trade":None},
                         "scores_history":[]}

    def save(self):
        self.data["updated"] = str(date.today())
        self._recalc_stats()
        with open(self.filepath,"w",encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        print(f"Portfolio sauvegardé → {self.filepath}")

    def open_position(self, isin, label, sens, sous_jacent, nb, prix_achat,
                      strike, parite, devise, eurusd, sj_entree, heure_achat, emetteur="SG"):
        pos = _empty_position(isin,label,sens,sous_jacent,nb,prix_achat,
                               strike,parite,devise,eurusd,sj_entree,heure_achat,emetteur)
        self.data["positions"].append(pos); self.save()
        print(f"Position ouverte : {label} ({nb}T × {prix_achat}€ = {pos['mise']}€)")
        return pos

    def close_position(self, isin, prix_cloture, sj_cloture, heure_cloture, raison="Manuel"):
        pos = self._find_open(isin)
        if not pos: print(f"Position {isin} non trouvée"); return None
        pct, eur = turbo_pnl(pos["prix_achat"], prix_cloture, pos["nb_titres"])
        pos.update({"statut":"CLÔTURÉ","prix_cloture":prix_cloture,"sj_cloture":sj_cloture,
                    "heure_cloture":heure_cloture,"date_cloture":str(date.today()),
                    "pnl_eur":eur,"pnl_pct":pct,"raison_cloture":raison})
        self.data["historique"].append(dict(pos)); self.save()
        print(f"Position clôturée : {pos['label']} → {pct:+.1f}% / {eur:+.0f}€ ({raison})")
        return pos

    def get_open_positions(self): return [p for p in self.data["positions"] if p["statut"]=="OUVERT"]

    def pnl_live(self, isin, sj_actuel, prix_turbo_actuel=None):
        pos = self._find_open(isin)
        if not pos: return None
        fx = pos["eurusd"] if pos["devise"]=="USD" else 1.0
        vi = turbo_vi(sj_actuel, pos["strike"], pos["parite"], fx, pos["sens"])
        prix_ref = prix_turbo_actuel if prix_turbo_actuel else vi
        pct, eur = turbo_pnl(pos["prix_achat"], prix_ref, pos["nb_titres"])
        return {"isin":isin,"label":pos["label"],"sj_actuel":sj_actuel,
                "vi_theorique":round(vi,4),"pnl_pct":pct,"pnl_eur":eur,
                "ko_dist_pct":ko_distance(sj_actuel,pos["strike"],pos["sens"]),"mise":pos["mise"]}

    def _find_open(self, isin):
        for p in self.data["positions"]:
            if p["isin"]==isin and p["statut"]=="OUVERT": return p
        return None

    def score_and_save(self, actif_label, **kwargs):
        result = score_setup_v2(actif_label=actif_label, **kwargs)
        self.data["scores_history"].append(result); self.save(); return result

    def _recalc_stats(self):
        closed = [p for p in self.data["positions"] if p["statut"]=="CLÔTURÉ" and p["pnl_eur"] is not None]
        if not closed: return
        gains = [p for p in closed if p["pnl_eur"]>0]
        t = sum(p["pnl_eur"] for p in closed); s = self.data["stats"]
        s["total_trades"]=len(closed); s["trades_gagnants"]=len(gains)
        s["trades_perdants"]=len(closed)-len(gains); s["pnl_total_eur"]=round(t,0)
        s["win_rate"]=round(len(gains)/len(closed)*100,1); s["pnl_moyen_eur"]=round(t/len(closed),0)
        if closed:
            s["meilleur_trade"]=max(closed,key=lambda x:x["pnl_eur"])["label"]
            s["pire_trade"]=min(closed,key=lambda x:x["pnl_eur"])["label"]

    def print_summary(self):
        opens = self.get_open_positions(); s = self.data["stats"]
        print(f"\n{'='*60}\nPORTFOLIO v2 — {self.data['updated']}\n{'='*60}")
        for p in opens: print(f"  [{p['sens']}] {p['label']} — {p['nb_titres']}T × {p['prix_achat']}€ = {p['mise']}€")
        print(f"\nTrades : {s['total_trades']} | WR: {s['win_rate']}% | P&L: {s['pnl_total_eur']:+.0f}€\n{'='*60}")
