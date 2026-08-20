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

# Source glyphs. Short label + the palette key that tints it, so one table
# serves both themes. This order is also the order of the count strip.
SOURCES = [
    ("jira",   "JIRA", "blue"),
    ("github", "GH",   "purple"),
    ("slack",  "SLK",  "green"),
]
SOURCE_LABEL = {k: (lbl, tint) for k, lbl, tint in SOURCES}


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
                "src": (it.get("source") or {}).get("type", ""),
                "refId": (it.get("source") or {}).get("refId", ""),
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
            "src": (it.get("source") or {}).get("type", ""),
            "refId": (it.get("source") or {}).get("refId", ""),
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

    # The H1 is whatever the model named today's board. The <title> and the
    # artifact name deliberately stay "Daily Ops" - renaming those would make
    # each day look like a different artifact in the gallery and the tab bar.
    board_title = (doc.get("boardTitle") or "Daily Ops").strip()

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
        # Morning has no closed/moved to count, so the tiles mirror the
        # pickability tiers instead - same numbers the ranking already uses.
        tiers = {"fire": 0, "today": 0, "radar": 0}
        for r in rows:
            if r.get("tier") in tiers:
                tiers[r["tier"]] += 1
        stat_html = f'''
  <div class="stat-grid">
    <div class="stat-tile"><div class="stat-n mono" style="color:{p["fire"]}">{tiers["fire"]}</div><div class="stat-l">on fire</div></div>
    <div class="stat-tile"><div class="stat-n mono" style="color:{p["today"]}">{tiers["today"]}</div><div class="stat-l">today</div></div>
    <div class="stat-tile"><div class="stat-n mono" style="color:{p["radar"]}">{tiers["radar"]}</div><div class="stat-l">on radar</div></div>
  </div>
  <div class="awaiting-note mono">Morning list. Outcomes fill in after the evening run.</div>''' 

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
        pill = source_pill(p, r.get("src", ""))
        title = (f'<a href="{esc(r["url"])}" target="_blank" rel="noopener">{esc(r["title"])}</a>'
                 if r["url"] else esc(r["title"]))
        badge = '<span class="chip chip-unplanned">unplanned</span>' if r["unplanned"] else ""
        flag_badges = "".join(
            f'<span class="chip chip-flag">{esc(f)}</span>'
            for f in r["flags"] if f in ("stalling", "missingFixVersion")
        )
        row_html.append(f'''
      <li class="row{' row-done' if done else ''}" data-src="{r.get('src','')}">
        <span class="box" style="border-color:{box_color};color:{box_color}{';background:' + box_color + '1f' if (done or moved) else ''}">{box}</span>
        <div class="row-body">
          <div class="row-title">{pill}{title}{badge}{flag_badges}</div>
          <div class="row-line">{esc(r["line"])}</div>
          <div class="row-meta mono">{esc(r["meta"])}</div>
        </div>
      </li>''')
    rows_joined = "".join(row_html) or '<li class="row"><div class="row-body"><div class="row-line">Nothing on the list.</div></div></li>'

    # ---- new blocks: progress scorecard (evening), no-destination, source strip
    score_html = progress_block(p, counts, doc.get("scorecard")) if evening else ""
    dest_html = no_destination_drawer(p, rows)
    strip_html = source_tabs(p, rows)

    gaps = doc.get("dataGaps") or []
    gaps_html = ""
    if gaps:
        gaps_html = ('<div class="gaps mono">' +
                     "".join(f"<div>&#9888; {esc(g)}</div>" for g in gaps) + "</div>")

    return TEMPLATE.format(
        p=p, mode=mode_lbl, date_lbl=esc(date_lbl), generated=esc(generated_display),
        headline=esc(headline), hero=hero_html, stats=stat_html, rows=rows_joined,
        gaps=gaps_html, list_heading="Today" if evening else "On your plate",
        count=len(rows), score=score_html, dest=dest_html, strip=strip_html,
        sky=sky_html(evening), board_title=esc(board_title),
    )


def source_pill(p, src):
    """Small colour-coded JIRA / GH / SLK badge. Returns '' for an unknown
    source rather than inventing a label for something we cannot identify."""
    if src not in SOURCE_LABEL:
        return ""
    label, tint = SOURCE_LABEL[src]
    c = p[tint]
    return (f'<span class="src-pill mono" style="color:{c};background:{c}1f;'
            f'border:1px solid {c}40">{label}</span>')


def source_tabs(p, rows):
    """Clickable filter tabs. Rows carry data-src; the inline script toggles
    them. If script never runs the default state is every row visible, so the
    board degrades to exactly what it was before."""
    tally = {}
    for r in rows:
        if r.get("src") in SOURCE_LABEL:
            tally[r["src"]] = tally.get(r["src"], 0) + 1
    if len(tally) < 2:          # one source only — tabs would be decoration
        return ""
    tabs = [f'<button class="tab tab-on" data-filter="all" '
            f'style="--tc:{p["text"]}">All<span class="tab-n">{len(rows)}</span></button>']
    for key, label, tint in SOURCES:
        if tally.get(key):
            tabs.append(f'<button class="tab" data-filter="{key}" style="--tc:{p[tint]}">'
                        f'{label}<span class="tab-n">{tally[key]}</span></button>')
    return '<div class="tabs mono">' + "".join(tabs) + '</div>'


def no_destination_drawer(p, rows):
    """Tickets carrying missingFixVersion, as a right-edge slide-out.

    Third iteration. A per-row chip and then an in-body section both got
    scrolled past; a rail pinned to the right edge keeps the count in
    peripheral vision without eating vertical space, which is the actual ask -
    the problem is forgetting, not not-knowing-where-to-look.
    """
    orphans = [r for r in rows if "missingFixVersion" in (r.get("flags") or [])]
    if not orphans:
        return ""
    items = []
    for r in orphans:
        label = esc(r.get("refId") or r.get("title") or "")
        link = (f'<a href="{esc(r["url"])}" target="_blank" rel="noopener">{label}</a>'
                if r.get("url") else label)
        items.append(
            '<li class="dest-row">' + source_pill(p, r.get("src", "")) + link +
            f'<span class="dest-title">{esc(r.get("title",""))}</span></li>')
    n = len(orphans)
    return (
        '<div class="rail" id="drawer">'
        '<button class="rail-tab mono" id="drawerbtn" aria-expanded="false" '
        'aria-controls="drawerpanel" title="Tickets with no fix version">'
        f'<span class="rt-flag">&#9873;</span>'
        f'<span class="rt-n">{n}</span>'
        '<span class="rt-txt">no destination</span>'
        '</button>'
        '<aside class="rail-panel" id="drawerpanel" aria-hidden="true">'
        '<div class="rail-head">'
        f'<span class="rail-title mono">&#9873; No destination &middot; {n}</span>'
        '<button class="rail-x" id="drawerclose" aria-label="Close">&#215;</button>'
        '</div>'
        '<div class="dest-sub">No fix version set. These can ship, or silently miss a '
        'release, with nobody watching.</div>'
        '<ul class="dest-list scroll">' + "".join(items) + '</ul>'
        '</aside></div>')


def progress_block(p, counts, scorecard):
    """Evening-only 'how on fire were you' bar.

    The percentage is real (closed over everything on the board). The line
    beside it is written by the model at generation time; when it is absent we
    say so rather than substituting a canned compliment.
    """
    if not counts:
        return ""
    total = counts["closed"] + counts["moved"] + counts["open"]
    if total <= 0:
        return ""
    closed_pct = round(100 * counts["closed"] / total)
    moved_pct = round(100 * counts["moved"] / total)
    line = (scorecard or {}).get("line") or "No verdict written for today."
    verdict = (scorecard or {}).get("verdict") or ""
    verdict_html = ""
    if verdict:
        verdict_html = f'<span class="score-verdict mono" style="color:{p["today"]}">{esc(verdict)}</span>'
    return (
        '<div class="score-box"><div class="score-top">'
        f'<span class="score-pct mono">{closed_pct}%</span>'
        f'<span class="score-cap">shipped &middot; {counts["closed"]} of {total}</span>'
        + verdict_html +
        '</div><div class="score-track">'
        f'<div class="score-fill-closed" style="width:{closed_pct}%"></div>'
        f'<div class="score-fill-moved" style="width:{moved_pct}%"></div>'
        '</div>'
        f'<div class="score-line">{esc(line)}</div></div>')


SUN_SVG = """
    <div class="sky sky-day" aria-hidden="true">
      <svg viewBox="0 0 44 44" width="40" height="40">
        <g class="rays">
          <line x1="22" y1="4"  x2="22" y2="10"/><line x1="22" y1="34" x2="22" y2="40"/>
          <line x1="4"  y1="22" x2="10" y2="22"/><line x1="34" y1="22" x2="40" y2="22"/>
          <line x1="9"  y1="9"  x2="13" y2="13"/><line x1="31" y1="31" x2="35" y2="35"/>
          <line x1="9"  y1="35" x2="13" y2="31"/><line x1="31" y1="13" x2="35" y2="9"/>
        </g>
        <circle class="orb sun" cx="22" cy="22" r="8"/>
      </svg>
    </div>"""

MOON_SVG = """
    <div class="sky sky-night" aria-hidden="true">
      <svg viewBox="0 0 44 44" width="40" height="40">
        <defs><mask id="moonmask">
          <rect width="44" height="44" fill="#fff"/>
          <circle cx="30" cy="15" r="10" fill="#000"/>
        </mask></defs>
        <circle class="orb moon" cx="22" cy="22" r="10" mask="url(#moonmask)"/>
      </svg>
      <span class="star s1"></span><span class="star s2"></span><span class="star s3"></span>
    </div>"""


def sky_html(evening):
    """Sun or moon beside the title. Pure CSS/SVG, no script at all; motion is
    opted out via prefers-reduced-motion in the stylesheet."""
    return MOON_SVG if evening else SUN_SVG


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
  .topbar h1 {{ font-size:30px; line-height:1.12; margin:0; letter-spacing:-.025em;
    font-weight:700; max-width:19ch; text-wrap:balance; }}
  @media (max-width:520px) {{ .topbar h1 {{ font-size:25px; }} }}
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

  /* ---- source pills + count strip ---- */
  .src-pill {{ display:inline-block; font-size:9.5px; letter-spacing:.08em; font-weight:700;
    border-radius:5px; padding:2px 5px; margin-right:8px; vertical-align:2px; }}

  /* ---- filter tabs ---- */
  .tabs {{ display:flex; gap:7px; margin:12px 0 4px; flex-wrap:wrap; }}
  .tab {{ font-family:inherit; font-size:10.5px; letter-spacing:.09em; font-weight:700;
    text-transform:uppercase; cursor:pointer; border-radius:999px; padding:7px 13px;
    background:transparent; color:{p[muted]}; border:1px solid {p[border]};
    display:inline-flex; align-items:center; gap:7px; transition:all .16s ease; }}
  .tab:hover {{ color:var(--tc); border-color:var(--tc); transform:translateY(-1px); }}
  .tab-n {{ font-size:10px; opacity:.7; font-weight:500; }}
  .tab-on {{ color:var(--tc); border-color:var(--tc); background:color-mix(in srgb, var(--tc) 13%, transparent); }}
  .tab:focus-visible {{ outline:2px solid var(--tc); outline-offset:2px; }}

  /* ---- scroll panes ---- */
  .scroll {{ max-height:440px; overflow-y:auto; overscroll-behavior:contain;
    -webkit-mask-image:linear-gradient(to bottom, transparent 0, #000 10px,
      #000 calc(100% - 14px), transparent 100%); }}
  .dest-list.scroll {{ max-height:190px; }}
  .scroll::-webkit-scrollbar {{ width:8px; }}
  .scroll::-webkit-scrollbar-track {{ background:transparent; }}
  .scroll::-webkit-scrollbar-thumb {{ background:{p[border]}; border-radius:999px; }}
  .scroll::-webkit-scrollbar-thumb:hover {{ background:{p[muted]}; }}
  .scroll {{ scrollbar-width:thin; scrollbar-color:{p[border]} transparent; }}
  .row-hidden {{ display:none; }}
  .empty-filter {{ padding:24px 0; font-size:13.5px; color:{p[muted]}; }}

  /* ---- no destination rail (right edge) ---- */
  .rail {{ position:fixed; inset:0 0 0 auto; z-index:9999; pointer-events:none; }}
  .rail-tab {{ pointer-events:auto; position:fixed; right:0; top:50%; z-index:10000;
    transform:translateY(-50%); transform-origin:center;
    font-family:inherit; cursor:pointer; display:flex; flex-direction:column;
    align-items:center; gap:6px; width:46px; padding:16px 0;
    border:1px solid {p[today]}66; border-right:none; border-radius:12px 0 0 12px;
    background:{p[card]}; color:{p[today]};
    box-shadow:-6px 0 22px -8px rgba(0,0,0,.4);
    transition:width .16s ease, background .16s ease; }}
  .rail-tab:hover {{ background:{p[today]}1a; width:52px; }}
  .rail-tab:focus-visible {{ outline:2px solid {p[today]}; outline-offset:3px; }}
  .rt-flag {{ font-size:13px; }}
  .rt-n {{ font-size:17px; font-weight:700; line-height:1; }}
  .rt-txt {{ writing-mode:vertical-rl; font-size:9.5px; letter-spacing:.16em;
    text-transform:uppercase; font-weight:700; color:{p[secondary]}; }}
  .rail.open .rail-tab {{ opacity:0; pointer-events:none; }}

  .rail-panel {{ pointer-events:auto; position:fixed; top:0; right:0; bottom:0;
    width:min(380px, 88vw); background:{p[card]}; border-left:1px solid {p[today]}66;
    box-shadow:-14px 0 40px -14px rgba(0,0,0,.5);
    padding:22px 22px 26px; overflow-y:auto;
    transform:translateX(102%); transition:transform .26s cubic-bezier(.4,0,.2,1);
    display:flex; flex-direction:column; }}
  .rail.open .rail-panel {{ transform:translateX(0); }}
  .rail-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px;
    margin-bottom:10px; }}
  .rail-title {{ font-size:11.5px; letter-spacing:.12em; text-transform:uppercase;
    font-weight:700; color:{p[today]}; }}
  .rail-x {{ font-family:inherit; cursor:pointer; background:transparent; border:none;
    color:{p[muted]}; font-size:24px; line-height:1; padding:0 2px; }}
  .rail-x:hover {{ color:{p[text]}; }}
  .rail-panel .dest-list {{ max-height:none; flex:1; }}
  @media (prefers-reduced-motion: reduce) {{
    .rail-panel {{ transition:none; }}
  }}
  .dest-head {{ font-size:11.5px; letter-spacing:.12em; text-transform:uppercase; font-weight:700; }}
  .dest-sub {{ font-size:13px; color:{p[secondary]}; margin:6px 0 12px; max-width:52ch; }}
  .dest-list {{ list-style:none; margin:0; padding:0; }}
  .dest-row {{ display:flex; align-items:baseline; gap:2px; padding:5px 0; font-size:13.5px; flex-wrap:wrap; }}
  .dest-row a {{ font-weight:600; text-decoration:none; border-bottom:1px solid {p[border]}; }}
  .dest-title {{ color:{p[secondary]}; margin-left:8px; }}

  /* ---- evening scorecard ---- */
  .score-box {{ background:{p[card]}; border:1px solid {p[border]}; border-radius:14px;
    padding:18px 20px; margin-bottom:28px; }}
  .score-top {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin-bottom:12px; }}
  .score-pct {{ font-size:30px; font-weight:500; letter-spacing:-.03em; line-height:1; color:{p[green]}; }}
  .score-cap {{ font-size:12.5px; color:{p[muted]}; }}
  .score-verdict {{ font-size:10.5px; letter-spacing:.12em; text-transform:uppercase; font-weight:700;
    margin-left:auto; }}
  .score-track {{ display:flex; height:9px; border-radius:999px; overflow:hidden;
    background:{p[hairline]}; }}
  .score-fill-closed {{ background:{p[green]}; }}
  .score-fill-moved {{ background:{p[blue]}; opacity:.55; }}
  .score-line {{ font-size:14px; line-height:1.5; color:{p[secondary]}; margin-top:12px; max-width:54ch; }}

  /* ---- sun / moon ---- */
  .topbar-flex {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }}
  .sky {{ position:relative; flex:0 0 auto; width:44px; height:44px; }}
  .orb {{ transform-origin:22px 22px; }}
  .sun {{ fill:{p[today]}; animation:pulse 4s ease-in-out infinite; }}
  .rays line {{ stroke:{p[today]}; stroke-width:2.2; stroke-linecap:round;
    transform-origin:22px 22px; animation:spin 22s linear infinite; }}
  .moon {{ fill:{p[radar]}; animation:pulse 6s ease-in-out infinite; }}
  .star {{ position:absolute; width:2.5px; height:2.5px; border-radius:50%;
    background:{p[radar]}; opacity:.8; }}
  .star.s1 {{ top:4px;  left:2px;  animation:twinkle 3.1s ease-in-out infinite; }}
  .star.s2 {{ top:26px; left:0px;  animation:twinkle 2.4s ease-in-out .6s infinite; }}
  .star.s3 {{ top:12px; left:38px; animation:twinkle 3.7s ease-in-out 1.2s infinite; }}
  @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
  @keyframes pulse {{ 0%,100% {{ opacity:.85; }} 50% {{ opacity:1; }} }}
  @keyframes twinkle {{ 0%,100% {{ opacity:.15; }} 50% {{ opacity:.9; }} }}
  @media (prefers-reduced-motion: reduce) {{
    .sun, .moon, .rays line, .star {{ animation:none !important; }}
  }}

  @media (max-width:520px) {{
    .stat-grid {{ grid-template-columns:1fr 1fr; }}
    .score-verdict {{ margin-left:0; }}
  }}
</style>
</head>
<body>
<div class="page"><div class="wrap">

  <div class="topbar topbar-flex">
    <div>
      <div class="date-label mono">{date_lbl} · {generated}</div>
      <h1>{board_title}<span class="mode-chip mono">{mode}</span></h1>
    </div>{sky}
  </div>

  <div class="headline">{headline}</div>
{hero}
{score}
{stats}
  <div class="section-head">
    <h2>{list_heading}</h2><span class="section-count mono">{count}</span>
  </div>
{strip}
  <ul class="rows scroll" id="rowlist">{rows}
    <li class="empty-filter" id="emptyfilter" style="display:none">Nothing from this source today.</li>
  </ul>
{dest}
{gaps}
  <footer>regenerated by the am / pm report skills · past days live in this artifact's version history</footer>

</div></div>
<script>
(function () {{
  var tabs = document.querySelectorAll('.tab');
  var rows = document.querySelectorAll('#rowlist .row');
  var empty = document.getElementById('emptyfilter');
  if (!tabs.length) return;
  tabs.forEach(function (t) {{
    t.addEventListener('click', function () {{
      var f = t.dataset.filter, shown = 0;
      tabs.forEach(function (o) {{ o.classList.toggle('tab-on', o === t); }});
      rows.forEach(function (r) {{
        var hit = (f === 'all') || (r.dataset.src === f);
        r.classList.toggle('row-hidden', !hit);
        if (hit) shown++;
      }});
      if (empty) empty.style.display = shown ? 'none' : 'block';
      var list = document.getElementById('rowlist');
      if (list) list.scrollTop = 0;
    }});
  }});
}})();
(function () {{
  var d = document.getElementById('drawer'),
      b = document.getElementById('drawerbtn'),
      x = document.getElementById('drawerclose'),
      panel = document.getElementById('drawerpanel');
  if (!d || !b || !panel) return;
  function set(open) {{
    d.classList.toggle('open', open);
    b.setAttribute('aria-expanded', open ? 'true' : 'false');
    panel.setAttribute('aria-hidden', open ? 'false' : 'true');
  }}
  b.addEventListener('click', function () {{ set(!d.classList.contains('open')); }});
  if (x) x.addEventListener('click', function () {{ set(false); }});
  document.addEventListener('keydown', function (e) {{
    if (e.key === 'Escape') set(false);
  }});
  document.addEventListener('click', function (e) {{
    if (d.classList.contains('open') && !panel.contains(e.target) && !b.contains(e.target)) set(false);
  }});
}})();
</script>
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
