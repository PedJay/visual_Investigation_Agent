"""Presentation helpers: HTML fragments for the UI and Markdown/CSV for export.
All model-produced text is HTML-escaped before it reaches unsafe_allow_html.

Design: a survey plate under night light. Ink-navy ground, ice text, one sky accent.
Mint / amber / coral are reserved for status (verified / inferred / risk), never decoration."""
import csv, html, io

E = lambda s: html.escape(str(s if s is not None else ""))

MINT, SKY, AMBER, CORAL = "#5eead4", "#7dd3fc", "#fbbf24", "#fb7185"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500..800&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
@property --p{syntax:'<number>';inherits:true;initial-value:0}

:root{--ink:#060d1a;--panel:#0a1528;--line:rgba(125,170,235,.2);--text:#d6e4f7;--muted:rgba(190,210,240,.64);
      --sky:#7dd3fc;--mint:#5eead4;--amber:#fbbf24;--coral:#fb7185;--display:'Bricolage Grotesque','IBM Plex Sans',system-ui,sans-serif}
html,body,[class*="css"],.stApp{font-family:'IBM Plex Sans',system-ui,sans-serif}
.stApp{background:radial-gradient(1100px 520px at 88% -8%,rgba(56,130,246,.16),transparent 62%) no-repeat,var(--ink)}
.block-container{padding-top:2.2rem;max-width:1240px}
[data-testid="stSidebar"]{background:#071020;border-right:1px solid var(--line)}
h1,h2,h3{font-family:var(--display);letter-spacing:-.01em}
:focus-visible{outline:2px solid var(--sky)!important;outline-offset:2px}

/* Streamlit widgets, kept minimal so they survive version changes */
.stButton>button{border-radius:6px;border:1px solid rgba(125,170,235,.38);background:rgba(18,38,72,.55);color:var(--text);font-weight:500;transition:border-color .15s,background .15s}
.stButton>button:hover{border-color:var(--sky);background:rgba(30,60,110,.6);color:#fff}
.stButton>button[kind="primary"]{background:#5ab0ff;border-color:#5ab0ff;color:#04101f;font-weight:600}
.stButton>button[kind="primary"]:hover{background:#8cc8ff;border-color:#8cc8ff;color:#04101f}
.stTabs [data-baseweb="tab-list"]{gap:22px;border-bottom:1px solid var(--line)}
.stTabs [data-baseweb="tab"]{color:var(--muted)}
.stTabs [aria-selected="true"]{color:var(--sky)}
.stTabs [data-baseweb="tab-highlight"]{background-color:var(--sky)}
[data-testid="stMetric"]{border-left:2px solid rgba(125,211,252,.5);padding-left:12px}
[data-testid="stMetricLabel"]{color:var(--muted)}

/* masthead */
.mast{margin:0 0 6px}
.mast-t{font:700 1.7rem/1.1 var(--display);letter-spacing:-.015em}
.mast-s{color:var(--muted);margin-top:4px;max-width:60ch}

/* survey plate (the hero) */
.plate{position:relative;display:flex;flex-wrap:wrap;gap:22px 34px;align-items:center;justify-content:space-between;
  border:1px solid var(--line);border-radius:6px;padding:28px 30px;margin:6px 0 18px;
  background:
    radial-gradient(760px 260px at 92% -20%,rgba(56,130,246,.24),transparent 60%),
    linear-gradient(rgba(125,170,235,.065) 1px,transparent 1px) 0 0/28px 28px,
    linear-gradient(90deg,rgba(125,170,235,.065) 1px,transparent 1px) 0 0/28px 28px,var(--panel)}
.plate::before,.plate::after{content:"";position:absolute;width:14px;height:14px;border:2px solid var(--sky);opacity:.85}
.plate::before{top:-1px;left:-1px;border-right:0;border-bottom:0}
.plate::after{bottom:-1px;right:-1px;border-left:0;border-top:0}
.plate-l{flex:1 1 280px;min-width:0}
.plate-title{font:700 clamp(1.7rem,3.2vw,2.5rem)/1.08 var(--display);letter-spacing:-.018em;overflow-wrap:anywhere}
.plate-subject{color:var(--muted);margin-top:6px}
.plate-loc{display:flex;align-items:center;gap:9px;margin:14px 0 14px;font-weight:500}
.plate-loc::before{content:"";width:9px;height:9px;border-radius:50%;border:2px solid var(--sky);box-shadow:0 0 0 4px rgba(125,211,252,.14);flex:none}
.plate-r{display:flex;gap:26px;flex:none}

/* instrument dials: the one memorable element */
.dialwrap{text-align:center;width:124px}
.dial{--size:116px;position:relative;width:var(--size);height:var(--size);margin:0 auto;display:grid;place-items:center}
.dial::before{content:"";position:absolute;inset:0;border-radius:50%;
  background:conic-gradient(var(--c) calc(var(--p)*1%),rgba(125,170,235,.17) 0);
  -webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 9px),#000 calc(100% - 8px));
          mask:radial-gradient(farthest-side,transparent calc(100% - 9px),#000 calc(100% - 8px));
  animation:sweep 1.1s cubic-bezier(.2,.7,.2,1) both}
@keyframes sweep{from{--p:0}}
@media (prefers-reduced-motion:reduce){.dial::before{animation:none}}
.dial-in{position:relative;line-height:1.05}
.dial-in b{display:block;font:700 1.9rem/1 var(--display)}
.dial-in small{color:var(--muted);font-size:.72rem}
.dial-cap{margin-top:8px;font-size:.8rem;line-height:1.3}
.dial-cap span{display:block;font-weight:600;color:var(--c)}

/* status pills and rails */
.pill{display:inline-flex;align-items:center;gap:6px;padding:2px 10px 2px 8px;border-radius:999px;font-size:.76rem;font-weight:600;margin:0 6px 4px 0;white-space:nowrap;border:1px solid transparent}
.pill::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
.p-observed{color:var(--sky);background:rgba(125,211,252,.1);border-color:rgba(125,211,252,.3)}
.p-inferred{color:var(--amber);background:rgba(251,191,36,.09);border-color:rgba(251,191,36,.3)}
.p-verified{color:var(--mint);background:rgba(94,234,212,.09);border-color:rgba(94,234,212,.3)}
.p-bad{color:var(--coral);background:rgba(251,113,133,.1);border-color:rgba(251,113,133,.32)}
.p-none{color:var(--muted);background:rgba(125,170,235,.08);border-color:var(--line)}
.legend{display:flex;flex-wrap:wrap;align-items:center;gap:4px 6px;font-size:.82rem;color:var(--muted);margin:8px 0 4px}
.legend .pill{margin-left:10px}

/* open sections instead of boxed cards */
.sec{padding:16px 0 6px;border-top:1px solid var(--line)}
.sec h4{font:600 1.02rem/1.2 var(--display);color:#bfd9f8;margin:0 0 8px;letter-spacing:0}
.sec p{margin:0;line-height:1.6;max-width:72ch}
.sec ul{margin:0 0 0 18px;line-height:1.6;max-width:72ch}
.clue{display:flex;gap:10px;align-items:flex-start;border-left:3px solid var(--rail,var(--line));padding:6px 0 6px 12px;margin:5px 0}
.clue .pill{margin:2px 0 0;flex:none;min-width:92px}
.clue span.t{line-height:1.5;max-width:68ch}
.r-observed{--rail:var(--sky)}.r-inferred{--rail:var(--amber)}.r-verified{--rail:var(--mint)}
.alt{display:grid;grid-template-columns:minmax(120px,max-content) 1fr;gap:4px 16px;padding:8px 0;border-bottom:1px solid rgba(125,170,235,.12)}
.alt:last-child{border-bottom:none}
.alt b{font-weight:600}
.src{padding:6px 0;border-bottom:1px solid rgba(125,170,235,.12)}
.src:last-child{border-bottom:none}
.src a{color:var(--sky);text-decoration:none}.src a:hover{text-decoration:underline}
.src small{color:var(--muted)}
.note{font-size:.8rem;color:var(--muted);margin-top:8px}
.warn{border-left:3px solid var(--amber);background:rgba(251,191,36,.08);padding:9px 14px;border-radius:0 4px 4px 0;font-size:.86rem;margin:8px 0}
.thumbcap{font-size:.8rem;margin:4px 0 8px;min-height:44px;line-height:1.35}
</style>
"""

STATUS_LABEL = {"observed": "Observed", "inferred": "Inferred", "verified": "Verified",
                "unidentified": "Unidentified", "undetermined": "Undetermined", "not_available": "Not available"}

def pill(status, prefix=None):
    s = (status or "").lower()
    cls = {"observed": "p-observed", "inferred": "p-inferred", "verified": "p-verified"}.get(s, "p-none")
    label = STATUS_LABEL.get(s, s or "Unknown")
    return f'<span class="pill {cls}">{E(prefix + ": " + label.lower() if prefix else label)}</span>'

def masthead():
    return ('<div class="mast"><div class="mast-t">Visual Investigator</div>'
            '<div class="mast-s">Evidence first. Every finding is marked as seen, inferred or verified.</div></div>')

def legend():
    return ('<div class="legend">Each finding is marked' + pill("observed") + "seen in the image"
            + pill("inferred") + "reasoned, not confirmed" + pill("verified") + "backed by a retrieved source</div>")

def _tone(p, high_is_good):
    good = p if high_is_good else 100 - p
    return MINT if good >= 70 else AMBER if good >= 40 else CORAL

def dial(label, pct, big, small, caption, high_is_good=True):
    p = 0 if pct is None else max(0, min(100, pct))
    c = _tone(p, high_is_good) if pct is not None else SKY
    return (f'<div class="dialwrap" style="--c:{c}"><div class="dial" style="--p:{p}">'
            f'<div class="dial-in"><b>{E(big)}</b><small>{E(small)}</small></div></div>'
            f'<div class="dial-cap">{E(label)}<span>{E(caption)}</span></div></div>')

def location_line(loc):
    parts = [loc.get("locality"), loc.get("region_city"), loc.get("country")]
    return ", ".join(E(p) for p in parts if p) or "Location could not be determined"

def hero_html(r):
    lm, loc, conf, au = r["identified_landmark"], r["probable_location"], r["location_confidence"], r["authenticity"]
    title = E(lm.get("name")) if lm.get("name") else "Landmark not identified"
    score, p = conf.get("score"), au.get("ai_generated_probability")
    verdict = {"likely_real": "Likely a real photo", "uncertain": "Authenticity uncertain",
               "likely_ai_generated": "Likely AI-generated"}.get(au.get("verdict"), "")
    vcls = {"likely_real": "p-verified", "uncertain": "p-inferred", "likely_ai_generated": "p-bad"}.get(au.get("verdict"), "p-none")
    dials = (dial("Location confidence", score, score if score is not None else "?", "of 100", str(conf.get("level") or "undetermined"), True)
             + dial("AI-generated", p, f"{p}%" if p is not None else "?", "probability", f'{au.get("confidence", "low")} confidence', False))
    return (f'<div class="plate"><div class="plate-l"><div class="plate-title">{title}</div>'
            f'<div class="plate-subject">{E(r.get("primary_subject"))}</div>'
            f'<div class="plate-loc">{location_line(loc)}</div>'
            f'{pill(lm.get("status"), "Landmark")}{pill(loc.get("status"), "Location")}<span class="pill {vcls}">{E(verdict)}</span></div>'
            f'<div class="plate-r">{dials}</div></div>')

def card(title, body_html):
    """An open section: hairline above, heading in sentence case."""
    return f'<div class="sec"><h4>{E(title)}</h4>{body_html}</div>'

def clues_html(r):
    rows = []
    for c in r["visual_clues"]:
        if not isinstance(c, dict):
            continue
        s = c.get("status") if c.get("status") in {"observed", "inferred", "verified"} else "inferred"
        rows.append(f'<div class="clue r-{s}">{pill(s)}<span class="t">{E(c.get("clue"))}</span></div>')
    return card("Visual clues", "".join(rows) or "<p>No clues recorded.</p>")

def alternatives_html(r):
    mark = {"kept": "Kept", "rejected": "Ruled out", "unresolved": "Unresolved"}
    rows = [f'<div class="alt"><b>{E(a.get("label"))}<br><span style="font-weight:500;color:var(--muted)">{mark.get(a.get("outcome"), "")}</span></b>'
            f'<span>{E(a.get("why"))}</span></div>' for a in r["alternatives_considered"] if isinstance(a, dict)]
    return card("Hypotheses considered", "".join(rows)) if rows else ""

def authenticity_html(r):
    au = r["authenticity"]
    items = "".join(f"<li>{E(i)}</li>" for i in au.get("indicators", []))
    note = f'<p style="margin-top:8px"><i>{E(au["notes"])}</i></p>' if au.get("notes") else ""
    body = (f"<ul>{items}</ul>" if items else "<p>No indicators recorded.</p>") + note
    body += '<div class="note">A probabilistic visual judgement, not a forensic result. Metadata is weak evidence either way.</div>'
    return card("Is this a real photograph?", body)

def context_html(r):
    c = r["historical_cultural_context"]
    text = E(c.get("text")) if c.get("text") else "No verified historical context is available for this image."
    return card("History and cultural context", f'<div>{pill(c.get("status"))}</div><p style="margin-top:6px">{text}</p>')

def sources_html(r):
    rows = []
    for s in r["sources"]:
        url = str(s.get("url", ""))
        if not url.startswith(("http://", "https://")):
            continue
        rows.append(f'<div class="src"><a href="{E(url)}" target="_blank" rel="noopener noreferrer">'
                    f'{E(s.get("title") or url)}</a><br><small>{E(s.get("supports"))}</small></div>')
    return card("Sources", "".join(rows) or "<p>No external sources were used. Nothing here is marked verified.</p>")

def warnings_html(r):
    return "".join(f'<div class="warn">{E(w)}</div>' for w in r.get("_warnings", []))

def short_row(name, r):
    lm, loc = r["identified_landmark"], r["probable_location"]
    return {"image": name, "landmark": lm.get("name") or "— not identified —",
            "status": lm.get("status"), "country": loc.get("country"), "region/city": loc.get("region_city"),
            "confidence": r["location_confidence"].get("level"), "score": r["location_confidence"].get("score"),
            "AI-generated %": r["authenticity"].get("ai_generated_probability"),
            "verdict": r["authenticity"].get("verdict"), "sources": len(r["sources"])}

def thumb_caption(r):
    if not r:
        return '<span class="pill p-none">Not analysed</span>'
    lm, conf = r["identified_landmark"], r["location_confidence"]
    nm = E(lm.get("name") or "Unidentified")
    return f'<b>{nm}</b><br>{pill(lm.get("status"))}<span class="pill p-none">{E(str(conf.get("level") or "").capitalize())} confidence</span>'


# ------------------------------------------------------------------------ exports
def report_to_markdown(r: dict) -> str:
    L = []
    loc, lm, conf = r["probable_location"], r["identified_landmark"], r["location_confidence"]
    au, ctx = r["authenticity"], r["historical_cultural_context"]
    L.append(f"**Image Summary:** {r['image_summary']}\n")
    L.append(f"**Primary Subject:** {r['primary_subject']}\n")
    L.append(f"**Identified Landmark:** {lm.get('name') or 'Not identifiable from evidence'} ({lm.get('status')})\n")
    L.append(f"**Probable Location:** {', '.join(x for x in [loc.get('locality'), loc.get('region_city'), loc.get('country')] if x) or 'undetermined'} ({loc.get('status')})\n")
    L.append(f"**Location Confidence:** {conf.get('level')} ({conf.get('score')}/100) — {conf.get('rationale', '')}\n")
    L.append("**Important Visual Clues:**")
    L += [f"- [{c.get('status')}] {c.get('clue')}" for c in r["visual_clues"]]
    L.append(f"\n**Image Authenticity:** {au.get('verdict')} — AI-generated probability {au.get('ai_generated_probability')}% (confidence: {au.get('confidence')})")
    L += [f"- {i}" for i in au.get("indicators", [])]
    if r["alternatives_considered"]:
        L.append("\n**Hypotheses Considered:**")
        L += [f"- {a.get('label')} → {a.get('outcome')}: {a.get('why')}" for a in r["alternatives_considered"]]
    L.append(f"\n**Historical & Cultural Context** ({ctx.get('status')}): {ctx.get('text') or 'Not available'}\n")
    L.append(f"**Reasoning & Evidence:** {r['reasoning_evidence']}\n")
    if r["additional_observations"]:
        L.append("**Additional Observations:**")
        L += [f"- {o}" for o in r["additional_observations"]]
    if r["sources"]:
        L.append("\n**Sources / References:**")
        L += [f"- [{s.get('title')}]({s.get('url')}) — {s.get('supports', '')}" for s in r["sources"]]
    if r.get("_warnings"):
        L.append("\n**Validation notes:** " + "; ".join(r["_warnings"]))
    return "\n".join(L)

def reports_to_markdown(reports: dict) -> str:
    out = ["# Visual Investigation Reports\n"]
    for name, r in reports.items():
        out.append(f"\n---\n\n## {name}\n\n{report_to_markdown(r)}")
    return "\n".join(out)

def reports_to_csv(reports: dict) -> str:
    rows = [short_row(n, r) for n, r in reports.items()]
    if not rows:
        return ""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()
