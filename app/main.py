import json
import logging
import subprocess
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select, func
from starlette.middleware.sessions import SessionMiddleware

from app.auth import NotAuthenticated, get_user_role, require_user, verify_password_login
from app.clustering import merge_clusters, split_cluster
from app.config import POLL_MINUTES_PRIORITY, POLL_MINUTES_STANDARD, POLL_MINUTES_LOW, SESSION_SECRET
from app.collectors.rss import collect_source
from app.collectors.twitter_manual import TweetCaptureError, capture_tweet
from app.db import SessionLocal
from app.handoff import write_handoff
from app.models import Source, NormalizedArticle, StoryCluster, StoryClusterArticle, CoveredPost
from app.render import (
    render_wire_page, render_detail_page, render_sources_page,
    render_pipeline_queue_page, render_login_page,
)

# ── First Signal pipeline paths ───────────────────────────────────────────────
_FSN_ROOT = Path(
    r"C:\Users\john\OneDrive\Documents\AMERICAN ICON MEDIA"
    r"\FIRST SIGNAL\AUTOMATION SOFTWARE"
    r"\first_signal_news-pipeline-20260602"
)
_FSN_QUEUE_PATH  = _FSN_ROOT / "memory" / "scanner_queue.json"
_FSN_PICKS_PATH  = _FSN_ROOT / "memory" / "approved_picks.json"
_FSN_JOB_PATH    = _FSN_ROOT / "memory" / "batch_job.json"
_batch_lock = threading.Lock()

def _load_fsn_queue() -> list[dict]:
    if _FSN_QUEUE_PATH.exists():
        try:
            return json.loads(_FSN_QUEUE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    # Running on deployed server (no local FSN path) — build queue from DB.
    # Shows all clusters where "Send to First Signal Pipeline" was clicked.
    session = SessionLocal()
    try:
        clusters = session.execute(
            select(StoryCluster).where(StoryCluster.handoff_sent_at.is_not(None))
            .order_by(StoryCluster.handoff_sent_at.desc())
            .limit(200)
        ).scalars().all()
        items = []
        for c in clusters:
            items.append({
                "cluster_id": c.id,
                "text": c.canonical_headline or "",
                "category": c.category or "general",
                "viral_score": round(float(c.viral_score or 0), 1),
                "confidence_score": round(float(c.confidence_score or 0), 1),
                "entities": json.loads(c.entities or "[]"),
                "keywords": json.loads(c.keywords or "[]"),
                "verification_status": c.verification_status or "unverified",
                "queue_status": "pending",
                "added_to_queue_at": c.handoff_sent_at.isoformat() if c.handoff_sent_at else "",
                "sources": [],
                "draft": None,
                "_source": "newsdesk_handoff",
            })
        return items
    finally:
        session.close()

def _save_fsn_queue(items: list[dict]) -> None:
    _FSN_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FSN_QUEUE_PATH.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")

def _read_picks() -> dict | None:
    if not _FSN_PICKS_PATH.exists():
        return None
    try:
        return json.loads(_FSN_PICKS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None

def _read_job() -> dict:
    if not _FSN_JOB_PATH.exists():
        return {"status": "idle"}
    try:
        return json.loads(_FSN_JOB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "idle"}

def _write_job(data: dict) -> None:
    _FSN_JOB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FSN_JOB_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_picks_from_approved_queue() -> dict | None:
    """Convert approved queue items → approved_picks.json and write it. Returns the picks dict."""
    items = _load_fsn_queue()
    approved = [x for x in items if x.get("queue_status") == "approved"]
    if not approved:
        return None

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    posts = []
    for idx, item in enumerate(approved, start=1):
        draft = item.get("draft") or {}
        gen_type = item.get("generation_type", "image_card")
        tmpl = item.get("suggested_template") or "A"
        scene = item.get("suggested_scene") or "US Capitol dome against dramatic sky, American flag, breaking news mood"

        if gen_type == "tobi":
            posts.append({
                "id": idx,
                "template": "tobi",
                "text": draft.get("headline") or item.get("text", ""),
                "image_url": None,
                "post_url": item.get("source_url", ""),
                "captions": {},
                "first_comment": draft.get("first_comment", ""),
            })
        else:
            headline = draft.get("headline") or item.get("text", "")
            tag = draft.get("tag") or "JUST IN"
            captions = draft.get("captions") or {}
            first_comment = draft.get("first_comment", "")
            posts.append({
                "id": idx,
                "template": tmpl,
                "text": headline,
                "_tag": tag,
                "image_url": "GENERATE",
                "post_url": item.get("source_url", ""),
                "scene": scene,
                "captions": captions,
                "first_comment": first_comment,
            })

    picks = {"batch_date": date_str, "posts": posts}
    _FSN_PICKS_PATH.write_text(json.dumps(picks, indent=2, ensure_ascii=False), encoding="utf-8")
    return picks


def _run_batch_background(picks: dict, batch_dir: str) -> None:
    """Full generation pipeline: batch → logo → report. Writes progress to batch_job.json."""
    posts    = picks.get("posts") or []
    n_images = sum(1 for p in posts if p.get("image_url"))
    n_tobi   = sum(1 for p in posts if not p.get("image_url"))
    total    = len(posts)
    root     = str(_FSN_ROOT)
    py       = sys.executable

    job: dict = {
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "batch_dir": batch_dir,
        "total": total,
        "n_images": n_images,
        "n_tobi": n_tobi,
        "completed": 0,
        "failed": 0,
        "log": [f"Starting: {n_images} image card(s) + {n_tobi} TOBI(s) → {batch_dir}"],
    }
    _write_job(job)

    # ── Step 1: generate images + TOBI ──────────────────────────────────────
    cmd = [
        py, "batch_from_scrape.py",
        "--input", str(_FSN_PICKS_PATH),
        "--images", str(n_images),
        "--tobi", str(n_tobi),
        "--count", str(total),
        "--batch-dir", batch_dir,
    ]

    # Build env: inherit current env + load FSN .env so KIE_AI_API_KEY is
    # always present regardless of which directory the web server was launched from.
    import os as _os
    batch_env = _os.environ.copy()
    fsn_env_path = _FSN_ROOT / ".env"
    if fsn_env_path.exists():
        for _line in fsn_env_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                batch_env.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

    # Hard wall: if batch takes longer than MAX_BATCH_TIME + 5 min, kill it.
    # This prevents the background thread hanging forever on a stalled subprocess.
    BATCH_WALL = 3900  # 65 min — well above the 3600s internal timeout

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            cwd=root, env=batch_env,
        )
        import threading as _threading
        def _kill_after(seconds, p):
            if p.poll() is None:
                p.kill()
        _timer = _threading.Timer(BATCH_WALL, _kill_after, args=[BATCH_WALL, proc])
        _timer.daemon = True
        _timer.start()
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                job["log"].append(line)
                if line.strip().startswith("OK") and "#" in line:
                    job["completed"] += 1
                elif "FAIL" in line and "#" in line:
                    job["failed"] += 1
                _write_job(job)
            proc.wait()
        finally:
            _timer.cancel()
        if proc.returncode != 0:
            job["status"] = "error"
            job["log"].append(f"batch_from_scrape.py exited {proc.returncode}")
            _write_job(job)
            return
    except Exception as exc:
        job["status"] = "error"
        job["log"].append(f"ERROR launching batch: {exc}")
        _write_job(job)
        return

    # ── Step 2: stamp logos ──────────────────────────────────────────────────
    job["log"].append("Stamping logos...")
    _write_job(job)
    r = subprocess.run([py, "apply_logo.py", "--batch-dir", batch_dir],
                       cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    for line in (r.stdout + r.stderr).splitlines():
        if line.strip():
            job["log"].append(line)

    # ── Step 3: batch report ─────────────────────────────────────────────────
    job["log"].append("Building report...")
    _write_job(job)
    r = subprocess.run([py, "build_batch_report.py", "--batch-dir", batch_dir],
                       cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    for line in (r.stdout + r.stderr).splitlines():
        if line.strip():
            job["log"].append(line)

    # ── Mark queue items used + write back output file path ─────────────────
    try:
        queue = _load_fsn_queue()
        # Build text → output PNG path from batch_summary.json
        output_map: dict[str, str] = {}
        summary_path = Path(batch_dir) / "batch_summary.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            for post in summary.get("post", []):
                post_id = post.get("id")
                tmpl = (post.get("template") or "a").lower()
                if post_id is not None and tmpl != "tobi":
                    png_name = f"{post_id:02d}_{tmpl}.png"
                    png_abs = str(Path(batch_dir) / png_name)
                    txt = (post.get("text") or "").strip()
                    if txt:
                        output_map[txt] = png_abs
        for item in queue:
            if item.get("queue_status") == "approved":
                item["queue_status"] = "used"
                item_txt = (item.get("text") or "").strip()
                if item_txt in output_map:
                    item["output_file"] = output_map[item_txt]
        _save_fsn_queue(queue)
        job["log"].append("Queue items marked used.")
    except Exception as exc:
        job["log"].append(f"WARN: could not mark queue items used: {exc}")

    job["status"] = "done"
    job["finished_at"] = datetime.now(timezone.utc).isoformat()
    _write_job(job)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aim-news-desk")

scheduler = BackgroundScheduler()

TIER_MINUTES = {
    "priority": POLL_MINUTES_PRIORITY,
    "standard": POLL_MINUTES_STANDARD,
    "low": POLL_MINUTES_LOW,
}

# Editor-settable statuses (per spec, only New->Developing is automatic).
VALID_STATUSES = {
    "New", "Developing", "Breaking", "Trending", "Watchlist",
    "Needs Verification", "Ready", "Covered", "Dismissed", "Archived",
}

# In-memory only (not persisted). "running" stops the manual "Scan Now"
# button from piling up overlapping full-fetch runs if clicked repeatedly --
# the scheduled per-tier polls (poll_tier) are unaffected either way, since
# collect_source's own URL dedup makes overlapping fetches harmless, just
# wasteful. "completed_unacknowledged" drives the one-time "Scan complete"
# banner: set True when a manual scan finishes, consumed (set back to False)
# the next time the Wire page renders it, so it shows exactly once rather
# than on every subsequent auto-refresh. Only the manual scan sets this --
# the automatic background polls stay silent, since a banner every 3 minutes
# would be noise, not signal.
_scan_state = {"running": False, "completed_unacknowledged": False, "last_result": None}

VALID_SORTS = {"latest", "viral"}
WINDOW_MINUTES = {
    "15m": 15, "1h": 60, "3h": 180,
    "6h": 360, "12h": 720, "24h": 1440, "48h": 2880,
}
# How recent latest_update_at must be to render the "Updated" column as a
# highlighted fresh-activity indicator on the Wire/Watchlist tables -- a
# lightweight stand-in for the spec's "trigger an alert when meaningful
# changes occur" without building a separate alerts/notifications system.
FRESH_UPDATE_MINUTES = 15


def _dt_aware(dt):
    if dt and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _optional_int(value: str | None) -> int | None:
    """Parses a query param that may be an empty string, not just absent.
    HTML forms submit "" for an unselected <select> or blank <input
    type=number> -- FastAPI's `int | None = None` typing only supplies the
    default when the param is ABSENT, so a plain `int | None` annotation on
    a route raised a 422 on every filter-form submission that left any
    field blank. Route params come in as `str | None` and get parsed here.
    """
    return int(value) if value else None


def _age_str(detected_at) -> str:
    now = datetime.now(timezone.utc)
    age_minutes = int((now - _dt_aware(detected_at)).total_seconds() // 60)
    if age_minutes < 60:
        return f"{age_minutes}m"
    if age_minutes < 1440:
        return f"{age_minutes // 60}h"
    return f"{age_minutes // 1440}d"


def poll_tier(tier: str):
    session = SessionLocal()
    try:
        sources = session.execute(
            select(Source).where(Source.enabled.is_(True), Source.polling_tier == tier)
        ).scalars().all()
        for source in sources:
            stats = collect_source(session, source)
            logger.info("polled %s (%s): %s", source.name, tier, stats)
    finally:
        session.close()


def run_full_scan():
    if _scan_state["running"]:
        return
    _scan_state["running"] = True
    session = SessionLocal()
    new_stories = 0
    sources_scanned = 0
    sources_failed = 0
    try:
        sources = session.execute(select(Source).where(Source.enabled.is_(True))).scalars().all()
        for source in sources:
            stats = collect_source(session, source)
            sources_scanned += 1
            new_stories += stats["canonical"]
            if stats["error"]:
                sources_failed += 1
            logger.info("manual scan: %s: %s", source.name, stats)
    finally:
        session.close()
        _scan_state["running"] = False
        _scan_state["last_result"] = {
            "new_stories": new_stories,
            "sources_scanned": sources_scanned,
            "sources_failed": sources_failed,
        }
        _scan_state["completed_unacknowledged"] = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    for tier, minutes in TIER_MINUTES.items():
        scheduler.add_job(
            poll_tier, "interval", minutes=minutes, args=[tier],
            id=f"poll_{tier}", replace_existing=True,
        )
    scheduler.start()
    logger.info("Scheduler started: %s", TIER_MINUTES)
    yield
    scheduler.shutdown(wait=False)


# docs_url/redoc_url disabled: nothing external consumes this API, and the
# auto-generated docs are the one FastAPI-provided route that can't be gated
# with Depends(require_user) -- easiest fix is to not serve them at all.
app = FastAPI(title="AIM News Desk - Phase 1b", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)

# Session cookie for team login (Phase 2). SESSION_SECRET is a fixed value
# from .env, not regenerated per-process -- see .env's comment on why.
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET or "dev-only-insecure-secret")


@app.exception_handler(NotAuthenticated)
async def _not_authenticated_handler(request: Request, exc: NotAuthenticated):
    return RedirectResponse(f"/login?next={exc.next_path}", status_code=303)


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/login", response_class=HTMLResponse)
def login_page(next: str = "/"):
    return HTMLResponse(render_login_page(next_path=next))


@app.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("/")):
    user = verify_password_login(email, password)
    if not user:
        return HTMLResponse(render_login_page(error="Incorrect email or password.", next_path=next), status_code=401)
    request.session["email"] = user["email"]
    request.session["role"] = get_user_role(user)
    return RedirectResponse(next or "/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/health")
def health():
    session = SessionLocal()
    try:
        return {
            "status": "ok",
            "sources": session.execute(select(func.count(Source.id))).scalar_one(),
            "sources_with_errors": session.execute(
                select(func.count(Source.id)).where(Source.last_error.is_not(None))
            ).scalar_one(),
            "raw_normalized_articles": session.execute(select(func.count(NormalizedArticle.id))).scalar_one(),
            "story_clusters": session.execute(select(func.count(StoryCluster.id))).scalar_one(),
        }
    finally:
        session.close()


@app.get("/api/handoffs")
def api_handoffs(request: Request):
    """Return all sent-handoff clusters as JSON for the local FSN pipeline.
    Reads from the database (Supabase) so data survives server restarts.
    Protected by X-Pipeline-Key header matching PIPELINE_API_KEY env var."""
    from app.config import PIPELINE_API_KEY
    key = request.headers.get("X-Pipeline-Key", "")
    if not PIPELINE_API_KEY or key != PIPELINE_API_KEY:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    session = SessionLocal()
    try:
        clusters = session.execute(
            select(StoryCluster).where(StoryCluster.handoff_sent_at.is_not(None))
            .order_by(StoryCluster.handoff_sent_at.desc())
            .limit(200)
        ).scalars().all()

        records = []
        for cluster in clusters:
            links = session.execute(
                select(StoryClusterArticle).where(
                    StoryClusterArticle.cluster_id == cluster.id)
            ).scalars().all()
            article_ids = [l.normalized_article_id for l in links]
            articles = session.execute(
                select(NormalizedArticle).where(NormalizedArticle.id.in_(article_ids))
            ).scalars().all()

            records.append({
                "cluster_id": cluster.id,
                "canonical_headline": cluster.canonical_headline,
                "category": cluster.category,
                "status": cluster.status,
                "verification_status": cluster.verification_status,
                "scores": {
                    "viral_score_preliminary": cluster.viral_score,
                    "confidence_score": cluster.confidence_score,
                    "momentum_score": cluster.momentum_score,
                },
                "entities": json.loads(cluster.entities or "[]"),
                "keywords": json.loads(cluster.keywords or "[]"),
                "location": cluster.location,
                "first_detected_at": cluster.first_detected_at.isoformat() if cluster.first_detected_at else None,
                "latest_update_at": cluster.latest_update_at.isoformat() if cluster.latest_update_at else None,
                "sources": [
                    {
                        "source_name": a.source.name if a.source else None,
                        "headline": a.raw_article.headline if a.raw_article else a.normalized_headline,
                        "url": a.canonical_url,
                        "tier": a.source_tier,
                        "published_at": a.published_at.isoformat() if a.published_at else None,
                    }
                    for a in articles
                ],
                "handoff_sent_at": cluster.handoff_sent_at.isoformat(),
            })
        return {"handoffs": records}
    finally:
        session.close()


def _wire_response(
    *, msg, sort, category, status, verification, source_id, window,
    min_viral, min_confidence, exclude_covered, page_title, base_path,
    show_status_filter, forced_status=None,
):
    if sort not in VALID_SORTS:
        sort = "latest"
    source_id = _optional_int(source_id)
    min_viral = _optional_int(min_viral)
    min_confidence = _optional_int(min_confidence)
    effective_status = forced_status or status
    session = SessionLocal()
    try:
        query = select(StoryCluster).where(StoryCluster.status.notin_(["Dismissed", "Archived"]))
        if category:
            query = query.where(StoryCluster.category == category)
        if effective_status:
            query = query.where(StoryCluster.status == effective_status)
        if verification:
            query = query.where(StoryCluster.verification_status == verification)
        if min_viral is not None:
            query = query.where(StoryCluster.viral_score >= min_viral)
        if min_confidence is not None:
            query = query.where(StoryCluster.confidence_score >= min_confidence)
        if exclude_covered:
            query = query.where(StoryCluster.status != "Covered")
        if window in WINDOW_MINUTES:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=WINDOW_MINUTES[window])
            query = query.where(StoryCluster.first_detected_at >= cutoff)
        if source_id:
            source_cluster_ids = select(StoryClusterArticle.cluster_id).join(
                NormalizedArticle, NormalizedArticle.id == StoryClusterArticle.normalized_article_id
            ).where(NormalizedArticle.source_id == source_id).distinct()
            query = query.where(StoryCluster.id.in_(source_cluster_ids))

        order_column = StoryCluster.latest_update_at if sort == "latest" else StoryCluster.viral_score
        clusters = session.execute(query.order_by(order_column.desc()).limit(200)).scalars().all()

        now = datetime.now(timezone.utc)
        rows = [{
            "id": c.id,
            "canonical_headline": c.canonical_headline,
            "category": c.category,
            "source_count": c.source_count,
            "age": _age_str(c.first_detected_at),
            "updated_ago": _age_str(c.latest_update_at),
            "is_fresh": (now - _dt_aware(c.latest_update_at)).total_seconds() <= FRESH_UPDATE_MINUTES * 60,
            "status": c.status,
            "viral_score": c.viral_score,
            "confidence_score": c.confidence_score,
            "momentum_score": c.momentum_score,
        } for c in clusters]

        error_sources = session.execute(
            select(Source).where(Source.last_error.is_not(None))
        ).scalars().all()

        last_fetch = session.execute(
            select(func.max(Source.last_fetch_at)).where(Source.enabled.is_(True))
        ).scalar_one()
        last_scan = _age_str(last_fetch) + " ago" if last_fetch else "never"

        flashes = [msg] if msg else []
        if _scan_state["completed_unacknowledged"]:
            result = _scan_state["last_result"] or {}
            failed_note = f", {result.get('sources_failed', 0)} source(s) failed" if result.get("sources_failed") else ""
            flashes.append(
                f"Scan complete: {result.get('new_stories', 0)} new stories found "
                f"across {result.get('sources_scanned', 0)} sources{failed_note}"
            )
            _scan_state["completed_unacknowledged"] = False
        flash = " | ".join(flashes) if flashes else None

        all_categories = [
            row[0] for row in session.execute(
                select(StoryCluster.category).where(StoryCluster.category.is_not(None)).distinct()
            ).all()
        ]
        all_sources = session.execute(select(Source).order_by(Source.name)).scalars().all()

        filters = {
            "category": category, "status": effective_status, "verification": verification,
            "source_id": source_id, "window": window, "min_viral": min_viral,
            "min_confidence": min_confidence, "exclude_covered": exclude_covered,
        }

        return HTMLResponse(render_wire_page(
            rows, [(s.name, s.last_error) for s in error_sources],
            last_scan=last_scan, scanning=_scan_state["running"], flash=flash, sort=sort,
            filters=filters, categories=sorted(all_categories),
            sources=[(s.id, s.name) for s in all_sources], statuses=sorted(VALID_STATUSES),
            page_title=page_title, base_path=base_path, show_status_filter=show_status_filter,
        ))
    finally:
        session.close()


@app.get("/", response_class=HTMLResponse)
def wire(
    user: dict = Depends(require_user),
    msg: str | None = None,
    sort: str = "latest",
    category: str | None = None,
    status: str | None = None,
    verification: str | None = None,
    # These come from <select>/<input> fields that submit "" when left on
    # "Any ..." or blank -- FastAPI's int|None only defaults to None when the
    # param is ABSENT, not when it's present-but-empty, so `int | None` here
    # raised a 422 on every filter-form submission with an unset field.
    # Accept the raw string and parse manually instead.
    source_id: str | None = None,
    window: str | None = None,
    min_viral: str | None = None,
    min_confidence: str | None = None,
    exclude_covered: bool = False,
):
    return _wire_response(
        msg=msg, sort=sort, category=category, status=status, verification=verification,
        source_id=source_id, window=window, min_viral=min_viral, min_confidence=min_confidence,
        exclude_covered=exclude_covered, page_title="First Signal Wire", base_path="/",
        show_status_filter=True,
    )


@app.get("/watchlist", response_class=HTMLResponse)
def watchlist(
    user: dict = Depends(require_user),
    msg: str | None = None,
    sort: str = "latest",
    category: str | None = None,
    verification: str | None = None,
    source_id: str | None = None,
    window: str | None = None,
    min_viral: str | None = None,
    min_confidence: str | None = None,
):
    return _wire_response(
        msg=msg, sort=sort, category=category, status=None, verification=verification,
        source_id=source_id, window=window, min_viral=min_viral, min_confidence=min_confidence,
        exclude_covered=False, page_title="Watchlist", base_path="/watchlist",
        show_status_filter=False, forced_status="Watchlist",
    )


@app.post("/scan-now")
def scan_now(background_tasks: BackgroundTasks, user: dict = Depends(require_user)):
    if _scan_state["running"]:
        return RedirectResponse("/?msg=A+scan+is+already+running", status_code=303)
    background_tasks.add_task(run_full_scan)
    return RedirectResponse("/?msg=Scan+started+in+the+background+--+refresh+in+a+moment", status_code=303)


@app.post("/capture/twitter")
def capture_twitter(tweet_url: str = Form(...), return_to: str = Form("/"), user: dict = Depends(require_user)):
    session = SessionLocal()
    try:
        try:
            cluster = capture_tweet(session, tweet_url)
        except TweetCaptureError as exc:
            session.rollback()
            safe_msg = str(exc).replace(" ", "+")
            return RedirectResponse(f"{return_to}?msg={safe_msg}", status_code=303)
        except Exception:
            # Root cause (found via temporary full-traceback diagnostics,
            # since removed): ANTHROPIC_API_KEY on Render had picked up a
            # stray non-ASCII character from being copy-pasted into the
            # dashboard's web form (vs. written programmatically to local
            # .env, which is always clean) -- httpx crashed encoding it as
            # an HTTP header value, three calls downstream of here in
            # score_story_content. Real fix is config._clean_secret()
            # stripping + validating every secret at load time; this stays
            # as a permanent safety net for any other unexpected failure
            # in the capture path, logged server-side rather than shown to
            # the user, since a user-facing traceback isn't useful to them.
            session.rollback()
            logger.exception("capture_twitter failed unexpectedly")
            return RedirectResponse(f"{return_to}?msg=Capture+failed+--+see+server+logs", status_code=303)
        return RedirectResponse(f"/stories/{cluster.id}?msg=Tweet+captured", status_code=303)
    finally:
        session.close()


@app.get("/stories/{cluster_id}", response_class=HTMLResponse)
def story_detail(cluster_id: int, msg: str | None = None, user: dict = Depends(require_user)):
    session = SessionLocal()
    try:
        cluster = session.get(StoryCluster, cluster_id)
        if not cluster:
            return HTMLResponse("<h1>Not found</h1>", status_code=404)

        links = session.execute(
            select(StoryClusterArticle)
            .where(StoryClusterArticle.cluster_id == cluster_id)
        ).scalars().all()
        article_ids = [link.normalized_article_id for link in links]
        match_level_by_article = {link.normalized_article_id: link.match_level for link in links}

        articles = session.execute(
            select(NormalizedArticle)
            .where(NormalizedArticle.id.in_(article_ids))
            .order_by(NormalizedArticle.detected_at.asc())
        ).scalars().all()

        article_rows = [{
            "id": a.id,
            "headline": a.raw_article.headline if a.raw_article else a.normalized_headline,
            "url": a.canonical_url,
            "source_id": a.source_id,
            "source_name": a.source.name if a.source else "-",
            "source_tier": a.source_tier,
            "published_at": a.published_at.strftime("%Y-%m-%d %H:%M UTC") if a.published_at else None,
            "detected_at": a.detected_at.strftime("%Y-%m-%d %H:%M UTC"),
            "match_level": match_level_by_article.get(a.id, "-"),
        } for a in articles]

        covered_posts = session.execute(
            select(CoveredPost).where(CoveredPost.cluster_id == cluster_id)
            .order_by(CoveredPost.covered_at.desc())
        ).scalars().all()
        covered_post_rows = [{
            "covered_at": cp.covered_at.strftime("%Y-%m-%d %H:%M UTC") if cp.covered_at else "-",
            "platform": cp.platform,
            "post_url": cp.post_url,
            "post_id": cp.post_id,
            "format": cp.format,
            "headline_used": cp.headline_used,
            "editor": cp.editor,
            "notes": cp.notes,
        } for cp in covered_posts]

        cluster_dict = {
            "id": cluster.id,
            "canonical_headline": cluster.canonical_headline,
            "status": cluster.status,
            "verification_status": cluster.verification_status,
            "category": cluster.category,
            "location": cluster.location,
            "viral_score": cluster.viral_score,
            "confidence_score": cluster.confidence_score,
            "momentum_score": cluster.momentum_score,
            "source_count": cluster.source_count,
            "article_count": cluster.article_count,
            "age": _age_str(cluster.first_detected_at),
            "entities": cluster.entities,
            "keywords": cluster.keywords,
            "handoff_sent_at": cluster.handoff_sent_at.strftime("%Y-%m-%d %H:%M UTC") if cluster.handoff_sent_at else None,
            "ai_emotional_strength": cluster.ai_emotional_strength,
            "ai_visual_potential": cluster.ai_visual_potential,
            "ai_conversation_potential": cluster.ai_conversation_potential,
            "ai_novelty": cluster.ai_novelty,
            "ai_scored_at": cluster.ai_scored_at.strftime("%Y-%m-%d %H:%M UTC") if cluster.ai_scored_at else None,
        }

        return HTMLResponse(render_detail_page(cluster_dict, article_rows, flash=msg, covered_posts=covered_post_rows))
    finally:
        session.close()


def mark_covered(session, cluster: StoryCluster, *, platform=None, post_url=None,
                  post_id=None, format_used=None, headline_used=None, editor=None, notes=None) -> CoveredPost:
    """Records one Mark-Covered event. Deliberately additive-only: a cluster
    that's covered, reopens on a new development (see clustering.py's
    Covered -> Developing transition), and gets covered again later ends up
    with two CoveredPost rows, not one overwritten row -- nothing in this
    codebase ever deletes a CoveredPost, so history is safe by construction.
    """
    now = datetime.now(timezone.utc)
    cluster.covered_at = now
    covered_post = CoveredPost(
        cluster_id=cluster.id, covered_at=now,
        platform=platform or None, post_url=post_url or None,
        post_id=post_id or None, format=format_used or None,
        headline_used=headline_used or cluster.canonical_headline,
        editor=editor or None, notes=notes or None,
    )
    session.add(covered_post)
    return covered_post


@app.post("/stories/{cluster_id}/status")
def update_status(
    cluster_id: int,
    user: dict = Depends(require_user),
    new_status: str = Form(...),
    platform: str = Form(""),
    post_url: str = Form(""),
    post_id: str = Form(""),
    format_used: str = Form(""),
    headline_used: str = Form(""),
    editor: str = Form(""),
    notes: str = Form(""),
):
    if new_status not in VALID_STATUSES:
        return RedirectResponse(f"/stories/{cluster_id}?msg=Invalid+status", status_code=303)
    session = SessionLocal()
    try:
        cluster = session.get(StoryCluster, cluster_id)
        if not cluster:
            return HTMLResponse("<h1>Not found</h1>", status_code=404)
        cluster.status = new_status
        if new_status == "Covered":
            mark_covered(
                session, cluster, platform=platform, post_url=post_url, post_id=post_id,
                format_used=format_used, headline_used=headline_used, editor=editor, notes=notes,
            )
        session.commit()
        return RedirectResponse(f"/stories/{cluster_id}?msg=Status+set+to+{new_status}", status_code=303)
    finally:
        session.close()


@app.post("/stories/{cluster_id}/handoff")
def handoff(cluster_id: int, user: dict = Depends(require_user)):
    session = SessionLocal()
    try:
        cluster = session.get(StoryCluster, cluster_id)
        if not cluster:
            return HTMLResponse("<h1>Not found</h1>", status_code=404)

        links = session.execute(
            select(StoryClusterArticle).where(StoryClusterArticle.cluster_id == cluster_id)
        ).scalars().all()
        article_ids = [link.normalized_article_id for link in links]
        articles = session.execute(
            select(NormalizedArticle).where(NormalizedArticle.id.in_(article_ids))
        ).scalars().all()

        write_handoff(cluster, articles)
        cluster.handoff_sent_at = datetime.now(timezone.utc)
        session.commit()
        return RedirectResponse(
            f"/stories/{cluster_id}?msg=Sent+to+First+Signal+Pipeline", status_code=303
        )
    finally:
        session.close()


@app.post("/stories/{cluster_id}/merge")
def merge(cluster_id: int, target_cluster_id: int = Form(...), user: dict = Depends(require_user)):
    session = SessionLocal()
    try:
        try:
            merge_clusters(session, source_cluster_id=cluster_id, target_cluster_id=target_cluster_id)
        except ValueError as exc:
            session.rollback()
            return RedirectResponse(f"/stories/{cluster_id}?msg={exc}", status_code=303)
        session.commit()
        return RedirectResponse(f"/stories/{target_cluster_id}?msg=Merged+into+this+story", status_code=303)
    finally:
        session.close()


@app.post("/stories/{cluster_id}/split")
def split(cluster_id: int, article_ids: list[int] = Form(...), user: dict = Depends(require_user)):
    session = SessionLocal()
    try:
        try:
            new_cluster = split_cluster(session, cluster_id, article_ids)
        except ValueError as exc:
            session.rollback()
            return RedirectResponse(f"/stories/{cluster_id}?msg={exc}", status_code=303)
        session.commit()
        return RedirectResponse(f"/stories/{new_cluster.id}?msg=Split+into+new+story", status_code=303)
    finally:
        session.close()


@app.get("/sources", response_class=HTMLResponse)
def sources_list(user: dict = Depends(require_user)):
    session = SessionLocal()
    try:
        rows = session.execute(select(Source).order_by(Source.polling_tier, Source.name)).scalars().all()
        source_rows = [{
            "id": s.id,
            "name": s.name,
            "type": s.type,
            "category": s.category,
            "credibility_tier": s.credibility_tier,
            "polling_tier": s.polling_tier,
            "enabled": s.enabled,
            "last_fetch_at": s.last_fetch_at.strftime("%Y-%m-%d %H:%M UTC") if s.last_fetch_at else "never",
            "last_error": s.last_error,
        } for s in rows]
        return HTMLResponse(render_sources_page(source_rows))
    finally:
        session.close()


@app.post("/sources")
def add_source(
    user: dict = Depends(require_user),
    name: str = Form(...),
    type_: str = Form(..., alias="type"),
    url_or_query: str = Form(...),
    category: str = Form(""),
    credibility_tier: int = Form(3),
    polling_tier: str = Form("standard"),
):
    session = SessionLocal()
    try:
        if type_ == "google_news":
            from app.collectors.google_news import build_google_news_url
            url = build_google_news_url(url_or_query)
            query = url_or_query
        else:
            url = url_or_query
            query = None

        session.add(Source(
            name=name, type=type_, url=url, query=query,
            category=category or None, credibility_tier=credibility_tier,
            polling_tier=polling_tier, enabled=True,
        ))
        session.commit()
        return RedirectResponse("/sources?msg=Source+added", status_code=303)
    finally:
        session.close()


@app.post("/sources/{source_id}/update")
def update_source(
    source_id: int,
    user: dict = Depends(require_user),
    credibility_tier: int = Form(...),
    polling_tier: str = Form(...),
    category: str = Form(""),
    enabled: bool = Form(False),
):
    session = SessionLocal()
    try:
        source = session.get(Source, source_id)
        if not source:
            return HTMLResponse("<h1>Not found</h1>", status_code=404)
        source.credibility_tier = credibility_tier
        source.polling_tier = polling_tier
        source.category = category or None
        source.enabled = enabled
        session.commit()
        return RedirectResponse("/sources?msg=Source+updated", status_code=303)
    finally:
        session.close()


@app.post("/sources/{source_id}/fetch")
def fetch_source_now(source_id: int, user: dict = Depends(require_user)):
    session = SessionLocal()
    try:
        source = session.get(Source, source_id)
        if not source:
            return HTMLResponse("<h1>Not found</h1>", status_code=404)
        stats = collect_source(session, source)
        if stats["error"]:
            msg = f"Fetch failed: {stats['error']}"
        else:
            msg = f"Fetched {stats['fetched']}, {stats['canonical']} new stories, {stats['duplicates']} duplicates"
        return RedirectResponse(f"/sources?msg={msg}", status_code=303)
    finally:
        session.close()


# ── First Signal Pipeline Queue ───────────────────────────────────────────────

def _run_scoring_background() -> None:
    """Score unscored pending queue items in background — fire and forget."""
    try:
        score_script = _FSN_ROOT / "score_queue_items.py"
        if not score_script.exists():
            return
        batch_env = __import__("os").environ.copy()
        fsn_env = _FSN_ROOT / ".env"
        if fsn_env.exists():
            for _line in fsn_env.read_text(encoding="utf-8").splitlines():
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _, _v = _line.partition("=")
                    batch_env.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
        if not batch_env.get("ANTHROPIC_API_KEY"):
            return
        subprocess.Popen(
            [sys.executable, str(score_script), "--score-all"],
            cwd=str(_FSN_ROOT), env=batch_env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


@app.get("/pipeline-queue", response_class=HTMLResponse)
def pipeline_queue(background_tasks: BackgroundTasks, msg: str = "", user: dict = Depends(require_user)):
    # Sync any new handoff files written since last page load
    handoff_sync = _FSN_ROOT / "handoff_queue.py"
    if handoff_sync.exists():
        subprocess.run([sys.executable, str(handoff_sync)], capture_output=True, cwd=str(_FSN_ROOT))
    # Score unscored pending items in background (non-blocking)
    background_tasks.add_task(_run_scoring_background)

    items  = _load_fsn_queue()
    job    = _read_job()
    picks  = _read_picks()
    posts  = (picks or {}).get("posts") or []

    # Load any fresh batch recommendation
    try:
        import importlib.util as _ilu, sys as _sys
        _spec = _ilu.spec_from_file_location("recommend_batch", str(_FSN_ROOT / "recommend_batch.py"))
        _mod  = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        recommendation = _mod.load_recommendation()
    except Exception:
        recommendation = None

    return render_pipeline_queue_page(
        items, msg=msg,
        job=job,
        picks_ready=bool(posts),
        picks_count=len(posts),
        picks_date=(picks or {}).get("batch_date", ""),
        recommendation=recommendation,
    )


@app.post("/pipeline-queue/generate")
async def pipeline_queue_generate(request: Request, user: dict = Depends(require_user)):
    form = await request.form()
    action = form.get("action", "generate")
    selected_ids = [int(v) for v in form.getlist("selected") if v.isdigit()]

    if not selected_ids:
        return RedirectResponse("/pipeline-queue?msg=No+stories+selected", status_code=303)

    items = _load_fsn_queue()
    now = datetime.now(timezone.utc).isoformat()
    updated = 0

    for item in items:
        cid = item.get("cluster_id")
        if cid not in selected_ids:
            continue
        if action == "generate":
            item["queue_status"] = "approved"
            item["approved_at"] = now
            # Read the per-row type the operator chose
            type_key = f"type_{cid}"
            chosen_type = form.get(type_key, "image_card")
            item["generation_type"] = chosen_type if chosen_type in ("image_card", "tobi") else "image_card"
            # Flag items that have no FSN draft so the operator knows to draft them
            has_draft = bool((item.get("draft") or {}).get("headline"))
            item["needs_draft"] = not has_draft
        elif action == "remove":
            item["queue_status"] = "skipped"
        updated += 1

    _save_fsn_queue(items)

    if action == "generate" and updated:
        # Write approved_picks.json NOW so run-batch always has fresh content
        picks = _build_picks_from_approved_queue()
        msg = f"{updated} story(s) ready — click Generate Images Now"
    elif action == "generate":
        msg = "No stories selected"
    else:
        msg = f"{updated} story(s) removed"
    return RedirectResponse(f"/pipeline-queue?msg={msg.replace(' ', '+')}", status_code=303)


@app.post("/pipeline-queue/recall")
def pipeline_queue_recall(user: dict = Depends(require_user)):
    """Move all approved items back to pending."""
    items = _load_fsn_queue()
    for item in items:
        if item.get("queue_status") == "approved":
            item["queue_status"] = "pending"
            item.pop("approved_at", None)
            item.pop("generation_type", None)
    _save_fsn_queue(items)
    return RedirectResponse("/pipeline-queue?msg=Moved+back+to+pending", status_code=303)


@app.post("/pipeline-queue/score-queue")
def pipeline_queue_score_queue(user: dict = Depends(require_user)):
    """Trigger immediate AI scoring of all unscored pending items."""
    script = _FSN_ROOT / "score_queue_items.py"
    if not script.exists():
        return RedirectResponse("/pipeline-queue?msg=score_queue_items.py+not+found", status_code=303)
    batch_env = __import__("os").environ.copy()
    fsn_env = _FSN_ROOT / ".env"
    if fsn_env.exists():
        for _line in fsn_env.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                batch_env.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
    result = subprocess.run(
        [sys.executable, str(script), "--score-all"],
        cwd=str(_FSN_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, env=batch_env,
    )
    lines = (result.stdout + result.stderr).strip().splitlines()
    summary = lines[-1] if lines else "Scoring complete"
    return RedirectResponse(f"/pipeline-queue?msg={summary.replace(' ', '+')}", status_code=303)


@app.post("/pipeline-queue/recommend-batch")
def pipeline_queue_recommend_batch(user: dict = Depends(require_user)):
    """Run AI batch recommendation and save to memory/batch_recommendation.json."""
    script = _FSN_ROOT / "recommend_batch.py"
    if not script.exists():
        return RedirectResponse("/pipeline-queue?msg=recommend_batch.py+not+found", status_code=303)
    batch_env = __import__("os").environ.copy()
    fsn_env = _FSN_ROOT / ".env"
    if fsn_env.exists():
        for _line in fsn_env.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                batch_env.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
    if not batch_env.get("ANTHROPIC_API_KEY"):
        return RedirectResponse(
            "/pipeline-queue?msg=ANTHROPIC_API_KEY+not+set+in+.env", status_code=303)
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(_FSN_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, env=batch_env,
    )
    lines = (result.stdout + result.stderr).strip().splitlines()
    summary = next((l for l in reversed(lines) if "recommend" in l.lower()), "Recommendation ready")
    return RedirectResponse(f"/pipeline-queue?msg={summary.replace(' ', '+')}", status_code=303)


@app.post("/pipeline-queue/draft-queue")
def pipeline_queue_draft_queue(user: dict = Depends(require_user)):
    """Run draft_queue_content.py --draft-queue to auto-draft all needs_draft items via Claude API."""
    script = _FSN_ROOT / "draft_queue_content.py"
    if not script.exists():
        return RedirectResponse("/pipeline-queue?msg=draft_queue_content.py+not+found", status_code=303)

    batch_env = __import__("os").environ.copy()
    fsn_env = _FSN_ROOT / ".env"
    if fsn_env.exists():
        for _line in fsn_env.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                batch_env.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

    if not batch_env.get("ANTHROPIC_API_KEY"):
        return RedirectResponse(
            "/pipeline-queue?msg=ANTHROPIC_API_KEY+not+set+in+.env+—+type+'draft+the+queue'+in+Claude+Code+chat+instead",
            status_code=303
        )

    result = subprocess.run(
        [sys.executable, str(script), "--draft-queue"],
        cwd=str(_FSN_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120, env=batch_env
    )
    lines = (result.stdout + result.stderr).strip().splitlines()
    # Rebuild picks with new drafts
    _build_picks_from_approved_queue()
    summary = lines[-1] if lines else "Done"
    return RedirectResponse(f"/pipeline-queue?msg={summary.replace(' ', '+')}", status_code=303)


@app.post("/pipeline-queue/full-batch")
def pipeline_queue_full_batch(user: dict = Depends(require_user)):
    """Auto-select top 12 pending stories as image cards + top 5 as TOBI, mark approved+needs_draft."""
    items = _load_fsn_queue()
    pending = [x for x in items if x.get("queue_status") == "pending"]
    # Sort: items with drafts first (ready to go), then by viral_score desc
    pending.sort(key=lambda x: (
        -int(bool((x.get("draft") or {}).get("headline"))),
        -(x.get("viral_score") or 0)
    ))

    n_images = 12
    n_tobi   = 5
    now = datetime.now(timezone.utc).isoformat()

    image_picks = pending[:n_images]
    tobi_picks  = pending[n_images:n_images + n_tobi]

    approved_count = 0
    for item in items:
        cid = item.get("cluster_id")
        if any(p.get("cluster_id") == cid for p in image_picks):
            item["queue_status"]   = "approved"
            item["approved_at"]    = now
            item["generation_type"] = "image_card"
            has_draft = bool((item.get("draft") or {}).get("headline"))
            item["needs_draft"] = not has_draft
            approved_count += 1
        elif any(p.get("cluster_id") == cid for p in tobi_picks):
            item["queue_status"]   = "approved"
            item["approved_at"]    = now
            item["generation_type"] = "tobi"
            has_draft = bool((item.get("draft") or {}).get("headline"))
            item["needs_draft"] = not has_draft
            approved_count += 1

    _save_fsn_queue(items)
    _build_picks_from_approved_queue()

    needs_draft = sum(1 for x in items if x.get("queue_status") == "approved" and x.get("needs_draft"))
    if needs_draft:
        msg = f"{approved_count}+stories+queued+({needs_draft}+need+drafts+—+type+'draft+the+queue'+in+chat)"
    else:
        msg = f"{approved_count}+stories+ready+—+click+Generate+Images+Now"
    return RedirectResponse(f"/pipeline-queue?msg={msg}", status_code=303)


@app.get("/pipeline-queue/batch-status")
def pipeline_queue_batch_status(user: dict = Depends(require_user)):
    """Polling endpoint: returns current job state + whether approved_picks.json is ready."""
    job   = _read_job()
    picks = _read_picks()
    posts = (picks or {}).get("posts") or []
    return JSONResponse({
        "job": job,
        "picks_ready": bool(posts),
        "picks_count": len(posts),
        "picks_date":  (picks or {}).get("batch_date", ""),
    })


@app.post("/pipeline-queue/run-batch")
def pipeline_queue_run_batch(background_tasks: BackgroundTasks, user: dict = Depends(require_user)):
    """Fire the full generation pipeline as a background task."""
    with _batch_lock:
        if _read_job().get("status") == "running":
            return RedirectResponse("/pipeline-queue?msg=Generation+already+running", status_code=303)

    picks = _read_picks()
    if not picks or not (picks.get("posts") or []):
        return RedirectResponse(
            "/pipeline-queue?msg=No+stories+approved.+Select+stories+and+click+Send+to+Generation+first.",
            status_code=303,
        )

    date_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    batch_dir = str(_FSN_ROOT / "output" / f"{date_str}-queue")
    background_tasks.add_task(_run_batch_background, picks, batch_dir)
    return RedirectResponse("/pipeline-queue?msg=Generation+started", status_code=303)


@app.post("/pipeline-queue/clear-job")
def pipeline_queue_clear_job(user: dict = Depends(require_user)):
    """Reset a finished/errored job so the status panel goes back to idle."""
    _write_job({"status": "idle"})
    return RedirectResponse("/pipeline-queue", status_code=303)


def _fetch_article_text(url: str) -> tuple[str, str]:
    """Fetch URL, return (title, body_text). Returns ('', '') on failure."""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        # Extract title
        import re
        title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
        title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""
        # Strip scripts/styles then all tags
        body = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", raw, flags=re.I | re.S)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"\s{3,}", "\n\n", body).strip()
        return title, body[:8000]
    except Exception:
        return "", ""


@app.get("/pipeline-queue/preview-url")
def pipeline_queue_preview_url(url: str = "", user: dict = Depends(require_user)):
    """Fetch a source URL and return title + first ~400 chars of body text."""
    if not url:
        return JSONResponse({"error": "no url"}, status_code=400)
    # Basic sanity — must be http/https
    if not url.startswith(("http://", "https://")):
        return JSONResponse({"error": "invalid url"}, status_code=400)
    title, body = _fetch_article_text(url)
    if not title and not body:
        return JSONResponse({"error": "Could not fetch the article. The site may block scrapers."}, status_code=200)
    # Return first paragraph-ish chunk — stop at first double newline or 400 chars
    first_para = body[:600]
    nl = first_para.find("\n\n")
    if nl > 60:
        first_para = first_para[:nl]
    first_para = first_para[:400].strip()
    return JSONResponse({"title": title, "snippet": first_para, "url": url})


@app.post("/pipeline-queue/add-article")
async def pipeline_queue_add_article(request: Request, user: dict = Depends(require_user)):
    """Manually add an article (URL and/or pasted text) to the production queue."""
    form = await request.form()
    url        = (form.get("article_url") or "").strip()
    paste_text = (form.get("article_text") or "").strip()

    if not url and not paste_text:
        return RedirectResponse(
            "/pipeline-queue?msg=Please+paste+article+text+or+provide+a+URL",
            status_code=303,
        )

    # Try to get a title from the URL if no text was pasted
    fetched_title = ""
    if url and not paste_text:
        fetched_title, _ = _fetch_article_text(url)

    # Use first non-empty line of pasted text as the working headline
    raw_headline = ""
    if paste_text:
        for line in paste_text.splitlines():
            line = line.strip()
            if line:
                raw_headline = line[:120]
                break
    if not raw_headline:
        raw_headline = fetched_title or url or "Untitled article"

    now    = datetime.now(timezone.utc).isoformat()
    new_id = int(datetime.now(timezone.utc).timestamp() * 1000)

    entry = {
        "cluster_id":          new_id,
        "text":                raw_headline,
        "category":            "manual",
        "viral_score":         0,
        "source_count":        1,
        "verification_status": "manual_add",
        "queue_status":        "pending",
        "added_to_queue_at":   now,
        "source_url":          url,
        "suggested_template":  "A",
        "suggested_scene":     "",
        "generation_type":     "image_card",
        "draft":               {"headline": "", "tag": "JUST IN", "captions": {}, "first_comment": ""},
        "manual":              True,
        "raw_text":            paste_text or "",
        "needs_draft":         True,
    }

    items = _load_fsn_queue()
    items.append(entry)
    _save_fsn_queue(items)

    msg = "Article added. Paste it in your Claude Code chat to generate the FSN draft, then send to generation."
    return RedirectResponse(
        f"/pipeline-queue?msg={msg.replace(' ', '+')}",
        status_code=303,
    )


@app.get("/pipeline-queue/output-json")
def pipeline_queue_output_json(user: dict = Depends(require_user)):
    """Return batch_summary.json for the last completed job."""
    job = _read_job()
    batch_dir = job.get("batch_dir")
    if not batch_dir:
        return JSONResponse({"error": "no job"}, status_code=404)
    summary_path = Path(batch_dir) / "batch_summary.json"
    if not summary_path.exists():
        return JSONResponse({"error": "batch_summary.json not found"}, status_code=404)
    try:
        return JSONResponse(json.loads(summary_path.read_text(encoding="utf-8")))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/pipeline-queue/critique-batch")
async def pipeline_queue_critique_batch(user: dict = Depends(require_user)):
    """Claude reviews the full approved batch plan before generation fires."""
    import os, sys as _sys
    key = None
    env_path = _FSN_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not set"}, status_code=400)

    picks_path = _FSN_PICKS_PATH
    if not picks_path.exists():
        return JSONResponse({"error": "No approved batch — send stories to generation first"}, status_code=400)

    picks = json.loads(picks_path.read_text(encoding="utf-8"))
    posts = picks.get("posts", [])
    if not posts:
        return JSONResponse({"error": "Approved batch is empty"}, status_code=400)

    batch_summary = [
        {
            "idx": i + 1,
            "type": p.get("template", "image_card"),
            "headline": (p.get("text") or "")[:120],
            "tag": p.get("_tag") or "",
            "scene": (p.get("scene") or p.get("suggested_scene") or "auto")[:80],
            "caption_short": ((p.get("captions") or {}).get("short") or "")[:80],
        }
        for i, p in enumerate(posts)
    ]

    system = """\
You are reviewing a First Signal News Facebook batch before it goes to paid image generation.
Check for these problems and output ONLY valid JSON:
{
  "issues": [
    {"severity": "high"|"medium"|"low", "type": "topic_overlap"|"framing_repeat"|"weak_tobi"|"portrait_overload"|"voice_fail"|"other", "description": "specific issue with card numbers"},
    ...
  ],
  "portrait_count": N,
  "topic_variety": "good"|"ok"|"poor",
  "overall": "APPROVE"|"REVIEW_FIRST",
  "summary": "one sentence overall assessment"
}
If no issues: "issues": [], "overall": "APPROVE".
Portrait cards are cards where scene contains "likeness" or "portrait". Cap is 2."""

    user_msg = f"Review this {len(batch_summary)}-post batch:\n{json.dumps(batch_summary, indent=2)}"

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        # Cache critique alongside the picks
        critique_path = _FSN_ROOT / "memory" / "batch_critique.json"
        from datetime import datetime, timezone
        result["generated_at"] = datetime.now(timezone.utc).isoformat()
        critique_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/pipeline-queue/rewrite-caption")
async def pipeline_queue_rewrite_caption(request: Request, user: dict = Depends(require_user)):
    """Rewrite one caption variant for an approved queue item."""
    form = await request.form()
    cluster_id = int(form.get("cluster_id", 0))
    variant    = (form.get("variant") or "short").strip()

    key = None
    env_path = _FSN_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not set"}, status_code=400)

    items = _load_fsn_queue()
    item = next((x for x in items if x.get("cluster_id") == cluster_id), None)
    if not item:
        return JSONResponse({"error": "Item not found"}, status_code=404)

    draft    = item.get("draft") or {}
    headline = draft.get("headline") or item.get("text") or ""
    captions = draft.get("captions") or {}

    bands = {"short": "10-15", "medium": "40-60", "long": "100-150", "extra_long": "200-300"}
    band  = bands.get(variant, "40-60")

    system = (
        "You are the First Signal News caption writer. America First conservative voice. "
        "No em-dashes, no hashtags, no emojis. Output ONLY the rewritten caption text — no explanation, no quotes around it."
    )
    user_msg = (
        f"Headline: {headline}\n"
        f"Current {variant} caption: {captions.get(variant, '')}\n\n"
        f"Rewrite the {variant} caption. Word band: {band} words. "
        f"Short captions must end with an agreement hook (Do you agree? / Right? / Yes or No?). "
        "Make it sharper and more scroll-stopping. Return ONLY the new caption text."
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        new_text = resp.content[0].text.strip().strip('"').strip("'")
        # Save back to queue
        if "captions" not in (item.get("draft") or {}):
            item.setdefault("draft", {})["captions"] = {}
        item["draft"]["captions"][variant] = new_text
        _save_fsn_queue(items)
        return JSONResponse({"ok": True, "variant": variant, "text": new_text})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/pipeline-queue/expand-angles")
async def pipeline_queue_expand_angles(request: Request, user: dict = Depends(require_user)):
    """Suggest 3 FSN story angles for a pending item before drafting."""
    form = await request.form()
    cluster_id = int(form.get("cluster_id", 0))

    key = None
    env_path = _FSN_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not set"}, status_code=400)

    items = _load_fsn_queue()
    item = next((x for x in items if x.get("cluster_id") == cluster_id), None)
    if not item:
        return JSONResponse({"error": "Item not found"}, status_code=404)

    headline = item.get("text") or ""
    sources  = item.get("sources") or []
    source_lines = "\n".join(f"  - {s.get('source_name','')}: {s.get('headline','')}" for s in sources[:3]) or "  (no sources)"

    system = """\
You are a First Signal News content strategist. Given a story, suggest 3 distinct content angles.
Output ONLY valid JSON:
{
  "angles": [
    {
      "angle_type": "accountability"|"vindication"|"breaking"|"outrage"|"poll"|"analysis",
      "hook": "the 8-16 word headline this angle would produce",
      "caption_lead": "the first sentence of the short caption for this angle",
      "tag": "EXACTLY 3 UPPERCASE WORDS for the red pill",
      "why": "one sentence — why this angle works for FSN audience"
    },
    ... exactly 3 angles ...
  ]
}
Each angle must be meaningfully different in framing. No em-dashes."""

    user_msg = f"Story: {headline}\nSources:\n{source_lines}\n\nSuggest 3 FSN angles."

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/pipeline-queue/history-image")
def pipeline_queue_history_image(path: str = "", user: dict = Depends(require_user)):
    """Serve any PNG from FSN output/ by absolute path (history viewer)."""
    if not path:
        return Response(status_code=400)
    safe_root = (_FSN_ROOT / "output").resolve()
    try:
        resolved = Path(path).resolve()
        resolved.relative_to(safe_root)
    except (ValueError, OSError):
        return Response(status_code=403)
    if not resolved.exists() or resolved.suffix.lower() != ".png":
        return Response(status_code=404)
    return Response(content=resolved.read_bytes(), media_type="image/png",
                    headers={"Cache-Control": "max-age=86400"})


@app.get("/pipeline-queue/output-image/{filename}")
def pipeline_queue_output_image(filename: str, user: dict = Depends(require_user)):
    """Serve a PNG card from the last completed job's batch dir."""
    job = _read_job()
    batch_dir = job.get("batch_dir")
    if not batch_dir:
        return Response(status_code=404)
    # Security: path must stay inside FSN_ROOT/output/
    safe_root = (_FSN_ROOT / "output").resolve()
    path = (Path(batch_dir) / filename).resolve()
    try:
        path.relative_to(safe_root)
    except ValueError:
        return Response(status_code=403)
    if not path.exists() or not path.suffix.lower() == ".png":
        return Response(status_code=404)
    return Response(content=path.read_bytes(), media_type="image/png")
