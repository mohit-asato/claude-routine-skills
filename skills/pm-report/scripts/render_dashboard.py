#!/usr/bin/env python3
"""
Render the Daily Ops dashboard as a self-contained HTML artifact.

Usage:
    python render_dashboard.py --am am.json [--pm pm.json] --out dashboard.html

Input files are the raw `daily_briefs` documents from Mongo (type "am" / "pm").
With only --am, renders MORNING mode (light palette, the day's plan).
With --pm too, renders EVENING mode (dark palette, items checked off,
unplanned work appended, counts in the stat row).

No history UI — artifact version history is handled by Claude itself.
"""
import argparse, html, json, sys
from datetime import datetime

# ---------------------------------------------------------------- palettes
LIGHT = {
    "bg": "#f7f6f1", "card": "#fffefb", "border": "#e8e6df", "hairline": "#e8e6df",
    "text": "#12110f", "secondary": "#56544d", "muted": "#92908a", "faint": "#b0ada5",
    "fire": "#c8402f", "today": "#c9721c", "radar": "#a8952c",
    "blue": "#2b6bb8", "green": "#2f7d3a", "purple": "#7a5cb5",
    "chip_bg": "rgba(122,92,181,.12)",
}
DARK = {
    "bg": "#12110f", "card": "#1a1917", "border": "#2b2926", "hairline": "#26241f",
    "text": "#f7f6f1", "secondary": "#b8b5ac", "muted": "#85827a", "faint": "#6b6961",
    "fire": "#e35d4a", "today": "#e08c33", "radar": "#c4ae3d",
    "blue": "#5a9ae0", "green": "#4fa85e", "purple": "#a78bd8",
    "chip_bg": "rgba(167,139,216,.16)",
}

STATUS_ORDER = {"untouched": 0, "pending": 0, "progressed": 1, "closed": 2, "done": 2}


def esc(s):
    return html.escape(str(s if s is not None else ""))


def day_label(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%A, %b %-d")
    except Exception:
        return iso


def tier_color(p, tier):
    return {"fire": p["fire"], "today": p["today"], "radar": p["radar"]}.get(tier, p["radar"])


def build_rows(am_doc, pm_doc):
    """Return (rows, counts). In evening mode rows carry status + unplanned."""
    am_items = (am_doc or {}).get("items", []) or []
    if not pm_doc:
        rows = []
        for it in am_items:
            rows.append({
                "title": it.get("title", ""),
                "line": it.get("ticketGist") or it.get("reasonAdded") or "",
                "why": it.get("reasonAdded", ""),
                "meta": meta_line(it),
                "url": (it.get("source") or {}).get("url", ""),
                "tier": it.get("tier", "radar"),
                "status": "open",
                "unplanned": False,
                "flags": it.get("flags", []) or [],
            })
        return rows, None

    am_ids = {i.get("itemId") for i in am_items}
    rows = []
    for it in pm_doc.get("items", []) or []:
        status = it.get("status", "untouched")
        rows.append({
            "title": it.get("title", ""),
            "line": it.get("eveningNote") or it.get("ticketGist") or "",
            "why": it.get("ticketGist", ""),
            "meta": meta_line(it),
            "url": (it.get("source") or {}).get("url", ""),
            "tier": it.get("tier", "radar"),
            "status": status,
            "unplanned": it.get("itemId") not in am_ids,
            "flags": it.get("flags", []) or [],
        })
    rows.sort(key=lambda r: STATUS_ORDER.get(r["status"], 0))
    counts = {
        "closed": sum(1 for r in rows if r["status"] in ("closed", "done")),
        "moved": sum(1 for r in rows if r["status"] == "progressed"),
        "open": sum(1 for r in rows if r["status"] in ("untouched", "pending")),
    }
    return rows, counts


def meta_line(it):
    bits = []
    src = (it.get("source") or {}).get("type")
    if src:
        bits.append({"jira": "Jira", "github": "GitHub", "slack": "Slack"}.get(src, src))
    if it.get("jiraStatus"):
        bits.append(it["jiraStatus"])
    age = it.get("ageDays")
    if isinstance(age, int) and age > 0:
        bits.append(f"{age}d")
    return " · ".join(bits)


def render(am_doc, pm_doc, generated_display):
    evening = pm_doc is not None
    p = DARK if evening else LIGHT
    doc = pm_doc if evening else am_doc
    rows, counts = build_rows(am_doc, pm_doc)

    headline = doc.get("headline", "")
    date_lbl = day_label(doc.get("date", ""))
    mode_lbl = "Evening" if evening else "Morning"

    # hero = first still-open row, else first row
    hero = next((r for r in rows if r["status"] in ("open", "untouched", "pending")), None) or (rows[0] if rows else None)

    # ---- hero block
    if hero:
        accent = tier_color(p, hero["tier"])
        hero_title = (f'<a href="{esc(hero["url"])}" target="_blank" rel="noopener">{esc(hero["title"])}</a>'
                      if hero["url"] else esc(hero["title"]))
        hero_html = f'''
  <div class="hero-outer">
    <div class="hero-inner" style="border-left:5px solid {accent};background:{hero_accent_tint(accent)}">
      <div class="hero-label mono" style="color:{accent}">{"Still needs you" if evening else "Do this first"}</div>
      <div class="hero-title">{hero_title}</div>
      <div class="hero-line">{esc(hero["line"])}</div>
      <div class="hero-meta mono">{esc(hero["meta"])}</div>
    </div>
  </div>'''
    else:
        hero_html = ""

    # ---- stat row (evening only)
    stat_html = ""
    if evening and counts:
        stat_html = f'''
  <div class="stat-grid">
    <div class="stat-tile"><div class="stat-n mono" style="color:{p["green"]}">{counts["closed"]}</div><div class="stat-l">closed</div></div>
    <div class="stat-tile"><div class="stat-n mono" style="color:{p["blue"]}">{counts["moved"]}</div><div class="stat-l">moved</div></div>
    <div class="stat-tile"><div class="stat-n mono" style="color:{p["fire"]}">{counts["open"]}</div><div class="stat-l">still open</div></div>
  </div>'''
    elif not evening:
        stat_html = '<div class="awaiting-note mono">Morning list. Outcomes fill in after the evening run.</div>'

    # ---- rows
    row_html = []
    for r in rows:
        done = r["status"] in ("closed", "done")
        moved = r["status"] == "progressed"
        if done:
            box, box_color = "&#10003;", p["green"]
        elif moved:
            box, box_color = "&#9679;", p["blue"]
        else:
            box, box_color = "", tier_color(p, r["tier"])
        title = (f'<a href="{esc(r["url"])}" target="_blank" rel="noopener">{esc(r["title"])}</a>'
                 if r["url"] else esc(r["title"]))
        badge = '<span class="chip chip-unplanned">unplanned</span>' if r["unplanned"] else ""
        flag_badges = "".join(
            f'<span class="chip chip-flag">{esc(f)}</span>'
            for f in r["flags"] if f in ("stalling", "missingFixVersion")
        )
        row_html.append(f'''
      <li class="row{' row-done' if done else ''}">
        <span class="box" style="border-color:{box_color};color:{box_color}{';background:' + box_color + '1f' if (done or moved) else ''}">{box}</span>
        <div class="row-body">
          <div class="row-title">{title}{badge}{flag_badges}</div>
          <div class="row-line">{esc(r["line"])}</div>
          <div class="row-meta mono">{esc(r["meta"])}</div>
        </div>
      </li>''')
    rows_joined = "".join(row_html) or '<li class="row"><div class="row-body"><div class="row-line">Nothing on the list.</div></div></li>'

    gaps = doc.get("dataGaps") or []
    gaps_html = ""
    if gaps:
        gaps_html = ('<div class="gaps mono">' +
                     "".join(f"<div>&#9888; {esc(g)}</div>" for g in gaps) + "</div>")

    return TEMPLATE.format(
        p=p, mode=mode_lbl, date_lbl=esc(date_lbl), generated=esc(generated_display),
        headline=esc(headline), hero=hero_html, stats=stat_html, rows=rows_joined,
        gaps=gaps_html, list_heading="Today" if evening else "On your plate",
        count=len(rows),
    )


def hero_accent_tint(accent):
    return accent + "14"  # ~8% alpha in hex


TEMPLATE = """<!DOCTYPE html>
<script type="application/json" id="cowork-artifact-meta">
{{
  "name": "Daily Ops Dashboard",
  "schemaVersion": 1,
  "description": "Mohit's daily ops board, regenerated by the am-report and pm-report skills from the daily_briefs Mongo records. Morning runs publish the day's plan in a light palette; evening runs republish in a dark palette with items checked off and unplanned work appended. Use the artifact version history to see past days.",
  "mcpTools": [],
  "mcpServerNames": []
}}
</script>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Ops — {mode}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin:0; padding:0; background:{p[bg]}; }}
  body {{ font-family:Archivo, system-ui, -apple-system, sans-serif; -webkit-font-smoothing:antialiased; color:{p[text]}; }}
  a {{ color:{p[text]}; }}
  .mono {{ font-family:'JetBrains Mono', ui-monospace, monospace; }}

  .page {{ min-height:100vh; padding:40px 20px 72px; }}
  .wrap {{ max-width:680px; margin:0 auto; }}

  .topbar {{ margin-bottom:26px; }}
  .date-label {{ font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:{p[muted]}; margin-bottom:6px; }}
  .topbar h1 {{ font-size:30px; line-height:1.1; margin:0; letter-spacing:-.025em; font-weight:700; }}
  .mode-chip {{ display:inline-block; font-size:11px; letter-spacing:.1em; text-transform:uppercase; font-weight:700;
    border:1px solid {p[border]}; border-radius:999px; padding:4px 10px; color:{p[secondary]}; margin-left:10px; vertical-align:6px; }}

  .headline {{ font-size:15.5px; line-height:1.5; color:{p[secondary]}; margin-bottom:24px; max-width:56ch; }}

  .hero-outer {{ background:{p[card]}; border:1px solid {p[border]}; border-radius:18px; padding:4px; margin-bottom:24px; }}
  .hero-inner {{ border-radius:15px; padding:22px 24px 24px; }}
  .hero-label {{ font-size:11px; letter-spacing:.14em; text-transform:uppercase; font-weight:700; margin-bottom:12px; }}
  .hero-title {{ font-size:22px; line-height:1.25; letter-spacing:-.02em; font-weight:600; margin-bottom:8px; }}
  .hero-title a {{ text-decoration:none; border-bottom:2px solid {p[border]}; }}
  .hero-line {{ font-size:15.5px; line-height:1.45; color:{p[secondary]}; max-width:46ch; }}
  .hero-meta {{ font-size:11.5px; color:{p[muted]}; margin-top:12px; }}

  .stat-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin-bottom:32px; }}
  .stat-tile {{ background:{p[card]}; border:1px solid {p[border]}; border-radius:14px; padding:16px 16px 14px; }}
  .stat-n {{ font-size:34px; font-weight:500; line-height:1; letter-spacing:-.03em; }}
  .stat-l {{ font-size:12.5px; color:{p[secondary]}; margin-top:8px; font-weight:500; }}
  .awaiting-note {{ font-size:12px; color:{p[muted]}; margin-bottom:32px; padding:14px 16px;
    border:1px dashed {p[border]}; border-radius:12px; }}

  .section-head {{ display:flex; align-items:baseline; gap:10px; margin-bottom:2px; }}
  .section-head h2 {{ font-size:15px; font-weight:700; letter-spacing:-.01em; margin:0; }}
  .section-count {{ font-size:12px; color:{p[muted]}; }}

  ul.rows {{ list-style:none; margin:0; padding:0; }}
  .row {{ display:flex; gap:14px; padding:18px 0; border-top:1px solid {p[hairline]}; align-items:flex-start; }}
  .box {{ width:19px; height:19px; border-radius:6px; border:1.5px solid; flex:0 0 auto; margin-top:2px;
    display:flex; align-items:center; justify-content:center; font-size:12px; line-height:1; font-weight:700; }}
  .row-body {{ flex:1; min-width:0; }}
  .row-title {{ font-size:17px; line-height:1.3; font-weight:600; letter-spacing:-.015em; }}
  .row-title a {{ text-decoration:none; }}
  .row-line {{ font-size:14.5px; line-height:1.45; color:{p[secondary]}; margin-top:5px; }}
  .row-meta {{ font-size:11.5px; color:{p[muted]}; margin-top:7px; }}
  .row-done .row-title {{ color:{p[muted]}; text-decoration:line-through; text-decoration-color:{p[green]}; }}
  .row-done .row-line {{ color:{p[muted]}; }}

  .chip {{ font-size:10px; letter-spacing:.09em; text-transform:uppercase; font-weight:700;
    border-radius:5px; padding:3px 6px; margin-left:8px; vertical-align:2px; white-space:nowrap; }}
  .chip-unplanned {{ color:{p[purple]}; background:{p[chip_bg]}; }}
  .chip-flag {{ color:{p[today]}; background:{p[today]}1f; }}

  .gaps {{ margin-top:28px; font-size:11.5px; line-height:1.6; color:{p[muted]};
    border:1px dashed {p[border]}; border-radius:12px; padding:12px 14px; }}
  .gaps div + div {{ margin-top:6px; }}

  footer {{ margin-top:30px; font-size:11px; color:{p[faint]}; text-align:center; letter-spacing:.04em; line-height:1.7; }}
</style>
</head>
<body>
<div class="page"><div class="wrap">

  <div class="topbar">
    <div class="date-label mono">{date_lbl} · {generated}</div>
    <h1>Daily Ops<span class="mode-chip mono">{mode}</span></h1>
  </div>

  <div class="headline">{headline}</div>
{hero}
{stats}
  <div class="section-head">
    <h2>{list_heading}</h2><span class="section-count mono">{count}</span>
  </div>
  <ul class="rows">{rows}</ul>
{gaps}
  <footer>regenerated by the am / pm report skills · past days live in this artifact's version history</footer>

</div></div>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--am", required=True, help="path to the day's type:am JSON document")
    ap.add_argument("--pm", help="path to the day's type:pm JSON document (switches to evening mode)")
    ap.add_argument("--out", required=True, help="path to write the HTML to")
    ap.add_argument("--generated", default="", help="display string for when this was generated")
    a = ap.parse_args()

    with open(a.am) as f:
        am_doc = json.load(f)
    pm_doc = None
    if a.pm:
        with open(a.pm) as f:
            pm_doc = json.load(f)

    generated = a.generated or (pm_doc or am_doc).get("generatedAt", "")
    out = render(am_doc, pm_doc, generated)
    with open(a.out, "w") as f:
        f.write(out)
    print(f"wrote {a.out} ({'evening' if pm_doc else 'morning'} mode, {len(out)} bytes)")


if __name__ == "__main__":
    sys.exit(main())
