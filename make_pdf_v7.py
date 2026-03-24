import os as _os
_BASE = _os.path.dirname(_os.path.abspath(__file__))

"""
make_pdf_v7.py — One-pager action plan + annexes
Layout: PAGE 1 = tout ce qui compte (positions + plan + scores + niveaux)
        PAGE 2 = annexes (macro, options flow, FOMC, PEA)
Philosophie: monochrome, typographie serrée, densité maximale
"""
import json, sys, os
pass  # sys.path handled by _BASE_PDF below
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable, PageBreak)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from portfolio import score_setup_v2, FACTEURS_V2

_BASE_PDF = _os.path.dirname(_os.path.abspath(__file__))
import sys as _sys
if _BASE_PDF not in _sys.path:
    _sys.path.insert(0, _BASE_PDF)
with open(_os.path.join(_BASE_PDF, "report_data.json"), encoding="utf-8") as f:
    r = json.load(f)

# ── Palette minimaliste ───────────────────────────────────────────────────────
INK  = colors.HexColor("#0F0F0F")   # quasi-noir
INK2 = colors.HexColor("#3A3A3A")
INK3 = colors.HexColor("#6A6A6A")
INK4 = colors.HexColor("#A0A0A0")
RULE = colors.HexColor("#D8D8D8")
RULE2= colors.HexColor("#EBEBEB")
W_BG = colors.HexColor("#FAFAFA")   # fond très léger
# Seulement 3 couleurs d'accent — utilisées avec parcimonie
G    = colors.HexColor("#1A5C2E")   # vert seulement pour gains confirmés
R    = colors.HexColor("#8B1A1A")   # rouge seulement pour stops/KO
A    = colors.HexColor("#7A4F0A")   # ambre seulement pour alertes
WHITE= colors.white

# ── Marges ultra-serrées ───────────────────────────────────────────────────────
doc = SimpleDocTemplate(
    "/mnt/user-data/outputs/reco_18mars_FOMC.pdf",
    pagesize=A4,
    leftMargin=8*mm, rightMargin=8*mm,
    topMargin=7*mm, bottomMargin=7*mm,
    title=f"Turbo Brief — {r['date']}",
)
W  = A4[0] - 16*mm
PH = A4[1] - 14*mm   # page height disponible

# ── Helpers typographie ───────────────────────────────────────────────────────
def S(sz=7, color=INK, bold=False, align=TA_LEFT, sp=0, leading=None):
    return ParagraphStyle("_",
        fontSize=sz, textColor=color,
        fontName="Helvetica-Bold" if bold else "Helvetica",
        alignment=align, spaceAfter=sp,
        leading=leading or max(sz * 1.25, sz + 1.5))

def P(t, **kw):   return Paragraph(str(t), S(**kw))
def SP(h=2):      return Spacer(1, h)
def HR(t=0.3, c=RULE): return HRFlowable(width="100%", thickness=t, color=c, spaceAfter=2, spaceBefore=2)

# ── Section label : ligne fine + texte majuscule ──────────────────────────────
def SEC(title, accent=INK3, w=None):
    return Table([[P(title.upper(), sz=6, color=accent, bold=True, sp=0)]],
        colWidths=[w or W],
        style=[("LINEBELOW",(0,0),(0,0),0.4,RULE),
               ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),2)])

# ── Tableau standard avec style épuré ─────────────────────────────────────────
def T(data, cols, hdr_bg=W_BG, row_alt=True, pad=3, extra=None):
    t = Table(data, colWidths=cols)
    style = [
        ("FONTSIZE",(0,0),(-1,-1),6.5),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,0),(-1,0),INK3),
        ("BACKGROUND",(0,0),(-1,0),hdr_bg),
        ("LINEBELOW",(0,0),(-1,0),0.4,RULE),
        ("BOX",(0,0),(-1,-1),0.4,RULE),
        ("INNERGRID",(0,0),(-1,-1),0.2,RULE2),
        ("TOPPADDING",(0,0),(-1,-1),pad),
        ("BOTTOMPADDING",(0,0),(-1,-1),pad),
        ("LEFTPADDING",(0,0),(-1,-1),4),
        ("RIGHTPADDING",(0,0),(-1,-1),4),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]
    if row_alt:
        style += [("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE, W_BG])]
    if extra:
        style += extra
    t.setStyle(TableStyle(style))
    return t

story = []

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — ONE-PAGER COMPLET
# ══════════════════════════════════════════════════════════════════════════════

# ── MASTHEAD compact ─────────────────────────────────────────────────────────
mast = Table([[
    P("<b>TURBO BRIEF</b>", sz=11, bold=True, color=INK),
    P(f"Day Trading · Paris", sz=7, color=INK3),
    P(f"{r['date']}  ·  {r.get('heure','09h00')} CET  ·  Turbos 8h30–18h30", sz=6.5, color=INK4, align=TA_RIGHT),
]], colWidths=[W*0.22, W*0.30, W*0.48])
mast.setStyle(TableStyle([
    ("LINEBELOW",(0,0),(-1,0),1.2,INK),
    ("TOPPADDING",(0,0),(-1,-1),0), ("BOTTOMPADDING",(0,0),(-1,-1),3),
    ("VALIGN",(0,0),(-1,-1),"BOTTOM"),
]))
story += [mast, SP(4)]

# ── BLOC 1 : KPIs + Signal sur une ligne ─────────────────────────────────────
cto = r["cto_recap"]
engage = max(cto["total_engage"], 1)
pnl_tp1 = cto.get("gain_potentiel_tp1", 0)
pnl_stop= cto.get("perte_max_stop", 0)
pnl_live= r.get("pnl_live_total", 0)

kpi = Table([[
    # KPIs CTO
    P(f'<b>{cto["total_engage"]:.0f}€</b>', sz=11, bold=True, color=INK, align=TA_CENTER),
    P(f'<b>{cto["reserve_dispo"]:.0f}€</b>', sz=11, bold=True, color=G, align=TA_CENTER),
    P(f'<b>{pnl_live:+.0f}€</b>', sz=11, bold=True,
      color=G if pnl_live >= 0 else R, align=TA_CENTER),
    P(f'<b>+{pnl_tp1:.0f}€</b>', sz=11, bold=True, color=G, align=TA_CENTER),
    P(f'<b>{pnl_stop:.0f}€</b>', sz=11, bold=True, color=R, align=TA_CENTER),
    # Signal + marchés
    P(f'<b>{r.get("signal","NEUTRE")}</b>', sz=9, bold=True, color=A, align=TA_CENTER),
    P(f'<b>NQ {r.get("nasdaq_current",25112):,}</b>'.replace(",","'"), sz=9, bold=True, color=INK, align=TA_CENTER),
    P(f'<b>VIX {r["additional_kpis"].get("vix",22.37)}</b>', sz=9, bold=True, color=INK2, align=TA_CENTER),
    P('<b>FOMC Hold 96%</b>', sz=9, bold=True, color=G, align=TA_CENTER),
],[
    P("Engagé CTO", sz=5.5, color=INK4, align=TA_CENTER),
    P("Réserve", sz=5.5, color=INK4, align=TA_CENTER),
    P("P&L live", sz=5.5, color=INK4, align=TA_CENTER),
    P("Gain si TP1", sz=5.5, color=INK4, align=TA_CENTER),
    P("Perte max SL", sz=5.5, color=INK4, align=TA_CENTER),
    P("Signal", sz=5.5, color=INK4, align=TA_CENTER),
    P("NQ Futures", sz=5.5, color=INK4, align=TA_CENTER),
    P("VIX", sz=5.5, color=INK4, align=TA_CENTER),
    P("FOMC 20h ET", sz=5.5, color=INK4, align=TA_CENTER),
]], colWidths=[W/9]*9)
kpi.setStyle(TableStyle([
    ("BOX",(0,0),(-1,-1),0.4,RULE),
    ("INNERGRID",(0,0),(-1,-1),0.2,RULE2),
    ("LINEAFTER",(4,0),(4,-1),0.8,RULE),   # séparateur CTO / marchés
    ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),3),
    ("LEFTPADDING",(0,0),(-1,-1),3), ("RIGHTPADDING",(0,0),(-1,-1),3),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("BACKGROUND",(0,0),(-1,-1),W_BG),
]))
story += [kpi, SP(5)]

# ── BLOC 2 : Positions (compact, 2 colonnes) ─────────────────────────────────
story.append(SEC("Positions ouvertes"))
story.append(SP(2))

positions = r.get("positions_ouvertes", [])
if not positions:
    story.append(P("Aucune position ouverte.", sz=7, color=INK3))
else:
    # Une ligne par position, tout sur une seule rangée compacte
    pos_hdr = [P(h, sz=6, color=INK3, bold=True, align=c) for h, c in [
        ("ACTIF", TA_LEFT), ("ISIN", TA_LEFT), ("ENTRÉE SJ", TA_CENTER),
        ("NB×PRIX", TA_CENTER), ("MISE", TA_CENTER), ("×LEV", TA_CENTER),
        ("KO DIST", TA_CENTER), ("SJ LIVE", TA_CENTER),
        ("P&L%", TA_CENTER), ("P&L€", TA_CENTER),
        ("STOP TURBO", TA_CENTER), ("TP1 TURBO", TA_CENTER), ("TP2 TURBO", TA_CENTER),
    ]]
    pos_rows = [pos_hdr]
    pos_extras = [("BACKGROUND",(0,0),(-1,0),W_BG)]

    for i, pos in enumerate(positions, 1):
        mise = pos["nb_titres"] * pos["prix_achat"]
        pnl_pct = pos.get("pnl_live_pct") or 0
        pnl_eur = pos.get("pnl_live_eur") or 0
        ko_d    = pos.get("ko_dist_live") or pos.get("ko_dist_pct") or 0
        sj_live = pos.get("sj_live") or pos.get("sj_entree") or 0

        pc = G if pnl_pct >= 0 else R
        kc = R if ko_d < 5 else A if ko_d < 8 else INK2

        pos_rows.append([
            P(f'<b>{pos["label"][:22]}</b>', sz=6.5, bold=True, color=G if pos["sens"]=="CALL" else R),
            P(pos["isin"][-10:], sz=5.5, color=INK4),
            P(f'{pos["sj_entree"]:,.0f}'.replace(",","'"), sz=6.5, color=INK2, align=TA_CENTER),
            P(f'{pos["nb_titres"]}×{pos["prix_achat"]:.2f}€', sz=6.5, color=INK2, align=TA_CENTER),
            P(f'<b>{mise:.0f}€</b>', sz=6.5, bold=True, color=INK, align=TA_CENTER),
            P(f'<b>×{pos.get("levier","—")}</b>', sz=6.5, bold=True, color=A, align=TA_CENTER),
            P(f'<b>−{ko_d:.1f}%</b>', sz=6.5, bold=True, color=kc, align=TA_CENTER),
            P(f'{sj_live:,.0f}'.replace(",","'"), sz=6.5, color=INK2, align=TA_CENTER),
            P(f'<b>{pnl_pct:+.1f}%</b>', sz=6.5, bold=True, color=pc, align=TA_CENTER),
            P(f'<b>{pnl_eur:+.0f}€</b>', sz=6.5, bold=True, color=pc, align=TA_CENTER),
            P(f'{pos.get("stop_turbo",0):.3f}€', sz=6.5, color=R, align=TA_CENTER),
            P(f'{pos.get("tp1_turbo",0):.3f}€', sz=6.5, color=G, align=TA_CENTER),
            P(f'{pos.get("tp2_turbo",0):.3f}€', sz=6.5, color=G, align=TA_CENTER),
        ])

    pos_t = T(pos_rows,
        [W*0.16, W*0.08, W*0.08, W*0.08, W*0.06, W*0.05,
         W*0.07, W*0.07, W*0.06, W*0.06, W*0.08, W*0.08, W*0.07],
        pad=3)  # sum = 1.00
    # Highlight via extra style commands at table creation time is handled in T() base style
    story += [pos_t, SP(5)]

# ── BLOC 3 : Plan d'action (tableau ultra-compact) ───────────────────────────
story.append(SEC("Plan d'action — 18 mars 2026", A))
story.append(SP(2))

FX=1.1534; NQ_E=24470; NQ_S=23997.58; NQ_P=100
HO_E=248.0; HO_S=236.5995; HO_P=10

def vi(sj, st, par, fx=1.0): return max((sj-st)/par/fx, 0)
def pnl_c(sj, st, tp, par, fx=1.0, mise=1000):
    ve = vi(sj,st,par,fx); vx = vi(tp,st,par,fx)
    if ve<=0: return 0,0
    pct=(vx-ve)/ve*100; return round(pct,0), round(mise*pct/100,0)

p1,e1 = pnl_c(NQ_E,NQ_S,25200,NQ_P,FX,1302)
p2,e2 = pnl_c(NQ_E,NQ_S,25478,NQ_P,FX,1302)
t1,f1 = pnl_c(HO_E,HO_S,260,HO_P,1,1067)
t2,f2 = pnl_c(HO_E,HO_S,264.4,HO_P,1,1067)

plan_data = [
    # Header
    [P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
        ("HEURE",TA_CENTER),("TRADE",TA_LEFT),("SJ ENTRÉE",TA_CENTER),
        ("STOP SJ",TA_CENTER),("TP1 SJ",TA_CENTER),("TP2 SJ",TA_CENTER),
        ("MISE",TA_CENTER),("P&L TP1",TA_CENTER),("P&L TP2",TA_CENTER),
        ("P&L STOP",TA_CENTER),("STATUT",TA_CENTER),
    ]],
    # NQ
    [P("OUVERT\n09h10",sz=6,bold=True,color=G,align=TA_CENTER),
     P("<b>CALL NQ ×22</b>  DE000FD0H2Z3  ·  150T×8,68€",sz=6.5,color=INK),
     P("24 470",sz=7,bold=True,color=INK2,align=TA_CENTER),
     P("24 800\n(stop −40%)",sz=6,color=R,align=TA_CENTER),
     P("25 200",sz=7,bold=True,color=G,align=TA_CENTER),
     P("25 478",sz=7,bold=True,color=G,align=TA_CENTER),
     P("1 302€",sz=7,bold=True,align=TA_CENTER),
     P(f"+{p1:.0f}%\n+{e1}€",sz=6.5,bold=True,color=G,align=TA_CENTER),
     P(f"+{p2:.0f}%\n+{e2}€",sz=6.5,bold=True,color=G,align=TA_CENTER),
     P("−40%\n−521€",sz=6.5,color=R,align=TA_CENTER),
     P("STOP −58% / −492€ → DÉCISION",sz=6,bold=True,color=R,align=TA_CENTER)],
    # Thales
    [P("KO\nCE MATIN",sz=6,bold=True,color=R,align=TA_CENTER),
     P("<b>CALL Thales ×13</b>  TALES236.7  ·  550T×1,94€  — KO franchi",sz=6.5,color=R),
     P("248€",sz=7,bold=True,color=G,align=TA_CENTER),
     P("248€\n(stop −40%)",sz=6,color=R,align=TA_CENTER),
     P("260€",sz=7,bold=True,color=G,align=TA_CENTER),
     P("264€",sz=7,bold=True,color=G,align=TA_CENTER),
     P("1 067€",sz=7,bold=True,align=TA_CENTER),
     P(f"+{t1:.0f}%\n+{f1}€",sz=6.5,bold=True,color=G,align=TA_CENTER),
     P(f"+{t2:.0f}%\n+{f2}€",sz=6.5,bold=True,color=G,align=TA_CENTER),
     P("−40%\n−427€",sz=6.5,color=R,align=TA_CENTER),
     P("KO — résiduel ~7€ → VENDRE",sz=6,bold=True,color=R,align=TA_CENTER)],
    # 18h15
    [P("DÉCISION\nURGENTE",sz=6,bold=True,color=R,align=TA_CENTER),
     P("🚨 <b>PUT NQ stop −40% atteint (−58%)</b> — Vendre OU garder si NQ < 24 500. Iran dénie talks. KO dist 1.6%.",sz=6.5,color=R),
     *[P("—",sz=6,color=INK4,align=TA_CENTER)]*9],
    # Demain
    [P("MAINTENANT",sz=6,bold=True,color=G,align=TA_CENTER),
     P("<b>CALL Thales +56% → vendre 50% maintenant</b>  |  Garder 50% stop 0.430€  |  PUT NQ : observer Iran avant nouveau trade",sz=6.5,color=G),
     *[P("—",sz=6,color=INK4,align=TA_CENTER)]*9],
]

plan_t = Table(plan_data, colWidths=[
    W*0.07, W*0.24, W*0.07, W*0.08, W*0.07, W*0.07,
    W*0.07, W*0.08, W*0.08, W*0.08, W*0.09])
plan_t.setStyle(TableStyle([
    ("FONTSIZE",(0,0),(-1,-1),6.5),
    ("BOX",(0,0),(-1,-1),0.4,RULE),
    ("INNERGRID",(0,0),(-1,-1),0.2,RULE2),
    ("BACKGROUND",(0,0),(-1,0),W_BG),
    ("LINEBELOW",(0,0),(-1,0),0.4,RULE),
    ("ROWBACKGROUNDS",(0,1),(-1,3),[WHITE, W_BG]),
    ("BACKGROUND",(0,3),(-1,3),colors.HexColor("#FFF4F4")),
    ("BACKGROUND",(0,4),(-1,4),colors.HexColor("#FFFBF0")),
    ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
    ("LEFTPADDING",(0,0),(-1,-1),4), ("RIGHTPADDING",(0,0),(-1,-1),4),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
]))
story += [plan_t, SP(5)]

# ── BLOC 4 : Scoring + Niveaux côte à côte ───────────────────────────────────
scores_data = r.get("scores_opportunites", [])[:5]

# Calculer scores v2 avec options flow
flow_data = r.get("options_flow", {})
cboe_pc = flow_data.get("cboe_equity_pc", 0.86)
qqq_oi  = flow_data.get("qqq_oi_pc", 1.60)

MACRO_ARGS = dict(
    vix=r["additional_kpis"].get("vix",22.37), vix_delta_3j=-17.7,
    dxy_delta_5j=-2.1, us10y=4.20, us10y_delta_5j=-8, spread_10y_2y=53,
    hy_oas=320, hy_oas_delta_5j=-15, gold_delta_5j=-0.5,
    fear_greed=22, copper_delta_5j=1.2,
    cboe_equity_pc=cboe_pc, qqq_oi_pc=qqq_oi, fomc_risk=True,
)

sc_configs = [
    ("CALL NQ ×22", "DE000FD0H2Z3", True,
     dict(sens="CALL", signal_technique="HAUSSIER", rsi=54, au_dessus_ma20=True, au_dessus_ma50=True,
          tp1_pct=38.5, stop_pct=-40.0, tp2_pct=70.6, prob_tp1=0.40, prob_tp2=0.20, prob_stop=0.40,
          ko_dist_pct=4.4, support_sous_ko=False,
          catalyseur_macro="POSITIF", catalyseur_sectoriel="POSITIF", catalyseur_micro="NEUTRE",
          nb_positions_nq=0, actif_correl_nq=1.0, pct_cto_engage=13.7,
          volume_ratio=1.4, spread_pct=2.0, liquidite_ok=True,
          bougie_pattern="HAMMER", bougie_sur_niveau=True, bougie_tendance_prev="BAISSIER")),
    ("CALL Thales ×13", "DE000FE1ZS87", True,
     dict(sens="CALL", signal_technique="HAUSSIER", rsi=61, au_dessus_ma20=True, au_dessus_ma50=True,
          tp1_pct=43.3, stop_pct=-40.0, tp2_pct=82.0, prob_tp1=0.45, prob_tp2=0.20, prob_stop=0.35,
          ko_dist_pct=7.6, support_sous_ko=True,
          catalyseur_macro="POSITIF", catalyseur_sectoriel="FORT_POSITIF", catalyseur_micro="POSITIF",
          nb_positions_nq=1, actif_correl_nq=0.45, pct_cto_engage=24.9,
          volume_ratio=1.2, spread_pct=1.8, liquidite_ok=True,
          bougie_pattern="BULLISH_ENGULFING", bougie_sur_niveau=True,
          bougie_volume_conf=True, bougie_tendance_prev="BAISSIER")),
    ("CALL TTE ×19", None, False,
     dict(sens="CALL", signal_technique="HAUSSIER", tp1_pct=50.0, stop_pct=-40.0,
          ko_dist_pct=5.1, nb_positions_nq=1, actif_correl_nq=0.6, pct_cto_engage=25.0,
          catalyseur_macro="POSITIF", catalyseur_sectoriel="POSITIF", catalyseur_micro="NEUTRE")),
    ("CALL CAC40 ×21", None, False,
     dict(sens="CALL", signal_technique="HAUSSIER", tp1_pct=53.0, stop_pct=-40.0,
          ko_dist_pct=4.8, nb_positions_nq=1, actif_correl_nq=0.85, pct_cto_engage=25.0,
          catalyseur_macro="POSITIF", catalyseur_sectoriel="NEUTRE", catalyseur_micro="NEUTRE")),
]

# SCORING + NIVEAUX côte à côte
col_score = W * 0.56
col_niv   = W * 0.44

# -- Scoring --
sc_hdr = [P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
    ("ACTIF",TA_LEFT),("/100",TA_CENTER),("CONV.",TA_CENTER),
    ("MOM",TA_CENTER),("RR",TA_CENTER),("KO",TA_CENTER),
    ("VIX",TA_CENTER),("CAT",TA_CENTER),("MACRO",TA_CENTER),
    ("FLOW",TA_CENTER),("BOUGIE",TA_CENTER),
]]
sc_rows = [sc_hdr]
CONV_C = {"MAXIMALE":G,"FORTE":G,"MODÉRÉE":A,"FAIBLE":R,"ÉVITER":R}

for lbl, isin, is_open, kw in sc_configs:
    sc = score_setup_v2(actif_label=lbl, **{**MACRO_ARGS, **kw})
    f  = sc["facteurs"]
    cc = CONV_C.get(sc["conviction"], INK2)
    tag = " ●" if is_open else ""
    def bar(k, max_v):
        v=f.get(k,0); pct=v/max_v*100 if max_v else 0
        c=G if pct>=70 else A if pct>=45 else R
        return P(f'{v}', sz=6.5, bold=True, color=c, align=TA_CENTER)
    sc_rows.append([
        P(f'<b>{lbl}{tag}</b>', sz=6.5, bold=True, color=cc),
        P(f'<b>{sc["score"]}</b>', sz=10, bold=True, color=cc, align=TA_CENTER),
        P(sc["conviction"][:4], sz=6, bold=True, color=cc, align=TA_CENTER),
        bar("momentum_technique",18), bar("esperance_ponderee",16),
        bar("ko_niveau",10), bar("vix_regime",8),
        bar("catalyseur_grille",10), bar("contexte_macro",8),
        bar("options_flow",10), bar("bougie_daily",8),
    ])

sc_tbl = T(sc_rows,
    [col_score*0.26, col_score*0.11, col_score*0.10,
     col_score*0.09]*1 +
    [col_score*0.09]*7,
    pad=3)
# Fix col widths properly
sc_tbl = Table(sc_rows, colWidths=[
    col_score*0.22, col_score*0.09, col_score*0.08,
    col_score*0.08, col_score*0.08, col_score*0.08,
    col_score*0.08, col_score*0.08, col_score*0.08,
    col_score*0.07, col_score*0.06,
])
sc_extra = [
    ("FONTSIZE",(0,0),(-1,-1),6.5),
    ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
    ("TEXTCOLOR",(0,0),(-1,0),INK3),
    ("BACKGROUND",(0,0),(-1,0),W_BG),
    ("LINEBELOW",(0,0),(-1,0),0.4,RULE),
    ("BOX",(0,0),(-1,-1),0.4,RULE),
    ("INNERGRID",(0,0),(-1,-1),0.2,RULE2),
    ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE, W_BG]),
    ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
]
sc_tbl.setStyle(TableStyle(sc_extra))

# -- Niveaux --
niv_hdr = [P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
    ("NQ FUTURES",TA_LEFT),("PRIX",TA_CENTER),("ACTION",TA_CENTER),
    ("THALES",TA_LEFT),("PRIX€",TA_CENTER),("ACTION",TA_CENTER),
]]
NQ_ROWS = [
    ("Résistance TP2","25 478","Prendre profits",  "ATH résistance","272","TP3"),
    ("Target FOMC",   "25 200","TP1 → vendre 50%", "Résistance TV", "264","TP2"),
    ("★ Actuel",      "25 112","Référence",         "★ Achat",       "256","Référence"),
    ("VWAP trimestr.","24 411","Alerte SL",         "Support MA5",   "248","SL turbo"),
    ("Support majeur","24 000","Sortie + PUT",       "Support clé",   "245","Invalidé"),
]
NQ_COLORS = [G, G, INK2, A, R]
niv_rows = [niv_hdr]
for (nl,np,na,tl,tp,ta), nc in zip(NQ_ROWS, NQ_COLORS):
    niv_rows.append([
        P(nl, sz=6.5, color=nc),
        P(f'<b>{np}</b>', sz=7, bold=True, color=nc, align=TA_CENTER),
        P(na, sz=6, color=nc, align=TA_CENTER),
        P(tl, sz=6.5, color=nc),
        P(f'<b>{tp}</b>', sz=7, bold=True, color=nc, align=TA_CENTER),
        P(ta, sz=6, color=nc, align=TA_CENTER),
    ])

niv_t = Table(niv_rows, colWidths=[
    col_niv*0.34, col_niv*0.18, col_niv*0.20,
    col_niv*0.15, col_niv*0.08, col_niv*0.15,
])
niv_extra = [
    ("FONTSIZE",(0,0),(-1,-1),6.5),
    ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
    ("TEXTCOLOR",(0,0),(-1,0),INK3),
    ("BACKGROUND",(0,0),(-1,0),W_BG),
    ("LINEBELOW",(0,0),(-1,0),0.4,RULE),
    ("BOX",(0,0),(-1,-1),0.4,RULE),
    ("INNERGRID",(0,0),(-1,-1),0.2,RULE2),
    ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,W_BG]),
    ("BACKGROUND",(0,3),(-1,3),W_BG),  # actuel
    ("BACKGROUND",(0,4),(-1,4),colors.HexColor("#FFF8EC")),  # alerte
    ("BACKGROUND",(0,5),(-1,5),colors.HexColor("#FFF0F0")),  # sortie
    ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
]
niv_t.setStyle(TableStyle(niv_extra))

# Côte à côte avec label
side_by_side = Table([
    [SEC("Scores setup v2 — 10 facteurs /100", w=col_score), P(""), SEC("Niveaux clés", w=col_niv-W*0.007)],
    [sc_tbl, P(""), niv_t],
], colWidths=[col_score, W*0.007, col_niv-W*0.007])
side_by_side.setStyle(TableStyle([
    ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
    ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
    ("VALIGN",(0,0),(-1,-1),"TOP"),
]))
story += [side_by_side, SP(5)]


# ── BLOC 4b : Reco du jour ───────────────────────────────────────────────────
allocs = r.get("allocation_cto_daytrading", [])
cats   = r.get("catalysts", [])[:3]
regime = r.get("regime", r.get("signal","—"))
fomc_n = r.get("fomc_note","")[:90]
bilan  = r.get("bilan_veille", {})

# Header régime
reco_regime = Table([[
    P("RECO DU JOUR", sz=6, color=INK3, bold=True),
    P(f"<b>{regime}</b>", sz=7, bold=True, color=A),
    P(f'Confiance : <b>{r.get("confiance","—")}%</b>  ·  Signal : <b>{r.get("signal","—")}</b>', sz=6.5, color=INK2, align=TA_RIGHT),
]], colWidths=[W*0.15, W*0.48, W*0.37])
reco_regime.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#FAFAFA")),
    ("LINEBELOW",(0,0),(-1,0),0.4,RULE),
    ("LINEABOVE",(0,0),(-1,0),0.4,RULE),
    ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
]))
story += [reco_regime]

# Trades recommandés
if allocs:
    conv_c_map = {"FORTE":G,"MAXIMALE":G,"MODÉRÉE":A,"FAIBLE":R}
    alloc_hdr = [P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
        ("PRIORITÉ",TA_CENTER),("TRADE RECOMMANDÉ",TA_LEFT),("MONTANT",TA_CENTER),
        ("ENTRÉE",TA_LEFT),("TP1",TA_LEFT),("TP2",TA_LEFT),
        ("STOP",TA_LEFT),("GAIN CIBLE",TA_CENTER),("CONVICTION",TA_CENTER),
    ]]
    alloc_rows = [alloc_hdr]
    for a in allocs:
        cc = conv_c_map.get(a.get("conviction","MODÉRÉE"), A)
        sens_c = G if a.get("sens","CALL")=="CALL" else R
        alloc_rows.append([
            P(f'<b>{a.get("priorite","—")}</b>', sz=8, bold=True, color=INK3, align=TA_CENTER),
            P(f'<b>{a.get("position","—")}</b>  ·  {a.get("sous_jacent","")[:20]}  ·  {a.get("emetteur","")}', sz=6.5, bold=True, color=sens_c),
            P(f'<b>{a.get("montant",0):,}€</b>'.replace(",","'"), sz=7, bold=True, color=INK, align=TA_CENTER),
            P(a.get("entree","—")[:28], sz=6.5, color=INK2),
            P(a.get("tp1","—")[:24], sz=6.5, color=G),
            P(a.get("tp2","—")[:24], sz=6.5, color=G),
            P(a.get("stop","—")[:24], sz=6.5, color=R),
            P(f'<b>{a.get("gain_cible_jour","—")}</b>', sz=6.5, bold=True, color=G, align=TA_CENTER),
            P(f'<b>{a.get("conviction","—")}</b>', sz=6.5, bold=True, color=cc, align=TA_CENTER),
        ])
        # Note sous le trade
        if a.get("note"):
            alloc_rows.append([
                P("", sz=6), 
                P(f'↳ {a.get("note","")[:80]}', sz=6, color=INK3),
                *[P("",sz=6)]*7,
            ])

    alloc_t = Table(alloc_rows, colWidths=[
        W*0.06, W*0.22, W*0.07, W*0.15,
        W*0.13, W*0.13, W*0.12, W*0.07, W*0.05,
    ])
    alloc_style = [
        ("FONTSIZE",(0,0),(-1,-1),6.5),
        ("BOX",(0,0),(-1,-1),0.4,RULE),
        ("INNERGRID",(0,0),(-1,-1),0.2,RULE2),
        ("BACKGROUND",(0,0),(-1,0),W_BG),
        ("LINEBELOW",(0,0),(-1,0),0.4,RULE),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]
    # Highlight note rows (lighter)
    for i in range(2, len(alloc_rows), 2):
        alloc_style.append(("BACKGROUND",(0,i),(-1,i),colors.HexColor("#FAFAFA")))
        alloc_style.append(("TOPPADDING",(0,i),(-1,i),1))
        alloc_style.append(("BOTTOMPADDING",(0,i),(-1,i),1))
        alloc_style.append(("FONTSIZE",(0,i),(-1,i),6))
    alloc_t.setStyle(TableStyle(alloc_style))
    story.append(alloc_t)

# Catalyseurs + note FOMC sur 1 ligne
if cats or fomc_n:
    cat_parts = []
    for cat in cats:
        cat_parts.append(f'<b>{cat.get("event","—")[:30]}</b> [{cat.get("timing","—")[:12]}]')
    cat_line = "  ·  ".join(cat_parts)
    
    cat_row = Table([[
        P("CATALYSEURS", sz=6, color=INK3, bold=True),
        P(cat_line, sz=6, color=INK2),
        P(f'<b>Note :</b> {fomc_n}', sz=6, color=A if fomc_n else INK3),
    ]], colWidths=[W*0.11, W*0.42, W*0.47])
    cat_row.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#FFFBF0")),
        ("BOX",(0,0),(-1,-1),0.4,RULE),
        ("INNERGRID",(0,0),(-1,-1),0.2,RULE2),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]))
    story.append(cat_row)

story.append(SP(5))

# ── BLOC 4c : Calendrier économique du jour ───────────────────────────────────
cal_events = r.get('calendrier_jour', [])
if cal_events:
    CIMP = {"CRITIQUE": R, "TRÈS HAUTE": R, "HAUTE": A, "MOYENNE": INK2, "STRUCTURELLE": INK3}
    cal_hdr = [P(h, sz=6, color=INK3, bold=True, align=c) for h, c in [
        ("HEURE (Paris)", TA_CENTER), ("ÉVÉNEMENT", TA_LEFT),
        ("PRÉV / CONSENSUS", TA_CENTER), ("IMPACT NQ", TA_LEFT),
    ]]
    cal_rows = [cal_hdr]
    for ev in cal_events:
        imp_c = CIMP.get(ev.get('importance','MOYENNE'), INK2)
        cal_rows.append([
            P(ev.get('heure_paris','—'), sz=6, color=INK3, align=TA_CENTER),
            P(f'<b>{ev["event"]}</b>  ·  {ev.get("note","")[:55]}', sz=6.5, color=imp_c),
            P(ev.get('consensus','—'), sz=6, color=INK3, align=TA_CENTER),
            P(ev.get('impact_nq','—'), sz=6.5, color=imp_c),
        ])
    cal_t = T(cal_rows,
        [W*0.14, W*0.44, W*0.15, W*0.27], pad=3,
        extra=[
            # Rouge pour Triple Witching (ligne 2) et Iran (ligne 5)
            ("BACKGROUND",(0,2),(-1,2),colors.HexColor("#FFF2F2")),
            ("BACKGROUND",(0,5),(-1,5),colors.HexColor("#FFF2F2")),
            ("BACKGROUND",(0,1),(-1,1),colors.HexColor("#FFFBF0")),
        ])
    story.append(SEC("Calendrier économique — semaine du 24 mars 2026", R))
    story.append(SP(2))
    story.append(cal_t)
    story.append(SP(5))

# ── BLOC 5 : Règles + Scénarios FOMC côte à côte ─────────────────────────────
col_r = W * 0.46
col_s = W * 0.54

# Règles
rules_data = [
    [P("01",sz=7,bold=True,color=INK3,align=TA_CENTER),
     P("<b>2 KO actés ce matin</b> — NQ −1 247€  |  Thales −1 060€  |  Total −2 307€",sz=6.5,color=R)],
    [P("02",sz=7,bold=True,color=INK3,align=TA_CENTER),
     P("<b>Pas de nouveau trade avant 11h</b> — tête froide après 2 KO. Réserve 7 131€.",sz=6.5,color=R)],
    [P("03",sz=7,bold=True,color=INK3,align=TA_CENTER),
     P("<b>Vendre résiduels</b> : NQ 0.37€×150 = 55€  |  Thales ~7€  |  sur sgbourse.fr",sz=6.5,color=A)],
    [P("04",sz=7,bold=True,color=INK3,align=TA_CENTER),
     P("<b>PUT NQ max 1 000€</b> si NQ < 24 000 stable après 11h. Strike ~24 898.",sz=6.5,color=INK)],
    [P("05",sz=7,bold=True,color=INK3,align=TA_CENTER),
     P("<b>Réserve 7 131€</b> — NE PAS tout rejouer. Max 1 000€ sur PUT NQ après 11h.",sz=6.5,color=INK)],
]
rules_t = Table(rules_data, colWidths=[col_r*0.10, col_r*0.90])
rules_t.setStyle(TableStyle([
    ("BOX",(0,0),(-1,-1),0.4,RULE),
    ("INNERGRID",(0,0),(-1,-1),0.2,RULE2),
    ("ROWBACKGROUNDS",(0,0),(-1,-1),[WHITE,W_BG]),
    ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("BACKGROUND",(0,1),(-1,1),colors.HexColor("#FFF2F2")),  # règle 18h15
]))

# Scénarios FOMC
sc_fomc_data = [
    [P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
        ("SCÉNARIO 24 MARS",TA_LEFT),("PROB",TA_CENTER),("NQ CIBLE",TA_CENTER),("ACTION",TA_LEFT)]],
    [P("Talks échouent → reprise guerre",sz=6.5,bold=True,color=R),
     P("<b>45%</b>",sz=7,bold=True,color=R,align=TA_CENTER),
     P("23 500–24 200",sz=6.5,color=R,align=TA_CENTER),
     P("<b>Garder PUT NQ</b> · TP partiel 23 500 · CALL HO stop 0.430€",sz=6.5,color=R)],
    [P("Pause 5j incertaine / range",sz=6.5,color=A),
     P("30%",sz=7,color=A,align=TA_CENTER),
     P("24 200–24 800",sz=6.5,align=TA_CENTER),
     P("Sortir PUT NQ (stop atteint) · Thales TP 50%",sz=6.5,color=A)],
    [P("<b>Ceasefire confirmé</b>",sz=6.5,bold=True,color=G),
     P("15%",sz=7,color=G,align=TA_CENTER),
     P("25 000–26 000",sz=6.5,color=G,align=TA_CENTER),
     P("<b>Sortir PUT immédiat · CALL NQ ×15 (1 500€)</b>",sz=6.5,color=G)],
    [P("PMI récession + Iran chaos",sz=6.5,color=R),
     P("10%",sz=7,color=R,align=TA_CENTER),
     P("< 23 000",sz=6.5,color=R,align=TA_CENTER),
     P("Tenir PUT · TP agressif 22 500",sz=6.5,color=R)],
]
sc_fomc_t = Table(sc_fomc_data, colWidths=[col_s*0.28, col_s*0.10, col_s*0.14, col_s*0.48])
sc_fomc_t.setStyle(TableStyle([
    ("FONTSIZE",(0,0),(-1,-1),6.5),
    ("BOX",(0,0),(-1,-1),0.4,RULE),
    ("INNERGRID",(0,0),(-1,-1),0.2,RULE2),
    ("BACKGROUND",(0,0),(-1,0),W_BG),
    ("LINEBELOW",(0,0),(-1,0),0.4,RULE),
    ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,W_BG]),
    ("BACKGROUND",(0,2),(-1,2),colors.HexColor("#F0F8F2")),  # dovish
    ("BACKGROUND",(0,3),(-1,3),colors.HexColor("#FEF5F5")),  # hawkish
    ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
]))

bottom_row = Table([
    [SEC("Règles impératives",R, w=col_r), P(""), SEC("Scénarios FOMC — repositionner demain 09h10",A, w=col_s-W*0.007)],
    [rules_t, P(""), sc_fomc_t],
], colWidths=[col_r, W*0.007, col_s-W*0.007])
bottom_row.setStyle(TableStyle([
    ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
    ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
    ("VALIGN",(0,0),(-1,-1),"TOP"),
]))
story += [bottom_row, SP(4)]

# ── FOOTER P1 ─────────────────────────────────────────────────────────────────
story += [HR(0.3),
    P(f'Turbo Brief · {r["date"]} · NQ {r.get("nasdaq_current",25112):,} ({r.get("nasdaq_change_pct",0):+.2f}%) · '
      f'VIX {r["additional_kpis"].get("vix","22.37")} · EUR/USD 1,1534 · '
      f'CBOE P/C {cboe_pc:.2f} · QQQ OI P/C {qqq_oi:.2f} · '
      f'Pas un conseil financier'.replace(",","'"),
      sz=5.5, color=INK4, align=TA_CENTER)]

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — ANNEXES
# ══════════════════════════════════════════════════════════════════════════════
story.append(PageBreak())

ann_hdr = Table([[
    P("<b>ANNEXES</b>  —  Analyses quantitatives", sz=9, bold=True, color=INK),
    P(f"{r['date']}  ·  {r.get('heure','09h00')} CET", sz=7, color=INK3, align=TA_RIGHT),
]], colWidths=[W*0.6, W*0.4])
ann_hdr.setStyle(TableStyle([
    ("LINEBELOW",(0,0),(-1,0),1.0,INK),
    ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ("VALIGN",(0,0),(-1,-1),"BOTTOM"),
]))
story += [ann_hdr, SP(4)]

# A1 — CME FedWatch + A2 Macro Cross-Assets côte à côte
fed = r.get("fed", {"hold_prob":96,"cut25_prob":4,"june_cut25":46.8})

fed_data = [
    [P(h,sz=6,color=INK3,bold=True) for h in ["RÉUNION","SCÉNARIO","PROB","IMPACT NQ"]],
    [P("18 Mars",sz=6.5),P("Hold 3.50–3.75%",sz=6.5),P(f'<b>{fed["hold_prob"]}%</b>',sz=8,bold=True,color=A,align=TA_CENTER),P("Acté — FOMC passé",sz=6.5)],
    [P("18 Mars",sz=6.5),P("Coupe −25bps",sz=6.5),P(f'{fed["cut25_prob"]}%',sz=7,color=A,align=TA_CENTER),P("Rally +1.5%",sz=6.5)],
    [P("Juin 2026",sz=6.5),P("Coupe −25bps",sz=6.5),P(f'<b>{fed["june_cut25"]}%</b>',sz=8,bold=True,color=R,align=TA_CENTER),P("Dégradé depuis 47% — hawkish",sz=6.5)],
]

macro_cross = [
    [P(h,sz=6,color=INK3,bold=True) for h in ["VARIABLE","VALEUR","Δ5j","SIGNAL NQ CALL"]],
    [P("DXY",sz=6.5,bold=True),P("99.46",sz=6.5,align=TA_CENTER),P("-0.8% sem.",sz=6.5,color=G,align=TA_CENTER),P("DXY stable — corrél. inverse NQ tenu",sz=6.5,color=A)],
    [P("US 10Y",sz=6.5,bold=True),P("4.20%",sz=6.5,align=TA_CENTER),P("−8bps",sz=6.5,color=G,align=TA_CENTER),P("Neutre — taux stables",sz=6.5)],
    [P("10Y-2Y Spread",sz=6.5,bold=True),P("+53bps",sz=6.5,align=TA_CENTER),P("—",sz=6.5,align=TA_CENTER),P("Courbe saine → expansion",sz=6.5,color=G)],
    [P("HY Credit OAS",sz=6.5,bold=True),P("~420bps",sz=6.5,align=TA_CENTER),P("+80bps sem.",sz=6.5,color=R,align=TA_CENTER),P("Spreads en crise — risk-off maximal",sz=6.5,color=R)],
    [P("Or XAU",sz=6.5,bold=True),P("$4 862",sz=6.5,align=TA_CENTER),P("−2.7%",sz=6.5,color=A,align=TA_CENTER),P("Or recule malgré tensions — liquidations",sz=6.5,color=A)],
    [P("CNN F&G",sz=6.5,bold=True),P("18/100",sz=6.5,align=TA_CENTER),P("−4pts",sz=6.5,color=R,align=TA_CENTER),P("Extreme Fear — panique confirme baisse",sz=6.5,color=R)],
    [P("Cuivre",sz=6.5,bold=True),P("+1.8%",sz=6.5,align=TA_CENTER),P("rebond",sz=6.5,color=G,align=TA_CENTER),P("Rebond talks Iran → growth expectations reprennent",sz=6.5,color=A)],
]

col_a1 = W*0.40
col_a2 = W*0.60

fed_t  = T(fed_data,  [col_a1*0.22,col_a1*0.35,col_a1*0.15,col_a1*0.28], pad=3)
macro_t= T(macro_cross,[col_a2*0.18,col_a2*0.14,col_a2*0.10,col_a2*0.58], pad=3)

# b1 = Table([[SEC("A1 — CME FedWatch", w=col_a1)],[fed_t]],   colWidths=[col_a1])
# b2 = Table([[SEC("A2 — Macro Cross-Assets", w=col_a2-W*0.007)],[macro_t]], colWidths=[col_a2])
# b1.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
# b2.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))

row1 = Table([[SEC("A1 — CME FedWatch",w=col_a1), P(""), SEC("A2 — Macro Cross-Assets",w=col_a2-W*0.007)],[fed_t,P(""),macro_t]],colWidths=[col_a1,W*0.007,col_a2-W*0.007])
row1.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),("VALIGN",(0,0),(-1,-1),"TOP")]))
story += [row1, SP(5)]

# A3 — Options Flow + Polymarket côte à côte
flow_data2 = r.get("options_flow", {})
cboe_pc2 = flow_data2.get("cboe_equity_pc", 0.86)
qqq_oi2  = flow_data2.get("qqq_oi_pc", 1.60)
fl_score2= flow_data2.get("score", 5)
fl_interp2=flow_data2.get("interpretation","Neutre")
fl_c = G if fl_score2>=6 else A if fl_score2>=4 else R

flow_tbl_data = [
    [P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
        ("INDICATEUR",TA_LEFT),("VALEUR",TA_CENTER),("SIGNAL",TA_CENTER),("LOGIQUE",TA_LEFT)]],
    [P("CBOE Equity P/C",sz=6.5,bold=True),
     P(f'<b>{cboe_pc2:.2f}</b>',sz=8,bold=True,color=A,align=TA_CENTER),
     P("Neutre pre-FOMC",sz=6.5,color=A,align=TA_CENTER),
     P("Hausse P/C = hedging normal avant FOMC",sz=6.5)],
    [P("QQQ OI P/C",sz=6.5,bold=True),
     P(f'<b>{qqq_oi2:.2f}</b>',sz=8,bold=True,color=G,align=TA_CENTER),
     P("Contrarien ↑",sz=6.5,color=G,align=TA_CENTER),
     P("OI puts > calls = mur de protection → rebond",sz=6.5,color=G)],
    [P("Score Flow",sz=6.5,bold=True),
     P(f'<b>{fl_score2}/10</b>',sz=8,bold=True,color=fl_c,align=TA_CENTER),
     P(fl_interp2[:20],sz=6,color=fl_c,align=TA_CENTER),
     P("Max Pain NQ ~25 000 · VIX −17.7% = GEX stabilisateur",sz=6.5)],
]

pm = r.get("polymarket", {"recession_2026":31,"ceasefire_iran_june":62,"hormuz_normal_april":39})
poly_data = [
    [P(h,sz=6,color=INK3,bold=True) for h in ["MARCHÉ","PROB","IMPACT NQ"]],
    [P("Récession US 2026",sz=6.5),P('<b>47%</b>',sz=8,bold=True,color=R,align=TA_CENTER),P("NQ −15% à −25%",sz=6.5,color=R)],
    [P("Ceasefire Iran juin",sz=6.5),P(f'<b>{pm.get("ceasefire_iran_june",62)}%</b>',sz=8,bold=True,color=G,align=TA_CENTER),P("NQ +6% à +10%",sz=6.5,color=G)],
    [P("Hormuz normal avril",sz=6.5),P(f'{pm.get("hormuz_normal_april",39)}%',sz=7,color=A,align=TA_CENTER),P("Brent <85$ → +4%",sz=6.5,color=A)],
    [P("US forces en Iran",sz=6.5),P("18%",sz=7,color=R,align=TA_CENTER),P("NQ −8% à −15%",sz=6.5,color=R)],
]

col_b1 = W*0.54
col_b2 = W*0.46

ft = T(flow_tbl_data, [col_b1*0.22,col_b1*0.12,col_b1*0.22,col_b1*0.44], pad=3)
pt = T(poly_data,     [col_b2*0.48,col_b2*0.14,col_b2*0.38], pad=3)

# b3 = Table([[SEC("A3 — Options Flow & Sentiment", w=col_b1)],[ft]], colWidths=[col_b1])
# b4 = Table([[SEC("A4 — Polymarket Risques Macro", w=col_b2-W*0.007)],[pt]], colWidths=[col_b2])
# b3.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
# b4.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
row2 = Table([[SEC("A3 — Options Flow & Sentiment",w=col_b1),P(""),SEC("A4 — Polymarket Risques Macro",w=col_b2-W*0.007)],[ft,P(""),pt]],colWidths=[col_b1,W*0.007,col_b2-W*0.007])
row2.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),("VALIGN",(0,0),(-1,-1),"TOP")]))
story += [row2, SP(5)]

# A5 — Scoring v2 détail facteurs + A6 PEA côte à côte
FLBL = {
    "momentum_technique":"Momentum","esperance_ponderee":"Espérance",
    "ko_niveau":"KO niveau","vix_regime":"VIX régime","catalyseur_grille":"Catalyseur",
    "contexte_macro":"Macro","correlation_portef":"Corrélation",
    "volume_relatif":"Volume","bougie_daily":"Bougie J-1","options_flow":"Flow Options",
}
FMAX = {k:v["weight"] for k,v in FACTEURS_V2.items()}

sc_nq = score_setup_v2(actif_label="NQ", **{**MACRO_ARGS,
    **dict(sens="CALL",signal_technique="HAUSSIER",rsi=54,au_dessus_ma20=True,au_dessus_ma50=True,
           tp1_pct=38.5,stop_pct=-40.0,tp2_pct=70.6,prob_tp1=0.40,prob_tp2=0.20,prob_stop=0.40,
           ko_dist_pct=4.4,support_sous_ko=False,catalyseur_macro="POSITIF",
           catalyseur_sectoriel="POSITIF",catalyseur_micro="NEUTRE",
           nb_positions_nq=0,actif_correl_nq=1.0,pct_cto_engage=13.7,
           volume_ratio=1.4,spread_pct=2.0,liquidite_ok=True,
           bougie_pattern="HAMMER",bougie_sur_niveau=True,bougie_tendance_prev="BAISSIER")})
sc_ho = score_setup_v2(actif_label="HO", **{**MACRO_ARGS,
    **dict(sens="CALL",signal_technique="HAUSSIER",rsi=61,au_dessus_ma20=True,au_dessus_ma50=True,
           tp1_pct=43.3,stop_pct=-40.0,tp2_pct=82.0,prob_tp1=0.45,prob_tp2=0.20,prob_stop=0.35,
           ko_dist_pct=7.6,support_sous_ko=True,catalyseur_macro="POSITIF",
           catalyseur_sectoriel="FORT_POSITIF",catalyseur_micro="POSITIF",
           nb_positions_nq=1,actif_correl_nq=0.45,pct_cto_engage=24.9,
           volume_ratio=1.2,spread_pct=1.8,liquidite_ok=True,
           bougie_pattern="BULLISH_ENGULFING",bougie_sur_niveau=True,
           bougie_volume_conf=True,bougie_tendance_prev="BAISSIER")})

sc_detail_rows = [[P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
    ("FACTEUR",TA_LEFT),("MAX",TA_CENTER),("NQ",TA_CENTER),("HO",TA_CENTER),("NQ%",TA_CENTER),("HO%",TA_CENTER)]]]
for k, lbl in FLBL.items():
    mx = FMAX[k]; vn = sc_nq["facteurs"][k]; vh = sc_ho["facteurs"][k]
    cn = G if vn/mx>=0.70 else A if vn/mx>=0.45 else R
    ch = G if vh/mx>=0.70 else A if vh/mx>=0.45 else R
    sc_detail_rows.append([
        P(lbl, sz=6.5, color=INK2),
        P(str(mx), sz=6.5, color=INK4, align=TA_CENTER),
        P(f'<b>{vn}</b>', sz=7, bold=True, color=cn, align=TA_CENTER),
        P(f'<b>{vh}</b>', sz=7, bold=True, color=ch, align=TA_CENTER),
        P(f'{vn/mx*100:.0f}%', sz=6, color=cn, align=TA_CENTER),
        P(f'{vh/mx*100:.0f}%', sz=6, color=ch, align=TA_CENTER),
    ])
sc_detail_rows.append([
    P("<b>TOTAL</b>",sz=7,bold=True,color=INK),
    P("100",sz=7,bold=True,color=INK4,align=TA_CENTER),
    P(f'<b>{sc_nq["score"]}</b>',sz=9,bold=True,color=CONV_C.get(sc_nq["conviction"],A),align=TA_CENTER),
    P(f'<b>{sc_ho["score"]}</b>',sz=9,bold=True,color=CONV_C.get(sc_ho["conviction"],G),align=TA_CENTER),
    P(sc_nq["conviction"][:5],sz=6,bold=True,color=CONV_C.get(sc_nq["conviction"],A),align=TA_CENTER),
    P(sc_ho["conviction"][:5],sz=6,bold=True,color=CONV_C.get(sc_ho["conviction"],G),align=TA_CENTER),
])

# PEA
pea_data = [[P(h,sz=6,color=INK3,bold=True) for h in ["TITRE","VALEUR","SIGNAL","NOTE"]]]
sc_pea_c = {"GREEN":G,"YELLOW":A,"RED":R}
for pos in r.get("pea_positions",[]):
    c = sc_pea_c.get(pos.get("signal_color",""), INK3)
    pea_data.append([
        P(f'<b>{pos["nom"]}</b>',sz=6.5,bold=True,color=INK),
        P(f'{pos["valeur_pea"]:,}€'.replace(",","'"),sz=7,bold=True,color=INK,align=TA_CENTER),
        P(pos.get("signal_jour","—"),sz=6.5,color=c),
        P(pos.get("reco_pea","—")[:40],sz=6,color=INK3),
    ])

col_c1 = W*0.42
col_c2 = W*0.58

sc_detail_t = T(sc_detail_rows,
    [col_c1*0.38,col_c1*0.10,col_c1*0.14,col_c1*0.14,col_c1*0.12,col_c1*0.12], pad=3,
    extra=[("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),
           ("BACKGROUND",(0,-1),(-1,-1),W_BG),
           ("LINEABOVE",(0,-1),(-1,-1),0.5,RULE)])
# Bold last row — done inline
pea_t = T(pea_data,[col_c2*0.24,col_c2*0.14,col_c2*0.22,col_c2*0.40], pad=3)

# b5 = Table([[SEC(f"A5 — Scores détail  NQ:{sc_nq['score']}/100 · Thales:{sc_ho['score']}/100", w=col_c1)],[sc_detail_t]], colWidths=[col_c1])
# b6 = Table([[SEC("A6 — PEA (26 000€) — NE PAS TOUCHER", w=col_c2-W*0.007)],[pea_t]], colWidths=[col_c2])
# b5.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
# b6.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
row3 = Table([[SEC("A5 — Scores détail",w=col_c1),P(""),SEC("A6 — PEA (26 000€) — NE PAS TOUCHER",w=col_c2-W*0.007)],[sc_detail_t,P(""),pea_t]],colWidths=[col_c1,W*0.007,col_c2-W*0.007])
row3.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),("VALIGN",(0,0),(-1,-1),"TOP")]))
story += [row3, SP(5)]

# A7 — Scénarios Monte Carlo
story.append(SEC("A7 — Scénarios Monte Carlo NQ"))
story.append(SP(2))
mc_data = [[P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
    ("SCÉNARIO",TA_LEFT),("PROB",TA_CENTER),("RANGE NQ",TA_CENTER),("DRIVER",TA_LEFT)]]]
for s in r.get("scenarios",[]):
    c = G if s["prob"]<20 else R if s["prob"]>35 else A
    mc_data.append([P(s["label"],sz=6.5),P(f'<b>{s["prob"]}%</b>',sz=7,bold=True,color=c,align=TA_CENTER),
                    P(s["range"],sz=6.5,align=TA_CENTER),P(s["driver"],sz=6.5,color=INK2)])
story.append(T(mc_data,[W*0.32,W*0.08,W*0.20,W*0.40],pad=3))
story.append(SP(5))

# Footer P2
story += [HR(0.3),
    P(f'Sources : CME FedWatch · TradingView · Polymarket · CBOE · EIA  ·  {r["date"]}  ·  Pas un conseil financier',
      sz=5.5, color=INK4, align=TA_CENTER)]

# ── Build ─────────────────────────────────────────────────────────────────────
def bg(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.white)
    canvas.rect(0,0,A4[0],A4[1],fill=1,stroke=0)
    canvas.restoreState()

doc.build(story, onFirstPage=bg, onLaterPages=bg)
print("PDF v7 OK — 2 pages (one-pager + annexes)")
