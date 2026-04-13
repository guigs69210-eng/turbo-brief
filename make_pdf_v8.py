import os as _os, sys as _sys
try:
    _BASE = _os.path.dirname(_os.path.abspath(__file__))
except NameError:
    _BASE = _os.getcwd()
_BASE = _BASE or _os.getcwd()
if _BASE not in _sys.path:
    _sys.path.insert(0, _BASE)

import json
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable, PageBreak)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

def load_json(path, fallback=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except:
        return fallback or {}

brief_path = _os.path.join(_BASE, "output", "brief_latest.json")
if not _os.path.exists(brief_path):
    brief_path = _os.path.join(_BASE, "brief_latest.json")
report_path = _os.path.join(_BASE, "report_data.json")

b = load_json(brief_path)
r = load_json(report_path)

signal   = b.get("signal_du_jour", {})
strip    = b.get("market_strip", {})
actions  = b.get("plan_actions", [])
niveaux  = b.get("niveaux_cles", [])
alertes  = b.get("alertes", [])
scenarios= b.get("scenarios", r.get("scenarios", []))
date_fr  = b.get("date_fr", r.get("date", datetime.now().strftime("%d/%m/%Y")))
edition  = b.get("edition", r.get("heure", datetime.now().strftime("%Hh%M CET")))
regles   = b.get("regles_session", [
    "Stop mental -40% sur le turbo = sortie immediate",
    "Actions FR -> cloture obligatoire avant 17h30",
    "Turbos NQ/indices -> cotent jusqu'a 22h CET",
    "TP1 (+25%) -> sortir 50%, stop a +10%",
    "Levier max x20 si VIX > 25",
    "Jamais de moyenne a la baisse",
])

positions     = r.get("positions_ouvertes", [])
cto           = r.get("cto_recap", {})
pea_positions = r.get("pea_positions", [])

cal_raw = (b.get("calendrier_economique") or b.get("calendar") or
           r.get("calendrier_jour") or [])
cal_norm = []
for ev in (cal_raw if isinstance(cal_raw, list) else []):
    if isinstance(ev, dict):
        cal_norm.append({
            "heure":  ev.get("heure", ev.get("heure_paris", ev.get("time","--"))),
            "event":  ev.get("event", ev.get("name", ev.get("titre","--"))),
            "impact": ev.get("impact_nq", ev.get("impact","--")),
            "note":   ev.get("note", ev.get("consensus","--")),
            "importance": ev.get("importance","NORMALE"),
        })

INK  = colors.HexColor("#0F0F0F")
INK2 = colors.HexColor("#3A3A3A")
INK3 = colors.HexColor("#6A6A6A")
INK4 = colors.HexColor("#A0A0A0")
RULE = colors.HexColor("#D8D8D8")
RULE2= colors.HexColor("#EBEBEB")
W_BG = colors.HexColor("#FAFAFA")
G    = colors.HexColor("#1A5C2E")
R    = colors.HexColor("#8B1A1A")
A    = colors.HexColor("#7A4F0A")
B    = colors.HexColor("#1A3D6E")
WHITE= colors.white

PDF_PATH = _os.path.join(_BASE, "turbo_brief_daily.pdf")
doc = SimpleDocTemplate(PDF_PATH, pagesize=A4,
    leftMargin=8*mm, rightMargin=8*mm,
    topMargin=7*mm, bottomMargin=7*mm,
    title=f"Turbo Brief -- {date_fr}")
W = A4[0] - 16*mm

def S(sz=7, color=INK, bold=False, align=TA_LEFT, sp=0, leading=None):
    return ParagraphStyle("_", fontSize=sz, textColor=color,
        fontName="Helvetica-Bold" if bold else "Helvetica",
        alignment=align, spaceAfter=sp,
        leading=leading or max(sz*1.25, sz+1.5))

def P(t, **kw):  return Paragraph(str(t), S(**kw))
def SP(h=2):     return Spacer(1, h)
def HR(t=0.3, c=RULE): return HRFlowable(width="100%", thickness=t, color=c, spaceAfter=2, spaceBefore=2)

def SEC(title, accent=INK3, w=None):
    return Table([[P(title.upper(), sz=6, color=accent, bold=True)]],
        colWidths=[w or W],
        style=[("LINEBELOW",(0,0),(0,0),0.4,RULE),
               ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),2)])

def T(data, cols, pad=3, extra=None):
    style = [
        ("FONTSIZE",(0,0),(-1,-1),6.5),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,0),(-1,0),INK3),
        ("BACKGROUND",(0,0),(-1,0),W_BG),
        ("LINEBELOW",(0,0),(-1,0),0.5,RULE),
        ("BOX",(0,0),(-1,-1),0.4,RULE),
        ("INNERGRID",(0,0),(-1,-1),0.2,RULE2),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,W_BG]),
        ("TOPPADDING",(0,0),(-1,-1),pad),("BOTTOMPADDING",(0,0),(-1,-1),pad),
        ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]
    if extra: style += extra
    t = Table(data, colWidths=cols)
    t.setStyle(TableStyle(style))
    return t

def side(left, right, lw, rw):
    t = Table([[left, P(""), right]], colWidths=[lw, W*0.008, rw])
    t.setStyle(TableStyle([
        ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
        ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
    ]))
    return t

def sv(k): return strip.get(k,{}).get("valeur","--")
def sd(k): return strip.get(k,{}).get("dir","fl")
def sc_color(k): return G if sd(k)=="up" else R if sd(k)=="dn" else INK3

story = []

# MASTHEAD
mast = Table([[
    P("<b>TURBO BRIEF</b>", sz=11, bold=True, color=INK),
    P("Day Trading - Paris", sz=7, color=INK3, align=TA_CENTER),
    P(f"{date_fr}  -  {edition}  -  Turbos 8h30-18h30", sz=6.5, color=INK4, align=TA_RIGHT),
]], colWidths=[W*0.22, W*0.30, W*0.48])
mast.setStyle(TableStyle([
    ("LINEBELOW",(0,0),(-1,0),1.5,INK),
    ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ("VALIGN",(0,0),(-1,-1),"BOTTOM"),
]))
story += [mast, SP(3)]

# SIGNAL + STRIP
biais   = signal.get("biais","neutre").lower()
biais_c = G if "haussier" in biais else R if "baissier" in biais else A
conv    = signal.get("conviction","--")

strip_inner = [[]]
for key, label in [("nq","NQ"),("cac40","CAC 40"),("vix","VIX"),("brent","Brent")]:
    chg = strip.get(key,{}).get("chg","")
    cc  = sc_color(key)
    cell = Table([[
        P(label, sz=5.5, color=INK4, align=TA_CENTER),
        P(f"<b>{sv(key)}</b>", sz=10, bold=True, color=INK, align=TA_CENTER),
        P(chg, sz=6.5, color=cc, align=TA_CENTER),
    ]], colWidths=[W*0.105],
    style=[("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),2),
           ("LEFTPADDING",(0,0),(-1,-1),2),("RIGHTPADDING",(0,0),(-1,-1),2),
           ("BOX",(0,0),(-1,-1),0.4,RULE),("BACKGROUND",(0,0),(-1,-1),W_BG),
           ("VALIGN",(0,0),(-1,-1),"MIDDLE")])
    strip_inner[0].append(cell)

strip_tbl = Table(strip_inner, colWidths=[W*0.42])
strip_tbl.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
    ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))

sig_inner = Table([[
    P(f"<b>{signal.get('titre','--')}</b>", sz=8, bold=True, color=biais_c),
    P(signal.get("description","")[:130], sz=6.5, color=INK2),
    P(f"Conviction: {conv}  -  {signal.get('contexte_macro','')[:90]}", sz=6, color=INK3),
]], colWidths=[W*0.55],
style=[("BOX",(0,0),(-1,-1),0.4,RULE),("BACKGROUND",(0,0),(-1,-1),W_BG),
       ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),2),
       ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
       ("VALIGN",(0,0),(-1,-1),"MIDDLE")])

sig_row = Table([[sig_inner, P(""), strip_tbl]], colWidths=[W*0.56, W*0.02, W*0.42])
sig_row.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
    ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
    ("VALIGN",(0,0),(-1,-1),"TOP")]))
story += [sig_row, SP(4)]

# POSITIONS OUVERTES
story += [SEC("Positions ouvertes", B), SP(2)]
reserve = cto.get("reserve_dispo", 6773)
if not positions:
    flat = Table([[
        P("FLAT -- Aucune position ouverte", sz=8, bold=True, color=INK3),
        P(f"Reserve disponible: <b>{reserve:,.0f}EUR</b>", sz=8, bold=True, color=G, align=TA_RIGHT),
    ]], colWidths=[W*0.60, W*0.40],
    style=[("BOX",(0,0),(-1,-1),0.4,RULE),("BACKGROUND",(0,0),(-1,-1),W_BG),
           ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
           ("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),
           ("VALIGN",(0,0),(-1,-1),"MIDDLE")])
    story.append(flat)
else:
    ph = [P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
        ("ACTIF",TA_LEFT),("ENTREE SJ",TA_CENTER),("NB x PRIX",TA_CENTER),
        ("MISE",TA_CENTER),("xLEV",TA_CENTER),("KO DIST",TA_CENTER),
        ("SJ LIVE",TA_CENTER),("P&L %",TA_CENTER),("P&L EUR",TA_CENTER),
        ("STOP",TA_CENTER),("TP1",TA_CENTER),("TP2",TA_CENTER)]]
    pr = [ph]
    for pos in positions:
        ppct = pos.get("pnl_live_pct",0) or 0
        peur = pos.get("pnl_live_eur",0) or 0
        kod  = pos.get("ko_dist_live",0) or pos.get("ko_dist_pct",0) or 0
        sjl  = pos.get("sj_live") or pos.get("sj_entree",0)
        mise = pos.get("nb_titres",0)*pos.get("prix_achat",0)
        pc   = G if ppct>=0 else R
        kc   = R if kod<3 else A if kod<6 else INK2
        sc_pos = G if pos.get("sens")=="CALL" else R
        pr.append([
            P(f"<b>{pos['label'][:22]}</b>", sz=6.5, bold=True, color=sc_pos),
            P(f"{pos.get('sj_entree',0):,}".replace(",","'"), sz=6.5, color=INK2, align=TA_CENTER),
            P(f"{pos.get('nb_titres',0)}x{pos.get('prix_achat',0):.2f}EUR", sz=6.5, align=TA_CENTER),
            P(f"<b>{mise:.0f}EUR</b>", sz=7, bold=True, color=INK, align=TA_CENTER),
            P(f"<b>x{pos.get('levier','--')}</b>", sz=7, bold=True, color=A, align=TA_CENTER),
            P(f"<b>-{kod:.1f}%</b>", sz=7, bold=True, color=kc, align=TA_CENTER),
            P(f"{sjl:,}".replace(",","'"), sz=6.5, color=INK2, align=TA_CENTER),
            P(f"<b>{ppct:+.1f}%</b>", sz=7, bold=True, color=pc, align=TA_CENTER),
            P(f"<b>{peur:+.0f}EUR</b>", sz=7, bold=True, color=pc, align=TA_CENTER),
            P(f"{pos.get('stop_turbo',0):.3f}EUR", sz=6.5, color=R, align=TA_CENTER),
            P(f"{pos.get('tp1_turbo',0):.3f}EUR", sz=6.5, color=G, align=TA_CENTER),
            P(f"{pos.get('tp2_turbo',0):.3f}EUR", sz=6.5, color=G, align=TA_CENTER),
        ])
    story.append(T(pr, [W*0.17,W*0.08,W*0.09,W*0.07,W*0.06,W*0.07,
                         W*0.07,W*0.07,W*0.07,W*0.08,W*0.08,W*0.09], pad=3))

story.append(SP(4))

# PLAN D'ACTION
story += [SEC("Plan d'action", A), SP(2)]
def get_lvl(titre):
    t = titre.lower()
    relevant = [n for n in niveaux if
        ("nq" in t and any(k in n.get("label","").lower() for k in ["nq","nasdaq"])) or
        ("cac" in t and any(k in n.get("label","").lower() for k in ["cac"])) or
        True]
    return (relevant or niveaux)[:3]

if not actions:
    story.append(P("Aucun trade recommande pour cette session.", sz=7, color=INK3))
else:
    pa_h = [P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
        ("HEURE",TA_CENTER),("TRADE",TA_LEFT),("SENS",TA_CENTER),
        ("MISE",TA_CENTER),("xLEV",TA_CENTER),("STRIKE/KO",TA_CENTER),
        ("GAIN CIBLE",TA_CENTER),("NIVEAUX CLES",TA_LEFT),("NOTE",TA_LEFT)]]
    pa_r = [pa_h]
    for ac in actions:
        sens = ac.get("sens","CALL")
        scc  = G if sens=="CALL" else R
        lvls = get_lvl(ac.get("titre",""))
        lvl_s= "  |  ".join([f"{n.get('label','')[:10]} {n.get('prix','')}" for n in lvls[:3]])
        pa_r.append([
            P(f"<b>{ac.get('heure','--')}</b>", sz=7, bold=True, color=INK2, align=TA_CENTER),
            P(f"<b>{ac.get('titre','--')}</b>", sz=7, bold=True, color=scc),
            P(f"<b>{sens}</b>", sz=8, bold=True, color=scc, align=TA_CENTER),
            P(f"<b>{ac.get('mise','--')}</b>", sz=7, bold=True, color=INK, align=TA_CENTER),
            P(f"<b>x{ac.get('levier','--')}</b>", sz=7, bold=True, color=A, align=TA_CENTER),
            P(ac.get("strike_ko","--"), sz=6.5, color=INK2, align=TA_CENTER),
            P(f"<b>{ac.get('gain_cible','--')}</b>", sz=6.5, bold=True, color=G, align=TA_CENTER),
            P(lvl_s, sz=6, color=INK3),
            P(ac.get("note","")[:55], sz=6, color=INK3),
        ])
        if ac.get("plateforme"):
            pa_r.append([P("",sz=5), P(f"-> {ac['plateforme'][:55]}", sz=6, color=INK4),
                         *[P("",sz=5)]*7])
    pa_t = Table(pa_r, colWidths=[W*0.07,W*0.17,W*0.06,W*0.07,W*0.05,
                                    W*0.11,W*0.10,W*0.18,W*0.19])
    pa_t.setStyle(TableStyle([
        ("FONTSIZE",(0,0),(-1,-1),6.5),
        ("BOX",(0,0),(-1,-1),0.4,RULE),("INNERGRID",(0,0),(-1,-1),0.2,RULE2),
        ("BACKGROUND",(0,0),(-1,0),W_BG),("LINEBELOW",(0,0),(-1,0),0.5,RULE),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,W_BG]),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]))
    story.append(pa_t)

story.append(SP(4))

# CALENDRIER
if cal_norm:
    story += [SEC("Calendrier economique", R), SP(2)]
    IMP_C = {"CRITIQUE":R,"TRES HAUTE":R,"HAUTE":A,"NORMALE":INK2}
    ch = [P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
        ("HEURE (CET)",TA_CENTER),("EVENEMENT",TA_LEFT),
        ("CONSENSUS",TA_CENTER),("IMPACT NQ",TA_LEFT)]]
    cr = [ch]
    for ev in cal_norm[:6]:
        ic = IMP_C.get(ev.get("importance","NORMALE"), INK2)
        cr.append([P(ev["heure"],sz=6.5,color=INK3,align=TA_CENTER),
                   P(f"<b>{ev['event']}</b>",sz=6.5,color=ic),
                   P(ev["note"],sz=6,color=INK3,align=TA_CENTER),
                   P(ev["impact"],sz=6.5,color=ic)])
    story.append(T(cr, [W*0.12,W*0.40,W*0.14,W*0.34], pad=3))
    story.append(SP(4))

# ALERTES
if alertes:
    story += [SEC("Alertes", R), SP(2)]
    al_r = []
    for al in alertes[:4]:
        crit = any(w in str(al).upper() for w in ["STOP","KO","URGENT","CLOTURE"])
        al_r.append([P("!", sz=8, bold=True, color=R if crit else A, align=TA_CENTER),
                     P(str(al), sz=7, color=R if crit else A)])
    al_t = Table(al_r, colWidths=[W*0.04, W*0.96])
    al_t.setStyle(TableStyle([
        ("BOX",(0,0),(-1,-1),0.4,RULE),("INNERGRID",(0,0),(-1,-1),0.2,RULE2),
        ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#FFFBF0")),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]))
    story.append(al_t)
    story.append(SP(3))

# FOOTER P1
story += [HR(0.3),
    P(f"Turbo Brief  -  {date_fr}  -  NQ {sv('nq')} ({strip.get('nq',{}).get('chg','')})  -  VIX {sv('vix')}  -  Brent {sv('brent')}  -  Pas un conseil financier",
      sz=5.5, color=INK4, align=TA_CENTER)]

# PAGE 2 ANNEXES
story.append(PageBreak())
ah = Table([[
    P("<b>ANNEXES</b>  --  Turbo Brief", sz=9, bold=True, color=INK),
    P(f"{date_fr}  -  {edition}", sz=7, color=INK3, align=TA_RIGHT),
]], colWidths=[W*0.6, W*0.4])
ah.setStyle(TableStyle([("LINEBELOW",(0,0),(-1,0),1.0,INK),
    ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ("VALIGN",(0,0),(-1,-1),"BOTTOM")]))
story += [ah, SP(4)]

# A1 SCENARIOS + A2 NIVEAUX
ca = W*0.50
sc_r = [[P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
    ("SCENARIO",TA_LEFT),("PROB",TA_CENTER),("CIBLE NQ",TA_CENTER),("ACTION",TA_LEFT)]]]
for s in scenarios[:5]:
    prob = s.get("prob", s.get("probabilite",0))
    try: pv = int(str(prob).replace("%",""))
    except: pv = 0
    pc = R if pv>=35 else A if pv>=20 else G
    sc_r.append([P(s.get("label","--")[:32],sz=6.5,color=INK2),
                 P(f"<b>{pv}%</b>",sz=7,bold=True,color=pc,align=TA_CENTER),
                 P(s.get("range", s.get("nq_cible","--")),sz=6.5,align=TA_CENTER),
                 P(s.get("action", s.get("driver","--"))[:35],sz=6.5,color=INK2)])
sc_t = T(sc_r, [ca*0.35,ca*0.10,ca*0.18,ca*0.37], pad=3)

nv_r = [[P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
    ("NIVEAU",TA_LEFT),("PRIX",TA_CENTER),("TYPE",TA_CENTER),("ACTION",TA_LEFT)]]]
NVC = {"resistance":R,"support":G,"current":B}
for n in niveaux[:7]:
    nc = NVC.get(n.get("type",""), INK2)
    nv_r.append([P(n.get("label","--")[:22],sz=6.5,color=nc),
                 P(f"<b>{n.get('prix','--')}</b>",sz=7,bold=True,color=nc,align=TA_CENTER),
                 P(n.get("type","--"),sz=6,color=nc,align=TA_CENTER),
                 P(n.get("action","--")[:28],sz=6.5,color=INK2)])
nv_t = T(nv_r, [ca*0.35,ca*0.18,ca*0.15,ca*0.32], pad=3)

l1 = Table([[SEC("A1 -- Scenarios",A,w=ca)],[sc_t]], colWidths=[ca])
r1 = Table([[SEC("A2 -- Niveaux cles",B,w=ca-W*0.008)],[nv_t]], colWidths=[ca])
for t in [l1,r1]:
    t.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
        ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
story += [side(l1,r1,ca,ca-W*0.008), SP(4)]

# A3 REGLES + A4 MARCHES
cb1, cb2 = W*0.38, W*0.62
rg_r = []
for i, txt in enumerate(regles[:6], 1):
    rg_r.append([P(f"<b>{i:02d}</b>",sz=7,bold=True,color=R if i<=2 else INK3,align=TA_CENTER),
                 P(str(txt),sz=6.5,color=R if i<=2 else INK2)])
rg_t = Table(rg_r, colWidths=[cb1*0.10, cb1*0.90])
rg_t.setStyle(TableStyle([
    ("BOX",(0,0),(-1,-1),0.4,RULE),("INNERGRID",(0,0),(-1,-1),0.2,RULE2),
    ("ROWBACKGROUNDS",(0,0),(-1,-1),[WHITE,W_BG]),
    ("BACKGROUND",(0,0),(-1,1),colors.HexColor("#FFF2F2")),
    ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
]))

mc_r = [[P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
    ("ACTIF",TA_LEFT),("VALEUR",TA_CENTER),("VAR",TA_CENTER),("SIGNAL",TA_LEFT)]]]
for key, label in [("nq","NQ Futures"),("cac40","CAC 40"),("vix","VIX"),
                   ("brent","Brent"),("gold","Or XAU"),("eurusd","EUR/USD"),("us10y","US 10Y")]:
    d = strip.get(key,{})
    if d.get("valeur"):
        dc = sc_color(key)
        sig = "Haussier" if sd(key)=="up" else "Baissier" if sd(key)=="dn" else "Neutre"
        mc_r.append([P(f"<b>{label}</b>",sz=6.5,color=INK2),
                     P(f"<b>{d['valeur']}</b>",sz=7,bold=True,color=dc,align=TA_CENTER),
                     P(d.get("chg",""),sz=6.5,color=dc,align=TA_CENTER),
                     P(sig,sz=6.5,color=dc)])
mc_t = T(mc_r, [cb2*0.25,cb2*0.20,cb2*0.15,cb2*0.40], pad=3)

l2 = Table([[SEC("A3 -- Regles imperatives",R,w=cb1)],[rg_t]], colWidths=[cb1])
r2 = Table([[SEC("A4 -- Marches cross-assets",B,w=cb2-W*0.008)],[mc_t]], colWidths=[cb2])
for t in [l2,r2]:
    t.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
        ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
story += [side(l2,r2,cb1,cb2-W*0.008), SP(4)]

# A5 PEA
story += [SEC("A5 -- PEA (26 000 EUR) -- NE PAS TOUCHER", R), SP(2)]
ph2 = [P(h,sz=6,color=INK3,bold=True,align=c) for h,c in [
    ("TITRE",TA_LEFT),("VALEUR",TA_CENTER),("SIGNAL",TA_CENTER),("NOTE",TA_LEFT)]]
pr2 = [ph2]
SCP = {"GREEN":G,"YELLOW":A,"RED":R}
for pos in pea_positions:
    sc_p = SCP.get(pos.get("signal_color",""), INK3)
    pr2.append([P(f"<b>{pos.get('nom','--')}</b>",sz=6.5,bold=True,color=INK),
                P(f"{pos.get('valeur_pea',0):,}EUR".replace(",","'"),sz=7,color=INK,align=TA_CENTER),
                P(pos.get("signal_jour","--"),sz=6.5,color=sc_p,align=TA_CENTER),
                P(pos.get("reco_pea","--")[:50],sz=6,color=INK3)])
total = sum(p.get("valeur_pea",0) for p in pea_positions) or 26000
pr2.append([P("<b>TOTAL PEA</b>",sz=7,bold=True,color=INK),
            P(f"<b>{total:,}EUR</b>".replace(",","'"),sz=8,bold=True,color=B,align=TA_CENTER),
            P("NE PAS TOUCHER",sz=6.5,bold=True,color=R,align=TA_CENTER),
            P(r.get("pea_note", b.get("pea_note","PEA -- Ne pas toucher."))[:60],sz=6,color=INK3)])
story.append(T(pr2, [W*0.22,W*0.12,W*0.14,W*0.52], pad=3,
    extra=[("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),
           ("BACKGROUND",(0,-1),(-1,-1),W_BG),
           ("LINEABOVE",(0,-1),(-1,-1),0.5,RULE)]))

story += [SP(3), HR(0.3),
    P(f"Sources: Mistral AI - yfinance - TradingView - CME  -  {date_fr}  -  Pas un conseil financier",
      sz=5.5, color=INK4, align=TA_CENTER)]

def bg(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(colors.white)
    canvas.rect(0,0,A4[0],A4[1],fill=1,stroke=0)
    canvas.restoreState()

doc.build(story, onFirstPage=bg, onLaterPages=bg)
print(f"PDF v8 OK -- {PDF_PATH}")
