"""
HTML Updater — Injecte le brief JSON dans turbo_brief_v2.html
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("output.html_updater")
PARIS = ZoneInfo("Europe/Paris")

HTML_TEMPLATE = Path(os.getenv("GITHUB_WORKSPACE", ".")) / "turbo_brief_v2.html"
HTML_OUTPUT   = Path("output/turbo_brief_live.html")
JSON_OUTPUT   = Path("output/brief_latest.json")


def update_turbo_brief_html(brief: dict) -> str:
    JSON_OUTPUT.parent.mkdir(exist_ok=True)
    JSON_OUTPUT.write_text(json.dumps(brief, indent=2, ensure_ascii=False))

    if not HTML_TEMPLATE.exists():
        log.warning("Template HTML introuvable")
        _create_fallback_html(brief)
        return str(HTML_OUTPUT)

    html = HTML_TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("</body>", _build_injection_script(brief) + "\n</body>")
    HTML_OUTPUT.write_text(html, encoding="utf-8")

    _create_index()
    _create_nojekyll()

    log.info(f"HTML mis à jour: {HTML_OUTPUT}")
    return str(HTML_OUTPUT)


def _build_injection_script(brief: dict) -> str:
    brief_json = json.dumps(brief, ensure_ascii=False)
    now_str = datetime.now(PARIS).strftime("%d/%m/%Y %H:%M")
    strip = brief.get("market_strip", {})

    def m(key, field, default="—"):
        return strip.get(key, {}).get(field, default)

    action_cards_html = ""
    for action in brief.get("plan_actions", []):
        sens = action.get("sens", "CALL")
        badge_class = "b-call" if sens == "CALL" else "b-put" if sens == "PUT" else "b-dec"
        badge_text  = "CALL ▲" if sens == "CALL" else "PUT ▼" if sens == "PUT" else "DÉCISION"
        gain_cls    = "g" if sens == "CALL" else "r" if sens == "PUT" else "a"
        action_cards_html += f"""
    <div class="action-card">
      <div class="ac-head">
        <div class="ac-time">{action.get('heure','?')}</div>
        <div class="ac-title">{action.get('titre','?')}</div>
        <div class="ac-badge {badge_class}">{badge_text}</div>
      </div>
      <div class="ac-grid">
        <div class="ac-field"><div class="af-lbl">Mise</div><div class="af-val {gain_cls}">{action.get('mise','—')}</div></div>
        <div class="ac-field"><div class="af-lbl">Levier</div><div class="af-val">×{action.get('levier','?')}</div></div>
        <div class="ac-field"><div class="af-lbl">Strike / KO</div><div class="af-val">{action.get('strike_ko','—')}</div></div>
        <div class="ac-field"><div class="af-lbl">Gain cible</div><div class="af-val {gain_cls}">{action.get('gain_cible','—')}</div></div>
      </div>
      <div class="ac-note">{action.get('note','')}</div>
    </div>"""

    alertes_html = "".join(
        f'<div class="alert"><div class="alert-badge">ALERTE</div><div class="alert-text">{a}</div></div>'
        for a in brief.get("alertes", [])
    )

    niveaux_rows = ""
    for niv in brief.get("niveaux_cles", []):
        color_map = {"bull": "var(--bull)", "bear": "var(--bear)", "amber": "var(--amber)", "blue": "var(--blue)"}
        color   = color_map.get(niv.get("couleur", "amber"), "var(--amber)")
        cls     = "up" if niv.get("couleur") == "bull" else "dn" if niv.get("couleur") == "bear" else "a"
        is_cur  = niv.get("type") == "current"
        row_cls = ' class="cur"' if is_cur else ""
        niveaux_rows += f"""
      <tr{row_cls}>
        <td><span class="dot" style="background:{color}"></span>{niv.get('label','?')}</td>
        <td><span class="lvl-price {cls}">{niv.get('prix','?')}</span></td>
        <td class="{cls}">{niv.get('action','?')}</td>
      </tr>"""

    return f"""
<script>
(function() {{
  const BRIEF = {brief_json};

  function applyBrief() {{
    const dateEl = document.querySelector('.mast-date');
    const edEl   = document.querySelector('.mast-edition');
    if (dateEl && BRIEF.date_fr) dateEl.textContent = BRIEF.date_fr;
    if (edEl && BRIEF.edition)   edEl.textContent = 'Édition ' + BRIEF.edition;

    const hed  = document.querySelector('.signal-hed');
    const deck = document.querySelector('.signal-deck');
    if (hed  && BRIEF.signal_du_jour?.titre)       hed.textContent  = BRIEF.signal_du_jour.titre;
    if (deck && BRIEF.signal_du_jour?.description) deck.textContent = BRIEF.signal_du_jour.description;

    const cells = document.querySelectorAll('.mkt-cell');
    const stripData = [
      {{lbl:'NQ',     val:'{m("nq","valeur")}',   chg:'{m("nq","chg")}',   cls:'{m("nq","dir","fl")}'}},
      {{lbl:'CAC 40', val:'{m("cac40","valeur")}', chg:'{m("cac40","chg")}', cls:'{m("cac40","dir","fl")}'}},
      {{lbl:'Brent',  val:'{m("brent","valeur")}', chg:'{m("brent","chg")}', cls:'{m("brent","dir","fl")}'}},
      {{lbl:'VIX',    val:'{m("vix","valeur")}',   chg:'{m("vix","chg")}',   cls:'{m("vix","dir","fl")}'}},
    ];
    cells.forEach((cell, i) => {{
      if (!stripData[i]) return;
      cell.innerHTML = `<div class="mkt-lbl">${{stripData[i].lbl}}</div><div class="mkt-num">${{stripData[i].val}}</div><div class="mkt-chg ${{stripData[i].cls}}">${{stripData[i].chg}}</div>`;
    }});

    const tr = document.getElementById('tr');
    if (tr) {{
      const items = [
        {{sym:'NQ',    val:'{m("nq","valeur")}',   chg:'{m("nq","chg")}',   cls:'{m("nq","dir","fl")}'}},
        {{sym:'FR40',  val:'{m("cac40","valeur")}', chg:'{m("cac40","chg")}', cls:'{m("cac40","dir","fl")}'}},
        {{sym:'BRENT', val:'{m("brent","valeur")}', chg:'{m("brent","chg")}', cls:'{m("brent","dir","fl")}'}},
        {{sym:'VIX',   val:'{m("vix","valeur")}',   chg:'{m("vix","chg")}',   cls:'{m("vix","dir","fl")}'}},
      ];
      const both = [...items, ...items];
      tr.innerHTML = both.map(t =>
        `<div class="t-item"><span class="t-sym">${{t.sym}}</span><span class="t-val">${{t.val}}</span><span class="t-chg ${{t.cls}}">${{t.chg}}</span></div>`
      ).join('');
    }}

    const wrap = document.querySelector('#p-actions .wrap');
    if (wrap) {{
      wrap.querySelectorAll('.alert').forEach(a => a.remove());
      wrap.insertAdjacentHTML('afterbegin', `{alertes_html}`);
      wrap.querySelectorAll('.action-card').forEach(c => c.remove());
      const secLabel = wrap.querySelector('.sec-label');
      if (secLabel) secLabel.insertAdjacentHTML('afterend', `{action_cards_html}`);
    }}

    const tbody = document.querySelector('.lvl-table tbody');
    if (tbody) tbody.innerHTML = `{niveaux_rows}`;

    console.log('Turbo Brief Live — {now_str}');
  }}

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', applyBrief);
  }} else {{
    applyBrief();
  }}
}})();
</script>"""


def _create_index():
    index = Path("output/index.html")
    if not index.exists():
        index.write_text("""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0; url=turbo_brief_live.html">
<title>Turbo Brief</title>
</head><body>
<p><a href="turbo_brief_live.html">Turbo Brief Live →</a></p>
</body></html>""")


def _create_nojekyll():
    nojekyll = Path("output/.nojekyll")
    if not nojekyll.exists():
        nojekyll.touch()


def _create_fallback_html(brief: dict):
    signal = brief.get("signal_du_jour", {})
    HTML_OUTPUT.write_text(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Turbo Brief</title></head>
<body style="font-family:Georgia;max-width:600px;margin:40px auto;padding:0 16px">
<h1>Turbo Brief — {brief.get('edition','?')}</h1>
<h2>{signal.get('titre','—')}</h2>
<p>{signal.get('description','')}</p>
</body></html>""")
