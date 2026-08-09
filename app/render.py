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
"""

NAV = """
  <div class="nav" style="display:flex;justify-content:space-between;align-items:center">
    <div>
      <a href="/">First Signal Wire</a>
      <a href="/watchlist">Watchlist</a>
      <a href="/sources">Sources</a>
      <a href="/pipeline-queue">&#9654; Production Queue</a>
    </div>
    <form method="post" action="/logout" class="inline-form">
      <button type="submit" style="font-size:11px">Logout</button>
    </form>
  </div>
"""

def _page_head(extra_meta: str = "") -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>AIM News Desk &mdash; Phase 1f</title>
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
    <h1 style="text-align:center;margin-bottom:24px">AIM News Desk</h1>
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
  <title>AIM News Desk &mdash; Log In</title>
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
        <td class="score {_score_class(c['viral_score'])}">{c['viral_score']:.0f}</td>
        <td class="score {_score_class(c['confidence_score'])}">{c['confidence_score']:.0f}</td>
        <td class="score {_score_class(c['momentum_score'])}">{c['momentum_score']:.0f}</td>
        <td><a href="/stories/{c['id']}">{escape(c['canonical_headline'])}</a></td>
        <td>{escape(c['category'] or '-')}</td>
        <td>{c['source_count']}</td>
        <td>{escape(c['age'])}</td>
        <td class="{fresh_class}">{escape(c.get('updated_ago', '-'))}{' <span class="new-dot">&bull;</span>' if c.get('is_fresh') else ''}</td>
        <td><span class="badge status-{escape(c['status'])}">{escape(c['status'])}</span></td>
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
    {len(clusters)} story clusters &middot; viral score is a rules-only PRELIMINARY approximation (AI enrichment lands in Phase 3) &middot; sorted by {sort_label}
    <br>Last scan: {escape(last_scan)} (auto-scans every 3-30 min in the background; this page refreshes itself every {refresh_seconds}s)
    <div class="sort-toggle">
      Sort:
      <a href="{base_path}?sort=latest" class="{latest_active}">Latest</a>
      <a href="{base_path}?sort=viral" class="{viral_active}">Highest Viral</a>
    </div>
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
        <th>Category</th><th>Sources</th><th>Age</th><th>Updated</th><th>Status</th>
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
        <td>{escape(cp['covered_at'])}</td>
        <td>{escape(cp.get('platform') or '-')}</td>
        <td>{link}</td>
        <td>{escape(cp.get('format') or '-')}</td>
        <td>{escape(cp.get('editor') or '-')}</td>
        <td>{escape(cp.get('notes') or '-')}</td>
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
        <td><a href="{escape(a['url'])}" target="_blank" rel="noopener">{escape(a['headline'])}</a></td>
        <td><a href="/?source_id={a['source_id']}">{escape(a['source_name'])}</a></td>
        <td><span class="badge tier-{a['source_tier']}">T{a['source_tier']}</span></td>
        <td>{escape(a['published_at'] or '-')}</td>
        <td>{escape(a['detected_at'])}</td>
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


def render_sources_page(sources: list[dict]) -> str:
    rows = []
    for s in sources:
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
        error_html = f'<div class="dup-flag">{escape(s["last_error"])}</div>' if s["last_error"] else ""

        rows.append(f"""
      <tr>
        <td><a href="/?source_id={s['id']}">{escape(s['name'])}</a><div class="dup-flag">{escape(s['type'])}</div></td>
        <td>{error_html or '-'}</td>
        <td>{escape(s['last_fetch_at'])}</td>
        <td>
          <form method="post" action="/sources/{s['id']}/update" class="inline-form">
            <input type="text" name="category" value="{escape(s['category'] or '')}" style="width:90px" placeholder="category">
            <select name="credibility_tier">{tier_options}</select>
            <select name="polling_tier">{polling_options}</select>
            <label><input type="checkbox" name="enabled" value="true" {"checked" if s['enabled'] else ""}> enabled</label>
            <button type="submit">Save</button>
          </form>
          <form method="post" action="/sources/{s['id']}/fetch" class="inline-form">
            <button type="submit">Fetch now</button>
          </form>
        </td>
      </tr>""")

    type_options_new = "".join(f'<option value="{t}">{label}</option>' for t, label in _TYPE_OPTIONS)
    tier_options_new = "".join(f'<option value="{t}">T{t}</option>' for t in _TIER_OPTIONS)
    polling_options_new = "".join(f'<option value="{p}">{p}</option>' for p in _POLLING_OPTIONS)

    body = f"""
  <h1>Sources</h1>
  <div class="sub">{len(sources)} sources &middot; add, edit, enable/disable, and re-prioritize below &middot; disabling removes a source from the polling schedule without deleting its history</div>

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
    <thead><tr><th>Name</th><th>Last error</th><th>Last fetch</th><th style="width:50%">Edit</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
"""
    return PAGE_HEAD + body + PAGE_TAIL


def render_pipeline_queue_page(
    items: list[dict],
    msg: str = "",
    job: dict | None = None,
    picks_ready: bool = False,
    picks_count: int = 0,
    picks_date: str = "",
    recommendation: dict | None = None,
) -> str:
    pending   = [x for x in items if x.get("queue_status") == "pending"]
    approved  = [x for x in items if x.get("queue_status") == "approved"]
    used      = [x for x in items if x.get("queue_status") == "used"]
    skipped   = [x for x in items if x.get("queue_status") == "skipped"]

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
        ai  = item.get("ai_viral_score")
        raw = item.get("viral_score", 0)
        if ai is not None:
            color = "#4ade80" if ai >= 70 else "#facc15" if ai >= 50 else "#8b93a3"
            reason = escape(item.get("ai_score_reason") or "")
            tip = f' title="{reason}"' if reason else ""
            return f'<span style="color:{color};font-weight:600;cursor:default;font-size:13px"{tip}>{ai}</span>'
        if raw:
            return f'<span style="color:#8b93a3">{raw:.0f}</span>'
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
            badges = ""
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
                # Use recommended gen_type if available, else suggested template
                eff_type = (rec.get("gen_type") if rec else None) or ("tobi" if s_tmpl == "tobi" else "image_card")
                img_sel  = "selected" if eff_type == "image_card" else ""
                tobi_sel = "selected" if eff_type == "tobi" else ""
                type_cell = (f'<select name="type_{cid}" style="font-size:12px;padding:3px 6px">'
                             f'<option value="image_card" {img_sel}>Image Card</option>'
                             f'<option value="tobi" {tobi_sel}>TOBI</option></select>')
                check = f'<input type="checkbox" name="selected" value="{cid}" {is_checked}>'
            else:
                label = "Image Card" if gen_type == "image_card" else "TOBI"
                type_cell = f'<span style="color:#8b93a3">{label}</span>'
                check = ""

            draft_html = draft_toggle(cid, draft, item) if selectable else ""
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

            rows.append(f"""
      <tr>
        <td style="width:28px">{check}</td>
        <td>
          <div style="font-size:13px;font-weight:500;line-height:1.4">{text}</div>
          <div style="color:#8b93a3;font-size:11px;margin-top:3px">{cat} &middot; {srcs} source(s) &middot; added {added}</div>
          <div style="margin-top:4px">{badges}</div>
          {draft_html}{angles_btn}{preview_btn}
        </td>
        <td>{ai_score_cell(item)}</td>
        <td>{verif_badge(verif)}</td>
        <td>{type_cell}</td>
      </tr>""")
        return "".join(rows)

    draft_js = """
<script>
function toggleDraft(cid) {
  var el = document.getElementById('draft-' + cid);
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
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

    pending_section = f"""
  {full_batch_btn}
  <h2>Pending ({len(pending)})</h2>
  <p class="sub">Select stories, choose Image Card or TOBI for each, then send to generation. Tmpl badge = suggested template. &#9888; SIMILAR = story may already be posted.</p>
  <form method="post" action="/pipeline-queue/generate" id="qf">
    <div style="margin-bottom:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button type="button" onclick="document.querySelectorAll('#qf input[type=checkbox]').forEach(c=>c.checked=true)" style="font-size:11px">Select All</button>
      <button type="button" onclick="document.querySelectorAll('#qf input[type=checkbox]').forEach(c=>c.checked=false)" style="font-size:11px">Clear</button>
      <button type="submit" name="action" value="generate" class="primary" style="margin-left:8px">&#9654;&nbsp;Send Selected to Generation</button>
      <button type="submit" name="action" value="remove" style="background:#3a1414;border-color:#7a2020">&#10005;&nbsp;Remove Selected</button>
    </div>
    <table>
      <thead><tr><th></th><th>Story</th><th>Viral</th><th>Verified</th><th>Type</th></tr></thead>
      <tbody>{make_rows(pending)}</tbody>
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

        approved_section = f"""
  <h2 style="margin-top:32px">Ready for Generation ({len(approved)})</h2>
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
  <h1>&#9654; First Signal Production Queue</h1>
  <p class="sub">Stories sent from the News Desk via "Send to First Signal Pipeline". Select and assign type, then send to generation. Page refreshes every 30 seconds.</p>
  {flash}
  {gen_panel}{gen_panel_js}
  {manual_add_panel}
  {pending_section}
  {approved_section}
  {history_section}
"""
    head = _page_head(extra_meta='<meta http-equiv="refresh" content="30">')
    return head + body + PAGE_TAIL
