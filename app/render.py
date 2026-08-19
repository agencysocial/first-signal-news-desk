"""
Plain server-rendered HTML -- no Jinja2 (see git history / BUILD_STATUS for
why: an internal starlette/Jinja2 template-cache bug on this Python build).
Standing in for the real Next.js dashboard; all user-sourced text is escaped.
"""
import json
from html import escape

STYLE = """
    body { background: #0b0e14; color: #e6e8ec; font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 0; padding: 24px; }
    h1 { font-size: 18px; font-weight: 600; margin: 0 0 4px 0; }
    h2 { font-size: 15px; font-weight: 600; margin: 20px 0 8px 0; color: #c7cbd4; }
    .sub { color: #8b93a3; font-size: 13px; margin-bottom: 16px; }
    a { color: #e6e8ec; text-decoration: none; }
    a:hover { text-decoration: underline; }
    a.back { color: #8b93a3; font-size: 13px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th { text-align: left; color: #8b93a3; font-weight: 600; text-transform: uppercase; font-size: 11px;
         padding: 6px 10px; border-bottom: 1px solid #232838; position: sticky; top: 0; background: #0b0e14; }
    td { padding: 8px 10px; border-bottom: 1px solid #1a1f2b; vertical-align: top; }
    tr:hover td { background: #11151f; }
    .badge { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 11px; font-weight: 600; }
    .tier-1, .tier-2 { background: #16321f; color: #4ade80; }
    .tier-3, .tier-4 { background: #3a2f12; color: #facc15; }
    .tier-5 { background: #3a1414; color: #f87171; }
    .status-New { background: #1e293b; color: #93c5fd; }
    .status-Developing { background: #3a2f12; color: #facc15; }
    .status-Breaking { background: #3a1414; color: #f87171; }
    .status-Covered, .status-Dismissed { background: #23262e; color: #8b93a3; }
    .status-Watchlist { background: #1e2a4a; color: #60a5fa; }
    .score { font-variant-numeric: tabular-nums; }
    .score-hi { color: #4ade80; }
    .score-mid { color: #facc15; }
    .score-lo { color: #8b93a3; }
    .dup-flag { color: #8b93a3; font-size: 12px; }
    .errors { margin-top: 24px; padding: 12px; background: #241414; border: 1px solid #4a2020; border-radius: 6px; font-size: 12px; }
    .errors h2 { font-size: 13px; margin: 0 0 6px 0; color: #f87171; }
    .meta-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; margin: 16px 0; }
    .meta-box { background: #11151f; border: 1px solid #1a1f2b; border-radius: 6px; padding: 10px 12px; }
    .meta-box .label { color: #8b93a3; font-size: 11px; text-transform: uppercase; }
    .meta-box .value { font-size: 20px; font-weight: 600; margin-top: 2px; }
    .tags { margin: 8px 0; }
    .tag { display: inline-block; background: #1a1f2b; color: #c7cbd4; border-radius: 3px; padding: 2px 8px; font-size: 12px; margin: 2px 4px 2px 0; }
    .actions { margin: 16px 0; display: flex; gap: 8px; flex-wrap: wrap; }
    .actions form { margin: 0; }
    .actions button { background: #1a1f2b; color: #e6e8ec; border: 1px solid #2a3040; border-radius: 4px;
                      padding: 6px 12px; font-size: 12px; cursor: pointer; }
    .actions button:hover { background: #232838; }
    .actions button.primary, button.primary { background: #1e3a8a; border-color: #2563eb; }
    button { background: #1a1f2b; color: #e6e8ec; border: 1px solid #2a3040; border-radius: 4px;
             padding: 5px 10px; font-size: 12px; cursor: pointer; }
    button:hover { background: #232838; }
    .flash { background: #16321f; border: 1px solid #245c33; color: #4ade80; border-radius: 6px; padding: 8px 12px; margin-bottom: 16px; font-size: 13px; }
    .nav { margin-bottom: 20px; font-size: 13px; }
    .nav a { color: #8b93a3; margin-right: 16px; }
    .nav a:hover { color: #e6e8ec; }
    .inline-form { display: inline; }
    .split-bar { margin: 8px 0 16px 0; }
    input[type=text], input[type=number], input[type=url], select {
        background: #11151f; color: #e6e8ec; border: 1px solid #2a3040; border-radius: 4px;
        padding: 5px 8px; font-size: 12px;
    }
    .sort-toggle { margin-top: 8px; font-size: 13px; }
    .sort-toggle a { color: #8b93a3; padding: 3px 10px; border: 1px solid #2a3040; border-radius: 4px; margin-right: 6px; }
    .sort-toggle a:hover { color: #e6e8ec; text-decoration: none; }
    .sort-toggle a.active { color: #e6e8ec; background: #1a1f2b; border-color: #3b82f6; font-weight: 600; }
    .chips { margin-top: 10px; font-size: 12px; display: flex; flex-wrap: wrap; gap: 6px; }
    .chips a { color: #8b93a3; padding: 4px 10px; border: 1px solid #2a3040; border-radius: 14px; }
    .chips a:hover { color: #e6e8ec; text-decoration: none; }
    .chips a.active { color: #e6e8ec; background: #1e3a8a; border-color: #2563eb; font-weight: 600; }
    .chips a.clear { color: #f87171; border-color: #4a2020; }
    .filter-form { margin-top: 10px; padding: 10px 12px; background: #11151f; border: 1px solid #1a1f2b;
                    border-radius: 6px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 12px; }
    .filter-form label { color: #8b93a3; }
    .updated-fresh { color: #4ade80; font-weight: 600; }
    .new-dot { color: #4ade80; }
    @keyframes blink-red { 0%,100%{opacity:1} 50%{opacity:.35} }

    /* Mobile: the full workflow needs to work on a phone, not just be
    readable -- reviewing stories, filtering, and sending to the production
    queue all happen away from a desk. The main structural problem tables
    have on a narrow screen isn't font size, it's column count (the Wire
    table alone is 9 columns) -- no amount of shrinking makes that fit, so
    below the breakpoint every data table becomes a stack of cards instead:
    hide the header row, turn each <tr> into its own bordered block, and
    turn each <td> into a labeled row using its data-label attribute. This
    is a CSS-only transform (see render_wire_page etc. for the data-label
    attributes) rather than maintaining separate mobile/desktop markup. */
    @media (max-width: 768px) {
        body { padding: 12px; }
        .nav { flex-wrap: wrap; gap: 8px; }
        .nav > div { display: flex; flex-wrap: wrap; gap: 4px 12px; }
        table, thead, tbody, th, td, tr { display: block; }
        table { border: none; }
        thead { position: absolute; left: -9999px; top: -9999px; } /* keep for screen readers, hide visually */
        tr { border: 1px solid #1a1f2b; border-radius: 6px; margin-bottom: 10px; padding: 8px 10px; background: #0d111a; }
        tr:hover td { background: none; }
        td { border-bottom: none; padding: 6px 0; display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
        td[data-label]::before {
            content: attr(data-label); color: #8b93a3; font-size: 11px; text-transform: uppercase;
            font-weight: 600; flex-shrink: 0; padding-top: 1px;
        }
        td:not([data-label]) { display: block; } /* checkbox/action-only cells: no label to show */
        .filter-form, .actions, .chips { gap: 10px; }
        input[type=text], input[type=number], input[type=url], input[type=email], input[type=password], select {
            font-size: 16px; /* prevents iOS Safari auto-zoom on focus */
        }
        button, .actions button, .chips a { padding: 8px 14px; } /* larger touch targets */
        .meta-grid { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); }
    }
"""

NAV = """
  <div class="nav" style="display:flex;justify-content:space-between;align-items:center">
    <div>
      <a href="/">First Signal Wire</a>
      <a href="/watchlist">Watchlist</a>
      <a href="/sources">Sources</a>
      <a href="/pipeline-queue">&#9654; Production Queue</a>
      <a href="/fb-scanner">&#128269; FB Scanner</a>
    </div>
    <div style="display:flex;align-items:center;gap:12px">
      <span id="_qcounts" style="font-size:11px;color:#8b93a3;letter-spacing:.3px"></span>
      <form method="post" action="/logout" class="inline-form">
        <button type="submit" style="font-size:11px">Logout</button>
      </form>
    </div>
  </div>
  <script>
  (function(){
    function _loadCounts(){
      fetch('/api/queue-counts').then(function(r){return r.ok?r.json():null;}).then(function(d){
        if(!d)return;
        var el=document.getElementById('_qcounts');
        if(!el)return;
        var parts=[];
        if(d.queued)parts.push(d.queued+' queued');
        if(d.generating)parts.push(d.generating+' generating');
        if(d.approved)parts.push(d.approved+' approved');
        el.textContent=parts.length?parts.join(' · '):'';
      }).catch(function(){});
    }
    _loadCounts();
    setInterval(_loadCounts,30000);
  })();
  </script>
"""

def _page_head(extra_meta: str = "") -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AIM News Desk &mdash; Phase 1f</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M1 9l2 2c2.76-2.76 6.57-4.47 10.78-4.47 4.21 0 8.02 1.71 10.78 4.47l2-2C23.55 6.07 18.66 4 13.78 4c-4.88 0-9.77 2.07-12.78 5zm10.78 10.78l1.22 1.22 1.22-1.22c-.67-.67-1.77-.67-2.44 0zm-3.66-3.66l2 2c.9-.9 2.15-1.46 3.44-1.46 1.29 0 2.54.56 3.44 1.46l2-2c-1.45-1.45-3.45-2.34-5.44-2.34-1.99 0-3.99.89-5.44 2.34zm-3.66-3.66l2 2C8.41 12.51 11 11.34 13.78 11.34c2.78 0 5.37 1.17 7.32 3.12l2-2C20.89 10.25 17.53 9 13.78 9 10.03 9 6.67 10.25 4.46 12.46z'/%3E%3C/svg%3E">
  {extra_meta}
  <style>{STYLE}</style>
</head>
<body>
{NAV}
"""


PAGE_HEAD = _page_head()
PAGE_TAIL = "</body></html>"


def _score_class(score: float) -> str:
    if score >= 60:
        return "score-hi"
    if score >= 30:
        return "score-mid"
    return "score-lo"


def render_login_page(error: str | None = None, next_path: str = "/") -> str:
    error_html = f'<div class="flash" style="background:#3a1414;border-color:#4a2020;color:#f87171">{escape(error)}</div>' if error else ""
    body = f"""
  <div style="max-width:340px;margin:80px auto 0 auto">
    <div style="text-align:center;margin-bottom:20px">
      <img src="/static/logo.png" alt="First Signal" style="width:300px;max-width:100%;height:auto">
    </div>
    <h1 style="text-align:center;margin-bottom:24px">News Desk</h1>
    {error_html}
    <form method="post" action="/login" style="display:flex;flex-direction:column;gap:10px">
      <input type="hidden" name="next" value="{escape(next_path)}">
      <label style="font-size:12px;color:#8b93a3">Email</label>
      <input type="email" name="email" required autofocus style="width:100%;box-sizing:border-box">
      <label style="font-size:12px;color:#8b93a3">Password</label>
      <input type="password" name="password" required style="width:100%;box-sizing:border-box">
      <button type="submit" class="primary" style="margin-top:8px;padding:8px;font-size:13px">Log In</button>
    </form>
  </div>
"""
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>News Desk &mdash; Log In</title>
  <style>{STYLE}</style>
</head>
<body>
{body}
</body></html>"""


def render_wire_page(clusters: list[dict], error_sources: list[tuple[str, str]],
                      last_scan: str = "never", scanning: bool = False, flash: str | None = None,
                      sort: str = "latest", filters: dict | None = None,
                      categories: list[str] | None = None, sources: list[tuple[int, str]] | None = None,
                      statuses: list[str] | None = None, page_title: str = "First Signal Wire",
                      base_path: str = "/", show_status_filter: bool = True) -> str:
    filters = filters or {}
    categories = categories or []
    sources = sources or []
    statuses = statuses or []
    rows = []
    for c in clusters:
        # "Updated" (latest_update_at) is a distinct signal from "Age"
        # (first_detected_at): a story can be old but just got fresh
        # corroboration. Highlighted when very recent -- a lightweight stand-in
        # for the spec's "trigger an alert when meaningful changes occur",
        # without building a separate alerts/notifications system.
        fresh_class = "updated-fresh" if c.get("is_fresh") else ""
        rows.append(f"""
      <tr>
        <td data-label="Viral" class="score {_score_class(c['viral_score'])}">{c['viral_score']:.0f}</td>
        <td data-label="Confidence" class="score {_score_class(c['confidence_score'])}">{c['confidence_score']:.0f}</td>
        <td data-label="Momentum" class="score {_score_class(c['momentum_score'])}">{c['momentum_score']:.0f}</td>
        <td data-label="Headline"><a href="/stories/{c['id']}">{escape(c['canonical_headline'])}</a></td>
        <td data-label="Category">{escape(c['category'] or '-')}</td>
        <td data-label="Sources">{c['source_count']}</td>
        <td data-label="Age">{escape(c['age'])}</td>
        <td data-label="Updated" class="{fresh_class}">{escape(c.get('updated_ago', '-'))}{' <span class="new-dot">&bull;</span>' if c.get('is_fresh') else ''}</td>
        <td data-label="Status"><span class="badge status-{escape(c['status'])}">{escape(c['status'])}</span></td>
        <td data-label="Queue" style="white-space:nowrap">
          <form method="post" action="/stories/{c['id']}/handoff" style="margin:0">
            <input type="hidden" name="return_to" value="/">
            <button type="submit" style="font-size:10px;padding:2px 8px;background:#0a1a28;border:1px solid #1a3a5a;color:#60a5fa;border-radius:3px;cursor:pointer;white-space:nowrap">&#43; Queue</button>
          </form>
        </td>
      </tr>""")

    errors_html = ""
    if error_sources:
        items = "".join(f"<div>{escape(name)}: {escape(err)}</div>" for name, err in error_sources)
        errors_html = f'<div class="errors"><h2>Source errors</h2>{items}</div>'

    flash_html = f'<div class="flash">{escape(flash)}</div>' if flash else ""
    scan_button_label = "Scanning…" if scanning else "Scan Now"
    scan_button_disabled = "disabled" if scanning else ""

    # Auto-refresh so the page reflects reality without a manual reload --
    # a "Scanning..." button with no refresh looked permanently stuck even
    # when the actual scan finished in seconds (the button just froze at
    # whatever state the page had when it first loaded). Refresh faster
    # while a scan is actually in flight, slower otherwise.
    refresh_seconds = 5 if scanning else 20
    refresh_meta = f'<meta http-equiv="refresh" content="{refresh_seconds}">'

    latest_active = "active" if sort == "latest" else ""
    viral_active = "active" if sort == "viral" else ""
    sort_label = "most recently updated" if sort == "latest" else "highest viral score"

    # Quick filters REFINE the currently active filters rather than resetting
    # them -- picking a category via the filter form, then clicking a time-
    # window chip, must keep the category (real operator-reported bug: it
    # was dropping category and every other active filter, since each chip
    # only ever encoded its own single param). "All" is the one deliberate
    # exception -- it's a true full reset, not a refinement.
    f = filters

    def chip(label, active, **params):
        merged = {k: v for k, v in f.items() if v not in (None, "", False)}
        merged.update(params)
        merged["sort"] = sort
        qs = "&".join(f"{k}={v}" for k, v in merged.items())
        cls = "active" if active else ""
        return f'<a href="{base_path}?{qs}" class="{cls}">{escape(label)}</a>'

    category_chips = [f'<a href="{base_path}?sort={escape(sort)}" class="{"active" if not f.get("category") else ""}">All Topics</a>']
    for cat in categories:
        category_chips.append(chip(cat.title(), f.get("category") == cat, category=cat))
    category_chips_html = "".join(category_chips)

    chip_list = [
        f'<a href="{base_path}?sort={escape(sort)}" class="{"active" if not any(f.values()) else ""}">All</a>',
        chip("Last 15m", f.get("window") == "15m", window="15m"),
        chip("Last 1h", f.get("window") == "1h", window="1h"),
        chip("Last 3h", f.get("window") == "3h", window="3h"),
        chip("Last 6h", f.get("window") == "6h", window="6h"),
        chip("Last 12h", f.get("window") == "12h", window="12h"),
        chip("Last 24h", f.get("window") == "24h", window="24h"),
        chip("Last 48h", f.get("window") == "48h", window="48h"),
        chip("High Viral", f.get("min_viral") == 70, min_viral=70),
        chip("High Confidence", f.get("min_confidence") == 70, min_confidence=70),
    ]
    # Status-based chip/filter don't make sense on a page where status is
    # already fixed (e.g. /watchlist is always status=Watchlist).
    if show_status_filter:
        chip_list.append(chip("Breaking", f.get("status") == "Breaking", status="Breaking"))
    chip_list += [
        chip("Needs Verification", f.get("verification") == "single_source", verification="single_source"),
        chip("Not Covered", bool(f.get("exclude_covered")), exclude_covered="true"),
    ]
    chips_html = "".join(chip_list)

    def option(value, current, label=None):
        selected = "selected" if str(current or "") == str(value) else ""
        return f'<option value="{escape(str(value))}" {selected}>{escape(label or str(value))}</option>'

    category_options = '<option value="">Any category</option>' + "".join(
        option(c, f.get("category")) for c in categories
    )
    status_options = '<option value="">Any status</option>' + "".join(
        option(s, f.get("status")) for s in statuses
    )
    source_options = '<option value="">Any source</option>' + "".join(
        option(sid, f.get("source_id"), label=name) for sid, name in sources
    )
    verification_options = '<option value="">Any verification</option>' + "".join(
        option(v, f.get("verification"), label=lbl) for v, lbl in [
            ("single_source", "Single source"),
            ("developing_coverage", "Developing coverage"),
            ("multi_source", "Multi-source"),
        ]
    )
    status_field_html = f"""
      <label>Status</label>
      <select name="status">{status_options}</select>""" if show_status_filter else ""

    body = f"""
  <h1>AIM News Desk &mdash; {escape(page_title)}</h1>
  <div class="sub">
    {len(clusters)} story clusters &middot; viral score blends coverage (momentum/tier/recency) with AI content judgment &middot; sorted by {sort_label}
    <br>Last scan: {escape(last_scan)} (auto-scans every 3-30 min in the background; this page refreshes itself every {refresh_seconds}s)
    <div class="sort-toggle">
      Sort:
      <a href="{base_path}?sort=latest" class="{latest_active}">Latest</a>
      <a href="{base_path}?sort=viral" class="{viral_active}">Highest Viral</a>
    </div>
    <div class="chips" style="margin-bottom:4px"><span style="font-size:10px;color:#8b93a3;text-transform:uppercase;letter-spacing:.5px;margin-right:6px">Topic</span>{category_chips_html}</div>
    <div class="chips">{chips_html}</div>
    <form method="get" action="{base_path}" class="filter-form">
      <input type="hidden" name="sort" value="{escape(sort)}">
      <label>Category</label>
      <select name="category">{category_options}</select>{status_field_html}
      <label>Source</label>
      <select name="source_id">{source_options}</select>
      <label>Verification</label>
      <select name="verification">{verification_options}</select>
      <label>Min viral</label>
      <input type="number" name="min_viral" min="0" max="100" style="width:60px" value="{f.get('min_viral') if f.get('min_viral') is not None else ''}">
      <label>Min confidence</label>
      <input type="number" name="min_confidence" min="0" max="100" style="width:60px" value="{f.get('min_confidence') if f.get('min_confidence') is not None else ''}">
      <button type="submit" class="primary">Apply</button>
    </form>
    <form method="post" action="/scan-now" class="inline-form" style="margin-top:8px">
      <button type="submit" class="primary" {scan_button_disabled}>{scan_button_label}</button>
    </form>
    <form method="post" action="/capture/twitter" class="inline-form" style="margin-top:8px">
      <input type="hidden" name="return_to" value="{escape(base_path)}">
      <input type="url" name="tweet_url" placeholder="Paste a tweet/X URL..." required
             style="width:260px" pattern="https?://(www\\.)?(twitter|x)\\.com/.+/status/[0-9]+">
      <button type="submit">+ Add from X</button>
    </form>
  </div>

  {flash_html}

  <table>
    <thead>
      <tr>
        <th>Viral*</th><th>Confidence</th><th>Momentum</th><th style="width:32%">Headline</th>
        <th>Category</th><th>Sources</th><th>Age</th><th>Updated</th><th>Status</th><th></th>
      </tr>
    </thead>
    <tbody>{''.join(rows)}
    </tbody>
  </table>
  {errors_html}
"""
    return _page_head(refresh_meta) + body + PAGE_TAIL


def _render_coverage_history(covered_posts: list[dict]) -> str:
    """A story can be Covered, reopen on a new development, and get Covered
    again later (see clustering.py's Covered -> Developing transition) --
    so this shows every past Mark-Covered event, not just the latest one."""
    if not covered_posts:
        return ""
    rows = []
    for cp in covered_posts:
        link = (
            f'<a href="{escape(cp["post_url"])}" target="_blank" rel="noopener">{escape(cp["post_url"])}</a>'
            if cp.get("post_url") else "-"
        )
        rows.append(f"""
      <tr>
        <td data-label="Covered">{escape(cp['covered_at'])}</td>
        <td data-label="Platform">{escape(cp.get('platform') or '-')}</td>
        <td data-label="Post">{link}</td>
        <td data-label="Format">{escape(cp.get('format') or '-')}</td>
        <td data-label="Editor">{escape(cp.get('editor') or '-')}</td>
        <td data-label="Notes">{escape(cp.get('notes') or '-')}</td>
      </tr>""")
    return f"""
  <h2>Coverage history ({len(covered_posts)})</h2>
  <table>
    <thead><tr><th>Covered</th><th>Platform</th><th style="width:25%">Post</th><th>Format</th><th>Editor</th><th>Notes</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
"""


def render_detail_page(cluster: dict, articles: list[dict], flash: str | None = None,
                        covered_posts: list[dict] | None = None) -> str:
    covered_posts = covered_posts or []
    entities = json.loads(cluster["entities"] or "[]")
    keywords = json.loads(cluster["keywords"] or "[]")

    tag_html = " ".join(f'<span class="tag">{escape(e)}</span>' for e in entities) or "<em>none extracted</em>"
    keyword_html = " ".join(f'<span class="tag">{escape(k)}</span>' for k in keywords) or "<em>none extracted</em>"

    article_rows = []
    for a in articles:
        dup_note = ""
        if a["match_level"] == "duplicate_inherit":
            dup_note = '<span class="dup-flag">duplicate coverage</span>'
        article_rows.append(f"""
      <tr>
        <td><input type="checkbox" name="article_ids" value="{a['id']}" form="split-form"></td>
        <td data-label="Headline"><a href="{escape(a['url'])}" target="_blank" rel="noopener">{escape(a['headline'])}</a></td>
        <td data-label="Source"><a href="/?source_id={a['source_id']}">{escape(a['source_name'])}</a></td>
        <td data-label="Tier"><span class="badge tier-{a['source_tier']}">T{a['source_tier']}</span></td>
        <td data-label="Published">{escape(a['published_at'] or '-')}</td>
        <td data-label="Detected">{escape(a['detected_at'])}</td>
        <td>{dup_note}</td>
      </tr>""")

    flash_html = f'<div class="flash">{escape(flash)}</div>' if flash else ""

    body = f"""
  <a class="back" href="/">&larr; Back to First Signal Wire</a>
  <h1>{escape(cluster['canonical_headline'])}</h1>
  <div class="sub">
    <span class="badge status-{escape(cluster['status'])}">{escape(cluster['status'])}</span>
    &nbsp;&middot;&nbsp; verification: {escape(cluster['verification_status'])}
    &nbsp;&middot;&nbsp; category: {escape(cluster['category'] or '-')}
    &nbsp;&middot;&nbsp; location: {escape(cluster['location'] or '-')}
  </div>

  {flash_html}

  <div class="meta-grid">
    <div class="meta-box"><div class="label">Viral score{' (AI-blended)' if cluster.get('ai_scored_at') else ' (coverage only)'}</div><div class="value {_score_class(cluster['viral_score'])}">{cluster['viral_score']:.0f}</div></div>
    <div class="meta-box"><div class="label">Confidence score</div><div class="value {_score_class(cluster['confidence_score'])}">{cluster['confidence_score']:.0f}</div></div>
    <div class="meta-box"><div class="label">Momentum score</div><div class="value {_score_class(cluster['momentum_score'])}">{cluster['momentum_score']:.0f}</div></div>
    <div class="meta-box"><div class="label">Sources</div><div class="value">{cluster['source_count']}</div></div>
    <div class="meta-box"><div class="label">Articles</div><div class="value">{cluster['article_count']}</div></div>
    <div class="meta-box"><div class="label">Age</div><div class="value">{escape(cluster['age'])}</div></div>
  </div>

  <h2>AI content judgment {'' if cluster.get('ai_scored_at') else '<span class="dup-flag">(not yet scored -- new clusters are scored automatically going forward)</span>'}</h2>
  {(
    '<div class="meta-grid">'
    f'<div class="meta-box"><div class="label">Emotional strength</div><div class="value {_score_class(cluster["ai_emotional_strength"])}">{cluster["ai_emotional_strength"]:.0f}</div></div>'
    f'<div class="meta-box"><div class="label">Visual potential</div><div class="value {_score_class(cluster["ai_visual_potential"])}">{cluster["ai_visual_potential"]:.0f}</div></div>'
    f'<div class="meta-box"><div class="label">Conversation potential</div><div class="value {_score_class(cluster["ai_conversation_potential"])}">{cluster["ai_conversation_potential"]:.0f}</div></div>'
    f'<div class="meta-box"><div class="label">Novelty</div><div class="value {_score_class(cluster["ai_novelty"])}">{cluster["ai_novelty"]:.0f}</div></div>'
    '</div>'
  ) if cluster.get('ai_scored_at') else ''}

  <h2>Entities</h2>
  <div class="tags">{tag_html}</div>
  <h2>Keywords</h2>
  <div class="tags">{keyword_html}</div>

  <div class="actions">
    <form method="post" action="/stories/{cluster['id']}/status"><input type="hidden" name="new_status" value="Breaking">
      <button type="submit">Mark Breaking</button></form>
    <form method="post" action="/stories/{cluster['id']}/status"><input type="hidden" name="new_status" value="Watchlist">
      <button type="submit">Add to Watchlist</button></form>
    <form method="post" action="/stories/{cluster['id']}/status"><input type="hidden" name="new_status" value="Dismissed">
      <button type="submit">Dismiss</button></form>
    <form method="post" action="/stories/{cluster['id']}/handoff">
      <button type="submit" class="primary">Send to First Signal Pipeline</button></form>
    <form method="post" action="/stories/{cluster['id']}/merge" class="inline-form">
      <input type="number" name="target_cluster_id" placeholder="target story #" required style="width:110px">
      <button type="submit">Merge into &rarr;</button>
    </form>
  </div>
  {'<div class="sub">Sent to pipeline at ' + escape(cluster['handoff_sent_at']) + '</div>' if cluster.get('handoff_sent_at') else ''}

  <h2>Mark Covered</h2>
  <form method="post" action="/stories/{cluster['id']}/status" class="filter-form">
    <input type="hidden" name="new_status" value="Covered">
    <label>Platform</label>
    <select name="platform">
      <option value="">-</option>
      <option value="Facebook">Facebook</option>
      <option value="Instagram">Instagram</option>
      <option value="X">X</option>
      <option value="TikTok">TikTok</option>
      <option value="Other">Other</option>
    </select>
    <label>Post URL</label>
    <input type="text" name="post_url" style="width:220px" placeholder="https://facebook.com/...">
    <label>Post ID</label>
    <input type="text" name="post_id" style="width:100px">
    <label>Format</label>
    <input type="text" name="format_used" style="width:110px" placeholder="Template A image">
    <label>Editor</label>
    <input type="text" name="editor" style="width:100px">
    <label>Notes</label>
    <input type="text" name="notes" style="width:180px">
    <button type="submit" class="primary">Mark Covered</button>
  </form>
  {_render_coverage_history(covered_posts)}

  <h2>Source articles ({len(articles)})</h2>
  <form id="split-form" method="post" action="/stories/{cluster['id']}/split"></form>
  <div class="split-bar">
    <button type="submit" form="split-form">Split checked into new story</button>
  </div>
  <table>
    <thead><tr><th></th><th style="width:40%">Headline</th><th>Source</th><th>Tier</th><th>Published</th><th>Detected</th><th></th></tr></thead>
    <tbody>{''.join(article_rows)}</tbody>
  </table>
"""
    return PAGE_HEAD + body + PAGE_TAIL


_TYPE_OPTIONS = [("rss", "RSS / Atom feed URL"), ("google_news", "Google News keyword query")]
_TIER_OPTIONS = [1, 2, 3, 4, 5]
_POLLING_OPTIONS = ["priority", "standard", "low"]


def _source_health(s: dict) -> tuple[str, str, str]:
    """Return (dot_color, label, tooltip) for a source's health indicator."""
    if not s.get("enabled"):
        return "#3a4055", "disabled", "Source is disabled"
    if s.get("last_error"):
        return "#f87171", "error", escape(s["last_error"][:120])
    raw = s.get("last_fetch_at_raw")
    if raw is None:
        return "#facc15", "never fetched", "This source has never been fetched"
    from datetime import datetime, timezone, timedelta
    if hasattr(raw, "tzinfo") and raw.tzinfo is None:
        raw = raw.replace(tzinfo=timezone.utc)
    age_h = (datetime.now(timezone.utc) - raw).total_seconds() / 3600
    if age_h > 48:
        return "#facc15", "stale", f"Last fetched {int(age_h // 24)}d ago"
    if s.get("articles_7d", 0) == 0:
        return "#facc15", "no stories", "Fetched OK but 0 stories in last 7 days"
    return "#4ade80", "ok", f"{s['articles_7d']} stories (7d)"


def render_sources_page(sources: list[dict]) -> str:
    # Summary counts
    n_ok      = sum(1 for s in sources if _source_health(s)[0] == "#4ade80")
    n_warn    = sum(1 for s in sources if _source_health(s)[0] == "#facc15")
    n_err     = sum(1 for s in sources if _source_health(s)[0] == "#f87171")
    n_dis     = sum(1 for s in sources if not s.get("enabled"))

    rows = []
    for s in sources:
        dot_color, health_label, health_tip = _source_health(s)
        type_options = "".join(
            f'<option value="{t}" {"selected" if s["type"] == t else ""}>{label}</option>'
            for t, label in _TYPE_OPTIONS
        )
        tier_options = "".join(
            f'<option value="{t}" {"selected" if s["credibility_tier"] == t else ""}>T{t}</option>'
            for t in _TIER_OPTIONS
        )
        polling_options = "".join(
            f'<option value="{p}" {"selected" if s["polling_tier"] == p else ""}>{p}</option>'
            for p in _POLLING_OPTIONS
        )
        arts = s.get("articles_7d", 0)
        arts_color = "#4ade80" if arts >= 10 else "#facc15" if arts >= 1 else "#f87171"
        arts_html = f'<span style="color:{arts_color};font-size:12px;font-weight:600">{arts}</span><span style="color:#3a4055;font-size:10px"> stories/7d</span>'

        rows.append(f"""
      <tr>
        <td data-label="Health" style="text-align:center;width:36px">
          <span title="{health_tip}" style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{dot_color};cursor:help;flex-shrink:0"></span>
        </td>
        <td data-label="Name">
          <a href="/?source_id={s['id']}">{escape(s['name'])}</a>
          <div style="font-size:10px;color:#3a4055;margin-top:1px">{escape(s['type'])}</div>
        </td>
        <td data-label="7d" style="white-space:nowrap">{arts_html}</td>
        <td data-label="Status" style="font-size:11px;color:#8b93a3;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
          {'<span style="color:#f87171">' + escape((s['last_error'] or '')[:80]) + '</span>' if s['last_error'] else escape(s['last_fetch_at'])}
        </td>
        <td data-label="Edit">
          <form method="post" action="/sources/{s['id']}/update" class="inline-form">
            <input type="text" name="category" value="{escape(s['category'] or '')}" style="width:90px" placeholder="category">
            <select name="credibility_tier">{tier_options}</select>
            <select name="polling_tier">{polling_options}</select>
            <input type="text" name="user_agent" value="{escape(s.get('user_agent') or '')}" style="width:110px" placeholder="UA override (blank=default)">
            <label><input type="checkbox" name="enabled" value="true" {"checked" if s['enabled'] else ""}> enabled</label>
            <label><input type="checkbox" name="show_in_main_feed" value="true" {"checked" if s.get('show_in_main_feed', True) else ""}> main feed</label>
            <button type="submit">Save</button>
          </form>
          <form method="post" action="/sources/{s['id']}/fetch" class="inline-form">
            <button type="submit">Fetch now</button>
          </form>
          <form method="post" action="/sources/{s['id']}/delete" class="inline-form"
                onsubmit="return confirm('Delete this source? This cannot be undone.')">
            <button type="submit" style="background:#3a1414;border-color:#7a2020;color:#f87171">Delete</button>
          </form>
        </td>
      </tr>""")

    type_options_new = "".join(f'<option value="{t}">{label}</option>' for t, label in _TYPE_OPTIONS)
    tier_options_new = "".join(f'<option value="{t}">T{t}</option>' for t in _TIER_OPTIONS)
    polling_options_new = "".join(f'<option value="{p}">{p}</option>' for p in _POLLING_OPTIONS)

    body = f"""
  <h1>Sources</h1>
  <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:18px;align-items:center">
    <span style="font-size:13px;color:#8b93a3">{len(sources)} sources</span>
    <span style="display:flex;align-items:center;gap:5px;font-size:12px">
      <span style="width:9px;height:9px;border-radius:50%;background:#4ade80;display:inline-block"></span>
      <span style="color:#c7cbd4">{n_ok} delivering</span>
    </span>
    <span style="display:flex;align-items:center;gap:5px;font-size:12px">
      <span style="width:9px;height:9px;border-radius:50%;background:#facc15;display:inline-block"></span>
      <span style="color:#c7cbd4">{n_warn} warning</span>
    </span>
    <span style="display:flex;align-items:center;gap:5px;font-size:12px">
      <span style="width:9px;height:9px;border-radius:50%;background:#f87171;display:inline-block"></span>
      <span style="color:#c7cbd4">{n_err} error</span>
    </span>
    <span style="display:flex;align-items:center;gap:5px;font-size:12px">
      <span style="width:9px;height:9px;border-radius:50%;background:#3a4055;display:inline-block"></span>
      <span style="color:#c7cbd4">{n_dis} disabled</span>
    </span>
  </div>

  <h2>Add a source</h2>
  <form method="post" action="/sources">
    <input type="text" name="name" placeholder="Source name" required>
    <select name="type">{type_options_new}</select>
    <input type="text" name="url_or_query" placeholder="Feed URL, or keyword query for Google News" required style="width:320px">
    <input type="text" name="category" placeholder="category">
    <select name="credibility_tier">{tier_options_new}</select>
    <select name="polling_tier">{polling_options_new}</select>
    <button type="submit" class="primary">Add source</button>
  </form>

  <h2>All sources</h2>
  <table>
    <thead><tr><th style="width:36px"></th><th>Name</th><th style="white-space:nowrap">Stories 7d</th><th>Status / Last error</th><th style="width:45%">Edit</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
"""
    return PAGE_HEAD + body + PAGE_TAIL


_STALE_DAYS = 14   # stories older than this are considered stale in the queue


def _item_age_days(item: dict) -> float:
    """Days since the item was added to the queue. Returns 0 if unknown."""
    from datetime import datetime, timezone
    ts = item.get("added_to_queue_at") or ""
    if not ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max((datetime.now(timezone.utc) - dt).total_seconds() / 86400, 0.0)
    except Exception:
        return 0.0


def _age_decay(age_days: float) -> float:
    """Score multiplier based on age. Returns 1.0 for fresh, 0.0 for 14+ days."""
    if age_days <= 1:   return 1.0
    if age_days <= 3:   return 0.7
    if age_days <= 7:   return 0.4
    if age_days <= 14:  return 0.15
    return 0.0


def render_pipeline_queue_page(
    items: list[dict],
    msg: str = "",
    job: dict | None = None,
    picks_ready: bool = False,
    picks_count: int = 0,
    picks_date: str = "",
    recommendation: dict | None = None,
    show_older: bool = False,
) -> str:
    pending   = [x for x in items if x.get("queue_status") == "pending"]
    approved  = [x for x in items if x.get("queue_status") == "approved"]
    used      = [x for x in items if x.get("queue_status") == "used"]
    skipped   = [x for x in items if x.get("queue_status") == "skipped"]

    # Split pending into fresh (≤14 days) and older (>14 days)
    pending_fresh = [x for x in pending if _item_age_days(x) <= _STALE_DAYS]
    pending_old   = [x for x in pending if _item_age_days(x) >  _STALE_DAYS]

    def _composite_sort_key(item: dict) -> float:
        """Decay-adjusted viral score × topic relevance (if scored). Higher = better."""
        age   = _item_age_days(item)
        decay = _age_decay(age)
        viral = float(item.get("viral_score") or 0)
        rel   = item.get("ai_topic_relevance")
        rel_factor = (float(rel) / 100.0) if rel is not None else 1.0
        return viral * decay * rel_factor

    pending_fresh.sort(key=_composite_sort_key, reverse=True)
    pending_old.sort(key=_composite_sort_key, reverse=True)

    # Build recommendation lookup {cluster_id: {template, reason, type}}
    rec_map: dict[int, dict] = {}
    if recommendation:
        for p in recommendation.get("image_picks", []):
            cid = p.get("cluster_id")
            if cid:
                rec_map[cid] = {"template": p.get("template","A"), "reason": p.get("reason",""), "gen_type": "image_card"}
        for p in recommendation.get("tobi_picks", []):
            cid = p.get("cluster_id")
            if cid:
                rec_map[cid] = {"template": "TOBI", "reason": p.get("reason",""), "gen_type": "tobi"}

    pending  = sorted(pending,  key=lambda x: x.get("added_to_queue_at", ""), reverse=True)
    approved = sorted(approved, key=lambda x: x.get("approved_at", ""),       reverse=True)

    flash = f'<div class="flash">{escape(msg)}</div>' if msg else ""

    def score_class(v):
        if v >= 80: return "score-hi"
        if v >= 65: return "score-mid"
        return "score-lo"

    def verif_badge(v):
        color = "#4ade80" if "multi" in (v or "") else "#facc15" if "verified" in (v or "") else "#8b93a3"
        label = "multi-source" if "multi" in (v or "") else (v or "").replace("_", " ")
        return f'<span class="badge" style="background:#11151f;color:{color}">{escape(label)}</span>'

    def tmpl_badge(t):
        color = "#3b82f6" if t == "B" else "#8b5cf6"
        label = f"Tmpl {t}"
        return f'<span class="badge" style="background:#11151f;color:{color};border:1px solid {color}">{label}</span>'

    def dedup_badge():
        return '<span class="badge" style="background:#3a1a00;color:#f97316;border:1px solid #7c3400">&#9888; SIMILAR</span>'

    def draft_toggle(cid, draft, item=None):
        if not draft:
            return (
                f'<button type="button" onclick="toggleDraft({cid})" '
                f'style="font-size:10px;padding:2px 7px;margin-top:4px;background:#1a2030;border:1px solid #2a3555;color:#8b93a3;cursor:pointer">'
                f'&#9998; Draft</button>'
                f'<div id="draft-{cid}" style="display:none;margin-top:8px;padding:10px;background:#0d111a;'
                f'border:1px solid #2a3555;border-radius:4px;font-size:12px;color:#8b93a3">'
                f'No draft yet. Run <strong>&#9998; Draft Queue</strong> above to auto-generate.'
                f'</div>'
            )
        hl      = escape((draft.get("headline") or "")[:100])
        tag     = escape(draft.get("tag") or "")
        cap     = escape((draft.get("captions") or {}).get("short") or "")
        scene   = escape((item or {}).get("scene") or (draft.get("image_scene") or "")[:100])
        opts    = draft.get("headline_options") or []
        opts_html = ""
        if opts:
            opts_html = '<div style="margin-top:8px"><div style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Headline Options</div>'
            for idx, opt in enumerate(opts[:3]):
                opt_esc = escape(str(opt)[:120])
                opts_html += (
                    f'<div style="display:flex;align-items:flex-start;gap:6px;margin-bottom:4px">'
                    f'<button type="button" onclick="pickHeadline({cid},{idx},this)" '
                    f'style="font-size:10px;padding:1px 6px;background:#1a2030;border:1px solid #2a3555;color:#8b93a3;cursor:pointer;flex-shrink:0;border-radius:3px">Use</button>'
                    f'<span style="color:#c0c8d8;font-size:11px">{opt_esc}</span>'
                    f'</div>'
                )
            opts_html += '</div>'
        scene_row = f'<div style="color:#8b93a3;font-size:10px;margin-top:6px">Scene: {scene}</div>' if scene else ""
        rewrite_btns = (
            '<div style="margin-top:8px;display:flex;gap:5px;flex-wrap:wrap">'
            + "".join(
                f'<button type="button" onclick="rewriteCap({cid},\'{v}\',this)" '
                f'style="font-size:10px;padding:2px 7px;background:#1a2030;border:1px solid #2a3555;color:#8b93a3;cursor:pointer;border-radius:3px">'
                f'&#8635; {label}</button>'
                for v, label in [("short","Short"),("medium","Medium"),("long","Long"),("extra_long","XL")]
            )
            + '</div>'
        )
        return (
            f'<button type="button" onclick="toggleDraft({cid})" '
            f'style="font-size:10px;padding:2px 7px;margin-top:4px;background:#1a2030;border:1px solid #2a3555;color:#8b93a3;cursor:pointer">'
            f'&#9998; Draft</button>'
            f'<div id="draft-{cid}" style="display:none;margin-top:8px;padding:10px;background:#0d111a;'
            f'border:1px solid #2a3555;border-radius:4px;font-size:12px;line-height:1.5">'
            f'<div id="hl-{cid}" style="color:#FFDE59;font-weight:700;margin-bottom:4px">{hl}</div>'
            f'<div style="color:#D02020;font-size:11px;margin-bottom:6px">&#9632; {tag}</div>'
            f'{opts_html}'
            f'{scene_row}'
            f'<div id="cap-short-{cid}" style="color:#c0c8d8;margin-top:6px">{cap}</div>'
            f'{rewrite_btns}'
            f'<div id="rewrite-status-{cid}" style="color:#8b93a3;font-size:10px;margin-top:4px"></div>'
            f'</div>'
        )

    def ai_score_cell(item):
        age_days = _item_age_days(item)
        decay    = _age_decay(age_days)
        if decay == 0.0:
            age_label = f"{int(age_days)}d"
            return f'<span style="color:#4a5568;font-size:10px;font-weight:600">STALE<br><span style="font-size:9px;font-weight:400">{age_label}</span></span>'
        ai  = item.get("ai_viral_score")
        raw = item.get("viral_score", 0)
        if ai is not None:
            effective = round(ai * decay)
            color = "#4ade80" if effective >= 70 else "#facc15" if effective >= 50 else "#8b93a3"
            reason = escape(item.get("ai_score_reason") or "")
            tip = f' title="{reason}"' if reason else ""
            decay_note = f'<span style="color:#4a5568;font-size:9px"> ×{decay}</span>' if decay < 1.0 else ""
            return f'<span style="color:{color};font-weight:600;cursor:default;font-size:13px"{tip}>{effective}</span>{decay_note}'
        if raw:
            effective = round(raw * decay)
            color = "#4ade80" if effective >= 70 else "#facc15" if effective >= 50 else "#8b93a3"
            decay_note = f'<span style="color:#4a5568;font-size:9px"> ×{decay}</span>' if decay < 1.0 else ""
            return f'<span style="color:{color}">{effective:.0f}</span>{decay_note}'
        return '<span style="color:#3a4055">—</span>'

    def make_rows(row_items, selectable=True):
        if not row_items:
            return '<tr><td colspan="6" style="color:#8b93a3;padding:20px 10px">Nothing here yet.</td></tr>'
        rows = []
        for item in row_items:
            cid      = item.get("cluster_id", "")
            text     = escape((item.get("text") or "")[:120])
            cat      = escape(item.get("category") or "")
            verif    = item.get("verification_status", "")
            added    = (item.get("added_to_queue_at") or "")[:16].replace("T", " ")
            gen_type = item.get("generation_type", "image_card")
            srcs     = item.get("source_count") or len(item.get("sources") or [])
            s_tmpl   = item.get("suggested_template") or ""
            dup_warn = item.get("dedup_warning")
            draft    = item.get("draft")
            rec      = rec_map.get(cid) if selectable else None

            needs_draft = item.get("needs_draft") and not (item.get("draft") or {}).get("headline")

            # BREAKING badge: high-momentum story detected within the last 6 hours
            _item_age_h = _item_age_days(item) * 24
            _is_breaking = (
                float(item.get("momentum_score") or 0) > 60
                and _item_age_h <= 6
            )

            badges = ""
            if _is_breaking:
                badges += ('<span class="badge" style="background:#7a0000;color:#fff;border:1px solid #cc0000;'
                           'font-weight:700;letter-spacing:.5px;animation:blink-red 1.4s step-start infinite">'
                           '&#128308; BREAKING</span> ')
            if rec:
                rec_reason = escape(rec.get("reason") or "")
                badges += (f'<span class="badge" style="background:#0a1a0a;color:#4ade80;border:1px solid #1a5a1a"'
                           f' title="{rec_reason}">&#9733; Recommended</span> ')
            if s_tmpl and not rec:
                badges += tmpl_badge(s_tmpl) + " "
            if dup_warn:
                badges += dedup_badge()
            if needs_draft:
                badges += ' <span class="badge" style="background:#1a1f00;color:#facc15;border:1px solid #5a5000">&#9998; Needs Draft — paste in chat</span>'
            dq = (item.get("draft_quality") or {})
            if dq.get("overall") == "NEEDS_REWRITE":
                flags_txt = "; ".join(dq.get("flags") or [])
                scores_txt = (f"headline:{dq.get('headline_score')} "
                              f"tag:{dq.get('tag_score')} "
                              f"hook:{dq.get('caption_hook_score')}")
                tip = escape(f"{scores_txt}" + (f" — {flags_txt}" if flags_txt else ""))
                badges += (f' <span class="badge" style="background:#1a0a0a;color:#f87171;border:1px solid #7a1a1a"'
                           f' title="{tip}">&#9888; Weak Draft</span>')

            if selectable:
                is_checked  = "checked" if rec else ""
                # Saved post_type wins; fall back to rec or template suggestion
                saved_type = item.get("post_type") or ""
                eff_type = saved_type or (rec.get("gen_type") if rec else None) or ("tobi" if s_tmpl == "tobi" else "image_card")
                img_sel  = "selected" if eff_type == "image_card" else ""
                tobi_sel = "selected" if eff_type == "tobi" else ""
                vid_sel  = "selected" if eff_type == "video_package" else ""
                type_cell = (
                    f'<select name="type_{cid}" id="type-sel-{cid}" onchange="onTypeChange({cid},this)" style="font-size:12px;padding:3px 6px">'
                    f'<option value="image_card" {img_sel}>Image Card</option>'
                    f'<option value="tobi" {tobi_sel}>TOBI</option>'
                    f'<option value="video_package" {vid_sel}>Video Package</option></select>'
                    f'<div id="tobi-write-wrap-{cid}" style="display:{"block" if eff_type == "tobi" else "none"};margin-top:4px">'
                    f'<button type="button" onclick="writeTOBI({cid},this)" '
                    f'style="font-size:10px;padding:2px 8px;background:#0a1a10;border:1px solid #1a5a30;color:#4ade80;cursor:pointer;border-radius:3px">&#9998; Write TOBI</button>'
                    f'<div id="tobi-panel-{cid}" style="display:none;margin-top:6px;padding:8px;background:#0d111a;border:1px solid #2a3555;border-radius:4px;font-size:12px"></div>'
                    f'</div>'
                    f'<div id="video-write-wrap-{cid}" style="display:{"block" if eff_type == "video_package" else "none"};margin-top:4px">'
                    f'<button type="button" onclick="writeVideoScript({cid},this)" '
                    f'style="font-size:10px;padding:2px 8px;background:#0a0a1a;border:1px solid #2a2060;color:#a78bfa;cursor:pointer;border-radius:3px">&#127916; Write Video Scripts</button>'
                    f'<div id="video-panel-{cid}" style="display:none;margin-top:6px;padding:8px;background:#0d111a;border:1px solid #2a3555;border-radius:4px;font-size:12px"></div>'
                    f'</div>'
                )
                check = f'<input type="checkbox" name="selected" value="{cid}" {is_checked}>'
            else:
                label_map = {"image_card": "Image Card", "tobi": "TOBI", "video_package": "Video Package"}
                label = label_map.get(gen_type, gen_type or "Image Card")
                type_cell = f'<span style="color:#8b93a3">{label}</span>'
                check = ""

            draft_html = draft_toggle(cid, draft, item) if selectable else ""

            # Story panel for approved (non-selectable) rows — shows headline, tag, captions, first comment
            story_panel_html = ""
            if not selectable and draft:
                hl  = escape((draft.get("headline") or "")[:160])
                tg  = escape(draft.get("tag") or "")
                fc  = escape(draft.get("first_comment") or "")
                caps = draft.get("captions") or {}
                c_short = escape(caps.get("short") or "")
                c_med   = escape(caps.get("medium") or "")
                c_long  = escape(caps.get("long") or "")
                c_xl    = escape(caps.get("extra_long") or "")
                scene   = escape(draft.get("image_scene") or "")
                inner = ""
                if tg:
                    inner += f'<div style="display:inline-block;background:#D02020;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:10px;margin-bottom:6px">{tg}</div>'
                if hl:
                    inner += f'<div style="color:#FFDE59;font-size:13px;font-weight:700;margin-bottom:6px">{hl}</div>'
                if scene:
                    inner += f'<div style="color:#60a5fa;font-size:10px;margin-bottom:8px">&#128247; Scene: {scene}</div>'
                if c_short:
                    inner += f'<div style="margin-bottom:8px"><span style="color:#8b93a3;font-size:10px">SHORT (30-50w):</span><div style="color:#c0c8d8;font-size:11px;margin-top:2px;line-height:1.5">{c_short}</div></div>'
                if c_med:
                    inner += f'<div style="margin-bottom:8px"><span style="color:#8b93a3;font-size:10px">MEDIUM (80-120w):</span><div style="color:#c0c8d8;font-size:11px;margin-top:2px;line-height:1.5">{c_med}</div></div>'
                if c_long:
                    inner += f'<div style="margin-bottom:8px"><span style="color:#8b93a3;font-size:10px">LONG ARTICLE (250-350w):</span><div style="color:#c0c8d8;font-size:11px;margin-top:2px;line-height:1.5;white-space:pre-wrap">{c_long}</div></div>'
                if c_xl:
                    inner += f'<div style="margin-bottom:8px"><span style="color:#8b93a3;font-size:10px">XL ARTICLE (450-600w):</span><div style="color:#c0c8d8;font-size:11px;margin-top:2px;line-height:1.5;white-space:pre-wrap">{c_xl}</div></div>'
                if fc:
                    inner += f'<div style="border-top:1px solid #1a1f2b;padding-top:6px;margin-top:4px"><span style="color:#8b93a3;font-size:10px">FIRST COMMENT:</span> <span style="color:#c0c8d8;font-size:11px">{fc}</span></div>'
                has_full_captions = bool(caps.get("medium") or caps.get("long"))
                gen_caps_btn = (
                    f'<button type="button" id="gencaps-btn-{cid}" onclick="generateAllCaptions({cid},this)" '
                    f'style="font-size:10px;padding:3px 10px;background:#0a1a10;border:1px solid #1a5a30;'
                    f'color:#4ade80;cursor:pointer;border-radius:3px;margin-bottom:10px">'
                    f'&#9998; Generate All Captions</button>'
                    f'<span id="gencaps-status-{cid}" style="font-size:10px;color:#8b93a3;margin-left:8px"></span>'
                    f'<div id="gencaps-result-{cid}"></div>'
                ) if not has_full_captions else ""
                if inner or not has_full_captions:
                    story_panel_html = (
                        f'<div style="margin-top:6px">'
                        f'<button type="button" onclick="toggleStory(\'{cid}\')" '
                        f'style="font-size:10px;padding:2px 8px;background:#0a1020;border:1px solid #2a3555;'
                        f'color:#c0c8d8;cursor:pointer;border-radius:3px">&#128196; Story &amp; Captions</button>'
                        f'<div id="story-{cid}" style="display:none;margin-top:8px;padding:10px;'
                        f'background:#060910;border:1px solid #1a1f2b;border-radius:4px">'
                        f'{gen_caps_btn}{inner}</div>'
                        f'</div>'
                    )

            # Video Package — persistent button+panel for ANY row that has scripts
            video_panel_html = ""
            vt = item.get("video_titles") or []
            vs = item.get("script_short") or ""
            vm = item.get("script_medium") or ""
            vl = item.get("script_long") or ""
            has_scripts = bool(vs or vm or vl)

            if has_scripts:
                vd = escape(item.get("reels_description") or "")
                vs_e = escape(vs); vm_e = escape(vm); vl_e = escape(vl)
                vp = escape(item.get("poll_question") or "")
                vf = escape(item.get("video_first_comment") or "")

                inner_v = ""
                if vt:
                    inner_v += '<div style="margin-bottom:10px"><div style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Reels Cover Titles</div>'
                    for i, t in enumerate(vt[:3], 1):
                        t_e = escape(t).replace("'", "&#39;")
                        inner_v += (
                            f'<div style="display:flex;align-items:flex-start;gap:6px;margin-bottom:4px">'
                            f'<span style="color:#a78bfa;font-size:10px;white-space:nowrap;margin-top:1px">Option {i}</span>'
                            f'<span style="color:#FFDE59;font-size:12px;font-weight:600;flex:1">{escape(t)}</span>'
                            f'<button type="button" onclick="copyEl(\'vt{i}-{cid}\')" style="font-size:9px;padding:1px 6px;flex-shrink:0">Copy</button>'
                            f'<span id="vt{i}-{cid}" style="display:none">{escape(t)}</span>'
                            f'</div>'
                        )
                    inner_v += '</div>'
                if vd:
                    inner_v += (
                        f'<div style="margin-bottom:10px"><div style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Reels Description</div>'
                        f'<div id="vd-{cid}" style="color:#c0c8d8;font-size:11px;line-height:1.6;white-space:pre-wrap">{vd}</div>'
                        f'<button type="button" onclick="copyEl(\'vd-{cid}\')" style="font-size:9px;padding:1px 6px;margin-top:4px">Copy</button></div>'
                    )
                for label_s, val_s, sid, col in [
                    ("SHORT (30-45s)",  vs_e, f"vs-{cid}", "#4ade80"),
                    ("MEDIUM (60-90s)", vm_e, f"vm-{cid}", "#60a5fa"),
                    ("LONG (120-180s)", vl_e, f"vl-{cid}", "#f59e0b"),
                ]:
                    if val_s:
                        inner_v += (
                            f'<div style="margin-bottom:12px;padding:10px;background:#060910;border-radius:4px;border-left:3px solid {col}">'
                            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
                            f'<span style="color:{col};font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px">{label_s}</span>'
                            f'<button type="button" onclick="copyEl(\'{sid}\')" style="font-size:9px;padding:1px 8px">Copy Script</button></div>'
                            f'<div id="{sid}" style="color:#c0c8d8;font-size:11px;line-height:1.8;white-space:pre-wrap">{val_s}</div></div>'
                        )
                if vp:
                    inner_v += (
                        f'<div style="margin-bottom:10px;padding:8px;background:#0d111a;border:1px solid #2a3555;border-radius:4px">'
                        f'<div style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Poll Question</div>'
                        f'<div id="vpoll-{cid}" style="color:#e6e8ec;font-size:12px;line-height:1.5;white-space:pre-wrap">{vp}</div>'
                        f'<button type="button" onclick="copyEl(\'vpoll-{cid}\')" style="font-size:9px;padding:1px 6px;margin-top:4px">Copy</button></div>'
                    )
                if vf:
                    inner_v += (
                        f'<div style="border-top:1px solid #1a1f2b;padding-top:8px;margin-top:4px">'
                        f'<div style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">First Comment</div>'
                        f'<div id="vfc-{cid}" style="color:#c0c8d8;font-size:11px;line-height:1.6;white-space:pre-wrap">{vf}</div>'
                        f'<button type="button" onclick="copyEl(\'vfc-{cid}\')" style="font-size:9px;padding:1px 6px;margin-top:4px">Copy</button></div>'
                    )

                video_panel_html = (
                    f'<div id="vidpanel-wrap-{cid}" style="display:none;margin-top:8px;padding:10px;'
                    f'background:#060910;border:1px solid #2a2060;border-radius:4px">'
                    f'{inner_v}</div>'
                )

            # Video Package persistent button — shown when scripts exist on any row
            video_saved_btn = ""
            if has_scripts:
                video_saved_btn = (
                    f'<button type="button" onclick="togglePanel(\'vidpanel-wrap-{cid}\')" '
                    f'style="font-size:10px;padding:2px 7px;margin-top:4px;margin-left:4px;background:#0a0a1a;'
                    f'border:1px solid #2a2060;color:#a78bfa;cursor:pointer;border-radius:3px">&#127916; Video</button>'
                )

            # Persistent TOBI panel — server-rendered when tobi_text is saved
            tobi_text_saved = escape(item.get("tobi_text") or (item.get("draft") or {}).get("tobi_text") or "")
            tobi_saved_btn = ""
            if tobi_text_saved:
                tobi_saved_btn = (
                    f'<button type="button" onclick="togglePanel(\'tobi-saved-{cid}\')" '
                    f'style="font-size:10px;padding:2px 7px;margin-top:4px;margin-left:4px;background:#0a1a10;'
                    f'border:1px solid #1a5a30;color:#4ade80;cursor:pointer;border-radius:3px">&#128221; TOBI</button>'
                    f'<div id="tobi-saved-{cid}" style="display:none;margin-top:8px;padding:10px;background:#0d111a;'
                    f'border:1px solid #1a5a30;border-radius:4px">'
                    f'<div style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">TOBI Post</div>'
                    f'<div id="tobi-text-{cid}" style="color:#c0c8d8;font-size:12px;line-height:1.6">{tobi_text_saved}</div>'
                    f'<button type="button" onclick="copyEl(\'tobi-text-{cid}\')" '
                    f'style="font-size:9px;padding:1px 8px;margin-top:6px">Copy</button>'
                    f'</div>'
                )

            angles_btn = (
                f'<button type="button" onclick="expandAngles({cid},this)" '
                f'style="font-size:10px;padding:2px 7px;margin-top:4px;margin-left:4px;background:#0a1020;'
                f'border:1px solid #2a3555;color:#60a5fa;cursor:pointer;border-radius:3px">&#9654; Angles</button>'
                f'<div id="angles-{cid}" style="display:none;margin-top:8px;padding:10px;background:#0d111a;'
                f'border:1px solid #2a3555;border-radius:4px;font-size:12px"></div>'
            ) if selectable else ""

            _raw_url = (item.get("source_url") or item.get("post_url")
                        or ((item.get("sources") or [{}])[0].get("url") or ""))
            src_url = escape(_raw_url)
            preview_btn = ""
            if src_url:
                preview_btn = (
                    f'<button type="button" onclick="previewSource({cid},this)" '
                    f'style="font-size:10px;padding:2px 7px;margin-top:4px;margin-left:4px;background:#0a1020;'
                    f'border:1px solid #2a3555;color:#a78bfa;cursor:pointer;border-radius:3px" '
                    f'data-url="{src_url}">&#128269; Preview</button>'
                    f'<div id="preview-{cid}" style="display:none;margin-top:8px;padding:10px;background:#0d111a;'
                    f'border:1px solid #2a3555;border-radius:4px;font-size:12px"></div>'
                )

            # Scores button — inline collapsible panel, server-rendered from item data
            _age_days_item = _item_age_days(item)
            _decay_item    = _age_decay(_age_days_item)

            def _score_bar(val, max_val=100, decayed=True):
                effective = val * (_decay_item if decayed else 1.0)
                pct = min(100, round((effective / max_val) * 100)) if max_val else 0
                col = "#4ade80" if pct >= 60 else "#facc15" if pct >= 30 else "#8b93a3"
                label = f"{effective:.0f}" + (f" ({val:.0f} raw)" if decayed and _decay_item < 1.0 else "")
                return (
                    f'<div style="display:flex;align-items:center;gap:6px">'
                    f'<div style="flex:1;height:4px;background:#1a1f2b;border-radius:2px">'
                    f'<div style="width:{pct}%;height:100%;background:{col};border-radius:2px"></div></div>'
                    f'<span style="color:{col};font-size:10px;width:60px;text-align:right">{label}</span>'
                    f'</div>'
                )

            vs   = float(item.get("viral_score") or 0)
            cs   = float(item.get("confidence_score") or 0)
            ms   = float(item.get("momentum_score") or 0)
            ai_e = item.get("ai_emotional_strength")
            ai_v = item.get("ai_visual_potential")
            ai_c = item.get("ai_conversation_potential")
            ai_n = item.get("ai_novelty")
            ai_r = item.get("ai_topic_relevance")

            age_label = (f"{int(_age_days_item)}d old" if _age_days_item >= 1
                         else f"{int(_age_days_item * 24)}h old")
            decay_note = ""
            if _decay_item == 0.0:
                decay_note = '<div style="color:#f87171;font-size:10px;margin-bottom:6px">&#9888; STALE — story is over 14 days old</div>'
            elif _decay_item < 1.0:
                decay_note = f'<div style="color:#facc15;font-size:10px;margin-bottom:6px">&#9202; Age decay ×{_decay_item} applied ({age_label})</div>'

            scores_inner = (
                f'{decay_note}'
                f'<div style="display:grid;grid-template-columns:110px 1fr;gap:5px 8px;align-items:center">'
                f'<span style="color:#8b93a3;font-size:10px">Viral</span>{_score_bar(vs)}'
                f'<span style="color:#8b93a3;font-size:10px">Confidence</span>{_score_bar(cs)}'
                f'<span style="color:#8b93a3;font-size:10px">Momentum</span>{_score_bar(ms)}'
            )
            if ai_e is not None:
                scores_inner += (
                    f'<span style="color:#8b93a3;font-size:10px;margin-top:6px;grid-column:1/-1;'
                    f'border-top:1px solid #1a1f2b;padding-top:5px">AI Scores (no decay)</span>'
                    f'<span style="color:#8b93a3;font-size:10px">Emotional</span>{_score_bar(float(ai_e), decayed=False)}'
                    f'<span style="color:#8b93a3;font-size:10px">Visual</span>{_score_bar(float(ai_v or 0), decayed=False)}'
                    f'<span style="color:#8b93a3;font-size:10px">Conversation</span>{_score_bar(float(ai_c or 0), decayed=False)}'
                    f'<span style="color:#8b93a3;font-size:10px">Novelty</span>{_score_bar(float(ai_n or 0), decayed=False)}'
                    + (f'<span style="color:#8b93a3;font-size:10px">&#127919; Relevance</span>{_score_bar(float(ai_r), decayed=False)}'
                       if ai_r is not None else
                       '<span style="color:#3a4055;font-size:10px;grid-column:1/-1">&#127919; Relevance — will score on new stories</span>')
                )
            scores_inner += '</div>'

            src_count = item.get("source_count") or len(item.get("sources") or [])
            scores_btn = (
                f'<button type="button" onclick="togglePanel(\'scores-{cid}\')" '
                f'style="font-size:10px;padding:2px 7px;margin-top:4px;margin-left:4px;background:#0a1020;'
                f'border:1px solid #2a3555;color:#facc15;cursor:pointer;border-radius:3px">'
                f'&#9733; Scores</button>'
                f'<div id="scores-{cid}" style="display:none;margin-top:8px;padding:10px;background:#0d111a;'
                f'border:1px solid #2a3555;border-radius:4px;font-size:12px;min-width:220px">'
                f'<div style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">'
                f'Scores &middot; {src_count} source(s) &middot; {age_label}</div>'
                f'{scores_inner}'
                f'</div>'
            )

            # Generated image display
            gen_img_url = item.get("generated_image_url") or ""
            gen_status  = item.get("image_gen_status") or ""
            gen_img_html = ""
            if gen_img_url:
                gen_img_html = (
                    f'<div style="margin-top:10px">'
                    f'<div style="color:#4ade80;font-size:10px;margin-bottom:4px">&#9989; Generated</div>'
                    f'<a href="{escape(gen_img_url)}" target="_blank">'
                    f'<img src="{escape(gen_img_url)}" alt="generated card"'
                    f' style="max-width:200px;width:100%;border-radius:4px;display:block;border:1px solid #2a3555">'
                    f'</a>'
                    f'<div style="margin-top:4px"><a href="{escape(gen_img_url)}" target="_blank" '
                    f'style="color:#60a5fa;font-size:10px">Open full image</a></div>'
                    f'</div>'
                )
            elif gen_status == "generating":
                gen_img_html = '<div style="margin-top:8px;color:#facc15;font-size:11px">&#9203; Generating image... (refresh in 60-90s)</div>'
            elif gen_status.startswith("error:"):
                gen_img_html = f'<div style="margin-top:8px;color:#f87171;font-size:10px">&#9888; {escape(gen_status)}</div>'

            rows.append(f"""
      <tr>
        <td style="width:28px">{check}</td>
        <td data-label="Story">
          <div style="font-size:13px;font-weight:500;line-height:1.4">{text}</div>
          <div style="color:#8b93a3;font-size:11px;margin-top:3px">{cat} &middot; {srcs} source(s) &middot; added {added}</div>
          <div style="margin-top:4px">{badges}</div>
          {draft_html}{story_panel_html}
          {video_panel_html}
          <div style="display:flex;flex-wrap:wrap;align-items:flex-start">
            <a href="/pipeline-queue/story/{cid}" style="font-size:10px;padding:2px 7px;margin-top:4px;margin-right:4px;background:#1e3a8a;border:1px solid #2563eb;color:#fff;border-radius:3px;text-decoration:none;display:inline-block">&#9998; Workspace</a>
            {angles_btn} {preview_btn} {tobi_saved_btn} {video_saved_btn} {scores_btn}
          </div>
          {gen_img_html}
        </td>
        <td data-label="Viral">{ai_score_cell(item)}</td>
        <td data-label="Verification">{verif_badge(verif)}</td>
        <td data-label="Type">{type_cell}</td>
      </tr>""")
        return "".join(rows)

    draft_js = """
<script>
function toggleDraft(cid) {
  var el = document.getElementById('draft-' + cid);
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function toggleStory(cid) {
  var el = document.getElementById('story-' + cid);
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function togglePanel(id) {
  var el = document.getElementById(id);
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function copyEl(id) {
  var el = document.getElementById(id);
  if (!el) return;
  var text = el.dataset.text || el.textContent || '';
  navigator.clipboard.writeText(text.trim()).catch(function(){
    var ta = document.createElement('textarea');
    ta.value = text.trim(); document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
  });
}

function copyText(btn, text) {
  navigator.clipboard.writeText((text||'').trim()).catch(function(){
    var ta = document.createElement('textarea');
    ta.value = (text||'').trim(); document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
  });
  var orig = btn.textContent; btn.textContent = '✓'; btn.style.color = '#4ade80';
  setTimeout(function(){ btn.textContent = orig; btn.style.color = ''; }, 1200);
}

function writeVideoScript(cid, btn, fromApproved) {
  var panel = fromApproved
    ? document.getElementById('story-vid-' + cid)
    : document.getElementById('video-panel-' + cid);
  var statusEl = document.getElementById('genvid-status-' + cid);
  if (panel && !fromApproved) { panel.style.display = 'block'; }
  var origText = btn.textContent;
  btn.disabled = true; btn.textContent = 'Writing scripts...';
  if (statusEl) statusEl.textContent = 'Calling AI...';
  var fd = new FormData(); fd.append('cluster_id', cid);
  fetch('/pipeline-queue/write-video-script', {method:'POST', body:fd})
    .then(function(r){return r.json();})
    .then(function(d){
      btn.disabled = false; btn.textContent = origText;
      if (statusEl) statusEl.textContent = '';
      if (d.error) {
        if (statusEl) statusEl.textContent = 'Error: ' + d.error;
        btn.disabled = false; btn.textContent = origText;
        return;
      }
      // Data is saved to DB. Reload so the server renders the full persistent panel.
      if (statusEl) statusEl.textContent = 'Done. Loading...';
      window.location.reload();
    })
    .catch(function(e){ btn.disabled=false; btn.textContent=origText; if(statusEl) statusEl.textContent='Request failed.'; });
}

function generateAllCaptions(cid, btn) {
  btn.disabled = true; btn.textContent = 'Generating...';
  var status = document.getElementById('gencaps-status-' + cid);
  if (status) status.textContent = 'Writing 4 variants...';
  var fd = new FormData(); fd.append('cluster_id', cid);
  fetch('/pipeline-queue/generate-all-captions', {method:'POST', body:fd})
    .then(function(r){return r.json();})
    .then(function(d){
      btn.disabled = false; btn.textContent = '✓ Done';
      if (status) status.textContent = '';
      if (d.error) { if (status) status.textContent = 'Error: ' + d.error; return; }
      var caps = d.captions || {};
      var fc   = d.first_comment || '';
      var html = '';
      var labels = {short:'SHORT (30-50w)',medium:'MEDIUM (80-120w)',long:'LONG ARTICLE (250-350w)',extra_long:'XL ARTICLE (450-600w)'};
      Object.keys(labels).forEach(function(k){
        if (caps[k]) html += '<div style="margin-bottom:8px"><span style="color:#8b93a3;font-size:10px">' + labels[k] + ':</span> <span style="color:#c0c8d8;font-size:11px">' + caps[k] + '</span></div>';
      });
      if (fc) html += '<div style="border-top:1px solid #1a1f2b;padding-top:6px;margin-top:4px"><span style="color:#8b93a3;font-size:10px">FIRST COMMENT:</span> <span style="color:#c0c8d8;font-size:11px">' + fc + '</span></div>';
      var res = document.getElementById('gencaps-result-' + cid);
      if (res) res.innerHTML = html;
      btn.style.display = 'none';
    })
    .catch(function(e){ btn.disabled=false; btn.textContent='Generate All Captions'; if(status) status.textContent='Request failed.'; });
}

function pickHeadline(cid, idx, btn) {
  var optSpan = btn.nextElementSibling;
  if (!optSpan) return;
  var newHl = optSpan.textContent.trim();
  var hlEl = document.getElementById('hl-' + cid);
  if (hlEl) hlEl.textContent = newHl;
  btn.textContent = '✓';
  btn.style.color = '#4ade80';
  setTimeout(function(){ btn.textContent = 'Use'; btn.style.color = '#8b93a3'; }, 1500);
}

function rewriteCap(cid, variant, btn) {
  var statusEl = document.getElementById('rewrite-status-' + cid);
  var orig = btn.textContent;
  btn.disabled = true; btn.textContent = '...';
  if (statusEl) statusEl.textContent = 'Rewriting ' + variant + '...';
  var fd = new FormData();
  fd.append('cluster_id', cid);
  fd.append('variant', variant);
  fetch('/pipeline-queue/rewrite-caption', {method:'POST', body:fd})
    .then(function(r){return r.json();})
    .then(function(d){
      btn.disabled = false; btn.textContent = orig;
      if (d.error) { if(statusEl) statusEl.textContent = 'Error: ' + d.error; return; }
      if (variant === 'short') {
        var capEl = document.getElementById('cap-short-' + cid);
        if (capEl) capEl.textContent = d.text;
      }
      if (statusEl) statusEl.textContent = '✓ ' + variant + ' rewritten';
      setTimeout(function(){ if(statusEl) statusEl.textContent=''; }, 3000);
    })
    .catch(function(){ btn.disabled=false; btn.textContent=orig; if(statusEl) statusEl.textContent='Request failed.'; });
}

function previewSource(cid, btn) {
  function _esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  var panel = document.getElementById('preview-' + cid);
  if (!panel) return;
  if (panel.style.display !== 'none') { panel.style.display = 'none'; btn.textContent = 'Preview'; return; }
  if (panel.dataset.loaded) { panel.style.display = 'block'; btn.textContent = '▲ Hide'; return; }
  var url = btn.dataset.url;
  if (!url) return;
  panel.style.display = 'block';
  panel.innerHTML = '<span style="color:#8b93a3;font-size:11px">Fetching article...</span>';
  btn.textContent = '▲ Hide';
  var xhr = new XMLHttpRequest();
  xhr.open('GET', '/pipeline-queue/preview-url?url=' + encodeURIComponent(url));
  xhr.onload = function() {
    try {
      var d = JSON.parse(xhr.responseText);
      panel.dataset.loaded = '1';
      if (d.error) {
        panel.innerHTML = '<span style="color:#f87171;font-size:11px">' + _esc(d.error) + '</span>'
          + ' <a href="' + _esc(url) + '" target="_blank" style="color:#60a5fa;font-size:11px;margin-left:8px">Open in tab ↗</a>';
        return;
      }
      var html = '';
      if (d.title) html += '<div style="color:#c0c8d8;font-size:12px;font-weight:600;margin-bottom:6px;line-height:1.4">' + _esc(d.title) + '</div>';
      if (d.snippet) html += '<div style="color:#8b93a3;font-size:11px;line-height:1.6;white-space:pre-wrap">' + _esc(d.snippet) + '</div>';
      html += '<a href="' + _esc(url) + '" target="_blank" style="display:inline-block;margin-top:8px;color:#60a5fa;font-size:10px">Open full article ↗</a>';
      panel.innerHTML = html;
    } catch(e) {
      panel.innerHTML = '<span style="color:#f87171;font-size:11px">Parse error.</span>';
    }
  };
  xhr.onerror = function() {
    panel.innerHTML = '<span style="color:#f87171;font-size:11px">Could not reach server.</span>';
  };
  xhr.send();
}

function expandAngles(cid, btn) {
  var panel = document.getElementById('angles-' + cid);
  if (!panel) return;
  if (panel.style.display !== 'none') { panel.style.display = 'none'; return; }
  panel.style.display = 'block';
  if (panel.dataset.loaded) return;
  panel.innerHTML = '<span style="color:#8b93a3">Loading angles...</span>';
  var fd = new FormData();
  fd.append('cluster_id', cid);
  fetch('/pipeline-queue/expand-angles', {method:'POST', body:fd})
    .then(function(r){return r.json();})
    .then(function(d){
      panel.dataset.loaded = '1';
      if (d.error) { panel.innerHTML = '<span style="color:#f87171">' + d.error + '</span>'; return; }
      var angles = d.angles || [];
      var html = '<div style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">3 Story Angles</div>';
      var colors = ['#f87171','#4ade80','#60a5fa'];
      angles.forEach(function(a, i){
        html += '<div style="margin-bottom:10px;padding:8px;background:#060910;border-radius:4px;border-left:3px solid ' + colors[i] + '">';
        html += '<div style="color:' + colors[i] + ';font-size:10px;text-transform:uppercase;font-weight:700;margin-bottom:3px">' + (a.angle_type||'') + ' &nbsp;&#9632;&nbsp; ' + (a.tag||'') + '</div>';
        html += '<div style="color:#FFDE59;font-size:12px;font-weight:600;margin-bottom:3px">' + (a.hook||'') + '</div>';
        html += '<div style="color:#c0c8d8;font-size:11px;margin-bottom:3px">' + (a.caption_lead||'') + '</div>';
        html += '<div style="color:#8b93a3;font-size:10px;margin-bottom:3px">' + (a.why||'') + '</div>';
        if (a.image_scene) {
          html += '<div style="color:#60a5fa;font-size:10px;font-style:italic;margin-bottom:3px">&#128247; ' + (a.image_scene||'') + '</div>';
        }
        html += '<button type="button" onclick="useAngle(' + cid + ',' + i + ',this)" '
          + 'style="margin-top:6px;font-size:10px;padding:2px 8px;background:#0a1a0a;border:1px solid #1a5a1a;'
          + 'color:#4ade80;cursor:pointer;border-radius:3px">&#10003; Use this angle</button>';
        html += '<div id="angle-status-' + cid + '-' + i + '" style="display:inline-block;margin-left:6px;font-size:10px;color:#8b93a3"></div>';
        html += '</div>';
      });
      panel._angles = angles;
      html += '<div style="margin-top:10px;padding:8px;background:#060910;border-radius:4px;border-left:3px solid #8b5cf6">';
      html += '<div style="color:#8b5cf6;font-size:10px;text-transform:uppercase;font-weight:700;margin-bottom:6px">&#9998; Custom</div>';
      html += '<div style="margin-bottom:4px"><label style="color:#8b93a3;font-size:10px">3-WORD TAG</label>'
        + '<input id="custom-tag-' + cid + '" type="text" maxlength="40" placeholder="e.g. JUST IN" '
        + 'style="display:block;width:100%;margin-top:2px;padding:4px 7px;background:#0d111a;border:1px solid #2a3555;'
        + 'color:#fff;font-size:12px;border-radius:3px;box-sizing:border-box"></div>';
      html += '<div style="margin-bottom:4px"><label style="color:#8b93a3;font-size:10px">MAIN HEADLINE</label>'
        + '<input id="custom-hook-' + cid + '" type="text" maxlength="120" placeholder="Your headline here" '
        + 'style="display:block;width:100%;margin-top:2px;padding:4px 7px;background:#0d111a;border:1px solid #2a3555;'
        + 'color:#FFDE59;font-size:12px;border-radius:3px;box-sizing:border-box"></div>';
      html += '<div style="margin-bottom:6px"><label style="color:#8b93a3;font-size:10px">IMAGE SCENE</label>'
        + '<input id="custom-scene-' + cid + '" type="text" maxlength="200" placeholder="e.g. US Capitol exterior, dramatic sky" '
        + 'style="display:block;width:100%;margin-top:2px;padding:4px 7px;background:#0d111a;border:1px solid #2a3555;'
        + 'color:#60a5fa;font-size:12px;border-radius:3px;box-sizing:border-box"></div>';
      html += '<button type="button" onclick="useCustomAngle(' + cid + ',this)" '
        + 'style="font-size:10px;padding:2px 8px;background:#0a0a1a;border:1px solid #5a3a9a;'
        + 'color:#8b5cf6;cursor:pointer;border-radius:3px">&#10003; Use custom</button>';
      html += '<span id="custom-angle-status-' + cid + '" style="margin-left:6px;font-size:10px;color:#8b93a3"></span>';
      html += '</div>';
      panel.innerHTML = html;
    })
    .catch(function(){ panel.innerHTML = '<span style="color:#f87171">Request failed.</span>'; });
}

function useAngle(cid, idx, btn) {
  var panel = document.getElementById('angles-' + cid);
  if (!panel || !panel._angles) return;
  var a = panel._angles[idx];
  if (!a) return;
  var status = document.getElementById('angle-status-' + cid + '-' + idx);
  btn.disabled = true;
  if (status) status.textContent = 'Saving...';
  fetch('/pipeline-queue/apply-angle', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: 'cluster_id=' + encodeURIComponent(cid)
      + '&hook=' + encodeURIComponent(a.hook||'')
      + '&tag=' + encodeURIComponent(a.tag||'')
      + '&caption_lead=' + encodeURIComponent(a.caption_lead||'')
      + '&image_scene=' + encodeURIComponent(a.image_scene||'')
      + '&angle_type=' + encodeURIComponent(a.angle_type||'')
  })
  .then(function(r){ return r.json(); })
  .then(function(d){
    if (d.ok) {
      if (status) status.textContent = 'Applied!';
      /* Update the headline display in the draft panel if open */
      var hl = document.getElementById('hl-' + cid);
      if (hl) hl.textContent = a.hook || '';
    } else {
      if (status) status.textContent = d.error || 'Error';
      btn.disabled = false;
    }
  })
  .catch(function(){ if (status) status.textContent = 'Failed'; btn.disabled = false; });
}

function onTypeChange(cid, sel) {
  var tobiWrap  = document.getElementById('tobi-write-wrap-' + cid);
  var videoWrap = document.getElementById('video-write-wrap-' + cid);
  if (tobiWrap)  tobiWrap.style.display  = sel.value === 'tobi'          ? 'block' : 'none';
  if (videoWrap) videoWrap.style.display = sel.value === 'video_package' ? 'block' : 'none';
  // Persist immediately so the type survives the 30s auto-refresh
  var fd = new FormData();
  fd.append('cluster_id', cid);
  fd.append('post_type', sel.value);
  fetch('/pipeline-queue/set-post-type', {method:'POST', body:fd}).catch(function(){});
}

function writeTOBI(cid, btn) {
  var panel = document.getElementById('tobi-panel-' + cid);
  if (!panel) return;
  if (panel.style.display !== 'none') { panel.style.display = 'none'; return; }
  if (panel.dataset.loaded) { panel.style.display = 'block'; return; }
  btn.textContent = 'Writing...';
  btn.disabled = true;
  fetch('/pipeline-queue/write-tobi', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: 'cluster_id=' + encodeURIComponent(cid)
  })
  .then(function(r){ return r.json(); })
  .then(function(d){
    btn.textContent = '✎ Write TOBI';
    btn.disabled = false;
    if (d.error) { panel.innerHTML = '<span style="color:#f87171">' + d.error + '</span>'; panel.style.display = 'block'; return; }
    var options = d.options || [];
    var html = '';
    options.forEach(function(opt, i) {
      html += '<div style="margin-bottom:8px;padding:8px;background:#060910;border-radius:4px;border-left:3px solid #4ade80">';
      html += '<div style="color:#c0c8d8;font-size:12px;line-height:1.5;margin-bottom:5px">' + opt + '</div>';
      html += '<button type="button" onclick="useTOBI(' + cid + ',' + i + ',this)" '
        + 'style="font-size:10px;padding:2px 8px;background:#0a1a0a;border:1px solid #1a5a1a;color:#4ade80;cursor:pointer;border-radius:3px">&#10003; Use this</button>';
      html += '<span id="tobi-status-' + cid + '-' + i + '" style="margin-left:6px;font-size:10px;color:#8b93a3"></span>';
      html += '</div>';
    });
    panel._options = options;
    panel.innerHTML = html;
    panel.dataset.loaded = '1';
    panel.style.display = 'block';
  })
  .catch(function(){ btn.textContent = '✎ Write TOBI'; btn.disabled = false; panel.innerHTML = '<span style="color:#f87171">Request failed.</span>'; panel.style.display = 'block'; });
}

function useTOBI(cid, idx, btn) {
  var panel = document.getElementById('tobi-panel-' + cid);
  var text = panel && panel._options ? panel._options[idx] : null;
  if (!text) return;
  var status = document.getElementById('tobi-status-' + cid + '-' + idx);
  btn.disabled = true;
  if (status) status.textContent = 'Saving...';
  fetch('/pipeline-queue/apply-tobi', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: 'cluster_id=' + encodeURIComponent(cid) + '&text=' + encodeURIComponent(text)
  })
  .then(function(r){ return r.json(); })
  .then(function(d){
    if (d.ok) {
      if (status) status.textContent = 'Saved. Loading...';
      window.location.reload();
    } else {
      if (status) status.textContent = d.error || 'Error';
      btn.disabled = false;
    }
  })
  .catch(function(){ if (status) status.textContent = 'Failed'; btn.disabled = false; });
}

function useCustomAngle(cid, btn) {
  var hook  = (document.getElementById('custom-hook-' + cid) || {}).value || '';
  var tag   = (document.getElementById('custom-tag-' + cid) || {}).value || '';
  var scene = (document.getElementById('custom-scene-' + cid) || {}).value || '';
  var status = document.getElementById('custom-angle-status-' + cid);
  if (!hook.trim()) { if (status) status.textContent = 'Enter a headline first.'; return; }
  btn.disabled = true;
  if (status) status.textContent = 'Saving...';
  fetch('/pipeline-queue/apply-angle', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: 'cluster_id=' + encodeURIComponent(cid)
      + '&hook=' + encodeURIComponent(hook)
      + '&tag=' + encodeURIComponent(tag)
      + '&image_scene=' + encodeURIComponent(scene)
      + '&angle_type=custom'
  })
  .then(function(r){ return r.json(); })
  .then(function(d){
    if (d.ok) {
      if (status) status.textContent = 'Applied!';
      var hl = document.getElementById('hl-' + cid);
      if (hl) hl.textContent = hook;
      btn.disabled = false;
    } else {
      if (status) status.textContent = d.error || 'Error';
      btn.disabled = false;
    }
  })
  .catch(function(){ if (status) status.textContent = 'Failed'; btn.disabled = false; });
}
</script>"""

    rec_age_str = ""
    if recommendation:
        rec_age_str = f' &middot; recommended {(recommendation.get("generated_at") or "")[:16].replace("T"," ")}'

    full_batch_btn = ""
    if len(pending) >= 5:
        rec_note = (f'<span style="color:#4ade80">&#9733; Recommendation loaded — {len(rec_map)} stories pre-selected</span>{rec_age_str}'
                    if recommendation else
                    f'No recommendation yet — click &#9733; Recommend Batch first, or run without it.')
        full_batch_btn = f"""
  <div style="background:#0d111a;border:1px solid #2a3555;border-radius:6px;padding:14px 16px;margin-bottom:16px">
    <div style="display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:10px">
      <div>
        <div style="font-size:13px;font-weight:600;color:#c0c8d8">Batch Controls</div>
        <div style="font-size:11px;color:#8b93a3;margin-top:3px">{rec_note}</div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <form method="post" action="/pipeline-queue/recommend-batch" style="margin:0">
          <button type="submit" style="white-space:nowrap;background:#0a1a0a;border-color:#1a5a1a;color:#4ade80">&#9733;&nbsp;Recommend Batch</button>
        </form>
        <form method="post" action="/pipeline-queue/full-batch" style="margin:0">
          <button type="submit" class="primary" style="white-space:nowrap">&#9654;&#9654;&nbsp;Run Full Batch (17)</button>
        </form>
      </div>
    </div>
    <div style="font-size:11px;color:#8b93a3">
      <b>Recommend Batch</b> — AI picks top 12 image + 5 TOBI and pre-selects them below (hover &#9733; badges for reasoning).
      &nbsp;&nbsp;<b>Run Full Batch (17)</b> — auto-selects top {len(pending)} stories, marks approved, ready for drafting.
      Stories without FSN drafts will be flagged — type <code style="background:#060910;padding:1px 5px;border-radius:3px">draft the queue</code> in chat.
    </div>
  </div>"""

    displayed_pending = pending if show_older else pending_fresh
    older_toggle = ""
    if pending_old:
        if show_older:
            older_toggle = (
                f'<a href="/pipeline-queue" style="font-size:11px;color:#8b93a3;margin-left:12px">'
                f'&#8593; Hide older stories</a>'
            )
        else:
            older_toggle = (
                f'<a href="/pipeline-queue?show_older=1" style="font-size:11px;color:#facc15;margin-left:12px">'
                f'&#9202; Show {len(pending_old)} older stor{"y" if len(pending_old)==1 else "ies"} (&gt;14 days)</a>'
            )

    pending_section = f"""
  {full_batch_btn}
  <h2>Pending ({len(displayed_pending)}{f" of {len(pending)}" if not show_older and pending_old else ""})</h2>
  <p class="sub">Select stories, choose Image Card or TOBI for each, then send to generation. Tmpl badge = suggested template. &#9888; SIMILAR = story may already be posted.</p>
  <form method="post" action="/pipeline-queue/generate" id="qf">
    <div style="margin-bottom:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button type="button" onclick="document.querySelectorAll('#qf input[type=checkbox]').forEach(c=>c.checked=true)" style="font-size:11px">Select All</button>
      <button type="button" onclick="document.querySelectorAll('#qf input[type=checkbox]').forEach(c=>c.checked=false)" style="font-size:11px">Clear</button>
      <button type="submit" name="action" value="generate" class="primary" style="margin-left:8px">&#9654;&nbsp;Send Selected to Generation</button>
      <button type="submit" name="action" value="remove" style="background:#3a1414;border-color:#7a2020">&#10005;&nbsp;Remove Selected</button>
      {older_toggle}
    </div>
    <table>
      <thead><tr><th></th><th>Story</th><th>Viral</th><th>Verified</th><th>Type</th></tr></thead>
      <tbody>{make_rows(displayed_pending)}</tbody>
    </table>
  </form>
  {draft_js}"""

    approved_section = ""
    if approved:
        needs_draft_count = sum(1 for x in approved if x.get("needs_draft") and not (x.get("draft") or {}).get("headline"))
        draft_warn = ""
        if needs_draft_count:
            draft_warn = (
                f'<div style="background:#1a1800;border:1px solid #5a5000;border-radius:6px;padding:12px 14px;margin-bottom:12px">'
                f'<div style="color:#facc15;font-size:12px;font-weight:600;margin-bottom:6px">&#9998; {needs_draft_count} story(s) need FSN drafts before generation</div>'
                f'<div style="color:#c0c8d8;font-size:11px;line-height:1.7;margin-bottom:10px">'
                f'<b>Option A (recommended):</b> Type <code style="background:#060910;padding:1px 5px;border-radius:3px">draft the queue</code> in Claude Code chat. '
                f'Claude writes FSN headlines, tags, and 4 caption variants for every flagged story and updates the queue automatically.<br>'
                f'<b>Option B (API key required):</b> Click the button below to auto-draft via Claude API — requires <code style="background:#060910;padding:1px 5px;border-radius:3px">ANTHROPIC_API_KEY</code> in .env.<br>'
                f'<span style="color:#8b93a3">Generation works without drafts — raw scanner text is the fallback — but FSN-drafted content produces sharper cards.</span>'
                f'</div>'
                f'<form method="post" action="/pipeline-queue/draft-queue" style="margin:0">'
                f'<button type="submit" style="font-size:11px;background:#2a2000;border-color:#7a5a00;color:#facc15">&#9998; Auto-Draft via API</button>'
                f'</form>'
                f'</div>'
            )
        critique_panel = """
  <div id="critique-panel" style="margin-bottom:12px">
    <div style="display:flex;align-items:center;gap:8px">
      <button id="critique-btn" onclick="runCritique(this)" type="button"
        style="font-size:11px;background:#0a1020;border:1px solid #2a3555;color:#8b93a3;padding:4px 10px;cursor:pointer;border-radius:4px">
        &#128269; Critique Batch
      </button>
      <span id="critique-status" style="color:#8b93a3;font-size:11px"></span>
    </div>
    <div id="critique-result" style="margin-top:10px"></div>
  </div>
  <script>
  function runCritique(btn) {
    var status = document.getElementById('critique-status');
    var result = document.getElementById('critique-result');
    btn.disabled = true; btn.textContent = '&#128269; Analysing...';
    status.textContent = 'Claude is reviewing your batch...';
    result.innerHTML = '';
    fetch('/pipeline-queue/critique-batch', {method:'POST'})
      .then(function(r){return r.json();})
      .then(function(d){
        btn.disabled = false; btn.textContent = '&#128269; Critique Batch';
        if (d.error) { status.textContent = 'Error: ' + d.error; return; }
        var overall = d.overall || 'REVIEW_FIRST';
        var color = overall === 'APPROVE' ? '#4ade80' : '#f87171';
        var issues = d.issues || [];
        var html = '<div style="background:#060910;border:1px solid #1a2340;border-radius:6px;padding:12px;font-size:12px">';
        html += '<div style="font-weight:700;color:' + color + ';margin-bottom:8px">' + overall + ' — ' + (d.summary||'') + '</div>';
        html += '<div style="color:#8b93a3;font-size:10px;margin-bottom:6px">Portraits: ' + (d.portrait_count||0) + '/2 cap &nbsp;|&nbsp; Topic variety: ' + (d.topic_variety||'?') + '</div>';
        if (issues.length) {
          issues.forEach(function(iss){
            var sev = iss.severity === 'high' ? '#f87171' : iss.severity === 'medium' ? '#facc15' : '#8b93a3';
            html += '<div style="color:' + sev + ';margin-bottom:4px">&#9654; [' + (iss.type||'').replace(/_/g,' ') + '] ' + (iss.description||'') + '</div>';
          });
        } else {
          html += '<div style="color:#4ade80">No issues found.</div>';
        }
        html += '</div>';
        result.innerHTML = html;
        status.textContent = '';
      })
      .catch(function(e){ btn.disabled=false; btn.textContent='&#128269; Critique Batch'; status.textContent='Request failed.'; });
  }
  </script>"""

        n_generating = sum(1 for x in approved if x.get("image_gen_status") == "generating")
        n_done       = sum(1 for x in approved if x.get("image_gen_status") == "done")
        gen_status_bar = ""
        if n_generating or n_done:
            gen_status_bar = (
                f'<div style="margin-bottom:10px;padding:10px 14px;background:#0d111a;border:1px solid #2a3555;border-radius:5px;font-size:12px">'
                f'<span style="color:#facc15">&#9203; {n_generating} generating</span>'
                f'&nbsp;&nbsp;<span style="color:#4ade80">&#9989; {n_done} done</span>'
                f'&nbsp;&nbsp;<span style="color:#8b93a3">{len(approved)-n_generating-n_done} queued</span>'
                + (' &nbsp;<span style="color:#8b93a3;font-size:10px">— page refreshes every 15s</span>' if n_generating else '')
                + '</div>'
            )

        approved_section = f"""
  <h2 style="margin-top:32px">Ready for Generation ({len(approved)})</h2>
  {gen_status_bar}
  {draft_warn}
  {critique_panel}
  <form method="post" action="/pipeline-queue/recall">
    <div style="margin-bottom:8px">
      <button type="submit" style="font-size:11px">&#8592; Move All Back to Pending</button>
    </div>
    <table>
      <thead><tr><th></th><th>Story</th><th>Viral</th><th>Verified</th><th>Type</th></tr></thead>
      <tbody>{make_rows(approved, selectable=False)}</tbody>
    </table>
  </form>"""

    history_section = ""
    if used or skipped:
        hist = sorted(used + skipped, key=lambda x: x.get("added_to_queue_at",""), reverse=True)[:20]
        hist_rows = []
        for i in hist:
            cid       = i.get("cluster_id", "")
            status    = i.get("queue_status", "")
            text      = escape((i.get("text") or "")[:120])
            src_url   = i.get("source_url") or ""
            raw_text  = escape((i.get("raw_text") or "")[:600])
            added     = (i.get("added_to_queue_at") or "")[:16].replace("T", " ")
            approved  = (i.get("approved_at") or "")[:16].replace("T", " ")
            cat       = escape(i.get("category") or "")
            draft     = i.get("draft") or {}
            hl        = escape((draft.get("headline") or "")[:120])
            tag       = escape(draft.get("tag") or "")
            cap_short = escape((draft.get("captions") or {}).get("short") or "")
            fc        = escape(draft.get("first_comment") or "")
            manual    = i.get("manual", False)
            sc        = i.get("viral_score", 0)
            output_file = i.get("output_file") or ""
            status_color = "#4ade80" if status == "used" else "#8b93a3"

            url_row = ""
            if src_url:
                url_row = f'<div style="margin-top:6px"><span style="color:#8b93a3;font-size:10px">URL: </span><a href="{escape(src_url)}" target="_blank" style="color:#60a5fa;font-size:11px;word-break:break-all">{escape(src_url)}</a></div>'

            raw_row = f'<div style="margin-top:6px"><span style="color:#8b93a3;font-size:10px">Raw text: </span><span style="color:#c0c8d8;font-size:11px">{raw_text}</span></div>' if raw_text else ""

            img_row = ""
            if output_file:
                import urllib.parse as _up
                img_src = "/pipeline-queue/history-image?path=" + _up.quote(output_file, safe="")
                img_row = (
                    f'<div style="margin-top:10px">'
                    f'<img src="{img_src}" alt="generated card"'
                    f' style="max-width:220px;width:100%;border-radius:4px;display:block">'
                    f'</div>'
                )

            draft_row = ""
            if hl:
                draft_row = (
                    f'<div style="margin-top:8px;padding:8px;background:#060910;border-radius:4px">'
                    f'<div style="color:#FFDE59;font-size:11px;font-weight:700">{hl}</div>'
                    + (f'<div style="color:#D02020;font-size:10px;margin-top:3px">&#9632; {tag}</div>' if tag else "")
                    + (f'<div style="color:#c0c8d8;font-size:11px;margin-top:4px">{cap_short}</div>' if cap_short else "")
                    + (f'<div style="color:#8b93a3;font-size:10px;margin-top:4px;border-top:1px solid #1a1f2b;padding-top:4px">First comment: {fc}</div>' if fc else "")
                    + f'</div>'
                )

            detail_id = f"hist-{cid}"
            meta = f'{"Manual" if manual else f"{cat} &middot; score {sc:.0f}"} &middot; added {added}' + (f" &middot; approved {approved}" if approved else "")

            hist_rows.append(
                f'<tr>'
                f'<td style="color:{status_color};font-size:11px;width:55px;vertical-align:top;padding-top:10px">{status}</td>'
                f'<td style="padding:6px 10px">'
                f'  <div style="font-size:12px;color:#c0c8d8;cursor:pointer;font-weight:500" onclick="toggleHist(\'{detail_id}\')">'
                f'    {text} <span style="color:#3b82f6;font-size:10px">&#9660;</span>'
                f'  </div>'
                f'  <div style="font-size:10px;color:#8b93a3;margin-top:2px">{meta}</div>'
                f'  <div id="{detail_id}" style="display:none;margin-top:8px;padding:10px;background:#0d111a;border:1px solid #2a3555;border-radius:4px">'
                f'    {img_row}{url_row}{raw_row}{draft_row}'
                f'  </div>'
                f'</td>'
                f'</tr>'
            )

        hist_js = """<script>
function toggleHist(id) {
  var el = document.getElementById(id);
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
</script>"""

        history_section = f"""
  <h2 style="margin-top:32px;color:#8b93a3">Recent History <span style="font-size:11px;font-weight:400">(last 20)</span></h2>
  <table><tbody>{"".join(hist_rows)}</tbody></table>
  {hist_js}"""

    # Determine initial panel state server-side (eliminates JS timing race)
    _job        = job or {}
    _job_status = _job.get("status", "idle")
    def _disp(panel_id):
        if _job_status == "running"                     and panel_id == "gen-running":  return "block"
        if _job_status == "done"                        and panel_id == "gen-done":     return "block"
        if _job_status == "error"                       and panel_id == "gen-error":    return "block"
        if _job_status not in ("running","done","error") and picks_ready and panel_id == "gen-idle": return "block"
        if _job_status not in ("running","done","error") and not picks_ready and panel_id == "gen-no-content": return "block"
        return "none"
    # Pre-fill summary line when done (server-side)
    _bd = (_job.get("batch_dir") or "").replace("\\", "/").split("/")
    _bd_name = _bd[-1] if _bd else ""
    _done_summary = (
        f'{_job.get("completed",0)} image card(s) + {_job.get("n_tobi",0)} TOBI(s) &middot; output/{escape(_bd_name)}'
        if _job_status == "done" else ""
    )
    # Only show error log when status is actually error (not stale from a previous run)
    _err_log = escape("\n".join((_job.get("log") or [])[-8:])) if _job_status == "error" else ""
    # picks-info text when idle
    _picks_info = f'{picks_count} post(s) drafted &middot; batch date {escape(picks_date)}' if picks_ready else ""

    gen_panel = f"""
<div id="gen-panel" style="margin-bottom:24px;padding:16px 20px;border-radius:6px;border:1px solid #2a3555;background:#0d111a">

  <!-- idle: content ready, waiting for generate click -->
  <div id="gen-idle" style="display:{_disp('gen-idle')}">
    <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
      <div>
        <div style="font-size:13px;font-weight:600;color:#c0c8d8">&#9654; Content ready in pipeline</div>
        <div id="picks-info" style="font-size:11px;color:#8b93a3;margin-top:2px">{_picks_info}</div>
      </div>
      <form method="post" action="/pipeline-queue/run-batch" style="margin:0">
        <button type="submit" class="primary" style="padding:8px 18px;font-size:13px">&#9654;&nbsp;Generate Images Now</button>
      </form>
    </div>
  </div>

  <!-- running: progress bar + live log -->
  <div id="gen-running" style="display:{_disp('gen-running')}">
    <div style="font-size:13px;font-weight:600;color:#FFDE59;margin-bottom:8px">&#9654; Generating...</div>
    <div style="background:#11151f;border-radius:4px;height:8px;overflow:hidden;margin-bottom:10px">
      <div id="gen-bar" style="height:100%;background:#FFDE59;width:0%;transition:width 0.5s"></div>
    </div>
    <div id="gen-count" style="font-size:11px;color:#8b93a3;margin-bottom:4px"></div>
    <div id="gen-timer" style="font-size:12px;color:#FFDE59;margin-bottom:8px;font-variant-numeric:tabular-nums"></div>
    <div id="gen-log" style="font-size:11px;font-family:monospace;color:#8b93a3;max-height:100px;overflow-y:auto;background:#060910;padding:8px;border-radius:4px;line-height:1.6"></div>
  </div>

  <!-- done: summary + full output viewer -->
  <div id="gen-done" style="display:{_disp('gen-done')}">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:16px">
      <div>
        <div style="font-size:13px;font-weight:600;color:#4ade80">&#10003; Generation complete</div>
        <div id="gen-summary" style="font-size:11px;color:#8b93a3;margin-top:2px">{_done_summary}</div>
      </div>
      <form method="post" action="/pipeline-queue/clear-job" style="margin:0">
        <button type="submit" style="font-size:11px">&#10005; Dismiss</button>
      </form>
    </div>
    <div id="output-viewer"></div>
  </div>

  <!-- error -->
  <div id="gen-error" style="display:{_disp('gen-error')}">
    <div style="font-size:13px;font-weight:600;color:#f87171;margin-bottom:6px">&#9888; Generation error</div>
    <div id="gen-err-msg" style="font-size:11px;font-family:monospace;color:#f87171;max-height:80px;overflow-y:auto;white-space:pre-wrap">{_err_log}</div>
    <form method="post" action="/pipeline-queue/clear-job" style="margin:0;margin-top:8px">
      <button type="submit" style="font-size:11px">Dismiss</button>
    </form>
  </div>

  <!-- no content yet -->
  <div id="gen-no-content" style="display:{_disp('gen-no-content')}">
    <div style="font-size:12px;color:#8b93a3">
      No content ready yet. Select stories above and click <b>Send Selected to Generation</b>,
      or run <code style="background:#11151f;padding:1px 5px;border-radius:3px">/batch source 4</code>
      in Claude Code to draft post content, then return here to generate images.
    </div>
  </div>
</div>
"""

    # Plain (non-f) string from here on -- this JS is full of literal single
    # braces (function bodies, object literals) that an f-string would try to
    # parse as interpolation expressions and fail on. Same pattern already
    # used correctly for draft_js above; gen_panel was an f-string all the way
    # through the closing </script>, which is what broke on startup
    # (SyntaxError at the JS's first `{`, Python trying to read `function() {
    # var _outputLoaded = false; ...` as a Python expression).
    gen_panel_js = """
<script>
(function() {
  var _outputLoaded = false;

  function esc(s) {
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function showCap(cid, variant) {
    var el = document.getElementById(cid);
    var scriptEl = document.getElementById('caps-' + cid);
    if (!el || !scriptEl) return;
    var caps = JSON.parse(scriptEl.textContent || '{}');
    var fc   = el.getAttribute('data-fc') || '';
    var text = caps[variant] || '';
    var open = el.getAttribute('data-open') === variant;
    if (open) { el.style.display='none'; el.removeAttribute('data-open'); return; }
    el.style.display = 'block';
    el.setAttribute('data-open', variant);
    el.dataset.variant = variant;
    el.innerHTML = '<div style="white-space:pre-wrap">' + esc(text) + '</div>' +
      (fc ? '<div style="color:#8b93a3;font-size:10px;margin-top:8px;padding-top:6px;border-top:1px solid #2a3555"><b>First comment:</b> ' + esc(fc) + '</div>' : '');
  }
  window.showCap = showCap;

  function copyText(text, btn) {
    navigator.clipboard.writeText(text).then(function() {
      var orig = btn.textContent;
      btn.textContent = 'Copied!';
      btn.style.color = '#4ade80';
      setTimeout(function(){ btn.textContent = orig; btn.style.color = ''; }, 1800);
    }).catch(function() {
      // Fallback for older browsers
      var ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      btn.textContent = 'Copied!';
      setTimeout(function(){ btn.textContent = 'Copy'; }, 1800);
    });
  }
  window.copyText = copyText;

  function copyCap(cid) {
    var el = document.getElementById(cid);
    if (!el || el.style.display === 'none') {
      alert('Open a caption variant first (Short / Med / Long / XL), then click Copy.');
      return;
    }
    // Get plain text content (strip the first_comment div)
    var scriptEl = document.getElementById('caps-' + cid);
    var variant  = el.getAttribute('data-open');
    var caps     = scriptEl ? JSON.parse(scriptEl.textContent || '{}') : {};
    var text     = caps[variant] || el.innerText || '';
    var btn      = el.parentElement.querySelector('button[onclick*="copyCap"]');
    copyText(text, btn || { textContent: '', style: {} });
  }
  window.copyCap = copyCap;

  // ── Gallery state ─────────────────────────────────────────────────────────
  var _galView   = 'grid';   // 'grid' | 'review'
  var _skipped   = {};       // pid → true

  function _galBtn(id, label, active) {
    var bg = active ? '#1a3a5a' : '#1a2030';
    var co = active ? '#60a5fa' : '#8b93a3';
    var bo = active ? '#2a5a8a' : '#2a3555';
    return '<button type="button" onclick="setGalView(\'' + id + '\')" '
         + 'style="font-size:11px;padding:3px 10px;background:' + bg + ';border:1px solid ' + bo + ';color:' + co + ';cursor:pointer;border-radius:3px">'
         + label + '</button>';
  }

  function setGalView(v) {
    _galView = v;
    var viewer = document.getElementById('output-viewer');
    if (!viewer || !viewer._data) return;
    viewer.innerHTML = buildViewer(viewer._data);
  }

  function skipCard(pid) {
    _skipped[pid] = !_skipped[pid];
    var card = document.getElementById('galcard-' + pid);
    if (!card) return;
    card.style.opacity = _skipped[pid] ? '0.35' : '1';
    var btn = document.getElementById('skipbtn-' + pid);
    if (btn) { btn.textContent = _skipped[pid] ? '↩ Restore' : '✕ Skip'; btn.style.color = _skipped[pid] ? '#4ade80' : '#f87171'; }
    _updateGalHeader();
  }

  function _updateGalHeader() {
    var el = document.getElementById('gal-approved-count');
    if (!el || !el._total) return;
    var skippedCount = Object.values(_skipped).filter(Boolean).length;
    el.textContent = (el._total - skippedCount) + ' approved · ' + skippedCount + ' skipped';
  }

  function copyPackage(pid, caps, fc) {
    var btn = document.getElementById('pkgbtn-' + pid);
    // find active caption variant
    var capEl = document.getElementById('cap-' + pid);
    var variant = capEl ? (capEl.dataset.variant || 'short') : 'short';
    var capText = caps[variant] || caps['short'] || '';
    var pkg = capText + (fc ? '\n\n——\nFirst comment: ' + fc : '');
    copyText(pkg, btn || {textContent:'',style:{}});
  }

  function buildViewer(data) {
    var posts  = data.post || data.posts || [];
    var genMap = {};
    (data.generated || []).forEach(function(g) {
      var parts = (g.file || '').replace(/\\\\/g,'/').split('/');
      genMap[g.idx] = parts[parts.length - 1];
    });

    var imgPosts  = posts.filter(function(p){ return !!(p.image_url); });
    var tobiPosts = posts.filter(function(p){ return !(p.image_url); });
    var totalImg  = imgPosts.length;

    // ── Header bar ──────────────────────────────────────────────────────────
    var html = '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:14px">';
    html += '<div>';
    html += '<span id="gal-approved-count" style="font-size:12px;font-weight:600;color:#4ade80">' + totalImg + ' approved · 0 skipped</span>';
    html += '<span style="color:#8b93a3;font-size:11px;margin-left:10px">' + tobiPosts.length + ' TOBI</span>';
    html += '</div>';
    html += '<div style="display:flex;gap:5px">'
          + _galBtn('grid',   '⊞ Grid',   _galView === 'grid')
          + _galBtn('review', '☰ Review', _galView === 'review')
          + '</div>';
    html += '</div>';

    // patch _total for the counter
    html += '<script>setTimeout(function(){var e=document.getElementById("gal-approved-count");if(e)e._total=' + totalImg + ';},0);<\/script>';

    // ── Image cards ─────────────────────────────────────────────────────────
    var colStyle = _galView === 'grid'
      ? 'display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px;margin-bottom:20px'
      : 'display:flex;flex-direction:column;gap:20px;margin-bottom:20px';

    html += '<div style="' + colStyle + '">';

    posts.forEach(function(p, i) {
      var pid   = p.id || (i + 1);
      var isImg = !!(p.image_url);
      var fname = genMap[pid] || '';
      var caps  = p.captions || {};
      var fc    = p.first_comment || '';
      var cid   = 'cap-' + pid;
      var tag   = p._tag || '';
      var text  = p.text || '';
      var imgSrc = fname ? '/pipeline-queue/output-image/' + encodeURIComponent(fname) : '';

      if (!isImg) {
        // ── TOBI card (same in both views) ──
        html += '<div id="galcard-' + pid + '" style="background:#11151f;border:1px solid #2a3555;border-radius:6px;padding:16px;display:flex;flex-direction:column;gap:10px">';
        html += '<div style="display:flex;align-items:center;justify-content:space-between">';
        html += '<div style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:1px">TOBI &middot; Text Only</div>';
        html += '<button onclick="copyText(' + JSON.stringify(text) + ',this)" style="font-size:10px;padding:2px 8px;background:#1a2030;border:1px solid #2a3555;color:#8b93a3;cursor:pointer;border-radius:3px">Copy</button>';
        html += '</div>';
        html += '<div style="color:#c0c8d8;font-size:13px;line-height:1.7;white-space:pre-wrap">' + esc(text) + '</div>';
        if (fc) {
          html += '<div style="padding-top:8px;border-top:1px solid #2a3555">';
          html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">';
          html += '<span style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:1px">First Comment</span>';
          html += '<button onclick="copyText(' + JSON.stringify(fc) + ',this)" style="font-size:10px;padding:2px 8px;background:#1a2030;border:1px solid #2a3555;color:#8b93a3;cursor:pointer;border-radius:3px">Copy</button>';
          html += '</div>';
          html += '<div style="color:#c0c8d8;font-size:11px">' + esc(fc) + '</div>';
          html += '</div>';
        }
        html += '</div>';
        return;
      }

      // ── Image card ──
      if (_galView === 'grid') {
        // Compact grid card
        html += '<div id="galcard-' + pid + '" style="background:#11151f;border:1px solid #2a3555;border-radius:6px;overflow:hidden;transition:opacity .2s">';
        if (imgSrc) {
          html += '<a href="' + imgSrc + '" target="_blank">';
          html += '<img src="' + imgSrc + '" style="width:100%;display:block;cursor:pointer">';
          html += '</a>';
        } else {
          html += '<div style="background:#1a2030;height:160px;display:flex;align-items:center;justify-content:center;color:#3a4055;font-size:11px">No image</div>';
        }
        html += '<div style="padding:10px">';
        if (tag) html += '<div style="color:#D02020;font-size:10px;font-weight:700;letter-spacing:1px;margin-bottom:3px">' + esc(tag) + '</div>';
        html += '<div style="color:#FFDE59;font-size:11px;font-weight:700;line-height:1.3;margin-bottom:8px">' + esc(text.substring(0,80)) + '</div>';
        // Caption tabs
        html += '<div style="display:flex;gap:3px;flex-wrap:wrap;align-items:center;margin-bottom:6px">';
        [['short','S'],['medium','M'],['long','L'],['extra_long','XL']].forEach(function(v) {
          html += '<button onclick="showCap(\'' + cid + '\',\'' + v[0] + '\')" style="font-size:10px;padding:1px 6px;background:#1a2030;border:1px solid #2a3555;color:#8b93a3;cursor:pointer;border-radius:3px">' + v[1] + '</button>';
        });
        html += '<button id="pkgbtn-' + pid + '" onclick="copyPackage(' + pid + ',' + JSON.stringify(caps) + ',' + JSON.stringify(fc) + ')" style="font-size:10px;padding:1px 6px;background:#0a1a0a;border:1px solid #1a4a1a;color:#4ade80;cursor:pointer;border-radius:3px;margin-left:2px">&#128203;</button>';
        html += '</div>';
        html += '<div id="' + cid + '" style="display:none;font-size:10px;color:#c0c8d8;line-height:1.6;max-height:100px;overflow-y:auto;background:#060910;padding:6px;border-radius:3px;margin-bottom:6px" data-fc="' + esc(fc) + '" data-variant="short"></div>';
        html += '<script type="application/json" id="caps-' + cid + '">' + JSON.stringify(caps) + '<\/script>';
        // Skip button
        html += '<button id="skipbtn-' + pid + '" onclick="skipCard(' + pid + ')" type="button" style="font-size:10px;padding:1px 7px;background:#1a0a0a;border:1px solid #5a1a1a;color:#f87171;cursor:pointer;border-radius:3px;width:100%">&#10005; Skip</button>';
        html += '</div></div>';

      } else {
        // ── Review mode: wide card with large image left, details right ──
        html += '<div id="galcard-' + pid + '" style="background:#11151f;border:1px solid #2a3555;border-radius:6px;overflow:hidden;display:flex;gap:0;transition:opacity .2s">';
        // Image column
        html += '<div style="flex:0 0 280px;max-width:280px">';
        if (imgSrc) {
          html += '<a href="' + imgSrc + '" target="_blank"><img src="' + imgSrc + '" style="width:100%;display:block;cursor:pointer"></a>';
        } else {
          html += '<div style="background:#1a2030;height:100%;min-height:200px;display:flex;align-items:center;justify-content:center;color:#3a4055;font-size:11px">No image</div>';
        }
        html += '</div>';
        // Details column
        html += '<div style="flex:1;padding:16px;display:flex;flex-direction:column;gap:10px;min-width:0">';
        // Header row
        html += '<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px">';
        html += '<div>';
        if (tag) html += '<div style="color:#D02020;font-size:10px;font-weight:700;letter-spacing:1px;margin-bottom:4px">' + esc(tag) + '</div>';
        html += '<div style="color:#FFDE59;font-size:13px;font-weight:700;line-height:1.4">' + esc(text) + '</div>';
        html += '</div>';
        // Skip button top-right
        html += '<button id="skipbtn-' + pid + '" onclick="skipCard(' + pid + ')" type="button" style="flex-shrink:0;font-size:10px;padding:3px 10px;background:#1a0a0a;border:1px solid #5a1a1a;color:#f87171;cursor:pointer;border-radius:3px">&#10005; Skip</button>';
        html += '</div>';
        // Caption tabs
        html += '<div>';
        html += '<div style="display:flex;gap:4px;flex-wrap:wrap;align-items:center;margin-bottom:8px">';
        [['short','Short'],['medium','Med'],['long','Long'],['extra_long','XL']].forEach(function(v) {
          html += '<button onclick="showCap(\'' + cid + '\',\'' + v[0] + '\')" style="font-size:10px;padding:2px 8px;background:#1a2030;border:1px solid #2a3555;color:#8b93a3;cursor:pointer;border-radius:3px">' + v[1] + '</button>';
        });
        html += '<button id="pkgbtn-' + pid + '" onclick="copyPackage(' + pid + ',' + JSON.stringify(caps) + ',' + JSON.stringify(fc) + ')" style="font-size:10px;padding:2px 10px;background:#0a1a0a;border:1px solid #1a4a1a;color:#4ade80;cursor:pointer;border-radius:3px;margin-left:4px">&#128203; Copy caption</button>';
        html += '</div>';
        html += '<div id="' + cid + '" style="display:none;font-size:12px;color:#c0c8d8;line-height:1.7;background:#060910;padding:10px;border-radius:4px;max-height:200px;overflow-y:auto" data-fc="' + esc(fc) + '" data-variant="short"></div>';
        html += '<script type="application/json" id="caps-' + cid + '">' + JSON.stringify(caps) + '<\/script>';
        html += '</div>';
        // First comment row
        if (fc) {
          html += '<div style="padding-top:8px;border-top:1px solid #1a2340">';
          html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">';
          html += '<span style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:1px">First Comment</span>';
          html += '<button onclick="copyText(' + JSON.stringify(fc) + ',this)" style="font-size:10px;padding:2px 8px;background:#1a2030;border:1px solid #2a3555;color:#8b93a3;cursor:pointer;border-radius:3px">Copy</button>';
          html += '</div>';
          html += '<div style="color:#c0c8d8;font-size:11px;line-height:1.6">' + esc(fc) + '</div>';
          html += '</div>';
        }
        html += '</div></div>';
      }
    });

    html += '</div>';
    return html;
  }

  function loadOutput() {
    if (_outputLoaded) return;
    _outputLoaded = true;
    var viewer = document.getElementById('output-viewer');
    if (!viewer) { console.error('[output-viewer] element not found'); return; }
    viewer.innerHTML = '<div style="color:#8b93a3;font-size:12px">Loading output...</div>';
    fetch('/pipeline-queue/output-json')
      .then(function(r){
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function(data) {
        console.log('[output-viewer] posts:', (data.post||data.posts||[]).length, 'generated:', (data.generated||[]).length);
        try {
          viewer._data = data;
          viewer.innerHTML = buildViewer(data);
        } catch(err) {
          console.error('[output-viewer] buildViewer error:', err);
          viewer.innerHTML = '<div style="color:#f87171;font-size:12px">Render error: ' + esc(String(err)) + '</div>';
        }
      })
      .catch(function(e) {
        console.error('[output-viewer] fetch error:', e);
        viewer.innerHTML = '<div style="color:#f87171;font-size:12px">Could not load output: ' + esc(String(e)) + '</div>';
      });
  }

  function showPanel(id) {
    ['gen-idle','gen-running','gen-done','gen-error','gen-no-content'].forEach(function(s) {
      document.getElementById(s).style.display = s === id ? 'block' : 'none';
    });
  }

  function poll() {
    fetch('/pipeline-queue/batch-status')
      .then(function(r){ return r.json(); })
      .then(function(d) {
        var job = d.job || {};
        var st  = job.status || 'idle';

        if (st === 'running') {
          showPanel('gen-running');
          var total = job.total || 1;
          var nImg  = job.n_images || job.total || 1;
          var nTobi = job.n_tobi || 0;
          var done  = (job.completed || 0) + nTobi;
          document.getElementById('gen-bar').style.width = Math.min(100, Math.round(done / total * 100)) + '%';
          document.getElementById('gen-count').textContent =
            (job.completed || 0) + ' of ' + nImg + ' image(s) done  ·  ' + nTobi + ' TOBI(s)';
          // Elapsed + ETA
          var timerEl = document.getElementById('gen-timer');
          if (job.started_at) {
            var startMs = new Date(job.started_at).getTime();
            var elapsedSec = Math.max(0, Math.floor((Date.now() - startMs) / 1000));
            var mm = Math.floor(elapsedSec / 60);
            var ss = String(elapsedSec % 60).padStart(2, '0');
            var elapsedStr = mm + ':' + ss + ' elapsed';
            var etaStr = '';
            var imgDone = job.completed || 0;
            if (imgDone > 0) {
              var secPerImg = elapsedSec / imgDone;
              var imgLeft   = nImg - imgDone;
              var etaSec    = Math.round(secPerImg * imgLeft);
              if (etaSec > 0) {
                var em = Math.floor(etaSec / 60);
                var es = String(etaSec % 60).padStart(2, '0');
                etaStr = '  ·  ~' + em + ':' + es + ' remaining';
              }
            } else if (nImg > 0) {
              var etaSec2 = Math.round(90 * nImg - elapsedSec);
              if (etaSec2 > 0) {
                var em2 = Math.floor(etaSec2 / 60);
                var es2 = String(etaSec2 % 60).padStart(2, '0');
                etaStr = '  ·  ~' + em2 + ':' + es2 + ' remaining';
              }
            }
            timerEl.innerText = '⏱ ' + elapsedStr + etaStr;
          }
          var logEl = document.getElementById('gen-log');
          var lines = (job.log || []).slice(-20).join('\\n');
          if (logEl.textContent !== lines) { logEl.textContent = lines; logEl.scrollTop = logEl.scrollHeight; }
          setTimeout(poll, 3000);

        } else if (st === 'done') {
          showPanel('gen-done');
          var bd = (job.batch_dir || '').replace(/\\\\/g, '/').split('/').pop();
          document.getElementById('gen-summary').textContent =
            (job.completed || 0) + ' image card(s) + ' + (job.n_tobi || 0) + ' TOBI(s)  ·  output/' + bd;
          loadOutput();

        } else if (st === 'error') {
          showPanel('gen-error');
          document.getElementById('gen-err-msg').textContent = (job.log || []).slice(-8).join('\\n');

        } else {
          _outputLoaded = false;
          if (d.picks_ready) {
            showPanel('gen-idle');
            document.getElementById('picks-info').textContent =
              d.picks_count + ' post(s) drafted  ·  batch date ' + (d.picks_date || '');
          } else {
            showPanel('gen-no-content');
          }
          setTimeout(poll, 8000);
        }
      })
      .catch(function() { setTimeout(poll, 10000); });
  }

  // If server already rendered the done panel, load output immediately
  if (document.getElementById('gen-done').style.display !== 'none') {
    loadOutput();
  }

  poll();
})();
</script>"""

    manual_add_panel = """
<details style="margin-bottom:20px;border:1px solid #2a3555;border-radius:6px;background:#0d111a">
  <summary style="padding:12px 16px;cursor:pointer;font-size:13px;font-weight:600;color:#c0c8d8;list-style:none;display:flex;align-items:center;gap:8px;user-select:none">
    <span style="color:#3b82f6;font-size:16px">&#43;</span> Add Article Manually
    <span style="color:#8b93a3;font-size:11px;font-weight:400;margin-left:4px">&mdash; for articles you found outside the scanner</span>
  </summary>
  <div style="padding:0 16px 16px 16px;border-top:1px solid #1a1f2b;margin-top:0">

    <div style="margin-top:14px;padding:10px 14px;background:#0a1628;border:1px solid #1e3a8a;border-radius:6px;font-size:12px;line-height:1.7;color:#93c5fd">
      <b style="color:#c0c8d8">How it works:</b><br>
      1. Paste the article URL and/or text below and click <b>Add to Queue</b> &mdash; it lands in Pending.<br>
      2. <b>Paste the same article text in your Claude Code chat.</b> Claude drafts the headline, tag, 4 captions, and first comment in First Signal News voice and updates the queue entry automatically.<br>
      3. Come back here, click the <b>&#9998; Draft</b> button on the entry to review, then send to generation.
    </div>

    <form method="post" action="/pipeline-queue/add-article" id="manual-add-form">
      <div style="margin-top:14px">
        <label style="display:block;font-size:11px;color:#8b93a3;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px">Article URL <span style="color:#4a5568;font-size:10px">(optional)</span></label>
        <input type="url" name="article_url" placeholder="https://..."
          style="width:100%;box-sizing:border-box;background:#11151f;color:#e6e8ec;border:1px solid #2a3040;border-radius:4px;padding:7px 10px;font-size:13px">
      </div>
      <div style="margin-top:12px">
        <label style="display:block;font-size:11px;color:#8b93a3;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px">Article Text <span style="color:#4a5568;font-size:10px">(paste headline + body &mdash; more text = better draft)</span></label>
        <textarea name="article_text" rows="5" placeholder="Paste article text here. At minimum the headline."
          style="width:100%;box-sizing:border-box;background:#11151f;color:#e6e8ec;border:1px solid #2a3040;border-radius:4px;padding:7px 10px;font-size:13px;font-family:inherit;resize:vertical"></textarea>
      </div>
      <div style="margin-top:10px;display:flex;align-items:center;gap:10px">
        <button type="submit" class="primary"
          style="padding:7px 16px;font-size:13px">&#43; Add to Queue</button>
        <span style="font-size:11px;color:#8b93a3">Then paste the article in Claude Code chat to generate the FSN draft.</span>
      </div>
    </form>
  </div>
</details>"""

    body = f"""
  <div class="nav" style="margin-bottom:12px">
    <a href="/pipeline-queue" style="color:#e6e8ec;font-weight:600">&#9654; Production Queue</a>
    <a href="/fb-scanner">&#128269; FB Scanner</a>
  </div>
  <h1>&#9654; First Signal Production Queue</h1>
  <p class="sub">Stories sent from the News Desk via "Send to First Signal Pipeline". Select and assign type, then send to generation. Page refreshes every 30 seconds.</p>
  {flash}
  <!-- gen_panel hidden: bulk generation replaced by per-workspace Generate Image -->
  {manual_add_panel}
  {pending_section}
  {approved_section}
  {history_section}
"""
    # Refresh every 15s when images are generating, 30s otherwise
    any_generating = any(x.get("image_gen_status") == "generating" for x in items)
    refresh_secs = 15 if any_generating else 30
    head = _page_head(extra_meta=f'<meta http-equiv="refresh" content="{refresh_secs}">')
    return head + body + PAGE_TAIL


# ── Story Workspace Page ───────────────────────────────────────────────────────

def _render_img_history(history: list, cid: str) -> str:
    if not history:
        return ""
    items_html = ""
    for i, kie_url in enumerate(reversed(history), 1):
        items_html += (
            f'<div style="display:flex;flex-direction:column;align-items:center;gap:4px">'
            f'<img src="{escape(kie_url)}" style="width:80px;height:100px;object-fit:cover;border-radius:4px;border:1px solid #2a3555;cursor:pointer" '
            f'onclick="useHistoryImage(\'{cid}\',\'{escape(kie_url)}\')" title="Click to use this version">'
            f'<div style="display:flex;gap:4px">'
            f'<button type="button" onclick="useHistoryImage(\'{cid}\',\'{escape(kie_url)}\')" '
            f'style="font-size:9px;padding:2px 6px;background:#1e3a8a;border:1px solid #2563eb;color:#fff;cursor:pointer;border-radius:3px">Use</button>'
            f'<a href="{escape(kie_url)}" download target="_blank" '
            f'style="font-size:9px;padding:2px 6px;background:#0a1020;border:1px solid #2a3555;color:#8b93a3;border-radius:3px;text-decoration:none">&#11015;</a>'
            f'</div>'
            f'<span style="font-size:9px;color:#8b93a3">v{i}</span>'
            f'</div>'
        )
    return (
        f'<div style="margin-top:10px">'
        f'<div style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Previous versions</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:8px">{items_html}</div>'
        f'</div>'
    )


def render_story_workspace_page(item: dict, flash: str = "") -> str:
    """Full dedicated workspace for a single production queue story."""
    cid       = str(item.get("cluster_id", ""))
    text      = item.get("text") or ""
    category  = item.get("category") or ""
    sources   = item.get("sources") or []
    draft     = item.get("draft") or {}
    caps      = draft.get("captions") or {}
    hl        = draft.get("headline") or ""
    tag       = draft.get("tag") or ""
    scene     = draft.get("scene") or item.get("suggested_scene") or ""
    fc        = draft.get("first_comment") or ""
    post_type = item.get("post_type") or "image_card"
    img_url      = item.get("generated_image_url") or ""
    img_status   = item.get("image_gen_status") or ""
    img_history  = item.get("image_history") or []
    tobi_text = item.get("tobi_text") or ""
    status    = item.get("queue_status") or "pending"
    viral     = float(item.get("viral_score") or 0)
    momentum  = float(item.get("momentum_score") or 0)

    age_days  = _item_age_days(item)
    age_label = (f"{int(age_days)}d old" if age_days >= 1 else f"{int(age_days*24)}h old")

    flash_html = f'<div class="flash">{escape(flash)}</div>' if flash else ""

    # Source list
    src_rows = "".join(
        f'<div style="padding:4px 0;border-bottom:1px solid #1a1f2b;font-size:12px">'
        f'<span style="color:#facc15">{escape(s.get("source_name","") or "")}</span>'
        f' &mdash; <a href="{escape(s.get("url","") or "")}" target="_blank" rel="noopener" style="color:#8b93a3">'
        f'{escape((s.get("headline","") or "")[:120])}</a></div>'
        for s in sources[:5]
    ) or '<div style="color:#8b93a3;font-size:12px">No sources</div>'

    def cap_block(label, key, rows=4):
        val = escape(caps.get(key) or "")
        return (
            f'<div style="margin-bottom:14px">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">'
            f'<label style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:.5px">{label}</label>'
            f'<div style="display:flex;gap:6px">'
            f'<button type="button" onclick="regenCap(\'{cid}\',\'{key}\')" '
            f'style="font-size:10px;padding:2px 8px;background:#0a1020;border:1px solid #2a3555;color:#facc15;cursor:pointer;border-radius:3px">&#8635; Rewrite</button>'
            f'<button type="button" onclick="copyField(\'cap-{key}-{cid}\')" '
            f'style="font-size:10px;padding:2px 8px;background:#0a1020;border:1px solid #2a3555;color:#8b93a3;cursor:pointer;border-radius:3px">&#10064; Copy</button>'
            f'</div></div>'
            f'<textarea id="cap-{key}-{cid}" rows="{rows}" '
            f'style="width:100%;box-sizing:border-box;background:#0d111a;border:1px solid #2a3555;'
            f'color:#e6e8ec;font-size:12px;border-radius:4px;padding:8px;font-family:inherit;resize:vertical">{val}</textarea>'
            f'</div>'
        )

    if img_url:
        img_html = (
            f'<img src="{escape(img_url)}" style="max-width:280px;width:100%;border-radius:6px;display:block;margin-bottom:6px">'
            f'<a href="{escape(img_url)}" download target="_blank" '
            f'style="display:inline-block;font-size:11px;padding:4px 12px;background:#0a1020;border:1px solid #2a3555;color:#8b93a3;border-radius:4px;text-decoration:none;margin-bottom:10px">&#11015; Download</a>'
        )
        regen_label = "&#8635; Regenerate Image"
    elif img_status == "generating":
        img_html = '<div style="width:200px;height:250px;background:#0d111a;border:1px solid #2a3555;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#8b93a3;font-size:12px;margin-bottom:10px">Generating...</div>'
        regen_label = "&#8635; Regenerate"
    else:
        img_html = '<div style="width:200px;height:250px;background:#0d111a;border:1px solid #2a3555;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#8b93a3;font-size:12px;margin-bottom:10px">No image yet</div>'
        regen_label = "&#9654; Generate Image"

    tobi_block = ""
    if post_type == "tobi" or tobi_text:
        tobi_block = (
            f'<div style="background:#0d111a;border:1px solid #2a3555;border-radius:6px;padding:14px;margin-bottom:16px">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">'
            f'<span style="color:#4ade80;font-size:12px;font-weight:600">&#128196; TOBI Text Post</span>'
            f'<button type="button" onclick="regenTOBI(\'{cid}\')" style="font-size:10px;padding:2px 8px;background:#0a1020;border:1px solid #2a3555;color:#facc15;cursor:pointer;border-radius:3px">&#8635; New Options</button>'
            f'</div>'
            f'<textarea id="tobi-text-{cid}" rows="3" '
            f'style="width:100%;box-sizing:border-box;background:#060910;border:1px solid #2a3555;color:#e6e8ec;font-size:13px;border-radius:4px;padding:8px;font-family:inherit;resize:vertical">{escape(tobi_text)}</textarea>'
            f'<div id="tobi-options-{cid}" style="margin-top:8px"></div>'
            f'</div>'
        )

    status_bg   = {"pending": "#3a3a00", "approved": "#0a2800", "skipped": "#1a1a1a"}.get(status, "#1a1f2b")
    status_fg   = {"pending": "#facc15", "approved": "#4ade80", "skipped": "#8b93a3"}.get(status, "#e6e8ec")
    status_badge = f'<span style="background:{status_bg};color:{status_fg};padding:2px 8px;border-radius:3px;font-size:11px;font-weight:600">{status.upper()}</span>'

    type_img  = "selected" if post_type == "image_card"    else ""
    type_tobi = "selected" if post_type == "tobi"          else ""
    type_vid  = "selected" if post_type == "video_package" else ""

    body = f"""
<div style="max-width:1200px;margin:0 auto">
<a class="back" href="/pipeline-queue">&larr; Back to Queue</a>
{flash_html}

<div style="margin:16px 0 20px 0;display:flex;align-items:flex-start;gap:12px;flex-wrap:wrap">
  <div style="flex:1;min-width:240px">
    <h1 style="margin:0 0 6px 0;font-size:16px">{escape(text[:200])}</h1>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      {status_badge}
      <span style="color:#8b93a3;font-size:12px">{escape(category)}</span>
      <span style="color:#8b93a3;font-size:12px">{age_label}</span>
      <span style="color:#facc15;font-size:12px">&#9733; {viral:.0f} viral</span>
      <span style="color:#60a5fa;font-size:12px">&#8679; {momentum:.0f} momentum</span>
    </div>
  </div>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding-top:4px">
    <form method="post" action="/pipeline-queue/story/{cid}/approve" style="margin:0">
      <button type="submit" class="primary" style="padding:7px 18px;font-size:13px">&#10003; Approve</button>
    </form>
    <form method="post" action="/pipeline-queue/story/{cid}/skip" style="margin:0">
      <button type="submit" style="padding:7px 14px;font-size:13px">Skip</button>
    </form>
    <form method="post" action="/pipeline-queue/story/{cid}/remove" style="margin:0">
      <button type="submit" style="background:#3a1414;border-color:#7a2020;padding:7px 14px;font-size:13px">&#10005; Remove</button>
    </form>
  </div>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">

  <!-- LEFT -->
  <div>

    <div style="background:#0d111a;border:1px solid #1a1f2b;border-radius:6px;padding:14px;margin-bottom:16px">
      <div style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">Source Stories</div>
      {src_rows}
    </div>

    <div style="background:#0d111a;border:1px solid #1a1f2b;border-radius:6px;padding:14px;margin-bottom:16px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
        <span style="color:#c7cbd4;font-size:13px;font-weight:600">Story Angles</span>
        <button type="button" id="angles-btn-{cid}" onclick="getAngles('{cid}')"
          style="font-size:11px;padding:4px 12px;background:#1e3a8a;border:1px solid #2563eb;color:#fff;cursor:pointer;border-radius:4px">
          &#128269; Get Angles</button>
      </div>
      <div id="angles-{cid}">
        <div style="color:#8b93a3;font-size:12px">Click "Get Angles" to generate 3 content angles for this story.</div>
      </div>
    </div>

    <div style="background:#0d111a;border:1px solid #1a1f2b;border-radius:6px;padding:14px;margin-bottom:16px">
      <div style="color:#c7cbd4;font-size:13px;font-weight:600;margin-bottom:10px">Draft</div>
      <div style="margin-bottom:10px">
        <label style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:.5px;display:block;margin-bottom:3px">Headline (yellow image text)</label>
        <input type="text" id="draft-hl-{cid}" value="{escape(hl)}" maxlength="120"
          style="width:100%;box-sizing:border-box;color:#FFDE59;font-size:14px;font-weight:600;padding:8px">
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">
        <div>
          <label style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:.5px;display:block;margin-bottom:3px">3-Word Tag (red pill)</label>
          <input type="text" id="draft-tag-{cid}" value="{escape(tag)}" maxlength="40"
            style="width:100%;box-sizing:border-box;color:#f87171;font-size:13px;font-weight:600;padding:8px">
        </div>
        <div>
          <label style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:.5px;display:block;margin-bottom:3px">Post Type</label>
          <select id="draft-type-{cid}" onchange="onTypeChange('{cid}',this)" style="width:100%;padding:8px">
            <option value="image_card" {type_img}>Image Card</option>
            <option value="tobi" {type_tobi}>TOBI (Text Post)</option>
            <option value="video_package" {type_vid}>Video Package</option>
          </select>
        </div>
      </div>
      <div style="margin-bottom:12px">
        <label style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:.5px;display:block;margin-bottom:3px">Image Scene</label>
        <textarea id="draft-scene-{cid}" rows="2"
          style="width:100%;box-sizing:border-box;background:#11151f;border:1px solid #2a3555;color:#e6e8ec;font-size:12px;border-radius:4px;padding:8px;font-family:inherit;resize:vertical">{escape(scene)}</textarea>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:14px">
        <button type="button" onclick="saveDraft('{cid}')"
          style="padding:6px 14px;background:#1a3a8a;border:1px solid #2563eb;color:#fff;cursor:pointer;border-radius:4px;font-size:12px">
          &#10003; Save Draft</button>
        <span id="draft-save-status-{cid}" style="font-size:11px;color:#4ade80;align-self:center"></span>
      </div>

      <div style="border-top:1px solid #2a3555;padding-top:12px">
        <div style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">Generate Full Content</div>
        <div style="display:flex;gap:8px;margin-bottom:6px;flex-wrap:wrap">
          <button type="button" onclick="genContent('{cid}','news')"
            style="padding:6px 14px;background:#0d1a2a;border:1px solid #1e3a8a;color:#93c5fd;cursor:pointer;border-radius:4px;font-size:12px">
            &#128240; News Style</button>
          <button type="button" onclick="genContent('{cid}','america_first')"
            style="padding:6px 14px;background:#1a0a00;border:1px solid #7a3010;color:#fb923c;cursor:pointer;border-radius:4px;font-size:12px">
            &#127777; America First</button>
          <span id="content-gen-status-{cid}" style="font-size:11px;color:#8b93a3;align-self:center"></span>
        </div>
        <div style="color:#3a4055;font-size:10px">News Style = straight who/what/when/where. America First = pointed, accountability, pro-Trump framing.</div>
      </div>
    </div>

    {tobi_block}
  </div>

  <!-- RIGHT -->
  <div>
    <div style="background:#0d111a;border:1px solid #1a1f2b;border-radius:6px;padding:14px;margin-bottom:16px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
        <span style="color:#c7cbd4;font-size:13px;font-weight:600">Image</span>
        <button type="button" onclick="regenImage('{cid}')"
          style="font-size:11px;padding:4px 12px;background:#1a0a00;border:1px solid #7a3010;color:#fb923c;cursor:pointer;border-radius:4px">
          {regen_label}</button>
      </div>
      <div id="img-wrap-{cid}">{img_html}</div>
      <div id="img-status-{cid}" style="font-size:11px;color:#8b93a3;margin-top:4px">{"Generating... refresh in ~60s" if img_status=="generating" else ""}</div>
      <div id="img-history-{cid}">{_render_img_history(img_history, cid)}</div>
    </div>

    <div style="background:#0d111a;border:1px solid #1a1f2b;border-radius:6px;padding:14px;margin-bottom:16px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
        <span style="color:#c7cbd4;font-size:13px;font-weight:600">Captions</span>
        <button type="button" onclick="regenAllCaps('{cid}')"
          style="font-size:10px;padding:3px 10px;background:#0a1020;border:1px solid #2a3555;color:#facc15;cursor:pointer;border-radius:3px">
          &#8635; Rewrite All</button>
      </div>
      {cap_block("Short (30-50 words)", "short", 3)}
      {cap_block("Medium (80-120 words)", "medium", 5)}
      {cap_block("Long (250-350 words)", "long", 8)}
      {cap_block("Extra Long (450-600 words)", "extra_long", 12)}
      <div style="margin-top:10px;padding-top:10px;border-top:1px solid #2a3555">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
          <label style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:.5px">First Comment</label>
          <button type="button" onclick="copyField('cap-first_comment-{cid}')"
            style="font-size:10px;padding:2px 8px;background:#0a1020;border:1px solid #2a3555;color:#8b93a3;cursor:pointer;border-radius:3px">&#10064; Copy</button>
        </div>
        <textarea id="cap-first_comment-{cid}" rows="2"
          style="width:100%;box-sizing:border-box;background:#060910;border:1px solid #2a3555;color:#e6e8ec;font-size:12px;border-radius:4px;padding:8px;font-family:inherit;resize:vertical">{escape(fc)}</textarea>
      </div>
    </div>
  </div>
</div>
</div>
<script>
function copyField(id) {{
  var el = document.getElementById(id);
  if (!el) return;
  var text = (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') ? el.value : el.innerText;
  if (!text) {{ alert('Nothing here yet.'); return; }}
  navigator.clipboard.writeText(text).then(function() {{
    var prev = el.style.borderColor;
    el.style.borderColor = '#4ade80';
    setTimeout(function(){{ el.style.borderColor = prev; }}, 700);
  }});
}}
function onTypeChange(cid, sel) {{
  fetch('/pipeline-queue/set-post-type', {{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:'cluster_id='+cid+'&post_type='+encodeURIComponent(sel.value)}});
}}
function saveDraft(cid) {{
  var hl    = (document.getElementById('draft-hl-'+cid)||{{}}).value || '';
  var tag   = (document.getElementById('draft-tag-'+cid)||{{}}).value || '';
  var scene = (document.getElementById('draft-scene-'+cid)||{{}}).value || '';
  var st    = document.getElementById('draft-save-status-'+cid);
  if (st) st.textContent = 'Saving...';
  fetch('/pipeline-queue/story/'+cid+'/save-draft',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},
    body:'headline='+encodeURIComponent(hl)+'&tag='+encodeURIComponent(tag)+'&scene='+encodeURIComponent(scene)
  }}).then(r=>r.json()).then(d=>{{
    if (st) {{ st.textContent = d.ok ? 'Saved!' : ('Error: '+(d.error||'?')); }}
    if (d.ok) setTimeout(function(){{ if(st) st.textContent=''; }},2000);
  }});
}}
var _ws_angles = {{}};
function getAngles(cid) {{
  var btn = document.getElementById('angles-btn-'+cid);
  var div = document.getElementById('angles-'+cid);
  if (btn) btn.textContent = 'Loading...';
  if (div) div.innerHTML = '<div style="color:#8b93a3;font-size:12px">Getting angles...</div>';
  fetch('/pipeline-queue/expand-angles',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:'cluster_id='+cid}})
  .then(function(r){{ if(!r.ok) return r.json().then(function(e){{throw new Error(e.error||r.status)}}); return r.json(); }})
  .then(function(d) {{
    if (btn) btn.innerHTML = '&#8635; Refresh Angles';
    if (d.error) {{ if(div) div.innerHTML='<div style="color:#f87171">Error: '+d.error+'</div>'; return; }}
    _ws_angles[cid] = d.angles || [];
    var typeC = {{accountability:'#f87171',outrage:'#fb923c',breaking:'#facc15',vindication:'#4ade80',poll:'#60a5fa',analysis:'#c084fc'}};
    function _esc(s){{ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }}
    var html = _ws_angles[cid].map(function(a,i){{
      return '<div style="background:#11151f;border:1px solid #2a3555;border-radius:5px;padding:10px;margin-bottom:8px">'
        +'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">'
        +'<span style="color:'+(typeC[a.angle_type]||'#8b93a3')+';font-size:10px;font-weight:700;text-transform:uppercase">'+_esc(a.angle_type)+'</span>'
        +'<button type="button" data-cid="'+_esc(cid)+'" data-idx="'+i+'" class="apply-angle-btn" style="font-size:10px;padding:2px 8px;background:#1e3a8a;border:1px solid #2563eb;color:#fff;cursor:pointer;border-radius:3px">Use This Angle</button>'
        +'</div>'
        +'<div style="color:#facc15;font-size:13px;font-weight:600;margin-bottom:4px">'+_esc(a.hook)+'</div>'
        +'<div style="color:#e6e8ec;font-size:12px;margin-bottom:4px">'+_esc(a.caption_lead)+'</div>'
        +'<div style="display:flex;gap:10px;font-size:11px;color:#8b93a3;flex-wrap:wrap">'
        +'<span>Tag: <b style="color:#f87171">'+_esc(a.tag)+'</b></span>'
        +'<span>Scene: '+_esc(a.image_scene)+'</span>'
        +'</div>'
        +'<div style="color:#8b93a3;font-size:11px;font-style:italic;margin-top:4px">'+_esc(a.why)+'</div>'
        +'</div>';
    }}).join('');
    if (div) div.innerHTML = html || '<div style="color:#f87171">No angles returned</div>';
  }}).catch(function(err) {{
    if (btn) btn.innerHTML = '&#9888; Error — retry';
    if (div) div.innerHTML = '<div style="color:#f87171">Error: '+err.message+'</div>';
  }});
}}
function applyAngle(cid, idx) {{
  var a = (_ws_angles[cid]||[])[idx];
  if (!a) return;
  var hlEl = document.getElementById('draft-hl-'+cid);
  var tagEl = document.getElementById('draft-tag-'+cid);
  var scEl  = document.getElementById('draft-scene-'+cid);
  if (hlEl) hlEl.value = a.hook;
  if (tagEl) tagEl.value = a.tag;
  if (scEl)  scEl.value = a.image_scene;
  saveDraft(cid);
  // Flash fields green then restore original backgrounds, and scroll to headline
  var origBg = ['', '', '#11151f'];
  [hlEl, tagEl, scEl].forEach(function(el, i) {{
    if (!el) return;
    el.style.transition = 'background 0.2s';
    el.style.background = '#14532d';
    setTimeout(function() {{
      el.style.transition = 'background 0.6s';
      el.style.background = origBg[i];
    }}, 1200);
  }});
  if (hlEl) hlEl.scrollIntoView({{behavior:'smooth', block:'center'}});
}}
function genContent(cid, voice) {{
  var st = document.getElementById('content-gen-status-'+cid);
  if (st) st.textContent = voice==='news' ? 'Writing News Style...' : 'Writing America First...';
  var hl    = (document.getElementById('draft-hl-'+cid)||{{}}).value||'';
  var tag   = (document.getElementById('draft-tag-'+cid)||{{}}).value||'';
  var scene = (document.getElementById('draft-scene-'+cid)||{{}}).value||'';
  fetch('/pipeline-queue/story/'+cid+'/generate-content',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},
    body:'voice='+voice+'&headline='+encodeURIComponent(hl)+'&tag='+encodeURIComponent(tag)+'&scene='+encodeURIComponent(scene)
  }}).then(r=>r.json()).then(function(d){{
    if (st) st.textContent = '';
    if (d.error) {{ if(st) st.textContent='Error: '+d.error; return; }}
    var keys = ['short','medium','long','extra_long'];
    keys.forEach(function(k){{ var el=document.getElementById('cap-'+k+'-'+cid); if(el&&d.captions&&d.captions[k]) el.value=d.captions[k]; }});
    var fcEl=document.getElementById('cap-first_comment-'+cid);
    if(fcEl&&d.first_comment) fcEl.value=d.first_comment;
    if(st){{ st.textContent=voice==='news'?'News Style loaded':'America First loaded'; setTimeout(function(){{st.textContent='';}},3000); }}
  }});
}}
function regenCap(cid, variant) {{
  var el = document.getElementById('cap-'+variant+'-'+cid);
  if (!el) return;
  var hl = (document.getElementById('draft-hl-'+cid)||{{}}).value||'';
  el.style.opacity='0.4';
  fetch('/pipeline-queue/rewrite-caption',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},
    body:'cluster_id='+cid+'&variant='+variant+'&headline='+encodeURIComponent(hl)
  }}).then(r=>r.json()).then(function(d){{ el.style.opacity='1'; if(d.text) el.value=d.text; }});
}}
function regenAllCaps(cid) {{
  var hl = (document.getElementById('draft-hl-'+cid)||{{}}).value||'';
  var st = document.getElementById('content-gen-status-'+cid);
  if(st) st.textContent='Rewriting all captions...';
  fetch('/pipeline-queue/generate-all-captions',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},
    body:'cluster_id='+cid+'&headline='+encodeURIComponent(hl)
  }}).then(r=>r.json()).then(function(d){{
    if(st) st.textContent='';
    if(d.error){{ if(st) st.textContent='Error: '+d.error; return; }}
    var keys=['short','medium','long','extra_long'];
    keys.forEach(function(k){{ var el=document.getElementById('cap-'+k+'-'+cid); if(el&&d.captions&&d.captions[k]) el.value=d.captions[k]; }});
    var fcEl=document.getElementById('cap-first_comment-'+cid);
    if(fcEl&&d.first_comment) fcEl.value=d.first_comment;
    if(st){{ st.textContent='Done!'; setTimeout(function(){{st.textContent='';}},2000); }}
  }});
}}
var _imgPollTimer = {{}};
function _startImagePoll(cid) {{
  if (_imgPollTimer[cid]) clearTimeout(_imgPollTimer[cid]);
  var st = document.getElementById('img-status-'+cid);
  var wrap = document.getElementById('img-wrap-'+cid);
  var secs = 90;
  function countdown() {{
    if (st && !document.getElementById('img-wrap-'+cid).querySelector('img')) {{
      st.textContent = 'Checking in ' + secs + 's…';
      secs = Math.max(0, secs - 5);
    }}
  }}
  var countTimer = setInterval(countdown, 5000);
  countdown();
  function poll() {{
    fetch('/pipeline-queue/story/'+cid+'/image-status')
      .then(function(r) {{ return r.json(); }})
      .then(function(d) {{
        if (d.url) {{
          clearInterval(countTimer);
          if (wrap) wrap.innerHTML = '<img src="'+d.url+'" style="max-width:280px;width:100%;border-radius:6px;display:block;margin-bottom:6px">'
            + '<a href="'+d.url+'" download target="_blank" style="display:inline-block;font-size:11px;padding:4px 12px;background:#0a1020;border:1px solid #2a3555;color:#8b93a3;border-radius:4px;text-decoration:none;margin-bottom:10px">&#11015; Download</a>';
          if (st) st.textContent = '';
          if (d.history && d.history.length) {{
            var histDiv = document.getElementById('img-history-'+cid);
            if (histDiv) {{
              var html = '<div style="margin-top:10px"><div style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Previous versions</div><div style="display:flex;flex-wrap:wrap;gap:8px">';
              var rev = d.history.slice().reverse();
              rev.forEach(function(u, i) {{
                html += '<div style="display:flex;flex-direction:column;align-items:center;gap:4px">'
                  +'<img src="'+u+'" style="width:80px;height:100px;object-fit:cover;border-radius:4px;border:1px solid #2a3555;cursor:pointer" onclick="useHistoryImage(\\''+cid+'\\',\\''+u+'\\')" title="Click to use this version">'
                  +'<div style="display:flex;gap:4px">'
                  +'<button type="button" onclick="useHistoryImage(\\''+cid+'\\',\\''+u+'\\')" style="font-size:9px;padding:2px 6px;background:#1e3a8a;border:1px solid #2563eb;color:#fff;cursor:pointer;border-radius:3px">Use</button>'
                  +'<a href="'+u+'" download target="_blank" style="font-size:9px;padding:2px 6px;background:#0a1020;border:1px solid #2a3555;color:#8b93a3;border-radius:3px;text-decoration:none">&#11015;</a>'
                  +'</div>'
                  +'<span style="font-size:9px;color:#8b93a3">v'+(i+1)+'</span>'
                  +'</div>';
              }});
              html += '</div></div>';
              histDiv.innerHTML = html;
            }}
          }}
        }} else if (d.status === 'generating' || d.status === '') {{
          _imgPollTimer[cid] = setTimeout(poll, 5000);
        }} else {{
          clearInterval(countTimer);
          if (st) st.textContent = '';
          if (wrap) wrap.innerHTML = '<div style="width:200px;height:250px;background:#0d111a;border:1px solid #7a1010;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#f87171;font-size:12px;padding:12px;text-align:center">'+d.status+'</div>';
        }}
      }})
      .catch(function() {{ _imgPollTimer[cid] = setTimeout(poll, 10000); }});
  }}
  _imgPollTimer[cid] = setTimeout(poll, 5000);
}}
function regenImage(cid) {{
  var hl    = (document.getElementById('draft-hl-'+cid)||{{}}).value||'';
  var tag   = (document.getElementById('draft-tag-'+cid)||{{}}).value||'';
  var scene = (document.getElementById('draft-scene-'+cid)||{{}}).value||'';
  var st    = document.getElementById('img-status-'+cid);
  var wrap  = document.getElementById('img-wrap-'+cid);
  function _showErr(msg) {{
    if (wrap) wrap.innerHTML = '<div style="width:200px;height:250px;background:#0d111a;border:1px solid #7a1010;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#f87171;font-size:12px;padding:12px;text-align:center">'+msg+'</div>';
    if (st) st.textContent = '';
  }}
  if (!hl && !scene && !tag) {{ _showErr('Enter a headline or scene first, or apply an angle.'); return; }}
  if (st) st.textContent = 'Queued...';
  if (wrap) wrap.innerHTML = '<div style="width:200px;height:250px;background:#0d111a;border:1px solid #2a3555;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#8b93a3;font-size:12px">Generating…</div>';
  fetch('/pipeline-queue/story/'+cid+'/regenerate-image',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},
    body:'headline='+encodeURIComponent(hl)+'&tag='+encodeURIComponent(tag)+'&scene='+encodeURIComponent(scene)
  }}).then(function(r){{
    if(!r.ok) return r.text().then(function(t){{ throw new Error('Server error '+r.status+': '+t.slice(0,200)); }});
    return r.json();
  }}).then(function(d){{
    if(d.error){{ _showErr('Error: '+d.error); return; }}
    _startImagePoll(cid);
  }}).catch(function(e){{ _showErr('Request failed: '+e.message); }});
}}
function useHistoryImage(cid, kieUrl) {{
  var wrap = document.getElementById('img-wrap-'+cid);
  var st   = document.getElementById('img-status-'+cid);
  if (st) st.textContent = 'Swapping...';
  fetch('/pipeline-queue/story/'+cid+'/set-image',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:'kie_url='+encodeURIComponent(kieUrl)}})
    .then(function(r){{ return r.json(); }})
    .then(function(d){{
      if (d.error){{ if(st) st.textContent='Error: '+d.error; return; }}
      if (wrap) wrap.innerHTML = '<img src="'+d.url+'?t='+Date.now()+'" style="max-width:280px;width:100%;border-radius:6px;display:block;margin-bottom:6px">'
        + '<a href="'+kieUrl+'" download target="_blank" style="display:inline-block;font-size:11px;padding:4px 12px;background:#0a1020;border:1px solid #2a3555;color:#8b93a3;border-radius:4px;text-decoration:none;margin-bottom:10px">&#11015; Download</a>';
      if (st) st.textContent = '';
      // Rebuild history thumbnails excluding the one just selected
      var histDiv = document.getElementById('img-history-'+cid);
      if (histDiv && d.history) {{
        if (!d.history.length) {{ histDiv.innerHTML = ''; return; }}
        var html = '<div style="margin-top:10px"><div style="color:#8b93a3;font-size:10px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Previous versions</div><div style="display:flex;flex-wrap:wrap;gap:8px">';
        d.history.slice().reverse().forEach(function(u, i) {{
          html += '<div style="display:flex;flex-direction:column;align-items:center;gap:4px">'
            +'<img src="'+u+'" style="width:80px;height:100px;object-fit:cover;border-radius:4px;border:1px solid #2a3555;cursor:pointer" onclick="useHistoryImage(\\''+cid+'\\',\\''+u+'\\')" title="Click to use">'
            +'<div style="display:flex;gap:4px">'
            +'<button type="button" onclick="useHistoryImage(\\''+cid+'\\',\\''+u+'\\')" style="font-size:9px;padding:2px 6px;background:#1e3a8a;border:1px solid #2563eb;color:#fff;cursor:pointer;border-radius:3px">Use</button>'
            +'<a href="'+u+'" download target="_blank" style="font-size:9px;padding:2px 6px;background:#0a1020;border:1px solid #2a3555;color:#8b93a3;border-radius:3px;text-decoration:none">&#11015;</a>'
            +'</div><span style="font-size:9px;color:#8b93a3">v'+(i+1)+'</span></div>';
        }});
        histDiv.innerHTML = html + '</div></div>';
      }}
    }});
}}
var _tobi_opts = {{}};
function regenTOBI(cid) {{
  var div = document.getElementById('tobi-options-'+cid);
  if(div) div.innerHTML='<div style="color:#8b93a3;font-size:12px">Writing options...</div>';
  fetch('/pipeline-queue/write-tobi',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:'cluster_id='+cid}})
  .then(r=>r.json()).then(function(d){{
    if(d.error){{ if(div) div.innerHTML='<div style="color:#f87171">'+d.error+'</div>'; return; }}
    _tobi_opts[cid] = d.options||[];
    var html = _tobi_opts[cid].map(function(t,i){{
      var tSafe = t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      return '<div style="background:#11151f;border:1px solid #2a3555;border-radius:4px;padding:8px;margin-bottom:6px;display:flex;align-items:flex-start;gap:8px">'
        +'<div style="flex:1;font-size:12px;color:#e6e8ec">'+tSafe+'</div>'
        +'<button type="button" data-cid="'+cid+'" data-idx="'+i+'" class="use-tobi-btn" style="font-size:10px;padding:2px 8px;background:#1e3a8a;border:1px solid #2563eb;color:#fff;cursor:pointer;border-radius:3px;white-space:nowrap">Use</button>'
        +'</div>';
    }}).join('');
    if(div) div.innerHTML = html||'No options returned';
  }});
}}
function useTOBIopt(cid, idx) {{
  var t = (_tobi_opts[cid]||[])[idx];
  if(!t) return;
  var el = document.getElementById('tobi-text-'+cid);
  if(el) el.value = t;
  fetch('/pipeline-queue/apply-tobi',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:'cluster_id='+cid+'&tobi_text='+encodeURIComponent(t)}});
}}
// Delegated handlers for dynamically-created buttons (avoids quote-escaping in onclick)
document.addEventListener('click', function(e) {{
  var btn = e.target.closest('.apply-angle-btn');
  if (btn) {{ applyAngle(btn.getAttribute('data-cid'), parseInt(btn.getAttribute('data-idx'))); return; }}
  var tbtn = e.target.closest('.use-tobi-btn');
  if (tbtn) {{ useTOBIopt(tbtn.getAttribute('data-cid'), parseInt(tbtn.getAttribute('data-idx'))); return; }}
}});
// Auto-start image polling on page load if image is still generating
(function() {{
  var wrap = document.getElementById('img-wrap-{cid}');
  if (wrap && !wrap.querySelector('img')) {{ _startImagePoll('{cid}'); }}
}})();
</script>
"""
    return PAGE_HEAD + body + PAGE_TAIL


# ── FB Scanner Page ────────────────────────────────────────────────────────────

def _fb_results_html(results: list[dict], id_offset: int = 0) -> str:
    """Render a table of FB scan results. id_offset avoids ID collisions across history sections."""
    if not results:
        return '<div style="color:#8b93a3;padding:16px 0">No posts with engagement in this scan.</div>'

    page_names: list[str] = []
    seen_pages: set[str] = set()
    for p in results:
        pn = p.get("page_name") or ""
        if pn and pn not in seen_pages:
            page_names.append(pn)
            seen_pages.add(pn)

    uid = f"s{id_offset}"   # unique prefix per scan section

    filter_pills = ''.join(
        f'<button type="button" class="pg-pill-{uid}" data-page="{escape(pn)}" '
        f'onclick="filterPage_{uid}(this)" '
        f'style="font-size:11px;padding:3px 10px;border-radius:12px;border:1px solid #2a3040;background:#11151f;color:#8b93a3;cursor:pointer;white-space:nowrap">'
        f'{escape(pn)}</button>'
        for pn in page_names
    )

    # Viral threshold buttons
    threshold_btns = (
        f'<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">'
        f'<span style="color:#8b93a3;font-size:11px">Show:</span>'
        f'<button type="button" class="thr-btn-{uid}" data-min="0" onclick="setThreshold_{uid}(this,0)" '
        f'style="font-size:11px;padding:3px 10px;border-radius:12px;border:1px solid #4ade80;background:#0a2010;color:#4ade80;cursor:pointer">All</button>'
        f'<button type="button" class="thr-btn-{uid}" data-min="500" onclick="setThreshold_{uid}(this,500)" '
        f'style="font-size:11px;padding:3px 10px;border-radius:12px;border:1px solid #2a3040;background:#11151f;color:#8b93a3;cursor:pointer">Viral 500+</button>'
        f'<button type="button" class="thr-btn-{uid}" data-min="2000" onclick="setThreshold_{uid}(this,2000)" '
        f'style="font-size:11px;padding:3px 10px;border-radius:12px;border:1px solid #2a3040;background:#11151f;color:#8b93a3;cursor:pointer">Hot 2k+</button>'
        f'<button type="button" class="thr-btn-{uid}" data-min="5000" onclick="setThreshold_{uid}(this,5000)" '
        f'style="font-size:11px;padding:3px 10px;border-radius:12px;border:1px solid #2a3040;background:#11151f;color:#8b93a3;cursor:pointer">🔥 5k+</button>'
        f'</div>'
    )

    rows = []
    for i, p in enumerate(results[:80], id_offset + 1):
        preview   = escape((p.get("preview") or "")[:200])
        img       = escape(p.get("image_url") or "")
        url       = escape(p.get("url") or "")
        page_name = escape(p.get("page_name") or "")
        page_key  = escape(p.get("page_name") or "")
        score     = int(p.get("engagement_score") or 0)
        reactions = int(p.get("reactions") or 0)
        shares    = int(p.get("shares") or 0)
        comments  = int(p.get("comments") or 0)
        pub       = (p.get("published_at") or "")[:10]
        score_col = "#4ade80" if score > 5000 else "#facc15" if score > 1000 else "#8b93a3"
        full_text = escape((p.get("text") or "")[:800])

        if img:
            thumb_html = (
                f'<div class="thumb-wrap" style="position:relative;display:inline-block;cursor:pointer"'
                f' onmouseenter="showPreview(event,{i})" onmouseleave="hidePreview({i})">'
                f'<img src="{img}" style="width:80px;height:62px;object-fit:cover;border-radius:4px;display:block">'
                f'<div id="prev-{i}" style="display:none;position:fixed;z-index:999;pointer-events:none;'
                f'background:#0b0e14;border:1px solid #2a3040;border-radius:8px;padding:10px;'
                f'box-shadow:0 8px 32px rgba(0,0,0,.8);max-width:320px;width:320px">'
                f'<img src="{img}" style="width:100%;border-radius:4px;display:block;margin-bottom:8px">'
                f'<div style="font-size:11px;color:#facc15;margin-bottom:4px;font-weight:600">{page_name}</div>'
                f'<div style="font-size:12px;color:#c7cbd4;line-height:1.5">{preview}</div>'
                f'</div></div>'
            )
        else:
            thumb_html = '<div style="width:80px;height:62px;background:#1a1f2b;border-radius:4px"></div>'

        rows.append(
            f'<tr class="scan-row-{uid}" data-page="{page_key}" data-score="{score}">'
            f'<td style="width:26px;padding:8px 6px;vertical-align:top;text-align:center">'
            f'<input type="checkbox" class="scan-chk-{uid}" data-idx="{i - id_offset - 1}" '
            f'onchange="updateBatchBtn_{uid}()" style="cursor:pointer;width:14px;height:14px">'
            f'</td>'
            f'<td style="width:90px;padding:8px 6px;vertical-align:top">{thumb_html}</td>'
            f'<td style="vertical-align:top;padding:8px 10px">'
            f'<div style="font-size:11px;color:#facc15;font-weight:600;margin-bottom:3px">{page_name}</div>'
            f'<div style="font-size:13px;line-height:1.4;color:#e6e8ec">{preview}</div>'
            f'<div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">'
            f'<button type="button" onclick="toggleFull({i})" '
            f'style="font-size:10px;padding:2px 7px;background:#0a1020;border:1px solid #2a3555;color:#8b93a3;cursor:pointer;border-radius:3px">&#9660; Full Text</button>'
            f'<a href="{url}" target="_blank" rel="noopener" '
            f'style="font-size:10px;padding:2px 7px;background:#0a1020;border:1px solid #2a3555;color:#8b93a3;border-radius:3px;text-decoration:none">&#128279; View Post</a>'
            f'</div>'
            f'<div id="full-{i}" style="display:none;margin-top:6px;font-size:12px;color:#c7cbd4;line-height:1.5;white-space:pre-wrap;background:#060910;padding:8px;border-radius:4px;border:1px solid #1a1f2b">{full_text}</div>'
            f'<div style="font-size:10px;color:#3a4055;margin-top:4px">{pub}</div>'
            f'</td>'
            f'<td style="white-space:nowrap;text-align:right;padding:8px 10px;vertical-align:top">'
            f'<div style="color:{score_col};font-size:17px;font-weight:700;margin-bottom:2px">{score:,}</div>'
            f'<div style="color:#8b93a3;font-size:9px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">eng. score</div>'
            f'<div style="display:flex;flex-direction:column;gap:3px;align-items:flex-end">'
            f'<span style="background:#1a2e1a;color:#4ade80;border-radius:4px;padding:2px 7px;font-size:12px;font-weight:600">&#128077; {reactions:,}</span>'
            f'<span style="background:#1a1a2e;color:#60a5fa;border-radius:4px;padding:2px 7px;font-size:12px;font-weight:600">&#128257; {shares:,}</span>'
            f'<span style="background:#2e1a1a;color:#f87171;border-radius:4px;padding:2px 7px;font-size:12px;font-weight:600">&#128172; {comments:,}</span>'
            f'</div>'
            f'</td>'
            f'<td style="padding:8px 10px;vertical-align:top;width:130px">'
            f'<form method="post" action="/fb-scanner/send-to-queue" style="margin:0">'
            f'<input type="hidden" name="idx" value="{i - id_offset - 1}">'
            f'<button type="submit" class="primary" style="font-size:11px;padding:5px 10px;width:100%;margin-bottom:4px">&#43; Send to Queue</button>'
            f'</form>'
            f'</td>'
            f'</tr>'
        )

    table = (
        f'<div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:10px">'
        f'{threshold_btns}'
        f'<div style="display:flex;flex-wrap:wrap;gap:4px;margin-left:auto">'
        f'<button type="button" id="pill-all-{uid}" class="pg-pill-{uid}" data-page="__all__" '
        f'onclick="filterPage_{uid}(this)" '
        f'style="font-size:11px;padding:3px 10px;border-radius:12px;border:1px solid #4ade80;background:#0a2010;color:#4ade80;cursor:pointer">All pages</button>'
        f'{filter_pills}</div></div>'
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">'
        f'<button type="button" id="batch-btn-{uid}" onclick="batchSend_{uid}()" '
        f'style="font-size:12px;padding:5px 14px;background:#0a2010;border:1px solid #4ade80;color:#4ade80;border-radius:4px;cursor:pointer;display:none">'
        f'&#43; Send Selected (<span id="batch-cnt-{uid}">0</span>)</button>'
        f'<button type="button" onclick="selectAll_{uid}()" '
        f'style="font-size:11px;padding:3px 10px;border-radius:12px;border:1px solid #2a3040;background:#11151f;color:#8b93a3;cursor:pointer">Select All</button>'
        f'<button type="button" onclick="selectNone_{uid}()" '
        f'style="font-size:11px;padding:3px 10px;border-radius:12px;border:1px solid #2a3040;background:#11151f;color:#8b93a3;cursor:pointer">Clear</button>'
        f'</div>'
        f'<table id="scan-table-{uid}" style="font-size:13px">'
        f'<thead><tr><th style="width:26px"></th><th style="width:90px"></th><th>Post</th>'
        f'<th style="text-align:right;white-space:nowrap">👍 Reactions &nbsp; 🔄 Shares &nbsp; 💬 Comments</th>'
        f'<th style="width:130px"></th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
        f'<script>'
        f'var _curPage_{uid}="__all__", _curMin_{uid}=0;'
        f'function _applyFilters_{uid}(){{'
        f'  document.querySelectorAll(".scan-row-{uid}").forEach(function(r){{'
        f'    var pg=r.getAttribute("data-page"), sc=parseInt(r.getAttribute("data-score")||"0");'
        f'    r.style.display=((_curPage_{uid}==="__all__"||pg===_curPage_{uid})&&sc>=_curMin_{uid})?"":"none";'
        f'  }});'
        f'}}'
        f'function filterPage_{uid}(btn){{'
        f'  _curPage_{uid}=btn.getAttribute("data-page");'
        f'  document.querySelectorAll(".pg-pill-{uid}").forEach(function(b){{b.style.background="#11151f";b.style.color="#8b93a3";b.style.borderColor="#2a3040";}});'
        f'  btn.style.background="#0a2010";btn.style.color="#4ade80";btn.style.borderColor="#4ade80";'
        f'  _applyFilters_{uid}();'
        f'}}'
        f'function setThreshold_{uid}(btn,min){{'
        f'  _curMin_{uid}=min;'
        f'  document.querySelectorAll(".thr-btn-{uid}").forEach(function(b){{b.style.background="#11151f";b.style.color="#8b93a3";b.style.borderColor="#2a3040";}});'
        f'  btn.style.background="#0a2010";btn.style.color="#4ade80";btn.style.borderColor="#4ade80";'
        f'  _applyFilters_{uid}();'
        f'}}'
        f'function updateBatchBtn_{uid}(){{'
        f'  var chks=document.querySelectorAll(".scan-chk-{uid}:checked");'
        f'  var n=chks.length;'
        f'  var btn=document.getElementById("batch-btn-{uid}");'
        f'  var cnt=document.getElementById("batch-cnt-{uid}");'
        f'  if(cnt)cnt.textContent=n;'
        f'  if(btn)btn.style.display=n>0?"":"none";'
        f'}}'
        f'function selectAll_{uid}(){{'
        f'  document.querySelectorAll(".scan-chk-{uid}").forEach(function(c){{c.checked=true;}});'
        f'  updateBatchBtn_{uid}();'
        f'}}'
        f'function selectNone_{uid}(){{'
        f'  document.querySelectorAll(".scan-chk-{uid}").forEach(function(c){{c.checked=false;}});'
        f'  updateBatchBtn_{uid}();'
        f'}}'
        f'function batchSend_{uid}(){{'
        f'  var idxs=[];'
        f'  document.querySelectorAll(".scan-chk-{uid}:checked").forEach(function(c){{idxs.push(c.getAttribute("data-idx"));}});'
        f'  if(!idxs.length)return;'
        f'  var fd=new FormData();'
        f'  idxs.forEach(function(v){{fd.append("idx",v);}});'
        f'  fd.append("id_offset","{id_offset}");'
        f'  fetch("/fb-scanner/send-selected",{{method:"POST",body:fd}})'
        f'    .then(function(r){{return r.json();}})'
        f'    .then(function(d){{'
        f'      var msg=d.queued+" post"+(d.queued!==1?"s":"")+" queued";'
        f'      if(d.skipped)msg+=" ("+d.skipped+" skipped)";'
        f'      alert(msg);'
        f'      document.querySelectorAll(".scan-chk-{uid}:checked").forEach(function(c){{c.checked=false;}});'
        f'      updateBatchBtn_{uid}();'
        f'    }})'
        f'    .catch(function(){{alert("Error sending to queue");}});'
        f'}}'
        f'</script>'
    )
    return table


def render_fb_scanner_page(
    results: list[dict],
    job: dict,
    competitors: list[str],
    history: list[dict] | None = None,
    flash: str = "",
    active_tab: str = "latest",
    top_posts: list[dict] | None = None,
) -> str:
    """Facebook competitor scanner page."""
    status   = job.get("status", "idle")
    started  = job.get("started_at", "")
    finished = job.get("finished_at", "")
    hours    = job.get("hours", 24)
    count    = len(results)
    err      = job.get("error", "")

    flash_html = f'<div class="flash">{escape(flash)}</div>' if flash else ""

    if status == "running":
        elapsed = ""
        if started:
            try:
                from datetime import datetime as _dt, timezone as _tz
                s = _dt.fromisoformat(started.replace("Z", "+00:00"))
                elapsed = f" — {int((_dt.now(_tz.utc) - s).total_seconds())}s elapsed"
            except Exception:
                pass
        status_html = (
            f'<div style="background:#1a1800;border:1px solid #5a5000;border-radius:6px;padding:10px 14px;margin-bottom:14px;font-size:13px;display:flex;align-items:center;justify-content:space-between;gap:12px">'
            f'<span>&#9203; Scanning Facebook pages{elapsed} &nbsp;<span style="color:#8b93a3;font-size:11px">(page refreshes every 10s)</span></span>'
            f'<form method="post" action="/fb-scanner/reset" style="margin:0">'
            f'<button type="submit" style="font-size:11px;padding:3px 10px;background:#3a1414;border-color:#7a2020;color:#f87171">&#9726; Reset</button>'
            f'</form></div>'
        )
        page_meta = '<meta http-equiv="refresh" content="10">'
    elif status == "error":
        status_html = (
            f'<div style="background:#1a0000;border:1px solid #7a0000;border-radius:6px;padding:10px 14px;margin-bottom:14px;font-size:13px;color:#f87171">'
            f'&#9888; Scan failed: {escape(err[:300])}</div>'
        )
        page_meta = ""
    elif status == "done" and results:
        status_html = (
            f'<div style="background:#0a1800;border:1px solid #1a5000;border-radius:6px;padding:10px 14px;margin-bottom:14px;font-size:13px">'
            f'&#10003; {count} posts ranked by engagement'
            + (f' &middot; <span style="color:#8b93a3">{finished[:16].replace("T"," ")}</span>' if finished else "")
            + '</div>'
        )
        page_meta = ""
    else:
        status_html = ""
        page_meta   = ""

    # Checkbox list of competitor pages — all checked by default
    comp_checks = ""
    for c in competitors[:50]:
        label = escape(c.rstrip("/").split("/")[-1])
        url_e = escape(c)
        comp_checks += (
            f'<label style="display:flex;align-items:center;gap:6px;font-size:12px;color:#c8cdd8;'
            f'padding:4px 8px;border:1px solid #2a3040;border-radius:5px;cursor:pointer;white-space:nowrap">'
            f'<input type="checkbox" name="page_url" value="{url_e}" checked style="accent-color:#3b82f6"> '
            f'{label}</label>'
        )

    is_running = status == "running"
    scan_form = (
        f'<form method="post" action="/fb-scanner/scan">'
        f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px">'
        f'<select name="hours" style="font-size:12px;padding:5px 8px">'
        f'<option value="24" {"selected" if hours==24 else ""}>Last 24 hours</option>'
        f'<option value="48" {"selected" if hours==48 else ""}>Last 48 hours</option>'
        f'<option value="72" {"selected" if hours==72 else ""}>Last 72 hours</option>'
        f'</select>'
        f'<button type="button" onclick="toggleAll(true)" style="font-size:11px;padding:3px 8px">All</button>'
        f'<button type="button" onclick="toggleAll(false)" style="font-size:11px;padding:3px 8px">None</button>'
        f'<button type="submit" class="primary" style="padding:6px 18px;font-size:13px"'
        + (' disabled' if is_running else '') + '>'
        + ('&#9203; Scanning...' if is_running else '&#128269; Scan Selected')
        + f'</button>'
        f'<a href="/pipeline-queue" style="font-size:12px;color:#8b93a3;padding:6px 12px;border:1px solid #2a3040;border-radius:4px">&#8592; Queue</a>'
        f'</div>'
        f'<div id="comp-checks" style="display:flex;flex-wrap:wrap;gap:6px">{comp_checks}</div>'
        f'</form>'
        f'<script>function toggleAll(v){{document.querySelectorAll(\'#comp-checks input[type=checkbox]\').forEach(function(c){{c.checked=v;}})}}</script>'
    )

    if not results:
        if status not in ("running", "error"):
            latest_html = '<div style="color:#8b93a3;padding:24px 0">No results yet. Click <b>Scan Competitors</b> to pull the latest posts from all competitor pages.</div>'
        else:
            latest_html = ""
    else:
        latest_html = _fb_results_html(results, id_offset=0)

    # History sections (previous scans, collapsed by default)
    history_html = ""
    if history:
        for h_idx, entry in enumerate(history):
            h_job     = entry.get("job", {})
            h_results = entry.get("results", [])
            h_fin     = (h_job.get("finished_at") or "")[:16].replace("T", " ")
            h_hours   = h_job.get("hours", 24)
            h_count   = len(h_results)
            if not h_results:
                continue
            h_table = _fb_results_html(h_results, id_offset=(h_idx + 1) * 1000)
            history_html += (
                f'<details style="margin-top:20px;border:1px solid #1a1f2b;border-radius:6px;padding:0">'
                f'<summary style="padding:10px 14px;cursor:pointer;font-size:13px;color:#8b93a3;list-style:none;display:flex;justify-content:space-between;align-items:center">'
                f'<span>&#128337; Previous scan &mdash; {escape(h_fin)} &nbsp; '
                f'<span style="color:#facc15">{h_count} posts</span> &middot; last {h_hours}h</span>'
                f'<span style="font-size:11px">&#9660; expand</span></summary>'
                f'<div style="padding:12px 14px">{h_table}</div>'
                f'</details>'
            )

    # Tab bar
    tab_style_active   = "padding:7px 18px;font-size:13px;border-radius:4px 4px 0 0;border:1px solid #2a3040;border-bottom:none;background:#0d111a;color:#facc15;cursor:pointer;font-weight:600"
    tab_style_inactive = "padding:7px 18px;font-size:13px;border-radius:4px 4px 0 0;border:1px solid transparent;background:none;color:#8b93a3;cursor:pointer"
    n_top = len(top_posts) if top_posts else (sum(len(e.get("results", [])) for e in (history or [])) + len(results))
    tab_bar = (
        f'<div style="display:flex;gap:0;border-bottom:1px solid #2a3040;margin-bottom:20px">'
        f'<a href="/fb-scanner?tab=latest" style="{tab_style_active if active_tab=="latest" else tab_style_inactive};text-decoration:none">'
        f'&#128240; Latest Scan</a>'
        f'<a href="/fb-scanner?tab=top" style="{tab_style_active if active_tab=="top" else tab_style_inactive};text-decoration:none">'
        f'&#128293; Top Posts (all scans)</a>'
        f'</div>'
    )

    # Top posts tab content
    if active_tab == "top" and top_posts is not None:
        top_html = _fb_results_html(top_posts, id_offset=9000)
        if not top_posts:
            top_html = '<div style="color:#8b93a3;padding:24px 0">No scan history yet. Run at least one scan first.</div>'
        tab_content = top_html
    else:
        tab_content = f"{latest_html}\n{history_html}"

    body = f"""
{flash_html}
<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:16px">
  <div>
    <h1 style="margin:0 0 4px 0">&#128240; Facebook Competitor Scanner</h1>
    <div style="color:#8b93a3;font-size:13px">Ranked by reactions + (shares&times;3) + (comments&times;2) &mdash; same formula as the pipeline</div>
  </div>
  <div></div>
</div>

{status_html}

<div style="margin-bottom:20px">
{scan_form}
</div>

{tab_bar}
{tab_content}

<details open style="margin-top:28px;border:1px solid #1a1f2b;border-radius:6px">
  <summary style="padding:10px 16px;cursor:pointer;font-size:13px;color:#8b93a3;list-style:none;display:flex;justify-content:space-between;align-items:center">
    <span>&#9881; Manage FB Sources ({len(competitors)} pages)</span>
    <span style="font-size:11px">&#9660; expand</span>
  </summary>
  <div style="padding:14px 16px">
    <form method="post" action="/fb-scanner/competitors/add" style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap">
      <input name="url" type="url" placeholder="https://www.facebook.com/pagename"
             style="flex:1;min-width:260px;font-size:13px;padding:6px 10px;background:#0d111a;border:1px solid #2a3040;border-radius:4px;color:#e6e8ec">
      <button type="submit" class="primary" style="padding:6px 14px;font-size:13px">+ Add Source</button>
    </form>
    <div style="display:flex;flex-direction:column;gap:4px">
      {''.join(
        f'<div style="display:flex;align-items:center;justify-content:space-between;padding:6px 10px;'
        f'background:#0d111a;border:1px solid #1a2030;border-radius:4px">'
        f'<span style="font-size:12px;color:#c8cdd8">{escape(c)}</span>'
        f'<form method="post" action="/fb-scanner/competitors/delete" style="margin:0">'
        f'<input type="hidden" name="url" value="{escape(c)}">'
        f'<button type="submit" style="background:#3a1414;border-color:#7a2020;font-size:11px;padding:2px 8px;color:#f87171">Remove</button>'
        f'</form></div>'
        for c in competitors
      )}
    </div>
  </div>
</details>

<script>
function toggleFull(i) {{
  var el = document.getElementById('full-'+i);
  if (!el) return;
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}}
function showPreview(e, i) {{
  var el = document.getElementById('prev-'+i);
  if (!el) return;
  el.style.display = 'block';
  _positionPreview(e, el);
}}
function _positionPreview(e, el) {{
  var x = e.clientX + 16, y = e.clientY - 20;
  var vw = window.innerWidth, vh = window.innerHeight;
  if (x + 330 > vw) x = e.clientX - 336;
  if (y + 300 > vh) y = vh - 310;
  el.style.left = x + 'px'; el.style.top = y + 'px';
}}
function hidePreview(i) {{
  var el = document.getElementById('prev-'+i);
  if (el) el.style.display = 'none';
}}
document.addEventListener('mousemove', function(e) {{
  document.querySelectorAll('[id^="prev-"]').forEach(function(el) {{
    if (el.style.display !== 'none') _positionPreview(e, el);
  }});
}});
</script>
"""
    head = _page_head(extra_meta=page_meta)
    return head + body + PAGE_TAIL
