"""Report finale: un unico HTML self-contained, navigabile e scaricabile.

Filosofia:
- **Un solo file** `report.html`: CSS e JS sono inline, nessuna dipendenza a
  runtime tranne Mermaid (caricato da CDN, con fallback al sorgente se offline).
- **Navigabile**: sidebar con indice + ricerca live.
- **Scaricabile a sé**: ogni sezione (architettura, singolo file/modulo, il
  mazzo di flashcard) puo' essere esportata come mini-HTML self-contained
  cliccando «Scarica». L'export clona il DOM gia' renderizzato — quindi gli SVG
  di Mermaid sono inclusi e il file scaricato funziona anche senza rete.

Nessuna logica di provider/git qui dentro: si riceve gia' tutto normalizzato.
"""

from __future__ import annotations

import html as _html
import json
import os
import re
from typing import Dict, List, Optional, Tuple

from ..models import AnalysisResult


# --------------------------------------------------------------- markdown mini

def _esc(text: str) -> str:
    """Escape HTML (senza toccare gli apici, per leggibilita' nel sorgente)."""
    return _html.escape(text, quote=False)


def _inline(text: str) -> str:
    """Converte il markdown inline in HTML. Il testo NON deve essere gia' escapato:
    l'escape avviene qui, proteggendo prima i code-span."""
    spans: List[str] = []

    def _stash(m: "re.Match[str]") -> str:
        spans.append("<code>" + _esc(m.group(1)) + "</code>")
        return f"\x00{len(spans) - 1}\x00"

    # 1) proteggi i code-span `...`
    text = re.sub(r"`([^`]+)`", _stash, text)
    # 2) escape del resto
    text = _esc(text)
    # 3) link [testo](url)
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        text,
    )
    # 4) grassetto / corsivo
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
    # 5) ripristina i code-span
    text = re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)
    return text


def _md_to_html(md: str) -> str:
    """Convertitore markdown -> HTML minimale ma robusto per contenuti AI.

    Copre: heading, liste (ord/non-ord), code fence ```, regole `---`,
    paragrafi e inline (grassetto/corsivo/code/link). Nessuna dipendenza.
    """
    if not md:
        return ""
    lines = md.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    i = 0
    n = len(lines)
    list_stack: List[str] = []  # "ul" | "ol"

    def close_lists() -> None:
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    while i < n:
        line = lines[i]

        # code fence
        m = re.match(r"^\s*```(\w*)\s*$", line)
        if m:
            close_lists()
            lang = m.group(1)
            i += 1
            buf: List[str] = []
            while i < n and not re.match(r"^\s*```\s*$", lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1  # salta la fence di chiusura
            cls = f' class="language-{lang}"' if lang else ""
            out.append(f"<pre class=\"code\"><code{cls}>" + _esc("\n".join(buf)) + "</code></pre>")
            continue

        # riga vuota
        if not line.strip():
            close_lists()
            i += 1
            continue

        # regola orizzontale
        if re.match(r"^\s*([-*_])\1{2,}\s*$", line):
            close_lists()
            out.append("<hr>")
            i += 1
            continue

        # heading
        h = re.match(r"^\s*(#{1,6})\s+(.*)$", line)
        if h:
            close_lists()
            lvl = min(len(h.group(1)) + 1, 6)  # sotto al <h2> della sezione
            out.append(f"<h{lvl}>{_inline(h.group(2).strip())}</h{lvl}>")
            i += 1
            continue

        # lista non ordinata
        ul = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if ul:
            if not list_stack or list_stack[-1] != "ul":
                close_lists()
                list_stack.append("ul")
                out.append("<ul>")
            out.append(f"<li>{_inline(ul.group(1).strip())}</li>")
            i += 1
            continue

        # lista ordinata
        ol = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if ol:
            if not list_stack or list_stack[-1] != "ol":
                close_lists()
                list_stack.append("ol")
                out.append("<ol>")
            out.append(f"<li>{_inline(ol.group(1).strip())}</li>")
            i += 1
            continue

        # paragrafo (accorpa righe consecutive non-strutturate)
        close_lists()
        para: List[str] = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not re.match(
            r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|```|([-*_])\2{2,}\s*$)", lines[i]
        ):
            para.append(lines[i].strip())
            i += 1
        out.append("<p>" + _inline(" ".join(para)) + "</p>")

    close_lists()
    return "\n".join(out)


def _clean_mermaid(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```(?:mermaid)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _slug(text: str) -> str:
    s = re.sub(r"[^\w.-]+", "-", text.strip().lower())
    return re.sub(r"-{2,}", "-", s).strip("-") or "dettaglio"


# --------------------------------------------------------------- CSS / JS

_CSS = r"""
:root{
  --bg:#f6f7f9; --panel:#ffffff; --ink:#1c2230; --muted:#5b6577; --line:#e4e8ef;
  --accent:#3455e6; --accent-soft:#eaeefe; --code-bg:#f2f4f8; --shadow:0 1px 3px rgba(20,30,60,.08);
  --ok:#127a4a; --warn:#a8621b;
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#12151c; --panel:#191d27; --ink:#e7ebf3; --muted:#9aa6bd; --line:#2a303d;
  --accent:#7c93ff; --accent-soft:#20263a; --code-bg:#0f131b; --shadow:0 1px 3px rgba(0,0,0,.4);
  --ok:#4fd394; --warn:#e0a35b;
}}
:root[data-theme=dark]{
  --bg:#12151c; --panel:#191d27; --ink:#e7ebf3; --muted:#9aa6bd; --line:#2a303d;
  --accent:#7c93ff; --accent-soft:#20263a; --code-bg:#0f131b; --shadow:0 1px 3px rgba(0,0,0,.4);
  --ok:#4fd394; --warn:#e0a35b;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
a{color:var(--accent)}
code{background:var(--code-bg);padding:.12em .38em;border-radius:5px;font-size:.88em;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}
pre.code{background:var(--code-bg);border:1px solid var(--line);border-radius:10px;
  padding:14px 16px;overflow:auto;font-size:13px;line-height:1.5;}
pre.code code{background:none;padding:0}
hr{border:none;border-top:1px solid var(--line);margin:18px 0}

.layout{display:grid;grid-template-columns:288px 1fr;min-height:100vh}
/* ---- sidebar ---- */
.side{position:sticky;top:0;align-self:start;height:100vh;overflow:auto;
  background:var(--panel);border-right:1px solid var(--line);padding:18px 14px}
.side h1{font-size:16px;margin:2px 6px 2px}
.side .sub{color:var(--muted);font-size:12px;margin:0 6px 14px}
.search{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:9px;
  background:var(--bg);color:var(--ink);font-size:13px;margin-bottom:12px}
.nav-group{margin:14px 6px 4px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.nav a{display:block;padding:7px 10px;border-radius:8px;color:var(--ink);text-decoration:none;
  font-size:13.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nav a:hover{background:var(--accent-soft)}
.nav a.active{background:var(--accent-soft);color:var(--accent);font-weight:600}
.nav a.hide{display:none}

/* ---- main ---- */
.main{padding:26px clamp(18px,4vw,46px);max-width:1000px}
.topbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;margin-bottom:8px}
.title{font-size:26px;font-weight:700;margin:0}
.tools{display:flex;flex-wrap:wrap;gap:8px}
.btn{border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer;
  padding:8px 12px;border-radius:9px;font-size:13px;box-shadow:var(--shadow)}
.btn:hover{border-color:var(--accent);color:var(--accent)}
.btn.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.btn.primary:hover{opacity:.92;color:#fff}

.meta{display:flex;flex-wrap:wrap;gap:8px 18px;color:var(--muted);font-size:13px;margin:6px 0 20px}
.meta b{color:var(--ink);font-weight:600}
.stats{display:flex;flex-wrap:wrap;gap:12px;margin:0 0 26px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 18px;box-shadow:var(--shadow)}
.stat .num{font-size:24px;font-weight:700}
.stat .lbl{color:var(--muted);font-size:12px}

.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:20px 22px;margin:0 0 22px;box-shadow:var(--shadow);scroll-margin-top:14px}
.detail-head{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.detail-head h2{margin:0;font-size:20px}
.kicker{color:var(--muted);font-size:11px;letter-spacing:.06em;text-transform:uppercase;font-weight:600}
.summary{font-size:15.5px}
.sec-h{font-size:13px;font-weight:700;color:var(--accent);margin:20px 0 6px;
  text-transform:uppercase;letter-spacing:.04em}
.map{background:var(--code-bg);border:1px solid var(--line);border-radius:10px;padding:12px;overflow:auto}
.map pre.mermaid{margin:0;text-align:center;background:none}
.map pre.mermaid.src{white-space:pre;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;text-align:left}

details.fc{border:1px solid var(--line);border-radius:10px;padding:0;margin:8px 0;background:var(--bg);overflow:hidden}
details.fc>summary{cursor:pointer;padding:11px 14px;font-weight:600;list-style:none;display:flex;gap:8px}
details.fc>summary::-webkit-details-marker{display:none}
details.fc>summary::before{content:"▶";color:var(--accent);font-size:11px;transform:translateY(2px)}
details.fc[open]>summary::before{content:"▼"}
.qlabel,.alabel{display:inline-block;min-width:16px;font-weight:800;color:var(--accent)}
.fa{padding:0 14px 12px 38px;color:var(--ink)}
.fa .alabel{color:var(--ok)}
.tags{display:inline-block;margin:0 14px 12px 38px;font-size:11px;color:var(--muted);
  background:var(--accent-soft);border-radius:20px;padding:2px 10px}
.hide{display:none!important}
.empty{color:var(--muted);font-style:italic}
.foot{color:var(--muted);font-size:12px;margin:30px 0 10px;text-align:center}

/* export standalone: nasconde chrome non pertinente */
body.standalone{background:var(--bg)}
body.standalone .wrap{max-width:900px;margin:0 auto;padding:30px 22px}
@media print{.side,.tools,.dl,.search{display:none!important}.layout{display:block}.main{max-width:none}}
@media (max-width:820px){.layout{grid-template-columns:1fr}.side{position:static;height:auto;border-right:none;border-bottom:1px solid var(--line)}}
"""

_JS = r"""
(function(){
  // ---- Mermaid (CDN, con fallback al sorgente se offline) ----
  var wantDark = (document.documentElement.getAttribute('data-theme')||
      (matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light'))==='dark';
  import('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs')
    .then(function(m){
      m.default.initialize({startOnLoad:false, theme: wantDark?'dark':'default', securityLevel:'loose'});
      return m.default.run({querySelector:'pre.mermaid'});
    })
    .catch(function(){
      document.querySelectorAll('pre.mermaid').forEach(function(p){ p.classList.add('src'); });
    });

  // ---- Download helper ----
  function download(filename, text, type){
    var blob=new Blob([text],{type:(type||'text/html')+';charset=utf-8'});
    var url=URL.createObjectURL(blob), a=document.createElement('a');
    a.href=url; a.download=filename; document.body.appendChild(a); a.click();
    setTimeout(function(){URL.revokeObjectURL(url); a.remove();},0);
  }
  function cssText(){ var e=document.getElementById('report-css'); return e?e.textContent:''; }
  function standalone(node, title){
    var clone=node.cloneNode(true);
    clone.querySelectorAll('.dl,.no-export').forEach(function(e){e.remove();});
    return '<!doctype html><html lang="it"><head><meta charset="utf-8">'+
      '<meta name="viewport" content="width=device-width,initial-scale=1"><title>'+
      title.replace(/[<>&]/g,'')+'</title><style>'+cssText()+'</style></head>'+
      '<body class="standalone"><div class="wrap">'+clone.outerHTML+'</div></body></html>';
  }

  // ---- Pulsanti «Scarica dettaglio» ----
  document.querySelectorAll('.dl[data-target]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var node=document.getElementById(btn.getAttribute('data-target'));
      if(!node) return;
      download(btn.getAttribute('data-name'), standalone(node, btn.getAttribute('data-title')||'dettaglio'));
    });
  });

  // ---- Scarica tutto (snapshot dell'intera pagina, SVG inclusi) ----
  var all=document.getElementById('dl-all');
  if(all) all.addEventListener('click', function(){
    download('report.html', '<!doctype html>\n'+document.documentElement.outerHTML);
  });

  // ---- Flashcard -> CSV (stile Anki) ----
  var csvBtn=document.getElementById('dl-csv');
  if(csvBtn) csvBtn.addEventListener('click', function(){
    var data=JSON.parse(document.getElementById('cards-data').textContent||'[]');
    function q(s){ return '"'+String(s==null?'':s).replace(/"/g,'""')+'"'; }
    var rows=data.map(function(c){return [c.front,c.back,c.tags,c.deck].map(q).join(',');});
    download('flashcards.csv', 'front,back,tags,deck\n'+rows.join('\n'), 'text/csv');
  });

  // ---- Tema ----
  var tt=document.getElementById('theme-toggle');
  if(tt) tt.addEventListener('click', function(){
    var cur=document.documentElement.getAttribute('data-theme');
    var next = cur==='dark' ? 'light' : (cur==='light' ? 'dark' :
      (matchMedia('(prefers-color-scheme:dark)').matches?'light':'dark'));
    document.documentElement.setAttribute('data-theme', next);
  });

  // ---- Ricerca nella sidebar ----
  var box=document.getElementById('search');
  if(box) box.addEventListener('input', function(){
    var q=box.value.trim().toLowerCase();
    document.querySelectorAll('.nav a[data-search]').forEach(function(a){
      a.classList.toggle('hide', q && a.getAttribute('data-search').indexOf(q)<0);
    });
  });

  // ---- Evidenzia voce attiva durante lo scroll ----
  var links=[].slice.call(document.querySelectorAll('.nav a[href^="#"]'));
  var map={}; links.forEach(function(a){ map[a.getAttribute('href').slice(1)]=a; });
  var obs=new IntersectionObserver(function(es){
    es.forEach(function(e){
      if(e.isIntersecting){
        links.forEach(function(a){a.classList.remove('active');});
        var a=map[e.target.id]; if(a) a.classList.add('active');
      }
    });
  },{rootMargin:'-10% 0px -80% 0px'});
  document.querySelectorAll('section[id]').forEach(function(s){obs.observe(s);});
})();
"""


# --------------------------------------------------------------- costruzione

def _flashcards_html(cards: List, prefix: str) -> str:
    parts = []
    for j, c in enumerate(cards):
        tags = f'<span class="tags">{_esc(c.tags)}</span>' if c.tags else ""
        parts.append(
            f'<details class="fc" id="{prefix}-fc-{j}">'
            f'<summary><span class="qlabel">Q</span>{_inline(c.front)}</summary>'
            f'<div class="fa"><span class="alabel">A</span> {_inline(c.back)}</div>'
            f"{tags}</details>"
        )
    return "\n".join(parts)


def _detail_section(idx: int, title: str, res: AnalysisResult) -> str:
    body: List[str] = []
    if res.summary:
        body.append(f'<p class="summary">{_inline(res.summary)}</p>')
    if res.technical_flow:
        body.append('<div class="sec-h">Flusso tecnico</div>')
        body.append(_md_to_html(res.technical_flow))
    if res.business_flow:
        body.append('<div class="sec-h">Flusso di business / dominio</div>')
        body.append(_md_to_html(res.business_flow))
    if res.notes_markdown:
        body.append('<div class="sec-h">Note</div>')
        body.append(_md_to_html(res.notes_markdown))
    mer = _clean_mermaid(res.mermaid)
    if mer:
        body.append('<div class="sec-h">Mappa del flusso</div>')
        body.append(f'<div class="map"><pre class="mermaid">{_esc(mer)}</pre></div>')
    if res.flashcards:
        body.append('<div class="sec-h">Flashcard</div>')
        body.append(_flashcards_html(res.flashcards, f"block-{idx}"))
    if not body:
        body.append('<p class="empty">Nessun contenuto per questo blocco.</p>')

    fname = f"{idx:02d}-{_slug(title)}.html"
    return (
        f'<section id="block-{idx}" class="card detail">'
        f'<div class="detail-head"><div>'
        f'<div class="kicker">Dettaglio</div>'
        f'<h2>{_esc(title)}</h2></div>'
        f'<button class="btn dl" data-target="block-{idx}" data-name="{fname}" '
        f'data-title="{_esc(title)}">⬇ Scarica dettaglio</button>'
        f"</div>{''.join(body)}</section>"
    )


def write_html_report(
    out_dir: str,
    *,
    run_title: str,
    deck: str,
    blocks: List[Tuple[str, AnalysisResult]],
    architecture: Optional[str] = None,
    meta: Optional[Dict[str, str]] = None,
) -> str:
    """Scrive l'unico `report.html` e ne ritorna il path.

    - `blocks`  : lista (titolo, AnalysisResult) — note/mappe/flashcard per blocco.
    - `architecture` : sorgente Mermaid dell'architettura macro (modalita' full).
    - `meta`    : coppie chiave->valore mostrate nella panoramica.
    """
    os.makedirs(out_dir, exist_ok=True)
    meta = meta or {}

    # --- aggregati per statistiche e CSV ---
    all_cards = []
    n_maps = 0
    for _title, res in blocks:
        if _clean_mermaid(res.mermaid):
            n_maps += 1
        for c in res.flashcards:
            all_cards.append({"front": c.front, "back": c.back, "tags": c.tags, "deck": deck})
    if architecture and _clean_mermaid(architecture):
        n_maps += 1

    cards_json = json.dumps(all_cards, ensure_ascii=False)

    # --- sidebar (indice) ---
    nav: List[str] = ['<a href="#panoramica" data-search="panoramica">Panoramica</a>']
    if architecture and _clean_mermaid(architecture):
        nav.append('<a href="#architettura" data-search="architettura architecture macro">Architettura macro</a>')
    detail_links: List[str] = []
    for idx, (title, _res) in enumerate(blocks):
        detail_links.append(
            f'<a href="#block-{idx}" data-search="{_esc(title.lower())}">{_esc(title)}</a>'
        )
    nav_details = ""
    if detail_links:
        nav_details = (
            '<div class="nav-group">Dettagli</div><div class="nav">'
            + "\n".join(detail_links) + "</div>"
        )
    nav_cards = ""
    if all_cards:
        nav_cards = '<div class="nav-group">Studio</div><div class="nav"><a href="#flashcards" data-search="flashcard studio">Flashcard</a></div>'

    # --- panoramica ---
    meta_html = "".join(
        f"<span><b>{_esc(k)}:</b> {_esc(v)}</span>" for k, v in meta.items()
    )
    stats_html = (
        f'<div class="stat"><div class="num">{len(blocks)}</div><div class="lbl">Dettagli</div></div>'
        f'<div class="stat"><div class="num">{len(all_cards)}</div><div class="lbl">Flashcard</div></div>'
        f'<div class="stat"><div class="num">{n_maps}</div><div class="lbl">Mappe</div></div>'
    )

    # --- corpo ---
    sections: List[str] = []
    sections.append(
        f'<section id="panoramica" class="card">'
        f'<div class="kicker">Report</div>'
        f'<h2 style="margin-top:2px">Panoramica</h2>'
        f'<div class="meta">{meta_html}</div>'
        f'<div class="stats">{stats_html}</div>'
        f'<p class="summary">Report di studio generato da CodeStudy. Usa l\'indice a '
        f'sinistra per navigare. Ogni dettaglio e ogni mazzo puo\' essere scaricato '
        f'singolarmente come file HTML autonomo tramite il pulsante «Scarica».</p>'
        f"</section>"
    )

    if architecture and _clean_mermaid(architecture):
        arch = _clean_mermaid(architecture)
        sections.append(
            f'<section id="architettura" class="card detail">'
            f'<div class="detail-head"><div><div class="kicker">Architettura</div>'
            f'<h2>Architettura macro</h2></div>'
            f'<button class="btn dl" data-target="architettura" data-name="00-architettura.html" '
            f'data-title="Architettura macro">⬇ Scarica dettaglio</button></div>'
            f'<div class="map"><pre class="mermaid">{_esc(arch)}</pre></div>'
            f"</section>"
        )

    for idx, (title, res) in enumerate(blocks):
        sections.append(_detail_section(idx, title, res))

    # --- sezione flashcard aggregata ---
    if all_cards:
        cards_all = []
        gi = 0
        for title, res in blocks:
            if not res.flashcards:
                continue
            cards_all.append(f'<div class="sec-h">{_esc(title)}</div>')
            for c in res.flashcards:
                tags = f'<span class="tags">{_esc(c.tags)}</span>' if c.tags else ""
                cards_all.append(
                    f'<details class="fc" id="all-fc-{gi}">'
                    f'<summary><span class="qlabel">Q</span>{_inline(c.front)}</summary>'
                    f'<div class="fa"><span class="alabel">A</span> {_inline(c.back)}</div>'
                    f"{tags}</details>"
                )
                gi += 1
        sections.append(
            f'<section id="flashcards" class="card detail">'
            f'<div class="detail-head"><div><div class="kicker">Studio</div>'
            f'<h2>Flashcard — {len(all_cards)} carte</h2></div>'
            f'<div class="tools">'
            f'<button class="btn" id="dl-csv">⬇ CSV (Anki)</button>'
            f'<button class="btn dl" data-target="flashcards" data-name="flashcards.html" '
            f'data-title="Flashcard">⬇ Scarica HTML</button></div></div>'
            f'<p class="summary no-export">Testano la ricostruzione del <b>flusso</b>, non '
            f'la memoria a pappagallo. Clicca una domanda per rivelare la risposta.</p>'
            f'{"".join(cards_all)}</section>'
        )

    # --- assemblaggio finale ---
    tools = (
        '<div class="tools no-export">'
        '<button class="btn primary" id="dl-all">⬇ Scarica tutto</button>'
        '<button class="btn" onclick="window.print()">🖨 Stampa / PDF</button>'
        '<button class="btn" id="theme-toggle">◐ Tema</button>'
        "</div>"
    )
    side = (
        '<aside class="side">'
        f'<h1>{_esc(run_title)}</h1>'
        f'<p class="sub">{_esc(meta.get("Generato", ""))}</p>'
        '<input id="search" class="search" type="search" placeholder="Cerca nel report…">'
        '<div class="nav-group">Report</div><div class="nav">'
        + "\n".join(nav) + "</div>"
        + nav_details + nav_cards
        + "</aside>"
    )
    main = (
        '<main class="main">'
        f'<div class="topbar"><h1 class="title">Report di studio</h1>{tools}</div>'
        + "\n".join(sections)
        + '<div class="foot">Generato da CodeStudy — report autonomo, navigabile e scaricabile.</div>'
        + "</main>"
    )

    doc = (
        '<!doctype html><html lang="it"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(run_title)} — CodeStudy</title>"
        f'<style id="report-css">{_CSS}</style></head><body>'
        f'<div class="layout">{side}{main}</div>'
        f'<script type="application/json" id="cards-data">{cards_json}</script>'
        f'<script type="module">{_JS}</script>'
        "</body></html>"
    )

    path = os.path.join(out_dir, "report.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path
