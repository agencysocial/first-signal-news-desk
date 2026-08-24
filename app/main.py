import json
import logging
import os
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, text as _sql_text
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
    render_story_workspace_page, render_fb_scanner_page,
)
from app import fb_scanner as _fb

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

# ── Kie.ai cloud image generation ─────────────────────────────────────────────
_KIE_CREATE = "https://api.kie.ai/api/v1/jobs/createTask"
_KIE_RECORD = "https://api.kie.ai/api/v1/jobs/recordInfo"
_KIE_MODEL  = "gpt-image-2-image-to-image"
_KIE_POLL_INTERVAL = 5
_KIE_POLL_TIMEOUT  = 600  # 10 min

_ANTI_SLOP = (
    "Candid Associated Press / Reuters wire-service photograph (NOT a cinematic poster, "
    "NOT stylized, NOT stock). Shot on a Canon EOS R5 with a 35-50mm prime lens at f/2.8-f/4, "
    "ISO 400-1600, raw documentary photojournalism style. Subject expression is ORDINARY and "
    "unposed. NO dramatic rim-light, NO cinematic grade. The image must look like it was pulled "
    "from a real newspaper, NOT generated."
)


def _get_kie_key() -> str | None:
    key = __import__("os").environ.get("KIE_AI_API_KEY", "").strip()
    if key and not key.startswith("YOUR_"):
        return key
    env_path = _FSN_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("KIE_AI_API_KEY="):
                v = line.split("=", 1)[1].strip()
                if v and not v.startswith("YOUR_"):
                    return v
    return None


def _build_image_prompt(headline: str, tag: str, scene: str, notes: str = "") -> str:
    notes_clause = f" Additional direction: {notes}." if notes else ""
    return (
        f"A 4:5 vertical portrait breaking-news share card with TWO ZONES — strictly no overlap between them.\n\n"
        f"ZONE 1 — UPPER TWO-THIRDS (photo area): {scene}.{notes_clause} {_ANTI_SLOP}\n\n"
        f"ZONE 2 — LOWER ONE-THIRD (footer panel): A SOLID FLAT PURE BLACK rectangle spanning the full width "
        f"at the bottom of the card. This panel must be completely opaque black with ZERO transparency, "
        f"ZERO gradient, ZERO bleed from the photo above. Inside this black panel:\n"
        f"  - TOP OF FOOTER: a small solid bright red rounded rectangle pill containing the text "
        f"\"{tag}\" in bold white uppercase letters. The red is vivid fire-engine red — NOT orange, NOT dark red.\n"
        f"  - BELOW THE TAG: the headline text \"{headline}\" in BOLD BRIGHT GOLDEN YELLOW uppercase "
        f"Montserrat-style sans-serif. The yellow is bright warm golden yellow — consistent, NOT pale, "
        f"NOT lime, NOT orange. Left-aligned, large enough to read at a glance, wrapped over 2 to 4 lines.\n"
        f"\n"
        f"RULES: Flat 2D text only — no drop shadows, no outer glows, no gradients on text. "
        f"No logos, no URLs, no social handles. Photo fills only the upper two-thirds. "
        f"4:5 vertical portrait format, photorealistic, sharp, magazine-quality."
    )


def _stamp_logo(image_bytes: bytes, cid: str) -> Path:
    """Download image bytes, stamp the FSN logo at top-left, save to /tmp. Returns path."""
    from PIL import Image as _PILImage
    import io as _io

    LOGO_FIXED_WIDTH = 200
    MARGIN = 20
    BRIGHTNESS_THRESHOLD = 140

    static_dir = Path(__file__).resolve().parent / "static"
    logo_white = static_dir / "logo_white_text.png"
    logo_black = static_dir / "logo_black_text.png"

    card = _PILImage.open(_io.BytesIO(image_bytes)).convert("RGBA")
    w, h = card.size

    # Sample top-left region to decide which logo variant
    region_w = min(300, w // 3)
    region_h = min(120, h // 6)
    region = card.crop((0, 0, region_w, region_h)).convert("RGB")
    pixels = list(region.getdata())
    avg_brightness = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in pixels) / max(len(pixels), 1)
    logo_path = logo_black if avg_brightness > BRIGHTNESS_THRESHOLD else logo_white

    logo = _PILImage.open(logo_path).convert("RGBA")
    ratio = LOGO_FIXED_WIDTH / logo.width
    logo_h = int(logo.height * ratio)
    logo = logo.resize((LOGO_FIXED_WIDTH, logo_h), _PILImage.LANCZOS)

    card.paste(logo, (MARGIN, MARGIN), logo)

    out = _PILImage.new("RGB", card.size, (0, 0, 0))
    out.paste(card, mask=card.split()[3])

    tmp_dir = Path("/tmp/fsn_images")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / f"{cid}.jpg"
    out.save(str(out_path), "JPEG", quality=88, optimize=True)
    return out_path


def _kie_submit(prompt: str, key: str) -> str:
    body = {"model": _KIE_MODEL, "input": {"prompt": prompt, "aspect_ratio": "4:5", "resolution": "1K"}}
    r = httpx.post(_KIE_CREATE, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                   json=body, timeout=60)
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != 200:
        raise RuntimeError(f"Kie createTask: code={payload.get('code')} msg={payload.get('msg')}")
    task_id = (payload.get("data") or {}).get("taskId")
    if not task_id:
        raise RuntimeError(f"Kie createTask: no taskId in {payload}")
    return task_id


def _kie_poll(task_id: str, key: str) -> str:
    deadline = time.time() + _KIE_POLL_TIMEOUT
    while time.time() < deadline:
        r = httpx.get(f"{_KIE_RECORD}?taskId={task_id}",
                      headers={"Authorization": f"Bearer {key}"}, timeout=30)
        r.raise_for_status()
        data = (r.json().get("data") or {})
        state = data.get("state")
        if state == "success":
            raw = data.get("resultJson")
            parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
            urls = parsed.get("resultUrls") or []
            if not urls:
                raise RuntimeError("Kie: success but no resultUrls")
            return urls[0]
        if state == "fail":
            raise RuntimeError(f"Kie task failed: {data.get('failMsg')}")
        time.sleep(_KIE_POLL_INTERVAL)
    raise TimeoutError(f"Kie task {task_id} timed out after {_KIE_POLL_TIMEOUT}s")

def _is_local() -> bool:
    """True when running on the local Windows machine (FSN pipeline exists)."""
    return _FSN_ROOT.exists()

def _get_anthropic_key() -> str | None:
    """Return ANTHROPIC_API_KEY from env var (Render) or local .env files."""
    import os as _os
    key = _os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    # Check AIM repo .env first, then FSN pipeline .env
    for env_path in [
        Path(__file__).parent.parent / ".env",
        _FSN_ROOT / ".env",
    ]:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY="):
                    val = line.split("=", 1)[1].strip()
                    if val:
                        return val
    return None

def _load_fsn_queue() -> list[dict]:
    if _FSN_QUEUE_PATH.exists():
        try:
            return json.loads(_FSN_QUEUE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    # Running on deployed server — build queue from DB.
    session = SessionLocal()
    try:
        clusters = session.execute(
            select(StoryCluster).where(StoryCluster.handoff_sent_at.is_not(None))
            .order_by(StoryCluster.handoff_sent_at.desc())
            .limit(200)
        ).scalars().all()
        cluster_ids = [c.id for c in clusters]
        url_map: dict[int, str] = {}
        if cluster_ids:
            rows = session.execute(
                select(StoryClusterArticle.cluster_id, NormalizedArticle.canonical_url)
                .join(NormalizedArticle, NormalizedArticle.id == StoryClusterArticle.normalized_article_id)
                .where(StoryClusterArticle.cluster_id.in_(cluster_ids))
            ).all()
            for cluster_id, url in rows:
                if cluster_id not in url_map and url:
                    url_map[cluster_id] = url

        items = []
        for c in clusters:
            url = url_map.get(c.id, "")
            # Merge persisted FSN production state from DB
            fsn = {}
            if c.fsn_state:
                try:
                    fsn = json.loads(c.fsn_state)
                except Exception:
                    pass
            item = {
                "cluster_id": c.id,
                "text": c.canonical_headline or "",
                "category": c.category or "general",
                "viral_score": round(float(c.viral_score or 0), 1),
                "confidence_score": round(float(c.confidence_score or 0), 1),
                "entities": json.loads(c.entities or "[]"),
                "keywords": json.loads(c.keywords or "[]"),
                "verification_status": c.verification_status or "unverified",
                "ai_emotional_strength":     c.ai_emotional_strength,
                "ai_visual_potential":       c.ai_visual_potential,
                "ai_conversation_potential": c.ai_conversation_potential,
                "ai_novelty":                c.ai_novelty,
                "ai_topic_relevance":        c.ai_topic_relevance,
                "queue_status": fsn.get("queue_status", "pending"),
                "post_type": fsn.get("post_type", "image_card"),
                "approved_at": fsn.get("approved_at", ""),
                "added_to_queue_at": c.handoff_sent_at.isoformat() if c.handoff_sent_at else "",
                "post_url": url,
                "sources": [{"url": url}] if url else [],
                "draft": fsn.get("draft"),
                "tobi_text": fsn.get("tobi_text") or (fsn.get("draft") or {}).get("tobi_text"),
                "generated_image_url": fsn.get("generated_image_url"),
                "image_gen_status": fsn.get("image_gen_status", ""),
                "video_titles":        fsn.get("video_titles", []),
                "reels_description":   fsn.get("reels_description", ""),
                "script_short":        fsn.get("script_short", ""),
                "script_medium":       fsn.get("script_medium", ""),
                "script_long":         fsn.get("script_long", ""),
                "poll_question":       fsn.get("poll_question", ""),
                "video_first_comment": fsn.get("video_first_comment", ""),
                "_source": "newsdesk_handoff",
            }
            items.append(item)
        return items
    finally:
        session.close()


_FSN_STATE_KEYS = {"queue_status", "post_type", "draft", "approved_at",
                   "generated_image_url", "image_gen_status", "image_history", "tobi_text", "output_file",
                   "video_titles", "reels_description", "script_short", "script_medium",
                   "script_long", "poll_question", "video_first_comment"}


def _save_fsn_queue(items: list[dict]) -> None:
    if _is_local():
        _FSN_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _FSN_QUEUE_PATH.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        return
    # On Render: persist FSN state to DB so changes survive redeploys.
    session = SessionLocal()
    try:
        for item in items:
            cid = item.get("cluster_id")
            if not cid:
                continue
            fsn = {k: item[k] for k in _FSN_STATE_KEYS if k in item}
            c = session.get(StoryCluster, int(cid))
            if c:
                c.fsn_state = json.dumps(fsn, ensure_ascii=False)
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def _queue_item_for(cluster_id: int) -> dict | None:
    """Return the queue dict for a cluster_id, falling back to DB when not in the local file.
    Always returns a dict with at least 'cluster_id' and 'text' so callers don't need to
    branch on local vs Render — they just check for None on total miss."""
    items = _load_fsn_queue()
    item = next((x for x in items if x.get("cluster_id") == cluster_id), None)
    if item:
        return item
    # Render path: queue lives in DB
    session = SessionLocal()
    try:
        c = session.get(StoryCluster, cluster_id)
        if not c:
            return None
        fsn: dict = {}
        if c.fsn_state:
            try:
                fsn = json.loads(c.fsn_state)
            except Exception:
                pass
        return {
            "cluster_id": cluster_id,
            "text": c.canonical_headline or "",
            "sources": fsn.get("sources") or ([{
                "source_name": fsn.get("source_page", ""),
                "headline":    c.canonical_headline or "",
                "url":         fsn.get("source_url", ""),
            }] if fsn.get("source_page") else []),
            "draft":    fsn.get("draft") or {},
            "category": c.category or "Politics",
            **fsn,
        }
    finally:
        session.close()


def _resolve_queue_item(cluster_id: int) -> tuple[list, dict | None]:
    """Load file queue and find item; if missing, fall back to DB and append to list.
    Returns (items, item) so callers can pass items to _save_fsn_queue after mutating item."""
    items = _load_fsn_queue()
    item = next((x for x in items if x.get("cluster_id") == cluster_id), None)
    if item is None:
        item = _queue_item_for(cluster_id)
        if item is not None:
            items.append(item)
    return items, item


def _update_cluster_fsn(cid: int | str, **kwargs) -> None:
    """Patch specific FSN state fields for one cluster directly in DB. Fast, no full queue load."""
    session = SessionLocal()
    try:
        c = session.get(StoryCluster, int(cid))
        if c:
            fsn: dict = {}
            if c.fsn_state:
                try:
                    fsn = json.loads(c.fsn_state)
                except Exception:
                    pass
            fsn.update(kwargs)
            c.fsn_state = json.dumps(fsn, ensure_ascii=False)
            session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("_update_cluster_fsn %s: %s", cid, exc)
    finally:
        session.close()

# ── Brand property helpers ────────────────────────────────────────────────────

_FSN_BRAND_COLORS = json.dumps({
    "color_footer":     "#000000",
    "color_headline":   "#FFDE59",
    "color_tag_bg":     "#D02020",
    "color_tag_text":   "#FFFFFF",
    "color_text":       "#FFFFFF",
})
_FSN_IMAGE_SETTINGS = json.dumps({
    "aspect_ratio":       "4:5",
    "resolution":         "1K",
    "output_format":      "png",
    "watermark_text":     "",
    "watermark_position": "bottom_center",
})
_FSN_VOICE = (
    "America First conservative news voice with a hard accuracy floor. "
    "Tell the REAL story from the source: keep verifiable facts (real names, real dates, real quotes). "
    "Rewrite the wording — NEVER fabricate a quote, position, event, charge, or statistic about any real person. "
    "Partisan and pointed: take a clear America First side, name the subject specifically. "
    "End captions with an agreement hook (Do you agree? / Right? / Yes or No? / Be honest:). "
    "No em-dashes."
)
_FSN_CAPTION_SETTINGS = json.dumps({
    "short":        [10, 15],
    "medium":       [40, 60],
    "long":         [100, 150],
    "extra_long":   [200, 300],
    "first_comment":[25, 45],
    "agreement_hook": True,
    "hashtags":     False,
    "emojis":       False,
})

_CATHYTALK_BRAND_COLORS = json.dumps({
    "color_footer":     "#1a1a2e",
    "color_headline":   "#FFFFFF",
    "color_tag_bg":     "#e94560",
    "color_tag_text":   "#FFFFFF",
    "color_text":       "#FFFFFF",
})
_CATHYTALK_IMAGE_SETTINGS = json.dumps({
    "aspect_ratio":       "4:5",
    "resolution":         "1K",
    "output_format":      "png",
    "watermark_text":     "",
    "watermark_position": "bottom_center",
})
_CATHYTALK_VOICE = (
    "Warm, conversational women's lifestyle and culture voice. "
    "Tone: relatable, encouraging, direct. Write like a smart friend sharing important news. "
    "Focus on how the story affects everyday women and families. "
    "End captions with an engaging question that invites personal responses. "
    "No partisan framing. No em-dashes."
)
_CATHYTALK_CAPTION_SETTINGS = json.dumps({
    "short":        [10, 15],
    "medium":       [40, 60],
    "long":         [100, 150],
    "extra_long":   [200, 300],
    "first_comment":[25, 45],
    "agreement_hook": False,
    "hashtags":     False,
    "emojis":       False,
})


def _seed_default_brands() -> None:
    """Insert First Signal News and CathyTalk if brand_properties table is empty."""
    from app.models import BrandProperty as _BP
    session = SessionLocal()
    try:
        if session.execute(select(func.count()).select_from(_BP)).scalar() > 0:
            return
        session.add(_BP(
            slug="first_signal", name="First Signal News", enabled=True, sort_order=0,
            colors=_FSN_BRAND_COLORS, image_settings=_FSN_IMAGE_SETTINGS,
            voice_instructions=_FSN_VOICE, caption_settings=_FSN_CAPTION_SETTINGS,
            logo_url="", notes="America First / conservative news page.",
        ))
        session.add(_BP(
            slug="cathy_talk", name="CathyTalk", enabled=True, sort_order=1,
            colors=_CATHYTALK_BRAND_COLORS, image_settings=_CATHYTALK_IMAGE_SETTINGS,
            voice_instructions=_CATHYTALK_VOICE, caption_settings=_CATHYTALK_CAPTION_SETTINGS,
            logo_url="", notes="Women's lifestyle and culture media property.",
        ))
        session.commit()
        logger.info("Seeded default brand properties.")
    except Exception as exc:
        session.rollback()
        logger.warning("Brand seed failed: %s", exc)
    finally:
        session.close()


def _get_all_brands() -> list[dict]:
    from app.models import BrandProperty as _BP
    session = SessionLocal()
    try:
        rows = session.execute(select(_BP).order_by(_BP.sort_order, _BP.id)).scalars().all()
        return [_brand_to_dict(b) for b in rows]
    finally:
        session.close()


def _get_brand(slug: str) -> dict | None:
    from app.models import BrandProperty as _BP
    session = SessionLocal()
    try:
        b = session.execute(select(_BP).where(_BP.slug == slug)).scalar_one_or_none()
        return _brand_to_dict(b) if b else None
    finally:
        session.close()


def _brand_to_dict(b) -> dict:
    def _j(v):
        try: return json.loads(v) if v else {}
        except: return {}
    return {
        "id": b.id, "slug": b.slug, "name": b.name, "enabled": b.enabled,
        "sort_order": b.sort_order, "colors": _j(b.colors),
        "image_settings": _j(b.image_settings), "voice_instructions": b.voice_instructions or "",
        "caption_settings": _j(b.caption_settings), "logo_url": b.logo_url or "",
        "notes": b.notes or "",
    }


def _build_image_prompt_for_brand(headline: str, tag: str, scene: str,
                                   brand: dict, notes: str = "") -> str:
    """Build a Kie.ai image prompt using brand-specific colors and layout."""
    colors = brand.get("colors") or {}
    footer_color  = colors.get("color_footer", "#000000")
    headline_color = colors.get("color_headline", "#FFDE59")
    tag_bg_color  = colors.get("color_tag_bg", "#D02020")
    img = brand.get("image_settings") or {}
    aspect = img.get("aspect_ratio", "4:5")

    # Map hex to English for the AI (inline hex can render as text)
    def _hex_to_english(h: str) -> str:
        mapping = {
            "#000000": "solid flat pure black",
            "#FFDE59": "bold bright golden yellow",
            "#D02020": "vivid fire-engine red",
            "#FFFFFF": "white",
            "#1a1a2e": "deep navy blue",
            "#e94560": "vivid rose pink",
        }
        return mapping.get(h.upper() if h else "", f"the color {h}")

    footer_eng  = _hex_to_english(footer_color)
    headline_eng = _hex_to_english(headline_color)
    tag_eng     = _hex_to_english(tag_bg_color)
    notes_clause = f" Additional direction: {notes}." if notes else ""

    return (
        f"A {aspect} vertical portrait breaking-news share card with TWO ZONES — strictly no overlap between them.\n\n"
        f"ZONE 1 — UPPER TWO-THIRDS (photo area): {scene}.{notes_clause} {_ANTI_SLOP}\n\n"
        f"ZONE 2 — LOWER ONE-THIRD (footer panel): A SOLID FLAT {footer_eng.upper()} rectangle spanning the full width "
        f"at the bottom of the card. This panel must be completely opaque with ZERO transparency, "
        f"ZERO gradient, ZERO bleed from the photo above. Inside this panel:\n"
        f"  - TOP OF FOOTER: a small solid {tag_eng} rounded rectangle pill containing the text "
        f"\"{tag}\" in bold white uppercase letters.\n"
        f"  - BELOW THE TAG: the headline text \"{headline}\" in BOLD {headline_eng.upper()} uppercase "
        f"Montserrat-style sans-serif. Left-aligned, large enough to read at a glance, wrapped over 2 to 4 lines.\n"
        f"\n"
        f"RULES: Flat 2D text only — no drop shadows, no outer glows, no gradients on text. "
        f"No logos, no URLs, no social handles. Photo fills only the upper two-thirds. "
        f"{aspect} vertical portrait format, photorealistic, sharp, magazine-quality."
    )


def _get_brand_voice_system(brand: dict, task: str = "captions") -> str:
    """Return a system prompt combining brand voice with task instructions."""
    voice = brand.get("voice_instructions") or _FSN_VOICE
    name  = brand.get("name", "this page")
    cs    = brand.get("caption_settings") or {}
    hook  = cs.get("agreement_hook", True)
    hook_note = (
        "\nEnd short and medium captions with an agreement hook (Do you agree? / Right? / Yes or No? / Be honest:)."
        if hook else
        "\nEnd captions with an engaging question that invites the reader to share their experience."
    )
    return (
        f"You are a content writer for {name}.\n\n"
        f"BRAND VOICE:\n{voice}\n\n"
        f"TASK: Write {task} in this brand's voice.{hook_note}\n"
        "Output ONLY valid JSON — no explanation, no markdown fences."
    )


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
    try:
        _FSN_PICKS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _FSN_PICKS_PATH.write_text(json.dumps(picks, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.warning("_build_picks_from_approved_queue: could not write picks file: %s", exc)
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

# Source types that must never go through collect_source's RSS/Atom fetch
# path. twitter_manual sources are auto-created by app/collectors/twitter_manual.py
# with .url set to the author's profile page (not a feed) -- collect_source
# was never guarded against this, so poll_tier, run_full_scan, and the
# per-source "Fetch now" button were all silently attempting to parse a
# Twitter profile page as RSS/XML on every scan (real operator-reported
# symptom: "Daily Mail US (X)", "jack (X)", "folkhero (X)" showing
# "parse failed: not well-formed (invalid token)" in the Source errors
# panel). The comment on twitter_manual.py's Source creation already said
# "not actually polled -- capture is manual/on-demand", but nothing
# actually enforced that anywhere until now.
NON_POLLABLE_SOURCE_TYPES = {"twitter_manual"}

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
            select(Source).where(
                Source.enabled.is_(True), Source.polling_tier == tier,
                Source.type.notin_(NON_POLLABLE_SOURCE_TYPES),
            )
        ).scalars().all()
        for source in sources:
            stats = collect_source(session, source)
            logger.info("polled %s (%s): %s", source.name, tier, stats)
    finally:
        session.close()


_PRUNE_DAYS = 14  # stories older than this are deleted from the DB


def prune_old_stories():
    """Delete story clusters (and their child rows) older than 14 days.

    Covered stories are kept forever — they're the record of what was posted.
    Stories in the FSN pipeline queue (handoff_sent_at set, or fsn_state
    with queue_status != None) are kept until they age out naturally.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=_PRUNE_DAYS)
    session = SessionLocal()
    try:
        old_clusters = session.execute(
            select(StoryCluster).where(
                StoryCluster.first_detected_at < cutoff,
            )
        ).scalars().all()
        if not old_clusters:
            logger.info("prune_old_stories: nothing to prune")
            return
        ids = [c.id for c in old_clusters]
        # Delete child rows first (FK constraints)
        session.execute(
            _sql_text("DELETE FROM covered_posts WHERE cluster_id = ANY(:ids)"),
            {"ids": ids},
        )
        session.execute(
            _sql_text("DELETE FROM story_cluster_articles WHERE cluster_id = ANY(:ids)"),
            {"ids": ids},
        )
        for c in old_clusters:
            session.delete(c)
        session.commit()
        logger.info("prune_old_stories: deleted %d clusters older than %d days", len(ids), _PRUNE_DAYS)
    except Exception as exc:
        session.rollback()
        logger.warning("prune_old_stories failed: %s", exc)
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
        sources = session.execute(
            select(Source).where(
                Source.enabled.is_(True), Source.type.notin_(NON_POLLABLE_SOURCE_TYPES),
            )
        ).scalars().all()
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
    # Add fsn_state column if it doesn't exist (idempotent — PostgreSQL IF NOT EXISTS).
    from app.db import engine as _engine
    try:
        with _engine.connect() as _conn:
            _conn.execute(_sql_text(
                "ALTER TABLE story_clusters ADD COLUMN IF NOT EXISTS fsn_state TEXT"
            ))
            _conn.execute(_sql_text(
                "ALTER TABLE story_clusters ADD COLUMN IF NOT EXISTS ai_topic_relevance FLOAT"
            ))
            _conn.execute(_sql_text(
                "ALTER TABLE sources ADD COLUMN IF NOT EXISTS show_in_main_feed BOOLEAN NOT NULL DEFAULT TRUE"
            ))
            _conn.commit()
    except Exception as _e:
        logger.warning("schema migration skipped: %s", _e)

    # Create brand_properties table if it doesn't exist, then seed defaults
    try:
        from app.models import BrandProperty as _BP
        from app.db import Base as _Base
        _Base.metadata.create_all(_engine, tables=[_BP.__table__], checkfirst=True)
        _seed_default_brands()
    except Exception as _e:
        logger.warning("brand_properties setup skipped: %s", _e)

    # Seed competitor URL list into /tmp on every startup so the FB Scanner
    # page always has a list to render — without this, the first page load
    # after a cold start shows no checkboxes because /tmp is empty.
    _load_competitor_urls()

    for tier, minutes in TIER_MINUTES.items():
        scheduler.add_job(
            poll_tier, "interval", minutes=minutes, args=[tier],
            id=f"poll_{tier}", replace_existing=True,
        )
    # Run once at startup (clears backlog on redeploy) then daily
    scheduler.add_job(prune_old_stories, "interval", hours=24,
                      id="prune_old_stories", replace_existing=True)
    scheduler.start()
    # Run an initial prune in a background thread so startup doesn't block
    import threading as _threading
    _threading.Thread(target=prune_old_stories, daemon=True).start()
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

# Static assets (logo, etc). Deliberately NOT behind require_user -- a
# StaticFiles mount bypasses route-level auth entirely regardless, and the
# login page (which renders before any session exists) needs to load the
# logo image without being authenticated first.
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")


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


@app.get("/api/ping")
def api_ping():
    """Keepalive endpoint — prevents Render from spinning down during active sessions."""
    return JSONResponse({"ok": True})


@app.get("/api/find-sources")
def api_find_sources(q: str = "", user: dict = Depends(require_user)):
    """Search Google News RSS for source links related to a story headline."""
    if not q or len(q) < 5:
        return JSONResponse({"results": []})
    import urllib.parse as _up, re as _re, xml.etree.ElementTree as _ET
    encoded = _up.quote_plus(q)
    rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AIMNewsDesk/1.0)"}
    try:
        r = httpx.get(rss_url, headers=headers, timeout=10, follow_redirects=True)
        root = _ET.fromstring(r.text)
        ns = {"media": "http://search.yahoo.com/mrss/"}
        results = []
        for item in root.findall(".//item")[:6]:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            desc  = _re.sub(r'<[^>]+>', '', item.findtext("description") or "").strip()[:200]
            src   = (item.findtext("source") or "").strip()
            if title and link:
                results.append({"title": title, "url": link, "snippet": desc, "source": src})
        return JSONResponse({"results": results[:5]})
    except Exception as exc:
        return JSONResponse({"error": str(exc), "results": []}, status_code=500)


@app.get("/api/queue-counts")
def api_queue_counts(user: dict = Depends(require_user)):
    """Return counts of FSN queue items by status for the header status bar."""
    from fastapi.responses import JSONResponse
    counts = {"queued": 0, "generating": 0, "approved": 0}
    try:
        items = _load_fsn_queue()
        for item in items:
            qs = (item.get("queue_status") or "").lower()
            if qs == "pending":
                counts["queued"] += 1
            elif qs in ("generating", "in_progress"):
                counts["generating"] += 1
            elif qs == "approved":
                counts["approved"] += 1
    except Exception:
        pass
    return JSONResponse(counts)


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
        query = select(StoryCluster).where(StoryCluster.status.notin_(["Dismissed", "Archived", "Covered"]))
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
        else:
            # Exclude clusters whose only sources are hidden from the main feed
            hidden_source_ids = select(Source.id).where(Source.show_in_main_feed.is_(False))
            visible_cluster_ids = select(StoryClusterArticle.cluster_id).join(
                NormalizedArticle, NormalizedArticle.id == StoryClusterArticle.normalized_article_id
            ).where(NormalizedArticle.source_id.notin_(hidden_source_ids)).distinct()
            query = query.where(StoryCluster.id.in_(visible_cluster_ids))

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
            "ai_topic_relevance": cluster.ai_topic_relevance,
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
def handoff(cluster_id: int, return_to: str = Form("/"), user: dict = Depends(require_user)):
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

        try:
            write_handoff(cluster, articles)
        except Exception:
            pass  # local-only; Render ephemeral path is fine to skip
        cluster.handoff_sent_at = datetime.now(timezone.utc)
        # Ensure the item surfaces in the Production Queue with pending status
        existing_fsn: dict = {}
        if cluster.fsn_state:
            try:
                existing_fsn = json.loads(cluster.fsn_state)
            except Exception:
                pass
        if not existing_fsn.get("queue_status"):
            existing_fsn["queue_status"] = "pending"
            cluster.fsn_state = json.dumps(existing_fsn, ensure_ascii=False)
        session.commit()
        # Return JSON so fetch() callers get a clean signal (redirects are swallowed by fetch)
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
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
    from sqlalchemy import func as sqlfunc
    session = SessionLocal()
    try:
        rows = session.execute(select(Source).order_by(Source.polling_tier, Source.name)).scalars().all()
        cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
        # Count articles per source in last 7 days
        counts_7d = dict(session.execute(
            select(NormalizedArticle.source_id, sqlfunc.count(NormalizedArticle.id))
            .where(NormalizedArticle.published_at >= cutoff_7d)
            .group_by(NormalizedArticle.source_id)
        ).all())
        source_rows = [{
            "id": s.id,
            "name": s.name,
            "type": s.type,
            "category": s.category,
            "credibility_tier": s.credibility_tier,
            "polling_tier": s.polling_tier,
            "enabled": s.enabled,
            "show_in_main_feed": getattr(s, "show_in_main_feed", True),
            "user_agent": s.user_agent,
            "last_fetch_at": s.last_fetch_at.strftime("%Y-%m-%d %H:%M UTC") if s.last_fetch_at else "never",
            "last_fetch_at_raw": s.last_fetch_at,
            "last_error": s.last_error,
            "articles_7d": counts_7d.get(s.id, 0),
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
    show_in_main_feed: bool = Form(False),
    user_agent: str = Form(""),
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
        source.show_in_main_feed = show_in_main_feed
        source.user_agent = user_agent.strip() or None
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
        if source.type in NON_POLLABLE_SOURCE_TYPES:
            return RedirectResponse(
                "/sources?msg=This+source+type+is+manual-capture+only+--+it+has+no+feed+to+fetch",
                status_code=303,
            )
        stats = collect_source(session, source)
        if stats["error"]:
            msg = f"Fetch failed: {stats['error']}"
        else:
            msg = f"Fetched {stats['fetched']}, {stats['canonical']} new stories, {stats['duplicates']} duplicates"
        return RedirectResponse(f"/sources?msg={msg}", status_code=303)
    finally:
        session.close()


@app.post("/sources/{source_id}/delete")
def delete_source(source_id: int, user: dict = Depends(require_user)):
    session = SessionLocal()
    try:
        source = session.get(Source, source_id)
        if not source:
            return RedirectResponse("/sources?msg=Source+not+found", status_code=303)
        name = source.name
        session.delete(source)
        session.commit()
        return RedirectResponse(f"/sources?msg={name}+deleted", status_code=303)
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
def pipeline_queue(background_tasks: BackgroundTasks, msg: str = "", show_older: str = "", user: dict = Depends(require_user)):
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

    # On Render, picks file never exists — treat approved image cards as "picks ready"
    approved_image_cards = [
        x for x in items
        if x.get("queue_status") == "approved" and x.get("post_type", "image_card") == "image_card"
    ]
    if not _is_local() and approved_image_cards:
        picks_ready = True
        picks_count = len(approved_image_cards)
        picks_date  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        picks_ready = bool(posts)
        picks_count = len(posts)
        picks_date  = (picks or {}).get("batch_date", "")

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
        picks_ready=picks_ready,
        picks_count=picks_count,
        picks_date=picks_date,
        recommendation=recommendation,
        show_older=bool(show_older),
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
        if _is_local():
            # Write approved_picks.json so run-batch has fresh content
            _build_picks_from_approved_queue()
            msg = f"{updated} story(s) approved — click Generate Images Now"
        else:
            msg = f"{updated} story(s) approved — click Generate Images Now"
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


def _generate_one_image(cid: str, key: str, item: dict, notes: str = "") -> None:
    """Generate image for a single cluster, stamp logo, and update DB. Runs in a thread."""
    draft = item.get("draft") or {}
    headline = draft.get("headline") or item.get("text") or ""
    tag      = draft.get("tag") or "BREAKING NEWS"
    scene    = draft.get("scene") or draft.get("image_scene") or item.get("suggested_scene") or "United States Capitol building exterior, wide establishing shot"
    effective_notes = notes or draft.get("image_notes") or ""
    brand_slug_for_gen = item.get("brand_slug") or "first_signal"
    try:
        brand = _get_brand(brand_slug_for_gen)
        if brand and brand.get("voice_instructions"):
            prompt = _build_image_prompt_for_brand(headline, tag, scene, brand, effective_notes)
        else:
            prompt = _build_image_prompt(headline, tag, scene, effective_notes)
        task_id = _kie_submit(prompt, key)
        kie_url = _kie_poll(task_id, key)

        # Download and stamp logo
        r = httpx.get(kie_url, timeout=60, follow_redirects=True)
        r.raise_for_status()
        _stamp_logo(r.content, cid)

        # Push previous CDN URL into image_history before overwriting
        session = SessionLocal()
        history: list = []
        try:
            c = session.get(StoryCluster, int(cid))
            if c and c.fsn_state:
                prev = json.loads(c.fsn_state)
                history = prev.get("image_history") or []
                old_kie = prev.get("kie_result_url") or ""
                if old_kie and old_kie not in history:
                    history.append(old_kie)
        except Exception:
            pass
        finally:
            session.close()

        # Store the served URL (ephemeral on Render; kie_result_url is the CDN fallback)
        served_url = f"/pipeline-queue/image/{cid}"
        _update_cluster_fsn(cid, generated_image_url=served_url, kie_result_url=kie_url,
                            image_gen_status="done", image_history=history)
        logger.info("cloud image gen cluster %s: done -> %s", cid, served_url)
    except Exception as exc:
        _update_cluster_fsn(cid, image_gen_status=f"error: {exc}")
        logger.error("cloud image gen cluster %s: %s", cid, exc)


def _generate_cloud_images_background(cluster_ids: list, items_snapshot: list) -> None:
    """Generate all images in parallel (up to 3 workers). Marks each as 'generating' first."""
    key = _get_kie_key()
    if not key:
        for cid in cluster_ids:
            _update_cluster_fsn(cid, image_gen_status="error: KIE_AI_API_KEY not set on server")
        logger.error("cloud image gen: KIE_AI_API_KEY not configured on Render")
        return

    # Build lookup from snapshot so we don't reload the queue 4× at the start
    item_map = {str(x.get("cluster_id")): x for x in items_snapshot}

    # Mark all as generating immediately so the UI shows status on next refresh
    for cid in cluster_ids:
        _update_cluster_fsn(cid, image_gen_status="generating")

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_generate_one_image, cid, key, item_map.get(cid, {})): cid
            for cid in cluster_ids
        }
        for future in as_completed(futures):
            cid = futures[future]
            try:
                future.result()
            except Exception as exc:
                logger.error("image gen thread %s: %s", cid, exc)


@app.post("/pipeline-queue/run-batch")
def pipeline_queue_run_batch(background_tasks: BackgroundTasks, user: dict = Depends(require_user)):
    """Generate images — uses Kie.ai REST on Render, local subprocess on Windows."""
    items = _load_fsn_queue()
    approved_image_cards = [
        x for x in items
        if x.get("queue_status") == "approved"
        and x.get("post_type", "image_card") == "image_card"
        and x.get("image_gen_status") != "done"
        and not x.get("generated_image_url")
        and x.get("image_gen_status") != "generating"
    ]

    if not approved_image_cards:
        return RedirectResponse(
            "/pipeline-queue?msg=No+new+image+cards+to+generate.+Already-generated+cards+are+skipped+automatically.",
            status_code=303,
        )

    if not _is_local():
        # Cloud path: call Kie.ai directly from the server (parallel, up to 3 at once)
        cluster_ids = [str(x["cluster_id"]) for x in approved_image_cards]
        background_tasks.add_task(_generate_cloud_images_background, cluster_ids, approved_image_cards)
        n = len(cluster_ids)
        return RedirectResponse(
            f"/pipeline-queue?msg=Generating+{n}+image(s)+in+parallel+via+Kie.ai",
            status_code=303,
        )

    # Local path: existing subprocess flow
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

    now = datetime.now(timezone.utc)

    # Insert a real StoryCluster row so the entry persists on Render (DB-backed queue)
    db = SessionLocal()
    try:
        cluster = StoryCluster(
            canonical_headline=raw_headline,
            summary=paste_text[:500] if paste_text else "",
            category="manual",
            status="New",
            verification_status="manual_add",
            first_detected_at=now,
            latest_update_at=now,
            article_count=1,
            source_count=1,
            viral_score=0.0,
            confidence_score=0.0,
            momentum_score=0.0,
            handoff_sent_at=now,  # mark as sent so it appears in the queue
            fsn_state=json.dumps({
                "queue_status": "pending",
                "post_type": "image_card",
                "draft": {"headline": "", "tag": "JUST IN", "captions": {}, "first_comment": ""},
                "needs_draft": True,
            }, ensure_ascii=False),
        )
        db.add(cluster)
        db.commit()
        db.refresh(cluster)
        new_id = cluster.id
    except Exception as exc:
        db.rollback()
        logger.error("add-article: DB insert failed: %s", exc)
        # Fallback: timestamp ID (local path)
        new_id = int(now.timestamp() * 1000)
    finally:
        db.close()

    entry = {
        "cluster_id":          new_id,
        "text":                raw_headline,
        "category":            "manual",
        "viral_score":         0,
        "source_count":        1,
        "verification_status": "manual_add",
        "queue_status":        "pending",
        "added_to_queue_at":   now.isoformat(),
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

    msg = "Article added."
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
    key = _get_anthropic_key()
    if not key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not set"}, status_code=400)

    picks_path = _FSN_PICKS_PATH
    if not picks_path.exists():
        return JSONResponse({"error": "No approved batch found. Run a batch from the pipeline first, or this feature is only available locally."}, status_code=400)

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
            model="claude-sonnet-4-6", max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "").strip()
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
    cluster_id = int(form.get("cluster_id") or 0)
    variant    = (form.get("variant") or "short").strip()
    notes      = str(form.get("notes", "")).strip()
    form_brand = str(form.get("brand_slug", "")).strip() or None

    key = _get_anthropic_key()
    if not key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not set"}, status_code=400)

    items, item = _resolve_queue_item(cluster_id)
    if not item:
        return JSONResponse({"error": "Item not found"}, status_code=404)

    draft    = item.get("draft") or {}
    form_headline = str(form.get("headline", "")).strip()
    headline = form_headline or draft.get("headline") or item.get("text") or ""
    story    = item.get("text") or ""
    captions = draft.get("captions") or {}
    sources  = item.get("sources") or []
    source_lines = "\n".join(f"  - {s.get('source_name','')}: {s.get('headline','')}" for s in sources[:3])

    bands = {"short": "10-15", "medium": "40-60", "long": "100-150", "extra_long": "200-300"}
    band  = bands.get(variant, "40-60")
    article_note = (
        " Write a full Facebook news article: lead paragraph states the facts, "
        "body paragraphs add context and accountability, closing line is the hook."
        if variant in ("long", "extra_long") else ""
    )
    notes_line = f"\nOperator notes: {notes}" if notes else ""

    brand = _get_brand(form_brand or item.get("brand_slug") or "first_signal")
    base_voice = (
        brand.get("voice_instructions") or _FSN_AMERICA_FIRST_VOICE
        if brand else _FSN_AMERICA_FIRST_VOICE
    )
    system = (
        base_voice + "\n\n"
        "Output ONLY the rewritten caption text — no explanation, no quotes around it."
    )
    story_block = f"Story text: {story}\n" if story else ""
    sources_block = f"Sources:\n{source_lines}\n" if source_lines else ""
    user_msg = (
        f"{story_block}{sources_block}"
        f"Post headline: {headline}\n"
        f"Current {variant} caption: {captions.get(variant, '')}\n\n"
        f"Rewrite the {variant} caption. Strict word count: {band} words.{article_note} "
        f"Short and medium captions must end with an agreement hook (Do you agree? / Right? / Yes or No?).{notes_line} "
        "Use ONLY facts from the story text above. Return ONLY the new caption text."
    )

    try:
        import anthropic as _ant
        client = _ant.Anthropic(api_key=key)

        collected = []

        def _stream():
            with client.messages.stream(
                model="claude-sonnet-4-6", max_tokens=600,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                for chunk in stream.text_stream:
                    collected.append(chunk)
                    yield chunk
            # After stream ends, persist to DB (generator has finished)
            new_text = "".join(collected).strip().strip('"').strip("'")
            if not item.get("draft"):
                item["draft"] = {}
            item["draft"].setdefault("captions", {})[variant] = new_text
            _update_cluster_fsn(cluster_id, draft=item["draft"])
            _save_fsn_queue(items)

        return StreamingResponse(_stream(), media_type="text/plain")
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/pipeline-queue/generate-all-captions")
async def pipeline_queue_generate_all_captions(request: Request, user: dict = Depends(require_user)):
    """Generate all 4 caption variants + first comment for a queue item in one AI call."""
    form = await request.form()
    cluster_id    = int(form.get("cluster_id") or 0)
    form_headline = str(form.get("headline", "")).strip()
    notes         = str(form.get("notes", "")).strip()
    form_brand    = str(form.get("brand_slug", "")).strip() or None

    key = _get_anthropic_key()
    if not key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not set"}, status_code=400)

    items, item = _resolve_queue_item(cluster_id)
    if not item:
        return JSONResponse({"error": "Item not found"}, status_code=404)

    draft    = item.get("draft") or {}
    headline = form_headline or draft.get("headline") or item.get("text") or ""
    tag      = draft.get("tag") or ""
    story    = item.get("text") or ""
    sources  = item.get("sources") or []
    source_lines = "\n".join(f"  - {s.get('source_name','')}: {s.get('headline','')}" for s in sources[:3])
    notes_line = f"\nOperator notes: {notes}" if notes else ""

    brand = _get_brand(form_brand or item.get("brand_slug") or "first_signal")
    base_voice = (
        _get_brand_voice_system(brand, task="captions")
        if brand and brand.get("voice_instructions")
        else _FSN_AMERICA_FIRST_VOICE
    )
    system = (
        base_voice + "\n\n"
        "Short ends with an agreement hook (Do you agree? / Right? / Yes or No? / Be honest:). "
        "Medium also ends with an agreement hook. "
        "Long and Extra Long are FULL FACEBOOK ARTICLES — lead with the biggest fact, "
        "build the case paragraph by paragraph, name names, cite what happened, end with the hook. "
        "Output ONLY valid JSON — no explanation, no markdown fences."
    )
    sources_block = f"\nSources:\n{source_lines}" if source_lines else ""
    user_msg = (
        f"Story: {story}{sources_block}\nHeadline: {headline}\nTag: {tag}{notes_line}\n\n"
        "Write all 4 Facebook caption variants and a first comment. Strict word counts:\n"
        "- short: 10-15 words, punchy hook, ends with agreement hook\n"
        "- medium: 40-60 words, 1-2 sharp sentences, ends with agreement hook\n"
        "- long: 100-150 words, 2-3 paragraphs, full context, ends with hook\n"
        "- extra_long: 200-300 words, complete Facebook article with background, context, "
        "why it matters to America First readers, strong closing hook\n"
        "- first_comment: 25-45 words — add one specific detail or context from the story not in the caption, "
        "then end with a direct question to the reader (e.g. 'What do you think about this?')\n\n"
        'Return JSON: {"short":"...","medium":"...","long":"...","extra_long":"...","first_comment":"..."}'
    )

    import re as _re
    try:
        import anthropic as _ant
        client = _ant.Anthropic(api_key=key)
        collected = []

        def _stream():
            with client.messages.stream(
                model="claude-sonnet-4-6", max_tokens=2500,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                for chunk in stream.text_stream:
                    collected.append(chunk)
                    yield chunk
            # Parse and persist once streaming finishes
            raw = "".join(collected).strip()
            m = _re.search(r'\{.*\}', raw, _re.S)
            if not m:
                return
            try:
                data = json.loads(m.group())
            except Exception:
                return
            if not item.get("draft"):
                item["draft"] = {}
            item["draft"].setdefault("captions", {}).update({
                "short":      data.get("short", ""),
                "medium":     data.get("medium", ""),
                "long":       data.get("long", ""),
                "extra_long": data.get("extra_long", ""),
            })
            if data.get("first_comment"):
                item["draft"]["first_comment"] = data["first_comment"]
            _update_cluster_fsn(cluster_id, draft=item["draft"])
            _save_fsn_queue(items)

        return StreamingResponse(_stream(), media_type="text/plain")
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


_VIDEO_SYSTEM = """You are the First Signal News video script writer for an AI Avatar presenter.

VOICE RULES (strict — this text will be fed to a TTS avatar):
- Short sentences. 8 to 18 words each. Every sentence is its own complete idea.
- No em-dashes. No semicolons. No parentheses mid-sentence.
- No complicated words. If a word needs explaining, replace it with a simpler one.
- Conversational flow. Write how a sharp anchor speaks, not how a journalist types.
- Numbers as digits: 36-year-old, 3 bills, not thirty-six or three bills.
- Attribution phrases instead of quote marks: use "Her exact words." then a new line for the quote. Or "Here is what she said." then the quote. Never wrap quotes in quotation marks mid-sentence.
- Context pivot: signal the shift with a full sentence. Example: "Here is why that matters."
- Hook: first sentence must be punchy and surprising. Subject plus action plus implication. Example: "AOC just turned her fertility treatment into a content series."
- Closing: end every script with the question for the audience, then "Follow First Signal." on its own line.

WHAT TO NEVER DO:
- No em-dashes anywhere
- No "delve", "tapestry", "it's worth noting", "in today's world"
- No hedging or balance. Take a clear America First side.
- Never fabricate a quote, charge, vote, or statistic. Stick to the sourced facts.

SCRIPT LENGTHS:
- short: 30 to 45 seconds. Hook plus 3 to 5 facts plus closing question. About 80 to 120 words.
- medium: 60 to 90 seconds. Hook plus facts plus one context paragraph plus closing question. About 160 to 240 words.
- long: 120 to 180 seconds. Hook plus facts plus context pivot section plus analysis paragraph plus stakes paragraph plus closing question. About 320 to 480 words.

Output ONLY valid JSON — no explanation, no markdown fences."""

_VIDEO_USER_TPL = """\
Story: {story}
Headline: {headline}

Write all video package content for this story. Return exactly this JSON shape:
{{
  "video_titles": ["title option 1", "title option 2", "title option 3"],
  "reels_description": "...",
  "script_short": "...",
  "script_medium": "...",
  "script_long": "...",
  "poll_question": "...",
  "video_first_comment": "..."
}}

Rules per field:
- video_titles: 3 short punchy options for a Reels cover card. Under 10 words each. No em-dashes.
- reels_description: 2 to 4 sentences. Rapid-fire facts from the story. End with 1 or 2 relevant emojis and 2 to 3 hashtags including #FirstSignal.
- script_short: 80 to 120 words. Hook plus key facts plus closing question plus "Follow First Signal." on its own line.
- script_medium: 160 to 240 words. Hook plus facts plus context section plus closing question plus "Follow First Signal." on its own line.
- script_long: 320 to 480 words. Full anchor script. Hook, facts, context pivot ("Here is why that matters."), analysis, stakes, closing question, "Follow First Signal." on its own line.
- poll_question: One binary poll. Question on first line. Then two options with thumbs up / thumbs down emoji.
- video_first_comment: 3 to 5 sentences. In-depth context that adds to the story. End with a question to drive replies. No em-dashes.
"""


@app.post("/pipeline-queue/write-video-script")
async def pipeline_queue_write_video_script(request: Request, user: dict = Depends(require_user)):
    """Generate all video package content (titles, description, 3 scripts, poll, first comment) in one AI call."""
    form = await request.form()
    cluster_id = int(form.get("cluster_id") or 0)

    key = _get_anthropic_key()
    if not key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not set"}, status_code=400)

    items, item = _resolve_queue_item(cluster_id)
    if not item:
        return JSONResponse({"error": "Item not found"}, status_code=404)

    draft    = item.get("draft") or {}
    headline = draft.get("headline") or item.get("text") or ""
    story    = item.get("text") or headline

    user_msg = _VIDEO_USER_TPL.format(story=story, headline=headline)

    try:
        import anthropic, re as _re
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=4000,
            system=_VIDEO_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "").strip()
        m = _re.search(r'\{.*\}', raw, _re.S)
        if not m:
            return JSONResponse({"error": f"No JSON in response: {raw[:300]}"}, status_code=500)
        data = json.loads(m.group())

        # Persist to queue / DB — include post_type so type survives reload
        video_fields = {
            "post_type":            "video_package",
            "video_titles":         data.get("video_titles") or [],
            "reels_description":    data.get("reels_description") or "",
            "script_short":         data.get("script_short") or "",
            "script_medium":        data.get("script_medium") or "",
            "script_long":          data.get("script_long") or "",
            "poll_question":        data.get("poll_question") or "",
            "video_first_comment":  data.get("video_first_comment") or "",
        }
        item.update(video_fields)
        # Persist to DB first (cloud-safe), then update local file cache
        _update_cluster_fsn(cluster_id, **video_fields)
        _save_fsn_queue(items)

        return JSONResponse({"ok": True, **video_fields})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/pipeline-queue/expand-angles")
async def pipeline_queue_expand_angles(request: Request, user: dict = Depends(require_user)):
    """Suggest 3 FSN story angles for a pending item before drafting."""
    form = await request.form()
    cluster_id = int(form.get("cluster_id") or 0)
    notes      = str(form.get("notes", "")).strip()

    key = _get_anthropic_key()
    if not key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not set"}, status_code=400)

    item = _queue_item_for(cluster_id)
    if not item:
        return JSONResponse({"error": "Item not found"}, status_code=404)

    headline = item.get("text") or ""
    sources  = item.get("sources") or []
    source_lines = "\n".join(f"  - {s.get('source_name','')}: {s.get('headline','')}" for s in sources[:3]) or "  (no sources)"

    system = _FSN_VOICE_CONTEXT + "\n\n" + """\
You are a First Signal News content strategist. Given a story, suggest 3 distinct content angles.
Output ONLY valid JSON:
{
  "angles": [
    {
      "angle_type": "accountability"|"vindication"|"breaking"|"outrage"|"poll"|"analysis",
      "hook": "the 8-16 word headline this angle would produce",
      "caption_lead": "the first sentence of the short caption for this angle",
      "tag": "EXACTLY 3 UPPERCASE WORDS for the red pill",
      "image_scene": "concrete scene for the image upper two-thirds — either a thematic scene (building, courthouse, border fence, port, etc.) or 'recognizable likeness of [Name], head-and-shoulders portrait' if the angle is specifically about that person",
      "why": "one sentence — why this angle works for FSN audience"
    },
    ... exactly 3 angles ...
  ]
}
Each angle must be meaningfully different in framing. No em-dashes."""

    notes_line = f"\nOperator direction: {notes}" if notes else ""
    user_msg = f"Story: {headline}\nSources:\n{source_lines}{notes_line}\n\nSuggest 3 FSN angles."

    try:
        import anthropic as _ant, re as _re
        client = _ant.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "").strip()
        # Strip markdown fences if model wraps JSON
        raw = _re.sub(r'^```(?:json)?\s*', '', raw, flags=_re.IGNORECASE)
        raw = _re.sub(r'\s*```$', '', raw)
        m = _re.search(r'\{.*\}', raw, _re.S)
        if not m:
            return JSONResponse({"error": f"No JSON returned: {raw[:200]}"}, status_code=500)
        result = json.loads(m.group())
        return JSONResponse(result)
    except json.JSONDecodeError as exc:
        return JSONResponse({"error": f"JSON parse error: {exc}"}, status_code=500)
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


@app.post("/pipeline-queue/write-tobi")
async def pipeline_queue_write_tobi(request: Request, user: dict = Depends(require_user)):
    """Generate 3 TOBI post options (12-32 words each) for a pending queue item."""
    form = await request.form()
    cluster_id = int(form.get("cluster_id") or 0)

    key = _get_anthropic_key()
    if not key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not set"}, status_code=400)

    items = _load_fsn_queue()
    item = next((x for x in items if x.get("cluster_id") == cluster_id), None)
    headline = (item or {}).get("text") or ""
    if not headline:
        # Fall back to DB
        session = SessionLocal()
        try:
            c = session.get(StoryCluster, cluster_id)
            if c:
                headline = c.canonical_headline or ""
        finally:
            session.close()
    if not headline:
        return JSONResponse({"error": "Item not found"}, status_code=404)

    system = """\
You are the First Signal News automation. Write 3 distinct TOBI text-only posts for the story.

Rules:
- Each post: 12-32 words (HARD LIMIT — count carefully)
- America First conservative voice, direct and punchy
- No em-dashes, no emojis, no hashtags
- End each post with an agreement hook: "Do you agree?" / "Yes or No?" / "Right?" / "Who agrees?" / "Be honest:"
- Each option must take a different angle (e.g. outrage, accountability, poll)

Output ONLY valid JSON:
{"options": ["post 1 text", "post 2 text", "post 3 text"]}"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": f"Story: {headline}\n\nWrite 3 TOBI options."}],
        )
        raw = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        return {"options": data.get("options") or []}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/pipeline-queue/set-post-type")
async def pipeline_queue_set_post_type(request: Request, user: dict = Depends(require_user)):
    """Immediately persist post_type for a cluster so it survives page refresh."""
    form = await request.form()
    cluster_id = int(form.get("cluster_id") or 0)
    post_type  = str(form.get("post_type", "image_card")).strip()
    if post_type not in ("image_card", "tobi", "video_package"):
        return JSONResponse({"error": "invalid type"}, status_code=400)
    _update_cluster_fsn(cluster_id, post_type=post_type)
    # Also update local queue file if running locally
    if _is_local():
        items = _load_fsn_queue()
        for item in items:
            if item.get("cluster_id") == cluster_id:
                item["post_type"] = post_type
                break
        _save_fsn_queue(items)
    return {"ok": True}


@app.post("/pipeline-queue/apply-tobi")
async def pipeline_queue_apply_tobi(request: Request, user: dict = Depends(require_user)):
    """Save chosen TOBI text onto the queue item."""
    form = await request.form()
    cluster_id = int(form.get("cluster_id") or 0)
    text = str(form.get("text", "")).strip()
    if not text:
        return JSONResponse({"error": "No text"}, status_code=400)

    # Persist to DB directly so it survives refresh
    _update_cluster_fsn(cluster_id, post_type="tobi", tobi_text=text)

    if _is_local():
        items = _load_fsn_queue()
        item = next((x for x in items if x.get("cluster_id") == cluster_id), None)
        if item:
            if not item.get("draft"):
                item["draft"] = {}
            item["draft"]["tobi_text"] = text
            item["post_type"] = "tobi"
            _save_fsn_queue(items)
    return {"ok": True}


@app.post("/pipeline-queue/apply-angle")
async def pipeline_queue_apply_angle(request: Request, user: dict = Depends(require_user)):
    """Save a chosen angle (hook/tag/caption_lead) onto the queue item as its working draft headline."""
    form = await request.form()
    cluster_id = int(form.get("cluster_id") or 0)
    hook         = str(form.get("hook", "")).strip()
    tag          = str(form.get("tag", "")).strip()
    caption_lead = str(form.get("caption_lead", "")).strip()
    angle_type   = str(form.get("angle_type", "")).strip()
    image_scene  = str(form.get("image_scene", "")).strip()

    items, item = _resolve_queue_item(cluster_id)
    if not item:
        return JSONResponse({"ok": False, "error": "item not found"}, status_code=404)

    # Patch the item's draft with the chosen angle values
    if not item.get("draft"):
        item["draft"] = {}
    item["draft"]["headline"] = hook.upper()
    item["draft"]["tag"] = tag
    if caption_lead:
        caps = item["draft"].setdefault("captions", {})
        caps["short"] = caption_lead
    if image_scene:
        item["draft"]["image_scene"] = image_scene
        item["scene"] = image_scene
    item["chosen_angle_type"] = angle_type
    _update_cluster_fsn(cluster_id, draft=item["draft"])
    _save_fsn_queue(items)
    return {"ok": True}


# ── Voice context injected into every AI generation call ──────────────────────
_FSN_VOICE_CONTEXT = (
    "CURRENT POLITICAL CONTEXT (August 2026): Donald Trump is the 47th President of the United States "
    "(since January 20, 2025). Kamala Harris lost the 2024 presidential election. Joe Biden is "
    "the former president. Key figures: JD Vance (VP), Elon Musk (DOGE), Marco Rubio (Secretary of State), "
    "Pete Hegseth (Secretary of Defense), Kash Patel (FBI Director), Robert F. Kennedy Jr. (HHS Secretary). "
    "2025 midterm/state election results changed many offices — do NOT use training-data assumptions about "
    "who currently holds a position. Always derive titles and offices from the story text provided to you. "
    "Major ongoing issues: border security (record deportations), government spending cuts (DOGE), "
    "tariffs/trade war, deep state accountability, immigration enforcement, economic nationalism. "
    "Never reference Biden as current president. Never say 'the Biden administration' for anything happening now."
)

_FSN_STORY_GROUNDING = (
    "\n\nCRITICAL — USE THE STORY TEXT AS YOUR ONLY SOURCE OF FACTS:\n"
    "Your training data is outdated for current events. The story text provided below is the authoritative source. "
    "Use ONLY the facts in that text: the person's current title, what they said or did, the specific details. "
    "Do NOT substitute titles, positions, or facts from your training memory. "
    "If the story says someone is Governor, they are Governor — do not call them Representative or Senator. "
    "If the story gives a specific number, quote, vote, or date, use it exactly. "
    "If a detail is not in the story text, do not invent it."
)

_FSN_NEWS_VOICE = (
    "You are a First Signal News writer producing straight news-style Facebook content. "
    "Tone: factual, direct, credible. Who/what/when/where up front. "
    "No partisan adjectives, no opinion framing, no agreement hooks. "
    "Accurate attribution for all claims. Short punchy sentences. No em-dashes. "
    + _FSN_VOICE_CONTEXT + _FSN_STORY_GROUNDING
)

_FSN_AMERICA_FIRST_VOICE = (
    "You are a First Signal News writer producing America First / conservative Facebook content. "
    "Tone: pointed, accountability-driven, pro-Trump, pro-America. Name the real people, name the real votes, "
    "name the real consequences. Take a clear side. End captions with an agreement hook "
    "(Do you agree? / Right? / Yes or No? / Be honest: / Who agrees?). "
    "No em-dashes, no hashtags, no emojis. Never fabricate a quote, charge, vote, or statistic. "
    + _FSN_VOICE_CONTEXT + _FSN_STORY_GROUNDING
)


# ── FB Scanner state — persisted to /tmp so all Render workers share it ────────
_FB_HISTORY_MAX        = 3
_FB_JOB_PATH           = Path("/tmp/fb_scan_job.json")
_FB_RESULTS_PATH       = Path("/tmp/fb_scan_results.json")
_FB_HISTORY_PATH       = Path("/tmp/fb_scan_history.json")
_FB_COMPETITORS_PATH   = Path("/tmp/fb_competitors.json")


def _load_competitor_urls() -> list[str]:
    """Load competitor URLs from /tmp (persisted across workers).
    Seeds from the repo file on first call after a cold start."""
    if _FB_COMPETITORS_PATH.exists():
        try:
            data = json.loads(_FB_COMPETITORS_PATH.read_text())
            if isinstance(data, list):
                return data
        except Exception:
            pass
    # Seed from file in repo
    aim_comp = Path(__file__).parent.parent / "input" / "competitors.txt"
    fsn_comp = _FSN_ROOT / "input" / "competitors.txt"
    comp_file = aim_comp if aim_comp.exists() else (fsn_comp if fsn_comp.exists() else None)
    urls: list[str] = []
    if comp_file:
        urls = [l.strip() for l in comp_file.read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.strip().startswith("#")]
    _FB_COMPETITORS_PATH.write_text(json.dumps(urls))
    return urls


def _save_competitor_urls(urls: list[str]) -> None:
    _FB_COMPETITORS_PATH.write_text(json.dumps(urls))


def _fb_read_job() -> dict:
    try:
        return json.loads(_FB_JOB_PATH.read_text()) if _FB_JOB_PATH.exists() else {"status": "idle"}
    except Exception:
        return {"status": "idle"}

def _fb_write_job(job: dict) -> None:
    try:
        _FB_JOB_PATH.write_text(json.dumps(job))
    except Exception:
        pass

def _fb_read_results() -> list:
    try:
        return json.loads(_FB_RESULTS_PATH.read_text()) if _FB_RESULTS_PATH.exists() else []
    except Exception:
        return []

def _fb_write_results(results: list) -> None:
    try:
        _FB_RESULTS_PATH.write_text(json.dumps(results))
    except Exception:
        pass

def _fb_read_history() -> list:
    try:
        return json.loads(_FB_HISTORY_PATH.read_text()) if _FB_HISTORY_PATH.exists() else []
    except Exception:
        return []

def _fb_write_history(history: list) -> None:
    try:
        _FB_HISTORY_PATH.write_text(json.dumps(history))
    except Exception:
        pass


def _get_apify_token() -> str:
    """Read APIFY_TOKEN from the AIM .env or the FSN pipeline .env."""
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        # Fall back to FSN pipeline .env
        fsn_env = _FSN_ROOT / ".env"
        if fsn_env.exists():
            for line in fsn_env.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("APIFY_TOKEN"):
                    _, _, val = line.partition("=")
                    token = val.strip().strip('"').strip("'")
                    if token:
                        break
    return token


def _fb_scan_worker(token: str, urls: list[str], days: int) -> None:
    """Background thread: run Apify, poll, fetch results. Writes to /tmp for cross-worker visibility."""
    try:
        run_id = _fb.start_scan(token, urls, days=days, limit_per_page=50)
        job = _fb_read_job()
        job["run_id"] = run_id
        _fb_write_job(job)

        deadline = time.time() + 900   # 15-minute hard cap
        while time.time() < deadline:
            time.sleep(8)
            status, dataset_id = _fb.poll_run(token, run_id)
            job = _fb_read_job()
            job["apify_status"] = status
            _fb_write_job(job)
            if status == "SUCCEEDED":
                results = _fb.fetch_results(token, dataset_id, days=days)
                job["status"]      = "done"
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
                job["count"]       = len(results)
                job["dataset_id"]  = dataset_id
                _fb_write_job(job)
                _fb_write_results(results)
                history = _fb_read_history()
                history.insert(0, {"job": dict(job), "results": list(results)})
                del history[_FB_HISTORY_MAX:]
                _fb_write_history(history)
                return
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                raise RuntimeError(f"Apify run {status}")
        raise RuntimeError("Apify run did not finish within 15 minutes")
    except Exception as exc:
        job = _fb_read_job()
        job["status"] = "error"
        job["error"]  = str(exc)
        _fb_write_job(job)


def _fb_top_posts(limit: int = 50) -> list[dict]:
    """Aggregate and deduplicate posts across all stored scan history, ranked by engagement."""
    history = _fb_read_history()
    # Include current results too
    all_entries = list(_fb_read_results())
    seen_urls: set[str] = set()
    for entry in all_entries:
        u = entry.get("url") or ""
        if u:
            seen_urls.add(u)
    for scan in history:
        for post in scan.get("results", []):
            u = post.get("url") or ""
            if u and u not in seen_urls:
                seen_urls.add(u)
                all_entries.append(post)
    all_entries.sort(key=lambda p: int(p.get("engagement_score") or 0), reverse=True)
    return all_entries[:limit]


# ── FB Scanner Routes ──────────────────────────────────────────────────────────

@app.get("/fb-scanner", response_class=HTMLResponse)
def fb_scanner_page(msg: str = "", tab: str = "latest", user: dict = Depends(require_user)):
    competitors = _load_competitor_urls()
    top_posts = _fb_top_posts(50) if tab == "top" else None
    return render_fb_scanner_page(_fb_read_results(), _fb_read_job(), competitors,
                                  history=_fb_read_history(), flash=msg,
                                  active_tab=tab, top_posts=top_posts)


@app.post("/fb-scanner/scan")
async def fb_scanner_scan(request: Request, background_tasks: BackgroundTasks,
                          user: dict = Depends(require_user)):
    job = _fb_read_job()
    if job.get("status") == "running":
        # Auto-reset if the job has been running for more than 20 minutes —
        # the background thread was likely killed by a Render worker restart.
        started = job.get("started_at", "")
        stuck = True
        if started:
            try:
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds()
                stuck = age > 1200  # 20 minutes
            except Exception:
                pass
        if not stuck:
            return RedirectResponse("/fb-scanner?msg=Scan+already+running", status_code=303)
        # Stuck — reset and allow the new scan to proceed

    token = _get_apify_token()
    if not token:
        return RedirectResponse("/fb-scanner?msg=APIFY_TOKEN+not+set+in+.env", status_code=303)

    form = await request.form()
    hours = int(form.get("hours", 24) or 24)
    import math
    days = max(1, math.ceil(hours / 24))

    # Use checked pages from the form; fall back to all competitors if none submitted
    selected = form.getlist("page_url")
    urls = [u for u in selected if u.strip()] if selected else _load_competitor_urls()
    if not urls:
        return RedirectResponse("/fb-scanner?msg=No+competitor+URLs+selected", status_code=303)

    _fb_write_job({"status": "running", "started_at": datetime.now(timezone.utc).isoformat(), "hours": hours, "days": days, "page_count": len(urls)})
    _fb_write_results([])

    background_tasks.add_task(_fb_scan_worker, token, urls, days)
    return RedirectResponse("/fb-scanner", status_code=303)


@app.post("/fb-scanner/reset")
def fb_scanner_reset(user: dict = Depends(require_user)):
    _fb_write_job({"status": "idle"})
    return RedirectResponse("/fb-scanner?msg=Scan+reset", status_code=303)


@app.post("/fb-scanner/competitors/add")
async def fb_competitor_add(request: Request, user: dict = Depends(require_user)):
    form = await request.form()
    url = (form.get("url") or "").strip().rstrip("/")
    if not url.startswith("https://www.facebook.com/"):
        return RedirectResponse("/fb-scanner?msg=Invalid+Facebook+URL", status_code=303)
    urls = _load_competitor_urls()
    if url not in urls:
        urls.append(url)
        _save_competitor_urls(urls)
    return RedirectResponse("/fb-scanner?msg=Source+added", status_code=303)


@app.post("/fb-scanner/competitors/delete")
async def fb_competitor_delete(request: Request, user: dict = Depends(require_user)):
    form = await request.form()
    url = (form.get("url") or "").strip()
    urls = [u for u in _load_competitor_urls() if u != url]
    _save_competitor_urls(urls)
    return RedirectResponse("/fb-scanner?msg=Source+removed", status_code=303)


@app.get("/fb-scanner/debug")
def fb_scanner_debug(user: dict = Depends(require_user)):
    results = _fb_read_results()
    return JSONResponse({"job": _fb_read_job(), "result_count": len(results),
                         "history_count": len(_fb_read_history()),
                         "sample": results[:2] if results else []})


@app.get("/fb-scanner/raw")
def fb_scanner_raw(user: dict = Depends(require_user)):
    """Fetch a raw Apify sample to inspect field names."""
    job = _fb_read_job()
    token = _get_apify_token()
    if not token or not job.get("run_id"):
        return JSONResponse({"error": "no completed run"})
    try:
        # Use stored dataset_id if available, otherwise look it up
        did = job.get("dataset_id")
        if not did:
            r = httpx.get(f"https://api.apify.com/v2/actor-runs/{job['run_id']}?token={token}", timeout=15)
            did = r.json()["data"].get("defaultDatasetId")
        if not did:
            return JSONResponse({"error": "no dataset id found"})
        r2 = httpx.get(f"https://api.apify.com/v2/datasets/{did}/items?token={token}&limit=1", timeout=30)
        return JSONResponse({"raw_items": r2.json()})
    except Exception as exc:
        return JSONResponse({"error": str(exc)})


@app.post("/fb-scanner/send-to-queue")
async def fb_scanner_send_to_queue(request: Request, user: dict = Depends(require_user)):
    """Create a StoryCluster from a scanned FB post and add it to the production queue."""
    form = await request.form()
    try:
        idx = int(form.get("idx", -1))
    except (ValueError, TypeError):
        return JSONResponse({"error": "Invalid post index"}, status_code=400)

    results = _fb_read_results()
    if idx < 0 or idx >= len(results):
        return JSONResponse({"error": "Post not found"}, status_code=404)

    post = results[idx]
    text = (post.get("text") or post.get("preview") or "")[:500]
    page_name = post.get("page_name") or "Facebook"
    url  = post.get("url") or ""

    if not text:
        return JSONResponse({"error": "Post has no text"}, status_code=400)

    now = datetime.now(timezone.utc)
    fsn_state = {
        "queue_status":  "pending",
        "post_type":     "image_card",
        "source":        "fb_scanner",
        "source_page":   page_name,
        "source_url":    url,
        "engagement_score": post.get("engagement_score", 0),
        "fb_reactions":  post.get("reactions", 0),
        "fb_shares":     post.get("shares", 0),
        "fb_comments":   post.get("comments", 0),
    }

    db = SessionLocal()
    try:
        cluster = StoryCluster(
            canonical_headline=text[:300],
            status="New",
            category="Politics",
            handoff_sent_at=now,
            first_detected_at=now,
            latest_update_at=now,
            fsn_state=json.dumps(fsn_state, ensure_ascii=False),
        )
        db.add(cluster)
        try:
            db.commit()
            db.refresh(cluster)
        except Exception:
            db.rollback()
            return JSONResponse({"error": "Database error saving post"}, status_code=500)
        new_id = cluster.id
    finally:
        db.close()

    if _is_local():
        items = _load_fsn_queue()
        items.append({
            "cluster_id":      new_id,
            "text":            text,
            "category":        "Politics",
            "sources":         [{"source_name": page_name, "url": url, "headline": text[:120]}],
            "source_count":    1,
            "viral_score":     0,
            "confidence_score": 0,
            "momentum_score":  0,
            "queue_status":    "pending",
            "post_type":       "image_card",
            "added_to_queue_at": now.isoformat(),
            "draft":           {},
            "source":          "fb_scanner",
        })
        _save_fsn_queue(items)

    return JSONResponse({"ok": True, "cluster_id": new_id})


@app.post("/fb-scanner/send-selected")
async def fb_scanner_send_selected(request: Request, user: dict = Depends(require_user)):
    """Batch-queue multiple scanned FB posts by index."""
    from fastapi.responses import JSONResponse
    form = await request.form()
    raw_idxs = form.getlist("idx")
    results = _fb_read_results()
    now = datetime.now(timezone.utc)
    queued = 0
    skipped = 0
    db = SessionLocal()
    try:
        for raw in raw_idxs:
            try:
                idx = int(raw)
            except (ValueError, TypeError):
                skipped += 1
                continue
            if idx < 0 or idx >= len(results):
                skipped += 1
                continue
            post = results[idx]
            text = (post.get("text") or post.get("preview") or "")[:500]
            if not text:
                skipped += 1
                continue
            page_name = post.get("page_name") or "Facebook"
            url = post.get("url") or ""
            fsn_state = {
                "queue_status":     "pending",
                "post_type":        "image_card",
                "source":           "fb_scanner",
                "source_page":      page_name,
                "source_url":       url,
                "engagement_score": post.get("engagement_score", 0),
                "fb_reactions":     post.get("reactions", 0),
                "fb_shares":        post.get("shares", 0),
                "fb_comments":      post.get("comments", 0),
            }
            cluster = StoryCluster(
                canonical_headline=text[:300],
                status="New",
                category="Politics",
                handoff_sent_at=now,
                first_detected_at=now,
                latest_update_at=now,
                fsn_state=json.dumps(fsn_state, ensure_ascii=False),
            )
            db.add(cluster)
            db.flush()
            new_id = cluster.id
            if _is_local():
                items = _load_fsn_queue()
                items.append({
                    "cluster_id":        new_id,
                    "text":              text,
                    "category":          "Politics",
                    "sources":           [{"source_name": page_name, "url": url, "headline": text[:120]}],
                    "source_count":      1,
                    "viral_score":       0,
                    "confidence_score":  0,
                    "momentum_score":    0,
                    "queue_status":      "pending",
                    "post_type":         "image_card",
                    "added_to_queue_at": now.isoformat(),
                    "draft":             {},
                    "source":            "fb_scanner",
                })
                _save_fsn_queue(items)
            queued += 1
        try:
            db.commit()
        except Exception:
            db.rollback()
            return JSONResponse({"error": "Database error saving posts"}, status_code=500)
    finally:
        db.close()
    return JSONResponse({"queued": queued, "skipped": skipped})


# ── Story Workspace Routes ─────────────────────────────────────────────────────

@app.get("/pipeline-queue/story/{cid}", response_class=HTMLResponse)
def pipeline_queue_story(cid: str, msg: str = "", user: dict = Depends(require_user)):
    """Dedicated workspace page for a single production queue story."""
    if not cid.isdigit():
        return RedirectResponse("/pipeline-queue", status_code=303)
    cluster_id = int(cid)
    item = _queue_item_for(cluster_id)
    if not item:
        return RedirectResponse("/pipeline-queue?msg=Story+not+found", status_code=303)
    return render_story_workspace_page(item, flash=msg)


@app.post("/pipeline-queue/story/{cid}/save-draft")
async def pipeline_queue_story_save_draft(cid: str, request: Request, user: dict = Depends(require_user)):
    """Save headline, tag, and scene for a queue item."""
    if not cid.isdigit():
        return JSONResponse({"error": "invalid id"}, status_code=400)
    cluster_id = int(cid)
    form = await request.form()
    headline   = str(form.get("headline", "")).strip()
    tag        = str(form.get("tag", "")).strip()
    scene      = str(form.get("scene", "")).strip()
    brand_slug = str(form.get("brand_slug", "")).strip()

    try:
        items, item = _resolve_queue_item(cluster_id)
        if not item:
            return JSONResponse({"error": "not found"}, status_code=404)

        if not item.get("draft"):
            item["draft"] = {}
        if headline:
            item["draft"]["headline"] = headline
        if tag:
            item["draft"]["tag"] = tag
        if scene:
            item["draft"]["scene"] = scene
            item["scene"] = scene
        if brand_slug:
            item["brand_slug"] = brand_slug

        _update_cluster_fsn(cluster_id, draft=item["draft"], brand_slug=item.get("brand_slug"))
        _save_fsn_queue(items)
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/pipeline-queue/story/{cid}/generate-content")
async def pipeline_queue_story_generate_content(cid: str, request: Request, user: dict = Depends(require_user)):
    """Generate captions + first comment in either News Style or America First voice."""
    if not cid.isdigit():
        return JSONResponse({"error": "invalid id"}, status_code=400)
    cluster_id = int(cid)
    form = await request.form()
    voice      = str(form.get("voice", "america_first")).strip()
    headline   = str(form.get("headline", "")).strip()
    tag        = str(form.get("tag", "")).strip()
    scene      = str(form.get("scene", "")).strip()
    brand_slug = str(form.get("brand_slug", "")).strip() or None

    key = _get_anthropic_key()
    if not key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not set"}, status_code=400)

    items, item = _resolve_queue_item(cluster_id)
    if not item:
        return JSONResponse({"error": "not found"}, status_code=404)

    story = item.get("text") or ""
    if not headline:
        headline = (item.get("draft") or {}).get("headline") or story[:120]

    # Brand-aware voice: use brand settings if a brand slug is provided
    active_brand_slug = brand_slug or item.get("brand_slug") or "first_signal"
    brand = _get_brand(active_brand_slug)
    if brand and brand.get("voice_instructions"):
        system = _get_brand_voice_system(brand, task="captions")
    else:
        system = _FSN_NEWS_VOICE if voice == "news" else _FSN_AMERICA_FIRST_VOICE
    system += (
        "\n\nOutput ONLY valid JSON — no explanation, no markdown fences.\n"
        "Return: {\"short\":\"...\",\"medium\":\"...\",\"long\":\"...\",\"extra_long\":\"...\",\"first_comment\":\"...\"}"
    )

    hook_note = "" if voice == "news" else "Short must end with an agreement hook (Do you agree? / Right? / Yes or No? / Be honest:).\n"
    user_msg = (
        f"Story: {story}\nHeadline: {headline}\nTag: {tag}\n\n"
        "Write 4 Facebook caption variants and a first comment. Strict word counts:\n"
        f"{hook_note}"
        "- short: 10-15 words, punchy hook, ends with agreement hook\n"
        "- medium: 40-60 words, 1-2 sharp sentences, ends with agreement hook\n"
        "- long: 100-150 words, 2-3 paragraphs, full context, ends with hook\n"
        "- extra_long: 200-300 words, complete Facebook article with background, context, why it matters, strong closing hook\n"
        "- first_comment: 25-45 words — add one specific detail or context from the story not in the caption, "
        "then end with a direct question to the reader\n\n"
        'Return JSON: {"short":"...","medium":"...","long":"...","extra_long":"...","first_comment":"..."}'
    )

    try:
        import anthropic as _ant, re as _re
        client = _ant.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=2500,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "").strip()
        m   = _re.search(r'\{.*\}', raw, _re.S)
        if not m:
            return JSONResponse({"error": f"No JSON in response: {raw[:200]}"}, status_code=500)
        data = json.loads(m.group())

        # Persist to queue
        if not item.get("draft"):
            item["draft"] = {}
        item["draft"].setdefault("captions", {}).update({
            "short":      data.get("short", ""),
            "medium":     data.get("medium", ""),
            "long":       data.get("long", ""),
            "extra_long": data.get("extra_long", ""),
        })
        if data.get("first_comment"):
            item["draft"]["first_comment"] = data["first_comment"]
        _update_cluster_fsn(cluster_id, draft=item["draft"])
        _save_fsn_queue(items)

        return JSONResponse({"ok": True, "captions": item["draft"]["captions"],
                             "first_comment": item["draft"].get("first_comment", ""),
                             "voice": voice})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/pipeline-queue/story/{cid}/regenerate-image")
async def pipeline_queue_story_regenerate_image(cid: str, request: Request,
                                                background_tasks: BackgroundTasks,
                                                user: dict = Depends(require_user)):
    """Queue a new Kie.ai image generation for this story, overwriting the previous."""
    if not cid.isdigit():
        return JSONResponse({"error": "invalid id"}, status_code=400)
    cluster_id = int(cid)
    try:
        form = await request.form()
        headline   = str(form.get("headline", "")).strip()
        tag        = str(form.get("tag", "")).strip()
        scene      = str(form.get("scene", "")).strip()
        notes      = str(form.get("notes", "")).strip()
        brand_slug = str(form.get("brand_slug", "")).strip() or None

        items, item = _resolve_queue_item(cluster_id)
        if not item:
            return JSONResponse({"error": "Story not found in queue"}, status_code=404)

        # Update draft with submitted fields before re-generating
        if not item.get("draft"):
            item["draft"] = {}
        if headline:
            item["draft"]["headline"] = headline
        if tag:
            item["draft"]["tag"] = tag
        # Use submitted scene, or fall back to whatever is already in draft/suggested
        effective_scene = scene or (item.get("draft") or {}).get("scene") or item.get("suggested_scene") or ""
        item["draft"]["scene"] = effective_scene
        item["scene"] = effective_scene
        if notes:
            item["draft"]["image_notes"] = notes
        if brand_slug:
            item["brand_slug"] = brand_slug

        # Clear old image so status shows "generating"
        _update_cluster_fsn(cluster_id, generated_image_url="", image_gen_status="generating",
                            kie_result_url="", draft=item["draft"],
                            brand_slug=item.get("brand_slug"))
        item["generated_image_url"] = ""
        item["image_gen_status"]    = "generating"
        item["kie_result_url"]      = ""
        _save_fsn_queue(items)

        key = _get_kie_key()
        if not key:
            return JSONResponse({"error": "KIE_AI_API_KEY not set on server"}, status_code=400)

        background_tasks.add_task(_generate_one_image, str(cluster_id), key, item, notes)
        return JSONResponse({"ok": True})
    except Exception as exc:
        logger.error("regenerate-image %s: %s", cid, exc)
        return JSONResponse({"error": f"Server error: {exc}"}, status_code=500)


@app.get("/pipeline-queue/story/{cid}/image-status")
def pipeline_queue_story_image_status(cid: str, user: dict = Depends(require_user)):
    """Lightweight poll endpoint for workspace image generation status."""
    if not cid.isdigit():
        return JSONResponse({"error": "invalid id"}, status_code=400)
    cluster_id = int(cid)
    item = _queue_item_for(cluster_id)
    if not item:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({
        "status":  item.get("image_gen_status") or "",
        "url":     item.get("generated_image_url") or "",
        "history": item.get("image_history") or [],
    })


@app.post("/pipeline-queue/story/{cid}/set-image")
async def pipeline_queue_story_set_image(cid: str, request: Request, user: dict = Depends(require_user)):
    """Swap a history image to be the current image (downloads and re-stamps logo)."""
    if not cid.isdigit():
        return JSONResponse({"error": "invalid id"}, status_code=400)
    cluster_id = int(cid)
    form = await request.form()
    kie_url = str(form.get("kie_url", "")).strip()
    if not kie_url:
        return JSONResponse({"error": "no url"}, status_code=400)
    try:
        r = httpx.get(kie_url, timeout=60, follow_redirects=True)
        r.raise_for_status()
        _stamp_logo(r.content, cid)
        # Swap history: push current kie_result_url into history, set new as current
        item = _queue_item_for(cluster_id)
        history = list(item.get("image_history") or []) if item else []
        old_kie = (item or {}).get("kie_result_url") or ""
        if old_kie and old_kie != kie_url and old_kie not in history:
            history.append(old_kie)
        if kie_url in history:
            history.remove(kie_url)
        served_url = f"/pipeline-queue/image/{cid}"
        _update_cluster_fsn(cluster_id, generated_image_url=served_url,
                            kie_result_url=kie_url, image_history=history)
        return JSONResponse({"ok": True, "url": served_url, "history": history})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/pipeline-queue/story/{cid}/complete")
def pipeline_queue_story_complete(cid: str, user: dict = Depends(require_user)):
    """Mark a story as completed (posted). Moves it to Recent History on the queue page."""
    if not cid.isdigit():
        return RedirectResponse("/pipeline-queue", status_code=303)
    cluster_id = int(cid)
    items, item = _resolve_queue_item(cluster_id)
    if item:
        item["queue_status"] = "completed"
        item["completed_at"] = datetime.now(timezone.utc).isoformat()
        _update_cluster_fsn(cluster_id, queue_status="completed", completed_at=item["completed_at"])
        _save_fsn_queue(items)
    return RedirectResponse("/pipeline-queue?msg=Marked+as+done", status_code=303)


@app.post("/pipeline-queue/story/{cid}/approve")
def pipeline_queue_story_approve(cid: str, user: dict = Depends(require_user)):
    """Legacy batch-approve: marks approved for Run Full Batch flow."""
    if not cid.isdigit():
        return RedirectResponse(f"/pipeline-queue/story/{cid}", status_code=303)
    cluster_id = int(cid)
    items, item = _resolve_queue_item(cluster_id)
    if item:
        item["queue_status"] = "approved"
        item["approved_at"] = datetime.now(timezone.utc).isoformat()
        _update_cluster_fsn(cluster_id, queue_status="approved", approved_at=item["approved_at"])
        _save_fsn_queue(items)
    _build_picks_from_approved_queue()
    return RedirectResponse(f"/pipeline-queue/story/{cid}?msg=Approved", status_code=303)


@app.post("/pipeline-queue/story/{cid}/skip")
def pipeline_queue_story_skip(cid: str, user: dict = Depends(require_user)):
    if not cid.isdigit():
        return RedirectResponse("/pipeline-queue", status_code=303)
    cluster_id = int(cid)
    items, item = _resolve_queue_item(cluster_id)
    if item:
        item["queue_status"] = "skipped"
        _update_cluster_fsn(cluster_id, queue_status="skipped")
        _save_fsn_queue(items)
    return RedirectResponse("/pipeline-queue?msg=Story+skipped", status_code=303)


@app.post("/pipeline-queue/story/{cid}/remove")
def pipeline_queue_story_remove(cid: str, user: dict = Depends(require_user)):
    if not cid.isdigit():
        return RedirectResponse("/pipeline-queue", status_code=303)
    cluster_id = int(cid)
    items = [x for x in _load_fsn_queue() if x.get("cluster_id") != cluster_id]
    _save_fsn_queue(items)
    _update_cluster_fsn(cluster_id, queue_status="removed")
    return RedirectResponse("/pipeline-queue?msg=Story+removed", status_code=303)


@app.get("/pipeline-queue/image/{cid}")
def pipeline_queue_serve_image(cid: str, user: dict = Depends(require_user)):
    """Serve a logo-stamped JPEG generated for a cluster. Re-stamps from Kie CDN if /tmp was cleared."""
    # Sanitise: cid must be numeric
    if not cid.isdigit():
        return Response(status_code=400)
    # Support both .jpg (new) and .png (legacy) in /tmp
    tmp_path_jpg = Path("/tmp/fsn_images") / f"{cid}.jpg"
    tmp_path_png = Path("/tmp/fsn_images") / f"{cid}.png"
    if tmp_path_jpg.exists():
        return Response(content=tmp_path_jpg.read_bytes(), media_type="image/jpeg")
    if tmp_path_png.exists():
        return Response(content=tmp_path_png.read_bytes(), media_type="image/png")

    # /tmp was cleared (redeploy) — re-download from Kie CDN and re-stamp
    session = SessionLocal()
    try:
        c = session.get(StoryCluster, int(cid))
        if not c or not c.fsn_state:
            return Response(status_code=404)
        fsn = json.loads(c.fsn_state)
        kie_url = fsn.get("kie_result_url")
        if not kie_url:
            return Response(status_code=404)
    finally:
        session.close()

    r = httpx.get(kie_url, timeout=60, follow_redirects=True)
    r.raise_for_status()
    _stamp_logo(r.content, cid)
    tmp_path_jpg = Path("/tmp/fsn_images") / f"{cid}.jpg"
    return Response(content=tmp_path_jpg.read_bytes(), media_type="image/jpeg")


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


# ── Brand / Settings routes ───────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
def settings_index(msg: str = "", user: dict = Depends(require_user)):
    from app.render import render_settings_index_page
    brands = _get_all_brands()
    return HTMLResponse(render_settings_index_page(brands, msg=msg))


@app.get("/settings/brands/new", response_class=HTMLResponse)
def settings_brand_new(user: dict = Depends(require_user)):
    from app.render import render_settings_brand_edit_page
    return HTMLResponse(render_settings_brand_edit_page(brand=None))


@app.post("/settings/brands/new")
async def settings_brand_create(request: Request, user: dict = Depends(require_user)):
    from app.models import BrandProperty as _BP
    form = await request.form()
    slug = str(form.get("slug", "")).strip().lower().replace(" ", "_")
    if not slug:
        return RedirectResponse("/settings?msg=Slug+required", status_code=303)
    session = SessionLocal()
    try:
        existing = session.execute(select(_BP).where(_BP.slug == slug)).scalar_one_or_none()
        if existing:
            return RedirectResponse(f"/settings?msg=Slug+{slug}+already+exists", status_code=303)
        b = _BP(
            slug=slug,
            name=str(form.get("name", slug)).strip(),
            enabled=form.get("enabled") == "on",
            sort_order=int(form.get("sort_order") or 0),
            colors=str(form.get("colors", "{}")),
            image_settings=str(form.get("image_settings", "{}")),
            voice_instructions=str(form.get("voice_instructions", "")),
            caption_settings=str(form.get("caption_settings", "{}")),
            logo_url=str(form.get("logo_url", "")),
            notes=str(form.get("notes", "")),
        )
        session.add(b)
        session.commit()
        return RedirectResponse(f"/settings?msg=Brand+{slug}+created", status_code=303)
    finally:
        session.close()


@app.get("/settings/brands/{slug}", response_class=HTMLResponse)
def settings_brand_edit(slug: str, msg: str = "", user: dict = Depends(require_user)):
    from app.render import render_settings_brand_edit_page
    brand = _get_brand(slug)
    if not brand:
        return RedirectResponse("/settings?msg=Brand+not+found", status_code=303)
    return HTMLResponse(render_settings_brand_edit_page(brand=brand, msg=msg))


@app.post("/settings/brands/{slug}")
async def settings_brand_save(slug: str, request: Request, user: dict = Depends(require_user)):
    from app.models import BrandProperty as _BP
    form = await request.form()
    session = SessionLocal()
    try:
        b = session.execute(select(_BP).where(_BP.slug == slug)).scalar_one_or_none()
        if not b:
            return RedirectResponse("/settings?msg=Brand+not+found", status_code=303)
        b.name              = str(form.get("name", b.name)).strip()
        b.enabled           = form.get("enabled") == "on"
        b.sort_order        = int(form.get("sort_order") or b.sort_order)
        b.colors            = str(form.get("colors", b.colors or "{}"))
        b.image_settings    = str(form.get("image_settings", b.image_settings or "{}"))
        b.voice_instructions= str(form.get("voice_instructions", b.voice_instructions or ""))
        b.caption_settings  = str(form.get("caption_settings", b.caption_settings or "{}"))
        b.logo_url          = str(form.get("logo_url", b.logo_url or ""))
        b.notes             = str(form.get("notes", b.notes or ""))
        session.commit()
        return RedirectResponse(f"/settings/brands/{slug}?msg=Saved", status_code=303)
    finally:
        session.close()


@app.get("/api/brands")
def api_brands(user: dict = Depends(require_user)):
    """Return enabled brands for the workspace dropdown."""
    brands = [b for b in _get_all_brands() if b["enabled"]]
    return JSONResponse({"brands": [{"slug": b["slug"], "name": b["name"]} for b in brands]})
